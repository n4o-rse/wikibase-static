"""S4 -- harvest entities from a Wikibase into data/raw/ (the only step that uses the network).

    python main.py harvest --url https://example.wikibase.cloud
    python main.py harvest --url https://example.wikibase.cloud --probe
    python main.py harvest --from-dir path/to/saved-json

How it works (PRIMER.md, S4):

1. One ``generator=allpages`` query per namespace lists every item and property
   together with the ``lastrevid`` of its page. That is the whole cost of a run
   in which nothing changed.
2. The list is compared with ``data/raw/manifest.json``. Only entities that are
   new, have a different ``lastrevid``, or whose file is missing or was edited by
   hand are fetched (``wbgetentities``, 50 per request).
3. Entities that no longer exist on the source are removed from ``data/raw/``.

Layout written:

    data/raw/manifest.json          source, and per entity: lastrevid, modified, sha256
    data/raw/entities/Q1.json       one entity object as Wikibase delivers it (keys sorted)

The manifest holds only values the server reported. There is no local clock in
it, so a second run on an unchanged source writes nothing at all.

Politeness: honest User-Agent, a pause between requests, ``maxlag`` on every
request, ``Retry-After`` honoured, only GET (and only GET is ever retried).
When a host answers with a bot challenge (Anubis, for example), the step stops
with a clear message and exit code 2. It never tries to solve or get around
the challenge; ``--from-dir`` reads JSON files saved in a browser instead.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # direct run: python py/wikibase_static/step_harvest.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikibase_static import __version__, utils

STEP = "harvest"
MANIFEST_SCHEMA = 1
BATCH = 50           # wbgetentities accepts at most 50 ids per request for normal users
LIST_LIMIT = 500     # allpages limit for normal users
MAXLAG = 5           # seconds; the standard value for bots
MAX_RETRIES = 4
EXIT_CHALLENGE = 2   # the host asked for a bot challenge, or is not reachable as an API

DEFAULT_CONTACT = "https://github.com/n4o-rse/wikibase-static"
CHALLENGE_MARKERS = ("anubis", "not a bot", "proof-of-work", "proof of work", "cf-challenge", "just a moment")


class HarvestError(Exception):
    """A problem that ends the step; the message is shown as it is."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


class Unreachable(HarvestError):
    """The host could not be contacted at all (DNS, refused, proxy, timeout)."""


# --------------------------------------------------------------------------- client


