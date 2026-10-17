"""Populate content-bound Lean evidence for built formalization-catalogue targets.

The catalogue builder and the evidence probe are deliberately separate.  Building an OLean
establishes that the module compiled; this script then asks the exact pinned Lean environment
for each named result's axioms, dependencies, and tactic goal-state trace.  Clean results are
stored in the same cache the static-site build consumes.  Failures and resource stops remain
UNKNOWN and are never cached.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from lean4_explainer.extensions import activate
from lean4_explainer.scan import scan_file
from lean4_explainer_corpora.showcase import _formalization_targets
from lean4_explainer_lean import LeanExtension, facts
try:  # direct execution puts ``scripts`` itself, not the repository root, on sys.path
    from build_lean_catalogue import internal_dependency_closures
except ModuleNotFoundError:  # imported as ``scripts.probe_lean_catalogue`` by tests and other Python code
    from scripts.build_lean_catalogue import internal_dependency_closures


def group_targets(encoded: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for target in encoded:
        relative, separator, name = target.partition("\t")
        if not separator or not relative or not name:
            raise ValueError(f"invalid encoded catalogue target: {target!r}")
        grouped[relative].append(name)
    return {relative: tuple(names) for relative, names in grouped.items()}


def output_path(output_root: Path, relative: str) -> Path:
    return output_root / Path(relative).with_suffix(".olean")


def complete_target_files(root: Path, output_root: Path, relatives: tuple[str, ...]) -> list[str]:
    closures = internal_dependency_closures(root, relatives)
    return [
        relative
        for relative in sorted(relatives)
        if all(output_path(output_root, dependency).is_file() for dependency in closures[relative])
    ]


def probe(args: argparse.Namespace) -> int:
    root = args.source_root.resolve()
    project = args.project.resolve()
    cache = args.cache.resolve()
    output_root = (args.output_root or project / ".lake" / "build" / "lib" / "lean").resolve()
    grouped = group_targets(_formalization_targets(args.catalogue.resolve()))
    selected = complete_target_files(root, output_root, tuple(grouped))
    if args.limit:
        selected = selected[: args.limit]
    extension = LeanExtension()
    state = {
        "schema": 1,
        "catalogue_targets": sum(len(names) for names in grouped.values()),
        "catalogue_files": len(grouped),
        "built_files_selected": len(selected),
        "results": {},
    }
    failures = 0
    activate([extension])
    try:
        for index, relative in enumerate(selected, 1):
            started = time.monotonic()
            lean_file = scan_file(root / relative, relative)
            summary = extension.index_file(
                relative, lean_file.declarations, lean_file.diagnostics.get(extension.name, ())
            )
            names = grouped[relative]
            analysis = extension.analyze(
                {},
                {relative: summary},
                {
                    "_root": str(root),
                    "lean_project": str(project),
                    "lean_cache": str(cache),
                    "lean_targets": [f"{relative}\t{name}" for name in names],
                    "lean_selection_label": f"catalogue {args.catalogue.name}",
                    "lean_jobs": 1,
                    "lean_timeout": args.timeout,
                    "lean_steps": args.steps,
                    "lean_max_working_set_mb": args.max_working_set_mb,
                    "lean_min_free_virtual_mb": args.min_free_virtual_mb,
                },
            )
            result = analysis.files[relative]
            classifications = (
                {decl.name: facts.classify(decl.axioms)[0] for decl in result.decls}
                if result.status == "ok"
                else {}
            )
            record = {
                "status": result.status,
                "reason": result.reason,
                "requested": list(names),
                "reported": [decl.name for decl in result.decls],
                "classifications": classifications,
                "tactic_steps": sum(len(decl.steps) for decl in result.decls),
                "reused": bool(analysis.reused),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            state["results"][relative] = record
            if result.status != "ok" or len(result.decls) != len(names) or result.errors:
                failures += 1
                detail = result.reason or (result.errors[0] if result.errors else "not every requested result was reported")
                print(f"[{index}/{len(selected)}] UNKNOWN {relative}: {detail}", flush=True)
            else:
                mode = "cache" if analysis.reused else "Lean"
                classes = ", ".join(f"{name}={kind}" for name, kind in classifications.items())
                print(
                    f"[{index}/{len(selected)}] checked by {mode}: {relative}: {classes}; "
                    f"{record['tactic_steps']} tactic steps",
                    flush=True,
                )
            if args.state:
                _write_state(args.state, state)
    finally:
        activate(None)
    checked = sum(record["status"] == "ok" for record in state["results"].values())
    print(
        f"catalogue evidence: {checked}/{len(selected)} built files clean; "
        f"{failures} UNKNOWN; {len(grouped) - len(selected)} target files not built",
        flush=True,
    )
    return 1 if failures else 0


def _write_state(path: Path, state: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source-root", required=True, type=Path)
    result.add_argument("--project", required=True, type=Path)
    result.add_argument("--catalogue", required=True, type=Path)
    result.add_argument("--cache", required=True, type=Path)
    result.add_argument("--output-root", type=Path)
    result.add_argument("--state", type=Path)
    result.add_argument("--timeout", type=int, default=300)
    result.add_argument("--steps", type=int, default=200)
    result.add_argument("--max-working-set-mb", type=int, default=12_288)
    result.add_argument("--min-free-virtual-mb", type=int, default=6_144)
    result.add_argument("--limit", type=int, default=0)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        return probe(parser().parse_args(argv))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
