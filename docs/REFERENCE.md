# lean4-explainer reference

The complete, detailed manual. For a gentle introduction start with the [README](../README.md).

Builds a static HTML proofsite from a Lean 4 source tree, so you can show your theorems to people who have not read the source. It reads `.lean` files as text and lists declarations, doc comments, plain comments, and statement snippets. It never runs Lean, so axiom and trust checks are UNKNOWN.

The core is small and needs nothing else. Everything that adds weight is an extension you opt into with a pip extra:

| You want | Install | What you get |
|---|---|---|
| A quick explanation page of your Lean code | `pip install lean4-explainer` | The site, from declarations and standard Lean comments |
| To write richer explanations in comments | `pip install lean4-explainer[l4del]` | **[L4DEL](#l4del-write-your-own-explanations)**: titles, intuition, proof steps, prerequisites, glossary, learning path, `check` and `annotate` |
| Tactic traces and kernel trust badges | `pip install lean4-explainer[lean]` | **[Lean run](#lean-run-tactic-traces-and-trust-badges)**: goals before and after each tactic, and the axioms each declaration depends on. Needs `lean` on the PATH |
| A plain-English reading of every declaration | `pip install lean4-explainer[reader]` | **[Reader](#reader-a-plain-english-reading-of-every-declaration)**: the statement in words and typeset, every proof step explained |
| What builds on what | `pip install lean4-explainer[map]` | A map on every declaration and a project map, read from the code |
| Claims that one result gives another | `pip install lean4-explainer[implications]` | **[Implications](#implications-curated-claims-about-what-follows)**: curated edges, each with hypotheses, conclusion, commit and status |
| `explain#Name` chat links, version diffs, a Lake facet | `pip install lean4-explainer[ecosystem]` | **[Ecosystem](#ecosystem-links-diffs-and-a-lake-facet)** |
| To see it on well-known Lean projects | `pip install lean4-explainer[all]` | Pinned descriptions of 8 projects, plus `sources`, `fetch` and `showcase` |

**Jump to:** [L4DEL: write your own explanations](#l4del-write-your-own-explanations) | [Quick start](#quick-start) | [Lake projects](#lake-projects) | [Implications](#implications-curated-claims-about-what-follows) | [Built-in corpora](#built-in-corpora-and-extras) | [Extensions](#extensions) | [Configuration](#configuration)

The default site, which `lean4-explainer[all]` builds with no annotation at all, is published from this repository's GitHub Pages once Pages is enabled for it (Settings, Pages, Source: GitHub Actions).

Note: the extension packages (`lean4-explainer-l4del`, `lean4-explainer-corpora`, `lean4-explainer-<corpus>`) are in `packages/` in this repository and have not been published to PyPI yet, so the extras resolve only after they are published. Until then install them from a checkout (see [Development](#development)).

## Quick start

```
pip install lean4-explainer
lean4-explainer build --lean-root lean --out docs
```

This writes `docs/index.html`, one page per Lean file (`docs/Foo/Bar.lean.html`), one `index.html` per folder, a search page, and shared assets in `docs/_assets/`. Pages make no network requests.

For a Lake project, list only the libraries its lakefile declares:

```
lean4-explainer build --lake-root . --out docs
```

### What is listed

- Declarations at column 0: `theorem`, `lemma`, `def`, `abbrev`, `structure`, `class`, `inductive`, `instance`, `axiom`, `opaque`, `example`.
- Qualified names from `namespace` and `section` blocks.
- A `/-- ... -/` doc comment directly above a declaration. If there is none, a plain `--` or `/- ... -/` comment directly above it (no blank line between) is used as its description.
- Statement snippets only for declarations that have a description. This keeps full-tree output small.
- The first `/-! ... -/` module doc in each file.
- Each file's imports, and the project files that import it (see `imports` below).

### Doc comments

Doc comments and module docs are Markdown with TeX in them, as doc-gen4 shows them, and the site draws them the same way: paragraphs, headings (`#` becomes a small heading under the declaration), bullet and numbered lists (nested too), quotes, rules, fenced code blocks, `` `code` ``, `*emphasis*`, `**strong**`, links and bare URLs. A link is made only to an `http`, `https` or `mailto` URL or a relative one; `[x](javascript:…)` stays text. Everything else is escaped. Tables, indented code blocks, reference-style links and HTML are not drawn: they show as written. A plain comment used as a description is shown as written, not as Markdown.

Formulas stay as their TeX, inside `<span class="tex">`, for the reader extension to typeset (without it they show as `$…$`). The rules, so that formulas are found and prices are not:

- `$…$` and `$$…$$`. A formula may run over a line break but not over a blank line, and a line inside an open `$$` that starts with `- ` or `#` stays part of it.
- A `$` inside braces does not close the formula (`$\max\{m \mid \textrm{$m$ prime}\}$` is one formula).
- A `$` just before a digit does not close one: "$100 for a proof and $1000 for a disproof" is text.
- A space just inside the dollars (`$A ⊆ ℕ $`) is allowed when the inside looks like TeX (a backslash, `^`, `_`, `=`, braces or a math symbol); "I have $ and you have $" stays text.
- `\$` is a dollar, and inside `` `code` `` nothing is a formula.
- Whether a declaration's text contains the word `sorry`.
- Same-named declarations: identical copies are one object; distinct definitions are listed with their files.

### Limits

- This is a text heuristic. Indented declarations, macro-generated declarations, and names created by `notation` or `syntax` are not listed.
- `sorry` detection is textual. It does not follow dependencies and does not check axioms.
- Without the Lean extension, Lean is not run, so axiom and trust checks are UNKNOWN.

<a id="l4del-write-your-own-explanations"></a>

## Lean4 Domain Explanation Language (L4DEL): write your own explanations

The Lean4 Domain Explanation Language (L4DEL) is an optional extension. It reads `-- L4DEL: key: value` line comments and adds an explanation layer to the site. The core never needs it, and a project that writes none gets the same output as without it.

```
pip install lean4-explainer[l4del]
```

Whenever a declaration has no valid L4DEL, the tool says what is missing and prints a template to paste in. The workflow for a human or an agent:

1. **Check** the tree with `lean4-explainer check --lean-root lean`. Errors go to stderr and the command exits with code 1. Warnings are listed.
2. **Annotate** one file with `lean4-explainer annotate --lean-root lean --file Demo/Basics.lean`. Each declaration without a valid annotation gets a template. Templates are printed, never written into your files.
3. **Paste** a template directly above its declaration, then replace every `TODO_` value.
4. **Build** with `lean4-explainer build --lean-root lean --out docs`. A `TODO_` left in a value is a warning, so the build reports it.

The generated site gets a Lean4 Domain Explanation Language guide page (`annotate.html`), its `term` and `acronym` lines in the glossary, an explanation legend at the top of each annotated file page, and a learning path ordered by prerequisites. Acronym-looking text without an explicit expansion is labeled unresolved rather than guessed; this guarantee covers the explanation layer, not arbitrary identifiers in upstream Lean code.

### The directive grammar

Each directive is one line comment:

    -- L4DEL: key: value

| Key | Value | Limit |
|---|---|---|
| `title` | short heading | at most one |
| `intuition` | one plain sentence on why the result holds | at most one |
| `step` | one proof step | any number, in source order |
| `prereq` | comma-separated fully qualified names the proof depends on | a repeated name is an error |
| `see` | comma-separated related declarations | a repeated name is an error |
| `term` | `word = definition` | each word is defined once in the project |
| `acronym` | `SHORT = expansion` | one consistent expansion across the project; repeated in affected page legends |
| `source` | `label = https://URL` | repeatable; each URL is unique |
| `quote` | `source label = exact excerpt` | repeatable; label must match a `source`, or the hosted overlay's pinned Lean source |

Rules:

- Only line comments carry directives. `L4DEL:` in a block, doc, or module comment is an error.
- Keys are case-sensitive. Any other key is an error.
- A directive attaches to the next declaration. Only blank lines, comments, attribute lines, and `set_option` lines may separate them. Other code makes a directive an orphan, which is an error.
- Anonymous declarations (`example`, unnamed `instance`) cannot carry directives.
- `prereq` and `see` names are exact. `foo` does not match `Demo.foo`. A name that matches nothing is a warning.
- `source` links appear beside the explanation under **Sources and attribution**. Use a full-commit GitHub blob URL, DOI, or versioned arXiv URL where possible; a citation makes the wording traceable but does not make it reviewed or correct.
- `quote` keeps exact source words visually and semantically separate from `intuition` and `step` prose. Its source label becomes the quotation link.
- A name with distinct definitions is ambiguous: a plain reference is an error, and it must be written `Name@path`, for example `Demo.value@Var/B.lean`.
- Values are trimmed, must not be empty, and are at most 2000 characters.
- The complete grammar is in `packages/l4del/src/lean4_explainer_l4del/grammar.py`.
- Without the extension installed, `-- L4DEL:` lines are ordinary comments.

`TODO_` placeholders are valid syntax, so a pasted template parses, and every `TODO_` left in a value is a warning until it is replaced. The tool never writes into your source files.

## Lean run: tactic traces and trust badges

`pip install lean4-explainer[lean]` adds an extension that elaborates each file with Lean (`lean` on the PATH; inside a Lake project it runs through `lake env`, so build the dependencies first). Every declaration then gets:

- a **trust badge** from the kernel: no axioms, standard axioms (`propext`, `Classical.choice`, `Quot.sound`), extra axioms (named), or `sorry`. This is `collectAxioms`, not a text search.
- a collapsible **tactic trace**: the goals before and after each tactic step. Each step has its own anchor (`#L<line>-step<k>`) and a link to its line in the source. With the reader installed, each step also links to the same step in the Reading ("in words"), and each step of the Reading links back to its goals.
- a **Trust** page listing declarations that depend on `sorry` or on extra axioms, with a legend of what each badge means (`trust.html#badges`; every badge links there).

A file that does not elaborate shows trust UNKNOWN with Lean's reason, and a file where Lean reported errors says so on every badge. Nothing is guessed. Results are cached by file content, Lean version and `lake-manifest.json`. A Lake project that pins a Lean version you do not have makes elan download that toolchain on the first run. Each badge also lists the constants the statement and the proof use, with instances, coercions and auxiliary definitions counted but left out. This filtering is the expression-tree compression: it is a filter on the set of constants, not a compressed term. See `packages/lean/README.md` for the config keys. Other extensions can ask what the kernel said of a declaration (the `kernel_trust` hook): the implications extension uses it to check an edge's bridge.

## Reader: a plain-English reading of every declaration

`packages/reader` (the extra `reader`, also part of `all`) gives every declaration a Reading: the statement in words, what is given and assumed, the proof's shape, every tactic step with what it does (cases, `induction … with` arms and `calc` chains shown as structure), the results it uses (linked) and the symbols in the statement. `_assets/reader.js` writes it in the browser from the file's source, which each page carries as JSON. With `reader_source_url` set (the showcase sets it for openai/math), a page instead fetches its file from that pinned raw URL. It reads text only, so it says what a tactic does, not the goal it leaves. In the earlier eight-corpus sweep (60,393 declarations, with a 1,500-file sample of openai/math) it read every header, raised no errors, fell back to code for 2.5% of statements and did not recognize 0.7% of tactic steps. That historical measurement predates the AlphaProof Nexus corpus. It also puts every word it explains in the glossary, and typesets the formulas the core marks in doc comments (on file pages and in the glossary), with the project's own TeX macros when it has a blueprint. Over the doc comments of seven of those corpora (19,460 formulas) it draws all but 6, which have errors in their TeX and stay as written. When the same build ran Lean, each step of the Reading links to its goals in the tactic trace ("goals" opens the trace at that step), joined by source line and tactic. Details and config keys: `packages/reader/README.md`.

## Implications: curated claims about what follows

`packages/implications` (the extra `implications`, also part of `all`) adds implication edges. A dependency, which the map and the "uses" lists show, records which declarations a proof invokes, read from the code. An implication edge records what one result could establish about another, even when the released proof goes another way. Because it is a claim, each edge keeps a contract: the declarations it starts from and the one it reaches, the exact hypotheses and the derived conclusion as Lean text, the commit the statements were read at, and its status: `proposed`, `argued` (the argument is written out), `proved` (a Lean bridge declaration proves it) or `refuted`. The kinds are *strengthens*, *composes with*, *specializes to* and *supports an executable construction*.

Edges live in a sidecar `implications.toml` beside the project, never in its sources. Every key is checked, and every name must be on the site. Each declaration an edge names lists it with its status and a link to its contract. `implications.html` groups the edges by kind, with candidates (suggestions without a contract yet) apart. `implications.json` has the same as data. When the same build runs Lean, a proved edge's bridge is checked by the kernel: no `sorry` and no extra axioms, or the edge shows as failing, with a build warning. An edge read at another commit than the site shows is marked stale. The showcase gives openai/math one argued edge (its 7/8 nonvanishing theorem gives the uniform real-zero gap with c = (log 3)/8) and one candidate. Format and details: `packages/implications/README.md`.

## Ecosystem: links, diffs and a Lake facet

`pip install lean4-explainer[ecosystem]` adds three things (details in `packages/ecosystem/README.md`):

- `find.html#Foo.bar` jumps to a declaration, the target for an `explain#Foo.bar` chat link (a Zulip linkifier is described there).
- `snapshot.json` on every site, and with `compare_to` set to an earlier snapshot, a `changes.html` listing statements changed, proofs changed, declarations added and removed. Digests are of the text, not of elaborated terms.
- `lean4-explainer lake-facet` prints the lakefile snippet that adds `lake build :explain`.

## Lake projects

Lean and Lake do not need to be installed. The explainer reads text and starts no processes.

- `--lake-root DIR` reads `lakefile.toml` (or best-effort, `lakefile.lean`) and lists only the files of the libraries it declares. A library `A` takes `A.lean` and the folder `A/`, explicit `roots` replace that default, `A.*` and `A.+` globs take the folder, and a plain glob takes one module. `srcDir` is honored. This is a rule on file names, not Lake's import resolution: a file in a library folder is listed even if nothing imports it.
- It also reads `lean-toolchain`, the `rev` of each `require`, and the commits in `lake-manifest.json`.
- `--lean-root DIR` lists every `.lean` file under `DIR`. Either way it skips `lakefile.lean` at any depth, `lake-packages/` (Lake's older dependency directory), and hidden directories such as `.lake/`.
- A library that is a test or example folder (for example `FLTTest`) is listed if the lakefile declares it. Add its name to `exclude`.

Tactic traces (the goal state after each tactic) are not in a lakefile; they come from the [Lean run](#lean-run-tactic-traces-and-trust-badges) extension.

## Built-in corpora and extras

`pip install lean4-explainer[all]` adds nine Lean projects, each pinned to a commit, so you can see what the tool produces and link your own theorems to them. Each is its own small package (`lean4-explainer-<name>`) holding the pinned description, license, and license notes. The sources are fetched from GitHub on request, never bundled.

| Name | Project | Extra | License |
|---|---|---|---|
| `formal-conjectures` | [google-deepmind/formal-conjectures](https://github.com/google-deepmind/formal-conjectures) | `conjectures` | Apache-2.0; other material CC-BY 4.0; Wikipedia, MathOverflow and OEIS content CC-BY-SA 4.0 |
| `carleson` | [fpvandoorn/carleson](https://github.com/fpvandoorn/carleson) | `carleson` | Apache-2.0 |
| `flt` | [ImperialCollegeLondon/FLT](https://github.com/ImperialCollegeLondon/FLT) (Fermat's Last Theorem) | `flt` | Apache-2.0 |
| `pfr` | [teorth/pfr](https://github.com/teorth/pfr) | `pfr` | Apache-2.0 |
| `compfiles` | [dwrensha/compfiles](https://github.com/dwrensha/compfiles) | `compfiles` | Apache-2.0 |
| `mil` | [Mathematics in Lean](https://github.com/leanprover-community/mathematics_in_lean) (tutorial) | `tutorials` | Apache-2.0 |
| `tpil` | [Theorem Proving in Lean 4](https://github.com/leanprover/theorem_proving_in_lean4) (tutorial) | `tutorials` | Apache-2.0 |
| `oai` | [openai/math](https://github.com/openai/math) | `oai` | Apache-2.0 |

Licenses are those of each repository's `LICENSE` file at the pinned commit. Whether every file in a repository carries that license was not checked, except for formal-conjectures, whose README states the extra terms above.

```
lean4-explainer sources [NAME...]              # installed corpora, pinned commits, licenses
lean4-explainer fetch tutorials --yes          # download only
lean4-explainer showcase --yes --out site --site-url https://example.org/base/  # build a public, canonical site
lean4-explainer                                # same as showcase; prints what it will download, asks first
```

Without `--yes`, the commands print the plan and ask. When stdin is not a terminal they download nothing and exit with code 2. Corpus packages do not select or contain L4DEL overlays, so an ordinary showcase remains annotation-free even when the L4DEL tooling is installed. A hosted build may opt in with `--overlay-manifest PATH`; every entry is checked against the corpus repository, exact commit and overlay SHA-256, and its review provenance is shown on the landing page and beside rendered annotations. The local release procedure also audits generated wording against pinned source-controlled comments or notes and publishes the machine-readable result as `annotation-audit.json`; curated wording is enumerated there as `source-linked-unreviewed`, not silently promoted to reviewed. The showcase landing page shows each project's commit, Lean toolchain, `mathlib` commit, and license, and the license text is copied next to each subsite. `--site-url` enables canonical and social metadata, a custom 404 page, `robots.txt`, and chunked sitemaps. Each corpus's build errors are printed (and its first warnings): an overlay or an implication edge that names a declaration the site does not have is an error, and the command then exits with code 1, so a broken site is not a publish candidate. Output must remain below the configured byte budget; the local release smoke check measures the generated artifact rather than relying on an older estimate. The hosted release is compiled and elaborated locally, finalized with machine-readable trust totals, and then published as static files; see `docs/RELEASING.md`.

## Extensions

An extension is an installed package that exposes an `Extension` subclass through the entry-point group `lean4_explainer.extensions`. Every hook is optional: parsing comments, indexing a file, analyzing the whole tree, adding blocks, pages, navigation links and CSS, adding sections to the glossary (`glossary`, with `GlossarySection` and `GlossaryEntry`) and a one-line description of a declaration for it (`describe`), adding command-line commands and config keys. Three hooks connect extensions: `every_declaration = True` gives an extension blocks on declarations it did not parse (the implications extension's edges come from a sidecar file), `review(analysis, analyses)` runs after every extension has analyzed the tree and sees all their results, and `kernel_trust(analysis, name, file, line)` answers what a Lean run said of a declaration. See `src/lean4_explainer/extensions.py`. `lean4-explainer extensions` lists what is installed. The shipped extensions are `lean4-explainer-l4del`, `lean4-explainer-lean`, `lean4-explainer-reader`, `lean4-explainer-map`, `lean4-explainer-implications`, `lean4-explainer-ecosystem` and `lean4-explainer-corpora`.

## Configuration

Pass `--config lean4-explainer.toml` to `build`. Unknown keys and wrong types are errors. Installed extensions can add keys (L4DEL adds `learning_path`).

- `title`: site title.
- `include`: list of glob patterns on paths relative to the lean root. When set, only matching files are listed (`--lake-root` fills this from the lakefile).
- `exclude`: list of glob patterns on paths relative to the lean root. `lakefile.lean` and `lake-packages/` are skipped on top of these, at any depth.
- `source_url`: template for source links, with `{path}`, `{line}`, and `{ref}`. `path` is relative to the lean root, so include `lean/` in the template if the repo layout needs it.
- `source_ref`: value for `{ref}`.
- `source_links`: `"declaration"` (default, one link per declaration) or `"file"` (one per page, for very large trees).
- `search`, `cross_links`: booleans that switch those features on or off.
- `home`: relative URL of a landing page above this site. Adds an "All corpora" link to every page.
- `site_url`: canonical HTTPS base URL, without a query or fragment. Every page gets a canonical URL; navigation, feature, and annotated pages also get Open Graph/Twitter metadata. Unannotated file pages use a compact shell so very large corpora remain deployable.
- `description`: page description used in metadata.
- `project_url`: HTTPS source-project link shown in full page footers.
- `report_url`: HTTPS feedback or issue link shown in full page footers.
- `byte_budget`: the build fails if the output exceeds this many bytes. The default is 1 GB, the GitHub Pages limit.
- `glossary`: which of the project's definitions the glossary lists: `"all"` (default), `"described"` (only those with a doc comment, a plain comment or an extension's note; the showcase uses this for openai/math) or `"none"`.
- `imports`: where file pages list imports: `"all"` (default), `"import-only"` (only on files that do nothing but import; the showcase uses this for openai/math, whose 336,022 imports would not fit) or `"none"`.

## Outputs

- One page per Lean file, named `path/File.lean.html`, and one `index.html` per folder. A file page lists the file's imports, folded: a project file links to its page, a module of Mathlib or a library it depends on (Init, Std, Lean, Batteries, Aesop, Qq, Plausible, ProofWidgets, LeanSearchClient) links to its page in the [Mathlib documentation](https://leanprover-community.github.io/mathlib4_docs/), anything else is named. It also lists the project files that import it. A file that only gathers imports (nothing but `import` lines, `module`, `prelude` and comments, like formal-conjectures' `FormalConjecturesUtil.lean`, which 1,469 problem files import) says so, shows its imports open instead of "No declarations listed", and its folder lists it as "18 imports, no declarations". The documentation links go to the current Mathlib documentation, so a module renamed since a project's pinned Mathlib may be missing there.
- `search.html`. `_assets/search/` holds the search index as plain script files, so search works from `file://` too. Search covers declarations that have a description. Every declaration is still listed on its file page, where browser find works. Indexing all 3.5 million declarations of the full openai/math tree would not fit GitHub Pages' 1 GB limit.
- `glossary.html`, linked from every page. Its sections, with a filter box and a list of contents:
  - **Defined in this project**: every `def`, `abbrev`, `structure`, `class`, `class inductive`, `inductive` and `opaque` (theorems, instances and examples are results, not words), under its own name (the last part of the full name), with the first paragraph of its description, or its declaration line when it has none, and a link to it. Identical copies in several files are one entry. More than 2,000 entries go on one page per first letter, `glossary-a.html` … `glossary-other.html`; up to that, a long list gets letter headings. The entries come from the incremental cache, so a rebuild that reuses every file still lists them all.
  - One section per extension that adds words (the `glossary` hook): L4DEL's `term` lines (the term links in explanations point here), and the reader's types, structures, properties, symbols and tactics.
  - **Lean words**: the language itself (`theorem`, `sorry`, `:=`, `namespace`, `⟨ ⟩`, `·`, …), including all of the README's "Words you will meet".
- Extension pages. L4DEL adds `annotate.html` and `learning-path.html`. The map extension (`packages/map`) adds `map.html`, with the project's folders and any one file with the files around it. The same relationships also appear in a searchable file table and a collapsible text representation, so map navigation does not require the diagram or a pointer device. It gives every declaration a "Map" of what it builds on and what uses it, two steps each way, drawn when opened. Its links are read from the code by Lean's name rules (namespaces, `open`, imports, local names; see `packages/map/README.md`), and L4DEL `prereq` links are added as dashed arrows. Imports are followed through files that only import (from the core's import graph): in formal-conjectures that more than doubled the links, from 6,077 to 12,707. Set `map_dependencies = false` to leave it out.
- Pages that have not changed since the last build are reused. The cache lives beside the output directory, outside the published site, and can be moved with `--cache`. It is loaded through an allow-list of this package's own types and the types extensions declare. A cache file that refers to anything else is ignored and rebuilt, never run.

## Development

The repository holds the core and the extensions as separate packages:

```
pip install -e ".[test]" -e packages/l4del -e packages/lean -e packages/ecosystem -e packages/corpora -e packages/corpus-flt   # and the other corpus-* packages
pytest                      # core, with no extension active
pytest packages/l4del       # L4DEL
pytest packages/lean        # Lean run (real-Lean tests are skipped when `lean` is missing)
pytest packages/ecosystem   # find page, snapshots, Lake facet
pytest packages/corpora     # registry, fetch, showcase
pytest packages/reader      # readings, lean2tex, glossary words (needs node)
pytest packages/map         # dependency map (needs node)
pytest packages/implications  # edge contracts; the kernel check of a bridge runs when `lean` is there
```

Licensed under Apache-2.0. The built-in corpora keep their own licenses, listed above.
