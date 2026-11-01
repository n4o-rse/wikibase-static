#!/usr/bin/env python3
"""Bring the satellite repositories to a version of wikibase-static.

    python tools/rollout.py                 the version of this package (py/wikibase_static/__init__.py)
    python tools/rollout.py 0.25.0          a given version
    python tools/rollout.py --dry-run       say what would happen, change nothing
    python tools/rollout.py --only fuzzy-sl-static --no-push
    python tools/rollout.py --here          the repository in the current folder, to the newest release (what .github/workflows/update.yml runs)

For every repository in ``tools/satellites.txt`` (cloned next to this one when it is missing) it does what you would do by hand:
``git pull``, change the pin in ``requirements.txt`` to ``@vX.Y.Z``, ``pip install --upgrade --force-reinstall -r requirements.txt``,
``python main.py --strict`` twice (and ``check_attribution.py`` where the repository has it), commit, build once more to be sure that the
commit is what a fresh build makes (the check of the CI), and push. A repository with uncommitted changes is skipped; a step that
fails stops that repository and the others go on. The tag ``vX.Y.Z`` has to be on GitHub first (``git push origin --tags``).
The package is installed once per run, not once per repository, when the installed version is the one wanted already.

``--here`` does the first half only, in the current folder: change the pin, install, build twice, check the attribution. It leaves the
changes in the working tree and writes ``changed``, ``version`` and ``old`` to ``$GITHUB_OUTPUT`` when that is set; the workflow makes
the branch and the pull request from there.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
INIT = PACKAGE / "py" / "wikibase_static" / "__init__.py"
SATELLITES = HERE / "satellites.txt"
REPO_URL = "https://github.com/n4o-rse/wikibase-static.git"
PIN = re.compile(r"(wikibase-static\s*@\s*git\+https://github\.com/n4o-rse/wikibase-static\.git@)(\S+)")
VERSION = re.compile(r'^__version__ = "([^"]+)"', re.M)


def package_version() -> str:
    match = VERSION.search(INIT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"no __version__ in {INIT}")
    return match.group(1)


def read_satellites(text: str) -> list[str]:
    """``owner/repo`` per line; ``#`` starts a comment."""
    found = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", line):
                raise SystemExit(f"not an owner/repo: {line!r}")
            found.append(line)
    return found


def repin(text: str, tag: str) -> tuple[str, str | None]:
    """The text of requirements.txt with the pin at ``tag``, and the tag it had (None: there is no pin)."""
    old: list[str] = []

    def swap(match: re.Match) -> str:
        old.append(match.group(2))
        return match.group(1) + tag

    new = PIN.sub(swap, text)
    return new, (old[0] if old else None)


def newest(tags: list[str]) -> str | None:
    """The highest ``vX.Y.Z`` of a list of tag names (others are ignored), without the v."""
    found = []
    for tag in tags:
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag.strip())
        if match:
            found.append((tuple(int(x) for x in match.groups()), tag.strip()[1:]))
    return max(found)[1] if found else None


def latest_tag() -> str | None:
    done = subprocess.run(["git", "ls-remote", "--tags", "--refs", REPO_URL, "v*"], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit("cannot read the tags of " + REPO_URL + ": " + done.stderr.strip())
    return newest([line.split("refs/tags/", 1)[1] for line in done.stdout.splitlines() if "refs/tags/" in line])


class Failed(Exception):
    pass


def run(args: list[str], cwd: Path, label: str) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-25:])
        raise Failed(f"{label} failed ({result.returncode}):\n{tail}")
    return result.stdout


