#!/usr/bin/env python3
"""The single entry point of wikibase-static.

    python main.py                  all default steps, in order
    python main.py --list           print the steps and exit
    python main.py --only build     one step
    python main.py --from build     this step and everything after it
    python main.py --skip search    everything but this step (repeatable)
    python main.py --dry-run        print the plan, run nothing
    python main.py --strict         warnings become errors (what CI runs)
    python main.py harvest          a step that is not in the default run

``harvest`` is the only step that touches the network, so it is never part of
the default run; give it its own verb. ``to-csv``, ``csv-fmt`` and ``import-open-archaeo`` write source files
(``data/csv/``) and have verbs of their own as well. Anything main.py does not recognise is
passed on to the step when exactly one step is selected, e.g.
``python main.py harvest --probe``.

Every step is a module of its own and runs standalone as well:
``python -m wikibase_static.step_build`` (from the repository root, with
``py`` on PYTHONPATH). Steps are started as child processes, so ``--list`` and
``--dry-run`` import nothing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / "py"
REPORT = ROOT / "dist" / "pipeline_report.txt"

# (name, module, in default run, description)
STEPS = [
    ("harvest", "step_harvest", False, "S4  fetch entities from a Wikibase (network, incremental)"),
    ("to-csv", "step_to_csv", False, "S7a harvested JSON -> CSV tables (writes data/csv)"),
    ("csv-fmt", "step_csv_fmt", False, "S7a canonical form of data/csv (--check for CI)"),
    ("import-open-archaeo", "step_import_open_archaeo", False, "S7c open-archaeo entries -> CSV tables (offline, writes data/csv)"),
    ("from-csv", "step_from_csv", True, "S7a CSV tables + kernel -> Wikibase JSON in data/derived"),
    ("load", "step_load", True, "S2  read data/raw and data/derived, check them"),
    ("build", "step_build", True, "S3  render the static pages into docs/"),
    ("search", "step_search", True, "S5  build the search index"),
    ("rdf", "step_rdf", True, "S6  export RDF in the Wikibase data model"),
    ("sparql", "step_sparql", True, "S6  build the in-browser SPARQL page"),
    ("check-crm", "step_check_crm", False, "S12 SHACL check: every class reaches the CIDOC CRM (after rdf)"),
]
NAMES = [s[0] for s in STEPS]


def select(args: argparse.Namespace) -> list[tuple[str, str, bool, str]]:
    """Resolve the command line into an ordered list of steps."""
    if args.verb:
        return [s for s in STEPS if s[0] == args.verb]
    if args.only:
        return [s for s in STEPS if s[0] == args.only]
    chosen = [s for s in STEPS if s[2] or s[0] == args.from_]
    if args.from_:
        start = next(i for i, s in enumerate(chosen) if s[0] == args.from_)
        chosen = chosen[start:]
    return [s for s in chosen if s[0] not in args.skip]


def run_step(step: tuple[str, str, bool, str], extra: list[str], lines: list[str]) -> tuple[int, int]:
    """Run one step as a child process; pass its output through line by line."""
    name, module = step[0], step[1]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PY) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", f"wikibase_static.{module}", *extra]
    proc = subprocess.Popen(
        cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    warnings = 0
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.lstrip().startswith("WARN"):
            warnings += 1
        emit(f"  {line}", lines)
    return proc.wait(), warnings


def emit(text: str, lines: list[str]) -> None:
    print(text, flush=True)
    lines.append(text)


def data_is_elsewhere() -> bool:
    """True when WBS_ROOT names a directory other than this repository."""
    root = os.environ.get("WBS_ROOT")
    return bool(root) and Path(root).resolve() != ROOT


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="wikibase-static orchestrator", add_help=True)
    parser.add_argument("verb", nargs="?", choices=NAMES, help="run exactly this step")
    parser.add_argument("--list", action="store_true", help="print the steps and exit")
    parser.add_argument("--only", choices=NAMES, help="run one step")
    parser.add_argument("--from", dest="from_", choices=NAMES, help="run this step and everything after it")
    parser.add_argument("--skip", action="append", default=[], choices=NAMES, help="leave a step out (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args, extra = parser.parse_known_args(argv)

    if args.list:
        for name, _module, default, description in STEPS:
            print(f"{name:9} {'default' if default else 'verb   '}  {description}")
        return 0

    steps = select(args)
    if extra and len(steps) != 1:
        parser.error(f"unrecognised arguments for several steps: {' '.join(extra)}")

    if args.dry_run:
        print("plan: " + (" -> ".join(s[0] for s in steps) or "(no steps)"))
        for name, module, _default, _description in steps:
            print(f"  {name}: python -m wikibase_static.{module} {' '.join(extra)}".rstrip())
        return 0

    lines: list[str] = []
    timings: list[tuple[str, float]] = []
    total_warnings = 0
    emit("wikibase-static: " + " -> ".join(s[0] for s in steps), lines)
    status = 0
    for step in steps:
        emit(f"[{step[0]}]", lines)
        started = time.perf_counter()
        rc, warnings = run_step(step, extra, lines)
        timings.append((step[0], time.perf_counter() - started))
        total_warnings += warnings
        if rc != 0:
            emit(f"step {step[0]} failed with exit code {rc}", lines)
            status = rc
            break
    if status == 0 and args.strict and total_warnings:
        emit(f"--strict: {total_warnings} warning(s) treated as errors", lines)
        status = 1

    # The report holds what the steps said, never how long they took,
    # so that running the pipeline twice leaves `git status` clean. Only a
    # full default run writes it: a partial run would replace the report
    # with a different, shorter one and show up as a change in `git status`.
    full_run = not (args.verb or args.only or args.from_ or args.skip)
    if full_run and data_is_elsewhere():
        # WBS_ROOT points to a site repository: the steps worked on its data, so a report written here
        # would describe that site, not this repository (and would be committed by mistake).
        print(f"\nreport not written: WBS_ROOT={os.environ['WBS_ROOT']} is not this repository (unset it to write {REPORT.name})")
    elif full_run:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")

    total = sum(t for _n, t in timings) or 1e-9
    print("\ntiming (terminal only):")
    for name, seconds in timings:
        print(f"  {name:9} {seconds:6.2f}s  {100 * seconds / total:5.1f}%")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
