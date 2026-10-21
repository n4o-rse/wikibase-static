"""CSV tables and the value codec of the CSV format (S7a).

The module is called ``csvio`` and not ``csv`` on purpose: a step started directly
(``python py/wikibase_static/step_from_csv.py``) has its own folder on ``sys.path``, and a
``csv.py`` there would hide the standard library's ``csv`` from every module that imports it.

Four tables describe a Wikibase (PRIMER.md, A4 "CSV, Quelle der Wahrheit")::

    entities.csv     id, kind, datatype, origin, label_<lang>, description_<lang>, aliases_<lang>
    statements.csv   sid, subject, property, value, rank, origin
    qualifiers.csv   sid, property, value
    references.csv   sid, group, property, value

The property decides how ``value`` is read, as in Wikibase. The syntax (A4 "CSV, Wertsyntax"):

    item, property        Q12  P3  or  wd:Q42  wd:P31 (an entity of Wikidata, only linked)
    string, url, ...      the text; a leading backslash makes what follows literal (``\\?``, ``\\-``)
    coordinate            lat,lon  or  lat,lon,precision  or  lat,lon,precision,globe-id (degrees)
    time                  2021  2021-06  2021-06-04  -0500  or  +2021-06-04T00:00:00Z/11
    quantity              12  or  12 Q5  or  -3.5 wd:Q11573  or  12 <unit URL>
    monolingual text      de:Text
    ?                     unknown value        -   no value

Files are written canonically (UTF-8 without BOM, LF, fixed column order, rows by id, quotes only where
needed), so that running a step twice leaves ``git status`` clean and ``csv-fmt`` has a well-defined result.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wikibase_static.model import (
    ENTITY_ID, WIKIDATA_ENTITY, Snak, federated_from_uri, federated_to_uri, id_sort_key, is_federated,
)

ENTITY_COLUMNS = ["id", "kind", "datatype", "origin"]
STATEMENT_COLUMNS = ["sid", "subject", "property", "value", "rank", "origin"]
QUALIFIER_COLUMNS = ["sid", "property", "value"]
REFERENCE_COLUMNS = ["sid", "group", "property", "value"]
TABLES = {
    "entities.csv": ENTITY_COLUMNS,
    "statements.csv": STATEMENT_COLUMNS,
    "qualifiers.csv": QUALIFIER_COLUMNS,
    "references.csv": REFERENCE_COLUMNS,
}
REQUIRED = {"entities.csv": ["id"], "statements.csv": ["subject", "property", "value"],
            "qualifiers.csv": ["sid", "property", "value"], "references.csv": ["sid", "property", "value"]}
KINDS = ("class", "property", "item")
RANKS = ("normal", "preferred", "deprecated")

DEFAULT_PRECISION = 1e-06            # coordinate precision in degrees when the CSV gives none (about 0.1 m)
EARTH = WIKIDATA_ENTITY + "Q2"
GREGORIAN = WIKIDATA_ENTITY + "Q1985727"
LANGUAGE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
STATEMENT_GUID = re.compile(r"^([QP][1-9][0-9]*)\$[A-Za-z0-9-]+$")


class CsvError(ValueError):
    """A value or row that cannot be read; the message says what is wrong (the caller adds ``file:line``)."""


# --------------------------------------------------------------------------- escapes


def escape_text(text: str) -> str:
    """Text as a CSV value: a literal that looks like ``?``, ``-`` or starts with a backslash gets a backslash."""
    if text in ("?", "-") or text.startswith("\\"):
        return "\\" + text
    return text


def unescape_text(text: str) -> str:
    return text[1:] if text.startswith("\\") else text


def split_aliases(text: str) -> list[str]:
    """``a|b\\|c`` -> ``["a", "b|c"]``; a backslash escapes the next character."""
    if text == "":
        return []
    parts, current, i = [], [], 0
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text):
            current.append(text[i + 1])
            i += 2
            continue
        if char == "|":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    parts.append("".join(current))
    return [p for p in parts if p != ""]


def join_aliases(values: list[str]) -> str:
    return "|".join(v.replace("\\", "\\\\").replace("|", "\\|") for v in values)


# --------------------------------------------------------------------------- values -> Wikibase JSON


def _entity_value(text: str, expect: str) -> dict[str, Any]:
    """``Q12`` / ``P3`` / ``wd:Q42`` as the ``wikibase-entityid`` value Wikibase JSON carries."""
    if is_federated(text):
        entity_id = federated_to_uri(text)
        kind = "item" if text[3] == "Q" else "property"
        return {"entity-type": kind, "id": entity_id}
    match = ENTITY_ID.match(text)
    if not match:
        raise CsvError(f"{text!r} is not an item or property id (Q12, P3, wd:Q42)")
    kind = "item" if match.group(1) == "Q" else "property"
    if expect == "wikibase-item" and kind != "item":
        raise CsvError(f"{text} is a property id, but the property takes items")
    if expect == "wikibase-property" and kind != "property":
        raise CsvError(f"{text} is an item id, but the property takes properties")
    return {"entity-type": kind, "id": text, "numeric-id": int(match.group(2))}


def parse_time(text: str) -> dict[str, Any]:
    """``2021``, ``2021-06``, ``2021-06-04``, ``-0500`` or ``+2021-06-04T00:00:00Z/11`` as a Wikibase time value."""
    full = re.match(r"^([+-])(\d{1,12})-(\d\d)-(\d\d)T00:00:00Z/(\d{1,2})$", text)
    if full:
        sign, year, month, day, precision = full.groups()
        precision_value = int(precision)
        if not 0 <= precision_value <= 14:
            raise CsvError(f"time precision {precision} is outside 0 to 14")
        return _time_value(sign, int(year), int(month), int(day), precision_value)
    short = re.match(r"^(-?)(\d{1,12})(?:-(\d\d)(?:-(\d\d))?)?$", text)
    if not short:
        raise CsvError(f"{text!r} is not a date (2021, 2021-06, 2021-06-04, -0500 or +2021-06-04T00:00:00Z/11)")
    minus, year, month, day = short.groups()
    precision = 9 if month is None else 10 if day is None else 11
    return _time_value("-" if minus else "+", int(year), int(month or 0), int(day or 0), precision)


def _time_value(sign: str, year: int, month: int, day: int, precision: int) -> dict[str, Any]:
    if month > 12 or day > 31:
        raise CsvError(f"month {month} or day {day} is out of range")
    if precision >= 10 and month == 0:
        raise CsvError("a month is needed for this precision")
    if precision >= 11 and day == 0:
        raise CsvError("a day is needed for this precision")
    return {"time": f"{sign}{year:04d}-{month:02d}-{day:02d}T00:00:00Z", "timezone": 0, "before": 0, "after": 0,
            "precision": precision, "calendarmodel": GREGORIAN}


def format_time(value: dict[str, Any]) -> str:
    """The CSV form of a time value; the full ``+...Z/precision`` form when the short one would lose something."""
    time_text = str(value.get("time", ""))
    precision = value.get("precision")
    match = re.match(r"^([+-])(\d{1,12})-(\d\d)-(\d\d)T00:00:00Z$", time_text)
    if match and precision in (9, 10, 11):
        sign, year, month, day = match.groups()
        candidate = f"{'-' if sign == '-' else ''}{int(year):04d}"
        if precision >= 10:
            candidate += f"-{month}"
        if precision == 11:
            candidate += f"-{day}"
        try:
            back = parse_time(candidate)
        except CsvError:
            back = None
        if back is not None and back["time"] == time_text and back["precision"] == precision \
                and all(value.get(key, default) == default for key, default in
                        (("timezone", 0), ("before", 0), ("after", 0), ("calendarmodel", GREGORIAN))):
            return candidate
    return f"{time_text}/{precision}"


def parse_quantity(text: str, base: str | None) -> dict[str, Any]:
    """``12``, ``12 Q5``, ``12 wd:Q11573`` or ``12 <unit URL>``; ``base`` is the concept URI base for local units."""
    parts = text.split(None, 1)
    if not parts:
        raise CsvError("an empty quantity")
    if not re.match(r"^[+-]?\d+(\.\d+)?$", parts[0]):
        raise CsvError(f"{parts[0]!r} is not a plain decimal number (12, -3.5)")
    amount_text = parts[0] if parts[0][0] in "+-" else "+" + parts[0]
    unit = "1"
    if len(parts) == 2:
        unit_text = parts[1].strip()
        if is_federated(unit_text):
            unit = federated_to_uri(unit_text)
        elif ENTITY_ID.match(unit_text):
            if not base:
                raise CsvError(f"unit {unit_text} is local, but the site has no rdf_base or source.url to build its URI from")
            unit = f"{base.rstrip('/')}/entity/{unit_text}"
        elif re.match(r"^https?://\S+$", unit_text):
            unit = unit_text
        else:
            raise CsvError(f"{unit_text!r} is not a unit (Q5, wd:Q11573 or a URL)")
    return {"amount": amount_text, "unit": unit}


def format_quantity(value: dict[str, Any], base: str | None) -> str:
    amount = str(value.get("amount", "0")).lstrip("+")
    unit = str(value.get("unit", "1"))
    if unit == "1":
        return amount
    short = federated_from_uri(unit)
    if short:
        return f"{amount} {short}"
    if base and unit.startswith(base.rstrip("/") + "/entity/") and ENTITY_ID.match(unit.rsplit("/", 1)[-1]):
        return f"{amount} {unit.rsplit('/', 1)[-1]}"
    return f"{amount} {unit}"


def parse_coordinate(text: str) -> dict[str, Any]:
    parts = [p.strip() for p in text.split(",")]
    if not 2 <= len(parts) <= 4:
        raise CsvError(f"{text!r} is not a coordinate (lat,lon or lat,lon,precision or lat,lon,precision,globe)")
    try:
        latitude, longitude = float(parts[0]), float(parts[1])
        precision = float(parts[2]) if len(parts) >= 3 and parts[2] != "" else DEFAULT_PRECISION
    except ValueError:
        raise CsvError(f"{text!r} holds a number that cannot be read") from None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise CsvError(f"latitude {latitude} or longitude {longitude} is out of range")
    if precision <= 0:
        raise CsvError(f"precision {precision} must be positive")
    globe = EARTH
    if len(parts) == 4 and parts[3] != "":
        globe = federated_to_uri(parts[3]) if is_federated(parts[3]) else parts[3]
    return {"latitude": latitude, "longitude": longitude, "altitude": None, "precision": precision, "globe": globe}


def format_coordinate(value: dict[str, Any]) -> str:
    out = f"{_float(value['latitude'])},{_float(value['longitude'])}"
    precision, globe = value.get("precision"), value.get("globe", EARTH)
    if globe != EARTH:
        short = federated_from_uri(str(globe))
        return f"{out},{_float(precision) if precision is not None else ''},{short or globe}"
    if precision is not None and float(precision) != DEFAULT_PRECISION:
        out += f",{_float(precision)}"
    return out


def _float(number: Any) -> str:
    """The shortest text that reads back as the same float; whole numbers without a trailing ``.0``."""
    as_float = float(number)
    return str(int(as_float)) if as_float == int(as_float) and abs(as_float) < 1e15 else repr(as_float)


def parse_value(text: str, datatype: str | None, base: str | None = None) -> tuple[str, Any, str | None]:
    """A CSV value as ``(snaktype, datavalue, datatype)``; ``datavalue`` is ``None`` unless the snak has a value.

    ``datatype`` is the Wikibase datatype of the property. A Wikidata property (``wd:P31``) has no datatype here:
    the caller passes ``None`` and the datatype is read from the shape of the value (an id gives an item or a
    property, a URL gives ``url``, anything else a string)."""
    if text == "?":
        return "somevalue", None, datatype
    if text == "-":
        return "novalue", None, datatype
    if datatype is None:
        datatype = _guess_datatype(text)
    if datatype in ("wikibase-item", "wikibase-property"):
        return "value", {"type": "wikibase-entityid", "value": _entity_value(text, datatype)}, datatype
    if datatype in ("string", "external-id", "url", "commonsMedia"):
        return "value", {"type": "string", "value": unescape_text(text)}, datatype
    if datatype == "time":
        return "value", {"type": "time", "value": parse_time(text)}, datatype
    if datatype == "quantity":
        return "value", {"type": "quantity", "value": parse_quantity(text, base)}, datatype
    if datatype == "monolingualtext":
        language, separator, body = text.partition(":")
        if not separator or not LANGUAGE.match(language) or body == "":
            raise CsvError(f"{text!r} is not monolingual text (de:Text)")
        return "value", {"type": "monolingualtext", "value": {"language": language, "text": body}}, datatype
    if datatype == "globe-coordinate":
        return "value", {"type": "globecoordinate", "value": parse_coordinate(text)}, datatype
    raise CsvError(f"the datatype {datatype} cannot be read from CSV")


def _guess_datatype(text: str) -> str:
    if is_federated(text) or ENTITY_ID.match(text):
        return "wikibase-item" if text.split(":")[-1][0] == "Q" else "wikibase-property"
    if re.match(r"^https?://\S+$", text):
        return "url"
    return "string"


def format_snak(snak: Snak, base: str | None = None) -> str:
    """The CSV value of a snak (the inverse of ``parse_value``)."""
    if snak.snaktype == "somevalue":
        return "?"
    if snak.snaktype == "novalue":
        return "-"
    value, kind = snak.value, snak.vtype
    if kind == "wikibase-entityid" and isinstance(value, dict):
        found = str(value.get("id", ""))                   # the loader keeps a Wikidata entity as wd:Q42; a URI is accepted too
        return federated_from_uri(found) or found
    if kind == "string" and isinstance(value, str):
        return escape_text(value)
    if kind == "time" and isinstance(value, dict):
        return format_time(value)
    if kind == "quantity" and isinstance(value, dict):
        return format_quantity(value, base)
    if kind == "monolingualtext" and isinstance(value, dict):
        return f"{value.get('language')}:{value.get('text')}"
    if kind == "globecoordinate" and isinstance(value, dict):
        return format_coordinate(value)
    raise CsvError(f"{snak.property} has a {kind} value that has no CSV form")


def lossy_parts(snak: Snak) -> list[str]:
    """What ``format_snak`` cannot keep of a snak (said once per entity by ``to-csv``)."""
    lost: list[str] = []
    value = snak.value
    if snak.vtype == "globecoordinate" and isinstance(value, dict) and value.get("altitude") not in (None, 0):
        lost.append("altitude")
    if snak.vtype == "quantity" and isinstance(value, dict) and (value.get("upperBound") or value.get("lowerBound")):
        lost.append("quantity bounds")
    if snak.vtype == "time" and isinstance(value, dict):
        if value.get("timezone", 0) != 0 or value.get("before", 0) != 0 or value.get("after", 0) != 0:
            lost.append("time timezone/before/after")
        if value.get("calendarmodel", GREGORIAN) != GREGORIAN:
            lost.append("time calendar model")
    return lost


# --------------------------------------------------------------------------- tables


@dataclass
class Table:
    """Rows of one CSV file, each a dict, with the file's 1-based line number kept for messages."""

    name: str
    columns: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)

    def where(self, index: int) -> str:
        return f"{self.name}:{self.lines[index]}"


