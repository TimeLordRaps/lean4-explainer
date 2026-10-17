"""Build the Lean modules named by a formalization catalogue, one target at a time.

Lake schedules every root in one build together.  For very large generated corpora that can
start more compiler processes than a workstation can safely commit.  This driver deliberately
invokes one module target per Lake process, records progress after every target, and resumes
without rebuilding completed OLean files.

It builds local evidence only.  The generated ``.olean`` files are inputs to the explainer's
Lean probe and are not copied into the hosted site.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path


_DECLARATION = re.compile(r"^\s+(?:-\s+)?declaration:\s*(\S+)\s*$")
_FILE = re.compile(r"^\s+(?:-\s+)?file:\s*(\S+\.lean)\s*$")
_IMPORT = re.compile(r"^\s*(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?(.+?)\s*$")


def catalogue_files(path: Path) -> tuple[str, ...]:
    """Return the catalogue's distinct target files without executing a YAML loader."""
    if not path.is_file():
        raise ValueError(f"catalogue not found: {path}")
    declaration = ""
    found: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if match := _DECLARATION.match(line):
            declaration = match.group(1)
        elif declaration and (match := _FILE.match(line)):
            rel = match.group(1).replace("\\", "/")
            if rel not in found:
                found.append(rel)
            declaration = ""
    if not found:
        raise ValueError(f"catalogue contains no declaration/file pairs: {path}")
    return tuple(found)


def module_name(relative: str) -> str:
    path = Path(relative)
    if path.suffix != ".lean" or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"invalid Lean source path in catalogue: {relative}")
    return ".".join(path.with_suffix("").parts)


def _source_imports(path: Path) -> tuple[str, ...]:
    """Read the header imports used only to prioritize smaller internal closures first."""
    imports: list[str] = []
    in_block_comment = False
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if in_block_comment:
            if "-/" in line:
                in_block_comment = False
            continue
        if line.startswith("/-"):
            in_block_comment = "-/" not in line[2:]
            continue
        if not line or line.startswith("--") or line in {"module", "prelude"}:
            continue
        match = _IMPORT.match(raw)
        if not match:
            break
        imports.extend(match.group(1).split())
    return tuple(imports)


def internal_dependency_closures(root: Path, files: tuple[str, ...]) -> dict[str, frozenset[str]]:
    """Return each target's full source-local import closure, including the target itself."""
    visiting: set[str] = set()

    @lru_cache(maxsize=None)
    def closure(relative: str) -> frozenset[str]:
        if relative in visiting:
            raise ValueError(f"cyclic internal import while ordering catalogue: {relative}")
        visiting.add(relative)
        source = root / relative
        if not source.is_file():
            raise ValueError(f"catalogue dependency source not found: {relative}")
        result = {relative}
        for imported in _source_imports(source):
            dependency = imported.replace(".", "/") + ".lean"
            if (root / dependency).is_file():
                result.update(closure(dependency))
        visiting.remove(relative)
        return frozenset(result)

    return {relative: closure(relative) for relative in files}


def internal_dependency_order(root: Path, relative: str) -> tuple[str, ...]:
    """Return source-local imports before their consumers, ending with ``relative``."""
    visiting: set[str] = set()
    visited: set[str] = set()
    ordered: list[str] = []

    def visit(item: str) -> None:
        if item in visited:
            return
        if item in visiting:
            raise ValueError(f"cyclic internal import while ordering catalogue: {item}")
        visiting.add(item)
        source = root / item
        if not source.is_file():
            raise ValueError(f"catalogue dependency source not found: {item}")
        for imported in _source_imports(source):
            dependency = imported.replace(".", "/") + ".lean"
            if (root / dependency).is_file():
                visit(dependency)
        visiting.remove(item)
        visited.add(item)
        ordered.append(item)

    visit(relative)
    return tuple(ordered)


def order_by_missing_closure(root: Path, output_root: Path, files: tuple[str, ...]) -> list[str]:
    """Prioritize targets that can become checkable with the fewest new internal OLean files."""
    closures = internal_dependency_closures(root, files)

    def score(relative: str) -> tuple[int, int, str]:
        dependencies = closures[relative]
        missing = sum(not (output_root / Path(item).with_suffix(".olean")).is_file() for item in dependencies)
        return missing, len(dependencies), relative

    return sorted(files, key=score)


