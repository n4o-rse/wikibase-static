"""Tests for the counterpart in a real Wikibase (S7g): ``counterpart.py``, ``counterpart`` in site.yaml, the line on entity
pages, ``owl:sameAs`` in the RDF and the published table.

    python tests/test_counterpart.py
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

import rdflib  # noqa: E402

from wikibase_static import counterpart, site_config, step_build, step_from_csv, step_rdf, utils  # noqa: E402

ENTITIES = """id,kind,datatype,origin,label_en,description_en
Q100,class,,,Software,
Q101,item,,,Alligator,
Q102,item,,,Other,
P100,property,string,,inventory,
"""
STATEMENTS = """sid,subject,property,value,rank,origin
,Q101,P2,Q100,,
a1,Q101,P100,x,,
"""
# the table the push writes: the third column is ignored; Q999 is not on the site; Q102 has no row
IDMAP = """source_id,target_id,label_en
Q100,Q5,Software
Q101,Q42,Alligator
P100,P34,inventory
Q999,Q77,not here
"""
SITE_YAML = """title: Demo
pages_url: https://example.org/demo/
rdf_base: https://example.org/demo
rdf_prefix: chb
counterpart:
  name: wiki.example
  uri: https://wiki.example/entity/{id}
  url: https://wiki.example/wiki/Special:EntityPage/{id}
  map: data/idmap-wiki.example.csv
