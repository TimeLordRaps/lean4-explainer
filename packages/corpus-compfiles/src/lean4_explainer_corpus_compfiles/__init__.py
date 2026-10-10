"""Compfiles: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

CORPUS = Corpus(
    name='compfiles',
    title='Compfiles',
    repo='dwrensha/compfiles',
    commit='47b19bbfe5f38dc49379a6b53008d2909c4d71c5',
    branch='main',
    kind='competition',
    blurb='Formalized statements and solutions of olympiad-style problems.',
)
