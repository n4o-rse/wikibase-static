"""The same entities in a real Wikibase (S7g, ``counterpart`` in site.yaml).

A site made from CSV tables has its own numbers. When the same data were pushed into a real Wikibase (``wikibase-federation``,
``usecases/chublets``), that Wikibase gave the entities numbers of its own and wrote the pairs into ``idmap-<target>.csv``.
This module reads that table, so that every entity page can link to its counterpart and its RDF can say ``owl:sameAs``.

The table needs the columns ``source_id`` and ``target_id``; other columns (``label_en``) are ignored.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

ID = re.compile(r"^[PQ][1-9][0-9]*$")


@dataclass
class Counterpart:
    name: str                                  # shown on the pages, e.g. chublets-wikibase.de
    uri: str                                   # concept URI with {id}, used for owl:sameAs
    url: str                                   # address of the page with {id}, used for the link
    map_file: str                              # path of the table, relative to the repository
    ids: dict[str, str] = field(default_factory=dict)     # id of this site -> id in the Wikibase
    problems: list[str] = field(default_factory=list)

    def target_uri(self, entity_id: str) -> str | None:
        target = self.ids.get(entity_id)
        return self.uri.replace("{id}", target) if target else None

    def target_url(self, entity_id: str) -> str | None:
        target = self.ids.get(entity_id)
        return self.url.replace("{id}", target) if target else None

    def target_id(self, entity_id: str) -> str | None:
        return self.ids.get(entity_id)


def load_table(path: Path) -> tuple[dict[str, str], list[str]]:
    """``(site id -> Wikibase id, problems)``; a bad row is a problem and skipped, nothing is guessed."""
    problems: list[str] = []
    ids: dict[str, str] = {}
    if not path.is_file():
        return ids, [f"counterpart: {path.name} not found; no links to the other Wikibase"]
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"source_id", "target_id"} <= set(reader.fieldnames):
            return ids, [f"counterpart: {path.name} needs the columns source_id and target_id; ignored"]
        for number, row in enumerate(reader, start=2):
            source, target = (row.get("source_id") or "").strip(), (row.get("target_id") or "").strip()
            if not ID.match(source) or not ID.match(target) or source[0] != target[0]:
                problems.append(f"counterpart: {path.name} line {number}: {source!r} -> {target!r} is not a pair of ids of the same kind; skipped")
            elif source in ids:
                problems.append(f"counterpart: {path.name} line {number}: {source} appears twice; the first row counts")
            else:
                ids[source] = target
    return ids, problems


def load(counterpart: Counterpart | None, root: Path, known: set[str]) -> Counterpart | None:
    """Read the table of ``counterpart`` (from site.yaml); ``known`` are the ids of the site, rows for other ids are a problem."""
    if counterpart is None:
        return None
    ids, problems = load_table(root / counterpart.map_file)
    counterpart.problems.extend(problems)
    counterpart.ids = {s: t for s, t in ids.items() if s in known}
    unknown = sorted(set(ids) - known)
    if unknown:
        counterpart.problems.append(
            f"counterpart: {len(unknown)} row(s) of {Path(counterpart.map_file).name} name ids that this site does not have "
            f"(first: {', '.join(unknown[:5])}); skipped")
    return counterpart
