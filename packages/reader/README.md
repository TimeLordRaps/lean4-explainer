# lean4-explainer-reader

Gives every declaration on a lean4-explainer site a **Reading**, written in plain English from its source:

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

Anything it cannot parse is left as Lean code, never guessed, and the Lean text is always one hover away. Across the eight example projects (60,393 declarations) it typesets 91% of statements and 87% of definition values; all 279,396 formulas it produces render in KaTeX without an error.

KaTeX 0.16.47 ships inside the package (`vendor/katex`, MIT licence, checked against the published release's checksums), and is copied to `_assets/katex/` with its licence. It loads only when a page has a formula. Pages make no network requests for it.

Parentheses are plain `( )` unless what they hold is tall (a fraction, a sum, a binomial, a root): `\left( … \right)` would leave a gap after a function's name, as in "capacity (z)".

## Doc comments

Doc comments are Markdown with TeX in them. The core draws the Markdown and marks each formula (its rules for dollars are in the [reference](../../docs/REFERENCE.md#doc-comments)); the reader typesets the formulas, on file pages and in the glossary. A formula is drawn as its author wrote it. When KaTeX will not take it, the reader tries what TeX itself would accept: a Markdown escape left in the TeX (`p_n\\#`, `\Sigma^\*`), and a command as a subscript (`f_\max`, which KaTeX wants as `f_{\max}`). Plain TeX's `\sp` and `\sb` are defined. A formula it still cannot draw stays as its TeX, never KaTeX's red error.

A project with a [blueprint](https://github.com/PatrickMassot/leanblueprint) keeps its TeX macros in `blueprint/src/macros/common.tex` (or `macro/`, `preamble/`) and `web.tex`. The reader reads `\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareMathOperator` and `\def` from there, so `\bbH[X]` in PFR's doc comments draws as it does in PFR's blueprint. A macro with an optional argument is left out, since KaTeX's macros cannot have one. The macros go into the site's `_assets/reader.js`, not into every page. PFR has 25, Carleson 39, FLT 39.

Over the doc comments of seven of the example projects (all but openai/math), 19,460 formulas, the reader draws all but 6. Those 6 have mistakes in their TeX (`\spN`, `\pmd`, `\mathbb^2`, a `\frac` with one argument, an unclosed brace), and stay as written.

## Glossary

Every word the reader explains is on the site's glossary page, each on a sample use: the types (`ℕ`, `Finset α`, `α → β`, …), the structures a type can have (`[Field K]`), the properties (`Injective f`, `Tendsto f atTop (𝓝 0)`), the symbols, and the tactics (`rw [h]`, `induction n with`). They come from `vocabulary.json`, which `tools/vocabulary.cjs` makes from the tables in `reader.js`:

```
node packages/reader/tools/vocabulary.cjs > packages/reader/src/lean4_explainer_reader/vocabulary.json
```

Run it after changing a table. A test checks the file is up to date and that every table entry is in it; the script stops on an entry that reads badly with no argument and has no sample.

## What it does not do

It reads text. Lean is not run, so a reading says what each tactic does in general, not the goal it leaves. For real goals after every step, install the Lean extension (`packages/lean`). The words for a statement come from patterns over common notation (quantifiers, connectives, relations, and predicates such as `Injective`, `Prime` and `Tendsto`). Anything it does not recognize is shown as code, never guessed.

## Config keys

- `reader_source_url`: a template such as `https://raw.githubusercontent.com/OWNER/REPO/{ref}/lean/{path}`. When it is set, pages do not carry the source. Instead each page fetches its file from that pinned URL when it opens. The showcase uses this for openai/math, whose 1.1 GB of source could not be published twice under GitHub Pages' 1 GB limit.
- `reader_embed_limit`: the largest file, in characters, a page carries. The default is 2,000,000. A bigger file gets no reading unless `reader_source_url` is set.
- `reader_blueprint_macros`: read the project's blueprint macros (default `true`).
