"""Carleson's theorem: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#17234a", bg="#f4f8fa", muted="#53647f", line="#c9d9e0", warn="#8a3b00", panel="rgba(23,35,74,0.06)", accent="#127c78", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#e3eefa", bg="#0c1530", muted="#8ea3c4", line="#233258", warn="#ffb46b", panel="rgba(255,255,255,0.05)", accent="#2aa6a0", **{"warn-bg": "#3a2a18"}),
    heading="Georgia, 'Times New Roman', serif",
    extra="""
h1 { padding-bottom: 0.5rem; background: WAVE repeat-x left bottom / 120px 12px; }
""".replace("WAVE", svg("<svg xmlns='http://www.w3.org/2000/svg' width='120' height='12'><path d='M0 6 Q 15 -2 30 6 T 60 6 T 90 6 T 120 6' fill='none' stroke='#2aa6a0' stroke-width='1.5'/></svg>")),
)

CORPUS = Corpus(
    name='carleson',
    title="Carleson's theorem",
    repo='fpvandoorn/carleson',
    commit='8972acdfd953c63bb2501ace20d61ced7c0697ec',
    branch='master',
    kind='formalization',
    blurb="The formalization of Carleson's theorem on the convergence of Fourier series.",
    accent='#2aa6a0',
    theme_css=THEME,
)
