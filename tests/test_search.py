"""Tests for the search index, the search box on the pages and the matching in the browser script (S5).

    python tests/test_search.py

Three layers:

* the index (``step_search.build_index`` and ``render_index``) as plain functions of a model built here,
* the ``search`` step and the pages on disk, in a temporary site repository made from the fixtures,
* the matching in ``static/search.js``, run under Node with an index made by the Python side, so that what
  the script is tested against is what the step really writes. Skipped, with a reason, when Node is missing
  (GitHub's runners have it).

The box itself (focus, keys, the list under the field) needs a browser; it was looked at in Chromium when the
step was made (PRIMER.md, S5, "Erledigt").
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))
sys.path.insert(0, str(HERE))

import test_build  # noqa: E402  (the temporary-site harness lives there; import the module, not the class)
from wikibase_static import step_build, step_search, utils  # noqa: E402
from wikibase_static.loader import Site as LoadedSite  # noqa: E402
from wikibase_static.model import Entity  # noqa: E402

SEARCH_JS = HERE.parent / "py" / "wikibase_static" / "static" / "search.js"
NODE = shutil.which("node")


def entity(entity_id: str, labels: dict | None = None, descriptions: dict | None = None, aliases: dict | None = None) -> Entity:
    return Entity(id=entity_id, kind="item" if entity_id.startswith("Q") else "property",
                  labels=labels or {}, descriptions=descriptions or {}, aliases=aliases or {})


def model(*entities: Entity) -> LoadedSite:
    site = LoadedSite()
    for e in entities:
        site.entities[e.id] = e
    return site


# --------------------------------------------------------------------------- the index as a function


class IndexTests(unittest.TestCase):
    def index(self, *entities: Entity, default: str = "en", second: str | None = "de") -> dict:
        return step_search.build_index(model(*entities), default, second)

    def entry(self, index: dict, entity_id: str) -> dict:
        return next(e for e in index["entities"] if e["id"] == entity_id)

    def test_entries_are_in_id_order_items_first_and_numeric(self) -> None:
        index = self.index(entity("P2"), entity("Q10"), entity("Q2"), entity("P10"), entity("Q1"))
        self.assertEqual([e["id"] for e in index["entities"]], ["Q1", "Q2", "Q10", "P2", "P10"])

    def test_shown_label_and_description_follow_the_rule_of_the_pages(self) -> None:
        e = entity("Q1", labels={"en": "Fort", "de": "Kastell"}, descriptions={"en": "a building"})
        entry = self.entry(self.index(e), "Q1")
        self.assertEqual(entry["l"], {"en": "Fort", "de": "Kastell"})
        self.assertEqual(entry["d"], {"en": "a building", "de": "a building"})   # no German text: the default language

    def test_a_missing_language_falls_back_to_the_default_then_to_any(self) -> None:
        only_en = self.entry(self.index(entity("Q1", labels={"en": "Fort"})), "Q1")
        self.assertEqual(only_en["l"], {"en": "Fort", "de": "Fort"})
        only_fr = self.entry(self.index(entity("Q2", labels={"fr": "Fortin", "es": "Fuerte"})), "Q2")
        self.assertEqual(only_fr["l"], {"en": "Fuerte", "de": "Fuerte"})        # alphabetically first language: es

    def test_other_labels_and_aliases_are_searchable_but_not_repeated(self) -> None:
        e = entity("Q1", labels={"en": "Fort", "de": "Kastell", "fr": "Fortin", "la": "Castellum"},
                   aliases={"en": ["Fort", "Stronghold"], "de": ["Burg", "Stronghold"], "it": ["Forte"]})
        entry = self.entry(self.index(e), "Q1")
        self.assertEqual(entry["x"], ["Fortin", "Castellum"])                     # fr before la; shown labels left out
        self.assertEqual(entry["a"], ["Stronghold", "Burg", "Forte"])             # en, de, then the rest; no repeats

    def test_an_entity_without_a_label_has_no_l_and_is_found_by_id(self) -> None:
        entry = self.entry(self.index(entity("Q7")), "Q7")
        self.assertEqual(entry, {"id": "Q7"})

    def test_a_site_with_one_language_indexes_only_that_one(self) -> None:
        entry = self.entry(self.index(entity("Q1", labels={"en": "Fort", "de": "Kastell"}), second=None), "Q1")
        self.assertEqual(entry["l"], {"en": "Fort"})
        self.assertEqual(entry["x"], ["Kastell"])

    def test_the_index_does_not_depend_on_the_order_the_entities_were_loaded_in(self) -> None:
        a = [entity("Q1", labels={"en": "A"}), entity("Q2", labels={"en": "B"}), entity("P1", labels={"en": "C"})]
        self.assertEqual(step_search.render_index(self.index(*a)), step_search.render_index(self.index(*reversed(a))))

    def test_the_text_is_one_assignment_with_sorted_compact_json(self) -> None:
        text = step_search.render_index(self.index(entity("Q1", labels={"en": "Fort"})))
        self.assertTrue(text.startswith("window.WBS_SEARCH_INDEX={"))
        self.assertTrue(text.endswith("};"))
        body = json.loads(text[len("window.WBS_SEARCH_INDEX="):-1])
        self.assertEqual(list(body), sorted(body))
        self.assertEqual(body["languages"], ["en", "de"])
        self.assertEqual(body["version"], step_search.INDEX_FORMAT_VERSION)
        self.assertNotIn(", ", text)

    def test_line_separators_are_escaped_so_the_file_is_a_valid_script_everywhere(self) -> None:
        line_sep, para_sep = chr(0x2028), chr(0x2029)           # built from code points: no invisible characters in this file
        label = "a" + line_sep + "b" + para_sep + "c"
        text = step_search.render_index(self.index(entity("Q1", labels={"en": label})))
        self.assertNotIn(line_sep, text)
        self.assertNotIn(para_sep, text)
        body = json.loads(text[len("window.WBS_SEARCH_INDEX="):-1])
        self.assertEqual(body["entities"][0]["l"]["en"], label)      # the escapes read back as the text

    def test_non_ascii_text_stays_readable(self) -> None:
        text = step_search.render_index(self.index(entity("Q1", labels={"de": "Römerkastell"}), default="de", second=None))
        self.assertIn("Römerkastell", text)


# --------------------------------------------------------------------------- the step and the pages


class SearchSite(test_build.Site):
    """The temporary site repository of the build tests, with a way to run the search step in it."""

    def search(self) -> tuple[int, str]:
        names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
        saved = {n: getattr(utils, n) for n in names}
        utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = self.root, self.root / "data" / "raw", self.root / "data" / "derived"
        utils.DOCS, utils.SITE_YAML, utils.DIST = self.docs, self.root / "site.yaml", self.root / "dist"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = step_search.main([])
        finally:
            for name, value in saved.items():
                setattr(utils, name, value)
        return code, out.getvalue()

    def index_text(self) -> str:
        return (self.docs / "assets" / step_search.INDEX_FILE).read_text(encoding="utf-8")


class StepTests(SearchSite):
    def test_an_empty_repository_has_nothing_to_do(self) -> None:
        shutil.rmtree(self.root / "data")
        code, out = self.search()
        self.assertEqual(code, 0)
        self.assertIn("[search] nothing to do: no entities", out)
        self.assertFalse((self.docs / "assets").exists())

    def test_it_writes_the_index_and_reports_what_it_holds(self) -> None:
        self.build()
        code, out = self.search()
        self.assertEqual(code, 0)
        self.assertIn("[search] 12 entities indexed (2 items, 10 properties), 14 searchable strings, languages: en", out)
        self.assertIn("docs/assets/search-index.js:", out)
        self.assertNotIn("WARN", out)
        self.assertTrue(self.index_text().startswith("window.WBS_SEARCH_INDEX="))

    def test_two_runs_write_the_same_bytes(self) -> None:
        self.build()
        self.search()
        first = (self.docs / "assets" / step_search.INDEX_FILE).read_bytes()
        self.search()
        self.assertEqual((self.docs / "assets" / step_search.INDEX_FILE).read_bytes(), first)
        self.assertNotIn(b"\r", first)
        self.assertTrue(first.endswith(b"};\n"))

    def test_the_languages_come_from_site_yaml(self) -> None:
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        self.search()
        self.assertIn('"languages":["en","de"]', self.index_text())
        self.assertIn('"l":{"de":"Beispielklasse","en":"Example class"}', self.index_text())

    def test_an_index_without_pages_is_a_warning_that_names_the_missing_ones(self) -> None:
        code, out = self.search()                       # the build step has not run: no pages in docs/
        self.assertEqual(code, 0)
        self.assertIn("WARN: [search] 12 indexed entities have no page in docs/ (Q1, Q2, P1, P2, P3, ...); run the build step first", out)

    def test_a_removed_entity_leaves_the_index(self) -> None:
        self.build()
        self.search()
        self.assertIn('"id":"P9"', self.index_text())
        self.entity_path("P9").unlink()
        self.build()
        self.search()
        self.assertNotIn('"id":"P9"', self.index_text())

    def test_entities_without_a_label_are_counted(self) -> None:
        self.edit("P9", lambda data: data.update(labels={}))
        self.build()
        _code, out = self.search()
        self.assertIn("[search] 1 entities have no label and are found by their id only", out)


class PageTests(SearchSite):
    def test_every_page_carries_the_box_and_loads_the_script(self) -> None:
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        for name in ("index.html", "Q1.html", "P4.html"):
            html = self.page(name)
            self.assertIn('<form class="search" role="search" action="#" hidden data-index="assets/search-index.js" data-default="en"', html, name)
            self.assertIn('<script src="assets/search.js"></script>', html, name)
            self.assertIn('role="combobox"', html)
            self.assertIn('placeholder="Search"', html)

    def test_the_box_texts_exist_for_each_language_of_the_site(self) -> None:
        self.site_yaml("languages:\n  default: en\n  second: de\n")
        self.build()
        html = self.page("Q1.html")
        start = html.index('data-text="') + len('data-text="')
        texts = json.loads(html[start:html.index('"', start)].replace("&#34;", '"').replace("&quot;", '"'))
        self.assertEqual(sorted(texts), ["de", "en"])
        self.assertEqual(texts["de"]["placeholder"], "Suche")
        self.assertEqual(texts["de"]["none"], "Keine Treffer")
        self.assertEqual(texts["en"]["none"], "No results")

    def test_a_default_language_without_a_translation_gets_the_english_texts(self) -> None:
        self.site_yaml("languages:\n  default: fr\n")
        self.build()
        self.assertIn('placeholder="Search"', self.page("Q1.html"))

    def test_the_script_is_copied_unchanged_and_the_linkcheck_still_finds_nothing_dead(self) -> None:
        code, out = self.build()
        self.assertEqual(code, 0)
        copied = (self.docs / "assets" / "search.js").read_bytes()
        self.assertEqual(copied, SEARCH_JS.read_bytes())
        self.assertNotIn(b"\r", copied)
        self.assertIn(", 0 dead", out)
        self.assertNotIn("WARN", out)

    def test_the_index_file_is_not_a_link_the_build_checks(self) -> None:
        # The index is named in a data attribute, not in an href or src, so a build that runs before the
        # search step (the order of the pipeline) does not report it as a dead link.
        self.build()
        self.assertFalse((self.docs / "assets" / step_search.INDEX_FILE).exists())
        self.assertNotIn("WARN", self.build()[1])


class StylesheetTests(unittest.TestCase):
    def test_the_tab_rules_do_not_reach_the_list_of_results(self) -> None:
        # The search box sits inside .tabs. A rule like `.tabs ul { display: flex }` or `.tabs li a { display: block }`
        # applies to it as well and lays the results out as a row of columns (seen in the first browser check).
        css = (HERE.parent / "py" / "wikibase_static" / "static" / "style.css").read_text(encoding="utf-8")
        selectors = [s.strip() for block in css.split("{")[:-1] for s in block.rsplit("}", 1)[-1].split(",")]
        leaking = [s for s in selectors if re.match(r"^\.tabs\s+(ul|li|a|span|form|input)\b", s)]
        self.assertEqual(leaking, [], "scope these to .tabs-left / .tabs-view")

    def test_the_list_sits_above_the_leaflet_controls(self) -> None:
        # Leaflet's zoom control has z-index 1000. A list that reaches onto the map (a wide list on a tablet) has to
        # be above it, or the control paints over the first hits (seen in the second browser check, 700 px wide).
        css = (HERE.parent / "py" / "wikibase_static" / "static" / "style.css").read_text(encoding="utf-8")
        block = re.search(r"\.search-results \{[^}]*\}", css)
        self.assertIsNotNone(block)
        z = re.search(r"z-index:\s*(\d+)", block.group(0))
        self.assertIsNotNone(z)
        self.assertGreater(int(z.group(1)), 1000)


# --------------------------------------------------------------------------- the matching, under Node

NODE_SCRIPT = r"""
const fs = require("fs");
const scriptPath = process.argv[2];
const job = JSON.parse(fs.readFileSync(0, "utf8"));
const s = require(scriptPath);
const records = s.prepare(job.index);
const out = job.queries.map(q => {
  const hits = s.search(records, q.query, q.lang || "en", "en");
  return {query: q.query, lang: q.lang || "en",
          ids: hits.map(h => h.entry.id), via: hits.map(h => h.via),
          labels: hits.map(h => s.labelFor(h.entry, q.lang || "en", "en"))};
});
process.stdout.write(JSON.stringify(out));
"""


def forts() -> list[Entity]:
    """Entities that match the query "fort" in each of the ways the script ranks."""
    return [
        entity("Q1", labels={"en": "Roman fort", "de": "Römisches Kastell"}, descriptions={"en": "Roman military camp"},
               aliases={"en": ["castellum"], "de": ["Römerkastell"]}),
        entity("Q3", labels={"en": "Archaeological site"}, descriptions={"en": "a place with a hidden word: lighthouse"}),
        entity("Q4", labels={"en": "Éire"}, aliases={"en": ["Ireland"]}),
        entity("Q10", labels={"en": "Ten"}), entity("Q11", labels={"en": "Eleven"}), entity("Q100", labels={"en": "Hundred"}),
        entity("Q20", labels={"en": "Fort"}),                                               # the whole label
        entity("Q21", labels={"en": "Bastion"}, aliases={"en": ["Fort"]}),                  # the whole alias
        entity("Q22", labels={"en": "Fortress"}),                                           # starts with
        entity("Q23", labels={"en": "Bastille"}, aliases={"en": ["Fortification"]}),         # alias starts with
        entity("Q24", labels={"en": "Roman Fort"}),                                         # a word starts with
        entity("Q25", labels={"en": "Comfort"}),                                            # inside
        entity("P1", labels={"en": "instance of"}), entity("P2", labels={"en": "fort of"}),
    ]


@unittest.skipUnless(NODE, "Node is not installed: the matching in search.js was not run")
class MatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = step_search.build_index(model(*forts()), "en", "de")
        # A script file, not `node -e`: quoting a multi-line program on the command line differs between shells and Windows.
        cls.tmp = tempfile.TemporaryDirectory()
        cls.runner = Path(cls.tmp.name) / "matcher.js"
        cls.runner.write_text(NODE_SCRIPT, encoding="utf-8", newline="\n")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_queries(self, *queries: tuple, index: dict | None = None) -> list[dict]:
        job = {"index": index or self.index,
               "queries": [{"query": q[0], "lang": q[1] if len(q) > 1 else "en"} for q in queries]}
        done = subprocess.run([NODE, str(self.runner), str(SEARCH_JS)], input=json.dumps(job), capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def ids(self, query: str, lang: str = "en") -> list[str]:
        return self.run_queries((query, lang))[0]["ids"]

    def test_a_label_finds_the_entity(self) -> None:
        self.assertEqual(self.ids("Archaeological site"), ["Q3"])
        self.assertEqual(self.ids("archaeo"), ["Q3"])

    def test_an_alias_finds_the_entity_and_says_which_alias_matched(self) -> None:
        result = self.run_queries(("castellum",))[0]
        self.assertEqual(result["ids"], ["Q1"])
        self.assertEqual(result["via"], ["castellum"])

    def test_a_q_id_finds_the_entity_whatever_its_case(self) -> None:
        self.assertEqual(self.ids("Q3"), ["Q3"])
        self.assertEqual(self.ids("q3"), ["Q3"])
        self.assertEqual(self.ids("p1"), ["P1"])

    def test_an_id_that_exists_ranks_ahead_of_ids_that_only_start_like_it(self) -> None:
        ids = self.ids("q10")
        self.assertEqual(ids[:2], ["Q10", "Q100"])

    def test_ids_that_share_a_start_stay_in_id_order(self) -> None:
        self.assertEqual(self.ids("q1"), ["Q1", "Q10", "Q11", "Q100"])

    def test_the_ranking_is_exact_then_start_then_word_then_inside_with_labels_before_aliases(self) -> None:
        ids = self.ids("fort")
        # The labels of the two alias hits (Bastion, Bastille) sort before "Fort", so a script that ranked aliases
        # like labels would put them first. P2 ("fort of") starts with the query like Q22 does and is left out of
        # the comparison: its place among the equals is decided by the label, not by the rule under test.
        order = [i for i in ids if i in ("Q20", "Q21", "Q22", "Q23", "Q24", "Q25")]
        self.assertEqual(order, ["Q20", "Q21", "Q22", "Q23", "Q24", "Q25"])
        self.assertEqual(len(order), 6)

    def test_at_most_ten_results(self) -> None:
        many = step_search.build_index(model(*[entity(f"Q{n}", labels={"en": f"Fort number {n}"}) for n in range(1, 31)]), "en", None)
        self.assertEqual(len(self.run_queries(("fort",), index=many)[0]["ids"]), 10)

    def test_accents_do_not_matter_in_either_direction(self) -> None:
        self.assertEqual(self.ids("eire"), ["Q4"])
        self.assertEqual(self.ids("Éire"), ["Q4"])
        self.assertEqual(self.ids("romisches"), ["Q1"])
        self.assertEqual(self.ids("ROMERKAS"), ["Q1"])

    def test_a_label_in_another_language_finds_the_entity_and_is_named(self) -> None:
        result = self.run_queries(("kastell", "en"))[0]
        self.assertEqual(result["ids"], ["Q1"])
        self.assertEqual(result["via"], ["Römisches Kastell"])     # the page shows the English label; this is why it matched

    def test_the_label_shown_follows_the_language(self) -> None:
        self.assertEqual(self.run_queries(("castellum", "de"))[0]["labels"], ["Römisches Kastell"])
        self.assertEqual(self.run_queries(("castellum", "en"))[0]["labels"], ["Roman fort"])

    def test_every_word_of_the_query_has_to_start_a_word_in_any_order(self) -> None:
        self.assertIn("Q24", self.ids("fort roman"))
        self.assertNotIn("Q24", self.ids("fort xyz"))

    def test_inside_matches_need_three_characters(self) -> None:
        self.assertNotIn("Q25", self.ids("or"))
        self.assertIn("Q25", self.ids("mfo"))

    def test_descriptions_are_shown_but_not_searched(self) -> None:
        self.assertEqual(self.ids("lighthouse"), [])
        self.assertEqual(self.ids("military"), [])

    def test_nothing_matches_an_empty_or_unmatched_query(self) -> None:
        self.assertEqual(self.ids(""), [])
        self.assertEqual(self.ids("   "), [])
        self.assertEqual(self.ids("(("), [])
        self.assertEqual(self.ids("zzzz"), [])

    def test_a_label_like_markup_is_just_text_to_the_matcher(self) -> None:
        self.assertEqual(self.ids("<img src=x onerror=alert(1)>"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
