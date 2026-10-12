"""fetch pins a corpus to its commit; the showcase builds one subsite per corpus under a landing page."""

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from lean4_explainer.errors import ExplainerError
from lean4_explainer_corpora import CorporaExtension, installed
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


def test_each_subsite_wears_its_corpus_theme_and_the_landing_card_its_accent(upstream, tmp_path):
    corpus, base = upstream
    corpus = replace(corpus, theme_css=".marker-theme { color: red; }\n", accent="#123456")
    out = tmp_path / "site"

    build_showcase([corpus], tmp_path / "work", out, base_url=base)

    assert ".marker-theme { color: red; }" in (out / "demo" / "_assets" / "site.css").read_text(encoding="utf-8")
    assert ".marker-theme" not in (out / "_assets" / "site.css").read_text(encoding="utf-8")  # the landing has its own look
    assert 'style="--card: #123456"' in (out / "index.html").read_text(encoding="utf-8")


def test_a_corpus_overlay_annotates_the_subsite_and_the_landing_says_who_wrote_it(upstream, tmp_path):
    from lean4_explainer import extensions
    from lean4_explainer_l4del import L4delExtension

    corpus, base = upstream
    overlay = tmp_path / "demo.l4del"
    overlay.write_text("@file Demo/A.lean\n@decl a_fact\n-- L4DEL: title: A sidecar title\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "overlays": {
                    "demo": {
                        "file": "demo.l4del",
                        "repo": corpus.repo,
                        "commit": corpus.commit,
                        "sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
                        "provenance": "ai-generated-unreviewed",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    extensions.activate([L4delExtension()])
    out = tmp_path / "site"

    build_site_result = build_showcase(
        [corpus], tmp_path / "work", out, base_url=base, overlay_manifest=manifest
    )

    page = (out / "demo" / "Demo" / "A.lean.html").read_text(encoding="utf-8")
    assert "A sidecar title" in page
    assert "AI-generated and not human-reviewed" in page
    assert "not mathematical authority" in page
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert "hosted sidecar overlay" in landing and "did not write these explanations" in landing
    assert "AI-generated and not human-reviewed" in landing
    assert build_site_result.total_bytes > 0


def test_without_an_explicit_manifest_the_corpus_stays_annotation_free(upstream, tmp_path):
    corpus, base = upstream
    overlay = tmp_path / "demo.l4del"
    overlay.write_text("@file Demo/A.lean\n@decl a_fact\n-- L4DEL: title: A sidecar title\n", encoding="utf-8")
    out = tmp_path / "site"

    build_showcase([corpus], tmp_path / "work", out, base_url=base)

    assert "A sidecar title" not in (out / "demo" / "Demo" / "A.lean.html").read_text(encoding="utf-8")
    assert "sidecar overlay" not in (out / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repo", "someone/else", "repo"),
        ("commit", "0" * 40, "commit"),
        ("sha256", "0" * 64, "sha256"),
        ("provenance", "reviewed-ish", "provenance"),
    ],
)
def test_overlay_manifest_fails_closed_when_its_binding_is_wrong(upstream, tmp_path, field, value, message):
    corpus, base = upstream
    overlay = tmp_path / "demo.l4del"
    overlay.write_text("@file Demo/A.lean\n@decl a_fact\n-- L4DEL: title: A sidecar title\n", encoding="utf-8")
    entry = {
        "file": "demo.l4del",
        "repo": corpus.repo,
        "commit": corpus.commit,
        "sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
        "provenance": "human-authored",
    }
    entry[field] = value
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "overlays": {"demo": entry}}), encoding="utf-8")

    with pytest.raises(ExplainerError, match=message):
        build_showcase(
            [corpus], tmp_path / "work", tmp_path / "site", base_url=base, overlay_manifest=manifest
        )


def _edges(path, commit):
    path.write_text(
        "[[edge]]\n"
        'id = "demo-edge"\n'
        'kind = "strengthens"\n'
        'from = ["a_fact"]\n'
        'to = "tool_fact"\n'
        "hypotheses = []\n"
        'conclusion = "True"\n'
        f'commit = "{commit}"\n'
        'status = "argued"\n'
        'origin = "a test"\n'
        'argument = "trivial"\n',
        encoding="utf-8",
    )
    return str(path)


