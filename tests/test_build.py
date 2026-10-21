"""Tests for the renderer, the site.yaml reader and the build step (S3).

    python tests/test_build.py

Needs Jinja2 and PyYAML (requirements.txt). Uses ``tests/fixtures/entities/``:
Q1 has one statement for each supported datatype, Q2 is its target.
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

from wikibase_static import render, site_config, step_build, utils  # noqa: E402

FIXTURES = HERE / "fixtures"


def snak(datatype: str, vtype: str, value: object, prop: str = "P2") -> dict:
    return {"datatype": datatype, "datavalue": {"type": vtype, "value": value}, "property": prop, "snaktype": "value"}


class Site(unittest.TestCase):
    """A temporary site repository: data/raw from the fixtures, an empty docs/, no site.yaml."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(FIXTURES / "entities", self.root / "data" / "raw" / "entities")
        self.docs = self.root / "docs"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def entity_path(self, name: str) -> Path:
        return self.root / "data" / "raw" / "entities" / f"{name}.json"

    def edit(self, name: str, change) -> None:
        data = json.loads(self.entity_path(name).read_text(encoding="utf-8"))
        change(data)
        self.entity_path(name).write_text(json.dumps(data), encoding="utf-8")

    def site_yaml(self, text: str) -> None:
        (self.root / "site.yaml").write_text(text, encoding="utf-8")

    def build(self) -> tuple[int, str]:
        names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
        saved = {n: getattr(utils, n) for n in names}
        utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = self.root, self.root / "data" / "raw", self.root / "data" / "derived"
        utils.DOCS, utils.SITE_YAML, utils.DIST = self.docs, self.root / "site.yaml", self.root / "dist"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = step_build.main([])
        finally:
            for name, value in saved.items():
                setattr(utils, name, value)
        return code, out.getvalue()

    def page(self, name: str) -> str:
        return (self.docs / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- pure functions


class FormatTests(unittest.TestCase):
    def test_time_by_precision(self) -> None:
        def t(time: str, precision: int, model: str = "http://www.wikidata.org/entity/Q1985727") -> str:
            return render.format_time({"time": time, "precision": precision, "calendarmodel": model})
        self.assertEqual(t("+2020-05-17T00:00:00Z", 11), "2020-05-17")
        self.assertEqual(t("+2020-05-00T00:00:00Z", 10), "2020-05")
        self.assertEqual(t("+2020-00-00T00:00:00Z", 9), "2020")
        self.assertEqual(t("+2020-00-00T00:00:00Z", 8), "2020s")
        self.assertEqual(t("+2001-00-00T00:00:00Z", 7), "21st century")
        self.assertEqual(t("+0101-00-00T00:00:00Z", 7), "2nd century")
        self.assertEqual(t("+2000-00-00T00:00:00Z", 6), "2nd millennium")
        self.assertEqual(t("-0300-00-00T00:00:00Z", 9), "300 BCE")
        self.assertEqual(t("-0300-03-04T00:00:00Z", 11), "0300-03-04 BCE")
        self.assertEqual(t("+1582-10-04T00:00:00Z", 11, "http://www.wikidata.org/entity/Q1985786"), "1582-10-04 (Julian)")

    def test_amount_and_unit(self) -> None:
        self.assertEqual(render.format_amount({"amount": "+42", "lowerBound": "+41", "upperBound": "+43", "unit": "1"}), ("42 ±1", None))
        self.assertEqual(render.format_amount({"amount": "+42", "lowerBound": "+40", "upperBound": "+43", "unit": "1"}), ("42 (40–43)", None))
        self.assertEqual(render.format_amount({"amount": "-1.50", "unit": "http://x/entity/Q11573"}), ("-1.50", "http://x/entity/Q11573"))

    def test_coordinate_text_keeps_the_source_digits(self) -> None:
        value = {"latitude": 39.08002, "longitude": 17.12661, "precision": 1e-06, "globe": render.EARTH}
        self.assertEqual(render.format_coordinate(value), "39.08002° N, 17.12661° E")
        value = {"latitude": -51.8937, "longitude": -8.4924, "precision": 0.0001, "globe": render.EARTH}
        self.assertEqual(render.format_coordinate(value), "51.8937° S, 8.4924° W")

    def test_only_earth_in_range_gets_a_map_point(self) -> None:
        good = {"latitude": 10, "longitude": 20, "globe": render.EARTH}
        self.assertEqual(render.map_point(good), (10.0, 20.0))
        self.assertIsNone(render.map_point({**good, "globe": "http://www.wikidata.org/entity/Q405"}))
        self.assertIsNone(render.map_point({**good, "latitude": 91}))
        self.assertIsNone(render.map_point({"latitude": "x", "longitude": 1, "globe": render.EARTH}))

    def test_links_only_for_web_schemes(self) -> None:
        self.assertTrue(render.is_linkable("https://example.org"))
        self.assertTrue(render.is_linkable("HTTP://example.org"))
        self.assertFalse(render.is_linkable("javascript:alert(1)"))
        self.assertFalse(render.is_linkable("data:text/html,x"))

    def test_commons_name(self) -> None:
        self.assertEqual(render.commons_name("My photo (1).jpg"), "My_photo_%281%29.jpg")


class ConfigTests(unittest.TestCase):
    def load(self, text: str | None, manifest: str | None = None) -> site_config.SiteConfig:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site.yaml"
            if text is not None:
                path.write_text(text, encoding="utf-8")
            return site_config.load_config(path, manifest)

    def test_missing_file_gives_defaults_and_a_title_from_the_source(self) -> None:
        cfg = self.load(None, "https://fuzzy-sl.wikibase.cloud")
        self.assertFalse(cfg.present)
        self.assertEqual((cfg.title, cfg.default_language, cfg.second_language), ("fuzzy-sl.wikibase.cloud", "en", None))
        self.assertEqual(cfg.problems, [])
        self.assertEqual(self.load(None).title, "Wikibase archive")

    def test_full_file(self) -> None:
        cfg = self.load("title: T\ncolour: '#990000'\nsource:\n  url: https://x.org/\nlicense:\n  name: CC0\n  url: https://c.org\n"
                        "languages:\n  default: de\n  second: en\nformatter_property: P18\nimprint: https://x.org/i\n", "https://x.org")
        self.assertEqual(cfg.problems, [])
        self.assertEqual((cfg.title, cfg.colour, cfg.source_url, cfg.languages, cfg.formatter_property),
                         ("T", "#990000", "https://x.org", ["de", "en"], "P18"))

    def test_bad_values_become_messages_and_defaults(self) -> None:
        cfg = self.load("colour: red\nlanguages:\n  default: EN!\n  second: en\nformatter_property: 18\nsurprise: 1\n"
                        "source:\n  url: https://a.org\n", "https://b.org")
        self.assertEqual((cfg.colour, cfg.default_language, cfg.formatter_property), (site_config.DEFAULT_COLOUR, "en", "P1630"))
        text = "\n".join(cfg.problems)
        for expected in ("colour 'red'", "languages.default 'EN!'", "formatter_property '18'", "unknown key 'surprise'",
                         "source.url https://a.org differs from the manifest"):
            self.assertIn(expected, text)
        self.assertIsNone(cfg.second_language)                                   # equal to the (fallen-back) default

    def test_licence_defaults_to_cc0_unless_site_yaml_gives_one(self) -> None:
        cfg = self.load(None)
        self.assertEqual((cfg.license_name, cfg.license_url, cfg.license_is_default),
                         ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/", True))
        cfg = self.load("license:\n  name: ODbL\n")
        self.assertEqual((cfg.license_name, cfg.license_url, cfg.license_is_default), ("ODbL", None, False))
        cfg = self.load("license:\n  url: https://example.org/terms\n")
        self.assertEqual((cfg.license_name, cfg.license_url, cfg.license_is_default), (None, "https://example.org/terms", False))

    def test_unreadable_yaml_does_not_raise(self) -> None:
        cfg = self.load("title: [unclosed\n")
        self.assertTrue(any("not readable" in p for p in cfg.problems))
        self.assertEqual(self.load("- a\n- b\n").problems, ["site.yaml: the top level must be a mapping; defaults used"])


# --------------------------------------------------------------------------- the build step


class BuildTests(Site):
    def test_every_entity_gets_a_page_and_there_is_an_index(self) -> None:
        code, out = self.build()
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in self.docs.glob("*.html")),
                         sorted(["index.html", "Q1.html", "Q2.html"] + [f"P{n}.html" for n in range(1, 11)]))
        self.assertIn("[build] 12 entities -> 12 entity pages + index.html in docs/ (difference 0)", out)
        self.assertIn("0 dead", out)
        self.assertNotIn("WARN", out)

    def test_values_of_every_datatype(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<a href="Q2.html">Example class <span class="id">(Q2)</span></a>', q1)   # item, internal link with its id
        self.assertIn('<a href="P1.html">instance of <span class="id">(P1)</span></a>', q1)      # property link with its id
        self.assertIn('<a href="P1.html">instance of <span class="id">(P1)</span></a>', q1.split('id="P10"')[1])  # value of a property-type statement
        self.assertIn('rank-preferred', q1)
        self.assertIn("plain text", q1)
        self.assertIn('<a href="https://example.org/" target="_blank" rel="noopener">https://example.org/</a>', q1)
        self.assertIn("2020-05-17", q1)
        self.assertIn("unknown value", q1)                                          # somevalue
        self.assertIn("42 ±1", q1)
        self.assertIn('lang="de">Beispiel</span>', q1)                              # monolingual text
        self.assertIn("49.9929° N, 8.2473° E", q1)
        self.assertIn("https://commons.wikimedia.org/wiki/Special:FilePath/Example.jpg?width=400", q1)
        self.assertIn('href="https://commons.wikimedia.org/wiki/File:Example.jpg" target="_blank"', q1)
        self.assertIn("qualifier text", q1)
        self.assertIn("<summary>1 reference</summary>", q1)                          # one reference: expandable
        self.assertIn('<div class="references zero"><span class="toggle">0 references</span></div>', q1)   # none: shown as 0
        self.assertIn("https://example.org/source", q1)

    def test_map_is_added_only_where_there_is_a_coordinate(self) -> None:
        self.build()
        q1, q2 = self.page("Q1.html"), self.page("Q2.html")
        self.assertIn('class="wbs-map"', q1)
        self.assertIn("&#34;lat&#34;:49.9929", q1)
        self.assertIn("assets/vendor/leaflet/leaflet.js", q1)
        self.assertNotIn("wbs-map", q2)
        self.assertNotIn("leaflet", q2)
        for name in ("style.css", "app.js", "map.js", "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css",
                     "vendor/leaflet/images/marker-icon.png"):
            self.assertTrue((self.docs / "assets" / name).is_file(), name)

    def test_a_coordinate_on_another_globe_is_text_without_marker(self) -> None:
        def moon(data: dict) -> None:
            data["claims"]["P8"][0]["mainsnak"]["datavalue"]["value"]["globe"] = "http://www.wikidata.org/entity/Q405"
        self.edit("Q1", moon)
        _code, out = self.build()
        q1 = self.page("Q1.html")
        self.assertNotIn("wbs-map", q1)
        self.assertIn("49.9929° N, 8.2473° E", q1)
        self.assertIn("1 not on Earth or out of range, shown as text", out)

    def test_urls_are_shown_unchanged_and_only_web_schemes_become_links(self) -> None:
        def change(data: dict) -> None:
            data["claims"]["P4"] = [{"mainsnak": snak("url", "string", "javascript:alert(1)", "P4"), "rank": "normal", "type": "statement"},
                                    {"mainsnak": snak("url", "string", "http://openopenstreetmap.org/node/1", "P4"), "rank": "normal", "type": "statement"}]
        self.edit("Q1", change)
        self.build()
        q1 = self.page("Q1.html")
        self.assertNotIn('href="javascript', q1)
        self.assertIn("javascript:alert(1)", q1)
        self.assertIn('href="http://openopenstreetmap.org/node/1"', q1)

    def test_text_is_escaped(self) -> None:
        def change(data: dict) -> None:
            data["labels"]["en"]["value"] = "<script>alert(1)</script> & co"
            data["claims"]["P2"][0]["mainsnak"]["datavalue"]["value"] = '"><img src=x onerror=alert(1)>'
        self.edit("Q1", change)
        self.build()
        q1 = self.page("Q1.html")
        self.assertNotIn("<script>alert", q1)
        self.assertNotIn("<img src=x", q1)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", q1)

    def test_external_id_uses_the_formatter_url_of_the_configured_property(self) -> None:
        def formatter(data: dict) -> None:
            data["claims"] = {"P2": [{"mainsnak": snak("string", "string", "https://ids.example/$1/view"), "rank": "normal", "type": "statement"}]}
        self.edit("P3", formatter)
        self.site_yaml("formatter_property: P2\n")
        self.build()
        self.assertIn('<a href="https://ids.example/EXT-0001/view" target="_blank" rel="noopener">EXT-0001</a>', self.page("Q1.html"))

    def test_external_id_without_formatter_is_plain_text(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn("EXT-0001", q1)
        self.assertNotIn(">EXT-0001</a>", q1)

    def test_a_value_the_site_does_not_hold_links_to_wikidata_in_a_new_tab(self) -> None:
        def change(data: dict) -> None:
            data["claims"]["P1"][0]["mainsnak"]["datavalue"]["value"] = {"entity-type": "item", "id": "Q42", "numeric-id": 42}
        self.edit("Q1", change)
        self.build()
        self.assertIn('<a class="federated" href="https://www.wikidata.org/wiki/Q42" target="_blank" rel="noopener"', self.page("Q1.html"))

    def test_second_language_gives_spans_and_a_switch_and_equal_text_stays_single(self) -> None:
        def label(data: dict) -> None:
            data["labels"]["de"] = {"language": "de", "value": "Beispielseite"}
        self.edit("Q1", label)
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<span class="l" lang="en">Example site</span><span class="l" lang="de">Beispielseite</span>', q1)
        self.assertIn('data-set-lang="de"', q1)
        self.assertIn('html[data-lang="de"] .l:not([lang="de"]) { display: none; }', q1)
        self.assertIn('<a href="P2.html">text <span class="id">(P2)</span></a>', q1)   # no German label for P2: one plain text, no spans
        self.assertIn('<span class="l" lang="de">Beispielklasse</span> <span class="id">(Q2)</span></a>', q1)  # the id follows both languages
        self.assertIn('<span class="l" lang="en">Statements</span><span class="l" lang="de">Aussagen</span>', q1)

    def test_without_second_language_there_is_no_switch(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertNotIn("data-set-lang", q1)
        self.assertNotIn('class="l"', q1)

    def test_footer_has_source_date_and_licence(self) -> None:
        self.site_yaml("source:\n  url: https://wb.example\nlicense:\n  name: CC0 1.0\n  url: https://creativecommons.org/publicdomain/zero/1.0/\n"
                       "imprint: Example Lab, Mainz\n")
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<a href="https://wb.example/entity/Q1" target="_blank" rel="noopener">Original page</a>', q1)
        self.assertIn("As of: 2026-01-02", q1)
        self.assertIn('Licence: <a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank" rel="noopener">CC0 1.0</a>', q1)
        self.assertIn("Imprint: Example Lab, Mainz", q1)

    def test_licence_defaults_to_cc0_public_domain(self) -> None:
        _code, out = self.build()
        self.assertIn('Licence: <a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank" rel="noopener">CC0 1.0</a>',
                      self.page("Q1.html"))
        self.assertNotIn("not stated", self.page("Q1.html"))
        self.assertIn("licence: CC0 1.0 (default)", out)

    def test_a_licence_in_site_yaml_replaces_the_default(self) -> None:
        self.site_yaml("license:\n  name: CC BY 4.0\n  url: https://creativecommons.org/licenses/by/4.0/\n")
        _code, out = self.build()
        q1 = self.page("Q1.html")
        self.assertIn('>CC BY 4.0</a>', q1)
        self.assertNotIn("CC0", q1)
        self.assertIn("licence: CC BY 4.0", out)
        self.assertNotIn("(default)", out)

    def test_a_licence_given_as_url_only_uses_the_url_as_its_text(self) -> None:
        self.site_yaml("license:\n  url: https://example.org/terms\n")
        self.build()
        self.assertIn('Licence: <a href="https://example.org/terms" target="_blank" rel="noopener">https://example.org/terms</a>',
                      self.page("Q1.html"))

    def test_a_licence_given_as_text_only_is_shown_as_text(self) -> None:
        self.site_yaml("license:\n  name: All rights reserved, see the imprint\n")
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn("Licence: All rights reserved, see the imprint", q1)
        self.assertNotIn("CC0", q1)

    def test_internal_links_carry_the_id_but_an_entity_without_label_is_not_doubled(self) -> None:
        def unlabelled(data: dict) -> None:
            data["labels"] = {}
        self.edit("Q2", unlabelled)
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<a href="Q2.html">Q2</a>', q1)
        self.assertNotIn("Q2 <span", q1)
        self.assertIn("<h1>Q2</h1>", self.page("Q2.html"))

    def test_references_are_counted_in_both_languages(self) -> None:
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<summary><span class="l" lang="en">1 reference</span><span class="l" lang="de">Eine Fundstelle</span></summary>', q1)
        self.assertIn('<span class="l" lang="en">0 references</span><span class="l" lang="de">0 Fundstellen</span>', q1)

        def two(data: dict) -> None:
            reference = data["claims"]["P1"][0]["references"][0]
            data["claims"]["P1"][0]["references"] = [reference, {**reference, "hash": "y"}]
        self.edit("Q1", two)
        self.build()
        self.assertIn('<span class="l" lang="de">2 Fundstellen</span>', self.page("Q1.html"))

    def test_qualifiers_and_references_are_label_value_pairs(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<div class="qprop"><a href="P2.html">text <span class="id">(P2)</span></a></div><div class="qval">qualifier text</div>', q1)
        self.assertIn('<div class="reference">', q1)
        self.assertIn('<div class="qprop"><a href="P4.html">website <span class="id">(P4)</span></a></div><div class="qval"><a href="https://example.org/source"', q1)

    def test_every_statement_has_a_rank_icon_with_a_title(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<span class="rank-icon rank-preferred" title="Rank: preferred"></span>', q1)
        self.assertIn('<span class="rank-icon rank-normal" title="Rank: normal"></span>', q1)

        def deprecated(data: dict) -> None:
            data["claims"]["P2"][0]["rank"] = "deprecated"
        self.edit("Q1", deprecated)
        self.build()
        self.assertIn('<span class="rank-icon rank-deprecated" title="Rank: deprecated"></span>', self.page("Q1.html"))

    def test_language_table_lists_default_second_and_every_other_language_present(self) -> None:
        def terms(data: dict) -> None:
            data["labels"]["fr"] = {"language": "fr", "value": "Site d'exemple"}
            data["descriptions"]["xx-odd"] = {"language": "xx-odd", "value": "odd <b>text</b>"}
            data["aliases"]["en"] = [{"language": "en", "value": "Sample site"}, {"language": "en", "value": "Test & demo"}]
        self.edit("Q1", terms)
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        q1 = self.page("Q1.html")
        table = q1[q1.index('<table class="terms">'):q1.index("</table>")]
        rows = [r for r in table.split("<tr lang=")[1:]]
        self.assertEqual([r[1:r.index('"', 1)] for r in rows], ["en", "de", "fr", "xx-odd"])      # default, second, the rest sorted
        self.assertIn('<td><span class="l" lang="en">English</span><span class="l" lang="de">Englisch</span></td>', rows[0])
        self.assertIn("Sample site | Test &amp; demo", rows[0])                                       # aliases joined, escaped
        self.assertIn('<span class="muted"><span class="l" lang="en">No label defined</span><span class="l" lang="de">Keine Bezeichnung vorhanden</span></span>', rows[1])
        self.assertIn("Site d&#39;exemple", rows[2])
        self.assertIn("<td>xx-odd</td>", rows[3])                                                     # an unknown code stays as it is
        self.assertIn("odd &lt;b&gt;text&lt;/b&gt;", rows[3])                                         # escaped
        self.assertIn('<span class="l" lang="en">In other languages</span><span class="l" lang="de">In weiteren Sprachen</span>', q1)

    def test_language_table_with_one_language_has_one_row_and_names_the_gap_only_for_the_second(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertEqual(q1.count("<tr lang="), 1)
        self.assertIn("<td>English</td>", q1)

    def test_tabs_name_the_kind_and_link_to_the_original(self) -> None:
        self.site_yaml("source:\n  url: https://wb.example\n")
        self.build()
        q1, p1, index = self.page("Q1.html"), self.page("P1.html"), self.page("index.html")
        self.assertIn('<ul class="tabs-left"><li class="active"><span>Item</span></li></ul>', q1)
        self.assertIn('<ul class="tabs-left"><li class="active"><span>Property</span></li></ul>', p1)
        self.assertIn('<li class="active"><span>Read</span></li><li><a href="https://wb.example/entity/Q1" target="_blank" rel="noopener">Original</a></li>', q1)
        self.assertIn('<ul class="tabs-left"><li class="active"><span>Home</span></li></ul>', index)
        self.assertIn('<ul class="tabs-view"></ul>', index)

    def test_without_a_source_there_is_no_original_tab(self) -> None:
        self.build()
        self.assertNotIn(">Original</a>", self.page("Q1.html"))

    def test_tools_section_is_there_only_when_something_points_to_the_page(self) -> None:
        self.build()
        self.assertIn('<h3>Tools</h3>', self.page("Q2.html"))
        self.assertIn('<a href="#incoming">Referenced by</a>', self.page("Q2.html"))
        self.assertIn('<section class="incoming" id="incoming">', self.page("Q2.html"))
        self.assertNotIn("<h3>Tools</h3>", self.page("Q1.html"))                                      # nothing points to Q1
        self.assertNotIn('id="incoming"', self.page("Q1.html"))

    def test_the_footer_sits_inside_the_content_column(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertLess(q1.index('<div class="content">'), q1.index('<footer class="site-footer">'))
        self.assertLess(q1.index('<footer class="site-footer">'), q1.index("</main>") + 200)

    def test_logo_and_navigation_sit_in_the_sidebar(self) -> None:
        self.build()
        q1 = self.page("Q1.html")
        self.assertIn('<aside class="sidebar">', q1)
        self.assertIn('<span class="logo-text">Wikibase archive</span>', q1)       # no logo: the title takes its place
        self.assertIn('href="index.html#items"', q1)
        self.assertIn('href="index.html#properties"', q1)
        self.assertIn('<section id="items">', self.page("index.html"))
        self.assertIn('<section id="properties">', self.page("index.html"))

    def test_referenced_by_lists_who_points_here(self) -> None:
        self.build()
        q2 = self.page("Q2.html")
        self.assertIn("Referenced by (1)", q2)
        self.assertIn('<a href="Q1.html">Example site <span class="id">(Q1)</span></a>', q2)
        self.assertIn("Referenced by (1)", self.page("P1.html"))    # P1 is used by Q1 (and pointed to by its P10 value)

    def test_index_lists_everything(self) -> None:
        self.site_yaml("title: Demo\ndescription: A test site\n")
        self.build()
        index = self.page("index.html")
        self.assertIn("<h1>Demo</h1>", index)
        self.assertIn("12 entities (2 items, 10 properties)", index)
        self.assertIn('<td class="id">Q1</td><td><a href="Q1.html">Example site</a></td>', index)   # the id has its own column
        self.assertIn('<a href="P10.html">related property</a>', index)

    def test_property_page_shows_the_datatype(self) -> None:
        self.build()
        p8 = self.page("P8.html")
        self.assertIn("Globe coordinate", p8)
        self.assertIn("<code>globe-coordinate</code>", p8)

    def test_a_logo_inside_the_repository_is_copied_and_one_outside_is_refused(self) -> None:
        (self.root / "logo.png").write_bytes(b"\x89PNG fake")
        self.site_yaml("logo: logo.png\n")
        self.build()
        self.assertEqual((self.docs / "assets" / "logo" / "logo.png").read_bytes(), b"\x89PNG fake")
        q1 = self.page("Q1.html")
        self.assertIn('<a class="logo" href="index.html"><img src="assets/logo/logo.png" alt="Wikibase archive"></a>', q1)
        self.assertNotIn("logo-text", q1)
        self.site_yaml("logo: ../../etc/passwd\n")
        _code, out = self.build()
        self.assertIn("WARN: [build] site.yaml: logo '../../etc/passwd' is not a file inside the repository", out)
        self.assertNotIn("assets/logo", self.page("Q1.html"))

    def test_two_runs_give_identical_files(self) -> None:
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        _c, first_out = self.build()
        first = {p.relative_to(self.docs): p.read_bytes() for p in sorted(self.docs.rglob("*")) if p.is_file()}
        _c, second_out = self.build()
        second = {p.relative_to(self.docs): p.read_bytes() for p in sorted(self.docs.rglob("*")) if p.is_file()}
        self.assertEqual(first, second)
        self.assertEqual(first_out, second_out)
        for path, data in first.items():
            if path.suffix in (".html", ".css", ".js") or path.name == "LICENSE":
                self.assertNotIn(b"\r\n", data, str(path))               # LF only (PRIMER.md, A3)

    def test_pages_of_removed_entities_are_removed_and_other_files_stay(self) -> None:
        self.build()
        (self.docs / "Q77.html").write_text("old", encoding="utf-8")
        (self.docs / "sparql.html").write_text("keep", encoding="utf-8")
        _code, out = self.build()
        self.assertFalse((self.docs / "Q77.html").exists())
        self.assertTrue((self.docs / "sparql.html").exists())
        self.assertIn("removed 1 stale page(s): Q77.html", out)

    def test_empty_data_is_nothing_to_do_and_writes_nothing(self) -> None:
        shutil.rmtree(self.root / "data")
        code, out = self.build()
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)
        self.assertFalse(self.docs.exists())

    def test_without_site_yaml_the_build_runs_with_defaults(self) -> None:
        code, out = self.build()
        self.assertEqual(code, 0)
        self.assertIn("no site.yaml: defaults used", out)
        self.assertNotIn("WARN", out)
        self.assertIn("<title>Example site (Q1) – Wikibase archive</title>", self.page("Q1.html"))


class LinkcheckTests(unittest.TestCase):
    def test_dead_links_are_found_and_external_ones_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "assets").mkdir()
            (docs / "assets" / "style.css").write_text("", encoding="utf-8")
            (docs / "Q2.html").write_text("<p>target</p>", encoding="utf-8")
            (docs / "Q1.html").write_text(
                '<link rel="stylesheet" href="assets/style.css"><a href="Q2.html#x">ok</a><a href="Q3.html">dead</a>'
                '<script src="assets/missing.js"></script><a href="https://example.org/x.html">ext</a><a href="#top">frag</a>'
                '<a href="mailto:a@b.c">mail</a><a href="../outside.html">out</a><img src="assets/a%20b.png">',
                encoding="utf-8")
            checked, dead = step_build.linkcheck(docs)
        self.assertEqual(checked, 6)
        self.assertEqual(dead, ["Q1.html -> ../outside.html (outside docs/)", "Q1.html -> Q3.html",
                                "Q1.html -> assets/a b.png", "Q1.html -> assets/missing.js"])

    def test_the_build_reports_a_dead_link_as_a_warning(self) -> None:
        case = BuildTests("test_values_of_every_datatype")
        case.setUp()
        original = step_build.linkcheck
        try:
            step_build.linkcheck = lambda docs: (5, ["Q1.html -> Q99.html"])
            code, out = case.build()
        finally:
            step_build.linkcheck = original
            case.tearDown()
        self.assertEqual(code, 0)
        self.assertIn("[build] linkcheck: 5 internal links checked, 1 dead", out)
        self.assertIn("WARN: [build] dead internal link Q1.html -> Q99.html", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
