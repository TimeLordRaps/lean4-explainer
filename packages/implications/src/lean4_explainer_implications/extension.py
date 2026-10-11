"""The implications extension: curated implication edges, each with its contract, on the pages they connect; and the
catalogue of implications the discovery pipeline found and Lean checked.

An edge shows on the page of every declaration it names (a source, the target, or the bridge that proves it), on
`implications.html` grouped by kind, in `implications.json` for other tools, and its kinds and statuses are in the
glossary. When the same build runs Lean (the lean extension), the kernel checks a proved edge's bridge. A bridge in a
bridge file is checked by the pipeline instead, which records the result beside the edge file; the build compares that
record with what it has and shows it as a recorded check, or as stale.

The catalogue (`implications_catalogue`, or a `catalogue` directory beside the edge file) is shown on
`implications/catalogue.html`, its unresolved attempts on `implications/notes.html`, and on each theorem's page that
it names. The build never searches and never runs Lean for it: it shows what was recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path
from typing import Any

from lean4_explainer.extensions import Extension, GlossaryEntry, GlossarySection
from lean4_explainer.render import href, page, source_href

from . import catalogue_site as CS
from . import edges as E

__version__ = "0.3.0"
DEFAULT_FILE = "implications.toml"
STATE_LABELS = {
    "proposed": "proposed",
    "argued": "argued",
    "unchecked": "proved, not checked here",
    "kernel-checked": "kernel-checked",
    "stale": "check is stale",
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
pre.bridge-source { white-space: pre-wrap; overflow-wrap: anywhere; }
pre.bridge-source span[id] { display: block; }
""" + CS.CSS

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
    records: Mapping[str, dict] = field(default_factory=dict)  # recorded contract checks, by edge id
    bridges: Mapping[str, tuple[str, str]] = field(default_factory=dict)  # bridge file -> (sha256, text), when present
    inputs: Mapping[str, str | None] = field(default_factory=dict)  # a recorded input file -> its sha256 here (None: unread)
    catalogue: Mapping[str, Any] | None = None  # the discovered catalogue's index
    catalogue_dir: str = ""
    catalogue_places: Mapping[str, tuple[str, int]] = field(default_factory=dict)  # theorem key -> (file, line)
    catalogue_at: Mapping[tuple[str, int], tuple[tuple[str, dict], ...]] = field(default_factory=dict)

    @property
    def any(self) -> bool:
        return bool(self.found.edges or self.found.candidates)

    def stale(self, edge: E.Edge) -> bool:
        return bool(self.commit) and not (self.commit.startswith(edge.commit) or edge.commit.startswith(self.commit))


