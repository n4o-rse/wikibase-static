#!/usr/bin/env python3
"""Entry point of this site repository (thin wrapper around the wikibase-static package).

    python main.py harvest --probe      one test request to the source Wikibase, writes nothing (network)
    python main.py harvest              back up the source Wikibase into data/raw/ (network, incremental)
    python main.py fetch-logo           save the logo of the source Wikibase as assets/logo.<ext> (network; --file PATH: your own image)
    python main.py                      all other steps in order (from-csv, load, build, search, rdf, sparql)
    python main.py --strict             the same, but any WARN line (a dead link, a bad entity) is an error
    python main.py --strict check-crm   SHACL check: every class reaches the CIDOC CRM (needs data/crm.csv)
    python main.py --list               print the steps and exit

Everything is done by the installed package ``wikibase-static`` ({{version}} or later); this file only points it at this
repository (WBS_ROOT) and starts the steps. Any further arguments are passed to the step.

``harvest`` and ``fetch-logo`` are the only steps that use the network and they write source files, so they never run in the
default run. The source Wikibase is ``source.url`` of site.yaml; the first ``harvest`` takes it from there (a later one from
data/raw/manifest.json). Order after every change at the source: harvest, then the default run.

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
    ("harvest", "step_harvest", False),
    ("fetch-logo", "step_fetch_logo", False),
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


def source_url() -> str | None:
    """``source.url`` of site.yaml, for the first harvest."""
    import yaml  # installed with the package

    try:
        data = yaml.safe_load((ROOT / "site.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    source = data.get("source") if isinstance(data, dict) else None
    url = source.get("url") if isinstance(source, dict) else None
    return str(url).rstrip("/") if url else None


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

    # The first harvest has no manifest yet: the address comes from site.yaml, so it is written down once.
    name, module, extra = steps[0]
    if name == "harvest" and not any(o in extra for o in ("--url", "--from-dir")) and not (ROOT / "data" / "raw" / "manifest.json").is_file():
        url = source_url()
        if url:
            steps = [(name, module, [*extra, "--url", url])]

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
