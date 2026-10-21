"""S7a -- bring the CSV tables into their canonical form.

    python main.py csv-fmt                rewrite data/csv/*.csv
    python main.py csv-fmt --check        change nothing; exit 1 when a file is not canonical (for CI)
    python main.py csv-fmt --csv DIR      another folder

Canonical form: UTF-8 without BOM, LF, fixed column order (``en`` and ``de`` first among the language columns),
rows by id (Q before P, numeric), statements stable within a property, qualifier and reference rows in the order
of their statements, quotes only where a cell needs them. A file that is already canonical is not touched.
Not part of the default run, because it writes source files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_csv_fmt.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvio, utils

STEP = "csv-fmt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py csv-fmt", description="Canonical form of the CSV tables.")
    parser.add_argument("--csv", type=Path, default=utils.ROOT / "data" / "csv", help="folder with the CSV tables")
    parser.add_argument("--check", action="store_true", help="only report; exit 1 when a file would change")
    args = parser.parse_args(argv)

    present = [name for name in csvio.TABLES if (args.csv / name).is_file()]
    if not present:
        utils.nothing_to_do(STEP, f"no CSV tables in {args.csv}")
        return 0
    problems: list[str] = []
    tables = {name: csvio.read_table(args.csv / name, csvio.REQUIRED[name], problems, name) for name in present}
    if problems:                      # a file that cannot be read is never rewritten from an empty table
        for message in sorted(set(problems)):
            utils.warn(STEP, message)
        print(f"[{STEP}] nothing written: fix the problems above first")
        return 2
    texts = csvio.canonical_texts(tables)
    changed = []
    for name in present:
        current = (args.csv / name).read_bytes()
        wanted = texts[name].encode("utf-8")
        if current != wanted:
            changed.append(name)
            if not args.check:
                (args.csv / name).write_bytes(wanted)
    if args.check:
        for name in changed:
            print(f"[{STEP}] {name} is not in canonical form")
        print(f"[{STEP}] {len(changed)} of {len(present)} file(s) not canonical")
        return 1 if changed else 0
    print(f"[{STEP}] {len(changed)} of {len(present)} file(s) rewritten" + (f": {', '.join(changed)}" if changed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
