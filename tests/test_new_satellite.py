"""Tests for tools/new_satellite.py: the skeleton of a satellite site made from the template (0.28.1).

    python tests/test_new_satellite.py

Standard library only. The skeleton is written to a temporary folder; nothing here uses the network.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))

import new_satellite  # noqa: E402

QUERY = "SELECT DISTINCT ?item ?kind WHERE { ?item wdt:P31 wd:Q1335799 . BIND(\"tower\" AS ?kind) }\n"


class Skeleton(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        (self.base / "wikidata-towers.rq").write_text(QUERY, encoding="utf-8")
        (self.base / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.out = self.base / "wd-towers-static"

    def make(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = new_satellite.main(["wd-towers-static", "--title", "Towers", "--description", "A set of towers.", "--prefix", "twr",
                                       "--query", str(self.base / "wikidata-towers.rq"), "--logo", str(self.base / "logo.png"),
                                       "--out", str(self.out), "--date", "2026-11-18", *extra])
        return code, out.getvalue()

    def read(self, name: str) -> str:
        return (self.out / name).read_text(encoding="utf-8")

    def test_the_files_are_there_and_nothing_is_left_unfilled(self) -> None:
        code, text = self.make()
        self.assertEqual(code, 0, text)
        for name in ("main.py", "site.yaml", "requirements.txt", "README.md", "PRIMER.md", "CITATION.cff", "update.cmd", ".gitignore",
                     ".github/workflows/site.yml", ".github/workflows/update.yml", "data/seeds/wikidata-towers.rq", "assets/logo.png",
                     "data/csv/entities.csv", "data/csv/idmap.csv"):
            self.assertTrue((self.out / name).is_file(), name)
        for path in self.out.rglob("*"):
            if path.is_file() and path.suffix != ".png":
                self.assertNotIn("{{", path.read_text(encoding="utf-8"), str(path))

    def test_the_settings_follow_the_size(self) -> None:
        self.make()
        site = self.read("site.yaml")
        self.assertIn("rdf_prefix: twr", site)
        self.assertIn("entity_files: false", site)
        self.assertIn("browser_graph: slim", site)
        self.assertIn("pages_url: https://n4o-rse.github.io/wd-towers-static/", site)
        self.assertIn("data_as_of: 2026-11-18", site)
        self.assertIn(f"@v{new_satellite.package_version()}", self.read("requirements.txt"))
        self.assertIn("deploy: true", self.read(".github/workflows/site.yml"))

    def test_small_keeps_the_files_per_item(self) -> None:
        self.make("--small")
        site = self.read("site.yaml")
        self.assertIn("entity_files: true", site)
        self.assertIn("browser_graph: full", site)

    def test_the_wrapper_starts_the_import_generic_and_with_item_provenance(self) -> None:
        self.make()
        main = self.read("main.py")
        self.assertIn('"--generic"', main)
        self.assertIn('"--provenance", "item"', main)
        compile(main, "main.py", "exec")

    def test_a_bad_prefix_or_a_site_without_seeds_is_refused(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                new_satellite.main(["wd-x-static", "--title", "t", "--description", "d", "--prefix", "wd", "--qids", "Q1", "--out", str(self.out)])
            with self.assertRaises(SystemExit):
                new_satellite.main(["wd-x-static", "--title", "t", "--description", "d", "--prefix", "xx", "--out", str(self.out)])

    def test_single_seeds_are_added_to_the_list(self) -> None:
        self.make("--qids", "Q42,Q7")
        listing = self.read("data/seeds/wikidata-qids.txt")
        self.assertIn("\nQ42\n", listing)
        self.assertIn("\nQ7\n", listing)

    def test_an_empty_skeleton_builds(self) -> None:
        self.make()
        run = subprocess.run([sys.executable, "main.py", "--strict"], cwd=self.out, capture_output=True, text=True,
                             env=dict(os.environ, PYTHONPATH=str(ROOT / "py")), timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
