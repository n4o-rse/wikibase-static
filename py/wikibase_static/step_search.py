"""S5 -- build the static search index (labels, aliases, descriptions).

Planned (see PRIMER.md, S5): a JSON index for in-browser autocomplete in the
style of Wikidata's search box.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_search.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils

STEP = "search"


def main(argv: list[str] | None = None) -> int:
    utils.nothing_to_do(STEP, "not implemented yet (PRIMER.md, S5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
