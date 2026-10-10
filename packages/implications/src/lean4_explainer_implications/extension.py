"""The implications extension: curated implication edges, each with its contract, on the pages they connect.

An edge shows on the page of every declaration it names (a source, the target, or the bridge that proves it), on
`implications.html` grouped by kind, in `implications.json` for other tools, and its kinds and statuses are in the
glossary. When the same build runs Lean (the lean extension), the kernel checks a proved edge's bridge.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path
from typing import Any

from lean4_explainer.extensions import Extension, GlossaryEntry, GlossarySection
from lean4_explainer.render import href, page, source_href

from . import edges as E

__version__ = "0.1.0"
DEFAULT_FILE = "implications.toml"
STATE_LABELS = {
    "proposed": "proposed",
    "argued": "argued",
    "unchecked": "proved, not checked here",
    "kernel-checked": "kernel-checked",
    "fails": "bridge fails",
    "refuted": "refuted",
}

CSS = """
.implications ul { margin: 0.2rem 0 0.4rem 1.2rem; padding: 0; }
.imp-kind { font-style: italic; }
.imp { display: inline-block; padding: 0 0.4rem; font-size: 0.75rem; border-radius: 4px; border: 1px solid var(--line); }
.imp-proposed, .imp-unchecked, .imp-candidate { color: var(--muted); border-style: dashed; }
.imp-argued { color: var(--fg); }
.imp-kernel-checked { color: var(--fg); font-weight: 600; border-width: 2px; }
.imp-fails, .imp-refuted, .imp-stale { color: var(--warn); background: var(--warn-bg); border-color: var(--warn); }
article.edge { border: 1px solid var(--line); border-radius: 6px; padding: 0.6rem 0.9rem; margin: 0.8rem 0; overflow-wrap: anywhere; }
article.edge h3 { margin: 0 0 0.3rem; font-size: 1rem; }
article.edge dt { font-weight: 600; margin-top: 0.5rem; }
article.edge dd { margin-left: 1rem; }
article.edge pre { margin: 0.2rem 0; white-space: pre-wrap; }
p.imp-stale { display: block; padding: 0.2rem 0.5rem; }
dl.imp-legend dt { font-weight: 600; margin-top: 0.4rem; }
dl.imp-legend dd { margin-left: 1rem; }
"""

INTRO = (
    "A dependency records which declarations a proof uses: the map and the “uses” lists show those, read from the code. "
    "An implication edge records what one result could establish about another, even when the released proof goes "
    "another way. It is a claim, so each one keeps its contract: the declarations it starts from and reaches, the exact "
    "hypotheses, the conclusion it derives, the commit the statements were read at, and how far it has been checked. "
    "The edges are curated beside the project, not written by its authors."
)


@dataclass(frozen=True)
class Analysis:
    path: str = ""  # the edge file, "" when the site has none
    found: E.Found = field(default_factory=E.Found)
    places: Mapping[str, tuple[str, int]] = field(default_factory=dict)  # each name an edge uses -> (file, line)
    commit: str = ""  # the commit this site shows, when it is known
    issues: tuple[str, ...] = ()

    @property
    def any(self) -> bool:
        return bool(self.found.edges or self.found.candidates)

    def stale(self, edge: E.Edge) -> bool:
        return bool(self.commit) and not (self.commit.startswith(edge.commit) or edge.commit.startswith(self.commit))


class ImplicationsExtension(Extension):
    name = "implications"
    version = __version__
    every_declaration = True  # the edges come from a sidecar file, not from anything parsed in the sources
    config_keys = {"implications_file": str, "implications_commit": str}

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        path = _edge_file(options)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path and path.is_file() else ""
        return f"{self.name}:{self.version}:{digest}:{options.get('implications_commit', '')}"

    def analyze(self, objects: Any, summaries: Mapping[str, Any], options: Mapping[str, Any]) -> Analysis:
        path = _edge_file(options)
        commit = str(options.get("implications_commit", "") or "")
        if path is None:
            return Analysis(commit=commit)
        if not path.is_file():
            return Analysis(str(path), commit=commit, issues=(f"error: implications: {path} does not exist",))
        found = E.load(path.read_text(encoding="utf-8"))
        issues = [f"error: implications: {path.name}: {problem}" for problem in found.problems]
        places: dict[str, tuple[str, int]] = {}
        for table, items in (("edge", found.edges), ("candidate", found.candidates)):
            for item in items:
                for name in item.names:
                    where = _place(objects, name)
                    if where is not None:
                        places[name] = where
                    elif name in objects.ambiguous:
                        choices = ", ".join(f"{name}@{copy.rel}" for copy in objects.copies.get(name, ())[:6])
                        issues.append(f"error: implications: {table} '{item.id}': {name} names distinct declarations; write one of {choices}")
                    else:
                        issues.append(f"error: implications: {table} '{item.id}': no declaration named {name} in this site")
        analysis = Analysis(str(path), found, places, commit)
        for edge in found.edges:
            if analysis.stale(edge):
                issues.append(
                    f"warning: implications: edge '{edge.id}' was read at commit {edge.commit}; this site shows "
                    f"{commit[:12]}, so its statements may have changed"
                )
        return replace(analysis, issues=tuple(issues))

    def analysis_issues(self, analysis: Analysis) -> Sequence[str]:
        return analysis.issues

    def review(self, analysis: Analysis, analyses: Sequence[tuple[Extension, Any]]) -> Sequence[str]:
        kernel = _kernel(analysis, analyses, self)
        out = []
        for edge in analysis.found.edges:
            checked = E.verify(edge, kernel)
            if checked.state == "fails":
                out.append(f"warning: implications: edge '{edge.id}': {checked.detail}")
        return out

    # -- rendering --
    def css(self, options: Mapping[str, Any]) -> str:
        return CSS

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        path = _edge_file(options)
        return (("Implications", f"{up}implications.html"),) if path and path.is_file() else ()

    def declaration_blocks(self, decl, payload, rel, dirs, ctx, analysis: Analysis) -> tuple[str, str]:
        if not analysis.any:
            return "", ""
        here = (rel, decl.line)
        up = "../" * len(dirs)
        kernel = _kernel(analysis, ctx.extensions, self)
        rows = []
        for edge in analysis.found.edges:
            role = _role(edge, here, analysis)
            if role:
                state = E.verify(edge, kernel).state
                badge = f' <span class="imp imp-{state}">{escape(STATE_LABELS[state])}</span>'
                if analysis.stale(edge):
                    badge += ' <span class="imp imp-stale">stale</span>'
                contract = f' <a href="{escape(up, quote=True)}implications.html#{escape(edge.id, quote=True)}">contract</a>'
                rows.append(f"<li>{_relation(edge, role, dirs, analysis)}{badge}{contract}</li>")
        for cand in analysis.found.candidates:
            role = _role(cand, here, analysis)
            if role:
                rows.append(
                    f'<li>{_relation(cand, role, dirs, analysis)} <span class="imp imp-candidate">candidate</span> '
                    f'<a href="{escape(up, quote=True)}implications.html#{escape(cand.id, quote=True)}">what it needs</a></li>'
                )
        if not rows:
            return "", ""
        return "", (
            f'<div class="implications"><p class="refs"><strong>Implications</strong> <span class="muted">(curated claims about '
            f'what follows, not dependencies: <a href="{escape(up, quote=True)}implications.html">what these are</a>)</span></p>'
            f'<ul>{"".join(rows)}</ul></div>'
        )

    def pages(self, ctx, analysis: Analysis) -> Mapping[str, str]:
        if not analysis.path:
            return {}
        kernel = _kernel(analysis, ctx.extensions, self)
        return {"implications.html": _index_page(ctx, analysis, kernel), "implications.json": _data(ctx, analysis, kernel)}

    def glossary(self, ctx, analysis: Analysis) -> Sequence[GlossarySection]:
        if not analysis.path:
            return ()
        entries = [GlossaryEntry(label, escape(meaning), anchor=f"imp-{kind}") for kind, (label, _, _, meaning) in E.KINDS.items()]
        entries += [GlossaryEntry(status, escape(meaning), anchor=f"imp-status-{status}") for status, meaning in E.STATUSES.items()]
        return (GlossarySection("implications", "Implication edges", tuple(entries), INTRO),)

    def summary(self, analysis: Analysis) -> Sequence[str]:
        if not analysis.path:
            return ()
        counts: dict[str, int] = {}
        for edge in analysis.found.edges:
            counts[edge.status] = counts.get(edge.status, 0) + 1
        said = ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "none"
        return (f"implications: {len(analysis.found.edges)} edges ({said}), {len(analysis.found.candidates)} candidates.",)


def _edge_file(options: Mapping[str, Any]) -> Path | None:
    named = str(options.get("implications_file", "") or "")
    root = options.get("_root")
    if named:
        path = Path(named)
        return path if path.is_absolute() or not root else Path(str(root)) / path
    if root and (Path(str(root)) / DEFAULT_FILE).is_file():
        return Path(str(root)) / DEFAULT_FILE
    return None


def _place(objects: Any, written: str) -> tuple[str, int] | None:
    """Where a name in the edge file is: `Name`, or `Name@path` for the copy in that file (a project can declare a name
    in several files; openai/math restates its results in ComparatorChallenges/)."""
    name, at, rel = written.partition("@")
    if at:
        for copy in objects.copies.get(name, ()):
            if copy.rel == rel:
                return (str(copy.rel), int(copy.line))
        where = objects.locations.get(name)  # declared once: the path must be its file
        return (str(where[0]), int(where[1])) if where is not None and str(where[0]) == rel else None
    where = objects.locations.get(written)
    return (str(where[0]), int(where[1])) if where is not None else None


def _bare(name: str) -> str:
    """The name Lean knows, without an `@path`."""
    return name.partition("@")[0]


def _kernel(analysis: Analysis, analyses: Sequence[tuple[Extension, Any]], me: Extension) -> Callable[[str], tuple[str, str] | None]:
    """What a Lean run in this build says of a declaration, or None when nothing ran Lean."""

    def ask(name: str) -> tuple[str, str] | None:
        place = analysis.places.get(name)
        if place is None:
            return None
        for ext, other in analyses:
            if ext is me:
                continue
            said = ext.kernel_trust(other, _bare(name), place[0], place[1])
            if said is not None:
                return said
        return None

    return ask


def _role(item, here: tuple[str, int], analysis: Analysis) -> str:
    for name in item.sources:
        if analysis.places.get(name) == here:
            return "source:" + name
    if item.target and analysis.places.get(item.target) == here:
        return "target"
    if getattr(item, "bridge", "") and analysis.places.get(item.bridge) == here:
        return "bridge"
    return ""


def _link(name: str, dirs: list[str], analysis: Analysis) -> str:
    place = analysis.places.get(name)
    if place is None:
        return f"<code>{escape(name)}</code>"
    return f'<a href="{escape(href(dirs, place[0], f"#L{place[1]}"), quote=True)}"><code>{escape(_bare(name))}</code></a>'


def _relation(item, role: str, dirs: list[str], analysis: Analysis) -> str:
    _, forward, backward, _ = E.KINDS[item.kind]
    link = lambda name: _link(name, dirs, analysis)  # noqa: E731
    if role == "target":
        return f'<span class="imp-kind">{backward}</span> ' + " and ".join(link(s) for s in item.sources)
    if role == "bridge":
        reach = f" {forward} {link(item.target)}" if item.target else ""
        return f'<span class="imp-kind">is the bridge</span> that proves: {" and ".join(link(s) for s in item.sources)}{reach}'
    me = role.split(":", 1)[1]
    others = [s for s in item.sources if s != me]
    if item.kind == "composes-with":
        out = f'<span class="imp-kind">{forward}</span> ' + " and ".join(link(s) for s in others)
        return out + (f' <span class="imp-kind">to give</span> {link(item.target)}' if item.target else "")
    out = f'<span class="imp-kind">{forward}</span> {link(item.target)}'
    return out + (" (with " + " and ".join(link(s) for s in others) + ")" if others else "")


def _index_page(ctx, analysis: Analysis, kernel) -> str:
    found = analysis.found
    body = ["<h1>Implications</h1>", f"<p>{escape(INTRO)}</p>"]
    if analysis.issues:
        body.append('<p class="warn">The edge file has problems; the build listed them: ' + escape("; ".join(analysis.issues[:5])) + "</p>")
    body.append('<details><summary>The kinds of edge, and what each status means</summary><dl class="imp-legend">')
    body.extend(f"<dt>{escape(label)}</dt><dd>{escape(meaning)}</dd>" for label, _, _, meaning in E.KINDS.values())
    body.extend(f"<dt>{escape(status)}</dt><dd>{escape(meaning)}</dd>" for status, meaning in E.STATUSES.items())
    body.append(
        "<dt>proved, not checked here</dt><dd>The edge file says a bridge proves it, but this build did not run Lean.</dd>"
        "<dt>kernel-checked</dt><dd>This build ran Lean, and the kernel checked the bridge with no sorry and no extra axioms.</dd>"
        "<dt>stale</dt><dd>The edge was read at another commit than the one this site shows: the statements may have changed.</dd>"
        "</dl></details>"
    )
    if not found.edges and not found.candidates:
        body.append('<p class="muted">The edge file has no edges yet.</p>')
    for kind, (label, _, _, meaning) in E.KINDS.items():
        items = [e for e in found.edges if e.kind == kind]
        if not items:
            continue
        body.append(f'<h2 id="kind-{kind}">{escape(label)} ({len(items)})</h2><p class="muted">{escape(meaning)}</p>')
        body.extend(_edge_card(ctx, analysis, edge, kernel) for edge in items)
    if found.candidates:
        body.append(
            '<section class="candidates"><h2 id="candidates">Candidates</h2><p class="muted">Suggested edges with no contract '
            "yet: what they would connect, in their proposer's words, and what is missing. They are not claims.</p>"
        )
        for cand in found.candidates:
            ends = " and ".join(_link(s, [], analysis) for s in cand.sources) + (f" → {_link(cand.target, [], analysis)}" if cand.target else "")
            body.append(
                f'<article class="edge" id="{escape(cand.id, quote=True)}"><h3>{escape(E.KINDS[cand.kind][0])}: {ends}</h3><dl>'
                f"<dt>Suggested as</dt><dd>“{escape(cand.phrase)}”</dd><dt>Origin</dt><dd>{escape(cand.origin)}</dd>"
                + (f"<dt>Missing</dt><dd>{escape(cand.missing)}</dd>" if cand.missing else "")
                + (f"<dt>Note</dt><dd>{escape(cand.note)}</dd>" if cand.note else "")
                + "</dl></article>"
            )
        body.append("</section>")
    body.append('<p class="muted">The same edges as data: <a href="implications.json">implications.json</a>.</p>')
    return page("Implications", 0, body, ctx)


def _edge_card(ctx, analysis: Analysis, edge: E.Edge, kernel) -> str:
    checked = E.verify(edge, kernel)
    ends = " and ".join(_link(s, [], analysis) for s in edge.sources) + (f" → {_link(edge.target, [], analysis)}" if edge.target else "")
    rows = [
        f'<article class="edge" id="{escape(edge.id, quote=True)}"><h3>{ends}</h3>',
        f'<p><span class="imp imp-{checked.state}">{escape(STATE_LABELS[checked.state])}</span> {escape(checked.detail)}</p>',
    ]
    if analysis.stale(edge):
        rows.append(
            f'<p class="imp-stale">Read at commit {escape(edge.commit)}; this site shows {escape(analysis.commit[:12])}. '
            "The statements may have changed since.</p>"
        )
    rows.append("<dl>")
    rows.append("<dt>Hypotheses</dt><dd>" + ("".join(f"<pre>{escape(h)}</pre>" for h in edge.hypotheses) or "none beyond the sources") + "</dd>")
    rows.append(f"<dt>Conclusion</dt><dd><pre>{escape(edge.conclusion)}</pre></dd>")
    if edge.argument:
        rows.append(f"<dt>Argument</dt><dd>{escape(edge.argument)}</dd>")
    if edge.bridge:
        rows.append(f"<dt>Bridge</dt><dd>{_link(edge.bridge, [], analysis)}</dd>")
    if edge.evidence:
        rows.append(f"<dt>Evidence</dt><dd>{escape(edge.evidence)}</dd>")
    rows.append(f"<dt>Read at commit</dt><dd><code>{escape(edge.commit)}</code>{_at_commit(ctx, analysis, edge)}</dd>")
    rows.append(f"<dt>Origin</dt><dd>{escape(edge.origin)}</dd>")
    if edge.note:
        rows.append(f"<dt>Note</dt><dd>{escape(edge.note)}</dd>")
    rows.append("</dl></article>")
    return "".join(rows)


def _at_commit(ctx, analysis: Analysis, edge: E.Edge) -> str:
    """Links to each end as it was at the edge's commit, when the site knows where its source lives."""
    if not ctx.source_url:
        return ""
    links = []
    for name in edge.names:
        place = analysis.places.get(name)
        if place:
            at = replace(ctx, source_ref=edge.commit)
            links.append(f'<a href="{escape(source_href(place[0], place[1], at), quote=True)}">{escape(_bare(name).split(".")[-1])}</a>')
    return (": " + ", ".join(links)) if links else ""


