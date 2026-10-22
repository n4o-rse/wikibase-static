"""S12 -- check that everything is anchored in the CIDOC CRM.

    python main.py check-crm

Reads the Turtle export (``dist/<host>.ttl``, written by ``rdf``) and validates it with pySHACL against
``data/shapes-crm.ttl`` of the package. The rule is the one the N4O profile applies (``n4o-kg-profile``,
``crm_anchor``): a class reaches a class of the CIDOC CRM namespaces over ``rdfs:subClassOf``, without inference.

* every class of the site (a ``wd:Q...`` that is the type of an item or has a superclass) and every DCAT class of the
  export must reach a CRM class, otherwise ``WARN`` (a violation; ``--strict`` turns it into an error);
* a class that reaches only E1 CRM Entity is reported as a note (``dcat:Resource`` is E1 and no more than a fallback).

The step is no part of the default run: a harvested Wikibase has no ``data/crm.csv`` yet and would fail it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_check_crm.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils
from wikibase_static.loader import load_site

STEP = "check-crm"
SHAPES = Path(__file__).resolve().parent / "data" / "shapes-crm.ttl"
SH = "http://www.w3.org/ns/shacl#"


def shapes_text(base: str) -> str:
    return SHAPES.read_text(encoding="utf-8").replace("@@base@@", base.rstrip("/"))


def validate(turtle: str, base: str) -> list[tuple[str, str, str]]:
    """``(severity, focus node, message)`` for each result, sorted; severity is ``Violation`` or ``Warning``."""
    import pyshacl
    import rdflib

    data = rdflib.Graph()
    data.parse(data=turtle, format="turtle")
    shapes = rdflib.Graph()
    shapes.parse(data=shapes_text(base), format="turtle")
    _conforms, report, _text = pyshacl.validate(data, shacl_graph=shapes, inference="none", advanced=True)
    rows = []
    for result in report.subjects(rdflib.RDF.type, rdflib.URIRef(SH + "ValidationResult")):
        severity = str(report.value(result, rdflib.URIRef(SH + "resultSeverity"))).rsplit("#", 1)[-1]
        focus = str(report.value(result, rdflib.URIRef(SH + "focusNode")))
        message = str(report.value(result, rdflib.URIRef(SH + "resultMessage")))
        rows.append((severity, focus, message))
    return sorted(set(rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py check-crm", description="Check the CIDOC CRM anchoring of the export.")
    parser.parse_args(argv)

    from wikibase_static.site_config import load_config
    from wikibase_static.step_rdf import resolve_base, target_file

    cfg = load_config(utils.SITE_YAML, load_site().source_url)
    base, _placeholder = resolve_base(cfg)
    target = target_file(base)
    if not target.is_file():
        utils.nothing_to_do(STEP, f"{target.relative_to(utils.ROOT).as_posix()} not found: run `python main.py rdf` first")
        return 0
    site = load_site()
    if not site.crm:
        classes = site.crm_classes()
        if classes:
            utils.warn(STEP, f"no data/crm.csv: {len(classes)} class(es) have no CIDOC CRM class ({', '.join(classes[:8])}{', ...' if len(classes) > 8 else ''})")
    try:
        rows = validate(target.read_text(encoding="utf-8"), base)
    except ImportError:
        utils.warn(STEP, "pySHACL is not installed (pip install pyshacl)")
        return 0
    violations = [r for r in rows if r[0] == "Violation"]
    notes = [r for r in rows if r[0] != "Violation"]
    print(f"[{STEP}] {target.name}: {len(violations)} violation(s), {len(notes)} warning(s)")
    for _severity, focus, message in violations:
        utils.warn(STEP, message.replace(focus, _short(focus, base)))
    for _severity, focus, message in notes:
        print(f"[{STEP}] note: {message.replace(focus, _short(focus, base))}")
    return 0


def _short(iri: str, base: str) -> str:
    return iri.replace(base.rstrip("/") + "/entity/", "wd:").replace("http://www.w3.org/ns/dcat#", "dcat:")


if __name__ == "__main__":
    raise SystemExit(main())
