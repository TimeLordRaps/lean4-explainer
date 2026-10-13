"""Fetch the built-in corpora at their pinned commits and build one subsite per corpus under a landing page."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from lean4_explainer.build import BuildSummary, build_site
from lean4_explainer.config import PAGES_LIMIT_BYTES, Config
from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import extensions
from lean4_explainer.lake import LakeProject, include_patterns, read_lake
from lean4_explainer.render import ASSET_DIR, FAVICON_SVG, SITE_CSS

from .registry import Corpus
from .overlays import HostedOverlay, load_overlay_manifest
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
.start { margin: 1rem 0 1.3rem; padding: 0.9rem 1rem; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); }
.start h2 { margin-top: 0; }
.start ul { margin-bottom: 0; }
.card-actions { display: flex; flex-wrap: wrap; gap: 0.35rem 0.85rem; margin-top: 0.55rem; font-size: 0.92rem; }
.card-actions a { font-weight: 600; }
""",
)

GITHUB = "https://github.com"
RAW = "https://raw.githubusercontent.com"
_GIT_TIMEOUT_SECONDS = 1800
SITE_REPOSITORY = "https://github.com/TimeLordRaps/lean4-explainer"
REPORT_URL = SITE_REPOSITORY + "/issues/new?title=Site%20feedback%3A%20"
SHOWCASE_DESCRIPTION = (
    "Explore declarations, source, grounded explanations, learning paths, and dependency maps across major Lean projects."
)


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
    overlay_manifest: Path | None = None,
    site_url: str | None = None,
) -> ShowcaseResult:
    """Fetch every corpus first, so a failed download stops the run before anything is published."""
    public_url = _site_url(site_url)
    overlays = load_overlay_manifest(overlay_manifest, corpora) if overlay_manifest else {}
    checkouts = [(corpus, fetch(corpus, work_dir, base_url=base_url)) for corpus in corpora]
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for corpus, checkout in checkouts:
        overlay = overlays.get(corpus.name)
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
            site_url=f"{public_url}{corpus.name}/" if public_url else None,
            description=f"Explore {corpus.title}: Lean declarations, pinned source, explanations, and dependencies.",
            project_url=f"{GITHUB}/{corpus.repo}/tree/{corpus.commit}",
            report_url=REPORT_URL,
            glossary=corpus.glossary,
            imports=corpus.imports,
            options=tuple(
                sorted(
                    [("theme_css", corpus.theme_css)] * bool(corpus.theme_css)
                    + _overlay_options(overlay)
                    # the edges were read at a commit: the site's pin is what they are checked against for staleness
                    + [("implications_file", corpus.implications), ("implications_commit", corpus.commit)]
                    * bool(corpus.implications and Path(corpus.implications).is_file())
                    # a tree too large to publish twice: its readings load the pinned source instead of carrying it
                    + [("reader_source_url", f"{RAW}/{corpus.repo}/{{ref}}/{prefix}{{path}}")]
                    * (corpus.source_links == "file")
                    + list(corpus.options)
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
    (out_dir / ASSET_DIR / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    guide = next(
        (f"{i.corpus.name}/annotate.html" for i in items if (out_dir / i.corpus.name / "annotate.html").is_file()),
        "",
    )  # the L4DEL guide exists only when the L4DEL extension is installed
    annotated = set(overlays) if any(ext.name == "l4del" for ext in extensions()) else set()
    curated = {i.corpus.name for i in items if (out_dir / i.corpus.name / "implications.html").is_file()}
    disclosures = {name: overlay.disclosure for name, overlay in overlays.items()}
    credits = {name: overlay.credit for name, overlay in overlays.items()}
    source_attributions = {name: overlay.sources for name, overlay in overlays.items()}
    actions = _corpus_actions(items, out_dir)
    start_links = _start_links(items, actions, out_dir)
    (out_dir / "index.html").write_text(
        _landing(
            items,
            link_out or [],
            guide,
            annotated,
            curated,
            disclosures,
            actions,
            start_links,
            public_url,
            credits=credits,
            source_attributions=source_attributions,
        ),
        encoding="utf-8",
    )
    (out_dir / "404.html").write_text(_not_found(public_url), encoding="utf-8")
    if public_url:
        _write_discovery(out_dir, public_url)
    return ShowcaseResult(tuple(items), _tree_bytes(out_dir), byte_budget)


def _copy_license(checkout: Path, target: Path, lean_root: str) -> None:
    """Redistributing the pages carries the upstream license text along (Apache-2.0 section 4a)."""
    for folder in (checkout, checkout / lean_root):
        source = folder / "LICENSE"
        if source.is_file():
            target.mkdir(parents=True, exist_ok=True)
            (target / "LICENSE.txt").write_bytes(source.read_bytes())
            return


def _site_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ExplainerError("site_url must be an HTTPS URL without a query or fragment")
    return value.rstrip("/") + "/"


def _corpus_actions(items: list[ShowcaseItem], out_dir: Path) -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {}
    for item in items:
        name = item.corpus.name
        root = out_dir / name
        choices = [
            ("Browse", "index.html"),
            ("Search", "search.html"),
            ("Glossary", "glossary.html"),
            ("Learn", "learning-path.html"),
            ("Map", "map.html"),
        ]
        found[name] = [(label, f"{name}/{rel}") for label, rel in choices if (root / rel).is_file()]
    return found


def _start_links(
    items: list[ShowcaseItem], actions: dict[str, list[tuple[str, str]]], out_dir: Path
) -> list[tuple[str, str, str]]:
    links: list[tuple[str, str, str]] = []
    titles = {item.corpus.name: item.corpus.title for item in items}
    if (out_dir / "flt" / "FLT" / "Proof.lean.html").is_file():
        links.append(("Read an explained theorem", "flt/FLT/Proof.lean.html#L111", "Fermat's Last Theorem and its unfinished proof boundary"))
    if (out_dir / "oai" / "search.html").is_file():
        links.append(("Search a concept", "oai/search.html?q=Hadwiger", "A shareable search in openai/math"))
    for wanted, heading, detail in (
        ("Learn", "Follow a learning path", "Declarations ordered after their prerequisites"),
        ("Glossary", "Use a project glossary", "Definitions and explanatory vocabulary"),
    ):
        match = next(((name, href) for name, rows in actions.items() for label, href in rows if label == wanted), None)
        if match:
            name, href = match
            links.append((heading, href, f"{detail} in {titles[name]}"))
    if not links and items:
        first = items[0].corpus
        links.append((f"Browse {first.title}", f"{first.name}/index.html", "Start at the corpus index"))
    return links[:4]


def _landing(
    items: list[ShowcaseItem],
    link_out: list[Corpus],
    guide: str,
    annotated: set[str] = frozenset(),  # type: ignore[assignment]
    curated: set[str] = frozenset(),  # type: ignore[assignment]
    disclosures: dict[str, str] | None = None,
    actions: dict[str, list[tuple[str, str]]] | None = None,
    start_links: list[tuple[str, str, str]] | None = None,
    site_url: str = "",
    credits: dict[str, str] | None = None,
    source_attributions: dict[str, tuple[tuple[str, str], ...]] | None = None,
) -> str:
    disclosures = disclosures or {}
    actions = actions or {}
    start_links = start_links or []
    credits = credits or {}
    source_attributions = source_attributions or {}
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
        corpus_actions = actions.get(corpus.name, ())
        action_html = ""
        if corpus_actions:
            action_html = (
                f'<nav class="card-actions" aria-label="Explore {escape(corpus.title, quote=True)}">'
                + " · ".join(
                    f'<a href="{escape(href, quote=True)}">{escape(label)}</a>'
                    for label, href in corpus_actions
                )
                + "</nav>"
            )
        attribution = ""
        if corpus.name in annotated:
            links = ", ".join(
                f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
                for label, url in source_attributions.get(corpus.name, ())
            )
            attribution = (
                f'<br><strong>Credit:</strong> {escape(credits.get(corpus.name, ""))}'
                + (f'<br><strong>Primary project and mathematical sources:</strong> {links}.' if links else "")
            )
        cards.append(
            f'<li style="--card: {escape(corpus.accent)}"><a href="{escape(corpus.name)}/index.html"><strong>{escape(corpus.title)}</strong></a> '
            f'<span class="muted">({escape(corpus.kind)})</span><br>{escape(corpus.blurb)}<br>'
            f'<span class="muted">{escape(", ".join(facts))}. {escape(", ".join(pins))}. '
            f'Source: <a href="{GITHUB}/{escape(corpus.repo)}/tree/{corpus.commit}">{escape(corpus.repo)} at the pinned commit</a>. '
            f'License: {escape(corpus.license)} (<a href="{escape(corpus.name)}/LICENSE.txt">text</a>).'
            + (f"<br>{escape(corpus.license_note)}" if corpus.license_note else "")
            + (
                "<br>Selected declarations are explained with L4DEL from a hosted sidecar overlay; "
                "the upstream authors did not write these explanations and their sources are unchanged. "
                "Each explanation links back to its exact pinned Lean source. "
                + escape(disclosures.get(corpus.name, ""))
                + attribution
                if corpus.name in annotated
                else ""
            )
            + (
                f'<br><a href="{escape(corpus.name)}/implications.html">Implication edges</a>: curated claims about what '
                "one result could establish about another, each with its contract and how far it is checked; kept in "
                "lean4-explainer, not by the upstream authors."
                if corpus.name in curated
                else ""
            )
            + "</span>"
            + action_html
            + "</li>"
        )
    for corpus in link_out:
        cards.append(
            f'<li><a href="{GITHUB}/{escape(corpus.repo)}/tree/{corpus.commit}"><strong>{escape(corpus.title)}</strong></a> '
            f'<span class="muted">({escape(corpus.kind)}, not built into this site)</span><br>{escape(corpus.blurb)}</li>'
        )
    start = ""
    if start_links:
        rows = "".join(
            f'<li><a href="{escape(href, quote=True)}"><strong>{escape(label)}</strong></a> — {escape(detail)}</li>'
            for label, href, detail in start_links
        )
        start = f'<section class="start" aria-labelledby="start-heading"><h2 id="start-heading">Start exploring</h2><ul>{rows}</ul></section>'
    canonical = f'<link rel="canonical" href="{escape(site_url, quote=True)}">' if site_url else ""
    og_url = f'<meta property="og:url" content="{escape(site_url, quote=True)}">' if site_url else ""
    audit = (
        '<p class="muted"><a href="annotation-audit.json">Annotation grounding audit (JSON)</a>: '
        "generated wording is checked against pinned source text; curated wording remains source-linked and "
        "unreviewed.</p>"
        if annotated
        else ""
    )
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>lean4-explainer showcase</title>",
            f'<meta name="description" content="{escape(SHOWCASE_DESCRIPTION, quote=True)}">',
            '<meta property="og:title" content="lean4-explainer showcase">',
            f'<meta property="og:description" content="{escape(SHOWCASE_DESCRIPTION, quote=True)}">',
            '<meta property="og:type" content="website">',
            '<meta name="twitter:card" content="summary">',
            canonical,
            og_url,
            f'<link rel="stylesheet" href="{ASSET_DIR}/site.css">',
            f'<link rel="icon" href="{ASSET_DIR}/favicon.svg" type="image/svg+xml">',
            "</head>",
            "<body>",
            '<a class="skip-link" href="#content">Skip to content</a>',
            '<main id="content" tabindex="-1">',
            "<h1>lean4-explainer showcase</h1>",
            "<p>What lean4-explainer produces for the Lean projects below. Hosted annotations, when present, "
            "carry their provenance and source grounding beside the explanation. "
            "To write your own explanations, start with the "
            + (
                f'<a href="{escape(guide)}">Lean4 Domain Explanation Language (L4DEL) guide</a>'
                if guide
                else "Lean4 Domain Explanation Language (L4DEL) guide"
            )
            + f' or <a href="{SITE_REPOSITORY}#l4del-write-your-own-explanations">the README</a>.</p>',
            '<p class="muted">Built from the source text only. Lean was not run, so axiom and trust checks are UNKNOWN '
            "and <code>sorry</code> detection is textual.</p>",
            audit,
            start,
            '<h2 id="corpora">All corpora</h2>',
            '<ol class="list">',
            *cards,
            "</ol>",
            "</main>",
            f'<footer class="site-footer"><a href="{SITE_REPOSITORY}">Site source</a> · <a href="{REPORT_URL}">Report a site issue</a></footer>',
            "</body>",
            "</html>",
            "",
        ]
    )


def _not_found(site_url: str) -> str:
    base_path = urlsplit(site_url).path if site_url else ""
    home = base_path or "index.html"
    css = f"{base_path}{ASSET_DIR}/site.css" if base_path else f"{ASSET_DIR}/site.css"
    icon = f"{base_path}{ASSET_DIR}/favicon.svg" if base_path else f"{ASSET_DIR}/favicon.svg"
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<meta name="robots" content="noindex">',
            "<title>Page not found — lean4-explainer</title>",
            f'<link rel="stylesheet" href="{escape(css, quote=True)}">',
            f'<link rel="icon" href="{escape(icon, quote=True)}" type="image/svg+xml">',
            "</head><body>",
            '<main id="content"><h1>That proof page is not here</h1>',
            "<p>The corpus may have moved at a newer pinned commit, or the address may be incomplete.</p>",
            f'<p><a href="{escape(home, quote=True)}">Return to all corpora</a> · <a href="{REPORT_URL}">Report a broken link</a></p>',
            "</main></body></html>",
            "",
        ]
    )


