"""Command-line entry point. The core has `build` and `extensions`; installed extensions add their own commands."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from .build import build_site
from .config import Config, load_config
from .errors import ExplainerError
from .extensions import extensions
from .lake import include_patterns, read_lake
from .version import __version__

_WARNING_PREVIEW = 20
_DEFAULT_JOBS = max(1, min(8, os.cpu_count() or 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lean4-explainer",
        description="Build a static HTML proofsite from Lean 4 source. Extensions add more (see: lean4-explainer extensions).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    build = commands.add_parser("build", help="scan Lean sources and write the site")
    roots = build.add_mutually_exclusive_group(required=True)
    roots.add_argument("--lean-root", type=Path, help="directory containing .lean files")
    roots.add_argument(
        "--lake-root", type=Path, help="Lake project root: lists the library roots named in lakefile.toml/lakefile.lean"
    )
    build.add_argument("--out", required=True, type=Path, help="output directory")
    build.add_argument("--config", type=Path, help="lean4-explainer.toml settings file")
    build.add_argument("--cache", type=Path, help="incremental build cache (default: beside --out)")
    build.add_argument("--jobs", type=int, default=_DEFAULT_JOBS, help="worker processes for indexing")

    commands.add_parser("extensions", help="list the installed extensions")

    installed = extensions()
    for ext in installed:
        ext.register_cli(commands)

    arguments = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(arguments)
    if args.command is None:
        for ext in installed:  # an extension may claim the bare command, as the corpora extension does
            default = getattr(ext, "default_command", None)
            if default:
                args = parser.parse_args([*arguments, default])
                break
        else:
            parser.print_help()
            return 2
    if args.command == "extensions":
        return _list_extensions()
    if args.command != "build":
        for ext in installed:
            result = ext.run_cli(args)
            if result is not None:
                return result
        print(f"error: no installed extension handles '{args.command}'", file=sys.stderr)
        return 1
    return _build(args)


def _list_extensions() -> int:
    installed = extensions()
    if not installed:
        print("No extensions installed. Extras: lean4-explainer[l4del], [conjectures], [tutorials], [oai], [all].")
    for ext in installed:
        print(f"{ext.name} {ext.version}")
    return 0


def _build(args) -> int:
    try:
        config = load_config(args.config)
        lean_root = args.lean_root
        if args.lake_root is not None:
            project = read_lake(args.lake_root)
            if project is None:
                raise ExplainerError(f"no lakefile.toml or lakefile.lean in {args.lake_root}")
            for message in project.issues:
                print(message)
            if not config.include and project.libs:
                config = replace(config, include=include_patterns(project))
            if config.title == Config().title:
                config = replace(config, title=project.name)
            lean_root = args.lake_root
        summary = build_site(lean_root, args.out, config, args.cache, jobs=args.jobs)
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote {summary.pages_written} pages, reused {summary.pages_reused}, to {args.out} "
        f"({summary.total_bytes / 1e6:.1f} MB total, {summary.bytes_written / 1e6:.1f} MB written)"
    )
    print(
        f"{summary.files} files, {summary.declarations} declarations, {summary.sorry} containing sorry, "
        f"{summary.axioms} axioms; {summary.search_entries} search entries. "
        "Lean not run; axiom and trust checks UNKNOWN."
    )
    for line in summary.extension_lines:
        print(line)
    if summary.identical_names or summary.variant_names:
        print(duplicates_line(summary.identical_names, summary.variant_names))
    for message in summary.errors:
        print(message, file=sys.stderr)
    for message in summary.warnings[:_WARNING_PREVIEW]:
        print(message)
    hidden = len(summary.warnings) - _WARNING_PREVIEW
    if hidden > 0:
        print(f"warning: {hidden} more not shown")
    if summary.errors:
        print(f"build failed with {len(summary.errors)} error(s)", file=sys.stderr)
        return 1
    if summary.over_budget:
        print(
            f"error: output is {summary.total_bytes} bytes, over the {summary.byte_budget} byte budget",
            file=sys.stderr,
        )
        return 1
    return 0


def duplicates_line(identical: int, variant: int) -> str:
    return (
        f"same-named declarations: {identical} identical copies (one object each), "
        f"{variant} with distinct definitions (qualify references as Name@path)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