def read_table(path: Path, required: list[str], problems: list[str], shown: str | None = None) -> Table:
    """Read a CSV file; a missing file is an empty table, a missing column a problem."""
    name = shown or path.name
    table = Table(name=name, columns=list(required))
    if not path.is_file():
        return table
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as err:
        problems.append(f"{name}: not readable as UTF-8 text ({str(err).splitlines()[0]}); skipped")
        return table
    reader = csv.reader(io.StringIO(text, newline=""))
    header: list[str] | None = None
    while True:
        line = reader.line_num + 1          # the line the row starts on (a quoted cell may run over several)
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as err:
            problems.append(f"{name}:{line}: {err}; file skipped from here")
            break
        if header is None:
            header = [h.strip() for h in row]
            table.columns = header
            missing = [c for c in required if c not in header]
            if missing:
                problems.append(f"{name}:{line}: missing column(s) {', '.join(missing)}; file skipped")
                return Table(name=name, columns=list(required))
            continue
        if not any(cell.strip() for cell in row):
            continue
        if len(row) > len(header):
            problems.append(f"{name}:{line}: {len(row)} cells for {len(header)} columns; the extra cells are ignored")
        values = {col: (row[i] if i < len(row) else "") for i, col in enumerate(header)}
        table.rows.append(values)
        table.lines.append(line)
    return table


