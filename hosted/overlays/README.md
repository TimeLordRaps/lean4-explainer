# Hosted L4DEL overlays

These explanatory overlays are inputs to the GitHub Pages showcase, not Python package data. The Pages workflow must
opt into them with `--overlay-manifest hosted/overlays/manifest.json`.

Every manifest entry binds the text to one corpus repository, one exact source commit, and the overlay's SHA-256.
The build fails if any binding drifts. Mixed `ai-generated-unreviewed` overlays and wholly
`source-derived-unreviewed` overlays are visibly labelled on the landing page and beside every rendered annotation.
Change an unreviewed provenance only after an identified human has reviewed the mathematical explanation, and record
that identity in `reviewed_by`.

Every rendered overlay annotation links directly to the declaration in the immutable, full-commit GitHub source URL.
The manifest also supplies at least two corpus-level primary references (normally pinned project documentation plus a
paper, blueprint, catalogue, or textbook). Commit-pinned GitHub blobs are used instead of mutable branch links or an
on-demand Wayback snapshot: the URL names the exact bytes the site built, while the manifest hash makes drift fail
closed. These links establish traceability; they do **not** turn a generated explanation into a human review.

The large generated sections copy or condense only material already present in the pinned source: declaration doc
comments, immediately leading source comments, and (for openai/math) formalization notes plus Comparator configs.
They do not infer mathematics from names. Existing curated entries remain separate at the top of each file and win
over generated entries. Source-derived text remains subject to the source corpus's license and attribution terms,
which the showcase displays with the repository and exact commit.

Manuscript-grounded curated entries add declaration-specific explanation without hiding their evidence chain. Each
quotation names a displayed source; `manuscript-sources.json` additionally binds every pinned-repository PDF citation
to the corpus, commit, repository-relative path, PDF SHA-256, page, exact excerpt, and Lean declaration. Before release,
`scripts/audit_manuscript_sources.py` checks the checkout commit and PDF bytes, extracts the cited page with
`pdftotext`, and confirms that the exact excerpt and source URL are still attached to the intended L4DEL target.
External historical sources remain direct, page-labelled links on the annotation; they are not misrepresented as
repository-owned manuscripts.

Retained generation history is deliberately narrower than a general model credit. The 71 original curated entries
were produced in a Claude Sonnet 5.5 session at medium effort; that session records Claude Opus 5.5 as an advisor,
not the direct author. The bulk source-derived expansion was generated mechanically by tooling developed in a
GPT-5.6 Sol session at ultra reasoning. The upstream authors supplied the source comments and mathematics, so that layer
is not represented as GPT-authored prose. The later manuscript-grounded entries record their own session-level history
in the manifest. Where the runtime did not expose an exact model identifier to the artifact generator, the manifest says
so instead of inferring one.

These files are intentionally outside every Python package. The Pages workflow opts into them explicitly; the
release-archive audit rejects `.l4del` files, hosted-overlay paths, and annotation manifests from wheels and sdists.
