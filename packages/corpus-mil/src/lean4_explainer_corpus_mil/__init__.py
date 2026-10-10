"""Mathematics in Lean: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

CORPUS = Corpus(
    name='mil',
    title='Mathematics in Lean',
    repo='leanprover-community/mathematics_in_lean',
    commit='dd6d752fedb14082f557913c2dccb2d4851e5173',
    branch='master',
    kind='tutorial',
    blurb=('The tutorial that teaches Lean 4 and mathlib through mathematics. Exercises and solutions share '
 'names.'),
)
