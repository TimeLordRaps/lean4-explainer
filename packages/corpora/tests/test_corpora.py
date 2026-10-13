"""The built-in corpora: the Lean repos lean4-explainer explains out of the box, and the pip extras that name them."""

import re
import tomllib
from pathlib import Path

import pytest

from lean4_explainer.errors import ExplainerError
from lean4_explainer_corpora import EXTRAS, installed, select

CORPORA = installed()

ALL = {"formal-conjectures", "alphaproof-nexus", "carleson", "flt", "pfr", "compfiles", "mil", "tpil", "oai"}


def test_registry_holds_the_nine_corpora():
    assert set(CORPORA) == ALL


def test_every_corpus_is_pinned_to_a_full_commit():
    for corpus in CORPORA.values():
        assert re.fullmatch(r"[0-9a-f]{40}", corpus.commit), corpus.name
        assert re.fullmatch(r"[\w.-]+/[\w.-]+", corpus.repo), corpus.name
        assert corpus.title and corpus.blurb, corpus.name


def test_seo_descriptions_never_use_l4del_without_expanding_it():
    for corpus in CORPORA.values():
        if "L4DEL" in corpus.seo_description:
            assert "Lean4 Domain Explanation Language (L4DEL)" in corpus.seo_description, corpus.name


def test_every_corpus_states_its_license():
    for corpus in CORPORA.values():
        assert corpus.license == "Apache-2.0", corpus.name  # the LICENSE file of each pinned checkout


def test_corpus_packages_do_not_select_explanatory_overlays():
    assert all(not hasattr(corpus, "overlay") for corpus in CORPORA.values())
    package_root = Path(__file__).resolve().parents[2]
    assert not list(package_root.glob("corpus-*/src/**/*.l4del"))


def test_formal_conjectures_carries_the_share_alike_notice():
    note = CORPORA["formal-conjectures"].license_note
    assert "CC-BY-SA" in note and "CC-BY" in note and "Wikipedia" in note and "OEIS" in note
    assert "CC-BY 4.0" in CORPORA["alphaproof-nexus"].license_note
    assert "OEIS" in CORPORA["alphaproof-nexus"].license_note
    assert all(not c.license_note for c in CORPORA.values() if c.name not in {"formal-conjectures", "alphaproof-nexus"})


def test_two_of_the_corpora_are_tutorials():
    assert {c.name for c in CORPORA.values() if c.kind == "tutorial"} == {"mil", "tpil"}
    assert [c.name for c in select("tutorials")] == ["mil", "tpil"]


def test_lft_is_not_an_extra():
    with pytest.raises(ExplainerError):
        select("lft")

def test_conjectures_is_the_conjectures_repo_only():
    assert [c.name for c in select("conjectures")] == ["formal-conjectures"]


def test_oai_is_openai_math():
    corpus = select("oai")[0]
    assert corpus.repo == "openai/math"
    assert corpus.lean_root == "lean"
    assert not corpus.lake


def test_alphaproof_nexus_is_the_published_results_repository():
    corpus = select("alphaproof-nexus")[0]
    assert corpus.repo == "google-deepmind/alphaproof-nexus-results"
    assert corpus.commit == "0647711a71183c1ea492ad60860776617ce1ea88"
    assert corpus.lake


def test_all_and_the_default_selection_hold_all_nine():
    assert {c.name for c in select("all")} == ALL
    assert {c.name for c in select(None)} == ALL


def test_several_names_are_joined_without_repeats():
    assert [c.name for c in select("pfr", "tutorials", "pfr")] == ["pfr", "mil", "tpil"]


def test_unknown_name_is_an_error_that_lists_the_choices():
    with pytest.raises(ExplainerError) as caught:
        select("nope")
    assert "nope" in str(caught.value) and "conjectures" in str(caught.value)


def test_core_pyproject_extras_match_the_registry_names():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    declared = set(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"])
    assert declared - {"test", "l4del", "lean", "ecosystem", "reader", "map", "implications"} == set(EXTRAS)  # the other extras are not corpora


def test_every_extra_installs_the_packages_of_its_corpora():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    extras = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for extra, names in EXTRAS.items():
        wanted = {f"lean4-explainer-{name}" for name in names}
        assert {item.split(">")[0].split("=")[0] for item in extras[extra]} >= wanted, extra
    assert extras["l4del"] == ["lean4-explainer-l4del>=0.5.0"]  # legends and linked quotes; overlays remain hosted-only
    assert "lean4-explainer-l4del>=0.5.0" in extras["all"]
    # 0.2.0 follows imports through files that only import (the core's import graph, core 0.3.0)
    assert extras["map"] == ["lean4-explainer-map>=0.2.0"] and "lean4-explainer-map>=0.2.0" in extras["all"]
    # 0.4.0 carries the proved edge's bridge, its verification record and the discovered catalogue
    assert extras["oai"] == ["lean4-explainer-oai>=0.4.0"] and "lean4-explainer-oai>=0.4.0" in extras["all"]
    # 0.2.0 checks verification records against the files and shows the catalogue; 0.1.0 would show neither
    assert extras["implications"] == ["lean4-explainer-implications>=0.2.0"] and "lean4-explainer-implications>=0.2.0" in extras["all"]


def test_an_uninstalled_corpus_names_the_extra_that_installs_it():
    from lean4_explainer_corpora import activate

    activate([])
    try:
        with pytest.raises(ExplainerError) as caught:
            select("tutorials")
    finally:
        activate(None)
    assert "pip install lean4-explainer[tutorials]" in str(caught.value)


def test_nothing_installed_says_how_to_install():
    from lean4_explainer_corpora import activate

    activate([])
    try:
        with pytest.raises(ExplainerError) as caught:
            select()
    finally:
        activate(None)
    assert "lean4-explainer[all]" in str(caught.value)


def test_compfiles_lists_its_problem_statements():
    assert installed()["compfiles"].extra_kinds == ("problem", "determine")
    assert all(not c.extra_kinds for name, c in installed().items() if name != "compfiles")


def test_themes_style_compact_declaration_kinds():
    selector = ".kind, ol.decls > li > b:first-child"
    assert all(selector in corpus.theme_css for corpus in CORPORA.values())
    assert f"{selector} {{ font-weight: 700; }}" in CORPORA["compfiles"].theme_css
