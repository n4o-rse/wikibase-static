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

    def test_a_requirement_without_any_ref_gets_the_pin(self) -> None:
        text = "wikibase-static @ git+https://github.com/n4o-rse/wikibase-static.git\nPyYAML\n"
        new, old = rollout.repin(text, "v0.26.1")
        self.assertEqual(new, "wikibase-static @ git+https://github.com/n4o-rse/wikibase-static.git@v0.26.1\nPyYAML\n")
        self.assertEqual(old, "main (no tag)")

    def test_without_a_wikibase_static_requirement_nothing_is_changed(self) -> None:
        text = "PyYAML\nrdflib\n"
        self.assertEqual(rollout.repin(text, "v0.26.1"), (text, None))

    def test_a_commit_pin_is_replaced_too(self) -> None:
        new, old = rollout.repin(PIN.replace("v0.24.2", "76d9722"), "v0.25.0")
        self.assertEqual(old, "76d9722")
        self.assertTrue(new.endswith("@v0.25.0"))


class Newest(unittest.TestCase):
    def test_the_highest_version_wins_by_number_not_by_text(self) -> None:
        self.assertEqual(rollout.newest(["v0.9.0", "v0.10.1", "v0.10.0", "v0.2.0"]), "0.10.1")

    def test_other_tags_are_ignored(self) -> None:
        self.assertEqual(rollout.newest(["latest", "v1", "v1.0.0-rc1", "v0.3.0"]), "0.3.0")
        self.assertIsNone(rollout.newest(["latest"]))


class Workflow(unittest.TestCase):
    """The update workflow and its caller say what the README promises."""

    def test_the_reusable_workflow_and_the_example_parse(self) -> None:
        import yaml
        root = Path(__file__).resolve().parent.parent
        workflow = yaml.safe_load((root / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8"))
        self.assertIn("workflow_call", workflow[True])                   # YAML reads the key `on` as True
        text = (root / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
        for needle in ("rollout.py\" --here", "gh pr create", "contents: write", "pull-requests: write", "changed == 'true'"):
            self.assertIn(needle, text)
        caller = yaml.safe_load((root / "examples" / "update-caller.yml").read_text(encoding="utf-8"))
        self.assertIn("schedule", caller[True])
        self.assertIn("workflow_dispatch", caller[True])
        self.assertTrue(caller["jobs"]["update"]["uses"].endswith("/update.yml@main"))


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
