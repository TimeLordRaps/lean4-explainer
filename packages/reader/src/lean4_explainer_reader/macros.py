r"""A project's own TeX macros, read from its blueprint, so the formulas in its doc comments draw as they do there.

Lean projects with a blueprint (leanblueprint) keep their macros in `blueprint/src/macros/common.tex` (some use
`macro/` or `preamble/`), with web-only ones in `web.tex` next to it. This reads `\newcommand`, `\renewcommand`,
`\providecommand`, `\DeclareMathOperator` and `\def` from those two files. A macro with an optional argument is
left out (KaTeX's macros cannot have one), and so is anything that is not a plain macro."""

from __future__ import annotations

import re
from pathlib import Path

PLACES = ("macros", "macro", "preamble")
FILES = ("common.tex", "web.tex")  # in this order: web.tex may redefine for the web
_FILE_LIMIT = 1_000_000  # bytes; a preamble is a few kilobytes
_COUNT_LIMIT = 2_000
_BODY_LIMIT = 1_000

_NAME = re.compile(r"\\[A-Za-z]+")
_COMMAND = re.compile(r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator)(\*?)|\\def(?=\s*\\[A-Za-z])")
_COMMENT = re.compile(r"(?<!\\)%.*")
_UNSAFE = re.compile(r"\\(?:def|newcommand|renewcommand|providecommand|makeatletter|makeatother|catcode|input|include)\b|@")


def blueprint_macros(root: Path) -> dict[str, str]:
    """The macros of the blueprint next to (or one level above) the Lean sources, or {} when there is none."""
    for base in (root, root.parent):
        for place in PLACES:
            folder = base / "blueprint" / "src" / place
            found: dict[str, str] = {}
            for name in FILES:
                path = folder / name
                if path.is_file() and path.stat().st_size <= _FILE_LIMIT:
                    found.update(parse_macros(path.read_bytes().decode("utf-8", errors="replace")))
            if found:
                return dict(list(found.items())[:_COUNT_LIMIT])
    return {}


def parse_macros(tex: str) -> dict[str, str]:
    tex = "\n".join(_COMMENT.sub("", line) for line in tex.split("\n"))
    found: dict[str, str] = {}
    for match in _COMMAND.finditer(tex):
        command, star = match.group(1) or "def", match.group(2) or ""
        pos = _skip(tex, match.end())
        name, pos = _macro_name(tex, pos)
        if name is None:
            continue
        if command == "DeclareMathOperator":
            text, pos = _group(tex, pos)
            if text is not None and not _UNSAFE.search(text):
                found[name] = f"\\operatorname{star}{{{text.strip()}}}"
            continue
        if command == "def":
            params = re.match(r"(?:#[1-9])*", tex[pos:])
            pos = _skip(tex, pos + (params.end() if params else 0))
        elif tex.startswith("[", pos):
            count = re.match(r"\[\s*([1-9])\s*\]", tex[pos:])
            if not count:
                continue
            pos = _skip(tex, pos + count.end())
        body, pos = _group(tex, pos)  # none after an optional argument's `[default]`: KaTeX cannot have one
        if body is None or len(body) > _BODY_LIMIT or _UNSAFE.search(body):
            continue
        if command == "providecommand" and name in found:
            continue
        found[name] = body.strip()
    return found


def _skip(tex: str, pos: int) -> int:
    while pos < len(tex) and tex[pos] in " \t\n":
        pos += 1
    return pos


def _macro_name(tex: str, pos: int) -> tuple[str | None, int]:
    """`{\name}` or `\name`."""
    if tex.startswith("{", pos):
        inner, end = _group(tex, pos)
        if inner is None or not _NAME.fullmatch(inner.strip()):
            return None, pos
        return inner.strip(), _skip(tex, end)
    name = _NAME.match(tex, pos)
    return (name.group(0), _skip(tex, name.end())) if name else (None, pos)


def _group(tex: str, pos: int) -> tuple[str | None, int]:
    """The text of the brace group at `pos`, and where it ends; (None, pos) when there is no closed group."""
    if not tex.startswith("{", pos):
        return None, pos
    depth = 0
    i = pos
    while i < len(tex):
        c = tex[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return tex[pos + 1 : i], i + 1
        i += 1
    return None, pos
