"""Tests for tools/untrack_output.py: a site repository stops committing docs/ and data/derived/ (0.29.0).

    python tests/test_untrack_output.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "tools"))

import untrack_output as tool  # noqa: E402

HAVE_GIT = shutil.which("git") is not None

MAIN = '''import pathlib
root = pathlib.Path(__file__).resolve().parent
text = (root / "data" / "raw" / "x.txt").read_text(encoding="utf-8")
for name, body in (("docs/index.html", "<p>" + text + "</p>"), ("data/derived/x.json", '{"x": "' + text + '"}')):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8", newline="\\n")
'''


class Pure(unittest.TestCase):
    def test_compare_names_what_the_fresh_build_lacks_adds_and_changes(self) -> None:
        diff = tool.compare({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "9", "d": "4"})
        self.assertEqual(diff, {"lost": ["c"], "added": ["d"], "changed": ["b"]})

    def test_the_ignore_lines_are_added_once(self) -> None:
        first = tool.ignore_text("*.pyc\n", ["docs", "data/derived"])
        self.assertIn("docs/\n", first)
        self.assertIn("data/derived/\n", first)
        self.assertEqual(tool.ignore_text(first, ["docs", "data/derived"]), first)

    def test_the_old_note_that_says_do_not_ignore_docs_goes(self) -> None:
        old = "*.pyc\n\n# --- Note ---\n# dist/, docs/ and data/ are deliberately NOT ignored: x\n# y\n\nPATCH-README.md\n"
        new = tool.ignore_text(old, ["docs"])
        self.assertNotIn("deliberately NOT ignored", new)
        self.assertIn("PATCH-README.md", new)
        self.assertIn("docs/\n", new)

    def test_the_template_ignores_the_output(self) -> None:
        text = (REPO / "tools" / "satellite-template" / ".gitignore").read_text(encoding="utf-8")
        lines = {line.strip() for line in text.splitlines()}
        self.assertTrue({"docs/", "data/derived/"} <= lines)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Run(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name) / "site"
        (self.site / "data" / "raw").mkdir(parents=True)
        (self.site / "data" / "raw" / "x.txt").write_text("one", encoding="utf-8")
        (self.site / "main.py").write_text(MAIN, encoding="utf-8")
        (self.site / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        subprocess.run([sys.executable, "main.py"], cwd=self.site, check=True)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "site")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args], cwd=self.site,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout

    def run_tool(self, *extra: str) -> int:
        return tool.main([str(self.site), "--command", f'"{sys.executable}" main.py', *extra])

    def test_it_refuses_without_the_word_about_pages(self) -> None:
        self.assertEqual(self.run_tool(), 1)
        self.assertIn("docs/index.html", self.git("ls-files"))

    def test_the_output_leaves_git_and_stays_on_disk(self) -> None:
        self.assertEqual(self.run_tool("--pages-is-actions"), 0)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "untrack")
        tracked = self.git("ls-files")
        self.assertNotIn("docs/", tracked)
        self.assertNotIn("data/derived/", tracked)
        self.assertIn("main.py", tracked)
        self.assertTrue((self.site / "docs" / "index.html").is_file())
        self.assertEqual(self.git("status", "--porcelain"), "")           # ignored now, the rebuild leaves the tree clean
        subprocess.run([sys.executable, "main.py"], cwd=self.site, check=True)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_hand_made_file_in_docs_stops_it_and_stays(self) -> None:
        (self.site / "docs" / "by-hand.html").write_text("x", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "by hand")
        self.assertEqual(self.run_tool("--pages-is-actions"), 1)
        self.assertTrue((self.site / "docs" / "by-hand.html").is_file())
        self.assertIn("docs/by-hand.html", self.git("ls-files"))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_site_that_is_out_of_date_stops_it(self) -> None:
        (self.site / "data" / "raw" / "x.txt").write_text("two", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "source changed, docs not rebuilt")
        self.assertEqual(self.run_tool("--pages-is-actions"), 1)
        self.assertIn("docs/index.html", self.git("ls-files"))

    def test_check_changes_nothing(self) -> None:
        self.assertEqual(self.run_tool("--pages-is-actions", "--check"), 0)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIn("docs/index.html", self.git("ls-files"))

    def test_a_repository_that_does_not_track_docs_is_left_alone(self) -> None:
        self.assertEqual(self.run_tool("--pages-is-actions"), 0)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "untrack")
        self.assertEqual(self.run_tool("--pages-is-actions"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
