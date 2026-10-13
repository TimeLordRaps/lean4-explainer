"""Load hosted L4DEL overlays only through an explicit, content-bound manifest."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from lean4_explainer.errors import ExplainerError

from .registry import Corpus

PROVENANCE = frozenset(
    {
        "source-authored",
        "human-authored",
        "ai-assisted-human-reviewed",
        "ai-generated-unreviewed",
        "source-derived-unreviewed",
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
DEFAULT_CREDIT = (
    "The upstream authors and contributors retain credit for the project and mathematics. "
    "lean4-explainer only renders their pinned source and adds the separately disclosed explanation layer."
)


@dataclass(frozen=True)
class HostedOverlay:
    path: Path
    provenance: str
    reviewed_by: str = ""
    sources: tuple[tuple[str, str], ...] = ()
    credit: str = DEFAULT_CREDIT
    generation_history: tuple[str, ...] = ()
    curated_annotations: int = 0
    source_derived_annotations: int = 0

    @property
    def disclosure(self) -> str:
        if self.provenance == "ai-generated-unreviewed":
            curated_noun = "annotation" if self.curated_annotations == 1 else "annotations"
            source_noun = "annotation" if self.source_derived_annotations == 1 else "annotations"
            composition = (
                f"This overlay contains {self.curated_annotations} curated AI-written {curated_noun} and "
                f"{self.source_derived_annotations} mechanical source-derived {source_noun}. "
            )
            history = f" Retained generation history: {' '.join(self.generation_history)}" if self.generation_history else ""
            return (
                composition
                + "They have not been human-reviewed as explanations; treat them as unverified and not mathematical authority."
                + history
            )
        if self.provenance == "source-derived-unreviewed":
            noun = "annotation" if self.source_derived_annotations == 1 else "annotations"
            history = f" Retained generation history: {' '.join(self.generation_history)}" if self.generation_history else ""
            return (
                f"All {self.source_derived_annotations} {noun} in this overlay were mechanically condensed from "
                "source-authored comments and have not been human-reviewed as explanations. "
                "The pinned Lean source remains the authority."
                + history
            )
        if self.provenance == "ai-assisted-human-reviewed":
            return f"AI-assisted and human-reviewed by {self.reviewed_by}."
        if self.provenance == "human-authored":
            return f"Human-authored by {self.reviewed_by}."
        return f"Source-authored and reviewed by {self.reviewed_by}."


def load_overlay_manifest(path: Path, corpora: list[Corpus]) -> dict[str, HostedOverlay]:
    """Select overlays for ``corpora`` and fail closed on any stale or ambiguous binding."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExplainerError(f"cannot read overlay manifest {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema") != 1:
        raise ExplainerError(f"overlay manifest {path}: schema must be 1")
    entries = document.get("overlays")
    if not isinstance(entries, dict):
        raise ExplainerError(f"overlay manifest {path}: overlays must be an object")
    default_history = document.get("annotation_generation_history", [])
    if not isinstance(default_history, list) or any(
        not isinstance(note, str) or not note.strip() for note in default_history
    ):
        raise ExplainerError(
            f"overlay manifest {path}: annotation_generation_history must be a list of non-empty strings"
        )

    root = path.resolve().parent
    selected: dict[str, HostedOverlay] = {}
    for corpus in corpora:
        entry = entries.get(corpus.name)
        where = f"overlay manifest {path}: {corpus.name}"
        if not isinstance(entry, dict):
            raise ExplainerError(f"{where}: missing entry")
        if entry.get("repo") != corpus.repo:
            raise ExplainerError(f"{where}: repo does not match {corpus.repo}")
        if entry.get("commit") != corpus.commit:
            raise ExplainerError(f"{where}: commit does not match {corpus.commit}")

        named = entry.get("file")
        if not isinstance(named, str) or not named.endswith(".l4del"):
            raise ExplainerError(f"{where}: file must name an .l4del file")
        overlay = (root / named).resolve()
        try:
            overlay.relative_to(root)
        except ValueError as exc:
            raise ExplainerError(f"{where}: file must stay inside the manifest directory") from exc
        try:
            content = overlay.read_bytes()
        except OSError as exc:
            raise ExplainerError(f"{where}: cannot read {overlay}: {exc}") from exc
        expected = entry.get("sha256")
        actual = hashlib.sha256(content).hexdigest()
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected) or expected != actual:
            raise ExplainerError(f"{where}: sha256 does not match {named}")

        provenance = entry.get("provenance")
        if provenance not in PROVENANCE:
            raise ExplainerError(f"{where}: provenance must be one of {', '.join(sorted(PROVENANCE))}")
        reviewed_by = entry.get("reviewed_by", "")
        if not isinstance(reviewed_by, str):
            raise ExplainerError(f"{where}: reviewed_by must be a string")
        if provenance not in {"ai-generated-unreviewed", "source-derived-unreviewed"} and not reviewed_by.strip():
            raise ExplainerError(f"{where}: reviewed_by is required for {provenance}")
        if provenance in {"ai-generated-unreviewed", "source-derived-unreviewed"} and reviewed_by.strip():
            raise ExplainerError(f"{where}: an unreviewed overlay cannot name a reviewer")
        history_rows = entry.get("generation_history", default_history)
        if not isinstance(history_rows, list) or any(
            not isinstance(note, str) or not note.strip() for note in history_rows
        ):
            raise ExplainerError(f"{where}: generation_history must be a list of non-empty strings")
        generation_history = tuple(note.strip() for note in history_rows)
        source_rows = entry.get("sources")
        if not isinstance(source_rows, list) or not source_rows:
            raise ExplainerError(f"{where}: sources must be a non-empty list of stable reference links")
        sources: list[tuple[str, str]] = []
        for index, row in enumerate(source_rows, start=1):
            if not isinstance(row, dict) or not isinstance(row.get("label"), str) or not row["label"].strip():
                raise ExplainerError(f"{where}: sources[{index}] needs a non-empty label")
            url = row.get("url")
            parsed = urlsplit(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise ExplainerError(f"{where}: sources[{index}] must be an HTTPS URL without credentials")
            if url in {found for _, found in sources}:
                raise ExplainerError(f"{where}: source URL repeated: {url}")
            sources.append((row["label"].strip(), url))
        credit = entry.get("credit", "")
        if not isinstance(credit, str):
            raise ExplainerError(f"{where}: credit must be a string")
        curated_annotations, source_derived_annotations = _annotation_counts(overlay, provenance)
        selected[corpus.name] = HostedOverlay(
            overlay,
            provenance,
            reviewed_by.strip(),
            tuple(sources),
            credit.strip() or DEFAULT_CREDIT,
            generation_history,
            curated_annotations,
            source_derived_annotations,
        )
    return selected


def _annotation_counts(path: Path, provenance: str) -> tuple[int, int]:
    """Count the curated prefix and deterministic generated section without interpreting L4DEL."""
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = next((index for index, line in enumerate(lines) if line.startswith("# BEGIN GENERATED")), None)
    if marker is None:
        total = sum(line.startswith("@decl ") for line in lines)
        return (0, total) if provenance == "source-derived-unreviewed" else (total, 0)
    return (
        sum(line.startswith("@decl ") for line in lines[:marker]),
        sum(line.startswith("@decl ") for line in lines[marker + 1 :]),
    )
