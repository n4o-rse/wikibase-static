"""The network side of ``import-osm`` (S15a/S5): a polite client for Overpass and the OSM API, and the plan of what to fetch.

The client is a small wrapper around ``urllib``; its ``transport`` can be replaced, which is how the tests run it without a network.
It pauses between requests, honours ``Retry-After``, retries on 429, 502, 503 and 504, and sends an honest ``User-Agent``.
The plan compares what Overpass says (type, id, current version) with the history files on disk and names the elements that are
new, changed, unchanged, or no longer in the answer. Nothing here writes a file.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

OVERPASS = "https://overpass-api.de/api/interpreter"
API = "https://api.openstreetmap.org"
MAX_RETRIES = 4
BUSY = (429, 502, 503, 504)

Transport = Callable[[urllib.request.Request, float], "tuple[int, Any, bytes]"]


class OsmError(Exception):
    """A request that cannot be answered, or an answer that cannot be used; the message says what to do."""


class Unreachable(OsmError):
    """The host could not be contacted at all (DNS, refused, proxy, timeout)."""


def urllib_transport(request: urllib.request.Request, timeout: float) -> tuple[int, Any, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise Unreachable(f"cannot reach {request.full_url.split('?')[0]}: {err}") from err


def _retry_after(headers: Any) -> float | None:
    try:
        value = headers.get("Retry-After") if headers is not None else None
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class OsmClient:
    """GET and POST with pauses and retries; returns the body bytes unchanged (they are stored byte for byte)."""

    def __init__(self, user_agent: str, delay: float = 1.0, timeout: float = 60.0, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.user_agent, self.delay, self.timeout = user_agent, delay, timeout
        self.transport = transport or urllib_transport
        self.sleep = sleep
        self.requests = 0
        self.by_kind: dict[str, int] = {}
        self._last = 0.0

    def fetch(self, url: str, kind: str, data: dict[str, str] | None = None, timeout: float | None = None) -> bytes:
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers)
        for attempt in range(MAX_RETRIES + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if self._last and wait > 0:
                self.sleep(wait)
            self.requests += 1
            self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
            status, response_headers, content = self.transport(request, timeout or self.timeout)
            self._last = time.monotonic()
            if status in BUSY and attempt < MAX_RETRIES:
                retry = _retry_after(response_headers)
                pause = retry if retry is not None else min(2.0 ** attempt * max(self.delay, 1.0), 60.0)
                print(f"  host busy (HTTP {status}), waiting {pause:g}s before retrying")
                self.sleep(pause)
                continue
            if status in BUSY:
                raise OsmError(f"{url.split('?')[0]} stayed overloaded (HTTP {status}) after several retries; try again later")
            if status == 404:
                raise OsmError(f"HTTP 404 from {url.split('?')[0]}: there is no such element")
            if status >= 400:
                snippet = content[:120].decode("utf-8", "replace").replace("\n", " ")
                raise OsmError(f"HTTP {status} from {url.split('?')[0]} (first bytes: {snippet!r})")
            return content
        raise OsmError(f"{url.split('?')[0]}: no answer")


# --------------------------------------------------------------------------- what the answers say


def element_key(kind: str, number: int) -> str:
    return f"{kind}/{number}"


def parse_overpass(body: bytes) -> dict[str, int]:
    """key (``node/123``) -> current version, from an Overpass answer; a runtime error or a timeout of the query is an error."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as err:
        raise OsmError("Overpass did not answer with JSON (the query needs [out:json])") from err
    remark = str(data.get("remark", "")) if isinstance(data, dict) else ""
    if "runtime error" in remark or "timed out" in remark.lower():
        raise OsmError(f"Overpass could not finish the query: {remark}")
    elements = data.get("elements") if isinstance(data, dict) else None
    if not isinstance(elements, list):
        raise OsmError("the Overpass answer has no list `elements`")
    found: dict[str, int] = {}
    for e in elements:
        if isinstance(e, dict) and e.get("type") in ("node", "way", "relation") and isinstance(e.get("id"), int) \
                and isinstance(e.get("version"), int):
            found[element_key(e["type"], e["id"])] = e["version"]
    return found


def stored_overpass(path: Path) -> dict[str, int] | None:
    """The state of the stored Overpass answer, or ``None`` when there is none (or it cannot be read)."""
    if not path.is_file():
        return None
    try:
        return parse_overpass(path.read_bytes())
    except (OsmError, OSError):
        return None


def stored_histories(folder: Path) -> dict[str, int]:
    """key -> highest version, for the ``<type>_<id>.json`` files in ``folder`` (files that cannot be read are left out)."""
    found: dict[str, int] = {}
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        kind, _, number = path.stem.partition("_")
        if kind not in ("node", "way", "relation") or not number.isdigit():
            continue
        try:
            elements = json.loads(path.read_text(encoding="utf-8-sig")).get("elements", [])
            versions = [e["version"] for e in elements if isinstance(e, dict) and isinstance(e.get("version"), int)]
        except (OSError, ValueError, AttributeError):
            continue
        if versions:
            found[element_key(kind, int(number))] = max(versions)
    return found


@dataclass
class Plan:
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)       # stored, but not in the Overpass answer

    def to_fetch(self, refresh: bool = False) -> list[str]:
        return sorted(self.new + self.changed + (self.unchanged if refresh else []))


def make_plan(overpass: dict[str, int], stored: dict[str, int]) -> Plan:
    plan = Plan()
    for key in sorted(overpass):
        if key not in stored:
            plan.new.append(key)
        elif overpass[key] > stored[key]:
            plan.changed.append(key)
        else:
            plan.unchanged.append(key)
    plan.gone = sorted(k for k in stored if k not in overpass)
    return plan


def history_url(api: str, key: str) -> str:
    return f"{api.rstrip('/')}/api/0.6/{key}/history.json"


def check_history(key: str, body: bytes) -> list[dict]:
    """The element records of a history answer; it must hold at least one and all of them must be ``key``."""
    try:
        elements = json.loads(body.decode("utf-8-sig")).get("elements")
    except (UnicodeDecodeError, ValueError, AttributeError) as err:
        raise OsmError(f"the history of {key} is not JSON") from err
    kind, _, number = key.partition("/")
    if not isinstance(elements, list) or not elements:
        raise OsmError(f"the history of {key} holds no element")
    for e in elements:
        if not isinstance(e, dict) or e.get("type") != kind or e.get("id") != int(number) or not isinstance(e.get("version"), int):
            raise OsmError(f"the history of {key} holds a record that is not {key} with a version number")
    return elements


def same_in_common(old: list[dict], new: list[dict]) -> bool:
    """True when every version the old file has is in the new answer with the same content."""
    by_version = {e["version"]: e for e in new}
    return all(by_version.get(e["version"]) == e for e in old if isinstance(e, dict) and "version" in e)
