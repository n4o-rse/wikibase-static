"""Offline tests for the harvest step (S4): a small fake Wikibase on localhost.

    python tests/test_harvest.py

Standard library only. Nothing here touches the network beyond 127.0.0.1.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py"))

from wikibase_static import step_harvest, utils  # noqa: E402


class FakeWikibase:
    """State of the fake source: entities, a mode, and a log of the requests it got."""

    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}
        self.mode = "ok"          # ok | anubis | maxlag-once
        self.requests: list[dict] = []
        self._lagged = False
        for n in range(1, 6):
            self.put(f"Q{n}", f"Item {n}")
        for n in range(1, 3):
            self.put(f"P{n}", f"Property {n}")

    def put(self, entity_id: str, label: str, rev: int | None = None) -> None:
        old = self.entities.get(entity_id)
        rev = rev if rev is not None else (old["lastrevid"] + 1 if old else 100)
        self.entities[entity_id] = {
            "id": entity_id, "type": "property" if entity_id[0] == "P" else "item",
            "lastrevid": rev, "modified": f"2026-10-{10 + rev % 10:02d}T08:00:00Z",
            "labels": {"en": {"language": "en", "value": label}}, "claims": {},
        }

    def handle(self, params: dict[str, str]) -> tuple[int, dict, bytes]:
        self.requests.append(params)
        if self.mode == "anubis":
            return 200, {"Content-Type": "text/html"}, b"<html><title>Making sure you're not a bot!</title>Protected by Anubis</html>"
        if self.mode == "maxlag-once" and not self._lagged:
            self._lagged = True
            body = json.dumps({"error": {"code": "maxlag", "info": "lagged"}}).encode()
            return 200, {"Content-Type": "application/json", "Retry-After": "0"}, body
        action = params.get("action")
        if action == "query" and params.get("meta") == "siteinfo":
            data = {"query": {"general": {"generator": "MediaWiki 1.43.0"}, "namespaces": {
                "0": {"id": 0, "defaultcontentmodel": "wikitext"},
                "120": {"id": 120, "defaultcontentmodel": "wikibase-item"},
                "122": {"id": 122, "defaultcontentmodel": "wikibase-property"}}}}
        elif action == "query" and params.get("generator") == "allpages":
            ns = int(params["gapnamespace"])
            prefix = "Q" if ns == 120 else "P"
            ids = sorted(i for i in self.entities if i[0] == prefix)
            limit = 2  # small on purpose: exercises continuation
            start = int(params.get("gapcontinue", "0"))
            chunk = ids[start:start + limit]
            pages = {str(1000 + start + k): {"pageid": 1000 + start + k, "ns": ns,
                                              "title": ("Item:" if prefix == "Q" else "Property:") + eid,
                                              "lastrevid": self.entities[eid]["lastrevid"]}
                     for k, eid in enumerate(chunk)}
            data = {"batchcomplete": "", "query": {"pages": pages}}
            if start + limit < len(ids):
                data["continue"] = {"gapcontinue": str(start + limit), "continue": "gapcontinue||"}
        elif action == "wbgetentities":
            wanted = params["ids"].split("|")
            data = {"entities": {i: (self.entities[i] if i in self.entities else {"id": i, "missing": ""}) for i in wanted}}
        else:
            data = {"error": {"code": "badvalue", "info": "unknown action"}}
        return 200, {"Content-Type": "application/json"}, json.dumps(data).encode()


def make_server(fake: FakeWikibase) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            if url.path != "/w/api.php":
                self.send_response(404)
                self.end_headers()
                return
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            params["_ua"] = self.headers.get("User-Agent", "")
            status, headers, body = fake.handle(params)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def snapshot(raw: Path) -> dict[str, bytes]:
    return {str(p.relative_to(raw)): p.read_bytes() for p in sorted(raw.rglob("*")) if p.is_file()}


class HarvestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeWikibase()
        self.server = make_server(self.fake)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "data" / "raw"
        self.saved = utils.DATA_RAW
        utils.DATA_RAW = self.raw

    def tearDown(self) -> None:
        utils.DATA_RAW = self.saved
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def run_harvest(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = step_harvest.main(["--delay", "0", *args])
        return code, out.getvalue()

    def test_first_run_then_nothing_to_do(self) -> None:
        code, out = self.run_harvest("--url", self.url)
        self.assertEqual(code, 0, out)
        self.assertIn("listed 7 entities (5 items, 2 properties)", out)
        self.assertIn("7 changed, 0 deleted, 0 unchanged", out)
        self.assertEqual(len(list((self.raw / "entities").glob("*.json"))), 7)
        manifest = json.loads((self.raw / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"]["namespaces"], {"item": 120, "property": 122})
        self.assertEqual(manifest["entities"]["Q1"]["lastrevid"], 100)
        before = snapshot(self.raw)

        self.fake.requests.clear()
        code, out = self.run_harvest()  # url comes from the manifest
        self.assertEqual(code, 0, out)
        self.assertIn("0 changed, 0 deleted, 7 unchanged (nothing written)", out)
        self.assertEqual(snapshot(self.raw), before)
        kinds = [r.get("generator") or r.get("action") for r in self.fake.requests]
        self.assertNotIn("wbgetentities", kinds)
        self.assertNotIn("siteinfo", [r.get("meta") for r in self.fake.requests])
        self.assertIn("requests: 4 (list 4)", out)  # 2 namespaces x 2 pages of 2-3 entries

    def test_user_agent_names_the_tool_and_contact(self) -> None:
        self.run_harvest("--url", self.url, "--contact", "mailto:someone@example.org")
        agents = {r["_ua"] for r in self.fake.requests}
        self.assertEqual(len(agents), 1)
        agent = agents.pop()
        self.assertTrue(agent.startswith("wikibase-static/"))
        self.assertIn("mailto:someone@example.org", agent)

    def test_changed_deleted_and_hand_edited(self) -> None:
        self.run_harvest("--url", self.url)
        self.fake.put("Q2", "Item 2 renamed")
        del self.fake.entities["Q5"]
        (self.raw / "entities" / "Q3.json").write_text("{}\n", encoding="utf-8")  # hand-edited
        code, out = self.run_harvest()
        self.assertEqual(code, 0, out)
        self.assertIn("2 changed, 1 deleted, 4 unchanged", out)
        self.assertFalse((self.raw / "entities" / "Q5.json").exists())
        q2 = json.loads((self.raw / "entities" / "Q2.json").read_text(encoding="utf-8"))
        self.assertEqual(q2["labels"]["en"]["value"], "Item 2 renamed")
        q3 = json.loads((self.raw / "entities" / "Q3.json").read_text(encoding="utf-8"))
        self.assertEqual(q3["id"], "Q3")

    def test_bot_challenge_stops_cleanly(self) -> None:
        self.fake.mode = "anubis"
        code, out = self.run_harvest("--url", self.url)
        self.assertEqual(code, step_harvest.EXIT_CHALLENGE)
        self.assertIn("bot challenge", out)
        self.assertIn("--from-dir", out)
        self.assertFalse(self.raw.exists() and any(self.raw.iterdir()))

    def test_probe_makes_one_request_and_writes_nothing(self) -> None:
        code, out = self.run_harvest("--url", self.url, "--probe")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertIn("nothing written", out)
        self.assertFalse(self.raw.exists() and any(self.raw.iterdir()))

    def test_probe_reports_challenge(self) -> None:
        self.fake.mode = "anubis"
        code, out = self.run_harvest("--url", self.url, "--probe")
        self.assertEqual(code, step_harvest.EXIT_CHALLENGE)
        self.assertEqual(len(self.fake.requests), 1)

    def test_maxlag_is_retried(self) -> None:
        self.fake.mode = "maxlag-once"
        code, out = self.run_harvest("--url", self.url)
        self.assertEqual(code, 0, out)
        self.assertIn("host busy", out)
        self.assertIn("7 changed", out)
        self.assertTrue(all(r.get("maxlag") == "5" for r in self.fake.requests))

    def test_other_source_is_refused(self) -> None:
        self.run_harvest("--url", self.url)
        code, out = self.run_harvest("--url", "http://127.0.0.1:1")
        self.assertEqual(code, 1)
        self.assertIn("already holds", out)

    def test_from_dir_accepts_three_shapes(self) -> None:
        folder = Path(self.tmp.name) / "saved"
        folder.mkdir()
        q1 = self.fake.entities["Q1"]
        (folder / "Q1.json").write_text(json.dumps({"entities": {"Q1": q1}}), encoding="utf-8")   # Special:EntityData
        (folder / "wbget.json").write_text(json.dumps({"entities": {"Q2": self.fake.entities["Q2"],
                                                                      "P1": self.fake.entities["P1"]}}), encoding="utf-8")
        (folder / "bare.json").write_text(json.dumps(self.fake.entities["Q3"]), encoding="utf-8")
        (folder / "broken.json").write_text("{not json", encoding="utf-8")
        code, out = self.run_harvest("--from-dir", str(folder))
        self.assertEqual(code, 0, out)
        self.assertIn("WARN: [harvest] broken.json: skipped", out)
        self.assertIn("4 changed (4 new, 0 updated), 0 unchanged, 1 skipped", out)
        self.assertIn("requests: 0", out)
        before = snapshot(self.raw)
        code, out = self.run_harvest("--from-dir", str(folder))
        self.assertIn("0 changed (0 new, 0 updated), 4 unchanged", out)
        self.assertEqual(snapshot(self.raw), before)
        self.assertEqual(self.fake.requests, [])

    def test_output_is_canonical(self) -> None:
        self.run_harvest("--url", self.url)
        text = (self.raw / "entities" / "Q1.json").read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertNotIn("\r", text)
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
