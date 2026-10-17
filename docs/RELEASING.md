# Publishing the hosted showcase

The public showcase is built with Lean **locally** and published as static files from the `gh-pages` branch. GitHub
Actions runs the test matrix, but it does not fetch, compile, or elaborate the corpora and it does not create trust
claims.

Use an environment with the core, every hosted extension (including `packages/lean`), and every corpus package
installed from this checkout. Keep the work and output directories on a local disk, not a synchronized drive.

```powershell
lean4-explainer showcase --yes `
  --out E:\lean4-explainer-work\site `
  --work E:\lean4-explainer-work\work `
  --jobs 4 `
  --site-url https://timelordraps.github.io/lean4-explainer/ `
  --overlay-manifest hosted/overlays/manifest.json

python scripts/audit_hosted_overlay_grounding.py `
  --manifest hosted/overlays/manifest.json `
  --work E:\lean4-explainer-work\work `
  --report E:\lean4-explainer-work\site\annotation-audit.json

python scripts/audit_manuscript_sources.py `
  --checkout alphaproof-nexus=PATH_TO_PINNED_ALPHAPROOF_NEXUS_CHECKOUT `
  --checkout oai=PATH_TO_PINNED_OPENAI_MATH_CHECKOUT

python scripts/finalize_local_site.py `
  --site E:\lean4-explainer-work\site `
  --repository-sha (git rev-parse HEAD)

python scripts/check_static_site.py `
  --site E:\lean4-explainer-work\site `
  --site-url https://timelordraps.github.io/lean4-explainer/
```

`finalize_local_site.py` fails unless every corpus has a local `trust.json`, the records name an exact Lean toolchain,
and at least one declaration was actually checked. `check_static_site.py` independently recomputes the totals and
rejects source-only wording, missing trust records, or a mismatched release manifest.

`audit_manuscript_sources.py` is also a release gate: it fails on a checkout-commit mismatch, changed PDF bytes,
an excerpt not found on the recorded page, or a source/quotation no longer attached to its recorded declaration.

Only after both checks pass should the exact output tree replace `gh-pages`. The branch is generated release output;
do not merge it into `main`, do not build it on GitHub runners, and do not publish a partially updated tree.
