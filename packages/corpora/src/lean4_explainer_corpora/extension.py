"""The corpora extension: `sources`, `fetch` and `showcase` for the installed lean4-explainer-<name> corpora."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import Extension

from . import registry, showcase

__version__ = "0.4.0"
_WORK_DEFAULT = ".lean4-explainer-work"
_SITE_DEFAULT = "lean4-explainer-site"
_DEFAULT_JOBS = max(1, min(8, os.cpu_count() or 1))
_WARNING_PREVIEW = 20  # per corpus, as `build` shows them


class CorporaExtension(Extension):
    name = "corpora"
    version = __version__
    default_command = "showcase"  # a bare `lean4-explainer` builds the showcase
    config_keys = {"theme_css": str}  # a corpus theme: CSS appended to the site stylesheet

    def css(self, options) -> str:
        return str(options.get("theme_css", ""))

    def fingerprint(self, options) -> str:
        return f"{self.name}:{self.version}"

    def register_cli(self, commands: argparse._SubParsersAction) -> None:
        sources = commands.add_parser("sources", help="list the installed corpora and their pinned commits")
        sources.add_argument("names", nargs="*", help="corpus names or extras (default: all installed)")
        fetch = commands.add_parser("fetch", help="download corpora at their pinned commits")
        fetch.add_argument("names", nargs="*", help="corpus names or extras (default: all installed)")
        fetch.add_argument("--work", type=Path, default=Path(_WORK_DEFAULT), help="where checkouts are kept")
        fetch.add_argument("--yes", action="store_true", help="download without asking")
        build = commands.add_parser("showcase", help="fetch corpora and build one subsite each under a landing page")
        build.add_argument("names", nargs="*", help="corpus names or extras (default: all installed)")
        build.add_argument("--out", type=Path, default=Path(_SITE_DEFAULT), help="output directory")
        build.add_argument("--work", type=Path, default=Path(_WORK_DEFAULT), help="where checkouts are kept")
        build.add_argument("--jobs", type=int, default=_DEFAULT_JOBS, help="worker processes for indexing")
        build.add_argument(
            "--site-url",
            help="canonical public HTTPS URL for metadata, robots.txt and sitemaps (for example https://example.org/site/)",
        )
        build.add_argument(
            "--overlay-manifest",
            type=Path,
            help="explicit hosted-overlay manifest (content, corpus repository and commit are verified)",
        )
        build.add_argument("--yes", action="store_true", help="download without asking")

    def run_cli(self, args: argparse.Namespace) -> int | None:
        if args.command == "sources":
            return _sources(args)
        if args.command == "fetch":
            return _fetch(args)
        if args.command == "showcase":
            return _showcase(args)
        return None


def _sources(args) -> int:
    try:
        corpora = registry.select(*args.names)
    except ExplainerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for corpus in corpora:
        print(f"{corpus.name:<20} {corpus.kind:<13} {corpus.repo}@{corpus.commit[:12]}  {corpus.license}  {corpus.title}")
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
        try:
            return input("Proceed? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:  # Windows calls NUL a terminal: `< /dev/null` gets here
            print()
    print("Nothing was downloaded. Re-run with --yes to proceed.")
    return False


def _fetch(args) -> int:
    try:
        corpora = registry.select(*args.names)
        if not _confirmed(args, _plan(corpora, "Will download")):
            return 2
        for corpus in corpora:
            print(f"fetched {corpus.name} to {showcase.fetch_corpus(corpus, args.work)}")
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _showcase(args) -> int:
    try:
        corpora = registry.select(*args.names)
        if not _confirmed(args, _plan(corpora, "Will download and build")):
            return 2
        chosen = {c.name for c in corpora}
        result = showcase.build_showcase(
            corpora,
            args.work,
            args.out,
            link_out=[c for c in registry.installed().values() if c.name not in chosen],
            jobs=args.jobs,
            overlay_manifest=args.overlay_manifest,
            site_url=args.site_url,
        )
    except (ExplainerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = 0
    for item in result.items:
        s = item.summary
        print(
            f"{item.corpus.name}: {s.files} files, {s.declarations} declarations, {s.sorry} containing sorry, "
            f"{s.total_bytes / 1e6:.1f} MB in {item.seconds:.0f}s"
        )
        # as `build` reports them: every error, the first few warnings
        for message in s.errors:
            print(f"{item.corpus.name}: {message}", file=sys.stderr)
        for message in s.warnings[:_WARNING_PREVIEW]:
            print(f"{item.corpus.name}: {message}")
        if len(s.warnings) > _WARNING_PREVIEW:
            print(f"{item.corpus.name}: warning: {len(s.warnings) - _WARNING_PREVIEW} more not shown")
        for line in s.extension_lines:
            print(f"{item.corpus.name}: {line}")
        errors += len(s.errors)
    lean_lines = [
        line
        for item in result.items
        for line in item.summary.extension_lines
        if line.startswith("lean ") or line.startswith("lean(")
    ]
    verification = (
        " Lean-backed trust results were produced locally; see each Trust page for UNKNOWN files."
        if any("Lean not found" not in line for line in lean_lines)
        else " Lean not run; axiom and trust checks UNKNOWN."
    )
    print(f"wrote {args.out} ({result.total_bytes / 1e6:.1f} MB).{verification}")
    failed = 0
    if errors:
        print(f"error: {errors} build error(s): the site was written, but should not be published as it is", file=sys.stderr)
        failed = 1
    if result.over_budget:
        print(f"error: output is {result.total_bytes} bytes, over the {result.byte_budget} byte budget", file=sys.stderr)
        failed = 1
    return failed
