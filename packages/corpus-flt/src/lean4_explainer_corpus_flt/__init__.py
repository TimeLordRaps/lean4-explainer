"""Fermat's Last Theorem (FLT): the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

CORPUS = Corpus(
    name='flt',
    title="Fermat's Last Theorem (FLT)",
    repo='ImperialCollegeLondon/FLT',
    commit='f6c6a2fe9796d6d89cd2a0d24e8a453729d881ff',
    branch='main',
    kind='formalization',
    blurb="The Imperial College project to formalize a proof of Fermat's Last Theorem.",
)
