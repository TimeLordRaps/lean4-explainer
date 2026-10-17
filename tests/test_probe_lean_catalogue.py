from pathlib import Path

import pytest

from scripts.probe_lean_catalogue import complete_target_files, group_targets, output_path


def test_catalogue_targets_are_grouped_without_losing_multiple_results_in_one_file():
    assert group_targets(("A/Main.lean\tA.first", "A/Main.lean\tA.second", "B.lean\tB.fact")) == {
        "A/Main.lean": ("A.first", "A.second"),
        "B.lean": ("B.fact",),
    }


def test_malformed_encoded_catalogue_target_is_rejected():
    with pytest.raises(ValueError, match="invalid encoded catalogue target"):
        group_targets(("A.lean",))


def test_output_path_matches_lake_library_layout(tmp_path):
    assert output_path(tmp_path, "OAI/Topic/Main.lean") == tmp_path / Path("OAI/Topic/Main.olean")


def test_probe_selection_requires_the_complete_internal_dependency_closure(tmp_path):
    root = tmp_path / "source"
    output = tmp_path / "build"
    (root / "A").mkdir(parents=True)
    (root / "A" / "Leaf.lean").write_text("theorem leaf : True := trivial\n", encoding="utf-8")
    (root / "A" / "Main.lean").write_text("import A.Leaf\ntheorem main : True := trivial\n", encoding="utf-8")
    (output / "A").mkdir(parents=True)
    (output / "A" / "Main.olean").write_bytes(b"stale target")

    assert complete_target_files(root, output, ("A/Main.lean",)) == []
    (output / "A" / "Leaf.olean").write_bytes(b"built")
    assert complete_target_files(root, output, ("A/Main.lean",)) == ["A/Main.lean"]
