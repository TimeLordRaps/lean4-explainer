"""Index a Lean tree, check its L4DEL annotations, and write the proofsite."""

from __future__ import annotations

import fnmatch
import gc
import hashlib
import os
from array import array
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .cache import Cache, FileIndex, Note, load_cache, save_cache
from .config import Config
from .errors import ExplainerError
from .graph import build_glossary, build_learning_path, merge_notes, unresolved_links
from .objects import Copy, Objects, index_objects
from .render import (
    ASSET_DIR,
    SITE_CSS,
    SITE_JS,
    Context,
    file_page,
    folder_pages,
    glossary_page,
    guide_page,
    learning_path_page,
    search_page,
    term_pattern,
)
from .scan import FileSummary, LeanFile, iter_lean_files, parse_source
from .search import write_search
from .templates import annotation_report, annotation_state
from .version import __version__

__all__ = [
    "BuildSummary",
    "ExplainerError",
    "TreeIndex",
    "annotation_templates",
    "build_site",
    "check_tree",
    "collect_tree",
]

CACHE_FORMAT = 6
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
    notes: list[Note]
    issues: list[str]
    graph_issues: list[str]
    terms: dict
    steps: list
    anchors: dict[str, str]
    annotated: int
    flagged: int
    unannotated: int
    described: frozenset[str]


@dataclass(frozen=True)
class BuildSummary:
    files: int
    declarations: int
    sorry: int
    axioms: int
    annotated: int
    flagged: int
    unannotated: int
    pages_written: int
    pages_reused: int
    bytes_written: int
    total_bytes: int
    byte_budget: int
    search_entries: int
    glossary_terms: int
    learning_steps: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    identical_names: int
    variant_names: int

    @property
    def over_budget(self) -> bool:
        return self.total_bytes > self.byte_budget


def default_cache_dir(out_dir: Path) -> Path:
    return out_dir.parent / f".{out_dir.name}-cache"


