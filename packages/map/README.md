# lean4-explainer-map

A map of how a Lean project builds on itself, for [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer).

- **Every declaration** gets a "Map" on its file page. It is a small diagram:
  - in the middle, the declaration;
  - on the left, what it uses, two steps back;
  - on the right, what uses it, two steps on.

  Each box links to that declaration. When there are many neighbours, the most-used ones are drawn and the counts say how many there are in all.
- **`map.html`** shows the whole project in two views:
  - folders, with an arrow wherever something in one folder is used in another;
  - one file with the files around it. Type any file name to move the centre.

The links are read from the code, not from annotations. A declaration uses another when a name in its text resolves to a declaration of the same project, the way Lean looks names up:

1. the name itself;
2. the name inside each enclosing `namespace`;
3. the name inside each namespace opened with `open` above it.

Names in comments and strings never count. Names from libraries such as Mathlib do not resolve, so the map shows the project's own structure.

Lean is not run, so two kinds of use are missed:

- a project name reached as a field of a value (`P.freyCurve` with `P : FreyPackage`), which needs the type of `P`;
- names that macros build.

If the [L4DEL](../l4del) extension is also installed, its `prereq:` notes are drawn as dashed arrows ("read this first").

## How it is drawn

The diagrams are drawn in the browser by `map.js` (no libraries), using a layered layout of the kind Sugiyama introduced:

1. Cycles are broken by turning arrows round.
2. Each box gets a column, so every arrow points right.
3. An arrow that skips columns runs between the boxes of the columns it crosses.
4. Boxes in a column are ordered to cross as few arrows as possible.

Arrows run straight across a column and curve only in the gaps between columns, so an arrow never passes through a box. The colours are the site's own theme colours (`--accent`, `--line`, `--fg`, `--muted`), so each corpus's map matches its pages.

A file page carries only its own declarations' neighbourhoods, as a small JSON block. A diagram is drawn when its "Map" is opened.

## Options

| Option | Default | Effect |
| --- | --- | --- |
| `map_dependencies` | `true` | Set to `false` to leave the map out. The pages, the script and `map.html` are then not written at all. |

Set it in the file passed with `--config` (for example `map_dependencies = false` in `lean4-explainer.toml`).

## Install

```
pip install -e packages/map
```

The extension is found through the `lean4_explainer.extensions` entry point and is used by every build once installed.
