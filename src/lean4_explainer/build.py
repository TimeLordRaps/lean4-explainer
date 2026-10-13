"""Index a Lean tree and write the proofsite. Extensions add to both steps (see extensions.py)."""

from __future__ import annotations

import fnmatch
import gc
import hashlib
import os
from array import array
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from .cache import Cache, FileIndex, load_cache, save_cache
from .config import GLOSSARY_SCOPES, IMPORT_SCOPES, Config
from .errors import ExplainerError
from .extensions import Extension, extensions
from .glossary import VOCABULARY_KINDS, glossary_pages, record
from .imports import modules
from .objects import Copy, Objects, index_objects
from .render import (
    ASSET_DIR,
    FAVICON_SVG,
    SITE_CSS,
    SITE_JS,
    Context,
    file_page,
    folder_pages,
    search_page,
)
from .scan import Declaration, FileSummary, LeanFile, iter_lean_files, parse_source
from .search import write_search
from .version import __version__

__all__ = [
    "BuildSummary",
    "ExplainerError",
    "TreeIndex",
    "build_site",
    "check_tree",
    "collect_tree",
]

CACHE_FORMAT = 9
# Rendered-page compatibility is separate from the parsed-source cache. Increment this when
# shared HTML changes so incremental builds rewrite pages without needlessly rescanning Lean.
PAGE_FORMAT = 6
# Lake's build configuration and its older dependency directory are not library source. Always skipped,
# at the root and in any subdirectory, on top of the user's exclude patterns. Hidden directories (.lake)
# are already skipped by the scanner.
_LAKE_EXCLUDE = ("lakefile.lean", "*/lakefile.lean", "lake-packages/*", "*/lake-packages/*")
CACHE_FILE = "index.pickle"
_SHIFT = 20
_SLOT_MASK = (1 << _SHIFT) - 1


@dataclass
class TreeIndex:
    sources: list[tuple[str, Path]]
    cache: Cache
    stale: list[str]
    locations: dict[str, tuple[str, int]]
    objects: Objects
    summaries: list[FileSummary]
    issues: list[str]
    described: frozenset[str]
    analyses: list[tuple[Extension, object]]  # each active extension with its analysis of this tree


@dataclass(frozen=True)
class BuildSummary:
    files: int
    declarations: int
    sorry: int
    axioms: int
    pages_written: int
    pages_reused: int
    bytes_written: int
    total_bytes: int
    byte_budget: int
    search_entries: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    identical_names: int
    variant_names: int
    extension_lines: tuple[str, ...] = ()  # what each extension reports after a build

    @property
    def over_budget(self) -> bool:
        return self.total_bytes > self.byte_budget


def default_cache_dir(out_dir: Path) -> Path:
    return out_dir.parent / f".{out_dir.name}-cache"


