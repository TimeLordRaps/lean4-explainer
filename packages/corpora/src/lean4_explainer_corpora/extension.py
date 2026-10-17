"""The corpora extension: `sources`, `fetch` and `showcase` for the installed lean4-explainer-<name> corpora."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import Extension

from . import registry, showcase

__version__ = "0.5.0"
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
        build.add_argument(
            "--lean-project",
            action="append",
            default=[],
            metavar="CORPUS=PATH",
            help="exact local Lake environment used to verify one corpus (repeatable)",
        )
        build.add_argument(
            "--lean-cache",
            action="append",
            default=[],
            metavar="CORPUS=PATH",
            help="content-bound Lean evidence cache for one corpus (repeatable)",
        )
        build.add_argument(
            "--lean-cached-only",
            action="append",
            default=[],
            metavar="CORPUS",
            help="reuse clean cached Lean evidence for one corpus and mark cache misses UNKNOWN (repeatable)",
        )
        build.add_argument(
            "--lean-file-limit",
            action="append",
            default=[],
            metavar="CORPUS=COUNT",
            help="diagnostic bound for one corpus's Lean pass; 0 means every declaration file (repeatable)",
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
        names = {corpus.name for corpus in corpora}
        lean_projects = _named_paths(args.lean_project, names)
        lean_caches = _named_cache_paths(args.lean_cache, names)
        lean_cached_only = _selected_names(args.lean_cached_only, "--lean-cached-only", names)
        lean_file_limits = _named_counts(args.lean_file_limit, names)
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
            lean_projects=lean_projects,
            lean_caches=lean_caches,
            lean_cached_only=lean_cached_only,
            lean_file_limits=lean_file_limits,
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


def _named_paths(values: list[str], selected: set[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for value in values:
        name, raw = _named_value(value, "--lean-project", selected, found)
        path = Path(raw).resolve()
        if not path.is_dir() or not any(path.joinpath(lakefile).is_file() for lakefile in ("lakefile.toml", "lakefile.lean")):
            raise ExplainerError(f"--lean-project for {name} must be a directory containing a lakefile: {path}")
        found[name] = path
    return found


def _named_cache_paths(values: list[str], selected: set[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for value in values:
        name, raw = _named_value(value, "--lean-cache", selected, found)
        path = Path(raw).resolve()
        if path.exists() and not path.is_dir():
            raise ExplainerError(f"--lean-cache for {name} must be a directory path: {path}")
        found[name] = path
    return found


def _selected_names(values: list[str], option: str, selected: set[str]) -> set[str]:
    found: set[str] = set()
    for name in values:
        if name not in selected:
            raise ExplainerError(f"{option} names unselected corpus '{name}'")
        if name in found:
            raise ExplainerError(f"{option} was supplied more than once for '{name}'")
        found.add(name)
    return found


def _named_counts(values: list[str], selected: set[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for value in values:
        name, raw = _named_value(value, "--lean-file-limit", selected, found)
        try:
            count = int(raw)
        except ValueError as exc:
            raise ExplainerError(f"--lean-file-limit for {name} must be a non-negative integer") from exc
        if count < 0:
            raise ExplainerError(f"--lean-file-limit for {name} must be a non-negative integer")
        found[name] = count
    return found


def _named_value(value: str, option: str, selected: set[str], found: dict[str, object]) -> tuple[str, str]:
    name, separator, raw = value.partition("=")
    if not separator or not name or not raw:
        raise ExplainerError(f"{option} must use CORPUS=VALUE")
    if name not in selected:
        raise ExplainerError(f"{option} names unselected corpus '{name}'")
    if name in found:
        raise ExplainerError(f"{option} was supplied more than once for '{name}'")
    return name, raw
