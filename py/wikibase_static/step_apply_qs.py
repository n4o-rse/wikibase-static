"""S7e -- change the CSV tables with a QuickStatements file (the update channel of PRIMER.md, A4 "CSV, Update-Kanal").

    python main.py apply-qs data/edits/my-change.qs             apply the file to data/csv
    python main.py apply-qs data/edits/my-change.qs --dry-run   say what would happen, write nothing

The CSV stays the state; QuickStatements is only the language of the change. The file is read in a subset of QuickStatements
v1 (tab separated, one command per line, ``#`` starts a comment line) with explicit local ids::

    CREATE                                   a new item gets the next free Q number; ``LAST`` is that item afterwards
    LAST   Len   "Alligator"                 label (L), description (D) or alias (A) in a language, ``Len``, ``Dde``, ``Aen``
    LAST   P2    Q141                        a statement; further pairs are qualifiers
    LAST   P8    "text"   P9   Q5            statement with one qualifier
    LAST   P6    "https://..."   S6  "https://..."     a pair whose property starts with S and a number is a reference
    Q12    P4    wd:Q42                      subject and value may be an entity of Wikidata, linked as wd:Q42
    -Q12   P4    wd:Q42                      remove exactly one statement with this property and value
    -Q12   Aen   "Old name"                 remove one alias
    MERGE  Q12   Q13                         a line in merges.csv (like ``python main.py merge Q12 Q13``); ``MERGE|Q12|Q13`` works as well

Values: ``Q12`` ``P3`` ``wd:Q42``, ``"text"``, ``de:"Text"`` (monolingual), ``+2021-06-04T00:00:00Z/11`` (time), ``@52.5/13.4``
(coordinate, ``lat/lon``), ``12`` or ``12U5`` (quantity with unit item), ``somevalue``, ``novalue``. A value is checked against the
datatype of its property and written in the canonical form of the CSV (``2021-06-04``, ``52.5,13.4``, ``?``, ``-``).

What happens, in this order of importance:

* All or nothing per file: every line is checked (with its line number) before anything is written. One bad line and no file
  changes; the messages name each bad line. The tables are built once more with the change, and a problem that was not there
  before refuses the file as well.
* A statement that is there already (same property, value, rank and qualifiers) is not added a second time.
* A file that was applied once does not act a second time: ``data/edits/applied.csv`` (``sha256, file, changes``) keeps the hash
  of the text (line ends do not count). The same text under another name is the same file.
* Commands that QuickStatements has but this subset does not (sitelinks, ``CREATE_PROPERTY``, removing a label, ...) are reported
  as ``WARN`` with the line number and skipped; the rest of the file is applied.
* New rows have an empty ``origin`` (by hand): a reimport of an importer never overwrites them. A removed row of an importer comes
  back with its next run; the report says so.
* A new statement gets a ``sid`` only when it has qualifiers or references (``<subject>-<property>-qs<hash>l<line>``).

Which parts of QuickStatements are written down from memory and not checked against its help page is listed in PRIMER.md (Befund 76).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_apply_qs.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvbuild, csvio, step_merge, utils
from wikibase_static.csvio import CsvError
from wikibase_static.model import ENTITY_ID, id_sort_key, is_federated

STEP = "apply-qs"
APPLIED = "applied.csv"
APPLIED_COLUMNS = ["sha256", "file", "changes"]
LANG_COMMAND = re.compile(r"^([LDA])([A-Za-z][A-Za-z0-9-]*)$")
REFERENCE_PROPERTY = re.compile(r"^S([1-9][0-9]*)$")
QS_TIME = re.compile(r"^[+-]\d{1,12}-\d\d-\d\dT00:00:00Z/\d{1,2}$")
QS_COORDINATE = re.compile(r"^@([+-]?\d+(?:\.\d+)?)/([+-]?\d+(?:\.\d+)?)$")
QS_QUANTITY = re.compile(r"^([+-]?\d+(?:\.\d+)?)(?:U(\S+))?$")
QS_MONO = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):\"(.*)\"$", re.S)
UNSUPPORTED = {"CREATE_PROPERTY": "creating a property", "CREATE_LEXEME": "creating a lexeme", "CREATE_FORM": "forms",
               "CREATE_SENSE": "senses"}

# which datatypes a shape of QuickStatements value can stand for
SHAPES = {
    "entity": ("wikibase-item", "wikibase-property"),
    "string": ("string", "external-id", "url", "commonsMedia"),
    "monolingual": ("monolingualtext",),
    "time": ("time",),
    "coordinate": ("globe-coordinate",),
    "quantity": ("quantity",),
}


class Bad(Exception):
    """A line that cannot be applied; the message says why (the caller adds ``file:line``)."""


class Unsupported(Exception):
    """A QuickStatements command this subset does not know; reported as WARN and skipped.

    ``placeholder`` stands in the command list for a skipped CREATE_*, so that a ``LAST`` after it is skipped too."""

    def __init__(self, message: str, placeholder: "Command | None" = None) -> None:
        super().__init__(message)
        self.placeholder = placeholder


# --------------------------------------------------------------------------- the language


@dataclass
class Command:
    line: int
    kind: str                           # create | merge | add | remove | label | description | alias
    subject: str = ""                   # "LAST" or an id
    prop: str = ""
    value: str = ""                     # a CSV value (already translated) or the text of a label
    shape: str = ""
    pairs: list[tuple[str, str, str]] = field(default_factory=list)       # (property, CSV value, shape) of qualifiers
    references: list[tuple[str, str, str]] = field(default_factory=list)  # (property, CSV value, shape), property without S
    language: str = ""
    remove: bool = False
    target: str = ""                    # MERGE: the item that stays


def unquote(token: str) -> str:
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise Bad(f"{token!r} is not a quoted text")
    return token[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def translate(token: str) -> tuple[str, str]:
    """A QuickStatements value as ``(CSV value, shape)``."""
    token = token.strip()
    if token == "":
        raise Bad("an empty value")
    if token == "somevalue":
        return "?", "any"
    if token == "novalue":
        return "-", "any"
    if token.startswith('"'):
        return csvio.escape_text(unquote(token)), "string"
    mono = QS_MONO.match(token)
    if mono:
        return f"{mono.group(1)}:{mono.group(2)}", "monolingual"
    if QS_TIME.match(token):
        return token, "time"
    coordinate = QS_COORDINATE.match(token)
    if coordinate:
        return f"{coordinate.group(1)},{coordinate.group(2)}", "coordinate"
    if is_federated(token) or ENTITY_ID.match(token):
        return token, "entity"
    quantity = QS_QUANTITY.match(token)
    if quantity:
        amount, unit = quantity.groups()
        return (f"{amount} {unit}" if unit else amount), "quantity"
    raise Bad(f"{token!r} is not a value this subset reads (Q12, \"text\", de:\"Text\", +2021-06-04T00:00:00Z/11, @lat/lon, 12, somevalue, novalue)")


def parse(text: str) -> tuple[list[Command], list[str], list[str]]:
    """(commands, errors, warnings) of a file's text; every message starts with the line number."""
    commands: list[Command] = []
    errors: list[str] = []
    warnings: list[str] = []
    for number, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        line = raw.strip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            commands.append(parse_line(number, line))
        except Unsupported as err:
            warnings.append(f"line {number}: {err}; line skipped")
            if err.placeholder:
                commands.append(err.placeholder)
        except Bad as err:
            errors.append(f"line {number}: {err}")
    return commands, errors, warnings


