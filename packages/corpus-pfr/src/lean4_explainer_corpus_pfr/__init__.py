"""Polynomial Freiman-Ruzsa (PFR): the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

CORPUS = Corpus(
    name='pfr',
    title='Polynomial Freiman-Ruzsa (PFR)',
    repo='teorth/pfr',
    commit='ce7ac95e620afe0ae448df63477de0b29e4dcf4d',
    branch='master',
    kind='formalization',
    blurb='The formalization of the polynomial Freiman-Ruzsa conjecture over characteristic 2.',
)
