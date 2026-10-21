"""Tests for the query page (S6): the queries, their check at build time, the page, the files, sparql.js.

    python tests/test_sparql.py

Needs rdflib, Jinja2 and PyYAML (requirements.txt); the script tests need Node and are skipped, with a reason,
when it is missing (GitHub's runners have it). Pyodide itself is not started here (it comes from a CDN): the
Python the page runs is the Python these tests run, see ``sparql.RUNNER_PY``.
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

import test_build  # noqa: E402
from wikibase_static import rdf, sparql, step_build, step_rdf, step_sparql, utils  # noqa: E402
from wikibase_static.loader import load_site  # noqa: E402

SPARQL_JS = HERE.parent / "py" / "wikibase_static" / "static" / "sparql.js"
NODE = shutil.which("node")
NS = rdf.Namespaces("https://wb.example.org")


def write_queries(directory: Path, text: str) -> Path:
    path = directory / "queries.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- the query set


class QuerySetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_default_set_is_valid(self) -> None:
        qs = sparql.load_queries(None)
        self.assertEqual(qs.problems, [])
        self.assertEqual(qs.source, "default")
        self.assertGreaterEqual(len(qs.queries), 10)
        ids = [q.id for q in qs.queries]
        self.assertEqual(len(ids), len(set(ids)))
        for q in qs.queries:
            self.assertRegex(q.sparql, r"(?m)^\s*SELECT\b", q.id)
            self.assertNotRegex(q.sparql, r"(?im)^\s*PREFIX\b", q.id)
            self.assertIsInstance(q.title, dict, q.id)       # both languages, so the page reads in both
            self.assertEqual(set(q.title), {"en", "de"}, q.id)
            self.assertEqual(set(q.intro), {"en", "de"}, q.id)

    def test_a_queries_file_of_the_site_replaces_the_default(self) -> None:
        path = write_queries(self.dir, "queries:\n  - id: mine\n    title: Mine\n    sparql: SELECT ?s WHERE { ?s ?p ?o } LIMIT 1\n")
        qs = sparql.load_queries(path)
        self.assertEqual([q.id for q in qs.queries], ["mine"])
        self.assertEqual(qs.source, "queries.yaml")

    def test_bad_entries_are_reported_and_left_out(self) -> None:
        path = write_queries(self.dir, """queries:
  - title: no id
    sparql: SELECT * WHERE { ?s ?p ?o }
  - id: Bad Id
    sparql: SELECT * WHERE { ?s ?p ?o }
  - id: no-body
  - id: with-prefix
    sparql: |
      PREFIX x: <http://x/>
      SELECT * WHERE { ?s ?p ?o }
  - id: good
    sparql: SELECT * WHERE { ?s ?p ?o }
  - id: good
    sparql: SELECT * WHERE { ?s ?p ?o }
  - just a string