def _write_discovery(out_dir: Path, site_url: str) -> None:
    pages = sorted(
        path.relative_to(out_dir).as_posix()
        for path in out_dir.rglob("*.html")
        if path.name != "404.html"
    )
    urls = [urljoin(site_url, quote(path, safe="/")) for path in pages]
    chunk_size = 45_000
    chunks = [urls[start : start + chunk_size] for start in range(0, len(urls), chunk_size)] or [[]]
    for stale in out_dir.glob("sitemap-*.xml"):
        stale.unlink()
    names = []
    for number, chunk in enumerate(chunks, start=1):
        name = f"sitemap-{number}.xml"
        names.append(name)
        body = "".join(f"<url><loc>{escape(url)}</loc></url>" for url in chunk)
        (out_dir / name).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + body
            + "</urlset>\n",
            encoding="utf-8",
        )
    index = "".join(f"<sitemap><loc>{escape(urljoin(site_url, name))}</loc></sitemap>" for name in names)
    (out_dir / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + index
        + "</sitemapindex>\n",
        encoding="utf-8",
    )
    (out_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {urljoin(site_url, 'sitemap.xml')}\n", encoding="utf-8"
    )


def _overlay_options(overlay: HostedOverlay | None) -> list[tuple[str, object]]:
    if overlay is None:
        return []
    return [
        ("overlay", str(overlay.path)),
        ("overlay_provenance", overlay.provenance),
        ("overlay_disclosure", overlay.disclosure),
        ("overlay_sources", json.dumps(overlay.sources, ensure_ascii=False, separators=(",", ":"))),
        ("overlay_credit", overlay.credit),
    ]


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
