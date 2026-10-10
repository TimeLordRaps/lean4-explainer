"""openai/math: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus

CORPUS = Corpus(
    name='oai',
    title='openai/math',
    repo='openai/math',
    commit='fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb',
    branch='main',
    kind='oai',
    blurb='Lean formalizations that accompany the openai/math manuscripts.',
    lean_root='lean',
    lake=False,
    source_links='file',
)
