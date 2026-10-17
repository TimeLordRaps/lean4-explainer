"""openai/math: the pinned source description lean4-explainer builds a site from."""

from lean4_explainer_corpora.registry import Corpus, package_file
from lean4_explainer_corpora.themes import make_theme, svg  # noqa: F401

THEME = make_theme(
    light=dict(fg="#222222", bg="#fafafa", muted="#767676", line="#e0e0e0", warn="#8a3b00", panel="rgba(0,0,0,0.05)", accent="#1b7f78", **{"warn-bg": "#fff1e0"}),
    dark=dict(fg="#dcdcdc", bg="#101010", muted="#8a8a8a", line="#2a2a2a", warn="#ffb46b", panel="rgba(255,255,255,0.05)", accent="#2aa198", **{"warn-bg": "#3a2a18"}),
    heading="ui-monospace, SFMono-Regular, Consolas, monospace",
    extra="""
h1 { font-size: 1.3rem; font-weight: 500; }
h1::before { content: "> "; color: var(--accent); }
h2 { border-bottom-style: dashed; font-weight: 500; }
""",
)

CORPUS = Corpus(
    name='oai',
    title='openai/math',
    repo='openai/math',
    commit='fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb',
    branch='main',
    kind='oai',
    blurb='Lean formalizations that accompany the openai/math manuscripts.',
    seo_description=(
        'Explore openai/math in plain language: locally checked Lean 4 formalizations, exact pinned source links, '
        'mathematical context, and separate Lean4 Domain Explanation Language (L4DEL) annotations.'
    ),
    lean_root='lean',
    lake=False,
    source_links='file',
    accent='#2aa198',
    theme_css=THEME,
    # curated implication edges, each a claim with its contract (see lean4-explainer-implications)
    implications=package_file(__file__, "implications.toml"),
    # 1.1 GB of Lean: per-declaration maps would not fit in the Pages size limit beside the pages themselves
    options=(
        ("map_dependencies", False),
        # Preserve concurrent workstation jobs. A resource stop is rendered as UNKNOWN and can be retried later.
        ("lean_max_working_set_mb", 5120),
        ("lean_min_free_virtual_mb", 10240),
    ),
    # its 1,286,783 definitions would not fit either: the glossary lists the 24,695 with a description
    glossary="described",
    # and its 336,022 imports: only a file that does nothing but import lists them (and what imports it)
    imports="import-only",
    # Hosted trust is complete by default. A resource-constrained diagnostic build must opt into a bound explicitly
    # with `showcase --lean-file-limit oai=N`; every omitted target then remains visibly UNKNOWN.
    lean_file_limit=0,
    # OpenAI explicitly recommends compiling only small portions of the 122k-file library. Its own catalogue names
    # the 200 main-result declarations that constitute the public formalization scope, so verify those exact targets.
    lean_catalogue="formalization.yaml",
)
