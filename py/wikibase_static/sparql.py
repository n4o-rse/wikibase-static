"""S6 -- the example queries of ``docs/sparql.html``: load, check, run.

Pure functions plus the one Python snippet that both the browser (under Pyodide) and the build (under CPython)
execute, so the query the build verified is the query the reader runs. Nothing here writes a file.

Queries come from ``queries.yaml`` in the site repository when it exists, else from the package's
``data/queries.default.yaml``. Schema::

    page:                         # optional
      title: Query the data       # text, or {en: ..., de: ...}
      intro: ...
    queries:
      - id: items-by-label        # slug; also the file name of the .rq download
        title: Items            # text or {en:, de:}
        intro: ...
        requires: [globe-coordinate]   # optional; the query is left out when the site has none of these
        sparql: |
          SELECT ... WHERE { ... }     # without PREFIX lines: they are added from the namespaces of the export

``requires`` names a property datatype (``globe-coordinate``, ``time``, ...) or one of ``reference``,
``qualifier``, ``alias``, ``preferred``, ``somevalue``, ``image`` (a Commons file, or a URL that ends in .jpg, .png and the like),
``distribution`` (the site states ``pages_url``), ``crm`` (the site has ``data/crm.csv``).

A comment line ``#defaultView:Map`` (or ``ImageGrid``, ``Table``) at the top of a query names the view of the query editor that opens first.
``@@lang@@`` in a query is replaced by the default language of the site. A query that is kept must return at least one row, or the
build fails: SPARQL answers a mistyped IRI with no rows, so an empty result is the usual symptom of a broken
export (PRIMER.md, S6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wikibase_static.loader import Site

PYODIDE_VERSION = "0.26.4"
RDFLIB_VERSION = "7.1.1"
MAX_ROWS = 500
PACKAGE = Path(__file__).resolve().parent
DEFAULT_QUERIES = PACKAGE / "data" / "queries.default.yaml"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FEATURES = {"reference", "qualifier", "alias", "preferred", "somevalue", "image", "crm"}
IMAGE_FILE = re.compile(r"\.(jpe?g|png|gif|svg|webp|tiff?)$", re.IGNORECASE)

# Executed by the page (Pyodide) and by the build (CPython), unchanged. ``wbs_run`` returns JSON text:
# {"kind": "select", "cols": [...], "rows": [[cell, ...]], "total": n, "triples": n}, or {"kind": "ask", "answer": bool, ...},
# or {"kind": "graph", "count": n, "turtle": "..."} for CONSTRUCT and DESCRIBE; a cell is null (unbound) or [kind, text, extra]
# with kind "u" (IRI), "l" (literal; extra is the language tag or the datatype IRI, or "") or "b" (blank node).
RUNNER_PY = '''\
import json
from rdflib import Graph, URIRef, BNode, Literal


def wbs_parse(text):
    g = Graph()
    g.parse(data=text, format="turtle")
    return g


def wbs_cell(term):
    if term is None:
        return None
    if isinstance(term, URIRef):
        return ["u", str(term), ""]
    if isinstance(term, BNode):
        return ["b", str(term), ""]
    extra = term.language or (str(term.datatype) if term.datatype else "")
    return ["l", str(term), extra]


def wbs_run(g, query, max_rows):
    res = g.query(query)
    out = {"triples": len(g)}
    if res.type == "ASK":
        out.update(kind="ask", answer=bool(res.askAnswer))
    elif res.type == "SELECT":
        cols = [str(v) for v in res.vars]
        rows = []
        total = 0
        for row in res:
            total += 1
            if total <= max_rows:
                rows.append([wbs_cell(row[i]) for i in range(len(cols))])
        out.update(kind="select", cols=cols, rows=rows, total=total)
    else:
        result = res.graph
        for prefix, namespace in g.namespaces():
            result.bind(prefix, namespace, override=False)
        out.update(kind="graph", count=len(result), turtle=result.serialize(format="turtle"))
    return json.dumps(out)
'''


@dataclass
class Query:
    id: str
    title: Any                      # str or {lang: str}
    intro: Any
    sparql: str
    requires: list[str] = field(default_factory=list)


@dataclass
class QuerySet:
    queries: list[Query]
    title: Any = None
    intro: Any = None
    source: str = "default"         # "queries.yaml" or "default"
    problems: list[str] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)      # ids dropped because the site lacks a required feature


def text_in(value: Any, language: str, default: str) -> str:
    """A plain string, or a ``{lang: text}`` mapping resolved for one language (then the default, then any)."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in (language, default):
            if isinstance(value.get(key), str):
                return value[key].strip()
        for key in sorted(value):
            if isinstance(value[key], str):
                return value[key].strip()
        return ""
    return str(value).strip()


