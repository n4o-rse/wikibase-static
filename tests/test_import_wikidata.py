"""Tests for ``import-wikidata`` (S7d): seeds, twins and stubs, no foreign ids, references, reimport, hand rows, the network.

    python tests/test_import_wikidata.py

Standard library only. The Wikidata answers in ``tests/fixtures/wikidata/`` are real (five software items of the chublets
project and the labels of the items they point to, saved from api.php / Special:EntityData). Each test builds a small site
(classes and properties with Wikidata twins) in a temporary folder and runs the step against it; the network is a fake client.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import csvbuild, step_import_wikidata as imp  # noqa: E402

FIXTURES = HERE / "fixtures" / "wikidata"
SEEDS = ["Q74003194", "Q74004218", "Q74005133", "Q74823867", "Q74824570"]

# local property -> (Wikidata twins, datatype); the numbers are the ones of the chublets demo
PROPS = {
    "P106": ("P195", "wikibase-item"), "P107": ("P275", "wikibase-item"), "P113": ("P178", "wikibase-item"),
    "P115": ("P2888", "url"), "P116": ("P217", "string"), "P118": ("P6104", "wikibase-item"),
    "P120": ("P856", "url"), "P122": ("P361", "wikibase-item"), "P123": ("P277", "wikibase-item"),
    "P125": ("P1324", "url"), "P126": ("P8423", "wikibase-item"), "P144": ("P577", "time"),
    "P148": ("P348", "string"), "P153": ("P548", "wikibase-item"), "P204": ("P18", "commonsMedia"),
    "P247": ("P1476", "monolingualtext"), "P248": ("P10627", "wikibase-item"), "P407": ("P407", "wikibase-item"),
    "P171": ("P170|P50", "wikibase-item"), "P114": ("P356", "external-id"),
}
CLASSES = {"Q100": ("software", "Q7397", "Q3"), "Q105": ("little minion", "Q73899440", "Q100"),
           "Q106": ("chublet", "Q141115627", "Q100")}
ITEMS = {"Q108": ("WikiProject chublets.software", "Q141169143"), "Q109": ("chublets.software", "Q141115774"),
         "Q110": ("open-archaeo (Repository)", "Q141190255"), "Q114": ("Git", "Q186055")}


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(c, "") for c in columns])
    path.write_text(out.getvalue(), encoding="utf-8", newline="")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_site(folder: Path, seeds: list[str] | None = None, extra_entities=None, extra_statements=None) -> dict[str, Path]:
    csv_dir = folder / "data" / "csv"
    ent = [{"id": i, "kind": "class", "origin": "starter-pack", "label_en": label} for i, (label, _w, _p) in CLASSES.items()]
    ent += [{"id": i, "kind": "item", "origin": "open-archaeo", "label_en": label} for i, (label, _w) in ITEMS.items()]
    ent += [{"id": i, "kind": "property", "datatype": dt, "origin": "starter-pack", "label_en": f"property {i}"}
            for i, (_w, dt) in PROPS.items()]
    stm = []
    for i, (_label, wikidata, parent) in CLASSES.items():
        stm += [{"subject": i, "property": "P1", "value": parent, "origin": "starter-pack"},
                {"subject": i, "property": "P4", "value": wikidata, "origin": "starter-pack"}]
    for i, (_label, wikidata) in ITEMS.items():
        stm += [{"subject": i, "property": "P2", "value": "Q3", "origin": "open-archaeo"},
                {"subject": i, "property": "P4", "value": wikidata, "origin": "open-archaeo"}]
    for i, (twins, _dt) in PROPS.items():
        stm += [{"subject": i, "property": "P4", "value": twin, "origin": "starter-pack"} for twin in twins.split("|")]
    write_csv(csv_dir / "entities.csv", ["id", "kind", "datatype", "origin", "label_en"], ent + (extra_entities or []))
    write_csv(csv_dir / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"], stm + (extra_statements or []))
    write_csv(csv_dir / "qualifiers.csv", ["sid", "property", "value"], [])
    write_csv(csv_dir / "references.csv", ["sid", "group", "property", "value"], [])
    write_csv(csv_dir / "idmap.csv", ["source", "key", "id"], [])
    seeds_path = csv_dir / "seeds-wikidata.csv"
    write_csv(seeds_path, ["qid", "kind", "note"], [{"qid": q, "kind": "research software"} for q in (SEEDS if seeds is None else seeds)])
    return {"csv": csv_dir, "seeds": seeds_path, "raw": folder / "data" / "raw" / "wikidata", "dist": folder / "dist"}


class FakeClient:
    """Answers wbgetentities from the fixtures and counts the calls."""

    api = "https://wikidata.invalid/w/api.php"

    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}
        for path in sorted(FIXTURES.glob("*.json")):
            for entity in json.loads(path.read_text(encoding="utf-8"))["entities"].values():
                self.entities[entity["id"]] = entity
        self.calls: list[tuple[str, str]] = []

    def get(self, params: dict, kind: str) -> dict:
        self.calls.append((kind, params["ids"]))
        found = {}
        for entity_id in params["ids"].split("|"):
            entity = self.entities.get(entity_id)
            if entity is None:
                found[entity_id] = {"id": entity_id, "missing": ""}
            elif params.get("props") == "info":
                found[entity_id] = {"id": entity_id, "lastrevid": entity.get("lastrevid") or 1, "modified": entity.get("modified", "2026-01-01T00:00:00Z")}
            else:                      # the real API sends the revision with every full answer
                found[entity_id] = dict(entity, lastrevid=entity.get("lastrevid") or 1, modified=entity.get("modified", "2026-01-01T00:00:00Z"))
        return {"entities": found}


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.paths = build_site(self.folder)

    def run_step(self, *extra: str, client=None) -> tuple[int, str]:
        args = ["--csv", str(self.paths["csv"]), "--seeds", str(self.paths["seeds"]), "--raw", str(self.paths["raw"]), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = imp.main(args, client=client)
        return code, out.getvalue()

    def load(self) -> tuple[int, str]:
        return self.run_step("--from-dir", str(FIXTURES))

    def table(self, name: str) -> list[dict[str, str]]:
        return read_csv(self.paths["csv"] / name)

    def snapshot(self) -> dict[str, bytes]:
        files = sorted(self.paths["csv"].glob("*.csv")) + sorted(self.paths["dist"].glob("*"))
        return {p.name: p.read_bytes() for p in files}

    def local(self, qid: str) -> str:
        return next(r["id"] for r in self.table("idmap.csv") if r["source"] == "wikidata" and r["key"] == qid)

    def values(self, subject: str, prop: str) -> list[str]:
        return [r["value"] for r in self.table("statements.csv") if r["subject"] == subject and r["property"] == prop]

    def label(self, entity_id: str) -> str:
        return next(r["label_en"] for r in self.table("entities.csv") if r["id"] == entity_id)


class Seeds(Case):
    def test_each_seed_becomes_an_item_with_a_new_id_and_its_twin(self) -> None:
        code, _out = self.load()
        self.assertEqual(code, 0)
        ids = [self.local(q) for q in SEEDS]
        self.assertEqual(len(set(ids)), 5)
        self.assertTrue(all(int(i[1:]) >= 100 for i in ids))
        rows = {r["id"]: r for r in self.table("entities.csv")}
        self.assertEqual(rows[self.local("Q74003194")]["label_en"], "Academic Meta Tool (AMT)")
        self.assertEqual(rows[self.local("Q74004218")]["label_de"], "Alligator - Allen Transformator")
        self.assertEqual(rows[self.local("Q74003194")]["origin"], "wikidata")
        self.assertEqual(self.values(self.local("Q74003194"), "P4"), ["Q74003194"])
        self.assertIn("Allen's interval algebra", rows[self.local("Q74004218")]["description_en"])

    def test_the_model_rules_are_met(self) -> None:
        self.load()
        found: list[str] = []
        site = csvbuild.read_set(self.paths["csv"], found, "csv")
        problems = sorted(set(found) | set(csvbuild.build(site, csvbuild.kernel_set(), None).problems))
        self.assertEqual(problems, [])

    def test_a_seed_file_with_a_bad_id_or_a_duplicate_is_refused(self) -> None:
        for rows in (["Q1", "42"], ["Q74003194", "Q74003194"]):
            write_csv(self.paths["seeds"], ["qid", "kind", "note"], [{"qid": q} for q in rows])
            code, out = self.run_step("--offline")
            self.assertEqual(code, 2, out)
            self.assertIn("ERROR", out)

    def test_an_empty_seed_list_has_nothing_to_do(self) -> None:
        write_csv(self.paths["seeds"], ["qid", "kind", "note"], [])
        code, out = self.run_step("--offline")
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)

    def test_missing_raw_data_is_an_error_that_names_the_ids(self) -> None:
        code, out = self.run_step("--offline")
        self.assertEqual(code, 2)
        self.assertIn("Q74003194", out)


class NoForeignIds(Case):
    def test_no_value_qualifier_or_reference_holds_a_wikidata_id(self) -> None:
        self.load()
        entities = {r["id"] for r in self.table("entities.csv")} | {"Q1", "Q2", "Q3"} | {f"P{i}" for i in range(1, 11)}
        datatypes = {r["id"]: r.get("datatype", "") for r in self.table("entities.csv") if r["kind"] == "property"}
        datatypes.update({"P1": "wikibase-item", "P2": "wikibase-item", "P3": "wikibase-property", "P4": "external-id",
                          "P6": "url", "P7": "time", "P8": "wikibase-item"})
        checked = 0
        for name in ("statements.csv", "qualifiers.csv", "references.csv"):
            for row in self.table(name):
                if row["property"] == "P4":
                    continue                               # the twin is the one place a Wikidata id belongs
                self.assertNotIn("wd:", row["value"], row)
                self.assertNotIn("wikidata.org/entity", row["value"], row)
                if datatypes.get(row["property"]) == "wikibase-item":
                    checked += 1
                    self.assertIn(row["value"], entities, f"{name}: {row}")
        self.assertGreater(checked, 80)

    def test_a_target_without_a_twin_becomes_a_stub_with_label_description_and_twin_only(self) -> None:
        self.load()
        github = next(r for r in self.table("entities.csv") if r["label_en"] == "GitHub")
        self.assertEqual(github["origin"], "wikidata-stub")
        self.assertEqual(github["description_de"], "webbasierter Hosting-Dienst für Software-Entwicklungsprojekte")
        self.assertEqual(self.values(github["id"], "P4"), ["Q364"])
        self.assertEqual([r["property"] for r in self.table("statements.csv") if r["subject"] == github["id"]], ["P4"])

    def test_a_target_with_a_twin_uses_the_local_item_and_makes_no_stub(self) -> None:
        self.load()
        amt = self.local("Q74003194")
        self.assertEqual(sorted(self.values(amt, "P2")), sorted(["Q100", "Q105", "Q106", self.local("Q312466")]))
        stubs = {r["label_en"] for r in self.table("entities.csv") if r["origin"] == "wikidata-stub"}
        self.assertNotIn("software", stubs)
        self.assertNotIn("Git", stubs)
        self.assertEqual(sum(1 for r in self.table("entities.csv") if r["label_en"] == "Git"), 1)

    def test_a_type_without_a_twin_becomes_a_class_stub_below_software_and_is_named_in_the_report(self) -> None:
        _code, out = self.load()
        self.assertIn("3 class stub(s) for types without a local twin, assumed to be subclasses of Q100", out)
        rows = {r["label_en"]: r for r in self.table("entities.csv")}
        for label, qid in (("utility software", "Q312466"), ("plug-in", "Q184148"), ("QGIS plugin", "Q123054280")):
            self.assertEqual(rows[label]["kind"], "class", label)
            self.assertEqual(rows[label]["origin"], "wikidata-stub", label)
            self.assertEqual(self.values(rows[label]["id"], "P1"), ["Q100"], label)
            self.assertEqual(self.values(rows[label]["id"], "P4"), [qid], label)
        subclass = next(r for r in self.table("statements.csv") if r["subject"] == rows["plug-in"]["id"] and r["property"] == "P1")
        self.assertEqual([r for r in self.table("references.csv") if r["sid"] == subclass["sid"]], [])
        self.assertEqual(rows["GitHub"]["kind"], "item")                      # only the values of "instance of" are classes

    def test_without_a_software_class_the_class_stubs_go_below_the_root(self) -> None:
        converter = imp.Converter([], {}, {}, {}, imp.IdMap([], set(), "wikidata"), ("en",))
        self.assertEqual(converter.parent, "Q3")

    def test_the_wikidata_item_of_stated_in_gets_a_label_even_without_raw_data(self) -> None:
        self.load()
        self.assertEqual(self.label(self.local("Q2013")), "Wikidata")

    def test_a_seed_that_already_has_a_twin_keeps_its_item(self) -> None:
        self.paths = build_site(self.folder, extra_entities=[{"id": "Q150", "kind": "item", "origin": "open-archaeo", "label_en": "Text mining minion"}],
                                extra_statements=[{"subject": "Q150", "property": "P2", "value": "Q106", "origin": "open-archaeo"},
                                                  {"subject": "Q150", "property": "P4", "value": "Q74824570", "origin": "open-archaeo"}])
        self.load()
        self.assertEqual(sum(1 for r in self.table("entities.csv") if r["label_en"] == "Text mining minion"), 1)
        self.assertEqual(self.values("Q150", "P4"), ["Q74824570"])
        self.assertTrue(self.values("Q150", "P125"))                 # the statements of Wikidata went to that item

    def test_an_existing_twin_of_the_author_is_used_and_p50_goes_to_creator(self) -> None:
        self.load()
        self.assertEqual(self.values(self.local("Q74824570"), "P171"), [self.local("Q58529575")])


class Gaps(Case):
    def test_properties_without_a_twin_are_reported_with_number_and_items_and_not_imported(self) -> None:
        _code, out = self.load()
        self.assertIn("Wikidata properties without a twin in the model: 3 (18 snak(s))", out)
        self.assertIn("P136 as statement: 7x in Q74003194, Q74004218", out)
        self.assertIn("P1535 as statement: 6x", out)
        self.assertIn("P2283 as statement: 5x in Q74005133, Q74823867", out)
        report = read_csv(self.paths["dist"] / "wikidata-gaps.csv")
        self.assertEqual([(r["wikidata_property"], r["snaks"]) for r in report], [("P136", "7"), ("P1535", "6"), ("P2283", "5")])
        self.assertTrue((self.paths["dist"] / "wikidata-import.txt").is_file())

    def test_a_property_with_a_twin_is_imported_from_then_on(self) -> None:
        self.load()
        self.paths = build_site(self.folder)               # the same model plus a twin for P136 (genre)
        write_csv(self.paths["csv"] / "entities.csv", ["id", "kind", "datatype", "origin", "label_en"],
                  read_csv(self.paths["csv"] / "entities.csv") + [{"id": "P180", "kind": "property", "datatype": "wikibase-item", "label_en": "genre"}])
        write_csv(self.paths["csv"] / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"],
                  read_csv(self.paths["csv"] / "statements.csv") + [{"subject": "P180", "property": "P4", "value": "P136"}])
        _code, out = self.run_step("--offline")
        self.assertIn("without a twin in the model: 2 (11 snak(s))", out)
        self.assertEqual(len(self.values(self.local("Q74003194"), "P180")), 4)

    def test_values_the_csv_cannot_hold_are_reported_and_left_out(self) -> None:
        converter = imp.Converter([], {}, {"Q5": "Q200"}, {"P150": "time", "P151": "quantity", "P152": "globe-coordinate", "P153": "string"},
                                  imp.IdMap([], set(), "wikidata"), ("en",))
        julian = {"snaktype": "value", "datatype": "time", "datavalue": {"type": "time", "value": {
            "time": "+1500-01-01T00:00:00Z", "precision": 11, "calendarmodel": "http://www.wikidata.org/entity/Q1985786", "timezone": 0, "before": 0, "after": 0}}}
        mars = {"snaktype": "value", "datatype": "globe-coordinate", "datavalue": {"type": "globecoordinate", "value": {
            "latitude": 1, "longitude": 2, "globe": "http://www.wikidata.org/entity/Q111", "precision": 1}}}
        wrong = {"snaktype": "value", "datatype": "url", "datavalue": {"type": "string", "value": "https://x.example"}}
        self.assertIsNone(converter.value(julian, "P150", "P1", "Q1"))
        self.assertIsNone(converter.value(mars, "P152", "P2", "Q1"))
        self.assertIsNone(converter.value(wrong, "P153", "P3", "Q1"))
        self.assertEqual(len(converter.gaps.other), 3)


class Values(unittest.TestCase):
    """The value conversions, one snak at a time."""

    def converter(self) -> imp.Converter:
        return imp.Converter([], {}, {"Q5": "Q200"}, {"P150": "time", "P151": "quantity", "P152": "globe-coordinate",
                                                     "P153": "string", "P154": "monolingualtext", "P155": "wikibase-item"},
                             imp.IdMap([], set(), "wikidata"), ("en",))

    def snak(self, datatype: str, vtype: str, value, snaktype: str = "value") -> dict:
        return {"snaktype": snaktype, "datatype": datatype, "datavalue": {"type": vtype, "value": value}} if snaktype == "value" \
            else {"snaktype": snaktype, "datatype": datatype}

    def test_time_precisions_and_the_other_datatypes(self) -> None:
        c = self.converter()
        time = lambda t, p: self.snak("time", "time", {"time": t, "precision": p, "calendarmodel": "http://www.wikidata.org/entity/Q1985727", "timezone": 0, "before": 0, "after": 0})
        self.assertEqual(c.value(time("+2019-11-08T00:00:00Z", 11), "P150", "P577", "Q1"), "2019-11-08")
        self.assertEqual(c.value(time("+2019-11-00T00:00:00Z", 10), "P150", "P577", "Q1"), "2019-11")
        self.assertEqual(c.value(time("+2019-00-00T00:00:00Z", 9), "P150", "P577", "Q1"), "2019")
        self.assertEqual(c.value(self.snak("monolingualtext", "monolingualtext", {"language": "en", "text": "Release 1.0"}), "P154", "P1476", "Q1"), "en:Release 1.0")
        self.assertEqual(c.value(self.snak("string", "string", "?"), "P153", "P217", "Q1"), "\\?")
        self.assertEqual(c.value(self.snak("quantity", "quantity", {"amount": "+12", "unit": "1"}), "P151", "P1", "Q1"), "12")
        self.assertEqual(c.value(self.snak("globe-coordinate", "globecoordinate", {"latitude": 50.5, "longitude": 8, "globe": "http://www.wikidata.org/entity/Q2", "precision": 1e-06}), "P152", "P625", "Q1"), "50.5,8")
        self.assertEqual(c.value(self.snak("string", "string", None, "somevalue"), "P153", "P1", "Q1"), "?")
        self.assertEqual(c.value(self.snak("string", "string", None, "novalue"), "P153", "P1", "Q1"), "-")

    def test_an_item_value_is_the_twin_or_a_stub_and_a_unit_too(self) -> None:
        c = self.converter()
        item = lambda q: self.snak("wikibase-item", "wikibase-entityid", {"entity-type": "item", "id": q})
        self.assertEqual(c.value(item("Q5"), "P155", "P31", "Q1"), "Q200")
        stub = c.value(item("Q146"), "P155", "P31", "Q1")
        self.assertEqual(stub, "Q100")
        self.assertEqual(c.value(item("Q146"), "P155", "P31", "Q1"), "Q100")        # the same id the second time
        quantity = c.value(self.snak("quantity", "quantity", {"amount": "-3.5", "unit": "http://www.wikidata.org/entity/Q11573"}), "P151", "P2048", "Q1")
        self.assertEqual(quantity, "-3.5 Q101")


class References(Case):
    def test_every_statement_has_the_import_reference_with_the_date_of_the_revision(self) -> None:
        self.load()
        amt = self.local("Q74003194")
        sid = next(r["sid"] for r in self.table("statements.csv") if r["subject"] == amt and r["property"] == "P120")
        group = {r["property"]: r["value"] for r in self.table("references.csv") if r["sid"] == sid and r["group"] == "1"}
        self.assertEqual(group, {"P6": "https://www.wikidata.org/wiki/Q74003194", "P7": "2026-08-18", "P8": self.local("Q2013")})
        everything = {r["sid"] for r in self.table("statements.csv") if r["origin"] == "wikidata"}
        self.assertEqual(everything - {r["sid"] for r in self.table("references.csv") if r["group"] == "1"}, set())

    def test_the_references_wikidata_holds_follow_as_further_groups(self) -> None:
        self.load()
        alligator = self.local("Q74004218")
        sids = [r["sid"] for r in self.table("statements.csv") if r["subject"] == alligator and r["property"] == "P148"]
        self.assertEqual(len(sids), 3)
        later = {r["property"]: r["value"] for r in self.table("references.csv") if r["sid"] == sids[0] and r["group"] == "2"}
        self.assertEqual(later, {"P6": "https://github.com/RGZM/alligator/releases/tag/v0.1", "P7": "2019-11-08",
                                 "P247": "en:Release 0.1", "P144": "2019-01-15"})

    def test_qualifiers_and_ranks_come_over(self) -> None:
        self.load()
        alligator = self.local("Q74004218")
        rows = [r for r in self.table("statements.csv") if r["subject"] == alligator and r["property"] == "P148"]
        self.assertEqual([r["rank"] for r in rows], ["", "", "preferred"])
        qualifiers = [(r["property"], r["value"]) for r in self.table("qualifiers.csv") if r["sid"] == rows[2]["sid"]]
        self.assertEqual(qualifiers, [("P144", "2024-04-25"), ("P153", self.local("Q2804309"))])


class Reimport(Case):
    def test_a_second_run_writes_nothing(self) -> None:
        self.load()
        before = self.snapshot()
        code, out = self.run_step("--offline")
        self.assertEqual(code, 0)
        self.assertIn("0 file(s) written", out)
        self.assertEqual(self.snapshot(), before)

    def test_the_ids_survive_a_new_seed_and_are_not_reused(self) -> None:
        write_csv(self.paths["seeds"], ["qid", "kind", "note"], [{"qid": "Q74003194"}])
        self.load()
        first = self.local("Q74003194")
        write_csv(self.paths["seeds"], ["qid", "kind", "note"], [{"qid": q} for q in SEEDS])
        self.run_step("--offline")
        self.assertEqual(self.local("Q74003194"), first)
        self.assertEqual(len({r["id"] for r in self.table("idmap.csv")}), len(self.table("idmap.csv")))

    def test_a_seed_that_is_dropped_leaves_no_rows_but_keeps_its_id(self) -> None:
        self.load()
        gone = self.local("Q74824570")
        write_csv(self.paths["seeds"], ["qid", "kind", "note"], [{"qid": q} for q in SEEDS[:-1]])
        self.run_step("--offline")
        self.assertNotIn(gone, {r["id"] for r in self.table("entities.csv")})
        self.assertIn(gone, {r["id"] for r in self.table("idmap.csv")})

    def test_a_row_whose_origin_was_emptied_wins(self) -> None:
        self.load()
        amt = self.local("Q74003194")
        rows = self.table("statements.csv")
        for row in rows:
            if row["subject"] == amt and row["property"] == "P120":
                row["value"], row["origin"] = "https://example.org/my-own", ""
        write_csv(self.paths["csv"] / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"], rows)
        _code, out = self.run_step("--offline")
        self.assertEqual(self.values(amt, "P120"), ["https://example.org/my-own"])
        self.assertIn("hand rows protect", out)
        entities = self.table("entities.csv")
        for row in entities:
            if row["id"] == amt:
                row["label_en"], row["origin"] = "AMT, my label", ""
        write_csv(self.paths["csv"] / "entities.csv", list(entities[0]), entities)
        self.run_step("--offline")
        self.assertEqual(self.label(amt), "AMT, my label")

    def test_a_dry_run_writes_nothing(self) -> None:
        self.load()
        shutil.rmtree(self.paths["dist"])
        before = {p.name: p.read_bytes() for p in self.paths["csv"].glob("*.csv")}
        rows = self.table("statements.csv")
        write_csv(self.paths["csv"] / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"], rows[:-3])
        changed = (self.paths["csv"] / "statements.csv").read_bytes()
        code, out = self.run_step("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("would change", out)
        self.assertEqual((self.paths["csv"] / "statements.csv").read_bytes(), changed)
        self.assertFalse(self.paths["dist"].exists())
        self.assertNotEqual(before["statements.csv"], changed)

    def test_dry_run_and_from_dir_exclude_each_other(self) -> None:
        code, out = self.run_step("--dry-run", "--from-dir", str(FIXTURES))
        self.assertEqual(code, 2)
        self.assertIn("ERROR", out)


class Reconcile(Case):
    def olditem(self, statements: list[dict[str, str]]) -> None:
        self.paths = build_site(self.folder, extra_entities=[{"id": "Q150", "kind": "item", "origin": "open-archaeo", "label_en": "alligator (open-archaeo)"}],
                                extra_statements=[{"subject": "Q150", "property": "P2", "value": "Q106", "origin": "open-archaeo"}] + statements)

    def test_a_repository_url_that_is_in_both_is_reported_not_merged(self) -> None:
        self.olditem([{"subject": "Q150", "property": "P125", "value": "https://github.com/rgzm/alligator.git/", "origin": "open-archaeo"}])
        _code, out = self.load()
        self.assertIn("(repository, exact match): 7 URL(s) compared, 1 found in both", out)
        self.assertIn(f"Q74004218 ({self.local('Q74004218')}) and Q150 share the repository URL https://github.com/RGZM/alligator", out)
        self.assertEqual(sum(1 for r in self.table("entities.csv") if "lligator" in r["label_en"]), 2)

    def test_a_project_that_moved_is_found_by_its_open_archaeo_page(self) -> None:
        self.olditem([{"subject": "Q150", "property": "P125", "value": "https://github.com/leiza-rse/alligator", "origin": "open-archaeo"},
                      {"subject": "Q150", "property": "P115", "value": "https://open-archaeo.info/post/alligator/", "origin": "open-archaeo"}])
        _code, out = self.load()
        self.assertIn("1 found in both", out)
        self.assertIn("share the exact match URL https://open-archaeo.info/post/alligator/", out)

    def test_no_match_is_said_plainly(self) -> None:
        _code, out = self.load()
        self.assertIn("7 URL(s) compared, 0 found in both", out)


class Network(Case):
    def test_the_first_run_fetches_seeds_and_stubs_and_the_second_only_asks_for_revisions(self) -> None:
        client = FakeClient()
        code, out = self.run_step(client=client)
        self.assertEqual(code, 0, out)
        kinds = [k for k, _ids in client.calls]
        self.assertEqual(kinds.count("fetch"), 1)
        self.assertEqual(kinds.count("labels"), 1)
        self.assertTrue((self.paths["raw"] / "entities" / "Q74003194.json").is_file())
        self.assertTrue((self.paths["raw"] / "entities" / "Q364.json").is_file())
        manifest = json.loads((self.paths["raw"] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entities"]["Q74003194"]["lastrevid"], 2532639498)
        self.assertEqual(self.label(self.local("Q364")), "GitHub")
        snapshot = self.snapshot()
        client2 = FakeClient()
        code, out = self.run_step(client=client2)
        self.assertEqual(code, 0, out)
        self.assertEqual({k for k, _ids in client2.calls}, {"info"})
        self.assertIn("fetched 0 changed", out)
        self.assertEqual(self.snapshot(), snapshot)

    def test_a_changed_revision_is_fetched_again(self) -> None:
        client = FakeClient()
        self.run_step(client=client)
        client2 = FakeClient()
        client2.entities["Q74824570"] = dict(client2.entities["Q74824570"], lastrevid=2999999999,
                                             descriptions={"en": {"language": "en", "value": "text mining tools, new text"}})
        self.run_step(client=client2)
        self.assertEqual([ids for k, ids in client2.calls if k == "fetch"], ["Q74824570"])
        self.assertIn("text mining tools, new text", {r.get("description_en") for r in self.table("entities.csv")})

    def test_the_network_is_not_touched_with_offline(self) -> None:
        self.load()
        client = FakeClient()
        self.run_step("--offline", client=client)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
