import json
from pathlib import Path

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
            _line(kind="decl", name="a", axioms=["propext"], statement_uses=["Nat"], proof_uses=["Eq.refl"], hidden=3),
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
    assert (a.statement_uses, a.proof_uses, a.hidden) == (("Nat",), ("Eq.refl",), 3)
    assert gone.statement_uses == () and gone.hidden == 0
    assert got.errors == ("line 9: boom",)


# ---- goal states recorded from a real Lean run ------------------------------------------------------------------
# tests/data/demo-goals.lean was run through Probe.lean with Lean 4.35.0 (`lean --run Probe.lean demo-goals.lean NAMES`);
# the probe's raw JSON lines are in demo-goals.lean-4.35.0.probe.jsonl. Several info nodes sit at one position (the `by`
# block, the tactic sequence, the tactic itself, pieces of a macro expansion, rewrite rules); the step shown must be the
# tactic the author wrote, with the goals Lean reports before and after exactly that tactic.
DEMO_DECLS = [("and_swap'", 1), ("add_zero_comm", 6), ("imp_chain", 13), ("or_comm'", 18), ("has_step", 24)]


def _demo_steps():
    data = Path(__file__).with_name("data")
    out = (data / "demo-goals.lean-4.35.0.probe.jsonl").read_text(encoding="utf-8")
    return {d.name: d.steps for d in F.parse_probe(out, DEMO_DECLS).decls}


def _step(steps, tactic):
    (found,) = [s for s in steps if s.tactic == tactic]
    return found


def test_the_step_is_the_tactic_and_not_the_block_that_starts_where_it_does():
    steps = _demo_steps()
    intro = _step(steps["or_comm'"], "intro h")  # the sequence node at this position closes the proof: after = no goals
    assert intro.after == ("p q : Prop\nh : p ∨ q\n⊢ q ∨ p",)
    have = _step(steps["has_step"], "have h2 : b < b + 1 := Nat.lt_succ_self b")
    assert have.after == ("a b : Nat\nh : a ≤ b\nh2 : b < b + 1\n⊢ a < b + 1",)
    rewrite = _step(steps["add_zero_comm"], "rw [Nat.add_zero] at ih ⊢")
    assert rewrite.after == ("case succ\nk : Nat\nih : 0 + k = k\n⊢ 0 + (k + 1) = k + 1",)


def test_a_tactic_that_splits_the_goal_shows_every_goal_it_made():
    constructor = _step(_demo_steps()["and_swap'"], "constructor")
    assert [g.splitlines()[0] for g in constructor.after] == ["case left", "case right"]


def test_only_tactics_are_steps_not_rewrite_rules_binders_or_blocks():
    steps = _demo_steps()
    assert [s.tactic for s in steps["add_zero_comm"]] == ["induction n with", "rfl", "rw [Nat.add_zero] at ih ⊢", "omega"]
    assert [s.tactic for s in steps["imp_chain"]] == ["intro hpq hqr hp", "apply hqr", "exact hpq hp"]
    for name, found in steps.items():
        assert not [s.tactic for s in found if s.tactic in ("]", "Nat.add_zero", "hqr", "hp", "by", "| zero =>")], name


def test_an_intro_of_several_names_reports_the_goal_after_all_of_them():
    intro = _step(_demo_steps()["imp_chain"], "intro hpq hqr hp")
    assert intro.before == ("p q r : Prop\n⊢ (p → q) → (q → r) → p → r",)
    assert intro.after == ("p q r : Prop\nhpq : p → q\nhqr : q → r\nhp : p\n⊢ r",)


def test_without_the_tactic_flag_the_innermost_node_still_wins_when_its_text_is_shorter():
    # output of an older probe: no `isTactic`. The block's first line equals the tactic's, so only the full texts differ.
    out = "\n".join(
        [
            _line(kind="tactic", line=2, column=2, tactic="intro h\n  exact h", before=["g"], after=[]),
            _line(kind="tactic", line=2, column=2, tactic="intro h", before=["g"], after=["g2"]),
        ]
    )
    (step,) = F.parse_probe(out, [("a", 1)]).decls[0].steps
    assert (step.tactic, step.after) == ("intro h", ("g2",))


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
