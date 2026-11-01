"""S15a -- import the version history of OpenStreetMap elements into the CSV tables (a verb of its own, offline in 0.20.0).

    python main.py import-osm --offline                 every file of data/raw/osm/history/
    python main.py import-osm --offline --from-dir DIR  another folder of history files
    python main.py import-osm --offline --dry-run       print the report, write nothing

Reads one file per element, ``data/raw/osm/history/<type>_<id>.json`` (the answer of ``GET /api/0.6/<type>/<id>/history.json``,
never edited), the role map ``data/csv/mapping/osm-properties.csv`` (columns ``role, id, kind, note``: which local property
carries which part of an OSM version) and the selection ``data/seeds/<name>.csv`` (columns ``selection, key, value``: the tag
condition an element has to meet; an empty ``value`` means the key only has to be there). It writes rows with ``origin=osm``
into the four tables in ``data/csv/`` and into ``idmap.csv``. It never writes Wikibase JSON; ``from-csv`` does that.

The model (PRIMER.md of osm-benchmarks-static, A2 and A4):

    one item per OSM element, never per version; ``instance of`` the class ``class_benchmark``; the id comes from ``idmap.csv``
    (source ``osm``, key ``node/6666122939``)
    ``element``            the URL of the element
    ``version``            one statement per version: the URL ``.../<type>/<id>/history/<n>``; qualifiers version number, timestamp,
                           changeset, user name, uid; the last version has rank ``preferred``
    ``selection_since``    the URL of the first version of each run of versions that meet the tag condition; qualifier selection
                           name; qualifier ``selection_until`` (the last version of the run) only when the element left it
    ``coordinate``         the position of the last version (for the map and the search)
    ``geometry_history``   WKT, one statement per change of position, qualifiers version number and timestamp
    ``image``              the Commons file of the tag ``wikimedia_commons`` of the last version
    ``tag``                every other tag of the last version as ``key=value``; older tags stay at OpenStreetMap

Only nodes are imported in 0.20.0; a way or a relation is reported and left out (their geometry needs a Wikibase-side WKT, S15b).
The label is ``name``, then ``name:en``, then the title of the Commons file, then ``OSM node <id>``. Statements carry a reference
(P6, the URL of the version they were read from), except ``element`` and ``version``, which are that URL themselves. Reimport:
every row with ``origin=osm`` is replaced; a row whose ``origin`` was emptied counts as written by hand and wins. No clock: the
output depends on the input files only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_import_osm.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvbuild, csvio, utils
from wikibase_static.step_import_open_archaeo import IdMap, ImportProblem, Out, merge, read_rows, shown

STEP = "import-osm"
SOURCE = "osm"
INSTANCE, REFERENCE_URL = "P2", "P6"
OSM = "https://www.openstreetmap.org"
ROLES = ("class_benchmark", "element", "version", "version_number", "timestamp", "changeset", "user_name", "user_id",
         "selection_since", "selection_until", "selection_name", "coordinate", "geometry_history", "image", "tag")
FILE_NAME = re.compile(r"^(node|way|relation)_([1-9][0-9]*)\.json$")
COMMONS_FILE = re.compile(r"^File:(.+)$")


# --------------------------------------------------------------------------- reading


def read_roles(path: Path) -> dict[str, str]:
    """role -> local id, from the role map; every role has to be there exactly once."""
    rows = read_rows(path, ["role", "id"], "role map")
    found: dict[str, str] = {}
    for number, row in enumerate(rows, start=2):
        role = row["role"].strip()
        if role not in ROLES:
            raise ImportProblem(f"role map: {path.name}:{number}: unknown role {role!r} (known: {', '.join(ROLES)})")
        if role in found:
            raise ImportProblem(f"role map: {path.name}:{number}: role {role!r} twice")
        found[role] = row["id"].strip()
    missing = [r for r in ROLES if r not in found]
    if missing:
        raise ImportProblem(f"role map: {path.name} has no row for {', '.join(missing)}")
    return found


def read_selection(folder: Path, name: str) -> list[tuple[str, str]]:
    """The tag condition of the selection ``name``: (key, value) pairs; an empty value means the key has to exist."""
    path = folder / f"{name}.csv"
    rows = read_rows(path, ["selection", "key", "value"], "selection")
    pairs = [(r["key"].strip(), r["value"].strip()) for r in rows if r["selection"].strip() == name and r["key"].strip()]
    if not pairs:
        raise ImportProblem(f"selection: {path.name} has no condition for {name!r}")
    return pairs


def meets(tags: dict[str, str], condition: list[tuple[str, str]]) -> bool:
    return all((key in tags and tags[key] != "") if value == "" else tags.get(key) == value for key, value in condition)


@dataclass
class Element:
    kind: str
    number: int
    versions: list[dict]        # sorted by version

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.number}"

    def url(self, version: int | None = None) -> str:
        base = f"{OSM}/{self.kind}/{self.number}"
        return base if version is None else f"{base}/history/{version}"


def read_element(path: Path) -> Element:
    match = FILE_NAME.match(path.name)
    if not match:
        raise ImportProblem(f"input: {path.name} is not named <node|way|relation>_<id>.json")
    kind, number = match.group(1), int(match.group(2))
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as err:
        raise ImportProblem(f"input: {path.name}:{err.lineno}: not valid JSON ({err.msg})") from err
    except (OSError, ValueError) as err:
        raise ImportProblem(f"input: {path.name}: not readable ({str(err).splitlines()[0]})") from err
    versions = [e for e in data.get("elements", []) if isinstance(e, dict)]
    if not versions:
        raise ImportProblem(f"input: {path.name} holds no element")
    for e in versions:
        if e.get("type") != kind or e.get("id") != number or not isinstance(e.get("version"), int):
            raise ImportProblem(f"input: {path.name} holds an element that is not {kind}/{number} with a version number")
    versions.sort(key=lambda e: e["version"])
    numbers = [e["version"] for e in versions]
    if len(set(numbers)) != len(numbers):
        raise ImportProblem(f"input: {path.name} has a version twice")
    return Element(kind, number, versions)


def coord(value: float) -> str:
    return format(value, ".7f").rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- the import


class Importer:
    def __init__(self, roles: dict[str, str], condition: list[tuple[str, str]], selection: str, idmap: IdMap) -> None:
        self.roles, self.condition, self.selection, self.idmap = roles, condition, selection, idmap
        self.out = Out()
        self.gaps: Counter[str] = Counter()
        self.kinds: Counter[str] = Counter()
        self.versions = 0

    def add(self, subject: str, role: str, value: str, tag: str, qualifiers: list[tuple[str, str]] | None = None,
            rank: str = "", reference: str = "") -> None:
        prop = self.roles[role]
        sid = f"{subject}-{prop}-{tag}"
        self.out.statements.append({"sid": sid, "subject": subject, "property": prop, "value": value, "rank": rank, "origin": SOURCE})
        for qrole, qvalue in qualifiers or []:
            self.out.qualifiers.append({"sid": sid, "property": self.roles[qrole], "value": qvalue})
        if reference:
            self.out.references.append({"sid": sid, "group": "1", "property": REFERENCE_URL, "value": reference})

    def element(self, element: Element) -> None:
        if element.kind != "node":
            self.gaps[f"{element.kind} (geometry needs S15b)"] += 1
            return
        versions = element.versions
        live = [v for v in versions if v.get("visible", True) and "lat" in v and "lon" in v]
        if not live:
            self.gaps["node without a position in any version"] += 1
            return
        for v in versions:
            if not v.get("visible", True) or "lat" not in v:
                self.gaps["version without a position (a deletion); no version statement"] += 1
        last = live[-1]
        subject = self.idmap.get(element.key)
        label = self.label(element, last)
        row = {"id": subject, "kind": "item", "datatype": "", "origin": SOURCE, "label_en": label,
               "description_en": f"OpenStreetMap {element.kind} {element.number}"}
        self.out.entities[subject] = row
        self.kinds[element.kind] += 1

        self.out.statements.append({"sid": "", "subject": subject, "property": INSTANCE,
                                    "value": self.roles["class_benchmark"], "rank": "", "origin": SOURCE})
        self.add(subject, "element", element.url(), "1")

        for v in live:
            self.versions += 1
            number = v["version"]
            self.add(subject, "version", element.url(number), str(number),
                     [("version_number", str(number)), ("timestamp", str(v.get("timestamp", ""))),
                      ("changeset", str(v.get("changeset", ""))), ("user_name", csvio.escape_text(str(v.get("user", "")))),
                      ("user_id", str(v.get("uid", "")))],
                     rank="preferred" if v is last else "")

        self.selection_runs(subject, element, live)

        ref = element.url(last["version"])
        self.add(subject, "coordinate", f"{coord(last['lat'])},{coord(last['lon'])}", "1", reference=ref)
        previous = None
        for v in live:
            here = (v["lat"], v["lon"])
            if here == previous:
                continue
            previous = here
            self.add(subject, "geometry_history", f"POINT({coord(v['lon'])} {coord(v['lat'])})", str(v["version"]),
                     [("version_number", str(v["version"])), ("timestamp", str(v.get("timestamp", "")))],
                     reference=element.url(v["version"]))

        tags = last.get("tags") or {}
        commons = tags.get("wikimedia_commons", "")
        if commons:
            match = COMMONS_FILE.match(commons)
            if match:
                self.add(subject, "image", csvio.escape_text(match.group(1).replace("_", " ")), "1", reference=ref)
            else:
                self.gaps["wikimedia_commons that is not a File: (a category, for example)"] += 1
        for number, (key, value) in enumerate(sorted((k, v) for k, v in tags.items() if k != "wikimedia_commons"), start=1):
            self.add(subject, "tag", csvio.escape_text(f"{key}={value}"), str(number), reference=ref)

    def selection_runs(self, subject: str, element: Element, live: list[dict]) -> None:
        """Runs of consecutive versions that meet the condition: ``selection_since`` for each, ``selection_until`` when it ended."""
        runs: list[list[dict]] = []
        inside = False
        for v in element.versions:
            ok = v in live and meets(v.get("tags") or {}, self.condition)
            if ok and inside:
                runs[-1].append(v)
            elif ok:
                runs.append([v])
            inside = ok
        if not runs:
            self.gaps["element that never met the selection"] += 1
        for run in runs:
            first, last = run[0], run[-1]
            qualifiers = [("selection_name", self.selection)]
            if last is not element.versions[-1]:
                qualifiers.append(("selection_until", element.url(last["version"])))
            self.add(subject, "selection_since", element.url(first["version"]), str(first["version"]), qualifiers)

    def label(self, element: Element, last: dict) -> str:
        tags = last.get("tags") or {}
        for key in ("name", "name:en"):
            if tags.get(key):
                return tags[key]
        match = COMMONS_FILE.match(tags.get("wikimedia_commons", ""))
        if match:
            title = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", match.group(1).replace("_", " "))
            if title:
                return title
        return f"OSM {element.kind} {element.number}"


# --------------------------------------------------------------------------- the step


def check_roles(roles: dict[str, str], entities: set[str]) -> list[str]:
    return [f"role map: {role} -> {pid} is not an entity of this site" for role, pid in sorted(roles.items()) if pid not in entities]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py import-osm",
                                     description="OSM element histories -> CSV tables (offline in 0.20.0).")
    csv_dir = utils.ROOT / "data" / "csv"
    parser.add_argument("--csv", type=Path, default=csv_dir, help="folder with the CSV tables")
    parser.add_argument("--from-dir", type=Path, default=utils.DATA_RAW / "osm" / "history",
                        help="folder with <type>_<id>.json files (default data/raw/osm/history)")
    parser.add_argument("--mapping", type=Path, default=csv_dir / "mapping" / "osm-properties.csv")
    parser.add_argument("--seeds", type=Path, default=utils.ROOT / "data" / "seeds", help="folder with the selections")
    parser.add_argument("--selection", default="benchmarks", help="name of the selection (default benchmarks)")
    parser.add_argument("--offline", action="store_true", help="read the files of --from-dir (the only mode of 0.20.0)")
    parser.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    args = parser.parse_args(argv)

    try:
        roles = read_roles(args.mapping)
        condition = read_selection(args.seeds, args.selection)
        if not args.from_dir.is_dir():
            raise ImportProblem(f"input: {args.from_dir} does not exist")
        files = sorted(p for p in args.from_dir.iterdir() if p.suffix == ".json")
        elements = [read_element(p) for p in files]
    except ImportProblem as err:
        print(f"ERROR: [{STEP}] {err}")
        return 2
    if not elements:
        utils.nothing_to_do(STEP, f"no history files in {shown(args.from_dir)}")
        return 0

    problems: list[str] = []
    site = csvbuild.read_set(args.csv, problems, shown(args.csv))
    existing = {"entities.csv": site.entities, "statements.csv": site.statements,
                "qualifiers.csv": site.qualifiers, "references.csv": site.references}
    for table in existing.values():
        table.columns = list(table.columns)
    entity_ids = {r["id"] for r in site.entities.rows}
    messages = check_roles(roles, entity_ids)
    idmap_rows = read_rows(args.csv / "idmap.csv", ["source", "key", "id"], "idmap") if (args.csv / "idmap.csv").is_file() else []
    idmap = IdMap(idmap_rows, entity_ids | {r["subject"] for r in site.statements.rows}, SOURCE)

    # an element that a person described by hand is not described a second time
    by_hand = {r["value"]: r["subject"] for r in site.statements.rows
               if r["property"] == roles["element"] and r.get("origin", "") != SOURCE}
    importer = Importer(roles, condition, args.selection, idmap)
    for element in elements:
        if element.url() in by_hand and idmap.ids.get((SOURCE, element.key)) != by_hand[element.url()]:
            messages.append(f"{element.key} is already described by hand as {by_hand[element.url()]}; "
                            f"importing it would make a second item (map it with the row `osm,{element.key},{by_hand[element.url()]}` in idmap.csv, "
                            f"or remove the hand-made rows)")
        importer.element(element)
    merged = merge(existing, importer.out, (SOURCE,))

    print(f"[{STEP}] {len(files)} history file(s) in {shown(args.from_dir)}; selection {args.selection}: "
          + " and ".join(f"{k}" + (f"={v}" if v else "") for k, v in condition))
    print(f"[{STEP}] items: {len(importer.out.entities)} ({', '.join(f'{n} {k}' for k, n in sorted(importer.kinds.items())) or 'none'}); "
          f"{importer.versions} version statement(s); {idmap.new} new id(s) in idmap.csv")
    print(f"[{STEP}] rows from the importer: {len(importer.out.entities)} entities, {len(importer.out.statements)} statements, "
          f"{len(importer.out.qualifiers)} qualifiers, {len(importer.out.references)} references; "
          f"{merged.replaced} earlier importer statement(s) replaced; hand rows protect {merged.skipped + merged.kept_by_hand}")
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
    for message in sorted(set(messages)):
        utils.warn(STEP, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
