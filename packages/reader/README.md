# lean4-explainer-reader

Gives every declaration on a lean4-explainer site a **Reading**, written in plain English from its source (and, for each proof step, from the goals Lean reports when the Lean extension ran; see [Where a step's words come from](#where-a-steps-words-come-from)):

- **It says:** the statement in words, for example "for every n, there is m such that n is less than m", and then the statement as a typeset formula.
- **Its value:** for a definition, the definition as a formula: `def capacity (z : Phase n) : ℝ := Real.pi * ∑ j, Complex.normSq (z j)` shows as capacity(z) = π ∑ⱼ |zⱼ|². A `match` or `if` it cannot draw is read case by case, and anything else it cannot draw is shown as written. Only a function applied to arguments is read as "Apply f to a, b".
- **… means:** for a definition whose value is a statement, what it means in words, then as a formula when one can be drawn: `def IsSumDistinctSet (A : Finset ℕ) (N : ℕ) : Prop := A ⊆ Finset.Icc 1 N ∧ …` reads "IsSumDistinctSet A N means: A is a subset of [1, N], and …".
- **Given:** each variable with what kind of thing it is ("a real number", "a number from 0 up to n − 1"), and each assumption in words.
- **How the proof goes:** the shape (by induction, by contradiction, by cases, one step), then every tactic step with what it does. Cases (`·`), `induction … with`, `calc` chains and `have` steps are shown as structure.
- **Results it uses:** linked to the declaration on the page, or to the Mathlib documentation.
- **Symbols:** what ∑, ∣, ↑, ⌊x⌋, `Finset.range` and other symbols in the statement mean.
- **The Lean source** of the declaration, folded.

```
pip install -e packages/reader      # from a checkout; on PyPI later as lean4-explainer[reader]
lean4-explainer build --lean-root lean --out docs
```

The reading is made by `_assets/reader.js` in the browser. A page carries its file's source as JSON, so it works offline.

## Formulas

`_assets/lean2tex.js` translates Lean expressions into LaTeX, and [KaTeX](https://katex.org) draws them. It knows Lean's operator precedences and Mathlib's notation: sums and products over sets and ranges, integrals, limits (`Tendsto … atTop (𝓝 a)`), "for all large enough n" (`∀ᶠ n in atTop`), "almost every" (`∀ᵐ`), asymptotic comparisons (`=O[…]`, `~[…]`), casts, absolute values and norms, set-builder notation, vectors and matrices, and more. `let` lines become "where x = …".

Anything it cannot parse is left as Lean code, never guessed, and the Lean text is always one hover away. In the earlier eight-corpus sweep (60,393 declarations, before AlphaProof Nexus was added) it typeset 91% of statements and 87% of definition values; all 279,396 formulas it produced rendered in KaTeX without an error.

KaTeX 0.16.47 ships inside the package (`vendor/katex`, MIT licence, checked against the published release's checksums), and is copied to `_assets/katex/` with its licence. It loads only when a page has a formula. Pages make no network requests for it.

Parentheses are plain `( )` unless what they hold is tall (a fraction, a sum, a binomial, a root): `\left( … \right)` would leave a gap after a function's name, as in "capacity (z)".

## Doc comments

Inline Lean applications in explanatory prose use the same parser-backed mathematical renderer as declaration readings: `f x`, `Fin r`, and `h_seq m d` appear as $f(x)$, $\operatorname{Fin}(r)$, and $h_{\mathrm{seq}}(m,d)$. Hovering preserves the exact Lean spelling. Linked quotations, fenced code, source blocks, and declaration statements remain verbatim.

Doc comments are Markdown with TeX in them. The core draws the Markdown and marks each formula (its rules for dollars are in the [reference](../../docs/REFERENCE.md#doc-comments)); the reader typesets the formulas, on file pages and in the glossary. A formula is drawn as its author wrote it. When KaTeX will not take it, the reader tries what TeX itself would accept: a Markdown escape left in the TeX (`p_n\\#`, `\Sigma^\*`), and a command as a subscript (`f_\max`, which KaTeX wants as `f_{\max}`). Plain TeX's `\sp` and `\sb` are defined. A formula it still cannot draw stays as its TeX, never KaTeX's red error.

A project with a [blueprint](https://github.com/PatrickMassot/leanblueprint) keeps its TeX macros in `blueprint/src/macros/common.tex` (or `macro/`, `preamble/`) and `web.tex`. The reader reads `\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareMathOperator` and `\def` from there, so `\bbH[X]` in PFR's doc comments draws as it does in PFR's blueprint. A macro with an optional argument is left out, since KaTeX's macros cannot have one. The macros go into the site's `_assets/reader.js`, not into every page. PFR has 25, Carleson 39, FLT 39.

Over the doc comments of seven of the example projects (all but openai/math), 19,460 formulas, the reader draws all but 6. Those 6 have mistakes in their TeX (`\spN`, `\pmd`, `\mathbb^2`, a `\frac` with one argument, an unclosed brace), and stay as written.

## Glossary

Every word the reader explains is on the site's glossary page, each on a sample use: the types (`ℕ`, `Finset α`, `α → β`, …), the structures a type can have (`[Field K]`), the properties (`Injective f`, `Tendsto f atTop (𝓝 0)`), the symbols, and the tactics (`rw [h]`, `induction n with`). They come from `vocabulary.json`, which `tools/vocabulary.cjs` makes from the tables in `reader.js`:

```
node packages/reader/tools/vocabulary.cjs > packages/reader/src/lean4_explainer_reader/vocabulary.json
```

Run it after changing a table. A test checks the file is up to date and that every table entry is in it; the script stops on an entry that reads badly with no argument and has no sample.

## Where a step's words come from

`reader.js` never runs Lean. What a proof step says depends on whether the same build ran the Lean extension (`packages/lean`):

- **Lean was run.** Each tactic step is read from the goals Lean reports before and after it. The words say how the goals change: `intro hpq hqr hp` reads "Introduces `hpq : p → q`, `hqr : q → r` and `hp : p`. The goal becomes `r`.", `constructor` reads "Splits the goal into 2 goals: `left`: `q`; `right`: `p`.", `exact h` reads "Closes the goal.". A `·` case names the goal it works on, and a step that holds sub-steps (`induction n with`, `cases h with`) says which goal it starts from, since the "no goals" Lean reports after it belongs to the whole block. The tactic's own words stay beside this as a quieter "how". A step carries `data-basis="goals"`.
- **A step Lean has no matching step for** is read from the text of its tactic and marked `data-basis="source"` and "read from the source text". A step matches the Lean step on its source line with the same tactic (Lean keeps a tactic's first line); a different tactic on that line is never given another step's goals.
- **The goals cannot be loaded** (the trace file is missing, of another version, or slow): the reading falls back to the source text, and the note at the top of the page says that and why.
- **Lean was not run** for the site: the reading is the source's alone, the page says "it does not reconstruct Lean's intermediate goals", and no step says anything about goals.

The page loads a declaration's trace (`_traces/*.json.gz`, the format `packages/lean` writes: `{"v": 1, "d": {"<line>:<name>": [[line, tactic, goals before, goals after, href]]}}`) when the page opens. Each step also gets a "goals" link that opens the tactic trace at that step, and each trace step an "in words" link back. The links are made from the trace data, so they exist before the trace is opened.

The words for a statement come from patterns over common notation (quantifiers, connectives, relations, and predicates such as `Injective`, `Prime` and `Tendsto`). Anything it does not recognize is shown as code, never guessed.

## Config keys

- `reader_source_url`: a template such as `https://raw.githubusercontent.com/OWNER/REPO/{ref}/lean/{path}`. When it is set, pages do not carry the source. The pinned template is stored once in the corpus's shared `reader.js`; each file page derives its path from its linked path title and fetches that file when it opens. The showcase uses this for openai/math, whose 1.1 GB of source could not be published twice under GitHub Pages' 1 GB limit.
- `reader_embed_limit`: the largest file, in characters, a page carries. The default is 2,000,000. A bigger file gets no reading unless `reader_source_url` is set.
- `reader_blueprint_macros`: read the project's blueprint macros (default `true`).
