"""Turn the model into page contexts and HTML fragments (S3).

Everything here is a pure function of the loaded site and ``site.yaml``: no
clock, no network, no file access, so a page changes exactly when data or model
change (PRIMER.md, A3).

What a page shows is what the source says. Values are formatted but never
repaired: a URL with a typo is shown with the typo (PRIMER.md, A1, Befund 7).

Text that exists in two languages is written as two ``<span lang=..>`` elements;
the language switch only changes ``data-lang`` on ``<html>`` and a style rule in
the page head hides the other one. Without JavaScript the default language
shows. When both languages give the same text (or the second is missing, so the
default language is the fallback) a single plain text is written.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from markupsafe import Markup, escape

from wikibase_static import crm
from wikibase_static.loader import LabelResolver, Site
from wikibase_static.model import Entity, Snak, Statement, id_sort_key, is_federated, pick_text
from wikibase_static.site_config import SiteConfig

EARTH = "http://www.wikidata.org/entity/Q2"
WIKIDATA = "https://www.wikidata.org/wiki/"
COMMONS = "https://commons.wikimedia.org/wiki/"
LINK_SCHEMES = ("http://", "https://", "ftp://", "ftps://")
ENTITY_URI = re.compile(r"/entity/([QP][1-9][0-9]*)$")
TIME = re.compile(r"^([+-])(\d+)-(\d\d)-(\d\d)T")
JULIAN = "Q1985786"

# --------------------------------------------------------------------------- interface texts

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "statements": "Statements", "no_statements": "No statements.", "also_known_as": "Also known as",
        "no_description": "No description", "references_one": "1 reference", "references_other": "{n} references",
        "unknown_value": "unknown value", "in_other_languages": "In other languages",
        "no_label_yet": "No label defined", "no_description_yet": "No description defined",
        "tools": "Tools", "referenced_by_short": "Referenced by", "tab_read": "Read", "tab_original": "Original",
        "page_downloads": "Download", "download_ttl": "RDF (Turtle)", "download_json": "JSON",
        "copy_uri": "Copy concept URI", "copy_page_uri": "Copy page URL", "copied": "Copied",
        "crm": "CIDOC CRM class", "crm_from": "from", "crm_none": "none yet",
        "rank": "Rank", "rank_normal": "normal",
        "no_value": "no value", "rank_preferred": "preferred", "rank_deprecated": "deprecated",
        "datatype": "Data type", "referenced_by": "Referenced by ({n})", "items": "Items", "properties": "Properties",
        "overview": "Overview", "overview_intro": "The items of this site, grouped by the class they are an instance of. An item with several classes appears under each of them.",
        "instances_n": "{n} instances", "instances_one": "1 instance", "overview_map": "Map of the instances of {class}", "index_lists": "Lists",
        "items_intro": "All items of this site.", "properties_intro": "All properties of this site.",
        "id": "ID", "label": "Label", "description": "Description", "source": "Source", "as_of": "As of",
        "license": "Licence", "license_missing": "Licence not stated", "imprint": "Imprint",
        "generated": "Static read-only copy, generated with", "map": "Map", "item": "Item", "property": "Property",
        "entities_n": "{n} entities ({items} items, {properties} properties)", "language": "Language",
        "open_original": "Original page", "federated": "Wikidata (opens in a new tab)",
        "dt_wikibase-item": "Item", "dt_wikibase-property": "Property", "dt_string": "String",
        "dt_external-id": "External identifier", "dt_url": "URL", "dt_commonsMedia": "Commons media file",
        "dt_time": "Point in time", "dt_quantity": "Quantity", "dt_monolingualtext": "Monolingual text",
        "dt_globe-coordinate": "Globe coordinate", "home": "Home", "unsupported": "Unsupported value",
        "search": "Search", "search_none": "No results", "search_error": "The search index could not be loaded.",
        "sparql": "SPARQL", "sq_run": "Run", "sq_reset": "Reset", "sq_rq": "Download as .rq",
        "sq_prefixes": "Prefixes (put in front of every query)", "sq_data": "The data",
        "sq_data_text": "A Turtle file in the RDF model of Wikibase with {n} triples:",
        "sq_ontology": "Wikibase ontology", "sq_files": "Every record on its own:",
        "sq_files_text": "each page has a Turtle file in ttl/ and the archived JSON in json/; the catalogue (DCAT) lists them.",
        "sq_note": "The first run loads Python (Pyodide) from cdn.jsdelivr.net and rdflib from PyPI; after that everything runs in your browser and what you type does not leave it.",
        "sq_noscript": "Running queries needs JavaScript.",
        "sq_start": "Press Run to start. The first run takes a few seconds.",
        "sq_js_loading_runtime": "Loading Python (Pyodide) ...", "sq_js_loading_rdflib": "Installing rdflib ...",
        "sq_js_loading_graph": "Loading the data ...", "sq_js_ready": "Ready: {n} triples.",
        "sq_js_start_failed": "Could not start: {error}", "sq_js_runtime_unreachable": "{url} cannot be reached (offline?)",
        "sq_js_graph_unreachable": "The data file could not be fetched; open this page over http(s), not from a file.",
        "sq_js_graph_http": "The data file answered with HTTP {status}.",
        "sq_js_running": "Running ...", "sq_js_done": "{s} s over {n} triples", "sq_js_empty": "No results. The query is valid but matched nothing.",
        "sq_js_capped": "Showing the first {shown} of {total} rows.", "sq_js_rows_one": "1 row.", "sq_js_rows_other": "{n} rows.",
        "sq_js_unbound": "no value",
        "sq_js_ask_true": "true", "sq_js_ask_false": "false", "sq_js_graph_count": "{n} triples constructed.",
        "sq_js_images_capped": "Showing the first {shown} of {total} images.",
        "sq_js_link_copied": "Link copied.", "sq_js_link_in_address_bar": "The address bar now holds the link.",
        "query": "Query", "sq_to_editor": "Open in the query editor",
        "sq_q_heading": "Query editor",
        "sq_q_intro": "Write any SPARQL query over the data of this site, as on the Query Service of Wikibase or Wikidata. The result is shown as a table, and as a map or pictures when it holds coordinates or image files.",
        "sq_q_examples": "Examples", "sq_q_pick": "Load an example ...", "sq_q_editor": "SPARQL query",
        "sq_q_run": "Run", "sq_q_share": "Copy link to this query", "sq_q_views": "Show the result as",
        "sq_q_table": "Table", "sq_q_map": "Map", "sq_q_images": "Images", "sq_q_download": "Download:",
        "sq_q_hint": "Ctrl+Enter runs the query. SELECT, ASK and CONSTRUCT work. A table with Point(...) values can be shown as a map, a table with image files as pictures; a comment line #defaultView:Map or #defaultView:ImageGrid opens that view first.",
    },
    "de": {
        "statements": "Aussagen", "no_statements": "Keine Aussagen.", "also_known_as": "Auch bekannt als",
        "no_description": "Keine Beschreibung", "references_one": "Eine Fundstelle", "references_other": "{n} Fundstellen",
        "unknown_value": "unbekannter Wert", "in_other_languages": "In weiteren Sprachen",
        "no_label_yet": "Keine Bezeichnung vorhanden", "no_description_yet": "Keine Beschreibung vorhanden",
        "tools": "Werkzeuge", "referenced_by_short": "Verwendet von", "tab_read": "Lesen", "tab_original": "Original",
        "page_downloads": "Herunterladen", "download_ttl": "RDF (Turtle)", "download_json": "JSON",
        "copy_uri": "Konzept-URI kopieren", "copy_page_uri": "Seiten-URL kopieren", "copied": "Kopiert",
        "crm": "CIDOC-CRM-Klasse", "crm_from": "von", "crm_none": "noch keine",
        "rank": "Rang", "rank_normal": "normal",
        "no_value": "kein Wert", "rank_preferred": "bevorzugt", "rank_deprecated": "veraltet",
        "datatype": "Datentyp", "referenced_by": "Verwendet von ({n})", "items": "Items", "properties": "Properties",
        "overview": "Übersicht", "overview_intro": "Die Items dieser Seite, gruppiert nach der Klasse, deren Instanz sie sind. Ein Item mit mehreren Klassen erscheint unter jeder von ihnen.",
        "instances_n": "{n} Instanzen", "instances_one": "1 Instanz", "overview_map": "Karte der Instanzen von {class}", "index_lists": "Listen",
        "items_intro": "Alle Items dieser Seite.", "properties_intro": "Alle Properties dieser Seite.",
        "id": "ID", "label": "Bezeichnung", "description": "Beschreibung", "source": "Quelle", "as_of": "Stand",
        "license": "Lizenz", "license_missing": "Lizenz nicht angegeben", "imprint": "Impressum",
        "generated": "Statische Nur-Lese-Kopie, erzeugt mit", "map": "Karte", "item": "Item", "property": "Property",
        "entities_n": "{n} Entitäten ({items} Items, {properties} Properties)", "language": "Sprache",
        "open_original": "Originalseite", "federated": "Wikidata (öffnet in neuem Tab)",
        "dt_wikibase-item": "Item", "dt_wikibase-property": "Property", "dt_string": "Zeichenkette",
        "dt_external-id": "Externer Bezeichner", "dt_url": "URL", "dt_commonsMedia": "Commons-Mediendatei",
        "dt_time": "Zeitpunkt", "dt_quantity": "Größe", "dt_monolingualtext": "Einsprachiger Text",
        "dt_globe-coordinate": "Geokoordinate", "home": "Startseite", "unsupported": "Nicht unterstützter Wert",
        "search": "Suche", "search_none": "Keine Treffer", "search_error": "Der Suchindex konnte nicht geladen werden.",
        "sparql": "SPARQL", "sq_run": "Ausführen", "sq_reset": "Zurücksetzen", "sq_rq": "Als .rq laden",
        "sq_prefixes": "Präfixe (werden jeder Abfrage vorangestellt)", "sq_data": "Die Daten",
        "sq_data_text": "Eine Turtle-Datei im RDF-Modell von Wikibase mit {n} Tripeln:",
        "sq_ontology": "Wikibase-Ontologie", "sq_files": "Jeder Datensatz einzeln:",
        "sq_files_text": "zu jeder Seite gibt es eine Turtle-Datei in ttl/ und das archivierte JSON in json/; der Katalog (DCAT) verzeichnet sie.",
        "sq_note": "Der erste Lauf lädt Python (Pyodide) von cdn.jsdelivr.net und rdflib von PyPI; danach läuft alles in Ihrem Browser, und was Sie eintippen, verlässt ihn nicht.",
        "sq_noscript": "Zum Ausführen von Abfragen wird JavaScript benötigt.",
        "sq_start": "Auf „Ausführen“ klicken, um zu starten. Der erste Lauf dauert einige Sekunden.",
        "sq_js_loading_runtime": "Python (Pyodide) wird geladen ...", "sq_js_loading_rdflib": "rdflib wird installiert ...",
        "sq_js_loading_graph": "Daten werden geladen ...", "sq_js_ready": "Bereit: {n} Tripel.",
        "sq_js_start_failed": "Start nicht möglich: {error}", "sq_js_runtime_unreachable": "{url} ist nicht erreichbar (offline?)",
        "sq_js_graph_unreachable": "Die Datendatei ließ sich nicht abrufen; die Seite bitte über http(s) öffnen, nicht aus einer Datei.",
        "sq_js_graph_http": "Die Datendatei antwortete mit HTTP {status}.",
        "sq_js_running": "Läuft ...", "sq_js_done": "{s} s über {n} Tripel", "sq_js_empty": "Keine Ergebnisse. Die Abfrage ist gültig, hat aber nichts gefunden.",
        "sq_js_capped": "Gezeigt werden die ersten {shown} von {total} Zeilen.", "sq_js_rows_one": "1 Zeile.", "sq_js_rows_other": "{n} Zeilen.",
        "sq_js_unbound": "kein Wert",
        "sq_js_ask_true": "wahr", "sq_js_ask_false": "falsch", "sq_js_graph_count": "{n} Tripel erzeugt.",
        "sq_js_images_capped": "Gezeigt werden die ersten {shown} von {total} Bildern.",
        "sq_js_link_copied": "Link kopiert.", "sq_js_link_in_address_bar": "Der Link steht jetzt in der Adresszeile.",
        "query": "Abfrage", "sq_to_editor": "Im Abfrage-Editor öffnen",
        "sq_q_heading": "Abfrage-Editor",
        "sq_q_intro": "Beliebige SPARQL-Abfragen über die Daten dieser Seite, wie im Query Service von Wikibase oder Wikidata. Das Ergebnis erscheint als Tabelle, bei Koordinaten oder Bilddateien auch als Karte oder Bilder.",
        "sq_q_examples": "Beispiele", "sq_q_pick": "Beispiel laden ...", "sq_q_editor": "SPARQL-Abfrage",
        "sq_q_run": "Ausführen", "sq_q_share": "Link zu dieser Abfrage kopieren", "sq_q_views": "Ergebnis zeigen als",
        "sq_q_table": "Tabelle", "sq_q_map": "Karte", "sq_q_images": "Bilder", "sq_q_download": "Herunterladen:",
        "sq_q_hint": "Strg+Eingabe führt die Abfrage aus. SELECT, ASK und CONSTRUCT funktionieren. Eine Tabelle mit Point(...)-Werten lässt sich als Karte zeigen, eine mit Bilddateien als Bilder; eine Kommentarzeile #defaultView:Map oder #defaultView:ImageGrid öffnet diese Ansicht zuerst.",
    },
}


# Names of languages, as (English, German); a code that is not listed is shown as it is.
LANGUAGE_NAMES: dict[str, tuple[str, str]] = {
    "en": ("English", "Englisch"), "de": ("German", "Deutsch"), "fr": ("French", "Französisch"),
    "es": ("Spanish", "Spanisch"), "it": ("Italian", "Italienisch"), "nl": ("Dutch", "Niederländisch"),
    "pt": ("Portuguese", "Portugiesisch"), "ru": ("Russian", "Russisch"), "pl": ("Polish", "Polnisch"),
    "cs": ("Czech", "Tschechisch"), "sk": ("Slovak", "Slowakisch"), "sv": ("Swedish", "Schwedisch"),
    "da": ("Danish", "Dänisch"), "no": ("Norwegian", "Norwegisch"), "nb": ("Norwegian Bokmål", "Norwegisch (Bokmål)"),
    "fi": ("Finnish", "Finnisch"), "el": ("Greek", "Griechisch"), "la": ("Latin", "Latein"),
    "tr": ("Turkish", "Türkisch"), "ja": ("Japanese", "Japanisch"), "zh": ("Chinese", "Chinesisch"),
    "ar": ("Arabic", "Arabisch"), "he": ("Hebrew", "Hebräisch"), "ga": ("Irish", "Irisch"),
    "cy": ("Welsh", "Walisisch"), "hu": ("Hungarian", "Ungarisch"), "ro": ("Romanian", "Rumänisch"),
    "hr": ("Croatian", "Kroatisch"), "sl": ("Slovenian", "Slowenisch"), "bg": ("Bulgarian", "Bulgarisch"),
    "uk": ("Ukrainian", "Ukrainisch"), "ca": ("Catalan", "Katalanisch"), "mul": ("Default for all languages", "Standard für alle Sprachen"),
}


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# --------------------------------------------------------------------------- pure value formatting


def format_time(value: dict[str, Any]) -> str:
    """A Wikibase time value as text, by precision. Years before 1 CE end in BCE."""
    match = TIME.match(str(value.get("time", "")))
    if not match:
        return str(value.get("time", ""))
    sign, year_text, month, day = match.groups()
    year = int(year_text)
    precision = value.get("precision")
    precision = precision if isinstance(precision, int) else 11
    bce = sign == "-"
    shown_year = f"{year} BCE" if bce else f"{year:04d}" if year < 1000 else str(year)
    if precision >= 11:
        text = f"{year_text.zfill(4)}-{month}-{day}"
        text = f"{text} BCE" if bce else text
    elif precision == 10:
        text = f"{year_text.zfill(4)}-{month}"
        text = f"{text} BCE" if bce else text
    elif precision == 9:
        text = shown_year
    elif precision == 8:
        text = f"{(year // 10) * 10}s" + (" BCE" if bce else "")
    elif precision == 7:
        text = f"{_ordinal((year - 1) // 100 + 1)} century" + (" BCE" if bce else "")
    elif precision == 6:
        text = f"{_ordinal((year - 1) // 1000 + 1)} millennium" + (" BCE" if bce else "")
    else:
        text = shown_year
    if str(value.get("calendarmodel", "")).endswith("/" + JULIAN):
        text += " (Julian)"
    return text


def _decimal(text: Any) -> Decimal | None:
    try:
        return Decimal(str(text).lstrip("+"))
    except (InvalidOperation, ValueError):
        return None


def format_amount(value: dict[str, Any]) -> tuple[str, str | None]:
    """Quantity amount with ``±`` when the bounds are symmetric, and the unit URI (``None`` for unit ``1``)."""
    amount = _decimal(value.get("amount"))
    text = str(value.get("amount", "")).lstrip("+") if amount is None else format(amount, "f")
    lower, upper = _decimal(value.get("lowerBound")), _decimal(value.get("upperBound"))
    if amount is not None and lower is not None and upper is not None:
        down, up = amount - lower, upper - amount
        if down == up and down != 0:
            text += f" ±{format(down, 'f')}"
        elif down != 0 or up != 0:
            text += f" ({format(lower, 'f')}–{format(upper, 'f')})"
    unit = value.get("unit")
    return text, (unit if isinstance(unit, str) and unit not in ("", "1") else None)


def format_coordinate(value: dict[str, Any]) -> str:
    """``39.08002° N, 17.12661° E``; at most as many decimals as the precision in degrees implies.

    Trailing zeros are dropped, so a value the source stores as 39.08002 is shown as 39.08002.
    """
    lat, lon = value.get("latitude"), value.get("longitude")
    precision = value.get("precision")
    if isinstance(precision, (int, float)) and precision > 0:
        decimals = min(8, max(0, math.ceil(-math.log10(precision))))
    else:
        decimals = 5
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return f"{lat}, {lon}"

    def number(x: float) -> str:
        text = f"{abs(x):.{decimals}f}"
        return text.rstrip("0").rstrip(".") if "." in text else text

    return (f"{number(lat_f)}° {'N' if lat_f >= 0 else 'S'}, "
            f"{number(lon_f)}° {'E' if lon_f >= 0 else 'W'}")


def map_point(value: dict[str, Any]) -> tuple[float, float] | None:
    """Latitude and longitude when the value is on Earth and in range, else ``None``."""
    if value.get("globe") != EARTH:
        return None
    try:
        lat, lon = float(value["latitude"]), float(value["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def commons_name(name: str) -> str:
    return quote(name.strip().replace(" ", "_"), safe="")


def is_linkable(url: str) -> bool:
    return url.lower().startswith(LINK_SCHEMES)


# --------------------------------------------------------------------------- the renderer


@dataclass
class MapPoint:
    lat: float
    lon: float
    text: str


class Renderer:
    """Builds the template contexts of the index page and of every entity page."""

    def __init__(self, site: Site, cfg: SiteConfig, version: str) -> None:
        self.site = site
        self.cfg = cfg
        self.version = version
        self.default = cfg.default_language
        self.second = cfg.second_language
        self._labels_default = LabelResolver(site, [self.default])
        self._labels_second = LabelResolver(site, [self.second, self.default]) if self.second else None
        self.incoming = self._build_incoming()
        self.unmapped_coordinates = 0
        self._crm_edges: dict[str, list[str]] | None = None
        self._kernel = False

    # ---- text

    def bilingual(self, default_text: str, second_text: str | None) -> Markup:
        if not self.second or second_text is None or second_text == default_text:
            return Markup(escape(default_text))
        return Markup(f'<span class="l" lang="{escape(self.default)}">{escape(default_text)}</span>'
                      f'<span class="l" lang="{escape(self.second)}">{escape(second_text)}</span>')

    def ui(self, key: str, **kwargs: Any) -> Markup:
        def text(language: str) -> str:
            table = STRINGS.get(language, STRINGS["en"])
            return table.get(key, STRINGS["en"][key]).format(**kwargs)
        return self.bilingual(text(self.default), text(self.second) if self.second else None)

    def ui_text(self, key: str, **kwargs: Any) -> str:
        """The default-language interface text as plain text (for ``<title>`` and attributes)."""
        table = STRINGS.get(self.default, STRINGS["en"])
        return table.get(key, STRINGS["en"][key]).format(**kwargs)

    def label_text(self, entity_id: str, second: bool = False) -> str:
        resolver = self._labels_second if second and self._labels_second else self._labels_default
        return resolver.label(entity_id)

    def label(self, entity_id: str) -> Markup:
        return self.bilingual(self.label_text(entity_id), self.label_text(entity_id, True) if self.second else None)

    def _pick(self, mapping: dict[str, str], languages: list[str]) -> str | None:
        return pick_text(mapping, languages)

    def description_text(self, entity: Entity) -> str | None:
        return self._pick(entity.descriptions, [self.default])

    def description(self, entity: Entity) -> Markup | None:
        first = self.description_text(entity)
        if first is None:
            return None
        other = self._pick(entity.descriptions, [self.second, self.default]) if self.second else None
        return self.bilingual(first, other)

    def search_texts_json(self) -> str:
        """The texts of the search box for ``search.js``, one set per language of the site, as JSON.

        The placeholder is an attribute and the "no results" line is made by script, so neither can use the
        two-``<span>`` technique of the other texts; the script picks the set that matches ``data-lang``."""
        texts = {}
        for language in [self.default] + ([self.second] if self.second else []):
            table = STRINGS.get(language, STRINGS["en"])
            texts[language] = {"placeholder": table["search"], "none": table["search_none"], "error": table["search_error"]}
        return json.dumps(texts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def sparql_texts(self) -> dict[str, dict[str, str]]:
        """The messages of ``sparql.js`` (``sq_js_*`` in ``STRINGS``), one set per language of the site, keys without the prefix."""
        texts = {}
        for language in [self.default] + ([self.second] if self.second else []):
            table = STRINGS.get(language, STRINGS["en"])
            texts[language] = {key[len("sq_js_"):]: table.get(key, STRINGS["en"][key])
                               for key in sorted(STRINGS["en"]) if key.startswith("sq_js_")}
        return texts

    def ui_plural(self, base: str, n: int) -> Markup:
        """``references_one`` for exactly one, ``references_other`` (with ``{n}``) otherwise."""
        return self.ui(f"{base}_one" if n == 1 else f"{base}_other", n=n)

    def language_name(self, code: str, language: str) -> str:
        names = LANGUAGE_NAMES.get(code)
        if not names:
            return code
        return names[1] if language == "de" else names[0]

    def language_rows(self, entity: Entity) -> list[dict[str, Any]]:
        """Rows of the table "in other languages": the default and the second language always, then every
        other language the entity has a label, description or alias in (sorted by code). A missing text is
        said to be missing, as Wikibase does."""
        codes = [self.default] + ([self.second] if self.second else [])
        present = set(entity.labels) | set(entity.descriptions) | set(entity.aliases)
        codes += sorted(present - set(codes))
        rows = []
        for code in codes:
            name = self.bilingual(self.language_name(code, self.default),
                                  self.language_name(code, self.second) if self.second else None)
            label, description = entity.labels.get(code), entity.descriptions.get(code)
            aliases = entity.aliases.get(code) or []
            rows.append({
                "code": code, "name": name,
                "label": Markup(escape(label)) if label else Markup(f'<span class="muted">{self.ui("no_label_yet")}</span>'),
                "description": Markup(escape(description)) if description else Markup(f'<span class="muted">{self.ui("no_description_yet")}</span>'),
                "aliases": Markup(" | ".join(str(escape(a)) for a in aliases)),
            })
        return rows

    def crm_rows(self, entity: Entity) -> list[dict[str, Any]] | None:
        """The CIDOC CRM classes of an item for the page (S11): ``None`` when the site has no ``data/crm.csv`` or the entity is
        a property or a kernel item; an empty list when the item has none yet. ``via`` is the link to the class the row
        was inherited from, ``None`` where the entity says it itself."""
        if not self.site.crm or entity.kind != "item":
            return None
        if self._crm_edges is None:
            self._crm_edges = self.site.crm_edges()
            self._kernel = self.site.has_kernel()
        if self._kernel and entity.id in ("Q1", "Q2", "Q3"):       # the kernel items are not data of the site
            return None
        return [{"curie": a.curie, "iri": crm.iri(a.curie), "via": None if a.via == entity.id else self.entity_link(a.via, show_id=False)}
                for a in self.site.crm_anchors(entity.id, self._crm_edges)]

    def heading(self, entity_id: str) -> Markup:
        """``Label (Q1)`` for the page heading."""
        return self.label_with_id(entity_id)

    # ---- links

    def label_with_id(self, entity_id: str) -> Markup:
        """The label followed by the id in a muted span, ``Label (Q10)``; just the id when there is no label."""
        if not self.site.entities[entity_id].labels:
            return Markup(escape(entity_id))
        return Markup(f'{self.label(entity_id)} <span class="id">({escape(entity_id)})</span>')

    def entity_link(self, entity_id: str, show_id: bool = True) -> Markup:
        """Internal link ``Label (Q10)`` when the site holds the entity; otherwise a link to Wikidata in a new tab."""
        if entity_id in self.site.entities:
            text = self.label_with_id(entity_id) if show_id else self.label(entity_id)
            return Markup(f'<a href="{escape(entity_id)}.html">{text}</a>')
        title = self.ui_text("federated")
        if is_federated(entity_id):     # wd:Q42 / wd:P31: the page is Q42 or Property:P31 on Wikidata, the text keeps the wd: prefix
            short = entity_id[3:]
            page = f"Property:{short}" if short.startswith("P") else short
            return Markup(f'<a class="federated" href="{WIKIDATA}{page}" target="_blank" '
                          f'rel="noopener" title="{escape(title)}">{escape(entity_id)}</a>')
        return Markup(f'<a class="federated" href="{WIKIDATA}{escape(entity_id)}" target="_blank" '
                      f'rel="noopener" title="{escape(title)}">{escape(entity_id)}</a>')

    def external_link(self, url: str, text: str | None = None) -> Markup:
        """A link that opens in a new tab, or plain text when the scheme is not one of http(s)/ftp."""
        shown = escape(url if text is None else text)
        if not is_linkable(url):
            return Markup(shown)
        return Markup(f'<a href="{escape(url)}" target="_blank" rel="noopener">{shown}</a>')

    # ---- values

    def formatter_url(self, property_id: str) -> str | None:
        prop = self.site.entities.get(property_id)
        if prop is None:
            return None
        for statement in prop.statements:
            snak = statement.mainsnak
            if snak.property == self.cfg.formatter_property and snak.vtype == "string" and isinstance(snak.value, str):
                if "$1" in snak.value:
                    return snak.value
        return None

    def value(self, snak: Snak) -> Markup:
        if snak.snaktype == "somevalue":
            return Markup(f'<span class="special">{self.ui("unknown_value")}</span>')
        if snak.snaktype == "novalue":
            return Markup(f'<span class="special">{self.ui("no_value")}</span>')
        value, kind = snak.value, snak.vtype
        if kind == "wikibase-entityid" and snak.entity_id:
            return self.entity_link(snak.entity_id)
        if kind == "string" and isinstance(value, str):
            return self._string_value(snak, value)
        if kind == "time" and isinstance(value, dict):
            return Markup(f'<span class="time">{escape(format_time(value))}</span>')
        if kind == "quantity" and isinstance(value, dict):
            return self._quantity(value)
        if kind == "monolingualtext" and isinstance(value, dict):
            return Markup(f'<span lang="{escape(value.get("language", ""))}">{escape(value.get("text", ""))}</span> '
                          f'<span class="tag">{escape(value.get("language", ""))}</span>')
        if kind == "globecoordinate" and isinstance(value, dict):
            return self._coordinate(value)
        shown = json.dumps(value, sort_keys=True, ensure_ascii=False)
        return Markup(f'<span class="special">{self.ui("unsupported")}:</span> <code>{escape(shown)}</code>')

    def _string_value(self, snak: Snak, value: str) -> Markup:
        datatype = snak.datatype
        if datatype == "url":
            return self.external_link(value)
        if datatype == "external-id":
            formatter = self.formatter_url(snak.property)
            if formatter:
                return self.external_link(formatter.replace("$1", quote(value, safe="")), value)
            return Markup(escape(value))
        if datatype == "commonsMedia":
            name = commons_name(value)
            image = f"{COMMONS}Special:FilePath/{name}?width=400"
            return Markup(f'<a class="commons" href="{COMMONS}File:{name}" target="_blank" rel="noopener">'
                          f'<img src="{escape(image)}" alt="{escape(value)}" loading="lazy"><br>{escape(value)}</a>')
        return Markup(escape(value))

    def _quantity(self, value: dict[str, Any]) -> Markup:
        text, unit = format_amount(value)
        out = escape(text)
        if unit:
            found = ENTITY_URI.search(unit)
            if found and found.group(1) in self.site.entities:
                out = Markup(f"{out} {self.entity_link(found.group(1))}")
            else:
                out = Markup(f"{out} {self.external_link(unit, found.group(1) if found else unit)}")
        return Markup(out)

    def _coordinate(self, value: dict[str, Any]) -> Markup:
        text = format_coordinate(value)
        point = map_point(value)
        if point is None:
            note = "" if value.get("globe") == EARTH else f' <span class="tag">{escape(str(value.get("globe", "")))}</span>'
            return Markup(f'<span class="coordinate">{escape(text)}</span>{note}')
        lat, lon = point
        osm = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=14/{lat}/{lon}"
        return Markup(f'<a class="coordinate" href="{escape(osm)}" target="_blank" rel="noopener">{escape(text)}</a>')

    # ---- statements

    def _snak_view(self, snak: Snak) -> dict[str, Any]:
        return {"property": snak.property, "label": self._property_label(snak.property),
                "link": snak.property in self.site.entities, "value": self.value(snak)}

    def _property_label(self, property_id: str) -> Markup:
        if property_id in self.site.entities:
            return self.label_with_id(property_id)
        return self.entity_link(property_id) if is_federated(property_id) else Markup(escape(property_id))

    def statement_groups(self, entity: Entity) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        for statement in entity.statements:
            prop = statement.mainsnak.property
            if not groups or groups[-1]["property"] != prop:
                groups.append({"property": prop, "label": self._property_label(prop), "link": prop in self.site.entities,
                               "statements": []})
            groups[-1]["statements"].append(self._statement_view(statement))
        return groups

    def _statement_view(self, statement: Statement) -> dict[str, Any]:
        return {
            "value": self.value(statement.mainsnak),
            "rank": statement.rank,
            "rank_title": f"{self.ui_text('rank')}: {self.ui_text('rank_' + statement.rank) if 'rank_' + statement.rank in STRINGS['en'] else statement.rank}",
            "qualifiers": [self._snak_view(q) for q in statement.qualifiers],
            "references": [[self._snak_view(s) for s in reference] for reference in statement.references],
            "references_label": self.ui_plural("references", len(statement.references)),
        }

    def map_points(self, entity: Entity) -> list[MapPoint]:
        points: list[MapPoint] = []
        for snak in entity.snaks():
            if snak.vtype != "globecoordinate" or not isinstance(snak.value, dict):
                continue
            point = map_point(snak.value)
            if point is None:
                self.unmapped_coordinates += 1
                continue
            text = format_coordinate(snak.value)
            if not any((p.lat, p.lon) == point for p in points):
                points.append(MapPoint(point[0], point[1], text))
        return points

    # ---- overview: instances by class

    def instance_property(self) -> str | None:
        """The property that says "instance of": P2 where the kernel is part of the site, otherwise the property whose
        English label is "instance of" (a harvested Wikibase has its own number, often P31); ``None`` when there is none."""
        if self.site.has_kernel():
            return "P2"
        for entity in sorted(self.site.properties, key=lambda e: id_sort_key(e.id)):
            if entity.labels.get("en", "").strip().lower() == "instance of":
                return entity.id
        return None

    def class_groups(self) -> list[dict[str, Any]]:
        """Classes with at least one direct instance, each with its instances, both in id order. The classes of the
        kernel (Q1 to Q3) are left out, and so are properties: the page is about the items of the domain."""
        prop = self.instance_property()
        if prop is None:
            return []
        kernel = {"Q1", "Q2", "Q3"} if prop == "P2" else set()
        members: dict[str, list[Entity]] = {}
        for entity in self.site.items:
            seen: set[str] = set()
            for statement in entity.statements:
                target = statement.mainsnak.entity_id
                if (statement.mainsnak.property == prop and target and target not in kernel and target not in seen
                        and target in self.site.entities):
                    seen.add(target)
                    members.setdefault(target, []).append(entity)
        groups = []
        for class_id in sorted(members, key=id_sort_key):
            instances = sorted(members[class_id], key=lambda e: id_sort_key(e.id))
            groups.append({"id": class_id, "instances": instances})
        return groups

    # ---- who points here

    def _build_incoming(self) -> dict[str, list[str]]:
        found: dict[str, set[str]] = {}
        for entity in self.site.entities.values():
            for target in entity.referenced_ids():
                if target != entity.id and target in self.site.entities:
                    found.setdefault(target, set()).add(entity.id)
        return {target: sorted(who, key=id_sort_key) for target, who in found.items()}

    def referenced_by(self, entity_id: str) -> list[dict[str, Any]]:
        return [{"id": who, "link": self.entity_link(who)} for who in self.incoming.get(entity_id, [])]

    # ---- the footer of every entity page

    def footer(self, entity: Entity | None) -> dict[str, Any]:
        source = self.cfg.source_url
        original = f"{source}/entity/{entity.id}" if source and entity else None
        modified = entity.modified[:10] if entity and entity.modified else None
        imprint = self.cfg.imprint
        return {
            "source_url": source, "source_text": re.sub(r"^https?://", "", source) if source else None,
            "original_url": original, "modified": modified,
            "license_name": self.cfg.license_name or self.cfg.license_url, "license_url": self.cfg.license_url,
            "imprint_url": imprint if imprint and is_linkable(imprint) else None,
            "imprint_text": imprint if imprint and not is_linkable(imprint) else None,
            "version": self.version,
        }