def collect_tree(lean_root: Path, config: Config, cache_dir: Path, jobs: int = 1) -> TreeIndex:
    if not lean_root.is_dir():
        raise ExplainerError(f"lean root is not a directory: {lean_root}")
    if config.glossary not in GLOSSARY_SCOPES:
        raise ExplainerError(f"glossary must be one of {', '.join(GLOSSARY_SCOPES)}, not {config.glossary!r}")
    if config.imports not in IMPORT_SCOPES:
        raise ExplainerError(f"imports must be one of {', '.join(IMPORT_SCOPES)}, not {config.imports!r}")
    patterns = (*config.exclude, *_LAKE_EXCLUDE)
    sources = [
        (rel, path)
        for rel, path in iter_lean_files(lean_root)
        if not _excluded(rel, patterns) and (not config.include or _excluded(rel, config.include))
    ]
    if not sources:
        raise ExplainerError(f"no .lean files found under {lean_root}")
    active = extensions()
    cache = load_cache(cache_dir / CACHE_FILE, _fingerprint(config))
    live = {rel for rel, _ in sources}
    stale = sorted(set(cache.files) - live)
    for rel in stale:
        del cache.files[rel]
        cache.pages.pop(rel, None)
    jobs_list = [
        (rel, str(path), cache.files[rel].sha if rel in cache.files else "", config.options, config.extra_kinds, config.glossary)
        for rel, path in sources
    ]
    if jobs > 1 and len(jobs_list) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            refreshed = list(pool.map(_refresh_file, jobs_list, chunksize=64))
    else:
        refreshed = [_refresh_file(job) for job in jobs_list]
    for rel, _, entry in refreshed:
        if entry is not None:
            cache.files[rel] = entry
    rels = [rel for rel, _ in sources]
    first: dict[str, int] = {}
    extra: dict[str, list[int]] = {}
    summaries: list[FileSummary] = []
    issues: list[str] = []
    described: set[str] = set()
    for file_ord, rel in enumerate(rels):
        entry = cache.files[rel]
        summaries.append(FileSummary(rel, entry.declarations, entry.sorry, entry.axioms, len(entry.imports), entry.import_only))
        names = entry.names.split("\n") if entry.names else []
        if len(names) > _SLOT_MASK:
            raise ExplainerError(f"too many declarations in {rel}")
        base = file_ord << _SHIFT
        for slot, name in enumerate(names):
            ref = base | slot
            seen = first.get(name)
            if seen is None:
                first[name] = ref
            else:
                extra.setdefault(name, [seen]).append(ref)
        issues.extend(entry.diagnostics)
        if entry.described:
            described.update(entry.described.split("\n"))

    def copy_at(ref: int) -> Copy:
        rel = rels[ref >> _SHIFT]
        entry = cache.files[rel]
        slot = ref & _SLOT_MASK
        return Copy(rel, entry.lines[slot], entry.codes[slot], entry.headers[slot])

    objects = replace(index_objects(first, extra, copy_at), modules=modules({rel: cache.files[rel].imports for rel in rels}))
    issues.extend(objects.issues)
    options = {**dict(config.options), "_root": str(lean_root)}  # `_root`: where the sources are, for extensions that read them
    analyses: list[tuple[Extension, object]] = []
    for ext in active:
        per_file = {rel: dict(cache.files[rel].ext).get(ext.name) for rel in rels}
        analysis = ext.analyze(objects, per_file, options)
        analyses.append((ext, analysis))
        issues.extend(ext.analysis_issues(analysis))
    for ext, analysis in analyses:  # issues that need what another extension found, such as a proof Lean checked
        issues.extend(ext.review(analysis, tuple(analyses)))
    return TreeIndex(
        sources=sources,
        cache=cache,
        stale=stale,
        locations=objects.locations,
        objects=objects,
        summaries=summaries,
        issues=issues,
        described=frozenset(described),
        analyses=analyses,
    )


def build_site(
    lean_root: Path,
    out_dir: Path,
    config: Config | None = None,
    cache_dir: Path | None = None,
    jobs: int = 1,
) -> BuildSummary:
    """Pause the cyclic collector: the index holds millions of acyclic objects."""
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        return _build_site(lean_root, out_dir, config, cache_dir, jobs)
    finally:
        if was_enabled:
            gc.enable()


