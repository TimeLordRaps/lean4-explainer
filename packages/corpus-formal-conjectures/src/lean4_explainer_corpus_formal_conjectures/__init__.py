"""Formal Conjectures: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#14213d", bg="#f5f7fb", muted="#5b6785", line="#cfd6e6", warn="#8a3b00", panel="rgba(20,33,61,0.06)", accent="#b86e00", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#e8ecf6", bg="#0b1220", muted="#8d9abb", line="#25314d", warn="#ffb46b", panel="rgba(255,255,255,0.05)", accent="#f2b134", **{"warn-bg": "#3a2a18"}),
    heading="ui-monospace, SFMono-Regular, Consolas, monospace",
    extra="""
body { background-image: radial-gradient(circle at 1px 1px, rgba(127,140,180,0.22) 1px, transparent 0); background-size: 28px 28px; }
h1 { letter-spacing: 0.04em; }
h1::before { content: "\\2726  "; color: var(--accent); }
.flag.sorry { border: 1px dashed var(--warn); }
""",
)

CORPUS = Corpus(
    name='formal-conjectures',
    title='Formal Conjectures',
    repo='google-deepmind/formal-conjectures',
    commit='1646ca16afd6cc7a693d3bdc9f066c4d3cc01a89',
    branch='main',
    kind='conjectures',
    blurb='Open and solved conjectures stated in Lean, one statement per problem.',
    license_note=('Software is Apache-2.0. Other material is CC-BY 4.0. Content taken from Wikipedia, MathOverflow '
 'and the OEIS is CC-BY-SA 4.0 (ShareAlike); material from bbchallenge.org is CC-BY 4.0; the '
 'source URL in each file names its origin. Doc comments and statements shown here are copies of '
 'that content.'),
    accent='#f2b134',
    theme_css=THEME,
)
