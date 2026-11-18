"""Offline tests for the fetch-logo step (0.30.0): a small fake Wikibase on localhost.

    python tests/test_fetch_logo.py

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
from unittest import mock
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))
sys.path.insert(0, str(HERE))

from test_harvest import FakeWikibase  # noqa: E402
from wikibase_static import step_fetch_logo, utils  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"logo-bytes"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes"

SITE = """title: t
source:
  url: {url}
# The logo.
# logo: assets/logo.png
languages:
  default: en
"""


class FakeWithLogo(FakeWikibase):
    """The fake of the harvest tests, whose site information also names a logo."""

    def __init__(self) -> None:
        super().__init__()
        self.logo = "/images/logo.png"       # relative, as MediaWiki usually has it
        self.image_mode = "ok"               # ok | anubis | missing

    def handle(self, params: dict[str, str]):
        status, headers, body = super().handle(params)
        if params.get("action") == "query" and params.get("meta") == "siteinfo" and self.mode == "ok":
            data = json.loads(body)
            if self.logo:
                data["query"]["general"]["logo"] = self.logo
            body = json.dumps(data).encode()
        return status, headers, body


def make_server(fake: FakeWithLogo) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/w/api.php":
                params = {k: v[0] for k, v in parse_qs(url.query).items()}
                params["_ua"] = self.headers.get("User-Agent", "")
                status, headers, body = fake.handle(params)
            elif url.path == "/images/logo.png":
                if fake.image_mode == "anubis":
                    status, headers, body = 200, {"Content-Type": "text/html"}, b"<html>Protected by Anubis. Making sure you're not a bot!</html>"
                elif fake.image_mode == "missing":
                    status, headers, body = 404, {"Content-Type": "text/plain"}, b"no"
                else:
                    status, headers, body = 200, {"Content-Type": "image/png"}, PNG
            else:
                status, headers, body = 404, {"Content-Type": "text/plain"}, b"no"
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


class FetchLogo(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeWithLogo()
        self.server = make_server(self.fake)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "site.yaml").write_text(SITE.format(url=self.url), encoding="utf-8")
        patches = [mock.patch.object(utils, "ROOT", self.root), mock.patch.object(utils, "SITE_YAML", self.root / "site.yaml"),
                   mock.patch.object(utils, "DATA_RAW", self.root / "data" / "raw")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def run_step(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = step_fetch_logo.main(["--delay", "0", *args])
        return code, out.getvalue()

    def site(self) -> str:
        return (self.root / "site.yaml").read_text(encoding="utf-8")

    def test_the_logo_is_saved_and_named_in_site_yaml(self) -> None:
        code, out = self.run_step()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.root / "assets" / "logo.png").read_bytes(), PNG)
        self.assertIn("\nlogo: assets/logo.png\n", self.site())
        self.assertNotIn("# logo:", self.site())
        self.assertIn("# The logo.", self.site())      # the rest of the file is as it was
        self.assertIn("licence", out)

    def test_a_second_run_changes_nothing(self) -> None:
        self.run_step()
        before = (self.site(), (self.root / "assets" / "logo.png").read_bytes())
        code, out = self.run_step()
        self.assertEqual(code, 0, out)
        self.assertIn("already named it", out)
        self.assertEqual((self.site(), (self.root / "assets" / "logo.png").read_bytes()), before)

    def test_an_absolute_logo_address_is_followed(self) -> None:
        self.fake.logo = self.url + "/images/logo.png"
        code, out = self.run_step()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "assets" / "logo.png").is_file())

    def test_a_bot_challenge_on_the_api_stops_the_step(self) -> None:
        self.fake.mode = "anubis"
        code, out = self.run_step()
        self.assertEqual(code, 2, out)
        self.assertIn("bot challenge", out)
        self.assertFalse((self.root / "assets").exists())
        self.assertIn("# logo:", self.site())

    def test_a_bot_challenge_on_the_image_stops_the_step(self) -> None:
        self.fake.image_mode = "anubis"
        code, out = self.run_step()
        self.assertEqual(code, 2, out)
        self.assertFalse((self.root / "assets").exists())

    def test_a_missing_image_and_a_missing_logo_are_errors(self) -> None:
        self.fake.image_mode = "missing"
        code, out = self.run_step()
        self.assertEqual(code, 1, out)
        self.assertIn("HTTP 404", out)
        self.fake.image_mode, self.fake.logo = "ok", ""
        code, out = self.run_step()
        self.assertEqual(code, 1, out)
        self.assertIn("names no logo", out)

    def test_your_own_file_replaces_a_logo_of_another_type(self) -> None:
        self.run_step()
        mine = self.root / "mine.jpeg"
        mine.write_bytes(JPEG)
        asked = len(self.fake.requests)
        code, out = self.run_step("--file", str(mine))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.root / "assets" / "logo.jpg").read_bytes(), JPEG)
        self.assertFalse((self.root / "assets" / "logo.png").exists())
        self.assertIn("\nlogo: assets/logo.jpg\n", self.site())
        self.assertEqual(len(self.fake.requests), asked)      # no request: it is your file

    def test_a_file_that_is_not_an_image_is_refused(self) -> None:
        notes = self.root / "notes.txt"
        notes.write_text("hello", encoding="utf-8")
        code, out = self.run_step("--file", str(notes))
        self.assertEqual(code, 1, out)
        self.assertIn("not an image", out)

    def test_without_a_source_address_there_is_nothing_to_ask(self) -> None:
        (self.root / "site.yaml").write_text("title: t\n", encoding="utf-8")
        code, out = self.run_step()
        self.assertEqual(code, 1, out)
        self.assertIn("no source address", out)

    def test_the_address_of_the_manifest_is_the_fallback(self) -> None:
        (self.root / "site.yaml").write_text("title: t\n# logo: x\n", encoding="utf-8")
        raw = self.root / "data" / "raw"
        raw.mkdir(parents=True)
        (raw / "manifest.json").write_text(json.dumps({"source": {"url": self.url}}), encoding="utf-8")
        code, out = self.run_step()
        self.assertEqual(code, 0, out)
        self.assertIn("logo: assets/logo.png", self.site())

    def test_the_line_is_added_when_the_file_has_none(self) -> None:
        (self.root / "site.yaml").write_text(f"title: t\nsource:\n  url: {self.url}\n", encoding="utf-8")
        self.run_step()
        self.assertTrue(self.site().endswith("\nlogo: assets/logo.png\n"))

    def test_the_type_comes_from_the_header_the_name_or_the_bytes(self) -> None:
        self.assertEqual(step_fetch_logo.extension_of("image/svg+xml; charset=utf-8", "x", b""), "svg")
        self.assertEqual(step_fetch_logo.extension_of("application/octet-stream", "https://h/a/b.JPG?x=1", b""), "jpg")
        self.assertEqual(step_fetch_logo.extension_of("", "noname", PNG), "png")
        self.assertIsNone(step_fetch_logo.extension_of("text/html", "page", b"<html>"))


if __name__ == "__main__":
    unittest.main()