def _build_site(
    lean_root: Path,
    out_dir: Path,
    config: Config | None,
    cache_dir: Path | None,
    jobs: int,
) -> BuildSummary:
    config = config or Config()
    cache_dir = cache_dir or default_cache_dir(out_dir)
    tree = collect_tree(lean_root, config, cache_dir, jobs)
    for rel in tree.stale:
        (out_dir / (rel + ".html")).unlink(missing_ok=True)
    digest = hashlib.sha256(f"{_fingerprint(config)}|page:{PAGE_FORMAT}".encode("utf-8"))
    for rel, _ in tree.sources:
        entry = tree.cache.files[rel]
        digest.update(rel.encode("utf-8") + b"\0" + entry.names.encode("utf-8") + b"\0" + entry.lines.tobytes())
        digest.update(b"\0".join(name.encode("utf-8") for name in entry.imports) + b"\1")  # a page lists who imports it
    for ext, analysis in tree.analyses:
        digest.update(repr((ext.name, ext.fingerprint(dict(config.options)), analysis)).encode("utf-8"))
    for name in sorted(tree.objects.copies):
        digest.update(repr((name, tree.objects.copies[name])).encode("utf-8"))
    global_key = digest.hexdigest()
    ctx = Context(
        title=config.title,
        source_url=config.source_url,
        source_ref=config.source_ref,
        locations=tree.locations,
        cross_links=config.cross_links,
        search=config.search,
        status=" ".join(filter(None, (ext.status(analysis) for ext, analysis in tree.analyses))),
        objects=tree.objects,
        extensions=tuple(tree.analyses),
        options=config.options + (("_root", str(lean_root)),),  # as `analyze` gets them: `_root` is where the sources are
        home=config.home,
        site_url=config.site_url,
        description=config.description,
        project_url=config.project_url,
        report_url=config.report_url,
        source_links=config.source_links,
        imports=config.imports,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    written = _write(out_dir / ASSET_DIR / "site.css", SITE_CSS + "".join(ext.css(dict(config.options)) for ext, _ in tree.analyses))
    written += _write(out_dir / ASSET_DIR / "favicon.svg", FAVICON_SVG)
    written += _write(out_dir / ASSET_DIR / "site.js", SITE_JS)
    written += _write(out_dir / ".nojekyll", "")

    pages_written = pages_reused = 0
    for rel, path in tree.sources:
        target = out_dir / (rel + ".html")
        page_key = hashlib.sha256(f"{tree.cache.files[rel].sha}|{global_key}".encode("utf-8")).hexdigest()
        if tree.cache.pages.get(rel) == page_key and target.is_file():
            pages_reused += 1
            continue
        text = path.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
        lean_file = parse_source(text, rel, options=dict(config.options), extra_kinds=config.extra_kinds)
        written += _write(target, file_page(lean_file, ctx, text))
        tree.cache.pages[rel] = page_key
        pages_written += 1

    for dirs, html in folder_pages(tree.summaries, ctx):
        written += _write(out_dir.joinpath(*dirs, "index.html"), html)
    for ext, analysis in tree.analyses:
        for name, html in ext.pages(ctx, analysis).items():
            written += _write(out_dir / name, html)
    # after the extensions' pages: the glossary is the core's, whatever an older extension writes
    sections = [section for ext, analysis in tree.analyses for section in ext.glossary(ctx, analysis)]
    records = ((rel, item) for rel, _ in tree.sources for item in tree.cache.files[rel].vocabulary)
    glossary = glossary_pages(ctx, records, sections, config.glossary)
    for old in out_dir.glob("glossary-*.html"):  # letter pages of an earlier, bigger build
        if old.name not in glossary:
            old.unlink()
    for name, html in glossary.items():
        written += _write(out_dir / name, html)
    search_entries = 0
    if config.search:
        written += _write(out_dir / "search.html", search_page(ctx))
        # Every declaration stays listed on its file page. Search covers only the ones with explanation text,
        # which keeps the index small enough for a full openai/math build to fit under the Pages limit.
        searchable = {name: where for name, where in tree.locations.items() if name in tree.described}
        entries, search_bytes = write_search(
            searchable,
            lambda parts, text: _write(out_dir.joinpath(*parts), text),
        )
        search_entries = entries
        written += search_bytes

    save_cache(cache_dir / CACHE_FILE, tree.cache)
    return BuildSummary(
        files=len(tree.sources),
        declarations=sum(s.declarations for s in tree.summaries),
        sorry=sum(s.sorry for s in tree.summaries),
        axioms=sum(s.axioms for s in tree.summaries),
        pages_written=pages_written,
        pages_reused=pages_reused,
        bytes_written=written,
        total_bytes=_tree_bytes(out_dir),
        byte_budget=config.byte_budget,
        search_entries=search_entries,
        errors=tuple(issue for issue in tree.issues if issue.startswith("error:")),
        warnings=tuple(issue for issue in tree.issues if issue.startswith("warning:")),
        identical_names=tree.objects.identical,
        variant_names=tree.objects.variant,
        extension_lines=tuple(line for ext, analysis in tree.analyses for line in ext.summary(analysis)),
    )


def check_tree(
    lean_root: Path, config: Config | None = None, cache_dir: Path | None = None, jobs: int = 1
) -> TreeIndex:
    config = config or Config()
    return collect_tree(lean_root, config, cache_dir or lean_root.parent / ".lean4-explainer-check", jobs)


def _index_of(lean_file: LeanFile, sha: str, glossary: str = "all") -> FileIndex:
    named = [decl for decl in lean_file.declarations if "(" not in decl.name]
    active = extensions()
    described = [
        decl for decl in named
        if decl.description or any(ext.is_described(decl.ext[ext.name]) for ext in active if ext.name in decl.ext)
    ]
    listed = {"all": named, "described": described, "none": []}[glossary]
    summaries: list[tuple[str, object]] = []
    diagnostics: list[str] = []
    for ext in active:
        summary = ext.index_file(lean_file.path, lean_file.declarations, lean_file.diagnostics.get(ext.name, ()))
        if summary is not None:
            summaries.append((ext.name, summary))
            diagnostics.extend(ext.issues(lean_file.path, summary))
    return FileIndex(
        sha=sha,
        declarations=len(lean_file.declarations),
        sorry=sum(decl.has_sorry for decl in lean_file.declarations),
        axioms=sum(decl.kind == "axiom" for decl in lean_file.declarations),
        names="\n".join(decl.name for decl in named),
        lines=array("I", (decl.line for decl in named)),
        codes=array("Q", (decl.code_digest for decl in named)),
        headers=array("Q", (decl.header_digest for decl in named)),
        diagnostics=tuple(diagnostics),
        described="\n".join(decl.name for decl in described),
        ext=tuple(summaries),
        vocabulary=tuple(record(decl, _describe(decl, active)) for decl in listed if decl.kind in VOCABULARY_KINDS),
        imports=lean_file.imports,
        import_only=lean_file.import_only,
    )


def _describe(decl: Declaration, active: tuple[Extension, ...]) -> str:
    """The first extension's one-line description of a declaration, for one with no comment of its own."""
    return next((text for ext in active if ext.name in decl.ext for text in (ext.describe(decl.ext[ext.name]),) if text), "")


def _refresh_file(job: tuple[str, str, str, tuple[tuple[str, object], ...], tuple[str, ...], str]) -> tuple[str, str, FileIndex | None]:
    """Hash a file; index it only if its hash differs from the cached one. Runs in worker processes."""
    rel, path, known, options, extra_kinds, glossary = job
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha == known:
        return rel, sha, None
    lean_file = parse_source(
        data.decode("utf-8-sig", errors="replace"),
        rel,
        options=dict(options),
        extra_kinds=extra_kinds,
        statement_kinds=VOCABULARY_KINDS if glossary == "all" else (),  # an undescribed definition shows its signature
    )
    return rel, sha, _index_of(lean_file, sha, glossary)


def _fingerprint(config: Config) -> str:
    installed = "|".join(ext.fingerprint(dict(config.options)) for ext in extensions())
    return hashlib.sha256(f"{__version__}|{CACHE_FORMAT}|{config!r}|{installed}".encode("utf-8")).hexdigest()


def _excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def _tree_bytes(root: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            total += os.path.getsize(os.path.join(dirpath, name))
    return total


def _write(path: Path, text: str | bytes) -> int:
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    try:
        path.write_bytes(data)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return len(data)