def load_queries(path: Path | None) -> QuerySet:
    """Parse ``path`` (the site's file) or the packaged default. Problems are collected, never raised."""
    import yaml

    source = "queries.yaml" if path is not None and path.is_file() else "default"
    use = path if source == "queries.yaml" else DEFAULT_QUERIES
    result = QuerySet(queries=[], source=source)
    try:
        data = yaml.safe_load(use.read_text(encoding="utf-8"))
    except Exception as err:
        result.problems.append(f"{use.name}: not readable ({str(err).splitlines()[0] if str(err) else type(err).__name__})")
        return result
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        result.problems.append(f"{use.name}: needs a top-level 'queries' list")
        return result
    page = data.get("page") if isinstance(data.get("page"), dict) else {}
    result.title, result.intro = page.get("title"), page.get("intro")
    seen: set[str] = set()
    for position, raw in enumerate(data["queries"], 1):
        if not isinstance(raw, dict):
            result.problems.append(f"{use.name}: query {position} is not a mapping; ignored")
            continue
        qid, body = raw.get("id"), raw.get("sparql")
        if not isinstance(qid, str) or not SLUG.match(qid):
            result.problems.append(f"{use.name}: query {position} needs an id like 'items-by-label'; ignored")
            continue
        if qid in seen:
            result.problems.append(f"{use.name}: id {qid!r} is used twice; the second is ignored")
            continue
        if not isinstance(body, str) or not body.strip():
            result.problems.append(f"{use.name}: query {qid} has no 'sparql'; ignored")
            continue
        if re.search(r"(?im)^\s*PREFIX\b", body):
            result.problems.append(f"{use.name}: query {qid} has PREFIX lines; they are added automatically, remove them")
            continue
        requires = raw.get("requires") or []
        if isinstance(requires, str):
            requires = [requires]
        if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
            result.problems.append(f"{use.name}: query {qid}: requires must be a list of names; ignored")
            continue
        seen.add(qid)
        result.queries.append(Query(qid, raw.get("title") or qid, raw.get("intro") or "", body.strip("\n") + "\n", list(requires)))
    return result


LANG_TOKEN = "@@lang@@"


def apply_language(queries: QuerySet, language: str) -> None:
    """Replace ``@@lang@@`` in every query by the default language of the site (so ``LANG(?x) = "@@lang@@"`` works)."""
    for query in queries.queries:
        query.sparql = query.sparql.replace(LANG_TOKEN, language)


def site_features(site: Site, pages_url: str | None = None) -> set[str]:
    """What the data contains, for ``requires``: property datatypes plus the names in ``FEATURES``."""
    found = {e.datatype for e in site.properties if e.datatype}
    if pages_url:
        found.add("distribution")
    if site.crm:
        found.add("crm")
    for entity in site.entities.values():
        if entity.aliases and any(entity.aliases.values()):
            found.add("alias")
        for statement in entity.statements:
            if statement.references:
                found.add("reference")
            if statement.qualifiers:
                found.add("qualifier")
            if statement.rank == "preferred":
                found.add("preferred")
            if statement.mainsnak.snaktype == "somevalue":
                found.add("somevalue")
            snak = statement.mainsnak
            if snak.snaktype == "value" and isinstance(snak.value, str) and (
                    snak.datatype == "commonsMedia" or (snak.datatype == "url" and IMAGE_FILE.search(snak.value.split("?")[0]))):
                found.add("image")
    return found


def apply_requirements(queries: QuerySet, features: set[str]) -> None:
    """Drop the queries whose ``requires`` the site does not meet; their ids go to ``left_out``."""
    kept = []
    for query in queries.queries:
        if all(name in features for name in query.requires):
            kept.append(query)
        else:
            queries.left_out.append(query.id)
    queries.queries = kept


_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')
_IRIREF = re.compile(r"<[^<>\s]*>")
_PNAME = re.compile(r"(?<![\w:/#.-])([A-Za-z][\w-]*):")


def used_prefixes(body: str, known: dict[str, str]) -> list[str]:
    """The prefixes of ``known`` that ``body`` uses, sorted (IRIs and string literals are not searched)."""
    plain = _IRIREF.sub(" ", _STRING.sub(" ", body))
    return sorted({m for m in _PNAME.findall(plain) if m in known})


def prefix_block(prefixes: dict[str, str], names: list[str] | None = None) -> str:
    chosen = sorted(prefixes) if names is None else names
    return "".join(f"PREFIX {name}: <{prefixes[name]}>\n" for name in chosen)


def rq_file(query: Query, prefixes: dict[str, str]) -> str:
    """The text of the downloadable ``.rq``: the prefixes the query uses, a blank line, the query."""
    block = prefix_block(prefixes, used_prefixes(query.sparql, prefixes))
    return (block + "\n" if block else "") + query.sparql


def run_all(ttl_text: str, queries: list[Query], prefixes: dict[str, str]) -> list[dict[str, Any]]:
    """Execute every query with the shared runner against the Turtle text; one result dict per query.

    ``rows`` is the total number of rows, ``error`` a message when the query failed (parse error, not SELECT)."""
    namespace: dict[str, Any] = {}
    exec(compile(RUNNER_PY, "<wbs-runner>", "exec"), namespace)
    graph = namespace["wbs_parse"](ttl_text)
    full = prefix_block(prefixes)
    results = []
    for query in queries:
        entry: dict[str, Any] = {"id": query.id, "rows": 0, "error": None, "cols": []}
        try:
            data = json.loads(namespace["wbs_run"](graph, full + query.sparql, MAX_ROWS))
            entry["kind"] = data["kind"]
            entry["rows"] = data["total"] if data["kind"] == "select" else (data["count"] if data["kind"] == "graph" else 1)
            entry["cols"], entry["triples"] = data.get("cols", []), data["triples"]
        except Exception as err:   # a bad query is the author's mistake: report, do not abort
            entry["error"] = (str(err).splitlines() or [type(err).__name__])[0][:200]
        results.append(entry)
    return results
