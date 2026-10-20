"""Shared constants and canonical writers for every step.

Rules that live here so that no step re-invents them:

* No generator reads the clock. Dates come from ``RELEASE_DATE`` or from the
  source data itself, so an artefact changes exactly when data or model change.
* Every text file is written with LF line endings and a trailing newline.
* JSON is written with sorted keys and ``ensure_ascii=False``.

Paths are relative to the working directory, which is the repository root
(``main.py`` guarantees that; run steps standalone from the root as well).
Set ``WBS_ROOT`` to point somewhere else, for instance when the package is
installed into a site repository.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

# Stamped into artefacts instead of "now". Bump it deliberately on release.
RELEASE_DATE = "2026-10-20"

ROOT = Path(os.environ.get("WBS_ROOT") or Path.cwd()).resolve()
DATA_RAW = ROOT / "data" / "raw"          # harvested JSON, unchanged, read-only
DATA_DERIVED = ROOT / "data" / "derived"  # intermediates made from CSV
DIST = ROOT / "dist"                      # versioned products (RDF, reports)
DOCS = ROOT / "docs"                      # GitHub Pages
SITE_YAML = ROOT / "site.yaml"            # site metadata (schema decided in S0)


def ensure_dirs() -> None:
    """Create the standard directories if they are missing."""
    for path in (DATA_RAW, DATA_DERIVED, DIST, DOCS):
        path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    """Write text with LF endings and exactly one trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text.replace("\r\n", "\n").rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)


def write_json(path: Path, obj: Any) -> None:
    """Write JSON canonically: sorted keys, UTF-8, two-space indent."""
    write_text(path, json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2))


def content_fingerprint(data: "bytes | str | Path") -> str:
    """SHA-256 of bytes, text or a file; used by the harvest manifest."""
    if isinstance(data, Path):
        data = data.read_bytes()
    elif isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def nothing_to_do(step: str, reason: str) -> None:
    """The standard line for a step that has no work."""
    print(f"[{step}] nothing to do: {reason}")


def warn(step: str, message: str) -> None:
    """A warning. ``main.py --strict`` turns lines starting with WARN into errors."""
    print(f"WARN: [{step}] {message}")
