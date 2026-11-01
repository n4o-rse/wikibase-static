"""Tests for tools/rollout.py: the parts that need no network (the pin, the list of repositories)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "rollout.py"
spec = importlib.util.spec_from_file_location("rollout", TOOL)
rollout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)

PIN = "wikibase-static @ git+https://github.com/n4o-rse/wikibase-static.git@v0.24.2"


class Pin(unittest.TestCase):
    def test_the_pin_is_changed_and_nothing_else(self) -> None:
        text = f"# Needs wikibase-static 0.24.0 or later\n\n{PIN}\nPyYAML>=6\n"
        new, old = rollout.repin(text, "v0.25.0")
        self.assertEqual(old, "v0.24.2")
        self.assertEqual(new, text.replace("@v0.24.2", "@v0.25.0"))

    def test_line_endings_are_kept(self) -> None:
        new, _ = rollout.repin(f"{PIN}\r\nrdflib\r\n", "v0.25.0")
        self.assertEqual(new, "wikibase-static @ git+https://github.com/n4o-rse/wikibase-static.git@v0.25.0\r\nrdflib\r\n")

    def test_without_a_pin_nothing_is_changed(self) -> None:
        text = "wikibase-static @ git+https://github.com/n4o-rse/wikibase-static.git\n"
        self.assertEqual(rollout.repin(text, "v0.25.0"), (text, None))

    def test_a_commit_pin_is_replaced_too(self) -> None:
        new, old = rollout.repin(PIN.replace("v0.24.2", "76d9722"), "v0.25.0")
        self.assertEqual(old, "76d9722")
        self.assertTrue(new.endswith("@v0.25.0"))


class Satellites(unittest.TestCase):
    def test_comments_and_blank_lines_are_skipped(self) -> None:
        self.assertEqual(rollout.read_satellites("# all\n\nn4o-rse/a  # first\n  n4o-rse/b\n"), ["n4o-rse/a", "n4o-rse/b"])

    def test_the_list_in_the_repository_is_valid(self) -> None:
        listed = rollout.read_satellites(rollout.SATELLITES.read_text(encoding="utf-8"))
        self.assertTrue(listed)
        self.assertTrue(all(s.startswith("n4o-rse/") for s in listed))

    def test_a_line_that_is_not_owner_repo_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            rollout.read_satellites("just-a-name\n")

    def test_the_package_version_is_read(self) -> None:
        self.assertRegex(rollout.package_version(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
