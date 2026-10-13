"""The map extension: how a project's declarations build on each other, drawn from the code itself.

Each declaration's names are read from its source in the indexing step (cached, in parallel), and resolved against
the project's own declarations when the tree is analysed. Each file page then carries the neighbourhood of its
declarations — what each builds on, two steps back, and what uses it, two steps on — and `map.js` draws one as a
layered diagram when its "Map" is opened. `map.html` draws the project at the level of files and folders.

The drawing uses the site's colours (the corpus theme's `--accent`, `--line`, `--fg`, …), so every project's map
matches its pages. When the L4DEL extension is active, its `prereq` links are drawn too, as "read first" edges.
Nothing here runs Lean; the edges are name lookups, which `deps` describes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lean4_explainer.extensions import Extension, ParseResult, SourceView
from lean4_explainer.render import Context, filter_box, href, page

from .deps import Resolver, bound_in, declaration_end, imports_in, names_in, opens_in, reverse, variables_in, reachable, visible_files

__version__ = "0.2.0"

HERE = Path(__file__).parent
SCRIPT = "_assets/map.js"
MAP_JS = (HERE / "map.js").read_text(encoding="utf-8")
DEPS_SOURCE = (HERE / "deps.py").read_bytes()
NEAR = 7  # direct neighbours drawn on each side of a declaration
FAR = 5  # second-step neighbours drawn on each side

CSS = """
details.depmap { margin: 0.35rem 0 0.2rem; }
details.depmap > summary { cursor: pointer; font-size: 0.9rem; color: var(--muted); }
.depmap-wrap { overflow-x: auto; padding: 0.3rem 0; }
.depmap-legend { color: var(--muted); font-size: 0.82rem; margin: 0.15rem 0 0; }
svg.depmap-svg { display: block; font: 13px system-ui, -apple-system, "Segoe UI", sans-serif; }
svg.depmap-svg .n rect { fill: var(--panel, var(--bg)); stroke: var(--line); stroke-width: 1.2; }
svg.depmap-svg .n text { fill: var(--fg); }
svg.depmap-svg .n.here rect { fill: var(--accent, var(--fg)); stroke: var(--accent, var(--fg)); }
svg.depmap-svg .n.here text { fill: var(--bg); font-weight: 600; }
svg.depmap-svg a:hover rect, svg.depmap-svg a:focus rect { stroke: var(--accent, var(--fg)); stroke-width: 2; }
svg.depmap-svg .e { fill: none; stroke: var(--muted); stroke-width: var(--w, 1.3px); opacity: 0.75; }
svg.depmap-svg .e.declared { stroke-dasharray: 5 4; }
svg.depmap-svg .e.lit { stroke: var(--accent, var(--fg)); stroke-width: calc(var(--w, 1.3px) + 1px); opacity: 1; }
svg.depmap-svg .tip { fill: var(--muted); }
/* the project's drawings are wide: they use the whole window, not the text column */
#project-map .depmap-wrap { width: calc(100vw - 2rem); position: relative; left: 50%; transform: translateX(-50%); }
#project-map .controls { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; margin: 0.5rem 0; }
#project-map input[type="search"] { min-width: 18rem; }
.map-table-wrap { overflow-x: auto; }
.map-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.map-table th, .map-table td { padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--line); text-align: left; }
.map-table th:not(:first-child), .map-table td:not(:first-child) { text-align: right; white-space: nowrap; }
.depmap-text { font-size: 0.88rem; }
"""


@dataclass
class Graph:
    """Who uses whom across the project. `digest` stands for the whole graph in the page-cache key."""

    uses: dict[str, list[str]] = field(default_factory=dict, repr=False)
    used_by: dict[str, list[str]] = field(default_factory=dict, repr=False)
    # identical copies fold into one key; what each copy uses, seen from its own file, is kept for its own page
    copy_uses: dict[tuple[str, str], list[str]] = field(default_factory=dict, repr=False)
    enabled: bool = True
    digest: str = ""


class MapExtension(Extension):
    name = "map"
    version = __version__
    config_keys = {"map_dependencies": bool}

    # -- indexing --
    def parse(self, view: SourceView) -> ParseResult | None:
        if not view.options.get("map_dependencies", True):
            return None
        heads = sorted(view.heads, key=lambda head: head.index)
        by_head: dict[int, Any] = {}
        imports = imports_in("\n".join(view.code[: heads[0].index])) if heads else ()
        opens: tuple[str, ...] = ()
        variables: frozenset[str] = frozenset()
        scanned = 0
        for k, head in enumerate(heads):
            stop = heads[k + 1].index if k + 1 < len(heads) else len(view.code)
            between = "\n".join(view.code[scanned : head.index])  # the commands since the last declaration began
            more = opens_in(between)
            if more:
                opens = tuple(dict.fromkeys(opens + more))
            variables = variables | frozenset(variables_in(between))
            scanned = head.index
            text = "\n".join(view.code[head.index : declaration_end(view.code, head.index, stop)])
            by_head[head.index] = (names_in(text, variables | bound_in(text)), opens, imports)
        return ParseResult(by_head)

    def index_file(self, path: str, declarations: Sequence[Any], diagnostics: Sequence[Any]) -> Any:
        found = [(decl.name, decl.ext[self.name]) for decl in declarations if self.name in decl.ext]
        if not found:
            return None
        imports = found[0][1][2]
        return imports, tuple((name, names, opens) for name, (names, opens, _) in found)

    def analyze(self, objects: Any, summaries: Mapping[str, Any], options: Mapping[str, Any]) -> Graph:
        if not options.get("map_dependencies", True):
            return Graph(enabled=False, digest="off")
        present = {rel: summary for rel, summary in summaries.items() if summary}
        modules = getattr(objects, "modules", None)  # the core's import graph: every file, also ones that only import
        if modules is not None and modules.local:
            visible = reachable(modules.local)
        else:
            visible = visible_files({rel: summary[0] for rel, summary in present.items()})
        resolver = Resolver(objects.locations, visible, getattr(objects, "copies", None))
        uses: dict[str, list[str]] = {}
        copy_uses: dict[tuple[str, str], list[str]] = {}
        for rel, (_imports, declarations) in present.items():
            for name, names, opens in declarations:
                key = resolver.key_of(name, rel)
                if key is None:
                    continue
                found = resolver.uses(name, rel, names, opens)
                if len(resolver.files.get(key, ())) > 1:
                    copy_uses[(key, rel)] = found
                if found:  # identical copies share a key: each copy adds what it uses, seen from its own file
                    uses[key] = list(dict.fromkeys([*uses.get(key, ()), *found]))
        state = [sorted(uses.items()), sorted((f"{k}\n{r}", v) for (k, r), v in copy_uses.items())]
        digest = hashlib.sha256(json.dumps(state, ensure_ascii=False).encode("utf-8")).hexdigest()
        return Graph(uses=uses, used_by=reverse(uses), copy_uses=copy_uses, digest=digest)

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        # the index cache keeps what `deps` read from each file, so a change to how it reads must rebuild the index
        code = hashlib.sha256(MAP_JS.encode("utf-8") + DEPS_SOURCE).hexdigest()[:16]
        return f"map:{__version__}:{code}:{options.get('map_dependencies', True)}:{NEAR}:{FAR}"

    # -- rendering --
    def css(self, options: Mapping[str, Any]) -> str:
        return CSS

    def scripts(self, options: Mapping[str, Any]) -> Sequence[str]:
        return (SCRIPT,) if options.get("map_dependencies", True) else ()

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        return (("Map", f"{up}map.html"),) if options.get("map_dependencies", True) else ()

    def pages(self, ctx: Context, analysis: Graph) -> Mapping[str, str]:
        if not analysis.enabled:
            return {}
        return {SCRIPT: MAP_JS, "map.html": _project_page(ctx, _with_declared(ctx, analysis))}

    def file_blocks(self, lean_file: Any, text: str, ctx: Context, analysis: Graph) -> str:
        if not analysis.enabled or not lean_file.declarations:
            return ""
        graph = _with_declared(ctx, analysis)
        dirs = lean_file.path.split("/")[:-1]
        table: dict[str, int] = {}
        nodes: list[list[Any]] = []
        # a plain key whose declaration also sits in this file is an identical copy: link to the copy here
        here = {decl.name: decl.line for decl in lean_file.declarations}

        def node(key: str) -> int:
            if key not in table:
                table[key] = len(nodes)
                rel, line = ctx.locations[key]
                if rel != lean_file.path and key in here:
                    rel, line = lean_file.path, here[key]
                link = f"#L{line}" if rel == lean_file.path else href(dirs, rel, f"#L{line}")
                nodes.append([key.partition("@")[0], link])
            return table[key]

        entries = []
        for decl in lean_file.declarations:
            key = decl.name if decl.name in ctx.locations else f"{decl.name}@{lean_file.path}"
            if key not in ctx.locations or not _holds(ctx, key, lean_file.path, decl.line):
                continue
            hood = _neighbourhood(key, graph, ctx.locations, lean_file.path)
            if hood is None:
                continue
            chosen, edges, more_up, more_down, n_up, n_down = hood
            index = [node(k) for k in chosen]
            local = {k: i for k, i in zip(chosen, index)}
            flat = [n for a, b, kind in edges for n in (local[a], local[b], kind)]
            entries.append([decl.line, local[key], flat, n_up, n_down, more_up, more_down])
        if not entries:
            return ""
        payload = json.dumps({"n": nodes, "d": entries}, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        return f'<script type="application/json" id="map-data">{payload}</script>'

    def summary(self, analysis: Graph) -> Sequence[str]:
        if not analysis.enabled:
            return ("Map: off for this site (map_dependencies = false).",)
        edges = sum(len(v) for v in analysis.uses.values())
        return (f"Map: {edges} uses between {len(set(analysis.uses) | set(analysis.used_by))} declarations, read from the code.",)


def _holds(ctx: Context, key: str, rel: str, line: int) -> bool:
    """True when the declaration at rel:line is `key` itself or one of its identical copies."""
    if ctx.locations[key] == (rel, line):
        return True
    copies = getattr(ctx.objects, "copies", None) or {}
    return any(copy.rel == rel and copy.line == line for copy in copies.get(key, ()))


def _with_declared(ctx: Context, graph: Graph) -> Graph:
    """The code graph plus L4DEL's `prereq` links (kind 1), when that extension is active. Computed once per tree."""
    l4del = next((analysis for ext, analysis in ctx.extensions if ext.name == "l4del"), None)
    prereqs = getattr(l4del, "prereqs", None) or {}
    if not prereqs:
        return graph
    cached = getattr(graph, "_declared", None)
    if cached is not None and cached[0] is l4del:
        return cached[1]
    uses = {k: list(v) for k, v in graph.uses.items()}
    declared: set[tuple[str, str]] = set()
    for user, targets in prereqs.items():
        if user not in ctx.locations:
            continue
        for target in targets:
            if target in ctx.locations and target != user:
                declared.add((target, user))
                if target not in uses.setdefault(user, []):
                    uses[user].append(target)
    merged = Graph(uses=uses, used_by=reverse(uses), copy_uses=graph.copy_uses, digest=graph.digest)
    merged.declared = declared  # type: ignore[attr-defined]
    graph._declared = (l4del, merged)  # type: ignore[attr-defined]
    return merged


