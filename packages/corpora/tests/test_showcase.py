"""fetch pins a corpus to its commit; the showcase builds one subsite per corpus under a landing page."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from lean4_explainer.errors import ExplainerError
from lean4_explainer_corpora import installed
from lean4_explainer_corpora.showcase import build_showcase, fetch_corpus

CORPORA = installed()


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def upstream(tmp_path):
    """A local stand-in for github.com/<owner>/<name>, with two commits so the pin matters."""
    repo = tmp_path / "hub" / "acme" / "demo"
    (repo / "Demo").mkdir(parents=True)
    (repo / "Tools").mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "lakefile.toml").write_text('name = "demo"\n\n[[lean_lib]]\nname = "Demo"\n', encoding="utf-8")
    (repo / "LICENSE").write_text("Apache License\nVersion 2.0, January 2004\n", encoding="utf-8")
    (repo / "lean-toolchain").write_text("leanprover/lean4:v4.0.0\n", encoding="utf-8")
    (repo / "Demo.lean").write_text("import Demo.A\n", encoding="utf-8")
    (repo / "Demo" / "A.lean").write_text("/-- first -/\ntheorem a_fact : True := trivial\n", encoding="utf-8")
    (repo / "Tools" / "T.lean").write_text("theorem tool_fact : True := trivial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "one")
    pinned = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    (repo / "Demo" / "B.lean").write_text("theorem later_fact : True := trivial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "two")
    corpus = replace(
        CORPORA["flt"], name="demo", title="Demo corpus", repo="acme/demo", commit=pinned, branch="main", lean_root=""
    )
    return corpus, (tmp_path / "hub").as_uri()


def test_fetch_checks_out_the_pinned_commit(upstream, tmp_path):
    corpus, base = upstream

    checkout = fetch_corpus(corpus, tmp_path / "work", base_url=base)

    assert (checkout / "Demo" / "A.lean").is_file()
    assert not (checkout / "Demo" / "B.lean").exists()  # added after the pin


def test_fetch_twice_reuses_the_checkout(upstream, tmp_path):
    corpus, base = upstream

    first = fetch_corpus(corpus, tmp_path / "work", base_url=base)
    (first / "marker.txt").write_text("kept", encoding="utf-8")
    second = fetch_corpus(corpus, tmp_path / "work", base_url=base)

    assert first == second and (second / "marker.txt").is_file()


def test_fetch_failure_names_the_corpus(tmp_path):
    corpus = replace(CORPORA["flt"], repo="acme/missing")

    with pytest.raises(ExplainerError) as caught:
        fetch_corpus(corpus, tmp_path / "work", base_url=(tmp_path / "nowhere").as_uri())

    assert "flt" in str(caught.value)


def test_showcase_builds_a_subsite_per_corpus_and_a_landing_page(upstream, tmp_path):
    corpus, base = upstream
    out = tmp_path / "site"

    result = build_showcase([corpus], tmp_path / "work", out, base_url=base)

    assert (out / "demo" / "Demo" / "A.lean.html").is_file()
    assert not (out / "demo" / "Tools").exists()  # not a library root in lakefile.toml
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="demo/index.html"' in landing
    assert "Demo corpus" in landing and "leanprover/lean4:v4.0.0" in landing
    assert corpus.commit[:12] in landing
    assert "#l4del-write-your-own-explanations" in landing  # the README's L4DEL section
    assert "demo/annotate.html" not in landing  # no L4DEL extension here, so no guide page to link
    assert 'href="../index.html">All corpora<' in (out / "demo" / "index.html").read_text(encoding="utf-8")
    assert result.total_bytes > 0 and not result.over_budget
    assert (out / ".nojekyll").is_file()


def test_showcase_copies_each_license_and_shows_it_on_the_landing_page(upstream, tmp_path):
    corpus, base = upstream
    corpus = replace(corpus, license="Apache-2.0", license_note="Parts are CC-BY-SA 4.0.")
    out = tmp_path / "site"

    build_showcase([corpus], tmp_path / "work", out, base_url=base)

    assert "Apache License" in (out / "demo" / "LICENSE.txt").read_text(encoding="utf-8")
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert "Apache-2.0" in landing and 'href="demo/LICENSE.txt"' in landing
    assert "Parts are CC-BY-SA 4.0." in landing


def test_showcase_without_a_lakefile_uses_the_corpus_include_patterns(upstream, tmp_path):
    corpus, base = upstream
    plain = replace(corpus, lake=False, include=("Tools/*",))
    out = tmp_path / "site"

    build_showcase([plain], tmp_path / "work", out, base_url=base)

    assert (out / "demo" / "Tools" / "T.lean.html").is_file()
    assert not (out / "demo" / "Demo").exists()


def test_showcase_links_to_corpora_that_were_left_out(upstream, tmp_path):
    corpus, base = upstream
    out = tmp_path / "site"

    build_showcase([corpus], tmp_path / "work", out, base_url=base, link_out=[CORPORA["oai"]])

    landing = (out / "index.html").read_text(encoding="utf-8")
    assert "https://github.com/openai/math" in landing


def test_showcase_reports_when_the_total_is_over_budget(upstream, tmp_path):
    corpus, base = upstream

    result = build_showcase([corpus], tmp_path / "work", tmp_path / "site", base_url=base, byte_budget=10)

    assert result.over_budget


def test_a_fetch_failure_stops_the_showcase_before_writing_the_landing_page(tmp_path):
    out = tmp_path / "site"

    with pytest.raises(ExplainerError):
        build_showcase(
            [replace(CORPORA["flt"], repo="acme/missing")],
            tmp_path / "work",
            out,
            base_url=(tmp_path / "nowhere").as_uri(),
        )

    assert not (out / "index.html").exists()


def test_landing_page_escapes_titles(upstream, tmp_path):
    corpus, base = upstream
    nasty = replace(corpus, title="<script>x</script>")
    out = tmp_path / "site"

    build_showcase([nasty], tmp_path / "work", out, base_url=base)

    assert "<script>x" not in (out / "index.html").read_text(encoding="utf-8")
    assert isinstance(out, Path)
