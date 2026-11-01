#!/usr/bin/env python3
"""Make the missing version tags (vX.Y.Z), one per version, on the commit that raised ``__version__``.

    python tools/tag_versions.py            create the missing tags here
    git push origin --tags                  and publish them

``0.1.0`` is tagged on the last commit before 0.2.0 (the first commit only holds the skeleton). An existing tag is never moved.
"""
from __future__ import annotations

import re
import subprocess
import sys

INIT = "py/wikibase_static/__init__.py"
VERSION = re.compile(r'^__version__ = "([^"]+)"', re.M)
FIRST = {"0.1.0": "775340f"}      # versions that are not tagged on the commit that introduced them


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main() -> int:
    existing = set(git("tag").split())
    previous, made = None, 0
    for commit in git("log", "--reverse", "--format=%H").split():
        try:
            match = VERSION.search(git("show", f"{commit}:{INIT}"))
        except subprocess.CalledProcessError:
            continue
        version = match.group(1) if match else None
        if version and version != previous:
            target = commit
            tag = f"v{version}"
            if tag not in existing:
                git("tag", "-a", tag, FIRST.get(version, target), "-m", f"wikibase-static {version}")
                print(f"tag {tag} on {git('rev-parse', '--short', tag + '^{commit}').strip()}")
                made += 1
            previous = version
    print(f"{made} tag(s) made, {len(existing)} existed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