class ImplicationsExtension(Extension):
    name = "implications"
    version = __version__
    every_declaration = True  # the edges come from a sidecar file, not from anything parsed in the sources
    config_keys = {"implications_file": str, "implications_commit": str, "implications_catalogue": str}

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        path = _edge_file(options)
        parts = [path, _record_file(path)] if path else []
        if path and path.is_file():
            found = E.load(path.read_text(encoding="utf-8"))
            parts += sorted({path.parent / e.bridge_file for e in found.edges if e.bridge_file})
        cat = _catalogue_dir(options)
        if cat:
            parts += [cat / "index.json", *sorted((cat / "shards").glob("*.json"))]
        digest = hashlib.sha256()
        for p in parts:
            digest.update(str(p).encode())
            digest.update(p.read_bytes() if p.is_file() else b"-")
        return f"{self.name}:{self.version}:{digest.hexdigest()[:16]}:{options.get('implications_commit', '')}"

    def analyze(self, objects: Any, summaries: Mapping[str, Any], options: Mapping[str, Any]) -> Analysis:
        path = _edge_file(options)
        commit = str(options.get("implications_commit", "") or "")
        cat_dir = _catalogue_dir(options)
        catalogue = CS.load(cat_dir) if cat_dir else None
        cat_places = CS.placed(catalogue, lambda written: _place(objects, written)) if catalogue else {}
        cat_at = {k: tuple(v) for k, v in CS.rows_at(catalogue, cat_places).items()} if catalogue else {}
        base = Analysis(commit=commit, catalogue=catalogue, catalogue_dir=str(cat_dir or ""), catalogue_places=cat_places, catalogue_at=cat_at)
        if path is None:
            return base
        if not path.is_file():
            return replace(base, path=str(path), issues=(f"error: implications: {path} does not exist",))
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
        record_file = _record_file(path)
        records = json.loads(record_file.read_text(encoding="utf-8")).get("edges", {}) if record_file.is_file() else {}
        bridges = {}
        for edge in found.edges:
            if edge.bridge_file and edge.bridge_file not in bridges and (path.parent / edge.bridge_file).is_file():
                data = (path.parent / edge.bridge_file).read_bytes()
                bridges[edge.bridge_file] = (E.content_sha256(data), data.decode("utf-8", errors="replace"))
        root = Path(str(options["_root"])) if options.get("_root") else None
        inputs: dict[str, str | None] = {}
        for record in records.values():
            for rel in record.get("inputs") or {}:
                f = root / rel if root else None
                inputs[rel] = E.content_sha256(f.read_bytes()) if f is not None and f.is_file() else None
        analysis = replace(base, path=str(path), found=found, places=places, records=records, bridges=bridges, inputs=inputs)
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
            checked = _verify(edge, kernel, analysis)
            if checked.state in ("fails", "stale"):
                out.append(f"warning: implications: edge '{edge.id}': {checked.detail}")
        return out

    # -- rendering --
    def css(self, options: Mapping[str, Any]) -> str:
        return CSS

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        # one link on every page (a big corpus pays for each byte on each page): implications.html links the catalogue
        path = _edge_file(options)
        return (("Implications", f"{up}implications.html"),) if (path and path.is_file()) or _catalogue_dir(options) else ()

    def declaration_blocks(self, decl, payload, rel, dirs, ctx, analysis: Analysis) -> tuple[str, str]:
        here = (rel, decl.line)
        up = "../" * len(dirs)
        blocks = []
        if analysis.any:
            kernel = _kernel(analysis, ctx.extensions, self)
            rows = []
            for edge in analysis.found.edges:
                role = _role(edge, here, analysis)
                if role:
                    checked = _verify(edge, kernel, analysis)
                    state = checked.state
                    where = " (recorded)" if checked.provenance == "recorded" else ""
                    badge = f' <span class="imp imp-{state}">{escape(STATE_LABELS[state] + where)}</span>'
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
            if rows:
                blocks.append(
                    f'<div class="implications"><p class="refs"><strong>Implications</strong> <span class="muted">(curated claims about '
                    f'what follows, not dependencies: <a href="{escape(up, quote=True)}implications.html">what these are</a>)</span></p>'
                    f'<ul>{"".join(rows)}</ul></div>'
                )
        entries = analysis.catalogue_at.get(here)
        if entries and analysis.catalogue is not None:
            keys = {k for k, p in analysis.catalogue_places.items() if p == here}
            theorems = analysis.catalogue.get("theorems", {})

            def link(key: str) -> str:
                t = theorems.get(key, {})
                name = escape(t.get("name", key.rsplit(":", 1)[-1]))
                place = analysis.catalogue_places.get(key)
                return f'<a href="{escape(href(dirs, place[0], f"#L{place[1]}"), quote=True)}"><code>{name}</code></a>' if place else f"<code>{name}</code>"

            blocks.append(CS.theorem_block(list(entries), keys, link, up))
        return "", "".join(blocks)

    def pages(self, ctx, analysis: Analysis) -> Mapping[str, str]:
        out: dict[str, str] = {}
        kernel = _kernel(analysis, ctx.extensions, self)
        if analysis.path or analysis.catalogue is not None:
            out["implications.html"] = _index_page(ctx, analysis, kernel)
        if analysis.path:
            out["implications.json"] = _data(ctx, analysis, kernel)
            for rel, (sha, text) in analysis.bridges.items():
                out[_bridge_page(rel)] = _bridge_source_page(ctx, analysis, rel, sha, text)
        if analysis.catalogue is not None:
            cat_dir = Path(analysis.catalogue_dir)
            out["implications/catalogue/index.json"] = CS.site_index(
                analysis.catalogue, analysis.catalogue_places, lambda place: href(["implications"], place[0], f"#L{place[1]}"))
            for shard in sorted((cat_dir / "shards").glob("*.json")):
                out[f"implications/catalogue/shards/{shard.name}"] = shard.read_text(encoding="utf-8")
            out["implications/catalogue.js"] = CS.script()
            out["implications/catalogue.html"] = page("Checked implications", 1, CS.catalogue_body(analysis.catalogue)
                                                      + ['<script src="catalogue.js" defer></script>'], ctx)
        if analysis.catalogue is not None or analysis.path:
            argued = [(e.id, f"{', '.join(_bare(s) for s in e.sources)} → {_bare(e.target) or 'a composite'}") for e in analysis.found.edges if e.status in ("argued", "proposed")]
            cands = [(c.id, c.phrase) for c in analysis.found.candidates]
            if analysis.catalogue is not None or argued or cands:
                out["implications/notes.html"] = page("Implication notes", 1, CS.notes_body(analysis.catalogue or {}, argued, cands), ctx)
        return out

    def glossary(self, ctx, analysis: Analysis) -> Sequence[GlossarySection]:
        if not analysis.path:
            return ()
        entries = [GlossaryEntry(label, escape(meaning), anchor=f"imp-{kind}") for kind, (label, _, _, meaning) in E.KINDS.items()]
        entries += [GlossaryEntry(status, escape(meaning), anchor=f"imp-status-{status}") for status, meaning in E.STATUSES.items()]
        return (GlossarySection("implications", "Implication edges", tuple(entries), INTRO),)

    def summary(self, analysis: Analysis) -> Sequence[str]:
        out = []
        if analysis.path:
            counts: dict[str, int] = {}
            for edge in analysis.found.edges:
                counts[edge.status] = counts.get(edge.status, 0) + 1
            said = ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "none"
            out.append(f"implications: {len(analysis.found.edges)} edges ({said}), {len(analysis.found.candidates)} candidates.")
        if analysis.catalogue is not None:
            c = analysis.catalogue.get("counts", {})
            out.append(f"implications: catalogue of {c.get('checked', 0)} checked ({c.get('connections', 0)} connections), "
                       f"{len(analysis.catalogue_places)} of {len(analysis.catalogue.get('theorems', {}))} theorems on this site.")
        return tuple(out)


