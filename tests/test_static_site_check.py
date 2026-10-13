from pathlib import Path
import json

from scripts.check_static_site import check_site


PUBLIC = "https://example.org/proofs/"


def _page(title: str, canonical: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta name="description" content="description"><meta property="og:title" content="{title}">
<meta property="og:description" content="description"><meta name="twitter:card" content="summary">
<link rel="canonical" href="{canonical}"></head><body>
<a class="skip-link" href="#content">Skip to content</a><main id="content">{body}</main></body></html>"""


def _site(root: Path) -> None:
    (root / "_assets").mkdir(parents=True)
    (root / "_assets" / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (root / "demo").mkdir()
    (root / "index.html").write_text(
        _page("Home", PUBLIC, '<h1>Start exploring</h1><p>Lean4 Domain Explanation Language (L4DEL)</p><h2>All corpora</h2><a href="demo/index.html">Demo</a><a href="https://example.org/issues">Report a site issue</a>'),
        encoding="utf-8",
    )
    (root / "demo" / "index.html").write_text(
        _page("Demo", PUBLIC + "demo/index.html", '<a href="../index.html">All corpora</a>'), encoding="utf-8"
    )
    (root / "404.html").write_text(
        '<!doctype html><html><body><main><a href="/proofs/">Return to all corpora</a></main></body></html>', encoding="utf-8"
    )
    (root / "sitemap-1.xml").write_text(
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{PUBLIC}index.html</loc></url><url><loc>{PUBLIC}demo/index.html</loc></url></urlset>",
        encoding="utf-8",
    )
    (root / "sitemap.xml").write_text(
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{PUBLIC}sitemap-1.xml</loc></sitemap></sitemapindex>",
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
