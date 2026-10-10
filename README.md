# lean4-explainer

**Read real, computer-checked mathematics, one step at a time.**

Lean 4 is a programming language where you write a math proof and the computer checks every single step. People have used it to formalize huge results, including Fermat's Last Theorem. But a pile of `.lean` files is hard to read if you have never seen one.

lean4-explainer turns that pile into a website you can browse like a guided tour: every theorem gets a plain-English heading, the idea behind it, the steps of the proof, and links to the things it depends on.

**See it live:** https://timelordraps.github.io/lean4-explainer/ (eight well-known Lean projects, including the Fermat's Last Theorem project)

## Who is this for?

Someone who loves math and is curious about Lean. You do not need to know Lean, and you do not need to install it to read the site. If you have seen calculus or differential equations in high school, you have the background for most of the pages. When a word is new, the site has a glossary.

It is also for people who write Lean and want others to understand it. You add short comments above your theorems, and the site does the rest.

## What a page shows

Every theorem and definition gets a **Reading**, written from its source:

- **It says:** the statement in words. For example, `(∀ a b, f (2 * a) + 2 * (f b) = f (f (a + b))) ↔ f ∈ solution_set` becomes "for every a, b, f (2 * a) + 2 * (f b) equals f (f (a + b)) exactly when f is an element of solution_set". Below the words, the statement is typeset as a formula, the way a textbook would print it.
- **Its value:** a definition as a formula. `Real.pi * ∑ j, Complex.normSq (z j)` shows as π ∑ⱼ |zⱼ|².
- **Given:** each variable and what kind of thing it is ("a function that takes ℤ and gives ℤ"), and each assumption in words.
- **How the proof goes:** by induction, by contradiction, by cases, or in N steps. Then every step of the proof, with what it does: "Rewrite using …", "Split into two cases: …", "Finish: … is exactly what is needed".
- **Results it uses**, each one a link, and the **symbols** in the statement explained (∑, ∣, ↑, ⌊x⌋, …).

Where a project has added explanations of its own (or we have, in a separate overlay file), you also see:

| You see | It means |
|---|---|
| A title and one-sentence **intuition** | Why this is true, in plain words |
| Numbered **proof steps** | The shape of the argument |
| **Prerequisites** | What you should understand first |
| **Glossary** words | A defined word links to its meaning |
| The **statement** and a link to the real source | The exact Lean, when you want it |

## How relationships show up

Math is a web of results leaning on each other. The site shows that web in four ways:

1. **The map on each declaration.** Open "Map" under any result to see what it builds on (left) and what uses it (right), two steps each way. The links are read from the code itself, so every project has them, explained or not. Every box is a link, and the map wears the project's own colours.
2. **The project map** (`map.html`). The folders and how they use each other, and any one file with the files around it.
3. **The learning path** (`learning-path.html`). One reading order where nothing appears before the things it needs (from L4DEL `prereq` lines).
4. **Link lists** under each declaration: Prerequisites, See also, and the results it uses.

With the optional Lean extension, each declaration also lists the definitions and lemmas its statement and its proof use, taken from Lean itself.

## Try it on your own computer

You need Python 3.11 or newer. The tool is not on PyPI yet, so install it from a copy of this repository:

```
git clone https://github.com/TimeLordRaps/lean4-explainer
cd lean4-explainer
pip install -e . -e packages/reader -e packages/map -e packages/l4del
lean4-explainer build --lean-root path/to/your/lean/files --out docs
```

Open `docs/index.html` in a browser. That is the whole site. It works offline and makes no network requests.

To see the explanation features without writing any, build one of the example projects (this downloads it, and asks first):

```
pip install -e packages/corpora -e packages/corpus-flt
lean4-explainer showcase --out site
```

## Write your own explanations (L4DEL)

L4DEL is a tiny way to explain a theorem inside a Lean comment. Put lines like these just above it:

```lean
-- L4DEL: title: Two odd numbers add to an even number
-- L4DEL: intuition: Odd means one more than a multiple of two, and two of those "one more"s make a multiple of two.
-- L4DEL: step: Write each number as 2k + 1.
-- L4DEL: step: Add them to get 2(k + m + 1).
-- L4DEL: prereq: Nat.odd_iff
theorem odd_add_odd ...
```

