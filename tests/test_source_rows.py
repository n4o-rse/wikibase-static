"""Tests for the tab "Source rows" (S7f): ``source_rows.py``, the section on entity pages, ``edit_url`` in site.yaml.

    python tests/test_source_rows.py
"""

from __future__ import annotations

import contextlib
import html
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import csvio, site_config, source_rows, step_build, step_from_csv, utils  # noqa: E402

# Written by hand, not through the canonical writer: a quoted cell that needs no quotes, a cell over two lines, a blank line between rows.
ENTITIES = '''id,kind,datatype,origin,label_en,description_en
Q100,class,,,Software,
Q101,item,,,"Alligator","A tool
over two lines"

Q102,item,,,Other,
P100,property,string,,inventory,
P101,property,url,,page,
'''
STATEMENTS = '''sid,subject,property,value,rank,origin
,Q100,P1,Q3,,
,Q101,P2,Q100,,
a1,Q101,P100,x,,
a2,Q101,P101,https://example.org/a,,
,Q102,P2,Q100,,
b1,Q102,P100,y,,
'''
QUALIFIERS = "sid,property,value\na1,P101,https://example.org/q\nb1,P101,https://example.org/other\n"
REFERENCES = "sid,group,property,value\na1,1,P101,https://example.org/ref\nb1,1,P101,https://example.org/ref-b\n"
MERGES = "from,to,note\nQ102,Q101,same\n"


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.csv = self.root / "data" / "csv"
        self.csv.mkdir(parents=True)
        for name, text in (("entities.csv", ENTITIES), ("statements.csv", STATEMENTS), ("qualifiers.csv", QUALIFIERS),
                           ("references.csv", REFERENCES), ("merges.csv", MERGES)):
            (self.csv / name).write_text(text, encoding="utf-8", newline="")

    def build(self, site_yaml: str = "") -> str:
        if site_yaml:
            (self.root / "site.yaml").write_text(site_yaml, encoding="utf-8")
        names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
        saved = {n: getattr(utils, n) for n in names}
        utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = self.root, self.root / "data" / "raw", self.root / "data" / "derived"
        utils.DOCS, utils.SITE_YAML, utils.DIST = self.root / "docs", self.root / "site.yaml", self.root / "dist"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(step_from_csv.main(["--csv", str(self.csv), "--out", str(utils.DATA_DERIVED)]), 0)
                self.assertEqual(step_build.main([]), 0, out.getvalue())
        finally:
            for name, value in saved.items():
                setattr(utils, name, value)
        return out.getvalue()

    def page(self, entity_id: str) -> str:
        return (self.root / "docs" / f"{entity_id}.html").read_text(encoding="utf-8")

    def blocks_of(self, page: str) -> dict[str, str]:
        found = {}
        for name, body in re.findall(r'<h3><code>([^<]+)</code>.*?<pre id="rows-\d+" class="rows"><code>(.*?)</code></pre>', page, re.S):
            found[name] = html.unescape(body)
        return found


class Rows(Case):
    def test_the_rows_are_the_lines_of_the_file_whatever_the_quoting(self) -> None:
        found = source_rows.SourceRows.load(self.csv).blocks("Q101")
        by_file = {b.file: b.text for b in found}
        self.assertEqual(by_file["entities.csv"], 'id,kind,datatype,origin,label_en,description_en\nQ101,item,,,"Alligator","A tool\nover two lines"')
        self.assertEqual(by_file["statements.csv"], "sid,subject,property,value,rank,origin\n,Q101,P2,Q100,,\na1,Q101,P100,x,,\na2,Q101,P101,https://example.org/a,,")

    def test_qualifiers_and_references_of_its_statements_only(self) -> None:
        by_file = {b.file: b.text for b in source_rows.SourceRows.load(self.csv).blocks("Q101")}
        self.assertEqual(by_file["qualifiers.csv"], "sid,property,value\na1,P101,https://example.org/q")
        self.assertEqual(by_file["references.csv"], "sid,group,property,value\na1,1,P101,https://example.org/ref")

    def test_merge_lines_are_shown_on_both_sides(self) -> None:
        for entity in ("Q101", "Q102"):
            self.assertIn("merges.csv", [b.file for b in source_rows.SourceRows.load(self.csv).blocks(entity)])

    def test_the_kernel_is_shown_from_its_own_tables_and_cannot_be_edited(self) -> None:
        blocks = source_rows.SourceRows.load(self.csv).blocks("P2")
        self.assertTrue(blocks)
        self.assertTrue(all(b.file.startswith("kernel/") and not b.editable for b in blocks), [b.file for b in blocks])

    def test_no_entities_csv_no_rows(self) -> None:
        (self.csv / "entities.csv").unlink()
        self.assertIsNone(source_rows.SourceRows.load(self.csv))

    def test_counts(self) -> None:
        counts = {b.file: b.rows for b in source_rows.SourceRows.load(self.csv).blocks("Q101")}
        self.assertEqual(counts, {"entities.csv": 1, "statements.csv": 3, "qualifiers.csv": 1, "references.csv": 1, "merges.csv": 1})


