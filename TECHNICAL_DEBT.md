# Technical debt

Known problems that are written down instead of fixed, with what was seen and when to look again. Close an entry by fixing it with a test, and say which commit did.

| ID | Where | What | Evidence | Status | Revisit |
|---|---|---|---|---|---|
| TD-1 | `src/lean4_explainer/scan.py` (declaration names) | A name with a quoted part that contains a space is cut at the space: `def Foo.«bar baz»` is indexed as `Foo.«bar`. Links to it, and the map, then miss it. | Seen on a two-line fixture, 2026-10-10. Quoted names with spaces are rare in the pinned corpora; not counted. | CONFIRMED | The next change to how the scanner reads names. |
| TD-2 | `packages/map` and the core | The map reads a file's imports from the code it is given per declaration, so a project file with no declarations is not followed through: a file that imports only through it does not see what it imports. | Counted on the pinned corpora, 2026-10-10: 8 such files with 9 importers (MIL solution files, FLT test files). | CONFIRMED, small | If extensions get a per-file hook from the core. |
| TD-3 | `packages/map` and `src/lean4_explainer/scan.py` | Imports are parsed twice: the core's `LeanFile.imports` (nothing uses it yet) and `deps.imports_in` in the map. The two must keep agreeing. | Both handle the module system's `public`/`meta`/`all` forms and several modules per line, each with its own test. | CONFIRMED, small | When the core passes `imports` to extensions. |
| TD-4 | `packages/corpus-oai` | The map is switched off for openai/math. Its per-page data adds about 10% to a site (measured on FLT: 0.67 MB on 6.8 MB), and that site is already about 900 MB of GitHub Pages' 1 GB. | `map_dependencies = false` in the corpus options; covered by a test. | DEFERRED | If the map data moves out of the pages into files loaded on demand, or the oai pages shrink. |
