"""Well-known text (WKT) for the geometries of an OSM element (S15b/S6): write, read, and turn into GeoJSON for the map.

Coordinates are ``lon lat`` (the order GeoSPARQL and ``POINT(x y)`` use), seven decimals, trailing zeros removed. The reader
understands POINT, LINESTRING, POLYGON, MULTIPOINT, MULTILINESTRING, MULTIPOLYGON and GEOMETRYCOLLECTION (also ``EMPTY`` is
refused: a geometry without a position is no geometry), in any letter case; a leading ``<crs-IRI>`` is skipped.
It returns GeoJSON geometry dicts, which is what Leaflet takes.
"""

from __future__ import annotations

import re
from typing import Any

Position = tuple[float, float]          # (lon, lat)
TOKEN = re.compile(r"\s*([A-Za-z]+|\(|\)|,|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
KINDS = {"POINT": "Point", "LINESTRING": "LineString", "POLYGON": "Polygon", "MULTIPOINT": "MultiPoint",
         "MULTILINESTRING": "MultiLineString", "MULTIPOLYGON": "MultiPolygon", "GEOMETRYCOLLECTION": "GeometryCollection"}
NAMES = {v: k for k, v in KINDS.items()}


class WktError(ValueError):
    pass


def num(value: float) -> str:
    return format(value, ".7f").rstrip("0").rstrip(".") or "0"


def pos(p: Position) -> str:
    return f"{num(p[0])} {num(p[1])}"


def ring(points: list[Position]) -> str:
    return "(" + ", ".join(pos(p) for p in points) + ")"


def point(p: Position) -> str:
    return f"POINT({pos(p)})"


def linestring(points: list[Position]) -> str:
    return "LINESTRING" + ring(points)


def polygon(rings: list[list[Position]]) -> str:
    return "POLYGON(" + ", ".join(ring(r) for r in rings) + ")"


def multipolygon(polygons: list[list[list[Position]]]) -> str:
    return "MULTIPOLYGON(" + ", ".join("(" + ", ".join(ring(r) for r in p) + ")" for p in polygons) + ")"


def multilinestring(lines: list[list[Position]]) -> str:
    return "MULTILINESTRING(" + ", ".join(ring(r) for r in lines) + ")"


def multipoint(points: list[Position]) -> str:
    return "MULTIPOINT(" + ", ".join(f"({pos(p)})" for p in points) + ")"


def collection(parts: list[str]) -> str:
    return "GEOMETRYCOLLECTION(" + ", ".join(parts) + ")"


# --------------------------------------------------------------------------- reading


def _tokens(text: str) -> list[str]:
    found: list[str] = []
    at = 0
    text = text.strip()
    if text.startswith("<"):                    # a CRS IRI in front
        end = text.find(">")
        if end < 0:
            raise WktError("a '<' without '>'")
        text = text[end + 1:]
    while at < len(text):
        match = TOKEN.match(text, at)
        if not match:
            if text[at:].strip() == "":
                break
            raise WktError(f"unexpected text at {text[at:at + 12]!r}")
        found.append(match.group(1))
        at = match.end()
    return found


class _Reader:
    def __init__(self, tokens: list[str]) -> None:
        self.t, self.i = tokens, 0

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, expected: str | None = None) -> str:
        if self.i >= len(self.t):
            raise WktError("the text ends too early")
        token = self.t[self.i]
        self.i += 1
        if expected is not None and token != expected:
            raise WktError(f"expected {expected!r}, found {token!r}")
        return token

    def position(self) -> list[float]:
        values = []
        while self.peek() not in (None, ",", ")"):
            token = self.take()
            try:
                values.append(float(token))
            except ValueError as err:
                raise WktError(f"{token!r} is not a number") from err
        if len(values) not in (2, 3):
            raise WktError("a position needs two numbers (lon lat)")
        lon, lat = values[0], values[1]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise WktError(f"the position {lon} {lat} is outside the globe")
        return [lon, lat]

    def group(self, inner):
        self.take("(")
        items = [inner()]
        while self.peek() == ",":
            self.take(",")
            items.append(inner())
        self.take(")")
        return items

    def line(self) -> list[list[float]]:
        return self.group(self.position)

    def poly(self) -> list[list[list[float]]]:
        return self.group(self.line)

    def point_item(self) -> list[float]:           # MULTIPOINT((1 2), (3 4)) and MULTIPOINT(1 2, 3 4)
        if self.peek() == "(":
            self.take("(")
            p = self.position()
            self.take(")")
            return p
        return self.position()

    def geometry(self) -> dict[str, Any]:
        word = self.take().upper()
        if word not in KINDS:
            raise WktError(f"{word!r} is not a geometry type")
        kind = KINDS[word]
        if self.peek() is not None and self.peek().upper() in ("Z", "M", "ZM"):
            self.take()
        if self.peek() is not None and self.peek().upper() == "EMPTY":
            raise WktError("an empty geometry")
        if kind == "Point":
            self.take("(")
            p = self.position()
            self.take(")")
            return {"type": kind, "coordinates": p}
        if kind == "LineString":
            return {"type": kind, "coordinates": self.line()}
        if kind == "Polygon":
            return {"type": kind, "coordinates": self.poly()}
        if kind == "MultiPoint":
            return {"type": kind, "coordinates": self.group(self.point_item)}
        if kind == "MultiLineString":
            return {"type": kind, "coordinates": self.group(self.line)}
        if kind == "MultiPolygon":
            return {"type": kind, "coordinates": self.group(self.poly)}
        return {"type": kind, "geometries": self.group(self.geometry)}


def parse(text: str) -> dict[str, Any]:
    """GeoJSON geometry from WKT; raises ``WktError`` with a short reason."""
    reader = _Reader(_tokens(text))
    geometry = reader.geometry()
    if reader.peek() is not None:
        raise WktError(f"text after the geometry: {reader.peek()!r}")
    return geometry


def positions(geometry: dict[str, Any]) -> list[list[float]]:
    """Every position of a GeoJSON geometry, flat."""
    if geometry["type"] == "GeometryCollection":
        return [p for g in geometry["geometries"] for p in positions(g)]
    found: list[list[float]] = []

    def walk(value: Any) -> None:
        if value and isinstance(value[0], (int, float)):
            found.append(value)
        else:
            for part in value:
                walk(part)

    walk(geometry["coordinates"])
    return found


def centre(geometry: dict[str, Any]) -> tuple[float, float]:
    """(lat, lon): the middle of the bounding box, which is cheap, stable, and inside the map view (not always inside the shape)."""
    ps = positions(geometry)
    lons, lats = [p[0] for p in ps], [p[1] for p in ps]
    return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
