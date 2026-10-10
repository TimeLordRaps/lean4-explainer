"""Fetch the built-in corpora at their pinned commits and build one subsite per corpus under a landing page."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path

from lean4_explainer.build import BuildSummary, build_site
from lean4_explainer.config import PAGES_LIMIT_BYTES, Config
from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import extensions
from lean4_explainer.lake import LakeProject, include_patterns, read_lake
from lean4_explainer.render import ASSET_DIR, SITE_CSS

from .registry import Corpus
from .themes import make_theme

# The landing page is an atlas: ink on paper, each project a card in its own colour.
LANDING_CSS = make_theme(
    light=dict(fg="#1d1b16", bg="#f6f1e7", muted="#6e6656", line="#d9d0bd", warn="#8a3b00", panel="rgba(60,40,10,0.06)", accent="#7a4b12", **{"warn-bg": "#f6dfc2"}),
    dark=dict(fg="#ece6d8", bg="#16140f", muted="#a39a86", line="#38332a", warn="#ffb46b", panel="rgba(255,240,210,0.06)", accent="#e0b36a", **{"warn-bg": "#3a2a18"}),
    heading="Georgia, 'Times New Roman', serif",
    extra="""
h1 { font-size: 2.1rem; letter-spacing: 0.01em; }
ol.list { counter-reset: none; padding: 0; }
ol.list > li { list-style: none; background: var(--panel); border: 1px solid var(--line); border-left: 6px solid var(--card, var(--accent)); border-radius: 6px; padding: 0.8rem 1rem; margin-bottom: 0.8rem; }
""",
)

GITHUB = "https://github.com"
_GIT_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True)
class ShowcaseItem:
    corpus: Corpus
    summary: BuildSummary
    project: LakeProject | None
    seconds: float


@dataclass(frozen=True)
class ShowcaseResult:
    items: tuple[ShowcaseItem, ...]
    total_bytes: int
    byte_budget: int

    @property
    def over_budget(self) -> bool:
        return self.total_bytes > self.byte_budget


def fetch_corpus(corpus: Corpus, work_dir: Path, base_url: str = GITHUB) -> Path:
    """Check out `corpus.commit` under `work_dir/<name>` and return the checkout. A matching checkout is reused."""
    target = work_dir / corpus.name
    if target.joinpath(".git").exists() and _head(target) == corpus.commit:
        return target
    target.mkdir(parents=True, exist_ok=True)
    url = f"{base_url.rstrip('/')}/{corpus.repo}"
    try:
        _git(target, "init", "-q")
        _git(target, "remote", "add", "origin", url, check=False)
        _git(target, "remote", "set-url", "origin", url)
        if corpus.lean_root:  # cone mode keeps the checkout to that subtree (openai/math has very long paths elsewhere)
            _git(target, "sparse-checkout", "set", "--cone", corpus.lean_root)
        _git(target, "fetch", "-q", "--depth", "1", "origin", corpus.commit)
        _git(target, "checkout", "-q", "--detach", "FETCH_HEAD")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ExplainerError(f"could not fetch {corpus.name} ({url} at {corpus.commit[:12]}): {detail.strip()}") from exc
    return target


def build_showcase(
    corpora: list[Corpus],
    work_dir: Path,
    out_dir: Path,
    *,
    base_url: str = GITHUB,
    link_out: list[Corpus] | None = None,
    byte_budget: int = PAGES_LIMIT_BYTES,
    jobs: int = 1,
    fetch=fetch_corpus,
) -> ShowcaseResult:
    """Fetch every corpus first, so a failed download stops the run before anything is published."""
    checkouts = [(corpus, fetch(corpus, work_dir, base_url=base_url)) for corpus in corpora]
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for corpus, checkout in checkouts:
        project = read_lake(checkout / corpus.lean_root) if corpus.lake else None
        include = include_patterns(project) if project and project.libs else corpus.include
        prefix = f"{corpus.lean_root.strip('/')}/" if corpus.lean_root else ""
        config = Config(
            title=corpus.title,
            include=include,
            exclude=corpus.exclude,
            extra_kinds=corpus.extra_kinds,
            source_url=f"{GITHUB}/{corpus.repo}/blob/{{ref}}/{prefix}{{path}}#L{{line}}",
            source_ref=corpus.commit,
            source_links=corpus.source_links,
            byte_budget=byte_budget,
            home="../index.html",
            options=tuple(
                sorted(
                    [("theme_css", corpus.theme_css)] * bool(corpus.theme_css)
                    + [("overlay", corpus.overlay)] * bool(corpus.overlay and Path(corpus.overlay).is_file())
                )
            ),
        )
        _copy_license(checkout, out_dir / corpus.name, corpus.lean_root)
        started = time.monotonic()
        summary = build_site(
            checkout / corpus.lean_root,
            out_dir / corpus.name,
            config,
            work_dir / ".cache" / corpus.name,
            jobs=jobs,
        )
        items.append(ShowcaseItem(corpus, summary, project, time.monotonic() - started))
    (out_dir / ASSET_DIR).mkdir(parents=True, exist_ok=True)
    (out_dir / ASSET_DIR / "site.css").write_text(SITE_CSS + LANDING_CSS, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    guide = next(
        (f"{i.corpus.name}/annotate.html" for i in items if (out_dir / i.corpus.name / "annotate.html").is_file()),
        "",
    )  # the L4DEL guide exists only when the L4DEL extension is installed
    annotated = {
        i.corpus.name for i in items if i.corpus.overlay and Path(i.corpus.overlay).is_file()
    } if any(ext.name == "l4del" for ext in extensions()) else set()
    (out_dir / "index.html").write_text(_landing(items, link_out or [], guide, annotated), encoding="utf-8")
    return ShowcaseResult(tuple(items), _tree_bytes(out_dir), byte_budget)


def _copy_license(checkout: Path, target: Path, lean_root: str) -> None:
    """Redistributing the pages carries the upstream license text along (Apache-2.0 section 4a)."""
    for folder in (checkout, checkout / lean_root):
        source = folder / "LICENSE"
        if source.is_file():
            target.mkdir(parents=True, exist_ok=True)
            (target / "LICENSE.txt").write_bytes(source.read_bytes())
            return


def _landing(items: list[ShowcaseItem], link_out: list[Corpus], guide: str, annotated: set[str] = frozenset()) -> str:  # type: ignore[assignment]
    cards = []
    for item in items:
        corpus, summary, project = item.corpus, item.summary, item.project
        facts = [f"{summary.files} files", f"{summary.declarations} declarations", f"{summary.sorry} contain sorry"]
        pins = [f"commit {corpus.commit[:12]}"]
        if project and project.toolchain:
            pins.append(f"toolchain {project.toolchain}")
        mathlib = dict(project.pinned).get("mathlib") if project else None
        if mathlib:
            pins.append(f"mathlib {mathlib[:12]}")
        cards.append(
            f'<li style="--card: {escape(corpus.accent)}"><a href="{escape(corpus.name)}/index.html"><strong>{escape(corpus.title)}</strong></a> '
            f'<span class="muted">({escape(corpus.kind)})</span><br>{escape(corpus.blurb)}<br>'
            f'<span class="muted">{escape(", ".join(facts))}. {escape(", ".join(pins))}. '
            f'Source: <a href="{GITHUB}/{escape(corpus.repo)}">{escape(corpus.repo)}</a>. '
            f'License: {escape(corpus.license)} (<a href="{escape(corpus.name)}/LICENSE.txt">text</a>).'
            + (f"<br>{escape(corpus.license_note)}" if corpus.license_note else "")
            + (
                "<br>Selected declarations are explained with L4DEL from a sidecar overlay kept in lean4-explainer; "
                "the upstream authors did not write these explanations and their sources are unchanged."
                if corpus.name in annotated
                else ""
            )
            + "</span></li>"
        )
    for corpus in link_out:
        cards.append(
            f'<li><a href="{GITHUB}/{escape(corpus.repo)}"><strong>{escape(corpus.title)}</strong></a> '
            f'<span class="muted">({escape(corpus.kind)}, not built into this site)</span><br>{escape(corpus.blurb)}</li>'
        )
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>lean4-explainer showcase</title>",
            f'<link rel="stylesheet" href="{ASSET_DIR}/site.css">',
            "</head>",
            "<body>",
            "<main>",
            "<h1>lean4-explainer showcase</h1>",
            "<p>What lean4-explainer produces, with no annotation, for the Lean projects below. "
            "To write your own explanations, start with the "
            + (f'<a href="{escape(guide)}">L4DEL guide</a>' if guide else "L4DEL guide")
            + ' or <a href="https://github.com/TimeLordRaps/lean4-explainer#l4del-write-your-own-explanations">'
            "the README</a>.</p>",
            '<p class="muted">Built from the source text only. Lean was not run, so axiom and trust checks are UNKNOWN '
            "and <code>sorry</code> detection is textual.</p>",
            '<ol class="list">',
            *cards,
            "</ol>",
            "</main>",
            "</body>",
            "</html>",
            "",
        ]
    )


def _head(checkout: Path) -> str:
    try:
        return _git(checkout, "rev-parse", "HEAD").stdout.strip()
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return ""


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    return subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
