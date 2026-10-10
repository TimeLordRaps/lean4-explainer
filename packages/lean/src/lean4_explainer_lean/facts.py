"""What a Lean run reports about one file, and how a declaration's axioms are classified."""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass, field

STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
MAX_GOAL_CHARS = 1500


@dataclass(frozen=True)
class Step:
    line: int  # 1-based
    column: int
    tactic: str  # first line of the tactic's source
    before: tuple[str, ...]  # goals before the step
    after: tuple[str, ...]  # goals after the step


@dataclass(frozen=True)
class DeclFacts:
    name: str
    line: int
    axioms: tuple[str, ...] | None  # None: Lean has no constant of this name
    steps: tuple[Step, ...] = ()
    statement_uses: tuple[str, ...] = ()  # constants in the type, kernel terms with instances and coercions left out
    proof_uses: tuple[str, ...] = ()  # constants in the proof or value, with the same filter
    hidden: int = 0  # how many instances, coercions and auxiliary constants were left out


@dataclass(frozen=True)
class FileFacts:
    status: str  # "ok" | "failed" | "unavailable"
    reason: str = ""
    errors: tuple[str, ...] = ()  # error messages Lean printed (the proofs may be incomplete)
    decls: tuple[DeclFacts, ...] = field(default_factory=tuple)

    def find(self, name: str, line: int) -> DeclFacts | None:
        return next((d for d in self.decls if d.name == name and d.line == line), None)


def classify(axioms: tuple[str, ...] | None) -> tuple[str, str]:
    """(kind, label). Kinds: unknown, none, standard, sorry, extra."""
    if axioms is None:
        return "unknown", "trust unknown: Lean has no constant by this name"
    if not axioms:
        return "none", "no axioms"
    if "sorryAx" in axioms:
        return "sorry", "depends on sorry"
    extra = sorted(a for a in axioms if a not in STANDARD_AXIOMS)
    if extra:
        return "extra", "extra axioms: " + ", ".join(extra)
    return "standard", "standard axioms: " + ", ".join(sorted(axioms))


def parse_probe(output: str, declarations: list[tuple[str, int]]) -> FileFacts:
    """Read the probe's JSON lines. `declarations` are (name, 1-based line) pairs from the text scan."""
    steps: dict[tuple[int, int], Step] = {}
    axioms: dict[str, tuple[str, ...] | None] = {}
    uses: dict[str, tuple[tuple[str, ...], tuple[str, ...], int]] = {}
    errors: list[str] = []
    for raw in output.splitlines():
        if not raw.startswith("{"):
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = item.get("kind")
        if kind == "tactic":
            first = item["tactic"].split("\n", 1)[0].strip()
            if not first or first == "by":
                continue
            key = (item["line"], item["column"])
            step = Step(
                item["line"],
                item["column"],
                first,
                tuple(_clip(g) for g in item["before"]),
                tuple(_clip(g) for g in item["after"]),
            )
            if key not in steps or len(item["tactic"]) < len(steps[key].tactic):  # keep the innermost node at a position
                steps[key] = step
        elif kind == "decl":
            axioms[item["name"]] = None if item["axioms"] is None else tuple(item["axioms"])
            uses[item["name"]] = (
                tuple(item.get("statement_uses", ())),
                tuple(item.get("proof_uses", ())),
                int(item.get("hidden", 0)),
            )
        elif kind == "message" and item.get("severity") == "error":
            errors.append(f"line {item['line']}: {item['text'].splitlines()[0] if item['text'] else ''}")
    ordered = sorted(declarations, key=lambda d: d[1])
    lines = [line for _, line in ordered]
    grouped: dict[int, list[Step]] = {i: [] for i in range(len(ordered))}
    for key in sorted(steps):
        slot = bisect_right(lines, key[0]) - 1
        if slot >= 0:
            grouped[slot].append(steps[key])
    decls = tuple(
        DeclFacts(name, line, axioms.get(name), tuple(grouped[i]), *uses.get(name, ((), (), 0)))
        for i, (name, line) in enumerate(ordered)
    )
    return FileFacts("ok", errors=tuple(errors), decls=decls)


def _clip(goal: str) -> str:
    return goal if len(goal) <= MAX_GOAL_CHARS else goal[:MAX_GOAL_CHARS] + "\n… (truncated)"


def to_json(facts: FileFacts) -> str:
    return json.dumps(
        {
            "status": facts.status,
            "reason": facts.reason,
            "errors": list(facts.errors),
            "decls": [
                {
                    "name": d.name,
                    "line": d.line,
                    "axioms": None if d.axioms is None else list(d.axioms),
                    "steps": [[s.line, s.column, s.tactic, list(s.before), list(s.after)] for s in d.steps],
                    "statement_uses": list(d.statement_uses),
                    "proof_uses": list(d.proof_uses),
                    "hidden": d.hidden,
                }
                for d in facts.decls
            ],
        },
        ensure_ascii=False,
    )


def from_json(text: str) -> FileFacts:
    raw = json.loads(text)
    return FileFacts(
        raw["status"],
        raw["reason"],
        tuple(raw["errors"]),
        tuple(
            DeclFacts(
                d["name"],
                d["line"],
                None if d["axioms"] is None else tuple(d["axioms"]),
                tuple(Step(s[0], s[1], s[2], tuple(s[3]), tuple(s[4])) for s in d["steps"]),
                tuple(d["statement_uses"]),
                tuple(d["proof_uses"]),
                d["hidden"],
            )
            for d in raw["decls"]
        ),
    )
