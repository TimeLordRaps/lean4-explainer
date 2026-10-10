"""Command-line surface for Lake roots and the built-in corpora."""

from lean4_explainer import cli
from lean4_explainer_corpora import extension
from lean4_explainer_corpora.showcase import ShowcaseResult


def _lake_project(root):
    (root / "Demo").mkdir(parents=True)
    (root / "Scripts").mkdir()
    (root / "lakefile.toml").write_text('name = "demo"\n\n[[lean_lib]]\nname = "Demo"\n', encoding="utf-8")
    (root / "Demo.lean").write_text("import Demo.A\n", encoding="utf-8")
    (root / "Demo" / "A.lean").write_text("theorem a : True := trivial\n", encoding="utf-8")
    (root / "Scripts" / "S.lean").write_text("theorem s : True := trivial\n", encoding="utf-8")


def test_sources_lists_every_corpus_with_its_pin(capsys):
    assert cli.main(["sources"]) == 0

    text = capsys.readouterr().out
    for name in ("formal-conjectures", "carleson", "flt", "pfr", "compfiles", "mil", "tpil", "oai"):
        assert name in text
    assert "openai/math" in text and "1646ca16afd6" in text


def test_sources_can_be_narrowed_by_extra(capsys):
    assert cli.main(["sources", "tutorials"]) == 0

    text = capsys.readouterr().out
    assert "mil" in text and "tpil" in text and "carleson" not in text


def test_sources_rejects_an_unknown_name(capsys):
    assert cli.main(["sources", "nope"]) == 1
    assert "unknown corpus" in capsys.readouterr().err


def test_build_from_a_lake_root_lists_only_library_files(tmp_path, capsys):
    project = tmp_path / "proj"
    _lake_project(project)
    out = tmp_path / "docs"

    assert cli.main(["build", "--lake-root", str(project), "--out", str(out)]) == 0

    assert (out / "Demo" / "A.lean.html").is_file()
    assert not (out / "Scripts").exists()


def test_lake_root_needs_a_lakefile(tmp_path, capsys):
    (tmp_path / "A.lean").write_text("theorem a : True := trivial\n", encoding="utf-8")

    assert cli.main(["build", "--lake-root", str(tmp_path), "--out", str(tmp_path / "docs")]) == 1
    assert "lakefile" in capsys.readouterr().err


def test_build_needs_exactly_one_root(tmp_path):
    try:
        cli.main(["build", "--out", str(tmp_path / "docs")])
    except SystemExit as exit_:
        assert exit_.code == 2
    else:
        raise AssertionError("expected a usage error")
    try:
        cli.main(["build", "--lean-root", "a", "--lake-root", "b", "--out", "c"])
    except SystemExit as exit_:
        assert exit_.code == 2
    else:
        raise AssertionError("expected a usage error")


def test_showcase_without_yes_prints_the_plan_and_downloads_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(extension.showcase, "build_showcase", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")))
    monkeypatch.setattr("sys.stdin", _NotATty())

    code = cli.main(["showcase", "pfr", "--out", str(tmp_path / "site"), "--work", str(tmp_path / "work")])

    text = capsys.readouterr().out
    assert code == 2
    assert "teorth/pfr" in text and "--yes" in text


def test_no_command_is_the_showcase_of_all_eight(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(extension.showcase, "build_showcase", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")))
    monkeypatch.setattr("sys.stdin", _NotATty())

    code = cli.main([])

    text = capsys.readouterr().out
    assert code == 2
    for repo in ("google-deepmind/formal-conjectures", "ImperialCollegeLondon/FLT", "openai/math"):
        assert repo in text


def test_showcase_with_yes_builds_and_reports(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake(corpora, work, out, **kwargs):
        seen.update(names=[c.name for c in corpora], out=out, jobs=kwargs["jobs"])
        return ShowcaseResult((), 1234, 1000)

    monkeypatch.setattr(extension.showcase, "build_showcase", fake)

    code = cli.main(["showcase", "tutorials", "--yes", "--out", str(tmp_path / "s"), "--work", str(tmp_path / "w")])

    assert seen["names"] == ["mil", "tpil"]
    assert code == 1  # the fake result is over its budget
    assert "over" in capsys.readouterr().err


def test_fetch_with_yes_fetches_each_corpus(tmp_path, monkeypatch, capsys):
    fetched = []
    monkeypatch.setattr(extension.showcase, "fetch_corpus", lambda corpus, work, **k: fetched.append(corpus.name) or work / corpus.name)

    assert cli.main(["fetch", "lft", "pfr", "--yes", "--work", str(tmp_path)]) == 0

    assert fetched == ["flt", "pfr"]


class _NotATty:
    def isatty(self):
        return False
