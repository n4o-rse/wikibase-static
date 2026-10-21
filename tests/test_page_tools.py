"""Tests for the tools on every entity page: the RDF and JSON downloads and the button that copies the concept URI.

    python tests/test_page_tools.py
"""

from __future__ import annotations

import contextlib
import io
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "py"))
sys.path.insert(0, str(HERE))

import test_build  # noqa: E402
from wikibase_static import step_build, step_rdf, utils  # noqa: E402


class PageTools(test_build.Site):
    def run_step(self, module) -> tuple[int, str]:
        names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
        saved = {n: getattr(utils, n) for n in names}
        utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = self.root, self.root / "data" / "raw", self.root / "data" / "derived"
        utils.DOCS, utils.SITE_YAML, utils.DIST = self.docs, self.root / "site.yaml", self.root / "dist"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = module.main([])
        finally:
            for name, value in saved.items():
                setattr(utils, name, value)
        return code, out.getvalue()

    def test_a_page_links_its_turtle_and_json_files(self) -> None:
        self.build()
        page = self.page("Q1.html")
        self.assertIn('<a href="ttl/Q1.ttl" download>RDF (Turtle)</a>', page)
        self.assertIn('<a href="json/Q1.json" download>JSON</a>', page)

    def test_the_links_are_not_dead_after_the_rdf_step_and_not_counted_dead_before_it(self) -> None:
        code, out = self.build()
        self.assertIn("0 dead", out)                             # the rdf step has not run yet: the files are pending
        self.site_yaml("rdf_base: https://example.org\n")
        self.run_step(step_rdf)
        for page in sorted(self.docs.glob("[QP]*.html")):
            for href in re.findall(r'<a href="((?:ttl|json)/[^"]+)" download>', page.read_text(encoding="utf-8")):
                self.assertTrue((self.docs / href).is_file(), f"{page.name} -> {href}")

    def test_the_json_link_is_left_out_when_there_is_no_file_for_it(self) -> None:
        self.entity_path("Q2").rename(self.root / "data" / "raw" / "entities" / "Q2-old.json")
        self.edit_ids = None
        self.build()
        # Q2 now lives in a file that is not named after it: the loader reports it, the page of Q1 stays complete
        self.assertIn('<a href="json/Q1.json" download>', self.page("Q1.html"))

    def test_without_a_base_uri_there_is_no_copy_button(self) -> None:
        self.build()
        self.assertNotIn("data-copy", self.page("Q1.html"))

    def test_with_rdf_base_the_button_carries_the_concept_uri(self) -> None:
        self.site_yaml("pages_url: https://example.org/wiki/\nrdf_base: https://example.org/wiki\n")
        self.build()
        page = self.page("Q1.html")
        self.assertIn('data-copy="https://example.org/wiki/entity/Q1"', page)
        self.assertIn('<span class="copy-label">Copy concept URI</span>', page)
        self.assertIn('<span class="copy-done" hidden>Copied</span>', page)
        self.assertIn('data-copy="https://example.org/wiki/entity/P1"', self.page("P1.html"))

    def test_the_texts_come_in_both_languages(self) -> None:
        self.site_yaml("pages_url: https://example.org/\nrdf_base: https://example.org\nlanguages:\n  default: en\n  second: de\n")
        self.build()
        page = self.page("Q1.html")
        self.assertIn("Konzept-URI kopieren", page)
        self.assertIn("Herunterladen", page)

    def test_a_concept_uri_under_the_published_site_opens_a_page_that_forwards(self) -> None:
        self.site_yaml("pages_url: https://example.org/demo/\nrdf_base: https://example.org/demo\n")
        self.build()
        code, _ = self.run_step(step_rdf)
        stub = (self.docs / "entity" / "Q1.html").read_text(encoding="utf-8")
        self.assertIn('url=../Q1.html', stub)
        self.assertIn('href="../ttl/Q1.ttl"', stub)
        self.assertEqual(sorted(p.stem for p in (self.docs / "entity").glob("*.html")),
                         sorted(p.stem for p in (self.docs / "ttl").glob("*.ttl")))

    def test_no_stubs_when_the_base_is_the_live_wikibase(self) -> None:
        self.site_yaml("pages_url: https://example.org/demo/\nrdf_base: https://wiki.example.org\n")
        self.build()
        self.run_step(step_rdf)
        self.assertFalse((self.docs / "entity").exists())

    def test_stubs_that_are_no_longer_wanted_are_removed(self) -> None:
        self.site_yaml("pages_url: https://example.org/demo/\nrdf_base: https://example.org/demo\n")
        self.build()
        self.run_step(step_rdf)
        self.assertTrue((self.docs / "entity" / "Q1.html").is_file())
        self.site_yaml("pages_url: https://example.org/demo/\nrdf_base: https://wiki.example.org\n")
        self.run_step(step_rdf)
        self.assertFalse((self.docs / "entity").exists())

    def test_the_meta_description_is_plain_text_even_with_two_languages(self) -> None:
        def terms(data: dict) -> None:
            data["descriptions"]["en"] = {"language": "en", "value": "A set of things"}
            data["descriptions"]["de"] = {"language": "de", "value": "Eine Menge"}
        self.edit("Q1", terms)
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        head = self.page("Q1.html").split("</head>")[0]
        self.assertIn('<meta name="description" content="A set of things">', head)

    def test_a_site_that_copies_a_wikibase_copies_its_own_page_address_not_the_wikibases(self) -> None:
        self.site_yaml("pages_url: https://example.org/copy/\nsource:\n  url: https://wb.example\n")
        self.build()
        page = self.page("Q1.html")
        self.assertIn('data-copy="https://example.org/copy/Q1.html"', page)
        self.assertIn("Copy page URL", page)
        self.assertNotIn("wb.example/entity", page.split('<div class="content">')[1].split("</p>")[0])

    def test_without_pages_url_a_live_wikibase_base_gives_no_button(self) -> None:
        self.site_yaml("source:\n  url: https://wb.example\n")
        self.build()
        self.assertNotIn("data-copy", self.page("Q1.html"))

    def test_the_meta_description_is_plain_text_even_with_two_languages(self) -> None:
        def terms(data: dict) -> None:
            data["descriptions"]["en"] = {"language": "en", "value": "A set of things"}
            data["descriptions"]["de"] = {"language": "de", "value": "Eine Menge"}
        self.edit("Q1", terms)
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        head = self.page("Q1.html").split("</head>")[0]
        self.assertIn('<meta name="description" content="A set of things">', head)

    def test_the_index_has_no_tools(self) -> None:
        self.site_yaml("pages_url: https://example.org/\nrdf_base: https://example.org\n")
        self.build()
        self.assertNotIn("data-copy", self.page("index.html"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_script_is_valid_javascript(self) -> None:
        result = subprocess.run(["node", "--check", str(REPO / "py" / "wikibase_static" / "static" / "app.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
