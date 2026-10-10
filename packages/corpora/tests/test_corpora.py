"""The built-in corpora: the Lean repos lean4-explainer explains out of the box, and the pip extras that name them."""

import re
import tomllib
from pathlib import Path

import pytest

from lean4_explainer.errors import ExplainerError
from lean4_explainer_corpora import EXTRAS, installed, select

CORPORA = installed()

ALL = {"formal-conjectures", "carleson", "flt", "pfr", "compfiles", "mil", "tpil", "oai"}


def test_registry_holds_the_eight_corpora():
    assert set(CORPORA) == ALL


def test_every_corpus_is_pinned_to_a_full_commit():
    for corpus in CORPORA.values():
        assert re.fullmatch(r"[0-9a-f]{40}", corpus.commit), corpus.name
        assert re.fullmatch(r"[\w.-]+/[\w.-]+", corpus.repo), corpus.name
        assert corpus.title and corpus.blurb, corpus.name


def test_every_corpus_states_its_license():
    for corpus in CORPORA.values():
        assert corpus.license == "Apache-2.0", corpus.name  # the LICENSE file of each pinned checkout


def test_formal_conjectures_carries_the_share_alike_notice():
    note = CORPORA["formal-conjectures"].license_note
    assert "CC-BY-SA" in note and "CC-BY" in note and "Wikipedia" in note and "OEIS" in note
    assert all(not c.license_note for c in CORPORA.values() if c.name != "formal-conjectures")


def test_two_of_the_corpora_are_tutorials():
    assert {c.name for c in CORPORA.values() if c.kind == "tutorial"} == {"mil", "tpil"}
    assert [c.name for c in select("tutorials")] == ["mil", "tpil"]


def test_lft_and_flt_name_the_same_corpus():
    assert [c.name for c in select("lft")] == ["flt"] == [c.name for c in select("flt")]


def test_conjectures_is_the_conjectures_repo_only():
    assert [c.name for c in select("conjectures")] == ["formal-conjectures"]


def test_oai_is_openai_math():
    corpus = select("oai")[0]
    assert corpus.repo == "openai/math"
    assert corpus.lean_root == "lean"
    assert not corpus.lake


def test_all_and_the_default_selection_hold_all_eight():
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
    assert declared - {"test", "l4del"} == set(EXTRAS)


def test_every_extra_installs_the_packages_of_its_corpora():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    extras = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for extra, names in EXTRAS.items():
        wanted = {f"lean4-explainer-{name}" for name in names}
        assert {item.split(">")[0].split("=")[0] for item in extras[extra]} >= wanted, extra
    assert extras["l4del"] == ["lean4-explainer-l4del>=0.1.0"]


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