def installed_version(folder: Path) -> str | None:
    done = subprocess.run([sys.executable, "-c", "import wikibase_static; print(wikibase_static.__version__)"],
                          cwd=folder, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def prepare(folder: Path, version: str, name: str, force: bool = False) -> str | None:
    """Change the pin, install, build twice, check the attribution. The changes stay in the working tree.

    Returns the tag the pin had before, or None when there was nothing to do (the pin is at the version already)."""
    tag = f"v{version}"
    req = folder / "requirements.txt"
    new, old = repin(req.read_bytes().decode("utf-8"), tag)
    if old is None:
        raise Failed("requirements.txt has no wikibase-static pin (...git@vX.Y.Z)")
    if old == tag and not force:
        return None
    print(f"[{name}] pin {old} -> {tag}")
    req.write_bytes(new.encode("utf-8"))
    if installed_version(folder) != version:
        run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--force-reinstall", "-r", "requirements.txt"], folder, "pip install")
        got = installed_version(folder)
        if got != version:
            raise Failed(f"pip installed {got}, not {version}")
    for round_ in (1, 2):
        print(f"[{name}] build {round_}/2")
        run([sys.executable, "main.py", "--strict"], folder, f"main.py --strict (round {round_})")
    if (folder / "check_attribution.py").is_file():
        print(f"[{name}] check_attribution")
        run([sys.executable, "check_attribution.py"], folder, "check_attribution.py")
    return old


def roll(slug: str, base: Path, version: str, args: argparse.Namespace) -> str:
    """One repository; returns a line for the summary."""
    name = slug.split("/", 1)[1]
    folder = base / name
    tag = f"v{version}"
    if not folder.is_dir():
        if args.dry_run:
            return f"would clone {slug} to {folder}"
        print(f"[{name}] clone")
        run(["git", "clone", "-q", f"https://github.com/{slug}.git", str(folder)], base, "git clone")
    if run(["git", "status", "--porcelain"], folder, "git status").strip():
        return "SKIPPED: uncommitted changes (commit or discard them first)"
    if not args.dry_run:
        run(["git", "pull", "-q", "--ff-only"], folder, "git pull")
    req = folder / "requirements.txt"
    if not req.is_file():
        return "SKIPPED: no requirements.txt"
    old = repin(req.read_bytes().decode("utf-8"), tag)[1]
    if old is None:
        return "SKIPPED: requirements.txt has no wikibase-static pin (...git@vX.Y.Z)"
    if old == tag and not args.force:
        return f"up to date ({tag})"
    if args.dry_run:
        return f"would change the pin {old} -> {tag}, build twice, commit and {'not ' if args.no_push else ''}push"
    prepare(folder, version, name, args.force)
    run(["git", "add", "-A"], folder, "git add")
    if not run(["git", "status", "--porcelain"], folder, "git status").strip():
        return f"nothing to commit after the pin change ({tag})"
    run(["git", "commit", "-q", "-m", f"Use wikibase-static {tag} and rebuild"], folder, "git commit")
    print(f"[{name}] build 3/3 (the CI check: nothing may change)")
    run([sys.executable, "main.py", "--strict"], folder, "main.py --strict (check)")
    if run(["git", "status", "--porcelain"], folder, "git status").strip():
        raise Failed("a third build changes files again: the commit is not what a fresh build makes (committed here, not pushed)")
    if args.no_push:
        return f"committed ({tag}), not pushed"
    run(["git", "push", "-q"], folder, "git push")
    return f"pushed ({tag})"


def here(version: str, args: argparse.Namespace) -> int:
    """The repository in the current folder (for the workflow): the first half of ``roll``."""
    folder = Path.cwd()
    try:
        old = prepare(folder, version, folder.name, args.force)
    except Failed as error:
        print(f"FAILED: {error}")
        return 1
    changed = old is not None
    print(f"wikibase-static v{version}: {'changed from ' + old if changed else 'the pin is at this version already'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\nversion=v{version}\nold={old or ''}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python tools/rollout.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("version", nargs="?", help="X.Y.Z (default: the version of this package)")
    parser.add_argument("--only", action="append", default=[], metavar="NAME", help="only this repository (its name; repeatable)")
    parser.add_argument("--base", type=Path, default=PACKAGE.parent, help="the folder that holds the repositories (default: next to this one)")
    parser.add_argument("--dry-run", action="store_true", help="change nothing")
    parser.add_argument("--no-push", action="store_true", help="commit, but do not push")
    parser.add_argument("--force", action="store_true", help="build and commit also when the pin is at the version already")
    parser.add_argument("--here", action="store_true", help="the repository in the current folder only: pin, install, build, no commit (for the workflow)")
    args = parser.parse_args(argv)

    if args.here:
        found = args.version or latest_tag()
        if not found:
            print("no release tag found on GitHub")
            return 1
        return here(found.lstrip("v"), args)
    version = (args.version or package_version()).lstrip("v")
    tags = subprocess.run(["git", "ls-remote", "--tags", REPO_URL, f"refs/tags/v{version}"], capture_output=True, text=True)
    if tags.returncode == 0 and not tags.stdout.strip():
        print(f"The tag v{version} is not on GitHub yet: python tools/tag_versions.py && git push origin --tags")
        return 2
    slugs = read_satellites(SATELLITES.read_text(encoding="utf-8"))
    if args.only:
        slugs = [s for s in slugs if s.split("/", 1)[1] in args.only]
    results, failed = [], 0
    for slug in slugs:
        try:
            results.append((slug, roll(slug, args.base, version, args)))
        except Failed as error:
            failed += 1
            results.append((slug, f"FAILED: {error}"))
    print(f"\nwikibase-static v{version}")
    for slug, line in results:
        print(f"  {slug}: {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
