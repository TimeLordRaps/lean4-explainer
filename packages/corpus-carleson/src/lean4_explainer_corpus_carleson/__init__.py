"""Carleson's theorem: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

CORPUS = Corpus(
    name='carleson',
    title="Carleson's theorem",
    repo='fpvandoorn/carleson',
    commit='8972acdfd953c63bb2501ace20d61ced7c0697ec',
    branch='master',
    kind='formalization',
    blurb="The formalization of Carleson's theorem on the convergence of Fourier series.",
)
