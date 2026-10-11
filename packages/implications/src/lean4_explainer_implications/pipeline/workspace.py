"""A Lean workspace for the discovery pipeline: pinned Mathlib from its cache, the corpus modules copied in, and
targeted builds of just the modules a run needs.

Builds call `lean -o` directly on each module, in import order, with Mathlib's cached `.olean` files on the search
path. (Lake also writes a setup file per module listing every import, about 10 MB each with Mathlib; on a disk
that is nearly full that matters more than anything else the build writes.) Each built module gets a trace: the
hash of its source, the toolchain, and the traces of the corpus modules it imports. A module whose trace matches
is not rebuilt.

Source text is read here only to order builds (which corpus modules each one imports). Nothing is inferred from it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import processes as P

IMPORT = re.compile(r"^\s*(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?([^\s]+)")
TRACE_FORMAT = 1


@dataclass(frozen=True)
class Workspace:
    root: Path  # the Lake workspace (its lakefile pins Mathlib)
    corpus_root: Path  # the corpus checkout's Lean root, read only
    corpus_prefixes: tuple[str, ...] = ("OAI", "ComparatorChallenges")

    @property
    def build_lib(self) -> Path:
        return self.root / ".lake" / "build" / "lib" / "lean"

    @property
    def trace_dir(self) -> Path:
        return self.root / ".lake" / "build" / "explainer-trace"

    def is_corpus(self, module: str) -> bool:
        return module.split(".")[0] in self.corpus_prefixes

    def source(self, module: str) -> Path:
        return self.corpus_root / (module.replace(".", "/") + ".lean")

    def olean(self, module: str) -> Path:
        return self.build_lib / (module.replace(".", "/") + ".olean")

    def lean_path(self) -> list[Path]:
        """The search path: every package's built library, then the workspace's own."""
        packages = self.root / ".lake" / "packages"
        found = sorted(p / ".lake" / "build" / "lib" / "lean" for p in packages.iterdir() if (p / ".lake" / "build" / "lib" / "lean").is_dir()) if packages.is_dir() else []
        return [*found, self.build_lib]

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["LEAN_PATH"] = os.pathsep.join(str(p) for p in self.lean_path())
        return env


# -- setting up --


def write_project(root: Path, mathlib_rev: str, toolchain: str, prefixes: Sequence[str]) -> None:
    """The lakefile and toolchain file of a workspace pinned to one Mathlib revision."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "lean-toolchain").write_text(toolchain.strip() + "\n", encoding="utf-8")
    libs = "".join(f"lean_lib {p} where\n  globs := #[`{p}.+]\n" for p in prefixes)
    (root / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\npackage oai_explainer_ws where\n  leanOptions := #[⟨`autoImplicit, false⟩]\n"
        f'require mathlib from git\n  "https://github.com/leanprover-community/mathlib4.git" @ "{mathlib_rev}"\n' + libs,
        encoding="utf-8",
    )


def fetch_dependencies(root: Path, corpus_manifest: Path, log: Callable[[str], None] = print) -> None:
    """Shallow-fetch Mathlib's dependencies at the revisions Mathlib pins, and write the workspace manifest. Mathlib
    itself must already be at `.lake/packages/mathlib` (the corpus manifest gives its exact entry)."""
    packages = root / ".lake" / "packages"
    mathlib_manifest = json.loads((packages / "mathlib" / "lake-manifest.json").read_text(encoding="utf-8"))
    corpus = json.loads(corpus_manifest.read_text(encoding="utf-8"))
    mathlib_entry = next(p for p in corpus["packages"] if p["name"] == "mathlib")
    entries = [dict(mathlib_entry, inherited=False)]
    for dep in mathlib_manifest["packages"]:
        _fetch(packages / dep["name"], dep["url"], dep["rev"], log)
        entries.append(dict(dep, inherited=True))
    manifest = {"version": mathlib_manifest["version"], "packagesDir": ".lake/packages", "packages": entries, "name": "oai_explainer_ws", "lakeDir": ".lake"}
    (root / "lake-manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")