def _edge_file(options: Mapping[str, Any]) -> Path | None:
    named = str(options.get("implications_file", "") or "")
    root = options.get("_root")
    if named:
        path = Path(named)
        return path if path.is_absolute() or not root else Path(str(root)) / path
    if root and (Path(str(root)) / DEFAULT_FILE).is_file():
        return Path(str(root)) / DEFAULT_FILE
    return None


def _record_file(edge_file: Path) -> Path:
    """Where the pipeline records its contract checks: beside the edge file, `<stem>.verified.json`."""
    return edge_file.with_name(edge_file.stem + ".verified.json")


def _catalogue_dir(options: Mapping[str, Any]) -> Path | None:
    named = str(options.get("implications_catalogue", "") or "")
    if named:
        path = Path(named)
        root = options.get("_root")
        path = path if path.is_absolute() or not root else Path(str(root)) / path
        return path if (path / "index.json").is_file() else None
    edge_file = _edge_file(options)
    if edge_file is not None and (edge_file.parent / "catalogue" / "index.json").is_file():
        return edge_file.parent / "catalogue"
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


def _verify(edge: E.Edge, kernel, analysis: Analysis) -> E.Verification:
    bridge = analysis.bridges.get(edge.bridge_file) if edge.bridge_file else None
    return E.verify(edge, kernel, analysis.records.get(edge.id), bridge[0] if bridge else None, dict(analysis.inputs))


def _role(item, here: tuple[str, int], analysis: Analysis) -> str:
    for name in item.sources:
        if analysis.places.get(name) == here:
            return "source:" + name
    if item.target and analysis.places.get(item.target) == here:
        return "target"
    if getattr(item, "bridge", "") and not getattr(item, "bridge_file", "") and analysis.places.get(item.bridge) == here:
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


def _bridge_page(rel: str) -> str:
    return "implications/" + rel.replace("\\", "/") + ".html"


def _bridge_line(text: str, name: str) -> int:
    """The line that declares `name` in a bridge file (to link to it), 0 when not found."""
    pattern = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|noncomputable\s+)*(?:theorem|lemma|def|abbrev)\s+" + re.escape(name) + r"\b")
    for i, line in enumerate(text.splitlines(), 1):
        if pattern.match(line):
            return i
    return 0


