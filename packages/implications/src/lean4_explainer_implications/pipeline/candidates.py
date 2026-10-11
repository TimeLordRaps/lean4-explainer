"""Structural retrieval: which statements to try against which, per rule, within fixed bounds.

Only Lean's own structure is used: the head of each statement's conclusion after unfolding corpus definitions, the
heads of its parts (`∧`, `↔`, `∃`), the heads of its hypotheses, and the constants it mentions. A pair is proposed
only when the heads fit the rule and the two statements share a rare constant (one few statements mention). Names,
doc strings and which file a declaration sits in are never used: nothing is inferred from vocabulary. Lemmas Lean
generates (a constructor's injectivity, equation lemmas, `sizeOf_spec`) have no source position and are never
proposed: they are not stated results.

Proposing is cheap and says nothing: every candidate is attempted in Lean, and only a kernel-checked derivation
counts.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

GENERIC_HEADS = {"<local>", "<sort>", "<pi>", "<lambda>", "<literal>", "<other>", "True", "False"}
ORDER_HEADS = {"LE.le", "LT.lt", "GE.ge", "GT.gt"}
# a hypothesis with one of these heads says too little on its own to make a composition worth proposing
WEAK_LINK_HEADS = GENERIC_HEADS | {"Eq", "Ne", "Not", "Membership.mem", "Iff", "And", "Or"}


@dataclass(frozen=True)
class Bounds:
    per_target: int = 6  # single-source candidates per target
    per_link: int = 3  # second sources per (source, target)
    per_compose: int = 4  # first sources per composition partner
    rare_df: int = 25  # a constant mentioned by at most this many statements is rare
    min_shared: int = 1  # rare constants a pair must share


@dataclass(frozen=True)
class Candidate:
    rule: str  # target | compose
    sources: tuple[str, ...]  # declaration keys
    target: str  # declaration key, "" for compose
    match: str  # the structural fit that proposed it
    shared: tuple[str, ...]  # the rare constants the statements share
    score: float


@dataclass
class Proposal:
    candidates: list[Candidate] = field(default_factory=list)
    per_rule: Counter = field(default_factory=Counter)
    statements: int = 0
    targets: int = 0
    rare_constants: int = 0
    generated: int = 0  # statements and targets left out because Lean generated them


def generated(d: dict) -> bool:
    """Whether Lean generated the declaration: extraction records every declaration's source range, and a generated
    one has none."""
    return "range" in d and not d["range"]


def is_statement(d: dict) -> bool:
    return d.get("kind") == "theorem" and bool(d.get("prop")) and not d.get("instance") and isinstance(d.get("norm"), dict)


def provides(d: dict) -> set[str]:
    """The heads a statement can conclude: its conclusion, and each part of a conjunction or equivalence."""
    n = d["norm"]
    return {n["conclusion_head"], *n.get("part_heads", [])} - GENERIC_HEADS


def propose(statements: list[dict], targets: Iterable[dict], bounds: Bounds = Bounds()) -> Proposal:
    """Candidates among `statements` (one layer: challenge statements, or a solution family's declarations) for each
    of `targets`, and compositions among the statements."""
    targets = list(targets)
    stated = [d for d in statements if not generated(d)]
    out = Proposal(statements=len(stated), generated=len({d["key"] for d in [*statements, *targets] if generated(d)}))
    statements, targets = stated, [t for t in targets if not generated(t)]
    df: Counter = Counter()
    for d in statements:
        df.update(set(d["norm"]["uses"]))
    n = max(1, len(statements))
    rare = {c for c, k in df.items() if k <= bounds.rare_df}
    out.rare_constants = len(rare)
    idf = {c: math.log(n / df[c]) + 1.0 for c in rare}
    anchors = {d["key"]: set(d["norm"]["uses"]) & rare for d in statements}

    def shared(a: dict, b: dict) -> tuple[tuple[str, ...], float]:
        common = anchors[a["key"]] & anchors[b["key"]]
        return tuple(sorted(common)), sum(idf[c] for c in common)

    by_head: dict[str, list[dict]] = defaultdict(list)
    for d in statements:
        for h in provides(d):
            by_head[h].append(d)
    order_like = [d for d in statements if d["norm"]["conclusion_head"] in ORDER_HEADS]
    equations = [d for d in statements if d["norm"]["conclusion_head"] == "Eq"]
    existentials = [d for d in statements if d["norm"]["conclusion_head"] == "Exists"]
    seen: set[tuple] = set()

    def add(c: Candidate) -> None:
        key = (c.rule, c.sources, c.target)
        if key not in seen:
            seen.add(key)
            out.candidates.append(c)
            out.per_rule[c.match] += 1

    for t in targets:
        out.targets += 1
        head = t["norm"]["conclusion_head"]
        pool: list[tuple[str, dict]] = []
        if head not in GENERIC_HEADS:
            pool += [("conclusion matches", s) for s in by_head.get(head, [])]
        if head in ORDER_HEADS:
            pool += [("bound transfer", s) for s in order_like]
        if head == "Exists":
            wt = (t["norm"].get("exists") or {}).get("witness_type")
            pool += [("witness transport", s) for s in existentials if (s["norm"].get("exists") or {}).get("witness_type") == wt]
        pool += [("equation", s) for s in equations]
        ranked: dict[str, tuple[float, str, tuple[str, ...], dict]] = {}
        for match, s in pool:
            if s["key"] == t["key"]:
                continue
            common, score = shared(s, t)
            if len(common) < bounds.min_shared:
                continue
            if s["key"] not in ranked or ranked[s["key"]][0] < score:
                ranked[s["key"]] = (score, match, common, s)
        best = sorted(ranked.values(), key=lambda r: (-r[0], r[3]["key"]))[: bounds.per_target]
        for score, match, common, s in best:
            add(Candidate("target", (s["key"],), t["key"], match, common, score))
            if match != "conclusion matches":
                continue
            # a second source that supplies one of the first source's hypotheses
            hyps = set(s["norm"]["hyp_heads"]) - WEAK_LINK_HEADS
            links: dict[str, tuple[float, tuple[str, ...], dict]] = {}
            for h in hyps:
                for s1 in by_head.get(h, []):
                    if s1["key"] in (s["key"], t["key"]):
                        continue
                    common1, score1 = shared(s1, s)
                    if len(common1) < bounds.min_shared:
                        continue
                    if s1["key"] not in links or links[s1["key"]][0] < score1:
                        links[s1["key"]] = (score1, common1, s1)
            for score1, common1, s1 in sorted(links.values(), key=lambda r: (-r[0], r[2]["key"]))[: bounds.per_link]:
                add(Candidate("target", (s1["key"], s["key"]), t["key"], "a second source supplies a hypothesis", common1, score1))

    # compositions: the first source's conclusion is one of the second's hypotheses
    for b in statements:
        hyps = set(b["norm"]["hyp_heads"]) - WEAK_LINK_HEADS
        partners: dict[str, tuple[float, tuple[str, ...], dict]] = {}
        for h in hyps:
            for a in by_head.get(h, []):
                if a["key"] == b["key"]:
                    continue
                common, score = shared(a, b)
                if len(common) < bounds.min_shared:
                    continue
                if a["key"] not in partners or partners[a["key"]][0] < score:
                    partners[a["key"]] = (score, common, a)
        for score, common, a in sorted(partners.values(), key=lambda r: (-r[0], r[2]["key"]))[: bounds.per_compose]:
            add(Candidate("compose", (a["key"], b["key"]), "", "conclusion supplies a hypothesis", common, score))
    return out
