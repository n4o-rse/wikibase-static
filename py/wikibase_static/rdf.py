"""S6 -- the Wikibase RDF data model: loaded entities in, sorted triples and Turtle out.

Pure functions of the model and the base URI; no file is read or written here (``step_rdf`` does that), no
clock, no network, nothing that depends on hash order. The mapping follows the RDF dump of Wikibase itself
(``RdfVocabulary``, ``FullStatementRdfBuilder``, ``TruthyStatementRdfBuilder``, ``SnakRdfBuilder``,
``PropertySpecificComponentsRdfBuilder`` and the value builders in the Wikibase source, read 2026-10-21; see
PRIMER.md, A1 Befund 22), so that a query written for the Query Service of a Wikibase runs against this file::

    wd:Q1  a wikibase:Item ;  rdfs:label, skos:prefLabel, schema:name "..."@en ;  schema:description ;  skos:altLabel
    wd:Q1  p:P1 wds:Q1-<guid> ;  wdt:P1 <value>                 (wdt only for the best-rank statements)
    wds:.. a wikibase:Statement, wikibase:BestRank ;  wikibase:rank wikibase:NormalRank ;  ps:P1 <value> ;
           pq:P2 <value> ;  prov:wasDerivedFrom wdref:<hash>
    wdref:<hash> a wikibase:Reference ;  pr:P4 <value>
    wd:P1  a wikibase:Property ;  wikibase:propertyType wikibase:WikibaseItem ;  wikibase:claim p:P1 ; ...

On top of that the export describes itself with DCAT 3 (``dcat:Catalog`` for the Wikibase and one per entity kind,
a ``dcat:Dataset`` for every entity record -- the ``data:Q1`` node Wikibase already types as ``schema:Dataset`` --
and a ``dcat:Distribution`` for each file that exists: the archived JSON, the HTML page and the Turtle file of
that entity). Distributions are only written when the site states ``pages_url``, because a distribution needs an
absolute download URL.

Where this differs from a real dump (and why) is listed in PRIMER.md, A4 ("RDF, Abweichungen"): the hashes of
reference and value nodes are our own (Wikibase's depend on PHP serialisation and cannot be reproduced from the
JSON), normalised external-id URIs (``wdtn:``) and sitelinks are not written, and blank nodes carry stable labels.

Output is deterministic: triples live in a set, are sorted with a natural order (``Q2`` before ``Q10``) and are
written by our own Turtle writer rather than by rdflib's serialiser, whose layout is not promised to be stable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Union
from urllib.parse import quote, urlparse

from wikibase_static import crm
from wikibase_static.loader import Site
from wikibase_static.model import (
    SUPPORTED_DATATYPES, Entity, Snak, Statement, federated_to_uri, id_sort_key, is_federated,
)

# --------------------------------------------------------------------------- vocabulary

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"
OWL = "http://www.w3.org/2002/07/owl#"
WIKIBASE = "http://wikiba.se/ontology#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
SCHEMA = "http://schema.org/"
CC = "http://creativecommons.org/ns#"
GEO = "http://www.opengis.net/ont/geosparql#"
PROV = "http://www.w3.org/ns/prov#"
DCAT = "http://www.w3.org/ns/dcat#"
DCTERMS = "http://purl.org/dc/terms/"
FILE_TYPE = "http://publications.europa.eu/resource/authority/file-type/"
MEDIA_TYPE = "https://www.iana.org/assignments/media-types/"
WIKIBASE_ONTOLOGY = "http://wikiba.se/ontology"

MEDIA_URI = "http://commons.wikimedia.org/wiki/Special:FilePath/"
GREGORIAN = "http://www.wikidata.org/entity/Q1985727"
JULIAN = "http://www.wikidata.org/entity/Q1985786"
EARTH = "http://www.wikidata.org/entity/Q2"
UNIT_ONE = "http://www.wikidata.org/entity/Q199"       # what Wikibase writes for the unit "1"
PLACEHOLDER_BASE = "https://wikibase.example"           # only when neither source.url nor rdf_base is known
FORMAT_VERSION = "1.0.0"                                # of the Wikibase RDF format this follows

# Datatypes whose direct property is an owl:ObjectProperty (the value is an IRI); the rest are DatatypeProperty.
OBJECT_DATATYPES = frozenset({"wikibase-item", "wikibase-property", "url", "commonsMedia"})

# The RDFS bridge (PRIMER.md, A4): when the kernel is part of the site, its three class properties and three
# classes are tied to RDFS and OWL, so that a reasoner (or a query with a property path) reads the class tree.
BRIDGE_PROPERTIES = {"P1": RDFS + "subClassOf", "P2": RDF + "type", "P3": RDFS + "subPropertyOf"}
BRIDGE_CLASSES = {"Q1": RDFS + "Class", "Q2": RDF + "Property", "Q3": OWL + "Thing"}
CRM_TITLE = ("CIDOC CRM anchoring (wikibase-static): the classes of this site tied to classes of the CIDOC CRM and its extensions "
             "(data/crm.csv) and the DCAT classes of this file (data/dcat-crm.csv),\nwith the superclasses of an extension class up to its first "
             "class of the CIDOC CRM, and subclass of / instance of spelled out as rdfs:subClassOf / rdf:type. Not part of the Wikibase data model.")
BRIDGE_TITLE = ("RDFS bridge of the kernel (wikibase-static): the direct properties P1 to P3 and the classes Q1 to Q3 "
                "tied to RDFS and OWL.\nNot part of the Wikibase data model; written only when the kernel is part of the site.")

PRECISION_YEAR, PRECISION_MONTH, PRECISION_DAY = 9, 10, 11


# --------------------------------------------------------------------------- terms


@dataclass(frozen=True)
class Iri:
    value: str


@dataclass(frozen=True)
class Lit:
    lexical: str
    datatype: str | None = None     # IRI of the datatype, None for a plain literal
    lang: str | None = None


@dataclass(frozen=True)
class Blank:
    label: str


Term = Union[Iri, Lit, Blank]
Triple = tuple[Term, Term, Term]

_IRI_BAD = re.compile(r"[\x00-\x20<>\"{}|^`\\]")
_LANG = re.compile(r"^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$")
_DECIMAL = re.compile(r"^[+-]?[0-9]+(\.[0-9]+)?$")


def iri(value: str) -> Iri:
    """An IRI with the characters Turtle does not allow inside ``<...>`` percent-encoded."""
    return Iri(_IRI_BAD.sub(lambda m: "".join(f"%{b:02X}" for b in m.group(0).encode("utf-8")), value))


def escape_literal(text: str) -> str:
    """The text of a string literal for N-Triples and Turtle (``"`` ``\\`` and control characters escaped)."""
    out = []
    for ch in text:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        else:
            out.append(ch)
    return "".join(out)


def nt(term: Term) -> str:
    """One term in N-Triples syntax."""
    if isinstance(term, Iri):
        return f"<{term.value}>"
    if isinstance(term, Blank):
        return f"_:{term.label}"
    text = f'"{escape_literal(term.lexical)}"'
    if term.lang:
        return f"{text}@{term.lang}"
    if term.datatype:
        return f"{text}^^<{term.datatype}>"
    return text


def bcp47(code: str) -> str:
    """A MediaWiki language code as a BCP 47 tag (``zh-hans`` becomes ``zh-Hans``); codes pass through otherwise."""
    parts = code.split("-")
    out = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            out.append(part.title())
        elif len(part) == 2 and part.isalpha():
            out.append(part.upper())
        else:
            out.append(part.lower())
    return "-".join(out)


# --------------------------------------------------------------------------- namespaces


class Namespaces:
    """The namespaces of a Wikibase for one base URI (``https://example.wikibase.cloud``), as in ``RdfVocabulary``.

    ``family`` is the short name of a prefix family (``chb``): ``chb:`` for the entities, ``chbt:`` for the direct claims,
    ``chbp:``, ``chbps:``, ``chbpq:`` and so on for the rest. Without it the names are those of Wikidata (``wd:``, ``wdt:``,
    ``p:``, ``ps:``), which is right where the base URI is the real Wikibase and wrong where it is a site's own address: a
    reader would take ``wd:Q933`` for an item of Wikidata. The namespaces themselves do not depend on the family.

    A family also changes where the dataset of an entity lives (``data``): Wikibase calls the document of an entity
    ``<base>/wiki/Special:EntityData/<ID>``, which a static host does not have, so the family points it at the file that
    exists, ``<base>/ttl/<ID>.ttl`` (``data_suffix``)."""

    #: prefix of the Wikidata family -> ending of the name in a family (``chb`` + ending)
    FAMILY_ENDINGS = {"wd": "", "wds": "s", "wdt": "t", "p": "p", "ps": "ps", "psv": "psv", "pq": "pq", "pqv": "pqv", "pr": "pr",
                      "prv": "prv", "wdno": "no", "wdref": "ref", "wdv": "v", "data": "data", "cat": "cat", "dist": "dist"}

    def __init__(self, base: str, family: str | None = None) -> None:
        self.base = base.rstrip("/")
        self.family = family or None
        b = self.base
        self.wd = f"{b}/entity/"
        self.wds = f"{b}/entity/statement/"
        self.wdref = f"{b}/reference/"
        self.wdv = f"{b}/value/"
        self.wdt = f"{b}/prop/direct/"
        self.wdno = f"{b}/prop/novalue/"
        self.p = f"{b}/prop/"
        self.ps = f"{b}/prop/statement/"
        self.psv = f"{b}/prop/statement/value/"
        self.pq = f"{b}/prop/qualifier/"
        self.pqv = f"{b}/prop/qualifier/value/"
        self.pr = f"{b}/prop/reference/"
        self.prv = f"{b}/prop/reference/value/"
        self.data = f"{b}/ttl/" if self.family else f"{b}/wiki/Special:EntityData/"
        self.data_suffix = ".ttl" if self.family else ""
        self.cat = f"{b}/catalog/"          # not part of Wikibase: the catalogues this export adds
        self.dist = f"{b}/distribution/"    # likewise: the distributions of the datasets

    def dataset(self, entity_id: str) -> str:
        """The IRI of the dataset (the document) that describes an entity."""
        return f"{self.data}{entity_id}{self.data_suffix}"

    def prefix_name(self, wikidata_name: str) -> str:
        """The prefix this export uses for the namespace that Wikidata calls ``wikidata_name`` (``wdt``, ``ps``, ...)."""
        if not self.family:
            return wikidata_name
        return self.family + self.FAMILY_ENDINGS[wikidata_name]

    def prefixes(self) -> dict[str, str]:
        """Prefix to namespace, for the Turtle header and the SPARQL page."""
        own = {"cat": self.cat, "data": self.data, "dist": self.dist, "p": self.p, "pq": self.pq, "pqv": self.pqv,
               "pr": self.pr, "prv": self.prv, "ps": self.ps, "psv": self.psv, "wd": self.wd, "wdno": self.wdno,
               "wdref": self.wdref, "wds": self.wds, "wdt": self.wdt, "wdv": self.wdv}
        found = {self.prefix_name(name): namespace for name, namespace in own.items()}
        found.update({"cc": CC, "dcat": DCAT, "dcterms": DCTERMS, "geo": GEO, "owl": OWL, "prov": PROV, "rdf": RDF, "rdfs": RDFS,
                      "schema": SCHEMA, "skos": SKOS, "wikibase": WIKIBASE, "xsd": XSD})
        return found


def file_stem(base: str) -> str:
    """The name of the Turtle file for a base URI: its host (and path), made safe for a file name."""
    parsed = urlparse(base)
    text = (parsed.netloc + parsed.path).strip("/") or "wikibase"
    return re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-") or "wikibase"


# --------------------------------------------------------------------------- hashes


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


# --------------------------------------------------------------------------- dates (Wikibase's DateTimeValueCleaner)

_DATE = re.compile(r"^[+-]?([0-9]+)-([0-9]+)-([0-9]+)T(.*)$")


def _parse_date(time_text: str) -> tuple[bool, int, int, int, str] | None:
    """(minus, year, month, day, rest) of a Wikibase time string; month and day are clamped as Wikibase does.
    ``None`` for year 0, which Wikibase treats as invalid."""
    match = _DATE.match(time_text)
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if year == 0:
        return None
    month = 1 if month <= 0 else min(month, 12)
    day = 1 if day <= 0 else day
    return time_text.startswith("-"), year, month, day, match.group(4)


def _days_in_month(month: int, year_astronomical: int) -> int:
    if month == 2:
        leap = year_astronomical % 4 == 0 and (year_astronomical % 100 != 0 or year_astronomical % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _gregorian_text(minus: bool, year_astronomical_abs: int, month: int, day: int, rest: str, negative: bool) -> str:
    return f"{'-' if negative else ''}{year_astronomical_abs:04d}-{month:02d}-{day:02d}T{rest}"


def _cleanup_gregorian(time_text: str, precision: int) -> str | None:
    parsed = _parse_date(time_text)
    if parsed is None:
        return None
    minus, year, month, day, rest = parsed
    if precision <= PRECISION_YEAR:
        month = day = 1
    elif precision == PRECISION_MONTH:
        day = 1
    if not (day <= 28 or (month != 2 and day <= 30)):
        astronomical = -(year - 1) if minus else year
        day = min(day, _days_in_month(month, astronomical))
    negative = minus
    if precision >= PRECISION_YEAR and minus:
        year -= 1                                # historical BCE numbering to XSD 1.1 (year 0 exists)
        if year == 0:
            negative = False
    return _gregorian_text(minus, year, month, day, rest, negative)


def _julian_to_gregorian(time_text: str) -> str | None:
    """The Gregorian reading of a Julian date at day precision, by Julian day number; ``None`` outside the range."""
    parsed = _parse_date(time_text)
    if parsed is None:
        return None
    minus, year, month, day, rest = parsed
    historical = -year if minus else year
    if historical < -4713 or historical > 1465072 or day > 31:
        return None
    astronomical = historical + 1 if historical < 0 else historical
    a = (14 - month) // 12
    y = astronomical + 4800 - a
    m = month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
    if jdn <= 0:
        return None
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    g_day = e - (153 * m + 2) // 5 + 1
    g_month = m + 3 - 12 * (m // 10)
    g_year = 100 * b + d - 4800 + m // 10
    return f"{'-' if g_year < 0 else ''}{abs(g_year):04d}-{g_month:02d}-{g_day:02d}T{rest}"


def standard_datetime(time_text: str, precision: int, calendar: str) -> str | None:
    """The ``xsd:dateTime`` text Wikibase writes for a time value, or ``None`` when it writes the original text.

    Gregorian dates, and any date less precise than a day, are tidied (month and day 00 become 01, a day past
    the end of the month is clamped, a negative year moves from historical to XSD 1.1 numbering). Julian dates at
    day precision are converted to the Gregorian calendar. Other calendars give ``None``."""
    calendar = calendar.strip()
    if calendar == JULIAN and precision >= PRECISION_DAY:
        return _julian_to_gregorian(time_text) or _cleanup_gregorian(time_text, precision)
    if calendar == GREGORIAN or precision < PRECISION_DAY:
        return _cleanup_gregorian(time_text, precision)
    return None


# --------------------------------------------------------------------------- numbers


def _number(x: float) -> str:
    """A float as PHP prints it (14 significant digits), without exponent for coordinates."""
    text = format(x, ".14g")
    if "e" in text and abs(x) >= 1e-4:
        text = format(x, ".14f").rstrip("0").rstrip(".")
    return text


# --------------------------------------------------------------------------- the build


@dataclass
class Rdf:
    triples: set[Triple] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)
    entities: int = 0
    statements: int = 0
    skipped: dict[str, int] = field(default_factory=dict)       # property id -> snaks not written
    by_entity: dict[str, set[Triple]] = field(default_factory=dict)   # the triples of each entity's own file
    notes: list[str] = field(default_factory=list)
    distributions: int = 0
    federated: int = 0                                          # snaks of Wikidata properties (wd:P...), linked but not exported
    bridge: set[Triple] = field(default_factory=set)            # the RDFS bridge triples (kernel only), also in ``triples``
    crm: set[Triple] = field(default_factory=set)               # the CIDOC CRM anchoring (data/crm.csv), also in ``triples``


@dataclass
class CatalogInfo:
    """What the DCAT description needs to know besides the entities."""
    title: str
    description: str = ""
    license_url: str | None = None
    source_url: str | None = None          # the Wikibase itself: landing page of the catalogue
    pages_url: str | None = None           # where docs/ is published; without it there are no distributions
    modified: str | None = None
    json_sizes: dict[str, int] = field(default_factory=dict)   # entity id -> bytes of the archived JSON file
    export_file: str | None = None         # e.g. downloads/fuzzy-sl.wikibase.cloud.ttl
    ontology_file: str | None = None       # e.g. downloads/wikibase-ontology.ttl
    ontology_bytes: int | None = None


class _Builder:
    def __init__(self, site: Site, ns: Namespaces, license_url: str | None, catalog: CatalogInfo | None = None) -> None:
        self.site = site
        self.ns = ns
        self.license_url = license_url
        self.catalog = catalog
        self.owner: set[Triple] | None = None
        self.out = Rdf()
        self.property_types = {e.id: e.datatype for e in site.properties if e.datatype}
        self.problems: set[str] = set()
        self.skipped_types: dict[str, str] = {}
        self.kernel = site.has_kernel()

    # ---- small helpers

    def add(self, s: Term, p: Term, o: Term) -> None:
        self.out.triples.add((s, p, o))
        if self.owner is not None:
            self.owner.add((s, p, o))

    def _wd(self, entity_id: str) -> Iri:
        if is_federated(entity_id):         # an entity of Wikidata keeps its own URI
            return Iri(federated_to_uri(entity_id))
        return Iri(self.ns.wd + entity_id)

    @staticmethod
    def _a() -> Iri:
        return Iri(RDF + "type")

    @staticmethod
    def _wb(name: str) -> Iri:
        return Iri(WIKIBASE + name)

    def _problem(self, message: str) -> None:
        self.problems.add(message)

    # ---- values

    def _datatype_of(self, snak: Snak) -> str | None:
        return snak.datatype or self.property_types.get(snak.property)

    def _value(self, snak: Snak, datatype: str) -> tuple[Term, tuple[Iri, list[tuple[Iri, Term]]] | None] | None:
        """(simple value, value node) of a snak, or ``None`` when it cannot be written (a problem is recorded).

        The value node is (its IRI, [(predicate, object)]) for time, quantity and globe-coordinate values."""
        value = snak.value
        where = f"{snak.property} ({datatype})"
        if datatype in ("wikibase-item", "wikibase-property"):
            target = snak.entity_id
            if not target or not (re.match(r"^[A-Za-z][0-9]+$", target) or is_federated(target)):
                self._problem(f"rdf: {where} value without a usable entity id; not written")
                return None
            return self._wd(target), None
        if datatype in ("string", "external-id"):
            if not isinstance(value, str):
                self._problem(f"rdf: {where} value is not text; not written")
                return None
            return Lit(value.strip() if datatype == "external-id" else value), None
        if datatype == "url":
            if not isinstance(value, str) or not value.strip():
                self._problem(f"rdf: {where} value is not text; not written")
                return None
            return iri(value.strip()), None
        if datatype == "commonsMedia":
            if not isinstance(value, str):
                self._problem(f"rdf: {where} value is not text; not written")
                return None
            return iri(MEDIA_URI + quote(value, safe="")), None
        if datatype == "monolingualtext" and isinstance(value, dict):
            tag = bcp47(str(value.get("language", "")))
            if not _LANG.match(tag):
                self._problem(f"rdf: {where} has the language code {value.get('language')!r}; not written")
                return None
            return Lit(str(value.get("text", "")), lang=tag), None
        node_hash = _md5(_canonical({"type": snak.vtype, "value": value}))
        node = Iri(self.ns.wdv + node_hash)
        if datatype == "time" and isinstance(value, dict):
            time_text = str(value.get("time", ""))
            precision = value.get("precision")
            precision = precision if isinstance(precision, int) else PRECISION_DAY
            calendar = str(value.get("calendarmodel") or GREGORIAN)
            standard = standard_datetime(time_text, precision, calendar)
            simple: Term = Lit(standard, XSD + "dateTime") if standard else Lit(time_text)
            timezone = value.get("timezone")
            facts = [
                (self._wb("timeValue"), simple),
                (self._wb("timePrecision"), Lit(str(precision), XSD + "integer")),
                (self._wb("timeTimezone"), Lit(str(timezone if isinstance(timezone, int) else 0), XSD + "integer")),
                (self._wb("timeCalendarModel"), iri(calendar)),
            ]
            return simple, (node, [(self._a(), self._wb("TimeValue"))] + facts)
        if datatype == "quantity" and isinstance(value, dict):
            amount = str(value.get("amount", ""))
            if not _DECIMAL.match(amount):
                self._problem(f"rdf: {where} amount {amount!r} is not a decimal number; not written")
                return None
            facts = [(self._a(), self._wb("QuantityValue")), (self._wb("quantityAmount"), Lit(amount, XSD + "decimal"))]
            for key, name in (("upperBound", "quantityUpperBound"), ("lowerBound", "quantityLowerBound")):
                bound = value.get(key)
                if bound is not None and _DECIMAL.match(str(bound)):
                    facts.append((self._wb(name), Lit(str(bound), XSD + "decimal")))
            unit = str(value.get("unit", "1")).strip()
            facts.append((self._wb("quantityUnit"), Iri(UNIT_ONE) if unit == "1" else iri(unit)))
            return Lit(amount, XSD + "decimal"), (node, facts)
        if datatype == "globe-coordinate" and isinstance(value, dict):
            try:
                lat, lon = float(value["latitude"]), float(value["longitude"])
            except (KeyError, TypeError, ValueError):
                self._problem(f"rdf: {where} value has no usable latitude and longitude; not written")
                return None
            point = f"Point({_number(lon)} {_number(lat)})"
            globe = str(value.get("globe") or "").strip()
            if globe and globe != EARTH:
                point = f"<{globe.replace('>', '%3E')}> {point}"
            simple = Lit(point, GEO + "wktLiteral")
            facts = [(self._a(), self._wb("GlobecoordinateValue")),
                     (self._wb("geoLatitude"), Lit(_number(lat), XSD + "double")),
                     (self._wb("geoLongitude"), Lit(_number(lon), XSD + "double"))]
            precision = value.get("precision")
            if precision is None:
                facts.append((self._a(), self._wb("GeoAutoPrecision")))
                precision = 1 / 3600
            facts.append((self._wb("geoPrecision"), Lit(_number(float(precision)), XSD + "double")))
            facts.append((self._wb("geoGlobe"), iri(globe)))
            return simple, (node, facts)
        self._problem(f"rdf: {where} value has an unexpected shape; not written")
        return None

    # ---- snaks

    def snak(self, subject: Term, snak: Snak, kind: str, parent: str) -> None:
        """One snak on ``subject`` as direct (``wdt``), statement (``ps``), qualifier (``pq``) or reference (``pr``)."""
        ns = self.ns
        if is_federated(snak.property):     # a Wikidata property has no p:/ps: namespace on this Wikibase
            self.out.federated += 1
            return
        predicate_ns, value_ns = {"direct": (ns.wdt, None), "statement": (ns.ps, ns.psv),
                                  "qualifier": (ns.pq, ns.pqv), "reference": (ns.pr, ns.prv)}[kind]
        if snak.snaktype == "novalue":
            self.add(subject, self._a(), Iri(ns.wdno + snak.property))
            return
        if snak.snaktype == "somevalue":
            label = _md5("-".join([parent, predicate_ns, snak.property, "somevalue"]))
            self.add(subject, Iri(predicate_ns + snak.property), Blank(label))
            return
        datatype = self._datatype_of(snak)
        if not datatype or datatype not in SUPPORTED_DATATYPES:
            if kind != "direct":        # the direct copy of a main value is the same snak again
                self.out.skipped[snak.property] = self.out.skipped.get(snak.property, 0) + 1
            self.skipped_types.setdefault(snak.property, datatype or "unknown")
            return
        made = self._value(snak, datatype)
        if made is None:
            return
        simple, node = made
        self.add(subject, Iri(predicate_ns + snak.property), simple)
        if node is not None and value_ns is not None:
            node_iri, facts = node
            self.add(subject, Iri(value_ns + snak.property), node_iri)
            for predicate, obj in facts:
                self.add(node_iri, predicate, obj)

    # ---- statements

    @staticmethod
    def statement_name(entity: Entity, statement: Statement, position: int) -> str:
        if statement.id:
            return re.sub(r"[^\w-]", "-", statement.id, flags=re.ASCII)
        digest = _sha1(_canonical([entity.id, position, statement.mainsnak.property, statement.mainsnak.snaktype,
                                   statement.mainsnak.value]))
        return f"{entity.id}-g{digest[:32]}"

    def reference(self, node: Iri, group: list[Snak]) -> None:
        self.add(node, self._a(), self._wb("Reference"))
        for snak in group:
            self.snak(node, snak, "reference", node.value)

    def statements(self, entity: Entity) -> None:
        ns = self.ns
        subject = self._wd(entity.id)
        by_property: dict[str, list[tuple[int, Statement]]] = {}
        for position, statement in enumerate(entity.statements):
            by_property.setdefault(statement.mainsnak.property, []).append((position, statement))
        for prop, group in by_property.items():
            if is_federated(prop):
                self.out.federated += len(group)
                continue
            ranks = [s.rank for _pos, s in group]
            best_rank = "preferred" if "preferred" in ranks else "normal"
            for position, statement in group:
                self.out.statements += 1
                name = self.statement_name(entity, statement, position)
                node = Iri(ns.wds + name)
                is_best = statement.rank == best_rank
                self.add(subject, Iri(ns.p + prop), node)
                self.add(node, self._a(), self._wb("Statement"))
                rank_name = {"preferred": "PreferredRank", "normal": "NormalRank", "deprecated": "DeprecatedRank"}.get(statement.rank)
                if rank_name:
                    if is_best:
                        self.add(node, self._a(), self._wb("BestRank"))
                    self.add(node, self._wb("rank"), self._wb(rank_name))
                else:
                    self._problem(f"rdf: statement {statement.id or name} has the unknown rank {statement.rank!r}")
                self.snak(node, statement.mainsnak, "statement", name)
                if is_best:
                    self.snak(subject, statement.mainsnak, "direct", name)
                for qualifier in statement.qualifiers:
                    self.snak(node, qualifier, "qualifier", name)
                for group_of_snaks in statement.references:
                    if not group_of_snaks:
                        continue
                    digest = _sha1(_canonical(sorted(
                        _canonical([s.property, s.snaktype, s.datatype, s.vtype, s.value]) for s in group_of_snaks)))
                    reference = Iri(ns.wdref + digest)
                    self.add(node, Iri(PROV + "wasDerivedFrom"), reference)
                    self.reference(reference, group_of_snaks)

    # ---- entities

    def terms(self, entity: Entity) -> None:
        subject = self._wd(entity.id)

        def language(code: str) -> str | None:
            tag = bcp47(code)
            if _LANG.match(tag):
                return tag
            self._problem(f"rdf: {entity.id} has text in the language code {code!r}, which is not a valid tag; skipped")
            return None

        for code, text in entity.labels.items():
            tag = language(code)
            if tag:
                for predicate in (RDFS + "label", SKOS + "prefLabel", SCHEMA + "name"):
                    self.add(subject, Iri(predicate), Lit(text, lang=tag))
        for code, text in entity.descriptions.items():
            tag = language(code)
            if tag:
                self.add(subject, Iri(SCHEMA + "description"), Lit(text, lang=tag))
        for code, aliases in entity.aliases.items():
            tag = language(code)
            if tag:
                for alias in aliases:
                    self.add(subject, Iri(SKOS + "altLabel"), Lit(alias, lang=tag))

    def property_definition(self, entity: Entity) -> None:
        ns = self.ns
        pid = entity.id
        subject = self._wd(pid)
        if not entity.datatype:
            self._problem(f"rdf: property {pid} has no datatype; its definition is incomplete")
        else:
            name = re.sub(r"\W+", "", entity.datatype.replace("-", " ").title()) if entity.datatype != "commonsMedia" else "CommonsMedia"
            if entity.datatype == "commonsMedia":
                name = "CommonsMedia"
            self.add(subject, self._wb("propertyType"), self._wb(name))
        links = [("directClaim", ns.wdt), ("claim", ns.p), ("statementProperty", ns.ps), ("statementValue", ns.psv),
                 ("qualifier", ns.pq), ("qualifierValue", ns.pqv), ("reference", ns.pr), ("referenceValue", ns.prv),
                 ("novalue", ns.wdno)]
        for predicate, namespace in links:
            self.add(subject, self._wb(predicate), Iri(namespace + pid))
        direct_type = "ObjectProperty" if entity.datatype in OBJECT_DATATYPES else "DatatypeProperty"
        for namespace in (ns.p, ns.psv, ns.pqv, ns.prv):
            self.add(Iri(namespace + pid), self._a(), Iri(OWL + "ObjectProperty"))
        for namespace in (ns.wdt, ns.ps, ns.pq, ns.pr):
            self.add(Iri(namespace + pid), self._a(), Iri(OWL + direct_type))
        novalue = Iri(ns.wdno + pid)
        self.add(novalue, self._a(), Iri(OWL + "Class"))
        restriction = Blank(_md5("-".join(["owl:complementOf", pid])))
        self.add(novalue, Iri(OWL + "complementOf"), restriction)
        self.add(restriction, self._a(), Iri(OWL + "Restriction"))
        self.add(restriction, Iri(OWL + "onProperty"), Iri(ns.wdt + pid))
        self.add(restriction, Iri(OWL + "someValuesFrom"), Iri(OWL + "Thing"))

    def bridge(self, entity: Entity) -> None:
        """The RDFS bridge triples of a kernel entity (only P1 to P3 and Q1 to Q3 have any)."""
        if entity.id in BRIDGE_PROPERTIES and entity.kind == "property":
            triple = (Iri(self.ns.wdt + entity.id), Iri(RDFS + "subPropertyOf"), Iri(BRIDGE_PROPERTIES[entity.id]))
        elif entity.id in BRIDGE_CLASSES and entity.kind == "item":
            triple = (self._wd(entity.id), Iri(OWL + "equivalentClass"), Iri(BRIDGE_CLASSES[entity.id]))
        else:
            return
        self.add(*triple)
        self.out.bridge.add(triple)

    def crm(self, entity: Entity) -> None:
        """``wd:Q100 rdfs:subClassOf crmdig:...`` for each CRM class the class says itself (not the inherited ones: the
        bridge and the class tree carry those), and the alignment of an extension class up to the CIDOC CRM."""
        for curie in self.site.crm.get(entity.id, []):
            triple = (self._wd(entity.id), Iri(RDFS + "subClassOf"), Iri(crm.iri(curie)))
            self.add(*triple)
            self.out.crm.add(triple)
            for child, parent in crm.chain(curie):
                link = (Iri(child), Iri(RDFS + "subClassOf"), Iri(parent))
                self.out.triples.add(link)
                self.out.crm.add(link)

    def spell_out(self) -> None:
        """With an overlay: ``subclass of`` (P1) and ``instance of`` (P2) of the kernel written as plain ``rdfs:subClassOf``
        and ``rdf:type`` (S12). The bridge only says ``wdt:P1 rdfs:subPropertyOf rdfs:subClassOf``, which a reader without
        inference (the N4O profile measures anchoring that way) does not see. Edges to Q1 to Q3 are left out (they are
        the kernel, not classes of the domain) and so are the kernel items themselves."""
        if not self.site.crm or not self.site.has_kernel():
            return
        kernel = {"Q1", "Q2", "Q3"}
        for entity in self.site.entities.values():
            if entity.id in kernel or not entity.id.startswith("Q"):
                continue
            for statement in entity.statements:
                snak = statement.mainsnak
                target = snak.entity_id
                if snak.property not in ("P1", "P2") or not target or target in kernel or not target.startswith("Q"):
                    continue
                predicate = Iri(RDFS + "subClassOf") if snak.property == "P1" else self._a()
                triple = (self._wd(entity.id), predicate, self._wd(target))
                self.out.triples.add(triple)
                self.out.crm.add(triple)

    def align_dcat(self) -> None:
        """The DCAT classes this export uses, tied to the CRM by the package table ``data/dcat-crm.csv`` (S12)."""
        used = {o.value for _s, p, o in self.out.triples if isinstance(o, Iri) and isinstance(p, Iri)
                and p.value == RDF + "type" and o.value.startswith(DCAT)}
        table = crm.read_dcat_table()
        for child, parent in crm.dcat_alignment(used, table):
            link = (Iri(child), Iri(RDFS + "subClassOf"), Iri(parent))
            self.out.triples.add(link)
            self.out.crm.add(link)
        left = sorted(u[len(DCAT):] for u in used if not table.get(u[len(DCAT):], ([], "none"))[0])
        if left:
            self.out.notes.append(f"DCAT classes without a CRM class (data/dcat-crm.csv): {', '.join(left)}")

    # ---- DCAT

    def _dcat(self, name: str) -> Iri:
        return Iri(DCAT + name)

    def _dct(self, name: str) -> Iri:
        return Iri(DCTERMS + name)

    def _distribution(self, dataset: Iri, key: str, title: str, kind: str, url: str, size: int | None,
                      access_only: bool = False) -> None:
        """One ``dcat:Distribution`` of ``dataset``; ``kind`` is json, ttl or html."""
        assert self.catalog is not None
        media, file_type = {
            "json": ("application/json", "JSON"), "ttl": ("text/turtle", "RDF_TURTLE"), "html": ("text/html", "HTML"),
        }[kind]
        node = Iri(self.ns.dist + key)
        self.add(dataset, self._dcat("distribution"), node)
        self.add(node, self._a(), self._dcat("Distribution"))
        self.add(node, self._dct("title"), Lit(title, lang="en"))
        self.add(node, self._dcat("mediaType"), Iri(MEDIA_TYPE + media))
        self.add(node, self._dct("format"), Iri(FILE_TYPE + file_type))
        self.add(node, self._dcat("accessURL" if access_only else "downloadURL"), iri(url))
        if size is not None:
            self.add(node, self._dcat("byteSize"), Lit(str(size), XSD + "nonNegativeInteger"))
        if self.catalog.license_url:
            self.add(node, self._dct("license"), iri(self.catalog.license_url))
        self.out.distributions += 1

    def _dataset(self, entity: Entity) -> None:
        """The DCAT view of ``data:Q1``: one dataset per entity record, with the files that exist as distributions."""
        info = self.catalog
        assert info is not None
        ns = self.ns
        dataset = Iri(ns.dataset(entity.id))
        parent = Iri(ns.cat + ("items" if entity.kind == "item" else "properties"))
        self.add(dataset, self._a(), self._dcat("Dataset"))
        self.add(dataset, self._dct("identifier"), Lit(entity.id))
        self.add(dataset, self._dct("isPartOf"), parent)
        self.add(dataset, self._dct("subject"), self._wd(entity.id))
        for code, text in entity.labels.items():
            tag = bcp47(code)
            if _LANG.match(tag):
                self.add(dataset, self._dct("title"), Lit(text, lang=tag))
        for code, text in entity.descriptions.items():
            tag = bcp47(code)
            if _LANG.match(tag):
                self.add(dataset, self._dct("description"), Lit(text, lang=tag))
        if entity.modified:
            self.add(dataset, self._dct("modified"), Lit(entity.modified, XSD + "dateTime"))
        if info.license_url:
            self.add(dataset, self._dct("license"), iri(info.license_url))
        if not info.pages_url:
            return
        pages = info.pages_url.rstrip("/") + "/"
        self.add(dataset, self._dcat("landingPage"), iri(f"{pages}{entity.id}.html"))
        if entity.id in info.json_sizes:
            self._distribution(dataset, f"{entity.id}-json", f"{entity.id}, as archived from the Wikibase API", "json",
                               f"{pages}json/{entity.id}.json", info.json_sizes[entity.id])
        self._distribution(dataset, f"{entity.id}-ttl", f"{entity.id}, RDF in the Wikibase data model", "ttl",
                           f"{pages}ttl/{entity.id}.ttl", None)
        self._distribution(dataset, f"{entity.id}-html", f"{entity.id}, page", "html", f"{pages}{entity.id}.html", None,
                           access_only=True)

    def catalogue(self) -> None:
        """The catalogues: the Wikibase as a whole, its items, its properties, and the two files that are not entities."""
        info = self.catalog
        assert info is not None
        ns = self.ns
        root = Iri(ns.cat.rstrip("/"))
        kinds = (("items", "Items", self.site.items), ("properties", "Properties", self.site.properties))
        self.add(root, self._a(), self._dcat("Catalog"))
        self.add(root, self._dct("title"), Lit(info.title))
        if info.description:
            self.add(root, self._dct("description"), Lit(info.description))
        if info.license_url:
            self.add(root, self._dct("license"), iri(info.license_url))
        if info.modified:
            self.add(root, self._dct("modified"), Lit(info.modified, XSD + "dateTime"))
        if info.pages_url and ns.base.rstrip("/") == info.pages_url.rstrip("/"):
            # the URIs are this site's own (a copy that must stand without its source): the landing page is the site,
            # the source Wikibase is only named as the source
            self.add(root, self._dcat("landingPage"), iri(info.pages_url))
            if info.source_url:
                self.add(root, self._dct("source"), iri(info.source_url))
        elif info.source_url:
            self.add(root, self._dcat("landingPage"), iri(info.source_url))
        self.add(root, self._dct("conformsTo"), iri(WIKIBASE_ONTOLOGY))
        for key, title, entities in kinds:
            if not entities:
                continue
            part = Iri(ns.cat + key)
            self.add(root, self._dct("hasPart"), part)
            self.add(part, self._a(), self._dcat("Catalog"))
            self.add(part, self._dct("title"), Lit(f"{title} of {info.title}", lang="en"))
            self.add(part, self._dct("isPartOf"), root)
            if info.license_url:
                self.add(part, self._dct("license"), iri(info.license_url))
            for entity in entities:
                self.add(part, self._dcat("dataset"), Iri(ns.dataset(entity.id)))
        if not info.pages_url:
            return
        pages = info.pages_url.rstrip("/") + "/"
        for key, title, kind_file, size in (
                ("export", "Complete RDF export", info.export_file, None),
                ("wikibase-ontology", "The Wikibase system ontology", info.ontology_file, info.ontology_bytes)):
            if not kind_file:
                continue
            dataset = Iri(ns.cat + key)
            self.add(root, self._dcat("dataset"), dataset)
            self.add(dataset, self._a(), self._dcat("Dataset"))
            self.add(dataset, self._dct("title"), Lit(title, lang="en"))
            self.add(dataset, self._dct("isPartOf"), root)
            if key == "wikibase-ontology":
                self.add(dataset, self._dct("license"), iri("https://creativecommons.org/publicdomain/zero/1.0/"))
                self.add(dataset, self._dct("source"), iri(WIKIBASE_ONTOLOGY))
            elif info.license_url:
                self.add(dataset, self._dct("license"), iri(info.license_url))
            self._distribution(dataset, key, title, "ttl", pages + kind_file, size)

    def entity(self, entity: Entity) -> None:
        ns = self.ns
        subject = self._wd(entity.id)
        self.owner = self.out.by_entity.setdefault(entity.id, set())
        self.out.entities += 1
        self.add(subject, self._a(), self._wb("Item" if entity.kind == "item" else "Property"))
        identifiers = sum(1 for s in entity.statements if self._datatype_of(s.mainsnak) == "external-id")
        self.add(subject, self._wb("statements"), Lit(str(len(entity.statements)), XSD + "integer"))
        self.add(subject, self._wb("identifiers"), Lit(str(identifiers), XSD + "integer"))
        self.terms(entity)
        self.statements(entity)
        if entity.kind == "property":
            self.property_definition(entity)
        if self.kernel:
            self.bridge(entity)
        if entity.id in self.site.crm:
            self.crm(entity)
        document = Iri(ns.dataset(entity.id))
        self.add(document, self._a(), Iri(SCHEMA + "Dataset"))
        self.add(document, Iri(SCHEMA + "about"), subject)
        if self.license_url:
            self.add(document, Iri(CC + "license"), iri(self.license_url))
        if entity.lastrevid is not None:
            self.add(document, Iri(SCHEMA + "version"), Lit(str(entity.lastrevid), XSD + "integer"))
        if entity.modified:
            self.add(document, Iri(SCHEMA + "dateModified"), Lit(entity.modified, XSD + "dateTime"))
        if self.catalog is not None:
            self._dataset(entity)
        self.owner = None


def build(site: Site, ns: Namespaces, license_url: str | None = None, catalog: CatalogInfo | None = None) -> Rdf:
    """Every loaded entity as triples (and, with ``catalog``, their DCAT description).

    ``Rdf.triples`` is the whole export, ``Rdf.by_entity`` the triples of each entity's own file. Problems
    (values that cannot be written) are sorted messages in ``problems``."""
    builder = _Builder(site, ns, license_url, catalog)
    for entity in sorted(site.entities.values(), key=lambda e: id_sort_key(e.id)):
        builder.entity(entity)
    for source, target in sorted(site.redirects.items(), key=lambda kv: id_sort_key(kv[0])):   # merged ids (S7e), as Wikibase writes a redirect
        builder.owner = builder.out.by_entity.setdefault(target, set())
        builder.add(builder._wd(source), Iri(OWL + "sameAs"), builder._wd(target))
    builder.owner = None
    if catalog is not None:
        builder.catalogue()
        if not catalog.pages_url:
            builder.out.notes.append("no pages_url in site.yaml: the datasets have no distributions (a distribution needs a download URL)")
    builder.spell_out()
    if catalog is not None:
        builder.align_dcat()
    if builder.out.bridge:
        builder.out.notes.append(f"the kernel is part of the site: {len(builder.out.bridge)} RDFS bridge triples written (own section in the Turtle file)")
    if builder.out.crm:
        classes = sum(1 for c in site.crm if site.crm[c])
        what = (f"{classes} class(es) anchored by data/crm.csv; {len(builder.out.crm)} triples written for them, the class tree, the types and the DCAT classes"
                if site.crm else f"no data/crm.csv; {len(builder.out.crm)} triples tie the DCAT classes of the export to the CRM")
        builder.out.notes.append(f"CIDOC CRM: {what} (own section in the Turtle file)")
    if builder.out.federated:
        builder.out.notes.append(f"{builder.out.federated} value(s) of Wikidata properties (wd:P...) are linked on the pages, not exported")
    problems = set(builder.problems)
    for prop, count in sorted(builder.out.skipped.items()):
        problems.add(f"rdf: {prop} has the datatype {builder.skipped_types[prop]}, which is not exported ({count} value(s) left out)")
    builder.out.problems = sorted(problems)
    return builder.out


# --------------------------------------------------------------------------- serialisation


def _natural(text: str) -> tuple[list[Any], str]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)], text