def parse_line(number: int, line: str) -> Command:
    if "\t" not in line and "|" in line and not line.lstrip().startswith(('"', "-")):
        fields = [f.strip() for f in line.split("|")]               # QuickStatements v2 writes the same commands with |
    else:
        fields = [f.strip() for f in line.split("\t")]
    while fields and fields[-1] == "":
        fields.pop()
    word = fields[0]
    if word == "CREATE" and len(fields) == 1:
        return Command(number, "create")
    if word in UNSUPPORTED:
        raise Unsupported(f"{word} ({UNSUPPORTED[word]}) is not part of the subset", Command(number, "lost"))
    if word == "MERGE":
        if len(fields) != 3:
            raise Bad("MERGE takes two items: MERGE<TAB>Q1<TAB>Q2")
        for item in fields[1:]:
            if not re.match(r"^Q[1-9][0-9]*$", item):
                raise Bad(f"{item!r} is not a local item id")
        return Command(number, "merge", subject=fields[1], target=fields[2])
    if word == "CREATE":
        raise Bad("CREATE takes no further fields")
    if word != "LAST" and word.isupper() and len(word) > 3 and word.isalpha():
        raise Unsupported(f"{word} is not part of the subset")
    if len(fields) == 1 and re.match(r"^-?(LAST|[QP][0-9]+)\s", word):
        raise Bad("fields must be separated by tabs (a TAB character, not spaces)")
    remove = word.startswith("-")
    subject = word[1:] if remove else word
    if subject != "LAST" and not ENTITY_ID.match(subject):
        if is_federated(subject):
            raise Bad(f"{subject} is an entity of Wikidata; only local items can be changed")
        raise Bad(f"{subject!r} is neither LAST nor an item id (Q12)")
    if subject.startswith("P"):
        raise Bad(f"{subject} is a property; statements on properties are not part of the subset")
    if len(fields) < 3:
        raise Bad("a command needs subject, property and value separated by tabs" if len(fields) > 1 or "\t" in line
                  else "fields must be separated by tabs")
    prop = fields[1]
    lang = LANG_COMMAND.match(prop)
    if lang:
        if len(fields) != 3:
            raise Bad("a label, description or alias takes only the text")
        kind = {"L": "label", "D": "description", "A": "alias"}[lang.group(1)]
        if remove and kind != "alias":
            raise Unsupported(f"removing a {kind} ({prop})")
        return Command(number, kind, subject=subject, prop=prop, value=unquote(fields[2]), language=lang.group(2), remove=remove)
    if re.match(r"^S[A-Za-z]", prop):
        raise Unsupported(f"sitelink {prop}")
    if not (ENTITY_ID.match(prop) and prop[0] == "P" or is_federated(prop) and prop[3] == "P"):
        raise Bad(f"{prop!r} is not a property (P3, wd:P31), a label command (Len) or a known command")
    value, shape = translate(fields[2])
    rest = fields[3:]
    if len(rest) % 2:
        raise Bad("qualifiers come in pairs of property and value")
    command = Command(number, "remove" if remove else "add", subject=subject, prop=prop, value=value, shape=shape)
    for i in range(0, len(rest), 2):
        qprop, (qvalue, qshape) = rest[i], translate(rest[i + 1])
        reference = REFERENCE_PROPERTY.match(qprop)
        if reference:
            command.references.append((f"P{reference.group(1)}", qvalue, qshape))
        elif ENTITY_ID.match(qprop) and qprop[0] == "P" or is_federated(qprop) and qprop[3] == "P":
            command.pairs.append((qprop, qvalue, qshape))
        else:
            raise Bad(f"{qprop!r} is not a qualifier property (P3) or a reference property (S3 for P3)")
    return command


