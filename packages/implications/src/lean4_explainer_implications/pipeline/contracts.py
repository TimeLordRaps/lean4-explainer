"""Check curated edges' contracts in Lean and record the result, so a site build can show what was checked, where.

A proved edge names a bridge file and a bridge declaration in it. Lean elaborates the file in the corpus's own
environment, and `Pipeline.lean contract` checks the bridge's proof term against the proposition the edge states
(its sources as hypotheses, then its hypotheses, then its conclusion), audits its axioms, checks that it neither uses
the target nor anything that reaches it, and that it uses each source. A `strengthens` edge also names a relation:
a proof that the contract gives the target's statement.

The record keeps what the check depended on: the edge's contract (fingerprint), the bridge file's and the imported
corpus files' digests, the environment's identity, and the revisions. A site build compares them with what it has;
any difference makes the record stale, and a stale record says nothing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from .. import edges as E
from . import attempts as A
from . import lean as L
from .workspace import Workspace, header_imports, toolchain_version

RECORD_FORMAT = 1


def bare(name: str) -> str:
    return name.partition("@")[0]


def sha256_file(path: Path) -> str:
    """A source file's digest, line endings made LF (see edges.content_sha256)."""
    return E.content_sha256(path.read_bytes())


def inputs_of(bridge_path: Path, corpus_root: Path, corpus_prefixes: tuple[str, ...]) -> dict[str, str]:
    """The digests of the corpus files the bridge imports (as paths relative to the corpus root)."""
    out = {}
    for m in header_imports(bridge_path):
        if m.split(".")[0] in corpus_prefixes:
            rel = m.replace(".", "/") + ".lean"
            p = corpus_root / rel
            out[rel] = sha256_file(p) if p.is_file() else "missing"
    return out


def contract_json(edge: E.Edge) -> dict:
    c = {"id": edge.id, "bridge": edge.bridge, "sources": [bare(s) for s in edge.sources], "hypotheses": list(edge.hypotheses),
         "conclusion": edge.conclusion, "target": bare(edge.target)}
    if edge.relation:
        c["relation"] = edge.relation
    if edge.construction:
        c["construction"] = edge.construction
    return c


def check(ws: Workspace, edges: list[E.Edge], edge_dir: Path, out_dir: Path, corpus_revision: str, mathlib_revision: str,
          command: str, log: Callable[[str], None] = print, commit_gb: float | None = None, timeout: int = 3600) -> dict[str, dict]:
    """Check every edge that names a bridge file, one Lean process per file. Returns records by edge id."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_file: dict[str, list[E.Edge]] = defaultdict(list)
    for e in edges:
        if e.bridge_file:
            by_file[e.bridge_file].append(e)
    toolchain = toolchain_version(ws)
    records: dict[str, dict] = {}
    for rel, group in sorted(by_file.items()):
        path = (edge_dir / rel).resolve()
        if not path.is_file():
            for e in group:
                records[e.id] = {"id": e.id, "status": "error", "reason": f"no bridge file {rel}"}
            continue
        tag = hashlib.sha256(rel.encode()).hexdigest()[:8]
        plan_path, result_path = (out_dir / f"contract-{tag}.json").resolve(), (out_dir / f"contract-{tag}.jsonl").resolve()
        plan = {"bridge_file": str(path), "corpus": list(ws.corpus_prefixes), "contracts": [contract_json(e) for e in group]}
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        imports = header_imports(path)
        env_id = A.environment_identity(ws, [m for m in imports if ws.is_corpus(m)])
        kwargs = {} if commit_gb is None else {"commit_gb": commit_gb}
        run = L.run(ws.env(), ws.root, ["contract", str(plan_path), str(result_path)], timeout, log, **kwargs)
        got = {}
        if result_path.is_file():
            for line in result_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    got[row["id"]] = row
        bridge_sha = sha256_file(path)
        inputs = inputs_of(path, ws.corpus_root, tuple(ws.corpus_prefixes))
        for e in group:
            row = got.get(e.id) or {"id": e.id, "status": "error", "reason": f"the Lean process gave no result: {run.tail(600)}"}
            row.pop("bridge_file", None)
            row.update({
                "format": RECORD_FORMAT, "bridge_file": rel, "bridge_sha256": bridge_sha, "fingerprint": E.fingerprint(e, bridge_sha),
                "inputs": inputs, "imports": imports, "environment": env_id, "toolchain": toolchain, "mathlib": mathlib_revision,
                "corpus_revision": corpus_revision, "checked_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "command": command, "seconds": round(run.seconds, 1), "policy": A.policy(),
            })
            records[e.id] = row
            log(f"contract {e.id}: {row['status']}" + (f" ({row.get('reason', '')[:200]})" if row.get("reason") else ""))
    return records


def write_records(path: Path, records: dict[str, dict]) -> None:
    """Merge into the edge file's record (other edges' records are kept)."""
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"format": RECORD_FORMAT, "edges": {}}
    data["edges"].update(records)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
