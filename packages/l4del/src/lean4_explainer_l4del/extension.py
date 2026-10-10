"""The L4DEL extension: reads `-- L4DEL: key: value` comments and adds the explanation layer to the site.

Adds, on top of the core site: titles, intuition, proof steps, prerequisite and see-also links on declarations;
a glossary; a learning path ordered by prerequisites; an annotation guide; and the `check` and `annotate`
commands. Without this package the core site is built from standard Lean comments only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from lean4_explainer.build import check_tree
from lean4_explainer.config import load_config
from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import Diagnostic, Extension, ParseResult, SourceView
from lean4_explainer.objects import Objects
from lean4_explainer.render import Context, href, page, refs, up_path
from lean4_explainer.scan import Declaration, parse_source

from .grammar import L4Notes, parse_l4del
from .graph import PathStep, build_glossary, build_learning_path, merge_notes, unresolved_links
from .model import FileSummary, Note
from .templates import annotation_report, annotation_state, notes_of, placeholder_block

__version__ = "0.1.0"

_PREFIX = "L4DEL:"
_CARRIER_RE = re.compile(r"^[ \t]*L4DEL:(?P<rest>.*)$")
_WARNING_PREVIEW = 20

CSS = """
.l4del { margin: 0.3rem 0; padding-left: 0.6rem; border-left: 3px solid var(--line); }
.l4term { margin: 0.3rem 0; }
dl.glossary dt { font-weight: 600; margin-top: 0.6rem; }
dl.glossary dd { margin: 0 0 0.2rem 1rem; }
"""

_GUIDE_EXAMPLE = "\n".join(
    [
        "/-- Three items in two boxes put two items in one box. -/",
        "-- L4DEL: title: Pigeonhole for three items in two boxes",
        "-- L4DEL: intuition: Three items cannot all sit in different boxes when there are only two boxes.",
        "-- L4DEL: step: Assume no box holds two items.",
        "-- L4DEL: step: Then three items need three different boxes, which do not exist.",
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
    steps: list = field(default_factory=list, repr=False)
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
    config_keys = {"learning_path": bool}

    # ---- parsing and indexing ----
    def hides_comment(self, body: str) -> bool:
        return body.strip().startswith(_PREFIX)

    def is_described(self, payload: Any) -> bool:
        return not payload.is_empty

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
        return ParseResult({index: parse_l4del(items) for index, items in directives_by_head.items()}, diagnostics)

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
            )
            for decl in named
            for n in (notes_of(decl),)
            if n.title or n.prereqs or n.see or n.terms
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
        use_path = bool(options.get("learning_path", True))
        steps, path_issues = build_learning_path(merged, objects) if use_path else ([], [])
        graph_issues = [*merge_issues, *path_issues, *unresolved_links(notes, objects)]
        words = sorted(terms, key=len, reverse=True)
        pattern = re.compile(r"(?<![\w'])(" + "|".join(re.escape(w) for w in words) + r")(?![\w'])") if words else None
        return Analysis(
            notes=tuple(notes),
            terms=terms,
            steps=steps,
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
        return f"l4del:{__version__}:learning_path={options.get('learning_path', True)}"

    # ---- rendering ----
    def css(self) -> str:
        return CSS

    def declaration_title(self, decl: Declaration, payload: L4Notes) -> str:
        return f' <span class="title">{escape(payload.title)}</span>' if payload.title else ""

    def declaration_blocks(
        self, decl: Declaration, payload: L4Notes, rel: str, dirs: list[str], ctx: Context, analysis: Analysis
    ) -> tuple[str, str]:
        top: list[str] = []
        depth = len(dirs)
        if payload.intuition:
            top.append(f'<p class="intuition">{_highlight(payload.intuition, analysis, depth)}</p>')
        if payload.steps:
            items = "".join(f"<li>{_highlight(step, analysis, depth)}</li>" for step in payload.steps)
            top.append(f'<ol class="steps">{items}</ol>')
        if payload.prereqs:
            top.append(refs("Prerequisites", payload.prereqs, None, dirs, ctx))
        if payload.see:
            top.append(refs("See also", payload.see, None, dirs, ctx))
        bottom = [
            f'<p class="l4term"><strong>{escape(word)}</strong>: {escape(definition)}</p>'
            for word, definition in payload.terms
        ]
        if payload.diagnostics:
            bottom.append(_hint(decl, payload, ctx))
        return "".join(top), "".join(bottom)

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        links = [("Glossary", f"{up}glossary.html"), ("L4DEL guide", f"{up}annotate.html")]
        if options.get("learning_path", True):
            links.append(("Learning path", f"{up}learning-path.html"))
        return links

    def pages(self, ctx: Context, analysis: Analysis) -> Mapping[str, str]:
        found = {"glossary.html": _glossary_page(ctx, analysis), "annotate.html": _guide_page(ctx)}
        if dict(ctx.options).get("learning_path", True):
            found["learning-path.html"] = _learning_path_page(analysis.steps, list(analysis.graph_issues), ctx)
        return found

    def status(self, analysis: Analysis) -> str:
        return (
            f"L4DEL: {analysis.annotated} annotated, {analysis.flagged} flagged (errors or placeholders), "
            f"{analysis.unannotated} without L4DEL. Run lean4-explainer annotate --file <path> for templates."
        )

    def summary(self, analysis: Analysis) -> Sequence[str]:
        return (
            f"L4DEL: {analysis.annotated} annotated, {analysis.flagged} flagged, {analysis.unannotated} without L4DEL; "
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
        f"{len(tree.sources)} files checked; L4DEL: {analysis.annotated} annotated, {analysis.flagged} flagged, "
        f"{analysis.unannotated} without L4DEL; {len(errors)} errors, {len(warnings)} warnings"
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


def _glossary_page(ctx: Context, analysis: Analysis) -> str:
    body = ["<h1>Glossary</h1>"]
    if analysis.terms:
        body.append('<dl class="glossary">')
        for term in sorted(analysis.terms, key=str.lower):
            definition, decl_name, (rel, line) = analysis.terms[term]
            link = escape(href([], rel, f"#L{line}"), quote=True)
            body.append(
                f'<dt id="{analysis.anchors[term]}">{escape(term)}</dt>'
                f'<dd>{escape(definition)} <span class="muted">(<a href="{link}">{escape(decl_name)}</a>)</span></dd>'
            )
        body.append("</dl>")
    else:
        body.append('<p class="muted">No terms yet. Add a term: word = definition line to an L4DEL comment.</p>')
    return page("Glossary", 0, body, ctx)


def _learning_path_page(steps: list[PathStep], warnings: list[str], ctx: Context) -> str:
    body = ["<h1>Learning path</h1>", '<p class="muted">Each declaration appears after its prerequisites.</p>']
    if steps:
        body.append('<ol class="path">')
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
    return page("Learning path", 0, body, ctx)


def _guide_page(ctx: Context) -> str:
    body = [
        "<h1>Annotating with L4DEL</h1>",
        '<p class="muted">lean4-explainer reads L4DEL from Lean line comments. An annotation is optional at first. '
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
        "</ul>",
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
    return page("L4DEL guide", 0, body, ctx)
