# lean4-explainer-oai

openai/math, as a lean4-explainer corpus.

- Source: https://github.com/openai/math
- Pinned commit: `fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`
- License: Apache-2.0

```
pip install lean4-explainer[oai]
lean4-explainer showcase oai --yes
```

This package holds the pinned description of the project. The sources are fetched from GitHub when you build.

It also carries sidecar files kept in lean4-explainer, never in the upstream sources, and not written by the
upstream authors:

- `overlay.l4del`: L4DEL explanations of selected declarations (used when `lean4-explainer[l4del]` is installed).
- `implications.toml`: curated implication edges, each a claim with its contract: what it starts from and reaches,
  the exact hypotheses and conclusion, the commit it was read at, and its status (used when
  `lean4-explainer[implications]` is installed). It has one proved edge: the 7/8 nonvanishing theorem for Dirichlet
  L-functions gives the uniform real-zero gap with the explicit constant c = (log 3)/8, for every character. Its
  proof is `bridges/SevenEighthsGap.lean`, which takes the 7/8 theorem as a hypothesis. It also has one candidate
  (the fluid halting theorem with the single-fold representation), with what it is missing.
- `implications.verified.json`: the record of Lean's kernel checking that bridge against the edge's exact contract,
  at the pinned commit, on Mathlib `d13f23b7` and Lean 4.34.1. A site build compares the record with the files it
  has and shows the edge as checked only when they match. It does not run Lean again.
- `catalogue/`: implications the discovery pipeline found among the challenge statements and Lean's kernel checked,
  the attempts that established nothing, and `REPORT.md` with every count and cost. Under rule set
  `rules-1:c88d27fdc5e2730d`: 3,823 attempts among 2,212 challenge statements gave 100 checked derivations, 24 of them
  connections (the rest routine, grouped), across 38 families in 12 areas; 3,719 attempts established nothing and 4
  were rejected. The sources were taken as hypotheses: the solution modules were not built, so none was applied to the
  released theorems yet.
