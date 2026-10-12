"""Read declarations from compiled modules, batch by batch, and give each its identity in the corpus.

A batch imports its modules together. Two modules that declare the same name cannot be imported together (openai/math
restates shared definitions in several challenge files). Lean's error names both, so the module that failed is moved
to another batch, one with no module it is known to clash with, and the batch is tried again. Any other failure splits
the batch in two. The batches that import are separate environments, and every move and split is recorded.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import lean as L
from .workspace import Workspace, closure


@dataclass(frozen=True)
class Identity:
    repo: str  # e.g. "openai/math"
    revision: str  # the commit the modules were read at
    path_prefix: str = ""  # the Lean root inside the repository, e.g. "lean/"

    def path(self, module: str) -> str:
        return f"{self.path_prefix}{module.replace('.', '/')}.lean"

    def key(self, module: str, name: str) -> str:
        return f"{self.repo}@{self.revision[:12]}:{module}:{name}"


CLASH = re.compile(r"import (\S+) failed, environment already contains '([^']+)' from (\S+)")


@dataclass
class Batch:
    modules: list[str]
    status: str  # ok | clash (a module moved out) | split | failed
    file: str = ""
    declarations: int = 0
    failed_declarations: int = 0
    import_ms: int = 0
    extract_ms: int = 0
    seconds: float = 0.0
    error: str = ""


@dataclass
class ExtractRecord:
    batches: list[Batch] = field(default_factory=list)
    clashes: list[dict] = field(default_factory=list)  # pairs of modules found to declare the same name, before importing
    added: list[str] = field(default_factory=list)  # modules extracted because they declare a theorem a challenge lists

    @property
    def environments(self) -> list[list[str]]:
        """The module sets that imported together."""
        return [b.modules for b in self.batches if b.status == "ok"]

    def failed_modules(self) -> list[tuple[str, str]]:
        return [(b.modules[0], b.error) for b in self.batches if b.status == "failed"]

    def to_json(self) -> dict:
        return {"batches": [asdict(b) for b in self.batches], "clashes": self.clashes}


def declared_names(ws: Workspace, modules: Sequence[str], out_dir: Path, log: Callable[[str], None] = print) -> dict[str, list[str]]:
    """The constants each module declares, read by Lean from the compiled files (no import, so it is fast and small)."""
    listing = (out_dir / "names.modules").resolve()
    target = (out_dir / "names.jsonl").resolve()
    listing.write_text("\n".join(modules) + "\n", encoding="utf-8")
    run = L.run(ws.env(), ws.root, ["names", str(target), str(listing)], 600, log, commit_gb=0)
    if not run.ok or not target.is_file():
        log(f"extract: could not read declared names ({run.tail(300)}); clashes will be found by importing")
        return {}
    out = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "names" in row:
            out[row["module"]] = row["names"]
    return out


def clash_graph(ws: Workspace, modules: Sequence[str], names: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """Which of `modules` cannot be imported together: two whose imports (themselves included) contain different
    modules declaring the same name. Returns module -> {other module: a name both sides declare}."""
    declarers: dict[str, set[str]] = {}
    for mod, ns in names.items():
        for n in ns:
            declarers.setdefault(n, set()).add(mod)
    shared = {n: ds for n, ds in declarers.items() if len(ds) > 1}
    closures = {m: set(closure(ws, [m])) | {m} for m in modules}
    out: dict[str, dict[str, str]] = {m: {} for m in modules}
    for n, ds in shared.items():
        groups: dict[frozenset[str], list[str]] = {}
        for m in modules:
            hit = frozenset(closures[m] & ds)
            if hit:
                groups.setdefault(hit, []).append(m)
        keys = list(groups)
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                if len(a | b) > 1:
                    for x in groups[a]:
                        for y in groups[b]:
                            out[x].setdefault(y, n)
                            out[y].setdefault(x, n)
    return out


def partition(modules: Sequence[str], graph: dict[str, dict[str, str]], batch_size: int) -> list[list[str]]:
    """Batches with no clash inside, in the given order: each module goes into the first batch that can take it."""
    batches: list[list[str]] = []
    for m in modules:
        for batch in batches:
            if len(batch) < batch_size and not any(o in graph.get(m, {}) for o in batch):
                batch.append(m)
                break
        else:
            batches.append([m])
    return batches


def run_extraction(ws: Workspace, modules: Sequence[str], out_dir: Path, batch_size: int = 500, timeout: int = 3600, log: Callable[[str], None] = print, commit_gb: float | None = None) -> ExtractRecord:
    out_dir.mkdir(parents=True, exist_ok=True)
    record = ExtractRecord()
    names = declared_names(ws, sorted({c for m in modules for c in closure(ws, [m])} | set(modules)), out_dir, log)
    # a solution module often proves its released theorems in modules it imports: extract those too (the challenge
    # specifications name the theorems; the challenge copies themselves are the statements layer)
    _, released = challenge_roles(ws.corpus_root)
    record.added = sorted(m for m, ns in names.items()
                          if m not in modules and not m.startswith("ComparatorChallenges.") and any(n in released for n in ns))
    if record.added:
        log(f"extract: {len(record.added)} more modules declare theorems the challenges list: {', '.join(record.added[:8])}")
        modules = [*modules, *record.added]
    graph = clash_graph(ws, modules, names) if names else {}
    pairs = sorted({tuple(sorted((a, b))) + (n,) for a, others in graph.items() for b, n in others.items()})
    record.clashes = [{"modules": [a, b], "name": n} for a, b, n in pairs]
    pending = partition(modules, graph, batch_size)
    if pairs:
        log(f"extract: {len(pairs)} pairs of modules declare the same name; {len(pending)} batches keep them apart")
    clashes: dict[str, set[str]] = {m: set(o) for m, o in graph.items()}  # module -> modules it cannot be imported with
    k = 0

    def place(mod: str) -> None:
        """Into the first pending batch with room and no known clash, else a new one."""
        for batch in pending:
            if len(batch) < batch_size and not (clashes.get(mod, set()) & set(batch)):
                batch.append(mod)
                return
        pending.append([mod])

    while pending:
        batch = pending.pop(0)
        if not batch:
            continue
        k += 1
        target = (out_dir / f"extract-{k:03d}.jsonl").resolve()
        listing = (out_dir / f"extract-{k:03d}.modules").resolve()
        listing.write_text("\n".join(batch) + "\n", encoding="utf-8")
        kwargs = {} if commit_gb is None else {"commit_gb": commit_gb}
        run = L.run(ws.env(), ws.root, ["extract", str(target), "--corpus=" + ",".join(ws.corpus_prefixes), "@" + str(listing)], timeout, log, **kwargs)
        clash = CLASH.search(run.tail(4000)) if not run.ok else None
        if run.ok:
            summary = json.loads(run.stdout.strip().splitlines()[-1])
            record.batches.append(Batch(batch, "ok", target.name, summary["declarations"], summary["failed"], summary["import_ms"], summary["extract_ms"], run.seconds))
            log(f"extract: batch {k}: {len(batch)} modules, {summary['declarations']} declarations ({run.seconds:.0f}s)")
        elif clash and clash.group(1) in batch and clash.group(3) in batch:  # else: a clash through an import, split
            failed, name, other = clash.groups()
            clashes.setdefault(failed, set()).add(other)
            clashes.setdefault(other, set()).add(failed)
            record.batches.append(Batch(list(batch), "clash", "", seconds=run.seconds, error=f"{failed} and {other} both declare {name}"))
            log(f"extract: batch {k}: {failed} and {other} both declare {name}; moving {failed} to another batch")
            batch.remove(failed)
            pending.insert(0, batch)
            place(failed)
        elif len(batch) == 1:
            record.batches.append(Batch(batch, "failed", "", seconds=run.seconds, error=run.tail()))
            log(f"extract: {batch[0]} failed: {run.tail(300)}")
        else:
            half = len(batch) // 2
            record.batches.append(Batch(batch, "split", "", seconds=run.seconds, error=run.tail(600)))
            log(f"extract: batch {k} ({len(batch)} modules) did not import together; splitting: {run.tail(200)}")
            pending[:0] = [batch[:half], batch[half:]]
    return record


def challenge_roles(corpus_root: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """The challenge specifications (ComparatorChallenges/*.json), by challenge module; and, for each released name,
    the challenge that lists it."""
    specs, released = {}, {}
    for spec in sorted((corpus_root / "ComparatorChallenges").glob("*.json")):
        data = json.loads(spec.read_text(encoding="utf-8"))
        mod = data.get("challenge_module") or f"ComparatorChallenges.{spec.stem}"
        specs[mod] = data
        for name in data.get("theorem_names", []):
            released.setdefault(name, mod)
    return specs, released


def area_family(solution_module: str) -> tuple[str, str]:
    parts = solution_module.split(".")
    area = parts[1] if len(parts) > 2 else ""
    family = ".".join(parts[1:3]) if len(parts) > 3 else solution_module
    return area, family


def load_declarations(record: ExtractRecord, out_dir: Path, identity: Identity, corpus_root: Path) -> list[dict]:
    """Every extracted declaration with its identity and role:
    statement  a released result as its challenge states it (the comparator's copy, proved by `sorry`)
    interface  a definition a challenge states
    released   a released result as its solution module proves it
    helper     anything else in a solution module"""
    specs, released = challenge_roles(corpus_root)
    out = []
    for env_index, batch in enumerate(b for b in record.batches if b.status == "ok"):
        for line in (out_dir / batch.file).read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            unreadable = "error" in d
            if unreadable:
                d["role"] = "unreadable"
            mod = d["module"]
            d["env"] = env_index
            d["repo"], d["revision"], d["path"] = identity.repo, identity.revision, identity.path(mod)
            d["key"] = identity.key(mod, d["name"])
            if mod.startswith("ComparatorChallenges."):
                spec = specs.get(mod, {})
                d["challenge"] = mod
                if not unreadable:
                    if d["name"] in spec.get("theorem_names", []):
                        d["role"] = "statement"
                    elif d.get("kind") == "def" or d["name"] in spec.get("definition_names", []):
                        d["role"] = "interface"
                    else:
                        d["role"] = "challenge-other"
                sol = spec.get("solution_module", "")
            else:
                d["challenge"] = released.get(d["name"], "")
                if not unreadable:
                    d["role"] = "released" if d["challenge"] else "helper"
                sol = mod
            d["area"], d["family"] = area_family(sol) if sol else ("", "")
            out.append(d)
    return out
