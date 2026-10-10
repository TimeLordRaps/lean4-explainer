"""The Lake facet, as text to paste into a project's lakefile.lean.

Lake facets are Lean code in the lakefile, so there is nothing to install on the Lake side: the facet runs the
`lean4-explainer` command, which must be on the PATH when `lake build :explain` runs.
"""

LAKEFILE_SNIPPET = """\
-- Add to lakefile.lean (after `import Lake` / `open Lake DSL` and the package declaration).
-- `lake build :explain` writes a lean4-explainer site for this package to `.lake/build/explain`.
-- It needs the `lean4-explainer` command on the PATH (pip install lean4-explainer).

/-- Build a lean4-explainer site for this package. -/
package_facet explain pkg : Unit := Job.async do
  let out := pkg.buildDir / "explain"
  let child ← IO.Process.output {
    cmd := "lean4-explainer"
    args := #["build", "--lake-root", pkg.dir.toString, "--out", out.toString]
  }
  if child.exitCode != 0 then
    error s!"lean4-explainer failed:\\n{child.stderr}{child.stdout}"
  logInfo s!"wrote {out}"
"""
