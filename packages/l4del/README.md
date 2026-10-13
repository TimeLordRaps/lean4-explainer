# lean4-explainer-l4del

Lean4 Domain Explanation Language (L4DEL) for [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer).

L4DEL is a set of `-- L4DEL: key: value` line comments that add titles, intuition, proof steps, prerequisites, related
declarations, glossary terms, top-of-page acronym legends, structured source citations, and linked quotations to a declaration. A citation uses
`-- L4DEL: source: label = https://stable.example/source`; it is displayed beside the explanation and may be repeated.
An acronym uses `-- L4DEL: acronym: SHORT = expansion`. A quotation uses
`-- L4DEL: quote: source label = exact excerpt` and must name one of the annotation's sources.
This package adds them to the generated site (the terms to its glossary page), plus a
learning path ordered by prerequisites, an annotation guide, and the `check` and `annotate` commands.

```
pip install lean4-explainer[l4del]
lean4-explainer check --lean-root lean
lean4-explainer annotate --lean-root lean --file Demo/Basics.lean
```

Without this package, lean4-explainer still builds a complete site from standard Lean comments.
The grammar is in the module docstring of `lean4_explainer_l4del/grammar.py`.
