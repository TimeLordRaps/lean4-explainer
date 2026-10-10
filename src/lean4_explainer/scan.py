"""Source-level scan of Lean 4 files. Text heuristics only; Lean is never run."""

from __future__ import annotations

import hashlib
import os
import re
import textwrap
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .extensions import Comment, Diagnostic, Head, SourceView, extensions

DECLARATION_KINDS = (
    "theorem",
    "lemma",
    "def",
    "abbrev",
    "structure",
    "class",
    "inductive",
    "instance",
    "axiom",
    "opaque",
    "example",
)

_DECL_RE = re.compile(
    r"^(?:@\[[^\]]*\]\s*)?"
    r"(?:(?:private|protected|noncomputable|partial|unsafe|nonrec)\s+)*"
    r"(?P<kind>" + "|".join(DECLARATION_KINDS) + r")\b"
    r"(?:[ \t]+(?P<name>[^\s:(){}\[\]|]+))?"
)
_NAMESPACE_RE = re.compile(r"^namespace[ \t]+(?P<name>\S+)")
_SECTION_RE = re.compile(r"^(?:noncomputable[ \t]+)?section\b")
_END_RE = re.compile(r"^end\b")
_IMPORT_RE = re.compile(r"^import[ \t]+(?P<name>\S+)")
_SORRY_RE = re.compile(r"\bsorry\b")
_STATEMENT_END_RE = re.compile(r":=|\bwhere\b")
_TOKEN_RE = re.compile(r"/-|--|\"|'")
_BLOCK_TOKEN_RE = re.compile(r"/-|-/")
_STRING_BODY_RE = re.compile(r'(?:\\.|[^"\\])*"', re.DOTALL)
_CHAR_LITERAL_RE = re.compile(r"'(?:\\.|[^'\\\n])'")

_LEADING_SKIP_PREFIXES = ("@[", "set_option")
_STATEMENT_MAX_LINES = 12
_INDENTED = ("", " ", "\t")


@dataclass(frozen=True)
class Declaration:
    kind: str
    name: str
    line: int
    doc: str | None
    comment: str | None
    statement: str
    has_sorry: bool
    code_digest: int = 0
    header_digest: int = 0
    ext: dict[str, Any] = field(default_factory=dict)  # extension name -> that extension's payload

    @property
    def description(self) -> str | None:
        return self.doc or self.comment


@dataclass(frozen=True)
class LeanFile:
    path: str
    module_doc: str | None
    imports: tuple[str, ...]
    declarations: tuple[Declaration, ...]
    diagnostics: dict[str, tuple[Diagnostic, ...]] = field(default_factory=dict)  # by extension name


@dataclass(frozen=True)
class FileSummary:
    path: str
    declarations: int
    sorry: int
    axioms: int


def summarize(lean_file: LeanFile) -> FileSummary:
    declarations = lean_file.declarations
    return FileSummary(
        path=lean_file.path,
        declarations=len(declarations),
        sorry=sum(decl.has_sorry for decl in declarations),
        axioms=sum(decl.kind == "axiom" for decl in declarations),
    )


_Comment = Comment


def scan_file(path: Path, relative: str) -> LeanFile:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return parse_source(text, relative)


