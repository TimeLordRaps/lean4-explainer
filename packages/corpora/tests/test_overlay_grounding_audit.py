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


FALLBACK = "This declaration is an exact comparator-selected statement. Read the Lean statement below for its mathematical content."


def _oai_fixture(tmp_path, overlay_body):
    checkout = tmp_path / "work" / "oai"
    lean = checkout / "lean"
    (lean / "docs").mkdir(parents=True)
    (lean / "ComparatorChallenges").mkdir()
    (lean / "docs" / "note.md").write_text(
        "# Two results\n\n## Scope\n\nCombined scope prose for both results.\n\n## Results\n\n"
        "| Result A | [A](../ComparatorChallenges/A.lean) |\n"
        "| Result B | [B](../ComparatorChallenges/B.lean) |\n"
        "| Result C | [C](../ComparatorChallenges/C.lean) |\n",
        encoding="utf-8",
    )
    (lean / "docs" / "single.md").write_text(
        "# One result\n\n## Scope\n\nScope prose for the single result.\n\n## Results\n\n"
        "| Result D | [D](../ComparatorChallenges/D.lean) |\n",
        encoding="utf-8",
    )
    sources = {
        "A": "theorem thmA : True := trivial\n",
        "B": "/-- Documented statement. -/\ntheorem thmB : True := trivial\n",
        "C": "theorem thmC : True := trivial\n",
        "D": "theorem thmD : True := trivial\n",
    }
    for stem, text in sources.items():
        (lean / "ComparatorChallenges" / f"{stem}.lean").write_text(text, encoding="utf-8")
        (lean / "ComparatorChallenges" / f"{stem}.json").write_text(
            json.dumps({"theorem_names": [f"thm{stem}"]}), encoding="utf-8"
        )
    _git(checkout, "init", "-q")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "fixture")
    commit = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    hosted = tmp_path / "hosted"
    hosted.mkdir()
    overlay = hosted / "oai.l4del"
    overlay.write_text("# overlay\n# BEGIN GENERATED OPENAI/MATH FORMALIZATION-NOTE ANNOTATIONS\n" + overlay_body, encoding="utf-8")
    manifest = hosted / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "overlays": {
                    "oai": {
                        "file": "oai.l4del",
                        "repo": "example/oai",
                        "commit": commit,
                        "sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
                        "provenance": "ai-generated-unreviewed",
                        "sources": [
                            {"label": "Docs", "url": f"https://github.com/example/oai/blob/{commit}/README.md"},
                            {"label": "Paper", "url": "https://arxiv.org/abs/1234.56789v1"},
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _entry(stem, intuition):
    return (
        f"@file ComparatorChallenges/{stem}.lean\n@decl thm{stem}\n"
        f"-- L4DEL: title: Challenge statement: Result {stem}\n-- L4DEL: intuition: {intuition}\n\n"
    )


def test_oai_multi_result_target_without_a_doc_comment_may_carry_the_bounded_fallback(tmp_path):
    manifest = _oai_fixture(tmp_path, _entry("A", FALLBACK))

    _, errors = audit(manifest, tmp_path / "work")

    assert errors == []


def test_oai_fallback_is_rejected_where_the_generator_would_not_emit_it(tmp_path):
    manifest = _oai_fixture(
        tmp_path,
        _entry("B", FALLBACK) + _entry("D", FALLBACK) + _entry("C", "Invented prose about thmC."),
    )

    _, errors = audit(manifest, tmp_path / "work")

    assert len(errors) == 3
    assert all("generated intuition no longer matches its pinned source text" in error for error in errors)