# --------------------------------------------------------------------------- applying


@dataclass
class State:
    """The tables in memory, the ids that exist and the datatypes of the properties."""

    tables: dict[str, csvio.Table]
    kernel: csvbuild.CsvSet
    base: str | None
    merges: list[dict[str, str]]
    idmap_ids: set[str]
    digest: str = ""
    created: list[str] = field(default_factory=list)
    last: str | None = None
    skipped_last: bool = False
    counts: dict[str, int] = field(default_factory=lambda: {
        "created": 0, "statements": 0, "present": 0, "removed": 0, "labels": 0, "descriptions": 0, "aliases": 0, "merges": 0})
    notes: list[str] = field(default_factory=list)

    def rows(self, name: str) -> list[dict[str, str]]:
        return self.tables[name].rows

    def entity(self, entity_id: str) -> dict[str, str] | None:
        return next((r for r in self.rows("entities.csv") if r.get("id", "").strip() == entity_id), None)

    def kernel_ids(self) -> set[str]:
        return {r["id"].strip() for r in self.kernel.entities.rows}

    def known(self, entity_id: str) -> bool:
        return self.entity(entity_id) is not None or entity_id in self.kernel_ids()

    def datatype(self, prop: str) -> tuple[bool, str | None]:
        if is_federated(prop):
            return True, None
        row = self.entity(prop) or next((r for r in self.kernel.entities.rows if r["id"].strip() == prop), None)
        if row is None or row.get("kind", "").strip() != "property":
            raise Bad(f"unknown property {prop}")
        return True, row.get("datatype", "").strip() or None

    def next_id(self) -> str:
        numbers = {int(i[1:]) for i in
                   [r.get("id", "").strip() for r in self.rows("entities.csv")] + sorted(self.idmap_ids)
                   + [m[k] for m in self.merges for k in ("from", "to")] if i[:1] == "Q" and i[1:].isdigit()}
        return f"Q{max([csvbuild.RESERVED - 1] + sorted(numbers)) + 1}"

    def merged_away(self) -> dict[str, str]:
        return {m["from"]: m["to"] for m in self.merges}


