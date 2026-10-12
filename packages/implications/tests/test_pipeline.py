"""The discovery pipeline against a small corpus in Lean's core library (tests/lean/ImplicationsFixture.lean).

Each regression case is something the pipeline must refuse: a valid proof of the wrong statement, an assumption the
contract does not record, another domain or quantifier order, sorry, an axiom of its own, a proof through the target
or an alias of it, a source it names but does not use, a stale record, a statement that holds without its sources,
and a timeout read as a refutation. Two cases must succeed: a specialization and a multi-source derivation.

The Lean tests need `lean` (the toolchain openai/math pins, v4.34.1); they are skipped without it.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from lean4_explainer_implications import edges as E
from lean4_explainer_implications.pipeline import attempts as A
from lean4_explainer_implications.pipeline import candidates as C
from lean4_explainer_implications.pipeline import catalogue as K
from lean4_explainer_implications.pipeline import contracts as T
from lean4_explainer_implications.pipeline import extract as X
from lean4_explainer_implications.pipeline import run as S
from lean4_explainer_implications.pipeline import workspace as W
from lean4_explainer_implications.pipeline import __main__ as CLI

HERE = Path(__file__).resolve().parent / "lean"
LEAN = shutil.which("lean")
needs_lean = pytest.mark.skipif(LEAN is None, reason="needs lean on PATH")
REV = "abcdef1234567890abcdef1234567890abcdef12"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """The fixture built and extracted once: a workspace, its run directory and its declarations."""
    if LEAN is None:
        pytest.skip("needs lean on PATH")
    root = tmp_path_factory.mktemp("pipeline")
    ws = W.Workspace(root / "ws", HERE, ("ImplicationsFixture",))
    ws.root.mkdir()
    record = W.build(ws, ["ImplicationsFixture"], jobs=1, lean_commit_gb=0, commit_reserve_gb=0, log=print)
    assert record.counts() == {"built": 1}, record.to_json()
    run = root / "run"
    summary = S.extract_layer(ws, X.Identity("test/fixture", REV, ""), ["ImplicationsFixture"], run, "fixture", log=print, commit_gb=0)
    assert summary["modules_extracted"] == 1 and not summary["modules_failed"], summary
    assert summary["policy"] == A.policy()  # each layer records the rule set it was extracted under
    decls = {d["name"]: d for d in S.read_declarations(run, "fixture")}
    return ws, run, decls


def _attempt(corpus, *attempts: A.Attempt, budget: A.Budget = A.Budget(ms=10000)) -> dict[str, dict]:
    ws, run, decls = corpus
    for a in attempts:
        a.meta.update(source_keys=[decls[s]["key"] for s in a.sources], target_key=decls[a.target]["key"] if a.target else "")
    results, stats = A.run_attempts(ws, list(attempts), budget, run / "attempts", A.Cache(run / "cache.jsonl"), log=print, commit_gb=0)
    assert stats.attempts == len(attempts)
    return {r["id"]: r for r in results}


def _one(corpus, rule, sources, target="", instantiate=True, **kw) -> dict:
    a = A.Attempt(rule, tuple(sources), target, ("ImplicationsFixture",), instantiate)
    return _attempt(corpus, a, **kw)[a.id]


# ---- extraction ----


@needs_lean
def test_extraction_reads_types_binders_and_proof_terms(corpus):
    _, run, decls = corpus
    d = decls["Fx.fine_of_two"]
    assert d["kind"] == "theorem" and d["prop"] and d["module"] == "ImplicationsFixture"
    assert d["key"] == f"test/fixture@{REV[:12]}:ImplicationsFixture:Fx.fine_of_two"
    assert [(b["name"], b["info"], b["prop"]) for b in d["binders"]] == [("n", "explicit", False), ("h", "explicit", True)]
    assert set(d["proof_uses"]) >= {"Fx.fine_of_good", "Fx.good_of_two"}  # read from the elaborated proof term
    assert d["norm"]["conclusion_head"] == "Fx.Fine" and d["norm"]["hyp_heads"] == ["LE.le"]
    assert d["axioms"] == ["propext", "Quot.sound"] and d["sorry"] is False  # omega, in fine_of_good, uses both
    # a corpus definition at the head is unfolded for the search: `size n` is `n * n + 1`, still an order statement
    assert decls["Fx.size_pos"]["norm"]["conclusion_head"] == "LE.le"
    assert decls["Fx.exists_fine"]["norm"]["exists"]["witness_type"] == "Nat"


@needs_lean
def test_extraction_records_which_declarations_are_a_structure_fields_projection(corpus):
    # TD-16: a composition through a structure's field applies a theorem to that structure's objects; the catalogue
    # can group it only if extraction says, from Lean's environment, that the source is a projection
    _, _, decls = corpus
    assert decls["Fx.Fine.pos"]["projection"] == {"structure": "Fx.Fine", "field": "pos", "index": 0, "class": False}
    assert decls["Fx.Good.big"]["projection"]["structure"] == "Fx.Good"
    assert decls["Fx.fine_of_two"]["projection"] is None and decls["Fx.size"]["projection"] is None


# ---- attempts: what must succeed ----


@needs_lean
def test_a_specialization_is_checked_and_applied_to_the_released_theorem(corpus):
    r = _one(corpus, "target", ["Fx.fine_of_two"], "Fx.fine_of_good_five")
    assert r["status"] == "checked-instantiated", r
    assert r["used"] == [True] and r["statement"] == "Fx.Good 5 → Fx.Fine 5"
    assert r["steps"][0]["step"] == "apply" and r["steps"][0]["substitutions"] == [{"variable": "n", "value": "5"}]
    assert any(s["step"] == "discharge" for s in r["steps"])  # 2 ≤ 5, by a discharger, recorded
    assert "specialization" in K.rules_used(r) and "premise discharge" in K.rules_used(r)


@needs_lean
def test_a_derivation_from_two_sources_uses_both_and_records_them(corpus):
    r = _one(corpus, "target", ["Fx.good_of_two", "Fx.fine_of_good"], "Fx.fine_of_two")
    assert r["status"] == "checked-instantiated", r
    assert r["used"] == [True, True]
    assert r["derived"].startswith("(∀ (n : Nat), 2 ≤ n → Fx.Good n) → (∀ (n : Nat), Fx.Good n → Fx.Fine n) →")
    assert set(r["axioms"]) <= {"propext", "Quot.sound", "Classical.choice"}


@needs_lean
def test_a_composition_derives_a_statement_and_witnesses_carry_over(corpus):
    ws, run, decls = corpus
    comp = A.Attempt("compose", ("Fx.fine_double", "Fx.Fine.pos"), "", ("ImplicationsFixture",), True)
    wit = A.Attempt("target", ("Fx.exists_big_fine",), "Fx.exists_fine", ("ImplicationsFixture",), True)
    got = _attempt(corpus, comp, wit)
    assert got[comp.id]["status"] == "checked-instantiated" and got[comp.id]["statement"] == "∀ (n : Nat), Fx.Fine (2 * n) → 0 < n + n"
    assert got[wit.id]["status"] == "checked-instantiated"
    assert [s["step"] for s in got[wit.id]["steps"]][0] == "witness transport"


@needs_lean
def test_a_universe_the_derivation_leaves_free_becomes_a_parameter_of_what_is_derived(corpus):
    # TD-15, found 2026-10-10 on openai/math: 65 compositions and 2 derivations ended "universe levels are not
    # determined", because a source's universe that nothing fixed stayed a metavariable
    r = _one(corpus, "compose", ["Fx.fine_double", "Fx.good_succ_of_fine"])
    assert r["status"] == "checked-instantiated", r
    assert r["statement"] == "∀ (n : Nat), Fx.Fine (2 * n) → ∀ {α : Type u_1} (_a : α), Fx.Good (n + n + 1)", r["statement"]
    assert r["used"] == [True, True]


@needs_lean
def test_a_premise_about_a_variable_the_composition_leaves_free_is_checked_where_it_is_in_scope(corpus):
    # TD-15: a premise of the second source that mentions one of its variables left free was checked in the context
    # of its own metavariable, which does not hold that variable: tactics either failed or stopped with "unknown
    # free variable" (20 compositions on openai/math)
    r = _one(corpus, "compose", ["Fx.fine_double", "Fx.fine_add_of_pos"])
    assert r["status"] == "checked-instantiated", r
    assert r["statement"] == "∀ (n : Nat), Fx.Fine (2 * n) → ∀ (m : Nat), Fx.Fine (n + n + m)", r["statement"]
    assert any(s["step"] == "discharge" and s["goal"] == "0 < m + 1" for s in r["steps"]), r["steps"]


@needs_lean
def test_a_composition_records_what_links_its_sources(corpus):
    # found 2026-10-11 on openai/math: 9 of the 14 connections are linked only by `0 < x`, a quantity's positivity;
    # the catalogue should say so from what Lean read, not from the printed text
    pos = _one(corpus, "compose", ["Fx.Fine.pos", "Fx.good_succ_of_pos"])
    assert pos["status"] == "checked-instantiated", pos
    supply = [s for s in pos["steps"] if s["step"] == "supply"][0]
    assert supply["hypothesis"] == "0 < n" and supply["hypothesis_head"] == "LT.lt" and supply["positivity"] is True
    other = _one(corpus, "compose", ["Fx.fine_double", "Fx.good_succ_of_fine"])
    supply = [s for s in other["steps"] if s["step"] == "supply"][0]
    assert supply["hypothesis_head"] == "Fx.Fine" and supply["positivity"] is False


@needs_lean
def test_bound_transfer_is_proof_producing_arithmetic_on_a_source_bound(corpus):
    r = _one(corpus, "target", ["Fx.size_ge"], "Fx.size_pos")
    assert r["status"] == "checked-instantiated", r
    step = next(s for s in r["steps"] if s["step"] == "bound transfer")
    assert step["closed by"] in ("linarith", "nlinarith", "omega") and step["bound"] == "n + 1 ≤ Fx.size n"


# ---- attempts: what must be refused ----


@needs_lean
def test_an_unused_source_is_not_a_composition(corpus):
    r = _one(corpus, "target", ["Fx.size_ge", "Fx.fine_of_two"], "Fx.fine_of_good_five")
    assert r["status"] == "rejected" and "does not use" in r["reason"] and r["used"] == [False, True]


@needs_lean
def test_a_statement_that_holds_without_its_sources_is_not_counted(corpus):
    r = _one(corpus, "compose", ["Fx.good_of_two", "Fx.Good.big"])  # gives 2 ≤ n → 2 ≤ n
    assert r["status"] == "rejected" and "holds without the sources" in r["reason"], r
    r = _one(corpus, "compose", ["Fx.fine_of_two", "Fx.Fine.pos"])  # gives 2 ≤ n → 0 < n, which omega proves alone
    assert r["status"] == "rejected" and "(by omega)" in r["reason"], r


@needs_lean
def test_a_source_is_not_one_of_the_statements_own_hypotheses(corpus):
    # found 2026-10-10 on openai/math (Ostmann.main → Ostmann.inverseGoldbach): the check that a statement holds
    # without its sources ran with the sources in scope, so `assumption` closed the goal with the source itself and a
    # valid derivation was rejected as saying nothing
    r = _one(corpus, "target", ["Fx.fine_of_two"], "Fx.fine_from_two", instantiate=False)
    assert r["status"] == "checked", r
    assert r["used"] == [True]


@needs_lean
def test_a_source_whose_released_proof_uses_the_target_is_circular(corpus):
    r = _one(corpus, "target", ["Fx.fine_and_true"], "Fx.fine_of_two")
    assert r["status"] == "instantiation-circular", r  # the derivation holds; applied to the released theorem it is circular
    assert r["reaches"][-2:] == ["Fx.fine_and_true", "Fx.fine_of_two"]


@needs_lean
def test_the_target_as_its_own_source_is_refused(corpus):
    r = _one(corpus, "target", ["Fx.fine_of_two"], "Fx.fine_of_two")
    assert r["status"] == "rejected" and "target is one of the sources" in r["reason"]


@needs_lean
def test_no_derivation_and_a_timeout_are_unresolved_never_false(corpus):
    nothing = A.Attempt("target", ("Fx.size_ge",), "Fx.not_fine_zero", ("ImplicationsFixture",), True)
    got = _attempt(corpus, nothing)
    assert got[nothing.id]["status"] == "no-proof"
    tiny = A.Attempt("target", ("Fx.good_of_two", "Fx.fine_of_good"), "Fx.fine_of_two", ("ImplicationsFixture",), False)
    got = _attempt(corpus, tiny, budget=A.Budget(heartbeats=1, ms=10000))
    assert got[tiny.id]["status"] == "budget", got[tiny.id]
    ws, run, decls = corpus
    cat = K.build(list(decls.values()), list(got.values()), {})
    assert cat["counts"]["checked"] == 0 and cat["unresolved"][0]["status"] == "budget"
    assert not any("false" in json.dumps(row).lower() or "refut" in json.dumps(row).lower() for row in cat["unresolved"])


@needs_lean
def test_a_wall_clock_limit_is_a_budget_outcome_and_the_next_attempt_still_runs(corpus):
    # found 2026-10-10 on openai/math: Lean's tryCatchRuntimeEx rethrows interrupts, so the first attempt that reached
    # its wall-clock limit ended the whole process ("uncaught exception: internal exception interrupt") and every
    # attempt after it in the chunk was lost
    slow = A.Attempt("target", ("Fx.size_ge",), "Fx.not_fine_zero", ("ImplicationsFixture",), False, {"tag": "slow"})
    after = A.Attempt("target", ("Fx.good_of_two", "Fx.fine_of_good"), "Fx.fine_of_two", ("ImplicationsFixture",), False, {"tag": "after"})
    got = _attempt(corpus, slow, after, budget=A.Budget(heartbeats=10**7, ms=1))
    assert got[slow.id]["status"] == "budget" and "wall-clock" in got[slow.id]["reason"], got[slow.id]
    assert got[after.id]["status"] in ("budget", "checked"), got[after.id]  # it ran: the process outlived the first


@needs_lean
def test_results_are_cached_by_rule_set_budget_and_environment(corpus):
    ws, run, decls = corpus
    a = A.Attempt("target", ("Fx.fine_of_two",), "Fx.fine_of_good_five", ("ImplicationsFixture",), True)
    first = _attempt(corpus, a)[a.id]
    again = _attempt(corpus, dataclasses.replace(a, meta={}))[a.id]
    assert again.get("cached") is True and again["status"] == first["status"]
    bigger = _attempt(corpus, dataclasses.replace(a, meta={}), budget=A.Budget(ms=10001))[a.id]
    assert not bigger.get("cached")  # another budget is another key


# ---- contracts ----


def _edge(**kw) -> E.Edge:
    base = dict(id="x", kind="composes-with", sources=("Fx.good_of_two", "Fx.fine_of_good"), target="Fx.fine_of_two",
                hypotheses=("(n : Nat) (h : 2 ≤ n)",), conclusion="Fx.Fine n", commit="abcdef1", status="proved",
                origin="test", bridge="bridge_good", bridge_file="bridges/Good.lean")
    return E.Edge(**{**base, **kw})


GOOD_EDGES = [
    _edge(id="good"),
    _edge(id="strengthens", kind="strengthens", sources=("Fx.size_ge",), target="Fx.size_pos", hypotheses=(),
          conclusion="∀ n : Nat, n + 1 ≤ Fx.size n", bridge="bridge_bound", relation="relation_bound", improvement="grows with n"),
    _edge(id="gap", kind="strengthens", sources=("Fx.size_ge",), target="Fx.exists_size_bound", hypotheses=(),
          conclusion="∀ n : Nat, n + 1 ≤ Fx.size n", bridge="bridge_bound", relation="relation_gap", improvement="every n, with the bound named"),
]
ONE = ("Fx.fine_of_good",)
BAD_EDGES = [
    # a valid theorem with the wrong statement must fail
    _edge(id="true", sources=ONE, target="", hypotheses=(), conclusion="Fx.Fine 5",
          bridge="bridge_true", bridge_file="bridges/Bad.lean"),
    _edge(id="extra", bridge="bridge_extra", bridge_file="bridges/Bad.lean"),
    _edge(id="domain", sources=("Fx.double_eq",), target="", hypotheses=(), conclusion="∀ n : Nat, n * 0 = 0", bridge="bridge_domain", bridge_file="bridges/Bad.lean"),
    _edge(id="order", sources=("Fx.double_eq",), target="", hypotheses=(), conclusion="∀ (n m : Nat), n ≤ n + m", bridge="bridge_order", bridge_file="bridges/Bad.lean"),
    _edge(id="sorry", sources=ONE, target="", hypotheses=(), conclusion="Fx.Fine 5", bridge="bridge_sorry", bridge_file="bridges/Bad.lean"),
    _edge(id="axiom", sources=ONE, target="", hypotheses=(), conclusion="Fx.Fine 7", bridge="bridge_axiom", bridge_file="bridges/Bad.lean"),
    _edge(id="direct", sources=ONE, bridge="bridge_direct", bridge_file="bridges/Bad.lean"),
    _edge(id="alias", sources=ONE, bridge="bridge_alias", bridge_file="bridges/Bad.lean"),
    _edge(id="unused", target="", hypotheses=("(n : Nat) (h : Fx.Good n)",), bridge="bridge_unused", bridge_file="bridges/Bad.lean"),
    _edge(id="relation-ignores", kind="strengthens", sources=("Fx.size_ge",), target="Fx.size_pos", hypotheses=(),
          conclusion="∀ n : Nat, n + 1 ≤ Fx.size n", bridge="bridge_bound_copy", bridge_file="bridges/Bad.lean",
          relation="relation_ignores", improvement="grows with n"),
    _edge(id="pointfree-unused", sources=ONE, target="", hypotheses=(), conclusion="True",
          bridge="bridge_pointfree", bridge_file="bridges/Bad.lean"),
    _edge(id="pointfree-relation", kind="strengthens", sources=("Fx.size_ge",), target="Fx.size_pos", hypotheses=(),
          conclusion="∀ n : Nat, n + 1 ≤ Fx.size n", bridge="bridge_bound_copy", bridge_file="bridges/Bad.lean",
          relation="relation_pointfree", improvement="grows with n"),
    _edge(id="unknown-target", sources=ONE, target="Fx.not_a_declaration", bridge="bridge_direct",
          bridge_file="bridges/Bad.lean"),
]


@pytest.fixture(scope="module")
def checked(corpus):
    ws, run, _ = corpus
    return T.check(ws, GOOD_EDGES + BAD_EDGES, HERE, run / "contracts", REV, "", "test", log=print, commit_gb=0)


@needs_lean
def test_a_bridge_that_proves_its_contract_is_checked_and_recorded(checked):
    good = checked["good"]
    assert good["status"] == "checked" and good["used"] == [True, True], good
    assert good["identical_up_to_names"] is True
    assert good["inputs"] == {"ImplicationsFixture.lean": T.sha256_file(HERE / "ImplicationsFixture.lean")}
    assert good["fingerprint"] == E.fingerprint(GOOD_EDGES[0], T.sha256_file(HERE / "bridges" / "Good.lean"))
    s = checked["strengthens"]
    assert s["status"] == "checked", s
    assert s["hypothesis_comparison"] == "rendered-text"
    assert s["target_conclusion"] == "1 ≤ Fx.size n" and s["contract_conclusion"] == "n + 1 ≤ Fx.size n"


@needs_lean
def test_a_relation_reads_the_targets_hypotheses_inside_an_existential(checked):
    # TD-12, found 2026-10-10 on the seven-eighths edge: Siegel's statement is `∃ c, 0 < c ∧ ∀ …`, so the record
    # listed none of its hypotheses and the improvement had to be stated in words instead of derived
    g = checked["gap"]
    assert g["status"] == "checked", g
    assert g["target_path"] == ["∃ c", "0 < c ∧"] and g["contract_path"] == []
    assert g["target_hypotheses"] == ["2 ≤ n"] and g["contract_hypotheses"] == []
    assert g["target_only_hypotheses"] == ["2 ≤ n"] and g["target_conclusion"] == "c ≤ Fx.size n"


@needs_lean
@pytest.mark.parametrize(
    "case, status, says",
    [
        ("true", "mismatch", "does not prove the stated contract"),
        ("extra", "mismatch", "does not prove the stated contract"),
        ("domain", "mismatch", "does not prove the stated contract"),
        ("order", "mismatch", "does not prove the stated contract"),
        ("sorry", "audit-failed", "sorryAx"),
        ("axiom", "audit-failed", "cheat"),
        ("direct", "audit-failed", "reaches the target"),
        ("alias", "audit-failed", "Fx.fine_of_two'"),
        ("unused", "rejected", "does not use every source"),
        ("relation-ignores", "rejected", "does not use the contract"),
        ("pointfree-unused", "rejected", "could not be determined"),
        ("pointfree-relation", "rejected", "could not be determined"),
        ("unknown-target", "error", "unknown declaration Fx.not_a_declaration"),
    ],
)
def test_a_bridge_that_does_not_prove_its_contract_fails(checked, case, status, says):
    r = checked[case]
    assert r["status"] == status and says in r["reason"], r


@needs_lean
@pytest.mark.parametrize(
    "case, expected, bridge_type",
    [
        (
            "true",
            "(∀ (n : Nat), Fx.Good n → Fx.Fine n) → Fx.Fine 5",
            "(∀ (n : Nat), Fx.Good n → Fx.Fine n) → True",
        ),
        (
            "extra",
            "(∀ (n : Nat), 2 ≤ n → Fx.Good n) → (∀ (n : Nat), Fx.Good n → Fx.Fine n) → ∀ (n : Nat), 2 ≤ n → Fx.Fine n",
            "(∀ (n : Nat), 2 ≤ n → Fx.Good n) → (∀ (n : Nat), Fx.Good n → Fx.Fine n) → ∀ (n : Nat), 2 ≤ n → 3 ≤ n → Fx.Fine n",
        ),
        (
            "domain",
            "(∀ (n : Nat), n + n = 2 * n) → ∀ (n : Nat), n * 0 = 0",
            "(∀ (n : Nat), n + n = 2 * n) → ∀ (n : Int), n * 0 = 0",
        ),
        (
            "order",
            "(∀ (n : Nat), n + n = 2 * n) → ∀ (n m : Nat), n ≤ n + m",
            "(∀ (n : Nat), n + n = 2 * n) → ∀ (m n : Nat), n ≤ n + m",
        ),
    ],
)
def test_each_bridge_mismatch_is_the_intended_type_mismatch(checked, case, expected, bridge_type):
    r = checked[case]
    assert r["expected"] == expected, r
    assert r["bridge_type"] == bridge_type, r
    assert r["identical_up_to_names"] is False, r


# ---- recorded verification: stale records say nothing ----


def _record(edge: E.Edge, sha: str = "b" * 64, **kw) -> dict:
    return {"status": "checked", "fingerprint": E.fingerprint(edge, sha), "corpus_revision": REV, "checked_at": "2026-10-10T00:00:00Z",
            "inputs": {"ImplicationsFixture.lean": "c" * 64}, "toolchain": "Lean (version 4.34.1)", "mathlib": "", "axioms": ["propext"], **kw}


def test_a_matching_record_shows_as_kernel_checked_from_the_record():
    edge = GOOD_EDGES[0]
    v = E.verify(edge, lambda n: None, _record(edge), "b" * 64, {"ImplicationsFixture.lean": "c" * 64})
    assert (v.state, v.provenance) == ("kernel-checked", "recorded") and "did not run Lean" in v.detail
    v = E.verify(edge, lambda n: None, _record(edge), "b" * 64, {"ImplicationsFixture.lean": None})
    assert v.state == "kernel-checked" and "could not read ImplicationsFixture.lean" in v.detail


@pytest.mark.parametrize(
    "change, state, says",
    [
        ({"bridge_sha": "d" * 64}, "stale", "changed since"),  # the bridge file changed
        ({"edge": {"conclusion": "Fx.Fine (n + 1)"}}, "stale", "changed since"),  # the contract changed
        ({"inputs": {"ImplicationsFixture.lean": "e" * 64}}, "stale", "differ in this build"),  # a source changed
        ({"record": {"corpus_revision": "0123456789"}}, "stale", "not at abcdef1"),
        ({"record": {"status": "mismatch", "reason": "no"}}, "fails", "failed (mismatch)"),
        ({"record": None}, "unchecked", "No recorded check"),
        ({"bridge_sha": None}, "fails", "is missing"),
    ],
)
def test_a_record_that_does_not_match_says_nothing(change, state, says):
    edge = GOOD_EDGES[0]
    record = _record(edge)
    if "record" in change:
        record = None if change["record"] is None else {**record, **change["record"]}
    edge = dataclasses.replace(edge, **change.get("edge", {}))
    v = E.verify(edge, lambda n: None, record, change.get("bridge_sha", "b" * 64), change.get("inputs", {"ImplicationsFixture.lean": "c" * 64}))
    assert v.state == state and says in v.detail, v


def test_digests_do_not_depend_on_line_endings():
    # found 2026-10-10: a Windows checkout (core.autocrlf) has CRLF where git and Linux have LF; a record made on one
    # must not be stale on the other
    assert E.content_sha256(b"theorem x :\r\n  True := trivial\r\n") == E.content_sha256(b"theorem x :\n  True := trivial\n")
    assert E.content_sha256(b"a\n") != E.content_sha256(b"b\n")


def test_the_rule_set_has_one_identity_whatever_the_line_endings(tmp_path, monkeypatch):
    # found 2026-10-10: Pipeline.lean is CRLF in a Windows checkout and LF in git and on Linux; the policy named in a
    # published catalogue must be the one anyone computes from the committed file
    from lean4_explainer_implications.pipeline import lean as L

    text = L.PIPELINE.read_bytes().replace(b"\r\n", b"\n")
    digests = []
    for name, data in (("lf.lean", text), ("crlf.lean", text.replace(b"\n", b"\r\n"))):
        (tmp_path / name).write_bytes(data)
        monkeypatch.setattr(L, "PIPELINE", tmp_path / name)
        digests.append(L.pipeline_digest())
    assert digests[0] == digests[1]
    (tmp_path / "changed.lean").write_bytes(text + b"\n-- a change\n")
    monkeypatch.setattr(L, "PIPELINE", tmp_path / "changed.lean")
    assert L.pipeline_digest() != digests[0]


def test_edge_files_check_bridge_file_keys():
    base = {"id": "a-b", "kind": "strengthens", "from": ["A.x"], "to": "A.y", "hypotheses": [], "conclusion": "P", "commit": "abcdef1",
            "status": "proved", "origin": "me", "bridge": "b", "bridge_file": "bridges/B.lean"}
    toml = lambda d: "[[edge]]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in d.items())  # noqa: E731
    problems = E.load(toml(base)).problems
    assert any("needs `relation`" in p for p in problems) and any("needs `improvement`" in p for p in problems)
    assert not E.load(toml({**base, "relation": "r", "improvement": "an explicit constant"})).problems
    assert any("relative path" in p for p in E.load(toml({**base, "relation": "r", "improvement": "i", "bridge_file": "../x.lean"})).problems)
    assert any("name `bridge_file` too" in p for p in E.load(toml({**base, "bridge_file": "", "relation": "r"})).problems)
    found = E.load(toml({**base, "relation": "r", "improvement": "i"}))
    assert found.edges[0].names == ("A.x", "A.y")  # a bridge in a bridge file is not a site declaration


# ---- retrieval and the catalogue, without Lean ----


def _decl(key, head, uses, hyps=(), parts=(), role="statement", family="F", type_hash=None, proof_uses=(), challenge=""):
    return {"key": key, "name": key, "module": "M", "path": "M.lean", "role": role, "kind": "theorem", "prop": True, "family": family,
            "type_hash": type_hash or key, "proof_uses": list(proof_uses), "challenge": challenge, "type": key,
            "norm": {"conclusion_head": head, "hyp_heads": list(hyps), "part_heads": list(parts), "uses": list(uses)}}


def test_attempt_ids_use_full_declaration_identities_not_bare_lean_names(tmp_path, monkeypatch):
    # found 2026-10-11 in the shipped openai/math catalogue: three checked IDs and 50 unresolved IDs each named two
    # different attempts. Clashing challenge modules can declare the same Lean name, so the bare name is not an
    # identity; the pipeline's identity is (repository, revision, module, declaration).
    left = A.Attempt("target", ("OAI.Same.result",), "OAI.Same.conclusion", ("ComparatorChallenges.Left",), False,
                     {"source_keys": ["openai/math@abc:ComparatorChallenges.Left:OAI.Same.result"],
                      "target_key": "openai/math@abc:ComparatorChallenges.Left:OAI.Same.conclusion"})
    right = A.Attempt("target", ("OAI.Same.result",), "OAI.Same.conclusion", ("ComparatorChallenges.Right",), False,
                      {"source_keys": ["openai/math@abc:ComparatorChallenges.Right:OAI.Same.result"],
                       "target_key": "openai/math@abc:ComparatorChallenges.Right:OAI.Same.conclusion"})
    assert left.id != right.id

    # Instantiation is a check of one particular derivation on released declarations. Two logical derivations can
    # have the same released source/target tuple; their result rows must still join back unambiguously.
    released = {"verification_source_keys": ["openai/math@abc:OAI.Solution:X.same"],
                "verification_target_key": "openai/math@abc:OAI.Solution:X.conclusion"}
    first = A.Attempt("target", ("X.same",), "X.conclusion", ("OAI.Solution",), True,
                      {**released, "source_keys": ["openai/math@abc:ComparatorChallenges.A:X.same"],
                       "target_key": "openai/math@abc:ComparatorChallenges.A:X.conclusion", "derivation": "derivation-a"})
    second = A.Attempt("target", ("X.same",), "X.conclusion", ("OAI.Solution",), True,
                       {**released, "source_keys": ["openai/math@abc:ComparatorChallenges.B:X.same"],
                        "target_key": "openai/math@abc:ComparatorChallenges.B:X.conclusion", "derivation": "derivation-b"})
    assert first.id != second.id
    assert first.verification_identity == second.verification_identity

    class OneVerificationCache:
        def get(self, _key):
            return {"id": "the-cached-verifications-id", "status": "checked-instantiated", "rule": "target"}

        def put(self, _rows):  # pragma: no cover - every attempt above is a cache hit
            raise AssertionError("nothing should run")

    monkeypatch.setattr(A, "environment_identity", lambda _ws, _modules: "env")
    ws = W.Workspace(tmp_path / "ws", tmp_path / "corpus", ("OAI",))
    rows, stats = A.run_attempts(ws, [first, second], A.Budget(), tmp_path / "attempts", OneVerificationCache())
    assert [r["id"] for r in rows] == [first.id, second.id] and stats.cached == 2 and stats.run == 0


def test_a_failed_attempt_process_cannot_reuse_or_cache_an_old_checked_output(tmp_path, monkeypatch):
    attempt = A.Attempt("target", ("X.source",), "X.target", ("Fixture",))
    monkeypatch.setattr(A, "environment_identity", lambda _ws, _modules: "fixture-env")
    out = tmp_path / "attempts"
    out.mkdir()
    tag = A.hashlib.sha256(json.dumps(["fixture-env", [attempt.id]]).encode()).hexdigest()[:10]
    out.joinpath(f"result-{tag}.jsonl").write_text(json.dumps({
        "id": attempt.id, "status": "checked", "rule": "target",
        "sources": ["X.source"], "target": "X.target",
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(A.L, "run", lambda *_args, **_kw: A.L.LeanRun(1, "", "import failed before output", 0.1))
    cache = A.Cache(tmp_path / "cache.jsonl")
    ws = W.Workspace(tmp_path / "ws", tmp_path / "corpus", ("Fixture",))

    rows, stats = A.run_attempts(ws, [attempt], A.Budget(), out, cache)

    assert rows[0]["status"] in {"env-error", "not-run"}, rows
    assert not cache.entries
    assert stats.process_failures


def test_a_failed_contract_process_cannot_reuse_an_old_checked_output(tmp_path, monkeypatch):
    edge = _edge(id="stale-output")
    out = tmp_path / "contracts"
    out.mkdir()
    tag = T.hashlib.sha256(edge.bridge_file.encode()).hexdigest()[:8]
    out.joinpath(f"contract-{tag}.jsonl").write_text(json.dumps({
        "id": edge.id, "status": "checked", "used": [True, True], "axioms": [],
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(T, "toolchain_version", lambda _ws: "Lean fixture")
    monkeypatch.setattr(T.A, "environment_identity", lambda _ws, _modules: "fixture-env")
    monkeypatch.setattr(T.L, "run", lambda *_args, **_kw: T.L.LeanRun(1, "", "import failed before output", 0.1))
    ws = W.Workspace(tmp_path / "ws", HERE, ("ImplicationsFixture",))

    records = T.check(ws, [edge], HERE, out, REV, "", "test", commit_gb=0)

    assert records[edge.id]["status"] == "error", records[edge.id]
    assert "gave no result" in records[edge.id]["reason"]


def test_released_declarations_with_the_same_lean_name_are_selected_by_provenance():
    stmt = {"key": "challenge-a", "name": "X.main", "family": "Family.A", "type_hash": "type-a"}
    right = {"key": "released-a", "name": "X.main", "family": "Family.A", "type_hash": "type-a"}
    other = {"key": "released-b", "name": "X.main", "family": "Family.B", "type_hash": "type-b"}
    got, reason = S.released_declaration(stmt, {"X.main": [other, right]})
    assert got == right and reason == ""
    got, reason = S.released_declaration(stmt, {"X.main": [right, {**right, "key": "released-a-duplicate"}]})
    assert got is None and reason.startswith("ambiguous released solution")
    got, reason = S.released_declaration(stmt, {})
    assert got is None and reason == "solution not built"
    for wrong_type in ("type-a", "type-b"):
        got, reason = S.released_declaration(
            stmt, {"X.main": [{**other, "type_hash": wrong_type}]}
        )
        assert got is None and reason == "solution not built"


def test_recorded_contract_command_never_exposes_workstation_paths(tmp_path):
    root = tmp_path / "repo"
    edge = root / "packages" / "corpus-oai" / "src" / "lean4_explainer_corpus_oai" / "implications.toml"
    record = edge.with_name("implications.verified.json")
    command = CLI._portable_contract_command([
        "contracts", "--workspace", str(tmp_path / "private-workspace"),
        "--corpus", str(tmp_path / "download" / "corpus"), "--run", str(tmp_path / "private-run"),
        "--edges", str(edge), "--record", str(record),
        "--revision", "abc123",
    ], root)
    assert command.startswith("python -I -m lean4_explainer_implications.pipeline contracts")
    assert "<workspace>" in command and "<corpus>" in command and "<run>" in command
    assert "packages/corpus-oai/src/lean4_explainer_corpus_oai/implications.toml" in command
    assert tmp_path.as_posix() not in command.replace("\\", "/")


def test_catalogue_cli_can_read_an_explicit_scratch_contract_record(tmp_path, monkeypatch):
    run, out = tmp_path / "run", tmp_path / "catalogue"
    run.mkdir()
    edges = tmp_path / "implications.toml"
    edges.write_text("", encoding="utf-8")
    edges.with_name("implications.verified.json").write_text(
        json.dumps({"edges": {"default": {"status": "stale"}}}), encoding="utf-8"
    )
    scratch = tmp_path / "scratch" / "contracts.json"
    scratch.parent.mkdir()
    scratch.write_text(json.dumps({"edges": {"scratch": {"status": "checked"}}}), encoding="utf-8")
    captured = {}

    def build(_decls, _results, _header, contracts):
        captured["contracts"] = contracts
        return {"counts": {}}

    monkeypatch.setattr(CLI.K, "build", build)
    monkeypatch.setattr(CLI.K, "write", lambda _catalogue, _out: {})

    assert CLI.main([
        "catalogue", "--run", str(run), "--out", str(out),
        "--edges", str(edges), "--record", str(scratch),
    ]) == 0
    assert captured["contracts"] == [{"status": "checked"}]


def test_report_cli_can_read_an_explicit_scratch_contract_record(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    edges = tmp_path / "implications.toml"
    edges.write_text("", encoding="utf-8")
    edges.with_name("implications.verified.json").write_text(
        json.dumps({"edges": {"default": {"status": "stale"}}}), encoding="utf-8"
    )
    scratch = tmp_path / "scratch" / "contracts.json"
    scratch.parent.mkdir()
    scratch.write_text(json.dumps({"edges": {"scratch": {"status": "checked"}}}), encoding="utf-8")
    captured = {}

    def collect(_run, _catalogue, contracts, _authoritative_builds):
        captured["contracts"] = contracts
        return {"builds": {}, "layers": {}, "catalogue": {}, "contracts": contracts}

    monkeypatch.setattr(CLI.R, "collect", collect)
    monkeypatch.setattr(CLI.R, "markdown", lambda _data: "report\n")

    assert CLI.main([
        "report", "--run", str(run), "--edges", str(edges), "--record", str(scratch),
    ]) == 0
    assert captured["contracts"] == {"scratch": {"status": "checked"}}


@pytest.mark.parametrize("command, extra", [("catalogue", ["--out", "catalogue"]), ("report", [])])
def test_an_explicit_contract_record_requires_its_edge_file(tmp_path, command, extra):
    with pytest.raises(SystemExit) as stopped:
        CLI.main([command, "--run", str(tmp_path / "run"), "--record", str(tmp_path / "record.json"), *extra])

    assert stopped.value.code == 2


def test_attempt_stage_exit_status_fails_closed_on_incomplete_or_infrastructure_results():
    complete = {"attempts": 2, "results": 2, "candidates": 3, "blocked": [{}],
                "outcomes": {"checked": 1, "no-proof": 1}, "process_failures": []}
    assert CLI._attempt_stage_ok(complete)
    for change in (
        {"process_failures": ["Lean exited"]},
        {"results": 1},
        {"outcomes": {"checked": 1, "env-error": 1}},
        {"outcomes": {"checked": 1, "not-run": 1}},
        {"outcomes": {"checked": 1, "error": 1}},
        {"candidates": 4},
    ):
        assert not CLI._attempt_stage_ok({**complete, **change})

    instantiation = {"checked_derivations": 3, "attempts": 2, "results": 2, "blocked": [{}],
                     "outcomes": {"checked-instantiated": 1, "budget": 1}, "process_failures": []}
    assert CLI._attempt_stage_ok(instantiation)
    assert not CLI._attempt_stage_ok({**instantiation, "checked_derivations": 4})


def test_an_extraction_error_can_never_be_relabelled_as_a_released_theorem(tmp_path):
    corpus = tmp_path / "corpus"
    specs = corpus / "ComparatorChallenges"
    specs.mkdir(parents=True)
    specs.joinpath("Fixture.json").write_text(json.dumps({
        "challenge_module": "ComparatorChallenges.Fixture",
        "solution_module": "OAI.Area.Family.Main",
        "theorem_names": ["X.main"],
    }), encoding="utf-8")
    extracted = tmp_path / "extract"
    extracted.mkdir()
    extracted.joinpath("batch.jsonl").write_text(json.dumps({
        "module": "OAI.Area.Family.Main", "name": "X.main", "error": "could not inspect declaration",
    }) + "\n", encoding="utf-8")
    record = X.ExtractRecord([X.Batch(["OAI.Area.Family.Main"], "ok", "batch.jsonl", failed_declarations=1)])
    declarations = X.load_declarations(record, extracted, X.Identity("openai/math", "abcdef"), corpus)
    assert declarations[0]["role"] == "unreadable"
    assert declarations[0]["challenge"] == "ComparatorChallenges.Fixture"


def test_statement_match_records_all_same_named_challenge_copies_without_order_dependence():
    from lean4_explainer_implications.pipeline import report as R

    statements = [
        {"key": "b", "name": "X.main", "role": "statement", "family": "Family.X", "challenge": "B", "type_hash": "same"},
        {"key": "a", "name": "X.main", "role": "statement", "family": "Family.X", "challenge": "A", "type_hash": "same"},
        {"key": "z", "name": "X.main", "role": "statement", "family": "Family.Z", "challenge": "Z", "type_hash": "other"},
        {"key": "c", "name": "Y.main", "role": "statement", "family": "Family.Y", "challenge": "C", "type_hash": "old"},
    ]
    solutions = [
        {"key": "r1", "name": "X.main", "role": "released", "family": "Family.X", "module": "S.X",
         "type_hash": "same", "sorry": False, "axioms": []},
        {"key": "r2", "name": "Y.main", "role": "released", "family": "Family.Y", "module": "S.Y",
         "type_hash": "new", "sorry": False, "axioms": []},
        {"key": "r3", "name": "X.main", "role": "released", "family": "Family.Q", "module": "S.Q",
         "type_hash": "same", "sorry": False, "axioms": []},
    ]
    got = R.statement_match(statements, solutions)
    assert got["compared"] == 2 and got["same"] == 1
    assert got["rows"][0]["challenge_keys"] == ["a", "b"] and got["rows"][0]["same"] is True
    assert got["rows"][1]["challenge_keys"] == ["c"] and got["rows"][1]["same"] is False


def test_the_catalogue_refuses_duplicate_attempt_ids():
    # An ID is the DOM/deep-link key and joins an instantiation to its derivation. Never silently let a later row
    # overwrite an earlier, different attempt.
    decls = [_decl("repo@abc:A:X.same", "P", []), _decl("repo@abc:B:X.same", "P", []), _decl("repo@abc:C:X.goal", "P", [])]
    rows = [
        {"id": "collision", "status": "no-proof", "rule": "target", "source_keys": [decls[0]["key"]], "target_key": decls[2]["key"]},
        {"id": "collision", "status": "no-proof", "rule": "target", "source_keys": [decls[1]["key"]], "target_key": decls[2]["key"]},
    ]
    with pytest.raises(ValueError, match="duplicate attempt id collision"):
        K.build(decls, rows, {})

    for missing_id in (None, ""):
        with pytest.raises(ValueError, match="nonempty attempt id"):
            K.build(decls, [{**rows[0], "id": missing_id}], {})

    derivation = {"id": "derivation", "status": "checked", "rule": "target", "source_keys": [decls[0]["key"]],
                  "target_key": decls[2]["key"], "sources": ["X.same"], "statement": "P", "statement_hash": "p"}
    applied = [
        {"id": "instantiation-1", "derivation": "derivation", "status": "checked-instantiated"},
        {"id": "instantiation-2", "derivation": "derivation", "status": "budget"},
    ]
    with pytest.raises(ValueError, match="duplicate instantiation for derivation derivation"):
        K.build(decls, [derivation, *applied], {})

    orphan = {"id": "instantiation-orphan", "derivation": "old-id", "status": "checked-instantiated",
              "rule": "target", "source_keys": derivation["source_keys"], "target_key": derivation["target_key"]}
    with pytest.raises(ValueError, match="orphan instantiation old-id"):
        K.build(decls, [derivation, orphan], {})

    mismatch = {"id": "instantiation-mismatch", "derivation": "derivation", "status": "checked-instantiated",
                "rule": "target", "source_keys": [decls[1]["key"]], "target_key": derivation["target_key"]}
    with pytest.raises(ValueError, match="instantiation does not match derivation derivation"):
        K.build(decls, [derivation, mismatch], {})


def test_lemmas_lean_generated_are_never_proposed():
    # found 2026-10-10 on openai/math: 2,048 of 4,012 attempts involved a constructor's injectivity lemma, an equation
    # lemma or `sizeOf_spec`, which have no source position; none can be a stated result
    target = dict(_decl("t", "Foo", ["Foo", "Rare"]), range={"line": 1})
    stated = dict(_decl("s", "Foo", ["Foo", "Rare"]), range={"line": 2})
    made = dict(_decl("g", "Foo", ["Foo", "Rare"]), range=None)
    p = C.propose([target, stated, made], [target, made])
    assert {c.sources for c in p.candidates if c.rule == "target"} == {("s",)}
    assert not any("g" in c.sources or c.target == "g" for c in p.candidates)


def test_retrieval_needs_a_shared_rare_constant_and_respects_its_bounds():
    target = _decl("t", "Foo", ["Foo", "Rare"])
    near = [_decl(f"s{i}", "Foo", ["Foo", "Rare"]) for i in range(10)]
    unrelated = _decl("u", "Foo", ["Other"])  # the same head, nothing shared: never proposed
    common = [_decl(f"c{i}", "Bar", ["Foo"]) for i in range(30)]  # makes Foo common (not rare)
    p = C.propose([target, unrelated, *near, *common], [target], C.Bounds(per_target=4, rare_df=25))
    singles = [c for c in p.candidates if c.rule == "target" and c.target == "t" and len(c.sources) == 1]
    assert len(singles) == 4 and all("Rare" in c.shared for c in singles)
    assert not any("u" in c.sources for c in p.candidates)


def test_retrieval_never_reads_names():
    a = _decl("Lemma.big_theorem", "Foo", ["X1"])
    b = _decl("Lemma.big_theorem'", "Foo", ["X2"])  # nearly the same name, nothing shared
    assert not C.propose([a, b], [a, b]).candidates


def test_the_catalogue_groups_routine_results_apart_from_connections():
    decls = [_decl("a", "P", []), _decl("b", "Q", [], type_hash="h"), _decl("c", "Q", [], type_hash="h"),
             _decl("d", "R", [], role="released", proof_uses=["a"]), _decl("e", "S", [], challenge="X"), _decl("f", "S", [], challenge="X")]
    row = lambda i, srcs, tgt, status="checked", **kw: {"id": i, "status": status, "rule": "target", "source_keys": srcs, "target_key": tgt,  # noqa: E731
                                                       "sources": srcs, "statement_hash": kw.pop("h", i), "statement": i, **kw}
    results = [row("1", ["b"], "c"), row("2", ["a"], "d"), row("3", ["e"], "f"), row("4", ["a"], "b"), row("5", ["b"], "a"),
               row("6", ["c"], "a", h="4"), row("7", ["d"], "c", status="instantiation-circular"), row("8", ["a"], "", status="no-proof"),
               row("9", ["a", "b"], "c", status="rejected", reason="does not use #[a]: not a result of all its sources")]
    cat = K.build(decls, results, {})
    groups = {i["id"]: i["group"] for i in cat["implications"]}
    assert groups == {"1": "same statement", "2": "in the released proof", "3": "one challenge", "4": "connection",
                      "5": "reverse direction", "6": "duplicate", "7": "source uses the target"}
    assert cat["counts"]["connections"] == 1 and cat["counts"]["unresolved"] == 1 and cat["counts"]["rejected"] == 1
    assert cat["counts"]["rejected_by_reason"] == {"a source is unused": 1}


def test_proof_dependencies_do_not_cross_same_named_solution_families():
    def named(key, name, family, role="statement", proof_uses=(), env=0):
        return {**_decl(key, "P", [], role=role, family=family, proof_uses=proof_uses),
                "name": name, "module": f"Solution.{family}.{env}", "env": env}

    declarations = [
        named("sa", "X.source", "A"), named("ta", "X.target", "A"),
        named("sb", "X.source", "B"), named("tb", "X.target", "B"),
        named("ha", "X.source", "A", "helper"), named("hb", "X.source", "B", "helper", env=1),
        named("hc", "X.source", "A", "helper", env=1),
        named("ra", "X.target", "A", "released", ["X.source"]),
        named("rb", "X.target", "B", "released"),
    ]
    row = lambda id_, source, target: {  # noqa: E731
        "id": id_, "status": "checked", "rule": "target", "source_keys": [source], "target_key": target,
        "sources": ["X.source"], "statement": "P", "statement_hash": id_,
    }
    catalogue = K.build(declarations, [row("edge-a", "sa", "ta"), row("edge-b", "sb", "tb")], {})
    groups = {entry["id"]: entry["group"] for entry in catalogue["implications"]}
    assert groups == {"edge-a": "in the released proof", "edge-b": "connection"}
    dependencies = {entry["from"]: entry["uses"] for entry in catalogue["dependencies"]}
    assert dependencies["ra"] == ["ha"]


def test_a_source_passed_through_unchanged_is_a_restatement_not_a_connection():
    # found 2026-10-10 on openai/math: Hyperinvariant.main_theorem and BackwardIntertwiners.direct_algebra_corollary
    # each define their own FullClaim; the "derivation" between them is the source itself, so the two challenges
    # state one proposition up to unfolding definitions. Counted as a connection, it would inflate the catalogue.
    decls = [_decl(k, k.upper(), []) for k in "abcdefgh"]
    apply = lambda subs: {"step": "apply", "fact": "source 1", "source": 1, "substitutions": [{"variable": v, "value": x} for v, x in subs]}  # noqa: E731
    assume = {"step": "assumption", "goal": "…"}
    row = lambda i, s, t, steps, proof: {"id": i, "status": "checked", "rule": "target", "source_keys": [s], "target_key": t, "sources": [s],  # noqa: E731
                                         "statement_hash": i, "statement": i, "steps": steps, "proof": proof}
    results = [
        row("1", "a", "b", [assume], "fun source1 => source1"),
        row("2", "c", "d", [apply([("H", "H")]), assume],
            "fun source1 H [NormedAddCommGroup H] [InnerProductSpace ℂ H] [CompleteSpace H]\n    hInf =>\n  source1 H hInf"),
        row("3", "e", "f", [apply([("A", "A"), ("B", "B")]), assume, assume], "fun source1 A B a a_1 => source1 A B a a_1"),
        # an implicit variable the printed proof hides: n := 5 is a specialization, not a restatement
        row("4", "g", "h", [apply([("n", "5")]), assume], "fun source1 h => source1 h"),
        # the arguments in another order: not the source passed through
        row("5", "a", "c", [apply([("m", "n"), ("n", "m")])], "fun source1 m n => source1 n m"),
        # a discharged premise: work was done
        row("6", "b", "e", [apply([("n", "n")]), {"step": "discharge", "by": "omega", "goal": "0 < n"}], "fun source1 n => source1 n (by omega)"),
    ]
    groups = {i["id"]: i["group"] for i in K.build(decls, results, {})["implications"]}
    assert groups == {"1": "restatement", "2": "restatement", "3": "restatement", "4": "connection", "5": "connection", "6": "connection"}


def test_compositions_inside_one_challenge_and_generated_lemmas_are_not_connections():
    # found 2026-10-10 on openai/math: 301 checked compositions, mostly a structure's field or its constructor's
    # injectivity lemma (which Lean generates, with no source position) composed with a statement of the same file
    at = {"line": 3}
    decls = [dict(_decl("a", "P", [], challenge="X"), range=at), dict(_decl("b", "Q", [], challenge="X"), range=at),
             dict(_decl("c", "R", [], challenge="Y"), range=at), dict(_decl("g", "Eq", [], challenge="Y"), range=None),
             dict(_decl("d", "S", [], challenge="Z"), range=at)]
    row = lambda i, srcs, tgt="", rule="compose": {"id": i, "status": "checked", "rule": rule, "source_keys": srcs, "target_key": tgt,  # noqa: E731
                                                   "sources": srcs, "statement_hash": i, "statement": i}
    results = [row("1", ["a", "b"]), row("2", ["a", "c"]), row("3", ["c", "g"]), row("4", ["g"], "d", rule="target")]
    groups = {i["id"]: i["group"] for i in K.build(decls, results, {})["implications"]}
    assert groups == {"1": "one challenge", "2": "connection", "3": "generated", "4": "generated"}


def test_the_catalogue_says_what_links_each_composition(tmp_path):
    # found 2026-10-11 on openai/math: 9 of the 14 connections are linked only by a quantity's positivity; the count
    # of connections must not read as 14 deep links
    from lean4_explainer_implications import catalogue_site as CS

    at = {"line": 3}
    decls = [dict(_decl(k, "P", [], challenge=c), range=at) for k, c in (("a", "X"), ("b", "Y"), ("c", "Z"), ("d", "W"))]
    supply = lambda hyp, head, pos: [{"step": "supply", "hypothesis": hyp, "hypothesis_head": head, "positivity": pos}]  # noqa: E731
    results = [{"id": i, "status": "checked", "rule": "compose", "source_keys": s, "target_key": "", "sources": s, "statement_hash": i,
                "statement": i, "steps": st} for i, s, st in
               (("1", ["a", "b"], supply("0 < K", "LT.lt", True)), ("2", ["c", "d"], supply("S.Infinite", "Set.Infinite", False)),
                ("3", ["a", "d"], []))]  # recorded before links were: not counted as either
    cat = K.build(decls, results, {})
    got = {i["id"]: i for i in cat["implications"]}
    assert got["1"]["link"] == {"hypothesis": "0 < K", "head": "LT.lt", "positivity": True} and got["3"]["link"] is None
    assert cat["counts"]["connections_by_link"] == {"positivity": 1, "Set.Infinite": 1, "not recorded": 1}
    K.write(cat, tmp_path)
    rows = {r["id"]: r for r in json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["implications"]}
    assert rows["1"]["link"] == "positivity" and rows["2"]["link"] == "Set.Infinite" and rows["3"]["link"] == ""
    page = "".join(CS.catalogue_body(cat))
    assert "1 of them linked only by a quantity's positivity" in page
    script = CS.script()
    has_link = "linked by " in script and "r.link" in script  # each listed entry says what links it
    assert has_link
    from lean4_explainer_implications.pipeline import report as R

    md = R.markdown({"builds": {}, "layers": {}, "contracts": {}, "catalogue": {"counts": cat["counts"], "total_bytes": 0, "bytes": {}}})
    assert "- connections by what links their sources: Set.Infinite 1, not recorded 1, positivity 1" in md
    assert "- rejected attempts 0: —" in md
    assert "catalogue index and shards (generated reports excluded): 0 bytes" in md


def test_the_report_calls_build_counts_import_closure_outcomes():
    from lean4_explainer_implications.pipeline import report as R

    data = {"builds": {"build-challenges": {"counts": {"built": 416, "replayed": 69}, "build_seconds": 1,
                                                   "stopped": "", "failed": []}},
            "layers": {}, "catalogue": {}, "contracts": {}}
    md = R.markdown(data)
    assert "corpus modules in each requested module's import closure" in md
    assert "built means compiled in that run; replayed means an existing matching build trace was reused" in md
    assert "| build | import-closure outcomes | module-seconds | stopped |" in md


def test_the_report_separates_authoritative_builds_from_retained_diagnostics(tmp_path):
    from lean4_explainer_implications.pipeline import report as R

    records = {
        "build-challenges": {"counts": {"built": 1}, "modules": []},
        "build-solutions-21": {"counts": {"replayed": 1}, "modules": []},
        "build-solutions-probe": {"counts": {"failed": 1}, "modules": []},
        "build-old": {"counts": {"built": 99}, "modules": []},
    }
    for name, record in records.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")

    ordinary = R.collect(tmp_path)
    assert set(ordinary["builds"]) == set(records) and not ordinary["build_diagnostics"]

    got = R.collect(tmp_path, authoritative_builds={"build-challenges", "build-solutions-21"})
    assert set(got["builds"]) == {"build-challenges", "build-solutions-21"}
    assert set(got["build_diagnostics"]) == {"build-old", "build-solutions-probe"}

    md = R.markdown(got)
    assert "## Authoritative builds" in md
    assert "## Historical build diagnostics" in md
    assert "retained for diagnosis and provenance, not promotion evidence" in md
    assert md.index("build-solutions-21") < md.index("build-old")


def test_the_report_refuses_a_missing_requested_authoritative_build(tmp_path):
    from lean4_explainer_implications.pipeline import report as R

    (tmp_path / "build-challenges.json").write_text(
        json.dumps({"counts": {"built": 1}, "modules": []}), encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError, match="requested authoritative build records are missing: build-solutions-21"):
        R.collect(tmp_path, authoritative_builds={"build-challenges", "build-solutions-21"})


def test_a_derivation_through_a_structures_field_is_not_a_connection():
    # TD-16, found 2026-10-10 on openai/math: `TriCylinder.convex : ∀ self, Convex ℝ self.base` composed with a
    # general convexity theorem of another challenge is checked and new, but says only that the theorem applies to
    # what the structure requires; 10 of the 24 connections looked like this
    at = {"line": 3}
    field = {"structure": "T", "field": "convex", "index": 1, "class": False}
    decls = [dict(_decl("T.convex", "P", [], challenge="X"), range=at, projection=field),
             dict(_decl("g", "Q", [], challenge="Y"), range=at, projection=None),
             dict(_decl("h", "R", [], challenge="Z"), range=at), dict(_decl("t", "S", [], challenge="Z"), range=at)]
    row = lambda i, srcs, tgt="", rule="compose": {"id": i, "status": "checked", "rule": rule, "source_keys": srcs, "target_key": tgt,  # noqa: E731
                                                   "sources": srcs, "statement_hash": i, "statement": i}
    results = [row("1", ["T.convex", "g"]), row("2", ["g", "h"]), row("3", ["T.convex"], "t", rule="target"), row("4", ["g", "T.convex"])]
    cat = K.build(decls, results, {})
    got = {i["id"]: i for i in cat["implications"]}
    assert {k: v["group"] for k, v in got.items()} == {"1": "structure field", "2": "connection", "3": "structure field", "4": "structure field"}
    assert "`convex`" in got["1"]["group_reason"] and "`T`" in got["1"]["group_reason"]
    assert cat["counts"]["connections"] == 1


def test_the_index_names_only_theorems_that_checked_entries_name(tmp_path):
    # found 2026-10-10 on openai/math: 13,396 theorem entries (9.5 MB) in an index of 518 checked entries, against a
    # site with about 25 MB left of GitHub Pages' 1 GB; unresolved rows keep their keys, in their family's shard
    decls = [_decl(k, "P", []) for k in ("a", "b", "u", "v")]
    row = {"id": "1", "status": "checked", "rule": "target", "source_keys": ["a"], "target_key": "b", "sources": ["a"], "statement": "b"}
    miss = {"id": "2", "status": "no-proof", "rule": "target", "source_keys": ["u"], "target_key": "v", "reason": "nothing within the rules"}
    cat = K.build(decls, [row, miss], {})
    assert set(cat["theorems"]) == {"a", "b"} and cat["counts"]["theorems_indexed"] == 2
    K.write(cat, tmp_path)
    shard = json.loads(next((tmp_path / "shards").glob("*.json")).read_text(encoding="utf-8"))
    assert [(r["sources"], r["target"]) for r in shard["unresolved"]] == [(["u"], "v")]


def test_rewriting_a_catalogue_leaves_no_shard_its_index_does_not_name(tmp_path):
    # the shipped catalogue is rewritten in place: a family that no longer has entries must not leave its old shard to
    # be published beside the new index
    row = {"id": "1", "status": "checked", "rule": "target", "source_keys": ["a"], "target_key": "b", "sources": ["a"], "statement": "b"}
    K.write(K.build([_decl("a", "P", [], family="Old.One"), _decl("b", "P", [], family="Old.One")], [row], {}), tmp_path)
    (tmp_path / "shards" / "notes.txt").write_text("not the writer's", encoding="utf-8")
    sizes = K.write(K.build([_decl("a", "P", [], family="New.Two"), _decl("b", "P", [], family="New.Two")], [row], {}), tmp_path)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    on_disk = {p.name for p in (tmp_path / "shards").glob("*.json")}
    assert on_disk == {f"{n}.json" for n in index["shards"]} == {k.split("/")[1] for k in sizes if k.startswith("shards/")}
    assert (tmp_path / "shards" / "notes.txt").is_file()  # only shard files are the writer's to remove


def test_the_report_counts_the_families_and_areas_each_stage_reached(tmp_path):
    from lean4_explainer_implications.pipeline import report as R

    decls: list[dict] = [dict(_decl(k, "P", [], family=f), area=a, range={"line": 1}) for k, f, a in
             (("a", "F1", "Algebra"), ("b", "F1", "Algebra"), ("c", "F2", "Geometry"), ("d", "F3", "Algebra"))]
    decls.append(dict(_decl("g", "Eq", [], family="F4"), area="Topology", range=None))  # generated: not a statement
    (tmp_path / "statements").mkdir()
    (tmp_path / "statements" / "declarations.jsonl").write_text("".join(json.dumps(d) + "\n" for d in decls), encoding="utf-8")
    results = [{"id": "1", "status": "checked", "source_keys": ["a"], "target_key": "b"},
               {"id": "2", "status": "no-proof", "source_keys": ["c"], "target_key": "a"},
               {"id": "3", "status": "checked", "source_keys": ["c"], "target_key": "d"}]
    (tmp_path / "statements" / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
    # applied to the released theorems: 1 checked, 3 ran out of budget (which establishes nothing)
    (tmp_path / "instantiation").mkdir()
    applied = [{"id": "i1", "derivation": "1", "status": "checked-instantiated"}, {"id": "i3", "derivation": "3", "status": "budget"}]
    (tmp_path / "instantiation" / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in applied), encoding="utf-8")
    # found 2026-10-10: a layer's connections were counted from the whole catalogue, so the solutions layer, which
    # attempted nothing, reported the statements layer's 27 families
    index = {"implications": [{"id": "1", "group": "connection", "families": ["F1"], "layer": "statements"},
                              {"id": "x", "group": "connection", "families": ["F3"], "layer": "solutions"}]}
    cov = R.coverage(tmp_path, "statements", index)
    assert cov["families"] == {"statements": 3, "attempted": 3, "checked": 3, "instantiated": 1, "connections": 1}
    assert cov["areas"] == {"statements": 2, "attempted": 2, "checked": 2, "instantiated": 1, "connections": 1}
    assert "families: statements 3, attempted 3, checked 3, instantiated 1, connections 1" in R.markdown(
        {"builds": {}, "layers": {}, "catalogue": {}, "contracts": {}, "coverage": {"statements": cov}})
    assert R.coverage(tmp_path, "solutions", index)["families"]["connections"] == 1  # its own, F3; not F1 as well


def test_the_report_does_not_include_its_self_rewriting_json_in_catalogue_bytes(tmp_path):
    from lean4_explainer_implications.pipeline import report as R

    run, catalogue = tmp_path / "run", tmp_path / "catalogue"
    run.mkdir()
    catalogue.mkdir()
    (catalogue / "index.json").write_text('{"counts": {}}', encoding="utf-8")
    (catalogue / "report.json").write_text("stale and a different length", encoding="utf-8")
    first = R.collect(run, catalogue)
    assert first["catalogue"]["bytes"] == {"index.json": (catalogue / "index.json").stat().st_size}
    (catalogue / "report.json").write_text(json.dumps(first, indent=1), encoding="utf-8")
    assert R.collect(run, catalogue)["catalogue"] == first["catalogue"]


def test_modules_that_declare_the_same_name_go_to_separate_environments(tmp_path, monkeypatch):
    """Lean names both modules of a clash: the one that failed moves to another batch, and both batches import."""
    from lean4_explainer_implications.pipeline import lean as L

    clash = {("A", "B")}  # A and B declare the same name
    runs = []

    def fake_run(env, cwd, args, timeout, log=print, **kw):
        if args[0] == "names":  # the names could not be read: clashes are found by importing
            return L.LeanRun(1, "", "no names", 1.0)
        listing = Path(args[-1][1:]).read_text(encoding="utf-8").split()
        runs.append(listing)
        for a, b in clash:
            if a in listing and b in listing:
                return L.LeanRun(1, "", f"uncaught exception: import {b} failed, environment already contains 'X.n' from {a}", 1.0)
        Path(args[1]).write_text("", encoding="utf-8")
        return L.LeanRun(0, json.dumps({"declarations": len(listing), "failed": 0, "import_ms": 1, "extract_ms": 1}), "", 1.0)

    monkeypatch.setattr(L, "run", fake_run)
    ws = W.Workspace(tmp_path, tmp_path, ("Z",))  # A to D are not corpus modules: no sources to read
    record = X.run_extraction(ws, ["A", "B", "C", "D"], tmp_path / "out", log=print)
    assert record.environments == [["A", "C", "D"], ["B"]]
    assert [b.status for b in record.batches] == ["clash", "ok", "ok"] and "B and A both declare X.n" in record.batches[0].error
    assert len(runs) == 3  # one failed import, then one per environment: no halving


def test_a_clash_found_before_importing_keeps_the_modules_apart():
    graph = {"A": {"B": "X.n"}, "B": {"A": "X.n", "C": "Y.m"}, "C": {"B": "Y.m"}, "D": {}}
    assert X.partition(["A", "B", "C", "D"], graph, 500) == [["A", "C", "D"], ["B"]]
    assert X.partition(["A", "B", "C", "D"], graph, 2) == [["A", "C"], ["B", "D"]]


def test_candidates_across_environments_share_one_and_clashing_ones_are_blocked():
    # found 2026-10-10 on openai/math's challenges: 727 cross-environment candidates needed 346 module sets, one Lean
    # process each, and 108 of those sets cannot be imported at all (two challenge files declare the same name)
    envs = [["A", "B"], ["C"], ["D"], ["E"]]
    clashes = {frozenset({"A", "C"}): "X.n", frozenset({"A", "D"}): "X.n", frozenset({"C", "D"}): "Y.m"}
    needs = [({0}, {"A"}), ({0, 1}, {"B", "C"}), ({0, 1}, {"A", "C"}), ({0, 2}, {"B", "D"}), ({1, 0}, {"C", "B"}), ({0, 3}, {"B", "E"})]
    modules, blocked = S.plan_environments(needs, envs, clashes, limit=500)
    assert modules == [("A", "B"), ("B", "C", "E"), (), ("B", "D"), ("B", "C", "E"), ("B", "C", "E")]
    assert blocked == {2: "no environment holds both A and C: each declares X.n"}
    modules, blocked = S.plan_environments(needs, envs, clashes, limit=2)
    assert modules[1] == modules[4] == ("B", "C") and modules[3] == ("B", "D") and modules[5] == ("B", "E")
    for ms in modules:  # no environment imports two modules that clash
        assert not any(frozenset({a, b}) in clashes for a in ms for b in ms)


def test_the_catalogue_names_the_rule_set_its_results_were_checked_under():
    # found 2026-10-10: the page named the rule set the extraction ran under (environment.json), and the catalogue the
    # one current when it was assembled, not the one each result records
    from lean4_explainer_implications import catalogue_site as CS
    from lean4_explainer_implications.pipeline import report as R

    decls = [_decl("a", "P", []), _decl("b", "P", [])]
    row = {"id": "1", "status": "checked", "rule": "target", "source_keys": ["a"], "target_key": "b", "sources": ["a"], "statement": "b",
           "policy": "rules-1:aaa"}
    cat = K.build(decls, [row], {"policy": "rules-1:bbb", "environment": {"policy": "rules-1:ccc"}})
    assert cat["policy"] == "rules-1:aaa"
    page = "".join(CS.catalogue_body(cat))
    assert "rules-1:aaa" in page and "rules-1:bbb" not in page
    assert "rules-1:ccc" not in page.split("extract")[0]  # the extraction's rule set only where it is named as such
    md = R.markdown({"environment": {"policy": "rules-1:ccc"}, "builds": {}, "layers": {}, "catalogue": {}, "contracts": {}})
    assert "- policy:" not in md and "rules-1:ccc" in md.split("extract")[1]
    # each layer names the rule set it was extracted under: two layers can differ, so the run-wide record does not
    cat = K.build(decls, [row], {"extraction": {"statements": "rules-1:ddd", "solutions": "rules-1:aaa"}, "environment": {}})
    page = "".join(CS.catalogue_body(cat))
    assert page.index("extracted under") < page.index("rules-1:ddd") and "statements" in page.split("extracted under")[1]
    # layers extracted under one rule set name it once
    cat = K.build(decls, [row], {"extraction": {"statements": "rules-1:eee", "solutions": "rules-1:eee"}, "environment": {}})
    page = "".join(CS.catalogue_body(cat))
    assert page.count("rules-1:eee") == 1 and "rules-1:eee (solutions, statements)" in page
    layer = {"extract": {"policy": "rules-1:ddd", "modules_requested": 1, "modules_added": ["S.Gauss"], "modules_extracted": 2, "environments": [2], "splits": [],
                         "declarations": 1, "by_role": {}, "statements": 1, "with_sorry": 0, "unreadable": 0, "seconds": 1}}
    md = R.markdown({"environment": {}, "builds": {}, "layers": {"statements": layer}, "catalogue": {}, "contracts": {}})
    assert "- extracted under rule set `rules-1:ddd`" in md
    assert "- 1 more modules extracted because they declare a theorem a challenge lists: `S.Gauss`" in md


def test_unresolved_reasons_that_differ_only_in_lean_internal_ids_are_one_group():
    # found 2026-10-10 on the notes page: one cause, "unknown free variable `_fvar.1889142`", made 21 rows of one
    rows = [{"status": "error", "reason": f"unknown free variable `_fvar.{n}`"} for n in (1889142, 2891681, 77)]
    rows.append({"status": "no-proof", "reason": "no derivation within the rules and depth"})
    assert K.summarize_unresolved(rows) == [
        {"status": "error", "reason": "unknown free variable `_fvar.…`", "count": 3},
        {"status": "no-proof", "reason": "no derivation within the rules and depth", "count": 1}]


def test_a_released_theorem_is_extracted_from_the_module_that_declares_it(tmp_path, monkeypatch):
    # found 2026-10-10 on openai/math: ProductSpaces.Main proves one of its four released theorems; the other three are
    # declared in GaussianBounds and WeakNullity, which it imports, and extracting Main alone missed them
    from lean4_explainer_implications.pipeline import lean as L

    corpus = tmp_path / "corpus"
    (corpus / "S").mkdir(parents=True)
    (corpus / "ComparatorChallenges").mkdir()
    (corpus / "S" / "Main.lean").write_text("import S.Gauss\nimport S.Util\n", encoding="utf-8")
    (corpus / "S" / "Gauss.lean").write_text("", encoding="utf-8")
    (corpus / "S" / "Util.lean").write_text("", encoding="utf-8")
    (corpus / "ComparatorChallenges" / "T.json").write_text(json.dumps({"theorem_names": ["T.main", "T.other"]}), encoding="utf-8")
    declared = {"S.Main": ["T.main", "S.x"], "S.Gauss": ["T.other"], "S.Util": ["S.u"]}
    runs = []

    def fake_run(env, cwd, args, timeout, log=print, **kw):
        if args[0] == "names":
            Path(args[1]).write_text("".join(json.dumps({"module": m, "names": ns}) + "\n" for m, ns in declared.items()), encoding="utf-8")
            return L.LeanRun(0, "", "", 1.0)
        runs.append(sorted(Path(args[-1][1:]).read_text(encoding="utf-8").split()))
        Path(args[1]).write_text("", encoding="utf-8")
        return L.LeanRun(0, json.dumps({"declarations": 0, "failed": 0, "import_ms": 1, "extract_ms": 1}), "", 1.0)

    monkeypatch.setattr(L, "run", fake_run)
    ws = W.Workspace(tmp_path / "ws", corpus, ("S", "ComparatorChallenges"))
    record = X.run_extraction(ws, ["S.Main"], tmp_path / "out", log=print)
    assert runs == [["S.Gauss", "S.Main"]] and record.added == ["S.Gauss"]


def test_an_instantiation_upgrades_the_derivation_it_applies_and_is_not_listed_again():
    # found 2026-10-10: the instantiate stage writes its own rows, each naming the derivation it applies; read as more
    # results they would list each derivation twice, and leave the derivation's own state unchanged
    decls = [_decl(k, "P", [], challenge=c) for k, c in (("a", "X"), ("b", "Y"), ("c", "Z"), ("d", "W"))]
    decls += [_decl("released-a", "P", [], role="released"), _decl("released-b", "P", [], role="released")]
    row = lambda i, s, t, **kw: {"id": i, "status": "checked", "rule": "target", "source_keys": s, "target_key": t, "sources": s,  # noqa: E731
                                  "statement": i, "statement_hash": i, **kw}
    results = [row("1", ["a"], "b"), row("2", ["c"], "d"), row("3", ["b"], "c"),
               {**row("i1", ["a"], "b"), "status": "checked-instantiated", "derivation": "1", "instantiated_axioms": ["propext"],
                "verification_source_keys": ["released-a"], "verification_target_key": "released-b", "env_modules": 2},
               {**row("i2", ["c"], "d"), "status": "budget", "derivation": "2", "reason": "wall-clock limit of 10000 ms"},
               {**row("i3", ["b"], "c"), "status": "instantiation-circular", "derivation": "3"}]
    cat = K.build(decls, results, {})
    got = {i["id"]: i for i in cat["implications"]}
    assert sorted(got) == ["1", "2", "3"]
    assert got["1"]["state"] == "checked-instantiated" and got["1"]["instantiated_axioms"] == ["propext"]
    assert got["1"]["instantiation"]["verification_sources"] == ["released-a"]
    assert got["1"]["instantiation"]["verification_target"] == "released-b"
    assert {"released-a", "released-b"} <= set(cat["theorems"])
    assert got["2"]["state"] == "checked-derivation" and got["2"]["instantiation"]["status"] == "budget"
    assert got["3"]["group"] == "source uses the target"
    assert cat["counts"]["instantiation"] == {"checked-instantiated": 1, "budget": 1, "instantiation-circular": 1}
    assert not cat["unresolved"]


def test_the_page_says_what_applying_a_derivation_to_the_released_theorems_established():
    # an attempt that ran out of time, errs or finds no proof establishes nothing either way: the page must not read it
    # as the implication failing for the released theorems
    from lean4_explainer_implications import catalogue_site as CS

    labels = json.loads(CS.script().split("var LABELS = ", 1)[1].split(";\n", 1)[0])["instantiation"]
    assert set(labels) == {"checked-instantiated", "instantiation-circular", "budget", "error", "no-proof", "audit-failed"}
    for status in ("budget", "error", "no-proof", "audit-failed"):
        assert labels[status].startswith("not established"), status
    for label in labels.values():
        assert not any(w in label.lower() for w in ("false", "refut", "disprov", "fails for")), label
    assert "d.instantiation" in CS.script()
    script = CS.script()
    assert "verification inputs" in script and "target statement" in script and "verification_target" in script
    assert "released sources checked" not in script and "released target checked" not in script


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_catalogue_page_draws_an_entrys_steps_and_what_applying_it_established(tmp_path):
    # the page's script had no test that runs it; found 2026-10-11 reading it: a composition's step was drawn as the
    # bare word "supply", without the hypothesis one source supplies to the other
    import subprocess

    from lean4_explainer_implications import catalogue_site as CS

    at = {"line": 3}
    decls = [dict(_decl(k, "P", [], challenge=c), range=at) for k, c in (("a", "X"), ("b", "Y"))]
    row = {"id": "1", "status": "checked", "rule": "compose", "source_keys": ["a", "b"], "target_key": "", "sources": ["a", "b"],
           "statement_hash": "1", "statement": "S", "derived": "A → B → S",
           "steps": [{"step": "supply", "from": "source 1, conclusion", "hypothesis": "0 < K", "of": "source 2",
                      "hypothesis_head": "LT.lt", "positivity": True}]}
    applied = {"id": "i1", "derivation": "1", "status": "budget", "rule": "compose",
               "source_keys": ["a", "b"], "target_key": "", "reason": "wall-clock limit of 10000 ms"}
    K.write(K.build(decls, [row, applied], {}), tmp_path / "catalogue")
    (tmp_path / "page.js").write_text(CS.script(), encoding="utf-8")
    run = subprocess.run([shutil.which("node") or "node", str(Path(__file__).parent / "catalogue_page_harness.js"), str(tmp_path / "page.js"),
                          str(tmp_path), "1"], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    drawn = json.loads(run.stdout)
    assert drawn["count"] == "1 of 1 checked entries"
    assert "linked only by a positivity fact" in drawn["head"]
    detail = drawn["detail"]
    assert "<li>source 1, conclusion supplies a hypothesis of source 2: <code>0 &lt; K</code></li>" in detail, detail
    assert "not established: the attempt ran out of its time or heartbeat budget" in detail and "wall-clock limit" in detail


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_catalogue_page_script_parses(tmp_path):
    # the script is JavaScript kept in a Python string: nothing else parses it before a browser does
    import subprocess

    from lean4_explainer_implications import catalogue_site as CS

    node = shutil.which("node") or "node"

    def parses(source: str) -> bool:
        path = tmp_path / "catalogue.js"
        path.write_text(source, encoding="utf-8")
        return subprocess.run([node, "--check", str(path)], capture_output=True, timeout=60).returncode == 0

    script = CS.script()
    good = parses(script)
    assert good
    # the check can fail: an unbalanced parenthesis in the same expression is rejected
    marker = '"<dt>Instantiation attempt</dt><dd>" +'
    assert marker in script
    broken = parses(script.replace(marker, marker[:-1] + ") +", 1))
    assert not broken
