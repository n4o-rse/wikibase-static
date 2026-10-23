"""S7e -- merge one item into another, the way Wikibase does (Special:MergeItems), as a line in ``data/csv/merges.csv``.

    python main.py merge Q381 Q359            Q381 is merged into Q359 (the first goes into the second); writes merges.csv
    python main.py merge Q381 Q359 --note "same project"     with a note for the reader
    python main.py merge Q381 Q359 --dry-run  say what would happen, write nothing
    python main.py merge --list               the merges and what each does
    python main.py merge --undo Q381          remove the line again (the item is back after the next ``from-csv``)
    python main.py merge --suggest            look for items that may be the same thing; writes dist/merge-suggestions.csv

``--suggest`` only suggests (S7i). It compares the items of different origins (Wikidata, open-archaeo, the Starter Pack, by hand)
by name, over the labels and aliases of every language, and writes one line per pair with the command that would merge it
(the Wikidata side stays, A4 "Merge von Items"): score 3 the same name (case, accents, spaces and punctuation do not count; names
shorter than four letters are left out), score 2 the same first and last name with other names in between ("Allard Mees",
"Allard Wijnand Mees"), score 1 an account name that looks like first initial plus surname ("nfrerebeau", "Nicolas Frerebeau").
Pairs that are merged already, classes and properties are left out. The file is a function of the tables (sorted, no clock).

The tables stay as they are: ``merges.csv`` (columns ``from, to, note``) is applied while ``from-csv`` reads them, so a merge
survives every reimport of the importers, and undoing it is deleting a line. What a merge does is described in
``csvbuild._apply_merges``: statements move over (identical ones are not doubled, their references are joined), different values
of one property are all kept and named in the report, the label of ``to`` wins and a different label of ``from`` becomes an alias,
every value that points at ``from`` points at ``to``, and ``from`` becomes a redirect (a page that forwards, ``owl:sameAs`` in the
RDF). No chains: ``to`` must not be merged into something else. The line is checked before it is written; nothing is
written when it would be a problem.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_merge.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvbuild, csvio, utils
from wikibase_static.model import id_sort_key

STEP = "merge"
SUGGESTIONS = "merge-suggestions.csv"
SUGGESTION_COLUMNS = ["score", "reason", "from", "from_label", "from_origin", "to", "to_label", "to_origin", "command"]
MIN_NAME = 4                    # a name of fewer letters is no evidence ("R", "Go")
REASONS = {3: "same name", 2: "same first and last name", 1: "account name looks like initial + surname"}
STAYS = {"wikidata": 0, "wikidata-stub": 1}          # who stays: the Wikidata item, then its stub, then the lower id


def read_lines(path: Path, problems: list[str]) -> list[dict[str, str]]:
    table = csvio.read_table(path, ["from", "to"], problems, path.name)
    return [{"from": r.get("from", "").strip(), "to": r.get("to", "").strip(), "note": r.get("note", "")} for r in table.rows]


def write_lines(path: Path, rows: list[dict[str, str]]) -> None:
    rows = sorted(rows, key=lambda r: id_sort_key(r["from"]))
    if rows:
        utils.write_text(path, csvio.render_table(csvbuild.MERGE_COLUMNS, rows))
    elif path.is_file():
        path.unlink()


def tokens(name: str) -> list[str]:
    """The words of a name: accents removed, lower case, letters and digits only."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return [t for t in re.split(r"[^a-z0-9]+", folded) if t]


def names_of(row: dict[str, str]) -> list[str]:
    found: list[str] = []
    for column, cell in row.items():
        kind, _sep, code = column.partition("_")
        if not code or not cell.strip():
            continue
        if kind == "label":
            found.append(cell)
        elif kind == "aliases":
            found += csvio.split_aliases(cell)
    return found


def suggest(site: csvbuild.CsvSet) -> list[dict[str, str]]:
    """Pairs of items of different origin that may be the same thing, as rows of ``SUGGESTION_COLUMNS``, best first."""
    merged: set[str] = set()
    for row in (site.merges.rows if site.merges else []):
        merged |= {row.get("from", "").strip(), row.get("to", "").strip()}
    items = {r["id"].strip(): r for r in site.entities.rows if r.get("kind", "").strip() == "item" and r["id"].strip() not in merged}
    by_squeezed: dict[str, set[str]] = defaultdict(set)
    by_parts: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_initial: dict[str, set[str]] = defaultdict(set)
    handles: dict[str, set[str]] = defaultdict(set)
    for item_id, row in items.items():
        for name in names_of(row):
            words = tokens(name)
            squeezed = "".join(words)
            if len(squeezed) < MIN_NAME:
                continue
            by_squeezed[squeezed].add(item_id)
            if len(words) >= 2 and len(words[0]) > 1 and len(words[-1]) > 1:
                by_parts[(words[0], words[-1])].add(item_id)
                by_initial[words[0][0] + words[-1]].add(item_id)
            if len(words) == 1:
                handles[squeezed].add(item_id)
    found: dict[tuple[str, str], int] = {}

    def note(left: set[str], right: set[str], score: int) -> None:
        for a in left:
            for b in right:
                if a != b and items[a].get("origin", "").strip() != items[b].get("origin", "").strip():
                    key = tuple(sorted((a, b), key=id_sort_key))
                    found[key] = max(found.get(key, 0), score)

    for group in by_squeezed.values():
        note(group, group, 3)
    for group in by_parts.values():
        note(group, group, 2)
    for key, owners in by_initial.items():
        if key in handles:
            note(owners, handles[key], 1)
    rows = []
    for (a, b), score in found.items():
        rank = lambda i: (STAYS.get(items[i].get("origin", "").strip(), 2), id_sort_key(i))
        source, target = sorted((a, b), key=rank, reverse=True)
        label = lambda i: items[i].get("label_en", "") or next((v for v in names_of(items[i])), "")
        rows.append({"score": str(score), "reason": REASONS[score], "from": source, "from_label": label(source),
                     "from_origin": items[source].get("origin", "").strip(), "to": target, "to_label": label(target),
                     "to_origin": items[target].get("origin", "").strip(), "command": f"merge {source} {target}"})
    return sorted(rows, key=lambda r: (-int(r["score"]), id_sort_key(r["from"]), id_sort_key(r["to"])))


