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
]
ONE = ("Fx.fine_of_good",)
BAD_EDGES = [
    # a valid theorem with the wrong statement must fail
    _edge(id="true", sources=ONE, bridge="bridge_true", bridge_file="bridges/Bad.lean"),
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
    assert s["target_conclusion"] == "1 ≤ Fx.size n" and s["contract_conclusion"] == "n + 1 ≤ Fx.size n"


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
    ],
)
def test_a_bridge_that_does_not_prove_its_contract_fails(checked, case, status, says):
    r = checked[case]
    assert r["status"] == status and says in r["reason"], r


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
    row = lambda i, s, t, **kw: {"id": i, "status": "checked", "rule": "target", "source_keys": s, "target_key": t, "sources": s,  # noqa: E731
                                  "statement": i, "statement_hash": i, **kw}
    results = [row("1", ["a"], "b"), row("2", ["c"], "d"), row("3", ["b"], "c"),
               {**row("i1", ["a"], "b"), "status": "checked-instantiated", "derivation": "1", "instantiated_axioms": ["propext"], "env_modules": 2},
               {**row("i2", ["c"], "d"), "status": "budget", "derivation": "2", "reason": "wall-clock limit of 10000 ms"},
               {**row("i3", ["b"], "c"), "status": "instantiation-circular", "derivation": "3"}]
    cat = K.build(decls, results, {})
    got = {i["id"]: i for i in cat["implications"]}
    assert sorted(got) == ["1", "2", "3"]
    assert got["1"]["state"] == "checked-instantiated" and got["1"]["instantiated_axioms"] == ["propext"]
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
    marker = '"<dt>Applied to the released theorems</dt><dd>" +'
    assert marker in script
    broken = parses(script.replace(marker, marker[:-1] + ") +", 1))
    assert not broken
