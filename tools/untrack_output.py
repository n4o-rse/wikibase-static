#!/usr/bin/env python3
"""Stop committing ``docs/`` and ``data/derived/`` in a site repository: the CI builds them and publishes them.

    python <path to>/tools/untrack_output.py                    the repository in the current folder
    python tools/untrack_output.py ../osm-ogham-static          another folder
    python tools/untrack_output.py --pages-is-actions           say that Settings -> Pages -> Source is "GitHub Actions"
    python tools/untrack_output.py --check                      only check, change nothing
    python tools/untrack_output.py --command "python main.py --strict && python check_attribution.py"

What it does, in this order, and stops at the first thing that is wrong:

1. The repository is clean (nothing uncommitted) and ``docs/`` is tracked.
2. GitHub Pages is served by GitHub Actions. With ``gh`` installed it asks GitHub; without it you confirm with
   ``--pages-is-actions``. A site that Pages serves from the branch (``main`` / ``/docs``) is gone the moment
   ``docs/`` leaves git, so this is the one thing to look at: Settings -> Pages -> Source.
3. It moves ``docs/`` and ``data/derived/`` away, builds the site from the sources (the command, ``python main.py --strict``
   by default) and compares the result with what was committed. A file that only the old folder has was made by hand, or
   by a step that is not in the command: the CI would not make it, so nothing is changed and the old folders come back.
4. It adds ``docs/`` and ``data/derived/`` to ``.gitignore`` and takes them out of the index (``git rm --cached``; the files
   stay on disk, so a local build and a preview work as before).

It does not commit. The last line it prints is the one-line commit and push. ``dist/`` (the Turtle and the report, the
products that are cited) stays in git.

The reusable workflow of wikibase-static (0.29.0 or later) notices by itself that ``docs/`` is not tracked: it builds twice,
compares a hash of ``docs/``, ``dist/`` and ``data/derived/`` and publishes the ``docs/`` of that build.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OUTPUT = ("docs", "data/derived")
IGNORE_MARK = "# Built by the pipeline, published by the CI (tools/untrack_output.py of wikibase-static):"
OLD_NOTE = re.compile(r"# --- Note ---\n(?:#[^\n]*\n)+", re.M)


class Stop(Exception):
    pass


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


def tree(root: Path) -> dict[str, str]:
    """Relative path (with ``/``) -> sha256 of every file under ``root``."""
    found: dict[str, str] = {}
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                found[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def compare(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    """What the committed folder has that a fresh build does not (``lost``), the reverse (``added``) and what differs."""
    return {
        "lost": sorted(set(old) - set(new)),
        "added": sorted(set(new) - set(old)),
        "changed": sorted(name for name in set(old) & set(new) if old[name] != new[name]),
    }


def ignore_text(text: str, folders: list[str]) -> str:
    """The text of ``.gitignore`` with the folders added (nothing is added twice); the old "do not ignore docs/" note goes."""
    text = OLD_NOTE.sub("", text) if "docs/" in text and "deliberately NOT ignored" in text else text
    present = {line.strip() for line in text.splitlines()}
    add = [f"{folder}/" for folder in folders if f"{folder}/" not in present and folder not in present]
    if not add:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    return text + IGNORE_MARK + "\n" + "\n".join(add) + "\n"


def owner_repo(folder: Path) -> str | None:
    try:
        url = git(folder, "remote", "get-url", "origin").strip()
    except Stop:
        return None
    match = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s*$", url)
    return match.group(1) if match else None


def pages_build_type(slug: str) -> str | None:
    """``workflow`` (GitHub Actions) or ``legacy`` (a branch), None when ``gh`` cannot tell."""
    if not shutil.which("gh"):
        return None
    done = subprocess.run(["gh", "api", f"repos/{slug}/pages", "--jq", ".build_type"], capture_output=True, text=True)
    return done.stdout.strip() or None if done.returncode == 0 else None


def move_aside(folder: Path, parking: Path, tracked: list[str]) -> list[str]:
    moved = []
    for name in tracked:
        source = folder / name
        if source.exists():
            target = parking / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved.append(name)
    return moved


def put_back(folder: Path, parking: Path, names: list[str]) -> None:
    for name in names:
        target = folder / name
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(parking / name), str(target))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="untrack_output.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", nargs="?", type=Path, default=Path("."), help="the site repository (default: the current folder)")
    parser.add_argument("--command", default="python main.py --strict", help="builds the site (run in a shell, in the folder)")
    parser.add_argument("--pages-is-actions", action="store_true", help="you checked: Settings -> Pages -> Source is GitHub Actions")
    parser.add_argument("--check", action="store_true", help="do the checks and the test build, change nothing")
    args = parser.parse_args(argv)
    folder = args.folder.resolve()
    try:
        if not (folder / ".git").exists():
            raise Stop(f"{folder} is not a git repository")
        if git(folder, "status", "--porcelain").strip():
            raise Stop("uncommitted changes: commit or discard them first")
        tracked = [name for name in OUTPUT if git(folder, "ls-files", name).strip()]
        if "docs" not in tracked:
            raise Stop("docs/ is not tracked: nothing to do (this repository builds in the CI already)")

        slug = owner_repo(folder)
        kind = pages_build_type(slug) if slug else None
        if kind == "legacy":
            raise Stop(f"GitHub Pages of {slug} is served from a branch: set Settings -> Pages -> Source to GitHub Actions first, "
                       "let the Site workflow deploy once, then run this again")
        if kind != "workflow" and not args.pages_is_actions:
            raise Stop("cannot tell whether GitHub Pages is served by GitHub Actions (no gh, or no answer): look at Settings -> Pages -> "
                       "Source, and run again with --pages-is-actions when it says GitHub Actions")

        old = {name: tree(folder / name) for name in tracked}
        with tempfile.TemporaryDirectory(prefix="untrack-") as parking_name:
            parking = Path(parking_name)
            moved = move_aside(folder, parking, tracked)
            try:
                print(f"building from the sources: {args.command}")
                built = subprocess.run(args.command, cwd=folder, shell=True)
                if built.returncode != 0:
                    raise Stop("the build from the sources fails (the folders are back as they were)")
                problems = []
                for name in tracked:
                    diff = compare(old[name], tree(folder / name))
                    for key, label in (("lost", "only in the committed folder"), ("added", "only in the fresh build"), ("changed", "different")):
                        for item in diff[key][:10]:
                            problems.append(f"{name}/{item}: {label}")
                        if len(diff[key]) > 10:
                            problems.append(f"{name}/: ... and {len(diff[key]) - 10} more ({label})")
                if problems:
                    hint = "\nFix the cause (a hand-made file belongs into assets/ or the pipeline), commit, and run this again."
                    if "docs/assets/version.js: different" in problems and not any(": only in" in item for item in problems):
                        hint = ("\nOnly files differ, none is missing or new, and version.js is among them: the installed wikibase-static is not the one "
                                "that built the committed site. Bring the repository to the installed version first (python tools/rollout.py "
                                "--only <name>, or its update.cmd), commit that, and run this again.")
                    raise Stop("a fresh build is not what is committed:\n  " + "\n  ".join(problems) + hint)
            except Stop:
                put_back(folder, parking, moved)
                raise
            if args.check:
                put_back(folder, parking, moved)
                print("check passed: a fresh build equals the committed docs/ and data/derived/; nothing was changed")
                return 0
            for name in moved:                                   # the fresh build stays on disk (it is the same)
                shutil.rmtree(parking / name, ignore_errors=True)

        ignore = folder / ".gitignore"
        before = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
        ignore.write_text(ignore_text(before, tracked), encoding="utf-8", newline="\n")
        for name in tracked:
            git(folder, "rm", "-r", "-q", "--cached", name)
        count = len(git(folder, "diff", "--cached", "--name-only").splitlines())
        print(f"{', '.join(tracked)} left the index ({count} files), .gitignore updated; the files on disk are the fresh build.")
        print("Commit and push (one line, Windows cmd):")
        print('git add -A && git commit -m "Stop tracking docs/ and data/derived/: built and published by the CI" && git push')
        return 0
    except Stop as error:
        print(f"STOPPED: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
