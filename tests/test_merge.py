"""Tests for merges (S7h, S7i): ``merges.csv``, the merge while the tables are read, redirects in pages and RDF, the ``merge`` verb.

    python tests/test_merge.py
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import csvbuild, csvio, loader, rdf, step_build, step_from_csv, step_merge, utils  # noqa: E402

ENTITIES = [
    ("Q100", "class", "", "Software"), ("Q101", "item", "", "Alligator (Wikidata)"), ("Q102", "item", "", "alligator"),
    ("Q103", "item", "", "A user"), ("Q104", "item", "", "Other"), ("Q105", "class", "", "Tool"),
    ("P100", "property", "string", "inventory"), ("P101", "property", "wikibase-item", "used by"), ("P102", "property", "url", "page"),
]
# subject, property, value, sid
STATEMENTS = [
    ("Q100", "P1", "Q3", ""), ("Q105", "P1", "Q3", ""),
    ("Q101", "P2", "Q100", "a1"), ("Q101", "P100", "x", "a2"), ("Q101", "P102", "https://example.org/a", "a3"),
    ("Q102", "P2", "Q100", "b1"), ("Q102", "P2", "Q105", "b2"), ("Q102", "P100", "x", "b3"), ("Q102", "P100", "y", "b4"),
    ("Q102", "P102", "https://example.org/b", "b5"),
    ("Q103", "P2", "Q100", "c1"), ("Q103", "P101", "Q102", "c2"),
    ("Q104", "P2", "Q100", "d1"),
]
REFERENCES = [("a2", "1", "P102", "https://example.org/source-a"), ("b3", "1", "P102", "https://example.org/source-b"),
              ("b3", "2", "P102", "https://example.org/second")]
QUALIFIERS = [("c2", "P102", "https://example.org/via-b")]


def write(folder: Path, name: str, columns: list[str], rows: list[dict[str, str]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(csvio.render_table(columns, rows), encoding="utf-8", newline="")


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.csv = self.root / "data" / "csv"
        write(self.csv, "entities.csv", ["id", "kind", "datatype", "origin", "label_en", "aliases_en"],
              [{"id": i, "kind": k, "datatype": d, "label_en": label} for i, k, d, label in ENTITIES])
        write(self.csv, "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"],
              [{"subject": s, "property": p, "value": v, "sid": sid} for s, p, v, sid in STATEMENTS])
        write(self.csv, "qualifiers.csv", ["sid", "property", "value"], [{"sid": a, "property": b, "value": c} for a, b, c in QUALIFIERS])
        write(self.csv, "references.csv", ["sid", "group", "property", "value"],
              [{"sid": a, "group": g, "property": b, "value": c} for a, g, b, c in REFERENCES])

    def merges(self, *lines: tuple[str, str]) -> None:
        write(self.csv, csvbuild.MERGES, csvbuild.MERGE_COLUMNS, [{"from": a, "to": b, "note": ""} for a, b in lines])

    def build(self) -> csvbuild.Built:
        problems: list[str] = []
        site = csvbuild.read_set(self.csv, problems, "csv")
        built = csvbuild.build(site, csvbuild.kernel_set(), None)
        built.problems = sorted(set(built.problems) | set(problems))
        return built

    def values(self, built: csvbuild.Built, entity: str, prop: str) -> list[str]:
        out = []
        for claim in built.entities[entity]["claims"].get(prop, []):
            value = claim["mainsnak"]["datavalue"]["value"]
            out.append(value["id"] if isinstance(value, dict) else value)
        return out

    def run_verb(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = step_merge.main(["--csv", str(self.csv), *args])
        return code, out.getvalue()


class Merging(Case):
    def test_without_merges_nothing_changes(self) -> None:
        built = self.build()
        self.assertEqual(built.problems, [])
        self.assertEqual(built.redirects, {})
        self.assertIn("Q102", built.entities)

    def test_statements_move_and_identical_ones_are_not_doubled(self) -> None:
        self.merges(("Q102", "Q101"))
        built = self.build()
        self.assertEqual(built.problems, [])
        self.assertNotIn("Q102", built.entities)
        self.assertEqual(built.redirects, {"Q102": "Q101"})
        self.assertEqual(self.values(built, "Q101", "P2"), ["Q100", "Q105"])                  # Q100 once
        self.assertEqual(self.values(built, "Q101", "P100"), ["x", "y"])                      # x once, y moved
        self.assertEqual(self.values(built, "Q101", "P102"), ["https://example.org/a", "https://example.org/b"])

    def test_references_of_identical_statements_are_joined(self) -> None:
        self.merges(("Q102", "Q101"))
        claims = self.build().entities["Q101"]["claims"]["P100"]
        refs = [[s["datavalue"]["value"] for r in c.get("references", []) for snaks in r["snaks"].values() for s in snaks] for c in claims]
        self.assertEqual(refs[0], ["https://example.org/source-a", "https://example.org/source-b", "https://example.org/second"])

    def test_values_pointing_at_the_merged_item_point_at_the_target_also_in_qualifiers_free_places(self) -> None:
        self.merges(("Q102", "Q101"))
        built = self.build()
        self.assertEqual(self.values(built, "Q103", "P101"), ["Q101"])

    def test_statements_that_differ_only_in_naming_a_merged_item_are_the_same_one(self) -> None:
        # Q101 and Q102 both say "used by": one names Q103, the other Q104; Q104 is merged into Q103 as well.
        (self.csv / "statements.csv").write_text((self.csv / "statements.csv").read_text(encoding="utf-8")
                                                 + "e1,Q101,P101,Q103,,\ne2,Q102,P101,Q104,,\n", encoding="utf-8", newline="")
        self.merges(("Q102", "Q101"), ("Q104", "Q103"))
        built = self.build()
        self.assertEqual(built.problems, [])
        self.assertEqual(self.values(built, "Q101", "P101"), ["Q103"])                      # once, not twice

    def test_the_label_of_the_target_wins_and_the_other_becomes_an_alias(self) -> None:
        self.merges(("Q102", "Q101"))
        entity = self.build().entities["Q101"]
        self.assertEqual(entity["labels"]["en"]["value"], "Alligator (Wikidata)")
        self.assertEqual([a["value"] for a in entity["aliases"]["en"]], ["alligator"])

    def test_different_values_are_kept_and_named_in_the_notes(self) -> None:
        self.merges(("Q102", "Q101"))
        notes = self.build().merge_notes
        self.assertEqual(len(notes), 1)
        self.assertIn("Q102 -> Q101", notes[0])
        self.assertIn("different values for P2, P100, P102", notes[0])
        self.assertIn("already there", notes[0])

    def test_merging_classes_is_possible_but_not_a_class_with_an_item(self) -> None:
        self.merges(("Q105", "Q100"))
        self.assertEqual(self.build().redirects, {"Q105": "Q100"})
        self.merges(("Q105", "Q101"))
        built = self.build()
        self.assertEqual(built.redirects, {})
        self.assertTrue(any("only two of a kind" in p for p in built.problems), built.problems)

    def test_the_rules_chains_self_unknown_twice(self) -> None:
        for lines, text in (((("Q102", "Q101"), ("Q101", "Q104")), "itself merged into another item"),
                            ((("Q102", "Q102"),), "into itself"),
                            ((("Q102", "Q999"),), "not an entity"),
                            ((("Q102", "Q101"), ("Q102", "Q104")), "merged twice"),
                            ((("P100", "P101"),), "item ids"),
                            ((("Q1", "Q101"),), "kernel")):
            self.merges(*lines)
            built = self.build()
            self.assertTrue(any(text in p for p in built.problems), (lines, built.problems))

    def test_a_chain_is_refused_but_the_other_lines_still_work(self) -> None:
        self.merges(("Q102", "Q101"), ("Q101", "Q104"), ("Q103", "Q104"))
        built = self.build()
        self.assertEqual(built.redirects, {"Q101": "Q104", "Q103": "Q104"})     # only the line that points at a merged item is refused
        self.assertEqual(len([p for p in built.problems if "merged into another item" in p]), 1)

    def test_the_result_is_a_function_of_the_tables(self) -> None:
        self.merges(("Q102", "Q101"))
        self.assertEqual(json.dumps(self.build().entities, sort_keys=True), json.dumps(self.build().entities, sort_keys=True))


class Pipeline(Case):
    def derive(self) -> Path:
        out = self.root / "data" / "derived"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(step_from_csv.main(["--csv", str(self.csv), "--out", str(out)]), 0)
        self.from_csv_output = buffer.getvalue()
        return out

    def test_from_csv_writes_redirects_json_and_no_entity_file_for_the_merged_id(self) -> None:
        self.merges(("Q102", "Q101"))
        out = self.derive()
        self.assertEqual(json.loads((out / "redirects.json").read_text(encoding="utf-8")), {"Q102": "Q101"})
        self.assertFalse((out / "entities" / "Q102.json").exists())
        self.assertIn("merge Q102 -> Q101", self.from_csv_output)
        write(self.csv, csvbuild.MERGES, csvbuild.MERGE_COLUMNS, [])
        (self.csv / csvbuild.MERGES).unlink()
        out = self.derive()
        self.assertFalse((out / "redirects.json").exists())
        self.assertTrue((out / "entities" / "Q102.json").exists())

    def test_the_loader_knows_the_redirect_and_does_not_report_it_as_missing(self) -> None:
        self.merges(("Q102", "Q101"))
        out = self.derive()
        site = loader.load_site(self.root / "data" / "raw", out)
        self.assertEqual(site.redirects, {"Q102": "Q101"})
        self.assertFalse([p for p in site.problems if "Q102" in p], site.problems)

    def test_a_redirect_to_nothing_is_a_problem(self) -> None:
        self.merges(("Q102", "Q101"))
        out = self.derive()
        (out / "redirects.json").write_text(json.dumps({"Q102": "Q777"}), encoding="utf-8")
        site = loader.load_site(self.root / "data" / "raw", out)
        self.assertTrue(any("Q777" in p for p in site.problems), site.problems)

    def test_rdf_says_same_as_in_the_whole_file_and_in_the_file_of_the_target(self) -> None:
        self.merges(("Q102", "Q101"))
        site = loader.load_site(self.root / "data" / "raw", self.derive())
        ns = rdf.Namespaces("https://example.org")
        result = rdf.build(site, ns)
        triple = (rdf.Iri(ns.wd + "Q102"), rdf.Iri(rdf.OWL + "sameAs"), rdf.Iri(ns.wd + "Q101"))
        self.assertIn(triple, result.triples)
        self.assertIn(triple, result.by_entity["Q101"])
        self.assertNotIn("Q102", result.by_entity)

    def test_the_page_of_the_merged_id_forwards_to_the_target(self) -> None:
        self.merges(("Q102", "Q101"))
        self.derive()
        names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
        saved = {n: getattr(utils, n) for n in names}
        utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = self.root, self.root / "data" / "raw", self.root / "data" / "derived"
        utils.DOCS, utils.SITE_YAML, utils.DIST = self.root / "docs", self.root / "site.yaml", self.root / "dist"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(step_build.main([]), 0)
        finally:
            for name, value in saved.items():
                setattr(utils, name, value)
        text = (self.root / "docs" / "Q102.html").read_text(encoding="utf-8")
        self.assertIn('http-equiv="refresh" content="0; url=Q101.html"', text)
        self.assertIn('href="Q101.html"', text)
        self.assertNotIn("WARN", out.getvalue(), out.getvalue())
        self.assertIn("1 merged id(s) forward", out.getvalue())
        self.assertIn("(difference 0)", out.getvalue())


class Suggestions(unittest.TestCase):
    """``merge --suggest`` (S7i): pairs of different origin that may be the same thing."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.csv = self.root / "csv"
        self.report = self.root / "report.csv"

    def tables(self, rows: list[tuple[str, str, str, str, str]], merges: list[tuple[str, str]] = ()) -> None:
        """rows: id, kind, origin, label_en, aliases_en"""
        write(self.csv, "entities.csv", ["id", "kind", "datatype", "origin", "label_en", "aliases_en"],
              [{"id": i, "kind": k, "datatype": "string" if k == "property" else "", "origin": o, "label_en": label, "aliases_en": a}
               for i, k, o, label, a in rows])
        if merges:
            write(self.csv, csvbuild.MERGES, csvbuild.MERGE_COLUMNS, [{"from": a, "to": b, "note": ""} for a, b in merges])

    def run_suggest(self) -> tuple[int, str, list[dict[str, str]]]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = step_merge.main(["--csv", str(self.csv), "--suggest", "--report", str(self.report)])
        rows: list[dict[str, str]] = []
        if self.report.is_file():
            with self.report.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        return code, out.getvalue(), rows

    def test_names_parts_and_account_names(self) -> None:
        self.tables([
            ("Q101", "item", "open-archaeo", "florianthiery", ""), ("Q102", "item", "wikidata-stub", "Florian Thiery", ""),
            ("Q103", "item", "open-archaeo", "Allard Mees", ""), ("Q104", "item", "wikidata-stub", "Allard Wijnand Mees", "Dr. Allard Wijnand Mees FSA"),
            ("Q105", "item", "open-archaeo", "nfrerebeau", ""), ("Q106", "item", "hand", "Nicolas Frérebeau", ""),
            ("Q107", "item", "open-archaeo", "Zoë Müller", ""), ("Q108", "item", "wikidata", "ZOE MULLER", ""),
        ])
        code, out, rows = self.run_suggest()
        self.assertEqual(code, 0, out)
        found = {frozenset((r["from"], r["to"])): r["score"] for r in rows}
        self.assertEqual(found[frozenset(("Q101", "Q102"))], "3")
        self.assertEqual(found[frozenset(("Q103", "Q104"))], "2")
        self.assertEqual(found[frozenset(("Q105", "Q106"))], "1")
        self.assertEqual(found[frozenset(("Q107", "Q108"))], "3")             # accents and case do not count
        self.assertEqual([r["score"] for r in rows], ["3", "3", "2", "1"])    # best first

    def test_the_wikidata_side_stays(self) -> None:
        self.tables([("Q101", "item", "wikidata-stub", "Python", ""), ("Q102", "item", "open-archaeo", "Python", ""),
                     ("Q103", "item", "wikidata", "Python programming", "Python"), ("Q104", "item", "wikidata-stub", "Mess", "")])
        _code, _out, rows = self.run_suggest()
        commands = {r["command"] for r in rows}
        self.assertIn("merge Q102 Q103", commands)          # the seed beats the stub and the other source
        self.assertIn("merge Q101 Q103", commands)
        self.assertNotIn("merge Q103 Q102", commands)

    def test_left_out_same_origin_short_names_classes_and_merged_ones(self) -> None:
        self.tables([
            ("Q101", "item", "open-archaeo", "Anna Maier", ""), ("Q102", "item", "open-archaeo", "Anna Maier", ""),     # same origin
            ("Q103", "item", "open-archaeo", "R", ""), ("Q104", "item", "wikidata-stub", "R", ""),                      # too short
            ("Q105", "class", "starter-pack", "Software", ""), ("Q106", "item", "open-archaeo", "Software", ""),        # a class
            ("P100", "property", "starter-pack", "Software", ""),                                                       # a property
            ("Q107", "item", "open-archaeo", "Ina Roth", ""), ("Q108", "item", "wikidata-stub", "Ina Roth", ""),        # merged already
            ("Q109", "item", "open-archaeo", "Anna Maier", ""), ("Q110", "item", "open-archaeo", "Ben Maier", ""),
        ], merges=[("Q107", "Q108")])
        _code, out, rows = self.run_suggest()
        self.assertEqual(rows, [], rows)
        self.assertIn("0 pair(s)", out)

    def test_two_people_with_the_same_initial_and_surname_are_not_suggested_for_each_other(self) -> None:
        self.tables([("Q101", "item", "open-archaeo", "Allard Mees", ""), ("Q102", "item", "wikidata-stub", "Anna Mees", "")])
        _code, _out, rows = self.run_suggest()
        self.assertEqual(rows, [])

    def test_the_report_is_a_function_of_the_tables(self) -> None:
        self.tables([("Q101", "item", "open-archaeo", "Ina Roth", ""), ("Q102", "item", "wikidata-stub", "Ina Roth", "")])
        self.run_suggest()
        first = self.report.read_bytes()
        self.run_suggest()
        self.assertEqual(self.report.read_bytes(), first)
        self.assertTrue(first.startswith(b"score,reason,from,from_label,from_origin,to,to_label,to_origin,command\n"))
        self.assertTrue(first.endswith(b"merge Q101 Q102\n"))


