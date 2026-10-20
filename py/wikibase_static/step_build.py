"""S3 -- render item and property pages in the Wikibase look into docs/.

    python main.py build

Reads data/raw/ and data/derived/ (through ``loader.load_site``) and ``site.yaml``
and writes, flat in docs/ (PRIMER.md, A4 "Seiten-URL-Schema")::

    docs/index.html        start page: title, description, list of items and properties
    docs/Q123.html         one page per item
    docs/P1.html           one page per property
    docs/assets/           style.css, app.js (language switch), map.js, vendor/leaflet, logo

Then it checks its own output: every entity has a page, and every internal link
(``href``/``src`` without a scheme) points to a file that exists. Problems are
``WARN`` lines, never an abort; ``main.py --strict`` turns them into errors.
Pages of entities that are no longer in the data are removed. Nothing here uses
the network or the clock.
"""

from __future__ import annotations

import json
import posixpath
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_build.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, utils
from wikibase_static.loader import load_site
from wikibase_static.model import id_sort_key

STEP = "build"
PACKAGE = Path(__file__).resolve().parent
TEMPLATES = PACKAGE / "templates"
STATIC = PACKAGE / "static"
ENTITY_PAGE = re.compile(r"^[QP][1-9][0-9]*\.html$")


# --------------------------------------------------------------------------- linkcheck


class _Links(HTMLParser):
    """Collects the targets of ``a``/``link`` (href) and ``script``/``img`` (src)."""

    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        wanted = {"a": "href", "link": "href", "script": "src", "img": "src"}.get(tag)
        for name, value in attrs:
            if name == wanted and value:
                self.targets.append(value)


def internal_targets(html: str) -> list[str]:
    """Targets without a scheme and not just a fragment, fragment and query removed, URL-decoded."""
    parser = _Links()
    parser.feed(html)
    found = []
    for target in parser.targets:
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        found.append(unquote(parsed.path))
    return found


def linkcheck(docs: Path) -> tuple[int, list[str]]:
    """(links checked, dead links as ``page -> target``) over every HTML file directly in ``docs``."""
    checked = 0
    dead: list[str] = []
    for page in sorted(docs.glob("*.html")):
        for target in internal_targets(page.read_text(encoding="utf-8")):
            checked += 1
            resolved = posixpath.normpath(target)
            if resolved.startswith(".."):
                dead.append(f"{page.name} -> {target} (outside docs/)")
            elif not (docs / resolved).is_file():
                dead.append(f"{page.name} -> {target}")
    return checked, sorted(set(dead))


# --------------------------------------------------------------------------- assets


def copy_assets(docs: Path) -> int:
    """Copy the package's ``static/`` into docs/assets/, byte for byte; returns the number of files."""
    count = 0
    for source in sorted(p for p in STATIC.rglob("*") if p.is_file()):
        target = docs / "assets" / source.relative_to(STATIC)
        data = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
        count += 1
    return count