def _bridge_link(rel: str, name: str, analysis: Analysis, up: str = "") -> str:
    """A link to a declaration in a bridge file, on the bridge's page."""
    bridge = analysis.bridges.get(rel)
    line = _bridge_line(bridge[1], name) if bridge else 0
    anchor = f"#L{line}" if line else ""
    return f'<a href="{escape(up + _bridge_page(rel) + anchor, quote=True)}"><code>{escape(name)}</code></a>'


def _bridge_source_page(ctx, analysis: Analysis, rel: str, sha: str, text: str) -> str:
    depth = _bridge_page(rel).count("/")
    up = "../" * depth
    users = [e for e in analysis.found.edges if e.bridge_file == rel]
    lines = "".join(f'<span id="L{i}">{escape(line) or " "}</span>' for i, line in enumerate(text.splitlines(), 1))
    body = [
        f"<h1>{escape(rel)}</h1>",
        f"<p>A bridge file for the curated edges below, kept beside the edge file (not in the project's sources). "
        f"SHA-256 <code>{escape(sha)}</code>. Each edge's card says whether a recorded Lean check of this exact file and "
        "contract exists.</p><ul>"
        + "".join(f'<li><a href="{escape(up, quote=True)}implications.html#{escape(e.id, quote=True)}">{escape(e.id)}</a></li>' for e in users)
        + "</ul>",
        f'<pre class="bridge-source"><code>{lines}</code></pre>',
    ]
    return page(rel, depth, body, ctx)


