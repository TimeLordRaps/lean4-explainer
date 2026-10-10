"""Declarations that share a name. Identical copies are one object; differing definitions are variants."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

Location = tuple[str, int]


@dataclass(frozen=True, slots=True)
class Copy:
    rel: str
    line: int
    code: str
    header: str


@dataclass(frozen=True)
class Objects:
    locations: Mapping[str, Location]
    copies: Mapping[str, tuple[Copy, ...]]
    ambiguous: frozenset[str]
    identical: int
    issues: tuple[str, ...] = ()

    @property
    def variant(self) -> int:
        return len(self.ambiguous)


class Locations(Mapping[str, Location]):
    """Read-only view: a plain name maps to its first copy; an ambiguous name maps to each name@rel."""

    def __init__(
        self,
        first: Mapping[str, int],
        copies: Mapping[str, tuple[Copy, ...]],
        ambiguous: frozenset[str],
        copy_at: Callable[[int], Copy],
    ) -> None:
        self._first = first
        self._copies = copies
        self._ambiguous = ambiguous
        self._copy_at = copy_at

    def __getitem__(self, key: str) -> Location:
        name, sep, rel = key.partition("@")
        if sep:
            if name in self._ambiguous:
                for copy in self._copies[name]:
                    if copy.rel == rel:
                        return (copy.rel, copy.line)
            raise KeyError(key)
        if key in self._ambiguous or key not in self._first:
            raise KeyError(key)
        copy = self._copy_at(self._first[key])
        return (copy.rel, copy.line)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        name, sep, rel = key.partition("@")
        if sep:
            return name in self._ambiguous and any(copy.rel == rel for copy in self._copies[name])
        return key in self._first and key not in self._ambiguous

    def __iter__(self) -> Iterator[str]:
        for name in self._first:
            if name not in self._ambiguous:
                yield name
        for name in self._ambiguous:
            for copy in self._copies[name]:
                yield f"{name}@{copy.rel}"

    def __len__(self) -> int:
        variants = sum(len(self._copies[name]) for name in self._ambiguous)
        return len(self._first) - len(self._ambiguous) + variants


def index_objects(
    first: Mapping[str, int],
    extra: Mapping[str, list[int]],
    copy_at: Callable[[int], Copy],
) -> Objects:
    """Group packed declaration references by name; identical copies collapse, differing ones are variants."""
    copies: dict[str, tuple[Copy, ...]] = {}
    ambiguous: set[str] = set()
    issues: list[str] = []
    identical = 0
    for name, refs in extra.items():
        unique: list[Copy] = []
        for ref in refs:
            copy = copy_at(ref)
            if any(kept.rel == copy.rel for kept in unique):
                issues.append(
                    f"warning: {copy.rel}:{copy.line}: {name} is declared again in this file; keeping the first"
                )
            else:
                unique.append(copy)
        if len(unique) > 1:
            copies[name] = tuple(unique)
        if len({copy.code for copy in unique}) > 1:
            ambiguous.add(name)
        elif len(unique) > 1:
            identical += 1
    frozen = frozenset(ambiguous)
    return Objects(Locations(first, copies, frozen, copy_at), copies, frozen, identical, tuple(issues))


def build_objects(by_name: Mapping[str, list[Copy]]) -> Objects:
    """Index copies given per name; the build path uses index_objects on packed references instead."""
    first: dict[str, int] = {}
    extra: dict[str, list[int]] = {}
    flat: list[Copy] = []
    for name, found in by_name.items():
        for copy in found:
            ref = len(flat)
            flat.append(copy)
            if name in first:
                extra.setdefault(name, [first[name]]).append(ref)
            else:
                first[name] = ref
    return index_objects(first, extra, flat.__getitem__)


def plain_objects(locations: Mapping[str, Location]) -> Objects:
    return Objects(locations=dict(locations), copies={}, ambiguous=frozenset(), identical=0)


def resolve_exact(token: str, objects: Objects) -> str | None:
    """The object key that a name or name@path refers to, or None if unknown or ambiguous."""
    if "@" not in token:
        return None if token in objects.ambiguous or token not in objects.locations else token
    name, rel = token.split("@", 1)
    if name in objects.ambiguous:
        return token if token in objects.locations else None
    if name in objects.copies:
        return name if any(copy.rel == rel for copy in objects.copies[name]) else None
    located = objects.locations.get(name)
    return name if located is not None and located[0] == rel else None


def note_key(name: str, rel: str, objects: Objects) -> str:
    return f"{name}@{rel}" if name in objects.ambiguous else name


def qualified_options(name: str, objects: Objects) -> list[str]:
    return [f"{name}@{copy.rel}" for copy in objects.copies.get(name, ())]
