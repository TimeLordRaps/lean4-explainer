"""The real Pages-only overlays stay content-bound, parseable, and outside packages."""

from pathlib import Path

from lean4_explainer_corpora.overlays import load_overlay_manifest
from lean4_explainer_corpora.registry import select
from lean4_explainer_l4del.grammar import parse_l4del
from lean4_explainer_l4del.overlay import parse_overlay


ROOT = Path(__file__).resolve().parents[3]
HOSTED = ROOT / "hosted" / "overlays"
EXPECTED = {
    "carleson": 997,
    "compfiles": 3321,
    "flt": 1280,
    "formal-conjectures": 7335,
    "mil": 74,
    "oai": 1316,
    "pfr": 523,
    "tpil": 144,
}


def test_real_hosted_overlays_are_bound_parseable_and_annotation_rich():
    selected = load_overlay_manifest(HOSTED / "manifest.json", select("all"))
    assert set(selected) == set(EXPECTED)

    counts = {}
    errors = []
    for name, hosted in selected.items():
        assert hosted.path.parent == HOSTED
        assert hosted.provenance == "ai-generated-unreviewed"
        overlay = parse_overlay(hosted.path.read_text(encoding="utf-8"), str(hosted.path))
        counts[name] = sum(len(declarations) for declarations in overlay.files.values())
        for file, declarations in overlay.files.items():
            for declaration, directives in declarations.items():
                notes = parse_l4del(directives)
                errors.extend(
                    f"{name}:{file}:{declaration}:{diagnostic.line}: {diagnostic.message}"
                    for diagnostic in notes.diagnostics
                    if diagnostic.severity == "error"
                )

    assert not errors
    assert counts == EXPECTED
    assert sum(counts.values()) == 14_990
