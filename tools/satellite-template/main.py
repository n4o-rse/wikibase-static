#!/usr/bin/env python3
"""Entry point of this site repository (thin wrapper around the wikibase-static package).

    python main.py                      all steps in order (from-csv, load, build, search, rdf, sparql)
    python main.py --strict             the same, but any WARN line (a dead link, a model rule) is an error
    python main.py --strict check-crm   SHACL check: every class reaches the CIDOC CRM (after the default run)
    python main.py csv-fmt              bring the tables in data/csv/ into canonical form (--check: only report)
    python main.py seeds-from-sparql    data/seeds/wikidata-*.rq + wikidata-qids.txt -> data/csv/seeds-wikidata.csv (network; --offline)
    python main.py import-wikidata      the seeds -> data/raw/wikidata/ and data/csv/ (network; --offline, --dry-run, --from-dir)
    python main.py --list               print the steps and exit

Everything is done by the installed package ``wikibase-static`` (0.28.0 or later); this file only points it at this
repository (WBS_ROOT) and starts the steps. Any further arguments are passed to the step.

The two verbs ``seeds-from-sparql`` and ``import-wikidata`` are the only steps that use the network, and they write source files,
so they never run in the default run. The first one makes the list of seeds from the queries of data/seeds/, the second one reads the
items of that list from Wikidata and turns them into rows of data/csv/. This site has no model of its own, so ``import-wikidata`` is
started with ``--generic`` (a Wikidata property without a twin becomes a local property) unless you say otherwise. The order after
every change of the queries or of the data at Wikidata is: seeds-from-sparql, import-wikidata, then the default run.

``--strict`` is what the GitHub workflow runs (.github/workflows/site.yml): the steps write ``WARN: ...``
lines for problems and this wrapper turns them into exit code 1, as the package's own main.py does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# (name, module, in the default run). The verbs never run by themselves: they write source files or use the network.
STEPS = [
    ("csv-fmt", "step_csv_fmt", False),
    ("seeds-from-sparql", "step_seeds_sparql", False),
    ("import-wikidata", "step_import_wikidata", False),
    ("apply-qs", "step_apply_qs", False),
    ("merge", "step_merge", False),
    ("from-csv", "step_from_csv", True),
    ("load", "step_load", True),
    ("build", "step_build", True),
    ("search", "step_search", True),
    ("rdf", "step_rdf", True),
    ("sparql", "step_sparql", True),
    ("check-crm", "step_check_crm", False),
]


def run(module: str, extra: list[str]) -> tuple[int, int]:
    """Run one step, pass its output through line by line; returns (exit code, number of WARN lines)."""
    env = dict(os.environ, WBS_ROOT=str(ROOT), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", f"wikibase_static.{module}", *extra], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    warnings = 0
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.lstrip().startswith("WARN"):
            warnings += 1
        print(line, flush=True)
    return proc.wait(), warnings


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    strict = argv[:1] == ["--strict"]
    if strict:
        argv = argv[1:]
    if argv[:1] == ["--list"]:
        for name, _module, default in STEPS:
            print(f"{name:10} {'default' if default else 'verb'}")
        return 0
    names = [name for name, _m, _d in STEPS]
    if argv and argv[0] in names:
        steps = [(argv[0], next(m for n, m, _d in STEPS if n == argv[0]), argv[1:])]
    elif argv:
        print(f"unknown step {argv[0]!r}; use --list", file=sys.stderr)
        return 2
    else:
        steps = [(name, module, []) for name, module, default in STEPS if default]

    # This site has no model of its own: a Wikidata property without a twin becomes a local property. With 1246 items the
    # provenance is kept per item (the P4 statement), not per statement: the site is a third smaller.
    if steps[0][0] == "import-wikidata":
        extra = [o for o in ("--generic", "--provenance") if o not in steps[0][2]]
        steps = [(steps[0][0], steps[0][1], [*steps[0][2], *(["--generic"] if "--generic" in extra else []),
                                             *(["--provenance", "item"] if "--provenance" in extra else [])])]

    total_warnings = 0
    for name, module, extra in steps:
        print(f"[{name}]", flush=True)
        code, warnings = run(module, extra)
        total_warnings += warnings
        if code:
            return code
    if strict and total_warnings:
        print(f"--strict: {total_warnings} warning(s) treated as errors", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
