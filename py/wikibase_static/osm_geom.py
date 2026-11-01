"""The geometry of an OSM way or relation at every moment it changed (S15b/S6), from stored histories only; no network, no clock.

A node has a position in each of its versions. A way is a list of node ids, a relation a list of members, and neither carries
coordinates. Their shape at a moment T is therefore built from the version of the element that was current at T and the version
of every member node (and member way) that was current at T. The shape changes when the element gets a new version **or** when
any member does (a moved node does not raise the version of its way), so the moments that matter are all version timestamps of
the element and its members. ``events`` walks them in order and keeps those where the WKT differs from the one before.

Shapes: a way is a POLYGON when it is closed (four or more nodes, first = last) and is not a linear feature (a closed
``highway``, ``barrier``, ``waterway``, ``railway``, ``power``, ``route`` or ``man_made=pipeline`` is a LINESTRING unless
``area=yes``; ``area=no`` is a LINESTRING too), otherwise a LINESTRING. A relation of type ``multipolygon`` or ``boundary`` is
assembled from its ``outer`` and ``inner`` member ways into a POLYGON or MULTIPOLYGON; any other relation is a MULTILINESTRING of
its member ways, a MULTIPOINT of its member nodes, or a GEOMETRYCOLLECTION of both. Members of type relation are not followed.
A shape that cannot be built (a member history is missing, a ring does not close) is skipped at that moment and named in ``notes``;
the keys of missing histories are in ``missing`` so that the harvest can fetch them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wikibase_static import wkt

Position = wkt.Position
LINEAR_KEYS = ("highway", "barrier", "waterway", "railway", "power", "route")


class Store:
    """Histories by key (``node/123``) from one or more folders of ``<type>_<id>.json`` files; the first folder that has a key wins."""

    def __init__(self, *folders: Path) -> None:
        self.folders = [f for f in folders if f is not None]
        self._cache: dict[str, list[dict] | None] = {}

    def versions(self, key: str) -> list[dict] | None:
        if key not in self._cache:
            self._cache[key] = self._read(key)
        return self._cache[key]

    def _read(self, key: str) -> list[dict] | None:
        name = key.replace("/", "_") + ".json"
        for folder in self.folders:
            path = folder / name
            if not path.is_file():
                continue
            try:
                elements = json.loads(path.read_text(encoding="utf-8-sig")).get("elements", [])
            except (OSError, ValueError, AttributeError):
                return None
            versions = [e for e in elements if isinstance(e, dict) and isinstance(e.get("version"), int)]
            versions.sort(key=lambda e: e["version"])
            return versions or None
        return None

    def keys(self) -> set[str]:
        found: set[str] = set()
        for folder in self.folders:
            if folder.is_dir():
                found.update(p.stem.replace("_", "/", 1) for p in folder.glob("*.json"))
        return found


def version_at(versions: list[dict], time: str) -> dict | None:
    """The last version whose timestamp is not after ``time`` (ISO 8601 UTC strings compare as text)."""
    found = None
    for v in versions:
        if str(v.get("timestamp", "")) <= time:
            found = v
        else:
            break
    return found


def member_keys(kind: str, versions: list[dict], store: Store) -> set[str]:
    """The histories needed to build the shape of a way or relation: its nodes; its member ways and nodes, and the nodes of those ways
    (as far as their histories are in the store; the harvest asks again after it has fetched them)."""
    keys: set[str] = set()
    for v in versions:
        if kind == "way":
            keys.update(f"node/{n}" for n in v.get("nodes") or [])
        elif kind == "relation":
            for m in v.get("members") or []:
                if m.get("type") in ("way", "node") and isinstance(m.get("ref"), int):
                    keys.add(f"{m['type']}/{m['ref']}")
    if kind == "relation":
        for key in sorted(k for k in keys if k.startswith("way/")):
            for v in store.versions(key) or []:
                keys.update(f"node/{n}" for n in v.get("nodes") or [])
    return keys


@dataclass
class Event:
    time: str          # the moment the shape changed
    version: int       # the version of the element that was current then
    wkt: str


@dataclass
class Result:
    events: list[Event] = field(default_factory=list)
    missing: set[str] = field(default_factory=set)
    notes: set[str] = field(default_factory=set)


class _At:
    """Shapes at one moment."""

    def __init__(self, store: Store, time: str, result: Result) -> None:
        self.store, self.time, self.result = store, time, result

    def node(self, number: int) -> Position | None:
        key = f"node/{number}"
        versions = self.store.versions(key)
        if versions is None:
            self.result.missing.add(key)
            return None
        v = version_at(versions, self.time)
        if v is None or not v.get("visible", True) or "lat" not in v or "lon" not in v:
            self.result.notes.add(f"{key} has no position at some moment a shape needs it")
            return None
        return (float(v["lon"]), float(v["lat"]))

    def way_version(self, number: int) -> dict | None:
        key = f"way/{number}"
        versions = self.store.versions(key)
        if versions is None:
            self.result.missing.add(key)
            return None
        v = version_at(versions, self.time)
        if v is None or not v.get("visible", True):
            self.result.notes.add(f"{key} does not exist at some moment a shape needs it")
            return None
        return v

    def way_positions(self, version: dict) -> list[Position] | None:
        points = [self.node(n) for n in version.get("nodes") or []]
        if any(p is None for p in points):
            return None
        return points  # type: ignore[return-value]


def is_area(tags: dict[str, str], closed: bool) -> bool:
    if not closed:
        return False
    if tags.get("area") == "yes":
        return True
    if tags.get("area") == "no":
        return False
    return not (any(k in tags for k in LINEAR_KEYS) or tags.get("man_made") == "pipeline")


def way_shape(points: list[Position], tags: dict[str, str]) -> str | None:
    if len(points) < 2:
        return None
    closed = len(points) >= 4 and points[0] == points[-1]
    return wkt.polygon([points]) if is_area(tags, closed) else wkt.linestring(points)


def _inside(p: Position, ring: list[Position]) -> bool:
    x, y, inside = p[0], p[1], False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def rings_of(lines: list[list[Position]]) -> list[list[Position]] | None:
    """Join the lines end to end into closed rings; ``None`` when one cannot be closed."""
    pool = [list(line) for line in lines if len(line) >= 2]
    rings: list[list[Position]] = []
    while pool:
        current = pool.pop(0)
        while current[0] != current[-1]:
            for index, other in enumerate(pool):
                if other[0] == current[-1]:
                    current += other[1:]
                elif other[-1] == current[-1]:
                    current += list(reversed(other))[1:]
                elif other[-1] == current[0]:
                    current = other[:-1] + current
                elif other[0] == current[0]:
                    current = list(reversed(other))[:-1] + current
                else:
                    continue
                pool.pop(index)
                break
            else:
                return None
        if len(current) < 4:
            return None
        rings.append(current)
    return rings


def area_shape(outer: list[list[Position]], inner: list[list[Position]]) -> str | None:
    outers, inners = rings_of(outer), rings_of(inner)
    if not outers or inners is None:
        return None
    polygons = [[o] for o in outers]
    for hole in inners:
        for polygon in polygons:
            if _inside(hole[0], polygon[0]):
                polygon.append(hole)
                break
    return wkt.polygon(polygons[0]) if len(polygons) == 1 else wkt.multipolygon(polygons)


def relation_shape(at: _At, version: dict) -> str | None:
    tags = version.get("tags") or {}
    members = [m for m in version.get("members") or [] if isinstance(m, dict)]
    if any(m.get("type") == "relation" for m in members):
        at.result.notes.add("a member of type relation is not followed")
    complete = True
    ways: list[tuple[str, list[Position]]] = []
    nodes: list[Position] = []
    for m in members:
        if not isinstance(m.get("ref"), int):
            continue
        if m.get("type") == "way":
            wv = at.way_version(m.get("ref"))
            points = at.way_positions(wv) if wv is not None else None
            if points is None:
                complete = False
            else:
                ways.append((str(m.get("role", "")), points))
        elif m.get("type") == "node":
            p = at.node(m.get("ref"))
            if p is None:
                complete = False
            else:
                nodes.append(p)
    if not complete:
        return None
    if tags.get("type") in ("multipolygon", "boundary"):
        shape = area_shape([p for r, p in ways if r in ("outer", "")], [p for r, p in ways if r == "inner"])
        if shape is None:
            at.result.notes.add("a multipolygon whose outer ring does not close, or has no outer way")
        return shape
    lines = [p for _r, p in ways if len(p) >= 2]
    parts = ([wkt.multilinestring(lines)] if lines else []) + ([wkt.multipoint(nodes)] if nodes else [])
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else wkt.collection(parts)


def events(kind: str, versions: list[dict], store: Store) -> Result:
    """The shape of a way or relation each time it changed, from the first moment all its parts are known."""
    result = Result()
    keys = member_keys(kind, versions, store)
    times = {str(v.get("timestamp", "")) for v in versions if v.get("visible", True)}
    for key in sorted(keys):
        members = store.versions(key)
        if members is None:
            result.missing.add(key)
            continue
        times.update(str(v.get("timestamp", "")) for v in members)
    previous = None
    for time in sorted(t for t in times if t):
        v = version_at(versions, time)
        if v is None or not v.get("visible", True):
            continue
        at = _At(store, time, result)
        if kind == "way":
            points = at.way_positions(v)
            shape = way_shape(points, v.get("tags") or {}) if points is not None else None
        else:
            shape = relation_shape(at, v)
        if shape is None or shape == previous:
            continue
        previous = shape
        result.events.append(Event(time, v["version"], shape))
    return result
