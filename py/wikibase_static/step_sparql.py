"""S6 -- the query page: example queries that run in the browser over the Turtle file.

    python main.py sparql

Reads ``dist/<host>.ttl`` (made by ``rdf``), the queries (``queries.yaml`` of the site repository, else the
package's default set) and ``site.yaml`` and writes::

    docs/sparql.html                   the page: editable example queries, Run, results as tables
    docs/query.html                    the free query editor: any query, result as table, map or pictures
    docs/downloads/queries/<id>.rq     every query as a plain file, with the prefixes it uses

Every query is executed here, against the very file the page serves and with the Python the page runs, and
**a query that returns no rows fails the build** (a WARN line, an error under ``--strict``): SPARQL answers a
mistyped IRI with no rows, so an empty example is the usual symptom of a broken export. Queries whose
``requires`` the data does not meet (no coordinates, no references, ...) are left out and named in the log.
Nothing here uses the network or the clock; the browser fetches Pyodide only when somebody presses Run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_sparql.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, rdf, sparql, utils
from wikibase_static.loader import load_site

STEP = "sparql"
QUERIES_FILE = "queries.yaml"
SHOWN = 5


def js_json(value) -> str:
    """JSON for a ``<script type="application/json">``: no ``</script>`` can end it, no U+2028 breaks it."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py sparql", description="Build the query page.")
    parser.parse_args(argv)

    site = load_site()
    if not site.entities:
        utils.nothing_to_do(STEP, "no entities in data/raw/entities or data/derived/entities")
        return 0

    # Only now: these need PyYAML, Jinja2 and rdflib, and an empty repository must not.
    from wikibase_static import step_build, step_rdf
    from wikibase_static.render import Renderer
    from wikibase_static.site_config import load_config
    from markupsafe import Markup, escape

    cfg = load_config(utils.SITE_YAML, site.source_url)
    base, _placeholder = step_rdf.resolve_base(cfg)
    ns = rdf.Namespaces(base)
    stem = rdf.file_stem(base)
    ttl = step_rdf.target_file(base)
    if not ttl.is_file():
        utils.warn(STEP, f"{ttl.relative_to(utils.ROOT).as_posix()} not found; run the rdf step first (python main.py rdf)")
        return 0
    published = utils.DOCS / "downloads" / f"{stem}.ttl"
    problems: list[str] = []
    if not published.is_file() or published.read_bytes() != ttl.read_bytes():
        problems.append(f"docs/downloads/{stem}.ttl is missing or differs from {ttl.relative_to(utils.ROOT).as_posix()}; run the rdf step")

    queries = sparql.load_queries(utils.ROOT / QUERIES_FILE)
    problems += queries.problems
    sparql.apply_language(queries, cfg.default_language)
    sparql.apply_requirements(queries, sparql.site_features(site, cfg.pages_url))
    print(f"[{STEP}] {len(queries.queries)} queries from {queries.source}"
          + (f"; left out because the data has nothing for them: {', '.join(queries.left_out)}" if queries.left_out else ""))
    if not queries.queries:
        problems.append("no query left to show; the page was not written")
        for message in problems:
            utils.warn(STEP, message)
        return 0

    prefixes = ns.prefixes()
    results = sparql.run_all(ttl.read_text(encoding="utf-8"), queries.queries, prefixes)
    for result in results:
        if result["error"]:
            problems.append(f"query {result['id']} failed: {result['error']}")
        elif result["rows"] == 0:
            problems.append(f"query {result['id']} returns no rows; an empty example points to a broken export or query")
        print(f"[{STEP}]   {result['id']}: {'ERROR' if result['error'] else result['rows']} rows")
    triples = max((r.get("triples", 0) for r in results), default=0)

    # ---- the files
    queries_dir = utils.DOCS / "downloads" / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)
    wanted = {f"{q.id}.rq": step_rdf.utils_bytes(sparql.rq_file(q, prefixes)) for q in queries.queries}
    step_rdf._sync(queries_dir, wanted)

    # ---- the page
    r = Renderer(site, cfg, __version__)
    default, second = cfg.default_language, cfg.second_language
    logo = step_build.logo_href(cfg.logo)
    common = step_build.page_context(site, cfg, r, logo)

    def both(value, fallback: str = "") -> Markup:
        first = sparql.text_in(value, default, default) or fallback
        other = sparql.text_in(value, second, default) if second else None
        return r.bilingual(first, other or first)

    heading_value = queries.title or {"en": "Query the data", "de": "Daten abfragen"}
    heading = both(heading_value, "Query the data")
    heading_text = sparql.text_in(heading_value, default, default) or "Query the data"
    rows = [{
        "id": q.id, "title": both(q.title, q.id), "title_text": sparql.text_in(q.title, default, default) or q.id,
        "intro": both(q.intro) if q.intro else None, "sparql": q.sparql.rstrip("\n"),
        "lines": min(max(q.sparql.count("\n") + 1, 4), 30), "rq": f"downloads/queries/{q.id}.rq",
    } for q in queries.queries]

    config = {
        "default": default, "pyodideUrl": f"https://cdn.jsdelivr.net/pyodide/v{sparql.PYODIDE_VERSION}/full/pyodide.js",
        "rdflibVersion": sparql.RDFLIB_VERSION, "graphUrl": f"downloads/{stem}.ttl", "maxRows": sparql.MAX_ROWS,
        "entityBase": ns.wd, "prefixes": prefixes, "prefixText": sparql.prefix_block(prefixes), "texts": r.sparql_texts(),
    }
    context = common("sparql.html", f"{heading_text} – {cfg.title}", None, r.footer(None))
    context.update({
        "heading": heading, "intro": both(queries.intro) if queries.intro else None, "queries": rows,
        "graph_url": f"downloads/{stem}.ttl", "graph_name": f"{stem}.ttl",
        "ontology_url": "downloads/wikibase-ontology.ttl" if (utils.DOCS / "downloads" / "wikibase-ontology.ttl").is_file() else None,
        "pages_known": bool(cfg.pages_url), "prefix_text": sparql.prefix_block(prefixes),
        "config_json": js_json(config), "runner_json": js_json(sparql.RUNNER_PY),
        "ui_sq_data": r.ui("sq_data"), "ui_sq_data_text": r.ui("sq_data_text", n=triples),
        "ui_sq_ontology": r.ui("sq_ontology"), "ui_sq_files": r.ui("sq_files"), "ui_sq_files_text": r.ui("sq_files_text"),
        "ui_sq_start": r.ui("sq_start"), "ui_sq_noscript": r.ui("sq_noscript"), "ui_sq_note": r.ui("sq_note"),
        "ui_sq_prefixes": r.ui("sq_prefixes"), "ui_sq_run": r.ui("sq_run"), "ui_sq_reset": r.ui("sq_reset"), "ui_sq_rq": r.ui("sq_rq"),
    })
    context["ui_sq_to_editor"] = r.ui("sq_to_editor")
    env = step_build.make_env()
    page = utils.DOCS / "sparql.html"
    utils.write_text(page, env.get_template("sparql.html").render(context))

    # ---- the free editor: the same queries as a list of examples, the first of them as the starting query
    languages = [default] + ([second] if second else [])
    editor_config = dict(config, examples=[
        {"id": q.id, "title": {language: sparql.text_in(q.title, language, default) or q.id for language in languages},
         "sparql": q.sparql.rstrip("\n")} for q in queries.queries])
    editor = common("query.html", f"{r.ui_text('sq_q_heading')} – {cfg.title}", None, r.footer(None))
    editor.update({key: value for key, value in context.items() if key.startswith(("ui_sq_", "graph_", "ontology_", "prefix_text", "runner_json"))})
    editor.update({
        "leaflet": True, "config_json": js_json(editor_config), "start_query": queries.queries[0].sparql.rstrip("\n"),
        "ui_query": r.ui("query"),
        **{f"ui_{key}": r.ui(f"sq_{key}") for key in ("q_heading", "q_intro", "q_examples", "q_run", "q_share", "q_table", "q_map",
                                              "q_images", "q_download", "q_hint")},
        **{f"ui_{key}_text": r.ui_text(f"sq_{key}") for key in ("q_pick", "q_editor", "q_views", "q_map")},
    })
    editor_page = utils.DOCS / "query.html"
    utils.write_text(editor_page, env.get_template("query.html").render(editor))

    # Only the links of these pages: the other pages were checked by the build step, and a dead link is reported once.
    dead: list[str] = []
    checked = 0
    for name in ("sparql.html", "query.html"):
        targets = step_build.internal_targets((utils.DOCS / name).read_text(encoding="utf-8"))
        checked += len(targets)
        dead += [f"{name} -> {t}" for t in sorted(set(targets)) if not (utils.DOCS / t).is_file()]
    dead = sorted(set(dead))
    print(f"[{STEP}] docs/sparql.html: {len(rows)} queries, {triples} triples; docs/query.html: editor with {len(rows)} examples")
    print(f"[{STEP}] linkcheck {checked} internal links, {len(dead)} dead")
    for message in problems:
        utils.warn(STEP, message)
    for link in dead:
        utils.warn(STEP, f"dead internal link {link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
