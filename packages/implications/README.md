# lean4-explainer-implications

Curated **implication edges** for a [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer) site: claims that one result could establish another, each with an explicit contract. And a **discovery pipeline** that finds narrowly defined implications between a corpus's theorems and has Lean's kernel check each one, for a catalogue of checked implications beside the curated edges.

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
| `proved` | `bridge` | A Lean declaration (the bridge) states the hypotheses and the conclusion and proves them. When the same build runs Lean (`lean4-explainer[lean]`), the kernel checks the bridge: the edge shows as kernel-checked, or as failing (with a build warning) if the bridge depends on `sorry` or on extra axioms. Without a Lean run it shows as "proved, not checked here". A bridge can also live in a bridge file beside the edge file, checked by the pipeline and recorded (below). |
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
# bridge_file = "bridges/Gap.lean"            # proved, optional: the file beside this one that declares the bridge
# relation = "gap_gives_target"               # strengthens with a bridge file: proves (the contract) -> the target's statement
# improvement = "an explicit constant"        # strengthens with a bridge file: what the contract adds
# construction = "Ns.f"                       # supports-construction with a bridge file: the computable definition
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

## Bridge files and recorded checks

A bridge that is not part of the project goes in a bridge file beside the edge file (`bridge_file`). It takes each source as a hypothesis, `theorem gap (source1 : S₁) … : ∀ hypotheses, conclusion`, so nothing in it can use a source's released proof.

```
python -I -m lean4_explainer_implications.pipeline contracts --workspace WS --corpus LEAN_ROOT --run RUN --edges implications.toml
```

By default this updates `implications.verified.json` beside the edge file. For a transactional promotion, add
`--record RUN/implications.verified.candidate.json`, then pass that same `--record` to `catalogue` and `report`;
the tracked record can remain unchanged until the complete candidate has passed its aggregate validation.

elaborates the bridge file in the corpus's own environment (one Lean process per file). Then, for each edge, the kernel checks that:

1. The bridge's proof term proves exactly `∀ (source1 : type of S₁) …, ∀ hypotheses, conclusion`, the proposition the edge states, with the sources' types read from Lean. A valid theorem of another statement fails: `True`, an extra hypothesis, another domain, another quantifier order.
2. It uses no axioms beyond `propext`, `Quot.sound` and `Classical.choice`, so no `sorry` and no axiom of its own.
3. It does not use the target, or anything whose dependency closure reaches it (an alias included).
4. It uses every source it names.
5. For `strengthens`, the `relation` proves `contract → the target's statement` and uses the contract. The record also keeps both conclusions and the rendered hypotheses shown only in the target (this last comparison is textual, so alpha-renamed binders are not claimed different). A statement of the form `∃ c, 0 < c ∧ ∀ …` is read inside: its witness becomes a variable, the last part of the conjunction is read on, and the record names what was read through.
6. For `supports-construction`, the `construction` is a computable definition the contract mentions.

The results go into `<edge file stem>.verified.json`, beside the edge file. Each record holds:

- the edge's **fingerprint** (its contract and the bridge file's SHA-256);
- the SHA-256 of each corpus file the bridge imports;
- the environment's identity, the Lean version, and the Mathlib and corpus revisions;
- the date, and a portable reproduction command (workspace and corpus paths are placeholders; workstation paths are never published).

A site build compares the record with what it has. The edge shows as kernel-checked "(recorded)" only when everything matches: the contract, the bridge file, the commit, and the corpus files it can read. Otherwise the record is **stale** and says nothing. A failed record fails the edge. Both are build warnings. The page says whether a check ran in that build or comes from a record.

## The discovery pipeline

`python -I -m lean4_explainer_implications.pipeline` runs in stages, each writing JSON into a run directory. It needs `lean`, and the workspace pins the corpus's Mathlib.