def _data(ctx, analysis: Analysis, kernel) -> str:
    def end(name: str) -> dict[str, str]:
        place = analysis.places.get(name)
        return {"name": _bare(name), "page": f"{place[0]}.html#L{place[1]}" if place else ""}

    edges = []
    for edge in analysis.found.edges:
        checked = E.verify(edge, kernel)
        edges.append(
            {
                "id": edge.id,
                "kind": edge.kind,
                "from": [end(s) for s in edge.sources],
                "to": end(edge.target) if edge.target else None,
                "hypotheses": list(edge.hypotheses),
                "conclusion": edge.conclusion,
                "commit": edge.commit,
                "status": edge.status,
                "verification": {"state": checked.state, "detail": checked.detail},
                "stale": analysis.stale(edge),
                "origin": edge.origin,
                "argument": edge.argument,
                "bridge": end(edge.bridge) if edge.bridge else None,
                "evidence": edge.evidence,
                "note": edge.note,
            }
        )
    candidates = [
        {
            "id": c.id,
            "kind": c.kind,
            "from": [end(s) for s in c.sources],
            "to": end(c.target) if c.target else None,
            "phrase": c.phrase,
            "origin": c.origin,
            "missing": c.missing,
            "note": c.note,
        }
        for c in analysis.found.candidates
    ]
    return json.dumps({"format": 1, "site_commit": analysis.commit, "edges": edges, "candidates": candidates}, ensure_ascii=False, indent=1) + "\n"
