import json

from lean4_explainer_corpora.registry import Corpus
from scripts import generate_oai_hosted_overlay as generator


def test_declaration_inventory_is_an_index_not_doc_comment_authority(monkeypatch, tmp_path):
    corpus = Corpus(
        name="oai",
        title="OpenAI math",
        repo="openai/math",
        commit="a" * 40,
        branch="main",
        kind="oai",
        blurb="demo",
        lean_root="lean",
    )
    monkeypatch.setattr(generator, "installed", lambda: {"oai": corpus})

    lean = tmp_path / "lean"
    docs = lean / "docs"
    challenges = lean / "ComparatorChallenges"
    docs.mkdir(parents=True)
    challenges.mkdir()
    (docs / "1.md").write_text(
        "# Demo result\n\n## Scope\n\nPinned scope.\n\n## Comparator links\n\n"
        "[Demo](../ComparatorChallenges/Demo.lean)\n",
        encoding="utf-8",
    )
    (challenges / "Demo.json").write_text(
        json.dumps(
            {
                "challenge_module": "ComparatorChallenges.Demo",
                "solution_module": "OAI.Demo.Main",
                "theorem_names": ["OAI.main"],
                "definition_names": [],
            }
        ),
        encoding="utf-8",
    )
    full_doc = (
        "This complete source-authored explanation is deliberately longer than the stale inventory value, "
        "and its final sentence must remain present after regeneration."
    )
    (challenges / "Demo.lean").write_text(
        "namespace OAI\n"
        "/-- Main result. -/\n"
        "theorem main : True := trivial\n\n"
        f"/-- {full_doc} -/\n"
        "theorem helper : True := trivial\n"
        "end OAI\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "declarations.jsonl"
    inventory.write_text(
        json.dumps(
            {
                    "module": "ComparatorChallenges.Demo",
                "path": "lean/ComparatorChallenges/Demo.lean",
                "name": "OAI.helper",
                "doc": "This complete source-authored explanation is delib",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    output, entries, notes = generator.generate(tmp_path, "# overlay\n", inventory)

    assert full_doc in output
    assert "explanation is delib\n" not in output
    assert entries == 2
    assert notes == 1


def test_multi_result_note_scope_is_not_copied_across_comparator_targets(monkeypatch, tmp_path):
    corpus = Corpus(
        name="oai",
        title="OpenAI math",
        repo="openai/math",
        commit="a" * 40,
        branch="main",
        kind="oai",
        blurb="demo",
        lean_root="lean",
    )
    monkeypatch.setattr(generator, "installed", lambda: {"oai": corpus})

    lean = tmp_path / "lean"
    docs = lean / "docs"
    challenges = lean / "ComparatorChallenges"
    docs.mkdir(parents=True)
    challenges.mkdir()
    (docs / "1.md").write_text(
        "# Combined note\n\n## Scope\n\n"
        "Alpha scope must not appear on beta.\n\n"
        "Beta scope must not appear on alpha.\n\n"
        "## Comparator links\n\n"
        "| Result | Comparator statement |\n"
        "| --- | --- |\n"
        "| Alpha result | [Alpha](../ComparatorChallenges/Alpha.lean) |\n"
        "| Beta result | [Beta](../ComparatorChallenges/Beta.lean) |\n",
        encoding="utf-8",
    )
    for stem, name in (("Alpha", "OAI.alpha"), ("Beta", "OAI.beta")):
        (challenges / f"{stem}.json").write_text(
            json.dumps(
                {
                    "challenge_module": f"ComparatorChallenges.{stem}",
                    "solution_module": f"OAI.{stem}.Main",
                    "theorem_names": [name],
                    "definition_names": [],
                }
            ),
            encoding="utf-8",
        )
    (challenges / "Alpha.lean").write_text(
        "namespace OAI\n/-- Alpha declaration only. -/\ntheorem alpha : True := trivial\nend OAI\n",
        encoding="utf-8",
    )
    (challenges / "Beta.lean").write_text(
        "namespace OAI\n/-- Beta declaration only. -/\ntheorem beta : True := trivial\nend OAI\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "declarations.jsonl"
    inventory.write_text(
        "\n".join(
            json.dumps(
                {
                    "module": f"ComparatorChallenges.{stem}",
                    "path": f"lean/ComparatorChallenges/{stem}.lean",
                    "name": name,
                    "doc": f"{stem} declaration only.",
                }
            )
            for stem, name in (("Alpha", "OAI.alpha"), ("Beta", "OAI.beta"))
        )
        + "\n",
        encoding="utf-8",
    )

    output, entries, notes = generator.generate(tmp_path, "# overlay\n", inventory)
    alpha, beta = output.split("@file ComparatorChallenges/Beta.lean", maxsplit=1)

    assert "Challenge statement: Alpha result" in alpha
    assert "Alpha declaration only." in alpha
    assert "Beta scope must not appear on alpha" not in alpha
    assert "Challenge statement: Beta result" in beta
    assert "Beta declaration only." in beta
    assert "Alpha scope must not appear on beta" not in beta
    assert "combined Scope prose is not copied" in alpha
    assert "combined Scope prose is not copied" in beta
    assert entries == 2
    assert notes == 1
