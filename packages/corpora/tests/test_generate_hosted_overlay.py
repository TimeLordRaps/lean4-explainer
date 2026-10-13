from lean4_explainer_corpora.registry import Corpus
from scripts import generate_documented_hosted_overlay as generator


def test_generator_never_uses_a_later_duplicate_to_describe_the_first(monkeypatch, tmp_path):
    corpus = Corpus(
        name="demo",
        title="Demo",
        repo="example/demo",
        commit="a" * 40,
        branch="main",
        kind="tutorial",
        blurb="demo",
        lake=False,
        include=("*.lean",),
    )
    monkeypatch.setattr(generator, "installed", lambda: {"demo": corpus})
    (tmp_path / "A.lean").write_text(
        "def repeated : Nat := 1\n\n/-- This describes only the later occurrence. -/\ndef repeated : Nat := 2\n"
        "\n/-- Anonymous declarations cannot be overlay targets. -/\ninstance : Inhabited Nat := ⟨0⟩\n"
        "\n/-- A unique declaration. -/\ndef unique : Nat := 3\n",
        encoding="utf-8",
    )

    output, entries, described = generator.generate("demo", tmp_path, "# overlay\n")

    assert "@decl repeated" not in output
    assert "@decl (instance" not in output
    assert "@decl unique" in output
    assert (entries, described) == (1, 1)
