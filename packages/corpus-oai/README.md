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

It also carries two sidecar files kept in lean4-explainer, never in the upstream sources, and not written by the
upstream authors:

- `overlay.l4del`: L4DEL explanations of selected declarations (used when `lean4-explainer[l4del]` is installed).
- `implications.toml`: curated implication edges, each a claim with its contract: what it starts from and reaches,
  the exact hypotheses and conclusion, the commit it was read at, and its status (used when
  `lean4-explainer[implications]` is installed). It has one argued edge: the 7/8 nonvanishing theorem for Dirichlet
  L-functions gives the uniform real-zero gap with the explicit constant c = (log 3)/8, for every character. It also
  has one candidate (the fluid halting theorem with the single-fold representation), with what it is missing.