def _index_page(ctx, analysis: Analysis, kernel) -> str:
    found = analysis.found
    body = ["<h1>Implications</h1>", f"<p>{escape(INTRO)}</p>"]
    if analysis.catalogue is not None:
        c = analysis.catalogue.get("counts", {})
        body.append(f'<p>Besides these curated edges, the discovery pipeline checked {c.get("checked", 0)} implications in Lean '
                    f'({c.get("connections", 0)} connections): <a href="implications/catalogue.html">the catalogue</a>. What it tried and did not '
                    'establish, and the suggestions still without a Lean check: <a href="implications/notes.html">notes</a>.</p>')
    if analysis.issues:
        body.append('<p class="warn">The edge file has problems; the build listed them: ' + escape("; ".join(analysis.issues[:5])) + "</p>")
    body.append('<details><summary>The kinds of edge, and what each status means</summary><dl class="imp-legend">')
    body.extend(f"<dt>{escape(label)}</dt><dd>{escape(meaning)}</dd>" for label, _, _, meaning in E.KINDS.values())
    body.extend(f"<dt>{escape(status)}</dt><dd>{escape(meaning)}</dd>" for status, meaning in E.STATUSES.items())
    body.append(
        "<dt>proved, not checked here</dt><dd>The edge file says a bridge proves it, and no Lean check of it ran in this build "
        "or was recorded.</dd>"
        "<dt>kernel-checked</dt><dd>Lean's kernel checked the bridge against the contract with no sorry and no extra axioms: "
        "either in this build, or in a recorded check this build compared with the contract, the bridge file, the commit and "
        "the corpus files it read. The card says which.</dd>"
        "<dt>check is stale</dt><dd>A check was recorded, but of another contract, bridge file, commit or corpus file than "
        "this build has: it says nothing now.</dd>"
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
    checked = _verify(edge, kernel, analysis)
    ends = " and ".join(_link(s, [], analysis) for s in edge.sources) + (f" → {_link(edge.target, [], analysis)}" if edge.target else "")
    where = {"this build": " (in this build)", "recorded": " (recorded)"}.get(checked.provenance, "")
    rows = [
        f'<article class="edge" id="{escape(edge.id, quote=True)}"><h3>{ends}</h3>',
        f'<p><span class="imp imp-{checked.state}">{escape(STATE_LABELS[checked.state])}{escape(where)}</span> {escape(checked.detail)}</p>',
    ]
    if analysis.stale(edge):
        rows.append(
            f'<p class="imp-stale">Read at commit {escape(edge.commit)}; this site shows {escape(analysis.commit[:12])}. '
            "The statements may have changed since.</p>"
        )
    rows.append("<dl>")
    rows.append("<dt>Hypotheses</dt><dd>" + ("".join(f"<pre>{escape(h)}</pre>" for h in edge.hypotheses) or "none beyond the sources") + "</dd>")
    rows.append(f"<dt>Conclusion</dt><dd><pre>{escape(edge.conclusion)}</pre></dd>")
    record = analysis.records.get(edge.id) if edge.bridge_file else None
    if record and record.get("expected") and checked.state in ("kernel-checked", "fails"):
        rows.append("<dt>The exact contract, as Lean states it</dt><dd><pre>" + escape(record["expected"]) + "</pre>"
                    '<span class="muted">Each source is a hypothesis: the bridge proves this, and the kernel checked that it does.</span></dd>')
    if edge.improvement:
        rows.append(f"<dt>What it adds to the target</dt><dd>{escape(edge.improvement)}</dd>")
    if edge.argument:
        label = "Argument (in words; Lean checked the bridge, not these words)" if checked.state == "kernel-checked" else "Argument"
        rows.append(f"<dt>{label}</dt><dd>{escape(edge.argument)}</dd>")
    if edge.bridge:
        if edge.bridge_file:
            rows.append(f"<dt>Bridge</dt><dd>{_bridge_link(edge.bridge_file, edge.bridge, analysis)} in "
                        f'<a href="{escape(_bridge_page(edge.bridge_file), quote=True)}">{escape(edge.bridge_file)}</a></dd>')
        else:
            rows.append(f"<dt>Bridge</dt><dd>{_link(edge.bridge, [], analysis)}</dd>")
    if edge.relation:
        relation = _bridge_link(edge.bridge_file, edge.relation, analysis)
        rows.append(f"<dt>Relation to the target</dt><dd>{relation} proves that the contract gives the target's statement"
                    + (_relation_detail(record) if record and checked.state == "kernel-checked" else "") + "</dd>")
    if edge.construction:
        rows.append(f"<dt>Construction</dt><dd>{_bridge_link(edge.bridge_file, edge.construction, analysis)}</dd>")
    if record and checked.state in ("kernel-checked", "fails", "stale"):
        rows.append("<dt>Recorded check</dt><dd>" + escape(
            f"{record.get('checked_at', '')}: {record.get('status', '')}; {record.get('toolchain', '')}; Mathlib "
            f"{str(record.get('mathlib', ''))[:12]}; corpus {str(record.get('corpus_revision', ''))[:12]}; environment "
            f"{record.get('environment', '')}; imports {', '.join(record.get('imports', []))}; bridge file SHA-256 "
            f"{str(record.get('bridge_sha256', ''))[:16]}…; run as: {record.get('command', '')}") + "</dd>")
    if edge.evidence:
        rows.append(f"<dt>Evidence</dt><dd>{escape(edge.evidence)}</dd>")
    rows.append(f"<dt>Read at commit</dt><dd><code>{escape(edge.commit)}</code>{_at_commit(ctx, analysis, edge)}</dd>")
    rows.append(f"<dt>Origin</dt><dd>{escape(edge.origin)}</dd>")
    if edge.note:
        rows.append(f"<dt>Note</dt><dd>{escape(edge.note)}</dd>")
    rows.append("</dl></article>")
    return "".join(rows)


def _relation_detail(record: dict) -> str:
    only = record.get("target_only_hypotheses") or []
    out = ""
    if record.get("target_conclusion") and record.get("contract_conclusion"):
        out += (f'. The contract concludes <code>{escape(record["contract_conclusion"])}</code>; the target, '
                f'<code>{escape(record["target_conclusion"])}</code>')
    if only:
        out += ". Hypotheses the target has and the contract does not need: " + ", ".join(f"<code>{escape(h)}</code>" for h in only)
    return out + "."


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
        checked = _verify(edge, kernel, analysis)
        record = analysis.records.get(edge.id) if edge.bridge_file else None
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
                "verification": {"state": checked.state, "detail": checked.detail, "provenance": checked.provenance,
                                 "record": {k: record.get(k) for k in ("status", "checked_at", "environment", "toolchain", "mathlib", "corpus_revision",
                                                                         "fingerprint", "bridge_sha256", "inputs", "axioms", "expected")} if record else None},
                "stale": analysis.stale(edge),
                "origin": edge.origin,
                "argument": edge.argument,
                "bridge": ({"name": edge.bridge, "file": edge.bridge_file, "page": _bridge_page(edge.bridge_file)} if edge.bridge_file else end(edge.bridge)) if edge.bridge else None,
                "relation": edge.relation or None,
                "improvement": edge.improvement or None,
                "construction": edge.construction or None,
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
