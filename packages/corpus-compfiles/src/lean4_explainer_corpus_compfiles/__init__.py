"""Compfiles: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#111111", bg="#ffffff", muted="#666666", line="#111111", warn="#8a3b00", panel="rgba(0,0,0,0.06)", accent="#d7261e", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#f5f5f5", bg="#0a0a0a", muted="#9a9a9a", line="#f5f5f5", warn="#ffb46b", panel="rgba(255,255,255,0.07)", accent="#ff4b3e", **{"warn-bg": "#3a2a18"}),
    heading="Impact, 'Arial Narrow Bold', 'Helvetica Neue', Arial, sans-serif",
    extra="""
h1 { text-transform: uppercase; letter-spacing: 0.05em; font-weight: 900; border-left: 0.6rem solid var(--accent); padding-left: 0.6rem; }
h2 { text-transform: uppercase; letter-spacing: 0.08em; border-bottom-width: 3px; }
ol.decls > li, ul.list > li { border-bottom-width: 2px; }
.kind { font-weight: 700; }
""",
)

CORPUS = Corpus(
    name='compfiles',
    title='Compfiles',
    repo='dwrensha/compfiles',
    commit='47b19bbfe5f38dc49379a6b53008d2909c4d71c5',
    branch='main',
    kind='competition',
    blurb='Formalized statements and solutions of olympiad-style problems.',
    accent='#d7261e',
    theme_css=THEME,
)
