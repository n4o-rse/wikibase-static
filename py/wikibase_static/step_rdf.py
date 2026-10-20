"""S6 -- export the archived entities as RDF in the Wikibase data model.

Planned (see PRIMER.md, S6): wd:/wdt:/p:/ps:/pq:/prov: triples, written as
sorted N-Triples first and converted to Turtle from there (deterministic).
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_rdf.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils

STEP = "rdf"


def main(argv: list[str] | None = None) -> int:
    utils.nothing_to_do(STEP, "not implemented yet (PRIMER.md, S6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
