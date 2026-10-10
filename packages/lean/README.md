# lean4-explainer-lean

Runs Lean over a project and adds to a [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer) site:

- **Trust badges** from the kernel: for each declaration, the axioms it depends on, as Lean's `collectAxioms` reports them. No axioms, standard axioms (`propext`, `Classical.choice`, `Quot.sound`), extra axioms, or `sorryAx`.
- **Tactic traces**: for each tactic step, the goals before and after.
- A **Trust** page listing declarations that depend on `sorry` or on axioms beyond the standard three.

```
pip install lean4-explainer[lean]
lean4-explainer build --lake-root . --out docs
```

It needs `lean` on the PATH. In a Lake project it runs through `lake env`, so the project's dependencies must already be built (`lake build`). A file that does not elaborate, or a declaration Lean has no constant for, is shown as trust UNKNOWN with the reason. Nothing is guessed. Results are cached by file content, Lean version, probe version and the project's `lake-manifest.json` and `lean-toolchain`.

Config keys: `lean_timeout` (seconds per file, default 300), `lean_jobs`, `lean_steps` (steps shown per declaration, default 200), `lean_project` (Lake project directory), `lean_cache`.
