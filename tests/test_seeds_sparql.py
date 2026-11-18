"""Tests for ``seeds-from-sparql`` (S14a): queries and ids -> ``seeds-wikidata.csv``.

    python tests/test_seeds_sparql.py

Standard library only. The answers of the Query Service are **synthetic** (invented ids and labels, in the shape of the
SPARQL JSON result); the network is a fake client that counts the calls.
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

from wikibase_static import step_seeds_sparql as seeds  # noqa: E402

WD = "http://www.wikidata.org/entity/"


def binding(qid: str, label: str | None = None, kind: str | None = None, note: str | None = None) -> dict:
    out = {"item": {"type": "uri", "value": WD + qid}}
    if label is not None:
        out["itemLabel"] = {"type": "literal", "value": label}
    if kind is not None:
        out["kind"] = {"type": "literal", "value": kind}
    if note is not None:
        out["note"] = {"type": "literal", "value": note}
    return out


def answer(*bindings: dict, variables=("item", "itemLabel")) -> dict:
    return {"head": {"vars": list(variables)}, "results": {"bindings": list(bindings)}}


STONES = answer(binding("Q9000003", "Stone three"), binding("Q9000001", "Stone one"), binding("Q9000002", "Q9000002"))


class FakeClient:
    api = "https://query.invalid/sparql"

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def get(self, params: dict, kind: str) -> dict:
        self.calls.append((kind, params["query"]))
        return self.answers[kind]


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.dir = self.folder / "data" / "seeds"
        self.dir.mkdir(parents=True)
        (self.dir / "wikidata-stones.rq").write_text("SELECT ?item ?itemLabel WHERE { ?item wdt:P31 wd:Q9000010 }\n", encoding="utf-8")
        self.output = self.folder / "data" / "csv" / "seeds-wikidata.csv"
        self.raw = self.folder / "data" / "raw" / "wikidata-seeds"

    def run_step(self, *extra: str, client=None) -> tuple[int, str]:
        args = ["--seeds-dir", str(self.dir), "--raw", str(self.raw), "--output", str(self.output), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = seeds.main(args, client=client)
        return code, out.getvalue()

    def rows(self) -> list[dict[str, str]]:
        with self.output.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def online(self, **answers: dict) -> tuple[int, str, FakeClient]:
        client = FakeClient(answers or {"stones": STONES})
        code, out = self.run_step(client=client)
        return code, out, client


class Online(Case):
    def test_the_query_is_run_and_the_list_is_written_sorted_by_number(self) -> None:
        code, out, client = self.online()
        self.assertEqual(code, 0, out)
        self.assertEqual([c[0] for c in client.calls], ["stones"])
        self.assertIn("wdt:P31", client.calls[0][1])
        self.assertEqual([r["qid"] for r in self.rows()], ["Q9000001", "Q9000002", "Q9000003"])
        self.assertEqual({r["kind"] for r in self.rows()}, {"stones"})
        self.assertEqual(self.output.read_text(encoding="utf-8").splitlines()[0], "qid,kind,note,instance_of")

    def test_the_label_becomes_the_note_but_not_an_id_that_stands_for_a_missing_label(self) -> None:
        self.online()
        notes = {r["qid"]: r["note"] for r in self.rows()}
        self.assertEqual(notes, {"Q9000001": "Stone one", "Q9000002": "", "Q9000003": "Stone three"})

    def test_kind_and_note_variables_win_over_the_defaults(self) -> None:
        self.online(stones=answer(binding("Q9000001", "label", kind="cross-slab", note="my note"), variables=("item", "itemLabel", "kind", "note")))
        self.assertEqual(self.rows()[0]["kind"], "cross-slab")
        self.assertEqual(self.rows()[0]["note"], "my note")

    def test_the_answer_is_stored_and_a_second_run_changes_nothing(self) -> None:
        self.online()
        stored = (self.raw / "stones.json").read_text(encoding="utf-8")
        self.assertIn("wikidata.org/entity/Q9000001", stored)
        before = self.output.read_bytes()
        code, out, _client = self.online()
        self.assertEqual(code, 0)
        self.assertIn("answer unchanged", out)
        self.assertIn("is up to date", out)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual((self.raw / "stones.json").read_text(encoding="utf-8"), stored)

    def test_the_order_of_the_bindings_does_not_matter_for_the_stored_file(self) -> None:
        self.online()
        first = (self.raw / "stones.json").read_text(encoding="utf-8")
        reversed_answer = answer(*reversed(STONES["results"]["bindings"]))
        self.online(stones=reversed_answer)
        self.assertEqual((self.raw / "stones.json").read_text(encoding="utf-8"), first)

    def test_only_wikidata_items_count(self) -> None:
        odd = answer(binding("Q9000001", "one"), {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/P18"}},
                     {"item": {"type": "uri", "value": "https://example.org/Q5"}}, {"item": {"type": "literal", "value": "Q7"}}, {})
        self.online(stones=odd)
        self.assertEqual([r["qid"] for r in self.rows()], ["Q9000001"])

    def test_a_query_without_the_item_variable_is_refused(self) -> None:
        code, out, _client = self.online(stones=answer(binding("Q1"), variables=("thing",)))
        self.assertEqual(code, 2)
        self.assertIn("no variable ?item", out)
        self.assertFalse(self.output.exists())


class Sources(Case):
    def test_listed_ids_come_after_the_queries_and_carry_their_note(self) -> None:
        (self.dir / "wikidata-qids.txt").write_text("# the ones we know\nQ9000005  a special stone  # trailing comment\nQ9000001\nQ9000004\n", encoding="utf-8")
        self.online()
        rows = {r["qid"]: r for r in self.rows()}
        self.assertEqual(sorted(rows), ["Q9000001", "Q9000002", "Q9000003", "Q9000004", "Q9000005"])
        self.assertEqual((rows["Q9000005"]["kind"], rows["Q9000005"]["note"]), ("listed", "a special stone"))
        self.assertEqual(rows["Q9000001"]["kind"], "stones")        # the query came first

    def test_an_id_named_twice_is_reported(self) -> None:
        (self.dir / "wikidata-qids.txt").write_text("Q9000001\n", encoding="utf-8")
        _code, out, _client = self.online()
        self.assertIn("named by more than one source", out)

    def test_a_bad_id_in_the_list_is_refused_with_its_line(self) -> None:
        (self.dir / "wikidata-qids.txt").write_text("Q1\nP18\n", encoding="utf-8")
        code, out, _client = self.online()
        self.assertEqual(code, 2)
        self.assertIn("wikidata-qids.txt:2", out)

    def test_two_queries_run_in_the_order_of_their_names(self) -> None:
        (self.dir / "wikidata-a-first.rq").write_text("SELECT ?item WHERE { ?item wdt:P31 wd:Q1 }", encoding="utf-8")
        _code, _out, client = self.online(**{"stones": STONES, "a-first": answer(binding("Q9000001", "x"))})
        self.assertEqual([c[0] for c in client.calls], ["a-first", "stones"])
        self.assertEqual({r["qid"]: r["kind"] for r in self.rows()}["Q9000001"], "a-first")

    def test_a_folder_without_sources_has_nothing_to_do(self) -> None:
        (self.dir / "wikidata-stones.rq").unlink()
        code, out = self.run_step()
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)


class Keeping(Case):
    def test_note_and_instance_of_of_a_seed_that_stays_are_kept(self) -> None:
        self.online()
        rows = self.rows()
        rows[0]["note"], rows[0]["instance_of"] = "by hand", "Q106"
        self.output.write_text("qid,kind,note,instance_of\n" + "".join(f"{r['qid']},{r['kind']},{r['note']},{r['instance_of']}\n" for r in rows), encoding="utf-8")
        self.online()
        self.assertEqual((self.rows()[0]["note"], self.rows()[0]["instance_of"]), ("by hand", "Q106"))

    def test_a_seed_that_no_source_names_any_more_is_dropped_and_said(self) -> None:
        self.online()
        _code, out, _client = self.online(stones=answer(binding("Q9000001", "Stone one")))
        self.assertEqual([r["qid"] for r in self.rows()], ["Q9000001"])
        self.assertIn("2 dropped", out)
        self.assertIn("Q9000002, Q9000003", out)

    def test_a_list_that_is_far_too_long_stops_before_anything_is_written(self) -> None:
        code, out = self.run_step("--max-seeds", "2", client=FakeClient({"stones": STONES}))
        self.assertEqual(code, 2)
        self.assertIn("--max-seeds", out)
        self.assertFalse(self.output.exists())


class Offline(Case):
    def test_offline_uses_the_stored_answers_and_never_asks(self) -> None:
        self.online()
        self.output.unlink()
        client = FakeClient({})
        code, _out = self.run_step("--offline", client=client)
        self.assertEqual(code, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(len(self.rows()), 3)

    def test_offline_without_a_stored_answer_names_the_query(self) -> None:
        code, out = self.run_step("--offline")
        self.assertEqual(code, 2)
        self.assertIn("no stored answer for stones", out)

    def test_dry_run_writes_nothing(self) -> None:
        self.online()
        self.output.unlink()
        code, out = self.run_step("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("would change", out)
        self.assertFalse(self.output.exists())

    def test_from_dir_stores_a_file_saved_in_the_browser(self) -> None:
        saved = self.folder / "saved"
        saved.mkdir()
        (saved / "stones.json").write_text(json.dumps(STONES), encoding="utf-8")
        code, out = self.run_step("--from-dir", str(saved))
        self.assertEqual(code, 0, out)
        self.assertTrue((self.raw / "stones.json").is_file())
        self.assertEqual(len(self.rows()), 3)

    def test_from_dir_with_a_file_that_is_no_sparql_result_is_refused(self) -> None:
        saved = self.folder / "saved"
        saved.mkdir()
        (saved / "stones.json").write_text('{"entities": {}}', encoding="utf-8")
        code, out = self.run_step("--from-dir", str(saved))
        self.assertEqual(code, 2)
        self.assertIn("not a SPARQL JSON result", out)

    def test_from_dir_and_dry_run_exclude_each_other(self) -> None:
        code, out = self.run_step("--from-dir", str(self.folder), "--dry-run")
        self.assertEqual(code, 2)


class Chain(Case):
    def test_the_list_is_what_import_wikidata_reads(self) -> None:
        from wikibase_static import step_import_wikidata as imp
        (self.dir / "wikidata-qids.txt").write_text("Q9000009  listed note\n", encoding="utf-8")
        self.online()
        read = imp.read_seeds(self.output)
        self.assertEqual([s["qid"] for s in read], ["Q9000001", "Q9000002", "Q9000003", "Q9000009"])
        self.assertEqual(read[0]["instance_of"], "")


if __name__ == "__main__":
    unittest.main()
