"""AlphaProof Nexus results: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#152238", bg="#f4f8ff", muted="#5c6c82", line="#cad6e6", warn="#8a3b00", panel="rgba(39,93,173,0.06)", accent="#2457c5", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#e7efff", bg="#0b1424", muted="#91a2bd", line="#263751", warn="#ffb46b", panel="rgba(88,145,255,0.07)", accent="#76a7ff", **{"warn-bg": "#3a2a18"}),
    heading="ui-monospace, SFMono-Regular, Consolas, monospace",
    extra="""
h1 { letter-spacing: 0.025em; }
h1::before { content: "APN  "; color: var(--accent); font-size: 0.72em; }
.kind { text-transform: uppercase; letter-spacing: 0.04em; }
""",
)

CORPUS = Corpus(
    name="alphaproof-nexus",
    title="AlphaProof Nexus results",
    repo="google-deepmind/alphaproof-nexus-results",
    commit="0647711a71183c1ea492ad60860776617ce1ea88",
    branch="main",
    kind="research results",
    blurb=(
        "Published Lean proof artifacts for AlphaProof Nexus across Erdős problems, OEIS, "
        "the Stacks Project, and mathematical collaborations."
    ),
    seo_description=(
        "Explore Google DeepMind AlphaProof Nexus results in plain language: Lean 4 proof artifacts with local "
        "compilation and trust checks for "
        "Erdős problems, OEIS conjectures, the Stacks Project, and research collaborations, with pinned sources "
        "and explicit annotation provenance."
    ),
    license_note=(
        "The pinned README licenses software under Apache-2.0 and other materials under CC-BY 4.0, with "
        "additional third-party-source notices for OEIS, Erdős Problems, Gergely Bérczi, and Mario Krenn."
    ),
    options=(("lean_steps", 0),),
    accent="#76a7ff",
    theme_css=THEME,
)
