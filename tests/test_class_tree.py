"""Tests for the class hierarchy on the overview and on class pages (``Renderer.class_tree``).

    python tests/test_class_tree.py
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import step_build, step_from_csv, utils  # noqa: E402

#   Q3 > Q100 software > Q101 library > Q103 R library
#                      > Q102 script  > Q103 R library      (two superclasses)
#   Q3 > Q104 other
ENTITIES = """id,kind,datatype,origin,label_en
Q100,class,,,software
Q101,class,,,library
Q102,class,,,script
Q103,class,,,R library
Q104,class,,,other
Q105,item,,,a package
"""
STATEMENTS = """sid,subject,property,value,rank,origin
,Q100,P1,Q3,,
,Q101,P1,Q100,,
,Q102,P1,Q100,,
,Q103,P1,Q101,,
,Q103,P1,Q102,,
,Q104,P1,Q3,,
,Q105,P2,Q101,,
"""


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        csv_dir = self.root / "data" / "csv"
        csv_dir.mkdir(parents=True)
        (csv_dir / "entities.csv").write_text(ENTITIES, encoding="utf-8", newline="")
        (csv_dir / "statements.csv").write_text(STATEMENTS, encoding="utf-8", newline="")
        names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
        saved = {n: getattr(utils, n) for n in names}
        utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = self.root, self.root / "data" / "raw", self.root / "data" / "derived"
        utils.DOCS, utils.SITE_YAML, utils.DIST = self.root / "docs", self.root / "site.yaml", self.root / "dist"
        self.addCleanup(lambda: [setattr(utils, n, v) for n, v in saved.items()])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(step_from_csv.main(["--csv", str(csv_dir), "--out", str(utils.DATA_DERIVED)]), 0)
            self.assertEqual(step_build.main([]), 0)

    def tree(self, page: str, index: int = 0) -> list[tuple[int, str, bool]]:
        """(depth, id, current) of the entries of the index-th hierarchy block, in order."""
        text = (self.root / "docs" / page).read_text(encoding="utf-8")
        block = re.findall(r'<div class="class-tree">(.*?)\n\s*</div>', text, re.S)[index]
        depth, found = 0, []
        for token in re.finditer(r'<ul>|</ul>|<li( class="current")?>.*?<a href="(Q\d+)\.html"', block, re.S):
            if token.group(0) == "<ul>":
                depth += 1
            elif token.group(0) == "</ul>":
                depth -= 1
            else:
                found.append((depth, token.group(2), bool(token.group(1))))
        return found


class Tree(Case):
    def test_the_class_sits_in_the_middle_with_everything_above_and_below(self) -> None:
        self.assertEqual(self.tree("Q101.html"),
                         [(1, "Q100", False), (2, "Q101", True), (3, "Q103", False)])

    def test_siblings_of_the_ancestors_are_left_out(self) -> None:
        ids = [i for _d, i, _c in self.tree("Q101.html")]
        self.assertNotIn("Q102", ids)
        self.assertNotIn("Q104", ids)

    def test_a_class_with_two_superclasses_appears_under_both(self) -> None:
        self.assertEqual(self.tree("Q103.html"),
                         [(1, "Q100", False), (2, "Q101", False), (3, "Q103", True),
                          (2, "Q102", False), (3, "Q103", True)])

    def test_the_root_shows_everything_below(self) -> None:
        ids = [i for _d, i, _c in self.tree("Q3.html")]
        self.assertEqual(ids[0], "Q3")
        self.assertEqual(set(ids), {"Q3", "Q1", "Q2", "Q100", "Q101", "Q102", "Q103", "Q104"})     # Q1 Class and Q2 Property sit below Q3 in the kernel

    def test_the_kernel_root_instance_is_not_shown_except_on_its_own_page(self) -> None:
        for page in ("Q100.html", "Q101.html", "Q103.html", "overview.html"):
            self.assertNotIn("Q3", [i for _d, i, _c in self.tree(page)], page)
        self.assertEqual(self.tree("Q3.html")[0], (1, "Q3", True))

    def test_a_class_directly_below_the_root_without_subclasses_has_no_block(self) -> None:
        text = (self.root / "docs" / "Q104.html").read_text(encoding="utf-8")
        self.assertNotIn('class="class-tree"', text)

    def test_an_item_has_no_hierarchy_block(self) -> None:
        self.assertNotIn('class="class-tree"', (self.root / "docs" / "Q105.html").read_text(encoding="utf-8"))

    def test_the_overview_shows_the_same_tree_under_each_group(self) -> None:
        self.assertEqual(self.tree("overview.html"), self.tree("Q101.html"))

    def test_the_block_has_its_heading(self) -> None:
        text = (self.root / "docs" / "Q101.html").read_text(encoding="utf-8")
        self.assertIn("Class hierarchy", text)


if __name__ == "__main__":
    unittest.main()
