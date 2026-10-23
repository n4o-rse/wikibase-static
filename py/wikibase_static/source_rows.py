"""The rows of the CSV tables that an entity page is built from (S7f, the tab "Source rows").

``SourceRows.load(folder)`` reads ``entities.csv``, ``statements.csv``, ``qualifiers.csv``, ``references.csv`` and ``merges.csv`` of a CSV
folder, and ``blocks(entity_id)`` gives, per file, the lines that belong to one entity: its row in ``entities.csv``, its rows in
``statements.csv``, the rows of ``qualifiers.csv`` and ``references.csv`` of those statements, and the lines of ``merges.csv`` that name it.

The text is the text of the file: a row is taken from the file line for line (a cell that runs over several lines stays whole), so
what a page shows is what ``git diff`` shows, whatever the quoting of the file. The header line comes first. The kernel (Q1 to Q3,
P1 to P10) is shown from the kernel tables of the package, under the name ``kernel/<file>``; those rows cannot be edited.
Rows that ``from-csv`` makes itself (the typing of a class as ``instance of`` Q1, of a property as Q2) are not in any file and not shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wikibase_static import csvbuild, csvio

FILES = ("entities.csv", "statements.csv", "qualifiers.csv", "references.csv", "merges.csv")


@dataclass
class Block:
    file: str                       # name as shown ("statements.csv", "kernel/statements.csv")
    name: str                       # plain file name, for the link into the repository
    editable: bool
    rows: int
    text: str                       # header line and the rows, LF line ends, no trailing newline


class _Source:
    """One folder: its tables, the raw lines of each file and an index from entity to rows."""

    def __init__(self, folder: Path, shown: str, editable: bool) -> None:
        problems: list[str] = []
        self.shown, self.editable = shown, editable
        self.set = csvbuild.read_set(folder, problems, "")
        self.tables = {"entities.csv": self.set.entities, "statements.csv": self.set.statements,
                       "qualifiers.csv": self.set.qualifiers, "references.csv": self.set.references}
        if self.set.merges is not None:
            self.tables["merges.csv"] = self.set.merges
        self.lines: dict[str, list[str]] = {}
        for name in self.tables:
            path = folder / name
            if path.is_file():
                text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
                self.lines[name] = text.split("\n")
        self.by_id: dict[str, list[int]] = {}
        self.by_subject: dict[str, list[int]] = {}
        self.by_sid: dict[str, dict[str, list[int]]] = {"qualifiers.csv": {}, "references.csv": {}}
        self.by_merge: dict[str, list[int]] = {}
        for i, row in enumerate(self.set.entities.rows):
            self.by_id.setdefault(row.get("id", "").strip(), []).append(i)
        for i, row in enumerate(self.set.statements.rows):
            self.by_subject.setdefault(row.get("subject", "").strip(), []).append(i)
        for name in self.by_sid:
            for i, row in enumerate(self.tables[name].rows):
                self.by_sid[name].setdefault(row.get("sid", "").strip(), []).append(i)
        if self.set.merges is not None:
            for i, row in enumerate(self.set.merges.rows):
                for column in ("from", "to"):
                    self.by_merge.setdefault(row.get(column, "").strip(), []).append(i)

    def text_of(self, name: str, indexes: list[int]) -> str:
        """The header line and the file lines of the rows ``indexes`` (each row from its first line to the line before the next row)."""
        table, lines = self.tables[name], self.lines[name]
        header_line = next((n for n, line in enumerate(lines) if line.strip()), 0)
        out = [lines[header_line]]
        for i in indexes:
            start = table.lines[i] - 1
            end = table.lines[i + 1] - 1 if i + 1 < len(table.lines) else len(lines)
            chunk = lines[start:end]
            while chunk and not chunk[-1].strip():
                chunk.pop()
            out += chunk
        return "\n".join(out)

    def blocks(self, entity_id: str) -> list[Block]:
        found: list[Block] = []
        statements = self.by_subject.get(entity_id, [])
        sids = [self.set.statements.rows[i].get("sid", "").strip() for i in statements]
        picks = {"entities.csv": self.by_id.get(entity_id, []), "statements.csv": statements,
                 "qualifiers.csv": sorted(i for sid in sids if sid for i in self.by_sid["qualifiers.csv"].get(sid, [])),
                 "references.csv": sorted(i for sid in sids if sid for i in self.by_sid["references.csv"].get(sid, [])),
                 "merges.csv": self.by_merge.get(entity_id, [])}
        for name in FILES:
            indexes = picks.get(name, [])
            if indexes and name in self.lines:
                shown = name if self.editable else f"{self.shown}/{name}"
                found.append(Block(shown, name, self.editable, len(indexes), self.text_of(name, indexes)))
        return found


class SourceRows:
    def __init__(self, site: _Source, kernel: _Source) -> None:
        self._site, self._kernel = site, kernel

    @classmethod
    def load(cls, folder: Path) -> "SourceRows | None":
        """The rows of ``folder``; ``None`` when it has no ``entities.csv`` (a site that was harvested, not made from CSV)."""
        if not (folder / "entities.csv").is_file():
            return None
        return cls(_Source(folder, "csv", True), _Source(csvbuild.KERNEL_DIR, "kernel", False))

    def blocks(self, entity_id: str) -> list[Block]:
        return self._site.blocks(entity_id) + self._kernel.blocks(entity_id)
