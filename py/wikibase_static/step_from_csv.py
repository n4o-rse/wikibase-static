"""S7a -- turn the CSV tables into Wikibase JSON in data/derived/ (a dummy Wikibase).

    python main.py from-csv                     data/csv/ -> data/derived/entities/*.json, with the kernel
    python main.py from-csv --no-kernel         without the kernel (CSV that holds all ids itself, e.g. from to-csv)
    python main.py from-csv --csv DIR --out DIR other folders (the output folder gets ``entities/`` inside)
    python main.py from-csv --all               print every warning (the default prints the first 50)

Reads ``entities.csv``, ``statements.csv``, ``qualifiers.csv`` and ``references.csv`` (format: ``csvio.py``), mixes in
the kernel of the package (Q1 to Q3, P1 to P10) and writes one JSON file per entity in the form ``harvest`` leaves in
``data/raw/entities/``, so ``load`` and everything after it need no second code path. Files without a CSV row are
removed from the output folder. Offline, deterministic, no clock. Without ``data/csv/`` there is nothing to do.

``data/csv/merges.csv`` (optional; columns ``from, to, note``; made by ``python main.py merge``) merges an item into another one
while the tables are read: see ``csvbuild._apply_merges``. A merged id has no entity file; ``redirects.json`` next to
``entities/`` says where it went (``{"Q359": "Q361"}``) and is removed when there is no merge.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_from_csv.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvbuild, csvio, utils

STEP = "from-csv"
SHOWN = 50
ENTITY_FILE = re.compile(r"^[QP][1-9][0-9]*\.json$")
REDIRECTS = "redirects.json"


def shown_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(utils.ROOT).as_posix()
    except ValueError:
        return str(path)


def write_entities(folder: Path, entities: dict[str, dict]) -> tuple[int, int, int]:
    """Write ``entities`` as ``<id>.json`` in ``folder``; returns (written, unchanged, removed)."""
    folder.mkdir(parents=True, exist_ok=True)
    written = unchanged = removed = 0
    wanted = {f"{entity_id}.json": data for entity_id, data in entities.items()}
    for name, data in wanted.items():
        target = folder / name
        text = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        if target.is_file() and target.read_bytes() == text.encode("utf-8"):
            unchanged += 1
            continue
        utils.write_text(target, text)
        written += 1
    for path in sorted(folder.iterdir()):
        if path.is_file() and ENTITY_FILE.match(path.name) and path.name not in wanted:
            path.unlink()
            removed += 1
    return written, unchanged, removed


def write_redirects(path: Path, redirects: dict[str, str]) -> None:
    """``redirects.json`` (merged id -> id it went into), or no file when nothing is merged."""
    if redirects:
        text = json.dumps(dict(sorted(redirects.items())), ensure_ascii=False, indent=2) + "\n"
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            utils.write_text(path, text)
    elif path.is_file():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py from-csv", description="CSV tables to Wikibase JSON.")
    parser.add_argument("--csv", type=Path, default=utils.ROOT / "data" / "csv", help="folder with the CSV tables")
    parser.add_argument("--out", type=Path, default=utils.DATA_DERIVED, help="folder that gets entities/<id>.json")
    parser.add_argument("--no-kernel", action="store_true", help="do not mix in the kernel (Q1-Q3, P1-P10)")
    parser.add_argument("--all", action="store_true", help=f"print every warning, not only the first {SHOWN}")
    args = parser.parse_args(argv)

    folder = args.csv
    if not any((folder / name).is_file() for name in csvio.TABLES):
        utils.nothing_to_do(STEP, f"no CSV tables in {shown_path(folder)}")
        return 0

    problems: list[str] = []
    site = csvbuild.read_set(folder, problems, shown_path(folder))
    kernel = None if args.no_kernel else csvbuild.kernel_set()
    built = csvbuild.build(site, kernel, csvbuild.site_base())
    problems = sorted(set(problems) | set(built.problems))

    target = args.out / "entities"
    written, unchanged, removed = write_entities(target, built.entities)
    write_redirects(args.out / REDIRECTS, built.redirects)
    counts = {kind: sum(1 for k in built.kinds.values() if k == kind) for kind in csvio.KINDS}
    print(f"[{STEP}] {len(built.entities)} entities ({counts['item']} items, {counts['class']} classes, "
          f"{counts['property']} properties), {built.statements} statements -> {shown_path(target)}")
    print(f"[{STEP}] {'kernel mixed in (Q1-Q3, P1-P10)' if built.kernel else 'no kernel (--no-kernel)'}; "
          f"{written} file(s) written, {unchanged} unchanged, {removed} removed")
    for note in built.merge_notes:
        print(f"[{STEP}] merge {note}")
    shown = problems if args.all else problems[:SHOWN]
    for message in shown:
        utils.warn(STEP, message)
    if len(shown) < len(problems):
        print(f"[{STEP}] {len(problems) - len(shown)} more warnings not shown (use --all)")
    print(f"[{STEP}] {len(problems)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
