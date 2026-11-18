"""Fetch the logo of a Wikibase once and keep it in the repository (0.30.0).

    python main.py fetch-logo                  ask the source Wikibase for its logo, save it as assets/logo.<ext>
    python main.py fetch-logo --file PATH      take a logo you saved yourself (when the host answers with a bot challenge)

The source address is ``source.url`` of ``site.yaml`` (or the one in ``data/raw/manifest.json``). The logo is the one the
Wikibase names in its site information (``siprop=general``, field ``logo``). The file is copied into the repository and
``logo:`` in ``site.yaml`` is set to it, so the published pages never load the image from the source Wikibase (if that is
gone, nothing here may break). The licence of the image is not known to this step: name it in ``site.yaml`` or the README.

Politeness and limits are those of ``harvest``: honest User-Agent, one request for the site information, one for the image,
GET only; a bot challenge (Anubis, for example) ends the step with exit code 2 and is never worked around.

Standard library only (the line in ``site.yaml`` is changed as text, so comments and order stay as they are).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # direct run
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, step_harvest, utils

STEP = "fetch-logo"
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/gif": "gif", "image/webp": "webp"}
SUFFIXES = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".svg": "svg", ".gif": "gif", ".webp": "webp"}
LOGO_LINE = re.compile(r"^#?[ \t]*logo:.*$", re.M)
MAX_BYTES = 5 * 1024 * 1024


class LogoError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def source_url(site_yaml: Path, manifest: Path) -> str | None:
    """``source.url`` of site.yaml, else the URL of the harvest manifest."""
    if site_yaml.is_file():
        import yaml  # the pages need it anyway (PyYAML is a requirement of the package)

        try:
            data = yaml.safe_load(site_yaml.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        source = data.get("source") if isinstance(data, dict) else None
        url = source.get("url") if isinstance(source, dict) else None
        if url:
            return str(url).rstrip("/")
    if manifest.is_file():
        try:
            url = json.loads(manifest.read_text(encoding="utf-8")).get("source", {}).get("url")
        except ValueError:
            url = None
        if url:
            return str(url).rstrip("/")
    return None


def extension_of(content_type: str, url: str, body: bytes) -> str | None:
    kind = content_type.split(";")[0].strip().lower()
    if kind in EXTENSIONS:
        return EXTENSIONS[kind]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in SUFFIXES:
        return SUFFIXES[suffix]
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if body[:3] == b"\xff\xd8\xff":
        return "jpg"
    if body.lstrip()[:5] in (b"<?xml", b"<svg "):
        return "svg"
    return None


def logo_url_of(base: str, user_agent: str, delay: float) -> str:
    """Ask the Wikibase for the address of its logo."""
    def factory(api: str) -> step_harvest.Client:
        return step_harvest.Client(api, user_agent, delay=delay)

    client, _info = step_harvest.discover(factory, base, None)
    general = client.get({"action": "query", "meta": "siteinfo", "siprop": "general"}, "site").get("query", {}).get("general", {})
    logo = str(general.get("logo") or "").strip()
    if not logo:
        raise LogoError(f"{base} names no logo in its site information; save one yourself and run: python main.py fetch-logo --file <path>")
    return urllib.parse.urljoin(base + "/", logo)


def download(url: str, user_agent: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "image/*"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read(MAX_BYTES + 1)
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as err:
        raise LogoError(f"HTTP {err.code} for {url}") from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise LogoError(f"cannot reach {url}: {err}") from err
    if len(body) > MAX_BYTES:
        raise LogoError(f"{url} is larger than {MAX_BYTES // 1024 // 1024} MB; not a logo")
    if step_harvest._is_challenge(body):
        raise LogoError(step_harvest.challenge_message(url), step_harvest.EXIT_CHALLENGE)
    return body, content_type


def set_logo_line(site_yaml: Path, value: str) -> bool:
    """Make ``logo: <value>`` the first (commented or not) ``logo:`` line of site.yaml; True if the file changed."""
    text = site_yaml.read_text(encoding="utf-8")
    new = f"logo: {value}"
    if LOGO_LINE.search(text):
        changed = LOGO_LINE.sub(new, text, count=1)
    else:
        changed = text.rstrip("\n") + f"\n{new}\n"
    if changed == text:
        return False
    utils.write_text(site_yaml, changed)
    return True


def save_logo(root: Path, body: bytes, ext: str) -> str:
    """Write assets/logo.<ext> (removing an older logo.* of another type) and return the relative path."""
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for old in assets.glob("logo.*"):
        if old.suffix.lstrip(".").lower() != ext:
            old.unlink()
    target = assets / f"logo.{ext}"
    if not target.exists() or target.read_bytes() != body:
        target.write_bytes(body)
    return f"assets/logo.{ext}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python main.py fetch-logo",
                                     description="Save the logo of the source Wikibase as assets/logo.<ext> and name it in site.yaml.")
    parser.add_argument("--file", metavar="PATH", help="use this image instead of asking the Wikibase")
    parser.add_argument("--url", help="base address of the Wikibase (default: source.url of site.yaml)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: 1)")
    parser.add_argument("--contact", help="contact named in the User-Agent (or WBS_CONTACT)")
    return parser


def run(args: argparse.Namespace) -> int:
    root = utils.ROOT
    if not utils.SITE_YAML.is_file():
        raise LogoError("no site.yaml in this folder")
    if args.file:
        path = Path(args.file)
        if not path.is_file():
            raise LogoError(f"--file {path}: no such file")
        body = path.read_bytes()
        ext = extension_of("", path.name, body)
        origin = str(path)
    else:
        base = (args.url or source_url(utils.SITE_YAML, utils.DATA_RAW / "manifest.json") or "").rstrip("/")
        if not base:
            raise LogoError("no source address: set source.url in site.yaml or use --url")
        contact = args.contact or os.environ.get("WBS_CONTACT") or step_harvest.DEFAULT_CONTACT
        user_agent = f"wikibase-static/{__version__} (+{contact}; static archive, read-only)"
        try:
            logo = logo_url_of(base, user_agent, args.delay)
        except step_harvest.HarvestError as err:
            raise LogoError(str(err), err.code) from err
        body, content_type = download(logo, user_agent)
        ext = extension_of(content_type, logo, body)
        origin = logo
    if ext is None:
        raise LogoError(f"{origin} is not an image of a known type (png, jpg, svg, gif, webp)")
    relative = save_logo(root, body, ext)
    changed = set_logo_line(utils.SITE_YAML, relative)
    print(f"[{STEP}] {origin} -> {relative} ({len(body)} bytes); site.yaml " + ("changed" if changed else "already named it"))
    print(f"[{STEP}] the licence of the image is not known here: say it in README.md (or in the license block of site.yaml)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except LogoError as err:
        print(f"ERROR: [{STEP}] {err}")
        return err.code


if __name__ == "__main__":
    raise SystemExit(main())
