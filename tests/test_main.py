"""Tests for the orchestrator's report rule (``main.py``).

    python tests/test_main.py

``python main.py`` writes ``dist/pipeline_report.txt`` only when the data it processed is this repository's
own. With ``WBS_ROOT`` pointing to a site repository the report is left alone: it would describe that
site and be committed here by mistake (this happened twice, PRIMER.md, A1 Befund 13).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


class ReportRule(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "package"                      # a copy, so a wrong write cannot touch the real repository
        self.repo.mkdir()
        shutil.copy(REPO / "main.py", self.repo / "main.py")
        shutil.copytree(REPO / "py", self.repo / "py", ignore=shutil.ignore_patterns("__pycache__"))
        self.site = base / "site"
        shutil.copytree(HERE / "fixtures" / "entities", self.site / "data" / "raw" / "entities")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_main(self, wbs_root: Path | None, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "WBS_ROOT"}
        env["PYTHONIOENCODING"] = "utf-8"
        if wbs_root is not None:
            env["WBS_ROOT"] = str(wbs_root)
        return subprocess.run([sys.executable, "main.py", *args], cwd=self.repo, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=120)

    def report(self) -> Path:
        return self.repo / "dist" / "pipeline_report.txt"

    def test_a_run_on_the_repository_own_data_writes_the_report(self) -> None:
        result = self.run_main(None)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to do", self.report().read_text(encoding="utf-8"))
        self.assertNotIn("report not written", result.stdout)

    def test_a_run_on_a_site_repository_leaves_the_report_alone(self) -> None:
        self.report().parent.mkdir()
        self.report().write_text("kept\n", encoding="utf-8")
        result = self.run_main(self.site)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.report().read_text(encoding="utf-8"), "kept\n")
        self.assertIn("report not written: WBS_ROOT=", result.stdout)
        self.assertTrue((self.site / "docs" / "Q1.html").is_file())     # the steps still ran on the site's data

    def test_no_report_appears_where_there_was_none(self) -> None:
        self.run_main(self.site)
        self.assertFalse(self.report().exists())

    def test_wbs_root_naming_the_repository_itself_counts_as_its_own_data(self) -> None:
        result = self.run_main(self.repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.report().is_file())

    def test_a_partial_run_never_writes_the_report(self) -> None:
        self.run_main(None, "--only", "load")
        self.assertFalse(self.report().exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