| Stage | What it does |
|---|---|
| `build` | Builds modules, and the corpus modules they import, with `lean -o` in import order. Each module gets a trace: its source, the toolchain and its imports' traces. A matching trace is not rebuilt. A new build starts only while the system can commit another Lean process's memory; low disk stops it. Every Lean process in the pipeline starts this way: parallel launches take turns, each after the one before has committed its memory, and a timeout stops the whole process tree (elan's `lean` is a proxy). |
| `extract` | Reads each declaration from Lean with `importModules`, not a parser. It records the name, module, range and universe parameters; the binders and their kinds; the elaborated type, with its conclusion and hypotheses after unfolding corpus definitions at the head; the constants the statement and the elaborated proof term use; the axioms; `sorry`; and, for a structure's field, its structure and index (Lean's projection info). Identity is (repository, revision, module, name). A declaration Lean could not inspect remains `unreadable` and makes the stage fail; it can never be relabelled as a released theorem. Two modules that declare the same name cannot be imported together. Before importing, Lean lists each compiled module's names, and such pairs go into separate environments. Every pair, and any batch an import still split, is recorded. |
| `discover` | Proposes candidates by structure only: heads of conclusions, parts and hypotheses, and shared constants that few statements mention, never names or doc text. Lemmas Lean generates (a constructor's injectivity, equation lemmas, `sizeOf_spec`) have no source position and are not proposed. Then it attempts each in Lean within a budget. A candidate whose declarations come from one extraction environment runs in it. Candidates that span environments share packed environments with no clash inside (`--env-modules`). A candidate whose own modules declare the same name is not attempted: no environment holds them, and it is listed as blocked with that name. Missing results, failed Lean processes and infrastructure/error outcomes make the stage exit nonzero. |
| `instantiate` | Applies checked derivations to the released theorems, for the solution modules that were built. A derivation whose sources' solution modules were not built is listed as blocked. Missing results, failed Lean processes and infrastructure/error outcomes make the stage exit nonzero. |
| `catalogue` | Groups the checked results and writes an index plus one shard per family; a rewrite removes the shards of families that no longer have entries. The index names the logical theorems and the exact released declarations used by checked instantiations; unresolved and rejected attempts keep their keys in the shards. An instantiation is not an entry of its own: a checked one makes its derivation `checked-instantiated`, a circular one moves it to "source uses the target", and one that established nothing is recorded on the entry, which stays a checked derivation. Orphan, duplicate or logically mismatched instantiation joins fail catalogue construction. |
| `contracts` | Checks curated bridge files (above). |
| `report` | Writes `REPORT.md` and `report.json` with every count and cost (connections also by what links their sources), and how many families and areas each stage of a layer reached (statements, attempts, checked derivations, derivations checked again on the released theorems, the layer's connections). |

On Windows, **free commit** is unused allocation capacity backed by RAM plus the pagefile; it is not just currently
free physical RAM. The default build gate waits for 17 GB of local headroom: an 11 GB measured allowance for one
Lean process plus a 6 GB safety reserve. That 17 GB is temporary build memory, not generated-site size and not
anything uploaded to GitHub Pages. Disk space is checked separately, and the system disk also matters when Windows
needs to grow the pagefile. While the gate waits it reports the current headroom once a minute.

`report` treats every `build*.json` in an ordinary run as current. If the run directory also retains diagnostic or
older build records, repeat `--authoritative-build NAME` for each record stem that is a current report input; the
others are labeled historical diagnostics rather than silently contributing promotion evidence.

### Rules and depth

An attempt states its sources as local hypotheses, `theorem derived (source₁ : S₁) … : D`, and searches backward from `D` to depth 2 (`--depth`). Its moves:

- **specialization**: apply a source with its variables filled by unification; every variable must be determined.
- **premise discharge**: close a remaining premise with `omega`, `norm_num`, `positivity` or `linarith`, each under its own heartbeat limit.
- **equivalence transport**: use either direction of an `↔`; the direction is recorded.
- **conjunction parts**: use either part of an `∧`.
- **equality rewriting**: one rewrite with a source equation, in either direction.
- **bound transfer**: assert a source inequality; `linarith`, `nlinarith` or `omega` must then close the goal using it.
- **witness transport**: take a source's existential witness, with the parts of its property.
- **short composition**: one source's conclusion, or a part of it, supplies another's hypothesis. The derived statement has the first source's binders, then what is left of the second's; a premise left over is discharged where the variables it mentions are in scope. The step records the supplied hypothesis's head and whether it only says a quantity is positive (`0 < x`, `0 ≤ x`). A universe level the derivation leaves free becomes a universe parameter of what is derived, as it is one of the source.

Quantifier order, domains, strict inequalities and exceptional cases are those of the statements. Nothing is inferred from names or nearby files. The search does not find every implication, and novelty is not assessed.

### What counts

The kernel checks the derivation and its axioms are audited. The proof must not reach the target. With `--instantiate`, or in the `instantiate` stage, the derivation is also applied to the actual released theorems and checked again. If a source's own released proof reaches the target, the instantiation is **circular**.

A derivation is **rejected** when it leaves a source unused, or when its statement holds without any source (its own hypotheses or one discharger prove it).

`no-proof` (nothing within the rules and depth) and `budget` (a heartbeat or time limit reached) are unresolved. Neither means "false".

The catalogue keeps three things apart: checked implications; proof dependencies, read from elaborated proof terms; and unresolved and rejected attempts, which go on the notes page.
Proof dependencies are resolved inside the extraction environment that contained the proof, so same-named declarations kept in separate Lean environments are never joined.

Checked results that add nothing are grouped, not counted as connections:

- a source with the same statement as the target;
- a source passed through unchanged: the proof is the source applied to the target's own variables, so the two state one proposition up to unfolding definitions (two challenges that each define the same claim);
- a lemma Lean generated, such as a constructor's injectivity or an equation lemma (it has no source position);
- two forms one challenge lists together, or a composition of statements from one challenge file;
- a route the released proof already takes;
- a source whose released proof uses the target;
- the other direction of an equivalence;
- a source that is a structure's field, such as `TriCylinder.convex : ∀ self, Convex ℝ self.base`: the derivation applies the other source to what the structure requires. Extraction reads this from Lean's projection info, not from names;
- a statement another result already derives.

Result IDs use each declaration's full corpus identity (repository, revision, module and declaration), not its Lean
name alone: different challenge modules can declare the same name. An instantiation keeps those logical challenge
identities for its public result and join, while its cache key uses the released declarations Lean actually checks;
one released verification can therefore be reused without conflating two logical derivations.

Results are cached by the rule set (the policy version and the digest of `Pipeline.lean`), the budget, the corpus prefixes and the environment's identity. Failures are cached too: only a larger budget or a changed rule set tries one again.

### On the site

Set `implications_catalogue`, or put a `catalogue` directory beside the edge file. The site then shows it in three places:

- **`implications/catalogue.html`** searches theorem, module, family and conclusion. It filters by relationship (rule), group, state, corpus layer and family. Data loads lazily: the index first, then a family's shard when an entry opens. An entry shows the statement checked, the exact contract (sources as hypotheses), the steps with their substitutions and discharged premises, the axioms, the environment, the cost and the proof term; where the derivation was applied to the released theorems, what that established, in which environment and at what cost (a run that ran out of budget reads "not established"). Multi-source entries read "jointly", and a composition says what links its sources: "linked only by a positivity fact" where the supplied hypothesis is `0 < x`, else the supplied hypothesis's head. The page counts the connections linked only by positivity. A chain view follows connections up to three steps each way.
- **Each theorem's page** lists "Gives" and "Follows from" for its checked connections. Routine entries are only counted.
- **`implications/notes.html`** lists unresolved attempts by status and reason, rejected derivations, and the curated edges still without a Lean check.

A site build never runs the search and never reruns Lean for the catalogue. Every catalogue page says it shows recorded results, with the environment they were checked in.
