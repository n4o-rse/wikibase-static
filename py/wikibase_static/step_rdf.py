"""S6 -- export the archived entities as RDF in the Wikibase data model.

    python main.py rdf

Reads the loaded entities and ``site.yaml`` and writes::

    dist/<host>.ttl                        everything (for https://fuzzy-sl.wikibase.cloud: fuzzy-sl.wikibase.cloud.ttl)
    docs/downloads/<host>.ttl              the same file, byte for byte, as published
    docs/downloads/wikibase-ontology.ttl   the Wikibase system ontology (CC0), copied from the package
    docs/ttl/Q1.ttl                        the triples of each entity on its own, with its DCAT description
    docs/json/Q1.json                      each entity as archived, byte for byte
    docs/entity/Q1.html                    only when the concept URIs lie under ``pages_url`` (see ``concept_stubs``)

The URIs are those of the real Wikibase (``site.yaml``: ``rdf_base``, else ``source.url``), so a query written for
its Query Service runs against the file. The mapping, including the DCAT 3 description (catalogues, one dataset
per entity, distributions), lives in ``rdf.py``.

The file is a function of the data and the package version, nothing else. It is built as sorted N-Triples first
and written from there; the step then parses the Turtle back with rdflib and compares it with the N-Triples (a
bug in the writer would show as a difference). Problems are ``WARN`` lines, never an abort; ``main.py --strict``
turns them into errors.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_rdf.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, rdf, utils
from wikibase_static.loader import load_site

STEP = "rdf"
SHOWN = 5
ONTOLOGY = Path(__file__).resolve().parent / "data" / "wikibase-ontology.ttl"
ONTOLOGY_NAME = "wikibase-ontology.ttl"


def resolve_base(cfg) -> tuple[str, bool]:
    """(base URI, whether it is a placeholder because the site states neither rdf_base nor source.url)."""
    base = cfg.rdf_base or cfg.source_url
    if base:
        return base.rstrip("/"), False
    return rdf.PLACEHOLDER_BASE, True


def target_file(base: str) -> Path:
    return utils.DIST / f"{rdf.file_stem(base)}.ttl"


def raw_file(entity) -> Path | None:
    """The archived JSON file of an entity, if it is a file of its own (``Q1.json`` holding Q1)."""
    file = utils.ROOT / entity.path
    return file if entity.path and file.is_file() and file.stem == entity.id else None


def _sync(directory: Path, wanted: dict[str, bytes]) -> None:
    """Make ``directory`` hold exactly the files in ``wanted`` (name -> bytes); unchanged files are not touched."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(wanted.items()):
        target = directory / name
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name not in wanted:
            path.unlink()


