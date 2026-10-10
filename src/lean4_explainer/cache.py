"""Incremental build state, kept beside the published site rather than inside it."""

from __future__ import annotations

from array import array
import pickle
from dataclasses import dataclass, field
from pathlib import Path

from .extensions import cache_types


@dataclass(frozen=True)
class FileIndex:
    sha: str
    declarations: int
    sorry: int
    axioms: int
    names: str  # newline-joined; Lean declaration names contain no newlines
    lines: array
    codes: array
    headers: array
    diagnostics: tuple[str, ...]
    described: str = ""  # newline-joined names of declarations with a description (comment or extension note)
    ext: tuple[tuple[str, object], ...] = ()  # (extension name, that extension's summary of the file)


@dataclass
class Cache:
    fingerprint: str
    files: dict[str, FileIndex] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)


# The only globals a cache written by save_cache refers to. The cache sits inside the source tree
# (the Lean root's parent, or the output's parent), so a repo can ship one: it must never run code.
_ALLOWED_GLOBALS = frozenset(
    {
        ("array", "array"),
        ("array", "_array_reconstructor"),
        (__name__, "Cache"),
        (__name__, "FileIndex"),
    }
)


class _CacheUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> object:
        # Extensions list the types of their own file summaries; nothing else is ever loaded.
        if (module, name) not in _ALLOWED_GLOBALS and (module, name) not in cache_types():
            raise pickle.UnpicklingError(f"cache refers to {module}.{name}")
        return super().find_class(module, name)


def load_cache(path: Path, fingerprint: str) -> Cache:
    if path.is_file():
        try:
            with path.open("rb") as handle:
                cached = _CacheUnpickler(handle).load()
        except Exception:  # any unreadable or refused cache is ignored and rebuilt
            cached = None
        if isinstance(cached, Cache) and cached.fingerprint == fingerprint:
            return cached
    return Cache(fingerprint=fingerprint)


def save_cache(path: Path, cache: Cache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(cache, handle, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)
