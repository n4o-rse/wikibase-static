"""The internal model of a Wikibase site: entities, statements, snaks (S2).

Plain dataclasses, no behaviour beyond small accessors. Everything the renderer
(S3), the search index (S5) and the RDF export (S6) read comes from here, so
none of them has to know what Wikibase JSON looks like.

Values are kept as Wikibase delivers them (``Snak.value`` is the ``value`` part
of the ``datavalue``, ``Snak.vtype`` its ``type``); the model does not convert
or "repair" them, because a page should show what the source says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Datatypes the site can show (PRIMER.md, A4 "Datentypen"), and the datavalue
# type each one must carry. Anything else is reported as a warning and kept.
VALUE_TYPE: dict[str, str] = {
    "wikibase-item": "wikibase-entityid",
    "wikibase-property": "wikibase-entityid",
    "string": "string",
    "external-id": "string",
    "url": "string",
    "commonsMedia": "string",
    "time": "time",
    "quantity": "quantity",
    "monolingualtext": "monolingualtext",
    "globe-coordinate": "globecoordinate",
}
SUPPORTED_DATATYPES = frozenset(VALUE_TYPE)

# Keys a value of each datavalue type must have, so that a template can rely on them.
VALUE_KEYS: dict[str, tuple[str, ...]] = {
    "wikibase-entityid": ("id",),
    "string": (),
    "time": ("time", "precision"),
    "quantity": ("amount",),
    "monolingualtext": ("text", "language"),
    "globecoordinate": ("latitude", "longitude"),
}

ENTITY_ID = re.compile(r"^([QP])([1-9][0-9]*)$")


def id_sort_key(entity_id: str) -> tuple[int, int, str]:
    """Items before properties, then numeric order (Q2 before Q10)."""
    match = ENTITY_ID.match(entity_id)
    if not match:
        return (2, 0, entity_id)
    return (0 if match.group(1) == "Q" else 1, int(match.group(2)), entity_id)


@dataclass(frozen=True)
class Snak:
    """One property-value pair: the main value, a qualifier or a reference part."""

    property: str
    snaktype: str                 # "value", "somevalue" or "novalue"
    datatype: str | None = None
    vtype: str | None = None      # the datavalue type, e.g. "string", "globecoordinate"
    value: Any = None

    @property
    def entity_id(self) -> str | None:
        """The Q-/P-id this snak points to, if it is an entity value."""
        if self.vtype == "wikibase-entityid" and isinstance(self.value, dict):
            found = self.value.get("id")
            return found if isinstance(found, str) else None
        return None


@dataclass
class Statement:
    id: str | None
    mainsnak: Snak
    rank: str = "normal"                                           # "preferred", "normal", "deprecated"
    qualifiers: list[Snak] = field(default_factory=list)
    references: list[list[Snak]] = field(default_factory=list)     # each reference is a group of snaks


@dataclass
class Entity:
    id: str
    kind: str                                                      # "item" or "property"
    datatype: str | None = None                                    # properties only
    labels: dict[str, str] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, list[str]] = field(default_factory=dict)
    statements: list[Statement] = field(default_factory=list)
    sitelinks: dict[str, dict[str, Any]] = field(default_factory=dict)
    lastrevid: int | None = None
    modified: str | None = None
    source: str = "raw"                                            # "raw" (harvest) or "derived" (CSV)
    path: str = ""                                                 # file it was read from, for messages

    def snaks(self) -> list[Snak]:
        """Every snak of the entity: main values, qualifiers and reference parts."""
        found: list[Snak] = []
        for statement in self.statements:
            found.append(statement.mainsnak)
            found.extend(statement.qualifiers)
            for reference in statement.references:
                found.extend(reference)
        return found

    def referenced_ids(self) -> set[str]:
        """Entities this one points to: property ids of all snaks and entity values."""
        ids: set[str] = set()
        for snak in self.snaks():
            ids.add(snak.property)
            target = snak.entity_id
            if target:
                ids.add(target)
        return ids