def _term_key(term: Term) -> tuple[list[Any], str]:
    return _natural(nt(term))


def ntriples(triples: Iterable[Triple]) -> str:
    """Sorted N-Triples (one triple per line): the stable intermediate form."""
    lines = sorted(f"{nt(s)} {nt(p)} {nt(o)} ." for s, p, o in triples)
    return "\n".join(lines) + ("\n" if lines else "")


_LOCAL = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?$")     # a dot is allowed inside a local name, not at its end


class _Abbreviator:
    def __init__(self, prefixes: dict[str, str]) -> None:
        self.prefixes = prefixes
        self.by_length = sorted(prefixes.items(), key=lambda item: (-len(item[1]), item[0]))

    def iri(self, value: str, predicate: bool = False) -> str:
        if predicate and value == RDF + "type":     # "a" is only valid as a predicate; as an object it is rdf:type
            return "a"
        for prefix, namespace in self.by_length:
            if value.startswith(namespace):
                local = value[len(namespace):]
                if _LOCAL.match(local):
                    return f"{prefix}:{local}"
        return f"<{value}>"

    def term(self, term: Term, predicate: bool = False) -> str:
        if isinstance(term, Iri):
            return self.iri(term.value, predicate)
        if isinstance(term, Blank):
            return f"_:{term.label}"
        text = f'"{escape_literal(term.lexical)}"'
        if term.lang:
            return f"{text}@{term.lang}"
        if term.datatype:
            return f"{text}^^{self.iri(term.datatype)}"
        return text