def check_value(state: State, prop: str, value: str, shape: str, what: str) -> str:
    """The canonical CSV text of a value of ``prop``; raises ``Bad`` when it does not fit."""
    _ok, datatype = state.datatype(prop)
    if shape != "any" and datatype is not None and datatype not in SHAPES[shape]:
        raise Bad(f"{what} {prop} takes {datatype}, but the value is written as {shape}")
    try:
        snaktype, datavalue, datatype = csvio.parse_value(value, datatype, state.base)
    except CsvError as err:
        raise Bad(f"{what} {prop}: {err}") from None
    if snaktype != "value":
        return value
    if datatype in ("wikibase-item", "wikibase-property"):
        found = datavalue["value"]["id"]
        if not is_federated(value) and not state.known(found):
            raise Bad(f"{what} {prop}: {found} does not exist")
        return value
    kind, inner = datavalue["type"], datavalue["value"]
    if kind == "time":
        return csvio.format_time(inner)
    if kind == "globecoordinate":
        return csvio.format_coordinate(inner)
    if kind == "quantity":
        unit = str(inner.get("unit", "1"))
        local = unit.rsplit("/", 1)[-1] if state.base and unit.startswith(state.base.rstrip("/") + "/entity/") else ""
        if local and not state.known(local):
            raise Bad(f"{what} {prop}: unit {local} does not exist")
        return csvio.format_quantity(inner, state.base)
    return value


def key_of(state: State, prop: str, value: str) -> str:
    _ok, datatype = state.datatype(prop)
    snaktype, datavalue, _dt = csvio.parse_value(value, datatype, state.base)
    return json.dumps([prop, snaktype, datavalue], sort_keys=True, ensure_ascii=False)


def snak_keys(state: State, rows: list[dict[str, str]]) -> list[str]:
    return sorted(key_of(state, r["property"].strip(), r["value"]) for r in rows)


def claims_of(state: State, subject: str) -> list[dict[str, str]]:
    return [r for r in state.rows("statements.csv") if r.get("subject", "").strip() == subject]


def resolve(state: State, command: Command) -> str:
    subject = command.subject
    if subject == "LAST":
        if state.last is None:
            if state.skipped_last:
                raise Unsupported("LAST refers to an item that was not created (an unsupported CREATE_* before it)")
            raise Bad("LAST is used before any CREATE")
        subject = state.last
    entity = state.entity(subject)
    if entity is None:
        raise Bad(f"{subject} does not exist" + (" (it is a kernel item and cannot be changed)" if subject in state.kernel_ids() else ""))
    if entity.get("kind", "").strip() != "item":
        raise Bad(f"{subject} is a {entity.get('kind', '').strip()}; only items can be changed")
    if subject in state.merged_away():
        raise Bad(f"{subject} is merged into {state.merged_away()[subject]}; use that item")
    return subject


def set_cell(state: State, entity: dict[str, str], column: str, value: str) -> None:
    if column not in state.tables["entities.csv"].columns:
        state.tables["entities.csv"].columns.append(column)
    entity[column] = value


