"""Per-declaration source links dominate a very large site, so a config can ask for one link per file instead."""

import pytest

from lean4_explainer.build import build_site
from lean4_explainer.config import Config, load_config
from lean4_explainer.errors import ExplainerError

URL = "https://example.org/blob/{ref}/{path}#L{line}"


def _tree(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "A.lean").write_text("theorem a : True := trivial\n\ntheorem b : True := trivial\n", encoding="utf-8")
    return root


def test_declaration_links_are_the_default(tmp_path):
    out = tmp_path / "docs"

    build_site(_tree(tmp_path), out, Config(source_url=URL, source_ref="abc"))

    page = (out / "A.lean.html").read_text(encoding="utf-8")
    assert page.count('class="src"') == 3
    assert ">Source file</a>" in page
    assert "https://example.org/blob/abc/A.lean#L1" in page
    assert "https://example.org/blob/abc/A.lean#L3" in page


def test_file_links_put_one_link_on_the_page(tmp_path):
    out = tmp_path / "docs"

    build_site(_tree(tmp_path), out, Config(source_url=URL, source_ref="abc", source_links="file"))

    page = (out / "A.lean.html").read_text(encoding="utf-8")
    assert page.count('class="src"') == 1
    assert "https://example.org/blob/abc/A.lean#L1" in page
    assert ">Source file</a>" in page
    assert page.index(">Source file</a>") < page.index("2 declarations")


def test_github_file_link_names_its_destination(tmp_path):
    out = tmp_path / "docs"
    github = "https://github.com/example/project/blob/{ref}/{path}#L{line}"

    build_site(_tree(tmp_path), out, Config(source_url=github, source_ref="abc", source_links="file"))

    page = (out / "A.lean.html").read_text(encoding="utf-8")
    assert ">GitHub source file</a>" in page
    assert page.index(">GitHub source file</a>") < page.index("2 declarations")


def test_github_declaration_links_keep_a_plain_file_link_near_the_title(tmp_path):
    out = tmp_path / "docs"
    github = "https://github.com/example/project/blob/{ref}/{path}#L{line}"

    build_site(_tree(tmp_path), out, Config(source_url=github, source_ref="abc"))

    page = (out / "A.lean.html").read_text(encoding="utf-8")
    assert page.count('class="src"') == 3
    assert 'href="https://github.com/example/project/blob/abc/A.lean#L1">GitHub source file</a>' in page
    assert 'href="https://github.com/example/project/blob/abc/A.lean#L3">source</a>' in page


def test_source_links_must_be_declaration_or_file(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('source_links = "everything"\n', encoding="utf-8")

    with pytest.raises(ExplainerError):
        load_config(path)
