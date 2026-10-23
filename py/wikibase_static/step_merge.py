"""S7e -- merge one item into another, the way Wikibase does (Special:MergeItems), as a line in ``data/csv/merges.csv``.

    python main.py merge Q381 Q359            Q381 is merged into Q359 (the first goes into the second); writes merges.csv
    python main.py merge Q381 Q359 --note "same project"     with a note for the reader
    python main.py merge Q381 Q359 --dry-run  say what would happen, write nothing
    python main.py merge --list               the merges and what each does
    python main.py merge --undo Q381          remove the line again (the item is back after the next ``from-csv``)

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
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_merge.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvbuild, csvio, utils
from wikibase_static.model import id_sort_key

STEP = "merge"


def read_lines(path: Path, problems: list[str]) -> list[dict[str, str]]:
    table = csvio.read_table(path, ["from", "to"], problems, path.name)
    return [{"from": r.get("from", "").strip(), "to": r.get("to", "").strip(), "note": r.get("note", "")} for r in table.rows]


def write_lines(path: Path, rows: list[dict[str, str]]) -> None:
    rows = sorted(rows, key=lambda r: id_sort_key(r["from"]))
    if rows:
        utils.write_text(path, csvio.render_table(csvbuild.MERGE_COLUMNS, rows))
    elif path.is_file():
        path.unlink()


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
    parser.add_argument("--csv", type=Path, default=utils.ROOT / "data" / "csv", help="folder with the CSV tables")
    args = parser.parse_args(argv)

    path = args.csv / csvbuild.MERGES
    read_problems: list[str] = []
    rows = read_lines(path, read_problems)
    if read_problems:
        for message in read_problems:
            print(f"ERROR: [{STEP}] {message}")
        return 1

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