def apply_command(state: State, command: Command) -> None:
    kind = command.kind
    if kind == "lost":
        state.last, state.skipped_last = None, True
        return
    if kind == "create":
        new = state.next_id()
        state.rows("entities.csv").append({"id": new, "kind": "item", "datatype": "", "origin": ""})
        state.created.append(new)
        state.last, state.skipped_last = new, False
        state.counts["created"] += 1
        state.notes.append(f"line {command.line}: CREATE -> {new}")
        return
    if kind == "merge":
        for item in (command.subject, command.target):
            if state.entity(item) is None:
                raise Bad(f"MERGE: {item} does not exist")
        if any(m["from"] == command.subject for m in state.merges):
            if any(m["from"] == command.subject and m["to"] == command.target for m in state.merges):
                state.counts["present"] += 1
                return
            raise Bad(f"MERGE: {command.subject} is merged already (into {state.merged_away()[command.subject]})")
        state.merges.append({"from": command.subject, "to": command.target, "note": f"apply-qs {state.digest[:8]} line {command.line}"})
        state.counts["merges"] += 1
        return
    subject = resolve(state, command)
    entity = state.entity(subject)
    assert entity is not None
    if kind in ("label", "description"):
        column = f"{kind}_{command.language}"
        if command.value == "":
            raise Bad(f"an empty {kind}")
        if entity.get(column, "") != command.value:
            set_cell(state, entity, column, command.value)
            state.counts["labels" if kind == "label" else "descriptions"] += 1
        return
    if kind == "alias":
        column = f"aliases_{command.language}"
        current = csvio.split_aliases(entity.get(column, ""))
        if command.remove:
            if command.value not in current:
                raise Bad(f"{subject} has no alias {command.value!r} in {command.language}")
            current.remove(command.value)
            set_cell(state, entity, column, csvio.join_aliases(current))
            state.counts["removed"] += 1
        elif command.value not in current and command.value != entity.get(f"label_{command.language}", None):
            set_cell(state, entity, column, csvio.join_aliases(current + [command.value]))
            state.counts["aliases"] += 1
        return
    value = check_value(state, command.prop, command.value, command.shape, "statement")
    key = key_of(state, command.prop, value)
    mine = claims_of(state, subject)
    if kind == "remove":
        for row in mine:
            if key_of(state, row["property"].strip(), row["value"]) == key:
                state.rows("statements.csv").remove(row)
                sid = row.get("sid", "").strip()
                if sid:
                    for name in ("qualifiers.csv", "references.csv"):
                        state.tables[name].rows[:] = [r for r in state.rows(name) if r.get("sid", "").strip() != sid]
                origin = row.get("origin", "").strip()
                if origin:
                    state.notes.append(f"line {command.line}: removed a row of the importer '{origin}'; its next run writes it again")
                state.counts["removed"] += 1
                return
        raise Bad(f"{subject} has no statement {command.prop} {command.value}")
    qualifiers = [(p, check_value(state, p, v, s, "qualifier"), s) for p, v, s in command.pairs]
    references = [(p, check_value(state, p, v, s, "reference"), s) for p, v, s in command.references]
    qualifier_rows = lambda sid: [r for r in state.rows("qualifiers.csv") if r.get("sid", "").strip() == sid]
    wanted = sorted(key_of(state, p, v) for p, v, _s in qualifiers)
    for row in mine:
        if key_of(state, row["property"].strip(), row["value"]) == key and (row.get("rank", "").strip() or "normal") == "normal":
            sid = row.get("sid", "").strip()
            if (snak_keys(state, qualifier_rows(sid)) if sid else []) == wanted:
                state.counts["present"] += 1
                return
    sid = ""
    if qualifiers or references:
        sid = f"{subject}-{command.prop.replace(':', '')}-qs{state.digest[:8]}l{command.line}"
    state.rows("statements.csv").append({"sid": sid, "subject": subject, "property": command.prop, "value": value, "rank": "", "origin": ""})
    for p, v, _s in qualifiers:
        state.rows("qualifiers.csv").append({"sid": sid, "property": p, "value": v})
    for p, v, _s in references:
        state.rows("references.csv").append({"sid": sid, "group": "1", "property": p, "value": v})
    state.counts["statements"] += 1


# --------------------------------------------------------------------------- the file


