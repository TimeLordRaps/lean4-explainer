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
