"""CIDOC CRM anchoring of the classes of a site (PRIMER.md, S11, A4 "CRM-Overlay").

A site may carry ``data/crm.csv`` next to its data::

    class,crm_class,note
    Q100,crmdig:D14,software is a D14 Software (a D1 Digital Object, an E73 Information Object)

``class`` is the id of a class of the site, ``crm_class`` a class of one of the allowed families in the form
``prefix:Name``. The raw data is never changed: the overlay is a table of its own. What a class does not say itself
it inherits over ``subclass of`` (P1) and ``instance of`` (P2) of the kernel, so one row at the root of a class tree
anchors the whole tree. That follows how the N4O profile reads CRM anchoring (``rdfs:subClassOf`` followed
transitively until a class of the CRM namespaces is reached).

The module is plain Python: no I/O except ``read_overlay``, no dependency outside the package.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# The allowed families (PRIMER.md, A4 "Erlaubte CRM-Familien"). The namespaces are those the N4O profile counts as CRM
# (``http://www.cidoc-crm.org/cidoc-crm/`` and everything under ``http://www.cidoc-crm.org/extensions/``).
FAMILIES: dict[str, str] = {
    "crm": "http://www.cidoc-crm.org/cidoc-crm/",
    "crmarchaeo": "http://www.cidoc-crm.org/extensions/crmarchaeo/",
    "crmdig": "http://www.cidoc-crm.org/extensions/crmdig/",
    "crmgeo": "http://www.cidoc-crm.org/extensions/crmgeo/",
    "crmsci": "http://www.cidoc-crm.org/extensions/crmsci/",
}

# Known classes with their label and their direct superclass, for the display and for the alignment triples that make a
# class of an extension reach ``crm:`` (without them a bundle would say ``wd:Q100 rdfs:subClassOf crmdig:D14`` and stop
# there). Only what the sites use so far; a class that is not listed is written without a superclass.
CLASSES: dict[str, tuple[str, str | None]] = {
    "crm:E1_CRM_Entity": ("CRM Entity", None),
    "crm:E31_Document": ("Document", "crm:E73_Information_Object"),
    "crm:E55_Type": ("Type", "crm:E28_Conceptual_Object"),
    "crm:E73_Information_Object": ("Information Object", "crm:E89_Propositional_Object"),
    "crm:E89_Propositional_Object": ("Propositional Object", "crm:E28_Conceptual_Object"),
    "crm:E28_Conceptual_Object": ("Conceptual Object", "crm:E71_Human-Made_Thing"),
    "crm:E71_Human-Made_Thing": ("Human-Made Thing", "crm:E70_Thing"),
    "crm:E70_Thing": ("Thing", "crm:E77_Persistent_Item"),
    "crm:E77_Persistent_Item": ("Persistent Item", "crm:E1_CRM_Entity"),
    "crm:E22_Human-Made_Object": ("Human-Made Object", "crm:E24_Physical_Human-Made_Thing"),
    "crm:E24_Physical_Human-Made_Thing": ("Physical Human-Made Thing", "crm:E18_Physical_Thing"),
    "crm:E18_Physical_Thing": ("Physical Thing", "crm:E72_Legal_Object"),
    "crm:E72_Legal_Object": ("Legal Object", "crm:E70_Thing"),
    "crm:E53_Place": ("Place", "crm:E1_CRM_Entity"),
    "crmdig:D1_Digital_Object": ("Digital Object", "crm:E73_Information_Object"),
    "crmdig:D14_Software": ("Software", "crmdig:D1_Digital_Object"),
}

# The short forms people write (``crmdig:D14``) and the full names of the class: ``E73`` is ``E73_Information_Object``.
_CODE = re.compile(r"^(?P<prefix>[a-z]+):(?P<name>[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9-]+)*)$")
_SHORT = re.compile(r"^[A-Za-z]+[0-9]+[a-z]?$")
ENTITY_ID = re.compile(r"^Q[1-9][0-9]*$")
COLUMNS = ["class", "crm_class", "note"]
OVERLAY_FILE = "data/crm.csv"


@dataclass(frozen=True)
class Anchor:
    """A CRM class and where it came from: ``via`` is the class of the site that carries the row (its own id when
    the entity says it itself)."""
    curie: str
    via: str


def full_name(curie: str) -> str:
    """``crmdig:D14`` -> ``crmdig:D14_Software`` when the class is known by its short code; unchanged otherwise."""
    prefix, _, name = curie.partition(":")
    if "_" in name:
        return curie
    for known in CLASSES:
        known_prefix, _, known_name = known.partition(":")
        if known_prefix == prefix and known_name.split("_", 1)[0] == name:
            return known
    return curie


def iri(curie: str) -> str:
    prefix, _, name = full_name(curie).partition(":")
    return FAMILIES[prefix] + name


def label(curie: str) -> str:
    """``Software`` for ``crmdig:D14``; the code itself for a class that is not in ``CLASSES``."""
    known = CLASSES.get(full_name(curie))
    code = curie.partition(":")[2].split("_", 1)[0]
    return f"{code} {known[0]}" if known else curie


def chain(curie: str) -> list[tuple[str, str]]:
    """(class, direct superclass) pairs from a class of an extension up to its first class of the CIDOC CRM itself, in IRI
    form: ``crmdig:D14`` gives D14 -> D1 and D1 -> E73, and stops there, because ``crm:`` defines the rest. A class of
    ``crm:`` gives nothing."""
    pairs, seen, current = [], set(), full_name(curie)
    while current in CLASSES and CLASSES[current][1] and not current.startswith("crm:") and current not in seen:
        seen.add(current)
        parent = CLASSES[current][1]
        pairs.append((iri(current), iri(parent)))
        current = parent
    return pairs


def read_overlay(path: Path, known_ids: set[str] | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """The overlay (class id -> CRM classes in the order of the file) and the problems with it, as sorted messages.

    A row with an unknown family, a malformed class or a class the site does not hold is reported and skipped; a
    row twice is reported once. ``known_ids`` is the set of entity ids of the site (``None`` skips that check)."""
    overlay: dict[str, list[str]] = {}
    problems: list[str] = []
    if not path.is_file():
        return overlay, problems
    shown = OVERLAY_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        return overlay, [f"{shown}: not readable ({str(err).splitlines()[0]})"]
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None or [c.strip() for c in reader.fieldnames][:2] != COLUMNS[:2]:
        return overlay, [f"{shown}: the first two columns must be {COLUMNS[0]} and {COLUMNS[1]}"]
    for number, row in enumerate(reader, start=2):
        class_id, curie = (row.get("class") or "").strip(), (row.get("crm_class") or "").strip()
        where = f"{shown}:{number}"
        if not class_id and not curie:
            continue
        if not ENTITY_ID.match(class_id):
            problems.append(f"{where}: {class_id!r} is not an entity id like Q100")
            continue
        match = _CODE.match(curie)
        if not match or match.group("prefix") not in FAMILIES:
            problems.append(f"{where}: {curie!r} is not a class of an allowed family ({', '.join(sorted(FAMILIES))}) in the form prefix:Name")
            continue
        if known_ids is not None and class_id not in known_ids:
            problems.append(f"{where}: {class_id} is not an entity of this site")
            continue
        curie = full_name(curie)
        if curie in overlay.setdefault(class_id, []):
            problems.append(f"{where}: {class_id} {curie} is listed twice")
        else:
            overlay[class_id].append(curie)
    return overlay, sorted(set(problems))


def ancestors(edges: dict[str, list[str]], start: str) -> list[str]:
    """The entity itself, then everything reachable over ``edges`` (breadth first, each once, in a fixed order)."""
    order, seen, queue = [start], {start}, [start]
    while queue:
        current = queue.pop(0)
        for parent in sorted(edges.get(current, [])):
            if parent not in seen:
                seen.add(parent)
                order.append(parent)
                queue.append(parent)
    return order


def anchors(overlay: dict[str, list[str]], edges: dict[str, list[str]], entity_id: str) -> list[Anchor]:
    """The CRM classes of an entity: its own rows first, then those of the classes above it, nearest first."""
    found: list[Anchor] = []
    seen: set[str] = set()
    for carrier in ancestors(edges, entity_id):
        for curie in overlay.get(carrier, []):
            if curie not in seen:
                seen.add(curie)
                found.append(Anchor(curie, carrier))
    return found
