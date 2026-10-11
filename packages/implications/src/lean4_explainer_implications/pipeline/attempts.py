"""Run candidates as bounded Lean attempts, grouped by the environment that holds their declarations, with a cache.

Every result is keyed by the rule set (policy version and the digest of Pipeline.lean), the budget, and the
environment's identity (toolchain, pinned packages, and the traces of the corpus modules imported). A failure is
cached under the same key: a larger budget or a changed rule set tries it again; nothing else does.

Outcomes are only what Lean said. `checked` and `checked-instantiated` are kernel-checked. `no-proof` means the
rules found nothing within the depth; `budget` means the time or heartbeat limit was reached. Neither says the
implication is false.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import POLICY_VERSION
from . import lean as L
from .workspace import Workspace, toolchain_version

CHECKED = ("checked", "checked-instantiated")
UNRESOLVED = ("no-proof", "budget", "not-run", "env-error", "error", "kernel-rejected", "instantiation-failed")


@dataclass(frozen=True)
class Budget:
    heartbeats: int = 200000  # per attempt, in units of the maxHeartbeats option
    ms: int = 20000  # per attempt, wall clock
    depth: int = 2
    discharge_heartbeats: int = 20000  # per tactic call
    dischargers: tuple[str, ...] = ("omega", "norm_num", "positivity", "linarith")
    bound_closers: tuple[str, ...] = ("linarith", "nlinarith", "omega")

    def to_json(self) -> dict:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(self).items()}


def policy() -> str:
    return f"{POLICY_VERSION}:{L.pipeline_digest()}"


def attempt_id(rule: str, sources: Iterable[str], target: str, instantiate: bool) -> str:
    raw = json.dumps([rule, list(sources), target, instantiate])
    return "a" + hashlib.sha256(raw.encode()).hexdigest()[:12]


class Cache:
    """Results by key, kept as JSON lines (appended; the last line for a key wins)."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, dict] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.entries[row["cache_key"]] = row

    def get(self, key: str) -> dict | None:
        return self.entries.get(key)

    def put(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for row in rows:
                self.entries[row["cache_key"]] = row
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


_TOOLCHAIN: dict[str, str] = {}


def environment_identity(ws: Workspace, modules: Iterable[str]) -> str:
    """The identity of an environment: the toolchain, the pinned packages, and each imported corpus module's trace
    (its source, and its imports' traces)."""
    root = str(ws.root)
    if root not in _TOOLCHAIN:
        _TOOLCHAIN[root] = toolchain_version(ws)
    manifest = ws.root / "lake-manifest.json"
    packages = {p["name"]: p["rev"] for p in json.loads(manifest.read_text(encoding="utf-8"))["packages"]} if manifest.is_file() else {}
    traces = {}
    for m in sorted(set(modules)):
        trace = ws.trace_dir / (m + ".json")
        traces[m] = json.loads(trace.read_text(encoding="utf-8"))["digest"] if trace.is_file() else hashlib.sha256(ws.olean(m).read_bytes()).hexdigest() if ws.olean(m).is_file() else "missing"
    blob = json.dumps({"toolchain": _TOOLCHAIN[root], "packages": packages, "modules": traces}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


@dataclass
class Attempt:
    rule: str
    sources: tuple[str, ...]  # declaration names
    target: str
    modules: tuple[str, ...]  # what the environment must import
    instantiate: bool = False
    meta: dict = field(default_factory=dict)  # carried into the result (candidate keys, match, …)

    @property
    def id(self) -> str:
        return attempt_id(self.rule, self.sources, self.target, self.instantiate)


@dataclass
class RunStats:
    environments: int = 0
    attempts: int = 0
    cached: int = 0
    run: int = 0
    lean_processes: int = 0
    lean_seconds: float = 0.0
    process_failures: list[str] = field(default_factory=list)


def run_attempts(
    ws: Workspace,
    attempts: list[Attempt],
    budget: Budget,
    out_dir: Path,
    cache: Cache,
    log: Callable[[str], None] = print,
    chunk: int = 250,
    jobs: int = 1,
    corpus: tuple[str, ...] | None = None,  # module prefixes (default: the workspace's)
    commit_gb: float | None = None,
) -> tuple[list[dict], RunStats]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = RunStats(attempts=len(attempts))
    pol = policy()
    prefixes = list(corpus if corpus is not None else ws.corpus_prefixes)
    groups: dict[tuple[str, ...], list[Attempt]] = defaultdict(list)
    for a in attempts:
        groups[tuple(sorted(set(a.modules)))].append(a)
    stats.environments = len(groups)
    results: list[dict] = []
    work: list[tuple[tuple[str, ...], str, list[Attempt]]] = []
    for modules, group in groups.items():
        env_id = environment_identity(ws, modules)
        todo = []
        for a in group:
            key = hashlib.sha256(json.dumps([pol, budget.to_json(), env_id, prefixes, a.rule, a.sources, a.target, a.instantiate]).encode()).hexdigest()
            hit = cache.get(key)
            if hit is not None:
                stats.cached += 1
                results.append({**hit, **a.meta, "cached": True})
            else:
                a.meta["cache_key"] = key
                todo.append(a)
        for i in range(0, len(todo), chunk):
            work.append((modules, env_id, todo[i : i + chunk]))

    def one(item: tuple[tuple[str, ...], str, list[Attempt]]) -> list[dict]:
        modules, env_id, part = item
        tag = hashlib.sha256(json.dumps([env_id, [a.id for a in part]]).encode()).hexdigest()[:10]
        plan_path, out_path = (out_dir / f"plan-{tag}.json").resolve(), (out_dir / f"result-{tag}.jsonl").resolve()
        plan = {"imports": list(modules), "corpus": prefixes, **budget.to_json(),
                "attempts": [{"id": a.id, "rule": a.rule, "sources": list(a.sources), "target": a.target, "instantiate": a.instantiate} for a in part]}
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        timeout = 600 + len(part) * (budget.ms // 1000 + 5)
        kwargs = {} if commit_gb is None else {"commit_gb": commit_gb}
        run = L.run(ws.env(), ws.root, ["attempt", str(plan_path), str(out_path)], timeout, log, **kwargs)
        got, imported = {}, False
        if out_path.is_file():
            for line in out_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if "id" in row:
                        got[row["id"]] = row
                    else:  # the first line, written once the environment imported
                        imported = True
        rows = []
        for a in part:
            row = got.get(a.id)
            if row is None:
                why = "the Lean process stopped before this attempt" if imported or got else "the environment did not import"
                row = {"id": a.id, "status": "not-run" if imported or got else "env-error", "reason": f"{why}: {run.tail(400)}",
                       "rule": a.rule, "sources": list(a.sources), "target": a.target}
            row.update(env_id=env_id, env_modules=len(modules), policy=pol, budget=budget.to_json(), cache_key=a.meta["cache_key"])
            rows.append({**row, **{k: v for k, v in a.meta.items() if k != "cache_key"}})
        log(f"attempts: {len(part)} in an environment of {len(modules)} modules: "
            + ", ".join(f"{s} {n}" for s, n in sorted(_count(r["status"] for r in rows).items())) + f" ({run.seconds:.0f}s)")
        stats.lean_processes += 1
        stats.lean_seconds += run.seconds
        if not run.ok:
            stats.process_failures.append(f"{len(modules)} modules: {run.tail(300)}")
            log(f"attempts: the Lean process ended with code {run.code}: {run.tail(300)}")
        # an environment that did not import is not cached: the cause is outside the attempt
        cache.put([r for r in rows if r["status"] not in ("env-error", "not-run")])
        return rows

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for rows in pool.map(one, work):
            results.extend(rows)
            stats.run += len(rows)
    return results, stats


def _count(xs: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out