class Pages(Case):
    def test_the_block_of_a_page_is_the_text_of_the_file_lines(self) -> None:
        self.build()
        page = self.page("Q101")
        blocks = self.blocks_of(page)
        source = source_rows.SourceRows.load(self.csv)
        self.assertEqual(blocks, {b.file: b.text for b in source.blocks("Q101")})
        for name, text in blocks.items():
            if name.startswith("kernel/") or name == "entities.csv":         # entities.csv holds the cell over two lines (see test above)
                continue
            file_lines = (self.csv / name).read_text(encoding="utf-8").split("\n")
            for line in text.split("\n"):
                self.assertIn(line, file_lines, f"{name}: {line}")

    def test_the_tab_links_to_the_section_and_the_section_has_copy_buttons(self) -> None:
        self.build()
        page = self.page("Q101")
        self.assertIn('<li><a href="#source-rows">', page)
        self.assertIn('<details id="source-rows">', page)
        self.assertEqual(len(re.findall(r'data-copy-from="rows-(\d+)"', page)), len(re.findall(r'<pre id="rows-\d+"', page)))

    def test_every_entity_page_has_the_section(self) -> None:
        self.build()
        for entity in ("Q100", "Q101", "P100", "P1", "Q1"):
            self.assertIn('id="source-rows"', self.page(entity), entity)

    def test_the_redirect_page_has_no_section(self) -> None:
        self.build()
        self.assertNotIn("source-rows", self.page("Q102"))

    def test_text_is_escaped(self) -> None:
        (self.csv / "statements.csv").write_text(STATEMENTS.replace("a1,Q101,P100,x,,", 'a1,Q101,P100,"<b>&x",,'), encoding="utf-8", newline="")
        self.build()
        page = self.page("Q101")
        self.assertIn("&lt;b&gt;&amp;x", page)
        self.assertNotIn("<b>&x", page)

    def test_without_csv_there_is_no_tab_and_no_section(self) -> None:
        # a site that was harvested: data/raw only, no data/csv (the fixtures of the other tests)
        import shutil
        shutil.rmtree(self.csv)
        shutil.copytree(HERE / "fixtures" / "entities", self.root / "data" / "raw" / "entities")
        names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
        saved = {n: getattr(utils, n) for n in names}
        utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = self.root, self.root / "data" / "raw", self.root / "data" / "derived"
        utils.DOCS, utils.SITE_YAML, utils.DIST = self.root / "docs", self.root / "site.yaml", self.root / "dist"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(step_build.main([]), 0)
        finally:
            for name, value in saved.items():
                setattr(utils, name, value)
        page = self.page("Q1")
        self.assertNotIn("source-rows", page)
        self.assertNotIn("Source rows", page)

    def test_edit_url_gives_a_link_per_editable_file_and_none_for_the_kernel(self) -> None:
        self.build("title: T\nedit_url: https://github.com/o/r/edit/main/data/csv/\n")
        page = self.page("Q101")
        for name in ("entities.csv", "statements.csv", "qualifiers.csv", "references.csv", "merges.csv"):
            self.assertIn(f'href="https://github.com/o/r/edit/main/data/csv/{name}"', page)
        kernel_page = self.page("P2")
        self.assertNotIn("github.com/o/r", kernel_page)

    def test_without_edit_url_no_edit_link(self) -> None:
        self.build()
        self.assertNotIn("Edit the file", self.page("Q101"))


class Config(unittest.TestCase):
    def read(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site.yaml"
            path.write_text(text, encoding="utf-8")
            return site_config.load_config(path, None)

    def test_edit_url_is_read_and_loses_its_trailing_slash(self) -> None:
        cfg = self.read("edit_url: https://github.com/o/r/edit/main/data/csv/\n")
        self.assertEqual((cfg.edit_url, cfg.problems), ("https://github.com/o/r/edit/main/data/csv", []))

    def test_a_bad_edit_url_is_a_problem_and_ignored(self) -> None:
        cfg = self.read("edit_url: not a url\n")
        self.assertIsNone(cfg.edit_url)
        self.assertTrue(any("edit_url" in p for p in cfg.problems))

    def test_both_languages_have_the_new_strings(self) -> None:
        from wikibase_static import render
        for key in ("tab_source", "source_rows", "copy_rows", "edit_file", "source_rows_intro", "rows_n"):
            self.assertIn(key, render.STRINGS["en"])
            self.assertIn(key, render.STRINGS["de"])


if __name__ == "__main__":
    unittest.main()
