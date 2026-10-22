"""S2 -- read data/raw/ and data/derived/ into the model and check them.

    python main.py load            counts and warnings
    python main.py load --all      print every warning (the default prints the first 50)

The loader itself is ``wikibase_static.loader``; later steps (build, search,
rdf) call ``load_site()`` directly. This step exists so that the pipeline report
names what the data holds and so that ``--strict`` fails on data the site cannot
show properly. It writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_load.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils
from wikibase_static.loader import load_site

STEP = "load"
SHOWN = 50


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python main.py load", description="Read and check the entity data.")
    parser.add_argument("--all", action="store_true", help=f"print every warning, not only the first {SHOWN}")
    args = parser.parse_args(argv)

    site = load_site()
    if site.files == 0 and not site.problems:
        utils.nothing_to_do(STEP, "no entities in data/raw/entities or data/derived/entities")
        return 0

    print(f"[{STEP}] {len(site.entities)} entities ({len(site.items)} items, {len(site.properties)} properties) "
          f"from {site.files} file(s)")
    counts = site.datatype_counts()
    if counts:
        detail = ", ".join(f"{name} {n}" for name, n in counts.items())
        print(f"[{STEP}] {site.statement_count()} statements: {detail}")
    if site.crm:
        classes = site.crm_classes()
        edges = site.crm_edges()
        without = [c for c in classes if not site.crm_anchors(c, edges)]
        print(f"[{STEP}] CIDOC CRM (data/crm.csv): {len(site.crm)} row-carrying class(es); {len(classes) - len(without)} of {len(classes)} classes anchored"
              + (f", without: {', '.join(without)}" if without else ""))
    if site.source_url:
        print(f"[{STEP}] source: {site.source_url}"
              + (f" (latest change {site.latest_modified})" if site.latest_modified else ""))
    shown = site.problems if args.all else site.problems[:SHOWN]
    for message in shown:
        utils.warn(STEP, message)
    if len(shown) < len(site.problems):
        print(f"[{STEP}] {len(site.problems) - len(shown)} more warnings not shown (use --all)")
    print(f"[{STEP}] {len(site.problems)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