def _read_state(path: Path) -> dict:
    if not path.is_file():
        return {"schema": 1, "targets": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read progress state {path}: {exc}") from exc
    if state.get("schema") != 1 or not isinstance(state.get("targets"), dict):
        raise ValueError(f"unsupported progress state: {path}")
    return state


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build(args: argparse.Namespace) -> int:
    root = args.source_root.resolve()
    project = args.project.resolve()
    catalogue = args.catalogue.resolve()
    output_root = (args.output_root or project / ".lake" / "build" / "lib" / "lean").resolve()
    state = _read_state(args.state)
    catalogue_entries = catalogue_files(catalogue)
    closures = internal_dependency_closures(root, catalogue_entries)
    dependency_orders = {relative: internal_dependency_order(root, relative) for relative in catalogue_entries}
    files = order_by_missing_closure(root, output_root, catalogue_entries)

    def missing_outputs(relative: str) -> list[Path]:
        return [
            output_root / Path(dependency).with_suffix(".olean")
            for dependency in closures[relative]
            if not (output_root / Path(dependency).with_suffix(".olean")).is_file()
        ]

    failures = 0
    attempted = 0
    for index, relative in enumerate(files, 1):
        output = output_root / Path(relative).with_suffix(".olean")
        missing_before = missing_outputs(relative)
        if not missing_before:
            state["targets"][relative] = {
                "status": "built",
                "output_bytes": output.stat().st_size,
                "dependency_modules": len(closures[relative]),
            }
            continue
        if args.limit and attempted >= args.limit:
            break
        attempted += 1
        started = time.time()
        modules_attempted = 0
        return_code = 0
        reason = ""
        for dependency in dependency_orders[relative]:
            dependency_output = output_root / Path(dependency).with_suffix(".olean")
            if dependency_output.is_file():
                continue
            free = shutil.disk_usage(project).free
            if free < args.min_free_bytes:
                print(
                    f"stopping before {dependency}: {free:,} bytes free is below the "
                    f"{args.min_free_bytes:,}-byte guard",
                    file=sys.stderr,
                    flush=True,
                )
                _write_state(args.state, state)
                return 2
            modules_attempted += 1
            target = f"+{module_name(dependency)}:olean"
            command = [str(args.launcher), *args.launcher_arg, "build", target]
            state["targets"][relative] = {
                "status": "running",
                "started_unix": started,
                "command": command,
                "current_dependency": dependency,
                "modules_attempted": modules_attempted,
            }
            _write_state(args.state, state)
            print(
                f"[{index}/{len(files)}] building {target} for {relative} "
                f"({free:,} bytes free; module {modules_attempted}/{len(missing_before)})",
                flush=True,
            )
            try:
                done = subprocess.run(command, cwd=project, timeout=args.timeout, check=False)
            except subprocess.TimeoutExpired:
                return_code = -1
                reason = f"{dependency} timed out after {args.timeout}s"
            else:
                return_code = done.returncode
                reason = f"{dependency}: Lake exited with {return_code}" if return_code else ""
            if return_code != 0 or not dependency_output.is_file():
                if return_code == 0:
                    reason = f"Lake exited successfully but did not write {dependency_output}"
                    return_code = 1
                break
        missing_after = missing_outputs(relative)
        complete = return_code == 0 and not missing_after
        if return_code == 0 and missing_after:
            reason = f"Lake exited successfully but {len(missing_after)} internal dependency OLean files are missing"
        record = {
            "status": "built" if complete else "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "return_code": return_code,
            "output_bytes": output.stat().st_size if output.is_file() else 0,
            "dependency_modules": len(closures[relative]),
            "missing_dependencies": len(missing_after),
            "modules_attempted": modules_attempted,
        }
        if reason:
            record["reason"] = reason
        state["targets"][relative] = record
        _write_state(args.state, state)
        if record["status"] == "failed":
            failures += 1
            print(f"FAILED {relative}: {reason}", file=sys.stderr, flush=True)
            if not args.keep_going:
                return 1
    built = sum(not missing_outputs(relative) for relative in files)
    print(f"catalogue build state: {built}/{len(files)} target modules built; {failures} failed this run", flush=True)
    return 1 if failures else 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source-root", required=True, type=Path)
    result.add_argument("--project", required=True, type=Path)
    result.add_argument("--catalogue", required=True, type=Path)
    result.add_argument("--launcher", type=Path, default=Path(shutil.which("lake") or "lake"))
    result.add_argument("--launcher-arg", action="append", default=[])
    result.add_argument("--output-root", type=Path)
    result.add_argument("--state", required=True, type=Path)
    result.add_argument("--min-free-bytes", type=int, default=2_000_000_000)
    result.add_argument("--timeout", type=int, default=86_400)
    result.add_argument("--limit", type=int, default=0)
    result.add_argument("--keep-going", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        return build(parser().parse_args(argv))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
