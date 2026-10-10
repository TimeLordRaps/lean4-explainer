# lean4-explainer

Builds a static HTML proofsite from a Lean 4 source tree. It reads `.lean` files as text and lists declarations, doc comments, L4DEL notes, and statement snippets. It never runs Lean, so axiom and trust checks are UNKNOWN.

**Jump to:** [Write your own explanations with L4DEL](#start-here-lean4-explainer-and-l4del-go-together) | [Try it on 8 Lean projects](#built-in-corpora-and-extras) | [Use it on your Lake project](#lake-projects) | [Usage](#usage)

The default site, built by `lean4-explainer` with no annotation at all, is published from this repository's GitHub Pages once Pages is enabled for it (Settings, Pages, Source: GitHub Actions).

## Start here: lean4-explainer and L4DEL go together

lean4-explainer reads L4DEL, the explanation metadata that Lean authors write as line comments. L4DEL is optional at first, but the tool is built around it. Whenever a declaration has no valid L4DEL, lean4-explainer says what is missing and prints a template to paste in.

The workflow for a human or an agent:

1. **Check** the tree with `lean4-explainer check --lean-root lean`. Errors go to stderr and the command exits with code 1. Warnings are listed.
2. **Annotate** one file with `lean4-explainer annotate --lean-root lean --file Demo/Basics.lean`. Each declaration without a valid annotation gets a template. Templates are printed, never written into your files.
3. **Paste** a template directly above its declaration, then replace every `TODO_` value.
4. **Build** with `lean4-explainer build --lean-root lean --out docs`. A `TODO_` left in a value is a warning, so the build reports it.

The generated site has an L4DEL guide page (`annotate.html`) with the same workflow and a worked example.

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
- Same-named declarations: identical copies are one object, so a plain name refers to it. A name with distinct definitions is ambiguous: a plain reference is an error, and it must be written `Name@path`, for example `Demo.value@Var/B.lean`.
- Values are trimmed, must not be empty, and are at most 2000 characters.
- The complete grammar is in the module docstring of `lean4_explainer/l4del.py`.

### Placeholders

Templates use `TODO_` placeholders. They are valid syntax, so a pasted template parses, and every `TODO_` left in a value is reported as a warning until it is replaced. The tool never writes into your source files.

## Usage

```
pip install lean4-explainer
lean4-explainer build --lean-root lean --out docs
lean4-explainer build --lake-root . --out docs   # a Lake project: only the libraries named in the lakefile
```

This writes `docs/index.html`, one page per Lean file (`docs/Foo/Bar.lean.html`), one `index.html` per folder, and shared assets in `docs/_assets/`. Pages make no network requests.

## What is listed

- Declarations at column 0: `theorem`, `lemma`, `def`, `abbrev`, `structure`, `class`, `inductive`, `instance`, `axiom`, `opaque`, `example`.
- Qualified names from `namespace` and `section` blocks.
- A `/-- ... -/` doc comment directly above a declaration. If there is none, a plain `--` or `/- ... -/` comment directly above it (no blank line between) is used as its description.
- Optional L4DEL notes: a `-- L4DEL: key: value` line comment directly above a declaration. Several directives may stack. A project that writes none gets the same output without any L4DEL markup.
- Statement snippets only for declarations that have a description or an L4DEL note. This keeps full-tree output small.
- The first `/-! ... -/` module doc in each file.
- Whether a declaration's text contains the word `sorry`.

## Built-in corpora and extras

lean4-explainer knows eight Lean projects, each pinned to a commit, so you can see what it produces and link your own theorems to them:

| Name | Project | Extra |
|---|---|---|
| `formal-conjectures` | [google-deepmind/formal-conjectures](https://github.com/google-deepmind/formal-conjectures) | `conjectures` |
| `carleson` | [fpvandoorn/carleson](https://github.com/fpvandoorn/carleson) | `carleson` |
| `flt` | [ImperialCollegeLondon/FLT](https://github.com/ImperialCollegeLondon/FLT) (Fermat's Last Theorem) | `lft` or `flt` |
| `pfr` | [teorth/pfr](https://github.com/teorth/pfr) | `pfr` |
| `compfiles` | [dwrensha/compfiles](https://github.com/dwrensha/compfiles) | `compfiles` |
| `mil` | [Mathematics in Lean](https://github.com/leanprover-community/mathematics_in_lean) (tutorial) | `tutorials` |
| `tpil` | [Theorem Proving in Lean 4](https://github.com/leanprover/theorem_proving_in_lean4) (tutorial) | `tutorials` |
| `oai` | [openai/math](https://github.com/openai/math) | `oai` |

`pip install lean4-explainer[all]` names all eight, `[tutorials]` the two tutorials, `[conjectures]` the conjectures project. The extras add no Python packages (PyPI does not allow extras that point at git repositories, and the sources are large). They are accepted names. The registry is part of the base package, and the sources are cloned on request, one shallow fetch of the pinned commit each:

```
lean4-explainer sources [NAME...]              # list names, repositories and pinned commits
lean4-explainer fetch tutorials --yes          # download only
lean4-explainer showcase --yes --out site      # download all and build one subsite each under a landing page
lean4-explainer                                # same as showcase; prints what it will download, asks first
```

Without `--yes`, the commands print the plan and ask. When stdin is not a terminal they download nothing and exit with code 2. Each corpus is built from the libraries its `lakefile.toml` names, with its pinned toolchain and `mathlib` commit shown on the landing page. Output is one folder per corpus, about 880 MB for all eight, mostly openai/math.

## Lake projects

Lean and Lake do not need to be installed. The explainer reads text and starts no processes.

- `--lake-root DIR` reads `lakefile.toml` (or best-effort, `lakefile.lean`) and lists only the files of the libraries it declares. A library `A` takes `A.lean` and the folder `A/`, explicit `roots` replace that default, `A.*` and `A.+` globs take the folder, and a plain glob takes one module. `srcDir` is honored. This is a rule on file names, not Lake's import resolution: a file in a library folder is listed even if nothing imports it.
- It also reads `lean-toolchain`, the `rev` of each `require`, and the commits in `lake-manifest.json`, and shows the toolchain and `mathlib` commit on the showcase landing page.
- `--lean-root DIR` lists every `.lean` file under `DIR`. Either way it skips `lakefile.lean` at any depth, `lake-packages/` (Lake's older dependency directory), and hidden directories such as `.lake/`.
- A library that is a test or example folder (for example `FLTTest`) is listed if the lakefile declares it. Add its name to `exclude`.

### Tactic traces

Tactic traces (the goal state after each tactic) are not in a lakefile. They come from elaborating the proof, which needs Lean and the project's dependencies built. lean4-explainer does not do that today, so the pages show the written proof text and the L4DEL `step` lines only. Traces are not implemented.

## Limits

- This is a text heuristic. Indented declarations, macro-generated declarations, and names created by `notation` or `syntax` are not listed.
- `sorry` detection is textual. It does not follow dependencies and does not check axioms.
- Lean is not run, so axiom and trust checks are UNKNOWN.

## Configuration

Pass `--config lean4-explainer.toml` to `build`. Unknown keys and wrong types are errors.

- `title`: site title.
- `include`: list of glob patterns on paths relative to the lean root. When set, only matching files are listed (`--lake-root` fills this from the lakefile).
- `exclude`: list of glob patterns on paths relative to the lean root. `lakefile.lean` and `lake-packages/` are skipped on top of these, at any depth.
- `source_url`: template for source links, with `{path}`, `{line}`, and `{ref}`. `path` is relative to the lean root, so include `lean/` in the template if the repo layout needs it.
- `source_ref`: value for `{ref}`.
- `search`, `cross_links`, `learning_path`: booleans that switch those features on or off.
- `home`: relative URL of a landing page above this site. Adds an "All corpora" link to every page.
- `byte_budget`: the build fails if the output exceeds this many bytes. The default is 1 GB, the GitHub Pages limit.

## Outputs

- One page per Lean file, named `path/File.lean.html`, and one `index.html` per folder.
- `glossary.html`, `search.html`, and `learning-path.html`.
- `_assets/search/` holds the search index as plain script files, so search works from `file://` too. Search covers declarations that have a description or an L4DEL note. Every declaration is still listed on its file page, where browser find works. Indexing all 3.5 million declarations of the full openai/math tree would not fit GitHub Pages' 1 GB limit.
- Pages that have not changed since the last build are reused. The cache lives beside the output directory, outside the published site, and can be moved with `--cache`. It is loaded through an allow-list of this package's own types. A cache file that refers to anything else is ignored and rebuilt, never run.

## Development

```
pip install -e ".[test]"
pytest
```
