"""The L4DEL extension: reads `-- L4DEL: key: value` comments and adds the explanation layer to the site.

Adds, on top of the core site: titles, intuition, proof steps, prerequisite and see-also links on declarations;
the terms of the glossary page; a learning path ordered by prerequisites; an annotation guide; and the `check` and `annotate`
commands. Without this package the core site is built from standard Lean comments only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path
from typing import Any

from lean4_explainer.build import check_tree
from lean4_explainer.config import load_config
from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import Diagnostic, Extension, GlossaryEntry, GlossarySection, ParseResult, SourceView
from lean4_explainer.objects import Objects
from lean4_explainer.render import Context, filter_box, href, page, refs, source_href, up_path
from lean4_explainer.scan import Declaration, parse_source

from .grammar import L4Notes, parse_l4del
from .graph import PathStep, build_acronyms, build_glossary, build_learning_path, build_links, merge_notes, unresolved_links
from .model import FileSummary, Note
from .overlay import load_overlay
from .templates import annotation_report, annotation_state, notes_of, placeholder_block

__version__ = "0.5.0"

_PREFIX = "L4DEL:"
_CARRIER_RE = re.compile(r"^[ \t]*L4DEL:(?P<rest>.*)$")
_WARNING_PREVIEW = 20
_CACHE_SCHEMA = 6  # Navigation names the purpose without introducing an unexplained acronym.
_ACRONYM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9-]+(?![A-Za-z0-9_])")
_L4DEL_EXPANSION = "Lean4 Domain Explanation Language"

CSS = """
.l4del { margin: 0.3rem 0; padding-left: 0.6rem; border-left: 3px solid var(--line); }
.l4term { margin: 0.3rem 0; }
.l4del-sources { margin: 0.45rem 0; font-size: 0.94em; }
.l4del-provenance { margin: 0.45rem 0; padding: 0.45rem 0.6rem; border-left: 3px solid var(--warn); background: var(--warn-bg); }
.l4del-quote { margin: 0.55rem 0; padding: 0.4rem 0.8rem; border-left: 3px solid var(--accent); background: var(--panel); }
.l4del-quote p { margin: 0 0 0.3rem; }
.l4del-quote footer { color: var(--muted); font-size: 0.9em; }
.explanation-legend { margin: 0.8rem 0 1rem; padding: 0.7rem 0.9rem; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }
.explanation-legend h2 { margin-top: 0; font-size: 1.05rem; }
.acronym-legend { display: grid; grid-template-columns: max-content 1fr; gap: 0.2rem 0.8rem; margin: 0.35rem 0; }
.acronym-legend dt { font-weight: 700; }
.acronym-legend dd { margin: 0; }
"""

_GUIDE_EXAMPLE = "\n".join(
    [
        "/-- Three items in two boxes put two items in one box. -/",
        "-- L4DEL: title: Pigeonhole for three items in two boxes",
        "-- L4DEL: intuition: Three items cannot all sit in different boxes when there are only two boxes.",
        "-- L4DEL: step: Assume no box holds two items.",
        "-- L4DEL: step: Then three items need three different boxes, which do not exist.",
        "-- L4DEL: source: Formal statement = https://example.org/pinned-source#L1",
        "-- L4DEL: quote: Formal statement = Three items in two boxes put two items in one box.",
        "-- L4DEL: acronym: DEL = Domain Explanation Language",
        "-- L4DEL: prereq: Demo.box_count",
        "-- L4DEL: term: box = a container for one item",
        "theorem pigeonhole_three_two : ...",
    ]
)


@dataclass(frozen=True)
class Analysis:
    """The tree-wide result: merged notes, glossary, learning path. Only `notes` is part of the page-cache key."""

    notes: tuple[Note, ...]
    terms: dict = field(default_factory=dict, repr=False)
    acronyms: dict = field(default_factory=dict, repr=False)
    steps: list = field(default_factory=list, repr=False)
    prereqs: dict = field(default_factory=dict, repr=False)  # key -> keys it builds on
    sees: dict = field(default_factory=dict, repr=False)  # key -> related keys (both directions)
    anchors: dict = field(default_factory=dict, repr=False)
    term_pattern: re.Pattern[str] | None = field(default=None, repr=False)
    issues: tuple[str, ...] = field(default=(), repr=False)
    graph_issues: tuple[str, ...] = field(default=(), repr=False)
    annotated: int = field(default=0, repr=False)
    flagged: int = field(default=0, repr=False)
    unannotated: int = field(default=0, repr=False)


class L4delExtension(Extension):
    name = "l4del"
    version = __version__
    cache_types = frozenset({(FileSummary.__module__, "FileSummary"), (Note.__module__, "Note")})
    config_keys = {
        "learning_path": bool,
        "overlay": str,
        "overlay_provenance": str,
        "overlay_disclosure": str,
        "overlay_sources": str,
        "overlay_credit": str,
    }  # overlay: a sidecar file of annotations (see overlay.py)

    # ---- parsing and indexing ----
    def promote_file_page(self, lean_file: Any) -> bool:
        return any(self.name in declaration.ext for declaration in lean_file.declarations)

    def hides_comment(self, body: str) -> bool:
        return body.strip().startswith(_PREFIX)

    def is_described(self, payload: Any) -> bool:
        return not payload.is_empty

    def describe(self, payload: Any) -> str:
        return payload.intuition or (payload.quotes[0][1] if payload.quotes else None) or payload.title or ""

    def parse(self, view: SourceView) -> ParseResult:
        diagnostics: list[Diagnostic] = []
        carriers: list[tuple[int, int, str]] = []
        for comment in view.comments:
            if comment.kind == "line":
                match = _CARRIER_RE.match(comment.body)
                if match is None:
                    continue
                rest = match["rest"]
                if not rest.strip(" \t"):
                    diagnostics.append(Diagnostic("error", comment.start_line, "empty L4DEL directive"))
                elif rest[0] not in " \t":
                    diagnostics.append(Diagnostic("error", comment.start_line, "L4DEL: needs a space before the directive"))
                else:
                    carriers.append((comment.start_line - 1, comment.start_line, rest))
            elif self.hides_comment(comment.body):
                diagnostics.append(Diagnostic("error", comment.start_line, "L4DEL is allowed only in line comments"))
        directives_by_head: dict[int, list[tuple[int, str]]] = {}
        for code_index, line, rest in carriers:
            following = next((head for head in view.heads if head.index > code_index), None)
            if following is None or view.has_code(code_index + 1, following.index):
                diagnostics.append(Diagnostic("error", line, "orphan L4DEL directive: no declaration follows it"))
            elif "(" in following.name:
                diagnostics.append(Diagnostic("error", line, "anonymous declarations cannot carry L4DEL"))
            else:
                directives_by_head.setdefault(following.index, []).append((line, rest))
        payloads = {index: parse_l4del(items) for index, items in directives_by_head.items()}
        overlay_path = view.options.get("overlay")
        entries = load_overlay(str(overlay_path)).files.get(view.path) if overlay_path else None
        for name, items in (entries or {}).items():
            head = next((h for h in view.heads if h.name == name), None)
            if head is None:
                diagnostics.append(Diagnostic("warning", 1, f"overlay: no declaration named {name} in this file (is the overlay out of date?)"))
            elif head.index not in payloads:  # an annotation in the source wins over the overlay
                payloads[head.index] = replace(
                    parse_l4del([(head.index + 1, rest) for _, rest in items]), origin="overlay"
                )
        return ParseResult(payloads, diagnostics)

    def index_file(self, path: str, declarations: Sequence[Declaration], diagnostics: Sequence[Diagnostic]) -> FileSummary:
        named = [decl for decl in declarations if "(" not in decl.name]
        notes = tuple(
            Note(
                name=decl.name,
                rel=path,
                line=decl.line,
                title=n.title,
                prereqs=n.prereqs,
                see=n.see,
                terms=n.terms,
                acronyms=n.acronyms,
            )
            for decl in named
            for n in (notes_of(decl),)
            if n.title or n.prereqs or n.see or n.terms or n.acronyms
        )
        issues = tuple(
            f"{d.severity}: {path}:{d.line}: {d.message}" for decl in declarations for d in notes_of(decl).diagnostics
        ) + tuple(f"{d.severity}: {path}:{d.line}: {d.message}" for d in diagnostics)
        states = [annotation_state(decl) for decl in named]
        return FileSummary(
            notes=notes,
            issues=issues,
            annotated=states.count("annotated"),
            flagged=states.count("flagged"),
            unannotated=states.count("unannotated"),
        )

    def issues(self, path: str, summary: FileSummary) -> Sequence[str]:
        return summary.issues

    # ---- tree analysis ----
    def analyze(self, objects: Objects, summaries: Mapping[str, Any], options: Mapping[str, Any]) -> Analysis:
        notes: list[Note] = []
        annotated = flagged = unannotated = 0
        for summary in summaries.values():
            if summary is None:
                continue
            notes.extend(summary.notes)
            annotated += summary.annotated
            flagged += summary.flagged
            unannotated += summary.unannotated
        merged, merge_issues = merge_notes(notes, objects)
        terms, term_issues = build_glossary(merged)
        acronyms, acronym_issues = build_acronyms(merged)
        use_path = bool(options.get("learning_path", True))
        steps, path_issues = build_learning_path(merged, objects) if use_path else ([], [])
        prereq_edges, see_edges = build_links(merged, objects)
        graph_issues = [*merge_issues, *acronym_issues, *path_issues, *unresolved_links(notes, objects)]
        words = sorted(terms, key=len, reverse=True)
        pattern = re.compile(r"(?<![\w'])(" + "|".join(re.escape(w) for w in words) + r")(?![\w'])") if words else None
        return Analysis(
            notes=tuple(notes),
            terms=terms,
            acronyms=acronyms,
            steps=steps,
            prereqs=prereq_edges,
            sees=see_edges,
            anchors={term: f"t{index}" for index, term in enumerate(sorted(terms, key=str.lower))},
            term_pattern=pattern,
            issues=tuple([*term_issues, *graph_issues]),
            graph_issues=tuple(graph_issues),
            annotated=annotated,
            flagged=flagged,
            unannotated=unannotated,
        )

    def analysis_issues(self, analysis: Analysis) -> Sequence[str]:
        return analysis.issues

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        path = options.get("overlay")
        overlay = load_overlay(str(path)).digest[:16] if path else ""
        disclosure = str(options.get("overlay_disclosure", ""))
        disclosure_digest = hashlib.sha256(disclosure.encode("utf-8")).hexdigest()[:16] if disclosure else ""
        sources = str(options.get("overlay_sources", ""))
        sources_digest = hashlib.sha256(sources.encode("utf-8")).hexdigest()[:16] if sources else ""
        credit = str(options.get("overlay_credit", ""))
        credit_digest = hashlib.sha256(credit.encode("utf-8")).hexdigest()[:16] if credit else ""
        return (
            f"l4del:{__version__}:schema={_CACHE_SCHEMA}:learning_path={options.get('learning_path', True)}:"
            f"overlay={overlay}:provenance={options.get('overlay_provenance', '')}:"
            f"disclosure={disclosure_digest}:sources={sources_digest}:credit={credit_digest}"
        )

    # ---- rendering ----
    def css(self, options: Mapping[str, Any]) -> str:
        return CSS

    def declaration_title(self, decl: Declaration, payload: L4Notes) -> str:
        return f' <span class="title">{escape(payload.title)}</span>' if payload.title else ""

    def declaration_blocks(
        self, decl: Declaration, payload: L4Notes, rel: str, dirs: list[str], ctx: Context, analysis: Analysis
    ) -> tuple[str, str]:
        top: list[str] = []
        depth = len(dirs)
        options = dict(ctx.options)
        sources = list(payload.sources)
        if payload.origin == "overlay" and ctx.source_url:
            pinned = source_href(rel, decl.line, ctx)
            if pinned not in {url for _, url in sources}:
                ref = ctx.source_ref[:12] if ctx.source_ref else "configured revision"
                sources.insert(0, (f"Pinned Lean source ({ref})", pinned))
        if payload.origin == "overlay":
            for shared in _overlay_sources(options.get("overlay_sources")):
                if shared[1] not in {url for _, url in sources}:
                    sources.append(shared)
        source_by_label = {label: url for label, url in sources}
        if payload.origin == "overlay" and sources:
            source_by_label.setdefault("Pinned Lean source", sources[0][1])
        disclosure = str(options.get("overlay_disclosure", "")).strip()
        if not disclosure and options.get("overlay_provenance") == "ai-generated-unreviewed":
            disclosure = (
                "AI-generated and not human-reviewed. Treat this explanatory draft as unverified "
                "and not mathematical authority."
            )
        if payload.origin == "overlay" and disclosure:
            top.append(
                '<aside class="l4del-provenance"><strong>Annotation provenance.</strong> '
                f"{escape(disclosure)}</aside>"
            )
        for label, excerpt in payload.quotes:
            url = source_by_label.get(label, "")
            citation = (
                f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
                if url
                else f'{escape(label)} (source link unresolved)'
            )
            top.append(
                f'<blockquote class="l4del-quote" cite="{escape(url, quote=True)}">'
                f'<p>{_highlight(excerpt, analysis, depth)}</p><footer>— {citation}</footer></blockquote>'
            )
        if payload.intuition:
            top.append(f'<p class="intuition">{_highlight(payload.intuition, analysis, depth)}</p>')
        if payload.steps:
            items = "".join(f"<li>{_highlight(step, analysis, depth)}</li>" for step in payload.steps)
            top.append(f'<ol class="steps">{items}</ol>')
        if payload.prereqs:
            top.append(refs("Prerequisites", payload.prereqs, None, dirs, ctx))
        if payload.see:
            top.append(refs("See also", payload.see, None, dirs, ctx))
        if sources:
            links = ", ".join(
                f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' for label, url in sources
            )
            top.append(f'<p class="l4del-sources"><strong>Sources and attribution:</strong> {links}</p>')
        bottom = [
            f'<p class="l4term"><strong>{escape(word)}</strong>: {escape(definition)}</p>'
            for word, definition in payload.terms
        ]
        if payload.diagnostics:
            bottom.append(_hint(decl, payload, ctx))
        return "".join(top), "".join(bottom)

    def file_preamble(self, lean_file: Any, ctx: Context, analysis: Analysis) -> str:
        payloads = [
            payload
            for declaration in lean_file.declarations
            for payload in (declaration.ext.get(self.name),)
            if isinstance(payload, L4Notes) and not payload.is_empty
        ]
        if not payloads:
            return ""
        tokens = {"L4DEL"}
        for payload in payloads:
            parts = [
                payload.title or "",
                payload.intuition or "",
                *payload.steps,
                *(definition for _, definition in payload.terms),
                *(excerpt for _, excerpt in payload.quotes),
            ]
            tokens.update(token for part in parts for token in _ACRONYM_TOKEN_RE.findall(part))
            tokens.update(short for short, _ in payload.acronyms)
        project_acronyms = analysis.acronyms if isinstance(analysis, Analysis) else {}
        local_acronyms = {short: expansion for payload in payloads for short, expansion in payload.acronyms}
        definitions = {
            "L4DEL": _L4DEL_EXPANSION,
            **{key: value[0] for key, value in project_acronyms.items()},
            **local_acronyms,
        }
        rows = []
        for token in sorted(tokens, key=str.casefold):
            expansion = definitions.get(token)
            if expansion:
                meaning = escape(expansion)
            else:
                meaning = "Used in an explanation or its source, but not expanded by this annotation. Follow its linked source."
            rows.append(f'<dt><abbr title="{escape(expansion or token, quote=True)}">{escape(token)}</abbr></dt><dd>{meaning}</dd>')
        options = dict(ctx.options)
        credit = str(options.get("overlay_credit", "")).strip()
        shared = _overlay_sources(options.get("overlay_sources"))
        source_links = ""
        if shared:
            links = ", ".join(
                f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' for label, url in shared
            )
            source_links = f'<p><strong>Project sources:</strong> {links}</p>'
        credit_html = f'<p><strong>Credit:</strong> {escape(credit)}</p>' if credit else ""
        return (
            '<section class="explanation-legend" aria-labelledby="explanation-legend-heading">'
            '<h2 id="explanation-legend-heading">Explanation legend</h2>'
            '<p><strong>L4DEL explanations are a separate layer.</strong> They do not change the Lean source. '
            'Intuition is explanatory prose; numbered items are a reading path; sources link the wording back to evidence.</p>'
            f'<dl class="acronym-legend">{"".join(rows)}</dl>{credit_html}{source_links}</section>'
        )

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        links = [("Explanation guide", f"{up}annotate.html")]
        if options.get("learning_path", True):
            links.append(("Learning path", f"{up}learning-path.html"))
        return links

    def pages(self, ctx: Context, analysis: Analysis) -> Mapping[str, str]:
        found = {"annotate.html": _guide_page(ctx)}
        if dict(ctx.options).get("learning_path", True):
            found["learning-path.html"] = _learning_path_page(analysis.steps, list(analysis.graph_issues), ctx)
        return found

    def glossary(self, ctx: Context, analysis: Analysis) -> Sequence[GlossarySection]:
        entries = tuple(
            GlossaryEntry(term=term, meaning=escape(definition), where=(rel, line, decl_name), anchor=analysis.anchors[term])
            for term, (definition, decl_name, (rel, line)) in analysis.terms.items()
        )
        intro = (
            "Words defined in the explanations on this site (Lean4 Domain Explanation Language term lines). "
            "Where they appear, they link here."
        )
        acronym_entries = tuple(
            GlossaryEntry(term=short, meaning=escape(expansion), where=(rel, line, decl_name))
            for short, (expansion, decl_name, (rel, line)) in analysis.acronyms.items()
        )
        sections = [GlossarySection(key="l4del", title="Terms from the explanations", entries=entries, intro=intro)]
        if acronym_entries:
            sections.append(
                GlossarySection(
                    key="l4del-acronyms",
                    title="Acronyms from the explanations",
                    entries=acronym_entries,
                    intro="Explicit expansions supplied by acronym lines and repeated in each affected page's legend.",
                )
            )
        return tuple(sections)

    def status(self, analysis: Analysis) -> str:
        return (
            f"{_L4DEL_EXPANSION} (L4DEL): {analysis.annotated} annotated, "
            f"{analysis.flagged} flagged (errors or placeholders), {analysis.unannotated} without an L4DEL annotation. "
            "Run lean4-explainer annotate --file <path> for templates."
        )

    def summary(self, analysis: Analysis) -> Sequence[str]:
        return (
            f"{_L4DEL_EXPANSION} (L4DEL): {analysis.annotated} annotated, {analysis.flagged} flagged, "
            f"{analysis.unannotated} without an L4DEL annotation; "
            f"{len(analysis.terms)} glossary terms, {len(analysis.steps)} learning-path steps.",
        )

    # ---- command line ----
    def register_cli(self, commands: argparse._SubParsersAction) -> None:
        check = commands.add_parser("check", help="validate L4DEL and names without writing a site")
        check.add_argument("--lean-root", required=True, type=Path, help="directory containing .lean files")
        check.add_argument("--config", type=Path, help="lean4-explainer.toml settings file")
        check.add_argument("--cache", type=Path, help="optional cache directory to reuse")
        check.add_argument("--jobs", type=int, default=1, help="worker processes for indexing")
        annotate = commands.add_parser("annotate", help="print L4DEL templates for one Lean file")
        annotate.add_argument("--lean-root", required=True, type=Path, help="directory containing .lean files")
        annotate.add_argument("--file", required=True, help="path of the file relative to the lean root")
        annotate.add_argument("--config", type=Path, help="lean4-explainer.toml settings file")
        annotate.add_argument("--cache", type=Path, help="optional cache directory to reuse")

    def run_cli(self, args: argparse.Namespace) -> int | None:
        if args.command == "check":
            return _check(args)
        if args.command == "annotate":
            return _annotate(args)
        return None


def _analysis_of(tree) -> Analysis:
    return next(analysis for ext, analysis in tree.analyses if ext.name == "l4del")


def _check(args) -> int:
    try:
        config = load_config(args.config)
        tree = check_tree(args.lean_root, config, args.cache, jobs=args.jobs)
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    analysis = _analysis_of(tree)
    errors = [issue for issue in tree.issues if issue.startswith("error:")]
    warnings = [issue for issue in tree.issues if issue.startswith("warning:")]
    for message in errors:
        print(message, file=sys.stderr)
    for message in warnings[:_WARNING_PREVIEW]:
        print(message)
    print(
        f"{len(tree.sources)} files checked; {_L4DEL_EXPANSION} (L4DEL): {analysis.annotated} annotated, "
        f"{analysis.flagged} flagged, {analysis.unannotated} without an L4DEL annotation; "
        f"{len(errors)} errors, {len(warnings)} warnings"
    )
    if tree.objects.identical or tree.objects.variant:
        from lean4_explainer.cli import duplicates_line

        print(duplicates_line(tree.objects.identical, tree.objects.variant))
    return 1 if errors else 0


def annotation_templates(lean_root: Path, rel: str, config=None, cache_dir: Path | None = None) -> str:
    tree = check_tree(lean_root, config, cache_dir)
    path = lean_root / rel
    if not path.is_file():
        raise ExplainerError(f"not a Lean file under {lean_root}: {rel}")
    lean_file = parse_source(path.read_bytes().decode("utf-8-sig", errors="replace"), rel, statements=True)
    return annotation_report(lean_file, tree.locations, tree.objects.ambiguous)


def _annotate(args) -> int:
    try:
        text = annotation_templates(args.lean_root, args.file, load_config(args.config), args.cache)
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(text)
    return 0


# ---- pages and fragments ----
def _highlight(text: str, analysis: Analysis, depth: int) -> str:
    if analysis.term_pattern is None:
        return escape(text)
    pieces: list[str] = []
    last = 0
    for match in analysis.term_pattern.finditer(text):
        term = match.group(1)
        link = up_path(depth) + f"glossary.html#{analysis.anchors[term]}"
        pieces.append(escape(text[last : match.start()]))
        pieces.append(f'<a class="term" href="{link}">{escape(term)}</a>')
        last = match.end()
    pieces.append(escape(text[last:]))
    return "".join(pieces)


def _overlay_sources(raw: object) -> tuple[tuple[str, str], ...]:
    if not raw:
        return ()
    try:
        rows = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise ExplainerError(f"overlay_sources is not valid JSON: {exc}") from exc
    if not isinstance(rows, list) or not all(
        isinstance(row, list)
        and len(row) == 2
        and all(isinstance(value, str) and value for value in row)
        and row[1].startswith("https://")
        for row in rows
    ):
        raise ExplainerError("overlay_sources must be a JSON list of [label, https://URL] pairs")
    return tuple((row[0], row[1]) for row in rows)


def _hint(decl: Declaration, payload: L4Notes, ctx: Context) -> str:
    objects = ctx.objects
    ambiguous = objects.ambiguous if objects else frozenset()
    rows = [f'<p class="warn">{escape(str(d))}</p>' for d in payload.diagnostics]
    template = escape(placeholder_block(decl, ctx.locations, ambiguous))
    rows.append(
        '<details class="hint"><summary>Template to annotate this declaration</summary>'
        f"<pre>{template}</pre></details>"
    )
    return "".join(rows)


def _learning_path_page(steps: list[PathStep], warnings: list[str], ctx: Context) -> str:
    body = ["<h1>Learning path</h1>", '<p class="muted">Each declaration appears after its prerequisites.</p>']
    if steps:
        body.append(filter_box("Filter learning path"))
        body.append('<ol class="path" data-filter-rows>')
        for step in steps:
            rel, line = step.location
            link = escape(href([], rel, f"#L{line}"), quote=True)
            title = f' <span class="title">{escape(step.title)}</span>' if step.title else ""
            after = ""
            if step.prereqs:
                after = ' <span class="muted">after ' + ", ".join(escape(p) for p in step.prereqs) + "</span>"
            body.append(f'<li><a href="{link}">{escape(step.name)}</a>{title}{after}</li>')
        body.append("</ol>")
    else:
        body.append('<p class="muted">No declarations have title or prerequisite notes yet.</p>')
    if warnings:
        body.append("<h2>Warnings</h2>")
        body.append('<ul class="list">' + "".join(f'<li class="warn">{escape(w)}</li>' for w in warnings) + "</ul>")
    return page("Learning path", 0, body, ctx, canonical_path="learning-path.html")


def _guide_page(ctx: Context) -> str:
    body = [
        "<h1>Lean4 Domain Explanation Language (L4DEL)</h1>",
        '<section class="explanation-legend" aria-labelledby="guide-legend-heading">'
        '<h2 id="guide-legend-heading">Acronym legend</h2>'
        f'<dl class="acronym-legend"><dt><abbr title="{_L4DEL_EXPANSION}">L4DEL</abbr></dt>'
        f'<dd>{_L4DEL_EXPANSION}</dd></dl>'
        '<p>A domain explanation language keeps expert meaning, provenance, definitions, and reading order explicit '
        'instead of asking a reader to infer them from jargon.</p></section>',
        '<p class="muted">lean4-explainer reads Lean4 Domain Explanation Language directives from Lean line comments. '
        "An annotation is optional at first. "
        "The tool checks every directive it finds, and for each declaration without a valid annotation it "
        "prints a template to paste in.</p>",
        "<h2>Workflow</h2>",
        "<ol>"
        "<li>Run <code>lean4-explainer check --lean-root lean</code> to see errors and warnings.</li>"
        "<li>Run <code>lean4-explainer annotate --lean-root lean --file Demo/Basics.lean</code> "
        "to print templates.</li>"
        "<li>Paste a template directly above its declaration and replace every TODO_ value.</li>"
        "<li>Run check again. A TODO_ value left behind is a warning, so the build reports it.</li>"
        "</ol>",
        "<h2>Directives</h2>",
        "<ul>"
        "<li><code>title</code>: a short heading. At most one.</li>"
        "<li><code>intuition</code>: one plain sentence on why the result holds. At most one.</li>"
        "<li><code>step</code>: one proof step, in order. Any number.</li>"
        "<li><code>prereq</code>: comma-separated fully qualified names the proof depends on.</li>"
        "<li><code>see</code>: comma-separated related declarations.</li>"
        "<li><code>term</code>: <code>word = definition</code>. Each word is defined once in the project.</li>"
        "<li><code>acronym</code>: <code>SHORT = expansion</code>. The expansion appears in the legend at the top "
        "of every affected file page. Acronym-looking source text without a supplied expansion is labeled as unresolved; "
        "the renderer never guesses what an upstream author meant.</li>"
        "<li><code>source</code>: <code>label = https://URL</code>. Repeat it for independent sources.</li>"
        "<li><code>quote</code>: <code>source label = exact excerpt</code>. The label must match a source line; the "
        "excerpt is rendered as a linked quotation rather than being passed off as the explainer's prose.</li>"
        "</ul>",
        "<h2>Sources and attribution</h2>",
        "<p>Use immutable links where possible: a full-commit repository blob for the exact formal source, "
        "a DOI or versioned arXiv record for a paper, or a versioned project blueprint. A citation makes an "
        "explanation traceable; it does not by itself certify that the explanation is correct.</p>",
        "<h2>Rules</h2>",
        "<p>Only line comments carry directives. A directive attaches to the next declaration. "
        "Anonymous declarations cannot carry directives. Keys are case-sensitive. "
        "The full grammar is in the module docstring of <code>lean4_explainer_l4del/grammar.py</code>.</p>",
        "<h2>Same-named declarations</h2>",
        "<p>Identical copies of a declaration count as one object, so a plain name refers to it. "
        "Declarations that share a name but differ in code are distinct definitions. "
        "Refer to one as <code>Name@path</code>, for example <code>Demo.value@Var/B.lean</code>.</p>",
        "<h2>Example</h2>",
        f"<pre>{escape(_GUIDE_EXAMPLE)}</pre>",
    ]
    return page("Lean4 Domain Explanation Language (L4DEL) guide", 0, body, ctx, canonical_path="annotate.html")