def parse_source(text: str, path: str, statements: bool = False, options: Mapping[str, Any] | None = None) -> LeanFile:
    text = text.replace("\r\n", "\n")
    masked, comments = _mask(text)
    code = masked.split("\n")
    source = text.split("\n")

    ending: dict[int, list[_Comment]] = {}
    for comment in comments:
        ending.setdefault(comment.end_line, []).append(comment)

    active = extensions()

    def hidden(body: str) -> bool:
        return any(ext.hides_comment(body) for ext in active)

    module_doc = next(
        (_clean(c.body) for c in comments if c.kind == "module" and not hidden(c.body)),
        "",
    )

    imports = []
    for line in code:
        match = _IMPORT_RE.match(line)
        if match:
            imports.append(match["name"])

    heads = _declaration_heads(code)
    bounds = [index for index, _, _ in heads[1:]] + [len(code)]

    payloads: dict[str, dict[int, Any]] = {}
    file_diagnostics: dict[str, tuple[Diagnostic, ...]] = {}
    if active:
        view = SourceView(path, code, comments, tuple(Head(*head) for head in heads), dict(options or {}))
        for ext in active:
            result = ext.parse(view)
            if result is not None:
                payloads[ext.name] = dict(result.by_head)
                file_diagnostics[ext.name] = tuple(result.diagnostics)
    boundaries = [k for k, line in enumerate(code) if line[:1] not in _INDENTED and _BOUNDARY_RE.match(line)]
    sorry_lines = [k for k, line in enumerate(code) if "sorry" in line and _SORRY_RE.search(line)]
    declarations = []
    for (index, kind, name), bound in zip(heads, bounds):
        leading, plain = _leading_comments(index, code, ending, hidden)
        doc = next((c for c in leading if c.kind == "doc" and not hidden(c.body)), None)
        doc_text = _clean(doc.body) if doc else ""
        comment = _plain_text(plain)
        here = {ext_name: by_head[index] for ext_name, by_head in payloads.items() if index in by_head}
        described = bool(doc_text or comment) or any(
            ext.is_described(here[ext.name]) for ext in active if ext.name in here
        )
        code_digest, header_digest = _fingerprints(code, boundaries, index, bound, name)
        at = bisect_left(sorry_lines, index)
        declarations.append(
            Declaration(
                kind=kind,
                name=name,
                line=index + 1,
                doc=doc_text or None,
                comment=comment,
                statement=_statement(source, code, index, bound) if described or statements else "",
                has_sorry=at < len(sorry_lines) and sorry_lines[at] < bound,
                code_digest=code_digest,
                header_digest=header_digest,
                ext=here,
            )
        )

    return LeanFile(
        path=path,
        module_doc=module_doc or None,
        imports=tuple(imports),
        declarations=tuple(declarations),
        diagnostics=file_diagnostics,
    )


def iter_lean_files(root: Path) -> list[tuple[str, Path]]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.endswith(".lean"):
                path = Path(dirpath, name)
                found.append((path.relative_to(root).as_posix(), path))
    return sorted(found)


def _declaration_heads(code: list[str]) -> list[tuple[int, str, str]]:
    heads: list[tuple[int, str, str]] = []
    scope: list[str] = []
    for index, line in enumerate(code):
        if line[:1] in _INDENTED:
            continue
        namespace = _NAMESPACE_RE.match(line)
        decl = _DECL_RE.match(line)
        if namespace:
            scope.append(namespace["name"])
        elif _SECTION_RE.match(line):
            scope.append("")
        elif _END_RE.match(line):
            if scope:
                scope.pop()
        elif decl:
            local = decl["name"] or f"({decl['kind']} at line {index + 1})"
            qualified = ".".join(part for part in [*scope, local] if part)
            heads.append((index, decl["kind"], qualified))
    return heads


def _mask(text: str) -> tuple[str, list[_Comment]]:
    """Blank comments and string or char literal bodies, keeping newlines so line numbers hold."""
    pieces: list[str] = []
    comments: list[_Comment] = []
    pos = 0
    line = 1
    while True:
        match = _TOKEN_RE.search(text, pos)
        if match is None:
            pieces.append(text[pos:])
            break
        start = match.start()
        pieces.append(text[pos:start])
        token_line = line + text.count("\n", pos, start)
        token = match.group()

        if token == "/-":
            end, closed = _block_end(text, start)
            span = text[start:end]
            if span.startswith("/--"):
                kind, opener = "doc", 3
            elif span.startswith("/-!"):
                kind, opener = "module", 3
            else:
                kind, opener = "block", 2
            body = span[opener:-2] if closed else span[opener:]
            comments.append(_Comment(kind, token_line, token_line + span.count("\n"), body))
            pieces.append(_blank(span))
        elif token == "--":
            end = text.find("\n", start)
            end = len(text) if end == -1 else end
            span = text[start:end]
            comments.append(_Comment("line", token_line, token_line, span[2:]))
            pieces.append(_blank(span))
        elif token == '"':
            end, closed = _string_end(text, start)
            span = text[start:end]
            inner = span[1:-1] if closed else span[1:]
            pieces.append('"' + _blank(inner) + ('"' if closed else ""))
        else:
            literal = _CHAR_LITERAL_RE.match(text, start)
            if literal and not (start > 0 and _is_ident_char(text[start - 1])):
                end = literal.end()
                pieces.append(_blank(literal.group()))
            else:
                end = start + 1
                pieces.append("'")

        line = token_line + text.count("\n", start, end)
        pos = end
    return "".join(pieces), comments