Lean treats them as ordinary comments, so your proofs are untouched. Run `lean4-explainer check` and it tells you what is missing or misspelled. Run `lean4-explainer annotate --file Foo.lean` and it prints a ready-to-fill template for every declaration that has no explanation.

If you do not own the project, keep the explanations in a separate **overlay** file instead of editing their source. That is how the example projects on the live site are annotated. The details are in the [reference](docs/REFERENCE.md).

## Pick your pieces

The core is small and works alone. You add only what you want:

| You want | Install | You get |
|---|---|---|
| A quick page of your Lean code | the core | The site from your declarations and comments |
| A plain-English reading of every declaration | `packages/reader` | The Reading: claim in words and as a typeset formula, givens, every proof step explained |
| What builds on what | `packages/map` | A map on every declaration and a project map, read from the code |
| Titles, intuition, steps, glossary, learning path | `packages/l4del` | L4DEL |
| Proof state after each tactic, and a trust badge | `packages/lean` | Needs Lean installed. It runs Lean on your files |
| `explain#Name` links, what changed between versions | `packages/ecosystem` | Links and a changes page |
| Ready-made example projects | `packages/corpora` and `packages/corpus-*` | Eight projects, pinned to exact versions |

Once the packages are published these become `pip install lean4-explainer[reader]`, `[map]`, `[l4del]`, `[lean]`, `[ecosystem]`, `[all]` and one extra per project (`conjectures`, `carleson`, `flt`, `pfr`, `compfiles`, `tutorials`, `oai`). They are not published yet, so use the checkout for now.

## Words you will meet

- **Theorem, lemma:** a statement that has been proved. A lemma is usually a smaller helper.
- **Definition (`def`):** a name for a precise idea, such as "continuous".
- **Proof:** the argument. In Lean, a proof is code, and Lean checks it.
- **Tactic:** one command inside a proof, such as "rewrite using this equation". The Lean extension shows what is left to prove after each tactic.
- **Mathlib:** the big shared library of formalized math that many Lean projects build on.
- **Axiom:** something assumed without proof. Lean's three standard ones are normal. The trust badge tells you if a result uses anything beyond them.
- **`sorry`:** Lean's "I have not proved this yet". A result that uses it is not finished.
- **Declaration:** any named thing in Lean: a theorem, a definition, and so on.
- **Kernel:** the small core of Lean that finally accepts or rejects a proof. The trust badge comes from asking it.

## Where to learn Lean itself

Two of the example projects are tutorials, so you can read them here and then do them for real: [Mathematics in Lean](https://github.com/leanprover-community/mathematics_in_lean) and [Theorem Proving in Lean 4](https://github.com/leanprover/theorem_proving_in_lean4).

## Honest limits

- The tool reads your files as text. Without the Lean extension it does not run Lean, so it cannot say whether a proof is correct. The site says so on each page.
- The Reading comes from patterns over the source. It says what each tactic does in general, not the exact goal left after it (the Lean extension shows that). Anything it does not recognize is shown as code, never guessed. Across all eight example projects about 3% of statements fall back to code.
- The map reads names, not types. It follows Lean's rules for namespaces, `open`, imports and local names, but it misses a result reached as a field of a value (`P.freyCurve`) and names built by macros. It is left out for openai/math, whose pages would not fit in GitHub Pages' size limit with it.
- The openai/math project is too big to publish twice (1.1 GB of source), so its pages fetch their file from GitHub, at the pinned commit, to make the Reading.
- The explanations on the example projects were written for this site. They are not the authors' words, and the site says that too.
- A few kinds of declaration (indented ones, ones made by macros) are not listed.

## More

The complete manual, with every setting and the exact rules for L4DEL, is in [docs/REFERENCE.md](docs/REFERENCE.md). Each extension has its own README in `packages/`.

Licensed under Apache-2.0. The example projects keep their own licenses, shown on the site next to each one.
