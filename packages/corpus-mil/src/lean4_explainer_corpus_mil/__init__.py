"""Mathematics in Lean: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus, package_file
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#1f2a24", bg="#fbfdf9", muted="#5f6f65", line="#d5e4da", warn="#8a3b00", panel="rgba(47,133,90,0.08)", accent="#2f855a", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#e5efe8", bg="#131a16", muted="#93a69a", line="#2b3a31", warn="#ffb46b", panel="rgba(255,255,255,0.05)", accent="#68d391", **{"warn-bg": "#3a2a18"}),
    body="'Segoe UI', 'Helvetica Neue', system-ui, sans-serif",
    extra="""
main { font-size: 1.05rem; }
ol.decls > li, ul.list > li { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.6rem; }
pre { border-radius: 8px; }
""",
)

CORPUS = Corpus(
    name='mil',
    title='Mathematics in Lean',
    repo='leanprover-community/mathematics_in_lean',
    commit='dd6d752fedb14082f557913c2dccb2d4851e5173',
    branch='master',
    kind='tutorial',
    blurb=('The tutorial that teaches Lean 4 and mathlib through mathematics. Exercises and solutions share '
 'names.'),
    accent='#2f855a',
    theme_css=THEME,
    overlay=package_file(__file__, "overlay.l4del"),
)