""")
        qs = sparql.load_queries(path)
        self.assertEqual([q.id for q in qs.queries], ["good"])
        text = "\n".join(qs.problems)
        for expected in ("query 1 needs an id", "query 2 needs an id", "query no-body has no 'sparql'", "has PREFIX lines",
                         "used twice", "query 7 is not a mapping"):
            self.assertIn(expected, text)

    def test_unreadable_yaml_is_a_problem_not_a_crash(self) -> None:
        qs = sparql.load_queries(write_queries(self.dir, "queries: [unclosed"))
        self.assertEqual(qs.queries, [])
        self.assertTrue(qs.problems)
        qs = sparql.load_queries(write_queries(self.dir, "nothing: here"))
        self.assertTrue(any("'queries' list" in p for p in qs.problems))

    def test_text_in_resolves_a_language_then_the_default(self) -> None:
        self.assertEqual(sparql.text_in({"en": "A", "de": "B"}, "de", "en"), "B")
        self.assertEqual(sparql.text_in({"en": "A"}, "de", "en"), "A")
        self.assertEqual(sparql.text_in({"fr": "F"}, "de", "en"), "F")
        self.assertEqual(sparql.text_in("plain", "de", "en"), "plain")
        self.assertEqual(sparql.text_in(None, "de", "en"), "")

    def test_the_language_token_is_replaced(self) -> None:
        qs = sparql.QuerySet(queries=[sparql.Query("a", "t", "", 'FILTER(LANG(?x) = "@@lang@@")\n')])
        sparql.apply_language(qs, "de")
        self.assertEqual(qs.queries[0].sparql, 'FILTER(LANG(?x) = "de")\n')

    def test_requirements_leave_out_what_the_data_lacks(self) -> None:
        qs = sparql.QuerySet(queries=[sparql.Query("a", "", "", "x", ["time"]), sparql.Query("b", "", "", "x", ["time", "quantity"]),
                                      sparql.Query("c", "", "", "x")])
        sparql.apply_requirements(qs, {"time"})
        self.assertEqual([q.id for q in qs.queries], ["a", "c"])
        self.assertEqual(qs.left_out, ["b"])

    def test_features_come_from_the_data(self) -> None:
        site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        features = sparql.site_features(site)
        for name in ("globe-coordinate", "time", "reference", "qualifier", "alias", "preferred"):
            self.assertIn(name, features)
        self.assertNotIn("distribution", features)
        self.assertIn("distribution", sparql.site_features(site, "https://p.example/"))


class PrefixTests(unittest.TestCase):
    KNOWN = {"wd": "http://x/wd/", "wdt": "http://x/wdt/", "rdfs": "http://r/"}

    def test_only_used_prefixes_are_found_and_iris_and_strings_are_ignored(self) -> None:
        body = 'SELECT ?x WHERE { ?x wdt:P1 wd:Q1 . FILTER(?x != <http://example.org/rdfs:thing>) } # "rdfs:label"\n'
        # a comment is not parsed away, but IRIs and quoted text are
        self.assertEqual(sparql.used_prefixes(body.split(" #")[0] + "\n", self.KNOWN), ["wd", "wdt"])
        self.assertEqual(sparql.used_prefixes('SELECT ("rdfs:x" AS ?y) WHERE {}', self.KNOWN), [])
        self.assertEqual(sparql.used_prefixes("SELECT * WHERE { ?s rdfs:label ?l }", self.KNOWN), ["rdfs"])

    def test_the_rq_file_carries_its_prefixes(self) -> None:
        q = sparql.Query("a", "", "", "SELECT ?l WHERE { ?s rdfs:label ?l }\n")
        text = sparql.rq_file(q, self.KNOWN)
        self.assertEqual(text, "PREFIX rdfs: <http://r/>\n\nSELECT ?l WHERE { ?s rdfs:label ?l }\n")
        self.assertEqual(sparql.rq_file(sparql.Query("b", "", "", "SELECT * WHERE {}\n"), self.KNOWN), "SELECT * WHERE {}\n")


# --------------------------------------------------------------------------- running the queries


class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        info = rdf.CatalogInfo(title="t", pages_url="https://p.example/", json_sizes={"Q1": 1})
        result = rdf.build(site, NS, None, info)
        cls.ttl = rdf.to_turtle(result.triples, NS)
        cls.prefixes = NS.prefixes()
        cls.site = site

    def run_one(self, body: str) -> dict:
        return sparql.run_all(self.ttl, [sparql.Query("t", "", "", body)], self.prefixes)[0]

    def test_every_default_query_that_applies_returns_rows(self) -> None:
        """The Abnahme of S6 on the fixture: no example query is empty."""
        qs = sparql.load_queries(None)
        sparql.apply_language(qs, "en")
        sparql.apply_requirements(qs, sparql.site_features(self.site, "https://p.example/"))
        self.assertEqual(qs.left_out, [])
        for result in sparql.run_all(self.ttl, qs.queries, self.prefixes):
            self.assertIsNone(result["error"], result["id"])
            self.assertGreaterEqual(result["rows"], 1, result["id"])

    def test_an_empty_result_is_reported_as_zero_rows(self) -> None:
        result = self.run_one("SELECT ?s WHERE { ?s wd:Q99999 wd:Q99999 }")
        self.assertEqual((result["rows"], result["error"]), (0, None))

    def test_a_mistyped_prefix_or_syntax_error_is_an_error_not_a_crash(self) -> None:
        self.assertTrue(self.run_one("SELECT ?s WHERE { ?s nope:x ?o }")["error"])
        self.assertTrue(self.run_one("SELECT ?s WHERE {")["error"])

    def test_only_select_can_be_shown_as_a_table(self) -> None:
        self.assertIn("SELECT", self.run_one("ASK { ?s ?p ?o }")["error"])

    def test_the_runner_caps_the_rows_but_counts_all(self) -> None:
        ns = {}
        exec(compile(sparql.RUNNER_PY, "<runner>", "exec"), ns)
        graph = ns["wbs_parse"](self.ttl)
        data = json.loads(ns["wbs_run"](graph, sparql.prefix_block(self.prefixes) + "SELECT ?s ?p ?o WHERE { ?s ?p ?o }", 5))
        self.assertEqual(len(data["rows"]), 5)
        self.assertGreater(data["total"], 5)
        self.assertEqual(data["triples"], len(graph))
        self.assertEqual(data["cols"], ["s", "p", "o"])

    def test_cells_say_what_kind_of_term_they_are(self) -> None:
        ns = {}
        exec(compile(sparql.RUNNER_PY, "<runner>", "exec"), ns)
        graph = ns["wbs_parse"](self.ttl)
        query = sparql.prefix_block(self.prefixes) + 'SELECT ?item ?label ?n WHERE { ?item rdfs:label ?label . OPTIONAL { ?item wikibase:statements ?n } FILTER(?item = wd:Q1) } LIMIT 1'
        row = json.loads(ns["wbs_run"](graph, query, 5))["rows"][0]
        self.assertEqual(row[0], ["u", NS.wd + "Q1", ""])
        self.assertEqual(row[1][0], "l")
        self.assertEqual(row[1][2], "en")
        self.assertEqual(row[2], ["l", "11", rdf.XSD + "integer"])


# --------------------------------------------------------------------------- the step and the page


def run_step(case: test_build.Site, module, args=()) -> tuple[int, str]:
    names = ("ROOT", "DATA_RAW", "DATA_DERIVED", "DOCS", "SITE_YAML", "DIST")
    saved = {n: getattr(utils, n) for n in names}
    utils.ROOT, utils.DATA_RAW, utils.DATA_DERIVED = case.root, case.root / "data" / "raw", case.root / "data" / "derived"
    utils.DOCS, utils.SITE_YAML, utils.DIST = case.docs, case.root / "site.yaml", case.root / "dist"
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = module.main(list(args))
    finally:
        for name, value in saved.items():
            setattr(utils, name, value)
    return code, out.getvalue()


class StepTests(test_build.Site):
    SITE = "title: Test wiki\nsource:\n  url: https://wb.example.org\npages_url: https://pages.example.org/site/\nlanguages:\n  default: en\n  second: de\n"

    def pipeline(self) -> str:
        out = ""
        for module in (step_build, step_rdf, step_sparql):
            code, text = run_step(self, module)
            self.assertEqual(code, 0)
            out += text
        return out

    def tree(self) -> dict[str, bytes]:
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob("*"))
                if p.is_file() and p.relative_to(self.root).parts[0] in ("docs", "dist")}

    def test_the_pipeline_writes_the_page_the_downloads_and_the_files_of_each_entity(self) -> None:
        self.site_yaml(self.SITE)
        out = self.pipeline()
        self.assertNotIn("WARN", out)
        for path in ("sparql.html", "downloads/wb.example.org.ttl", "downloads/wikibase-ontology.ttl", "downloads/queries/items.rq",
                     "ttl/Q1.ttl", "ttl/P1.json" if False else "json/Q1.json", "assets/sparql.js"):
            self.assertTrue((self.docs / path).is_file(), path)
        self.assertTrue((self.root / "dist" / "wb.example.org.ttl").is_file())
        self.assertEqual((self.docs / "downloads" / "wb.example.org.ttl").read_bytes(), (self.root / "dist" / "wb.example.org.ttl").read_bytes())
        self.assertEqual((self.docs / "json" / "Q1.json").read_bytes(), self.entity_path("Q1").read_bytes())
        self.assertEqual(len(list((self.docs / "ttl").glob("*.ttl"))), 12)

    def test_every_page_links_to_the_query_page_and_the_link_is_alive(self) -> None:
        self.site_yaml(self.SITE)
        self.pipeline()
        for name in ("index.html", "Q1.html", "P1.html", "sparql.html"):
            self.assertIn('<a href="sparql.html"', self.page(name), name)
        self.assertIn('aria-current="page"', self.page("sparql.html"))
        checked, dead = step_build.linkcheck(self.docs)
        self.assertEqual(dead, [])

    def test_the_first_build_does_not_report_the_not_yet_written_query_page(self) -> None:
        self.site_yaml(self.SITE)
        code, out = run_step(self, step_build)
        self.assertEqual(code, 0)
        self.assertNotIn("WARN", out)
        self.assertFalse((self.docs / "sparql.html").exists())

    def test_the_page_has_every_query_in_both_languages_and_the_prefixes(self) -> None:
        self.site_yaml(self.SITE)
        self.pipeline()
        html = self.page("sparql.html")
        self.assertIn('<html lang="en" data-lang="en">', html)
        for qid in ("items", "properties", "references", "coordinates"):
            self.assertIn(f'<section class="query" id="{qid}">', html)
            self.assertIn(f"downloads/queries/{qid}.rq", html)
        self.assertIn('<span class="l" lang="en">Items with label and description</span><span class="l" lang="de">Items mit Bezeichnung und Beschreibung</span>', html)
        self.assertIn("PREFIX wd: &lt;https://wb.example.org/entity/&gt;", html)
        self.assertIn('FILTER(LANG(?label) = &#34;en&#34;)', html)
        self.assertNotIn("@@lang@@", html)
        self.assertIn('<script src="assets/sparql.js">', html)
        self.assertNotRegex(html, r'<script\b[^>]*\ssrc="https?://')            # on load, nothing is fetched from another site
        self.assertNotRegex(html, r'<link\b[^>]*rel="stylesheet"[^>]*href="https?://')

    def test_the_config_and_the_runner_are_valid_json_that_cannot_end_the_script(self) -> None:
        self.site_yaml(self.SITE)
        self.pipeline()
        html = self.page("sparql.html")
        config = json.loads(re.search(r'<script type="application/json" id="wbs-sparql-config">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(config["pyodideUrl"], f"https://cdn.jsdelivr.net/pyodide/v{sparql.PYODIDE_VERSION}/full/pyodide.js")
        self.assertEqual(config["rdflibVersion"], sparql.RDFLIB_VERSION)
        self.assertEqual(config["graphUrl"], "downloads/wb.example.org.ttl")
        self.assertEqual(config["entityBase"], NS.wd)
        self.assertEqual(set(config["texts"]), {"en", "de"})
        self.assertEqual(set(config["texts"]["en"]), set(config["texts"]["de"]))
        runner = json.loads(re.search(r'id="wbs-sparql-runner">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(runner, sparql.RUNNER_PY)

    def test_a_queries_file_in_the_repository_is_used_and_escaped(self) -> None:
        self.site_yaml(self.SITE)
        (self.root / "queries.yaml").write_text("""page:
  title: A <b>title</b>
