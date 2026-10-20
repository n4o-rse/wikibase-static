"""S7 -- turn CSV files into Wikibase JSON in data/derived/ (a dummy Wikibase).

Planned (see PRIMER.md, S7): items, properties and statements from CSV plus a
small mapping file, producing the same intermediate format as the harvest.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_from_csv.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils

STEP = "from-csv"


def main(argv: list[str] | None = None) -> int:
    utils.nothing_to_do(STEP, "not implemented yet (PRIMER.md, S7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
