"""Tests for tools/check_status.py (the Status workflow): no network, a fake GitHub API stands in.

    python tests/test_status.py
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_status", REPO / "tools" / "check_status.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def run(name, conclusion, wid, when="2026-11-18T10:00:00Z", event="push", status="completed", path=None):
    return {"name": name, "conclusion": conclusion, "workflow_id": wid, "updated_at": when, "event": event, "status": status,
            "html_url": f"https://github.com/x/y/actions/runs/{wid}", "path": path or f".github/workflows/{name.lower()}.yml"}


class FakeApi:
    """GET answers from a dict (path prefix -> value or ApiError); every POST and PATCH is written down."""

    def __init__(self, repos: dict, issues: list | None = None) -> None:
        self.repos, self.issues, self.calls = repos, issues or [], []

    def get(self, path: str):
        if path.endswith("/issues?state=open&per_page=100"):
            return self.issues
        repo = path.split("/")[2] + "/" + path.split("/")[3]
        value = self.repos.get(repo)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise cs.ApiError(404, "Not Found")
        return {"default_branch": "main"} if path == f"/repos/{repo}" else {"workflow_runs": value}

    def post(self, path: str, body: dict):
        self.calls.append(("POST", path, body))
        return {"number": 7, **body}

    def patch(self, path: str, body: dict):
        self.calls.append(("PATCH", path, body))
        return {}


class Judging(unittest.TestCase):
    def test_what_counts(self) -> None:
        self.assertEqual(cs.judge(run("Site", "success", 1)), "green")
        for conclusion in ("failure", "timed_out", "startup_failure"):
            self.assertEqual(cs.judge(run("Site", conclusion, 1)), "red")
        for conclusion in ("cancelled", "skipped", "neutral", "action_required", "stale", None):
            self.assertIsNone(cs.judge(run("Site", conclusion, 1)))

    def test_pull_requests_and_running_runs_say_nothing(self) -> None:
        self.assertIsNone(cs.judge(run("Site", "failure", 1, event="pull_request")))
        self.assertIsNone(cs.judge(run("Site", None, 1, status="in_progress")))

    def test_the_newest_run_of_every_workflow_counts(self) -> None:
        runs = [run("Site", "success", 1), run("Site", "failure", 1), run("Update", "failure", 2), run("Update", "success", 2)]
        got = {r["workflow"]: r["state"] for r in cs.latest_per_workflow(runs, skip_own=False)}
        self.assertEqual(got, {"Site": "green", "Update": "red"})

    def test_a_cancelled_run_does_not_hide_the_one_before(self) -> None:
        runs = [run("Site", "cancelled", 1), run("Site", "failure", 1)]
        self.assertEqual(cs.latest_per_workflow(runs, skip_own=False)[0]["state"], "red")

    def test_an_unapproved_bot_run_is_no_problem(self) -> None:
        runs = [run("Site", "action_required", 1, event="pull_request"), run("Site", "success", 1)]
        self.assertEqual(cs.latest_per_workflow(runs, skip_own=False)[0]["state"], "green")

    def test_the_status_workflow_leaves_itself_out(self) -> None:
        runs = [run("Status", "failure", 3, path=".github/workflows/status.yml"), run("CI", "success", 4)]
        self.assertEqual([r["workflow"] for r in cs.latest_per_workflow(runs, skip_own=True)], ["CI"])
        self.assertEqual(len(cs.latest_per_workflow(runs, skip_own=False)), 2)


class Looking(unittest.TestCase):
    def test_states(self) -> None:
        api = FakeApi({"o/green": [run("Site", "success", 1)], "o/red": [run("Site", "failure", 1)], "o/new": [],
                       "o/gone": cs.ApiError(404, "Not Found")})
        got = {r: cs.look(api, r)["state"] for r in ("o/green", "o/red", "o/new", "o/gone", "o/absent")}
        self.assertEqual(got, {"o/green": "green", "o/red": "red", "o/new": "empty", "o/gone": "unreadable", "o/absent": "unreadable"})

    def test_problems_and_headline(self) -> None:
        api = FakeApi({"o/a": [run("Site", "failure", 1), run("Update", "success", 2)], "o/b": [run("Site", "success", 1)],
                       "o/c": cs.ApiError(403, "no")})
        results = [cs.look(api, r) for r in ("o/a", "o/b", "o/c")]
        self.assertEqual(cs.problems(results), ["o/a: Site", "o/c: unreadable"])
        self.assertIn("2 problem(s) in 3 repositories", cs.headline(results))
        self.assertIn("**RED**", cs.table(results))
        self.assertNotIn("o/b", cs.table(results, only_problems=True))


class Lists(unittest.TestCase):
    def test_comments_blank_lines_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.txt", Path(tmp) / "b.txt"
            a.write_text("# comment\no/one\n\no/two  # trailing\n", encoding="utf-8")
            b.write_text("o/two\no/three\n", encoding="utf-8")
            self.assertEqual(cs.read_lists([a, b, Path(tmp) / "missing.txt"]), ["o/one", "o/two", "o/three"])

    def test_the_real_lists_hold_every_satellite_and_the_registry(self) -> None:
        repos = cs.read_lists(cs.DEFAULT_LISTS)
        self.assertGreaterEqual(len(repos), 14)
        self.assertIn("beaverbridge-framework/beaverbridge-registry", repos)
        self.assertIn("n4o-rse/wikibase-static", repos)
        self.assertTrue(all(r.count("/") == 1 for r in repos))


class Issue(unittest.TestCase):
    red = [cs.look(FakeApi({"o/a": [run("Site", "failure", 1)]}), "o/a")]
    green = [cs.look(FakeApi({"o/a": [run("Site", "success", 1)]}), "o/a")]

    def test_red_opens_the_issue(self) -> None:
        api = FakeApi({})
        self.assertEqual(cs.sync_alert(api, "o/tool", self.red), "opened the issue")
        method, path, body = api.calls[0]
        self.assertEqual((method, path, body["title"]), ("POST", "/repos/o/tool/issues", cs.ALERT_TITLE))
        self.assertIn("o/a", body["body"])

    def test_the_same_red_changes_nothing(self) -> None:
        first = FakeApi({})
        cs.sync_alert(first, "o/tool", self.red)
        body = first.calls[0][2]["body"]
        api = FakeApi({}, issues=[{"number": 3, "title": cs.ALERT_TITLE, "body": body}])
        self.assertEqual(cs.sync_alert(api, "o/tool", self.red), "the issue is up to date")
        self.assertEqual(api.calls, [])

    def test_a_changed_red_updates_and_comments(self) -> None:
        api = FakeApi({}, issues=[{"number": 3, "title": cs.ALERT_TITLE, "body": "old"}])
        self.assertEqual(cs.sync_alert(api, "o/tool", self.red), "updated the issue")
        self.assertEqual([c[0] for c in api.calls], ["PATCH", "POST"])

    def test_green_closes_an_open_issue(self) -> None:
        api = FakeApi({}, issues=[{"number": 3, "title": cs.ALERT_TITLE, "body": "x"}])
        self.assertEqual(cs.sync_alert(api, "o/tool", self.green), "closed the issue")
        self.assertEqual(api.calls[-1][2]["state"], "closed")

    def test_green_without_an_issue_does_nothing_and_pull_requests_are_no_issues(self) -> None:
        api = FakeApi({}, issues=[{"number": 5, "title": cs.ALERT_TITLE, "pull_request": {}}])
        self.assertEqual(cs.sync_alert(api, "o/tool", self.green), "nothing to report")
        self.assertEqual(api.calls, [])

    def test_the_weekly_report_makes_its_issue_once_and_comments(self) -> None:
        api = FakeApi({})
        cs.post_digest(api, "o/tool", self.green, "2026-11-23")
        self.assertEqual([c[1] for c in api.calls], ["/repos/o/tool/issues", "/repos/o/tool/issues/7/comments"])
        api = FakeApi({}, issues=[{"number": 9, "title": cs.WEEKLY_TITLE}])
        cs.post_digest(api, "o/tool", self.green, "2026-11-23")
        self.assertEqual([c[1] for c in api.calls], ["/repos/o/tool/issues/9/comments"])
        self.assertIn("2026-11-23", api.calls[0][2]["body"])


class Main(unittest.TestCase):
    def lists(self, tmp: str) -> Path:
        path = Path(tmp) / "r.txt"
        path.write_text("o/a\no/b\n", encoding="utf-8")
        return path

    def test_exit_code_follows_the_colour(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            green = FakeApi({"o/a": [run("Site", "success", 1)], "o/b": [run("Site", "success", 1)]})
            red = FakeApi({"o/a": [run("Site", "success", 1)], "o/b": [run("Site", "failure", 1)]})
            self.assertEqual(cs.main(["--repos", str(self.lists(tmp))], api=green), 0)
            self.assertEqual(cs.main(["--repos", str(self.lists(tmp))], api=red), 1)

    def test_summary_and_report_files_and_the_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = FakeApi({"o/a": [run("Site", "failure", 1)], "o/b": [run("Site", "success", 1)]})
            summary, report = Path(tmp) / "s.md", Path(tmp) / "r.md"
            code = cs.main(["--repos", str(self.lists(tmp)), "--summary", str(summary), "--report", str(report), "--issue", "o/tool",
                            "--digest"], api=api)
            self.assertEqual(code, 1)
            self.assertIn("## Satellite status", summary.read_text(encoding="utf-8"))
            self.assertIn("o/a", report.read_text(encoding="utf-8"))
            self.assertEqual([c[0] for c in api.calls], ["POST", "POST", "POST"])    # alert issue, weekly issue, weekly comment

    def test_an_issue_that_cannot_be_written_is_reported_and_red(self) -> None:
        class Locked(FakeApi):
            def post(self, path, body):
                raise cs.ApiError(403, "no write")
        with tempfile.TemporaryDirectory() as tmp:
            api = Locked({"o/a": [run("Site", "failure", 1)], "o/b": [run("Site", "success", 1)]})
            self.assertEqual(cs.main(["--repos", str(self.lists(tmp)), "--issue", "o/tool"], api=api), 1)


class Workflow(unittest.TestCase):
    def setUp(self) -> None:
        text = (REPO / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.text = text
        self.data = yaml.safe_load(text)
        self.on = self.data.get("on", self.data.get(True))

    def test_it_runs_daily_and_on_mondays_and_by_hand(self) -> None:
        crons = [s["cron"] for s in self.on["schedule"]]
        self.assertEqual(len(crons), 2)
        self.assertTrue(any(c.endswith("* * 1") for c in crons))
        self.assertIn("workflow_dispatch", self.on)

    def test_it_may_write_issues_and_read_actions_and_nothing_else(self) -> None:
        self.assertEqual(self.data["permissions"], {"contents": "read", "actions": "read", "issues": "write"})

    def test_it_calls_the_tool_and_the_weekly_cron_matches_the_script_test(self) -> None:
        self.assertIn("tools/check_status.py --issue", self.text)
        self.assertIn('"11 6 * * 1"', self.text)                      # the weekly schedule that the digest step compares with
        self.assertTrue((REPO / "tools" / "check_status.py").is_file())
        self.assertIn("MAIL_SERVER", self.text)


if __name__ == "__main__":
    unittest.main()
