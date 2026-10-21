"""Tests for the CI gate (S8): what the workflows in .github/workflows/ rely on.

    python tests/test_ci.py

The workflows themselves only run on GitHub. These tests run what they run -- ``python main.py --strict``,
twice, then ``git status --porcelain`` -- against a temporary site repository made from the fixtures, and
check that the workflow files still say it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WORKFLOWS = REPO / ".github" / "workflows"

HAVE_GIT = shutil.which("git") is not None


class SiteRepo(unittest.TestCase):
    """A temporary site repository: data/raw from the fixtures; the package is this repository's main.py."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name) / "site"
        shutil.copytree(HERE / "fixtures" / "entities", self.site / "data" / "raw" / "entities")
        shutil.copy(REPO / ".gitattributes", self.site / ".gitattributes")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def pipeline(self, *args: str, hash_seed: str = "0") -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "WBS_ROOT"}
        env.update(WBS_ROOT=str(self.site), PYTHONIOENCODING="utf-8", PYTHONHASHSEED=hash_seed)
        return subprocess.run([sys.executable, str(REPO / "main.py"), *args], cwd=self.site, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=180)

    def git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "user.name=ci", "-c", "user.email=ci@example.org", *args],
            cwd=self.site, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout

    def commit_everything(self) -> None:
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "site")


class StrictGate(SiteRepo):
    def test_a_clean_site_passes_strict(self) -> None:
        result = self.pipeline("--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 dead", result.stdout)
        self.assertNotIn("WARN", result.stdout)

    def test_a_dead_internal_link_fails_strict(self) -> None:
        # A page that somebody added to docs/ by hand: the linkcheck reads every HTML file there.
        (self.site / "docs").mkdir()
        (self.site / "docs" / "impressum.html").write_text(
            '<!doctype html><title>Imprint</title><a href="datenschutz.html">Privacy</a>\n', encoding="utf-8")
        result = self.pipeline("--strict")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("WARN: [build] dead internal link impressum.html -> datenschutz.html", result.stdout)
        self.assertIn("--strict: 1 warning(s) treated as errors", result.stdout)

    def test_without_strict_the_same_link_is_only_a_warning(self) -> None:
        (self.site / "docs").mkdir()
        (self.site / "docs" / "impressum.html").write_text('<a href="datenschutz.html">Privacy</a>\n', encoding="utf-8")
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 dead", result.stdout)

    def test_the_dead_link_is_gone_once_the_target_exists(self) -> None:
        (self.site / "docs").mkdir()
        (self.site / "docs" / "impressum.html").write_text('<a href="datenschutz.html">Privacy</a>\n', encoding="utf-8")
        (self.site / "docs" / "datenschutz.html").write_text("<title>Privacy</title>\n", encoding="utf-8")
        result = self.pipeline("--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TreeIsClean(SiteRepo):
    def status(self) -> str:
        return self.git("status", "--porcelain")

    def test_after_committing_a_build_further_runs_leave_the_tree_clean(self) -> None:
        self.assertEqual(self.pipeline("--strict", hash_seed="1").returncode, 0)
        self.commit_everything()
        # Different hash seeds: a result that is only stable by luck of one seed shows up here.
        for seed in ("2", "3"):
            result = self.pipeline("--strict", hash_seed=seed)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.status(), "", f"tree not clean after a run with PYTHONHASHSEED={seed}")

    def test_a_committed_site_that_is_out_of_date_is_detected(self) -> None:
        self.assertEqual(self.pipeline("--strict").returncode, 0)
        page = self.site / "docs" / "Q2.html"
        page.write_text(page.read_text(encoding="utf-8") + "<!-- edited by hand -->\n", encoding="utf-8", newline="\n")
        self.commit_everything()
        self.assertEqual(self.pipeline("--strict").returncode, 0)   # the build itself is fine ...
        self.assertIn("docs/Q2.html", self.status())                # ... but the checked-in page differs from it

    def test_a_page_missing_from_the_commit_is_detected(self) -> None:
        self.assertEqual(self.pipeline("--strict").returncode, 0)
        (self.site / "docs" / "Q2.html").unlink()
        self.commit_everything()
        self.assertEqual(self.pipeline("--strict").returncode, 0)
        self.assertIn("?? docs/Q2.html", self.status())


