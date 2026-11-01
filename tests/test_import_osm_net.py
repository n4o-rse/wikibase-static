"""Tests for the network part of ``import-osm`` (S5): plan, requests, byte-exact storage, second run, version jump, leaving, probe.

    python tests/test_import_osm_net.py

Standard library only. A fake transport plays Overpass and the OSM API with the 21 history files of tests/fixtures/osm/history;
no test touches the network, and none sleeps.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import osm_net, step_import_osm as imp  # noqa: E402

FIXTURES = HERE / "fixtures" / "osm"
QUERY = '[out:json][timeout:180];\n(\n  area(3600062273)->.roi;\n);\n(\n  nwr(area.roi)["man_made"="survey_point"];\n);\nout meta;'


class Fake:
    """Overpass and API in one: ``histories`` maps a key to the bytes of its history answer."""

    def __init__(self) -> None:
        self.histories: dict[str, bytes] = {}
        self.overpass_answer: bytes | None = None
        self.log: list[tuple[str, str]] = []
        self.busy_once = False
        for path in sorted((FIXTURES / "history").glob("*.json")):
            self.histories[path.stem.replace("_", "/", 1)] = path.read_bytes()

    def versions(self) -> dict[str, int]:
        return {k: max(e["version"] for e in json.loads(b)["elements"]) for k, b in self.histories.items()}

    def overpass(self, only: set[str] | None = None) -> bytes:
        elements = [{"type": k.split("/")[0], "id": int(k.split("/")[1]), "version": v} for k, v in sorted(self.versions().items())
                    if only is None or k in only]
        return json.dumps({"version": 0.6, "generator": "fake", "elements": elements}).encode("utf-8")

    def __call__(self, request, timeout):
        url = request.full_url
        if "interpreter" in url:
            self.log.append(("overpass", url))
            if self.busy_once:
                self.busy_once = False
                return 429, {"Retry-After": "1"}, b"busy"
            return 200, {}, self.overpass_answer if self.overpass_answer is not None else self.overpass()
        key = "/".join(urllib.parse.urlparse(url).path.split("/")[3:5])
        self.log.append(("history", key))
        if key not in self.histories:
            return 404, {}, b"not found"
        return 200, {}, self.histories[key]

    def kinds(self) -> list[str]:
        return [k for k, _ in self.log]


class Site:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.csv = self.root / "data" / "csv"
        (self.csv / "mapping").mkdir(parents=True)
        for name in ("entities.csv", "statements.csv", "qualifiers.csv"):
            shutil.copy(FIXTURES / "model" / name, self.csv / name)
        shutil.copy(FIXTURES / "model" / "osm-properties.csv", self.csv / "mapping" / "osm-properties.csv")
        self.seeds = self.root / "data" / "seeds"
        self.seeds.mkdir(parents=True)
        shutil.copy(FIXTURES / "model" / "benchmarks.csv", self.seeds / "benchmarks.csv")
        (self.seeds / "overpass-benchmarks.overpassql").write_text(QUERY, encoding="utf-8")
        self.history = self.root / "data" / "raw" / "osm" / "history"
        self.overpass_file = self.root / "data" / "raw" / "osm" / "overpass" / "benchmarks.json"
        self.fake = Fake()
        self.sleeps: list[float] = []

    def close(self) -> None:
        self.tmp.cleanup()

    def run(self, *extra: str) -> tuple[int, str]:
        imp.CLIENT_FACTORY = lambda: osm_net.OsmClient("test-agent", delay=0, transport=self.fake, sleep=self.sleeps.append)
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                code = imp.main(["--csv", str(self.csv), "--from-dir", str(self.history), "--mapping", str(self.csv / "mapping" / "osm-properties.csv"),
                                 "--seeds", str(self.seeds), "--overpass-file", str(self.overpass_file),
                                 "--members-dir", str(self.root / "data" / "raw" / "osm" / "members"), *extra])
        finally:
            imp.CLIENT_FACTORY = None
        return code, buffer.getvalue()

    def snapshot(self) -> dict[str, bytes]:
        files = [*self.csv.glob("*.csv"), *self.history.glob("*.json"), self.overpass_file]
        return {str(p.relative_to(self.root)): p.read_bytes() for p in sorted(files) if p.is_file()}


class FirstAndSecondRun(unittest.TestCase):
    def setUp(self) -> None:
        self.site = Site()

    def tearDown(self) -> None:
        self.site.close()

    def test_first_run_fetches_everything_byte_for_byte(self) -> None:
        code, out = self.site.run()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.site.fake.kinds().count("overpass"), 1)
        self.assertEqual(self.site.fake.kinds().count("history"), 21)
        for path in sorted((FIXTURES / "history").glob("*.json")):
            self.assertEqual((self.site.history / path.name).read_bytes(), path.read_bytes())
        self.assertIn("21 new element(s) with 59 version(s)", out)
        self.assertIn("items: 21 (21 node); 59 version statement(s)", out)
        self.assertTrue(self.site.overpass_file.is_file())

    def test_second_run_asks_overpass_only_and_changes_nothing(self) -> None:
        self.site.run()
        before = self.site.snapshot()
        self.site.fake.log.clear()
        code, out = self.site.run()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.site.fake.log[0][0], "overpass")
        self.assertEqual(self.site.fake.kinds(), ["overpass"])
        self.assertEqual(self.site.snapshot(), before)
        self.assertIn("unchanged 21", out)
        self.assertIn("0 file(s) written", out)

    def test_probe_sends_one_request_and_writes_nothing(self) -> None:
        code, out = self.site.run("--probe")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.site.fake.kinds(), ["overpass"])
        self.assertFalse(self.site.history.exists())
        self.assertFalse(self.site.overpass_file.exists())
        self.assertIn("21 history request(s) would follow", out)

    def test_limit_spreads_the_first_run(self) -> None:
        _, out = self.site.run("--limit", "8")
        self.assertEqual(self.site.fake.kinds().count("history"), 8)
        self.assertIn("13 element(s) are left for the next run", out)
        self.site.fake.log.clear()
        self.site.run("--limit", "50")
        self.assertEqual(self.site.fake.kinds().count("history"), 13)
        self.assertEqual(len(list(self.site.history.glob("*.json"))), 21)

    def test_busy_host_is_waited_for(self) -> None:
        self.site.fake.busy_once = True
        code, out = self.site.run()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.site.fake.kinds().count("overpass"), 2)
        self.assertIn(1, self.site.sleeps)
        self.assertIn("host busy (HTTP 429)", out)


class Changes(unittest.TestCase):
    def setUp(self) -> None:
        self.site = Site()
        self.site.run()
        self.key = "node/6666122939"

    def tearDown(self) -> None:
        self.site.close()

    def bump(self, tags: dict) -> bytes:
        data = json.loads(self.site.fake.histories[self.key])
        last = data["elements"][-1]
        data["elements"].append({**last, "version": last["version"] + 1, "timestamp": "2026-11-02T10:00:00Z", "changeset": 9, "tags": tags})
        raw = json.dumps(data).encode("utf-8")
        self.site.fake.histories[self.key] = raw
        return raw

    def test_a_new_version_costs_one_history_request(self) -> None:
        raw = self.bump({**json.loads(self.site.fake.histories[self.key])["elements"][-1]["tags"], "note": "new"})
        self.site.fake.log.clear()
        code, out = self.site.run()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.site.fake.kinds(), ["overpass", "history"])
        self.assertEqual((self.site.history / "node_6666122939.json").read_bytes(), raw)
        self.assertIn("1 known element(s) with 1 new version(s)", out)
        self.assertIn("60 version statement(s)", out)

    def test_leaving_the_selection_by_tags_sets_until(self) -> None:
        self.bump({"highway": "milestone"})
        self.site.run()
        text = (self.site.csv / "qualifiers.csv").read_text(encoding="utf-8")
        self.assertIn("/node/6666122939/history/3", text)
        self.assertTrue(any("P108" in line and "history/3" in line for line in text.splitlines()))

    def test_leaving_the_area_sets_until(self) -> None:
        only = set(self.site.fake.histories) - {self.key}
        self.site.fake.overpass_answer = self.site.fake.overpass(only)
        _, out = self.site.run()
        self.assertIn("no longer in the answer", out)
        self.assertIn("1 element(s) left the selection area", out)
        lines = [l for l in (self.site.csv / "qualifiers.csv").read_text(encoding="utf-8").splitlines() if ",P108," in l]
        self.assertEqual(len(lines), 1)
        self.assertIn("history/3", lines[0])
        # it comes back: the marker goes again
        self.site.fake.overpass_answer = None
        self.site.run()
        self.assertEqual([l for l in (self.site.csv / "qualifiers.csv").read_text(encoding="utf-8").splitlines() if ",P108," in l], [])


class Refresh(unittest.TestCase):
    def test_refresh_replaces_reindented_files_and_compares(self) -> None:
        site = Site()
        try:
            site.run()
            for path in site.history.glob("*.json"):       # the files of the probe were indented
                path.write_text(json.dumps(json.loads(path.read_bytes()), separators=(",", ":")), encoding="utf-8")
            indented = site.snapshot()
            site.fake.log.clear()
            code, out = site.run("--refresh")
            self.assertEqual(code, 0, out)
            self.assertEqual(site.fake.kinds().count("history"), 21)
            self.assertIn("refresh: 21 stored histories agree with the API", out)
            for path in sorted((FIXTURES / "history").glob("*.json")):
                self.assertEqual((site.history / path.name).read_bytes(), path.read_bytes())
            self.assertNotEqual(site.snapshot(), indented)
            # a stored version that the API contradicts is reported
            key = "node/6666122939"
            data = json.loads(site.fake.histories[key])
            data["elements"][0]["user"] = "someone else"
            site.fake.histories[key] = json.dumps(data).encode("utf-8")
            _, out = site.run("--refresh")
            self.assertIn("1 differ", out)
            self.assertIn("WARN", out)
        finally:
            site.close()


class Errors(unittest.TestCase):
    def setUp(self) -> None:
        self.site = Site()

    def tearDown(self) -> None:
        self.site.close()

    def test_runtime_error_of_overpass(self) -> None:
        self.site.fake.overpass_answer = json.dumps({"elements": [], "remark": "runtime error: Query timed out"}).encode()
        code, out = self.site.run()
        self.assertEqual(code, 1)
        self.assertIn("Overpass could not finish the query", out)
        self.assertFalse(self.site.overpass_file.exists())

    def test_query_with_geom_is_refused(self) -> None:
        (self.site.seeds / "overpass-benchmarks.overpassql").write_text(QUERY.replace("out meta;", "out meta geom;"), encoding="utf-8")
        code, out = self.site.run()
        self.assertEqual(code, 2)
        self.assertIn("no `geom`", out)
        self.assertEqual(self.site.fake.log, [])

    def test_missing_query(self) -> None:
        (self.site.seeds / "overpass-benchmarks.overpassql").unlink()
        code, out = self.site.run()
        self.assertEqual(code, 2)
        self.assertIn("does not exist", out)

    def test_unknown_history_is_an_error_and_names_the_element(self) -> None:
        del self.site.fake.histories["node/6666122939"]
        self.site.fake.overpass_answer = json.dumps({"elements": [{"type": "node", "id": 6666122939, "version": 3}]}).encode()
        code, out = self.site.run()
        self.assertEqual(code, 1)
        self.assertIn("HTTP 404", out)

    def test_offline_refuses_probe(self) -> None:
        code, out = self.site.run("--offline", "--probe")
        self.assertEqual(code, 2)

    def test_unreachable_host(self) -> None:
        def down(request, timeout):
            raise osm_net.Unreachable("cannot reach overpass: no route")
        imp.CLIENT_FACTORY = lambda: osm_net.OsmClient("t", delay=0, transport=down, sleep=lambda s: None)
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                code = imp.main(["--csv", str(self.site.csv), "--from-dir", str(self.site.history), "--mapping", str(self.site.csv / "mapping" / "osm-properties.csv"),
                                 "--seeds", str(self.site.seeds), "--overpass-file", str(self.site.overpass_file)])
        finally:
            imp.CLIENT_FACTORY = None
        self.assertEqual(code, 1)
        self.assertIn("with --offline", buffer.getvalue())


class RealTransport(unittest.TestCase):
    """The urllib transport against a small HTTP server on this machine: POST of the query, GET of a history, User-Agent, bytes."""

    def test_a_run_over_http(self) -> None:
        fake = Fake()
        seen: list[tuple[str, str, str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _send(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                data = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8")
                seen.append(("POST", self.path, self.headers["User-Agent"], urllib.parse.parse_qs(data)["data"][0]))
                self._send(200, fake.overpass())

            def do_GET(self) -> None:
                seen.append(("GET", self.path, self.headers["User-Agent"], ""))
                key = "/".join(self.path.split("/")[3:5])
                self._send(200, fake.histories[key]) if key in fake.histories else self._send(404, b"no")

        patch = unittest.mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
        patch.start()
        self.addCleanup(patch.stop)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        site = Site()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = imp.main(["--csv", str(site.csv), "--from-dir", str(site.history), "--mapping", str(site.csv / "mapping" / "osm-properties.csv"),
                                 "--seeds", str(site.seeds), "--overpass-file", str(site.overpass_file), "--overpass", base + "/api/interpreter",
                                 "--api", base, "--delay", "0", "--contact", "me@example.org", "--limit", "3"])
            self.assertEqual(code, 0, buffer.getvalue())
            self.assertEqual(seen[0][0], "POST")
            self.assertEqual(seen[0][3], QUERY)
            self.assertIn("me@example.org", seen[0][2])
            self.assertTrue(seen[0][2].startswith("wikibase-static/"))
            self.assertEqual([s[0] for s in seen].count("GET"), 3)
            self.assertTrue(seen[1][1].endswith("/history.json"))
            first = sorted(site.history.glob("*.json"))[0]
            self.assertEqual(first.read_bytes(), (FIXTURES / "history" / first.name).read_bytes())
        finally:
            server.shutdown()
            server.server_close()
            site.close()


class PlanFunctions(unittest.TestCase):
    def test_plan(self) -> None:
        plan = osm_net.make_plan({"node/1": 2, "node/2": 3, "node/3": 1}, {"node/2": 3, "node/3": 1, "node/9": 4})
        self.assertEqual((plan.new, plan.changed, plan.unchanged, plan.gone), (["node/1"], [], ["node/2", "node/3"], ["node/9"]))
        self.assertEqual(osm_net.make_plan({"node/2": 4}, {"node/2": 3}).changed, ["node/2"])
        self.assertEqual(osm_net.make_plan({"node/2": 2}, {"node/2": 3}).unchanged, ["node/2"])

    def test_history_url(self) -> None:
        self.assertEqual(osm_net.history_url("https://x.org/", "way/5"), "https://x.org/api/0.6/way/5/history.json")


if __name__ == "__main__":
    unittest.main()