def check(csv_dir: Path, rows: list[dict[str, str]]) -> tuple[list[str], list[str], dict[str, str]]:
    """(new problems, notes, redirects) of the tables with ``rows`` as merges.csv, compared with no merges at all."""
    problems: list[str] = []
    site = csvbuild.read_set(csv_dir, problems, csv_dir.name)
    base = csvbuild.build(csvbuild.CsvSet(site.entities, site.statements, site.qualifiers, site.references, site.folder,
                                          csvio.Table(csvbuild.MERGES, ["from", "to", "note"])), csvbuild.kernel_set(), csvbuild.site_base())
    site.merges = csvio.Table(csvbuild.MERGES, ["from", "to", "note"], rows=rows, lines=list(range(2, len(rows) + 2)))
    built = csvbuild.build(site, csvbuild.kernel_set(), csvbuild.site_base())
    return sorted(set(built.problems) - set(base.problems)), built.merge_notes, built.redirects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py merge", description="Merge one item into another (data/csv/merges.csv).")
    parser.add_argument("source", nargs="?", help="the item that is merged away (from)")
    parser.add_argument("target", nargs="?", help="the item that stays (to)")
    parser.add_argument("--note", default="", help="a note for the reader, kept in merges.csv")
    parser.add_argument("--dry-run", action="store_true", help="say what would happen, write nothing")
    parser.add_argument("--list", action="store_true", help="the merges of merges.csv and what each does")
    parser.add_argument("--undo", metavar="ID", help="remove the merge of this id from merges.csv")
    parser.add_argument("--suggest", action="store_true", help="look for items that may be the same thing; writes the report")
    parser.add_argument("--report", type=Path, default=None, help=f"where --suggest writes (default dist/{SUGGESTIONS})")
    parser.add_argument("--csv", type=Path, default=utils.ROOT / "data" / "csv", help="folder with the CSV tables")
    args = parser.parse_args(argv)

    path = args.csv / csvbuild.MERGES
    read_problems: list[str] = []
    rows = read_lines(path, read_problems)
    if read_problems:
        for message in read_problems:
            print(f"ERROR: [{STEP}] {message}")
        return 1

    if args.suggest:
        problems: list[str] = []
        rows_found = suggest(csvbuild.read_set(args.csv, problems, args.csv.name))
        target = args.report or utils.DIST / SUGGESTIONS
        utils.write_text(target, csvio.render_table(SUGGESTION_COLUMNS, rows_found))
        shown = target.resolve().relative_to(utils.ROOT).as_posix() if target.resolve().is_relative_to(utils.ROOT) else str(target)
        counts = {score: sum(1 for r in rows_found if r["score"] == str(score)) for score in (3, 2, 1)}
        print(f"[{STEP}] {len(rows_found)} pair(s) may be the same thing: {counts[3]} with the same name, {counts[2]} with the same first "
              f"and last name, {counts[1]} with an account name like initial + surname -> {shown}")
        for r in rows_found[:10]:
            print(f"[{STEP}]   {r['score']}  {r['command']}   ({r['from_label']!r} / {r['to_label']!r})")
        if len(rows_found) > 10:
            print(f"[{STEP}]   ... {len(rows_found) - 10} more in the file")
        return 0

    if args.list:
        if not rows:
            print(f"[{STEP}] no merges")
            return 0
        _problems, notes, _redirects = check(args.csv, rows)
        print(f"[{STEP}] {len(rows)} merge(s) in {csvbuild.MERGES}")
        for note in notes:
            print(f"[{STEP}]   {note}")
        return 0

    if args.undo:
        left = [r for r in rows if r["from"] != args.undo]
        if len(left) == len(rows):
            print(f"ERROR: [{STEP}] {args.undo} is not merged into anything in {csvbuild.MERGES}")
            return 1
        write_lines(path, left)
        print(f"[{STEP}] {args.undo} is no longer merged; run from-csv and the later steps to bring it back")
        return 0

    if not args.source or not args.target:
        parser.error("name the item that goes away and the item that stays: merge Q381 Q359")
    wanted = {"from": args.source.strip(), "to": args.target.strip(), "note": args.note}
    if any(r["from"] == wanted["from"] for r in rows):
        print(f"ERROR: [{STEP}] {wanted['from']} is already merged into "
              f"{next(r['to'] for r in rows if r['from'] == wanted['from'])}; undo that first (--undo {wanted['from']})")
        return 1
    problems, notes, redirects = check(args.csv, rows + [wanted])
    if problems or wanted["from"] not in redirects:
        for message in problems or [f"{wanted['from']} could not be merged into {wanted['to']}"]:
            print(f"ERROR: [{STEP}] {message}")
        return 1
    for note in notes:
        if note.startswith(f"{wanted['from']} -> "):
            print(f"[{STEP}] {note}")
    if args.dry_run:
        print(f"[{STEP}] dry run: nothing written")
        return 0
    write_lines(path, rows + [wanted])
    print(f"[{STEP}] {wanted['from']} -> {wanted['to']} written to {csvbuild.MERGES}; run from-csv and the steps after it "
          f"(python main.py --strict)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