def render_table(columns: list[str], rows: list[dict[str, str]]) -> str:
    """Canonical CSV text: LF, quotes only where a cell needs them, one trailing newline."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(col, "") for col in columns])
    return out.getvalue()


# --------------------------------------------------------------------------- canonical form


def language_order(codes: set[str]) -> list[str]:
    """``en`` first, then ``de``, then the rest alphabetically: the column order of the language columns."""
    first = [c for c in ("en", "de") if c in codes]
    return first + sorted(c for c in codes if c not in ("en", "de"))


def entity_columns(rows: list[dict[str, str]], extra: list[str] | None = None) -> list[str]:
    """Fixed columns, then ``label_*``, ``description_*`` and ``aliases_*`` each in ``language_order``."""
    languages: dict[str, set[str]] = {"label": set(), "description": set(), "aliases": set()}
    for column in list(extra or []) + [c for row in rows for c in row]:
        prefix, _sep, code = column.partition("_")
        if prefix in languages and code:
            languages[prefix].add(code)
    columns = list(ENTITY_COLUMNS)
    for prefix in ("label", "description", "aliases"):
        columns += [f"{prefix}_{code}" for code in language_order(languages[prefix])]
    return columns


def canonical_rows(name: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Rows in canonical order. ``entities.csv`` by id (Q before P, numeric); ``statements.csv`` by subject and
    property, stable within a property (the order of the values is meaningful); qualifier and reference rows
    follow the order of their statements, stable within a statement."""
    if name == "entities.csv":
        return sorted(rows, key=lambda r: id_sort_key(r.get("id", "")))
    if name == "statements.csv":
        return sorted(rows, key=lambda r: (id_sort_key(r.get("subject", "")), id_sort_key(_prop(r.get("property", "")))))
    raise ValueError(name)


