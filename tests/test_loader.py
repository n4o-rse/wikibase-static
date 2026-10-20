"""Tests for the loader, the validator and the load step (S2).

    python tests/test_loader.py

Standard library only. ``tests/fixtures/entities/`` holds one property for each
supported datatype and an item (Q1) with a statement of each, plus Q2 as its target.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import loader, step_load, utils  # noqa: E402
from wikibase_static.model import SUPPORTED_DATATYPES  # noqa: E402

FIXTURES = HERE / "fixtures"


class Workspace(unittest.TestCase):
    """A temporary copy of the fixtures as data/raw, so a test can break it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "data" / "raw"
        self.derived = Path(self.tmp.name) / "data" / "derived"
        shutil.copytree(FIXTURES / "entities", self.raw / "entities")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def load(self) -> loader.Site:
        return loader.load_site(self.raw, self.derived)

    def entity(self, name: str) -> dict:
        return json.loads((self.raw / "entities" / f"{name}.json").read_text(encoding="utf-8"))

    def save(self, name: str, data: dict) -> None:
        (self.raw / "entities" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


class ReadingTests(Workspace):
    def test_fixtures_load_without_problems(self) -> None:
        site = self.load()
        self.assertEqual(site.problems, [])
        self.assertEqual((len(site.entities), len(site.items), len(site.properties)), (12, 2, 10))
        self.assertEqual(site.statement_count(), 11)

    def test_every_supported_datatype_has_a_fixture_and_is_read(self) -> None:
        site = self.load()
        self.assertEqual({p.datatype for p in site.properties}, set(SUPPORTED_DATATYPES))
        self.assertEqual(set(site.datatype_counts()), set(SUPPORTED_DATATYPES))

    def test_values_keep_their_shape(self) -> None:
        q1 = self.load().entities["Q1"]
        by_property = {s.mainsnak.property: s.mainsnak for s in q1.statements if s.mainsnak.snaktype == "value"}
        self.assertEqual(by_property["P1"].entity_id, "Q2")
        self.assertEqual(by_property["P10"].entity_id, "P1")
        self.assertEqual(by_property["P8"].value["latitude"], 49.9929)
        self.assertEqual(by_property["P7"].value, {"text": "Beispiel", "language": "de"})
        self.assertEqual(by_property["P9"].value, "Example.jpg")          # a Commons file name, not converted
        self.assertTrue(by_property["P5"].value["time"].startswith("+2020"))
        somevalue = [s for s in q1.statements if s.mainsnak.snaktype == "somevalue"]
        self.assertEqual(len(somevalue), 1)
        self.assertIsNone(somevalue[0].mainsnak.value)

    def test_qualifiers_references_and_rank(self) -> None:
        statement = self.load().entities["Q1"].statements[0]
        self.assertEqual(statement.rank, "preferred")
        self.assertEqual([q.property for q in statement.qualifiers], ["P2"])
        self.assertEqual([[s.property for s in ref] for ref in statement.references], [["P4"]])

    def test_statements_are_in_numeric_property_order(self) -> None:
        properties = [s.mainsnak.property for s in self.load().entities["Q1"].statements]
        self.assertEqual(properties, ["P1", "P2", "P3", "P4", "P5", "P5", "P6", "P7", "P8", "P9", "P10"])  # P2 before P10

    def test_entities_are_ordered_items_first_then_numerically(self) -> None:
        self.assertEqual(list(self.load().entities), ["Q1", "Q2"] + [f"P{n}" for n in range(1, 11)])

    def test_entitydata_form_is_read(self) -> None:
        wrapped = {"entities": {"Q3": {"type": "item", "id": "Q3", "labels": {"en": {"language": "en", "value": "Wrapped"}}, "claims": {}}}}
        (self.raw / "entities" / "Q3.json").write_text(json.dumps(wrapped), encoding="utf-8")
        site = self.load()
        self.assertEqual(site.entities["Q3"].labels, {"en": "Wrapped"})


class ValidationTests(Workspace):
    def test_broken_json_is_a_warning_not_a_crash(self) -> None:
        (self.raw / "entities" / "Q3.json").write_text("{not json", encoding="utf-8")
        site = self.load()
        self.assertEqual(len(site.entities), 12)
        self.assertEqual(len(site.problems), 1)
        self.assertIn("data/raw/entities/Q3.json: not readable as JSON", site.problems[0])

    def test_file_without_id_and_foreign_entity_types(self) -> None:
        self.save("X1", {"labels": {}})
        self.save("L1", {"type": "lexeme", "id": "L1"})
        site = self.load()
        self.assertEqual(len(site.entities), 12)
        text = "\n".join(site.problems)
        self.assertIn("X1.json: no entity id", text)
        self.assertIn("L1 is not an item or property id", text)

    def test_missing_reference_is_reported_once_with_its_referrers(self) -> None:
        for name in ("Q3", "Q4"):
            data = self.entity("Q1")
            data["id"] = name
            data["claims"]["P1"][0]["mainsnak"]["datavalue"]["value"] = {"entity-type": "item", "numeric-id": 99, "id": "Q99"}
            self.save(name, data)
        problems = self.load().problems
        self.assertEqual([p for p in problems if "Q99" in p], ["Q99 is referenced by Q3, Q4 but has no data"])

    def test_missing_property_is_reported(self) -> None:
        (self.raw / "entities" / "P2.json").unlink()
        problems = self.load().problems
        self.assertIn("P2 is referenced by Q1 but has no data", problems)

    def test_datatype_and_value_mismatch(self) -> None:
        data = self.entity("Q1")
        data["claims"]["P2"][0]["mainsnak"]["datatype"] = "wikibase-item"
        self.save("Q1", data)
        self.assertTrue(any("P2 has datatype wikibase-item but a string value" in p for p in self.load().problems))

    def test_malformed_value(self) -> None:
        data = self.entity("Q1")
        data["claims"]["P8"][0]["mainsnak"]["datavalue"]["value"] = {"latitude": 1.0}
        self.save("Q1", data)
        self.assertTrue(any("malformed globecoordinate value" in p for p in self.load().problems))

    def test_value_snak_without_datavalue(self) -> None:
        data = self.entity("Q1")
        del data["claims"]["P3"][0]["mainsnak"]["datavalue"]
        self.save("Q1", data)
        self.assertTrue(any("snaktype value but no datavalue" in p for p in self.load().problems))

    def test_unsupported_datatype_is_reported_and_kept(self) -> None:
        prop = self.entity("P9")
        prop["datatype"] = "tabular-data"
        self.save("P9", prop)
        site = self.load()
        self.assertIn("P9", site.entities)
        self.assertTrue(any("tabular-data" in p and "cannot show" in p for p in site.problems))

    def test_file_name_and_duplicate(self) -> None:
        shutil.copy(self.raw / "entities" / "Q2.json", self.raw / "entities" / "Q7.json")
        shutil.copytree(self.raw / "entities", self.derived / "entities")
        text = "\n".join(self.load().problems)
        self.assertIn("Q7.json: holds Q2, but the file is named Q7", text)
        self.assertIn("is already loaded from data/raw/entities", text)

    def test_manifest_is_compared_with_the_files(self) -> None:
        rows = {n: {"lastrevid": 1, "modified": "2026-01-01T00:00:00Z", "sha256": "x"} for n in ("Q1", "Q2", "Q5")}
        (self.raw / "manifest.json").write_text(json.dumps(
            {"source": {"url": "https://example.org"}, "entities": rows, "latest_modified": "2026-01-01T00:00:00Z"}), encoding="utf-8")
        site = self.load()
        self.assertEqual(site.source_url, "https://example.org")
        text = "\n".join(site.problems)
        self.assertIn("lists Q5, but it could not be loaded", text)
        self.assertIn("P1.json: not listed in the manifest", text)

    def test_problems_are_deterministic(self) -> None:
        (self.raw / "entities" / "Q3.json").write_text("{not json", encoding="utf-8")
        (self.raw / "entities" / "P2.json").unlink()
        self.assertEqual(self.load().problems, self.load().problems)
        self.assertEqual(self.load().problems, sorted(self.load().problems))


class LabelTests(Workspace):
    def test_language_order_fallback_and_bare_id(self) -> None:
        site = self.load()
        self.assertEqual(site.labeller(["de", "en"]).label("Q2"), "Beispielklasse")
        self.assertEqual(site.labeller(["en", "de"]).label("Q2"), "Example class")
        self.assertEqual(site.labeller(["de"]).label("Q1"), "Example site")      # no de label: any language beats the id
        resolver = site.labeller(["en"])
        self.assertEqual(resolver.label("Q99"), "Q99")                          # not in the site: shown as itself
        self.assertFalse(resolver.has_label("Q99"))
        self.assertTrue(resolver.has_label("Q1"))


class StepTests(Workspace):
    def run_step(self, *args: str) -> tuple[int, str]:
        saved = utils.DATA_RAW, utils.DATA_DERIVED
        utils.DATA_RAW, utils.DATA_DERIVED = self.raw, self.derived
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = step_load.main(list(args))
        finally:
            utils.DATA_RAW, utils.DATA_DERIVED = saved
        return code, out.getvalue()

    def test_report_names_the_counts(self) -> None:
        code, out = self.run_step()
        self.assertEqual(code, 0)
        self.assertIn("[load] 12 entities (2 items, 10 properties) from 12 file(s)", out)
        self.assertIn("11 statements:", out)
        self.assertIn("globe-coordinate 1", out)
        self.assertIn("[load] 0 warning(s)", out)
        self.assertNotIn("WARN", out)

    def test_report_is_identical_on_a_second_run(self) -> None:
        self.assertEqual(self.run_step(), self.run_step())

    def test_warnings_start_with_warn_so_strict_sees_them(self) -> None:
        (self.raw / "entities" / "Q3.json").write_text("{not json", encoding="utf-8")
        code, out = self.run_step()
        self.assertEqual(code, 0)
        self.assertIn("WARN: [load] data/raw/entities/Q3.json: not readable as JSON", out)
        self.assertIn("[load] 1 warning(s)", out)

    def test_warning_list_is_capped_unless_all(self) -> None:
        for n in range(60):
            (self.raw / "entities" / f"Q{100 + n}.json").write_text("{bad", encoding="utf-8")
        _code, out = self.run_step()
        self.assertEqual(out.count("WARN:"), step_load.SHOWN)
        self.assertIn("10 more warnings not shown (use --all)", out)
        _code, out = self.run_step("--all")
        self.assertEqual(out.count("WARN:"), 60)

    def test_empty_data_is_nothing_to_do(self) -> None:
        shutil.rmtree(self.raw)
        code, out = self.run_step()
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)
        self.assertNotIn("WARN", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