queries:
  - id: mine
    title: "Tags </script><script>alert(1)</script>"
    intro: "Fish & chips"
    sparql: |
      SELECT ?label WHERE { ?s rdfs:label ?label . FILTER(?label != "<x>") } LIMIT 3
""", encoding="utf-8")
        out = self.pipeline()
        self.assertIn("1 queries from queries.yaml", out)
        html = self.page("sparql.html")
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;/script&gt;&lt;script&gt;alert(1)", html)
        self.assertIn("Fish &amp; chips", html)
        self.assertIn("A &lt;b&gt;title&lt;/b&gt;", html)
        self.assertEqual((self.docs / "downloads" / "queries" / "mine.rq").read_text(encoding="utf-8").splitlines()[0], "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>")
        self.assertFalse((self.docs / "downloads" / "queries" / "items.rq").exists())

    def test_an_empty_example_is_a_warning(self) -> None:
        self.site_yaml(self.SITE)
        (self.root / "queries.yaml").write_text("queries:\n  - id: empty\n    sparql: SELECT ?s WHERE { ?s wd:Q99999 wd:Q99999 }\n  - id: broken\n    sparql: SELECT ?s WHERE { ?s nope:x ?o }\n", encoding="utf-8")
        out = self.pipeline()
        self.assertIn("WARN: [sparql] query empty returns no rows", out)
        self.assertIn("WARN: [sparql] query broken failed:", out)

    def test_without_the_rdf_step_the_query_step_says_so(self) -> None:
        self.site_yaml(self.SITE)
        run_step(self, step_build)
        code, out = run_step(self, step_sparql)
        self.assertEqual(code, 0)
        self.assertIn("WARN: [sparql] dist/wb.example.org.ttl not found; run the rdf step first", out)
        self.assertFalse((self.docs / "sparql.html").exists())

    def test_a_stale_download_is_reported(self) -> None:
        self.site_yaml(self.SITE)
        self.pipeline()
        (self.docs / "downloads" / "wb.example.org.ttl").write_text("# old\n", encoding="utf-8")
        code, out = run_step(self, step_sparql)
        self.assertIn("differs from dist/wb.example.org.ttl", out)

    def test_without_pages_url_the_distribution_query_is_left_out_and_nothing_warns(self) -> None:
        self.site_yaml("title: T\nsource:\n  url: https://wb.example.org\n")
        out = self.pipeline()
        self.assertNotIn("WARN", out)
        self.assertIn("left out because the data has nothing for them: distributions", out)
        self.assertFalse((self.docs / "downloads" / "queries" / "distributions.rq").exists())

    def test_the_whole_output_is_byte_identical_over_two_runs(self) -> None:
        self.site_yaml(self.SITE)
        self.pipeline()
        first = self.tree()
        self.pipeline()
        second = self.tree()
        self.assertEqual(sorted(first), sorted(second))
        changed = [k for k in first if first[k] != second[k]]
        self.assertEqual(changed, [])

    def test_files_of_removed_entities_are_removed(self) -> None:
        self.site_yaml(self.SITE)
        self.pipeline()
        self.entity_path("Q2").unlink()
        self.pipeline()
        self.assertFalse((self.docs / "ttl" / "Q2.ttl").exists())
        self.assertFalse((self.docs / "json" / "Q2.json").exists())
        self.assertTrue((self.docs / "ttl" / "Q1.ttl").exists())

    def test_the_rdf_base_of_site_yaml_wins_over_the_source_url(self) -> None:
        self.site_yaml("source:\n  url: https://wb.example.org\nrdf_base: https://other.example.net/w\n")
        self.pipeline()
        self.assertTrue((self.root / "dist" / "other.example.net-w.ttl").is_file())
        self.assertIn("@prefix wd: <https://other.example.net/w/entity/> .", (self.root / "dist" / "other.example.net-w.ttl").read_text(encoding="utf-8"))

    def test_a_bad_rdf_base_is_a_warning_and_the_source_url_is_used(self) -> None:
        self.site_yaml("source:\n  url: https://wb.example.org\nrdf_base: not a url\n")
        code, out = run_step(self, step_build)
        self.assertIn("WARN: [build] site.yaml: rdf_base 'not a url' is not an http(s) URL", out)

    def test_no_entities_means_nothing_to_do(self) -> None:
        shutil.rmtree(self.root / "data" / "raw" / "entities")
        for module in (step_rdf, step_sparql):
            code, out = run_step(self, module)
            self.assertEqual(code, 0)
            self.assertIn("nothing to do", out)


# --------------------------------------------------------------------------- sparql.js under Node


@unittest.skipUnless(NODE, "Node is not installed")
class ScriptTests(unittest.TestCase):
    def node(self, body: str) -> object:
        code = f"const m = require({json.dumps(str(SPARQL_JS))}); const out = (function(){{ {body} }})(); console.log(JSON.stringify(out));"
        done = subprocess.run([NODE, "-e", code], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    TEXTS = '{unbound:"none",empty:"No results",capped:"first {shown} of {total}",rows_one:"1 row",rows_other:"{n} rows"}'
    CONFIG = '{entityBase:"https://wb.example.org/entity/",prefixes:{wd:"https://wb.example.org/entity/",wdt:"https://wb.example.org/prop/direct/"}}'

    def test_escape_covers_the_five_characters(self) -> None:
        self.assertEqual(self.node('return m.esc(`<a href="x">&\'</a>`);'), "&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;")

    def test_format_fills_names_and_keeps_unknown_ones(self) -> None:
        self.assertEqual(self.node('return m.format("{n} of {total} {x}", {n: 2, total: 5});'), "2 of 5 {x}")

    def test_the_prefixes_come_first(self) -> None:
        self.assertEqual(self.node('return m.fullQuery("PREFIX a: <x>\\n", "SELECT * {}");'), "PREFIX a: <x>\nSELECT * {}")

    def test_wikibase_iris_link_to_the_page_of_the_site_and_others_to_themselves(self) -> None:
        self.assertEqual(self.node(f'return [m.iriHref("https://wb.example.org/entity/Q12", {self.CONFIG}), m.iriHref("https://wb.example.org/entity/statement/Q1-x", {self.CONFIG}), m.iriHref("https://example.org/a", {self.CONFIG}), m.iriHref("urn:x:y", {self.CONFIG})];'),
                         ["Q12.html", "https://wb.example.org/entity/statement/Q1-x", "https://example.org/a", None])

    def test_iris_are_shortened_with_the_longest_matching_namespace(self) -> None:
        self.assertEqual(self.node(f'return [m.shortIri("https://wb.example.org/entity/Q1", {self.CONFIG}), m.shortIri("https://elsewhere.org/x", {self.CONFIG}), m.shortIri("https://wb.example.org/entity/", {self.CONFIG})];'),
                         ["wd:Q1", "https://elsewhere.org/x", "https://wb.example.org/entity/"])

    def test_values_from_the_data_cannot_inject_markup(self) -> None:
        html = self.node(f'return m.resultHtml({{cols:["<th>"],rows:[[["l","<img src=x onerror=alert(1)>",""]],[["u","https://e.org/\\"onmouseover=\\"x",""]],[["b","<b>",""]]],total:3}}, {self.CONFIG}, {self.TEXTS});')
        self.assertNotIn("<img", html)
        self.assertNotIn('"onmouseover', html)
        self.assertNotIn("<th><th>", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)

    def test_unbound_cells_and_language_tags_are_marked(self) -> None:
        html = self.node(f'return m.resultHtml({{cols:["a","b"],rows:[[null,["l","Haus","de"]]],total:1}}, {self.CONFIG}, {self.TEXTS});')
        self.assertIn('<td class="nil" title="none">&mdash;</td>', html)
        self.assertIn('Haus <span class="lang">@de</span>', html)
        self.assertIn("1 row", html)

    def test_a_datatype_is_a_tooltip_not_text(self) -> None:
        html = self.node(f'return m.cellHtml(["l","5","http://www.w3.org/2001/XMLSchema#integer"], {self.CONFIG}, {self.TEXTS});')
        self.assertEqual(html, '<td title="http://www.w3.org/2001/XMLSchema#integer">5</td>')

    def test_no_rows_says_so_and_a_capped_result_says_how_many_there_are(self) -> None:
        self.assertIn("No results", self.node(f'return m.resultHtml({{cols:["a"],rows:[],total:0}}, {self.CONFIG}, {self.TEXTS});'))
        self.assertIn("first 1 of 700", self.node(f'return m.resultHtml({{cols:["a"],rows:[[["l","x",""]]],total:700}}, {self.CONFIG}, {self.TEXTS});'))

    def test_real_results_of_the_runner_render(self) -> None:
        """What Python produces is what the script renders: the fixture's first query, end to end."""
        site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        text = rdf.to_turtle(rdf.build(site, NS).triples, NS)
        ns = {}
        exec(compile(sparql.RUNNER_PY, "<runner>", "exec"), ns)
        graph = ns["wbs_parse"](text)
        qs = sparql.load_queries(None)
        sparql.apply_language(qs, "en")
        query = next(q for q in qs.queries if q.id == "items")
        data = ns["wbs_run"](graph, sparql.prefix_block(NS.prefixes()) + query.sparql, 500)
        config = json.dumps({"entityBase": NS.wd, "prefixes": NS.prefixes()})
        html = self.node(f'return m.resultHtml({data}, {config}, {self.TEXTS});')
        self.assertIn('<a href="Q1.html">wd:Q1</a>', html)
        self.assertIn("<th>item</th><th>label</th><th>description</th>", html)
        self.assertIn("2 rows", html)


if __name__ == "__main__":
    unittest.main()
