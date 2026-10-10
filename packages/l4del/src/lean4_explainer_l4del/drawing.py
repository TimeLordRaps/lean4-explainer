"""Relationship maps drawn as inline SVG: no scripts, no network, readable with the images of a page turned off.

Two drawings share one look. A neighborhood map shows one declaration with what it builds on at its left and what
builds on it at its right; the whole-project map lays every connected declaration out in columns, with the
foundations at the left. Each box is a link to the declaration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from html import escape

BOX_W, BOX_H, GAP_X, GAP_Y, MAX_LABEL = 210, 28, 60, 10, 28

CSS = """
svg.relmap { max-width: 100%; height: auto; margin: 0.4rem 0; }
svg.relmap .box { fill: var(--bg); stroke: var(--line); stroke-width: 1.2; }
svg.relmap .here .box { stroke: currentColor; stroke-width: 2; }
svg.relmap text { fill: currentColor; font: 13px system-ui, sans-serif; }
svg.relmap .edge { fill: none; stroke: var(--muted); stroke-width: 1.3; }
svg.relmap .seeedge { fill: none; stroke: var(--muted); stroke-width: 1.3; stroke-dasharray: 4 4; }
svg.relmap .arrow { fill: var(--muted); }
svg.relmap a:hover .box, svg.relmap a:focus .box { stroke: currentColor; stroke-width: 2; }
p.maplegend { color: var(--muted); font-size: 0.85rem; margin: 0; }
"""


def layers(prereqs: Mapping[str, Sequence[str]]) -> dict[str, int]:
    """Column of each node: the length of its longest chain of prerequisites. Cycles do not loop forever."""
    nodes = set(prereqs)
    for targets in prereqs.values():
        nodes.update(targets)
    depth: dict[str, int] = {}

    def visit(start: str) -> None:
        stack = [(start, iter(prereqs.get(start, ())))]
        active = {start}
        while stack:
            node, pending = stack[-1]
            advanced = False
            for target in pending:
                if target in active:
                    continue  # a cycle: ignore the edge that closes it
                if target not in depth:
                    active.add(target)
                    stack.append((target, iter(prereqs.get(target, ()))))
                    advanced = True
                    break
            if not advanced:
                stack.pop()
                active.discard(node)
                below = [depth[t] for t in prereqs.get(node, ()) if t in depth]
                depth[node] = (max(below) + 1) if below else 0

    for node in sorted(nodes):
        if node not in depth:
            visit(node)
    return depth


def _short(text: str) -> str:
    return text if len(text) <= MAX_LABEL else "…" + text[-(MAX_LABEL - 1) :]  # the last part of a name says most


def _box(x: float, y: float, text: str, target: str | None, here: bool = False) -> str:
    inner = (
        f'<title>{escape(text)}</title><rect class="box" x="{x:.0f}" y="{y:.0f}" width="{BOX_W}" height="{BOX_H}" rx="6"/>'
        f'<text x="{x + BOX_W / 2:.0f}" y="{y + BOX_H / 2 + 4.5:.0f}" text-anchor="middle">{escape(_short(text))}</text>'
    )
    cls = ' class="here"' if here else ""
    if target is None:
        return f"<g{cls}>{inner}</g>"
    return f'<a href="{escape(target, quote=True)}"{cls}>{inner}</a>'


def _curve(x1: float, y1: float, x2: float, y2: float, css: str = "edge", arrow: bool = True) -> str:
    mid = (x1 + x2) / 2
    path = f'<path class="{css}" d="M{x1:.0f},{y1:.0f} C{mid:.0f},{y1:.0f} {mid:.0f},{y2:.0f} {x2:.0f},{y2:.0f}"/>'
    if arrow:
        path += f'<path class="arrow" d="M{x2:.0f},{y2:.0f} l-8,-4 l0,8 z"/>'
    return path


def _column(items: Sequence[str], cap: int) -> tuple[list[str], int]:
    return list(items[:cap]), max(0, len(items) - cap)


def neighborhood_svg(
    key: str,
    prereqs: Sequence[str],
    dependents: Sequence[str],
    sees: Sequence[str],
    label: Callable[[str], str],
    link: Callable[[str], str | None],
    cap: int = 8,
) -> str:
    """One declaration in the middle, its prerequisites on the left, what uses it on the right, related ones below."""
    left, left_more = _column(prereqs, cap)
    right, right_more = _column(dependents, cap)
    below, below_more = _column(sees, 3)  # one row, the width of the three columns
    rows = max(len(left) + bool(left_more), len(right) + bool(right_more), 1)
    step = BOX_H + GAP_Y
    cx = BOX_W + GAP_X
    rx = 2 * (BOX_W + GAP_X)
    top = 6
    height = top + rows * step
    cy = top + (rows * step - GAP_Y - BOX_H) / 2
    see_y = height + 14
    total_h = see_y + (BOX_H + 6 if below else 0) + 6
    width = 3 * BOX_W + 2 * GAP_X + 2
    parts = [
        f'<svg class="relmap" role="img" aria-label="Map around {escape(label(key), quote=True)}" '
        f'viewBox="0 0 {width} {total_h:.0f}" width="{width}">'
    ]
    for index, other in enumerate(left):
        y = top + index * step
        parts.append(_curve(BOX_W + 1, y + BOX_H / 2, cx - 1, cy + BOX_H / 2))
        parts.append(_box(1, y, label(other), link(other)))
    for index, other in enumerate(right):
        y = top + index * step
        parts.append(_curve(cx + BOX_W + 1, cy + BOX_H / 2, rx - 1, y + BOX_H / 2))
        parts.append(_box(rx, y, label(other), link(other)))
    if left_more:
        parts.append(f'<text x="{BOX_W / 2:.0f}" y="{top + len(left) * step + 18}" text-anchor="middle">+{left_more} more</text>')
    if right_more:
        parts.append(f'<text x="{rx + BOX_W / 2:.0f}" y="{top + len(right) * step + 18}" text-anchor="middle">+{right_more} more</text>')
    for index, other in enumerate(below):
        x = 1 + index * (BOX_W + GAP_X)
        parts.append(_curve(cx + BOX_W / 2, cy + BOX_H, x + BOX_W / 2, see_y, css="seeedge", arrow=False))
        parts.append(_box(x, see_y, label(other), link(other)))
    if below_more:
        parts.append(f'<text x="{width - 6}" y="{total_h - 8:.0f}" text-anchor="end">+{below_more} more related</text>')
    parts.append(_box(cx, cy, label(key), None, here=True))
    parts.append("</svg>")
    return "".join(parts)


def map_svg(
    prereqs: Mapping[str, Sequence[str]],
    sees: Mapping[str, Sequence[str]],
    nodes: Sequence[str],
    label: Callable[[str], str],
    link: Callable[[str], str | None],
) -> str:
    """Every node in `nodes` in columns by depth, foundations at the left; arrows run from a prerequisite to its user."""
    wanted = set(nodes)
    depth = layers({n: [t for t in prereqs.get(n, ()) if t in wanted] for n in nodes})
    columns: dict[int, list[str]] = {}
    for node in nodes:
        columns.setdefault(depth[node], []).append(node)
    spots: dict[str, tuple[float, float]] = {}
    for column, members in columns.items():
        for row, node in enumerate(members):
            spots[node] = (1 + column * (BOX_W + GAP_X), 6 + row * (BOX_H + GAP_Y))
    width = (max(columns) + 1) * (BOX_W + GAP_X) - GAP_X + 2
    height = max(len(members) for members in columns.values()) * (BOX_H + GAP_Y) + 6
    parts = [f'<svg class="relmap" role="img" aria-label="Map of the whole project" viewBox="0 0 {width} {height}" width="{width}">']
    for node in nodes:
        x2, y2 = spots[node]
        for target in prereqs.get(node, ()):
            if target in spots:
                x1, y1 = spots[target]
                parts.append(_curve(x1 + BOX_W + 1, y1 + BOX_H / 2, x2 - 1, y2 + BOX_H / 2))
        for target in sees.get(node, ()):
            if target in spots and node < target:
                x1, y1 = spots[target]
                parts.append(_curve(x1 + BOX_W / 2, y1 + BOX_H / 2, x2 + BOX_W / 2, y2 + BOX_H / 2, css="seeedge", arrow=False))
    for node in nodes:
        x, y = spots[node]
        parts.append(_box(x, y, label(node), link(node)))
    parts.append("</svg>")
    return "".join(parts)
