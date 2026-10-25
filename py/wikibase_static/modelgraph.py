"""Data-model graphics as SVG (S16): what an entity says, and what the classes of a site say.

Two pictures, both drawn from the loaded data and nothing else (no network, no clock, no layout engine):

``ModelGraphs.entity_svg(entity)``
    The statements of one entity as a graph. The entity on the left, one box per property, the values to the right of
    it, qualifiers and own references as chips under their value. A reference that several statements share is drawn
    once at the bottom. Item values link to their pages.

``ModelGraphs.site_svg()``
    The data model of the whole site as one card per class: the properties the instances of the class use, the class
    or data type of their values, and how many statements there are. The model is read from the data, not from a
    schema, so it shows what the site does and not what it was meant to do.

Colours follow one scheme everywhere: real objects dark green, classes dark orange, other items pale grey, properties and
the metadata of a statement (qualifiers, references) amber, literals white. The colours are fixed and the SVG carries its own
``<style>``, so a picture looks the same inline, as a downloaded file and in a paper.

Everything is deterministic: orders are sorted, text widths are estimated from the characters, nothing is random.
"""

from __future__ import annotations

from html import escape
from typing import Any

from wikibase_static import render as rendering
from wikibase_static.model import Entity, Snak, id_sort_key, is_federated

WIDTH = 880                 # viewBox width; the picture scales to the width of the page
FONT = 13                   # px, labels
SMALL = 11                  # px, chips and legends
NODE_H = 30
CHIP_H = 20
GAP = 14

STYLE = """<style>
.mg-t{fill:#000;font:13px sans-serif}.mg-w{fill:#fff;font:13px sans-serif}.mg-s{fill:#000;font:11px sans-serif}.mg-sw{fill:#fff;font:11px sans-serif}
.mg-id{font:11px sans-serif;opacity:.7}.mg-b{font-weight:600}
.mg-self{fill:#166534;stroke:#000;stroke-width:.8}.mg-class{fill:#9a3412;stroke:#000;stroke-width:.8}
.mg-item{fill:#e2e8f0;stroke:#000;stroke-width:.8}.mg-wd{fill:#e2e8f0;stroke:#000;stroke-width:.8;stroke-dasharray:4 3}
.mg-lit{fill:#fff;stroke:#000;stroke-width:.8}.mg-prop{fill:#f8fafc;stroke:#000;stroke-width:.8}
.mg-meta{fill:#fbbf24;stroke:#000;stroke-width:.8}.mg-card{fill:#fff;stroke:#000;stroke-width:.8}
.mg-ref{stroke-dasharray:4 2}.mg-pref{stroke-width:2}.mg-depr{stroke-dasharray:3 3;opacity:.7}
.mg-edge{fill:none;stroke:#6b7280;stroke-width:1.2}.mg-leader{fill:none;stroke:#6b7280;stroke-width:.8;stroke-dasharray:3 3}
.mg-link{cursor:pointer}.mg-link:hover rect,.mg-link:hover ellipse{stroke-width:2}
</style>"""

MARKER = ('<defs><marker id="mg-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
          '<path d="M2 1L8 5L2 9" fill="none" stroke="#6b7280" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
          '</marker></defs>')


# --------------------------------------------------------------------------- text

def text_width(text: str, size: int = FONT) -> float:
    """A fair estimate of the width of ``text`` in a sans-serif font: wide characters count full, others a little over half."""
    return sum(size if ord(ch) >= 0x2E80 else size * 0.58 if ch.isupper() or ch in "mwMW@%" else size * 0.54 for ch in text)


def fit(text: str, width: float, size: int = FONT) -> str:
    """``text``, cut with an ellipsis so that it is estimated to fit in ``width``."""
    if text_width(text, size) <= width:
        return text
    out = ""
    for ch in text:
        if text_width(out + ch + "…", size) > width:
            break
        out += ch
    return out.rstrip() + "…"


def esc(text: str) -> str:
    return escape(str(text), quote=True)


def link(href: str | None, inner: str, title: str | None = None) -> str:
    """``inner`` inside an SVG link (when there is a target) with the full text as tooltip."""
    tip = f"<title>{esc(title)}</title>" if title else ""
    if href:
        return f'<a href="{esc(href)}" class="mg-link">{tip}{inner}</a>'
    return f"<g>{tip}{inner}</g>" if tip else inner