def normalised(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def read_applied(path: Path, problems: list[str]) -> list[dict[str, str]]:
    table = csvio.read_table(path, ["sha256", "file"], problems, path.name)
    return [{"sha256": r.get("sha256", "").strip(), "file": r.get("file", ""), "changes": r.get("changes", "")} for r in table.rows]


def messages_without_place(messages: list[str]) -> set[str]:
    return {m.split(": ", 1)[-1] if re.match(r"^[^ ]+:\d+: ", m) else m for m in messages}


def shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(utils.ROOT).as_posix()
    except ValueError:
        return path.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py apply-qs", description="Change the CSV tables with a QuickStatements file.")
    parser.add_argument("file", type=Path, help="the .qs file")
    parser.add_argument("--dry-run", action="store_true", help="say what would happen, write nothing")
    parser.add_argument("--csv", type=Path, default=utils.ROOT / "data" / "csv", help="folder with the CSV tables")
    parser.add_argument("--applied", type=Path, default=None, help=f"the list of applied files (default data/edits/{APPLIED})")
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"ERROR: [{STEP}] {args.file}: no such file")
        return 2
    data = normalised(args.file.read_bytes())
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        print(f"ERROR: [{STEP}] {args.file}: not UTF-8 text")
        return 2
    digest = hashlib.sha256(data).hexdigest()
    applied_path = args.applied or utils.ROOT / "data" / "edits" / APPLIED
    read_problems: list[str] = []
    applied = read_applied(applied_path, read_problems)
    for message in read_problems:
        print(f"ERROR: [{STEP}] {message}")
    if read_problems:
        return 1
    done = next((r for r in applied if r["sha256"] == digest), None)
    if done:
        print(f"[{STEP}] {shown(args.file)} was applied already (as {done['file']}, sha256 {digest[:12]}); nothing to do")
        return 0

    commands, errors, warnings = parse(text)
    problems: list[str] = []
    site = csvbuild.read_set(args.csv, problems, args.csv.name)
    kernel = csvbuild.kernel_set()
    base = csvbuild.site_base()
    before = csvbuild.build(site, kernel, base).problems
    idmap_path = args.csv / "idmap.csv"
    idmap_ids = {r.get("id", "").strip() for r in csvio.read_table(idmap_path, ["id"], [], "idmap.csv").rows} if idmap_path.is_file() else set()
    state = State(
        tables={"entities.csv": site.entities, "statements.csv": site.statements,
                "qualifiers.csv": site.qualifiers, "references.csv": site.references},
        kernel=kernel, base=base, merges=step_merge.read_lines(args.csv / csvbuild.MERGES, []), idmap_ids=idmap_ids, digest=digest)
    for table in state.tables.values():
        table.columns = list(table.columns)

    for command in commands:
        try:
            apply_command(state, command)
        except Unsupported as err:
            warnings.append(f"line {command.line}: {err}; line skipped")
        except Bad as err:
            errors.append(f"line {command.line}: {err}")
            if command.kind == "create":
                state.last = None
    label = shown(args.file)
    if not errors:
        errors += verify(args, state, kernel, base, before)
    if errors:
        errors.sort(key=lambda m: int(m.split()[1].rstrip(":")) if m.startswith("line ") else 10**9)
        for message in warnings:
            utils.warn(STEP, f"{label}: {message}")
        for message in errors:
            print(f"ERROR: [{STEP}] {label}: {message}")
        print(f"ERROR: [{STEP}] {len(errors)} line(s) cannot be applied; nothing was changed")
        return 1

    counts = state.counts
    summary = ", ".join(f"{n} {name}" for name, n in (
        ("item(s) created", counts["created"]), ("statement(s) added", counts["statements"]),
        ("already there", counts["present"]), ("removed", counts["removed"]), ("label(s) set", counts["labels"]),
        ("description(s) set", counts["descriptions"]), ("alias(es) added", counts["aliases"]), ("merge(s)", counts["merges"])) if n) or "no change"
    print(f"[{STEP}] {label}: {len(commands)} command(s): {summary}")
    for note in state.notes:
        print(f"[{STEP}]   {note}")
    for message in warnings:
        utils.warn(STEP, f"{label}: {message}")

    texts = csvio.canonical_texts(state.tables)
    written = 0
    for name, content in sorted(texts.items()):
        target = args.csv / name
        if target.is_file() and target.read_bytes() == content.encode("utf-8"):
            continue
        written += 1
        if not args.dry_run:
            utils.write_text(target, content)
    if counts["merges"]:
        written += 1
        if not args.dry_run:
            step_merge.write_lines(args.csv / csvbuild.MERGES, state.merges)
    entry = {"sha256": digest, "file": label, "changes": summary}
    if not args.dry_run:
        rows = sorted(applied + [entry], key=lambda r: (r["file"], r["sha256"]))
        utils.write_text(applied_path, csvio.render_table(APPLIED_COLUMNS, rows))
    print(f"[{STEP}] {written} table file(s) {'would change' if args.dry_run else 'written'} in {shown(args.csv)}"
          + ("" if args.dry_run else f"; {shown(applied_path)} lists the file"))
    return 0


def verify(args: argparse.Namespace, state: State, kernel: csvbuild.CsvSet, base: str | None,
           before: list[str]) -> list[str]:
    """Build the tables with the change in a scratch folder; what the build complains about and did not before is an error."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch) / args.csv.name
        folder.mkdir()
        for name, content in csvio.canonical_texts(state.tables).items():
            (folder / name).write_text(content, encoding="utf-8", newline="")
        if state.merges:
            step_merge.write_lines(folder / csvbuild.MERGES, state.merges)
        found: list[str] = []
        probe = csvbuild.read_set(folder, found, folder.name)
        built = csvbuild.build(probe, kernel, base)
        new = messages_without_place(found + built.problems) - messages_without_place(before)
        return [f"after the change the tables are not sound: {m}" for m in sorted(new)]


if __name__ == "__main__":
    raise SystemExit(main())