def canonical_by_sid(rows: list[dict[str, str]], statements: list[dict[str, str]]) -> list[dict[str, str]]:
    """Qualifier or reference rows in the order of ``statements`` (canonical), unknown sids last; stable."""
    position: dict[str, int] = {}
    for index, row in enumerate(statements):
        sid = row.get("sid", "")
        if sid and sid not in position:
            position[sid] = index
    return sorted(rows, key=lambda r: position.get(r.get("sid", ""), len(position) + 1))


def _prop(text: str) -> str:
    """Sort key part of a property id: a Wikidata property sorts after the local ones."""
    return text if not is_federated(text) else "~" + text


IDENT_COLUMNS = ("id", "kind", "datatype", "origin", "rank", "subject", "property", "sid", "group")


def _clean(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Identifier-like cells lose stray blanks; value and text cells are never touched."""
    return [{k: (v.strip() if k in IDENT_COLUMNS else v) for k, v in row.items()} for row in rows]


def canonical_texts(tables: dict[str, Table]) -> dict[str, str]:
    """The canonical text of every table given (by file name). Unknown columns are kept, after the known ones."""
    out: dict[str, str] = {}
    entities = tables.get("entities.csv")
    if entities is not None:
        rows = _clean(entities.rows)
        columns = entity_columns(rows, entities.columns)
        columns += [c for c in entities.columns if c not in columns]
        out["entities.csv"] = render_table(columns, canonical_rows("entities.csv", rows))
    statements = tables.get("statements.csv")
    ordered: list[dict[str, str]] = []
    if statements is not None:
        ordered = canonical_rows("statements.csv", _clean(statements.rows))
        columns = STATEMENT_COLUMNS + [c for c in statements.columns if c not in STATEMENT_COLUMNS]
        out["statements.csv"] = render_table(columns, ordered)
    for name, base in (("qualifiers.csv", QUALIFIER_COLUMNS), ("references.csv", REFERENCE_COLUMNS)):
        table = tables.get(name)
        if table is not None:
            columns = base + [c for c in table.columns if c not in base]
            out[name] = render_table(columns, canonical_by_sid(_clean(table.rows), ordered))
    return out