def place_logo(logo: str | None, docs: Path, problems: list[str]) -> str | None:
    """The href for the header logo: a URL as given, or a repository file copied into docs/assets/logo/."""
    if not logo:
        return None
    if logo.lower().startswith(("http://", "https://")):
        return logo
    source = (utils.ROOT / logo).resolve()
    if not source.is_relative_to(utils.ROOT) or not source.is_file():
        problems.append(f"site.yaml: logo {logo!r} is not a file inside the repository; no logo shown")
        return None
    target = docs / "assets" / "logo" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    if not target.is_file() or target.read_bytes() != data:
        target.write_bytes(data)
    return f"assets/logo/{source.name}"


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    site = load_site()
    if not site.entities:
        utils.nothing_to_do(STEP, "no entities in data/raw/entities or data/derived/entities")
        return 0

    # Heavy imports only now, so that --list, --dry-run and an empty repository never need them.
    import jinja2
    from wikibase_static.render import Renderer
    from wikibase_static.site_config import load_config

    cfg = load_config(utils.SITE_YAML, site.source_url)
    problems = list(cfg.problems)
    if not cfg.present:
        print(f"[{STEP}] no site.yaml: defaults used (title {cfg.title!r})")
    docs = utils.DOCS
    docs.mkdir(parents=True, exist_ok=True)
    assets = copy_assets(docs)
    logo = place_logo(cfg.logo, docs, problems)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True, undefined=jinja2.StrictUndefined,
        trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
    )
    r = Renderer(site, cfg, __version__)
    base_url = (cfg.pages_url.rstrip("/") + "/") if cfg.pages_url else None

    def common(page: str, title: str, description: str | None, footer: dict[str, Any],
               map_points: list[Any] | None = None) -> dict[str, Any]:
        return {
            "default": cfg.default_language, "second": cfg.second_language, "colour": cfg.colour, "logo": logo,
            "site_title": cfg.title, "language_label": r.ui_text("language"),
            "canonical": f"{base_url}{page}" if base_url else None,
            "title": title, "description": description, "footer": footer, "map_points": map_points or [],
            "ui_source": r.ui("source"), "ui_original": r.ui("open_original"), "ui_as_of": r.ui("as_of"),
            "ui_license": r.ui("license"), "ui_license_missing": r.ui("license_missing"),
            "ui_imprint": r.ui("imprint"), "ui_generated": r.ui("generated"),
            "ui_home": r.ui("home"), "ui_home_text": r.ui_text("home"), "ui_items": r.ui("items"), "ui_properties": r.ui("properties"),
            "has_items": bool(site.items), "has_properties": bool(site.properties),
        }

    expected: set[str] = set()
    pages_with_map = markers = 0
    for entity in site.entities.values():
        name = f"{entity.id}.html"
        expected.add(name)
        points = r.map_points(entity)
        pages_with_map += bool(points)
        markers += len(points)
        label = r.label_text(entity.id)
        title = f"{label} ({entity.id})" if entity.labels else entity.id
        datatype_label = None
        if entity.datatype:
            datatype_label = r.ui(f"dt_{entity.datatype}") if f"dt_{entity.datatype}" in _known_datatypes() else entity.datatype
        context = common(name, f"{title} – {cfg.title}", r.description_text(entity), r.footer(entity), points)
        context.update({
            "heading": r.heading(entity.id), "description": r.description(entity), "aliases": r.aliases(entity),
            "ui_kind": r.ui("item" if entity.kind == "item" else "property"),
            "datatype": entity.datatype, "datatype_label": datatype_label,
            "points_json": json.dumps([{"lat": p.lat, "lon": p.lon, "text": p.text} for p in points],
                                      ensure_ascii=False, separators=(",", ":")),
            "ui_map_text": r.ui_text("map"), "groups": r.statement_groups(entity),
            "incoming": r.referenced_by(entity.id),
            "ui_no_description": r.ui("no_description"), "ui_also_known_as": r.ui("also_known_as"),
            "ui_datatype": r.ui("datatype"), "ui_map": r.ui("map"), "ui_statements": r.ui("statements"),
            "ui_no_statements": r.ui("no_statements"), "ui_rank_preferred": r.ui("rank_preferred"),
            "ui_rank_deprecated": r.ui("rank_deprecated"),
            "ui_referenced_by": r.ui("referenced_by", n=len(r.incoming.get(entity.id, []))),
        })
        utils.write_text(docs / name, env.get_template("entity.html").render(context))

    sections = []
    for title_key, entities in (("items", site.items), ("properties", site.properties)):
        rows = [{"id": e.id, "link": r.entity_link(e.id, show_id=False), "description": r.description(e)}
                for e in sorted(entities, key=lambda e: id_sort_key(e.id))]
        if rows:
            sections.append({"id": title_key, "title": r.ui(title_key), "rows": rows})
    index = common("index.html", cfg.title, cfg.description or None, r.footer(None))
    index.update({
        "site_description": cfg.description, "sections": sections,
        "ui_counts": r.ui("entities_n", n=len(site.entities), items=len(site.items), properties=len(site.properties)),
        "ui_id": r.ui("id"), "ui_label": r.ui("label"), "ui_description": r.ui("description"),
    })
    expected.add("index.html")
    utils.write_text(docs / "index.html", env.get_template("index.html").render(index))

    stale = sorted(p.name for p in docs.glob("*.html") if ENTITY_PAGE.match(p.name) and p.name not in expected)
    for name in stale:
        (docs / name).unlink()

    entity_pages = sorted(p.name for p in docs.glob("*.html") if ENTITY_PAGE.match(p.name))
    missing = sorted(f"{e}.html" for e in site.entities if f"{e}.html" not in entity_pages)
    checked, dead = linkcheck(docs)

    print(f"[{STEP}] {len(site.entities)} entities -> {len(entity_pages)} entity pages + index.html in docs/ "
          f"(difference {len(site.entities) - len(entity_pages)}), {assets} asset files")
    print(f"[{STEP}] languages: {', '.join(cfg.languages)}; source: {cfg.source_url or 'not stated'}; "
          f"licence: {cfg.license_name or 'not stated'}{' (default)' if cfg.license_is_default else ''}")
    print(f"[{STEP}] maps: {markers} distinct coordinate(s) on {pages_with_map} page(s)"
          + (f"; {r.unmapped_coordinates} not on Earth or out of range, shown as text" if r.unmapped_coordinates else ""))
    if stale:
        print(f"[{STEP}] removed {len(stale)} stale page(s): {', '.join(stale)}")
    print(f"[{STEP}] linkcheck: {checked} internal links checked, {len(dead)} dead")
    for message in sorted(set(problems)):
        utils.warn(STEP, message)
    for name in missing:
        utils.warn(STEP, f"no page written for {name[:-5]}")
    for link in dead:
        utils.warn(STEP, f"dead internal link {link}")
    return 0


def _known_datatypes() -> set[str]:
    from wikibase_static.render import STRINGS
    return {key for key in STRINGS["en"] if key.startswith("dt_")}


if __name__ == "__main__":
    raise SystemExit(main())