def test_a_corpus_with_implication_edges_shows_them_and_the_landing_says_who_curated_them(upstream, tmp_path):
    implications = pytest.importorskip("lean4_explainer_implications")
    from lean4_explainer import extensions

    corpus, base = upstream
    corpus = replace(corpus, lake=False, include=("Demo/*", "Tools/*"), implications=_edges(tmp_path / "edges.toml", corpus.commit))
    extensions.activate([implications.ImplicationsExtension()])
    out = tmp_path / "site"
    try:
        build_showcase([corpus], tmp_path / "work", out, base_url=base)
    finally:
        extensions.activate([CorporaExtension()])

    page = (out / "demo" / "Demo" / "A.lean.html").read_text(encoding="utf-8")
    assert "strengthens" in page and "implications.html#demo-edge" in page
    assert 'class="imp imp-stale"' not in page  # read at the commit this site shows
    assert (out / "demo" / "implications.html").is_file()
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="demo/implications.html"' in landing and "not by the upstream authors" in landing


def test_an_edge_read_at_another_commit_than_the_corpus_pin_shows_as_stale(upstream, tmp_path):
    implications = pytest.importorskip("lean4_explainer_implications")
    from lean4_explainer import extensions

    corpus, base = upstream
    corpus = replace(corpus, lake=False, include=("Demo/*", "Tools/*"), implications=_edges(tmp_path / "edges.toml", "0" * 40))
    extensions.activate([implications.ImplicationsExtension()])
    try:
        build_showcase([corpus], tmp_path / "work", tmp_path / "site", base_url=base)
    finally:
        extensions.activate([CorporaExtension()])

    assert 'class="imp imp-stale"' in (tmp_path / "site" / "demo" / "Demo" / "A.lean.html").read_text(encoding="utf-8")


def test_without_the_implications_extension_the_landing_does_not_claim_edges(upstream, tmp_path):
    corpus, base = upstream
    corpus = replace(corpus, lake=False, include=("Demo/*", "Tools/*"), implications=_edges(tmp_path / "edges.toml", corpus.commit))

    build_showcase([corpus], tmp_path / "work", tmp_path / "site", base_url=base)

    assert not (tmp_path / "site" / "demo" / "implications.html").exists()
    assert "implications.html" not in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")


def test_the_oai_implication_edges_are_contracts_read_at_its_pin():
    edges = pytest.importorskip("lean4_explainer_implications.edges")
    oai = CORPORA["oai"]

    found = edges.load(Path(oai.implications).read_text(encoding="utf-8"))

    assert found.problems == ()
    assert found.edges, "the oai sidecar holds at least one edge"
    assert all(edge.commit == oai.commit for edge in found.edges)
    assert all(c.implications == "" for name, c in CORPORA.items() if name != "oai")
    # a proved edge ships its bridge file and a recorded kernel check that still matches its contract and that file
    side = Path(oai.implications).parent
    record_file = side / (Path(oai.implications).stem + ".verified.json")
    records = json.loads(record_file.read_text(encoding="utf-8"))["edges"] if record_file.is_file() else {}
    proved = [e for e in found.edges if e.status == "proved"]
    for edge in proved:
        assert edge.bridge_file, f"{edge.id} is proved by a bridge in the corpus sidecar, so it needs a bridge file"
        bridge = side / edge.bridge_file
        assert bridge.is_file(), bridge
        v = edges.verify(edge, lambda name: None, records.get(edge.id), edges.content_sha256(bridge.read_bytes()))
        assert (v.state, v.provenance) == ("kernel-checked", "recorded"), (edge.id, v.detail)
    assert [e.id for e in proved] == ["seven-eighths-gives-an-explicit-real-zero-gap"]  # the fluid candidate is unfinished


def test_the_packaged_oai_catalogue_has_unique_deep_link_ids():
    catalogue = Path(CORPORA["oai"].implications).parent / "catalogue" / "index.json"
    rows = json.loads(catalogue.read_text(encoding="utf-8"))["implications"]
    ids = [row["id"] for row in rows]

    assert all(isinstance(row_id, str) and row_id for row_id in ids)
    assert len(ids) == len(set(ids))


