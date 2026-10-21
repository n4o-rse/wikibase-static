"""Tests for the CSV format, the kernel, ``from-csv``, ``to-csv`` and ``csv-fmt`` (S7a).

    python tests/test_csv.py

Standard library only (the steps themselves need nothing else either).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "py"))

from wikibase_static import csvbuild, csvio, loader, step_csv_fmt, step_from_csv, step_to_csv, utils  # noqa: E402
from wikibase_static.csvio import CsvError  # noqa: E402
from wikibase_static.model import Snak, federated_from_uri, is_federated  # noqa: E402

FIXTURES = HERE / "fixtures"
DROP = {"hash", "lastrevid", "modified", "pageid", "ns", "title"}


def normalise(obj):
    """Wikibase JSON without what a CSV cannot hold (hashes, revision ids) and without statement ids."""
    if isinstance(obj, dict):
        return {k: normalise(v) for k, v in obj.items() if k not in DROP}
    if isinstance(obj, list):
        return [normalise(v) for v in obj]
    return obj


def without_statement_ids(entity: dict) -> dict:
    entity = normalise(entity)
    for claims in entity.get("claims", {}).values():
        for claim in claims:
            claim.pop("id", None)
    return entity


def write(folder: Path, name: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8", newline="")


def run_step(module, *args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = module.main(list(args))
    return code, out.getvalue()


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.csv = self.base / "csv"
        self.out = self.base / "derived"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build(self, kernel: bool = True) -> csvbuild.Built:
        problems: list[str] = []
        site = csvbuild.read_set(self.csv, problems, "csv")
        built = csvbuild.build(site, csvbuild.kernel_set() if kernel else None, "https://example.org")
        built.problems = sorted(set(problems) | set(built.problems))
        return built


# --------------------------------------------------------------------------- the value codec


class CodecTests(unittest.TestCase):
    def parse(self, text: str, datatype: str):
        return csvio.parse_value(text, datatype, "https://example.org")

    def test_every_value_form_reads_and_writes_back_to_the_same_text(self) -> None:
        cases = [
            ("wikibase-item", "Q12"), ("wikibase-item", "wd:Q42"), ("wikibase-property", "P3"), ("wikibase-property", "wd:P31"),
            ("string", "plain text"), ("string", "\\?"), ("string", "\\-"), ("string", "\\\\back"),
            ("url", "https://example.org/a?b=c"), ("external-id", "0000-0002-1825-0097"), ("commonsMedia", "Example.jpg"),
            ("time", "2021"), ("time", "2021-06"), ("time", "2021-06-04"), ("time", "-0500"),
            ("time", "+2021-06-04T00:00:00Z/8"),
            ("quantity", "12"), ("quantity", "-3.5"), ("quantity", "12 Q5"), ("quantity", "7 wd:Q11573"),
            ("quantity", "7 https://example.org/unit/metre"),
            ("monolingualtext", "de:Hallo Welt"), ("monolingualtext", "en:a: b"),
            ("globe-coordinate", "51.5,-0.09"), ("globe-coordinate", "51.5,-0.09,2.7e-06"),
            ("globe-coordinate", "0,0"), ("globe-coordinate", "51.5,-0.09,0.0001,wd:Q405"),
        ]
        for datatype, text in cases:
            with self.subTest(datatype=datatype, text=text):
                snaktype, datavalue, kept = self.parse(text, datatype)
                self.assertEqual((snaktype, kept), ("value", datatype))
                snak = Snak(property="P1", snaktype=snaktype, datatype=kept, vtype=datavalue["type"], value=datavalue["value"])
                if datatype in ("wikibase-item", "wikibase-property") and not is_federated(text):
                    snak = Snak("P1", "value", kept, "wikibase-entityid", datavalue["value"])
                self.assertEqual(csvio.format_snak(snak, "https://example.org"), text)

    def test_unknown_and_no_value(self) -> None:
        self.assertEqual(self.parse("?", "string")[0], "somevalue")
        self.assertEqual(self.parse("-", "time")[0], "novalue")
        self.assertEqual(csvio.format_snak(Snak("P1", "somevalue"), None), "?")
        self.assertEqual(csvio.format_snak(Snak("P1", "novalue"), None), "-")

    def test_time_precision_follows_the_length_of_the_date(self) -> None:
        precisions = {text: csvio.parse_time(text)["precision"] for text in ("2021", "2021-06", "2021-06-04")}
        self.assertEqual(precisions, {"2021": 9, "2021-06": 10, "2021-06-04": 11})
        self.assertEqual(csvio.parse_time("-0500")["time"], "-0500-00-00T00:00:00Z")

    def test_a_time_the_short_form_would_change_keeps_the_long_form(self) -> None:
        value = csvio.parse_time("2021-06-04")
        value["timezone"] = 60
        self.assertEqual(csvio.format_time(value), "+2021-06-04T00:00:00Z/11")

    def test_coordinate_default_precision_is_left_out_and_globe_is_kept(self) -> None:
        self.assertEqual(csvio.format_coordinate(csvio.parse_coordinate("1,2,1e-06")), "1,2")
        self.assertEqual(csvio.parse_coordinate("1,2")["precision"], csvio.DEFAULT_PRECISION)
        self.assertEqual(csvio.parse_coordinate("1,2")["globe"], csvio.EARTH)

    def test_unit_one_is_the_default_and_a_local_unit_needs_a_base(self) -> None:
        self.assertEqual(csvio.parse_quantity("5", None), {"amount": "+5", "unit": "1"})
        self.assertEqual(csvio.parse_quantity("5 Q9", "https://example.org/")["unit"], "https://example.org/entity/Q9")
        with self.assertRaises(CsvError):
            csvio.parse_quantity("5 Q9", None)

    def test_bad_values_say_what_is_wrong(self) -> None:
        bad = [("time", "2021-13-01"), ("time", "June 2021"), ("time", "2021-06-00"), ("quantity", "1e3"), ("quantity", "twelve"),
               ("quantity", "5 metres"), ("monolingualtext", "no language"), ("monolingualtext", "de:"),
               ("globe-coordinate", "91,0"), ("globe-coordinate", "1"), ("globe-coordinate", "1,x"),
               ("wikibase-item", "P3"), ("wikibase-property", "Q3"), ("wikibase-item", "banana"), ("wikibase-item", "Q0")]
        for datatype, text in bad:
            with self.subTest(datatype=datatype, text=text), self.assertRaises(CsvError):
                self.parse(text, datatype)

    def test_a_wikidata_property_has_its_datatype_read_from_the_value(self) -> None:
        self.assertEqual(csvio.parse_value("wd:Q7397", None)[2], "wikibase-item")
        self.assertEqual(csvio.parse_value("wd:P31", None)[2], "wikibase-property")
        self.assertEqual(csvio.parse_value("https://example.org", None)[2], "url")
        self.assertEqual(csvio.parse_value("some text", None)[2], "string")

    def test_aliases_with_a_bar_survive(self) -> None:
        values = ["a|b", "c\\d", "plain"]
        self.assertEqual(csvio.split_aliases(csvio.join_aliases(values)), values)
        self.assertEqual(csvio.split_aliases(""), [])

    def test_uri_and_short_form_of_a_wikidata_entity(self) -> None:
        self.assertEqual(federated_from_uri("http://www.wikidata.org/entity/Q42"), "wd:Q42")
        self.assertEqual(federated_from_uri("https://www.wikidata.org/entity/P31"), "wd:P31")
        self.assertIsNone(federated_from_uri("https://example.org/entity/Q42"))
        self.assertIsNone(federated_from_uri("Q42"))


# --------------------------------------------------------------------------- tables and the canonical form


class TableTests(Workspace):
    def test_files_with_bom_and_crlf_are_read(self) -> None:
        (self.csv).mkdir()
        (self.csv / "entities.csv").write_bytes("﻿id,kind,label_en\r\nQ100,class,Eine\r\n".encode("utf-8"))
        problems: list[str] = []
        table = csvio.read_table(self.csv / "entities.csv", ["id"], problems)
        self.assertEqual(problems, [])
        self.assertEqual(table.rows, [{"id": "Q100", "kind": "class", "label_en": "Eine"}])

    def test_a_missing_column_is_reported_with_the_file_and_the_file_is_skipped(self) -> None:
        write(self.csv, "statements.csv", "subject,property\nQ100,P1\n")
        problems: list[str] = []
        table = csvio.read_table(self.csv / "statements.csv", csvio.REQUIRED["statements.csv"], problems, "statements.csv")
        self.assertEqual(table.rows, [])
        self.assertIn("statements.csv:1: missing column(s) value; file skipped", problems)

    def test_canonical_form_orders_columns_rows_and_quotes_only_where_needed(self) -> None:
        write(self.csv, "entities.csv",
              "label_fr,aliases_en,id,description_de,label_de,label_en,kind,note\r\n"
              'fr,"a|b",P100,,,,property,keep me\r\n'
              ',,Q101,,Zwei,Two,item,\r\n'
              ',,Q9,,Neun,"Nine, nearly",item,\r\n')
        code, out = run_step(step_csv_fmt, "--csv", str(self.csv))
        self.assertEqual(code, 0, out)
        text = (self.csv / "entities.csv").read_bytes().decode("utf-8")
        self.assertNotIn("\r", text)
        self.assertEqual(text.splitlines()[0],
                         "id,kind,datatype,origin,label_en,label_de,label_fr,description_de,aliases_en,note")
        self.assertEqual([line.split(",")[0] for line in text.splitlines()[1:]], ["Q9", "Q101", "P100"])
        self.assertIn('"Nine, nearly"', text)
        self.assertIn("a|b", text)                                   # no quotes where none are needed
        self.assertNotIn('"a|b"', text)

    def test_statements_stay_in_their_order_within_a_property_and_qualifiers_follow_their_statements(self) -> None:
        write(self.csv, "entities.csv", "id,kind\nQ100,class\nP100,property\n")
        write(self.csv, "statements.csv",
              "sid,subject,property,value\n"
              "b,Q100,P100,second\n,Q100,P100,third\na,Q100,P100,first\n")
        # the file order inside P100 is meaningful and must not change; only subject and property are sorted
        write(self.csv, "qualifiers.csv", "sid,property,value\na,P100,qa\nb,P100,qb\nb,P100,qb2\n")
        run_step(step_csv_fmt, "--csv", str(self.csv))
        rows = (self.csv / "statements.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual([r.split(",")[3] for r in rows[1:]], ["second", "third", "first"])
        qualifiers = (self.csv / "qualifiers.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual([r.split(",")[2] for r in qualifiers[1:]], ["qb", "qb2", "qa"])

    def test_running_csv_fmt_twice_changes_nothing_and_check_agrees(self) -> None:
        write(self.csv, "entities.csv", "label_en,id\nThing,Q100\n")
        self.assertEqual(run_step(step_csv_fmt, "--check", "--csv", str(self.csv))[0], 1)
        run_step(step_csv_fmt, "--csv", str(self.csv))
        first = (self.csv / "entities.csv").read_bytes()
        code, out = run_step(step_csv_fmt, "--csv", str(self.csv))
        self.assertIn("0 of 1 file(s) rewritten", out)
        self.assertEqual((self.csv / "entities.csv").read_bytes(), first)
        self.assertEqual(run_step(step_csv_fmt, "--check", "--csv", str(self.csv))[0], 0)

    def test_the_kernel_files_are_canonical(self) -> None:
        code, out = run_step(step_csv_fmt, "--check", "--csv", str(csvbuild.KERNEL_DIR))
        self.assertEqual(code, 0, out)

    def test_a_file_that_cannot_be_read_is_never_rewritten(self) -> None:
        write(self.csv, "statements.csv", "subject,property\nQ100,P1\n")
        before = (self.csv / "statements.csv").read_bytes()
        code, out = run_step(step_csv_fmt, "--csv", str(self.csv))
        self.assertEqual(code, 2)
        self.assertEqual((self.csv / "statements.csv").read_bytes(), before)


# --------------------------------------------------------------------------- the kernel


class KernelTests(Workspace):
    def test_the_kernel_is_complete_and_makes_a_site_without_problems(self) -> None:
        built = self.build()
        self.assertEqual(built.problems, [])
        self.assertEqual(sorted(built.entities, key=csvbuild.id_sort_key),
                         ["Q1", "Q2", "Q3"] + [f"P{n}" for n in range(1, 11)])
        for entity_id, (kind, datatype) in csvbuild.KERNEL.items():
            entity = built.entities[entity_id]
            self.assertEqual(entity.get("datatype"), datatype, entity_id)
            self.assertTrue(entity["labels"]["en"]["value"] and entity["labels"]["de"]["value"], entity_id)

    def test_the_kernel_gives_wikidata_equivalent_its_formatter_url(self) -> None:
        built = self.build()
        claims = built.entities["P4"]["claims"]["P5"]
        self.assertEqual([c["mainsnak"]["datavalue"]["value"] for c in claims], ["https://www.wikidata.org/entity/$1"])

    def test_classes_are_typed_as_classes_and_properties_as_properties(self) -> None:
        write(self.csv, "entities.csv", "id,kind,datatype,label_en\nQ100,class,,Thing\nP100,property,string,note\n")
        write(self.csv, "statements.csv", "subject,property,value\nQ100,P1,Q3\n")
        built = self.build()
        self.assertEqual(built.problems, [])

        def instance_of(entity_id: str) -> list[str]:
            return [c["mainsnak"]["datavalue"]["value"]["id"] for c in built.entities[entity_id]["claims"]["P2"]]

        self.assertEqual(instance_of("Q100"), ["Q1"])
        self.assertEqual(instance_of("P100"), ["Q2"])
        self.assertEqual(instance_of("Q3"), ["Q1"])             # the kernel is typed the same way

    def test_a_site_may_add_translations_descriptions_and_aliases_to_a_kernel_entity(self) -> None:
        write(self.csv, "entities.csv", "id,kind,label_en,label_fr,description_fr,aliases_en\nQ1,class,Class,Classe,Un ensemble,type|kind\n")
        built = self.build()
        self.assertEqual(built.problems, [])
        entity = built.entities["Q1"]
        self.assertEqual(entity["labels"]["fr"]["value"], "Classe")
        self.assertEqual(entity["descriptions"]["fr"]["value"], "Un ensemble")
        self.assertEqual([a["value"] for a in entity["aliases"]["en"]], ["type", "kind"])
        self.assertEqual(entity["labels"]["en"]["value"], "Class")

    def test_changing_the_kernel_is_a_warning_and_has_no_effect(self) -> None:
        write(self.csv, "entities.csv", "id,kind,datatype,label_en\nQ1,class,,Category\nP1,property,string,sub\n")
        write(self.csv, "statements.csv", "subject,property,value\nQ1,P1,Q2\n")
        built = self.build()
        self.assertEqual(built.entities["Q1"]["labels"]["en"]["value"], "Class")
        self.assertEqual(built.entities["P1"]["datatype"], "wikibase-item")
        text = "\n".join(built.problems)
        self.assertIn("csv/entities.csv:2: Q1 is part of the kernel; its label_en cannot be changed", text)
        self.assertIn("csv/entities.csv:3: P1 is part of the kernel; its kind and datatype cannot be changed", text)
        self.assertIn("csv/statements.csv:2: Q1 is part of the kernel; statements on it cannot be added", text)

    def test_ids_below_100_are_reserved(self) -> None:
        write(self.csv, "entities.csv", "id,kind,label_en\nQ50,item,Early\nQ100,class,Fine\n")
        built = self.build()
        self.assertIn("csv/entities.csv:2: Q50 lies in the range 1 to 99, which is reserved for the kernel", built.problems)
        self.assertEqual(len([p for p in built.problems if "reserved" in p]), 1)

    def test_an_incomplete_kernel_is_reported(self) -> None:
        problems: list[str] = []
        site = csvbuild.read_set(self.csv, problems, "csv")
        kernel = csvbuild.kernel_set()
        kernel.entities.rows = [r for r in kernel.entities.rows if r["id"] != "P4"]
        kernel.entities.rows = [dict(r, datatype="string") if r["id"] == "P5" else r for r in kernel.entities.rows]
        kernel.entities.rows = [dict(r, datatype="string") if r["id"] == "P6" else r for r in kernel.entities.rows]
        built = csvbuild.build(site, kernel)
        text = "\n".join(built.problems)
        self.assertIn("kernel: P4 is missing or changed", text)
        self.assertNotIn("kernel: P5", text)        # P5 is a string property in the kernel as well, so it is unchanged
        self.assertIn("kernel: P6 is missing or changed", text)

    def test_without_the_kernel_the_model_rules_are_silent(self) -> None:
        write(self.csv, "entities.csv", "id,kind,label_en\nQ1,item,A thing\n")
        built = self.build(kernel=False)
        self.assertEqual(built.problems, [])
        self.assertEqual(sorted(built.entities), ["Q1"])


# --------------------------------------------------------------------------- the warnings of the validator


class ValidationTests(Workspace):
    def problems(self, entities: str, statements: str = "", qualifiers: str = "", references: str = "") -> list[str]:
        write(self.csv, "entities.csv", entities)
        if statements:
            write(self.csv, "statements.csv", statements)
        if qualifiers:
            write(self.csv, "qualifiers.csv", qualifiers)
        if references:
            write(self.csv, "references.csv", references)
        return self.build().problems

    BASE = "id,kind,datatype,label_en\nQ100,class,,Thing\nQ101,item,,An item\nP100,property,string,note\nP101,property,time,date\n"

    def test_class_without_a_path_to_the_root(self) -> None:
        found = self.problems(self.BASE)
        self.assertIn("csv/entities.csv:2: class Q100 has no path to Q3 (Instance) over P1 (subclass of)", found)

    def test_a_class_with_a_path_has_no_problem(self) -> None:
        found = self.problems(self.BASE, "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\n")
        self.assertEqual(found, [])

    def test_a_long_path_through_several_classes_is_found(self) -> None:
        entities = "id,kind\nQ100,class\nQ101,class\nQ102,class\n"
        found = self.problems(entities, "subject,property,value\nQ100,P1,Q101\nQ101,P1,Q102\nQ102,P1,Q3\n")
        self.assertEqual(found, [])

    def test_item_without_a_class(self) -> None:
        found = self.problems(self.BASE, "subject,property,value\nQ100,P1,Q3\n")
        self.assertIn("csv/entities.csv:3: item Q101 is not an instance of a class (P2)", found)

    def test_item_that_is_an_instance_of_something_that_is_not_a_class(self) -> None:
        entities = self.BASE + "Q102,item,,Other\n"
        found = self.problems(entities, "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nQ102,P2,Q101\n")
        self.assertIn("csv/entities.csv:6: item Q102 is an instance of Q101, which is not a class", found)

    def test_a_wikidata_stub_needs_no_class_and_a_wikidata_class_is_accepted(self) -> None:
        entities = "id,kind,origin\nQ100,item,wikidata-stub\nQ101,item,\n"
        found = self.problems(entities, "subject,property,value\nQ101,P2,wd:Q7397\n")
        self.assertEqual(found, [])

    def test_value_against_the_datatype(self) -> None:
        found = self.problems(self.BASE + "", "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nQ101,P101,sometime\nQ101,P2,P100\n")
        self.assertIn("csv/statements.csv:4: P101 'sometime' is not a date (2021, 2021-06, 2021-06-04, -0500 or "
                      "+2021-06-04T00:00:00Z/11); row skipped", found)
        self.assertTrue(any("csv/statements.csv:5: P2 P100 is a property id, but the property takes items" in p for p in found))

    def test_time_formats(self) -> None:
        base = self.BASE + ""
        good = self.problems(base, "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nQ101,P101,2021\nQ101,P101,2021-06\nQ101,P101,2021-06-04\nQ101,P101,-0044-03-15\n")
        self.assertEqual(good, [])
        bad = self.problems(base, "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nQ101,P101,2021-6-4\nQ101,P101,2021-02-31x\n")
        self.assertEqual(len([p for p in bad if "is not a date" in p]), 2)

    def test_duplicate_entity_id(self) -> None:
        found = self.problems(self.BASE + "Q100,item,,Again\n")
        self.assertIn("csv/entities.csv:6: Q100 is already defined in csv/entities.csv:2; row ignored", found)

    def test_unknown_property_and_unknown_subject(self) -> None:
        found = self.problems(self.BASE, "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nQ101,P777,x\nQ999,P100,x\n")
        self.assertIn("csv/statements.csv:4: unknown property P777; row skipped", found)
        self.assertIn("csv/statements.csv:5: unknown subject 'Q999'; row skipped", found)

    def test_property_without_a_datatype_and_a_kind_that_does_not_match_the_id(self) -> None:
        found = self.problems("id,kind,datatype\nP100,property,\nQ100,property,\nP101,item,\n")
        self.assertIn("csv/entities.csv:2: property P100 has no datatype", found)
        self.assertTrue(any("csv/entities.csv:3: Q100 has kind property" in p for p in found))
        self.assertTrue(any("csv/entities.csv:4: P101 has kind item" in p for p in found))

    def test_unknown_datatype(self) -> None:
        found = self.problems("id,kind,datatype\nP100,property,geo-shape\n")
        self.assertIn("csv/entities.csv:2: P100 has datatype geo-shape, which the site cannot show; row skipped", found)

    def test_a_bad_rank_a_repeated_sid_and_a_qualifier_without_a_statement(self) -> None:
        found = self.problems(
            self.BASE, "sid,subject,property,value,rank\nQ100,P1,Q3,,\nQ101,P2,Q100,,\nx,Q101,P100,v,best\nx,Q101,P100,w,\ny,Q101,P100,z,preferred\n"
            .replace("Q100,P1,Q3,,", ",Q100,P1,Q3,").replace("Q101,P2,Q100,,", ",Q101,P2,Q100,"),
            "sid,property,value\nnope,P100,q\ny,P100,fine\n")
        self.assertTrue(any("rank 'best' is not normal, preferred or deprecated" in p for p in found), found)
        self.assertTrue(any("sid 'nope' names no statement" in p for p in found), found)
        self.assertEqual(len([p for p in found if "csv/statements.csv" in p and "already used" in p]), 0)

    def test_the_same_sid_twice(self) -> None:
        found = self.problems(
            self.BASE, "sid,subject,property,value\n,Q100,P1,Q3\n,Q101,P2,Q100\nx,Q101,P100,v\nx,Q101,P100,w\n")
        self.assertTrue(any("sid x is already used in csv/statements.csv:4" in p for p in found), found)

    def test_domain_and_range_are_checked_through_subclass_of(self) -> None:
        entities = ("id,kind,datatype,label_en\nQ100,class,,Thing\nQ101,class,,Special thing\nQ102,class,,Other\n"
                    "Q103,item,,A special thing\nQ104,item,,An other\nP100,property,wikibase-item,related to\n")
        statements = ("subject,property,value\nQ100,P1,Q3\nQ101,P1,Q100\nQ102,P1,Q3\nQ103,P2,Q101\nQ104,P2,Q102\n"
                      "P100,P9,Q100\nP100,P10,Q100\n"
                      "Q103,P100,Q103\n"          # a special thing relates to a special thing: fine through subclass of
                      "Q104,P100,Q103\n"          # an other thing is outside the domain
                      "Q103,P100,Q104\n")         # the value is outside the range
        found = self.problems(entities, statements)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(any("csv/statements.csv:10: Q104 is not an instance of the domain Q100 of P100" in p for p in found), found)
        self.assertTrue(any("csv/statements.csv:11: Q104 is not an instance of the range Q100 of P100" in p for p in found), found)

    def test_a_domain_on_a_property_that_is_not_a_class_is_reported(self) -> None:
        entities = "id,kind,datatype\nQ100,class,\nQ101,item,\nP100,property,string\n"
        found = self.problems(entities, "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nP100,P9,Q101\n")
        self.assertTrue(any("csv/statements.csv:4: Q101 is not an instance of the range Q1 of P9" in p for p in found), found)

    def test_every_message_names_file_and_line(self) -> None:
        found = self.problems(self.BASE + "Q100,item,,Again\n", "subject,property,value\nQ999,P100,x\n")
        for message in found:
            self.assertRegex(message, r"^(csv/\w+\.csv:\d+|kernel):", message)

    def test_problems_are_sorted_and_deterministic(self) -> None:
        a = self.problems(self.BASE + "Q100,item,,Again\n", "subject,property,value\nQ999,P100,x\n")
        b = self.build().problems
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a))


# --------------------------------------------------------------------------- JSON and the round trip


class JsonTests(Workspace):
    def test_statement_ids_are_a_function_of_the_data(self) -> None:
        write(self.csv, "entities.csv", "id,kind,datatype\nQ100,class,\nP100,property,globe-coordinate\n")
        write(self.csv, "statements.csv", "subject,property,value\nQ100,P1,Q3\nQ100,P100,\"1,2\"\nQ100,P100,\"1,2\"\n")
        first = self.build().entities["Q100"]["claims"]["P100"]
        second = self.build().entities["Q100"]["claims"]["P100"]
        self.assertEqual(first, second)
        self.assertEqual(len({c["id"] for c in first}), 2)          # two identical values get two statement ids
        self.assertTrue(all(c["id"].startswith("Q100$") for c in first))

    def test_a_sid_in_the_form_of_a_statement_id_is_kept(self) -> None:
        write(self.csv, "entities.csv", "id,kind,datatype\nQ100,class,\nP100,property,string\n")
        write(self.csv, "statements.csv", "sid,subject,property,value\n,Q100,P1,Q3\nQ100$abc-123,Q100,P100,v\n")
        write(self.csv, "references.csv", "sid,group,property,value\nQ100$abc-123,1,P6,https://example.org\n")
        claim = self.build().entities["Q100"]["claims"]["P100"][0]
        self.assertEqual(claim["id"], "Q100$abc-123")
        self.assertEqual(len(claim["references"]), 1)

    def test_references_keep_their_groups_and_order(self) -> None:
        write(self.csv, "entities.csv", "id,kind,datatype\nQ100,class,\nP100,property,string\n")
        write(self.csv, "statements.csv", "sid,subject,property,value\n,Q100,P1,Q3\ns,Q100,P100,v\n")
        write(self.csv, "references.csv", "sid,group,property,value\ns,2,P6,https://b.example\ns,1,P6,https://a.example\ns,1,P7,2020\n")
        refs = self.build().entities["Q100"]["claims"]["P100"][0]["references"]
        self.assertEqual([r["snaks-order"] for r in refs], [["P6", "P7"], ["P6"]])
        self.assertEqual(refs[0]["snaks"]["P6"][0]["datavalue"]["value"], "https://a.example")

    def test_a_wikidata_property_and_value_are_written_as_uris_and_read_back_as_wd(self) -> None:
        write(self.csv, "entities.csv", "id,kind\nQ100,class\n")
        write(self.csv, "statements.csv", "subject,property,value\nQ100,P1,Q3\nQ100,wd:P31,wd:Q7397\nQ100,wd:P275,https://example.org/licence\n")
        built = self.build()
        self.assertEqual(built.problems, [])
        for entity_id, entity in built.entities.items():
            write(self.out / "entities", f"{entity_id}.json", json.dumps(entity))
        claims = built.entities["Q100"]["claims"]
        self.assertEqual(claims["http://www.wikidata.org/entity/P31"][0]["mainsnak"]["datavalue"]["value"]["id"],
                         "http://www.wikidata.org/entity/Q7397")
        self.assertEqual(claims["http://www.wikidata.org/entity/P275"][0]["mainsnak"]["datatype"], "url")
        site = loader.load_site(self.base / "none", self.out)
        self.assertEqual(site.problems, [])                          # nothing "has no data": Wikidata is only linked
        statement = [s for s in site.entities["Q100"].statements if s.mainsnak.property == "wd:P31"][0]
        self.assertEqual(statement.mainsnak.entity_id, "wd:Q7397")

    def test_from_csv_twice_leaves_the_files_alone_and_removes_stale_ones(self) -> None:
        write(self.csv, "entities.csv", "id,kind\nQ100,class\nQ101,item\n")
        write(self.csv, "statements.csv", "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\n")
        code, out = run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out))
        self.assertEqual(code, 0, out)
        self.assertIn("15 file(s) written, 0 unchanged, 0 removed", out)
        first = {p.name: p.read_bytes() for p in (self.out / "entities").iterdir()}
        code, out = run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out))
        self.assertIn("0 file(s) written, 15 unchanged, 0 removed", out)
        self.assertEqual({p.name: p.read_bytes() for p in (self.out / "entities").iterdir()}, first)
        write(self.csv, "entities.csv", "id,kind\nQ100,class\n")
        (self.out / "entities" / "notes.json").write_text("{}", encoding="utf-8")      # not an entity file: left alone
        code, out = run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out))
        self.assertIn("1 removed", out)
        self.assertFalse((self.out / "entities" / "Q101.json").exists())
        self.assertTrue((self.out / "entities" / "notes.json").exists())

    def test_output_has_lf_endings_and_sorted_keys(self) -> None:
        write(self.csv, "entities.csv", "id,kind\nQ100,class\n")
        run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out))
        data = (self.out / "entities" / "Q100.json").read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"}\n"))
        parsed = json.loads(data)
        self.assertEqual(list(parsed), sorted(parsed))

    def test_nothing_to_do_without_a_csv_folder_and_nothing_is_written(self) -> None:
        code, out = run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out))
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)
        self.assertFalse(self.out.exists())

    def test_the_example_of_the_primer(self) -> None:
        write(self.csv, "entities.csv",
              "id,kind,datatype,origin,label_en,label_de,description_en\n"
              "Q100,class,,,Chublet,,small research software nugget\n"
              "Q101,item,,,Alligator,,statistical analysis and ontology tool\n"
              "Q102,item,,wikidata-stub,Python,,programming language\n"
              "P100,property,string,,source code repository,Quellcode-Repositorium,\n")
        write(self.csv, "statements.csv",
              "sid,subject,property,value,rank,origin\n"
              ",Q100,P1,Q3,,\n,Q102,P4,Q28865,,wikidata\n,Q101,P2,Q100,,\n"
              "s1,Q101,P100,https://github.com/leiza-rse/alligator,,open-archaeo\n")
        write(self.csv, "references.csv", "sid,group,property,value\ns1,1,P6,https://open-archaeo.info/post/alligator/\ns1,1,P7,2021-06-04\n")
        built = self.build()
        self.assertEqual(built.problems, [])
        self.assertEqual(len(built.entities), 17)
        reference = built.entities["Q101"]["claims"]["P100"][0]["references"][0]
        self.assertEqual(reference["snaks"]["P7"][0]["datavalue"]["value"]["precision"], 11)


class RoundTripTests(Workspace):
    def fixture_raw(self, strip_bounds: bool = True) -> Path:
        raw = self.base / "raw"
        shutil.copytree(FIXTURES / "entities", raw / "entities")
        if strip_bounds:                         # the CSV has no bounds; the loss itself is tested below
            for path in (raw / "entities").glob("Q1.json"):
                data = json.loads(path.read_text(encoding="utf-8"))
                for claim in data["claims"]["P6"]:
                    claim["mainsnak"]["datavalue"]["value"].pop("lowerBound", None)
                    claim["mainsnak"]["datavalue"]["value"].pop("upperBound", None)
                path.write_text(json.dumps(data), encoding="utf-8")
        return raw

    def test_to_csv_then_from_csv_gives_the_same_entities(self) -> None:
        raw = self.fixture_raw()
        code, out = run_step(step_to_csv, "--raw", str(raw), "--out", str(self.csv))
        self.assertEqual(code, 0, out)
        self.assertIn("0 warning(s)", out)
        code, out = run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out), "--no-kernel")
        self.assertEqual(code, 0, out)
        self.assertIn("0 warning(s)", out)
        for path in sorted((raw / "entities").glob("*.json")):
            with self.subTest(entity=path.stem):
                original = without_statement_ids(json.loads(path.read_text(encoding="utf-8")))
                again = without_statement_ids(json.loads((self.out / "entities" / path.name).read_text(encoding="utf-8")))
                self.assertEqual(again, original)

    def test_the_loaded_model_is_the_same_before_and_after(self) -> None:
        raw = self.fixture_raw()
        run_step(step_to_csv, "--raw", str(raw), "--out", str(self.csv))
        run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out), "--no-kernel")
        before = loader.load_site(raw, self.base / "none")
        after = loader.load_site(self.base / "none", self.out)
        self.assertEqual((len(after.entities), after.statement_count()), (len(before.entities), before.statement_count()))
        self.assertEqual(after.problems, before.problems)
        self.assertEqual(after.datatype_counts(), before.datatype_counts())

    def test_the_csv_is_a_fixed_point(self) -> None:
        raw = self.fixture_raw()
        run_step(step_to_csv, "--raw", str(raw), "--out", str(self.csv))
        run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out), "--no-kernel")
        again = self.base / "again"
        run_step(step_to_csv, "--raw", str(self.out), "--out", str(again))
        for name in csvio.TABLES:
            self.assertEqual((again / name).read_bytes(), (self.csv / name).read_bytes(), name)
        self.assertEqual(run_step(step_csv_fmt, "--check", "--csv", str(self.csv))[0], 0)

    def test_what_the_csv_cannot_hold_is_reported(self) -> None:
        raw = self.fixture_raw(strip_bounds=False)
        code, out = run_step(step_to_csv, "--raw", str(raw), "--out", str(self.csv))
        self.assertIn("WARN: [to-csv]", out)
        self.assertIn("quantity bounds not kept by the CSV format", out)

    def test_existing_tables_are_not_overwritten_without_force(self) -> None:
        raw = self.fixture_raw()
        write(self.csv, "entities.csv", "id\nQ100\n")
        code, out = run_step(step_to_csv, "--raw", str(raw), "--out", str(self.csv))
        self.assertEqual(code, 2)
        self.assertIn("already exist", out)
        self.assertEqual((self.csv / "entities.csv").read_text(encoding="utf-8"), "id\nQ100\n")
        self.assertEqual(run_step(step_to_csv, "--raw", str(raw), "--out", str(self.csv), "--force")[0], 0)

    def test_a_wikidata_entity_in_harvested_json_comes_out_as_wd(self) -> None:
        raw = self.fixture_raw()
        path = raw / "entities" / "Q1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["claims"]["P1"][0]["mainsnak"]["datavalue"]["value"] = {"entity-type": "item", "id": "http://www.wikidata.org/entity/Q7397"}
        path.write_text(json.dumps(data), encoding="utf-8")
        run_step(step_to_csv, "--raw", str(raw), "--out", str(self.csv))
        self.assertIn(",wd:Q7397,", (self.csv / "statements.csv").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- the orchestrator


class PackagingTests(unittest.TestCase):
    def test_the_kernel_files_are_shipped_with_the_package(self) -> None:
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("data/kernel/*.csv", text)
        self.assertEqual(sorted(p.name for p in csvbuild.KERNEL_DIR.iterdir()), ["entities.csv", "statements.csv"])

    def test_the_module_does_not_shadow_the_standard_library(self) -> None:
        self.assertFalse((REPO / "py" / "wikibase_static" / "csv.py").exists())
        import csv as standard
        self.assertTrue(hasattr(standard, "reader"))


class OrchestratorTests(unittest.TestCase):
    def run_main(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "WBS_ROOT"}
        env["WBS_ROOT"] = str(root)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, str(REPO / "main.py"), *args], cwd=root, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=180)

    def test_list_names_the_csv_steps_and_only_from_csv_is_in_the_default_run(self) -> None:
        result = subprocess.run([sys.executable, str(REPO / "main.py"), "--list"], capture_output=True, text=True, encoding="utf-8")
        lines = {line.split()[0]: line.split()[1] for line in result.stdout.splitlines()}
        self.assertEqual(lines["from-csv"], "default")
        self.assertEqual((lines["to-csv"], lines["csv-fmt"]), ("verb", "verb"))
        names = list(lines)
        self.assertLess(names.index("from-csv"), names.index("load"))

    def test_a_site_in_csv_runs_through_every_step_under_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write(root / "data" / "csv", "entities.csv", "id,kind,datatype,label_en\nQ100,class,,Thing\nQ101,item,,An item\nP100,property,string,note\n")
            write(root / "data" / "csv", "statements.csv", "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nQ101,P100,hello\n")
            result = self.run_main(root, "--strict")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("[from-csv] 16 entities", result.stdout)
            self.assertTrue((root / "docs" / "Q101.html").is_file())
            self.assertTrue((root / "docs" / "Q3.html").is_file())
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(self.run_main(root, "--strict").returncode, 0)
            after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(after, before)                  # the second run changes nothing

    def test_a_warning_of_from_csv_fails_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write(root / "data" / "csv", "entities.csv", "id,kind\nQ100,class\n")        # a class without a path to Q3
            result = self.run_main(root, "--strict")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("has no path to Q3", result.stdout)

    def test_to_csv_and_csv_fmt_are_called_by_their_verb_and_take_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            shutil.copytree(FIXTURES / "entities", root / "data" / "raw" / "entities")
            result = self.run_main(root, "to-csv")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / "data" / "csv" / "entities.csv").is_file())
            self.assertEqual(self.run_main(root, "csv-fmt", "--check").returncode, 0)


class FederatedRenderingTests(Workspace):
    def test_pages_and_rdf_treat_wikidata_entities_as_links_and_their_own_uris(self) -> None:
        from wikibase_static import rdf, render
        from wikibase_static.site_config import SiteConfig

        write(self.csv, "entities.csv", "id,kind,label_en\nQ100,class,Thing\nQ101,item,Item\n")
        write(self.csv, "statements.csv", "subject,property,value\nQ100,P1,Q3\nQ101,P2,Q100\nQ101,P8,wd:Q7397\nQ101,wd:P31,wd:Q5\n")
        run_step(step_from_csv, "--csv", str(self.csv), "--out", str(self.out))
        site = loader.load_site(self.base / "none", self.out)
        self.assertEqual(site.problems, [])
        renderer = render.Renderer(site, SiteConfig(), "test")
        link = str(renderer.entity_link("wd:Q7397"))
        self.assertIn('href="https://www.wikidata.org/wiki/Q7397"', link)
        self.assertIn(">wd:Q7397<", link)
        self.assertIn("wiki/Property:P31", str(renderer.entity_link("wd:P31")))
        page = renderer.statement_groups(site.entities["Q101"])
        self.assertIn("wd:P31", "".join(str(group["label"]) for group in page))
        result = rdf.build(site, rdf.Namespaces("https://example.org"))
        objects = {str(o.value) for (_s, _p, o) in result.triples if hasattr(o, "value")}
        self.assertTrue("http://www.wikidata.org/entity/Q7397" in objects, "the Wikidata entity keeps its own URI")
        self.assertFalse(any("wd:" in str(o.value) for (_s, _p, o) in result.triples if hasattr(o, "value")))
        self.assertTrue(any("wd:P..." in n for n in result.notes))


if __name__ == "__main__":
    unittest.main()
