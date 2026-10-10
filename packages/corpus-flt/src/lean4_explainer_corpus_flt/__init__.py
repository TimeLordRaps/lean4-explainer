"""Fermat's Last Theorem (FLT): the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#2b2118", bg="#f4ecd8", muted="#7a6a55", line="#d8c9a8", warn="#7a2e00", panel="rgba(90,60,20,0.08)", accent="#8b2635", **{"warn-bg": "#f6dfc2"}),
    dark=dict(fg="#eadfc8", bg="#1c1712", muted="#a8977c", line="#3a3026", warn="#ffb46b", panel="rgba(255,235,200,0.06)", accent="#d9b26f", **{"warn-bg": "#3a2a18"}),
    body="'Palatino Linotype', Palatino, 'Book Antiqua', Georgia, serif",
    extra="""
h1 { font-variant: small-caps; letter-spacing: 0.06em; text-align: center; font-weight: 600; }
h1 + p, h1 + .muted { text-align: center; }
h2 { font-variant: small-caps; letter-spacing: 0.04em; border-bottom-style: double; border-bottom-width: 3px; }
.doc { font-style: italic; }
main { border-left: 1px solid var(--line); border-right: 1px solid var(--line); background: rgba(255,255,255,0.12); }
""",
)

CORPUS = Corpus(
    name='flt',
    title="Fermat's Last Theorem (FLT)",
    repo='ImperialCollegeLondon/FLT',
    commit='f6c6a2fe9796d6d89cd2a0d24e8a453729d881ff',
    branch='main',
    kind='formalization',
    blurb="The Imperial College project to formalize a proof of Fermat's Last Theorem.",
    accent='#8b2635',
    theme_css=THEME,
)
