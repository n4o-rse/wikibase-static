"""Tests for ``import-osm`` (S15a): one item per element, the versions as statements, the selection runs, ids, reimport, hand rows.

    python tests/test_import_osm.py

Standard library only. The 21 history files of the benchmark nodes (tests/fixtures/osm/history, the answers of the OSM API) and the
tables of the model of osm-benchmarks-static (tests/fixtures/osm/model) are copied into a temporary site; the step runs against it.
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

from wikibase_static import crm, csvio, step_import_osm as imp  # noqa: E402

FIXTURES = HERE / "fixtures" / "osm"
URL = "https://www.openstreetmap.org"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class Site:
    """A temporary site folder with the model tables, the role map, the selection and the history files."""

    def __init__(self, history: bool = True) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.csv = self.root / "data" / "csv"
        (self.csv / "mapping").mkdir(parents=True)
        for name in ("entities.csv", "statements.csv", "qualifiers.csv"):
            shutil.copy(FIXTURES / "model" / name, self.csv / name)
        shutil.copy(FIXTURES / "model" / "osm-properties.csv", self.csv / "mapping" / "osm-properties.csv")
        (self.root / "data" / "seeds").mkdir(parents=True)
        shutil.copy(FIXTURES / "model" / "benchmarks.csv", self.root / "data" / "seeds" / "benchmarks.csv")
        self.history = self.root / "data" / "raw" / "osm" / "history"
        self.history.mkdir(parents=True)
        if history:
            for path in sorted((FIXTURES / "history").glob("*.json")):
                shutil.copy(path, self.history / path.name)

    def close(self) -> None:
        self.tmp.cleanup()

    def put(self, kind: str, number: int, versions: list[dict]) -> None:
        elements = [{"type": kind, "id": number, **v} for v in versions]
        (self.history / f"{kind}_{number}.json").write_text(json.dumps({"version": "0.6", "elements": elements}), encoding="utf-8")

    def run(self, *extra: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = imp.main(["--csv", str(self.csv), "--from-dir", str(self.history), "--mapping", str(self.csv / "mapping" / "osm-properties.csv"),
                             "--seeds", str(self.root / "data" / "seeds"), "--offline",
                             "--members-dir", str(self.root / "data" / "raw" / "osm" / "members"), *extra])
        return code, buffer.getvalue()

    def table(self, name: str) -> list[dict[str, str]]:
        return rows(self.csv / name)

    def snapshot(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted(self.csv.glob("*.csv"))}


def version(n: int, lat: float = 53.0, lon: float = -6.0, tags: dict | None = None, **kw) -> dict:
    return {"version": n, "timestamp": f"2020-01-0{n}T10:00:00Z", "changeset": 1000 + n, "user": "u", "uid": 7,
            "lat": lat, "lon": lon, "tags": tags if tags is not None else {}, **kw}


GOOD = {"man_made": "survey_point", "benchmark": "yes", "wikimedia_commons": "File:A_b.jpg"}


class FullImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.site = Site()
        cls.code, cls.out = cls.site.run()
        cls.statements = cls.site.table("statements.csv")
        cls.qualifiers = cls.site.table("qualifiers.csv")
        cls.idmap = cls.site.table("idmap.csv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.site.close()

    def of(self, subject: str, prop: str) -> list[dict[str, str]]:
        return [r for r in self.statements if r["subject"] == subject and r["property"] == prop]

    def test_runs(self) -> None:
        self.assertEqual(self.code, 0)
        self.assertIn("21 history file(s)", self.out)

    def test_one_item_per_element(self) -> None:
        items = [r for r in self.site.table("entities.csv") if r["origin"] == "osm"]
        self.assertEqual(len(items), 21)
        self.assertEqual(len(self.idmap), 21)
        self.assertEqual(len({r["id"] for r in self.idmap}), 21)
        self.assertEqual(len([r for r in self.statements if r["property"] == "P100"]), 21)

    def test_every_version_is_a_statement(self) -> None:
        self.assertEqual(len([r for r in self.statements if r["property"] == "P101"]), 59)
        self.assertEqual(len([r for r in self.statements if r["rank"] == "preferred"]), 21)

    def test_geometry_entries_follow_moves(self) -> None:
        self.assertEqual(len([r for r in self.statements if r["property"] == "P111"]), 33)

    def test_numbers_start_after_the_class(self) -> None:
        ids = sorted(int(r["id"][1:]) for r in self.idmap)
        self.assertEqual(ids, list(range(101, 122)))

    def test_the_milestone(self) -> None:
        subject = next(r["id"] for r in self.idmap if r["key"] == "node/6666122939")
        self.assertEqual(self.of(subject, "P100")[0]["value"], f"{URL}/node/6666122939")
        self.assertEqual([r["value"] for r in self.of(subject, "P101")],
                         [f"{URL}/node/6666122939/history/{n}" for n in (1, 2, 3)])
        self.assertEqual([r["value"] for r in self.of(subject, "P107")], [f"{URL}/node/6666122939/history/3"])
        self.assertEqual(self.of(subject, "P110")[0]["value"], "53.390985,-6.0906714")
        self.assertEqual([r["value"] for r in self.of(subject, "P111")], ["POINT(-6.0906724 53.3909747)", "POINT(-6.0906714 53.390985)"])
        self.assertEqual(self.of(subject, "P112")[0]["value"], "MilestoneDublin8Howth1.jpg")
        tags = [r["value"] for r in self.of(subject, "P113")]
        self.assertIn("inscription=P.O Dublin 8 Howth 1", tags)
        self.assertNotIn("wikimedia_commons", " ".join(tags))
        label = next(r["label_en"] for r in self.site.table("entities.csv") if r["id"] == subject)
        self.assertEqual(label, "Milestone Dublin 8 Howth 1")
        row = next(r for r in self.site.table("entities.csv") if r["id"] == subject)
        self.assertEqual(row["label_de"], "Milestone Dublin 8 Howth 1")
        self.assertEqual(row["description_en"], "Milestone, inscription \u201cP.O Dublin 8 Howth 1\u201d (OpenStreetMap node 6666122939)")
        self.assertEqual(row["description_de"], "Meilenstein, Inschrift \u201eP.O Dublin 8 Howth 1\u201c (OpenStreetMap-Node 6666122939)")

    def test_version_qualifiers(self) -> None:
        subject = next(r["id"] for r in self.idmap if r["key"] == "node/6666122939")
        sid = f"{subject}-P101-3"
        q = {r["property"]: r["value"] for r in self.qualifiers if r["sid"] == sid}
        self.assertEqual(q, {"P102": "3", "P103": "2024-02-26T13:33:57Z", "P104": "147932304", "P105": "b-unicycling", "P106": "1713634"})

    def test_second_run_changes_nothing(self) -> None:
        before = self.site.snapshot()
        code, out = self.site.run()
        self.assertEqual(code, 0)
        self.assertEqual(self.site.snapshot(), before)
        self.assertIn("0 file(s) written", out)

    def test_tables_read_back(self) -> None:
        problems: list[str] = []
        from wikibase_static import csvbuild
        found = csvbuild.read_set(self.site.csv, problems, "")
        self.assertEqual(problems, [])
        self.assertEqual(len([r for r in found.entities.rows if r.get("origin") == "osm"]), 21)


class SelectionRuns(unittest.TestCase):
    def setUp(self) -> None:
        self.site = Site(history=False)

    def tearDown(self) -> None:
        self.site.close()

    def statements(self, prop: str) -> list[dict[str, str]]:
        return [r for r in self.site.table("statements.csv") if r["property"] == prop]

    def test_leaving_and_entering_again(self) -> None:
        self.site.put("node", 5, [version(1, tags=GOOD), version(2, tags=GOOD), version(3, tags={"man_made": "survey_point"}),
                                  version(4, tags=GOOD)])
        code, _ = self.site.run()
        self.assertEqual(code, 0)
        since = self.statements("P107")
        self.assertEqual([r["value"] for r in since], [f"{URL}/node/5/history/1", f"{URL}/node/5/history/4"])
        until = {r["sid"]: r["value"] for r in self.site.table("qualifiers.csv") if r["property"] == "P108"}
        self.assertEqual(until, {since[0]["sid"]: f"{URL}/node/5/history/2"})
        names = [r["value"] for r in self.site.table("qualifiers.csv") if r["property"] == "P109"]
        self.assertEqual(names, ["benchmarks", "benchmarks"])

    def test_entry_in_a_later_version(self) -> None:
        self.site.put("node", 6, [version(1, tags={"man_made": "survey_point"}), version(2, tags=GOOD)])
        self.site.run()
        self.assertEqual([r["value"] for r in self.statements("P107")], [f"{URL}/node/6/history/2"])
        self.assertEqual(len(self.statements("P101")), 2)

    def test_never_met(self) -> None:
        self.site.put("node", 7, [version(1, tags={"highway": "milestone"})])
        _, out = self.site.run()
        self.assertEqual(self.statements("P107"), [])
        self.assertIn("element that never met the selection", out)

    def test_way_without_member_histories_is_an_item_without_a_shape(self) -> None:
        self.site.put("way", 8, [{"version": 1, "timestamp": "2020-01-01T10:00:00Z", "changeset": 1, "user": "u", "uid": 1,
                                  "nodes": [1, 2, 3], "tags": GOOD}])
        _, out = self.site.run()
        self.assertEqual(len(self.statements("P100")), 1)
        self.assertEqual(self.statements("P111"), [])
        self.assertIn("way without a shape (3 member histories not stored", out)

    def test_deleted_version_breaks_the_run(self) -> None:
        self.site.put("node", 9, [version(1, tags=GOOD), {"version": 2, "visible": False, "timestamp": "2020-01-02T10:00:00Z",
                                                          "changeset": 2, "user": "u", "uid": 1}, version(3, tags=GOOD)])
        self.site.run()
        self.assertEqual(len(self.statements("P107")), 2)
        self.assertEqual(len(self.statements("P101")), 2)

    def test_labels(self) -> None:
        cases = {10: ({**GOOD, "name": "Alpha"}, "Alpha"), 11: ({**GOOD, "name:en": "Beta"}, "Beta"),
                 12: (GOOD, "A b"), 13: ({"man_made": "survey_point"}, "OSM node 13")}
        for number, (tags, _) in cases.items():
            self.site.put("node", number, [version(1, tags=tags)])
        self.site.run()
        labels = {r["id"]: r["label_en"] for r in self.site.table("entities.csv")}
        ids = {r["key"]: r["id"] for r in self.site.table("idmap.csv")}
        for number, (_, expected) in cases.items():
            self.assertEqual(labels[ids[f"node/{number}"]], expected)

    def test_clean_title(self) -> None:
        from wikibase_static.step_import_osm import clean_title
        self.assertEqual(clean_title("Second_Presbyterian_Church,_Ballybay_-_geograph.org.uk_-_3013138.jpg"),
                         "Second Presbyterian Church, Ballybay")
        self.assertEqual(clean_title("MilestoneDublin9Howth.jpg"), "Milestone Dublin 9 Howth")
        self.assertEqual(clean_title("Milestone Old Dublin Road.jpg"), "Milestone Old Dublin Road")

    def test_inscription_label_and_german_fallback(self) -> None:
        self.site.put("node", 16, [version(1, tags={"man_made": "survey_point", "inscription": "LM 2"})])
        self.site.put("node", 17, [version(1, tags={"man_made": "survey_point"})])
        self.site.run()
        ids = {r["key"]: r["id"] for r in self.site.table("idmap.csv")}
        rows = {r["id"]: r for r in self.site.table("entities.csv")}
        self.assertEqual(rows[ids["node/16"]]["label_en"], "Benchmark LM 2")
        self.assertEqual(rows[ids["node/17"]]["label_en"], "OSM node 17")
        self.assertEqual(rows[ids["node/17"]]["label_de"], "OSM-Node 17")
        self.assertEqual(rows[ids["node/17"]]["description_de"], "Höhenmarke (OpenStreetMap-Node 17)")

    def test_commons_category_is_not_an_image(self) -> None:
        self.site.put("node", 14, [version(1, tags={**GOOD, "wikimedia_commons": "Category:Benchmarks"})])
        _, out = self.site.run()
        self.assertEqual(self.statements("P112"), [])
        self.assertIn("not a File:", out)

    def test_hand_row_wins(self) -> None:
        self.site.put("node", 15, [version(1, tags={**GOOD, "material": "stone"})])
        self.site.run()
        path = self.site.csv / "statements.csv"
        table = csvio.read_table(path, ["subject"], [])
        for row in table.rows:
            if row["property"] == "P113":
                row["origin"] = ""
                row["value"] = "material=granite"
        path.write_text(csvio.render_table(table.columns, table.rows), encoding="utf-8")
        self.site.run()
        values = [r["value"] for r in self.statements("P113")]
        self.assertIn("material=granite", values)
        self.assertNotIn("material=stone", values)

    def test_hand_described_element_is_reported(self) -> None:
        self.site.put("node", 16, [version(1, tags=GOOD)])
        with (self.site.csv / "entities.csv").open("a", encoding="utf-8", newline="") as handle:
            handle.write("Q900,item,,,Hand made,,,\n")
        with (self.site.csv / "statements.csv").open("a", encoding="utf-8", newline="") as handle:
            handle.write(f",Q900,P100,{URL}/node/16,,\n")
        _, out = self.site.run()
        self.assertIn("already described by hand as Q900", out)


class Problems(unittest.TestCase):
    def test_role_missing(self) -> None:
        site = Site()
        try:
            path = site.csv / "mapping" / "osm-properties.csv"
            lines = [l for l in path.read_text(encoding="utf-8").splitlines() if not l.startswith("tag,")]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            code, out = site.run()
            self.assertEqual(code, 2)
            self.assertIn("no row for tag", out)
        finally:
            site.close()

    def test_unknown_role_property(self) -> None:
        site = Site(history=False)
        try:
            site.put("node", 1, [version(1, tags=GOOD)])
            path = site.csv / "mapping" / "osm-properties.csv"
            path.write_text(path.read_text(encoding="utf-8").replace("tag,P113", "tag,P999"), encoding="utf-8")
            _, out = site.run()
            self.assertIn("tag -> P999 is not an entity of this site", out)
        finally:
            site.close()

    def test_empty_folder(self) -> None:
        site = Site(history=False)
        try:
            code, out = site.run()
            self.assertEqual(code, 0)
            self.assertIn("nothing to do", out)
        finally:
            site.close()

    def test_broken_json_gives_one_message_with_file_and_line(self) -> None:
        site = Site(history=False)
        try:
            (site.history / "node_5.json").write_text('{\n  "elements": [\n', encoding="utf-8")
            code, out = site.run()
            self.assertEqual(code, 2)
            self.assertEqual(len([l for l in out.splitlines() if l.startswith("ERROR")]), 1)
            self.assertIn("node_5.json:3:", out)
        finally:
            site.close()

    def test_wrong_file_name(self) -> None:
        site = Site(history=False)
        try:
            (site.history / "foo.json").write_text("{}", encoding="utf-8")
            code, out = site.run()
            self.assertEqual(code, 2)
            self.assertIn("foo.json", out)
        finally:
            site.close()


class CrmFeature(unittest.TestCase):
    def test_e25_is_known(self) -> None:
        self.assertEqual(crm.full_name("crm:E25"), "crm:E25_Human-Made_Feature")
        self.assertEqual(crm.label("crm:E25"), "E25 Human-Made Feature")
        self.assertEqual(crm.iri("crm:E25"), "http://www.cidoc-crm.org/cidoc-crm/E25_Human-Made_Feature")


if __name__ == "__main__":
    unittest.main()
