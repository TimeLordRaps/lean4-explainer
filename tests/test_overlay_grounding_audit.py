import hashlib
import json
import subprocess

from scripts.audit_hosted_overlay_grounding import _stable_reference, audit


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def test_grounding_references_are_immutable_coordinates():
    commit = "a" * 40
    assert _stable_reference(f"https://github.com/acme/demo/blob/{commit}/README.md")
    assert _stable_reference("https://arxiv.org/abs/1234.56789v2")
    assert _stable_reference("https://doi.org/10.1000/example")
    assert _stable_reference("https://web.archive.org/web/20260102030405/https://example.org/page")
    assert not _stable_reference("https://github.com/acme/demo/blob/main/README.md")
    assert not _stable_reference("https://arxiv.org/abs/1234.56789")


def test_grounding_audit_matches_generated_wording_to_the_pinned_source(tmp_path):
    checkout = tmp_path / "work" / "demo"
    checkout.mkdir(parents=True)
    (checkout / "A.lean").write_text("/-- A true fact. -/\ntheorem fact : True := trivial\n", encoding="utf-8")
    _git(checkout, "init", "-q")
    _git(checkout, "add", "A.lean")
    _git(checkout, "commit", "-qm", "fixture")
    commit = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    hosted = tmp_path / "hosted"
    hosted.mkdir()
    overlay = hosted / "demo.l4del"
    overlay.write_text(
        "# overlay\n# BEGIN GENERATED SOURCE-COMMENT ANNOTATIONS\n"
        "@file A.lean\n@decl fact\n-- L4DEL: title: A true fact\n-- L4DEL: intuition: A true fact.\n",
        encoding="utf-8",
    )
    manifest = hosted / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "overlays": {
                    "demo": {
                        "file": "demo.l4del",
                        "repo": "example/demo",
                        "commit": commit,
                        "sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
                        "provenance": "ai-generated-unreviewed",
                        "sources": [
                            {
                                "label": "Docs",
                                "url": f"https://github.com/example/demo/blob/{commit}/README.md",
                            },
                            {"label": "Paper", "url": "https://arxiv.org/abs/1234.56789v1"},
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report, errors = audit(manifest, tmp_path / "work")

    assert errors == []
    assert report["status"] == "PASS"
    assert report["totals"] == {
        "annotations": 1,
        "generated_source_matched": 1,
        "curated_source_linked_unreviewed": 0,
    }
    assert report["curated_entries"] == []


def test_grounding_audit_lists_curated_wording_with_an_exact_source_link(tmp_path):
    checkout = tmp_path / "work" / "demo"
    checkout.mkdir(parents=True)
    (checkout / "A file.lean").write_text("\ntheorem fact : True := trivial\n", encoding="utf-8")
    _git(checkout, "init", "-q")
    _git(checkout, "add", "A file.lean")
    _git(checkout, "commit", "-qm", "fixture")
    commit = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    hosted = tmp_path / "hosted"
    hosted.mkdir()
    overlay = hosted / "demo.l4del"
    overlay.write_text(
        "# curated\n@file A file.lean\n@decl fact\n"
        "-- L4DEL: title: A fact\n-- L4DEL: intuition: This remains explicitly unreviewed.\n"
        "# BEGIN GENERATED SOURCE-COMMENT ANNOTATIONS\n",
        encoding="utf-8",
    )
    manifest = hosted / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "overlays": {
                    "demo": {
                        "file": "demo.l4del",
                        "repo": "example/demo",
                        "commit": commit,
                        "sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
                        "provenance": "ai-generated-unreviewed",
                        "sources": [
                            {
                                "label": "Docs",
                                "url": f"https://github.com/example/demo/blob/{commit}/README.md",
                            },
                            {"label": "Paper", "url": "https://arxiv.org/abs/1234.56789v1"},
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report, errors = audit(manifest, tmp_path / "work")

    assert errors == []
    assert report["curated_entries"] == [
        {
            "corpus": "demo",
            "file": "A file.lean",
            "declaration": "fact",
            "line": 2,
            "title": "A fact",
            "intuition": "This remains explicitly unreviewed.",
            "source_statement": "theorem fact : True := trivial",
            "source_statement_sha256": hashlib.sha256(b"theorem fact : True := trivial").hexdigest(),
            "review_state": "source-linked-unreviewed",
            "exact_source_url": f"https://github.com/example/demo/blob/{commit}/A%20file.lean#L2",
            "corpus_references": [
                {"label": "Docs", "url": f"https://github.com/example/demo/blob/{commit}/README.md"},
                {"label": "Paper", "url": "https://arxiv.org/abs/1234.56789v1"},
            ],
        }
    ]
