"""Placeholder L4DEL templates for declarations that do not yet have a valid annotation."""

from __future__ import annotations

import re
from collections.abc import Mapping

from lean4_explainer.objects import Location, resolve
from lean4_explainer.scan import Declaration, LeanFile

from .grammar import PLACEHOLDER, L4Notes

_IDENT_RE = re.compile(r"[^\W\d][\w'.!?]*")
_MAX_CANDIDATES = 5


def notes_of(decl: Declaration) -> L4Notes:
    return decl.ext.get("l4del") or L4Notes()


def annotation_state(decl: Declaration) -> str:
    if "(" in decl.name:
        return "anonymous"
    notes = notes_of(decl)
    if any(d.severity == "error" for d in notes.diagnostics):
        return "flagged"
    if any(d.message.startswith("placeholder") for d in notes.diagnostics):
        return "flagged"
    if notes.is_empty:
        return "unannotated"
    return "annotated"


def placeholder_block(
    decl: Declaration,
    locations: Mapping[str, Location],
    ambiguous: frozenset[str] = frozenset(),
) -> str:
    scope = decl.name.split(".")[:-1]
    candidates: list[str] = []
    for token in _IDENT_RE.findall(decl.statement):
        target = resolve(token, scope, locations, ambiguous)
        if target is not None and target != decl.name and target not in candidates:
            candidates.append(target)
            if len(candidates) == _MAX_CANDIDATES:
                break
    prereq = ", ".join(candidates) if candidates else f"{PLACEHOLDER}fully_qualified_name"
    return "\n".join(
        [
            f"-- L4DEL: title: {PLACEHOLDER}short_result_name",
            f"-- L4DEL: intuition: {PLACEHOLDER}one_plain_sentence_why_it_holds",
            f"-- L4DEL: step: {PLACEHOLDER}first_proof_step",
            f"-- L4DEL: prereq: {prereq}",
        ]
    )


def annotation_report(
    lean_file: LeanFile,
    locations: Mapping[str, Location],
    ambiguous: frozenset[str] = frozenset(),
) -> str:
    blocks: list[str] = []
    for decl in lean_file.declarations:
        state = annotation_state(decl)
        if state == "unannotated":
            header = f"{lean_file.path}:{decl.line} {decl.name} (no L4DEL yet)"
        elif state == "flagged":
            header = f"{lean_file.path}:{decl.line} {decl.name} (flagged: fix or remove its L4DEL lines first)"
        else:
            continue
        blocks.append(f"{header}\n{placeholder_block(decl, locations, ambiguous)}")
    if not blocks:
        return f"{lean_file.path}: every named declaration has a valid L4DEL annotation"
    return "\n\n".join(blocks)