class WorkflowFiles(unittest.TestCase):
    """The workflow files are YAML, say what the PRIMER promises, and pin their actions to a major tag."""

    @staticmethod
    def load(name: str) -> dict:
        data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        # YAML 1.1 reads the key `on` as the boolean True.
        if True in data and "on" not in data:
            data["on"] = data.pop(True)
        return data

    @staticmethod
    def run_lines(job: dict) -> list[str]:
        return [step["run"] for step in job["steps"] if "run" in step]

    def uses(self, workflow: dict) -> list[str]:
        return [step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step]

    def test_ci_runs_the_tests_and_the_pipeline_twice(self) -> None:
        ci = self.load("ci.yml")
        self.assertTrue(any("unittest discover" in line for line in self.run_lines(ci["jobs"]["test"])))
        pipeline = self.run_lines(ci["jobs"]["pipeline"])
        self.assertEqual(sum("python main.py --strict" in line for line in pipeline), 2)
        self.assertEqual(sum("git status --porcelain" in line for line in pipeline), 2)

    def test_ci_covers_the_reference_platform_and_the_oldest_python(self) -> None:
        include = self.load("ci.yml")["jobs"]["test"]["strategy"]["matrix"]["include"]
        self.assertIn("windows-latest", {entry["os"] for entry in include})
        self.assertIn("3.10", {entry["python"] for entry in include})

    def test_site_is_reusable_with_strict_as_the_default_command(self) -> None:
        site = self.load("site.yml")
        call = site["on"]["workflow_call"]
        self.assertEqual(call["inputs"]["command"]["default"], "python main.py --strict")
        self.assertIs(call["inputs"]["deploy"]["default"], True)

    def test_site_checks_twice_before_it_deploys(self) -> None:
        site = self.load("site.yml")
        check = self.run_lines(site["jobs"]["check"])
        self.assertEqual(sum('bash -c "$COMMAND"' in line for line in check), 2)
        self.assertEqual(sum("git status --porcelain" in line for line in check), 2)
        deploy = site["jobs"]["deploy"]
        self.assertEqual(deploy["needs"], "check")
        self.assertEqual(deploy["permissions"]["pages"], "write")
        self.assertEqual(deploy["permissions"]["id-token"], "write")
        self.assertIn("default_branch", deploy["if"])
        self.assertIn("pull_request", deploy["if"])

    def test_site_never_interpolates_inputs_into_a_shell_line(self) -> None:
        for line in self.run_lines(self.load("site.yml")["jobs"]["check"]):
            self.assertNotIn("${{", line)

    def test_every_action_is_pinned_to_a_major_tag(self) -> None:
        for name in ("ci.yml", "site.yml"):
            for ref in self.uses(self.load(name)):
                self.assertRegex(ref, r"^actions/[a-z-]+@v\d+$", f"{name}: {ref}")

    def test_the_example_caller_points_at_the_reusable_workflow(self) -> None:
        caller = yaml.safe_load((REPO / "examples" / "site-caller.yml").read_text(encoding="utf-8"))
        ref = caller["jobs"]["site"]["uses"]
        match = re.fullmatch(r"n4o-rse/wikibase-static/(\.github/workflows/[a-z.-]+\.yml)@\w+", ref)
        self.assertIsNotNone(match, ref)
        self.assertTrue((REPO / match.group(1)).is_file())
        permissions = caller["jobs"]["site"]["permissions"]
        self.assertEqual((permissions["pages"], permissions["id-token"]), ("write", "write"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