"""
OWL_SAME = rdflib.URIRef("http://www.w3.org/2002/07/owl#sameAs")


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.csv = self.root / "data" / "csv"
        self.csv.mkdir(parents=True)
        for name, text in (("entities.csv", ENTITIES), ("statements.csv", STATEMENTS)):
            (self.csv / name).write_text(text, encoding="utf-8", newline="")
        (self.root / "data" / "idmap-wiki.example.csv").write_text(IDMAP, encoding="utf-8", newline="")

    def build(self, site_yaml: str = SITE_YAML) -> str:
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
                self.assertEqual(step_rdf.main([]), 0, out.getvalue())
        finally:
            for name, value in saved.items():
                setattr(utils, name, value)
        return out.getvalue()

    def page(self, entity_id: str) -> str:
        return (self.root / "docs" / f"{entity_id}.html").read_text(encoding="utf-8")

    def graph(self, entity_id: str) -> rdflib.Graph:
        g = rdflib.Graph()
        g.parse(self.root / "docs" / "ttl" / f"{entity_id}.ttl", format="turtle")
        return g

    def read(self, text: str) -> site_config.SiteConfig:
        path = self.root / "site.yaml"
        path.write_text(text, encoding="utf-8")
        return site_config.load_config(path)


class Config(Case):
    def test_a_complete_block_is_read(self) -> None:
        cfg = self.read(SITE_YAML)
        c = cfg.counterpart
        self.assertEqual((c.name, c.uri, c.url, c.map_file),
                         ("wiki.example", "https://wiki.example/entity/{id}", "https://wiki.example/wiki/Special:EntityPage/{id}",
                          "data/idmap-wiki.example.csv"))
        self.assertEqual(cfg.problems, [])

    def test_the_page_address_defaults_to_the_concept_uri(self) -> None:
        cfg = self.read("counterpart:\n  name: w\n  uri: https://w.example/entity/{id}\n  map: data/m.csv\n")
        self.assertEqual(cfg.counterpart.url, "https://w.example/entity/{id}")

    def test_no_block_no_counterpart(self) -> None:
        cfg = self.read("title: T\n")
        self.assertIsNone(cfg.counterpart)
        self.assertEqual(cfg.problems, [])

    def test_a_half_written_block_is_a_problem_and_ignored(self) -> None:
        for text in ("counterpart:\n  name: w\n  map: data/m.csv\n",                                      # no uri
                     "counterpart:\n  uri: https://w.example/entity/{id}\n  map: data/m.csv\n",           # no name
                     "counterpart:\n  name: w\n  uri: https://w.example/entity/{id}\n",                   # no map
                     "counterpart:\n  name: w\n  uri: https://w.example/entity/\n  map: data/m.csv\n",     # no {id}
                     "counterpart:\n  name: w\n  uri: not a url {id}\n  map: data/m.csv\n",
                     "counterpart:\n  name: w\n  uri: https://w.example/entity/{id}\n  map: ../m.csv\n",   # outside the repository
                     "counterpart: nonsense\n"):
            cfg = self.read(text)
            self.assertIsNone(cfg.counterpart, text)
            self.assertTrue(any("counterpart" in p for p in cfg.problems), text)

    def test_an_unknown_key_in_the_block_is_reported_and_ignored(self) -> None:
        cfg = self.read(SITE_YAML + "  colour: red\n")
        self.assertIsNotNone(cfg.counterpart)
        self.assertTrue(any("counterpart.colour" in p for p in cfg.problems))


class Table(Case):
    def test_rows_of_this_site_only_and_the_extra_column_is_ignored(self) -> None:
        c = counterpart.load(self.read(SITE_YAML).counterpart, self.root, {"Q100", "Q101", "Q102", "P100"})
        self.assertEqual(c.ids, {"Q100": "Q5", "Q101": "Q42", "P100": "P34"})
        self.assertTrue(any("Q999" in p and "does not have" in p for p in c.problems), c.problems)
        self.assertIsNone(c.target_uri("Q102"))
        self.assertEqual(c.target_uri("Q101"), "https://wiki.example/entity/Q42")
        self.assertEqual(c.target_url("Q101"), "https://wiki.example/wiki/Special:EntityPage/Q42")

    def test_bad_rows_are_skipped_with_a_message_and_nothing_is_guessed(self) -> None:
        table = self.root / "t.csv"
        table.write_text("source_id,target_id\nQ1,Q2\nQ3,P4\nQ1,Q9\nx,Q5\nQ5,\n", encoding="utf-8")
        ids, problems = counterpart.load_table(table)
        self.assertEqual(ids, {"Q1": "Q2"})
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("appears twice" in p for p in problems))

    def test_a_table_without_the_columns_or_a_missing_file_is_one_message(self) -> None:
        table = self.root / "t.csv"
        table.write_text("a,b\n1,2\n", encoding="utf-8")
        self.assertEqual(counterpart.load_table(table)[0], {})
        self.assertIn("needs the columns", counterpart.load_table(table)[1][0])
        self.assertIn("not found", counterpart.load_table(self.root / "nope.csv")[1][0])


class Pages(Case):
    def test_a_mapped_entity_links_to_its_counterpart_in_a_new_tab(self) -> None:
        self.build()
        page = self.page("Q101")
        self.assertRegex(page, re.compile(r'<p class="counterpart">.*?<a href="https://wiki\.example/wiki/Special:EntityPage/Q42" '
                                          r'target="_blank" rel="noopener">Q42</a>', re.S))
        self.assertIn("The same entity in wiki.example", page)

    def test_a_property_links_with_its_own_id(self) -> None:
        self.build()
        self.assertIn("https://wiki.example/wiki/Special:EntityPage/P34", self.page("P100"))

    def test_an_entity_without_a_row_has_no_line(self) -> None:
        self.build()
        self.assertNotIn('class="counterpart"', self.page("Q102"))

    def test_the_start_page_links_to_the_table_and_the_table_is_published_as_it_is(self) -> None:
        self.build()
        index = (self.root / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="downloads/idmap-wiki.example.csv"', index)
        self.assertEqual((self.root / "docs" / "downloads" / "idmap-wiki.example.csv").read_text(encoding="utf-8"), IDMAP)

    def test_without_the_block_nothing_of_it_appears(self) -> None:
        self.build("title: Demo\npages_url: https://example.org/demo/\nrdf_base: https://example.org/demo\nrdf_prefix: chb\n")
        self.assertNotIn("counterpart", self.page("Q101"))
        self.assertNotIn("counterpart", (self.root / "docs" / "index.html").read_text(encoding="utf-8"))
        self.assertFalse((self.root / "docs" / "downloads" / "idmap-wiki.example.csv").exists())

    def test_a_missing_table_is_a_warning_and_the_build_goes_on(self) -> None:
        (self.root / "data" / "idmap-wiki.example.csv").unlink()
        out = self.build()
        self.assertIn("counterpart: idmap-wiki.example.csv not found", out)
        self.assertNotIn('class="counterpart"', self.page("Q101"))

    def test_two_builds_give_the_same_files(self) -> None:
        self.build()
        first = {p.name: p.read_bytes() for p in (self.root / "docs").rglob("*") if p.is_file()}
        self.build()
        second = {p.name: p.read_bytes() for p in (self.root / "docs").rglob("*") if p.is_file()}
        self.assertEqual(first, second)


class Rdf(Case):
    def test_the_entity_is_the_same_as_its_counterpart_in_its_own_file(self) -> None:
        self.build()
        g = self.graph("Q101")
        twins = {str(o) for s, o in g.subject_objects(OWL_SAME)}
        self.assertEqual(twins, {"https://wiki.example/entity/Q42"})
        subject = {str(s) for s in g.subjects(OWL_SAME, None)}
        self.assertEqual(subject, {"https://example.org/demo/entity/Q101"})

    def test_a_property_too_and_an_unmapped_entity_not(self) -> None:
        self.build()
        self.assertEqual({str(o) for o in self.graph("P100").objects(None, OWL_SAME)}, {"https://wiki.example/entity/P34"})
        self.assertEqual(list(self.graph("Q102").subject_objects(OWL_SAME)), [])

    def test_the_whole_export_carries_the_same_triples(self) -> None:
        self.build()
        whole = rdflib.Graph()
        for ttl in (self.root / "docs" / "downloads").glob("*.ttl"):
            if "ontology" not in ttl.name:
                whole.parse(ttl, format="turtle")
        self.assertEqual(len(list(whole.subject_objects(OWL_SAME))), 3)

    def test_the_note_says_how_many(self) -> None:
        out = self.build()
        self.assertTrue(re.search(r"note: counterpart wiki\.example: owl:sameAs written for 3 of \d+ entities", out), out)


if __name__ == "__main__":
    unittest.main()
