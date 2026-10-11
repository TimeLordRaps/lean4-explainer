"""The run's report: what was built and read, what was proposed and attempted per rule, what Lean checked, what is
unresolved and why, and what it cost. Everything comes from the JSON the stages wrote; nothing is estimated."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .attempts import CHECKED
from .candidates import generated, is_statement


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _declarations(run: Path, layer: str) -> list[dict]:
    path = run / layer / "declarations.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def coverage(run: Path, layer: str, index: dict | None) -> dict:
    """How many families and areas each stage reached in a layer: with a statement (not one Lean generated), in an
    attempt, in a checked derivation, in one that was then checked on the released theorems, in a connection of the
    catalogue found in this layer."""
    decls = {d["key"]: d for d in _declarations(run, layer)}
    results = _rows(run / layer / "results.jsonl")
    applied = {r["derivation"] for r in _rows(run / "instantiation" / "results.jsonl") if r.get("status") == "checked-instantiated"}
    keys = lambda r: (r.get("source_keys") or []) + ([r["target_key"]] if r.get("target_key") else [])  # noqa: E731
    stages = {
        "statements": [d for d in decls.values() if is_statement(d) and not generated(d)],
        "attempted": [decls[k] for r in results for k in keys(r) if k in decls],
        "checked": [decls[k] for r in results if r.get("status") in CHECKED for k in keys(r) if k in decls],
        "instantiated": [decls[k] for r in results if r.get("status") in CHECKED and r.get("id") in applied for k in keys(r) if k in decls],
    }
    by_family = {d.get("family", ""): d.get("area", "") for d in decls.values()}
    conn = {f for i in (index or {}).get("implications", []) if i.get("group") == "connection" and i.get("layer") == layer
            for f in i.get("families", [])}
    out = {}
    for what in ("family", "area"):
        counts = {stage: len({d.get(what, "") for d in ds} - {""}) for stage, ds in stages.items()}
        counts["connections"] = len(conn if what == "family" else {by_family.get(f, "") for f in conn} - {""})
        out["families" if what == "family" else "areas"] = counts
    return out


def statement_match(statements: list[dict], solutions: list[dict]) -> dict:
    """For each released theorem that was built, whether its elaborated type is the same expression as its challenge
    copy's (the same constants by name, in the same structure). The definitions those names refer to are compared by
    openai/math's comparator, not here."""
    copies = {d["name"]: d for d in statements if d.get("role") == "statement"}
    rows = []
    for d in solutions:
        if d.get("role") != "released" or d["name"] not in copies:
            continue
        c = copies[d["name"]]
        rows.append({"name": d["name"], "challenge": c.get("challenge", ""), "module": d["module"], "same": d.get("type_hash") == c.get("type_hash"),
                     "released_sorry": bool(d.get("sorry")), "released_axioms": d.get("axioms", [])})
    return {"compared": len(rows), "same": sum(r["same"] for r in rows), "different": [r for r in rows if not r["same"]],
            "released_with_sorry": [r["name"] for r in rows if r["released_sorry"]], "rows": rows}


def collect(run: Path, catalogue_dir: Path | None = None, contracts: dict | None = None) -> dict:
    builds = {p.stem: _load(p) for p in sorted(run.glob("build*.json"))}
    layers = {}
    for layer_dir in sorted(p for p in run.iterdir() if p.is_dir()):
        extract, discover = _load(layer_dir / "extract.json"), _load(layer_dir / "discover.json")
        inst = _load(layer_dir / "instantiate.json")
        if extract or discover or inst:
            layers[layer_dir.name] = {"extract": {k: v for k, v in (extract or {}).items() if k != "batches"} or None,
                                      "discover": discover, "instantiate": inst}
    index = _load(catalogue_dir / "index.json") if catalogue_dir else None
    sizes = {}
    if catalogue_dir and catalogue_dir.is_dir():
        sizes = {str(p.relative_to(catalogue_dir)).replace("\\", "/"): p.stat().st_size for p in sorted(catalogue_dir.rglob("*.json"))}
    return {
        "run": run.name,  # not the absolute path: the report is published
        "environment": _load(run / "environment.json"),
        "builds": {name: {k: v for k, v in (b or {}).items() if k != "modules"} | {
            "failed": [m for m in (b or {}).get("modules", []) if m["status"] not in ("built", "replayed")][:200],
            "build_seconds": round(sum(m.get("seconds", 0) for m in (b or {}).get("modules", [])), 1)} for name, b in builds.items()},
        "layers": layers,
        "catalogue": {"counts": (index or {}).get("counts"), "bytes": sizes, "total_bytes": sum(sizes.values())},
        "contracts": contracts or {},
        "coverage": {name: coverage(run, name, index) for name in layers if (run / name / "declarations.jsonl").is_file()},
        "statement_match": statement_match(_declarations(run, "statements"), _declarations(run, "solutions")),
    }


