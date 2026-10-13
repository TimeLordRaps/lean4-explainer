# Hosted L4DEL overlays

These explanatory overlays are inputs to the GitHub Pages showcase, not Python package data. The Pages workflow must
opt into them with `--overlay-manifest hosted/overlays/manifest.json`.

Every manifest entry binds the text to one corpus repository, one exact source commit, and the overlay's SHA-256.
The build fails if any binding drifts. `ai-generated-unreviewed` overlays are visibly labelled as unverified drafts on
the landing page and beside every rendered annotation. Change that provenance only after an identified human has
reviewed the mathematical explanation, and record that identity in `reviewed_by`.

Every rendered overlay annotation links directly to the declaration in the immutable, full-commit GitHub source URL.
The manifest also supplies at least two corpus-level primary references (normally pinned project documentation plus a
paper, blueprint, catalogue, or textbook). Commit-pinned GitHub blobs are used instead of mutable branch links or an
on-demand Wayback snapshot: the URL names the exact bytes the site built, while the manifest hash makes drift fail
closed. These links establish traceability; they do **not** turn an AI-generated explanation into a human review.

The large generated sections copy or condense only material already present in the pinned source: declaration doc
comments, immediately leading source comments, and (for openai/math) formalization notes plus Comparator configs.
They do not infer mathematics from names. Existing curated entries remain separate at the top of each file and win
over generated entries. Source-derived text remains subject to the source corpus's license and attribution terms,
which the showcase displays with the repository and exact commit.

These files are intentionally outside every Python package. The Pages workflow opts into them explicitly; the
release-archive audit rejects `.l4del` files, hosted-overlay paths, and annotation manifests from wheels and sdists.
