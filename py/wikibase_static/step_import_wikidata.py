"""S7d -- import items of Wikidata into the CSV tables (a verb of its own; the only importer that may use the network).

    python main.py import-wikidata                  fetch what changed at Wikidata, then import the seeds
    python main.py import-wikidata --offline        no network: import what data/raw/wikidata/ holds
    python main.py import-wikidata --from-dir DIR   store JSON files saved in a browser (Special:EntityData,
                                                    wbgetentities) in data/raw/wikidata/, then import offline
    python main.py import-wikidata --dry-run        print the report, write nothing (reads data/raw only)

The seeds are listed in ``data/csv/seeds-wikidata.csv`` (columns ``qid, kind, note``; ``kind`` and ``note`` are for the
reader, the importer treats every seed alike). Each seed becomes a local item (``origin=wikidata``) with its labels,
descriptions and aliases in the wanted languages and its statements, qualifiers and references.

How Wikidata ids are kept out of the data (PRIMER.md, Befund 34): a property is translated through the Wikidata twin
(``P4``) of a local property -- a Wikidata property without a twin is not imported but reported. An item value is
translated through the twin of a local item; a target without a twin becomes a *stub* (``origin=wikidata-stub``): a local
item with label, description and the twin ``P4``, nothing more (depth 1). A target that is the value of "instance of" is a
class: its stub is a class and, as an assumption of the importer, a subclass of the local twin of Q7397 (software); that
one statement has no reference. No value, qualifier or reference holds a
Wikidata id, except the twin ``P4`` itself and the stub's twin.

Every statement carries a reference: ``P6`` (the Wikidata page of the item), ``P7`` (the ``modified`` date of the revision
that was read, never the clock) and ``P8`` (stated in: Wikidata). The references Wikidata itself holds follow as further
groups, as far as their properties have a twin.

Raw data: ``data/raw/wikidata/entities/<id>.json`` (one entity as the API returns it, written canonically) and
``manifest.json`` (``lastrevid``, ``modified``, ``sha256``), the layout of ``harvest``. Only seeds and stubs whose revision
changed are fetched again. Reimport: rows with ``origin=wikidata`` or ``wikidata-stub`` are replaced; a row of anyone
else (empty ``origin``) wins, as in ``import-open-archaeo``.

The report lists what was not imported (Wikidata properties without a twin, values the CSV cannot hold) and which
repository and exact-match URLs of the seeds occur in the local items of another origin (open-archaeo) -- a report only,
nothing is merged.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_import_wikidata.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, csvbuild, csvio, utils
from wikibase_static.model import id_sort_key
from wikibase_static.step_harvest import (
    BATCH, Client, HarvestError, is_current, load_manifest, read_saved, store_entity, write_manifest,
)
from wikibase_static.step_import_open_archaeo import (
    IdMap, ImportProblem, Out, merge, read_rows, shown, twin_map,
)

STEP = "import-wikidata"
SOURCE = "wikidata"
STUB = "wikidata-stub"
ORIGINS = (SOURCE, STUB)
API = "https://www.wikidata.org/w/api.php"
PAGE = "https://www.wikidata.org/wiki/"
WIKIDATA_ITEM, WIKIDATA_LABEL = "Q2013", "Wikidata"      # the item named in "stated in" of every statement
SUBCLASS, INSTANCE, TWIN, REFERENCE_URL, RETRIEVED, STATED_IN = "P1", "P2", "P4", "P6", "P7", "P8"
PARENT_CLASS = "Q7397"                       # software: its local twin is the parent of the class stubs
DEFAULT_LANGUAGES = ("en", "de")
QID = re.compile(r"^Q[1-9][0-9]*$")
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})T")
GREGORIAN = csvio.GREGORIAN
REPORT = "wikidata-import.txt"


# --------------------------------------------------------------------------- reading


def read_seeds(path: Path) -> list[dict[str, str]]:
    rows = read_rows(path, ["qid"], "seeds")
    seen: set[str] = set()
    for number, row in enumerate(rows, start=2):
        row.setdefault("kind", "")
        row.setdefault("note", "")
        if not QID.match(row["qid"]):
            raise ImportProblem(f"seeds: {path.name}:{number}: {row['qid']!r} is not an item id (Q42)")
        if row["qid"] in seen:
            raise ImportProblem(f"seeds: {path.name}:{number}: {row['qid']} is listed twice")
        seen.add(row["qid"])
    return rows


def load_raw(raw: Path) -> dict[str, dict[str, Any]]:
    """Every stored entity, by id."""
    found: dict[str, dict[str, Any]] = {}
    folder = raw / "entities"
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            try:
                found.update({e["id"]: e for e in read_saved(path)})
            except (ValueError, OSError) as err:
                raise ImportProblem(f"raw: {shown(path)} cannot be read ({err})") from err
    return found


def property_datatypes(*sets: csvbuild.CsvSet) -> dict[str, str]:
    """Local property id -> datatype, from the site and the kernel."""
    found: dict[str, str] = {}
    for one in sets:
        for row in one.entities.rows:
            if row.get("kind") == "property":
                found[row["id"]] = row.get("datatype", "")
    return found


# --------------------------------------------------------------------------- conversion


@dataclass
class Gaps:
    """What was not imported, for the report."""

    properties: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)   # (pid, role) -> count, items
    other: Counter = field(default_factory=Counter)

    def property(self, pid: str, role: str, qid: str, count: int = 1) -> None:
        row = self.properties.setdefault((pid, role), {"count": 0, "items": set()})
        row["count"] += count
        row["items"].add(qid)


class Converter:
    def __init__(self, seeds: list[dict[str, str]], entities: dict[str, dict[str, Any]], twins: dict[str, str],
                 datatypes: dict[str, str], idmap: IdMap, languages: tuple[str, ...]) -> None:
        self.seeds, self.entities, self.twins, self.datatypes = seeds, entities, twins, datatypes
        self.idmap, self.languages = idmap, languages
        self.out = Out()
        self.gaps = Gaps()
        self.counter: Counter[tuple[str, str]] = Counter()
        self.resolved = 0                       # item values translated through a twin
        self.stubs: list[str] = []              # Wikidata ids that got a stub, in order of appearance
        self.stub_of: dict[str, str] = {}       # local id of a stub -> its Wikidata id
        self.seed_ids: dict[str, str] = {}
        self.subject = ""
        self.retrieved = ""
        for seed in seeds:                      # a seed that already has a twin keeps that item (nothing is merged here)
            self.seed_ids[seed["qid"]] = twins.get(seed["qid"]) or idmap.get(seed["qid"])
        # A Wikidata item that is the value of "instance of" is a class. Without a local twin it becomes a class stub
        # below the local twin of PARENT_CLASS (software); the importer assumes that, Wikidata does not say it here.
        self.parent = twins.get(PARENT_CLASS) or csvbuild.ROOT
        self.class_qids: set[str] = set()
        for seed in seeds:
            for pid, claims in entities.get(seed["qid"], {}).get("claims", {}).items():
                if twins.get(pid) == INSTANCE:
                    for claim in claims:
                        data = claim["mainsnak"].get("datavalue")
                        if data and data["type"] == "wikibase-entityid":
                            self.class_qids.add(data["value"].get("id", ""))

    # ---- ids

    def item(self, qid: str, count: bool = True) -> str:
        """The local id for a Wikidata item: its twin, the item of a seed, or a stub."""
        if qid in self.seed_ids:
            return self.seed_ids[qid]
        if qid in self.twins:
            self.resolved += count
            return self.twins[qid]
        return self.stub(qid)

    def stub(self, qid: str) -> str:
        entity_id = self.idmap.get(qid)
        if entity_id in self.out.entities:
            return entity_id
        self.stubs.append(qid)
        self.stub_of[entity_id] = qid
        raw = self.entities.get(qid, {})
        is_class = qid in self.class_qids
        row = {"id": entity_id, "kind": "class" if is_class else "item", "datatype": "", "origin": STUB}
        self.texts(row, raw, qid)
        self.out.entities[entity_id] = row
        if is_class:                            # no reference: the placement below the parent is an assumption of the importer
            self.out.statements.append({"sid": f"{entity_id}-{SUBCLASS}-wd1", "subject": entity_id, "property": SUBCLASS,
                                        "value": self.parent, "rank": "", "origin": STUB})
        sid = f"{entity_id}-{TWIN}-wd1"
        self.out.statements.append({"sid": sid, "subject": entity_id, "property": TWIN, "value": qid, "rank": "", "origin": STUB})
        self.out.references.append({"sid": sid, "group": "1", "property": REFERENCE_URL, "value": PAGE + qid})
        return entity_id

    def texts(self, row: dict[str, str], raw: dict[str, Any], qid: str) -> None:
        """Labels, descriptions and aliases in the wanted languages; ``label_en`` always has something."""
        labels = {k: v["value"] for k, v in raw.get("labels", {}).items()}
        if qid == WIKIDATA_ITEM and not labels:
            labels = {"en": WIKIDATA_LABEL}
        for language in self.languages:
            if labels.get(language):
                row[f"label_{language}"] = labels[language]
            text = raw.get("descriptions", {}).get(language, {}).get("value")
            if text:
                row[f"description_{language}"] = text
            aliases = [a["value"] for a in raw.get("aliases", {}).get(language, [])]
            if aliases:
                row[f"aliases_{language}"] = csvio.join_aliases(aliases)
        first = self.languages[0]
        if not row.get(f"label_{first}"):
            fallback = labels.get("mul") or (labels[sorted(labels)[0]] if labels else "")
            if fallback:
                row[f"label_{first}"] = fallback
            else:
                row[f"label_{first}"] = qid
                self.gaps.other[f"{qid}: no label in the raw data (the label is the Wikidata id)"] += 1

    # ---- values

    def value(self, snak: dict[str, Any], local: str, pid: str, qid: str) -> str | None:
        """The CSV value of a Wikidata snak, or ``None`` (and a line in the gaps)."""
        kind = snak.get("snaktype")
        if kind == "somevalue":
            return "?"
        if kind == "novalue":
            return "-"
        data = snak.get("datavalue")
        if not data:
            self.gaps.other[f"{pid}: a snak without a value"] += 1
            return None
        wanted, found = self.datatypes.get(local, ""), snak.get("datatype", "")
        if wanted != found:
            self.gaps.other[f"{pid} -> {local}: datatype {found} at Wikidata, {wanted or 'none'} in the model; not imported"] += 1
            return None
        value, vtype = data["value"], data["type"]
        if vtype == "wikibase-entityid":
            target = value.get("id", "")
            if not QID.match(target):
                self.gaps.other[f"{pid}: a value that is not an item ({target}); not imported"] += 1
                return None
            return self.item(target)
        if vtype == "string":
            return csvio.escape_text(value)
        if vtype == "monolingualtext":
            return f"{value['language']}:{value['text']}"
        if vtype == "time":
            if value.get("calendarmodel", GREGORIAN) != GREGORIAN or value.get("precision", 11) > 11:
                self.gaps.other[f"{pid}: a date outside the Gregorian calendar or finer than a day; not imported"] += 1
                return None
            return csvio.format_time(value)
        if vtype == "quantity":
            amount = str(value["amount"]).lstrip("+")
            unit = str(value.get("unit", "1"))
            if unit == "1":
                return amount
            target = unit.rsplit("/", 1)[-1]
            if not QID.match(target):
                self.gaps.other[f"{pid}: a quantity with an unknown unit; not imported"] += 1
                return None
            return f"{amount} {self.item(target)}"
        if vtype == "globecoordinate":
            if value.get("globe") != csvio.EARTH:
                self.gaps.other[f"{pid}: a coordinate on another globe; not imported"] += 1
                return None
            return csvio.format_coordinate(value)
        self.gaps.other[f"{pid}: a value of type {vtype}; not imported"] += 1
        return None

    # ---- one seed

    def seed(self, qid: str) -> None:
        raw = self.entities[qid]
        self.subject = self.seed_ids[qid]
        modified = DATE.match(raw.get("modified", "") or "")
        self.retrieved = modified.group(1) if modified else ""
        if not self.retrieved:
            self.gaps.other[f"{qid}: no 'modified' in the raw data, so no 'retrieved' date"] += 1
        row = {"id": self.subject, "kind": "item", "datatype": "", "origin": SOURCE}
        self.texts(row, raw, qid)
        self.out.entities[self.subject] = row
        self.add_twin(qid)
        for pid, claims in raw.get("claims", {}).items():
            local = self.twins.get(pid)
            if local is None:
                self.gaps.property(pid, "statement", qid, len(claims))
                continue
            for claim in claims:
                self.statement(local, pid, claim, qid)

    def add_twin(self, qid: str) -> None:
        if self.twins.get(qid) == self.subject:      # an existing twin of someone else's: that item already says it
            return
        sid = f"{self.subject}-{TWIN}-wd1"
        self.out.statements.append({"sid": sid, "subject": self.subject, "property": TWIN, "value": qid, "rank": "", "origin": SOURCE})
        self.out.references.append({"sid": sid, "group": "1", "property": REFERENCE_URL, "value": PAGE + qid})

    def statement(self, local: str, pid: str, claim: dict[str, Any], qid: str) -> None:
        value = self.value(claim["mainsnak"], local, pid, qid)
        if value is None:
            return
        self.counter[(self.subject, local)] += 1
        sid = f"{self.subject}-{local}-wd{self.counter[(self.subject, local)]}"
        rank = claim.get("rank", "normal")
        self.out.statements.append({"sid": sid, "subject": self.subject, "property": local, "value": value,
                                    "rank": "" if rank == "normal" else rank, "origin": SOURCE})
        for qpid in claim.get("qualifiers-order", list(claim.get("qualifiers", {}))):
            qlocal = self.twins.get(qpid)
            for snak in claim.get("qualifiers", {}).get(qpid, []):
                if qlocal is None:
                    self.gaps.property(qpid, "qualifier", qid)
                    continue
                qvalue = self.value(snak, qlocal, qpid, qid)
                if qvalue is not None:
                    self.out.qualifiers.append({"sid": sid, "property": qlocal, "value": qvalue})
        group = 1
        self.reference(sid, group, [(REFERENCE_URL, PAGE + qid)]
                       + ([(RETRIEVED, self.retrieved)] if self.retrieved else [])
                       + [(STATED_IN, self.item(WIKIDATA_ITEM, count=False))])
        for reference in claim.get("references", []):
            rows: list[tuple[str, str]] = []
            for rpid in reference.get("snaks-order", list(reference.get("snaks", {}))):
                rlocal = self.twins.get(rpid)
                for snak in reference.get("snaks", {}).get(rpid, []):
                    if rlocal is None:
                        self.gaps.property(rpid, "reference", qid)
                        continue
                    rvalue = self.value(snak, rlocal, rpid, qid)
                    if rvalue is not None:
                        rows.append((rlocal, rvalue))
            if rows:
                group += 1
                self.reference(sid, group, rows)

    def reference(self, sid: str, group: int, rows: list[tuple[str, str]]) -> None:
        for prop, value in rows:
            self.out.references.append({"sid": sid, "group": str(group), "property": prop, "value": value})


# --------------------------------------------------------------------------- the network


def info(client: Client, ids: list[str]) -> dict[str, dict[str, Any]]:
    """``lastrevid`` and ``modified`` of the ids (one request per 50)."""
    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        data = client.get({"action": "wbgetentities", "ids": "|".join(batch), "props": "info"}, "info")
        for entity_id in batch:
            entity = data.get("entities", {}).get(entity_id)
            if isinstance(entity, dict) and "missing" not in entity and entity.get("lastrevid") is not None:
                found[entity_id] = entity
    return found


def fetch(client: Client, ids: list[str], full: bool, languages: tuple[str, ...]) -> list[dict[str, Any]]:
    """Entities as the API returns them: everything for a seed, info, labels, descriptions and aliases for a stub."""
    got: list[dict[str, Any]] = []
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        params: dict[str, Any] = {"action": "wbgetentities", "ids": "|".join(batch)}
        if not full:
            params.update({"props": "info|labels|descriptions|aliases", "languages": "|".join(languages)})
        data = client.get(params, "fetch" if full else "labels")
        for entity_id in batch:
            entity = data.get("entities", {}).get(entity_id)
            if isinstance(entity, dict) and "missing" not in entity and entity.get("id"):
                got.append(entity)
            else:
                utils.warn(STEP, f"{entity_id} could not be fetched; skipped")
    return got


def refresh(client: Client, raw: Path, ids: list[str], full: bool, languages: tuple[str, ...]) -> tuple[int, int]:
    """Fetch what is new or changed; returns (changed, unchanged)."""
    manifest = load_manifest(raw)
    rows: dict[str, Any] = manifest["entities"]
    current = info(client, ids)
    todo = [i for i in ids if i in current and not is_current(raw, i, rows.get(i), int(current[i]["lastrevid"]))]
    for entity in fetch(client, todo, full, languages):
        rows[entity["id"]] = store_entity(raw, entity)
    manifest["source"] = {"url": "https://www.wikidata.org", "api": client.api}
    write_manifest(raw, manifest)
    return len(todo), len(ids) - len(todo)


def store_saved(folder: Path, raw: Path) -> int:
    """``--from-dir``: put saved JSON files into the raw folder."""
    if not folder.is_dir():
        raise HarvestError(f"--from-dir {folder}: not a directory")
    manifest = load_manifest(raw)
    stored = 0
    for path in sorted(folder.rglob("*.json")):
        try:
            entities = read_saved(path)
        except (ValueError, OSError) as err:
            utils.warn(STEP, f"{path.name}: skipped ({err})")
            continue
        for entity in entities:
            if QID.match(str(entity["id"])):
                manifest["entities"][entity["id"]] = store_entity(raw, entity)
                stored += 1
    manifest["source"] = {"url": "https://www.wikidata.org", "api": API}
    write_manifest(raw, manifest)
    return stored


# --------------------------------------------------------------------------- the report


def normal_url(url: str) -> str:
    url = url.strip().lower().rstrip("/")
    return url[:-4] if url.endswith(".git") else url


RECONCILE = (("repository", "P1324"), ("exact match", "P2888"))     # Wikidata properties whose URLs identify a piece of software


def reconcile(converter: Converter, site: csvbuild.CsvSet) -> list[str]:
    """URLs of the seeds (repository, exact match) that also occur in local items of another origin. A report only.
    A repository URL alone misses a project that moved (Wikidata: RGZM/alligator, open-archaeo: leiza-rse/alligator), which
    is why the exact-match URL (the open-archaeo page) is compared as well."""
    keys = [(name, converter.twins.get(pid)) for name, pid in RECONCILE]
    keys = [(name, local) for name, local in keys if local]
    if not keys:
        return ["reconcile: the model has no property with the twin P1324 or P2888; nothing compared"]
    own = set(converter.seed_ids.values())
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in site.statements.rows:
        for name, local in keys:
            if row["property"] == local and row.get("origin", "") not in ORIGINS and row["subject"] not in own:
                owners[(name, normal_url(row["value"]))].add(row["subject"])
    lines, compared = [], 0
    by_local = {local: name for name, local in keys}
    for qid, local_id in converter.seed_ids.items():
        for statement in converter.out.statements:
            name = by_local.get(statement["property"])
            if name and statement["subject"] == local_id:
                compared += 1
                for other in sorted(owners.get((name, normal_url(statement["value"])), ())):
                    lines.append(f"  {qid} ({local_id}) and {other} share the {name} URL {statement['value']}")
    head = f"reconcile with the other local items by URL ({', '.join(n for n, _l in keys)}): {compared} URL(s) compared, {len(lines)} found in both"
    return [head] + lines


def report_lines(converter: Converter, seeds: list[dict[str, str]], reconciled: list[str]) -> list[str]:
    """The report, a function of the input only (it is written to dist/ and must not change between two runs)."""
    out = converter.out
    lines = [f"{len(seeds)} seed(s): " + ", ".join(f"{s['qid']} ({converter.seed_ids[s['qid']]}{', ' + s['kind'] if s['kind'] else ''})" for s in seeds)]
    lines.append(f"items: {len(seeds)} seed(s), {len(converter.stubs)} stub(s); {converter.resolved} item value(s) translated "
                 f"through an existing twin")
    lines.append(f"rows from the importer: {len(out.entities)} entities, {len(out.statements)} statements, "
                 f"{len(out.qualifiers)} qualifiers, {len(out.references)} references")
    pairs = sorted(converter.gaps.properties.items())
    properties = {pid for (pid, _role), _row in pairs}
    lines.append(f"Wikidata properties without a twin in the model: {len(properties)} ({sum(r['count'] for _k, r in pairs)} snak(s))")
    for (pid, role), row in pairs:
        lines.append(f"  {pid} as {role}: {row['count']}x in {', '.join(sorted(row['items']))}")
    for text, count in sorted(converter.gaps.other.items()):
        lines.append(f"not imported ({count}x): {text}")
    classes = [local for local in out.entities if out.entities[local]["kind"] == "class"]
    if classes:
        named = ", ".join(f"{local} ({converter.stub_of[local]}, {out.entities[local].get('label_en', '')})"
                          for local in sorted(classes, key=id_sort_key))
        lines.append(f"{len(classes)} class stub(s) for types without a local twin, assumed to be subclasses of {converter.parent}: {named}")
    return lines + reconciled


def gap_file(converter: Converter) -> str:
    rows = [{"wikidata_property": pid, "role": role, "snaks": str(row["count"]), "items": "|".join(sorted(row["items"]))}
            for (pid, role), row in sorted(converter.gaps.properties.items())]
    return csvio.render_table(["wikidata_property", "role", "snaks", "items"], rows)


# --------------------------------------------------------------------------- the step


def build_parser() -> argparse.ArgumentParser:
    csv_dir = utils.ROOT / "data" / "csv"
    parser = argparse.ArgumentParser(prog="python main.py import-wikidata",
                                     description="Wikidata items (the seeds) -> CSV tables.")
    parser.add_argument("--csv", type=Path, default=csv_dir, help="folder with the CSV tables")
    parser.add_argument("--seeds", type=Path, default=csv_dir / "seeds-wikidata.csv")
    parser.add_argument("--raw", type=Path, default=utils.DATA_RAW / "wikidata", help="folder for the raw Wikidata JSON")
    parser.add_argument("--languages", default=",".join(DEFAULT_LANGUAGES), help="labels and descriptions to import")
    parser.add_argument("--offline", action="store_true", help="no network: use what is in the raw folder")
    parser.add_argument("--from-dir", metavar="DIR", type=Path, help="store saved JSON files in the raw folder first")
    parser.add_argument("--dry-run", action="store_true", help="print the report, write nothing (implies --offline)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: 1)")
    parser.add_argument("--maxlag", type=float, default=0.0,
                        help="send maxlag=N seconds (default: 0 = off; Wikidata counts the lag of its query service, which is often above 5 s and irrelevant for reading)")
    parser.add_argument("--contact", help="contact named in the User-Agent; or set WBS_CONTACT")
    return parser


def convert(seeds, raw_entities, site, kernel, idmap, languages) -> Converter:
    twins = twin_map(site, kernel, ORIGINS)
    converter = Converter(seeds, raw_entities, twins, property_datatypes(kernel, site), idmap, languages)
    for seed in seeds:
        converter.seed(seed["qid"])
    return converter


def main(argv: list[str] | None = None, client: Client | None = None) -> int:
    args = build_parser().parse_args(argv)
    languages = tuple(code.strip() for code in args.languages.split(",") if code.strip()) or DEFAULT_LANGUAGES
    if args.from_dir and args.dry_run:
        print(f"ERROR: [{STEP}] --from-dir writes the raw folder, --dry-run writes nothing; use one of them")
        return 2
    try:
        seeds = read_seeds(args.seeds)
    except ImportProblem as err:
        print(f"ERROR: [{STEP}] {err}")
        return 2
    if not seeds:
        utils.nothing_to_do(STEP, f"{shown(args.seeds)} lists no seed")
        return 0

    problems: list[str] = []
    site = csvbuild.read_set(args.csv, problems, shown(args.csv))
    kernel = csvbuild.kernel_set()
    existing = {"entities.csv": site.entities, "statements.csv": site.statements,
                "qualifiers.csv": site.qualifiers, "references.csv": site.references}
    for table in existing.values():
        table.columns = list(table.columns)
    idmap_rows = read_rows(args.csv / "idmap.csv", ["source", "key", "id"], "idmap") if (args.csv / "idmap.csv").is_file() else []
    taken = {r["id"] for r in site.entities.rows} | {r["subject"] for r in site.statements.rows}
    wanted = [s["qid"] for s in seeds]
    fetched: tuple[int, int] | None = None

    try:
        if args.from_dir:
            print(f"[{STEP}] {store_saved(args.from_dir, args.raw)} entity file(s) stored in {shown(args.raw)}")
        online = not (args.offline or args.dry_run or args.from_dir)
        if online:
            contact = args.contact or os.environ.get("WBS_CONTACT") or "https://github.com/n4o-rse/wikibase-static"
            client = client or Client(API, f"wikibase-static/{__version__} (+{contact}; static archive, read-only)", delay=args.delay, maxlag=args.maxlag)
            changed, same = refresh(client, args.raw, wanted, True, languages)
            first = convert(seeds, load_raw(args.raw), site, kernel, IdMap(idmap_rows, taken, SOURCE), languages)
            more = sorted(set(first.stubs) - set(wanted))
            c2, s2 = refresh(client, args.raw, more, False, languages) if more else (0, 0)
            fetched = (changed + c2, same + s2)
        raw_entities = load_raw(args.raw)
        missing = [q for q in wanted if q not in raw_entities]
        if missing:
            print(f"ERROR: [{STEP}] no raw data for {', '.join(missing)} in {shown(args.raw)}; run without --offline "
                  "or give the files with --from-dir")
            return 2
        idmap = IdMap(idmap_rows, taken, SOURCE)
        converter = convert(seeds, raw_entities, site, kernel, idmap, languages)
    except (HarvestError, ImportProblem) as err:
        print(f"ERROR: [{STEP}] {err}")
        return getattr(err, "code", 2)

    merged = merge(existing, converter.out, ORIGINS)
    reconciled = reconcile(converter, site)
    lines = report_lines(converter, seeds, reconciled)
    run = ([f"fetched {fetched[0]} changed, {fetched[1]} unchanged"] if fetched is not None else []) \
        + [f"{idmap.new} new id(s) in idmap.csv; {merged.replaced} earlier importer statement(s) replaced; hand rows protect "
           f"{merged.skipped + merged.kept_by_hand} ({merged.skipped} not written, {merged.kept_by_hand} kept)"]
    for line in run[:-1] + lines + run[-1:]:
        print(f"[{STEP}] {line}")
    # A gap is a report, not a warning: nothing here starts with WARN, so --strict stays usable.
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
    if not args.dry_run:
        for name, text in ((REPORT, "\n".join(lines) + "\n"), ("wikidata-gaps.csv", gap_file(converter))):
            target = args.csv.parent.parent / "dist" / name
            if not target.is_file() or target.read_bytes() != (text.rstrip("\n") + "\n").encode("utf-8"):
                utils.write_text(target, text)
    print(f"[{STEP}] {written} file(s) {'would change' if args.dry_run else 'written'} in {shown(args.csv)}")
    for message in sorted(set(problems)):
        utils.warn(STEP, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
