"""Formal Conjectures: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

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
)
