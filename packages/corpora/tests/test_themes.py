import pytest

from lean4_explainer_corpora import installed
from lean4_explainer_corpora.themes import make_theme

PALETTE = dict(fg="#000", bg="#fff", muted="#666", line="#ccc", warn="#a00", panel="#eee", accent="#00f", **{"warn-bg": "#fee"})


def test_theme_needs_a_full_palette():
    short = {k: v for k, v in PALETTE.items() if k != "accent"}
    with pytest.raises(ValueError, match="accent"):
        make_theme(light=short, dark=PALETTE)


def test_theme_sets_light_and_dark_variables():
    css = make_theme(light=PALETTE, dark={**PALETTE, "bg": "#101010"})
    assert "--bg: #fff;" in css
    assert "@media (prefers-color-scheme: dark) { :root { " in css and "--bg: #101010;" in css


def test_every_installed_corpus_has_its_own_look():
    corpora = installed()
    assert corpora, "install the corpus packages (pip install -e packages/corpus-*)"
    assert all(c.theme_css and c.accent.startswith("#") for c in corpora.values())
    assert len({c.theme_css for c in corpora.values()}) == len(corpora)
    assert len({c.accent for c in corpora.values()}) == len(corpora)


def test_themes_use_no_external_resources():
    for corpus in installed().values():
        assert "http://" not in corpus.theme_css.replace("http://www.w3.org/2000/svg", "")
        assert "https://" not in corpus.theme_css
        assert "@import" not in corpus.theme_css
