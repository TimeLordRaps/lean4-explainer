import json

from lean4_explainer_lean import facts as F


def _line(**kw):
    return json.dumps(kw)


def test_classify_every_kind():
    assert F.classify(None)[0] == "unknown"
    assert F.classify(())[0] == "none"
    assert F.classify(("propext", "Quot.sound"))[0] == "standard"
    assert F.classify(("propext", "sorryAx"))[0] == "sorry"
    kind, label = F.classify(("Classical.choice", "mainStatement"))
    assert kind == "extra" and "mainStatement" in label and "Classical.choice" not in label


def test_sorry_wins_over_extra_axioms():
    assert F.classify(("sorryAx", "weird"))[0] == "sorry"


def test_steps_go_to_the_declaration_they_sit_in_and_nested_nodes_collapse():
    out = "\n".join(
        [
            _line(kind="tactic", line=2, column=2, tactic="induction n with\n | zero => rfl", before=["g"], after=[]),
            _line(kind="tactic", line=2, column=2, tactic="induction n with", before=["g"], after=[]),
            _line(kind="tactic", line=1, column=40, tactic="by", before=["g"], after=[]),
            _line(kind="tactic", line=7, column=2, tactic="sorry", before=["h"], after=[]),
            _line(kind="decl", name="a", axioms=["propext"]),
            _line(kind="decl", name="b", axioms=["sorryAx"]),
            _line(kind="decl", name="gone", axioms=None),
            _line(kind="message", severity="error", line=9, text="boom\nmore"),
            "not json at all",
        ]
    )

    got = F.parse_probe(out, [("a", 1), ("b", 6), ("gone", 9)])

    a, b, gone = got.decls
    assert [s.tactic for s in a.steps] == ["induction n with"]  # innermost node, and `by` is dropped
    assert [s.tactic for s in b.steps] == ["sorry"]
    assert a.axioms == ("propext",) and gone.axioms is None
    assert got.errors == ("line 9: boom",)


def test_json_round_trip_keeps_everything():
    original = F.parse_probe(
        _line(kind="tactic", line=1, column=0, tactic="rfl", before=["⊢ 1 = 1"], after=[]) + "\n"
        + _line(kind="decl", name="a", axioms=[]),
        [("a", 1)],
    )
    assert F.from_json(F.to_json(original)) == original


def test_long_goals_are_clipped():
    out = _line(kind="tactic", line=1, column=0, tactic="simp", before=["x" * 5000], after=[])
    step = F.parse_probe(out, [("a", 1)]).decls[0].steps[0]
    assert len(step.before[0]) < 1600 and step.before[0].endswith("(truncated)")
