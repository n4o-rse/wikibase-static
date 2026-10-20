"""S3 -- render item and property pages in the Wikibase look into docs/.

Planned (see PRIMER.md, S3): Jinja2 templates, statements with qualifiers and
references, Leaflet for coordinates, Commons images, internal links between
Q- and P-ids, external links in a new tab.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_build.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import utils

STEP = "build"


def main(argv: list[str] | None = None) -> int:
    utils.nothing_to_do(STEP, "not implemented yet (PRIMER.md, S3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
