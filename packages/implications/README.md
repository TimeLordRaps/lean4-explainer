# lean4-explainer-implications

Curated **implication edges** for a [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer) site: claims that one result could establish another, each with an explicit contract.

A dependency records which declarations a proof actually invokes; the map and the "uses" lists show those, read from the code. An implication edge records what a result could establish, even when the released proof goes another way. Because it is a claim, each edge keeps:

- the **source declarations** it starts from, and the declaration it reaches;
- the **exact hypotheses** and the **derived conclusion**, as Lean text;
- the **commit** the statements were read at;
- its **status**, and what backs it.

```
pip install lean4-explainer[implications]
```

## Kinds

| Kind | Contract |
|---|---|
| `strengthens` | From the sources and the hypotheses, the conclusion follows, and it gives the target's statement with more: an explicit constant, a weaker hypothesis, a wider range. |
| `composes-with` | The sources together give the conclusion, and it needs each of them (two or more sources; the target is optional). |
| `specializes-to` | The target's statement is the source's general statement with particular values or in a narrower setting; the hypotheses say which. |
| `supports-construction` | The sources justify a computable definition, the target, and the conclusion says what it computes. |

## Status

| Status | Needs | Means |
|---|---|---|
| `proposed` | `origin` | Someone suggested it. Nothing has checked it. |
| `argued` | `argument` | The argument is written out. Lean has not checked it. |
| `proved` | `bridge` | A Lean declaration (the bridge) states the hypotheses and the conclusion and proves them. When the same build runs Lean (`lean4-explainer[lean]`), the kernel checks the bridge: the edge shows as kernel-checked, or as failing (with a build warning) if the bridge depends on `sorry` or on extra axioms. Without a Lean run it shows as "proved, not checked here". |
| `refuted` | `evidence` | It does not hold as stated. |

An edge read at another commit than the one the site shows (`implications_commit`) is marked stale, with a build warning.

## The file

Edges live in a TOML file beside the project, never in its Lean sources: `implications.toml` in the Lean root, or the path in the config key `implications_file`.

```toml
[[edge]]
id = "explicit-real-zero-gap"                 # lowercase letters, digits, hyphens; unique
kind = "strengthens"
from = ["OAI.DirichletCharacter.LFunction_ne_zero_of_seven_eighths_lt_re"]
to = "OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap"
hypotheses = ["(q : ℕ) [NeZero q] (hq : 3 ≤ q) (χ : DirichletCharacter ℂ q) (hχ : χ ≠ 1)", "…"]
conclusion = "Real.log 3 / 8 ≤ (1 - β) * Real.log (q : ℝ)"
commit = "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb"
status = "argued"                             # proposed | argued | proved | refuted
origin = "who suggested it, and when"
argument = "the argument in words, and whose it is"
# bridge = "Ns.edge_lemma"                    # for proved
# evidence = "…"                              # for refuted
# note = "…"

[[candidate]]                                 # a suggestion with no contract yet, shown apart from the edges
id = "…"
kind = "composes-with"
from = ["Ns.a", "Ns.b"]
phrase = "the suggestion, in its proposer's words"
origin = "…"
missing = "what it needs to become an edge"
```

A name declared in more than one file of the project (with different text) is written `Name@path`, the path relative to the Lean root, to say which copy is meant: `OAI.SingleFold.main@OAI/NumberTheory/SingleFold/Main.lean`. The build lists the choices when a name is ambiguous. Pages and the JSON show the name as Lean knows it.

Every key is checked. An unknown key, a missing one, a contract with a gap (an `argued` edge with no argument, a `proved` one with no bridge), or a name the site does not have is a build error, so a typo never passes as a claim.

## On the site

- Each declaration an edge names (a source, the target, or the bridge) lists it, with its status and a link to its contract.
- `implications.html`: every edge grouped by kind, with its hypotheses, conclusion, argument or bridge, origin, and links to each end as it was at the edge's commit. Candidates follow, apart.
- `implications.json`: the same, as data, with the status this build could confirm.
- The glossary explains each kind and status.

Config keys: `implications_file` (the TOML file; relative paths are from the Lean root), `implications_commit` (the commit the site shows, for the stale check; the showcase sets it to each corpus's pin).
