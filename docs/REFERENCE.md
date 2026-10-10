# lean4-explainer reference

The complete, detailed manual. For a gentle introduction start with the [README](../README.md).

Builds a static HTML proofsite from a Lean 4 source tree, so you can show your theorems to people who have not read the source. It reads `.lean` files as text and lists declarations, doc comments, plain comments, and statement snippets. It never runs Lean, so axiom and trust checks are UNKNOWN.

The core is small and needs nothing else. Everything that adds weight is an extension you opt into with a pip extra:

| You want | Install | What you get |
|---|---|---|
| A quick explanation page of your Lean code | `pip install lean4-explainer` | The site, from declarations and standard Lean comments |
| To write richer explanations in comments | `pip install lean4-explainer[l4del]` | **[L4DEL](#l4del-write-your-own-explanations)**: titles, intuition, proof steps, prerequisites, glossary, learning path, `check` and `annotate` |
| Tactic traces and kernel trust badges | `pip install lean4-explainer[lean]` | **[Lean run](#lean-run-tactic-traces-and-trust-badges)**: goals before and after each tactic, and the axioms each declaration depends on. Needs `lean` on the PATH |
| `explain#Name` chat links, version diffs, a Lake facet | `pip install lean4-explainer[ecosystem]` | **[Ecosystem](#ecosystem-links-diffs-and-a-lake-facet)** |
| To see it on well-known Lean projects | `pip install lean4-explainer[all]` | Pinned descriptions of 8 projects, plus `sources`, `fetch` and `showcase` |

**Jump to:** [L4DEL: write your own explanations](#l4del-write-your-own-explanations) | [Quick start](#quick-start) | [Lake projects](#lake-projects) | [Built-in corpora](#built-in-corpora-and-extras) | [Extensions](#extensions) | [Configuration](#configuration)

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
- Whether a declaration's text contains the word `sorry`.
- Same-named declarations: identical copies are one object; distinct definitions are listed with their files.

### Limits

- This is a text heuristic. Indented declarations, macro-generated declarations, and names created by `notation` or `syntax` are not listed.
- `sorry` detection is textual. It does not follow dependencies and does not check axioms.
- Without the Lean extension, Lean is not run, so axiom and trust checks are UNKNOWN.

## L4DEL: write your own explanations

L4DEL is an optional extension. It reads `-- L4DEL: key: value` line comments and adds an explanation layer to the site. The core never needs it, and a project that writes none gets the same output as without it.

```
pip install lean4-explainer[l4del]
```

Whenever a declaration has no valid L4DEL, the tool says what is missing and prints a template to paste in. The workflow for a human or an agent:

1. **Check** the tree with `lean4-explainer check --lean-root lean`. Errors go to stderr and the command exits with code 1. Warnings are listed.
2. **Annotate** one file with `lean4-explainer annotate --lean-root lean --file Demo/Basics.lean`. Each declaration without a valid annotation gets a template. Templates are printed, never written into your files.
3. **Paste** a template directly above its declaration, then replace every `TODO_` value.
4. **Build** with `lean4-explainer build --lean-root lean --out docs`. A `TODO_` left in a value is a warning, so the build reports it.

The generated site gets an L4DEL guide page (`annotate.html`), a glossary, and a learning path ordered by prerequisites.

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

Rules:

- Only line comments carry directives. `L4DEL:` in a block, doc, or module comment is an error.
- Keys are case-sensitive. Any other key is an error.
- A directive attaches to the next declaration. Only blank lines, comments, attribute lines, and `set_option` lines may separate them. Other code makes a directive an orphan, which is an error.
- Anonymous declarations (`example`, unnamed `instance`) cannot carry directives.
- `prereq` and `see` names are exact. `foo` does not match `Demo.foo`. A name that matches nothing is a warning.
- A name with distinct definitions is ambiguous: a plain reference is an error, and it must be written `Name@path`, for example `Demo.value@Var/B.lean`.
- Values are trimmed, must not be empty, and are at most 2000 characters.
- The complete grammar is in `packages/l4del/src/lean4_explainer_l4del/grammar.py`.
- Without the extension installed, `-- L4DEL:` lines are ordinary comments.

`TODO_` placeholders are valid syntax, so a pasted template parses, and every `TODO_` left in a value is a warning until it is replaced. The tool never writes into your source files.

## Lean run: tactic traces and trust badges

`pip install lean4-explainer[lean]` adds an extension that elaborates each file with Lean (`lean` on the PATH; inside a Lake project it runs through `lake env`, so build the dependencies first). Every declaration then gets:

- a **trust badge** from the kernel: no axioms, standard axioms (`propext`, `Classical.choice`, `Quot.sound`), extra axioms (named), or `sorry`. This is `collectAxioms`, not a text search.
- a collapsible **tactic trace**: the goals before and after each tactic step.
- a **Trust** page listing declarations that depend on `sorry` or on extra axioms.

A file that does not elaborate shows trust UNKNOWN with Lean's reason, and a file where Lean reported errors says so on every badge. Nothing is guessed. Results are cached by file content, Lean version and `lake-manifest.json`. A Lake project that pins a Lean version you do not have makes elan download that toolchain on the first run. Each badge also lists the constants the statement and the proof use, with instances, coercions and auxiliary definitions counted but left out. This filtering is the expression-tree compression: it is a filter on the set of constants, not a compressed term. See `packages/lean/README.md` for the config keys.

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

`pip install lean4-explainer[all]` adds eight Lean projects, each pinned to a commit, so you can see what the tool produces and link your own theorems to them. Each is its own small package (`lean4-explainer-<name>`) holding the pinned description, license, and license notes. The sources are fetched from GitHub on request, never bundled.

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
lean4-explainer showcase --yes --out site      # download and build one subsite each under a landing page
lean4-explainer                                # same as showcase; prints what it will download, asks first
```

Without `--yes`, the commands print the plan and ask. When stdin is not a terminal they download nothing and exit with code 2. The showcase landing page shows each project's commit, Lean toolchain, `mathlib` commit, and license, and the license text is copied next to each subsite. Output is about 880 MB for all eight, mostly openai/math (which gets one source link per file instead of one per declaration to stay under the 1 GB Pages limit).

## Extensions

An extension is an installed package that exposes an `Extension` subclass through the entry-point group `lean4_explainer.extensions`. Every hook is optional: parsing comments, indexing a file, analyzing the whole tree, adding blocks, pages, navigation links and CSS, adding command-line commands and config keys. See `src/lean4_explainer/extensions.py`. `lean4-explainer extensions` lists what is installed. The shipped extensions are `lean4-explainer-l4del`, `lean4-explainer-lean`, `lean4-explainer-ecosystem` and `lean4-explainer-corpora`.

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
- `byte_budget`: the build fails if the output exceeds this many bytes. The default is 1 GB, the GitHub Pages limit.

## Outputs

- One page per Lean file, named `path/File.lean.html`, and one `index.html` per folder.
- `search.html`. `_assets/search/` holds the search index as plain script files, so search works from `file://` too. Search covers declarations that have a description. Every declaration is still listed on its file page, where browser find works. Indexing all 3.5 million declarations of the full openai/math tree would not fit GitHub Pages' 1 GB limit.
- Extension pages (L4DEL adds `glossary.html`, `annotate.html`, `learning-path.html` and `map.html`). Every declaration that has a `prereq` or `see` link also gets a small SVG map of its neighbours: what it builds on at the left, what builds on it at the right, related ones dashed below. `map.html` draws the whole project the same way, foundations at the left, up to 120 declarations (largest connected groups first).
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
```

Licensed under Apache-2.0. The built-in corpora keep their own licenses, listed above.
