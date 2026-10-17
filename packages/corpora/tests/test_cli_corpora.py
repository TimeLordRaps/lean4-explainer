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
    for name in ("formal-conjectures", "alphaproof-nexus", "carleson", "flt", "pfr", "compfiles", "mil", "tpil", "oai"):
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


def test_no_command_is_the_showcase_of_all_nine(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(extension.showcase, "build_showcase", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")))
    monkeypatch.setattr("sys.stdin", _NotATty())

    code = cli.main([])

    text = capsys.readouterr().out
    assert code == 2
    for repo in ("google-deepmind/formal-conjectures", "google-deepmind/alphaproof-nexus-results", "ImperialCollegeLondon/FLT", "openai/math"):
        assert repo in text


def test_showcase_with_yes_builds_and_reports(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake(corpora, work, out, **kwargs):
        seen.update(
            names=[c.name for c in corpora], out=out, jobs=kwargs["jobs"], site_url=kwargs["site_url"],
            lean_projects=kwargs["lean_projects"], lean_caches=kwargs["lean_caches"],
            lean_cached_only=kwargs["lean_cached_only"], lean_file_limits=kwargs["lean_file_limits"]
        )
        return ShowcaseResult((), 1234, 1000)

    monkeypatch.setattr(extension.showcase, "build_showcase", fake)

    code = cli.main([
        "showcase", "tutorials", "--yes", "--site-url", "https://example.org/proofs/",
        "--out", str(tmp_path / "s"), "--work", str(tmp_path / "w")
    ])

    assert seen["names"] == ["mil", "tpil"]
    assert seen["site_url"] == "https://example.org/proofs/"
    assert seen["lean_projects"] == {} and seen["lean_caches"] == {}
    assert seen["lean_cached_only"] == set() and seen["lean_file_limits"] == {}
    assert code == 1  # the fake result is over its budget
    assert "over" in capsys.readouterr().err


def test_showcase_passes_an_explicit_lean_environment_and_diagnostic_bound(tmp_path, monkeypatch):
    project = tmp_path / "oai-environment"
    project.mkdir()
    (project / "lakefile.lean").write_text('package "oai"\n', encoding="utf-8")
    cache = tmp_path / "lean-cache"
    seen = {}

    def fake(corpora, work, out, **kwargs):
        seen.update(kwargs)
        return ShowcaseResult((), 10, 1000)

    monkeypatch.setattr(extension.showcase, "build_showcase", fake)

    assert cli.main([
        "showcase", "oai", "--yes", "--lean-project", f"oai={project}",
        "--lean-cache", f"oai={cache}", "--lean-cached-only", "oai",
        "--lean-file-limit", "oai=7", "--out", str(tmp_path / "s"), "--work", str(tmp_path / "w")
    ]) == 0

    assert seen["lean_projects"] == {"oai": project.resolve()}
    assert seen["lean_caches"] == {"oai": cache.resolve()}
    assert seen["lean_cached_only"] == {"oai"}
    assert seen["lean_file_limits"] == {"oai": 7}


def test_showcase_rejects_malformed_or_unselected_lean_overrides(tmp_path, capsys):
    assert cli.main(["showcase", "pfr", "--yes", "--lean-project", "bad", "--out", str(tmp_path / "s")]) == 1
    assert "CORPUS=VALUE" in capsys.readouterr().err
    assert cli.main(["showcase", "pfr", "--yes", "--lean-file-limit", "oai=2", "--out", str(tmp_path / "s")]) == 1
    assert "unselected corpus" in capsys.readouterr().err
    assert cli.main(["showcase", "pfr", "--yes", "--lean-cached-only", "oai", "--out", str(tmp_path / "s")]) == 1
    assert "unselected corpus" in capsys.readouterr().err


def _summary(errors=(), warnings=()):
    from lean4_explainer.build import BuildSummary

    return BuildSummary(
        files=1, declarations=1, sorry=0, axioms=0, pages_written=1, pages_reused=0, bytes_written=10, total_bytes=10,
        byte_budget=1000, search_entries=0, errors=tuple(errors), warnings=tuple(warnings), identical_names=0, variant_names=0,
    )


def test_showcase_reports_each_corpus_build_errors_and_fails(tmp_path, monkeypatch, capsys):
    # found 2026-10-10: an edge naming an ambiguous declaration was an error the showcase neither printed nor failed on,
    # so a broken site would have been published
    from lean4_explainer_corpora.registry import installed
    from lean4_explainer_corpora.showcase import ShowcaseItem

    pfr = installed()["pfr"]
    bad = _summary(errors=["error: implications: edge 'x': no declaration named Foo in this site"], warnings=["warning: stale"])
    monkeypatch.setattr(extension.showcase, "build_showcase", lambda *a, **k: ShowcaseResult((ShowcaseItem(pfr, bad, None, 1.0),), 10, 1000))

    code = cli.main(["showcase", "pfr", "--yes", "--out", str(tmp_path / "s"), "--work", str(tmp_path / "w")])

    captured = capsys.readouterr()
    assert code == 1
    assert "pfr: error: implications: edge 'x': no declaration named Foo" in captured.err
    assert "pfr: warning: stale" in captured.out
    assert "1 build error" in captured.err


def test_showcase_without_build_errors_succeeds(tmp_path, monkeypatch, capsys):
    from lean4_explainer_corpora.registry import installed
    from lean4_explainer_corpora.showcase import ShowcaseItem

    pfr = installed()["pfr"]
    monkeypatch.setattr(extension.showcase, "build_showcase", lambda *a, **k: ShowcaseResult((ShowcaseItem(pfr, _summary(), None, 1.0),), 10, 1000))

    assert cli.main(["showcase", "pfr", "--yes", "--out", str(tmp_path / "s"), "--work", str(tmp_path / "w")]) == 0
    assert "error" not in capsys.readouterr().err


def test_fetch_with_yes_fetches_each_corpus(tmp_path, monkeypatch, capsys):
    fetched = []
    monkeypatch.setattr(extension.showcase, "fetch_corpus", lambda corpus, work, **k: fetched.append(corpus.name) or work / corpus.name)

    assert cli.main(["fetch", "flt", "pfr", "--yes", "--work", str(tmp_path)]) == 0

    assert fetched == ["flt", "pfr"]


def test_a_console_that_ends_at_once_is_a_no_not_a_crash(tmp_path, monkeypatch, capsys):
    # on Windows, stdin from NUL (`< /dev/null`, a scheduled task) says it is a terminal, then input() hits its end
    monkeypatch.setattr(extension.showcase, "build_showcase", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")))
    monkeypatch.setattr("sys.stdin", _EmptyTty())

    code = cli.main(["showcase", "pfr", "--out", str(tmp_path / "site"), "--work", str(tmp_path / "work")])

    assert code == 2
    assert "--yes" in capsys.readouterr().out


class _NotATty:
    def isatty(self):
        return False


class _EmptyTty:
    def isatty(self):
        return True

    def readline(self):
        return ""
