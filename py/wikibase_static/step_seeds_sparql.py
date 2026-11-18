"""S14a -- make the seed list of ``import-wikidata`` from SPARQL queries and a list of ids (a verb of its own; it uses the network).

    python main.py seeds-from-sparql                 run the queries at the Wikidata Query Service, store the answers, write the seed list
    python main.py seeds-from-sparql --offline       no network: write the seed list from the stored answers
    python main.py seeds-from-sparql --from-dir DIR  store answers saved in a browser (the "JSON" download of query.wikidata.org)
                                                     as data/raw/wikidata-seeds/<name>.json, then write the seed list
    python main.py seeds-from-sparql --dry-run       print what would change, write nothing

Where the seeds come from (a site repository has a folder ``data/seeds/``, as the OSM sites do):

* ``data/seeds/wikidata-<name>.rq``: a SPARQL query for the Wikidata Query Service. It must return the variable ``?item`` (the
  entity URI). Optional variables: ``?kind`` (text for the column ``kind``; the default is ``<name>``) and ``?itemLabel`` or
  ``?note`` (text for the column ``note``). The prefixes ``wd:``, ``wdt:``, ``wikibase:``, ``bd:`` need no PREFIX line there.
* ``data/seeds/wikidata-qids.txt``: single ids, one per line, ``Q42`` or ``Q42  a note`` (``#`` starts a comment).

The answers are kept as they came (``data/raw/wikidata-seeds/<name>.json``, canonical JSON), so the list can be written again
without the network and a change of the list can be seen in git. The result is ``data/csv/seeds-wikidata.csv`` (the columns
``qid, kind, note, instance_of``), sorted by number. It is a function of the queries, the ids and the stored answers: a seed that
no query and no list names any more is dropped from it (its rows stay in the tables until ``import-wikidata`` runs, which
removes them but keeps the local id). What the file already says in ``note`` and ``instance_of`` for a seed that stays is kept.
``--max-seeds`` (default 2000) stops a query that is far too broad before it is imported.

Wikidata ids are the only thing this step handles; nothing is merged and no entity is read (that is ``import-wikidata``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_seeds_sparql.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, csvio, utils
from wikibase_static.model import id_sort_key
from wikibase_static.step_harvest import Client, HarvestError
from wikibase_static.step_import_open_archaeo import ImportProblem, read_rows, shown

STEP = "seeds-from-sparql"
API = "https://query.wikidata.org/sparql"
ENTITY_URI = re.compile(r"^https?://www\.wikidata\.org/entity/(Q[1-9][0-9]*)$")
QID = re.compile(r"^Q[1-9][0-9]*$")
QUERY_FILE = re.compile(r"^wikidata-(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)\.rq$")
QIDS_FILE = "wikidata-qids.txt"
COLUMNS = ["qid", "kind", "note", "instance_of"]
DEFAULT_MAX = 2000


# --------------------------------------------------------------------------- reading the sources


def read_queries(folder: Path) -> dict[str, str]:
    """name -> query text, for every ``wikidata-<name>.rq`` of the folder (sorted by name)."""
    found: dict[str, str] = {}
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            match = QUERY_FILE.match(path.name)
            if match and path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if not text:
                    raise ImportProblem(f"{shown(path)} is empty")
                found[match.group("name")] = text
    return found


def read_qids(path: Path) -> list[tuple[str, str]]:
    """(id, note) for every line of ``wikidata-qids.txt``."""
    found: list[tuple[str, str]] = []
    if not path.is_file():
        return found
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        qid, _space, note = text.partition(" ")
        if not QID.match(qid):
            raise ImportProblem(f"{shown(path)}:{number}: {qid!r} is not an item id (Q42)")
        found.append((qid, note.strip()))
    return found


def answer_path(raw: Path, name: str) -> Path:
    return raw / f"{name}.json"


def read_answer(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ImportProblem(f"{shown(path)} cannot be read ({err})") from err
    if not isinstance(data, dict) or "results" not in data or "bindings" not in data["results"]:
        raise ImportProblem(f"{shown(path)} is not a SPARQL JSON result (no results.bindings)")
    return data


def canonical(data: dict[str, Any]) -> str:
    """The stored form: bindings sorted by the item, nothing that changes between two identical answers."""
    head = {"vars": sorted(data.get("head", {}).get("vars", []))}
    bindings = sorted(data["results"]["bindings"], key=lambda b: json.dumps(b, sort_keys=True, ensure_ascii=False))
    return json.dumps({"head": head, "results": {"bindings": bindings}}, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def items_of(name: str, data: dict[str, Any]) -> list[dict[str, str]]:
    """The rows of an answer: ``qid``, ``kind`` and ``note``; bindings without a Wikidata item in ``?item`` are skipped."""
    variables = data.get("head", {}).get("vars", [])
    if "item" not in variables:
        raise ImportProblem(f"query {name}: the answer has no variable ?item (it has {', '.join(variables) or 'none'})")
    rows: list[dict[str, str]] = []
    for binding in data["results"]["bindings"]:
        found = ENTITY_URI.match(binding.get("item", {}).get("value", ""))
        if not found:
            continue
        note = binding.get("note", binding.get("itemLabel", {})).get("value", "")
        rows.append({"qid": found.group(1), "kind": binding.get("kind", {}).get("value", "") or name,
                     "note": "" if QID.match(note) else note})          # an unlabelled item has its id as label: no note
    return rows


# --------------------------------------------------------------------------- the list


def build_list(answers: dict[str, dict[str, Any]], qids: list[tuple[str, str]], before: list[dict[str, str]],
               report: list[str]) -> list[dict[str, str]]:
    """The seed rows: queries in the order of their names, then the ids; the first source of an id wins."""
    kept = {row["qid"]: row for row in before}
    rows: dict[str, dict[str, str]] = {}
    sources: dict[str, list[str]] = {}

    def add(qid: str, kind: str, note: str, source: str) -> None:
        sources.setdefault(qid, []).append(source)
        if qid in rows:
            return
        old = kept.get(qid, {})
        rows[qid] = {"qid": qid, "kind": kind, "note": old.get("note") or note, "instance_of": old.get("instance_of", "")}

    for name in sorted(answers):
        for row in items_of(name, answers[name]):
            add(row["qid"], row["kind"], row["note"], f"query {name}")
    for qid, note in qids:
        add(qid, "listed", note, QIDS_FILE)
    twice = sorted((qid for qid, names in sources.items() if len(set(names)) > 1), key=id_sort_key)
    if twice:
        report.append(f"{len(twice)} seed(s) named by more than one source (the first one decides the kind): "
                      + ", ".join(f"{q} ({', '.join(sorted(set(sources[q])))})" for q in twice))
    return [rows[q] for q in sorted(rows, key=id_sort_key)]


# --------------------------------------------------------------------------- the network


def run_query(client: Client, name: str, text: str) -> dict[str, Any]:
    data = client.get({"query": text}, name)
    if "results" not in data or "bindings" not in data.get("results", {}):
        raise HarvestError(f"query {name}: the Query Service did not send a SPARQL JSON result")
    return data


def store(raw: Path, name: str, data: dict[str, Any]) -> bool:
    """Write an answer; ``True`` if the file changed."""
    path = answer_path(raw, name)
    text = canonical(data)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    utils.write_text(path, text)
    return True


# --------------------------------------------------------------------------- the step


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python main.py seeds-from-sparql",
                                     description="SPARQL queries and ids -> data/csv/seeds-wikidata.csv (input of import-wikidata).")
    parser.add_argument("--seeds-dir", type=Path, default=utils.ROOT / "data" / "seeds", help="folder with wikidata-<name>.rq and wikidata-qids.txt")
    parser.add_argument("--raw", type=Path, default=utils.DATA_RAW / "wikidata-seeds", help="folder for the stored answers")
    parser.add_argument("--output", type=Path, default=utils.ROOT / "data" / "csv" / "seeds-wikidata.csv")
    parser.add_argument("--offline", action="store_true", help="no network: use the stored answers")
    parser.add_argument("--from-dir", metavar="DIR", type=Path, help="store saved SPARQL JSON files (<name>.json) first")
    parser.add_argument("--dry-run", action="store_true", help="print what would change, write nothing (implies --offline)")
    parser.add_argument("--max-seeds", type=int, default=DEFAULT_MAX, help=f"stop if the list has more seeds (default {DEFAULT_MAX})")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: 1)")
    parser.add_argument("--contact", help="contact named in the User-Agent; or set WBS_CONTACT")
    return parser


def main(argv: list[str] | None = None, client: Client | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_dir and args.dry_run:
        print(f"ERROR: [{STEP}] --from-dir writes the raw folder, --dry-run writes nothing; use one of them")
        return 2
    try:
        queries = read_queries(args.seeds_dir)
        qids = read_qids(args.seeds_dir / QIDS_FILE)
        if not queries and not qids:
            utils.nothing_to_do(STEP, f"{shown(args.seeds_dir)} has no wikidata-<name>.rq and no {QIDS_FILE}")
            return 0
        before = read_rows(args.output, ["qid"], "seeds") if args.output.is_file() else []
        notes: list[str] = []
        if args.from_dir:
            if not args.from_dir.is_dir():
                raise HarvestError(f"--from-dir {args.from_dir}: not a directory")
            for name in queries:
                saved = args.from_dir / f"{name}.json"
                if saved.is_file():
                    store(args.raw, name, read_answer(saved))
                    notes.append(f"stored {saved.name}")
                else:
                    notes.append(f"no {saved.name} in {shown(args.from_dir)}")
        elif not (args.offline or args.dry_run):
            contact = args.contact or os.environ.get("WBS_CONTACT") or "https://github.com/n4o-rse/wikibase-static"
            client = client or Client(API, f"wikibase-static/{__version__} (+{contact}; static archive, read-only)",
                                      delay=args.delay, maxlag=0)
            for name, text in queries.items():
                changed = store(args.raw, name, run_query(client, name, text))
                notes.append(f"query {name}: answer {'changed' if changed else 'unchanged'}")
        answers: dict[str, dict[str, Any]] = {}
        missing = []
        for name in queries:
            path = answer_path(args.raw, name)
            if path.is_file():
                answers[name] = read_answer(path)
            else:
                missing.append(name)
        if missing:
            print(f"ERROR: [{STEP}] no stored answer for {', '.join(missing)} in {shown(args.raw)}; run without --offline "
                  "or give the files with --from-dir")
            return 2
        report: list[str] = []
        rows = build_list(answers, qids, before, report)
    except (HarvestError, ImportProblem) as err:
        print(f"ERROR: [{STEP}] {err}")
        return getattr(err, "code", 2)

    if len(rows) > args.max_seeds:
        print(f"ERROR: [{STEP}] the sources name {len(rows)} seeds, more than --max-seeds {args.max_seeds}; "
              "narrow the query or raise the limit")
        return 2
    for line in notes + report:
        print(f"[{STEP}] {line}")
    names = {row["qid"] for row in rows}
    dropped = sorted((row["qid"] for row in before if row["qid"] not in names), key=id_sort_key)
    added = sorted((row["qid"] for row in rows if row["qid"] not in {r["qid"] for r in before}), key=id_sort_key)
    print(f"[{STEP}] {len(rows)} seed(s) from {len(answers)} query/queries and {len(qids)} listed id(s); "
          f"{len(added)} new, {len(dropped)} dropped")
    if dropped:
        print(f"[{STEP}] dropped (named by no query and not listed): {', '.join(dropped)}")
    text = csvio.render_table(COLUMNS, rows)
    if args.output.is_file() and args.output.read_bytes() == text.encode("utf-8"):
        print(f"[{STEP}] {shown(args.output)} is up to date")
        return 0
    if args.dry_run:
        print(f"[{STEP}] {shown(args.output)} would change")
        return 0
    utils.write_text(args.output, text)
    print(f"[{STEP}] {shown(args.output)} written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