class Verb(Case):
    def test_dry_run_writes_nothing(self) -> None:
        code, out = self.run_verb("Q102", "Q101", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("Q102 -> Q101", out)
        self.assertFalse((self.csv / csvbuild.MERGES).exists())

    def test_merge_writes_a_sorted_canonical_line_and_undo_removes_it(self) -> None:
        self.assertEqual(self.run_verb("Q103", "Q104", "--note", "same person")[0], 0)
        self.assertEqual(self.run_verb("Q102", "Q101")[0], 0)
        text = (self.csv / csvbuild.MERGES).read_text(encoding="utf-8")
        self.assertEqual(text, "from,to,note\nQ102,Q101,\nQ103,Q104,same person\n")
        code, out = self.run_verb("--list")
        self.assertEqual(code, 0)
        self.assertIn("Q102 -> Q101", out)
        self.assertEqual(self.run_verb("--undo", "Q102")[0], 0)
        self.assertEqual((self.csv / csvbuild.MERGES).read_text(encoding="utf-8"), "from,to,note\nQ103,Q104,same person\n")
        self.assertEqual(self.run_verb("--undo", "Q103")[0], 0)
        self.assertFalse((self.csv / csvbuild.MERGES).exists())
        self.assertEqual(self.run_verb("--undo", "Q103")[0], 1)

    def test_a_merge_that_would_be_a_problem_is_refused_and_nothing_is_written(self) -> None:
        self.assertEqual(self.run_verb("Q102", "Q101")[0], 0)
        before = (self.csv / csvbuild.MERGES).read_bytes()
        for args in (("Q101", "Q104"), ("Q102", "Q104"), ("Q101", "Q101"), ("Q102", "Q999"), ("Q105", "Q101")):
            code, out = self.run_verb(*args)
            self.assertEqual(code, 1, (args, out))
            self.assertIn("ERROR", out)
        self.assertEqual((self.csv / csvbuild.MERGES).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
