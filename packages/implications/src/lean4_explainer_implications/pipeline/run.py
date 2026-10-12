"""The stages of a run, each reading and writing JSON in the run directory.

    <run>/<layer>/extract/…            Lean's extraction output, per batch
    <run>/<layer>/extract.json         the batches: which modules imported together, which failed and why
    <run>/<layer>/declarations.jsonl   every declaration, with its identity and role
    <run>/<layer>/candidates.json      what structural retrieval proposed, per rule
    <run>/<layer>/results.jsonl        every attempt's outcome
    <run>/<layer>/discover.json        the batch's counts and costs
    <run>/cache.jsonl                  attempt results by key (policy, budget, environment)

A layer is a set of modules read together: `statements` (the ComparatorChallenges copies, which state each released
result with `sorry`) or `solutions` (the solution modules of the families that were built, with their proofs).
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from . import attempts as A
from . import candidates as C
from . import extract as X
from .workspace import Workspace


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def read_declarations(run: Path, layer: str) -> list[dict]:
    path = run / layer / "declarations.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def read_results(run: Path, layer: str) -> list[dict]:
    path = run / layer / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def released_declaration(statement: dict, by_name: dict[str, list[dict]]) -> tuple[dict | None, str]:
    """Select the released copy of one exact challenge declaration, or fail closed when provenance is ambiguous."""
    candidates = by_name.get(statement["name"], [])
    if not candidates:
        return None, "solution not built"
    family = statement.get("family")
    same_family = [d for d in candidates if d.get("family") == family]
    if family and not same_family:
        # Two independent challenge environments may legally declare the same Lean name. A theorem from another
        # family is not this statement's released proof, even when the elaborated types happen to be identical.
        return None, "solution not built"
    pool = same_family if family else candidates
    same_type = [d for d in pool if d.get("type_hash") == statement.get("type_hash")]
    if len(same_type) == 1:
        return same_type[0], ""
    if len(pool) == 1:
        return pool[0], ""  # Lean still checks a unique released declaration whose statement changed
    keys = ", ".join(sorted(d["key"] for d in (same_type or pool)))
    return None, f"ambiguous released solution for {statement['name']}: {keys}"


def extract_layer(ws: Workspace, identity: X.Identity, modules: list[str], run: Path, layer: str, batch_size: int = 500, log: Callable[[str], None] = print, commit_gb: float | None = None) -> dict:
    started = time.monotonic()
    record = X.run_extraction(ws, modules, run / layer / "extract", batch_size, log=log, commit_gb=commit_gb)
    decls = X.load_declarations(record, run / layer / "extract", identity, ws.corpus_root)
    with (run / layer / "declarations.jsonl").open("w", encoding="utf-8") as handle:
        for d in decls:
            handle.write(json.dumps(d, ensure_ascii=False) + "\n")
    extracted = {m for env in record.environments for m in env}
    summary = {
        "layer": layer, "policy": A.policy(), "modules_requested": len(modules), "modules_added": record.added,
        "modules_extracted": len(extracted),
        "modules_failed": [{"module": m, "error": e[-500:]} for m, e in record.failed_modules()],
        "environments": [len(e) for e in record.environments],
        "splits": [{"modules": len(b.modules), "error": b.error[-300:]} for b in record.batches if b.status == "split"],
        "clashes": record.clashes, "moved_on_import": [b.error for b in record.batches if b.status == "clash"],
        "declarations": len(decls), "by_role": dict(Counter(d["role"] for d in decls)),
        "failed_declarations": sum(b.failed_declarations for b in record.batches),
        "by_kind": dict(Counter(d.get("kind", "?") for d in decls)),
        "unreadable": sum(d["role"] == "unreadable" for d in decls),
        "with_sorry": sum(bool(d.get("sorry")) for d in decls),
        "statements": sum(C.is_statement(d) for d in decls),
        "seconds": round(time.monotonic() - started, 1), "batches": record.to_json()["batches"],
    }
    _write_json(run / layer / "extract.json", summary)
    return summary


def _env_modules(run: Path, layer: str) -> list[list[str]]:
    batches = json.loads((run / layer / "extract.json").read_text(encoding="utf-8"))["batches"]
    return [b["modules"] for b in batches if b["status"] == "ok"]


def _clashes(run: Path, layer: str) -> dict[frozenset[str], str]:
    """The pairs of the layer's modules that cannot be imported together, with a name both declare: those found before
    importing, and those an import found."""
    data = json.loads((run / layer / "extract.json").read_text(encoding="utf-8"))
    out = {frozenset(c["modules"]): c["name"] for c in data.get("clashes", [])}
    for moved in data.get("moved_on_import", []):
        head, _, name = moved.partition(" both declare ")
        a, _, b = head.partition(" and ")
        out.setdefault(frozenset({a, b}), name)
    return out


def _clash_in(modules, clashes: dict[frozenset[str], str], others=None) -> tuple[str, str, str] | None:
    """A pair that clashes: within `modules`, or (with `others`) between the two."""
    pool = sorted(modules)
    for i, a in enumerate(pool):
        for b in (sorted(others) if others is not None else pool[i + 1 :]):
            name = clashes.get(frozenset({a, b}))
            if name is not None and a != b:
                return (a, b, name) if a < b else (b, a, name)
    return None


def plan_environments(needs, envs, clashes: dict[frozenset[str], str], limit: int = 500) -> tuple[list[tuple[str, ...]], dict[int, str]]:
    """The modules each candidate is attempted in. `needs[i]` is (the extraction environments of its declarations,
    their modules). Declarations from one environment: that environment's modules, as extracted. From several: their
    modules, packed with other such candidates, in order, into shared environments of at most `limit` modules in which
    no two modules declare the same name. A candidate whose own modules clash is blocked, with the reason: no
    environment holds them all."""
    out: list[tuple[str, ...]] = []
    blocked: dict[int, str] = {}
    groups: list[set[str]] = []
    member: dict[int, int] = {}
    for i, (env_ids, modules) in enumerate(needs):
        if len(env_ids) == 1:
            out.append(tuple(envs[next(iter(env_ids))]))
            continue
        out.append(())
        clash = _clash_in(modules, clashes)
        if clash:
            blocked[i] = f"no environment holds both {clash[0]} and {clash[1]}: each declares {clash[2]}"
            continue
        for g, group in enumerate(groups):
            if len(group | modules) <= limit and not _clash_in(group - modules, clashes, modules - group):
                group |= modules
                member[i] = g
                break
        else:
            groups.append(set(modules))
            member[i] = len(groups) - 1
    for i, g in member.items():
        out[i] = tuple(sorted(groups[g]))
    return out, blocked


def discover_layer(ws: Workspace, run: Path, layer: str, bounds: C.Bounds, budget: A.Budget, log: Callable[[str], None] = print,
                   jobs: int = 1, instantiate: bool = False, targets_roles: tuple[str, ...] = ("statement", "released"),
                   chunk: int = 250, commit_gb: float | None = None, sources_roles: tuple[str, ...] | None = None,
                   env_limit: int = 500) -> dict:
    """Propose candidates among the layer's statements (those with `sources_roles`, default all) for each statement
    with `targets_roles`, attempt them in Lean, and record the batch. A candidate whose modules cannot be imported
    together is not attempted; it is recorded as blocked, with the name two of its modules both declare."""
    started = time.monotonic()
    decls = read_declarations(run, layer)
    by_key = {d["key"]: d for d in decls}
    envs = _env_modules(run, layer)
    statements = [d for d in decls if C.is_statement(d) and (sources_roles is None or d["role"] in sources_roles or d["role"] in targets_roles)]
    targets = [d for d in statements if d["role"] in targets_roles]
    proposal = C.propose(statements, targets, bounds)
    _write_json(run / layer / "candidates.json", {
        "bounds": bounds.__dict__, "statements": proposal.statements, "targets": proposal.targets, "generated": proposal.generated,
        "rare_constants": proposal.rare_constants, "per_match": dict(proposal.per_rule),
        "candidates": [c.__dict__ for c in proposal.candidates]})
    needs = []
    for c in proposal.candidates:
        ds = [by_key[k] for k in list(c.sources) + ([c.target] if c.target else [])]
        needs.append(({d["env"] for d in ds}, {d["module"] for d in ds}))
    planned, blocked = plan_environments(needs, envs, _clashes(run, layer), env_limit)
    attempts = []
    for i, c in enumerate(proposal.candidates):
        if i in blocked:
            continue
        attempts.append(A.Attempt(c.rule, tuple(by_key[k]["name"] for k in c.sources), by_key[c.target]["name"] if c.target else "",
                                  planned[i], instantiate,
                                  {"source_keys": list(c.sources), "target_key": c.target, "match": c.match, "shared": list(c.shared), "layer": layer}))
    blocked_rows = [{"source_keys": list(proposal.candidates[i].sources), "target_key": proposal.candidates[i].target,
                     "rule": proposal.candidates[i].rule, "match": proposal.candidates[i].match, "reason": why} for i, why in sorted(blocked.items())]
    if blocked_rows:
        log(f"discover: {len(blocked_rows)} candidates not attempted: their modules declare the same name, so no environment holds them")
    cache = A.Cache(run / "cache.jsonl")
    results, stats = A.run_attempts(ws, attempts, budget, run / layer / "attempts", cache, log=log, jobs=jobs, chunk=chunk, commit_gb=commit_gb)
    with (run / layer / "results.jsonl").open("w", encoding="utf-8") as handle:
        for r in results:
            handle.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {
        "layer": layer, "policy": A.policy(), "budget": budget.to_json(), "bounds": bounds.__dict__,
        "targets_roles": list(targets_roles), "sources_roles": list(sources_roles) if sources_roles else "all",
        "statements": proposal.statements, "targets": proposal.targets, "generated_left_out": proposal.generated,
        "candidates": len(proposal.candidates), "candidates_per_match": dict(proposal.per_rule),
        "blocked": blocked_rows, "blocked_per_match": dict(Counter(b["match"] for b in blocked_rows)),
        "blocked_module_pairs": len({b["reason"] for b in blocked_rows}), "env_limit": env_limit,
        "attempts": stats.attempts, "results": len(results), "cached": stats.cached, "run": stats.run,
        "environments": stats.environments, "lean_processes": stats.lean_processes, "lean_seconds": round(stats.lean_seconds, 1),
        "process_failures": stats.process_failures,
        "outcomes": dict(Counter(r["status"] for r in results)),
        "outcomes_per_match": {m: dict(Counter(r["status"] for r in results if r.get("match") == m)) for m in proposal.per_rule},
        "attempt_ms_total": sum(r.get("ms", 0) for r in results), "attempt_ms_max": max((r.get("ms", 0) for r in results), default=0),
        "seconds": round(time.monotonic() - started, 1),
    }
    _write_json(run / layer / "discover.json", summary)
    return summary


def instantiate_checked(ws: Workspace, run: Path, from_layer: str, solutions_layer: str, budget: A.Budget, log: Callable[[str], None] = print,
                        jobs: int = 1, commit_gb: float | None = None) -> dict:
    """Apply checked derivations from `from_layer` (statements) to the released theorems, where the sources'
    solution modules were built: the sources from their solution modules, the target from its own solution module
    when that was built too, else from its challenge statement."""
    started = time.monotonic()
    stmts = {d["key"]: d for d in read_declarations(run, from_layer)}
    released: dict[str, list[dict]] = {}
    for declaration in read_declarations(run, solutions_layer):
        if declaration["role"] == "released" and not declaration.get("sorry"):
            released.setdefault(declaration["name"], []).append(declaration)
    attempts, blocked = [], []
    for r in read_results(run, from_layer):
        if r.get("status") not in A.CHECKED:
            continue
        srcs = [stmts[k] for k in r["source_keys"]]
        tgt = stmts.get(r.get("target_key", ""))
        selected = [(s, *released_declaration(s, released)) for s in srcs]
        unavailable = [(s, reason) for s, actual, reason in selected if actual is None]
        if unavailable:
            reasons = [f"{reason} for {s['name']}" if reason == "solution not built" else reason for s, reason in unavailable]
            blocked.append({"id": r["id"], "reason": "; ".join(reasons)})
            continue
        actual_sources = [actual for _s, actual, _reason in selected]
        actual_target = None
        if tgt is not None:
            actual_target, target_reason = released_declaration(tgt, released)
            if actual_target is None and target_reason.startswith("ambiguous"):
                blocked.append({"id": r["id"], "reason": target_reason})
                continue
            if actual_target is None:  # a target solution need not be built: the exact challenge statement remains
                actual_target = tgt
        modules = {s["module"] for s in actual_sources}
        if actual_target is not None:
            modules.add(actual_target["module"])
        attempts.append(A.Attempt(r["rule"], tuple(s["name"] for s in actual_sources), actual_target["name"] if actual_target else "",
                                  tuple(sorted(modules)), True,
                                  {"source_keys": r["source_keys"], "target_key": r.get("target_key", ""),
                                   "verification_source_keys": [s["key"] for s in actual_sources],
                                   "verification_target_key": actual_target["key"] if actual_target else "",
                                   "match": r.get("match", ""), "layer": "instantiation", "derivation": r["id"]}))
    results, stats = A.run_attempts(ws, attempts, budget, run / "instantiation" / "attempts", A.Cache(run / "cache.jsonl"), log=log, jobs=jobs, commit_gb=commit_gb)
    (run / "instantiation").mkdir(parents=True, exist_ok=True)
    with (run / "instantiation" / "results.jsonl").open("w", encoding="utf-8") as handle:
        for r in results:
            handle.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"checked_derivations": sum(1 for r in read_results(run, from_layer) if r.get("status") in A.CHECKED),
               "attempts": stats.attempts, "attempted": len(attempts), "results": len(results), "blocked": blocked,
               "cached": stats.cached, "run": stats.run, "environments": stats.environments,
               "lean_processes": stats.lean_processes, "process_failures": stats.process_failures,
               "outcomes": dict(Counter(r["status"] for r in results)),
               "lean_seconds": round(stats.lean_seconds, 1), "seconds": round(time.monotonic() - started, 1)}
    _write_json(run / "instantiation" / "instantiate.json", summary)
    return summary
