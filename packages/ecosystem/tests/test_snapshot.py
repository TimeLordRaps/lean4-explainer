import pytest

from lean4_explainer_ecosystem import snapshot as S


def _snap(files, limit=100):
    return S.make({rel: [S.Entry(*e) for e in found] for rel, found in files.items()}, limit)


def test_statement_and_proof_changes_are_told_apart():
    old = _snap({"A.lean": [("keep", 1, 10, 1), ("proof", 5, 20, 2), ("stmt", 9, 30, 3), ("gone", 12, 40, 4)]})
    new = _snap({"A.lean": [("keep", 1, 10, 1), ("proof", 5, 21, 2), ("stmt", 9, 31, 33), ("new", 12, 50, 5)]})

    got = S.diff(old, new)

    assert got.level == "declaration"
    assert got.proof_changed == ("proof (A.lean)",)
    assert got.statement_changed == ("stmt (A.lean)",)  # a statement change is not also reported as a proof change
    assert got.added == ("new (A.lean)",) and got.removed == ("gone (A.lean)",)


def test_a_moved_declaration_is_not_a_change():
    old = _snap({"A.lean": [("t", 1, 10, 1)]})
    new = _snap({"A.lean": [("t", 40, 10, 1)]})

    got = S.diff(old, new)

    assert not (got.added or got.removed or got.statement_changed or got.proof_changed)


def test_big_trees_fall_back_to_file_level():
    files = {"A.lean": [("a", 1, 1, 1)], "B.lean": [("b", 1, 2, 2), ("c", 2, 3, 3)]}
    small, big = _snap(files, limit=100), _snap(files, limit=2)
    assert small["level"] == "declaration" and big["level"] == "file"

    changed = _snap({**files, "B.lean": [("b", 1, 2, 2), ("c", 2, 99, 3)]}, limit=2)
    got = S.diff(big, changed)

    assert got.level == "file" and got.files_changed == ("B.lean",)


def test_mixed_levels_compare_files_only():
    files = {"A.lean": [("a", 1, 1, 1)]}
    got = S.diff(_snap(files, limit=100), _snap(files, limit=0))
    assert got.level == "mixed" and got.files_changed == ()


def test_round_trip_and_rejection_of_other_json():
    snap = _snap({"A.lean": [("a", 1, 2**63, 3)]})
    assert S.loads(S.dumps(snap)) == snap
    for bad in ("[]", '{"format": 2, "level": "file"}', '{"format": 1, "level": "x"}'):
        with pytest.raises(ValueError):
            S.loads(bad)
