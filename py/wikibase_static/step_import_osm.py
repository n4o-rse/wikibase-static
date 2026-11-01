"""S15a/S5 -- harvest the version history of OpenStreetMap elements and import it into the CSV tables (a verb of its own).

    python main.py import-osm                           ask Overpass, fetch what is new or changed, then import
    python main.py import-osm --probe                   one Overpass request: say what would be fetched, write nothing
    python main.py import-osm --refresh                 fetch every history again and compare it with the stored one
    python main.py import-osm --offline                 no network: import every file of data/raw/osm/history/
    python main.py import-osm --offline --from-dir DIR  another folder of history files
    python main.py import-osm --offline --dry-run       print the report, write nothing
    python main.py import-osm --element way/123         fetch this element and its members (no Overpass), then import

The network part (``osm_net.py``): the Overpass query of the selection, ``data/seeds/overpass-<selection>.overpassql`` (``out meta``,
no ``geom``), is sent once; its answer is stored byte for byte in ``data/raw/osm/overpass/<selection>.json`` when the list of
(element, version) in it has changed. Each element it names is compared with the history file on disk: new (no file) or changed (a
higher version) elements get ``GET /api/0.6/<type>/<id>/history.json`` and the answer is stored byte for byte in
``data/raw/osm/history/<type>_<id>.json``; the others cost no request. A second run without any change at OpenStreetMap therefore
sends one Overpass request and nothing else. An element that is in the history folder but no longer in the Overpass answer has left
the area (or was deleted): its last run of versions in the selection gets ``selection_until``. ``--limit N`` caps the history
requests of one run (default 100, so a large first run is spread over several), ``--delay`` is the pause between requests (default 1 s),
``--contact`` names a contact in the User-Agent (or set WBS_CONTACT). ``--probe`` and, with the network, ``--dry-run`` send the Overpass request only.

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

A way or a relation (0.22.0, S15b) is an item like a node; its ``geometry_history`` entries are WKT built by ``osm_geom`` from the
stored histories of its members (``data/raw/osm/members/``, fetched by the network part), one entry each time the shape changed
(version of the element, or of a member node, qualifier timestamp = that moment; statement ids ``g1``, ``g2``, ...); its
``coordinate`` is the middle of the bounding box of the last shape. Without the member histories the item is imported without a shape
and the report says how many are missing. ``--element way/123`` fetches one element and its members without asking Overpass.
The label is ``name``, then ``name:en``, then the title of the Commons file (cleaned: ``_`` and a CamelCase run become spaces, a
`` - geograph.org.uk - <number>`` tail goes), then the inscription, then ``OSM node <id>``; the German label is the same text
(names and titles are not translated), only the last resort is German (``OSM-Node <id>``). The description says what the thing is
and where it comes from, in English and German (0.23.0): "Milestone, inscription “P.O Dublin 8 Howth 1” (OpenStreetMap node 1234)",
"Meilenstein, Inschrift „P.O Dublin 8 Howth 1“ (OpenStreetMap-Node 1234)". Statements carry a reference
(P6, the URL of the version they were read from), except ``element`` and ``version``, which are that URL themselves. Reimport:
every row with ``origin=osm`` is replaced; a row whose ``origin`` was emptied counts as written by hand and wins. No clock: the
output depends on the input files only.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_import_osm.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, csvbuild, csvio, osm_geom, osm_net, utils, wkt
from wikibase_static.step_harvest import DEFAULT_CONTACT
from wikibase_static.step_import_open_archaeo import IdMap, ImportProblem, Out, merge, read_rows, shown

STEP = "import-osm"
CLIENT_FACTORY = None      # the tests put a client with a fake transport here
SOURCE = "osm"
INSTANCE, REFERENCE_URL = "P2", "P6"
OSM = "https://www.openstreetmap.org"
ROLES = ("class_benchmark", "element", "version", "version_number", "timestamp", "changeset", "user_name", "user_id",
         "selection_since", "selection_until", "selection_name", "coordinate", "geometry_history", "image", "tag")
FILE_NAME = re.compile(r"^(node|way|relation)_([1-9][0-9]*)\.json$")
COMMONS_FILE = re.compile(r"^File:(.+)$")
GEOGRAPH_TAIL = re.compile(r"\s+-\s+geograph\.org\.uk\s+-\s+\d+$")
CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z])")
# (English, German) by the tag that tells the thing apart; the first match wins, the last row is the fallback
THINGS = (("historic", "milestone", "Milestone", "Meilenstein"), ("", "", "Benchmark", "Höhenmarke"))
KINDS = {"node": ("node", "Node"), "way": ("way", "Weg"), "relation": ("relation", "Relation")}


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
    def __init__(self, roles: dict[str, str], condition: list[tuple[str, str]], selection: str, idmap: IdMap,
                 present: dict[str, int] | None = None) -> None:
        self.roles, self.condition, self.selection, self.idmap = roles, condition, selection, idmap
        self.present = present            # key -> version of the last Overpass answer; None: no answer stored, nobody has left
        self.left = 0
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

    def element(self, element: Element, store: "osm_geom.Store | None" = None) -> None:
        versions = element.versions
        shape = None
        if element.kind == "node":
            live = [v for v in versions if v.get("visible", True) and "lat" in v and "lon" in v]
            if not live:
                self.gaps["node without a position in any version"] += 1
                return
        else:
            live = [v for v in versions if v.get("visible", True)]
            if not live:
                self.gaps[f"{element.kind} that is deleted in every version"] += 1
                return
            shape = osm_geom.events(element.kind, versions, store or osm_geom.Store())
            if not shape.events:
                missing = len(shape.missing)
                self.gaps[f"{element.kind} without a shape ({missing} member histor{'y' if missing == 1 else 'ies'} not stored; "
                          f"run import-osm with the network)" if missing else f"{element.kind} without a shape"] += 1
            for note in shape.notes:
                self.gaps[f"{element.key}: {note}"] += 1
        for v in versions:
            if not v.get("visible", True) or (element.kind == "node" and "lat" not in v):
                self.gaps["version without a position (a deletion); no version statement"] += 1
        last = live[-1]
        subject = self.idmap.get(element.key)
        label = self.label(element, last)
        description_en, description_de = self.describe(element, last)
        row = {"id": subject, "kind": "item", "datatype": "", "origin": SOURCE, "label_en": label,
               "label_de": label if not label.startswith("OSM ") else f"OSM-{KINDS[element.kind][1]} {element.number}",
               "description_en": description_en, "description_de": description_de}
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
        if shape is None:
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
        elif shape.events:
            lat, lon = wkt.centre(wkt.parse(shape.events[-1].wkt))
            self.add(subject, "coordinate", f"{coord(lat)},{coord(lon)}", "1", reference=element.url(shape.events[-1].version))
            for number, event in enumerate(shape.events, start=1):
                self.add(subject, "geometry_history", event.wkt, f"g{number}",
                         [("version_number", str(event.version)), ("timestamp", event.time)],
                         reference=element.url(event.version))

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
        gone = self.present is not None and element.key not in self.present
        if gone and runs:
            self.left += 1
        for run in runs:
            first, last = run[0], run[-1]
            qualifiers = [("selection_name", self.selection)]
            if last is not element.versions[-1] or (gone and run is runs[-1]):
                qualifiers.append(("selection_until", element.url(last["version"])))
            self.add(subject, "selection_since", element.url(first["version"]), str(first["version"]), qualifiers)

    def label(self, element: Element, last: dict) -> str:
        tags = last.get("tags") or {}
        for key in ("name", "name:en"):
            if tags.get(key):
                return tags[key]
        match = COMMONS_FILE.match(tags.get("wikimedia_commons", ""))
        if match:
            title = clean_title(match.group(1))
            if title:
                return title
        if tags.get("inscription"):
            return f"{self.thing(last)[0]} {tags['inscription']}"
        return f"OSM {element.kind} {element.number}"

    @staticmethod
    def thing(last: dict) -> tuple[str, str]:
        tags = last.get("tags") or {}
        for key, value, english, german in THINGS:
            if not key or tags.get(key) == value:
                return english, german
        return THINGS[-1][2:]

    def describe(self, element: Element, last: dict) -> tuple[str, str]:
        """What it is and where it comes from, English and German; the inscription (if any) is quoted."""
        english, german = self.thing(last)
        inscription = " ".join(str((last.get("tags") or {}).get("inscription", "")).split())
        kind_en, kind_de = KINDS[element.kind]
        en = english + (f", inscription \u201c{inscription}\u201d" if inscription else "")
        de = german + (f", Inschrift \u201e{inscription}\u201c" if inscription else "")
        return f"{en} (OpenStreetMap {kind_en} {element.number})", f"{de} (OpenStreetMap-{kind_de} {element.number})"


def clean_title(name: str) -> str:
    """The title of a Commons file as a label: no extension, no geograph tail, spaces for ``_`` and for CamelCase."""
    title = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name.replace("_", " ")).strip()
    title = GEOGRAPH_TAIL.sub("", title).strip()
    if " " not in title:
        title = CAMEL.sub(" ", title)
    return title


# --------------------------------------------------------------------------- the network part


def run_network(args: argparse.Namespace, client: "osm_net.OsmClient | None" = None) -> int | None:
    """Ask Overpass, fetch the new and changed histories, store the answers. Returns an exit code when the run is over
    (probe, error), ``None`` when the import is to follow."""
    query_file = args.query or args.seeds / f"overpass-{args.selection}.overpassql"
    if not query_file.is_file():
        print(f"ERROR: [{STEP}] the Overpass query {shown(query_file)} does not exist; the selection {args.selection!r} needs one for the network "
              f"(or run with --offline)")
        return 2
    query = query_file.read_text(encoding="utf-8")
    if "out meta" not in query or "geom" in query.split("out meta", 1)[1].split(";", 1)[0]:
        print(f"ERROR: [{STEP}] {shown(query_file)} has to end with `out meta;` (no `geom`: the history comes from the API, not from Overpass)")
        return 2
    contact = args.contact or os.environ.get("WBS_CONTACT") or DEFAULT_CONTACT
    client = client or osm_net.OsmClient(f"wikibase-static/{__version__} (+{contact}; static archive, read-only)", delay=args.delay)
    history_dir = args.from_dir
    overpass_path = args.overpass_file or utils.DATA_RAW / "osm" / "overpass" / f"{args.selection}.json"
    try:
        stored = osm_net.stored_histories(history_dir)
        if args.element:
            body, answer = b"", {}
            todo = sorted(set(args.element))
            plan = osm_net.Plan(new=[k for k in todo if k not in stored], changed=[k for k in todo if k in stored])
            probing = args.probe or args.dry_run
            print(f"[{STEP}] --element: {len(todo)} element(s) named, Overpass is not asked; stored histories: {len(stored)}")
        else:
            body = client.fetch(args.overpass, "overpass", data={"data": query}, timeout=240.0)
            answer = osm_net.parse_overpass(body)
            plan = osm_net.make_plan(answer, stored)
            todo = plan.to_fetch(args.refresh)
            probing = args.probe or args.dry_run
            requests = client.by_kind.get("overpass", 1)
            print(f"[{STEP}] Overpass: {len(answer)} element(s) in the answer ({requests} request{'' if requests == 1 else 's'}); "
                  f"stored histories: {len(stored)}; "
                  f"new {len(plan.new)}, changed {len(plan.changed)}, unchanged {len(plan.unchanged)}, no longer in the answer {len(plan.gone)}")
            if plan.gone:
                print(f"[{STEP}] no longer in the answer (left the area, or deleted): " + ", ".join(plan.gone[:10]) + (" ..." if len(plan.gone) > 10 else ""))
        if probing:
            print(f"[{STEP}] probe: {len(todo)} history request(s) would follow{' (--refresh)' if args.refresh else ''}; nothing written")
            return 0
        if not args.element and osm_net.stored_overpass(overpass_path) != answer:
            overpass_path.parent.mkdir(parents=True, exist_ok=True)
            overpass_path.write_bytes(body)
            print(f"[{STEP}] stored the Overpass answer: {shown(overpass_path)}")
        batch, rest = todo[:args.limit], todo[args.limit:]
        history_dir.mkdir(parents=True, exist_ok=True)
        new_versions = changed_versions = same = differ = 0
        differing: list[str] = []
        for key in batch:
            raw = client.fetch(osm_net.history_url(args.api, key), "history")
            elements = osm_net.check_history(key, raw)
            if key in answer and max(e["version"] for e in elements) != answer[key]:
                utils.warn(STEP, f"{key}: Overpass says version {answer[key]}, the history ends at {max(e['version'] for e in elements)}; "
                                 f"the history is stored, a later run settles it")
            path = history_dir / f"{key.replace('/', '_')}.json"
            if key in stored:
                old = osm_net.check_history(key, path.read_bytes())
                if osm_net.same_in_common(old, elements):
                    same += 1
                else:
                    differ += 1
                    differing.append(key)
                changed_versions += max(0, len(elements) - len(old))
            else:
                new_versions += len(elements)
            path.write_bytes(raw)
        print(f"[{STEP}] fetched {len(batch)} histor{'y' if len(batch) == 1 else 'ies'} "
              f"({client.by_kind.get('history', 0)} history request(s), {client.by_kind.get('overpass', 0)} Overpass request(s)): "
              f"{len([k for k in batch if k in plan.new])} new element(s) with {new_versions} version(s), "
              f"{len([k for k in batch if k not in plan.new])} known element(s) with {changed_versions} new version(s)")
        if args.refresh and batch:
            print(f"[{STEP}] refresh: {same} stored histor{'y' if same == 1 else 'ies'} agree with the API in the versions they share, {differ} differ")
            for key in differing[:10]:
                utils.warn(STEP, f"{key}: a stored version differs from what the API says now (the stored file was replaced)")
        if rest:
            print(f"[{STEP}] {len(rest)} element(s) are left for the next run (--limit {args.limit})")
        fetch_members(args, client, history_dir)
        return None
    except osm_net.Unreachable as err:
        print(f"ERROR: [{STEP}] {err}\n  the network is needed for this run; with --offline the stored files are imported instead")
        return 1
    except osm_net.OsmError as err:
        print(f"ERROR: [{STEP}] {err}")
        return 1


def fetch_members(args: argparse.Namespace, client: "osm_net.OsmClient", history_dir: Path) -> None:
    """The histories of the nodes of every way and of the ways and nodes of every relation, into ``--members-dir``.

    A way has no coordinates; its shape needs each node's history (S15b). New members are fetched; with ``--refresh`` every needed member
    is fetched again and compared. A member that is found only after another one has been fetched (the nodes of a way of a relation) is
    fetched in the next round. ``--member-limit`` caps the requests of one run."""
    members_dir = args.members_dir
    done: set[str] = set()
    fetched = same = differ = 0
    differing: list[str] = []
    left = 0
    while True:
        store = osm_geom.Store(history_dir, members_dir)
        elements = osm_net.stored_histories(history_dir)
        needed: set[str] = set()
        for key in elements:
            kind = key.split("/")[0]
            if kind != "node":
                needed |= osm_geom.member_keys(kind, store.versions(key) or [], store)
        needed -= set(elements)
        todo = [k for k in sorted(needed - done) if args.refresh or store.versions(k) is None]
        room = args.member_limit - fetched
        left = max(0, len(todo) - room)
        todo = todo[:max(0, room)]
        if not todo:
            break
        members_dir.mkdir(parents=True, exist_ok=True)
        for key in todo:
            done.add(key)
            try:
                raw = client.fetch(osm_net.history_url(args.api, key), "member")
            except osm_net.OsmError as err:
                if str(err).startswith("HTTP 404"):
                    utils.warn(STEP, f"{key}: the API has no history of it; a shape that needs it stays incomplete")
                    continue
                raise
            fetched += 1
            elements_of = osm_net.check_history(key, raw)
            path = members_dir / f"{key.replace('/', '_')}.json"
            if path.is_file():
                if osm_net.same_in_common(osm_net.check_history(key, path.read_bytes()), elements_of):
                    same += 1
                else:
                    differ += 1
                    differing.append(key)
            path.write_bytes(raw)
    if fetched or left:
        print(f"[{STEP}] member histories (nodes of ways, members of relations): {fetched} fetched into {shown(members_dir)}"
              + (f"; {left} left for the next run (--member-limit {args.member_limit})" if left else ""))
    if args.refresh and (same or differ):
        print(f"[{STEP}] refresh: {same} stored member histor{'y' if same == 1 else 'ies'} agree with the API in the versions they share, {differ} differ")
        for key in differing[:10]:
            utils.warn(STEP, f"{key}: a stored version differs from what the API says now (the stored file was replaced)")


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
    parser.add_argument("--members-dir", type=Path, default=utils.DATA_RAW / "osm" / "members",
                        help="folder with the histories of the nodes of ways and the members of relations (default data/raw/osm/members)")
    parser.add_argument("--member-limit", type=int, default=500, help="at most this many member-history requests per run (default 500)")
    parser.add_argument("--element", action="append", default=[], metavar="TYPE/ID",
                        help="fetch the history of this element (node/1, way/2, relation/3) and its members, without asking Overpass; repeatable")
    parser.add_argument("--offline", action="store_true", help="no network: import the files of --from-dir")
    parser.add_argument("--probe", action="store_true", help="one Overpass request: report what would be fetched, write nothing")
    parser.add_argument("--refresh", action="store_true", help="fetch every history again and compare it with the stored one")
    parser.add_argument("--limit", type=int, default=100, help="at most this many history requests per run (default 100)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    parser.add_argument("--contact", help="contact (address or URL) named in the User-Agent; or set WBS_CONTACT (default: the repository URL)")
    parser.add_argument("--overpass", default=osm_net.OVERPASS, help="Overpass endpoint")
    parser.add_argument("--api", default=osm_net.API, help="base URL of the OSM API")
    parser.add_argument("--query", type=Path, help="the Overpass query (default data/seeds/overpass-<selection>.overpassql)")
    parser.add_argument("--overpass-file", type=Path, help="where the Overpass answer is stored (default data/raw/osm/overpass/<selection>.json)")
    parser.add_argument("--dry-run", action="store_true", help="print the report, write nothing (with the network: the probe)")
    args = parser.parse_args(argv)
    args.overpass_file = args.overpass_file or utils.DATA_RAW / "osm" / "overpass" / f"{args.selection}.json"
    if args.offline and (args.probe or args.refresh or args.element):
        print(f"ERROR: [{STEP}] --probe, --refresh and --element need the network; drop --offline")
        return 2
    bad = [e for e in args.element if not re.fullmatch(r"(node|way|relation)/[1-9][0-9]*", e)]
    if bad:
        print(f"ERROR: [{STEP}] --element {bad[0]!r} is not node/<id>, way/<id> or relation/<id>")
        return 2

    try:
        roles = read_roles(args.mapping)
        condition = read_selection(args.seeds, args.selection)
        if not args.offline:
            code = run_network(args, CLIENT_FACTORY() if CLIENT_FACTORY else None)
            if code is not None:
                return code
        if not args.from_dir.is_dir():
            raise ImportProblem(f"input: {args.from_dir} does not exist")
        files = sorted(p for p in args.from_dir.iterdir() if p.suffix == ".json")
        elements = [read_element(p) for p in files]
    except ImportProblem as err:
        print(f"ERROR: [{STEP}] {err}")
        return 2
    if not elements:
        utils.nothing_to_do(STEP, f"no history files in {shown(args.from_dir)}" + ("" if args.offline else " (the Overpass answer named no element)"))
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
    importer = Importer(roles, condition, args.selection, idmap, osm_net.stored_overpass(args.overpass_file))
    store = osm_geom.Store(args.from_dir, args.members_dir)
    for element in elements:
        if element.url() in by_hand and idmap.ids.get((SOURCE, element.key)) != by_hand[element.url()]:
            messages.append(f"{element.key} is already described by hand as {by_hand[element.url()]}; "
                            f"importing it would make a second item (map it with the row `osm,{element.key},{by_hand[element.url()]}` in idmap.csv, "
                            f"or remove the hand-made rows)")
        importer.element(element, store)
    merged = merge(existing, importer.out, (SOURCE,))

    print(f"[{STEP}] {len(files)} history file(s) in {shown(args.from_dir)}; selection {args.selection}: "
          + " and ".join(f"{k}" + (f"={v}" if v else "") for k, v in condition))
    print(f"[{STEP}] items: {len(importer.out.entities)} ({', '.join(f'{n} {k}' for k, n in sorted(importer.kinds.items())) or 'none'}); "
          f"{importer.versions} version statement(s); {idmap.new} new id(s) in idmap.csv"
          + (f"; {importer.left} element(s) left the selection area" if importer.left else ""))
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
