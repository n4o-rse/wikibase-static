"""S7a -- write the harvested entities of data/raw/ as the four CSV tables (the inverse of from-csv).

    python main.py to-csv                      data/raw/ -> data/csv/
    python main.py to-csv --raw DIR --out DIR  other folders
    python main.py to-csv --force              overwrite tables that already exist

The tables are the source of a site that is kept in CSV from now on (PRIMER.md, A4 "CSV, Quelle der Wahrheit"). The
harvested ids are kept as they are, so ``from-csv --no-kernel`` brings the same entities back; with the kernel the ids
1 to 99 would collide with the kernel's. What the CSV cannot hold (hashes, revision ids, sitelinks, a coordinate's
altitude, quantity bounds, a time's time zone) is dropped and reported as ``WARN``. Not part of the default run: it
writes source files, and it refuses to overwrite existing ones unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_to_csv.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import csvbuild, csvio, utils
from wikibase_static.csvio import CsvError
from wikibase_static.loader import Site, load_site
from wikibase_static.model import Entity, Snak, id_sort_key

STEP = "to-csv"
SHOWN = 50


def entity_row(entity: Entity) -> dict[str, str]:
    row = {"id": entity.id, "kind": "property" if entity.kind == "property" else "item",
           "datatype": entity.datatype or "", "origin": ""}
    for code, text in entity.labels.items():
        row[f"label_{code}"] = text
    for code, text in entity.descriptions.items():
        row[f"description_{code}"] = text
    for code, values in entity.aliases.items():
        row[f"aliases_{code}"] = csvio.join_aliases(values)
    return row


def convert(site: Site, base: str | None) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    """The rows of the four tables (unordered) and what could not be kept."""
    tables: dict[str, list[dict[str, str]]] = {name: [] for name in csvio.TABLES}
    problems: list[str] = []
    for entity in sorted(site.entities.values(), key=lambda e: id_sort_key(e.id)):
        tables["entities.csv"].append(entity_row(entity))
        if entity.sitelinks:
            problems.append(f"{entity.path}: {entity.id} has sitelinks, which the CSV does not hold; dropped")
        lost: set[str] = set()

        def text(snak: Snak, where: str) -> str | None:
            lost.update(csvio.lossy_parts(snak))
            try:
                return csvio.format_snak(snak, base)
            except CsvError as err:
                problems.append(f"{where}: {err}; dropped")
                return None

        for position, statement in enumerate(entity.statements):
            where = f"{entity.path or entity.id} ({entity.id}, statement {position + 1})"
            value = text(statement.mainsnak, where)
            if value is None:
                continue
            sid = ""
            if statement.qualifiers or statement.references:
                sid = statement.id or f"{entity.id}-s{position + 1}"
            tables["statements.csv"].append({
                "sid": sid, "subject": entity.id, "property": statement.mainsnak.property, "value": value,
                "rank": "" if statement.rank == "normal" else statement.rank, "origin": ""})
            for qualifier in statement.qualifiers:
                cell = text(qualifier, where)
                if cell is not None:
                    tables["qualifiers.csv"].append({"sid": sid, "property": qualifier.property, "value": cell})
            for group, reference in enumerate(statement.references, start=1):
                for part in reference:
                    cell = text(part, where)
                    if cell is not None:
                        tables["references.csv"].append(
                            {"sid": sid, "group": str(group), "property": part.property, "value": cell})
        if lost:
            problems.append(f"{entity.path or entity.id}: {entity.id}: {', '.join(sorted(lost))} not kept by the CSV format")
    return tables, sorted(set(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py to-csv", description="Harvested JSON to CSV tables.")
    parser.add_argument("--raw", type=Path, default=utils.DATA_RAW, help="folder with entities/<id>.json")
    parser.add_argument("--out", type=Path, default=utils.ROOT / "data" / "csv", help="folder for the CSV tables")
    parser.add_argument("--force", action="store_true", help="overwrite tables that already exist")
    parser.add_argument("--all", action="store_true", help=f"print every warning, not only the first {SHOWN}")
    args = parser.parse_args(argv)

    site = load_site(args.raw, args.out / "__none__")
    if not site.entities:
        utils.nothing_to_do(STEP, "no entities in data/raw/entities")
        return 0
    existing = [name for name in csvio.TABLES if (args.out / name).is_file()]
    if existing and not args.force:
        print(f"[{STEP}] {', '.join(existing)} already exist in {args.out}; nothing written (use --force to overwrite)")
        return 2

    rows, problems = convert(site, csvbuild.site_base() or site.source_url)
    ordered = {
        "entities.csv": csvio.canonical_rows("entities.csv", rows["entities.csv"]),
        "statements.csv": csvio.canonical_rows("statements.csv", rows["statements.csv"]),
    }
    for name in ("qualifiers.csv", "references.csv"):
        ordered[name] = csvio.canonical_by_sid(rows[name], ordered["statements.csv"])
    columns = {"entities.csv": csvio.entity_columns(ordered["entities.csv"]), **{n: c for n, c in csvio.TABLES.items() if n != "entities.csv"}}
    args.out.mkdir(parents=True, exist_ok=True)
    for name, table_rows in ordered.items():
        (args.out / name).write_bytes(csvio.render_table(columns[name], table_rows).encode("utf-8"))

    print(f"[{STEP}] {len(site.entities)} entities ({len(site.items)} items, {len(site.properties)} properties), "
          f"{len(ordered['statements.csv'])} statements, {len(ordered['qualifiers.csv'])} qualifier rows, "
          f"{len(ordered['references.csv'])} reference rows -> {args.out}")
    if site.problems:
        print(f"[{STEP}] the data has {len(site.problems)} warning(s) of its own (python main.py load shows them)")
    shown = problems if args.all else problems[:SHOWN]
    for message in shown:
        utils.warn(STEP, message)
    if len(shown) < len(problems):
        print(f"[{STEP}] {len(problems) - len(shown)} more warnings not shown (use --all)")
    print(f"[{STEP}] {len(problems)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
