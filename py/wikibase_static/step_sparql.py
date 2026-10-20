"""S6 -- build the in-browser SPARQL page (rdflib under Pyodide, no endpoint).

Planned (see PRIMER.md, S6): one queries.yaml becomes docs/sparql.html and the
same queries as plain .rq files, following the wdt-sparql pattern.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_sparql.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils

STEP = "sparql"


def main(argv: list[str] | None = None) -> int:
    utils.nothing_to_do(STEP, "not implemented yet (PRIMER.md, S6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
