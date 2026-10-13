"""Name resolution, learning-path ordering, glossary, and link checks across all files."""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lean4_explainer.objects import Location, Objects, note_key, qualified_options, resolve, resolve_exact

from .model import Note


@dataclass(frozen=True)
class PathStep:
    name: str
    title: str | None
    location: Location
    prereqs: tuple[str, ...]


def build_learning_path(notes: Sequence[Note], objects: Objects) -> tuple[list[PathStep], list[str]]:
    locations = objects.locations
    issues: list[str] = []
    members = [note for note in notes if note.title or note.prereqs]
    info: dict[str, Note | None] = {note_key(note.name, note.rel, objects): note for note in members}
    resolved: dict[str, list[str]] = {}
    dependents: dict[str, set[str]] = {}
    for note in members:
        key = note_key(note.name, note.rel, objects)
        for token in note.prereqs:
            target = resolve_exact(token, objects)
            if target is None:
                continue
            if target == key:
                issues.append(f"error: {note.rel}:{note.line}: {key} lists itself as a prerequisite")
                continue
            info.setdefault(target, None)
            resolved.setdefault(key, []).append(target)
            dependents.setdefault(target, set()).add(key)

    indegree = dict.fromkeys(info, 0)
    for group in dependents.values():
        for dependent in group:
            indegree[dependent] += 1

    def order(name: str) -> tuple[str, int, str]:
        rel, line = locations[name]
        return (rel, line, name)

    ready = [order(name) for name, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        name = heapq.heappop(ready)[2]
        ordered.append(name)
        for dependent in sorted(dependents.get(name, ())):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, order(dependent))

    if len(ordered) < len(indegree):
        placed = set(ordered)
        stuck = sorted((name for name in indegree if name not in placed), key=order)
        issues.append(f"error: prerequisite cycle among {len(stuck)} declarations; they are listed last")
        ordered.extend(stuck)

    steps = [
        PathStep(
            name,
            info[name].title if info[name] else None,
            locations[name],
            tuple(resolved.get(name, ())),
        )
        for name in ordered
    ]
    return steps, issues


def build_glossary(notes: Sequence[Note]) -> tuple[dict[str, tuple[str, str, Location]], list[str]]:
    terms: dict[str, tuple[str, str, Location]] = {}
    issues: list[str] = []
    for note in notes:
        for word, definition in note.terms:
            if word in terms:
                issues.append(
                    f"error: {note.rel}:{note.line}: term '{word}' is already defined; keeping the first"
                )
            else:
                terms[word] = (definition, note.name, (note.rel, note.line))
    return terms, issues


def build_acronyms(notes: Sequence[Note]) -> tuple[dict[str, tuple[str, str, Location]], list[str]]:
    """One unambiguous expansion per acronym across a project."""
    found: dict[str, tuple[str, str, Location]] = {}
    issues: list[str] = []
    for note in notes:
        for short, expansion in note.acronyms:
            kept = found.get(short)
            if kept is not None and kept[0] != expansion:
                issues.append(
                    f"error: {note.rel}:{note.line}: acronym '{short}' is already expanded as '{kept[0]}'; keeping the first"
                )
            else:
                found.setdefault(short, (expansion, note.name, (note.rel, note.line)))
    return found, issues


def merge_notes(notes: Sequence[Note], objects: Objects) -> tuple[list[Note], list[str]]:
    """One note per object. Identical copies may repeat an annotation; differing ones conflict."""
    merged: dict[str, Note] = {}
    issues: list[str] = []
    for note in notes:
        kept = merged.setdefault(note_key(note.name, note.rel, objects), note)
        if kept is not note and _content(kept) != _content(note):
            issues.append(
                f"error: {note.rel}:{note.line}: L4DEL for {note.name} differs from its copy at "
                f"{kept.rel}:{kept.line}; make the identical copies' annotations match"
            )
    return list(merged.values()), issues


def _content(note: Note) -> tuple[object, ...]:
    return (note.title, note.prereqs, note.see, note.terms, note.acronyms)


def unresolved_links(notes: Sequence[Note], objects: Objects) -> list[str]:
    issues: list[str] = []
    for note in notes:
        for token in (*note.prereqs, *note.see):
            if "@" not in token and token in objects.ambiguous:
                options = ", ".join(qualified_options(token, objects))
                issues.append(f"error: {note.rel}:{note.line}: reference {token} is ambiguous; qualify it as {options}")
            elif resolve_exact(token, objects) is None:
                issues.append(f"warning: {note.rel}:{note.line}: unresolved reference {token}")
    return issues


def build_links(notes: Sequence[Note], objects: Objects) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Resolved `prereq` edges (declaration -> what it builds on) and `see` edges (both directions), by object key."""
    prereqs: dict[str, list[str]] = {}
    sees: dict[str, list[str]] = {}
    for note in notes:
        key = note_key(note.name, note.rel, objects)
        for token in note.prereqs:
            target = resolve_exact(token, objects)
            if target is not None and target != key and target not in prereqs.setdefault(key, []):
                prereqs[key].append(target)
        for token in note.see:
            target = resolve_exact(token, objects)
            if target is not None and target != key:
                for a, b in ((key, target), (target, key)):
                    if b not in sees.setdefault(a, []):
                        sees[a].append(b)
    return (
        {k: tuple(v) for k, v in prereqs.items()},
        {k: tuple(v) for k, v in sees.items()},
    )
