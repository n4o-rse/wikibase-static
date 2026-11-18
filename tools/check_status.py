#!/usr/bin/env python3
"""Look at the latest GitHub Actions runs of the satellite repositories and report what is red.

    python tools/check_status.py                         table on the screen; exit 1 when a workflow is red or a repository unreadable
    python tools/check_status.py --issue OWNER/REPO      keep the issue "Satellite status" of that repository in line with it:
                                                         opened (and updated) while something is red, closed when all is green
    python tools/check_status.py --digest --issue ...    also add the table as a comment to the issue "Satellite weekly report"
    python tools/check_status.py --summary FILE          append the table to FILE (the job summary: $GITHUB_STEP_SUMMARY)
    python tools/check_status.py --report FILE           write the table to FILE (for a mail)
    python tools/check_status.py --repos A.txt B.txt     other lists (default: tools/satellites.txt and tools/status-extra.txt)

The repositories are the lines of the lists (``owner/repo``, ``#`` starts a comment). For every repository the latest run of every
workflow on the default branch counts: ``success`` is green; ``failure``, ``timed_out`` and ``startup_failure`` are red. Cancelled,
skipped and neutral runs, a run that waits for approval (``action_required``) and runs of pull requests are ignored, so a bot pull
request whose check was never approved is not a problem of the repository. A run that is still going is shown as running and does not
count either way. The workflow "Status" of the repository that runs this tool is left out, or yesterday's red would keep today's red.

The token is ``GITHUB_TOKEN`` or ``GH_TOKEN``; without one the tool asks ``gh auth token``, and without that it goes anonymous (public
repositories only, 60 requests an hour; this tool needs about two per repository). The issue needs a token that may write issues:
the workflow ``.github/workflows/status.yml`` gives its own ``github.token`` that right. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
DEFAULT_LISTS = [HERE / "satellites.txt", HERE / "status-extra.txt"]
ALERT_TITLE = "Satellite status"
WEEKLY_TITLE = "Satellite weekly report"
MARKER = "<!-- satellite-status -->"
RED = {"failure", "timed_out", "startup_failure"}
GREEN = {"success"}
OWN_WORKFLOW = "status.yml"            # the workflow of this tool, left out in the repository that runs it


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class Api:
    """The few GitHub REST calls the tool needs; the tests put a fake with the same three methods in its place."""

    def __init__(self, token: str | None) -> None:
        self.token = token

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{API}{path}", data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "wikibase-static-check-status")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            raise ApiError(err.code, err.read().decode("utf-8", "replace")[:300]) from None
        except urllib.error.URLError as err:
            raise ApiError(0, str(err.reason)) from None
        return json.loads(text) if text else None

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, body: dict):
        return self.request("POST", path, body)

    def patch(self, path: str, body: dict):
        return self.request("PATCH", path, body)


def find_token() -> str | None:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        done = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def read_lists(paths: list[Path]) -> list[str]:
    """The repositories of the lists in order, each once."""
    repos: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and line not in repos:
                repos.append(line)
    return repos


def judge(run: dict) -> str | None:
    """``green``, ``red`` or ``None`` (the run says nothing: cancelled, skipped, waiting for approval, a pull request)."""
    if run.get("event") == "pull_request" or run.get("status") != "completed":
        return None
    conclusion = run.get("conclusion")
    if conclusion in GREEN:
        return "green"
    if conclusion in RED:
        return "red"
    return None


def latest_per_workflow(runs: list[dict], skip_own: bool) -> list[dict]:
    """The newest run that says something, for every workflow; ``runs`` come newest first as GitHub sends them."""
    seen: dict[object, dict] = {}
    for run in runs:
        if skip_own and str(run.get("path", "")).split("@", 1)[0].endswith(OWN_WORKFLOW):
            continue
        state = judge(run)
        key = run.get("workflow_id") or run.get("name")
        if state and key not in seen:
            seen[key] = {"workflow": run.get("name") or str(key), "state": state, "url": run.get("html_url", ""),
                         "when": str(run.get("updated_at") or run.get("created_at") or "")[:10], "event": run.get("event", "")}
    return sorted(seen.values(), key=lambda r: r["workflow"].lower())


def look(api, repo: str, own_repo: str = "") -> dict:
    """``{"repo", "state", "workflows", "error"}``; state is green, red, unreadable or empty (no run yet)."""
    try:
        info = api.get(f"/repos/{repo}")
        branch = info.get("default_branch", "main")
        data = api.get(f"/repos/{repo}/actions/runs?branch={branch}&status=completed&per_page=100&exclude_pull_requests=true")
    except ApiError as err:
        return {"repo": repo, "state": "unreadable", "workflows": [], "error": str(err)}
    workflows = latest_per_workflow(data.get("workflow_runs", []), skip_own=(repo == own_repo))
    if not workflows:
        return {"repo": repo, "state": "empty", "workflows": [], "error": ""}
    state = "red" if any(w["state"] == "red" for w in workflows) else "green"
    return {"repo": repo, "state": state, "workflows": workflows, "error": ""}


def problems(results: list[dict]) -> list[str]:
    """One key per thing that is wrong: ``repo: workflow`` for a red workflow, ``repo: unreadable`` for a repository that could not be read."""
    keys = []
    for item in results:
        if item["state"] == "unreadable":
            keys.append(f"{item['repo']}: unreadable")
        for workflow in item["workflows"]:
            if workflow["state"] == "red":
                keys.append(f"{item['repo']}: {workflow['workflow']}")
    return sorted(keys)


ICON = {"green": "green", "red": "RED", "unreadable": "unreadable", "empty": "no runs yet"}


def table(results: list[dict], only_problems: bool = False) -> str:
    rows = ["| Repository | State | Workflow runs |", "|---|---|---|"]
    for item in results:
        if only_problems and item["state"] in ("green", "empty"):
            continue
        if item["workflows"]:
            parts = []
            for workflow in item["workflows"]:
                label = f"{workflow['workflow']} ({workflow['when']})"
                label = f"[{label}]({workflow['url']})" if workflow["url"] else label
                parts.append(f"**RED** {label}" if workflow["state"] == "red" else label)
            detail = "; ".join(parts)
        else:
            detail = item["error"] or ""
        rows.append(f"| [{item['repo']}](https://github.com/{item['repo']}/actions) | {ICON[item['state']]} | {detail} |")
    return "\n".join(rows)


def headline(results: list[dict]) -> str:
    keys = problems(results)
    greens = sum(1 for r in results if r["state"] == "green")
    if not keys:
        return f"All green: {greens} of {len(results)} repositories have no red workflow."
    return f"{len(keys)} problem(s) in {len(results)} repositories: " + ", ".join(keys)


def find_issue(api, repo: str, title: str) -> dict | None:
    for issue in api.get(f"/repos/{repo}/issues?state=open&per_page=100") or []:
        if "pull_request" not in issue and issue.get("title") == title:
            return issue
    return None


def sync_alert(api, repo: str, results: list[dict]) -> str:
    """Keep the issue "Satellite status" in line with the results; returns what was done."""
    keys = problems(results)
    issue = find_issue(api, repo, ALERT_TITLE)
    body = f"{MARKER}\n{headline(results)}\n\n{table(results, only_problems=True)}\n\nThe list is made by `tools/check_status.py` " \
           "(workflow Status of this repository); this issue closes itself when everything is green again."
    if keys and issue is None:
        api.post(f"/repos/{repo}/issues", {"title": ALERT_TITLE, "body": body})
        return "opened the issue"
    if keys:
        before = issue.get("body") or ""
        old = {line for line in before.splitlines() if line.startswith("| [")}
        new = {line for line in body.splitlines() if line.startswith("| [")}
        if old == new:
            return "the issue is up to date"
        api.patch(f"/repos/{repo}/issues/{issue['number']}", {"body": body})
        api.post(f"/repos/{repo}/issues/{issue['number']}/comments", {"body": f"Changed.\n\n{headline(results)}"})
        return "updated the issue"
    if issue is not None:
        api.post(f"/repos/{repo}/issues/{issue['number']}/comments", {"body": "All green again. Closing."})
        api.patch(f"/repos/{repo}/issues/{issue['number']}", {"state": "closed", "state_reason": "completed"})
        return "closed the issue"
    return "nothing to report"


def post_digest(api, repo: str, results: list[dict], today: str) -> None:
    """One long-lived issue; every week adds a comment, which is the mail GitHub sends to those who watch the repository."""
    issue = find_issue(api, repo, WEEKLY_TITLE)
    if issue is None:
        issue = api.post(f"/repos/{repo}/issues", {"title": WEEKLY_TITLE, "body": "Every Monday a comment with the state of the Actions of "
                         "all satellite repositories (`tools/check_status.py --digest`). Subscribe to this issue for the weekly mail."})
    api.post(f"/repos/{repo}/issues/{issue['number']}/comments", {"body": f"### {today}\n\n{headline(results)}\n\n{table(results)}"})


def main(argv: list[str] | None = None, api=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repos", nargs="*", type=Path, default=DEFAULT_LISTS)
    parser.add_argument("--issue", metavar="OWNER/REPO")
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    repos = read_lists(args.repos)
    if not repos:
        print("no repositories in the lists")
        return 1
    api = api or Api(find_token())
    own = os.environ.get("GITHUB_REPOSITORY", "")
    results = [look(api, repo, own) for repo in repos]
    text = f"{headline(results)}\n\n{table(results)}\n"
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(f"## Satellite status\n\n{text}\n")
    if args.report:
        args.report.write_text(f"{text}\n", encoding="utf-8")
    if args.issue:
        try:
            print(sync_alert(api, args.issue, results))
            if args.digest:
                post_digest(api, args.issue, results, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        except ApiError as err:
            print(f"the issue could not be kept up to date: {err}")
            return 1
    return 1 if problems(results) else 0


if __name__ == "__main__":
    sys.exit(main())