def _subject_group(term: Term, ns: Namespaces) -> float:
    if isinstance(term, Blank):
        return 9
    value = term.value  # type: ignore[union-attr]
    if value.startswith(ns.cat.rstrip("/")):
        return -1
    if value.startswith(ns.dist):
        return 0.5      # type: ignore[return-value]
    for index, (namespace, _name) in enumerate((
            (ns.data, "data"), (ns.wds, "wds"), (ns.wdref, "wdref"), (ns.wdv, "wdv"))):
        if value.startswith(namespace):
            return {0: 0, 1: 3, 2: 4, 3: 5}[index]
    if value.startswith(ns.wd):
        return 1 if value[len(ns.wd):].startswith("Q") else 2
    if value.startswith(ns.wdno):
        return 7
    if value.startswith(ns.p):
        return 6
    return 8


def to_turtle(triples: Iterable[Triple], ns: Namespaces, header: str = "",
              section: "tuple[str, Iterable[Triple]] | list[tuple[str, Iterable[Triple]]] | None" = None) -> str:
    """The triples as Turtle: prefixes, then one block per subject, everything in a fixed order.

    ``section`` is a title and a set of triples that are written last, under a comment of their own, instead of
    among the others (the RDFS bridge), or a list of such pairs (the bridge, then the CRM anchoring); empty ones are
    left out. The graph is the same either way. The prefixes of the CRM families are declared when a triple uses one."""
    sections = [] if section is None else [section] if isinstance(section, tuple) else list(section)
    sections = [(title, set(members)) for title, members in sections if members]
    prefixes = dict(ns.prefixes())
    iris = {term.value for _, members in sections for triple in members for term in triple if isinstance(term, Iri)}
    for prefix, namespace in crm.FAMILIES.items():
        if any(value.startswith(namespace) for value in iris):
            prefixes[prefix] = namespace
    abbreviate = _Abbreviator(prefixes)
    marked = set().union(*(members for _, members in sections)) if sections else set()
    main = [t for t in triples if t not in marked]

    lines: list[str] = []
    for line in header.splitlines():
        lines.append(f"# {line}" if line else "#")
    if lines:
        lines.append("")
    for prefix, namespace in sorted(prefixes.items()):
        lines.append(f"@prefix {prefix}: <{namespace}> .")
    lines.extend(_blocks(main, ns, abbreviate))
    for title, members in sections:
        lines.append("")
        lines.extend(f"# {line}" if line else "#" for line in title.splitlines())
        lines.extend(_blocks(members, ns, abbreviate))
    return "\n".join(lines) + "\n"


