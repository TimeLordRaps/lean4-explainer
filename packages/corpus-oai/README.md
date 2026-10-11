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
  `rules-1:c88d27fdc5e2730d`: 3,823 attempts among 2,212 challenge statements gave 100 checked derivations across 38
  families in 12 areas; 3,719 attempts established nothing and 4 were rejected. 14 of the 100 are connections, across
  15 families in 7 areas. The rest are routine and grouped, among them 13 that go through a structure's field
  (extraction, under `rules-1:2417946e30d8228a`, reads which declarations are fields from Lean). The sources were
  taken as hypotheses. The solution modules of two families (ProductSpaces,
  PlanarAnderson) were built: 9 of the 100 were then applied to the released theorems and checked again (3 of them
  connections), and 91 wait for solution modules that were not built. That build also compared the 5 released
  theorems it holds with their challenge copies (the same expression each) and read 374 proof dependencies among 84
  of their theorems, which are listed apart from the checked implications.
