# lean4-explainer-lean

Runs Lean over a project and adds to a [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer) site:

- **Trust badges** from the kernel: for each declaration, the axioms it depends on, as Lean's `collectAxioms` reports them. No axioms, standard axioms (`propext`, `Classical.choice`, `Quot.sound`), extra axioms, or `sorryAx`.
- **Tactic traces**: for each tactic step, the goals before and after. A step is a tactic as the author wrote it: Lean records info for more than tactics (the `by` block, a tactic sequence, a rewrite rule, one name inside a macro expansion), so the probe marks the nodes whose syntax kind is in Lean's `tactic` category (`isTactic`) and keeps, at each position, the widest of them, with the goals Lean reports around exactly that tactic. The reader (`packages/reader`) reads each step's words from these goals. Checked on Lean 4.27.0, 4.28.0, 4.30.0, 4.33.0 and 4.35.0, with Mathlib on 4.27.0. Each step has an anchor, `#L<line>-step<k>` (the declaration's line and the step's number), and a link to the tactic's line in the source. With the reader (`packages/reader`) on the same page, each step links to the same step of the Reading ("in words") and back ("goals").
- A **Trust** page listing declarations that depend on `sorry` or on axioms beyond the standard three, with a legend of the badges (`trust.html#badges`). Every badge links to it.
- An answer to other extensions about what the kernel said of a declaration (`kernel_trust`). The implications extension uses it to check an edge's bridge.

```
pip install lean4-explainer[lean]
lean4-explainer build --lake-root . --out docs
```

It needs `lean` on the PATH. In a Lake project it runs through `lake env`, so the project's dependencies must already be built (`lake build`). A file that does not elaborate, or a declaration Lean has no constant for, is shown as trust UNKNOWN with the reason. Nothing is guessed. Results are cached by file content, Lean version, probe version and the project's `lake-manifest.json` and `lean-toolchain`.

Config keys: `lean_timeout` (seconds per file, default 300), `lean_jobs`, `lean_steps` (steps shown per declaration, default 200), `lean_project` (Lake project directory), `lean_cache`, `lean_max_working_set_mb`, and `lean_min_free_virtual_mb`. On Windows the first bound is also installed as an OS-enforced per-process commit ceiling; both are monitored every 250 ms. A guard stop remains `UNKNOWN` and is never reported as a failed proof.