def _table(rows: list[list], head: list[str]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def markdown(data: dict) -> str:
    env = data.get("environment") or {}
    lines = ["# Implication discovery: run report", ""]
    if env:
        lines += ["## Environment", ""]
        names = {"policy": "declarations extracted under rule set", "extract_policy": "declarations extracted under rule set"}
        lines += [f"- {names.get(k, k)}: `{v}`" for k, v in env.items()]
        lines.append("")
    if data["builds"]:
        lines += ["## Builds", ""]
        rows = [[n, ", ".join(f"{s} {c}" for s, c in sorted((b.get("counts") or {}).items())), b.get("build_seconds", 0), b.get("stopped") or "—"] for n, b in data["builds"].items()]
        lines += _table(rows, ["build", "modules", "seconds", "stopped"]) + [""]
        for n, b in data["builds"].items():
            for m in b.get("failed", []):
                lines.append(f"- {n}: `{m['module']}` {m['status']}: {m.get('detail', '')[:200]}")
        lines.append("")
    for name, layer in data["layers"].items():
        lines += [f"## Layer `{name}`", ""]
        ex = layer.get("extract")
        if ex:
            lines += [f"- modules requested {ex['modules_requested']}, extracted {ex['modules_extracted']}, in {len(ex['environments'])} environments "
                      f"(sizes {ex['environments']}); {len(ex.get('clashes', []))} pairs of modules declare the same name and were kept apart ({len(ex.get('moved_on_import', []))} more moved when an import failed), {len(ex['splits'])} batches split for other import failures",
                      f"- declarations {ex['declarations']}: " + ", ".join(f"{k} {v}" for k, v in sorted(ex["by_role"].items())),
                      f"- statements (theorems whose type is a proposition) {ex['statements']}; with sorry {ex['with_sorry']}; unreadable {ex['unreadable']}",
                      f"- extraction took {ex['seconds']} s"] + ([f"- extracted under rule set `{ex['policy']}`"] if ex.get("policy") else []) + (
                [f"- {len(ex['modules_added'])} more modules extracted because they declare a theorem a challenge lists: "
                 + ", ".join(f"`{m}`" for m in ex["modules_added"])] if ex.get("modules_added") else [])
            for f in ex.get("modules_failed", []):
                lines.append(f"- failed to import: `{f['module']}`: {f['error'][:200]}")
            lines.append("")
        d = layer.get("discover")
        if d:
            lines += [f"Discovery: policy `{d['policy']}`, budget {json.dumps(d['budget'])}, bounds {json.dumps(d['bounds'])}", ""]
            rows = []
            for match, n in sorted(d["candidates_per_match"].items()):
                outcomes = d["outcomes_per_match"].get(match, {})
                rows.append([match, n, sum(outcomes.get(s, 0) for s in ("checked", "checked-instantiated")),
                             ", ".join(f"{s} {c}" for s, c in sorted(outcomes.items()))])
            lines += _table(rows, ["candidate match", "candidates", "checked", "outcomes"]) + [""]
            lines += [f"- {d['attempts']} attempts ({d['cached']} from the cache, {d['run']} run) in {d['environments']} environments, "
                      f"{d['lean_processes']} Lean processes, {d['lean_seconds']} s of Lean, {d['seconds']} s in all; "
                      f"attempt time {d['attempt_ms_total']} ms total, {d['attempt_ms_max']} ms at most"]
            if d.get("generated_left_out"):
                lines.append(f"- {d['generated_left_out']} statements Lean generated (injectivity, equation lemmas; no source position) were not proposed")
            if d.get("blocked"):
                lines.append(f"- {len(d['blocked'])} candidates not attempted: two of their modules declare the same name, so no environment holds them "
                             f"({d['blocked_module_pairs']} module pairs; " + ", ".join(f"{m} {n}" for m, n in sorted(d["blocked_per_match"].items())) + ")")
            for f in d.get("process_failures", []):
                lines.append(f"- a Lean process failed: {f[:200]}")
            lines.append("")
        inst = layer.get("instantiate")
        if inst:
            lines += [f"Instantiation: {inst['checked_derivations']} checked derivations, {inst['attempted']} applied to the released theorems, "
                      f"{len(inst['blocked'])} blocked; outcomes " + ", ".join(f"{s} {c}" for s, c in sorted(inst["outcomes"].items())), ""]
            reasons = Counter(b["reason"].split(" for ")[0] for b in inst["blocked"])
            lines += [f"- blocked: {why} ({n})" for why, n in reasons.most_common()] + [""]
    cat = data["catalogue"]
    if cat.get("counts"):
        c = cat["counts"]
        lines += ["## Catalogue", "",
                  f"- checked implications {c['checked']}: " + ", ".join(f"{k} {v}" for k, v in sorted(c["checked_by_group"].items())),
                  f"- by state: " + ", ".join(f"{k} {v}" for k, v in sorted(c["checked_by_state"].items())),
                  f"- connections (checked, not grouped as routine) {c['connections']}",
                  f"- proof dependencies (from elaborated proof terms) {c['dependencies']}",
                  f"- unresolved attempts {c['unresolved']}: " + ", ".join(f"{k} {v}" for k, v in sorted(c["unresolved_by_status"].items())),
                  f"- size: {cat['total_bytes']} bytes in {len(cat['bytes'])} files", ""]
    if data.get("coverage"):
        lines += ["## Coverage", ""]
        for name, cov in data["coverage"].items():
            for what in ("families", "areas"):
                lines.append(f"- `{name}` {what}: " + ", ".join(f"{k} {v}" for k, v in cov[what].items()))
        lines.append("")
    m = data.get("statement_match") or {}
    if m.get("compared"):
        lines += ["## Released theorems against their challenge statements", "",
                  f"- {m['compared']} released theorems built and compared with their ComparatorChallenges copy: {m['same']} the same expression"]
        lines += [f"- different: `{r['name']}` ({r['module']})" for r in m["different"]]
        lines += [f"- released with sorry: `{n}`" for n in m["released_with_sorry"]]
        lines.append("")
    if data["contracts"]:
        lines += ["## Curated contracts", ""]
        for cid, r in sorted(data["contracts"].items()):
            lines.append(f"- `{cid}`: {r.get('status')}" + (f": {r.get('reason')[:300]}" if r.get("reason") else "")
                         + f" (checked {r.get('checked_at', '')}, environment {r.get('environment', '')})")
        lines.append("")
    return "\n".join(lines) + "\n"