STUB = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{id}</title>
<meta http-equiv="refresh" content="0; url=../{id}.html">
<link rel="canonical" href="../{id}.html">
<link rel="alternate" type="text/turtle" href="../ttl/{id}.ttl">
<link rel="alternate" type="application/json" href="../json/{id}.json">
</head>
<body>
<p>The concept <code>{id}</code> is described on <a href="../{id}.html">{id}.html</a>
(<a href="../ttl/{id}.ttl">RDF, Turtle</a>).</p>
</body>
</html>
"""


def concept_stubs(site, base: str, pages_url: str | None) -> dict[str, bytes]:
    """``entity/<ID>.html`` for each entity, when the concept URIs (``<base>/entity/<ID>``) lie under the published site.

    A static host cannot answer ``/entity/Q1`` with a redirect or with Turtle; GitHub Pages does serve ``entity/Q1.html``
    for ``/entity/Q1``, so a small page that forwards to the real one makes the URI open instead of ending in a 404. It is
    no content negotiation (a machine asking for Turtle gets the HTML stub, which names the Turtle file). For a site whose
    base URI is that of the live Wikibase nothing is written."""
    if not pages_url or pages_url.rstrip("/") != base.rstrip("/"):
        return {}
    return {f"{entity_id}.html": utils_bytes(STUB.format(id=entity_id)) for entity_id in sorted(site.entities)}


def write_published(site, ns, result, text: str, stem: str, header: list[str], pages_url: str | None = None) -> int:
    """The files that go into docs/; returns how many."""
    downloads = {f"{stem}.ttl": utils_bytes(text), ONTOLOGY_NAME: ONTOLOGY.read_bytes()}
    ttl, raw = {}, {}
    for entity_id, triples in sorted(result.by_entity.items()):
        own = [f"{entity_id}: the part of the RDF export of {header[0].split(' of ', 1)[-1].split(',')[0]} that describes this entity",
               header[1], header[2]]
        part = triples & result.bridge
        ttl[f"{entity_id}.ttl"] = utils_bytes(rdf.to_turtle(triples, ns, "\n".join(own),
                                                            (rdf.BRIDGE_TITLE, part) if part else None))
        entity = site.entities[entity_id]
        file = raw_file(entity)
        if file is not None:
            raw[f"{entity_id}.json"] = file.read_bytes()
    _sync(utils.DOCS / "downloads", downloads)
    _sync(utils.DOCS / "ttl", ttl)
    _sync(utils.DOCS / "json", raw)
    stubs = concept_stubs(site, ns.base, pages_url)
    if stubs or (utils.DOCS / "entity").is_dir():
        _sync(utils.DOCS / "entity", stubs)
        if not stubs:
            (utils.DOCS / "entity").rmdir()
    return len(downloads) + len(ttl) + len(raw) + len(stubs)


def utils_bytes(text: str) -> bytes:
    """The bytes ``utils.write_text`` would write: LF line endings and one trailing newline."""
    return (text.replace("\r\n", "\n").rstrip("\n") + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py rdf", description="Export the entities as Turtle.")
    parser.parse_args(argv)

    site = load_site()
    if not site.entities:
        utils.nothing_to_do(STEP, "no entities in data/raw/entities or data/derived/entities")
        return 0

    from wikibase_static.site_config import load_config

    cfg = load_config(utils.SITE_YAML, site.source_url)
    base, placeholder = resolve_base(cfg)
    ns = rdf.Namespaces(base)
    stem = rdf.file_stem(base)
    json_sizes = {e.id: file.stat().st_size for e in site.entities.values() if (file := raw_file(e)) is not None}
    catalog = rdf.CatalogInfo(
        title=cfg.title, description=cfg.description, license_url=cfg.license_url, source_url=cfg.source_url,
        pages_url=cfg.pages_url, modified=site.latest_modified, json_sizes=json_sizes,
        export_file=f"downloads/{stem}.ttl", ontology_file=f"downloads/{ONTOLOGY_NAME}",
        ontology_bytes=ONTOLOGY.stat().st_size)
    result = rdf.build(site, ns, cfg.license_url, catalog)

    header = [f"RDF export of {cfg.source_url or cfg.title}, Wikibase data model; base URI {ns.base}",
              f"Generated with wikibase-static {__version__}; data as of {site.latest_modified or 'unknown'}",
              f"Licence: {cfg.license_name or 'not stated'}"]
    text = rdf.to_turtle(result.triples, ns, "\n".join(header), (rdf.BRIDGE_TITLE, result.bridge) if result.bridge else None)
    target = target_file(base)
    utils.write_text(target, text)
    published = write_published(site, ns, result, text, stem, header, cfg.pages_url)

    print(f"[{STEP}] {result.entities} entities, {result.statements} statements -> {len(result.triples)} triples")
    print(f"[{STEP}] {published} file(s) in docs/ (downloads, ttl/, json/, entity/); {result.distributions} distributions described")
    for note in result.notes:
        print(f"[{STEP}] note: {note}")
    print(f"[{STEP}] {target.relative_to(utils.ROOT).as_posix()}: {len(target.read_bytes())} bytes, base URI {ns.base}"
          + (" (placeholder: no source.url or rdf_base in site.yaml)" if placeholder else ""))

    problems = list(result.problems)
    try:
        import rdflib
    except ImportError:
        problems.append("rdflib is not installed; the Turtle file was not checked (pip install rdflib)")
    else:
        parsed = rdflib.Graph()
        parsed.parse(data=text, format="turtle")
        expected = rdflib.Graph()
        expected.parse(data=rdf.ntriples(result.triples), format="nt")
        if len(parsed) != len(result.triples) or not parsed.isomorphic(expected):
            problems.append(f"the Turtle file does not read back as the {len(result.triples)} triples it was written from "
                            f"({len(parsed)} found)")
        else:
            print(f"[{STEP}] read back with rdflib {rdflib.__version__}: {len(parsed)} triples, identical")
    for message in problems:
        utils.warn(STEP, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
