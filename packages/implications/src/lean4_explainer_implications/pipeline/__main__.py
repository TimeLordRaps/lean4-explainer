"""Command line for the discovery pipeline. Every stage writes JSON into the run directory.

    build        build modules (and the corpus modules they import) with `lean -o`, gated on memory and disk
    extract      read the declarations of a layer's modules from Lean
    discover     propose candidates by structure and attempt each in Lean, within a budget
    instantiate  apply checked derivations to the released theorems whose solution modules were built
    catalogue    assemble the checked implications, proof dependencies and unresolved attempts
    contracts    check curated edges' bridge files in Lean and record the results beside the edge file
    report       write REPORT.md and report.json from what the stages recorded
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .. import edges as E
from . import attempts as A
from . import candidates as C
from . import catalogue as K
from . import contracts as T
from . import extract as X
from . import report as R
from . import run as S
from . import workspace as W


def _ws(args) -> W.Workspace:
    return W.Workspace(Path(args.workspace).resolve(), Path(args.corpus).resolve(), tuple(args.prefix))


def _modules(args) -> list[str]:
    mods = list(args.modules)
    if args.challenges:
        mods += sorted("ComparatorChallenges." + p.stem for p in (Path(args.corpus) / "ComparatorChallenges").glob("*.lean"))
    if args.modules_file:
        mods += [m.strip() for m in Path(args.modules_file).read_text(encoding="utf-8").splitlines() if m.strip() and not m.startswith("#")]
    return list(dict.fromkeys(mods))


def _git_head(path: Path) -> str:
    try:
        done = subprocess.run(["git", "--no-optional-locks", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _mathlib(ws: W.Workspace) -> str:
    manifest = ws.root / "lake-manifest.json"
    if not manifest.is_file():
        return ""
    return next((p["rev"] for p in json.loads(manifest.read_text(encoding="utf-8"))["packages"] if p["name"] == "mathlib"), "")


def _log(s: str) -> None:
    print(s, flush=True)


def _record_path(edges: Path, given: str) -> Path:
    return Path(given) if given else edges.with_name(edges.stem + ".verified.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lean4_explainer_implications.pipeline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, lean=True):
        if lean:
            p.add_argument("--workspace", required=True, help="the workspace pinned to the corpus's Mathlib (packages and build output)")
            p.add_argument("--corpus", required=True, help="the corpus checkout's Lean root (read only)")
            p.add_argument("--prefix", action="append", default=None, help="a corpus module prefix (default: OAI and ComparatorChallenges)")
            p.add_argument("--commit-gb", type=float, default=None, help="memory a Lean run waits to be able to commit (0: do not wait)")
        p.add_argument("--run", required=True, help="the run directory: every stage writes its JSON here")

    def budget(p):
        p.add_argument("--heartbeats", type=int, default=A.Budget.heartbeats)
        p.add_argument("--ms", type=int, default=A.Budget.ms)
        p.add_argument("--depth", type=int, default=A.Budget.depth)
        p.add_argument("--jobs", type=int, default=1, help="Lean processes at a time")

    def modules(p):
        p.add_argument("modules", nargs="*")
        p.add_argument("--challenges", action="store_true", help="every ComparatorChallenges module")
        p.add_argument("--modules-file", default="")

    b = sub.add_parser("build", help="build modules with lean -o")
    common(b)
    modules(b)
    b.add_argument("--jobs", type=int, default=3)
    b.add_argument("--min-free-gb", type=float, default=6.0)
    b.add_argument("--timeout", type=int, default=1800)
    b.add_argument("--name", default="build", help="the record's file name in the run directory")

    x = sub.add_parser("extract", help="read a layer's declarations from Lean")
    common(x)
    modules(x)
    x.add_argument("--layer", required=True)
    x.add_argument("--batch-size", type=int, default=500)
    x.add_argument("--repo", default="openai/math")
    x.add_argument("--revision", default="", help="the corpus commit (default: the checkout's HEAD)")
    x.add_argument("--path-prefix", default="lean/", help="the Lean root inside the repository")

    d = sub.add_parser("discover", help="propose candidates and attempt them in Lean")
    common(d)
    budget(d)
    d.add_argument("--layer", required=True)
    d.add_argument("--instantiate", action="store_true", help="also apply each checked derivation to the actual sources")
    d.add_argument("--targets", default="statement,released", help="the roles of the declarations to find derivations of")
    d.add_argument("--sources", default="", help="the roles of the declarations to derive from (default: every statement in the layer)")
    for f in ("per_target", "per_link", "per_compose", "rare_df", "min_shared"):
        d.add_argument("--" + f.replace("_", "-"), type=int, default=getattr(C.Bounds, f))
    d.add_argument("--chunk", type=int, default=250, help="attempts per Lean process")
    d.add_argument("--env-modules", type=int, default=500, help="most modules in an environment shared by candidates from several extraction environments")

    i = sub.add_parser("instantiate", help="apply checked derivations to the released theorems")
    common(i)
    budget(i)
    i.add_argument("--from-layer", default="statements")
    i.add_argument("--solutions-layer", default="solutions")

    k = sub.add_parser("catalogue", help="assemble the catalogue")
    common(k, lean=False)
    k.add_argument("--layers", default="statements,solutions,instantiation")
    k.add_argument("--out", required=True)
    k.add_argument("--edges", default="", help="the curated edge file, whose verification record goes into the catalogue")

    t = sub.add_parser("contracts", help="check curated edges' bridge files in Lean")
    common(t)
    t.add_argument("--edges", required=True, help="the edge file (TOML)")
    t.add_argument("--ids", default="", help="only these edge ids (comma-separated)")
    t.add_argument("--revision", default="", help="the corpus commit (default: the checkout's HEAD)")
    t.add_argument("--record", default="", help="where to write the record (default: <edge file stem>.verified.json beside it)")

    r = sub.add_parser("report", help="write REPORT.md and report.json")
    common(r, lean=False)
    r.add_argument("--catalogue", default="")
    r.add_argument("--edges", default="")
    r.add_argument("--out", default="", help="the directory to write into (default: the run directory)")

    args = parser.parse_args(argv)
    if hasattr(args, "prefix") and args.prefix is None:
        args.prefix = ["OAI", "ComparatorChallenges"]
    run = Path(args.run).resolve()  # Lean runs in the workspace: every path it is given must be absolute
    run.mkdir(parents=True, exist_ok=True)
    gb = getattr(args, "commit_gb", None)

    if args.command == "build":
        ws = _ws(args)
        sizing = {} if gb is None else {"lean_commit_gb": gb, "commit_reserve_gb": 0.0 if gb == 0 else 6.0}
        record = W.build(ws, _modules(args), jobs=args.jobs, min_free_gb=args.min_free_gb, timeout=args.timeout, log=_log, **sizing)
        (run / f"{args.name}.json").write_text(json.dumps(record.to_json(), indent=1), encoding="utf-8")
        print(json.dumps({"counts": record.counts(), "stopped": record.stopped, "min_free_gb_seen": round(record.min_free_gb_seen, 2)}), flush=True)
        return 0 if not record.stopped else 3

    if args.command == "extract":
        ws = _ws(args)
        revision = args.revision or _git_head(ws.corpus_root)
        if not revision:
            print("extract: the corpus commit is unknown: pass --revision", file=sys.stderr)
            return 2
        identity = X.Identity(args.repo, revision, args.path_prefix)
        env = {"toolchain": W.toolchain_version(ws), "mathlib": _mathlib(ws), "corpus_repo": args.repo, "corpus_revision": revision,
               "extract_policy": A.policy()}
        (run / "environment.json").write_text(json.dumps(env, indent=1), encoding="utf-8")
        summary = S.extract_layer(ws, identity, _modules(args), run, args.layer, args.batch_size, log=_log, commit_gb=gb)
        print(json.dumps({k: v for k, v in summary.items() if k != "batches"}), flush=True)
        return 0 if summary["modules_extracted"] else 1

    if args.command in ("discover", "instantiate"):
        ws = _ws(args)
        bud = A.Budget(heartbeats=args.heartbeats, ms=args.ms, depth=args.depth)
        if args.command == "discover":
            bounds = C.Bounds(args.per_target, args.per_link, args.per_compose, args.rare_df, args.min_shared)
            summary = S.discover_layer(ws, run, args.layer, bounds, bud, log=_log, jobs=args.jobs, instantiate=args.instantiate,
                                       targets_roles=tuple(args.targets.split(",")), chunk=args.chunk, commit_gb=gb,
                                       sources_roles=tuple(args.sources.split(",")) if args.sources else None, env_limit=args.env_modules)
        else:
            summary = S.instantiate_checked(ws, run, args.from_layer, args.solutions_layer, bud, log=_log, jobs=args.jobs, commit_gb=gb)
        print(json.dumps({k: v for k, v in summary.items() if k != "blocked"}), flush=True)
        return 0

    if args.command == "catalogue":
        decls, results, seen = [], [], set()
        for layer in args.layers.split(","):
            for dcl in S.read_declarations(run, layer):
                if dcl["key"] not in seen:
                    seen.add(dcl["key"])
                    decls.append(dcl)
            results += S.read_results(run, layer)
        env = json.loads((run / "environment.json").read_text(encoding="utf-8")) if (run / "environment.json").is_file() else {}
        contracts = []
        if args.edges:
            rec = _record_path(Path(args.edges), "")
            contracts = list((json.loads(rec.read_text(encoding="utf-8"))["edges"] if rec.is_file() else {}).values())
        header = {"environment": env, "layers": args.layers.split(","), "policy": A.policy(),
                  "provenance": "Recorded: each checked entry was checked by Lean's kernel when the pipeline ran, in the environment "
                                "named; a site build that shows the catalogue does not run Lean again."}
        cat = K.build(decls, results, header, contracts)
        sizes = K.write(cat, Path(args.out))
        print(json.dumps({"counts": cat["counts"], "bytes": sum(sizes.values()), "files": len(sizes)}), flush=True)
        return 0

    if args.command == "contracts":
        ws = _ws(args)
        path = Path(args.edges).resolve()
        found = E.load(path.read_text(encoding="utf-8"))
        if found.problems:
            print("\n".join(found.problems), file=sys.stderr)
            return 2
        ids = {s for s in args.ids.split(",") if s}
        edges = [e for e in found.edges if e.bridge_file and (not ids or e.id in ids)]
        command = "python -m lean4_explainer_implications.pipeline " + " ".join(sys.argv[1:] if argv is None else argv)
        records = T.check(ws, edges, path.parent, run / "contracts", args.revision or _git_head(ws.corpus_root), _mathlib(ws), command, log=_log, commit_gb=gb)
        T.write_records(_record_path(path, args.record), records)
        print(json.dumps({k: v["status"] for k, v in records.items()}), flush=True)
        return 0 if all(v["status"] == "checked" for v in records.values()) else 1

    if args.command == "report":
        contracts = {}
        if args.edges:
            rec = _record_path(Path(args.edges), "")
            contracts = json.loads(rec.read_text(encoding="utf-8"))["edges"] if rec.is_file() else {}
        data = R.collect(run, Path(args.catalogue) if args.catalogue else None, contracts)
        out = Path(args.out) if args.out else run
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        (out / "REPORT.md").write_text(R.markdown(data), encoding="utf-8")
        print(f"report: {out / 'REPORT.md'}", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
