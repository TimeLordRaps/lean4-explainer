"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dataclasses import replace

from .build import annotation_templates, build_site, check_tree
from .config import Config, load_config
from .corpora import CORPORA, select
from .errors import ExplainerError
from .lake import include_patterns, read_lake
from .showcase import build_showcase, fetch_corpus
from .version import __version__

_WARNING_PREVIEW = 20
_DEFAULT_JOBS = max(1, min(8, os.cpu_count() or 1))
_WORK_DEFAULT = ".lean4-explainer-work"
_SITE_DEFAULT = "lean4-explainer-site"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lean4-explainer",
        description="Build a static HTML proofsite from Lean 4 source, with L4DEL annotation checks.",
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

    check = commands.add_parser("check", help="validate L4DEL and names without writing a site")
    check.add_argument("--lean-root", required=True, type=Path, help="directory containing .lean files")
    check.add_argument("--config", type=Path, help="lean4-explainer.toml settings file")
    check.add_argument("--cache", type=Path, help="optional cache directory to reuse")
    check.add_argument("--jobs", type=int, default=_DEFAULT_JOBS, help="worker processes for indexing")

    annotate = commands.add_parser("annotate", help="print L4DEL templates for one Lean file")
    annotate.add_argument("--lean-root", required=True, type=Path, help="directory containing .lean files")
    annotate.add_argument("--file", required=True, help="path of the file relative to the lean root")
    annotate.add_argument("--config", type=Path, help="lean4-explainer.toml settings file")
    annotate.add_argument("--cache", type=Path, help="optional cache directory to reuse")

    sources = commands.add_parser("sources", help="list the built-in corpora and their pinned commits")
    sources.add_argument("names", nargs="*", help="corpus names or extras (default: all)")

    fetch = commands.add_parser("fetch", help="download built-in corpora at their pinned commits")
    fetch.add_argument("names", nargs="*", help="corpus names or extras (default: all)")
    fetch.add_argument("--work", type=Path, default=Path(_WORK_DEFAULT), help="where checkouts are kept")
    fetch.add_argument("--yes", action="store_true", help="download without asking")

    showcase = commands.add_parser("showcase", help="fetch corpora and build one subsite each under a landing page")
    showcase.add_argument("names", nargs="*", help="corpus names or extras (default: all)")
    showcase.add_argument("--out", type=Path, default=Path(_SITE_DEFAULT), help="output directory")
    showcase.add_argument("--work", type=Path, default=Path(_WORK_DEFAULT), help="where checkouts are kept")
    showcase.add_argument("--jobs", type=int, default=_DEFAULT_JOBS, help="worker processes for indexing")
    showcase.add_argument("--yes", action="store_true", help="download without asking")

    arguments = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(arguments)
    if args.command is None:  # a bare `lean4-explainer` is the showcase of every built-in corpus
        args = parser.parse_args([*arguments, "showcase"])
    if args.command == "check":
        return _check(args)
    if args.command == "annotate":
        return _annotate(args)
    if args.command == "sources":
        return _sources(args)
    if args.command == "fetch":
        return _fetch(args)
    if args.command == "showcase":
        return _showcase(args)
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
        f"{summary.axioms} axioms; L4DEL: {summary.annotated} annotated, {summary.flagged} flagged, "
        f"{summary.unannotated} without L4DEL; {summary.search_entries} search entries, "
        f"{summary.glossary_terms} glossary terms, {summary.learning_steps} learning-path steps. "
        "Lean not run; axiom and trust checks UNKNOWN."
    )
    if summary.identical_names or summary.variant_names:
        print(_duplicates(summary.identical_names, summary.variant_names))
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


def _duplicates(identical: int, variant: int) -> str:
    return (
        f"same-named declarations: {identical} identical copies (one object each), "
        f"{variant} with distinct definitions (qualify references as Name@path)"
    )


def _check(args) -> int:
    try:
        config = load_config(args.config)
        tree = check_tree(args.lean_root, config, args.cache, jobs=args.jobs)
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = [issue for issue in tree.issues if issue.startswith("error:")]
    warnings = [issue for issue in tree.issues if issue.startswith("warning:")]
    for message in errors:
        print(message, file=sys.stderr)
    for message in warnings[:_WARNING_PREVIEW]:
        print(message)
    print(
        f"{len(tree.sources)} files checked; L4DEL: {tree.annotated} annotated, {tree.flagged} flagged, "
        f"{tree.unannotated} without L4DEL; {len(errors)} errors, {len(warnings)} warnings"
    )
    if tree.objects.identical or tree.objects.variant:
        print(_duplicates(tree.objects.identical, tree.objects.variant))
    return 1 if errors else 0


def _annotate(args) -> int:
    try:
        config = load_config(args.config)
        text = annotation_templates(args.lean_root, args.file, config, args.cache)
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(text)
    return 0


def _sources(args) -> int:
    try:
        corpora = select(*args.names)
    except ExplainerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for corpus in corpora:
        print(f"{corpus.name:<20} {corpus.kind:<13} {corpus.repo}@{corpus.commit[:12]}  {corpus.title}")
    return 0


def _plan(corpora, verb: str) -> str:
    lines = [f"{verb} {len(corpora)} corpora from github.com (shallow fetch of one pinned commit each):"]
    lines += [f"  {c.name:<20} {c.repo}@{c.commit[:12]}" for c in corpora]
    return "\n".join(lines)


def _confirmed(args, plan: str) -> bool:
    print(plan)
    if args.yes:
        return True
    if sys.stdin is not None and sys.stdin.isatty():
        return input("Proceed? [y/N] ").strip().lower() in ("y", "yes")
    print("Nothing was downloaded. Re-run with --yes to proceed.")
    return False


def _fetch(args) -> int:
    try:
        corpora = select(*args.names)
        if not _confirmed(args, _plan(corpora, "Will download")):
            return 2
        for corpus in corpora:
            print(f"fetched {corpus.name} to {fetch_corpus(corpus, args.work)}")
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _showcase(args) -> int:
    try:
        corpora = select(*args.names)
        if not _confirmed(args, _plan(corpora, "Will download and build")):
            return 2
        chosen = {c.name for c in corpora}
        result = build_showcase(
            corpora,
            args.work,
            args.out,
            link_out=[c for c in CORPORA.values() if c.name not in chosen],
            jobs=args.jobs,
        )
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for item in result.items:
        s = item.summary
        print(
            f"{item.corpus.name}: {s.files} files, {s.declarations} declarations, {s.sorry} containing sorry, "
            f"{s.total_bytes / 1e6:.1f} MB in {item.seconds:.0f}s"
        )
    print(f"wrote {args.out} ({result.total_bytes / 1e6:.1f} MB). Lean not run; axiom and trust checks UNKNOWN.")
    if result.over_budget:
        print(f"error: output is {result.total_bytes} bytes, over the {result.byte_budget} byte budget", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
