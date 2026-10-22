"""S7c -- import the software entries of open-archaeo into the CSV tables (a verb of its own, offline).

    python main.py import-open-archaeo                 about 100 of the entries, stratified by category
    python main.py import-open-archaeo --limit 40      another size (the same limit always picks the same entries)
    python main.py import-open-archaeo --all           every entry
    python main.py import-open-archaeo --dry-run       print the report, write nothing

Reads ``data/raw/open-archaeo-software.csv`` (a copy of the output of ``py/transform.py`` in open-archaeo, never edited),
the mapping ``data/csv/mapping/open-archaeo.csv`` (columns ``column, property, qualifiers, rule, note``) and the
vocabulary ``data/csv/mapping/open-archaeo-vocabulary.csv`` (columns ``section, value, wikidata, label, note``), and
writes rows with ``origin=open-archaeo`` into the four tables in ``data/csv/`` and into ``idmap.csv``. It never writes
Wikibase JSON; ``from-csv`` does that (PRIMER.md of wikibase-static, A4 "Importer schreiben in die CSV").

The mapping names Wikidata properties (the Pack's crosswalk); each is turned into the local property that carries it as
its Wikidata twin (``P4``). A mapped property without a local twin is a ``WARN``. The rules are fixed in this module,
the choice of properties and qualifiers is in the table:

    ignore         the column is not imported (``id`` is a function of the slug, ``twitter`` and ``notes`` are no data)
    label          the cell is the English label of the software item
    description    the cell is the English description, unchanged
    string         the cell is the value of the (first) property as it is
    monolingual    the cell is the value as ``en:<text>``
    slug           the cell is the value; the qualifier P195 (collection) is the open-archaeo collection item
    class          the cell is a category; its class is the local twin of the Wikidata class in the vocabulary
    items          ``|``-separated controlled values, one local item each (section ``tag``)
    persons        ``|``-separated names, one local item each; the qualifier P1545 is the position (order matters)
    platform       ``platform_role`` chooses: language -> P277, host application -> P1547, deployment -> not imported
    repository     ``|``-separated URLs; qualifiers P8423 (from ``repository_host``), P1065 and P2960 (from
                   ``internetarchive``, the date is read from the path)
    registry       ``registry_name`` chooses: CRAN -> P5565, PyPI -> P5568; the package name is read from the URL
    work           a publication: one local item (instance of Q3), labelled with the DOI or the URL; no statements, because
                   every property of the model has the domain software
    identity       the identity block of every item: instance of chublet, maintained by the WikiProject, part of
                   chublets.software and of the open-archaeo collection, collection (variant V2 of the Pack)

Ids: ``idmap.csv`` (``source, key, id``) fixes which entry or vocabulary value became which local item; a new key gets
the next free number from 100 and a number is never used twice. Reimport: every row with ``origin=open-archaeo`` is
replaced; a row whose ``origin`` was emptied counts as written by hand and wins -- the importer then leaves that
property of that subject (all its rows) alone. Every statement carries a reference (P6, the page of the entry). No
clock: the output depends on the input files and the options only.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_import_open_archaeo.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvbuild, csvio, utils
from wikibase_static.model import id_sort_key

STEP = "import-open-archaeo"
SOURCE = "open-archaeo"
FIRST_FREE = 100
DEFAULT_LIMIT = 100
INSTANCE, ROOT_CLASS, TWIN, REFERENCE_URL = "P2", "Q3", "P4", "P6"
STRATUM = "category"                       # the column the selection is stratified by
GIT_HOSTS = {"GitHub", "GitHub Gist", "Codeberg", "GitLab"}   # hosts that speak Git; Bitbucket is ambiguous (Pack)
RULES = ("ignore", "label", "description", "string", "monolingual", "slug", "class", "items", "persons",
         "platform", "repository", "registry", "work", "identity")
VOCABULARY_SECTIONS = ("identity", "category", "vcs", "language", "host", "tag")
IDENTITY_KEYS = ("chublet", "wikiproject", "platform", "collection")
ARCHIVE_DATE = re.compile(r"_-_(\d{4}-\d{2}-\d{2})_")
CRAN_PACKAGE = re.compile(r"package=([^&/#]+)")
PYPI_PROJECT = re.compile(r"/project/([^/?#]+)")
DOI_URL = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)


class ImportProblem(ValueError):
    """The mapping, the vocabulary or the input cannot be used; the message says what is wrong."""


# --------------------------------------------------------------------------- reading


def read_rows(path: Path, columns: list[str], what: str) -> list[dict[str, str]]:
    if not path.is_file():
        raise ImportProblem(f"{what}: {path} does not exist")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ImportProblem(f"{what}: {path.name} lacks the column(s) {', '.join(missing)}")
        return [{k: (v or "") for k, v in row.items()} for row in reader]


def split_pipe(text: str) -> list[str]:
    return [part.strip() for part in text.split("|") if part.strip()]


@dataclass
class Mapping:
    rows: list[dict[str, str]]

    def properties(self, row: dict[str, str]) -> list[str]:
        return split_pipe(row["property"])

    def qualifiers(self, row: dict[str, str]) -> set[str]:
        return set(split_pipe(row["qualifiers"]))


def read_mapping(path: Path) -> Mapping:
    rows = read_rows(path, ["column", "property", "qualifiers", "rule"], "mapping")
    for number, row in enumerate(rows, start=2):
        if row["rule"] not in RULES:
            raise ImportProblem(f"mapping: {path.name}:{number}: unknown rule {row['rule']!r} (known: {', '.join(RULES)})")
    return Mapping(rows)


def read_vocabulary(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows = read_rows(path, ["section", "value", "wikidata"], "vocabulary")
    found: dict[tuple[str, str], dict[str, str]] = {}
    for number, row in enumerate(rows, start=2):
        if row["section"] not in VOCABULARY_SECTIONS:
            raise ImportProblem(f"vocabulary: {path.name}:{number}: unknown section {row['section']!r}")
        found[(row["section"], row["value"])] = row
    for key in IDENTITY_KEYS:
        if ("identity", key) not in found:
            raise ImportProblem(f"vocabulary: {path.name} has no identity row for {key!r}")
    return found


# --------------------------------------------------------------------------- selection


def select(entries: list[dict[str, str]], limit: int | None) -> list[dict[str, str]]:
    """``limit`` entries, in proportion to the size of each category (largest remainder), the first ones by id in each.
    The same input and limit give the same entries. ``None`` or a limit at least as large as the input: all of them."""
    ordered = sorted(entries, key=lambda e: e["id"])
    if limit is None or limit >= len(ordered):
        return ordered
    groups: dict[str, list[dict[str, str]]] = {}
    for entry in ordered:
        groups.setdefault(entry.get(STRATUM, ""), []).append(entry)
    total = len(ordered)
    quota = {name: limit * len(group) // total for name, group in groups.items()}
    rest = limit - sum(quota.values())
    by_remainder = sorted(groups, key=lambda n: (-(limit * len(groups[n]) % total), n))
    for name in by_remainder[:rest]:
        quota[name] += 1
    chosen = [entry for name, group in groups.items() for entry in group[:quota[name]]]
    return sorted(chosen, key=lambda e: e["id"])


# --------------------------------------------------------------------------- ids


class IdMap:
    """``data/csv/idmap.csv``: (source, key) -> id. A new key gets the next number after the highest ever given."""

    COLUMNS = ["source", "key", "id"]

    def __init__(self, rows: list[dict[str, str]], taken: set[str]) -> None:
        self.ids: dict[tuple[str, str], str] = {(r["source"], r["key"]): r["id"] for r in rows}
        self.used = {int(i[1:]) for i in list(self.ids.values()) + sorted(taken) if i[:1] == "Q" and i[1:].isdigit()}
        self.new = 0

    def get(self, key: str) -> str:
        found = self.ids.get((SOURCE, key))
        if found:
            return found
        number = max([FIRST_FREE - 1] + sorted(self.used)) + 1
        self.used.add(number)
        self.ids[(SOURCE, key)] = f"Q{number}"
        self.new += 1
        return f"Q{number}"

    def text(self) -> str:
        rows = [{"source": s, "key": k, "id": i} for (s, k), i in self.ids.items()]
        rows.sort(key=lambda r: (r["source"], id_sort_key(r["id"])))
        return csvio.render_table(self.COLUMNS, rows)


# --------------------------------------------------------------------------- the import


@dataclass
class Out:
    entities: dict[str, dict[str, str]] = field(default_factory=dict)
    statements: list[dict[str, str]] = field(default_factory=list)
    qualifiers: list[dict[str, str]] = field(default_factory=list)
    references: list[dict[str, str]] = field(default_factory=list)


class Importer:
    def __init__(self, mapping: Mapping, vocabulary: dict, twins: dict[str, str], idmap: IdMap,
                 properties: dict[str, str]) -> None:
        self.mapping, self.vocabulary, self.twins, self.idmap = mapping, vocabulary, twins, idmap
        self.properties = properties          # local property id -> datatype is not needed; kept for the check
        self.out = Out()
        self.counter: Counter[tuple[str, str]] = Counter()
        self.gaps: Counter[str] = Counter()
        self.problems: list[str] = []
        self.kinds: Counter[str] = Counter()
        self.entry_url = ""
        self._unresolved: set[str] = set()

    # ---- helpers

    def local(self, pid: str) -> str | None:
        """The local property that has the Wikidata property ``pid`` as its twin."""
        found = self.twins.get(pid)
        if found is None and pid not in self._unresolved:
            self._unresolved.add(pid)
            self.problems.append(f"mapping: the Wikidata property {pid} has no local twin ({TWIN} on a property); not imported")
        return found

    def gap(self, text: str) -> None:
        self.gaps[text] += 1

    def add(self, subject: str, prop: str, value: str, qualifiers: list[tuple[str, str]] | None = None) -> None:
        """A statement with its qualifiers and the reference of the current entry."""
        n = self.counter[(subject, prop)] = self.counter[(subject, prop)] + 1
        sid = f"{subject}-{prop}-{n}"
        self.out.statements.append({"sid": sid, "subject": subject, "property": prop, "value": value, "rank": "", "origin": SOURCE})
        for qprop, qvalue in qualifiers or []:
            self.out.qualifiers.append({"sid": sid, "property": qprop, "value": qvalue})
        self.out.references.append({"sid": sid, "group": "1", "property": REFERENCE_URL, "value": self.entry_url})

    def new_item(self, key: str, label: str, description: str = "") -> tuple[str, bool]:
        entity_id = self.idmap.get(key)
        if entity_id in self.out.entities:
            return entity_id, False
        row = {"id": entity_id, "kind": "item", "datatype": "", "origin": SOURCE, "label_en": label}
        if description:
            row["description_en"] = description
        self.out.entities[entity_id] = row
        return entity_id, True

    def vocab_item(self, section: str, value: str, label: str | None = None) -> str:
        """A controlled value as a local item: the local twin of its Wikidata item when there is one, otherwise an
        item of its own (instance of Q3), with the Wikidata item as its twin when the vocabulary names one."""
        row = self.vocabulary.get((section, value), {})
        wikidata = row.get("wikidata", "")
        if wikidata and wikidata in self.twins:
            return self.twins[wikidata]
        key = f"{section}:{value}"
        entity_id, created = self.new_item(key, label or row.get("label") or value)
        if created:
            self.kinds[section] += 1
            self.add(entity_id, INSTANCE, ROOT_CLASS)
            if wikidata:
                self.add(entity_id, TWIN, wikidata)
        return entity_id

    def person(self, name: str) -> str:
        entity_id, created = self.new_item(f"person:{name}", name)
        if created:
            self.kinds["person"] += 1
            self.add(entity_id, INSTANCE, ROOT_CLASS)
        return entity_id

    def work(self, url: str) -> str:
        doi = DOI_URL.match(url)
        entity_id, created = self.new_item(f"work:{url}", doi.group(1) if doi else url)
        if created:
            self.kinds["work"] += 1
            self.add(entity_id, INSTANCE, ROOT_CLASS)     # the label is the DOI or the URL: every property of the
        return entity_id                                  # model has the domain "software" (see PRIMER.md, Befund 68)

    def identity_class(self, key: str) -> str | None:
        wikidata = self.vocabulary[("identity", key)]["wikidata"]
        found = self.twins.get(wikidata)
        if found is None:
            self.problems.append(f"vocabulary: the class {wikidata} ({key}) has no local twin; the identity block is incomplete")
        return found

    def identity_item(self, key: str) -> str:
        return self.vocab_item("identity", key)

    # ---- one entry

    def entry(self, entry: dict[str, str]) -> None:
        self.entry_url = entry["url"]
        subject, created = self.new_item(f"entry:{entry['id']}", entry["name"])
        self.kinds["software"] += 1
        for row in self.mapping.rows:
            getattr(self, f"rule_{row['rule']}")(subject, entry, row)

    def rule_ignore(self, subject, entry, row) -> None:
        return None

    def rule_label(self, subject, entry, row) -> None:
        self.out.entities[subject]["label_en"] = entry[row["column"]]

    def rule_description(self, subject, entry, row) -> None:
        if entry[row["column"]]:
            self.out.entities[subject]["description_en"] = entry[row["column"]]

    def rule_string(self, subject, entry, row) -> None:
        value = entry[row["column"]]
        props = self.mapping.properties(row)
        if value and props and (prop := self.local(props[0])):
            self.add(subject, prop, csvio.escape_text(value))

    def rule_monolingual(self, subject, entry, row) -> None:
        value = entry[row["column"]]
        props = self.mapping.properties(row)
        if value and props and (prop := self.local(props[0])):
            self.add(subject, prop, f"en:{value}")

    def rule_slug(self, subject, entry, row) -> None:
        props = self.mapping.properties(row)
        prop = self.local(props[0]) if props else None
        if not prop or not entry[row["column"]]:
            return
        qualifiers = []
        collection = self.local("P195")
        if "P195" in self.mapping.qualifiers(row) and collection:
            qualifiers.append((collection, self.identity_item("collection")))
        self.add(subject, prop, csvio.escape_text(entry[row["column"]]), qualifiers)

    def rule_class(self, subject, entry, row) -> None:
        value = entry[row["column"]]
        props = self.mapping.properties(row)
        if not value or not props or not self.local(props[0]):
            return
        wikidata = self.vocabulary.get(("category", value), {}).get("wikidata", "")
        target = self.twins.get(wikidata)
        if target is None:
            self.gap(f"category {value!r}: no local class (the vocabulary names {wikidata or 'no Wikidata class'})")
            return
        self.add(subject, INSTANCE, target)

    def rule_items(self, subject, entry, row) -> None:
        props = self.mapping.properties(row)
        if not props or not (prop := self.local(props[0])):
            return
        section = "tag"
        for value in split_pipe(entry[row["column"]]):
            self.add(subject, prop, self.vocab_item(section, value))

    def rule_persons(self, subject, entry, row) -> None:
        props = self.mapping.properties(row)
        if not props or not (prop := self.local(props[0])):
            return
        ordinal = self.local("P1545") if "P1545" in self.mapping.qualifiers(row) else None
        for position, name in enumerate(split_pipe(entry[row["column"]]), start=1):
            self.add(subject, prop, self.person(name), [(ordinal, str(position))] if ordinal else None)

    def rule_platform(self, subject, entry, row) -> None:
        value, role = entry[row["column"]], entry.get("platform_role", "")
        if not value:
            return
        pids = {"language": "P277", "host application": "P1547"}
        if role == "deployment":
            self.gap("platform with the role deployment (refines P31): not imported, it would need classes of their own")
            return
        pid = pids.get(role)
        if pid is None or pid not in self.mapping.properties(row):
            self.gap(f"platform {value!r} with the role {role or 'none'}: not imported")
            return
        prop = self.local(pid)
        if prop:
            self.add(subject, prop, self.vocab_item("language" if role == "language" else "host", value))

    def rule_repository(self, subject, entry, row) -> None:
        props = self.mapping.properties(row)
        if not props or not (prop := self.local(props[0])):
            return
        urls = split_pipe(entry[row["column"]])
        hosts = split_pipe(entry.get("repository_host", ""))
        wanted = self.mapping.qualifiers(row)
        archive = entry.get("internetarchive", "")
        for i, url in enumerate(urls):
            qualifiers: list[tuple[str, str]] = []
            host = hosts[i] if i < len(hosts) else (hosts[-1] if hosts else "")
            if "P8423" in wanted and (q := self.local("P8423")):
                if host in GIT_HOSTS:
                    qualifiers.append((q, self.vocab_item("vcs", "Git")))
                else:
                    self.gap(f"repository host {host or 'none'!r}: no version control system set (not Git for sure)")
            if i == 0 and archive:
                if "P1065" in wanted and (q := self.local("P1065")):
                    qualifiers.append((q, csvio.escape_text(archive)))
                date = ARCHIVE_DATE.search(archive)
                if "P2960" in wanted and (q := self.local("P2960")):
                    if date:
                        qualifiers.append((q, date.group(1)))
                    else:
                        self.gap("internetarchive URL without a date in its path: no archive date")
            self.add(subject, prop, csvio.escape_text(url), qualifiers)

    def rule_registry(self, subject, entry, row) -> None:
        name, url = entry.get("registry_name", ""), entry[row["column"]]
        if not url:
            return
        table = {"CRAN": ("P5565", CRAN_PACKAGE), "PyPI": ("P5568", PYPI_PROJECT)}
        if name not in table or table[name][0] not in self.mapping.properties(row):
            self.gap(f"registry {name or 'none'!r}: not imported")
            return
        pid, pattern = table[name]
        found = pattern.search(url)
        prop = self.local(pid)
        if not found:
            self.gap(f"registry URL that does not name a package ({name})")
        elif prop:
            self.add(subject, prop, csvio.escape_text(found.group(1)))

    def rule_work(self, subject, entry, row) -> None:
        props = self.mapping.properties(row)
        url = entry[row["column"]]
        if url and props and (prop := self.local(props[0])):
            self.add(subject, prop, self.work(url))

    def rule_identity(self, subject, entry, row) -> None:
        wanted = self.mapping.properties(row)
        chublet = self.identity_class("chublet")
        if "P31" in wanted and chublet:
            self.add(subject, INSTANCE, chublet)
        for pid, key in (("P6104", "wikiproject"), ("P361", "platform"), ("P361", "collection"), ("P195", "collection")):
            if pid in wanted and (prop := self.local(pid)):
                self.add(subject, prop, self.identity_item(key))


# --------------------------------------------------------------------------- merging into the tables


@dataclass
class Merged:
    tables: dict[str, csvio.Table]
    replaced: int
    kept_by_hand: int       # importer rows left in place because a hand row protects their property
    skipped: int            # statements the importer made but did not write, for the same reason
    added: dict[str, int]


def merge(existing: dict[str, csvio.Table], out: Out) -> Merged:
    """The tables after the import: importer rows replaced, rows of anyone else untouched, and where a hand row exists for
    a (subject, property) the importer leaves that property of that subject alone."""
    entities, statements = existing["entities.csv"], existing["statements.csv"]
    hand_ids = {r["id"] for r in entities.rows if r.get("origin", "") != SOURCE}
    protected = {(r["subject"], r["property"]) for r in statements.rows if r.get("origin", "") != SOURCE}

    kept_entities = [r for r in entities.rows if r.get("origin", "") != SOURCE]
    new_entities = [row for entity_id, row in out.entities.items() if entity_id not in hand_ids]
    columns = list(entities.columns)
    for row in new_entities:
        for column in row:
            if column not in columns:
                columns.append(column)

    kept_statements, dropped, kept_by_hand = [], set(), 0
    for row in statements.rows:
        if row.get("origin", "") == SOURCE and (row["subject"], row["property"]) not in protected:
            dropped.add(row.get("sid", ""))
        else:
            kept_statements.append(row)
            if row.get("origin", "") == SOURCE:
                kept_by_hand += 1
    dropped.discard("")
    replaced = len(statements.rows) - len(kept_statements)
    added = [r for r in out.statements if (r["subject"], r["property"]) not in protected]
    added_sids = {r["sid"] for r in added}

    def keep(table: csvio.Table, new: list[dict[str, str]]) -> csvio.Table:
        rows = [r for r in table.rows if r.get("sid", "") not in dropped] + [r for r in new if r["sid"] in added_sids]
        return csvio.Table(table.name, list(table.columns), rows, [])

    tables = {
        "entities.csv": csvio.Table(entities.name, columns, kept_entities + new_entities, []),
        "statements.csv": csvio.Table(statements.name, list(statements.columns), kept_statements + added, []),
        "qualifiers.csv": keep(existing["qualifiers.csv"], out.qualifiers),
        "references.csv": keep(existing["references.csv"], out.references),
    }
    return Merged(tables, replaced, kept_by_hand, len(out.statements) - len(added),
                  {"entities": len(new_entities), "statements": len(added)})


# --------------------------------------------------------------------------- the step


def twin_map(site: csvbuild.CsvSet, kernel: csvbuild.CsvSet) -> dict[str, str]:
    """Wikidata id -> local id, from the P4 statements of the site and of the kernel (the site wins a clash)."""
    found: dict[str, str] = {}
    for table in (kernel.statements, site.statements):
        for row in table.rows:
            if row["property"] == TWIN and row.get("origin", "") != SOURCE:
                found[row["value"]] = row["subject"]
    return found


def shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(utils.ROOT).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py import-open-archaeo",
                                     description="open-archaeo software entries -> CSV tables.")
    csv_dir = utils.ROOT / "data" / "csv"
    parser.add_argument("--csv", type=Path, default=csv_dir, help="folder with the CSV tables")
    parser.add_argument("--input", type=Path, default=utils.DATA_RAW / "open-archaeo-software.csv")
    parser.add_argument("--mapping", type=Path, default=csv_dir / "mapping" / "open-archaeo.csv")
    parser.add_argument("--vocabulary", type=Path, default=csv_dir / "mapping" / "open-archaeo-vocabulary.csv")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"number of entries (default {DEFAULT_LIMIT})")
    parser.add_argument("--all", action="store_true", help="import every entry")
    parser.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    args = parser.parse_args(argv)

    try:
        mapping = read_mapping(args.mapping)
        vocabulary = read_vocabulary(args.vocabulary)
        entries = read_rows(args.input, ["id", "slug", "url", "name", STRATUM], "input")
    except ImportProblem as err:
        print(f"ERROR: [{STEP}] {err}")
        return 2

    problems: list[str] = []
    site = csvbuild.read_set(args.csv, problems, shown(args.csv))
    kernel = csvbuild.kernel_set()
    existing = {"entities.csv": site.entities, "statements.csv": site.statements,
                "qualifiers.csv": site.qualifiers, "references.csv": site.references}
    for table in existing.values():
        table.columns = list(table.columns)
    idmap_rows = read_rows(args.csv / "idmap.csv", ["source", "key", "id"], "idmap") if (args.csv / "idmap.csv").is_file() else []
    idmap = IdMap(idmap_rows, {r["id"] for r in site.entities.rows} | {r["subject"] for r in site.statements.rows})

    chosen = select(entries, None if args.all else args.limit)
    importer = Importer(mapping, vocabulary, twin_map(site, kernel), idmap, {})
    for entry in chosen:
        importer.entry(entry)
    merged = merge(existing, importer.out)

    by_category = Counter(e[STRATUM] for e in chosen)
    print(f"[{STEP}] {len(entries)} entries in {shown(args.input)}, {len(chosen)} selected "
          f"({'all' if args.all else f'limit {args.limit}, stratified by {STRATUM}'}): "
          + ", ".join(f"{name} {count}" for name, count in sorted(by_category.items())))
    kinds = importer.kinds
    print(f"[{STEP}] items: {kinds['software']} software, {kinds['tag']} tags, {kinds['person']} persons, "
          f"{kinds['language']} languages, {kinds['host']} host applications, {kinds['work']} works, "
          f"{kinds['vcs'] + kinds['identity']} other; {idmap.new} new id(s) in idmap.csv")
    print(f"[{STEP}] rows from the importer: {len(importer.out.entities)} entities, {len(importer.out.statements)} statements, "
          f"{len(importer.out.qualifiers)} qualifiers, {len(importer.out.references)} references; "
          f"{merged.replaced} earlier importer statement(s) replaced; hand rows protect {merged.skipped + merged.kept_by_hand} "
          f"({merged.skipped} not written, {merged.kept_by_hand} kept)")
    for text, count in sorted(importer.gaps.items()):
        print(f"[{STEP}] not imported ({count}x): {text}")

    texts = csvio.canonical_texts(merged.tables)
    texts["idmap.csv"] = idmap.text()
    written = 0
    for name, text in sorted(texts.items()):
        target = args.csv / name
        if target.is_file() and target.read_bytes() == text.encode("utf-8"):
            continue
        written += 1
        if not args.dry_run:
            utils.write_text(target, text)
    print(f"[{STEP}] {written} file(s) {'would change' if args.dry_run else 'written'} in {shown(args.csv)}")
    for message in sorted(set(importer.problems)):
        utils.warn(STEP, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
