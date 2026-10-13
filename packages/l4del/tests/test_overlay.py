"""A sidecar overlay annotates sources that stay untouched."""

import pytest

from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer.errors import ExplainerError
from lean4_explainer_l4del.overlay import parse_overlay

SOURCE = """\
namespace Demo

/-- Doc comment from upstream. -/
theorem first : True := trivial

theorem second : True := trivial

-- L4DEL: title: Written in the source
theorem inline : True := trivial

end Demo
"""

OVERLAY = """\
# explanations for Demo.lean
@file Demo.lean
@decl Demo.first
-- L4DEL: title: First, explained
-- L4DEL: intuition: Trivial things are true.
-- L4DEL: source: Logic reference = https://example.org/logic
@decl Demo.second
-- L4DEL: step: Apply trivial.
@decl Demo.inline
-- L4DEL: title: Overlay title that must lose
@decl Demo.missing
-- L4DEL: title: Not in the file
"""


def _site(tmp_path, overlay_text, name="a", jobs=1, source=SOURCE):
    root = tmp_path / name / "src"
    root.mkdir(parents=True, exist_ok=True)
    (root / "Demo.lean").write_text(source, encoding="utf-8")
    overlay = tmp_path / name / "demo.l4del"
    overlay.write_text(overlay_text, encoding="utf-8")
    config = Config(options=(("overlay", str(overlay)),))
    out = tmp_path / name / "out"
    summary = build_site(root, out, config, tmp_path / name / "idx", jobs=jobs)
    return summary, out, root


def test_overlay_text_is_parsed_into_files_and_declarations():
    got = parse_overlay(OVERLAY)

    assert list(got.files) == ["Demo.lean"]
    assert list(got.files["Demo.lean"]) == ["Demo.first", "Demo.second", "Demo.inline", "Demo.missing"]
    assert got.files["Demo.lean"]["Demo.first"][0] == (4, " title: First, explained")


@pytest.mark.parametrize(
    "text, message",
    [
        ("@decl A\n", "before any @file"),
        ("@file F.lean\n-- L4DEL: title: x\n", "before any @decl"),
        ("@file F.lean\n@decl A\n@decl A\n", "annotated twice"),
        ("@file F.lean\n@decl A\nnot a directive\n", "expected '-- L4DEL"),
        ("@file F.lean\n@thing A\n", "unknown line"),
        ("@file \n", "needs a path"),
    ],
)
def test_malformed_overlays_are_rejected_with_a_line_number(text, message):
    with pytest.raises(ExplainerError, match=message) as caught:
        parse_overlay(text, "x.l4del")
    assert "x.l4del:" in str(caught.value)


def test_overlay_annotations_reach_the_page_and_the_source_is_untouched(tmp_path):
    summary, out, root = _site(tmp_path, OVERLAY)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert "First, explained" in page and "Trivial things are true." in page
    assert '<strong>Sources and attribution:</strong>' in page and 'href="https://example.org/logic"' in page
    assert "Apply trivial." in page
    assert (root / "Demo.lean").read_text(encoding="utf-8") == SOURCE  # the sidecar never writes upstream


def test_linked_quote_renders_as_a_citation(tmp_path):
    overlay = """@file Demo.lean
@decl Demo.first
-- L4DEL: source: Original note = https://example.org/note
-- L4DEL: quote: Original note = Exact words from the note.
"""
    _, out, _ = _site(tmp_path, overlay)
    rendered = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert '<blockquote class="l4del-quote" cite="https://example.org/note">' in rendered
    assert '>Original note</a>' in rendered


def test_overlay_adds_the_configured_pinned_source_beside_the_explanation(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "Demo.lean").write_text(SOURCE, encoding="utf-8")
    overlay = tmp_path / "demo.l4del"
    overlay.write_text(OVERLAY, encoding="utf-8")
    config = Config(
        source_url="https://github.com/example/repo/blob/{ref}/{path}#L{line}",
        source_ref="0123456789abcdef",
        options=(
            ("overlay", str(overlay)),
            ("overlay_sources", '[["Pinned project documentation","https://example.org/docs/abc"]]'),
        ),
    )

    build_site(root, tmp_path / "out", config, tmp_path / "idx")

    page = (tmp_path / "out" / "Demo.lean.html").read_text(encoding="utf-8")
    assert "Pinned Lean source (0123456789ab)" in page
    assert "https://github.com/example/repo/blob/0123456789abcdef/Demo.lean#L4" in page
    assert "Pinned project documentation" in page and "https://example.org/docs/abc" in page


