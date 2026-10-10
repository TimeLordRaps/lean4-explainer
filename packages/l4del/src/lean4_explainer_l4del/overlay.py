"""A sidecar overlay: L4DEL annotations kept outside the Lean sources they describe.

The sources of a project you do not own stay untouched; the explanations live in a separate file that names the file
and the declaration each one belongs to. The format is plain text:

    # a comment
    @file Foo/Bar.lean
    @decl Foo.bar_theorem
    -- L4DEL: title: Short heading
    -- L4DEL: intuition: Why it holds, in one sentence.
    @decl Foo.other
    -- L4DEL: step: First step

Directive lines are exactly the L4DEL comments you would put above the declaration. An annotation written in the source
itself wins over the overlay's for the same declaration.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lean4_explainer.errors import ExplainerError

_DIRECTIVE_RE = re.compile(r"^--[ \t]*L4DEL:(?P<rest>.*)$")


@dataclass(frozen=True)
class Overlay:
    # file -> declaration name -> ((line in the overlay file, text after "L4DEL:"), ...)
    files: dict[str, dict[str, tuple[tuple[int, str], ...]]]
    digest: str


def parse_overlay(text: str, source: str = "overlay") -> Overlay:
    files: dict[str, dict[str, list[tuple[int, str]]]] = {}
    current_file: str | None = None
    current_decl: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "@file" or line.startswith("@file "):
            current_file, current_decl = line[5:].strip(), None
            if not current_file:
                raise ExplainerError(f"{source}:{number}: @file needs a path")
            files.setdefault(current_file, {})
        elif line == "@decl" or line.startswith("@decl "):
            if current_file is None:
                raise ExplainerError(f"{source}:{number}: @decl before any @file")
            current_decl = line[5:].strip()
            if not current_decl:
                raise ExplainerError(f"{source}:{number}: @decl needs a declaration name")
            if current_decl in files[current_file]:
                raise ExplainerError(f"{source}:{number}: {current_decl} is annotated twice in {current_file}")
            files[current_file][current_decl] = []
        elif line.startswith("@"):
            raise ExplainerError(f"{source}:{number}: unknown line {line.split()[0]!r}; expected @file or @decl")
        else:
            match = _DIRECTIVE_RE.match(line)
            if match is None:
                raise ExplainerError(f"{source}:{number}: expected '-- L4DEL: key: value', got {line[:40]!r}")
            if current_decl is None:
                raise ExplainerError(f"{source}:{number}: directive before any @decl")
            files[current_file][current_decl].append((number, match["rest"]))  # type: ignore[index]
    frozen = {
        rel: {name: tuple(items) for name, items in decls.items()} for rel, decls in files.items()
    }
    return Overlay(frozen, hashlib.sha256(text.encode("utf-8")).hexdigest())


@lru_cache(maxsize=8)
def _load(path: str, mtime_ns: int, size: int) -> Overlay:
    return parse_overlay(Path(path).read_text(encoding="utf-8"), path)


def load_overlay(path: str) -> Overlay:
    """Read an overlay file (cached per process while the file is unchanged)."""
    try:
        stat = Path(path).stat()
    except OSError as exc:
        raise ExplainerError(f"cannot read overlay {path}: {exc}") from exc
    return _load(str(Path(path).resolve()), stat.st_mtime_ns, stat.st_size)