def _rank(keys: Iterable[str], graph: Graph) -> list[str]:
    """Most-used first, so the drawing keeps the results that matter most when it has to leave some out."""
    return sorted(keys, key=lambda k: (-len(graph.used_by.get(k, ())), k))


def _neighbourhood(key: str, graph: Graph, locations: Mapping[str, Any], rel: str = ""):
    """`key`'s neighbourhood as drawn on the page of file `rel` (which matters for a key with identical copies)."""
    declared = getattr(graph, "declared", set())
    own = graph.copy_uses.get((key, rel))
    mine = graph.uses.get(key, ()) if own is None else [*own, *(t for t in graph.uses.get(key, ()) if (t, key) in declared)]

    def targets(user: str) -> Sequence[str]:
        return mine if user == key else graph.uses.get(user, ())

    up1 = [k for k in _rank(mine, graph) if k in locations]
    down1 = [k for k in _rank(graph.used_by.get(key, ()), graph) if k in locations]
    if not up1 and not down1:
        return None
    near_up, near_down = up1[:NEAR], down1[:NEAR]
    taken = {key, *near_up, *near_down}
    up2 = _rank({k for u in near_up for k in graph.uses.get(u, ()) if k not in taken and k in locations}, graph)[:FAR]
    taken.update(up2)
    down2 = _rank({k for d in near_down for k in graph.used_by.get(d, ()) if k not in taken and k in locations}, graph)[:FAR]
    chosen = [key, *near_up, *near_down, *up2, *down2]
    inside = set(chosen)
    edges = [
        (target, user, 1 if (target, user) in declared else 0)
        for user in chosen
        for target in targets(user)
        if target in inside
    ]
    return chosen, edges, len(up1) - len(near_up), len(down1) - len(near_down), len(up1), len(down1)


