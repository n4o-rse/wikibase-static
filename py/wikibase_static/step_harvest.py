"""S4 -- harvest entities from a Wikibase into data/raw/ (the only step that uses the network).

Planned (see PRIMER.md, S4): list ids, compare ``lastrevid`` against
``data/raw/manifest.json`` and fetch only what changed; ``--probe`` and
``--from-dir`` as fallbacks when the host is protected by a bot challenge.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_harvest.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils

STEP = "harvest"


def main(argv: list[str] | None = None) -> int:
    utils.nothing_to_do(STEP, "not implemented yet (PRIMER.md, S4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