def _blocks(triples: Iterable[Triple], ns: Namespaces, abbreviate: "_Abbreviator") -> list[str]:
    by_subject: dict[Term, dict[Term, list[Term]]] = {}
    for s, p, o in triples:
        by_subject.setdefault(s, {}).setdefault(p, []).append(o)

    def subject_key(term: Term) -> tuple[float, tuple[list[Any], str]]:
        return _subject_group(term, ns), _term_key(term)

    def object_key(term: Term) -> tuple[int, tuple[list[Any], str]]:
        return (0 if isinstance(term, Iri) else 1 if isinstance(term, Blank) else 2), _term_key(term)

    lines: list[str] = []
    for subject in sorted(by_subject, key=subject_key):
        predicates = by_subject[subject]
        order = sorted(predicates, key=lambda p: (0 if isinstance(p, Iri) and p.value == RDF + "type" else 1, _term_key(p)))
        lines.append("")
        lines.append(abbreviate.term(subject))
        for index, predicate in enumerate(order):
            objects = sorted(predicates[predicate], key=object_key)
            rendered = [abbreviate.term(o) for o in objects]
            end = " ." if index == len(order) - 1 else " ;"
            head = f"    {abbreviate.term(predicate, True)} "
            if len(rendered) == 1:
                lines.append(head + rendered[0] + end)
            else:
                pad = " " * 8
                lines.append(head + rendered[0] + ",")
                for item in rendered[1:-1]:
                    lines.append(pad + item + ",")
                lines.append(pad + rendered[-1] + end)
    return lines
