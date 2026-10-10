"""A snapshot of a build, and the difference between two of them.

A snapshot records, per declaration, a whitespace-insensitive digest of its header (the statement) and of its whole
text (statement and proof). The site publishes its snapshot as `snapshot.json`, so the next build can compare itself
with the last deployed site: download that file and pass it as `compare_to`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

FORMAT = 1


@dataclass(frozen=True)
class Entry:
    name: str
    line: int
    code: int  # digest of the declaration's text
    header: int  # digest of its header, the statement


def make(files: Mapping[str, Sequence[Entry]], limit: int) -> dict:
    """Declaration-level while the tree has at most `limit` declarations, else file-level."""
    total = sum(len(v) for v in files.values())
    if total <= limit:
        return {
            "format": FORMAT,
            "level": "declaration",
            "files": {rel: [[e.name, e.line, str(e.code), str(e.header)] for e in found] for rel, found in files.items()},
        }
    return {
        "format": FORMAT,
        "level": "file",
        "files": {rel: [str(_fold(found)), len(found)] for rel, found in files.items()},
    }


def _fold(found: Sequence[Entry]) -> int:
    value = 0
    for e in found:
        value = (value * 1000003 + e.code + 31 * e.header) % (1 << 64)
    return value


def dumps(snapshot: dict) -> str:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))


def loads(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("level") not in ("declaration", "file"):
        raise ValueError("not a lean4-explainer snapshot (format 1)")
    return data


@dataclass(frozen=True)
class Changes:
    level: str  # "declaration" | "file" | "mixed" (the two snapshots differ in level; only file-level facts are compared)
    added: tuple[str, ...]
    removed: tuple[str, ...]
    statement_changed: tuple[str, ...]
    proof_changed: tuple[str, ...]  # same statement, different text
    files_changed: tuple[str, ...] = ()  # file level only


def diff(old: dict, new: dict) -> Changes:
    if old["level"] == "declaration" and new["level"] == "declaration":
        before = {(rel, e[0]): e for rel, found in old["files"].items() for e in found}
        after = {(rel, e[0]): e for rel, found in new["files"].items() for e in found}
        added = sorted(f"{name} ({rel})" for (rel, name) in after.keys() - before.keys())
        removed = sorted(f"{name} ({rel})" for (rel, name) in before.keys() - after.keys())
        statement, proof = [], []
        for key in sorted(after.keys() & before.keys()):
            was, now = before[key], after[key]
            if was[3] != now[3]:
                statement.append(f"{key[1]} ({key[0]})")
            elif was[2] != now[2]:
                proof.append(f"{key[1]} ({key[0]})")
        return Changes("declaration", tuple(added), tuple(removed), tuple(statement), tuple(proof))
    old_files = {rel: _file_digest(old, rel) for rel in old["files"]}
    new_files = {rel: _file_digest(new, rel) for rel in new["files"]}
    changed = sorted(rel for rel in old_files.keys() & new_files.keys() if old_files[rel] != new_files[rel])
    return Changes(
        "file" if old["level"] == new["level"] == "file" else "mixed",
        tuple(sorted(new_files.keys() - old_files.keys())),
        tuple(sorted(old_files.keys() - new_files.keys())),
        (),
        (),
        tuple(changed),
    )


def _file_digest(snapshot: dict, rel: str) -> int:
    found = snapshot["files"][rel]
    if snapshot["level"] == "file":
        return int(found[0])
    return _fold([Entry(e[0], e[1], int(e[2]), int(e[3])) for e in found])
