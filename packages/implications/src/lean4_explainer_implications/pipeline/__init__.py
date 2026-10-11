"""The discovery pipeline: read theorem statements from compiled Lean, propose narrowly defined relationships between
them, and keep only the ones Lean's kernel checks.

    python -m lean4_explainer_implications.pipeline --help

Stages, each recorded: build (targeted `lean -o` builds against a pinned Mathlib), extract (declarations, types,
binders, proof dependencies and axioms, read from the compiled environment), index (structural keys), candidates
(bounded, per rule), attempts (bounded proof search in Lean, kernel check, audit), catalogue (checked results, proof
dependencies and unresolved attempts, kept apart), report (coverage, costs and failures).
"""

POLICY_VERSION = "rules-1"
