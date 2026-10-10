"""Search covers declarations a reader gets explanation for, so the full openai/math tree fits the Pages limit.

Every declaration is still listed on its file page; only the search index is limited.
"""

from lean4_explainer.build import build_site


def _search_shards(out):
    return "".join(path.read_text(encoding="utf-8") for path in (out / "_assets" / "search").glob("s_*.js"))


def test_search_indexes_only_described_declarations(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "A.lean").write_text(
        "/-- Documented. -/\ntheorem described_one : True := trivial\n\ntheorem bare_one : True := trivial\n",
        encoding="utf-8",
    )
    out = tmp_path / "docs"

    summary = build_site(root, out)

    assert summary.search_entries == 1
    shards = _search_shards(out)
    assert "described_one" in shards
    assert "bare_one" not in shards
    assert "bare_one" in (out / "A.lean.html").read_text(encoding="utf-8")


def test_search_includes_declarations_with_only_an_l4del_note(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "A.lean").write_text(
        "-- L4DEL: title: Titled only\ntheorem annotated_only : True := trivial\n\ntheorem plain_only : True := trivial\n",
        encoding="utf-8",
    )
    out = tmp_path / "docs"

    summary = build_site(root, out)

    assert summary.search_entries == 1
    shards = _search_shards(out)
    assert "annotated_only" in shards
    assert "plain_only" not in shards
