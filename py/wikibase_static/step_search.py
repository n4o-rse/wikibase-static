"""S5 -- build the search index for the autocomplete box.

    python main.py search

Reads the loaded entities and ``site.yaml`` and writes ``docs/assets/search-index.js``. The pages
(``build``) carry the search box and ``assets/search.js``; the script loads the index the first time
somebody uses the box, so a page that is only read never fetches it. The index is a script file that
assigns ``window.WBS_SEARCH_INDEX``, not a bare JSON file, because a script loads from ``file://`` as
well: the folder ``docs/`` can be opened from a disk or a USB stick and the search still works, which
``fetch()`` of a JSON file would not allow.

The index is a function of the loaded data and the two languages of ``site.yaml`` and nothing else (no
clock, no network, no hash-order dependence), so it changes exactly when the data change. Layout::

    {"entities": [{"id": "Q97",
                   "l": {"de": "...", "en": "..."},     label shown, per language of the site (with fallback)
                   "d": {"de": "...", "en": "..."},     description shown, same rule
                   "x": ["..."],                         labels in other languages, searchable only
                   "a": ["..."]}],                       aliases of every language, searchable only
     "languages": ["en", "de"],                          default language first
     "version": 1}

``l`` and ``d`` use the rule of the pages (``model.pick_text``). An entity without any label has no ``l``;
the script then shows its id. Entries are in id order (items first, numerically), which the script uses as
the last tie-break.

Problems are ``WARN`` lines, never an abort; ``main.py --strict`` turns them into errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_search.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils
from wikibase_static.loader import Site, load_site
from wikibase_static.model import Entity, id_sort_key, pick_text

STEP = "search"
INDEX_FORMAT_VERSION = 1
INDEX_FILE = "search-index.js"     # in docs/assets/; the page's data-index attribute says the same (base.html)
GLOBAL_NAME = "WBS_SEARCH_INDEX"
SHOWN_MISSING = 5                  # how many entities without a page a WARN line names


def language_order(entity: Entity, languages: list[str]) -> list[str]:
    """The site's languages first, then every other language the entity has text in, sorted by code."""
    present = set(entity.labels) | set(entity.aliases)
    return list(languages) + sorted(present - set(languages))


def entry_for(entity: Entity, default: str, second: str | None) -> dict[str, Any]:
    """The index entry of one entity (see the module docstring)."""
    languages = [default] + ([second] if second else [])
    entry: dict[str, Any] = {"id": entity.id}
    shown: dict[str, str] = {}
    described: dict[str, str] = {}
    for language in languages:
        chain = [default] if language == default else [language, default]
        label = pick_text(entity.labels, chain)
        if label:
            shown[language] = label
        description = pick_text(entity.descriptions, chain)
        if description:
            described[language] = description
    if shown:
        entry["l"] = shown
    if described:
        entry["d"] = described

    seen = set(shown.values())
    others: list[str] = []
    aliases: list[str] = []
    order = language_order(entity, languages)
    for language in order:
        text = entity.labels.get(language)
        if text and text not in seen:
            seen.add(text)
            others.append(text)
    for language in order:
        for text in entity.aliases.get(language, []):
            if text and text not in seen:
                seen.add(text)
                aliases.append(text)
    if others:
        entry["x"] = others
    if aliases:
        entry["a"] = aliases
    return entry


def build_index(site: Site, default: str, second: str | None) -> dict[str, Any]:
    """The whole index as a plain dict (pure: the same site and languages give the same dict)."""
    entities = sorted(site.entities.values(), key=lambda e: id_sort_key(e.id))
    return {
        "entities": [entry_for(e, default, second) for e in entities],
        "languages": [default] + ([second] if second else []),
        "version": INDEX_FORMAT_VERSION,
    }


def render_index(index: dict[str, Any]) -> str:
    """The text of ``search-index.js``: canonical JSON (sorted keys, compact, UTF-8) in one assignment.

    U+2028 and U+2029 are legal in JSON but ended a line in a JavaScript string before ES2019, so they are
    escaped; the result is a valid script for every browser."""
    text = json.dumps(index, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return f"window.{GLOBAL_NAME}={text};"


def term_count(index: dict[str, Any]) -> int:
    """How many strings the script can match against (shown labels, other labels, aliases)."""
    total = 0
    for entry in index["entities"]:
        total += len(entry.get("l", {})) + len(entry.get("x", [])) + len(entry.get("a", []))
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py search", description="Build the search index.")
    parser.parse_args(argv)

    site = load_site()
    if not site.entities:
        utils.nothing_to_do(STEP, "no entities in data/raw/entities or data/derived/entities")
        return 0

    # Only now: PyYAML is needed for site.yaml, and an empty repository must not need it.
    from wikibase_static.site_config import load_config

    cfg = load_config(utils.SITE_YAML, site.source_url)
    index = build_index(site, cfg.default_language, cfg.second_language)
    text = render_index(index)
    target = utils.DOCS / "assets" / INDEX_FILE
    utils.write_text(target, text)

    size = len(target.read_bytes())
    unlabelled = [e["id"] for e in index["entities"] if "l" not in e]
    print(f"[{STEP}] {len(index['entities'])} entities indexed ({len(site.items)} items, {len(site.properties)} properties), "
          f"{term_count(index)} searchable strings, languages: {', '.join(index['languages'])}")
    print(f"[{STEP}] docs/assets/{INDEX_FILE}: {size} bytes")
    if unlabelled:
        print(f"[{STEP}] {len(unlabelled)} entities have no label and are found by their id only")

    missing = [e["id"] for e in index["entities"] if not (utils.DOCS / f"{e['id']}.html").is_file()]
    if missing:
        named = ", ".join(missing[:SHOWN_MISSING]) + (", ..." if len(missing) > SHOWN_MISSING else "")
        utils.warn(STEP, f"{len(missing)} indexed entities have no page in docs/ ({named}); run the build step first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
