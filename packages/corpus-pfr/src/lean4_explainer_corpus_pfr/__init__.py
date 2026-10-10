"""Polynomial Freiman-Ruzsa (PFR): the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#12233f", bg="#f7fafe", muted="#5d6f8c", line="#cbd8ee", warn="#8a3b00", panel="rgba(47,111,219,0.07)", accent="#2f6fdb", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#e5edfb", bg="#0e1626", muted="#8fa3c5", line="#233556", warn="#ffb46b", panel="rgba(255,255,255,0.05)", accent="#6aa2ff", **{"warn-bg": "#3a2a18"}),
    heading="'Trebuchet MS', system-ui, sans-serif",
    extra="""
body { background-image: linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px); background-size: 24px 24px; background-position: -1px -1px; }
main { background: var(--bg); box-shadow: 0 0 0 1px var(--line); margin-top: 1rem; margin-bottom: 1rem; }
""",
)

CORPUS = Corpus(
    name='pfr',
    title='Polynomial Freiman-Ruzsa (PFR)',
    repo='teorth/pfr',
    commit='ce7ac95e620afe0ae448df63477de0b29e4dcf4d',
    branch='master',
    kind='formalization',
    blurb='The formalization of the polynomial Freiman-Ruzsa conjecture over characteristic 2.',
    accent='#2f6fdb',
    theme_css=THEME,
)