class Client:
    """A polite, read-only MediaWiki API client (GET only)."""

    def __init__(self, api: str, user_agent: str, delay: float = 1.0, timeout: float = 60.0) -> None:
        self.api = api
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self.requests = 0
        self.by_kind: dict[str, int] = {}
        self._last = 0.0

    def _pause(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if self._last and wait > 0:
            time.sleep(wait)

    def get(self, params: dict[str, Any], kind: str) -> dict[str, Any]:
        """One API call with retries on 429, 5xx and ``maxlag``; returns decoded JSON."""
        query = {"format": "json", "maxlag": str(MAXLAG), **params}
        url = self.api + "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        for attempt in range(MAX_RETRIES + 1):
            self._pause()
            self.requests += 1
            self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
            status, headers, body = self._open(request)
            self._last = time.monotonic()
            retry_after = _retry_after(headers)
            if status in (429, 502, 503, 504) and attempt < MAX_RETRIES and not _is_challenge(body):
                self._sleep_retry(retry_after, attempt)
                continue
            data = self._decode(status, body, url)
            error = data.get("error")
            if isinstance(error, dict) and error.get("code") == "maxlag" and attempt < MAX_RETRIES:
                self._sleep_retry(retry_after, attempt)
                continue
            if isinstance(error, dict):
                raise HarvestError(f"the API reported an error: {error.get('code')}: {error.get('info')}")
            return data
        raise HarvestError("the host stayed overloaded after several retries; try again later")

    def _sleep_retry(self, retry_after: float | None, attempt: int) -> None:
        pause = retry_after if retry_after is not None else min(2.0 ** attempt * max(self.delay, 1.0), 60.0)
        print(f"  host busy, waiting {pause:g}s before retrying")
        time.sleep(pause)

    def _open(self, request: urllib.request.Request) -> tuple[int, Any, bytes]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise Unreachable(f"cannot reach {self.api}: {err}") from err

    def _decode(self, status: int, body: bytes, url: str) -> dict[str, Any]:
        if _is_challenge(body):
            raise HarvestError(challenge_message(self.api), EXIT_CHALLENGE)
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            snippet = body[:120].decode("utf-8", "replace").replace("\n", " ")
            raise HarvestError(
                f"HTTP {status} from {self.api} did not return JSON (first bytes: {snippet!r}). "
                "Is --api the right address of api.php?", EXIT_CHALLENGE,
            ) from None
        if status >= 400 and "error" not in data:
            raise HarvestError(f"HTTP {status} from {self.api}")
        return data


def _retry_after(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers is not None else None
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


def _is_challenge(body: bytes) -> bool:
    head = body[:4000].lstrip()
    if head[:1] in (b"{", b"["):
        return False
    text = head.decode("utf-8", "replace").lower()
    return any(marker in text for marker in CHALLENGE_MARKERS)


def challenge_message(api: str) -> str:
    return (
        f"{api} answered with a bot challenge (for instance Anubis) instead of API data.\n"
        "  The harvest does not try to solve or get around such a protection.\n"
        "  Options: (1) save entity JSON in a browser, for example <site>/wiki/Special:EntityData/Q1.json,\n"
        "  into a folder and run: python main.py harvest --from-dir <folder>;\n"
        "  (2) ask the operator of the Wikibase to allow this client; the User-Agent names the contact."
    )


# --------------------------------------------------------------------------- discovery


def discover(client_factory: Any, base: str, api: str | None) -> tuple[Client, dict[str, Any]]:
    """Find api.php and read the namespaces; this is also what ``--probe`` runs."""
    candidates = [api] if api else [base + "/w/api.php", base + "/api.php"]
    last: HarvestError | None = None
    for candidate in candidates:
        client = client_factory(candidate)
        try:
            data = client.get({"action": "query", "meta": "siteinfo", "siprop": "general|namespaces"}, "site")
        except Unreachable:
            raise  # trying another path on the same host would not help
        except HarvestError as err:
            if err.code == EXIT_CHALLENGE and "bot challenge" in str(err):
                raise
            last = err
            continue
        general = data.get("query", {}).get("general", {})
        namespaces = data.get("query", {}).get("namespaces", {})
        if isinstance(namespaces, list):
            namespaces = {str(n.get("id")): n for n in namespaces}
        found: dict[str, int] = {}
        for ns in namespaces.values():
            model = ns.get("defaultcontentmodel") or ns.get("content_model")
            if model == "wikibase-item":
                found["item"] = int(ns["id"])
            elif model == "wikibase-property":
                found["property"] = int(ns["id"])
        if "item" not in found or "property" not in found:
            raise HarvestError(
                f"{candidate} is a MediaWiki API, but no Wikibase item and property namespaces were found "
                "(is the Wikibase extension enabled?)"
            )
        info = {
            "api": candidate,
            "generator": str(general.get("generator", "")),
            "namespaces": found,
        }
        return client, info
    raise last or HarvestError(f"no API found under {base}")


# --------------------------------------------------------------------------- manifest


def manifest_path(raw: Path) -> Path:
    return raw / "manifest.json"


def entity_path(raw: Path, entity_id: str) -> Path:
    return raw / "entities" / f"{entity_id}.json"


def load_manifest(raw: Path) -> dict[str, Any]:
    path = manifest_path(raw)
    if not path.exists():
        return {"schema": MANIFEST_SCHEMA, "source": {}, "entities": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        raise HarvestError(f"{path} is not valid JSON ({err}); fix or remove it") from err
    data.setdefault("entities", {})
    data.setdefault("source", {})
    return data


def entity_text(entity: dict[str, Any]) -> str:
    return json.dumps(entity, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def store_entity(raw: Path, entity: dict[str, Any]) -> dict[str, Any]:
    """Write one entity canonically (only when it differs) and return its manifest row."""
    text = entity_text(entity)
    path = entity_path(raw, entity["id"])
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        utils.write_text(path, text)
    return {
        "lastrevid": entity.get("lastrevid"),
        "modified": entity.get("modified"),
        "sha256": utils.content_fingerprint(text),
    }


def write_manifest(raw: Path, manifest: dict[str, Any]) -> bool:
    """Write the manifest only when it changed; returns whether it did."""
    rows = manifest["entities"]
    modified = [row["modified"] for row in rows.values() if row.get("modified")]
    manifest["schema"] = MANIFEST_SCHEMA
    manifest["latest_modified"] = max(modified) if modified else None
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    path = manifest_path(raw)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    utils.write_text(path, text)
    return True


def is_current(raw: Path, entity_id: str, row: dict[str, Any] | None, lastrevid: int) -> bool:
    """Is the stored copy of this entity still what the server has?"""
    if not row or row.get("lastrevid") != lastrevid:
        return False
    path = entity_path(raw, entity_id)
    return path.exists() and utils.content_fingerprint(path) == row.get("sha256")


# --------------------------------------------------------------------------- listing and fetching


def list_entities(client: Client, namespaces: dict[str, int]) -> dict[str, int]:
    """``{entity id: lastrevid}`` for every item and property, from allpages with page info."""
    listing: dict[str, int] = {}
    for kind in ("item", "property"):
        params: dict[str, Any] = {
            "action": "query", "generator": "allpages", "gapnamespace": str(namespaces[kind]),
            "gaplimit": str(LIST_LIMIT), "prop": "info",
        }
        while True:
            data = client.get(params, "list")
            pages = data.get("query", {}).get("pages", {})
            for page in (pages.values() if isinstance(pages, dict) else pages):
                if "missing" in page or page.get("lastrevid") is None:
                    continue
                entity_id = str(page["title"]).split(":", 1)[-1]  # "Item:Q1" on Wikibase Cloud, "Q1" on Wikidata
                listing[entity_id] = int(page["lastrevid"])
            more = data.get("continue")
            if not more:
                break
            params = {**params, **more}
    return listing


def fetch_entities(client: Client, ids: list[str]) -> list[dict[str, Any]]:
    """Fetch full entity JSON in batches; the order of ``ids`` does not matter."""
    entities: list[dict[str, Any]] = []
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        data = client.get({"action": "wbgetentities", "ids": "|".join(batch)}, "fetch")
        got = data.get("entities", {})
        for entity_id in batch:
            entity = got.get(entity_id)
            if not isinstance(entity, dict) or "missing" in entity or entity.get("id") is None:
                utils.warn(STEP, f"{entity_id} was listed but could not be fetched; skipped")
                continue
            entities.append(entity)
    return entities


# --------------------------------------------------------------------------- modes


def run_api(args: argparse.Namespace, raw: Path) -> int:
    base = args.url.rstrip("/") if args.url else None
    manifest = load_manifest(raw)
    source = manifest["source"]
    if base is None:
        base = source.get("url")
    if not base:
        raise HarvestError("no source given: use --url https://<your>.wikibase.cloud (it is remembered in the manifest)")
    if source.get("url") and source["url"] != base:
        raise HarvestError(
            f"data/raw/ already holds {source['url']}, not {base}. "
            "Use a separate repository or directory per Wikibase."
        )

    contact = args.contact or os.environ.get("WBS_CONTACT") or DEFAULT_CONTACT
    user_agent = f"wikibase-static/{__version__} (+{contact}; static archive, read-only)"

    def factory(api_url: str) -> Client:
        return Client(api_url, user_agent, delay=args.delay)

    cached = source.get("api") and source.get("namespaces") and not args.rediscover and not args.probe
    if cached:
        client = factory(args.api or source["api"])
        info = {"api": client.api, "generator": source.get("generator", ""), "namespaces": source["namespaces"]}
    else:
        client, info = discover(factory, base, args.api)

    if args.probe:
        print(f"[{STEP}] probe: {info['api']} answers as an API ({info['generator'] or 'generator unknown'})")
        print(f"[{STEP}] probe: item namespace {info['namespaces']['item']}, "
              f"property namespace {info['namespaces']['property']}; no bot challenge")
        print(f"[{STEP}] requests: {client.requests}; nothing written")
        return 0

    listing = list_entities(client, info["namespaces"])
    rows: dict[str, Any] = manifest["entities"]
    todo = sorted(i for i, rev in listing.items() if not is_current(raw, i, rows.get(i), rev))
    gone = sorted(set(rows) - set(listing))

    for entity in fetch_entities(client, todo):
        rows[entity["id"]] = store_entity(raw, entity)
    for entity_id in gone:
        path = entity_path(raw, entity_id)
        if path.exists():
            path.unlink()
        del rows[entity_id]

    manifest["source"] = {
        "url": base, "api": info["api"], "generator": info["generator"], "namespaces": info["namespaces"],
    }
    changed_manifest = write_manifest(raw, manifest)

    items = sum(1 for i in listing if i.startswith("Q"))
    props = sum(1 for i in listing if i.startswith("P"))
    print(f"[{STEP}] source: {base}")
    print(f"[{STEP}] listed {len(listing)} entities ({items} items, {props} properties)")
    print(f"[{STEP}] {len(todo)} changed, {len(gone)} deleted, {len(listing) - len(todo)} unchanged"
          + ("" if changed_manifest or todo or gone else " (nothing written)"))
    kinds = ", ".join(f"{k} {v}" for k, v in sorted(client.by_kind.items()))
    print(f"[{STEP}] requests: {client.requests} ({kinds})")
    return 0


def read_saved(path: Path) -> list[dict[str, Any]]:
    """Entity objects from a saved file: Special:EntityData, wbgetentities, or a bare entity."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("entities"), dict):
        return [e for e in data["entities"].values() if isinstance(e, dict) and e.get("id")]
    if isinstance(data, dict) and data.get("id"):
        return [data]
    raise ValueError("no entity found")


def run_from_dir(args: argparse.Namespace, raw: Path) -> int:
    folder = Path(args.from_dir)
    if not folder.is_dir():
        raise HarvestError(f"--from-dir {folder}: not a directory")
    manifest = load_manifest(raw)
    rows: dict[str, Any] = manifest["entities"]
    files = sorted(folder.rglob("*.json"))
    added = updated = unchanged = skipped = 0
    for path in files:
        try:
            entities = read_saved(path)
        except (ValueError, OSError) as err:
            utils.warn(STEP, f"{path.name}: skipped ({err})")
            skipped += 1
            continue
        for entity in entities:
            if str(entity["id"])[:1] not in ("Q", "P"):
                utils.warn(STEP, f"{path.name}: {entity['id']} is not an item or property; skipped")
                skipped += 1
                continue
            before = rows.get(entity["id"])
            row = store_entity(raw, entity)
            rows[entity["id"]] = row
            if before is None:
                added += 1
            elif before != row:
                updated += 1
            else:
                unchanged += 1
    if args.url:
        manifest["source"]["url"] = args.url.rstrip("/")
    changed_manifest = write_manifest(raw, manifest)
    print(f"[{STEP}] read {len(files)} file(s) from {folder.name}")
    print(f"[{STEP}] {added + updated} changed ({added} new, {updated} updated), "
          f"{unchanged} unchanged, {skipped} skipped; nothing deleted in --from-dir mode"
          + ("" if changed_manifest or added or updated else " (nothing written)"))
    print(f"[{STEP}] requests: 0")
    return 0


# --------------------------------------------------------------------------- entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py harvest",
        description="Back up the items and properties of a Wikibase into data/raw/ (incremental).",
    )
    parser.add_argument("--url", help="base address of the Wikibase, e.g. https://example.wikibase.cloud "
                                      "(remembered in data/raw/manifest.json)")
    parser.add_argument("--api", help="full address of api.php if it is not <url>/w/api.php or <url>/api.php")
    parser.add_argument("--probe", action="store_true",
                        help="one test request: report whether the host answers as an API or with a bot challenge")
    parser.add_argument("--from-dir", metavar="DIR",
                        help="read JSON files saved in a browser instead of using the network")
    parser.add_argument("--rediscover", action="store_true",
                        help="read the namespaces from the host again instead of using the manifest")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: 1)")
    parser.add_argument("--contact", help="contact (address or URL) named in the User-Agent; "
                                          "or set WBS_CONTACT (default: the repository URL)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_dir and args.probe:
        print("--probe and --from-dir cannot be combined", file=sys.stderr)
        return 1
    raw = utils.DATA_RAW
    try:
        if args.from_dir:
            return run_from_dir(args, raw)
        return run_api(args, raw)
    except HarvestError as err:
        print(f"ERROR: [{STEP}] {err}")
        return err.code


if __name__ == "__main__":
    raise SystemExit(main())