def test_unreviewed_overlay_discloses_its_provenance_beside_the_annotation(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "Demo.lean").write_text(SOURCE, encoding="utf-8")
    overlay = tmp_path / "demo.l4del"
    overlay.write_text(OVERLAY, encoding="utf-8")
    config = Config(
        options=(
            ("overlay", str(overlay)),
            ("overlay_provenance", "ai-generated-unreviewed"),
        )
    )

    build_site(root, tmp_path / "out", config, tmp_path / "idx")

    page = (tmp_path / "out" / "Demo.lean.html").read_text(encoding="utf-8")
    assert "AI-generated and not human-reviewed" in page
    assert "not mathematical authority" in page


def test_a_source_annotation_wins_over_the_overlay(tmp_path):
    _, out, _ = _site(tmp_path, OVERLAY)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert "Written in the source" in page and "Overlay title that must lose" not in page


def test_an_overlay_entry_for_a_missing_declaration_is_a_warning(tmp_path):
    summary, _, _ = _site(tmp_path, OVERLAY)

    assert any("no declaration named Demo.missing" in w for w in summary.warnings)


def test_declaration_lines_do_not_shift(tmp_path):
    _, with_overlay, _ = _site(tmp_path, OVERLAY, "a")
    _, without, _ = _site(tmp_path, "@file Demo.lean\n", "b")

    for page in (with_overlay, without):
        text = (page / "Demo.lean.html").read_text(encoding="utf-8")
        assert "id=L4" in text and "id=L6" in text and "id=L9" in text


def test_changing_the_overlay_rebuilds_with_the_new_text(tmp_path):
    summary, out, root = _site(tmp_path, OVERLAY)
    overlay = tmp_path / "a" / "demo.l4del"
    overlay.write_text(OVERLAY.replace("First, explained", "First, explained again"), encoding="utf-8")

    build_site(root, out, Config(options=(("overlay", str(overlay)),)), tmp_path / "a" / "idx")

    assert "First, explained again" in (out / "Demo.lean.html").read_text(encoding="utf-8")


def test_changing_overlay_review_provenance_rebuilds_the_disclosure(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "Demo.lean").write_text(SOURCE, encoding="utf-8")
    overlay = tmp_path / "demo.l4del"
    overlay.write_text(OVERLAY, encoding="utf-8")
    out = tmp_path / "out"
    cache = tmp_path / "idx"
    first = Config(
        options=(
            ("overlay", str(overlay)),
            ("overlay_provenance", "ai-generated-unreviewed"),
        )
    )
    reviewed = Config(
        options=(
            ("overlay", str(overlay)),
            ("overlay_provenance", "ai-assisted-human-reviewed"),
            ("overlay_disclosure", "AI-assisted and human-reviewed by Ada."),
        )
    )

    build_site(root, out, first, cache)
    assert "not human-reviewed" in (out / "Demo.lean.html").read_text(encoding="utf-8")
    build_site(root, out, reviewed, cache)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert "human-reviewed by Ada" in page and "not human-reviewed" not in page


def test_workers_apply_the_overlay_too(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    for number in range(4):
        (root / f"F{number}.lean").write_text(SOURCE.replace("namespace Demo", f"namespace D{number}"), encoding="utf-8")
    overlay = tmp_path / "o.l4del"
    overlay.write_text("".join(f"@file F{n}.lean\n@decl D{n}.first\n-- L4DEL: title: worker {n}\n" for n in range(4)), encoding="utf-8")

    build_site(root, tmp_path / "out", Config(options=(("overlay", str(overlay)),)), tmp_path / "idx", jobs=2)

    for n in range(4):
        assert f"worker {n}" in (tmp_path / "out" / f"F{n}.lean.html").read_text(encoding="utf-8")
