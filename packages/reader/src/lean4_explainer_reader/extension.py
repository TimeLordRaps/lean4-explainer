"""The reader extension: a plain-English reading of every declaration, made from its source text.

Every page stays small: it carries only the source (or where to fetch it), and reader.js writes the rest.
On each file page, every declaration gets a "Reading": what the statement says in words, what is given and assumed,
each proof step with what it does, the results it uses, and the symbols a newcomer may not know. The reading is
written by `reader.js` in the browser from the file's source, which the page either carries (the default) or, for a
tree too large to publish twice, loads from a pinned raw-source URL when the page opens.

It reads text only. Lean is not run, so the reading says what each tactic does, not the goal it leaves.

The glossary page gets every word the reader explains (types, classes, properties, symbols, tactics) from
`vocabulary.json`, which `tools/vocabulary.cjs` makes from the tables in reader.js.

The formulas in doc comments (which the core marks) are typeset too, with the project's own TeX macros when it has a
blueprint (`macros.py`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from lean4_explainer.extensions import Extension, GlossaryEntry, GlossarySection
from lean4_explainer.render import Context

from .macros import blueprint_macros

__version__ = "0.2.0"

HERE = Path(__file__).parent
SCRIPT = "_assets/reader.js"
LEAN2TEX = "_assets/lean2tex.js"
READER_JS = (HERE / "reader.js").read_text(encoding="utf-8")
LEAN2TEX_JS = (HERE / "lean2tex.js").read_text(encoding="utf-8")
KATEX_DIR = HERE / "vendor" / "katex"
KATEX = json.loads((KATEX_DIR / "VENDOR.json").read_text(encoding="utf-8"))
VOCABULARY = json.loads((HERE / "vocabulary.json").read_text(encoding="utf-8"))
# KaTeX (MIT) draws the formulas lean2tex writes; it goes into every site next to reader.js, so pages work offline
KATEX_FILES = {f"_assets/katex/{'LICENSE.txt' if rel == 'LICENSE' else rel}": KATEX_DIR / rel for rel in KATEX["sha256"]}
_EMBED_LIMIT = 2_000_000  # characters of source per page; a bigger file gets no reading unless a source URL is set

CSS = """
#reader-note { font-size: 0.9rem; color: var(--muted); border-left: 3px solid var(--line); padding: 0.2rem 0.6rem; margin: 0.6rem 0; }
#reader-note .reader-status:empty { display: none; }
#reader-note .reader-controls { display: inline-flex; gap: 0.35rem; margin-left: 0.45rem; }
#reader-note button { font: inherit; color: inherit; background: transparent; border: 1px solid var(--line); border-radius: 4px; cursor: pointer; }
details.reading { margin: 0.45rem 0 0.2rem; }
details.reading > summary { cursor: pointer; font-size: 0.9rem; color: var(--muted); }
details.reading[open] > summary { margin-bottom: 0.3rem; }
.rd { border-left: 3px solid var(--line); padding: 0.1rem 0 0.1rem 0.75rem; }
.rd p { margin: 0.35rem 0; }
.rd ul, .rd ol { margin: 0.25rem 0 0.4rem; padding-left: 1.4rem; }
.rd li { margin: 0.18rem 0; }
.rd code.rd-tac { background: var(--line); padding: 0 0.25rem; border-radius: 3px; margin-right: 0.3rem; }
.rd .rd-case { font-weight: 600; }
.rd ol.rd-calc { list-style: none; padding-left: 0.8rem; }
.rd details { margin: 0.35rem 0; }
.rd details > summary { cursor: pointer; color: var(--muted); font-size: 0.88rem; }
.rd dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.15rem 0.8rem; margin: 0.3rem 0; }
.rd dt { font-family: ui-monospace, monospace; }
.rd dd { margin: 0; }
.rd pre { overflow-x: auto; font-size: 0.85rem; }
.rd .rd-math { overflow-x: auto; overflow-y: hidden; padding: 0.15rem 0 0.25rem; }
.rd .rd-math:not(.typeset) > code { display: block; }
.rd .m.typeset .katex { font-size: 1.08em; }
.rd .rd-math.typeset .katex-display { margin: 0.35rem 0; text-align: left; }
.rd .rd-math.typeset .katex-display > .katex { text-align: left; }
.doc .m.typeset .katex, dl.glossary .m.typeset .katex { font-size: 1.05em; }
"""



class ReaderExtension(Extension):
    name = "reader"
    version = __version__
    config_keys = {"reader_source_url": str, "reader_embed_limit": int, "reader_blueprint_macros": bool}

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        digest = hashlib.sha256((READER_JS + LEAN2TEX_JS).encode("utf-8")).hexdigest()[:16]
        return (
            f"reader:{__version__}:{digest}:katex-{KATEX['version']}:{options.get('reader_source_url', '')}:"
            f"{options.get('reader_embed_limit', _EMBED_LIMIT)}"
        )

    def analyze(self, objects: Any, summaries: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        root = options.get("_root")
        if not root or not options.get("reader_blueprint_macros", True):
            return {"macros": {}}
        return {"macros": blueprint_macros(Path(str(root)))}

    def css(self, options: Mapping[str, Any]) -> str:
        return CSS

    def scripts(self, options: Mapping[str, Any]) -> Sequence[str]:
        return (LEAN2TEX, SCRIPT)  # deferred scripts run in order: the translator is there before the reader starts

    def pages(self, ctx: Context, analysis: Any) -> Mapping[str, str | bytes]:
        return {SCRIPT: reader_js(_macros(analysis)), LEAN2TEX: LEAN2TEX_JS} | {path: source.read_bytes() for path, source in KATEX_FILES.items()}

    def file_blocks(self, lean_file: Any, text: str, ctx: Context, analysis: Any) -> str:
        if not lean_file.declarations:
            return ""
        options = dict(ctx.options)
        template = options.get("reader_source_url")
        if template:
            url = str(template).replace("{path}", quote(lean_file.path)).replace("{ref}", quote(ctx.source_ref))
            return f'<div id="lean-source" data-src="{escape(url, quote=True)}" hidden></div>'
        if not text or len(text) > int(options.get("reader_embed_limit", _EMBED_LIMIT)):
            return ""
        payload = json.dumps(text, ensure_ascii=False).replace("<", "\\u003c")
        return f'<script type="application/json" id="lean-source">{payload}</script>'

    def glossary(self, ctx: Context, analysis: Any) -> Sequence[GlossarySection]:
        return tuple(
            GlossarySection(
                key=section["key"],
                title=section["title"],
                intro=section["intro"],
                entries=tuple(
                    GlossaryEntry(term=e["term"], meaning=e["meaning"], example=e["example"], anchor=e["anchor"])
                    for e in section["entries"]
                ),
            )
            for section in VOCABULARY["sections"]
        )

    def summary(self, analysis: Any) -> Sequence[str]:
        lines = ["Reader: every file page carries a plain-English reading of its declarations (made in the browser)."]
        if _macros(analysis):
            lines.append(f"Reader: {len(_macros(analysis))} TeX macros from the project's blueprint.")
        return tuple(lines)


_MACROS_MARK = "const PROJECT_MACROS = {};"


def reader_js(macros: Mapping[str, str]) -> str:
    """reader.js with the project's TeX macros in it."""
    assert READER_JS.count(_MACROS_MARK) == 1
    return READER_JS.replace(_MACROS_MARK, f"const PROJECT_MACROS = {json.dumps(dict(macros), ensure_ascii=True)};")


def _macros(analysis: Any) -> Mapping[str, str]:
    return analysis.get("macros", {}) if isinstance(analysis, dict) else {}
