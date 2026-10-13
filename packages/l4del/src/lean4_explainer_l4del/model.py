"""Types this extension keeps in the incremental cache. Listed in `cache_types` so the cache loader accepts them."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    name: str
    rel: str
    line: int
    title: str | None
    prereqs: tuple[str, ...]
    see: tuple[str, ...]
    terms: tuple[tuple[str, str], ...]
    acronyms: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FileSummary:
    notes: tuple[Note, ...] = ()
    issues: tuple[str, ...] = ()
    annotated: int = 0
    flagged: int = 0
    unannotated: int = 0