def collect_tree(lean_root: Path, config: Config, cache_dir: Path, jobs: int = 1) -> TreeIndex:
    if not lean_root.is_dir():
        raise ExplainerError(f"lean root is not a directory: {lean_root}")
    patterns = (*config.exclude, *_LAKE_EXCLUDE)
    sources = [
        (rel, path)
        for rel, path in iter_lean_files(lean_root)
        if not _excluded(rel, patterns) and (not config.include or _excluded(rel, config.include))
    ]
    if not sources:
        raise ExplainerError(f"no .lean files found under {lean_root}")
    cache = load_cache(cache_dir / CACHE_FILE, _fingerprint(config))
    live = {rel for rel, _ in sources}
    stale = sorted(set(cache.files) - live)
    for rel in stale:
        del cache.files[rel]
        cache.pages.pop(rel, None)
    jobs_list = [(rel, str(path), cache.files[rel].sha if rel in cache.files else "") for rel, path in sources]
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
    notes: list[Note] = []
    issues: list[str] = []
    annotated = flagged = unannotated = 0
    described: set[str] = set()
    for file_ord, rel in enumerate(rels):
        entry = cache.files[rel]
        summaries.append(FileSummary(rel, entry.declarations, entry.sorry, entry.axioms))
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
        notes.extend(entry.notes)
        issues.extend(entry.diagnostics)
        annotated += entry.annotated
        flagged += entry.flagged
        unannotated += entry.unannotated
        if entry.described:
            described.update(entry.described.split("\n"))

    def copy_at(ref: int) -> Copy:
        rel = rels[ref >> _SHIFT]
        entry = cache.files[rel]
        slot = ref & _SLOT_MASK
        return Copy(rel, entry.lines[slot], entry.codes[slot], entry.headers[slot])

    objects = index_objects(first, extra, copy_at)
    merged, merge_issues = merge_notes(notes, objects)
    terms, term_issues = build_glossary(merged)
    steps, path_issues = build_learning_path(merged, objects) if config.learning_path else ([], [])
    graph_issues = [*merge_issues, *path_issues, *unresolved_links(notes, objects)]
    issues.extend([*objects.issues, *term_issues, *graph_issues])
    anchors = {term: f"t{index}" for index, term in enumerate(sorted(terms, key=str.lower))}
    return TreeIndex(
        sources=sources,
        cache=cache,
        stale=stale,
        locations=objects.locations,
        objects=objects,
        summaries=summaries,
        notes=notes,
        issues=issues,
        graph_issues=graph_issues,
        terms=terms,
        steps=steps,
        anchors=anchors,
        annotated=annotated,
        flagged=flagged,
        unannotated=unannotated,
        described=frozenset(described),
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
    digest = hashlib.sha256(_fingerprint(config).encode("utf-8"))
    for rel, _ in tree.sources:
        entry = tree.cache.files[rel]
        digest.update(rel.encode("utf-8") + b"\0" + entry.names.encode("utf-8") + b"\0" + entry.lines.tobytes())
    for note in tree.notes:
        digest.update(repr(note).encode("utf-8"))
    for name in sorted(tree.objects.copies):
        digest.update(repr((name, tree.objects.copies[name])).encode("utf-8"))
    global_key = digest.hexdigest()
    ctx = Context(
        title=config.title,
        source_url=config.source_url,
        source_ref=config.source_ref,
        locations=tree.locations,
        glossary=tree.terms,
        term_anchors=tree.anchors,
        term_pattern=term_pattern(tree.terms),
        cross_links=config.cross_links,
        search=config.search,
        learning_path=config.learning_path,
        status=_status(tree),
        objects=tree.objects,
        home=config.home,
        source_links=config.source_links,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    written = _write(out_dir / ASSET_DIR / "site.css", SITE_CSS)
    written += _write(out_dir / ASSET_DIR / "site.js", SITE_JS)
    written += _write(out_dir / ".nojekyll", "")

    pages_written = pages_reused = 0
    for rel, path in tree.sources:
        target = out_dir / (rel + ".html")
        page_key = hashlib.sha256(f"{tree.cache.files[rel].sha}|{global_key}".encode("utf-8")).hexdigest()
        if tree.cache.pages.get(rel) == page_key and target.is_file():
            pages_reused += 1
            continue
        lean_file = parse_source(path.read_bytes().decode("utf-8-sig", errors="replace"), rel)
        written += _write(target, file_page(lean_file, ctx))
        tree.cache.pages[rel] = page_key
        pages_written += 1

    for dirs, html in folder_pages(tree.summaries, ctx):
        written += _write(out_dir.joinpath(*dirs, "index.html"), html)
    written += _write(out_dir / "glossary.html", glossary_page(ctx))
    written += _write(out_dir / "annotate.html", guide_page(ctx))
    if config.learning_path:
        written += _write(out_dir / "learning-path.html", learning_path_page(tree.steps, tree.graph_issues, ctx))
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
        annotated=tree.annotated,
        flagged=tree.flagged,
        unannotated=tree.unannotated,
        pages_written=pages_written,
        pages_reused=pages_reused,
        bytes_written=written,
        total_bytes=_tree_bytes(out_dir),
        byte_budget=config.byte_budget,
        search_entries=search_entries,
        glossary_terms=len(tree.terms),
        learning_steps=len(tree.steps),
        errors=tuple(issue for issue in tree.issues if issue.startswith("error:")),
        warnings=tuple(issue for issue in tree.issues if issue.startswith("warning:")),
        identical_names=tree.objects.identical,
        variant_names=tree.objects.variant,
    )


def check_tree(
    lean_root: Path, config: Config | None = None, cache_dir: Path | None = None, jobs: int = 1
) -> TreeIndex:
    config = config or Config()
    return collect_tree(lean_root, config, cache_dir or lean_root.parent / ".lean4-explainer-check", jobs)


def annotation_templates(
    lean_root: Path,
    rel: str,
    config: Config | None = None,
    cache_dir: Path | None = None,
) -> str:
    tree = check_tree(lean_root, config, cache_dir)
    path = lean_root / rel
    if not path.is_file():
        raise ExplainerError(f"not a Lean file under {lean_root}: {rel}")
    lean_file = parse_source(path.read_bytes().decode("utf-8-sig", errors="replace"), rel, statements=True)
    return annotation_report(lean_file, tree.locations, tree.objects.ambiguous)


def _status(tree: TreeIndex) -> str:
    return (
        f"L4DEL: {tree.annotated} annotated, {tree.flagged} flagged (errors or placeholders), "
        f"{tree.unannotated} without L4DEL. Run lean4-explainer annotate --file <path> for templates."
    )


def _index_of(lean_file: LeanFile, sha: str) -> FileIndex:
    named = [decl for decl in lean_file.declarations if "(" not in decl.name]
    notes = tuple(
        Note(
            name=decl.name,
            rel=lean_file.path,
            line=decl.line,
            title=decl.l4.title,
            prereqs=decl.l4.prereqs,
            see=decl.l4.see,
            terms=decl.l4.terms,
        )
        for decl in named
        if decl.l4.title or decl.l4.prereqs or decl.l4.see or decl.l4.terms
    )
    diagnostics = tuple(
        f"{d.severity}: {lean_file.path}:{d.line}: {d.message}"
        for decl in lean_file.declarations
        for d in decl.l4.diagnostics
    ) + tuple(f"{d.severity}: {lean_file.path}:{d.line}: {d.message}" for d in lean_file.diagnostics)
    states = [annotation_state(decl) for decl in named]
    return FileIndex(
        sha=sha,
        declarations=len(lean_file.declarations),
        sorry=sum(decl.has_sorry for decl in lean_file.declarations),
        axioms=sum(decl.kind == "axiom" for decl in lean_file.declarations),
        names="\n".join(decl.name for decl in named),
        lines=array("I", (decl.line for decl in named)),
        codes=array("Q", (decl.code_digest for decl in named)),
        headers=array("Q", (decl.header_digest for decl in named)),
        notes=notes,
        diagnostics=diagnostics,
        annotated=states.count("annotated"),
        flagged=states.count("flagged"),
        unannotated=states.count("unannotated"),
        described="\n".join(decl.name for decl in named if decl.description or not decl.l4.is_empty),
    )


def _refresh_file(job: tuple[str, str, str]) -> tuple[str, str, FileIndex | None]:
    """Hash a file; index it only if its hash differs from the cached one. Runs in worker processes."""
    rel, path, known = job
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha == known:
        return rel, sha, None
    return rel, sha, _index_of(parse_source(data.decode("utf-8-sig", errors="replace"), rel), sha)


def _fingerprint(config: Config) -> str:
    return hashlib.sha256(f"{__version__}|{CACHE_FORMAT}|{config!r}".encode("utf-8")).hexdigest()


def _excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def _tree_bytes(root: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            total += os.path.getsize(os.path.join(dirpath, name))
    return total


def _write(path: Path, text: str) -> int:
    data = text.encode("utf-8")
    try:
        path.write_bytes(data)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return len(data)
