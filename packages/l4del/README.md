# lean4-explainer-l4del

L4DEL (Lean4 Domain Explanation Language) for [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer).

L4DEL is a set of `-- L4DEL: key: value` line comments that add titles, intuition, proof steps, prerequisites, related
declarations and glossary terms to a declaration. This package adds them to the generated site (the terms to its glossary page), plus a
learning path ordered by prerequisites, an annotation guide, and the `check` and `annotate` commands.

```
pip install lean4-explainer[l4del]
lean4-explainer check --lean-root lean
lean4-explainer annotate --lean-root lean --file Demo/Basics.lean
```

Without this package, lean4-explainer still builds a complete site from standard Lean comments.
The grammar is in the module docstring of `lean4_explainer_l4del/grammar.py`.