def _block_end(text: str, start: int) -> tuple[int, bool]:
    depth = 0
    pos = start
    while True:
        match = _BLOCK_TOKEN_RE.search(text, pos)
        if match is None:
            return len(text), False
        depth += 1 if match.group() == "/-" else -1
        pos = match.end()
        if depth == 0:
            return pos, True


def _string_end(text: str, start: int) -> tuple[int, bool]:
    match = _STRING_BODY_RE.match(text, start + 1)
    if match is None:
        return len(text), False
    return match.end(), True


def _leading_comments(
    index: int, code: list[str], ending: dict[int, list[_Comment]], hidden
) -> tuple[list[_Comment], list[_Comment]]:
    """Comments above a declaration, nearest first, as (all, plain). Plain comments must touch the declaration."""
    found: list[_Comment] = []
    plain: list[_Comment] = []
    attached = True
    j = index - 1
    while j >= 0:
        stripped = code[j].strip()
        if stripped and not stripped.startswith(_LEADING_SKIP_PREFIXES):
            break
        here = ending.get(j + 1)
        if here:
            found.extend(here)
            if attached:
                plain.extend(c for c in here if c.kind in ("line", "block") and not hidden(c.body))
            j = min(c.start_line for c in here) - 2
        else:
            if not stripped:
                attached = False
            j -= 1
    return found, plain


def _plain_text(plain: list[_Comment]) -> str | None:
    return "\n".join(_clean(c.body) for c in reversed(plain)) or None


def _statement(source: list[str], code: list[str], index: int, bound: int) -> str:
    limit = min(bound, index + _STATEMENT_MAX_LINES)
    end = limit - 1
    for k in range(index, limit):
        if _STATEMENT_END_RE.search(code[k]):
            end = k
            break
    snippet = "\n".join(source[index : end + 1]).rstrip()
    if any(code[k].strip() for k in range(end + 1, bound)):
        snippet += "\n…"
    return snippet


def _blank(span: str) -> str:
    return re.sub(r"[^\n]", " ", span)


_BOUNDARY_RE = re.compile(r"(?:end|namespace|section|noncomputable section|import)\b")


def _fingerprints(
    code: list[str], boundaries: list[int], index: int, bound: int, name: str
) -> tuple[int, int]:
    """Whitespace-insensitive digests of a declaration's code and of its header (before := or where)."""
    if "(" in name:
        return 0, 0
    at = bisect_right(boundaries, index)
    cut = boundaries[at] if at < len(boundaries) and boundaries[at] < bound else bound
    span = "\n".join(code[index:cut])
    marker = _STATEMENT_END_RE.search(span)
    header = span[: marker.start()] if marker else span
    return _digest(span), _digest(header)


def _digest(text: str) -> int:
    normalized = " ".join(text.split())
    return int.from_bytes(hashlib.blake2b(normalized.encode("utf-8"), digest_size=8).digest(), "big")


def _is_ident_char(char: str) -> bool:
    return char.isalnum() or char in "_'!?"


def _clean(body: str) -> str:
    return textwrap.dedent(body).strip()
