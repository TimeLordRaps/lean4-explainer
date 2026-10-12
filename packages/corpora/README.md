# lean4-explainer-corpora

The `sources`, `fetch` and `showcase` commands for [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer),
and the registry that finds installed corpus packages (`lean4-explainer-flt`, `-carleson`, `-pfr`, ...).

```
pip install lean4-explainer[all]       # every corpus
lean4-explainer sources                # what is installed, with pinned commits and licenses
lean4-explainer showcase --yes         # download them and build one subsite each
```

Nothing is downloaded without `--yes` (or a typed yes in a terminal). Corpus sources are fetched from GitHub at the
commit each corpus package pins.

Corpus packages contain the pinned repository description, not L4DEL explanations. A hosted showcase can opt into
overlays through `--overlay-manifest`: the manifest binds each overlay to the corpus repository, exact commit and
content hash, and records whether a human reviewed it. Unreviewed AI-generated explanations remain visibly labelled.

The openai/math corpus also has an `implications` file of curated implication edges. The showcase checks each edge
against the corpus's pinned commit, and the landing page says who curated them.
