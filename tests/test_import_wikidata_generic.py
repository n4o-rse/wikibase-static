"""Tests for ``import-wikidata --generic`` (S14a): a site without a model of its own; properties are created from Wikidata.

    python tests/test_import_wikidata_generic.py

Standard library only. The Wikidata answers are **synthetic**: ``stone()`` and ``prop()`` build entities in the shape of the
API (``wbgetentities``) for two invented stones, a few properties of every kind the importer handles and one it cannot hold
(``geo-shape``). They are not copies of Wikidata items; the real run (Govan Stones) is made by Florian (PRIMER.md, Befund 35).
The site is empty: the kernel (Q1 to Q3, P1 to P10) is all it has, which is the point of ``--generic``.
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

from wikibase_static import csvbuild, step_import_wikidata as imp  # noqa: E402

SEEDS = ["Q9000001", "Q9000002"]
MODIFIED = "2026-11-10T08:00:00Z"


def snak(pid: str, datatype: str, value=None, vtype: str = "string", snaktype: str = "value") -> dict:
    out = {"snaktype": snaktype, "property": pid, "datatype": datatype}
    if snaktype == "value":
        out["datavalue"] = {"value": value, "type": vtype}
    return out


def claim(main: dict, qualifiers: dict | None = None, references: list | None = None, rank: str = "normal") -> dict:
    out = {"mainsnak": main, "type": "statement", "rank": rank}
    if qualifiers:
        out["qualifiers"] = qualifiers
        out["qualifiers-order"] = list(qualifiers)
    if references:
        out["references"] = [{"snaks": r, "snaks-order": list(r)} for r in references]
    return out


def item_ref(pid: str, target: str) -> dict:
    return snak(pid, "wikibase-item", {"entity-type": "item", "id": target}, "wikibase-entityid")


def texts(label: str, description: str = "", label_de: str = "") -> dict:
    out = {"labels": {"en": {"language": "en", "value": label}}, "descriptions": {}, "aliases": {}}
    if label_de:
        out["labels"]["de"] = {"language": "de", "value": label_de}
    if description:
        out["descriptions"]["en"] = {"language": "en", "value": description}
    return out


def entity(entity_id: str, kind: str, label: str, claims: dict | None = None, description: str = "", label_de: str = "",
           datatype: str = "") -> dict:
    out = {"id": entity_id, "type": kind, "lastrevid": 1000 + int(entity_id[1:]) % 1000, "modified": MODIFIED,
           "claims": claims or {}, **texts(label, description, label_de)}
    if datatype:
        out["datatype"] = datatype
    return out


def stone(number: int, label: str, extra: dict | None = None) -> dict:
    qid = f"Q{9000000 + number}"
    claims = {
        "P31": [claim(item_ref("P31", "Q9000010"))],
        "P18": [claim(snak("P18", "commonsMedia", f"Stone {number}.jpg"))],
        "P625": [claim(snak("P625", "globe-coordinate", {"latitude": 55.86, "longitude": -4.31, "precision": 1e-05,
                                                          "globe": "http://www.wikidata.org/entity/Q2"}, "globecoordinate"),
                       qualifiers={"P585": [snak("P585", "time", {"time": "+2019-05-01T00:00:00Z", "precision": 11, "timezone": 0,
                                                                  "before": 0, "after": 0,
                                                                  "calendarmodel": "http://www.wikidata.org/entity/Q1985727"}, "time")]},
                       references=[{"P248": [item_ref("P248", "Q9000020")], "P854": [snak("P854", "url", "https://example.org/survey", )]}])],
        "P131": [claim(item_ref("P131", "Q9000011"))],
        "P2671": [claim(snak("P2671", "external-id", f"/g/{number}abc"))],
        "P373": [claim(snak("P373", "string", f"Stone {number}"))],
        "P2048": [claim(snak("P2048", "quantity", {"amount": "+1.8", "unit": "http://www.wikidata.org/entity/Q11573"}, "quantity"))],
        "P3896": [claim(snak("P3896", "geo-shape", "Data:Stone.map", "string"))],
    }
    claims.update(extra or {})
    return entity(qid, "item", label, claims, f"synthetic stone {number}", f"Stein {number}")


def world() -> dict[str, dict]:
    """The synthetic Wikidata: two seeds, the items they point to and the properties they use."""
    found = [
        stone(1, "Stone one"),
        stone(2, "Stone two", {"P2671": [claim(snak("P2671", "external-id", "/g/2xyz"))]}),
        entity("Q9000010", "item", "cross-slab", description="a type of stone"),
        entity("Q9000011", "item", "Govan", description="a place"),
        entity("Q9000020", "item", "a survey"),
        entity("Q11573", "item", "metre"),
        entity("P18", "property", "image", description="image of the subject", label_de="Bild", datatype="commonsMedia"),
        entity("P625", "property", "coordinate location", datatype="globe-coordinate"),
        entity("P131", "property", "located in the administrative territorial entity", datatype="wikibase-item"),
        entity("P585", "property", "point in time", datatype="time"),
        entity("P248", "property", "stated in", datatype="wikibase-item"),
        entity("P854", "property", "reference URL", datatype="url"),
        entity("P373", "property", "Commons category", datatype="string"),
        entity("P2048", "property", "height", datatype="quantity"),
        entity("P3896", "property", "geoshape", datatype="geo-shape"),
        entity("P2671", "property", "Google Knowledge Graph ID", datatype="external-id", claims={
            "P1630": [claim(snak("P1630", "string", "https://www.google.com/search?kgmid=$1"))]}),
    ]
    return {e["id"]: e for e in found}


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


class FakeClient:
    api = "https://wikidata.invalid/w/api.php"

    def __init__(self, entities: dict[str, dict]) -> None:
        self.entities = entities
        self.calls: list[tuple[str, str]] = []

    def get(self, params: dict, kind: str) -> dict:
        self.calls.append((kind, params["ids"]))
        found = {}
        for entity_id in params["ids"].split("|"):
            one = self.entities.get(entity_id)
            if one is None:
                found[entity_id] = {"id": entity_id, "missing": ""}
            elif params.get("props") == "info":
                found[entity_id] = {"id": entity_id, "lastrevid": one["lastrevid"], "modified": one["modified"]}
            else:
                found[entity_id] = dict(one)
        return {"entities": found}


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.csv = self.folder / "data" / "csv"
        write_csv(self.csv / "entities.csv", ["id", "kind", "datatype", "origin", "label_en"], [])
        write_csv(self.csv / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"], [])
        write_csv(self.csv / "qualifiers.csv", ["sid", "property", "value"], [])
        write_csv(self.csv / "references.csv", ["sid", "group", "property", "value"], [])
        write_csv(self.csv / "idmap.csv", ["source", "key", "id"], [])
        write_csv(self.csv / "seeds-wikidata.csv", ["qid", "kind", "note"], [{"qid": q, "kind": "stone"} for q in SEEDS])
        self.saved = self.folder / "saved"
        self.saved.mkdir()
        self.world = world()
        for entity_id, one in self.world.items():
            (self.saved / f"{entity_id}.json").write_text(json.dumps({"entities": {entity_id: one}}), encoding="utf-8")

    def run_step(self, *extra: str, client=None) -> tuple[int, str]:
        args = ["--csv", str(self.csv), "--seeds", str(self.csv / "seeds-wikidata.csv"),
                "--raw", str(self.folder / "data" / "raw" / "wikidata"), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = imp.main(args, client=client)
        return code, out.getvalue()

    def load(self, *extra: str) -> tuple[int, str]:
        return self.run_step("--from-dir", str(self.saved))

    def generic(self, *extra: str) -> tuple[int, str]:
        self.load()
        return self.run_step("--offline", "--generic", *extra)

    def table(self, name: str) -> list[dict[str, str]]:
        return read_csv(self.csv / name)

    def properties(self) -> dict[str, dict[str, str]]:
        return {r["id"]: r for r in self.table("entities.csv") if r["kind"] == "property"}

    def twin_of(self, wikidata: str) -> str:
        return next(r["subject"] for r in self.table("statements.csv") if r["property"] == "P4" and r["value"] == wikidata)

    def snapshot(self) -> dict[str, bytes]:
        files = sorted(self.csv.glob("*.csv")) + sorted((self.folder / "dist").glob("*"))
        return {p.name: p.read_bytes() for p in files}


class Created(Case):
    def test_each_wikidata_property_becomes_a_local_property_with_a_twin(self) -> None:
        code, out = self.generic()
        self.assertEqual(code, 0, out)
        props = self.properties()
        self.assertEqual(len(props), 7, sorted(props))            # seven with a datatype the CSV holds and no twin in the kernel; the geo-shape is left out
        self.assertEqual((self.twin_of_kernel("P854"), self.twin_of_kernel("P248")), ("P6", "P8"))   # the kernel has twins of reference URL and stated in
        for pid, datatype in (("P18", "commonsMedia"), ("P625", "globe-coordinate"), ("P131", "wikibase-item"), ("P585", "time"),
                              ("P373", "string"), ("P2048", "quantity"), ("P2671", "external-id")):
            local = self.twin_of(pid)
            self.assertTrue(local.startswith("P") and int(local[1:]) >= 100, local)
            self.assertEqual(props[local]["datatype"], datatype)
            self.assertEqual(props[local]["origin"], "wikidata")

    def twin_of_kernel(self, pid: str) -> str:
        kernel = csvbuild.kernel_set()
        return next(r["subject"] for r in kernel.statements.rows if r["property"] == "P4" and r["value"] == pid)

    def test_labels_come_from_the_raw_property_and_the_twin_has_a_reference(self) -> None:
        self.generic()
        local = self.twin_of("P18")
        row = self.properties()[local]
        self.assertEqual((row["label_en"], row["label_de"]), ("image", "Bild"))
        self.assertEqual(row["description_en"], "image of the subject")
        sid = next(r["sid"] for r in self.table("statements.csv") if r["subject"] == local and r["property"] == "P4")
        refs = [r for r in self.table("references.csv") if r["sid"] == sid]
        self.assertEqual([(r["property"], r["value"]) for r in refs], [("P6", "https://www.wikidata.org/wiki/Property:P18")])

    def test_an_external_id_keeps_the_formatter_url_in_the_formatter_property(self) -> None:
        self.generic()
        local = self.twin_of("P2671")
        found = [r["value"] for r in self.table("statements.csv") if r["subject"] == local and r["property"] == "P5"]
        self.assertEqual(found, ["https://www.google.com/search?kgmid=$1"])
        other = self.twin_of("P18")                              # not an external id: no formatter
        self.assertEqual([r for r in self.table("statements.csv") if r["subject"] == other and r["property"] == "P5"], [])

    def test_the_statements_use_the_created_properties(self) -> None:
        self.generic()
        stone_one = next(r["id"] for r in self.table("idmap.csv") if r["key"] == "Q9000001")
        by_property = {}
        for r in self.table("statements.csv"):
            if r["subject"] == stone_one:
                by_property.setdefault(r["property"], []).append(r["value"])
        self.assertEqual(by_property[self.twin_of("P18")], ["Stone 1.jpg"])
        self.assertEqual(by_property[self.twin_of("P373")], ["Stone 1"])
        self.assertTrue(by_property[self.twin_of("P625")][0].startswith("55.86,-4.31"), by_property[self.twin_of("P625")])
        self.assertEqual(by_property[self.twin_of("P2671")], ["/g/1abc"])
        self.assertEqual(len(by_property["P2"]), 1)              # instance of: the stub class of the cross-slab

    def test_qualifier_and_reference_properties_are_created_too(self) -> None:
        self.generic()
        point_in_time = self.twin_of("P585")
        self.assertIn(point_in_time, {r["property"] for r in self.table("qualifiers.csv")})
        self.assertEqual({"P6", "P7", "P8"} - {r["property"] for r in self.table("references.csv")}, set())     # P854, retrieved and P248 are the kernel's

    def test_class_stubs_hang_below_the_root_of_the_class_tree(self) -> None:
        self.generic()
        classes = [r for r in self.table("entities.csv") if r["kind"] == "class"]
        self.assertEqual([r["label_en"] for r in classes], ["cross-slab"])
        self.assertEqual([r["value"] for r in self.table("statements.csv") if r["subject"] == classes[0]["id"] and r["property"] == "P1"], ["Q3"])

    def test_the_model_rules_are_met(self) -> None:
        self.generic()
        found: list[str] = []
        site = csvbuild.read_set(self.csv, found, "csv")
        problems = sorted(set(found) | set(csvbuild.build(site, csvbuild.kernel_set(), "https://example.org/site").problems))
        self.assertEqual(problems, [])

    def test_a_property_the_csv_cannot_hold_is_reported_not_created(self) -> None:
        _code, out = self.generic()
        self.assertIn("not created: P3896: datatype geo-shape cannot be held", out)
        self.assertNotIn("P3896", {r["value"] for r in self.table("statements.csv") if r["property"] == "P4"})
        gaps = read_csv(self.folder / "dist" / "wikidata-gaps.csv")
        self.assertIn("P3896", {r["wikidata_property"] for r in gaps})

    def test_the_report_names_what_was_created(self) -> None:
        _code, out = self.generic()
        self.assertIn("--generic: 7 properties created", out)
        self.assertIn("P18 -> ", out)
        report = (self.folder / "dist" / "wikidata-import.txt").read_text(encoding="utf-8")
        self.assertIn("--generic: 7 properties created", report)


class WithoutTheFlag(Case):
    def test_nothing_is_created_and_the_properties_are_reported_as_before(self) -> None:
        self.load()
        code, out = self.run_step("--offline")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.properties(), {})
        self.assertIn("Wikidata properties without a twin in the model", out)
        self.assertNotIn("--generic", out)


class Choices(Case):
    def test_skip_property_leaves_a_property_out(self) -> None:
        _code, out = self.generic("--skip-property", "P2671, P373")
        self.assertNotIn("P2671", {r["value"] for r in self.table("statements.csv") if r["property"] == "P4"})
        self.assertNotIn("P373", {r["value"] for r in self.table("statements.csv") if r["property"] == "P4"})
        self.assertIn("not created: P2671: skipped (--skip-property)", out)
        self.assertEqual(len(self.properties()), 5)

    def test_skip_property_needs_property_ids_and_the_generic_flag(self) -> None:
        self.load()
        for extra in (["--generic", "--skip-property", "Q5"], ["--skip-property", "P18"]):
            code, out = self.run_step("--offline", *extra)
            self.assertEqual(code, 2, out)
            self.assertIn("--skip-property", out)

    def test_an_existing_twin_is_used_and_no_property_is_created_for_it(self) -> None:
        write_csv(self.csv / "entities.csv", ["id", "kind", "datatype", "origin", "label_en"],
                  [{"id": "P50", "kind": "property", "datatype": "commonsMedia", "label_en": "picture"}])
        write_csv(self.csv / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"],
                  [{"subject": "P50", "property": "P4", "value": "P18"}])
        self.generic()
        self.assertEqual(self.twin_of("P18"), "P50")
        self.assertEqual(self.properties()["P50"]["label_en"], "picture")
        self.assertEqual(len(self.properties()), 7)               # P50 and six created ones
        stone_one = next(r["id"] for r in self.table("idmap.csv") if r["key"] == "Q9000001")
        self.assertEqual([r["value"] for r in self.table("statements.csv") if r["subject"] == stone_one and r["property"] == "P50"], ["Stone 1.jpg"])


class Reimport(Case):
    def test_a_second_run_changes_nothing_and_the_ids_stay(self) -> None:
        self.generic()
        first = self.snapshot()
        ids = {r["key"]: r["id"] for r in self.table("idmap.csv")}
        self.run_step("--offline", "--generic")
        self.assertEqual(self.snapshot(), first)
        self.assertEqual({r["key"]: r["id"] for r in self.table("idmap.csv")}, ids)
        self.assertEqual(sorted(k for k in ids if k.startswith("P")), ["P131", "P18", "P2048", "P2671", "P373", "P585", "P625"])

    def test_property_numbers_start_at_100_and_are_not_reused(self) -> None:
        self.generic()
        numbers = sorted(int(r["id"][1:]) for r in self.table("idmap.csv") if r["key"].startswith("P"))
        self.assertEqual(numbers, list(range(100, 100 + len(numbers))))
        # a seed that drops a property does not free its number
        gone = {r["key"]: r["id"] for r in self.table("idmap.csv")}["P373"]
        del self.world["Q9000001"]["claims"]["P373"], self.world["Q9000002"]["claims"]["P373"]
        self.world["Q9000001"]["lastrevid"] += 1
        (self.saved / "Q9000001.json").write_text(json.dumps({"entities": {"Q9000001": self.world["Q9000001"]}}), encoding="utf-8")
        (self.saved / "Q9000002.json").write_text(json.dumps({"entities": {"Q9000002": self.world["Q9000002"]}}), encoding="utf-8")
        self.load()
        self.run_step("--offline", "--generic")
        self.assertEqual({r["key"]: r["id"] for r in self.table("idmap.csv")}["P373"], gone)
        self.assertNotIn(gone, self.properties())

    def test_a_hand_made_property_row_is_kept(self) -> None:
        self.generic()
        local = self.twin_of("P18")
        rows = self.table("entities.csv")
        for row in rows:
            if row["id"] == local:
                row["origin"] = ""
                row["label_en"] = "picture (by hand)"
        write_csv(self.csv / "entities.csv", ["id", "kind", "datatype", "origin", "label_en", "label_de", "description_en", "description_de"], rows)
        self.run_step("--offline", "--generic")
        self.assertEqual(self.properties()[local]["label_en"], "picture (by hand)")


class Network(Case):
    def test_the_property_entities_are_fetched_once_and_a_second_run_asks_only_for_the_revision(self) -> None:
        client = FakeClient(self.world)
        code, out = self.run_step("--generic", client=client)
        self.assertEqual(code, 0, out)
        fetched = {i for kind, ids in client.calls if kind in ("fetch", "labels") for i in ids.split("|")}
        for pid in ("P18", "P625", "P2671", "P373"):
            self.assertIn(pid, fetched)
        self.assertEqual(self.properties()[self.twin_of("P18")]["label_en"], "image")
        self.assertEqual(self.properties()[self.twin_of("P2671")]["datatype"], "external-id")
        client2 = FakeClient(self.world)
        before = self.snapshot()
        code, out = self.run_step("--generic", client=client2)
        self.assertEqual(code, 0, out)
        self.assertEqual({kind for kind, _ids in client2.calls}, {"info"})
        self.assertIn("fetched 0 changed", out)
        self.assertEqual(self.snapshot(), before)

    def test_a_stub_of_an_earlier_run_that_is_a_seed_now_is_fetched_in_full(self) -> None:
        """First real run of wd-govanstones-static: the stones were stubs (labels only) and, as seeds, were not fetched again
        because their revision had not changed; they stayed without statements."""
        from wikibase_static import step_harvest as harvest
        client = FakeClient(self.world)
        code, out = self.run_step("--generic", client=client)
        self.assertEqual(code, 0, out)
        raw = self.folder / "data" / "raw" / "wikidata"
        seed = SEEDS[0]
        manifest = harvest.load_manifest(raw)
        stub = {k: v for k, v in json.loads(harvest.entity_path(raw, seed).read_text(encoding="utf-8")).items() if k != "claims"}
        manifest["entities"][seed] = harvest.store_entity(raw, stub)
        harvest.write_manifest(raw, manifest)
        client2 = FakeClient(self.world)
        code, out = self.run_step("--generic", client=client2)
        self.assertEqual(code, 0, out)
        self.assertIn("fetched 1 changed", out)
        self.assertIn("claims", harvest.entity_path(raw, seed).read_text(encoding="utf-8"))


class Provenance(Case):
    def test_statement_is_the_default_every_statement_names_the_wikidata_page(self) -> None:
        self.generic()
        statements = [r for r in self.table("statements.csv") if r["origin"] == "wikidata" and r["property"] != "P4"]
        pages = {r["sid"] for r in self.table("references.csv") if r["property"] == "P6"}
        self.assertTrue(statements)
        self.assertTrue(all(r["sid"] in pages for r in statements))

    def test_item_keeps_the_reference_on_the_twin_statement_only(self) -> None:
        self.load()
        code, out = self.run_step("--offline", "--generic", "--provenance", "item")
        self.assertEqual(code, 0, out)
        references = self.table("references.csv")
        twins = {r["sid"] for r in self.table("statements.csv") if r["property"] == "P4"}
        for r in references:                                  # "retrieved" and "stated in" are item-level now: only the twins say them
            if r["value"].startswith("https://www.wikidata.org/wiki/Q"):
                self.assertIn(r["sid"], twins, r)
        stone = next(r["id"] for r in self.table("idmap.csv") if r["key"] == "Q9000001")
        own = [r for r in references if r["sid"].startswith(f"{stone}-") and not r["sid"].endswith("-P4-wd1")]
        self.assertTrue(all(r["group"] != "0" for r in own))
        self.assertEqual(min((int(r["group"]) for r in own), default=1), 1)      # Wikidata's own references start at group 1

    def test_item_twin_names_date_and_source(self) -> None:
        self.load()
        self.run_step("--offline", "--generic", "--provenance", "item")
        stone = next(r["id"] for r in self.table("idmap.csv") if r["key"] == "Q9000001")
        sid = f"{stone}-P4-wd1"
        found = {r["property"] for r in self.table("references.csv") if r["sid"] == sid}
        self.assertEqual(found, {"P6", "P7", "P8"})


class SavedFiles(Case):
    def test_from_dir_stores_property_files_too(self) -> None:
        code, out = self.load()
        self.assertEqual(code, 0, out)
        stored = {p.stem for p in (self.folder / "data" / "raw" / "wikidata" / "entities").glob("*.json")}
        self.assertIn("P18", stored)
        self.assertIn("Q9000001", stored)


if __name__ == "__main__":
    unittest.main()
