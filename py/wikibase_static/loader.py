"""Read data/raw/ and data/derived/ into the model and check it (S2).

``load_site()`` never raises on bad data: a file it cannot use becomes a
problem message (printed as ``WARN`` by ``step_load``) and is skipped, a
statement it cannot make sense of is kept as far as possible and reported.
Problems are plain strings, sorted, so a run is deterministic.

Both layouts hold one JSON file per entity under ``entities/``::

    data/raw/entities/Q1.json        harvested (S4)
    data/derived/entities/Q1.json    made from CSV (S7)

A file holds one entity object as ``wbgetentities`` delivers it. Files in the
``Special:EntityData`` form (``{"entities": {"Q1": {...}}}``) are read as well.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wikibase_static import crm, utils
from wikibase_static.model import (
    ENTITY_ID, SUPPORTED_DATATYPES, VALUE_KEYS, VALUE_TYPE, Entity, Snak, Statement, federated_from_uri,
    id_sort_key, is_federated,
)

MAX_REFERRERS = 5   # how many referring entities a "missing" message names


# What identifies the kernel (``Site.has_kernel``): id, kind, datatype; and the statements (subject, property, value).
KERNEL_CORE_ENTITIES = (("Q1", "item", None), ("Q2", "item", None), ("Q3", "item", None),
                        ("P1", "property", "wikibase-item"), ("P2", "property", "wikibase-item"),
                        ("P3", "property", "wikibase-property"))
KERNEL_CORE_STATEMENTS = (("Q1", "P1", "Q3"), ("Q2", "P1", "Q3"),
                          ("P1", "P10", "Q1"), ("P2", "P10", "Q1"), ("P3", "P10", "Q2"))


@dataclass
class Site:
    """Everything loaded from disk, plus what was wrong with it."""

    entities: dict[str, Entity] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    files: int = 0
    source_url: str | None = None          # from data/raw/manifest.json, if present
    latest_modified: str | None = None
    crm: dict[str, list[str]] = field(default_factory=dict)   # data/crm.csv: class id -> CRM classes (S11)

    @property
    def items(self) -> list[Entity]:
        return [e for e in self.entities.values() if e.kind == "item"]

    @property
    def properties(self) -> list[Entity]:
        return [e for e in self.entities.values() if e.kind == "property"]

    def statement_count(self) -> int:
        return sum(len(e.statements) for e in self.entities.values())

    def datatype_counts(self) -> dict[str, int]:
        """Main values by datatype (qualifiers and references are not counted)."""
        counts: dict[str, int] = {}
        for entity in self.entities.values():
            for statement in entity.statements:
                key = statement.mainsnak.datatype or "unknown"
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def has_kernel(self) -> bool:
        """True when the kernel of ``from-csv`` is part of the site (PRIMER.md, A4 "Kern" and "RDFS-Brücke").

        The loaded JSON carries no marker, so the kernel is recognised by what it says: Q1, Q2 and Q3 are items,
        P1, P2 and P3 are properties of the datatypes the kernel gives them, and the class tree and the ranges of
        the three are as the kernel states them. A harvested Wikibase that merely uses the same numbers does not
        match, and neither does a CSV site built with ``--no-kernel``."""
        for entity_id, kind, datatype in KERNEL_CORE_ENTITIES:
            entity = self.entities.get(entity_id)
            if entity is None or entity.kind != kind or (entity.datatype or None) != datatype:
                return False
        for subject, prop, target in KERNEL_CORE_STATEMENTS:
            if not any(s.mainsnak.property == prop and s.mainsnak.entity_id == target
                       for s in self.entities[subject].statements):
                return False
        return True

    def crm_edges(self) -> dict[str, list[str]]:
        """Entity -> the classes it says it belongs to or descends from (kernel P1 and P2); empty without the kernel,
        where those two properties have no fixed meaning. The CRM rows are inherited over these edges."""
        edges: dict[str, list[str]] = {}
        if not self.has_kernel():
            return edges
        for entity in self.entities.values():
            for statement in entity.statements:
                if statement.mainsnak.property in ("P1", "P2") and statement.mainsnak.entity_id:
                    edges.setdefault(entity.id, []).append(statement.mainsnak.entity_id)
        return edges

    def crm_anchors(self, entity_id: str, edges: dict[str, list[str]] | None = None) -> list["crm.Anchor"]:
        """The CIDOC CRM classes of an entity from ``data/crm.csv``: its own, then those of the classes above it."""
        return crm.anchors(self.crm, self.crm_edges() if edges is None else edges, entity_id) if self.crm else []

    def crm_classes(self) -> list[str]:
        """The items that are classes (kernel): the target of a ``subclass of`` or ``instance of`` statement, or with a
        ``subclass of`` statement of their own, except Q1 to Q3 which are the kernel."""
        if not self.has_kernel():
            return []
        found = set()
        for entity in self.entities.values():
            for statement in entity.statements:
                prop, target = statement.mainsnak.property, statement.mainsnak.entity_id
                if prop == "P1" and entity.kind == "item":
                    found.add(entity.id)
                if prop in ("P1", "P2") and target in self.entities and self.entities[target].kind == "item":
                    found.add(target)
        return sorted(found - {"Q1", "Q2", "Q3"}, key=id_sort_key)

    def labeller(self, languages: list[str]) -> "LabelResolver":
        return LabelResolver(self, languages)


class LabelResolver:
    """Label of an entity in the first language that has one; the id when none does.

    Labels come only from the entities loaded here, never from the network
    (PRIMER.md, A3). An id the site does not hold, for instance a Wikidata item
    that a statement points to, is shown as itself: nothing is invented.
    """

    def __init__(self, site: Site, languages: list[str]) -> None:
        self._site = site
        self._languages = list(languages)
        self._cache: dict[str, str] = {}

    def label(self, entity_id: str) -> str:
        if entity_id not in self._cache:
            self._cache[entity_id] = self._resolve(entity_id)
        return self._cache[entity_id]

    def has_label(self, entity_id: str) -> bool:
        return self.label(entity_id) != entity_id

    def _resolve(self, entity_id: str) -> str:
        entity = self._site.entities.get(entity_id)
        if entity is None or not entity.labels:
            return entity_id
        for language in self._languages:
            if entity.labels.get(language):
                return entity.labels[language]
        return entity.labels[sorted(entity.labels)[0]]   # any language beats a bare id, deterministically


# --------------------------------------------------------------------------- parsing


def _text_map(raw: Any, where: str, problems: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(raw, dict):
        if raw not in (None, [], ""):
            problems.append(f"{where}: labels or descriptions have an unexpected shape; ignored")
        return result
    for language, entry in raw.items():
        value = entry.get("value") if isinstance(entry, dict) else None
        if isinstance(value, str) and value:
            result[language] = value
    return result


def _alias_map(raw: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for language, entries in raw.items():
            values = [e.get("value") for e in entries if isinstance(e, dict) and isinstance(e.get("value"), str)]
            if values:
                result[language] = values
    return result


def _snak(raw: Any, where: str, problems: list[str]) -> Snak | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("property"), str):
        problems.append(f"{where}: a snak without a property; skipped")
        return None
    prop = federated_from_uri(raw["property"]) or raw["property"]     # a Wikidata property is kept as wd:P31
    snaktype = raw.get("snaktype", "value")
    datatype = raw.get("datatype")
    datavalue = raw.get("datavalue")
    vtype = value = None
    if snaktype == "value":
        if not isinstance(datavalue, dict) or "value" not in datavalue:
            problems.append(f"{where}: {prop} has snaktype value but no datavalue")
        else:
            vtype, value = datavalue.get("type"), datavalue["value"]
            if vtype == "wikibase-entityid" and isinstance(value, dict) and federated_from_uri(value.get("id")):
                value = {**value, "id": federated_from_uri(value["id"])}    # an entity of Wikidata, kept as wd:Q42
            expected = VALUE_TYPE.get(datatype or "")
            if expected and vtype != expected:
                problems.append(f"{where}: {prop} has datatype {datatype} but a {vtype} value (expected {expected})")
            elif vtype in VALUE_KEYS:
                if vtype == "string":
                    if not isinstance(value, str):
                        problems.append(f"{where}: {prop} has a string value that is not text")
                elif not isinstance(value, dict) or any(k not in value for k in VALUE_KEYS[vtype]):
                    problems.append(f"{where}: {prop} has a malformed {vtype} value")
    if datatype is not None and datatype not in SUPPORTED_DATATYPES:
        problems.append(f"{where}: {prop} has datatype {datatype}, which the site cannot show yet")
    return Snak(property=prop, snaktype=snaktype, datatype=datatype, vtype=vtype, value=value)


def _snak_groups(raw: Any, order: Any, where: str, problems: list[str]) -> list[Snak]:
    """Qualifiers or one reference: ``{P: [snak, ...]}`` in ``order`` (the *-order list) when given."""
    if not isinstance(raw, dict):
        return []
    keys = [p for p in (order or []) if p in raw] if isinstance(order, list) else []
    keys += sorted((p for p in raw if p not in keys), key=id_sort_key)
    snaks: list[Snak] = []
    for prop in keys:
        for entry in raw[prop] if isinstance(raw[prop], list) else []:
            snak = _snak(entry, where, problems)
            if snak:
                snaks.append(snak)
    return snaks


def _statements(raw: Any, where: str, problems: list[str]) -> list[Statement]:
    """Claims in numeric property order (the harvest stores keys sorted, so the source order is gone)."""
    statements: list[Statement] = []
    if not isinstance(raw, dict):
        return statements
    names = {key: (federated_from_uri(key) or key) for key in raw}
    for key in sorted(raw, key=lambda k: id_sort_key(names[k])):
        prop = names[key]
        for claim in raw[key] if isinstance(raw[key], list) else []:
            if not isinstance(claim, dict):
                problems.append(f"{where}: a statement of {prop} is not an object; skipped")
                continue
            main = _snak(claim.get("mainsnak"), where, problems)
            if main is None:
                continue
            if main.property != prop:
                problems.append(f"{where}: statement filed under {prop} has main property {main.property}")
            references = []
            for reference in claim.get("references", []) or []:
                if isinstance(reference, dict):
                    parts = _snak_groups(reference.get("snaks"), reference.get("snaks-order"), where, problems)
                    if parts:
                        references.append(parts)
            statements.append(Statement(
                id=claim.get("id"), mainsnak=main, rank=claim.get("rank", "normal"),
                qualifiers=_snak_groups(claim.get("qualifiers"), claim.get("qualifiers-order"), where, problems),
                references=references,
            ))
    return statements


def parse_entity(obj: Any, source: str, path: str, problems: list[str]) -> Entity | None:
    """One entity object into the model, or ``None`` when it cannot be used at all."""
    if not isinstance(obj, dict) or not isinstance(obj.get("id"), str):
        problems.append(f"{path}: no entity id; skipped")
        return None
    entity_id = obj["id"]
    match = ENTITY_ID.match(entity_id)
    if not match:
        problems.append(f"{path}: {entity_id} is not an item or property id (lexemes and media are out of scope); skipped")
        return None
    kind = "item" if match.group(1) == "Q" else "property"
    if obj.get("type") not in (None, kind):
        problems.append(f"{path}: {entity_id} has type {obj.get('type')}, expected {kind}")
    where = f"{path}"
    datatype = obj.get("datatype") if kind == "property" else None
    if kind == "property" and datatype is None:
        problems.append(f"{where}: property {entity_id} has no datatype")
    elif datatype is not None and datatype not in SUPPORTED_DATATYPES:
        problems.append(f"{where}: property {entity_id} has datatype {datatype}, which the site cannot show yet")
    sitelinks = obj.get("sitelinks")
    return Entity(
        id=entity_id, kind=kind, datatype=datatype,
        labels=_text_map(obj.get("labels"), where, problems),
        descriptions=_text_map(obj.get("descriptions"), where, problems),
        aliases=_alias_map(obj.get("aliases")),
        statements=_statements(obj.get("claims"), where, problems),
        sitelinks=sitelinks if isinstance(sitelinks, dict) else {},
        lastrevid=obj.get("lastrevid") if isinstance(obj.get("lastrevid"), int) else None,
        modified=obj.get("modified") if isinstance(obj.get("modified"), str) else None,
        source=source, path=path,
    )


def _read_objects(path: Path, problems: list[str], shown: str) -> list[Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        problems.append(f"{shown}: not readable as JSON ({str(err).splitlines()[0]}); skipped")
        return []
    if isinstance(data, dict) and isinstance(data.get("entities"), dict):
        return [e for e in data["entities"].values()]
    return [data]


# --------------------------------------------------------------------------- loading


def load_site(raw: Path | None = None, derived: Path | None = None) -> Site:
    """Load every entity under ``raw/entities`` and ``derived/entities`` and check the whole."""
    raw = raw if raw is not None else utils.DATA_RAW
    derived = derived if derived is not None else utils.DATA_DERIVED
    site = Site()
    problems = site.problems

    for source, base in (("raw", raw), ("derived", derived)):
        folder = base / "entities"
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            site.files += 1
            shown = f"data/{source}/entities/{path.name}"
            for obj in _read_objects(path, problems, shown):
                entity = parse_entity(obj, source, shown, problems)
                if entity is None:
                    continue
                if entity.id != path.stem:
                    problems.append(f"{shown}: holds {entity.id}, but the file is named {path.stem}")
                if entity.id in site.entities:
                    problems.append(f"{shown}: {entity.id} is already loaded from {site.entities[entity.id].path}; ignored")
                    continue
                site.entities[entity.id] = entity

    site.entities = dict(sorted(site.entities.items(), key=lambda kv: id_sort_key(kv[0])))
    site.crm, crm_problems = crm.read_overlay(raw.parent / "crm.csv", set(site.entities))
    problems.extend(crm_problems)
    _check_manifest(site, raw)
    _check_references(site)
    site.problems = sorted(set(site.problems))
    return site


def _check_manifest(site: Site, raw: Path) -> None:
    path = raw / "manifest.json"
    if not path.is_file():
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        rows = manifest.get("entities", {})
    except (OSError, ValueError, AttributeError) as err:
        site.problems.append(f"data/raw/manifest.json: not readable ({str(err).splitlines()[0]})")
        return
    site.source_url = (manifest.get("source") or {}).get("url")
    site.latest_modified = manifest.get("latest_modified")
    loaded_raw = {e.id for e in site.entities.values() if e.source == "raw"}
    for entity_id in sorted(set(rows) - loaded_raw, key=id_sort_key):
        site.problems.append(f"data/raw/manifest.json: lists {entity_id}, but it could not be loaded")
    for entity_id in sorted(loaded_raw - set(rows), key=id_sort_key):
        site.problems.append(f"data/raw/entities/{entity_id}.json: not listed in the manifest")


def _check_references(site: Site) -> None:
    """Report every Q-/P-id that is pointed to but has no data, once, with who points to it."""
    referrers: dict[str, set[str]] = {}
    for entity in site.entities.values():
        for target in entity.referenced_ids():
            if target not in site.entities and not is_federated(target):     # wd:Q42 is only linked (A4)
                referrers.setdefault(target, set()).add(entity.id)
    for target in sorted(referrers, key=id_sort_key):
        who = sorted(referrers[target], key=id_sort_key)
        named = ", ".join(who[:MAX_REFERRERS]) + (f" and {len(who) - MAX_REFERRERS} more" if len(who) > MAX_REFERRERS else "")
        site.problems.append(f"{target} is referenced by {named} but has no data")
