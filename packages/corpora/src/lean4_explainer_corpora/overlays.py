"""Load hosted L4DEL overlays only through an explicit, content-bound manifest."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from lean4_explainer.errors import ExplainerError

from .registry import Corpus

PROVENANCE = frozenset(
    {
        "source-authored",
        "human-authored",
        "ai-assisted-human-reviewed",
        "ai-generated-unreviewed",
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class HostedOverlay:
    path: Path
    provenance: str
    reviewed_by: str = ""

    @property
    def disclosure(self) -> str:
        if self.provenance == "ai-generated-unreviewed":
            return (
                "AI-generated and not human-reviewed. Treat this explanatory draft as unverified "
                "and not mathematical authority."
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
        if provenance != "ai-generated-unreviewed" and not reviewed_by.strip():
            raise ExplainerError(f"{where}: reviewed_by is required for {provenance}")
        if provenance == "ai-generated-unreviewed" and reviewed_by.strip():
            raise ExplainerError(f"{where}: an unreviewed overlay cannot name a reviewer")
        selected[corpus.name] = HostedOverlay(overlay, provenance, reviewed_by.strip())
    return selected