def _fetch(target: Path, url: str, rev: str, log: Callable[[str], None]) -> None:
    if (target / ".git").is_dir():
        head = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head != rev:
            raise SystemExit(f"{target.name}: at {head[:12]}, expected {rev[:12]}; not touching it")
        log(f"{target.name}: already at {rev[:12]}")
        return
    target.mkdir(parents=True)
    for args in (["init", "-q"], ["remote", "add", "origin", url], ["fetch", "-q", "--depth", "1", "origin", rev], ["-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD"]):
        subprocess.run(["git", "-C", str(target), *args], check=True)
    log(f"{target.name}: fetched {rev[:12]}")


def header_imports(path: Path) -> list[str]:
    """The modules a Lean file imports, read from its header (to order builds; nothing else uses it)."""
    text = re.sub(r"/-.*?-/", "", path.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.startswith("module") or stripped.startswith("prelude"):
            continue
        match = IMPORT.match(line)
        if match is None:
            break
        found.append(match.group(1))
    return found


def closure(ws: Workspace, modules: Iterable[str]) -> dict[str, list[str]]:
    """Each corpus module the given ones need, with the corpus modules it imports directly."""
    graph: dict[str, list[str]] = {}
    todo = list(modules)
    while todo:
        mod = todo.pop()
        if mod in graph or not ws.is_corpus(mod):
            continue
        src = ws.source(mod)
        if not src.is_file():
            raise FileNotFoundError(f"no source for {mod}: {src}")
        deps = [d for d in header_imports(src) if ws.is_corpus(d)]
        graph[mod] = deps
        todo.extend(deps)
    return graph


def sync(ws: Workspace, modules: Iterable[str]) -> tuple[dict[str, list[str]], int]:
    """Copy the modules and their corpus imports into the workspace, writing only files that differ."""
    graph = closure(ws, modules)
    copied = 0
    for mod in graph:
        src, dst = ws.source(mod), ws.root / (mod.replace(".", "/") + ".lean")
        data = src.read_bytes()
        if not dst.is_file() or dst.read_bytes() != data:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            copied += 1
    return graph, copied


# -- building --


@dataclass
class ModuleBuild:
    module: str
    status: str  # built | replayed | failed | timeout | blocked | skipped (the run stopped: low disk, or no memory)
    seconds: float = 0.0
    detail: str = ""


@dataclass
class BuildRecord:
    toolchain: str
    modules: list[ModuleBuild] = field(default_factory=list)
    stopped: str = ""  # why the run stopped launching builds, if it did
    min_free_gb_seen: float = -1.0

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for m in self.modules:
            out[m.status] = out.get(m.status, 0) + 1
        return out

    def ok(self) -> set[str]:
        return {m.module for m in self.modules if m.status in ("built", "replayed")}

    def to_json(self) -> dict:
        return {"toolchain": self.toolchain, "stopped": self.stopped, "min_free_gb_seen": self.min_free_gb_seen, "counts": self.counts(), "modules": [asdict(m) for m in self.modules]}


def toolchain_version(ws: Workspace) -> str:
    done = subprocess.run(["lean", "--version"], cwd=ws.root, capture_output=True, text=True, env=ws.env(), timeout=600)
    return done.stdout.strip().splitlines()[0] if done.returncode == 0 and done.stdout.strip() else ""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# A Lean process that imports a slice of Mathlib commits about 8 GB on Windows (measured: three build processes took
# the free commit charge from 35 GB to 11 GB); one that imports 353 openai/math challenge files with their Mathlib
# commits 10.8 GB (2026-10-10, attempt processes). Past the commit limit Windows grows the page file on the system
# disk, and when it cannot, allocations fail in every process on the machine.
LEAN_COMMIT_GB = 11.0


def build(
    ws: Workspace,
    modules: Iterable[str],
    jobs: int = 3,
    min_free_gb: float = 6.0,
    timeout: int = 1800,
    log: Callable[[str], None] = print,
    commit_reserve_gb: float = 6.0,
    lean_commit_gb: float = LEAN_COMMIT_GB,
) -> BuildRecord:
    """Build the modules and the corpus modules they import, in import order, at most `jobs` at a time. A new build
    starts once the system can commit another Lean process's memory and keep `commit_reserve_gb` spare: it waits,
    for memory other processes hold too (up to processes.MEMORY_WAIT_SECONDS, then the run stops). Parallel builds
    start one at a time, each after the one before has committed its memory. A timeout stops the build's whole
    process tree. Stops launching when the disk holding the workspace has less than `min_free_gb` free; what was not
    built is recorded."""
    graph, copied = sync(ws, modules)
    log(f"build: {len(graph)} corpus modules in the closure, {copied} source files copied")
    record = BuildRecord(toolchain_version(ws))
    traces: dict[str, str] = {}
    status: dict[str, str] = {}
    lock = threading.Lock()
    pending = dict(graph)
    dependents: dict[str, list[str]] = {m: [] for m in graph}
    for mod, deps in graph.items():
        for d in deps:
            dependents.setdefault(d, []).append(mod)

    def trace_of(mod: str) -> str:
        parts = {"format": TRACE_FORMAT, "toolchain": record.toolchain, "source": _sha256(ws.root / (mod.replace(".", "/") + ".lean")), "deps": {d: traces[d] for d in sorted(graph[mod])}}
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    def one(mod: str) -> ModuleBuild:
        digest = trace_of(mod)
        trace_file = ws.trace_dir / (mod + ".json")
        olean = ws.olean(mod)
        if olean.is_file() and trace_file.is_file() and json.loads(trace_file.read_text(encoding="utf-8")).get("digest") == digest:
            traces[mod] = digest
            return ModuleBuild(mod, "replayed")
        olean.parent.mkdir(parents=True, exist_ok=True)
        src = ws.root / (mod.replace(".", "/") + ".lean")
        # a build waits until the system can commit its memory, and parallel builds take turns to start, each after
        # the one before has committed (processes.launch)
        need = lean_commit_gb + commit_reserve_gb if lean_commit_gb > 0 else 0.0
        try:
            proc, began = P.launch(["lean", str(src), "-o", str(olean)], ws.root, ws.env(), need, 0.8 * lean_commit_gb, log=log)
        except RuntimeError as exc:  # the memory never came free
            return ModuleBuild(mod, "skipped", 0.0, str(exc))
        code, out, err, seconds = P.finish(proc, began, timeout)
        if code == -1:
            return ModuleBuild(mod, "timeout", seconds, f"no result after {timeout}s")
        errors = [line for line in (out + err).splitlines() if ": error" in line or line.startswith("error")]
        if code != 0 or not olean.is_file():
            return ModuleBuild(mod, "failed", seconds, "\n".join(errors[:5]) or (err or out)[-800:])
        ws.trace_dir.mkdir(parents=True, exist_ok=True)
        trace_file.write_text(json.dumps({"digest": digest, "module": mod}), encoding="utf-8")
        traces[mod] = digest
        return ModuleBuild(mod, "built", seconds)

    ready = sorted(m for m, deps in graph.items() if not deps)
    running: dict[Future, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        while ready or running:
            while ready and len(running) < jobs and not record.stopped:
                free = shutil.disk_usage(ws.root).free / 1e9
                record.min_free_gb_seen = free if record.min_free_gb_seen < 0 else min(record.min_free_gb_seen, free)
                if free < min_free_gb:
                    record.stopped = f"free space on the workspace disk fell to {free:.1f} GB (limit {min_free_gb} GB)"
                    log(f"build: stopping: {record.stopped}")
                    break
                mod = ready.pop(0)
                running[pool.submit(one, mod)] = mod
            if not running:
                break
            done_set, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done_set:
                mod = running.pop(fut)
                result = fut.result()
                with lock:
                    record.modules.append(result)
                    status[mod] = result.status
                log(f"build: {result.status:9} {mod} ({result.seconds:.0f}s){' ' + result.detail.splitlines()[0][:160] if result.detail else ''}")
                if result.status == "skipped" and not record.stopped:
                    record.stopped = result.detail
                    log(f"build: stopping: {record.stopped}")
                pending.pop(mod, None)
                for dep in dependents.get(mod, ()):
                    if all(status.get(d) in ("built", "replayed") for d in graph[dep]) and dep not in status and dep not in ready:
                        ready.append(dep)
    for mod in graph:
        if mod not in status:
            failed = [d for d in graph[mod] if status.get(d) not in (None, "built", "replayed")]
            record.modules.append(ModuleBuild(mod, "blocked" if failed else "skipped" if record.stopped else "blocked", 0.0, f"needs {', '.join(failed)}" if failed else record.stopped))
    return record