def node(x: float, y: float, w: float, h: float, shape: str, text: str, title: str | None = None, href: str | None = None,
         white_text: bool = False, extra: str = "", sub: str | None = None) -> str:
    """One labelled box (or pill when ``shape`` ends in ``-pill``). ``shape`` is a CSS class: self, class, item, wd, lit, prop, meta."""
    pill = shape.endswith("-pill")
    cls = "mg-" + shape.removesuffix("-pill")
    radius = h / 2 if pill else 4
    tcls = "mg-w" if white_text else "mg-t"
    cy = y + h / 2
    body = [f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{radius:g}" class="{cls}{(" " + extra) if extra else ""}"/>']
    if sub:
        body.append(f'<text x="{x + w / 2:g}" y="{cy - 6:g}" class="{tcls} mg-b" text-anchor="middle" dominant-baseline="central">{esc(text)}</text>')
        body.append(f'<text x="{x + w / 2:g}" y="{cy + 10:g}" class="{"mg-sw" if white_text else "mg-s"}" text-anchor="middle" dominant-baseline="central">{esc(sub)}</text>')
    else:
        body.append(f'<text x="{x + w / 2:g}" y="{cy:g}" class="{tcls}" text-anchor="middle" dominant-baseline="central">{esc(text)}</text>')
    return link(href, "".join(body), title)


def chip(x: float, y: float, w: float, text: str, title: str | None = None, is_reference: bool = False) -> str:
    """An amber chip: a qualifier or a reference of a statement."""
    return link(None, f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{CHIP_H}" rx="4" class="mg-meta{" mg-ref" if is_reference else ""}"/>'
                      f'<text x="{x + 8:g}" y="{y + CHIP_H / 2:g}" class="mg-s" dominant-baseline="central">{esc(text)}</text>', title)


def arrow(x1: float, y1: float, x2: float, y2: float) -> str:
    return f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" class="mg-edge" marker-end="url(#mg-arrow)"/>'


def svg_document(width: int, height: float, title: str, description: str, body: list[str], standalone: bool = False) -> str:
    head = '<?xml version="1.0" encoding="UTF-8"?>\n' if standalone else ""
    ns = ' xmlns="http://www.w3.org/2000/svg"' if standalone else ""
    return (f'{head}<svg{ns} class="model-graph" width="100%" viewBox="0 0 {width} {height:g}" role="group" aria-label="{esc(title)}" '
            f'style="max-width:{width}px;height:auto">\n<title>{esc(title)}</title><desc>{esc(description)}</desc>\n{STYLE}\n{MARKER}\n'
            + "\n".join(body) + "\n</svg>\n")


# --------------------------------------------------------------------------- the graphs

class ModelGraphs:
    """Draws the two pictures for one loaded site (``r`` is the page ``Renderer`` of the build)."""

    def __init__(self, r: Any) -> None:
        self.r = r
        self.site = r.site
        self._groups = r.class_groups()
        self.instance_property = r.instance_property()
        self.subclass_property = r.subclass_property()
        self.class_ids = {g["id"] for g in self._groups}
        for entity in self.site.entities.values():      # a class is also what something is a subclass of or a subclass
            for statement in entity.statements:
                target = statement.mainsnak.entity_id
                if self.subclass_property and statement.mainsnak.property == self.subclass_property and target in self.site.entities:
                    self.class_ids.update({entity.id, target})
        self.classes_of: dict[str, list[str]] = {}
        for group in self._groups:
            for entity in group["instances"]:
                self.classes_of.setdefault(entity.id, []).append(group["id"])

    # ---- small helpers

    def label(self, entity_id: str) -> str:
        return self.r.label_text(entity_id) if entity_id in self.site.entities else entity_id

    def href(self, entity_id: str, base: str) -> str | None:
        return f"{base}{entity_id}.html" if entity_id in self.site.entities else None

    def item_shape(self, entity_id: str) -> tuple[str, bool]:
        """(CSS shape, white text) of an item that is the value of a statement."""
        if entity_id in self.class_ids:
            return "class-pill", True
        if entity_id in self.site.entities:
            return "item-pill", False
        return "wd-pill", False

    def plain(self, snak: Snak) -> tuple[str, str]:
        """(text, kind) of a value; kind is ``item``, ``literal`` or ``special``."""
        if snak.snaktype == "somevalue":
            return self.r.ui_text("unknown_value"), "special"
        if snak.snaktype == "novalue":
            return self.r.ui_text("no_value"), "special"
        target, value = snak.entity_id, snak.value
        if target:
            return self.label(target), "item"
        if snak.vtype == "time" and isinstance(value, dict):
            return rendering.format_time(value), "literal"
        if snak.vtype == "quantity" and isinstance(value, dict):
            amount, unit = rendering.format_amount(value)
            if unit and not unit.startswith(("http://", "https://")):
                amount += f" {unit}"
            return amount, "literal"
        if snak.vtype == "monolingualtext" and isinstance(value, dict):
            return f"{value.get('text', '')} ({value.get('language', '')})", "literal"
        if snak.vtype == "globecoordinate" and isinstance(value, dict):
            return rendering.format_coordinate(value), "literal"
        return str(value), "literal"

    def datatype_name(self, snak: Snak) -> str:
        key = f"dt_{snak.datatype}"
        return self.r.ui_text(key) if snak.datatype and key in rendering.STRINGS["en"] else (snak.datatype or snak.vtype or "?")

    # ---- one entity

    def entity_svg(self, entity: Entity, base: str = "", standalone: bool = False) -> str | None:
        """The statements of ``entity`` as an SVG; ``None`` for an entity without statements. ``base`` goes before the page names."""
        if not entity.statements:
            return None
        groups: list[tuple[str, list[Any]]] = []
        for statement in entity.statements:
            prop = statement.mainsnak.property
            if not groups or groups[-1][0] != prop:
                groups.append((prop, []))
            groups[-1][1].append(statement)

        def signature(reference: list[Snak]) -> tuple[tuple[str, str], ...]:
            return tuple((snak.property, self.plain(snak)[0]) for snak in reference)

        used: dict[tuple[tuple[str, str], ...], int] = {}
        for statement in entity.statements:
            for sig in {signature(reference) for reference in statement.references}:
                used[sig] = used.get(sig, 0) + 1
        shared = sorted((sig for sig, n in used.items() if n > 1), key=lambda sig: (-used[sig], sig))

        prop_w = min(210.0, max(100.0, *(text_width(self.label(prop)) + 22 for prop, _ in groups)))
        self_w = 180.0
        prop_x = self_w + 50
        val_x = prop_x + prop_w + 46
        max_x = WIDTH - 10
        cell_max = max_x - val_x

        body: list[str] = []
        y = 12.0
        prop_rows: list[tuple[str, float]] = []
        for prop, statements in groups:
            rows: list[list[tuple[Any, float, float]]] = [[]]      # (cell, x, width)
            cursor = val_x
            built: list[tuple[Any, float, float, list[str]]] = []
            for statement in statements:
                text = self.plain(statement.mainsnak)[0]
                chips = [f"{self.label(q.property)}: {self.plain(q)[0]}" for q in statement.qualifiers]
                for reference in statement.references:
                    if signature(reference) not in shared:
                        chips.append("§" + " · ".join(f"{self.label(p)} {t}" for p, t in signature(reference)))
                node_w = min(cell_max, max(48.0, text_width(text) + 24))
                chip_w = [min(cell_max, text_width(c.lstrip("§"), SMALL) + 18) for c in chips]
                width = max([node_w, *chip_w])
                built.append((statement, node_w, width, chips))
            for statement, node_w, width, chips in built:
                if rows[-1] and cursor + width > max_x:
                    rows.append([])
                    cursor = val_x
                rows[-1].append((statement, cursor, node_w))
                cursor += width + GAP
            row_tops: list[float] = []
            lookup = {id(s): (w, chips) for s, w, _wd, chips in built}
            group_top = y
            for row in rows:
                height = NODE_H + max((len(lookup[id(s)][1]) for s, _x, _w in row), default=0) * (CHIP_H + 4)
                row_tops.append(y)
                for statement, x, node_w in row:
                    text = self.plain(statement.mainsnak)[0]
                    target = statement.mainsnak.entity_id
                    shape, white = self.item_shape(target) if target else ("lit", False)
                    extra = "mg-pref" if statement.rank == "preferred" else "mg-depr" if statement.rank == "deprecated" else ""
                    body.append(node(x, y, node_w, NODE_H, shape, fit(text, node_w - 16), text, self.href(target, base) if target else None,
                                     white, extra))
                    cy = y + NODE_H + 4
                    for chip_text in lookup[id(statement)][1]:
                        is_ref = chip_text.startswith("§")
                        plain_text = chip_text.lstrip("§")
                        body.append(chip(x, cy, min(cell_max, text_width(plain_text, SMALL) + 18), fit(plain_text, cell_max - 18, SMALL),
                                         (self.r.ui_text("graph_reference") + ": " if is_ref else "") + plain_text, is_ref))
                        cy += CHIP_H + 4
                y += height + 8
            first_cy = row_tops[0] + NODE_H / 2
            prop_rows.append((prop, first_cy))
            if len(rows) == 1:
                body.append(arrow(prop_x + prop_w, first_cy, rows[0][0][1] - 3, first_cy))
            else:                                           # several lines: a bracket with one arrow into each line
                bracket = val_x - 20
                body.append(f'<line x1="{prop_x + prop_w:g}" y1="{first_cy:g}" x2="{bracket:g}" y2="{first_cy:g}" class="mg-edge"/>')
                body.append(f'<line x1="{bracket:g}" y1="{first_cy:g}" x2="{bracket:g}" y2="{row_tops[-1] + NODE_H / 2:g}" class="mg-edge"/>')
                for top, row in zip(row_tops, rows):
                    body.append(arrow(bracket, top + NODE_H / 2, row[0][1] - 3, top + NODE_H / 2))
            body.append(node(prop_x, first_cy - NODE_H / 2, prop_w, NODE_H, "prop", fit(self.label(prop), prop_w - 16),
                             f"{self.label(prop)} ({prop})", self.href(prop, base)))
            y += 6

        for sig in shared:                                  # the references that several statements share, once
            text = " · ".join(f"{self.label(p)} {t}" for p, t in sig)
            title = self.r.ui_text("graph_shared_reference", n=used[sig], total=len(entity.statements))
            w = max_x - prop_x
            body.append(f'<rect x="{prop_x:g}" y="{y:g}" width="{w:g}" height="44" rx="8" class="mg-meta"/>')
            body.append(f'<text x="{prop_x + w / 2:g}" y="{y + 15:g}" class="mg-t mg-b" text-anchor="middle" dominant-baseline="central">{esc(title)}</text>')
            body.append(f'<text x="{prop_x + w / 2:g}" y="{y + 32:g}" class="mg-s" text-anchor="middle" dominant-baseline="central">{esc(fit(text, w - 24, SMALL))}</text>')
            y += 54

        height = y + 6
        centre = max(NODE_H, min(height / 2, height - 30))
        shape = "class" if entity.id in self.class_ids else "prop" if entity.kind == "property" else "self"
        label = self.label(entity.id)
        body.insert(0, node(10, centre - 26, self_w, 52, "meta" if shape == "prop" else shape, fit(label, self_w - 16), f"{label} ({entity.id})",
                            None, shape in ("class", "self"), sub=entity.id))
        for prop, cy in prop_rows:
            body.insert(1, f'<line x1="{10 + self_w:g}" y1="{centre:g}" x2="{prop_x - 3:g}" y2="{cy:g}" class="mg-edge" marker-end="url(#mg-arrow)"/>')
        title = self.r.ui_text("graph_title") + f": {label} ({entity.id})"
        return svg_document(WIDTH, height, title, f"{len(entity.statements)} statements, {len(groups)} properties, {len(shared)} shared references", body, standalone)

    # ---- the whole site

    def site_svg(self, base: str = "", standalone: bool = False) -> str | None:
        """One card per class with the properties its instances use; ``None`` when the site has no classes with instances."""
        if not self._groups:
            return None
        skip = {p for p in (self.instance_property, self.subclass_property) if p}
        cards = []
        for group in sorted(self._groups, key=lambda g: (-len(g["instances"]), id_sort_key(g["id"]))):
            usage: dict[str, dict[str, Any]] = {}
            for entity in group["instances"]:
                for statement in entity.statements:
                    snak = statement.mainsnak
                    if snak.property in skip:
                        continue
                    row = usage.setdefault(snak.property, {"n": 0, "targets": {}})
                    row["n"] += 1
                    target = snak.entity_id
                    if target and self.classes_of.get(target):
                        keys = [("class", c) for c in self.classes_of[target]]
                    elif target and target in self.class_ids:
                        keys = [("class", target)]
                    elif target:
                        keys = [("wd" if is_federated(target) or target not in self.site.entities else "item", self.r.ui_text("graph_item"))]
                    else:
                        keys = [("dt", self.datatype_name(snak))]
                    for key in keys:
                        row["targets"][key] = row["targets"].get(key, 0) + 1
            rows = sorted(usage.items(), key=lambda kv: (-kv[1]["n"], id_sort_key(kv[0])))
            cards.append((group, rows))

        shown = cards[:12]
        card_w = (WIDTH - 20 - 20) / 2
        columns = [10.0, 10.0 + card_w + 20]
        heights = [10.0, 10.0]
        body: list[str] = []
        for group, rows in shown:
            col = 0 if heights[0] <= heights[1] else 1
            x, y = columns[col], heights[col]
            visible = rows[:10]
            more = len(rows) - len(visible)
            height = 34 + len(visible) * 26 + (22 if more else 0) + (8 if visible else 0)
            class_id = group["id"]
            label = self.label(class_id)
            count = self.r.ui_text("graph_instances", n=len(group["instances"]))
            body.append(f'<rect x="{x:g}" y="{y:g}" width="{card_w:g}" height="{height:g}" rx="6" class="mg-card"/>')
            head = (f'<path d="M{x:g} {y + 34:g}V{y + 6:g}a6 6 0 0 1 6-6H{x + card_w - 6:g}a6 6 0 0 1 6 6V{y + 34:g}Z" class="mg-class"/>'
                    f'<text x="{x + 12:g}" y="{y + 17:g}" class="mg-w mg-b" dominant-baseline="central">{esc(fit(label, card_w - 24 - text_width(count, SMALL) - 10))}</text>'
                    f'<text x="{x + card_w - 12:g}" y="{y + 17:g}" class="mg-sw" text-anchor="end" dominant-baseline="central">{esc(count)}</text>')
            body.append(link(self.href(class_id, base), head, f"{label} ({class_id})"))
            ry = y + 34 + 6
            for prop, usage_row in visible:
                prop_label = fit(self.label(prop), 190 - 16)
                body.append(link(self.href(prop, base),
                                 f'<rect x="{x + 10:g}" y="{ry:g}" width="190" height="20" rx="4" class="mg-meta"/>'
                                 f'<text x="{x + 18:g}" y="{ry + 10:g}" class="mg-s" dominant-baseline="central">{esc(prop_label)}</text>',
                                 f"{self.label(prop)} ({prop})"))
                px = x + 210
                limit = x + card_w - 56
                targets = sorted(usage_row["targets"].items(), key=lambda kv: (-kv[1], kv[0]))
                drawn = 0
                for (kind, name), _n in targets:
                    shown_text = self.label(name) if kind == "class" else name
                    w = min(limit - px, text_width(shown_text, SMALL) + 16)
                    if w < 30 or (drawn and px + w > limit):
                        break
                    shape = "class-pill" if kind == "class" else "wd-pill" if kind == "wd" else "item-pill" if kind == "item" else "lit"
                    body.append(link(self.href(name, base) if kind == "class" else None,
                                     f'<rect x="{px:g}" y="{ry:g}" width="{w:g}" height="20" rx="{10 if shape.endswith("pill") else 4}" class="mg-{shape.removesuffix("-pill")}"/>'
                                     f'<text x="{px + w / 2:g}" y="{ry + 10:g}" class="{"mg-sw" if kind == "class" else "mg-s"}" text-anchor="middle" dominant-baseline="central">'
                                     f'{esc(fit(shown_text, w - 12, SMALL))}</text>', shown_text))
                    px += w + 6
                    drawn += 1
                if len(targets) > drawn:
                    body.append(f'<text x="{px:g}" y="{ry + 10:g}" class="mg-s" dominant-baseline="central">+{len(targets) - drawn}</text>')
                body.append(f'<text x="{x + card_w - 10:g}" y="{ry + 10:g}" class="mg-s" text-anchor="end" dominant-baseline="central">×{usage_row["n"]}</text>')
                ry += 26
            if more:
                body.append(f'<text x="{x + 12:g}" y="{ry + 8:g}" class="mg-s" dominant-baseline="central">{esc(self.r.ui_text("graph_more_properties", n=more))}</text>')
            heights[col] = y + height + 14

        y = max(heights)
        if len(cards) > len(shown):
            body.append(f'<text x="10" y="{y + 6:g}" class="mg-s" dominant-baseline="central">{esc(self.r.ui_text("graph_more_classes", n=len(cards) - len(shown)))}</text>')
            y += 22
        legend_y = y + 8
        lx = 10.0
        for shape, white, key in (("class-pill", True, "graph_legend_class"), ("meta", False, "graph_legend_property"),
                                  ("lit", False, "graph_legend_datatype"), ("item-pill", False, "graph_legend_item")):
            text = self.r.ui_text(key)
            w = text_width(text, SMALL) + 18
            body.append(f'<rect x="{lx:g}" y="{legend_y:g}" width="{w:g}" height="18" rx="{9 if shape.endswith("pill") else 4}" class="mg-{shape.removesuffix("-pill")}"/>'
                        f'<text x="{lx + w / 2:g}" y="{legend_y + 9:g}" class="{"mg-sw" if white else "mg-s"}" text-anchor="middle" dominant-baseline="central">{esc(text)}</text>')
            lx += w + 10
        height = legend_y + 18 + 12
        title = self.r.ui_text("model_title")
        return svg_document(WIDTH, height, title, f"{len(shown)} of {len(cards)} classes with the properties of their instances", body, standalone)