def test_with_the_reader_a_corpus_too_big_to_publish_twice_reads_from_its_pinned_raw_source(upstream, tmp_path):
    reader = pytest.importorskip("lean4_explainer_reader")
    from lean4_explainer import extensions

    corpus, base = upstream
    extensions.activate([reader.ReaderExtension()])
    try:
        build_showcase([replace(corpus, source_links="file")], tmp_path / "work", tmp_path / "big", base_url=base)
        build_showcase([corpus], tmp_path / "work", tmp_path / "small", base_url=base)
    finally:
        extensions.activate(None)
    big = (tmp_path / "big" / "demo" / "Demo" / "A.lean.html").read_text(encoding="utf-8")
    assert f'data-src="https://raw.githubusercontent.com/acme/demo/{corpus.commit}/Demo/A.lean"' in big
    small = (tmp_path / "small" / "demo" / "Demo" / "A.lean.html").read_text(encoding="utf-8")
    assert '<script type="application/json" id="lean-source">' in small and "data-src" not in small


def test_a_corpus_carries_its_own_extension_settings_into_its_build(upstream, tmp_path):
    map_ext = pytest.importorskip("lean4_explainer_map")
    from lean4_explainer import extensions

    corpus, base = upstream
    extensions.activate([map_ext.MapExtension()])
    try:
        build_showcase([corpus], tmp_path / "work", tmp_path / "on", base_url=base)
        build_showcase([replace(corpus, options=(("map_dependencies", False),))], tmp_path / "work", tmp_path / "off", base_url=base)
    finally:
        extensions.activate([CorporaExtension()])
    assert (tmp_path / "on" / "demo" / "map.html").is_file()
    assert not (tmp_path / "off" / "demo" / "map.html").exists()


def test_the_oai_corpus_leaves_out_the_map_to_stay_inside_the_pages_limit():
    assert ("map_dependencies", False) in CORPORA["oai"].options
    assert all(("map_dependencies", False) not in c.options for name, c in CORPORA.items() if name != "oai")


def test_a_corpus_chooses_how_much_of_itself_its_glossary_lists(upstream, tmp_path, monkeypatch):
    from lean4_explainer_corpora import showcase

    corpus, base = upstream
    seen = []
    real = showcase.build_site

    def spy(root, out, config, cache, jobs=1):
        seen.append(config.glossary)
        return real(root, out, config, cache, jobs=jobs)

    monkeypatch.setattr(showcase, "build_site", spy)
    build_showcase([replace(corpus, glossary="described")], tmp_path / "work", tmp_path / "described", base_url=base)
    build_showcase([corpus], tmp_path / "work", tmp_path / "all", base_url=base)
    assert seen == ["described", "all"]
    assert (tmp_path / "all" / "demo" / "glossary.html").is_file()


def test_a_corpus_chooses_where_file_pages_list_imports(upstream, tmp_path, monkeypatch):
    from lean4_explainer_corpora import showcase

    corpus, base = upstream
    seen = []
    real = showcase.build_site

    def spy(root, out, config, cache, jobs=1):
        seen.append(config.imports)
        return real(root, out, config, cache, jobs=jobs)

    monkeypatch.setattr(showcase, "build_site", spy)
    build_showcase([replace(corpus, imports="import-only")], tmp_path / "work", tmp_path / "only", base_url=base)
    build_showcase([corpus], tmp_path / "work", tmp_path / "all", base_url=base)
    assert seen == ["import-only", "all"]


def test_the_oai_pages_list_imports_only_where_a_file_does_nothing_else():
    # openai/math: 336,022 imports in 122,875 files; lists on every page would not fit in the Pages limit
    assert CORPORA["oai"].imports == "import-only"
    assert all(c.imports == "all" for name, c in CORPORA.items() if name != "oai")


def test_the_oai_glossary_lists_only_described_definitions_to_stay_inside_the_pages_limit():
    # 1,286,783 definitions in openai/math, 24,695 of them described (counted at the pinned commit, 2026-10-10)
    assert CORPORA["oai"].glossary == "described"
    assert all(c.glossary == "all" for name, c in CORPORA.items() if name != "oai")
