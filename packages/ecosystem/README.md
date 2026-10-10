# lean4-explainer-ecosystem

Three ways to connect a [lean4-explainer](https://github.com/TimeLordRaps/lean4-explainer) site to the rest of the Lean world.

```
pip install lean4-explainer[ecosystem]
```

## `explain#Name` links

The site gets `find.html`. `find.html#Foo.bar` jumps to the declaration `Foo.bar`, so a chat link can point at it the way `docs#Foo.bar` points into doc-gen4. For Zulip, an organization administrator adds a linkifier:

- pattern: `explain#(?P<name>[A-Za-z0-9_.'!?]+)`
- URL template: `https://YOUR-SITE/find.html#%(name)s`

The name table has the first `find_limit` names (default 200000, sorted); a larger tree gets a partial table, and a name outside it answers "No declaration named ...".

## Version diffs

Every build writes `snapshot.json`: per declaration, a whitespace-insensitive digest of its statement and of its whole text. Pass a snapshot from an earlier build as `compare_to` and the site also gets `changes.html`: statements changed, proofs changed with the statement the same, declarations added and removed. In CI, fetch the previously deployed `snapshot.json` (for example `curl -fsSL https://YOUR-SITE/snapshot.json -o previous.json`) and set `compare_to = "previous.json"`. A tree with more than `snapshot_limit` declarations (default 100000) gets file-level snapshots, and only whole files are compared. Digests come from text, not from elaborated terms, so a change in a definition that a proof unfolds is not noticed.

## Lake facet

```
lean4-explainer lake-facet            # prints a snippet for lakefile.lean
lake build :explain                   # then writes the site to .lake/build/explain
```

The facet runs the `lean4-explainer` command, which must be on the PATH.

Config keys: `compare_to`, `find_limit`, `snapshot_limit`.
