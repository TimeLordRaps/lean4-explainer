"""Three things that connect a site to the rest of the Lean world.

- `find.html`: `find.html#Foo.bar` jumps to the declaration `Foo.bar`. That is the target for an `explain#Foo.bar` chat
  link, the way `docs#Foo.bar` works for doc-gen4 (see the README for a Zulip linkifier).
- `snapshot.json` and `changes.html`: what changed since an earlier build, statement versus proof.
- `lake-facet`: prints a Lake snippet that adds `lake build :explain` to a project.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from lean4_explainer.extensions import Extension, ParseResult, SourceView
from lean4_explainer.render import href, page

from . import snapshot as S
from .lakefacet import LAKEFILE_SNIPPET

__version__ = "0.1.0"
_FIND_LIMIT = 200_000
_SNAPSHOT_LIMIT = 100_000
_ROWS = 2000

FIND_JS = """
(function () {
  var box = document.getElementById("name");
  var out = document.getElementById("result");
  function go(name) {
    name = decodeURIComponent((name || "").replace(/^[#?]/, "").replace(/^name=/, "")).trim();
    if (!name) { return; }
    box.value = name;
    var table = window.L4Names || {};
    var at = table[name];
    if (at) { location.replace(at); return; }
    out.textContent = "No declaration named " + name + " on this site.";
  }
  window.addEventListener("hashchange", function () { go(location.hash); });
  document.getElementById("go").addEventListener("submit", function (e) { e.preventDefault(); go(box.value); });
  go(location.hash || location.search);
})();
"""


@dataclass(frozen=True)
class Analysis:
    snapshot: Mapping[str, Any]
    changes: S.Changes | None
    baseline_error: str = ""


class EcosystemExtension(Extension):
    name = "ecosystem"
    version = __version__
    config_keys = {"compare_to": str, "find_limit": int, "snapshot_limit": int}

    def parse(self, view: SourceView) -> ParseResult | None:
        return None

    def index_file(self, path, declarations, diagnostics):
        return tuple(S.Entry(d.name, d.line, d.code_digest, d.header_digest) for d in declarations if "(" not in d.name)

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        return f"{self.name}:{self.version}:{options.get('compare_to', '')}"

    cache_types = frozenset({("lean4_explainer_ecosystem.snapshot", "Entry")})

    def analyze(self, objects, summaries, options) -> Analysis:
        files = {rel: tuple(found or ()) for rel, found in summaries.items()}
        current = S.make(files, int(options.get("snapshot_limit", _SNAPSHOT_LIMIT)))
        path = str(options.get("compare_to", ""))
        if not path:
            return Analysis(current, None)
        try:
            baseline = S.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Analysis(current, None, f"could not read the baseline snapshot {path}: {exc}")
        return Analysis(current, S.diff(baseline, current))

    def analysis_issues(self, analysis: Analysis) -> Sequence[str]:
        return [f"warning: {analysis.baseline_error}"] if analysis.baseline_error else []

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        links = [("Find", f"{up}find.html")]
        if options.get("compare_to"):
            links.append(("Changes", f"{up}changes.html"))
        return links

    def pages(self, ctx, analysis: Analysis) -> Mapping[str, str]:
        options = dict(ctx.options)
        found = {
            "snapshot.json": S.dumps(analysis.snapshot),
            "find.html": _find_page(ctx),
            "_assets/find.js": FIND_JS,
            "_assets/find-names.js": _names_script(ctx, int(options.get("find_limit", _FIND_LIMIT))),
        }
        if options.get("compare_to"):
            found["changes.html"] = _changes_page(ctx, analysis)
        return found

    def status(self, analysis: Analysis) -> str:
        if analysis.changes is None:
            return ""
        c = analysis.changes
        return (
            f"Since the baseline: {len(c.added)} added, {len(c.removed)} removed, "
            f"{len(c.statement_changed)} statements changed, {len(c.proof_changed)} proofs changed."
        )

    def summary(self, analysis: Analysis) -> Sequence[str]:
        return (self.status(analysis),) if analysis.changes else ()

    # -- command line --
    def register_cli(self, commands: argparse._SubParsersAction) -> None:
        facet = commands.add_parser("lake-facet", help="print the lakefile.lean snippet that adds `lake build :explain`")
        facet.add_argument("--out", type=Path, help="write the snippet to this file instead of printing it")

    def run_cli(self, args: argparse.Namespace) -> int | None:
        if args.command != "lake-facet":
            return None
        if args.out:
            args.out.write_text(LAKEFILE_SNIPPET, encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(LAKEFILE_SNIPPET, end="")
        return 0


def _find_page(ctx) -> str:
    body = [
        "<h1>Find a declaration</h1>",
        '<p class="muted">Open <code>find.html#Name</code> to jump to a declaration by its full name. '
        "This is the page an <code>explain#Name</code> chat link points to.</p>",
        '<form id="go"><input id="name" type="search" placeholder="Foo.bar" autocomplete="off"></form>',
        '<p id="result" class="warn"></p>',
        '<script src="_assets/find-names.js"></script>',
        '<script src="_assets/find.js"></script>',
    ]
    return page("Find", 0, body, ctx)


def _names_script(ctx, limit: int) -> str:
    names = sorted(ctx.locations)
    kept = names[:limit]
    table = {name: href([], ctx.locations[name][0], f"#L{ctx.locations[name][1]}") for name in kept}
    note = f"/* {len(names) - len(kept)} names beyond find_limit={limit} are not in this table */\n" if len(names) > limit else ""
    return note + "window.L4Names = " + json.dumps(table, ensure_ascii=False, separators=(",", ":")) + ";\n"


def _changes_page(ctx, analysis: Analysis) -> str:
    body = ["<h1>Changes since the baseline</h1>"]
    if analysis.changes is None:
        body.append(f'<p class="warn">{escape(analysis.baseline_error or "No baseline was compared.")}</p>')
        return page("Changes", 0, body, ctx)
    c = analysis.changes
    if c.level != "declaration":
        body.append(
            '<p class="muted">The two snapshots are not both declaration-level (the tree is too large for per-declaration '
            "snapshots), so only whole files are compared.</p>"
        )
    sections = (
        ("Statement changed", c.statement_changed),
        ("Proof changed (statement the same)", c.proof_changed),
        ("Added", c.added),
        ("Removed", c.removed),
        ("Files changed", c.files_changed),
    )
    for heading, rows in sections:
        if not rows:
            continue
        body.append(f'<h2>{heading} ({len(rows)})</h2><ul class="list">')
        for row in rows[:_ROWS]:
            body.append(f"<li><code>{escape(row)}</code></li>")
        if len(rows) > _ROWS:
            body.append(f'<li class="muted">… and {len(rows) - _ROWS} more</li>')
        body.append("</ul>")
    if not any(rows for _, rows in sections):
        body.append("<p>Nothing changed.</p>")
    return page("Changes", 0, body, ctx)
