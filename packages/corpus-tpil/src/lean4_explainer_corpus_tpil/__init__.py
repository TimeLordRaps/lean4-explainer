"""Theorem Proving in Lean 4: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

CORPUS = Corpus(
    name='tpil',
    title='Theorem Proving in Lean 4',
    repo='leanprover/theorem_proving_in_lean4',
    commit='4e28129fdd58037f8f5857548d5e99fe4fb0cc57',
    branch='master',
    kind='tutorial',
    blurb='The book on Lean 4 itself: dependent types, tactics, inductive types.',
    lake=False,
    include=('book/TPiL.lean', 'book/TPiL/*', 'examples/Examples.lean', 'examples/Examples/*'),
)
