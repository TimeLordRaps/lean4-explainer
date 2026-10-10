"""Theorem Proving in Lean 4: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus, package_file
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#1c2033", bg="#fafaff", muted="#62678a", line="#d6d8ee", warn="#8a3b00", panel="rgba(76,81,191,0.07)", accent="#4c51bf", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#e7e9fb", bg="#12131f", muted="#9296ba", line="#2a2d4a", warn="#ffb46b", panel="rgba(255,255,255,0.05)", accent="#9aa0ff", **{"warn-bg": "#3a2a18"}),
    heading="Georgia, 'Times New Roman', serif",
    extra="""
main { max-width: 46rem; }
h1 { border-left: 6px solid var(--accent); padding-left: 0.7rem; }
h2 { border-bottom: 0; border-left: 3px solid var(--accent); padding-left: 0.5rem; }
.doc { font-family: Georgia, 'Times New Roman', serif; }
""",
)

CORPUS = Corpus(
    name='tpil',
    title='Theorem Proving in Lean 4',
    repo='leanprover/theorem_proving_in_lean4',
    commit='4e28129fdd58037f8f5857548d5e99fe4fb0cc57',
    branch='master',
    kind='tutorial',
    blurb='The book on Lean 4 itself: dependent types, tactics, inductive types.',
    lake=False,
    include=('book/TPiL.lean', 'book/TPiL/*', 'examples/Examples.lean', 'examples/Examples/*'),
    accent='#4c51bf',
    theme_css=THEME,
    overlay=package_file(__file__, "overlay.l4del"),
)
