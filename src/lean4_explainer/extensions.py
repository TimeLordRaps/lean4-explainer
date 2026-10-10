"""The extension interface. The core builds a plain proofsite; extensions add to it.

An extension is an installed Python package that exposes an `Extension` subclass through the entry-point group
`lean4_explainer.extensions`. Every hook is optional. With no extension installed the core still builds a complete
site from Lean declarations and their standard comments.

Hooks run in this order for a build:

1. `parse`: per file, in worker processes. May read the comments and declaration heads, and returns one payload
   per declaration plus file-level diagnostics. `hides_comment` keeps an extension's own comment syntax out of
   the plain-comment descriptions.
2. `index_file`: per file, in worker processes. Returns a small picklable summary that is kept in the incremental
   cache. Its types must be listed in `cache_types`, because the cache is loaded through an allow-list.
3. `analyze`: once per tree, with every file's summary and the name index. Returns an analysis object, which the
   later hooks receive.
4. `declaration_title`, `declaration_blocks`, `pages`, `nav_links`, `css`, `status`: rendering.
5. `summary`: lines printed after a build.
6. `register_cli` / `run_cli`: extra subcommands.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from typing import Any

ENTRY_POINT_GROUP = "lean4_explainer.extensions"


@dataclass(frozen=True)
class Comment:
    kind: str  # "line", "block", "doc", or "module"
    start_line: int  # 1-based
    end_line: int
    body: str


@dataclass(frozen=True)
class Head:
    index: int  # 0-based line of the declaration
    kind: str
    name: str


@dataclass(frozen=True)
class SourceView:
    """What `Extension.parse` may read: masked code lines (comments and strings blanked), comments, heads."""

    path: str
    code: Sequence[str]
    comments: Sequence[Comment]
    heads: Sequence[Head]

    def has_code(self, first: int, stop: int) -> bool:
        """True when a line in code[first:stop] is code; blank lines, attributes and set_option lines are not."""
        return any(
            stripped and not stripped.startswith(("@[", "set_option"))
            for stripped in (line.strip() for line in self.code[first:stop])
        )


@dataclass(frozen=True)
class Diagnostic:
    severity: str  # "error" or "warning"
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: line {self.line}: {self.message}"


@dataclass(frozen=True)
class ParseResult:
    by_head: Mapping[int, Any]  # head line index -> payload for that declaration
    diagnostics: Sequence[Diagnostic] = ()


class Extension:
    name = ""
    version = ""
    cache_types: frozenset[tuple[str, str]] = frozenset()  # (module, class) names allowed in cache payloads
    config_keys: Mapping[str, type] = {}  # extra keys accepted in lean4-explainer.toml

    # -- parsing and indexing (worker processes) --
    def parse(self, view: SourceView) -> ParseResult | None:
        return None

    def hides_comment(self, body: str) -> bool:
        return False

    def is_described(self, payload: Any) -> bool:
        return False

    def index_file(self, path: str, declarations: Sequence[Any], diagnostics: Sequence[Diagnostic]) -> Any:
        return None

    def issues(self, path: str, summary: Any) -> Sequence[str]:
        return ()

    # -- tree analysis --
    def analyze(self, objects: Any, summaries: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        return None

    def analysis_issues(self, analysis: Any) -> Sequence[str]:
        return ()

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        """Anything that changes this extension's output must change this string; it is part of the cache key."""
        return f"{self.name}:{self.version}"

    # -- rendering --
    def css(self) -> str:
        return ""

    def declaration_title(self, decl: Any, payload: Any) -> str:
        return ""

    def declaration_blocks(self, decl: Any, payload: Any, rel: str, dirs: list[str], ctx: Any, analysis: Any) -> tuple[str, str]:
        """HTML before and after the "also declared" block."""
        return "", ""

    def pages(self, ctx: Any, analysis: Any) -> Mapping[str, str]:
        return {}

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        return ()

    def status(self, analysis: Any) -> str:
        return ""

    def summary(self, analysis: Any) -> Sequence[str]:
        return ()

    # -- command line --
    def register_cli(self, commands: argparse._SubParsersAction) -> None:
        return None

    def run_cli(self, args: argparse.Namespace) -> int | None:
        return None


_active: list[Extension] | None = None


@lru_cache(maxsize=1)
def _discover() -> tuple[Extension, ...]:
    found: dict[str, Extension] = {}
    for entry in metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            candidate = entry.load()
            extension = candidate() if isinstance(candidate, type) else candidate
        except Exception as exc:  # a broken extension must not take the core down with it
            import sys

            print(f"warning: extension {entry.name} could not be loaded: {exc}", file=sys.stderr)
            continue
        found.setdefault(extension.name or entry.name, extension)
    return tuple(found[name] for name in sorted(found))


def extensions() -> tuple[Extension, ...]:
    """Installed extensions (sorted by name), unless `activate` replaced them."""
    return tuple(_active) if _active is not None else _discover()


def activate(chosen: Sequence[Extension] | None) -> None:
    """Use exactly these extensions (tests and embedding); `None` goes back to the installed ones."""
    global _active
    _active = None if chosen is None else list(chosen)


def cache_types() -> frozenset[tuple[str, str]]:
    return frozenset(pair for extension in extensions() for pair in extension.cache_types)


def config_keys() -> dict[str, type]:
    keys: dict[str, type] = {}
    for extension in extensions():
        keys.update(extension.config_keys)
    return keys
