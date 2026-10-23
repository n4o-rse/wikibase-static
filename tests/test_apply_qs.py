"""Tests for ``apply-qs`` (S7e): a QuickStatements file changes the CSV tables.

    python tests/test_apply_qs.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import csvbuild, csvio, step_apply_qs, step_merge  # noqa: E402

ENTITIES = [
    ("Q100", "class", "", "Software"), ("Q101", "item", "", "Alligator"), ("Q102", "item", "", "Other"),
    ("P100", "property", "string", "inventory"), ("P101", "property", "wikibase-item", "used by"),
    ("P102", "property", "url", "page"), ("P103", "property", "time", "date"), ("P104", "property", "monolingualtext", "motto"),
    ("P105", "property", "globe-coordinate", "place"), ("P106", "property", "quantity", "size"),
    ("P107", "property", "external-id", "account"),
]
STATEMENTS = [("Q100", "P1", "Q3", ""), ("Q101", "P2", "Q100", ""), ("Q101", "P100", "old", "a1"), ("Q102", "P2", "Q100", "")]
TAB = "\t"


def qs(*lines: str) -> str:
    return "\n".join(line.replace(" | ", TAB) for line in lines) + "\n"


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.csv = self.root / "data" / "csv"
        self.csv.mkdir(parents=True)
        self.applied = self.root / "data" / "edits" / "applied.csv"
        self.write("entities.csv", ["id", "kind", "datatype", "origin", "label_en", "aliases_en"],
                   [{"id": i, "kind": k, "datatype": d, "label_en": label} for i, k, d, label in ENTITIES])
        self.write("statements.csv", ["sid", "subject", "property", "value", "rank", "origin"],
                   [{"subject": s, "property": p, "value": v, "sid": sid, "origin": "open-archaeo" if sid == "a1" else ""} for s, p, v, sid in STATEMENTS])
        self.write("qualifiers.csv", ["sid", "property", "value"], [])
        self.write("references.csv", ["sid", "group", "property", "value"], [])
        self.normalise()

    def write(self, name: str, columns: list[str], rows: list[dict[str, str]]) -> None:
        (self.csv / name).write_text(csvio.render_table(columns, rows), encoding="utf-8", newline="")

    def normalise(self) -> None:
        """Bring the fixture to canonical form, so that a later difference comes from apply-qs alone."""
        problems: list[str] = []
        site = csvbuild.read_set(self.csv, problems, "csv")
        tables = {t.name.split("/")[-1]: t for t in site.tables}
        for name, text in csvio.canonical_texts(tables).items():
            (self.csv / name).write_text(text, encoding="utf-8", newline="")

    def file(self, text: str, name: str = "change.qs") -> Path:
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def run_qs(self, text: str, *args: str, name: str = "change.qs") -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = step_apply_qs.main([str(self.file(text, name)), "--csv", str(self.csv), "--applied", str(self.applied), *args])
        return code, out.getvalue()

    def tables(self) -> dict[str, str]:
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(self.csv.glob("*.csv")) if p.name != "idmap.csv"}

    def rows(self, name: str) -> list[dict[str, str]]:
        return csvio.read_table(self.csv / name, [], [], name).rows

    def statements(self, subject: str) -> list[tuple[str, str]]:
        return [(r["property"], r["value"]) for r in self.rows("statements.csv") if r["subject"] == subject]

    def built(self):
        problems: list[str] = []
        site = csvbuild.read_set(self.csv, problems, "csv")
        return csvbuild.build(site, csvbuild.kernel_set(), None)


class Parsing(unittest.TestCase):
    def test_values(self) -> None:
        for token, expected in [('"a b"', ("a b", "string")), ('"?"', ("\\?", "string")), ("Q12", ("Q12", "entity")),
                                ("wd:Q42", ("wd:Q42", "entity")), ('de:"Hallo"', ("de:Hallo", "monolingual")),
                                ("+2021-06-04T00:00:00Z/11", ("+2021-06-04T00:00:00Z/11", "time")), ("@52.5/13.4", ("52.5,13.4", "coordinate")),
                                ("12", ("12", "quantity")), ("12Uwd:Q11573", ("12 wd:Q11573", "quantity")),
                                ("somevalue", ("?", "any")), ("novalue", ("-", "any"))]:
            self.assertEqual(step_apply_qs.translate(token), expected, token)

    def test_quoted_quotes(self) -> None:
        self.assertEqual(step_apply_qs.translate('"say \\"hi\\""')[0], 'say "hi"')

    def test_comments_blank_lines_and_pipes(self) -> None:
        commands, errors, warnings = step_apply_qs.parse("# note\n\nCREATE\nMERGE|Q1|Q2\n")
        self.assertEqual([c.kind for c in commands], ["create", "merge"])
        self.assertEqual((errors, warnings), ([], []))

    def test_reference_pairs_are_split_from_qualifiers(self) -> None:
        (command,), errors, _w = step_apply_qs.parse(qs('Q1 | P100 | "x" | P102 | "https://a.org" | S102 | "https://b.org"'))
        self.assertEqual(errors, [])
        self.assertEqual([p for p, _v, _s in command.pairs], ["P102"])
        self.assertEqual([p for p, _v, _s in command.references], ["P102"])

    def test_spaces_instead_of_tabs_are_named(self) -> None:
        _c, errors, _w = step_apply_qs.parse("Q1 P100 \"x\"\n")
        self.assertIn("separated by tabs", errors[0])

    def test_unsupported_commands_warn_with_line_number(self) -> None:
        commands, errors, warnings = step_apply_qs.parse(qs("CREATE_PROPERTY", "Q1 | Sdewiki | \"Foo\"", "-Q1 | Len | \"x\""))
        self.assertEqual(errors, [])
        self.assertEqual([w.split(":")[0] for w in warnings], ["line 1", "line 2", "line 3"])
        self.assertEqual([c.kind for c in commands], ["lost"])


class Applying(Case):
    def test_create_with_everything(self) -> None:
        code, out = self.run_qs(qs(
            "CREATE", 'LAST | Len | "New tool"', 'LAST | Dde | "ein Werkzeug"', 'LAST | Aen | "NT"', "LAST | P2 | Q100",
            'LAST | P100 | "nt-1" | P102 | "https://example.org/q" | S102 | "https://example.org/ref"',
            "LAST | P101 | wd:Q42", "LAST | P103 | +2021-06-04T00:00:00Z/11", 'LAST | P104 | de:"Moin"',
            "LAST | P105 | @52.5/13.4", "LAST | P106 | 12", 'LAST | P107 | "x?"'))
        self.assertEqual(code, 0, out)
        self.assertIn("CREATE -> Q103", out)
        new = next(r for r in self.rows("entities.csv") if r.get("label_en") == "New tool")
        self.assertEqual((new["id"], new["kind"], new["origin"], new["description_de"], new["aliases_en"]), ("Q103", "item", "", "ein Werkzeug", "NT"))
        found = dict(self.statements("Q103"))
        self.assertEqual((found["P103"], found["P104"], found["P105"], found["P106"]), ("2021-06-04", "de:Moin", "52.5,13.4", "12"))
        self.assertEqual(found["P107"], "x?")
        sid = next(r["sid"] for r in self.rows("statements.csv") if r["subject"] == "Q103" and r["property"] == "P100")
        self.assertEqual([(r["property"], r["value"]) for r in self.rows("qualifiers.csv") if r["sid"] == sid], [("P102", "https://example.org/q")])
        self.assertEqual([(r["group"], r["property"], r["value"]) for r in self.rows("references.csv") if r["sid"] == sid],
                         [("1", "P102", "https://example.org/ref")])
        built = self.built()
        self.assertEqual(built.problems, [])
        self.assertIn("Q103", built.entities)

    def test_second_application_does_nothing(self) -> None:
        text = qs("CREATE", 'LAST | Len | "New"', "LAST | P2 | Q100")
        self.assertEqual(self.run_qs(text)[0], 0)
        after = self.tables()
        applied = self.applied.read_text(encoding="utf-8")
        code, out = self.run_qs(text)
        self.assertEqual(code, 0)
        self.assertIn("applied already", out)
        self.assertEqual((self.tables(), self.applied.read_text(encoding="utf-8")), (after, applied))
        again, _o = self.run_qs(text.replace("\n", "\r\n"), name="other-name.qs")      # line ends and the name do not matter
        self.assertEqual((again, self.tables()), (0, after))
        self.assertEqual(len(self.rows("entities.csv")), len(ENTITIES) + 1)

    def test_applied_csv_has_hash_file_and_changes(self) -> None:
        self.run_qs(qs('Q101 | P100 | "new"'))
        (row,) = csvio.read_table(self.applied, [], [], "applied.csv").rows
        self.assertEqual(len(row["sha256"]), 64)
        self.assertEqual(row["file"], "change.qs")
        self.assertEqual(row["changes"], "1 statement(s) added")

    def test_identical_statement_is_not_doubled(self) -> None:
        before = self.statements("Q101")
        code, out = self.run_qs(qs("Q101 | P2 | Q100", 'Q101 | P100 | "old"'))
        self.assertEqual((code, self.statements("Q101")), (0, before))
        self.assertIn("2 already there", out)

    def test_other_value_or_other_qualifiers_are_added(self) -> None:
        self.run_qs(qs('Q101 | P100 | "old" | P102 | "https://example.org/x"', 'Q101 | P100 | "second"'))
        self.assertEqual([v for p, v in self.statements("Q101") if p == "P100"], ["old", "old", "second"])

    def test_remove_takes_exactly_one_statement_and_its_qualifiers(self) -> None:
        self.run_qs(qs('Q101 | P100 | "old" | P102 | "https://example.org/x"'), name="a.qs")
        self.run_qs(qs('Q101 | P100 | "old" | P102 | "https://example.org/y"'), name="b.qs")
        self.assertEqual(len([1 for p, v in self.statements("Q101") if (p, v) == ("P100", "old")]), 3)
        code, out = self.run_qs(qs('-Q101 | P100 | "old"'), name="c.qs")
        self.assertEqual(code, 0, out)
        self.assertEqual(len([1 for p, v in self.statements("Q101") if (p, v) == ("P100", "old")]), 2)
        self.assertIn("importer 'open-archaeo'", out)           # the first match was the importer's row
        self.assertEqual(len(self.rows("qualifiers.csv")), 2)

    def test_remove_of_a_missing_statement_refuses_the_file(self) -> None:
        before = self.tables()
        code, out = self.run_qs(qs('Q101 | P100 | "added"', '-Q101 | P100 | "nothing"'))
        self.assertEqual(code, 1)
        self.assertIn("line 2: Q101 has no statement P100", out)
        self.assertEqual(self.tables(), before)
        self.assertFalse(self.applied.exists())

    def test_invalid_lines_change_nothing_and_all_are_named(self) -> None:
        before = self.tables()
        code, out = self.run_qs(qs("CREATE", 'LAST | Len | "Fine"', "Q101 | P999 | Q100", "Q101 | P101 | Q555", 'Q101 | P103 | "2021"',
                                   'Q101 | P102 | Q100', "Q555 | P2 | Q100", "P100 | P2 | Q100", "Q101 | P106 | 1x", "Q101 | P2 | Q100 | P100"))
        self.assertEqual(code, 1)
        for number in (3, 4, 5, 6, 7, 8, 9, 10):
            self.assertIn(f"line {number}:", out)
        self.assertEqual(self.tables(), before)
        self.assertFalse(self.applied.exists())

    def test_last_before_create_and_after_unsupported_create(self) -> None:
        code, out = self.run_qs(qs('LAST | Len | "x"'))
        self.assertEqual((code, "line 1: LAST is used before any CREATE" in out), (1, True))
        code, out = self.run_qs(qs("CREATE_PROPERTY", 'LAST | Len | "x"', 'Q101 | Aen | "ok"'), name="b.qs")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN: [apply-qs]", out)
        self.assertIn("line 1: CREATE_PROPERTY", out)
        self.assertIn("line 2: LAST refers to an item that was not created", out)

    def test_unsupported_lines_warn_and_the_rest_is_applied(self) -> None:
        code, out = self.run_qs(qs('Q101 | Sdewiki | "Alligator"', 'Q101 | P100 | "kept"'))
        self.assertEqual(code, 0)
        self.assertIn("WARN: [apply-qs] change.qs: line 1: sitelink Sdewiki", out)
        self.assertIn(("P100", "kept"), self.statements("Q101"))

    def test_kernel_property_and_wikidata_property_work_and_type_is_checked(self) -> None:
        self.assertEqual(self.run_qs(qs("Q102 | wd:P31 | wd:Q5", "Q102 | wd:P856 | \"https://example.org\""))[0], 0)
        self.assertIn(("wd:P31", "wd:Q5"), self.statements("Q102"))
        code, out = self.run_qs(qs("Q102 | P100 | Q100"), name="b.qs")
        self.assertEqual(code, 1)
        self.assertIn("takes string, but the value is written as entity", out)

    def test_the_shape_of_the_pack_example_alligator(self) -> None:
        """``examples/alligator.qs`` of the Starter Pack, with its properties turned into the ones of this fixture:
        the same commands, the same kinds of value (label, description, item, wd: item, URL, URL with a qualifier,
        time qualifier, item with an ordinal qualifier), the comments in between."""
        code, out = self.run_qs(qs(
            "# QuickStatements v1 (tab-separated) -- ILLUSTRATIVE, untested.", "CREATE",
            'LAST | Len | "Alligator"', 'LAST | Den | "chublet: statistical analysis and ontology tool"',
            "LAST | P2 | Q100", "LAST | P101 | wd:Q141115774", "LAST | P101 | wd:Q141190255",
            'LAST | P100 | "alligator" | P101 | wd:Q141190255',
            'LAST | P102 | "https://open-archaeo.info/post/alligator/"',
            'LAST | P102 | "https://github.com/leiza-rse/alligator" | P101 | wd:Q186055',
            "# archive URL and date", 'LAST | P102 | "https://archive.org/details/x" | P103 | +2021-06-04T00:00:00Z/11',
            'LAST | P101 | wd:Q66606154 | P100 | "1"', 'LAST | P101 | wd:Q88865971 | P100 | "2"'))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.statements("Q103"), [
            ("P2", "Q100"), ("P100", "alligator"), ("P101", "wd:Q141115774"), ("P101", "wd:Q141190255"), ("P101", "wd:Q66606154"),
            ("P101", "wd:Q88865971"), ("P102", "https://open-archaeo.info/post/alligator/"), ("P102", "https://github.com/leiza-rse/alligator"),
            ("P102", "https://archive.org/details/x")])
        qualifiers = sorted((r["property"], r["value"]) for r in self.rows("qualifiers.csv"))
        self.assertEqual(qualifiers, [("P100", "1"), ("P100", "2"), ("P101", "wd:Q141190255"), ("P101", "wd:Q186055"), ("P103", "2021-06-04")])
        self.assertEqual(self.built().problems, [])
        self.assertEqual(self.run_qs(qs("CREATE"), name="x.qs")[0], 1)       # an item without instance of is refused

    def test_labels_descriptions_and_aliases(self) -> None:
        code, out = self.run_qs(qs('Q102 | Len | "Renamed"', 'Q102 | Dfr | "décrit"', 'Q102 | Aen | "A"', 'Q102 | Aen | "B|C"', 'Q102 | Aen | "A"'))
        self.assertEqual(code, 0, out)
        row = next(r for r in self.rows("entities.csv") if r["id"] == "Q102")
        self.assertEqual((row["label_en"], row["description_fr"], csvio.split_aliases(row["aliases_en"])), ("Renamed", "décrit", ["A", "B|C"]))
        self.run_qs(qs('-Q102 | Aen | "A"'), name="b.qs")
        row = next(r for r in self.rows("entities.csv") if r["id"] == "Q102")
        self.assertEqual(csvio.split_aliases(row["aliases_en"]), ["B|C"])
        code, out = self.run_qs(qs('-Q102 | Aen | "zzz"'), name="c.qs")
        self.assertEqual(code, 1)

    def test_merge_writes_a_line_in_merges_csv(self) -> None:
        code, out = self.run_qs(qs("MERGE | Q102 | Q101"))
        self.assertEqual(code, 0, out)
        rows = step_merge.read_lines(self.csv / csvbuild.MERGES, [])
        self.assertEqual([(r["from"], r["to"]) for r in rows], [("Q102", "Q101")])
        self.assertEqual(self.built().redirects, {"Q102": "Q101"})
        code, out = self.run_qs(qs('Q102 | Aen | "late"'), name="b.qs")
        self.assertEqual(code, 1)
        self.assertIn("merged into Q101", out)

    def test_bad_merge_changes_nothing(self) -> None:
        self.run_qs(qs("MERGE | Q102 | Q101"), name="a.qs")
        before = self.tables()
        code, out = self.run_qs(qs("MERGE | Q101 | Q102"), name="b.qs")           # a chain: the target is merged away already
        self.assertEqual(code, 1, out)
        self.assertEqual(self.tables(), before)

    def test_created_ids_follow_the_highest_used(self) -> None:
        (self.csv / "idmap.csv").write_text("source,key,id\nopen-archaeo,x,Q150\n", encoding="utf-8")
        self.run_qs(qs("CREATE", "LAST | P2 | Q100", "CREATE", "LAST | P2 | Q100"))
        ids = [r["id"] for r in self.rows("entities.csv") if r["id"].startswith("Q")]
        self.assertIn("Q151", ids)
        self.assertIn("Q152", ids)

    def test_dry_run_writes_nothing(self) -> None:
        before = self.tables()
        code, out = self.run_qs(qs("CREATE", 'LAST | Len | "x"', "LAST | P2 | Q100"), "--dry-run")
        self.assertEqual((code, self.tables()), (0, before))
        self.assertIn("would change", out)
        self.assertFalse(self.applied.exists())
        self.assertEqual(self.run_qs(qs("CREATE", 'LAST | Len | "x"', "LAST | P2 | Q100"))[0], 0)     # a dry run does not count as applied

    def test_canonical_form_is_kept(self) -> None:
        self.run_qs(qs('Q101 | P100 | "z"', 'Q102 | P100 | "y"', 'Q101 | P103 | +2021-06-04T00:00:00Z/11'))
        problems: list[str] = []
        site = csvbuild.read_set(self.csv, problems, "csv")
        tables = {t.name.split("/")[-1]: t for t in site.tables}
        self.assertEqual({n: (self.csv / n).read_text(encoding="utf-8") for n in tables}, csvio.canonical_texts(tables))
        self.assertEqual([v for p, v in self.statements("Q101") if p in ("P100", "P103")], ["old", "z", "2021-06-04"])


class Verb(unittest.TestCase):
    def test_main_knows_the_verb(self) -> None:
        sys.path.insert(0, str(HERE.parent))
        import main
        self.assertIn("apply-qs", main.NAMES)
        self.assertFalse(next(s for s in main.STEPS if s[0] == "apply-qs")[2])


if __name__ == "__main__":
    unittest.main()
