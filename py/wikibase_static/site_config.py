"""Read and check ``site.yaml`` (schema decided in PRIMER.md, A4; confirmed in S3).

Keys (all optional; a missing file gives the defaults and one note)::

    title: My Wikibase                # page title and header
    description: One line for the start page
    logo: assets/logo.png             # URL, or a file in the repository (copied into docs/assets/)
    colour: "#990000"                 # accent colour, hex only
    source:
      url: https://example.wikibase.cloud   # must match data/raw/manifest.json
    license:                          # optional; without it the pages say CC0 1.0 (Public Domain)
      name: CC BY 4.0
      url: https://creativecommons.org/licenses/by/4.0/
    languages:
      default: en
      second: de                      # optional; gives the language switch
    imprint: https://example.org/imprint    # text or URL
    pages_url: https://example.github.io/repo/   # optional, for the canonical link
    formatter_property: P18           # property that holds the formatter URL of external-id
                                      # properties ($1 is replaced); Wikidata uses P1630
    rdf_base: https://example.org/    # optional; base URI of the RDF export (wd:, wdt:, ...). Default: source.url,
                                      # so that the Turtle file uses the URIs of the real Wikibase
    rdf_prefix: chb                   # optional; short name for the prefix family of the export (chb:, chbt:, chbp:, ...).
                                      # Without it the Wikibase names wd:, wdt:, p:, ... are used, which is right when the base
                                      # URI is the real Wikibase; a site with URIs of its own should not borrow them
    data_as_of: 2026-10-25            # optional; date (or date and time) of the data, for entities that carry no "modified" of
                                      # their own (tables kept as CSV); used in the header and the catalogue of the RDF export
    counterpart:                      # optional; the same entities in a real Wikibase (S7g): a link on every page, owl:sameAs in the RDF
      name: chublets-wikibase.de      # shown on the pages
      uri: https://chublets-wikibase.de/entity/{id}                 # concept URI, {id} is the id there (owl:sameAs)
      url: https://chublets-wikibase.de/wiki/Special:EntityPage/{id}   # page address for the link (default: uri)
      map: data/idmap-chublets-wikibase.de.csv    # table with the columns source_id,target_id (written by the push)

``load_config()`` never raises: unusable values become messages (printed as
``WARN`` by the build step) and fall back to the default.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wikibase_static.counterpart import Counterpart

LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]+)*$")
COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
PROPERTY = re.compile(r"^P[1-9][0-9]*$")
RDF_PREFIX = re.compile(r"^[a-z][a-z0-9]{0,11}$")
# Prefixes the export declares for vocabularies; a site's own family must not take one of them.
RESERVED_PREFIXES = frozenset({"cc", "dcat", "dcterms", "geo", "owl", "prov", "rdf", "rdfs", "schema", "skos", "wikibase", "xsd",
                               "crm", "crmdig", "crmsci", "crmgeo", "crmarchaeo", "crminf", "crmba", "crmtex", "lrmoo", "sh"})
DATA_AS_OF = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?Z?$")
DEFAULT_COLOUR = "#336699"
DEFAULT_LICENSE = ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")   # PRIMER.md, A4
KNOWN_KEYS = {"title", "description", "logo", "colour", "source", "license", "languages",
              "imprint", "pages_url", "formatter_property", "rdf_base", "rdf_prefix", "edit_url", "data_as_of", "counterpart"}


@dataclass
class SiteConfig:
    title: str = ""
    description: str = ""
    logo: str | None = None
    colour: str = DEFAULT_COLOUR
    source_url: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    license_is_default: bool = False
    default_language: str = "en"
    second_language: str | None = None
    imprint: str | None = None
    pages_url: str | None = None
    rdf_base: str | None = None
    rdf_prefix: str | None = None
    data_as_of: str | None = None              # ISO instant (YYYY-MM-DDThh:mm:ssZ) for data that carry no modification time of their own
    counterpart: Counterpart | None = None     # the same entities in a real Wikibase (S7g): links and owl:sameAs
    edit_url: str | None = None                # folder of the CSV tables in the repository editor (S7f), without a trailing slash
    formatter_property: str = "P1630"
    present: bool = False                      # was there a site.yaml at all
    problems: list[str] = field(default_factory=list)

    @property
    def languages(self) -> list[str]:
        return [self.default_language] + ([self.second_language] if self.second_language else [])


def _text(raw: Any, key: str, problems: list[str]) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (str, int, float)) and str(raw).strip():
        return str(raw).strip()
    problems.append(f"site.yaml: {key} must be text; ignored")
    return None


def _mapping(raw: Any, key: str, problems: list[str]) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    problems.append(f"site.yaml: {key} must be a mapping; ignored")
    return {}


def _counterpart(value: Any, problems: list[str]) -> Counterpart | None:
    """``counterpart:`` with ``name``, ``uri``, ``url`` and ``map``; a half-written block is a problem and ignored as a whole."""
    if value is None:
        return None
    block = _mapping(value, "counterpart", problems)
    if not block:
        return None
    name = _text(block.get("name"), "counterpart.name", problems)
    uri = _text(block.get("uri"), "counterpart.uri", problems)
    url = _text(block.get("url"), "counterpart.url", problems) or uri
    map_file = _text(block.get("map"), "counterpart.map", problems)
    for key in sorted(set(block) - {"name", "uri", "url", "map"}):
        problems.append(f"site.yaml: unknown key counterpart.{key}; ignored")
    for key, text in (("uri", uri), ("url", url)):
        if text and not (re.match(r"^https?://[^\s{}]+\{id\}[^\s{}]*$", text)):
            problems.append(f"site.yaml: counterpart.{key} {text!r} is not an http(s) address with {{id}} in it; counterpart ignored")
            return None
    if not (name and uri and map_file):
        problems.append("site.yaml: counterpart needs name, uri and map; ignored")
        return None
    if Path(map_file).is_absolute() or ".." in Path(map_file).parts:
        problems.append(f"site.yaml: counterpart.map {map_file!r} must be a path inside the repository; counterpart ignored")
        return None
    return Counterpart(name=name, uri=uri, url=url or uri, map_file=map_file)


def load_config(path: Path, manifest_source: str | None = None) -> SiteConfig:
    """``site.yaml`` into a ``SiteConfig``; ``manifest_source`` is the source URL of the harvest, if any."""
    cfg = SiteConfig()
    problems = cfg.problems
    data: dict[str, Any] = {}
    if path.is_file():
        cfg.present = True
        try:
            import yaml
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as err:  # YAML errors carry several lines; the first is enough
            problems.append(f"site.yaml: not readable ({str(err).splitlines()[0] if str(err) else type(err).__name__}); defaults used")
            loaded = None
        if isinstance(loaded, dict):
            data = loaded
        elif loaded is not None:
            problems.append("site.yaml: the top level must be a mapping; defaults used")
    for key in sorted(set(data) - KNOWN_KEYS):
        problems.append(f"site.yaml: unknown key {key!r}; ignored")

    cfg.title = _text(data.get("title"), "title", problems) or ""
    cfg.description = _text(data.get("description"), "description", problems) or ""
    cfg.logo = _text(data.get("logo"), "logo", problems)
    cfg.imprint = _text(data.get("imprint"), "imprint", problems)
    cfg.pages_url = _text(data.get("pages_url"), "pages_url", problems)

    colour = _text(data.get("colour"), "colour", problems)
    if colour:
        if COLOUR.match(colour):
            cfg.colour = colour
        else:
            problems.append(f"site.yaml: colour {colour!r} is not a hex colour such as #336699; {DEFAULT_COLOUR} used")

    source = _mapping(data.get("source"), "source", problems)
    cfg.source_url = (_text(source.get("url"), "source.url", problems) or "").rstrip("/") or None
    if cfg.source_url and manifest_source and cfg.source_url != manifest_source.rstrip("/"):
        problems.append(f"site.yaml: source.url {cfg.source_url} differs from the manifest ({manifest_source})")
    if not cfg.source_url and manifest_source:
        cfg.source_url = manifest_source.rstrip("/")

    licence = _mapping(data.get("license"), "license", problems)
    cfg.license_name = _text(licence.get("name"), "license.name", problems)
    cfg.license_url = _text(licence.get("url"), "license.url", problems)
    if not cfg.license_name and not cfg.license_url:
        cfg.license_name, cfg.license_url = DEFAULT_LICENSE
        cfg.license_is_default = True

    langs = _mapping(data.get("languages"), "languages", problems)
    default = _text(langs.get("default"), "languages.default", problems)
    second = _text(langs.get("second"), "languages.second", problems)
    if default:
        if LANGUAGE.match(default):
            cfg.default_language = default
        else:
            problems.append(f"site.yaml: languages.default {default!r} is not a language code; en used")
    if second:
        if not LANGUAGE.match(second):
            problems.append(f"site.yaml: languages.second {second!r} is not a language code; ignored")
        elif second == cfg.default_language:
            problems.append("site.yaml: languages.second equals languages.default; ignored")
        else:
            cfg.second_language = second

    rdf_base = _text(data.get("rdf_base"), "rdf_base", problems)
    if rdf_base:
        if re.match(r"^https?://[^\s/]+(/[^\s?#]*)?$", rdf_base):
            cfg.rdf_base = rdf_base.rstrip("/")
        else:
            problems.append(f"site.yaml: rdf_base {rdf_base!r} is not an http(s) URL without query or fragment; ignored")

    rdf_prefix = _text(data.get("rdf_prefix"), "rdf_prefix", problems)
    if rdf_prefix:
        if RDF_PREFIX.match(rdf_prefix) and rdf_prefix not in RESERVED_PREFIXES:
            cfg.rdf_prefix = rdf_prefix
        else:
            problems.append(f"site.yaml: rdf_prefix {rdf_prefix!r} is not a short lower-case name (letters and digits, at most 12, "
                            "starting with a letter) that is free of the vocabulary prefixes; the Wikibase names (wd, wdt, ...) used")

    stated = data.get("data_as_of")
    if stated is not None:
        if isinstance(stated, datetime.datetime):                    # YAML reads 2026-10-25T08:30:00Z as a point in time
            if stated.tzinfo is not None:
                stated = stated.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            instant = stated.strftime("%Y-%m-%dT%H:%M:%S")
        elif isinstance(stated, datetime.date):
            instant = stated.isoformat()
        else:
            instant = str(stated).strip()
        found = DATA_AS_OF.match(instant)
        if found:
            cfg.data_as_of = f"{found.group(1)}T{found.group(2) or '00:00:00'}Z"
        else:
            problems.append(f"site.yaml: data_as_of {stated!r} is not a date (2026-10-25) or a date and time (2026-10-25T08:30:00Z); ignored")

    cfg.counterpart = _counterpart(data.get("counterpart"), problems)
    edit_url = _text(data.get("edit_url"), "edit_url", problems)
    if edit_url:
        if re.match(r"^https?://[^\s]+$", edit_url):
            cfg.edit_url = edit_url.rstrip("/")
        else:
            problems.append(f"site.yaml: edit_url {edit_url!r} is not an http(s) URL; ignored")

    formatter = _text(data.get("formatter_property"), "formatter_property", problems)
    if formatter:
        if PROPERTY.match(formatter):
            cfg.formatter_property = formatter
        else:
            problems.append(f"site.yaml: formatter_property {formatter!r} is not a property id; {cfg.formatter_property} used")

    if not cfg.title:
        cfg.title = (re.sub(r"^https?://", "", cfg.source_url) if cfg.source_url else "Wikibase archive")
    return cfg
