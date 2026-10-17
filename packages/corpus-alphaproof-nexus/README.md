# lean4-explainer-alphaproof-nexus

Google DeepMind's published AlphaProof Nexus result files, as a pinned lean4-explainer corpus.

- Source: https://github.com/google-deepmind/alphaproof-nexus-results
- Pinned commit: `0647711a71183c1ea492ad60860776617ce1ea88`
- Peer-reviewed paper: https://doi.org/10.1126/science.aej2213
- License: Apache-2.0

```text
pip install lean4-explainer[alphaproof-nexus]
lean4-explainer showcase alphaproof-nexus --yes
```

This package contains only the pinned corpus description. It does not bundle the upstream Lean files, the upstream
human-written prose companions, or the hosted L4DEL overlay. Sources are fetched from GitHub when a user explicitly
builds the corpus. The public showcase compiles the pin locally and keeps its separately disclosed explanatory overlay
under `hosted/overlays/`.

The hosted showcase retains each declaration's local Lean trust classification, corpus Trust page, and bounded
per-tactic goal traces. The complete site is measured before publication so these traces cannot silently cross the
GitHub Pages published-site boundary.