def _project_page(ctx: Context, graph: Graph) -> str:
    """map.html: files and folders, an arrow where something in one is used in the other."""
    files: dict[str, int] = {}
    order: list[list[Any]] = []
    weights: dict[tuple[int, int], int] = {}

    def file(rel: str) -> int:
        if rel not in files:
            files[rel] = len(order)
            order.append([rel, href([], rel), 0])
        return files[rel]

    for rel, _line in ctx.locations.values():
        order[file(rel)][2] += 1
    for user, targets in graph.uses.items():
        if user not in ctx.locations:
            continue
        b = file(ctx.locations[user][0])
        for target in targets:
            if target in ctx.locations:
                a = file(ctx.locations[target][0])
                if a != b:
                    weights[(a, b)] = weights.get((a, b), 0) + 1
    builds_on: dict[int, set[int]] = {index: set() for index in range(len(order))}
    used_by: dict[int, set[int]] = {index: set() for index in range(len(order))}
    for a, b in weights:
        builds_on[b].add(a)
        used_by[a].add(b)
    data = {"f": order, "e": [[a, b, w] for (a, b), w in sorted(weights.items())]}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    rows = "".join(
        f'<tr><td><a href="{item[1]}">{item[0]}</a></td><td>{item[2]}</td>'
        f'<td>{len(builds_on[index])}</td><td>{len(used_by[index])}</td></tr>'
        for index, item in enumerate(order)
    )
    body = [
        "<h1>Map</h1>",
        '<p class="muted">How this project builds on itself. An arrow goes from a file to a file that uses something '
        "in it, so the foundations are on the left. These links come from names in the source code, not from kernel "
        "dependency facts; the separate Trust page says exactly what Lean checked. "
        "every declaration's own map, on its file page, shows the same thing one result at a time.</p>",
        '<div id="project-map"><noscript><p>The map is drawn by JavaScript.</p></noscript></div>',
        f'<script type="application/json" id="project-map-data">{payload}</script>',
        '<section data-filter-section><h2>Files as a table</h2>',
        '<p class="muted">The same map data in a searchable keyboard- and screen-reader-friendly form.</p>',
        filter_box("Filter map files"),
        '<div class="map-table-wrap"><table class="map-table"><caption>Files and cross-file dependency counts</caption>'
        '<thead><tr><th scope="col">File</th><th scope="col">Declarations</th><th scope="col">Builds on</th>'
        '<th scope="col">Used by</th></tr></thead><tbody data-filter-rows>'
        + rows
        + "</tbody></table></div></section>",
    ]
    if not data["e"]:
        body.insert(2, '<p class="muted">No file uses another yet, so there is nothing to connect.</p>')
    return page("Map", 0, body, ctx, canonical_path="map.html")

