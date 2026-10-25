"""S3 -- render item and property pages in the Wikibase look into docs/.

    python main.py build

Reads data/raw/ and data/derived/ (through ``loader.load_site``) and ``site.yaml``
and writes, flat in docs/ (PRIMER.md, A4 "Seiten-URL-Schema")::

    docs/index.html        start page: title, description, counts, links to the three lists below
    docs/items.html        all items;  docs/properties.html  all properties
    docs/overview.html     the items grouped by class (instance of), one section and one map per class
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
from wikibase_static.source_rows import SourceRows

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


def linkcheck(docs: Path, pending: tuple[str, ...] = (), pending_dirs: tuple[str, ...] = ()) -> tuple[int, list[str]]:
    """(links checked, dead links as ``page -> target``) over every HTML file directly in ``docs``.

    ``pending`` names files a later step writes (``sparql.html``), ``pending_dirs`` folders it fills (``ttl/``): a link
    to one of them is not dead yet."""
    checked = 0
    dead: list[str] = []
    for page in sorted(docs.glob("*.html")):
        for target in internal_targets(page.read_text(encoding="utf-8")):
            checked += 1
            resolved = posixpath.normpath(target)
            if resolved.startswith(".."):
                dead.append(f"{page.name} -> {target} (outside docs/)")
            elif resolved in pending or resolved.startswith(pending_dirs):
                continue
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


def make_env():
    """The Jinja environment of all pages (also used by the SPARQL step)."""
    import jinja2
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True, undefined=jinja2.StrictUndefined,
        trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
    )


def logo_href(logo: str | None) -> str | None:
    """The href for the header logo without copying anything (the build step has placed the file already)."""
    if not logo:
        return None
    if logo.lower().startswith(("http://", "https://")):
        return logo
    source = (utils.ROOT / logo).resolve()
    return f"assets/logo/{source.name}" if source.is_relative_to(utils.ROOT) and source.is_file() else None


def page_context(site: Any, cfg: Any, r: Any, logo: str | None):
    """The function that makes the context every page shares (title, strings, navigation, footer)."""
    base_url = (cfg.pages_url.rstrip("/") + "/") if cfg.pages_url else None
    has_overview = bool(r.class_groups())

    def common(page: str, title: str, description: str | None, footer: dict[str, Any],
               map_points: list[Any] | None = None) -> dict[str, Any]:
        return {
            "default": cfg.default_language, "second": cfg.second_language, "colour": cfg.colour, "logo": logo,
            "site_title": cfg.title, "language_label": r.ui_text("language"),
            "canonical": f"{base_url}{page}" if base_url else None,
            "title": title, "description": description, "meta_description": description, "footer": footer, "map_points": map_points or [], "leaflet": False,
            "ui_source": r.ui("source"), "ui_original": r.ui("open_original"), "ui_as_of": r.ui("as_of"),
            "ui_license": r.ui("license"), "ui_license_missing": r.ui("license_missing"),
            "ui_imprint": r.ui("imprint"), "ui_generated": r.ui("generated"),
            "ui_home": r.ui("home"), "ui_home_text": r.ui_text("home"), "ui_items": r.ui("items"), "ui_properties": r.ui("properties"),
            "ui_sparql": r.ui("sparql"), "ui_query": r.ui("query"), "has_sparql": True, "page_name": page,
            "search_text": r.ui_text("search"), "search_texts": r.search_texts_json(),
            "has_items": bool(site.items), "has_properties": bool(site.properties), "has_overview": has_overview,
            "ui_overview": r.ui("overview"),
        }
    return common


def source_context(r: Any, cfg: Any, source_rows: SourceRows | None, entity_id: str) -> dict[str, Any]:
    """Template values of the tab "Source rows" (S7f): ``source_rows`` is ``None`` when the site is not made from CSV or the entity has no row."""
    blocks = source_rows.blocks(entity_id) if source_rows else []
    if not blocks:
        return {"source_rows": None}
    return {
        "source_rows": [{"file": b.file, "count": r.ui("rows_n", n=b.rows), "text": b.text,
                         "edit_href": f"{cfg.edit_url}/{b.name}" if cfg.edit_url and b.editable else None} for b in blocks],
        "ui_tab_source": r.ui("tab_source"), "ui_source_rows": r.ui("source_rows"), "ui_source_rows_intro": r.ui("source_rows_intro"),
        "ui_copy_rows": r.ui("copy_rows"), "ui_edit_file": r.ui("edit_file"),
    }


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
    from wikibase_static import counterpart, rdf
    from markupsafe import Markup
    from wikibase_static.modelgraph import ModelGraphs
    from wikibase_static.render import Renderer
    from wikibase_static.site_config import load_config
    from wikibase_static.step_rdf import raw_file, resolve_base

    cfg = load_config(utils.SITE_YAML, site.source_url)
    twin = counterpart.load(cfg.counterpart, utils.ROOT, set(site.entities))        # the same entities in a real Wikibase, or None
    problems = list(cfg.problems) + (twin.problems if twin else [])
    if not cfg.present:
        print(f"[{STEP}] no site.yaml: defaults used (title {cfg.title!r})")
    docs = utils.DOCS
    docs.mkdir(parents=True, exist_ok=True)
    assets = copy_assets(docs)
    logo = place_logo(cfg.logo, docs, problems)

    env = make_env()
    r = Renderer(site, cfg, __version__)
    graphs = ModelGraphs(r)
    source_rows = SourceRows.load(utils.ROOT / "data" / "csv")          # None for a site that was harvested and not made from CSV
    common = page_context(site, cfg, r, logo)
    base, placeholder = resolve_base(cfg)
    own = cfg.pages_url.rstrip("/") if cfg.pages_url else None
    concepts = rdf.Namespaces(base, cfg.rdf_prefix).wd if own and not placeholder and base == own else None   # URIs that resolve here (entity/<ID>.html)

    def copy_target(entity_id: str) -> tuple[str | None, str]:
        """(what the button copies, its text key): the concept URI where it opens a page of this site, else the page's own
        address; never an address on another host (the Wikibase the data came from)."""
        if concepts:
            return f"{concepts}{entity_id}", "copy_uri"
        if own:
            return f"{own}/{entity_id}.html", "copy_page_uri"
        return None, "copy_uri"

    expected: set[str] = set()
    pages_with_map = markers = 0
    points_of: dict[str, list[Any]] = {}
    for entity in site.entities.values():
        name = f"{entity.id}.html"
        expected.add(name)
        points = points_of[entity.id] = r.map_points(entity)
        pages_with_map += bool(points)
        markers += len(points)
        label = r.label_text(entity.id)
        title = f"{label} ({entity.id})" if entity.labels else entity.id
        datatype_label = None
        if entity.datatype:
            datatype_label = r.ui(f"dt_{entity.datatype}") if f"dt_{entity.datatype}" in _known_datatypes() else entity.datatype
        context = common(name, f"{title} – {cfg.title}", r.description_text(entity), r.footer(entity), points)
        context.update({
            "heading": r.heading(entity.id), "description": r.description(entity),
            "language_rows": r.language_rows(entity), "crm_rows": r.crm_rows(entity),
            "ui_crm": r.ui("crm"), "ui_crm_from": r.ui("crm_from"), "ui_crm_none": r.ui("crm_none"),
            "ui_kind": r.ui("item" if entity.kind == "item" else "property"),
            "datatype": entity.datatype, "datatype_label": datatype_label,
            "points_json": json.dumps([{"lat": p.lat, "lon": p.lon, "text": p.text} for p in points],
                                      ensure_ascii=False, separators=(",", ":")),
            "ui_map_text": r.ui_text("map"), "groups": r.statement_groups(entity),
            "incoming": r.referenced_by(entity.id), "class_tree_nodes": r.class_tree(entity.id), "ui_hierarchy": r.ui("hierarchy"),
            "ui_no_description": r.ui("no_description"), "ui_also_known_as": r.ui("also_known_as"),
            "ui_language": r.ui("language"), "ui_label": r.ui("label"), "ui_description": r.ui("description"),
            "ui_in_other_languages": r.ui("in_other_languages"), "ui_tools": r.ui("tools"),
            "ui_referenced_by_short": r.ui("referenced_by_short"), "ui_tab_read": r.ui("tab_read"),
            "concept_uri": copy_target(entity.id)[0], "entity_id": entity.id,
            "ttl_href": f"ttl/{entity.id}.ttl", "json_href": f"json/{entity.id}.json" if raw_file(entity) else None,
            "ui_page_downloads": r.ui("page_downloads"), "ui_download_ttl": r.ui("download_ttl"),
            "ui_download_json": r.ui("download_json"), "ui_copy_uri": r.ui(copy_target(entity.id)[1]), "ui_copied": r.ui("copied"),
            "ui_datatype": r.ui("datatype"), "ui_map": r.ui("map"), "ui_statements": r.ui("statements"),
            "ui_no_statements": r.ui("no_statements"), "ui_rank_preferred": r.ui("rank_preferred"),
            "ui_rank_deprecated": r.ui("rank_deprecated"),
            "ui_referenced_by": r.ui("referenced_by", n=len(r.incoming.get(entity.id, []))),
            "graph_svg": Markup(svg) if (svg := graphs.entity_svg(entity)) else None, "ui_graph": r.ui("graph_title"), "ui_graph_svg": r.ui("graph_svg"), "ui_graph_png": r.ui("graph_png"),
        })
        context.update(source_context(r, cfg, source_rows, entity.id))
        context["counterpart"] = ({"label": r.ui("counterpart", name=twin.name), "id": twin.target_id(entity.id),
                                   "href": twin.target_url(entity.id)} if twin and twin.target_id(entity.id) else None)
        utils.write_text(docs / name, env.get_template("entity.html").render(context))

    for source, target in sorted(site.redirects.items(), key=lambda kv: id_sort_key(kv[0])):    # merged ids (S7e): a page that forwards
        name = f"{source}.html"
        expected.add(name)
        context = common(name, f"{source} – {cfg.title}", None, r.footer(None))
        context.update({"source": source, "target": target, "target_label": r.label_text(target),
                        "ui_merged_into": r.ui("merged_into")})
        utils.write_text(docs / name, env.get_template("redirect.html").render(context))

    def rows_of(entities: list[Any]) -> list[dict[str, Any]]:
        return [{"id": e.id, "link": r.entity_link(e.id, show_id=False), "description": r.description(e)}
                for e in sorted(entities, key=lambda e: id_sort_key(e.id))]

    groups = r.class_groups()
    page_links = []
    list_pages = []
    for name, key, entities in (("items.html", "items", site.items), ("properties.html", "properties", site.properties)):
        if entities:
            list_pages.append((name, key, entities))
    for name, key, entities in list_pages:
        page_links.append({"href": name, "title": r.ui(key), "note": f"({len(entities)})"})
        if key == "items" and groups:
            page_links.append({"href": "overview.html", "title": r.ui("overview"), "note": f"({len(groups)})"})
    if not any(link["href"] == "items.html" for link in page_links) and groups:
        page_links.append({"href": "overview.html", "title": r.ui("overview"), "note": f"({len(groups)})"})
    for name, key, entities in list_pages:
        listing = common(name, f"{r.ui_text(key)} – {cfg.title}", None, r.footer(None))
        listing.update({"list_title": r.ui(key), "list_intro": r.ui(f"{key}_intro"), "rows": rows_of(entities),
                        "ui_id": r.ui("id"), "ui_label": r.ui("label"), "ui_description": r.ui("description")})
        utils.write_text(docs / name, env.get_template("list.html").render(listing))
    if groups:
        overview = common("overview.html", f"{r.ui_text('overview')} – {cfg.title}", None, r.footer(None))
        view_groups = []
        for group in groups:
            class_entity = site.entities[group["id"]]
            points = []
            for entity in group["instances"]:
                for p in points_of.get(entity.id, []):
                    points.append({"lat": p.lat, "lon": p.lon, "text": r.label_text(entity.id), "href": f"{entity.id}.html"})
            count = r.ui("instances_one") if len(group["instances"]) == 1 else r.ui("instances_n", n=len(group["instances"]))
            view_groups.append({
                "id": group["id"], "title": r.label(group["id"]), "link": r.entity_link(group["id"], show_id=False),
                "count": count, "description": r.description(class_entity), "rows": rows_of(group["instances"]),
                "tree": r.class_tree(group["id"]),
                "points_json": json.dumps(points, ensure_ascii=False, separators=(",", ":")) if points else None,
                "map_text": r.ui_text("overview_map", **{"class": r.label_text(group["id"])}),
            })
        overview["leaflet"] = any(g["points_json"] for g in view_groups)
        overview.update({"groups": view_groups, "ui_hierarchy": r.ui("hierarchy"), "overview_intro": r.ui("overview_intro"),
                         "ui_id": r.ui("id"), "ui_label": r.ui("label"), "ui_description": r.ui("description")})
        utils.write_text(docs / "overview.html", env.get_template("overview.html").render(overview))
    model_inline = graphs.site_svg()
    model_file = docs / "graphs" / "model.svg"
    if model_inline:
        utils.write_text(model_file, graphs.site_svg("../", standalone=True) or "")
    elif model_file.is_file():
        model_file.unlink()
        model_file.parent.rmdir()
    table_href = (f"downloads/{Path(twin.map_file).name}"       # the rdf step publishes the table, after this step
                  if twin and twin.ids and (utils.ROOT / twin.map_file).is_file() else None)
    index = common("index.html", cfg.title, cfg.description or None, r.footer(None))
    index.update({
        "model_svg": Markup(model_inline) if model_inline else None, "ui_model": r.ui("model_title"),
        "ui_model_intro": r.ui("model_intro"), "ui_model_download": r.ui("model_download"), "ui_graph_png": r.ui("graph_png"),
        "site_description": cfg.description, "page_links": page_links,
        "counterpart_table": ({"href": table_href, "text": r.ui("counterpart_table", name=twin.name)} if table_href else None),
        "ui_counts": r.ui("entities_n", n=len(site.entities), items=len(site.items), properties=len(site.properties)),
    })
    expected.add("index.html")
    utils.write_text(docs / "index.html", env.get_template("index.html").render(index))

    stale = sorted(p.name for p in docs.glob("*.html") if ENTITY_PAGE.match(p.name) and p.name not in expected)
    for name in stale:
        (docs / name).unlink()

    entity_pages = sorted(p.name for p in docs.glob("*.html") if ENTITY_PAGE.match(p.name))
    missing = sorted(f"{e}.html" for e in [*site.entities, *site.redirects] if f"{e}.html" not in entity_pages)
    checked, dead = linkcheck(docs, pending=("sparql.html", "query.html", *([table_href] if table_href else [])),
                              pending_dirs=("ttl/", "json/"))

    pages = len(entity_pages) - len(site.redirects)
    print(f"[{STEP}] {len(site.entities)} entities -> {pages} entity pages + index.html in docs/ "
          f"(difference {len(site.entities) - pages}), {assets} asset files")
    if site.redirects:
        print(f"[{STEP}] {len(site.redirects)} merged id(s) forward to the entity they were merged into")
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
