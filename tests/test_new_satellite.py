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

try:
    from test_harvest import FakeWikibase, make_server
except ImportError:  # run from another folder
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_harvest import FakeWikibase, make_server

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


class WikibaseSkeleton(unittest.TestCase):
    """``--wikibase``: a static copy of a Wikibase (0.30.0)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        (self.base / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.out = self.base / "wb-sq-static"

    def make(self, *extra: str, url: str = "https://sq.wikibase.cloud/") -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = new_satellite.main(["wb-sq-static", "--title", "sq (static copy)", "--description", "A copy of sq.", "--prefix", "sqb",
                                       "--wikibase", url, "--out", str(self.out), "--date", "2026-11-18", *extra])
        return code, out.getvalue()

    def read(self, name: str) -> str:
        return (self.out / name).read_text(encoding="utf-8")

    def run_main(self, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "main.py", *args], cwd=self.out, capture_output=True, text=True, timeout=300,
                              env=dict(os.environ, PYTHONPATH=str(ROOT / "py"), **(extra_env or {})))

    def test_the_files_are_there_and_nothing_is_left_unfilled(self) -> None:
        code, text = self.make()
        self.assertEqual(code, 0, text)
        for name in ("main.py", "site.yaml", "requirements.txt", "README.md", "PRIMER.md", "CITATION.cff", "LICENSE", "update.cmd", "harvest.cmd",
                     ".gitignore", ".gitattributes", ".github/workflows/site.yml", ".github/workflows/update.yml"):
            self.assertTrue((self.out / name).is_file(), name)
        self.assertFalse((self.out / "data").exists(), "the data come from the harvest")
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("{{", path.read_text(encoding="utf-8"), str(path))

    def test_site_yaml_names_the_source_and_its_own_uris(self) -> None:
        self.make()
        site = self.read("site.yaml")
        self.assertIn("source:\n  url: https://sq.wikibase.cloud\n", site)       # no trailing slash
        self.assertIn("rdf_base: https://n4o-rse.github.io/wb-sq-static\n", site)
        self.assertIn("pages_url: https://n4o-rse.github.io/wb-sq-static/\n", site)
        self.assertIn("rdf_prefix: sqb\n", site)
        self.assertIn("\n# logo: assets/logo.png\n", site)                        # fetch-logo fills this line
        self.assertIn(f"@v{new_satellite.package_version()}", self.read("requirements.txt"))
        self.assertIn("deploy: true", self.read(".github/workflows/site.yml"))
        self.assertIn("data/derived/", self.read(".gitignore"))
        self.assertNotIn("\ndata/raw/\n", self.read(".gitignore"))                # the archived source is committed

    def test_the_first_run_line_harvests_and_fetches_the_logo(self) -> None:
        _code, text = self.make()
        line = [row for row in text.splitlines() if row.startswith("pip install")][0]
        self.assertEqual(line.split(" && ")[:4], ["pip install -r requirements.txt", "python main.py harvest --probe", "python main.py harvest",
                                                   "python main.py fetch-logo"])
        self.assertIn("python main.py --strict && git add -A", line)

    def test_a_logo_given_is_copied_and_named(self) -> None:
        _code, text = self.make("--logo", str(self.base / "logo.png"))
        self.assertTrue((self.out / "assets" / "logo.png").is_file())
        self.assertIn("\nlogo: assets/logo.png\n", self.read("site.yaml"))
        self.assertNotIn("fetch-logo", text)

    def test_cmd_files_keep_their_line_endings(self) -> None:
        self.make()
        for name in ("harvest.cmd", "update.cmd"):
            data = (self.out / name).read_bytes()
            self.assertIn(b"\r\n", data, name)
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), name)
        self.assertIn(b"python main.py harvest", (self.out / "harvest.cmd").read_bytes())

    def test_seeds_and_a_bad_address_are_refused(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            for extra in (("--qids", "Q1"), ("--small",), ("--seeds-text", "x")):
                with self.assertRaises(SystemExit):
                    self.make(*extra)
            for url in ("squirrelbase.wikibase.cloud", "ftp://x.org", "https://x y.org"):
                with self.assertRaises(SystemExit):
                    self.make(url=url)
        self.assertFalse(self.out.exists())

    def test_the_wrapper_lists_the_verbs(self) -> None:
        self.make()
        run = self.run_main("--list")
        self.assertEqual(run.returncode, 0, run.stderr)
        rows = {line.split()[0]: line.split()[1] for line in run.stdout.splitlines()}
        self.assertEqual(rows["harvest"], "verb")
        self.assertEqual(rows["fetch-logo"], "verb")
        self.assertEqual(rows["build"], "default")

    def test_the_first_harvest_takes_the_address_from_site_yaml(self) -> None:
        fake = FakeWikibase()
        server = make_server(fake)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        code, _text = self.make(url=f"http://127.0.0.1:{server.server_address[1]}")
        self.assertEqual(code, 0)
        run = self.run_main("harvest", "--delay", "0")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("listed 7 entities", run.stdout)
        manifest = (self.out / "data" / "raw" / "manifest.json").read_text(encoding="utf-8")
        self.assertIn(f"127.0.0.1:{server.server_address[1]}", manifest)
        again = self.run_main("harvest", "--delay", "0")                         # now the manifest has it
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("(nothing written)", again.stdout)

    def test_a_harvested_skeleton_builds_strict_twice_with_the_same_output(self) -> None:
        self.make()
        run = self.run_main("harvest", "--from-dir", str(ROOT / "tests" / "fixtures" / "entities"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        first = self.run_main("--strict")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertTrue((self.out / "docs" / "index.html").is_file())
        self.assertIn("sqb:", (next((self.out / "dist").glob("*.ttl")).read_text(encoding="utf-8")))

        def tree() -> dict[str, bytes]:
            return {str(p.relative_to(self.out)): p.read_bytes() for folder in ("docs", "dist", "data/derived") for p in sorted((self.out / folder).rglob("*")) if p.is_file()}

        one = tree()
        second = self.run_main("--strict")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(tree(), one)


if __name__ == "__main__":
    unittest.main()
