from pathlib import Path
import gzip
import json

from scripts.check_static_site import check_site


PUBLIC = "https://example.org/proofs/"


def _page(title: str, canonical: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta name="description" content="description"><meta property="og:title" content="{title}">
<meta property="og:description" content="description"><meta property="og:site_name" content="lean4-explainer"><meta name="twitter:card" content="summary">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebSite"}}</script>
<link rel="canonical" href="{canonical}"></head><body>
<a class="skip-link" href="#content">Skip to content</a><main id="content">{body}</main></body></html>"""


def _site(root: Path) -> None:
    (root / "_assets").mkdir(parents=True)
    (root / "_assets" / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (root / "demo").mkdir()
    (root / "index.html").write_text(
        _page("Home", PUBLIC, '<h1>Start exploring</h1><p>Lean4 Domain Explanation Language (L4DEL)</p><p>Lean-backed trust results produced locally.</p><h2>OpenAI/math and AlphaProof Nexus explanations</h2><h2>All corpora</h2><a href="demo/index.html">Demo</a><a href="https://example.org/issues">Report a site issue</a>'),
        encoding="utf-8",
    )
    (root / "demo" / "index.html").write_text(
        _page("Demo", PUBLIC + "demo/index.html", '<a href="../index.html">All corpora</a>'), encoding="utf-8"
    )
    (root / "demo" / "trust.html").write_text(
        _page("Trust", PUBLIC + "demo/trust.html", '<a href="index.html">Demo</a>'), encoding="utf-8"
    )
    (root / "demo" / "trust.json").write_text(
        json.dumps(
            {
                "format": 1,
                "provenance": "local-lean-run",
                "toolchain": "Lean (version 4.34.1, test)",
                "probe_sha256_16": "a" * 16,
                "files": {"ok": 1, "failed": 0, "unavailable": 0},
                "declarations": {"total": 1, "kernel_checked": 1, "classified": 1, "no axioms": 1, "standard axioms": 0, "sorry": 0, "extra axioms": 0, "unknown": 0},
                "execution": {"elaborated_now": 1, "reused_content_bound_cache": 0},
            }
        ),
        encoding="utf-8",
    )
    (root / "build-info.json").write_text(
        json.dumps(
            {
                "format": 1,
                "repository_sha": "b" * 40,
                "built_at": "2026-10-13T00:00:00Z",
                "build_mode": "local-lean",
                "trust": {"corpora": ["demo"], "kernel_checked_declarations": 1, "ok_files": 1, "unknown_files": 0},
            }
        ),
        encoding="utf-8",
    )
    (root / "404.html").write_text(
        '<!doctype html><html><body><main><a href="/proofs/">Return to all corpora</a></main></body></html>', encoding="utf-8"
    )
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{PUBLIC}index.html</loc></url><url><loc>{PUBLIC}demo/index.html</loc></url>"
        f"<url><loc>{PUBLIC}demo/trust.html</loc></url></urlset>"
    )
    (root / "sitemap-1.xml.gz").write_bytes(gzip.compress(sitemap.encode("utf-8"), mtime=0))
    (root / "sitemap.xml").write_text(
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{PUBLIC}sitemap-1.xml.gz</loc></sitemap></sitemapindex>",
        encoding="utf-8",
    )
    (root / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {PUBLIC}sitemap.xml\n", encoding="utf-8")


def test_static_site_gate_accepts_the_release_contract(tmp_path):
    _site(tmp_path)

    assert check_site(tmp_path, PUBLIC) == []


def test_static_site_gate_reports_a_broken_sampled_link(tmp_path):
    _site(tmp_path)
    path = tmp_path / "demo" / "index.html"
    path.write_text(path.read_text(encoding="utf-8").replace("../index.html", "missing.html"), encoding="utf-8")

    assert any("broken local link missing.html" in error for error in check_site(tmp_path, PUBLIC))


def test_static_site_gate_rejects_a_global_source_only_disclaimer(tmp_path):
    _site(tmp_path)
    landing = tmp_path / "index.html"
    landing.write_text(
        landing.read_text(encoding="utf-8").replace(
            "<h2>All corpora</h2>",
            "<p>Built from the source text only. Lean was not run, so axiom and trust checks are UNKNOWN.</p><h2>All corpora</h2>",
        ),
        encoding="utf-8",
    )

    assert any("source-only release" in error for error in check_site(tmp_path, PUBLIC))


def test_static_site_gate_rejects_a_false_reader_disclaimer(tmp_path):
    _site(tmp_path)
    assets = tmp_path / "demo" / "_assets"
    assets.mkdir()
    (assets / "reader.js").write_text('note.textContent = "Lean was not run";', encoding="utf-8")

    assert any("falsely says Lean was not run" in error for error in check_site(tmp_path, PUBLIC))


def test_static_site_gate_rejects_an_unexpanded_l4del_acronym(tmp_path):
    _site(tmp_path)
    page = tmp_path / "demo" / "index.html"
    page.write_text(page.read_text(encoding="utf-8").replace("All corpora", "L4DEL"), encoding="utf-8")

    assert any("uses L4DEL without expanding" in error for error in check_site(tmp_path, PUBLIC))


def test_static_site_gate_requires_local_lean_evidence_for_every_corpus(tmp_path):
    _site(tmp_path)
    (tmp_path / "demo" / "trust.json").unlink()

    assert any("missing local Lean trust record" in error for error in check_site(tmp_path, PUBLIC))


def test_static_site_gate_requires_a_valid_linked_annotation_audit(tmp_path):
    _site(tmp_path)
    landing = tmp_path / "index.html"
    landing.write_text(
        landing.read_text(encoding="utf-8").replace(
            "</main>", '<a href="annotation-audit.json">Annotation audit</a></main>'
        ),
        encoding="utf-8",
    )

    assert any("annotation audit is missing" in error for error in check_site(tmp_path, PUBLIC))

    (tmp_path / "annotation-audit.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "totals": {"curated_source_linked_unreviewed": 1},
                "curated_entries": [
                    {
                        "review_state": "source-linked-unreviewed",
                        "exact_source_url": "https://github.com/acme/demo/blob/" + "a" * 40 + "/A.lean#L1",
                        "source_statement_sha256": "b" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert check_site(tmp_path, PUBLIC) == []
