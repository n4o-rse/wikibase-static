"""From the four CSV tables to Wikibase JSON, with the kernel mixed in and the model checked (S7a).

``build()`` never raises on bad rows: a row it cannot use becomes a problem message ``file:line: ...`` (printed as
``WARN`` by ``step_from_csv``) and is skipped. Problems are plain strings, sorted, so a run is deterministic.

The kernel (PRIMER.md, A4 "Kern"), shipped with the package in ``data/kernel/``::

    Q1 Class   Q2 Property   Q3 Instance (root of the class tree)
    P1 subclass of   P2 instance of   P3 subproperty of
    P4 Wikidata equivalent   P5 formatter URL   P6 reference URL   P7 retrieved   P8 stated in
    P9 domain   P10 range

IDs 1 to 99 are reserved for it. A CSV of the site may add translations, descriptions and aliases to a kernel
entity; anything else on a kernel id is a problem and ignored. Mixing the kernel in also types every ``class`` as
``instance of`` Q1 and every ``property`` as ``instance of`` Q2 (the rows are not in the CSV, they are made here).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wikibase_static import csvio
from wikibase_static.csvio import CsvError, Table
from wikibase_static.model import (
    ENTITY_ID, SUPPORTED_DATATYPES, federated_from_uri, federated_to_uri, id_sort_key, is_federated,
)

KERNEL_DIR = Path(__file__).resolve().parent / "data" / "kernel"
RESERVED = 100                      # ids below this number belong to the kernel
NAMESPACE = uuid.UUID("6f1c6a0e-3f0b-5b5e-9f8e-77a1d2c4b9a1")     # fixed, so statement ids are a function of the data

# What a complete kernel looks like: id -> (kind, datatype). The check "kernel incomplete or changed" uses it.
KERNEL: dict[str, tuple[str, str | None]] = {
    "Q1": ("class", None), "Q2": ("class", None), "Q3": ("class", None),
    "P1": ("property", "wikibase-item"), "P2": ("property", "wikibase-item"), "P3": ("property", "wikibase-property"),
    "P4": ("property", "external-id"), "P5": ("property", "string"), "P6": ("property", "url"),
    "P7": ("property", "time"), "P8": ("property", "wikibase-item"), "P9": ("property", "wikibase-item"),
    "P10": ("property", "wikibase-item"),
}
SUBCLASS, INSTANCE, DOMAIN, RANGE = "P1", "P2", "P9", "P10"
CLASS, PROPERTY, ROOT = "Q1", "Q2", "Q3"


@dataclass
class CsvSet:
    """The four tables of one folder."""

    entities: Table
    statements: Table
    qualifiers: Table
    references: Table
    folder: str = ""

    @property
    def tables(self) -> list[Table]:
        return [self.entities, self.statements, self.qualifiers, self.references]


def read_set(folder: Path, problems: list[str], shown: str | None = None) -> CsvSet:
    """Read ``entities.csv``, ``statements.csv``, ``qualifiers.csv`` and ``references.csv`` of ``folder`` (all optional)."""
    shown = shown if shown is not None else folder.name
    prefix = f"{shown}/" if shown else ""
    return CsvSet(
        entities=csvio.read_table(folder / "entities.csv", csvio.REQUIRED["entities.csv"], problems, f"{prefix}entities.csv"),
        statements=csvio.read_table(folder / "statements.csv", ["subject", "property", "value"], problems, f"{prefix}statements.csv"),
        qualifiers=csvio.read_table(folder / "qualifiers.csv", ["sid", "property", "value"], problems, f"{prefix}qualifiers.csv"),
        references=csvio.read_table(folder / "references.csv", ["sid", "property", "value"], problems, f"{prefix}references.csv"),
        folder=shown,
    )


def kernel_set() -> CsvSet:
    return read_set(KERNEL_DIR, [], "kernel")


# --------------------------------------------------------------------------- the working model


@dataclass
class Row:
    """One entity as the CSV states it."""

    id: str
    kind: str
    datatype: str | None
    origin: str
    labels: dict[str, str] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, list[str]] = field(default_factory=dict)
    where: str = ""
    statements: list["Claim"] = field(default_factory=list)


@dataclass
class Claim:
    sid: str
    prop: str
    value: str
    rank: str
    origin: str
    where: str
    snaktype: str = "value"
    datavalue: Any = None
    datatype: str | None = None
    qualifiers: list[tuple[str, str, Any, str | None, str]] = field(default_factory=list)       # prop, snaktype, datavalue, datatype, where
    references: dict[str, list[tuple[str, str, Any, str | None, str]]] = field(default_factory=dict)


@dataclass
class Built:
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)       # id -> Wikibase JSON
    problems: list[str] = field(default_factory=list)
    kinds: dict[str, str] = field(default_factory=dict)
    statements: int = 0
    kernel: bool = False


def _language_cells(row: dict[str, str], prefix: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for column, cell in row.items():
        head, _sep, code = column.partition("_")
        if head == prefix and code and cell.strip() != "":
            found[code] = cell
    return found


def _read_entities(table: Table, source: str, rows: dict[str, Row], problems: list[str], kernel_ids: set[str]) -> None:
    for index, raw in enumerate(table.rows):
        where = table.where(index)
        entity_id = raw.get("id", "").strip()
        match = ENTITY_ID.match(entity_id)
        if not match:
            problems.append(f"{where}: {entity_id!r} is not an item or property id (Q12, P3); row skipped")
            continue
        is_property = match.group(1) == "P"
        kind = raw.get("kind", "").strip() or ("property" if is_property else "item")
        datatype = raw.get("datatype", "").strip() or None
        if kind not in csvio.KINDS:
            problems.append(f"{where}: kind {kind!r} of {entity_id} is not one of class, property, item; row skipped")
            continue
        if (kind == "property") != is_property:
            problems.append(f"{where}: {entity_id} has kind {kind}, but a {'P' if is_property else 'Q'}-id is "
                            f"{'a property' if is_property else 'an item or class'}; row skipped")
            continue
        if is_property and datatype is None:
            problems.append(f"{where}: property {entity_id} has no datatype")
        elif datatype is not None and datatype not in SUPPORTED_DATATYPES:
            problems.append(f"{where}: {entity_id} has datatype {datatype}, which the site cannot show; row skipped")
            continue
        elif datatype is not None and not is_property:
            problems.append(f"{where}: {entity_id} is not a property, its datatype {datatype} is ignored")
            datatype = None
        aliases = {code: csvio.split_aliases(cell) for code, cell in _language_cells(raw, "aliases").items()}
        aliases = {code: values for code, values in aliases.items() if values}
        new = Row(id=entity_id, kind=kind, datatype=datatype, origin=raw.get("origin", "").strip(),
                  labels=_language_cells(raw, "label"), descriptions=_language_cells(raw, "description"),
                  aliases=aliases, where=where)
        if entity_id in rows:
            if entity_id in kernel_ids and source == "site":
                _extend_kernel(rows[entity_id], new, where, problems)
            else:
                problems.append(f"{where}: {entity_id} is already defined in {rows[entity_id].where}; row ignored")
            continue
        if source == "site" and int(match.group(2)) < RESERVED and kernel_ids:
            problems.append(f"{where}: {entity_id} lies in the range 1 to {RESERVED - 1}, which is reserved for the kernel")
        rows[entity_id] = new


def _extend_kernel(kernel: Row, new: Row, where: str, problems: list[str]) -> None:
    """A site row for a kernel id may add languages and aliases; every other difference is a problem."""
    if new.kind != kernel.kind or (new.datatype or None) != (kernel.datatype or None):
        problems.append(f"{where}: {kernel.id} is part of the kernel; its kind and datatype cannot be changed")
    for mine, theirs, name in ((kernel.labels, new.labels, "label"), (kernel.descriptions, new.descriptions, "description")):
        for code, text in theirs.items():
            if code not in mine:
                mine[code] = text
            elif mine[code] != text:
                problems.append(f"{where}: {kernel.id} is part of the kernel; its {name}_{code} cannot be changed")
    for code, values in new.aliases.items():
        present = kernel.aliases.setdefault(code, [])
        present += [v for v in values if v not in present]


def _datatype_for(prop: str, rows: dict[str, Row], where: str, problems: list[str]) -> tuple[bool, str | None]:
    """(usable, datatype) of a property id: a local property must exist, a Wikidata one has no datatype here."""
    if is_federated(prop):
        if prop[3] != "P":
            problems.append(f"{where}: {prop} is an item, not a property")
            return False, None
        return True, None
    if not ENTITY_ID.match(prop) or prop[0] != "P":
        problems.append(f"{where}: {prop!r} is not a property id (P3 or wd:P31)")
        return False, None
    row = rows.get(prop)
    if row is None or row.kind != "property":
        problems.append(f"{where}: unknown property {prop}; row skipped")
        return False, None
    return True, row.datatype


def _read_statements(site: CsvSet, kernel_ids: set[str], rows: dict[str, Row], base: str | None,
                     problems: list[str]) -> dict[str, Claim]:
    by_sid: dict[str, Claim] = {}
    for index, raw in enumerate(site.statements.rows):
        where = site.statements.where(index)
        subject, prop = raw.get("subject", "").strip(), raw.get("property", "").strip()
        text, sid = raw.get("value", ""), raw.get("sid", "").strip()
        rank = raw.get("rank", "").strip() or "normal"
        if subject not in rows:
            problems.append(f"{where}: unknown subject {subject!r}; row skipped")
            continue
        if subject in kernel_ids:
            problems.append(f"{where}: {subject} is part of the kernel; statements on it cannot be added; row ignored")
            continue
        if rank not in csvio.RANKS:
            problems.append(f"{where}: rank {rank!r} is not normal, preferred or deprecated; row skipped")
            continue
        usable, datatype = _datatype_for(prop, rows, where, problems)
        if not usable:
            continue
        try:
            snaktype, datavalue, datatype = csvio.parse_value(text, datatype, base)
        except CsvError as err:
            problems.append(f"{where}: {prop} {err}; row skipped")
            continue
        claim = Claim(sid=sid, prop=prop, value=text, rank=rank, origin=raw.get("origin", "").strip(), where=where,
                      snaktype=snaktype, datavalue=datavalue, datatype=datatype)
        if sid:
            if sid in by_sid:
                problems.append(f"{where}: sid {sid} is already used in {by_sid[sid].where}; row skipped")
                continue
            by_sid[sid] = claim
        rows[subject].statements.append(claim)
    return by_sid


def _snak_parts(raw: dict[str, str], where: str, rows: dict[str, Row], base: str | None, problems: list[str]
                ) -> tuple[str, str, Any, str | None, str] | None:
    prop, text = raw.get("property", "").strip(), raw.get("value", "")
    usable, datatype = _datatype_for(prop, rows, where, problems)
    if not usable:
        return None
    try:
        snaktype, datavalue, datatype = csvio.parse_value(text, datatype, base)
    except CsvError as err:
        problems.append(f"{where}: {prop} {err}; row skipped")
        return None
    return prop, snaktype, datavalue, datatype, where


def _read_snaks(site: CsvSet, by_sid: dict[str, Claim], rows: dict[str, Row], base: str | None, problems: list[str]) -> None:
    for index, raw in enumerate(site.qualifiers.rows):
        where = site.qualifiers.where(index)
        claim = by_sid.get(raw.get("sid", "").strip())
        if claim is None:
            problems.append(f"{where}: sid {raw.get('sid', '')!r} names no statement; row skipped")
            continue
        parts = _snak_parts(raw, where, rows, base, problems)
        if parts:
            claim.qualifiers.append(parts)
    for index, raw in enumerate(site.references.rows):
        where = site.references.where(index)
        claim = by_sid.get(raw.get("sid", "").strip())
        if claim is None:
            problems.append(f"{where}: sid {raw.get('sid', '')!r} names no statement; row skipped")
            continue
        parts = _snak_parts(raw, where, rows, base, problems)
        if parts:
            claim.references.setdefault(raw.get("group", "").strip() or "1", []).append(parts)


# --------------------------------------------------------------------------- validation


def _entity_id(datavalue: Any) -> str:
    """The id of an entity value; a Wikidata entity is ``wd:Q42`` here (the JSON carries its URI)."""
    found = datavalue["value"]["id"]
    return federated_from_uri(found) or found


def _targets(row: Row, prop: str) -> list[str]:
    return [_entity_id(c.datavalue) for c in row.statements
            if c.prop == prop and c.snaktype == "value" and c.datavalue and c.datavalue["type"] == "wikibase-entityid"]


def _validate_kernel(rows: dict[str, Row], problems: list[str]) -> None:
    for entity_id, (kind, datatype) in KERNEL.items():
        row = rows.get(entity_id)
        if row is None or row.kind != kind or row.datatype != datatype or not row.labels.get("en"):
            problems.append(f"kernel: {entity_id} is missing or changed (expected {kind}"
                            f"{', ' + datatype if datatype else ''} with an English label)")


def _validate_model(rows: dict[str, Row], problems: list[str]) -> None:
    """The rules that need the kernel: a class tree rooted at Q3, typed items, domain and range."""
    classes = {i for i, r in rows.items() if r.kind == "class"}

    def superclasses(start: str) -> set[str]:
        seen, todo = set(), [start]
        while todo:
            current = todo.pop()
            for parent in _targets(rows[current], SUBCLASS) if current in rows else []:
                if parent not in seen and not is_federated(parent):
                    seen.add(parent)
                    todo.append(parent)
        return seen

    for class_id in sorted(classes, key=id_sort_key):
        if class_id != ROOT and ROOT not in superclasses(class_id):
            problems.append(f"{rows[class_id].where}: class {class_id} has no path to {ROOT} (Instance) over {SUBCLASS} (subclass of)")
    for item_id in sorted((i for i, r in rows.items() if r.kind == "item" and r.origin != "wikidata-stub"), key=id_sort_key):
        parents = _targets(rows[item_id], INSTANCE)
        if not parents:
            problems.append(f"{rows[item_id].where}: item {item_id} is not an instance of a class ({INSTANCE})")
        elif not any(is_federated(p) or p in classes for p in parents):
            problems.append(f"{rows[item_id].where}: item {item_id} is an instance of {', '.join(parents)}, which is not a class")

    def instance_of(entity_id: str) -> set[str] | None:
        """Every class the entity belongs to over ``instance of`` and ``subclass of``; ``None`` when it has none."""
        direct = [p for p in _targets(rows[entity_id], INSTANCE) if not is_federated(p)] if entity_id in rows else []
        if not direct:
            return None
        found = set(direct)
        for parent in direct:
            found |= superclasses(parent)
        return found

    constraints: dict[str, dict[str, list[str]]] = {}
    for prop_id, row in rows.items():
        if row.kind == "property":
            domain = [t for t in _targets(row, DOMAIN) if not is_federated(t)]
            span = [t for t in _targets(row, RANGE) if not is_federated(t)]
            if domain or span:
                constraints[prop_id] = {"domain": domain, "range": span}
    for entity_id in sorted(rows, key=id_sort_key):
        row = rows[entity_id]
        for claim in row.statements:
            limit = constraints.get(claim.prop)
            if not limit:
                continue
            belongs = instance_of(entity_id)
            if limit["domain"] and belongs is not None and not set(limit["domain"]) & belongs:
                problems.append(f"{claim.where}: {entity_id} is not an instance of the domain {', '.join(limit['domain'])} of {claim.prop}")
            if limit["range"] and claim.snaktype == "value" and claim.datavalue["type"] == "wikibase-entityid":
                target = _entity_id(claim.datavalue)
                if is_federated(target) or target not in rows:
                    continue
                target_classes = instance_of(target)
                if target_classes is not None and not set(limit["range"]) & target_classes:
                    problems.append(f"{claim.where}: {target} is not an instance of the range {', '.join(limit['range'])} of {claim.prop}")


# --------------------------------------------------------------------------- JSON


def statement_id(subject: str, claim: Claim, occurrence: int) -> str:
    """A Wikibase-style statement id ``Q1$GUID``: the sid when it already is one, else a fixed function of the row."""
    match = csvio.STATEMENT_GUID.match(claim.sid) if claim.sid else None
    if match and match.group(1) == subject:
        return claim.sid
    key = f"{subject}|{claim.sid}" if claim.sid else f"{subject}|{claim.prop}|{claim.value}|{occurrence}"
    return f"{subject}${str(uuid.uuid5(NAMESPACE, key)).upper()}"


def _property_key(prop: str) -> str:
    return federated_to_uri(prop) if is_federated(prop) else prop


def _snak_json(prop: str, snaktype: str, datavalue: Any, datatype: str | None) -> dict[str, Any]:
    snak: dict[str, Any] = {"snaktype": snaktype, "property": _property_key(prop)}
    if datatype:
        snak["datatype"] = datatype
    if snaktype == "value":
        snak["datavalue"] = datavalue
    return snak


def _grouped(snaks: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for snak in snaks:
        grouped.setdefault(snak["property"], []).append(snak)
    return grouped, list(grouped)


def _entity_json(row: Row) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id, "type": "property" if row.kind == "property" else "item",
        "labels": {c: {"language": c, "value": v} for c, v in sorted(row.labels.items())},
        "descriptions": {c: {"language": c, "value": v} for c, v in sorted(row.descriptions.items())},
        "aliases": {c: [{"language": c, "value": v} for v in values] for c, values in sorted(row.aliases.items())},
    }
    if row.kind == "property":
        out["datatype"] = row.datatype          # properties have no sitelinks
    else:
        out["sitelinks"] = {}
    claims: dict[str, list[dict[str, Any]]] = {}
    seen: dict[tuple[str, str, str], int] = {}
    for claim in row.statements:
        key = (claim.prop, claim.value, claim.sid)
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        entry: dict[str, Any] = {
            "id": statement_id(row.id, claim, occurrence),
            "mainsnak": _snak_json(claim.prop, claim.snaktype, claim.datavalue, claim.datatype),
            "rank": claim.rank, "type": "statement",
        }
        if claim.qualifiers:
            entry["qualifiers"], entry["qualifiers-order"] = _grouped(
                [_snak_json(p, st, dv, dt) for p, st, dv, dt, _w in claim.qualifiers])
        if claim.references:
            entry["references"] = []
            for group in sorted(claim.references, key=lambda g: (int(g) if g.isdigit() else 10 ** 9, g)):
                snaks, order = _grouped([_snak_json(p, st, dv, dt) for p, st, dv, dt, _w in claim.references[group]])
                entry["references"].append({"snaks": snaks, "snaks-order": order})
        claims.setdefault(_property_key(claim.prop), []).append(entry)
    out["claims"] = claims
    return out


def _type_by_kind(rows: dict[str, Row]) -> None:
    """Mix in ``instance of`` Q1 for every class and ``instance of`` Q2 for every property (unless it is there)."""
    for row in rows.values():
        wanted = CLASS if row.kind == "class" else PROPERTY if row.kind == "property" else None
        if wanted and wanted not in _targets(row, INSTANCE):
            _, _, datavalue, datatype, _w = _snak_parts({"property": INSTANCE, "value": wanted}, row.where, rows, None, [])
            row.statements.insert(0, Claim(sid="", prop=INSTANCE, value=wanted, rank="normal", origin="kernel",
                                           where=row.where, snaktype="value", datavalue=datavalue, datatype=datatype))


def build(site: CsvSet, kernel: CsvSet | None, base: str | None = None) -> Built:
    """Wikibase JSON for every entity of ``site`` (and of the ``kernel`` when given), plus the problems found."""
    built = Built(kernel=kernel is not None)
    problems = built.problems
    rows: dict[str, Row] = {}
    kernel_ids: set[str] = set()
    if kernel is not None:
        _read_entities(kernel.entities, "kernel", rows, problems, set())
        kernel_ids = set(rows)
        kernel_claims = _read_statements(kernel, set(), rows, base, problems)
        _read_snaks(kernel, kernel_claims, rows, base, problems)
    _read_entities(site.entities, "site", rows, problems, kernel_ids)
    by_sid = _read_statements(site, kernel_ids, rows, base, problems)
    _read_snaks(site, by_sid, rows, base, problems)
    if kernel is not None:
        _validate_kernel(rows, problems)
        _type_by_kind(rows)
        _validate_model(rows, problems)
    for entity_id in sorted(rows, key=id_sort_key):
        built.entities[entity_id] = _entity_json(rows[entity_id])
        built.kinds[entity_id] = rows[entity_id].kind
        built.statements += len(rows[entity_id].statements)
    built.problems = sorted(set(problems))
    return built


def site_base() -> str | None:
    """The concept-URI base of the site (``rdf_base``, else ``source.url`` of ``site.yaml``), for local quantity units."""
    from wikibase_static import utils
    from wikibase_static.site_config import load_config

    cfg = load_config(utils.SITE_YAML)
    return cfg.rdf_base or cfg.source_url
