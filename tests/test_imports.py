"""What a file imports and what imports it, on its page: a file that only gathers imports must not look empty."""

import re
from html import unescape

import pytest

from lean4_explainer import extensions
from lean4_explainer.build import build_site
from lean4_explainer.config import Config, load_config
from lean4_explainer.errors import ExplainerError

HUB = """\
/- Copyright notice. import NotAnImport -/
module

public import P.Def
public meta import P.Deep.Leaf
public import Mathlib.Data.Nat.Basic
import Other.Thing Third.Thing
-- import Commented.Out

/-!
# Standard imports

Problem files import this one file.
-/
"""

DEF = """\
module

public import Mathlib

/-- A constant. -/
def Kc : Nat := 7
"""

LEAF = "def leaf : Nat := 1\n"

USER = """\
import Hub

theorem uses : Kc = 7 := rfl
"""


@pytest.fixture(autouse=True)
def core_only():
    extensions.activate([])
    yield
    extensions.activate(None)


def _tree(tmp_path, user=USER):
    src = tmp_path / "src"
    (src / "P" / "Deep").mkdir(parents=True, exist_ok=True)
    (src / "Hub.lean").write_text(HUB, encoding="utf-8")
    (src / "P" / "Def.lean").write_text(DEF, encoding="utf-8")
    (src / "P" / "Deep" / "Leaf.lean").write_text(LEAF, encoding="utf-8")
    (src / "User.lean").write_text(user, encoding="utf-8")
    return src


def _build(tmp_path, config=None, out="out", jobs=1):
    summary = build_site(tmp_path / "src", tmp_path / out, config or Config(), tmp_path / "idx", jobs=jobs)
    assert not summary.errors
    return tmp_path / out


def _block(page, kind):
    """The <details> or <section> of one kind ("imports" or "imported-by"), or None."""
    match = re.search(rf'<(details|section) class="{kind}"[^>]*>(.*?)</\1>', page, re.S)
    return match.group(2) if match else None


def _links(block):
    return [(unescape(href), unescape(re.sub("<[^>]+>", "", text))) for href, text in re.findall(r'<a href="([^"]+)">(.*?)</a>', block)]


def _codes(block):
    return [unescape(text) for text in re.findall(r"<code>(.*?)</code>", block)]


def test_an_import_only_file_says_so_and_lists_what_it_gathers(tmp_path):
    _tree(tmp_path)
    out = _build(tmp_path)
    page = (out / "Hub.lean.html").read_text(encoding="utf-8")
    assert "No declarations listed." not in page
    assert "This file declares nothing itself. It gathers the 5 imports below" in page
    block = _block(page, "imports")
    assert block is not None
    assert _links(block) == [
        ("P/Def.lean.html", "P.Def"),
        ("P/Deep/Leaf.lean.html", "P.Deep.Leaf"),
        ("https://leanprover-community.github.io/mathlib4_docs/Mathlib/Data/Nat/Basic.html", "Mathlib.Data.Nat.Basic"),
    ]
    # outside the project and not in the Mathlib documentation: named, not linked; comments are not imports
    assert [c for c in _codes(block) if "Thing" in c] == ["Other.Thing", "Third.Thing"]
    assert "Commented" not in block and "NotAnImport" not in block
    assert '<details class="imports" open>' in page or '<section class="imports">' in page  # shown, not folded


def test_a_file_lists_its_imports_folded_and_the_project_files_that_import_it(tmp_path):
    _tree(tmp_path)
    out = _build(tmp_path)
    page = (out / "P" / "Def.lean.html").read_text(encoding="utf-8")
    assert '<details class="imports">' in page  # folded under a file that declares something
    assert _links(_block(page, "imports")) == [("https://leanprover-community.github.io/mathlib4_docs/Mathlib.html", "Mathlib")]
    assert _links(_block(page, "imported-by")) == [("../Hub.lean.html", "Hub.lean")]
    leaf = (out / "P" / "Deep" / "Leaf.lean.html").read_text(encoding="utf-8")
    assert _block(leaf, "imports") is None  # imports nothing
    assert _links(_block(leaf, "imported-by")) == [("../../Hub.lean.html", "Hub.lean")]
    hub = (out / "Hub.lean.html").read_text(encoding="utf-8")
    assert _links(_block(hub, "imported-by")) == [("User.lean.html", "User.lean")]


def test_every_import_link_lands_on_a_page(tmp_path):
    _tree(tmp_path)
    out = _build(tmp_path)
    checked = 0
    for page_path in out.rglob("*.lean.html"):
        page = page_path.read_text(encoding="utf-8")
        for kind in ("imports", "imported-by"):
            block = _block(page, kind)
            for href, _ in _links(block or ""):
                if href.startswith("https://"):
                    continue
                assert (page_path.parent / href).resolve().is_file(), (page_path, href)
                checked += 1
    assert checked == 6  # Hub: 2 imports + 1 importer; Def, Leaf: 1 importer each; User: 1 import; Def's Mathlib is external


def test_the_folder_list_says_a_file_only_imports_instead_of_zero_declarations(tmp_path):
    _tree(tmp_path)
    out = _build(tmp_path)
    index = (out / "index.html").read_text(encoding="utf-8")
    item = re.search(r'<li data-filterable><a href="Hub.lean.html">Hub.lean</a> <span class="muted">([^<]*)</span>', index)
    assert item and item.group(1) == "5 imports, no declarations"
    assert '<a href="User.lean.html">User.lean</a> <span class="muted">1 declarations</span>' in index


def test_imported_by_follows_a_change_in_another_file(tmp_path):
    _tree(tmp_path)
    out = _build(tmp_path)
    assert _links(_block((out / "Hub.lean.html").read_text(encoding="utf-8"), "imported-by")) == [("User.lean.html", "User.lean")]
    # User stops importing Hub: Hub's own source did not change, but its page must
    (tmp_path / "src" / "User.lean").write_text("theorem uses : 7 = 7 := rfl\n", encoding="utf-8")
    again = build_site(tmp_path / "src", out, Config(), tmp_path / "idx", jobs=1)
    assert not again.errors
    assert _block((out / "Hub.lean.html").read_text(encoding="utf-8"), "imported-by") is None


def test_imports_come_back_from_the_cache_and_from_worker_processes(tmp_path):
    _tree(tmp_path)
    first = _build(tmp_path, out="one")
    reused = _build(tmp_path, out="two")  # the index is read back from the cache
    workers = build_site(tmp_path / "src", tmp_path / "three", Config(), tmp_path / "idx3", jobs=2)
    assert not workers.errors
    for rel in ("Hub.lean.html", "P/Def.lean.html", "P/Deep/Leaf.lean.html", "User.lean.html"):
        expected = (first / rel).read_text(encoding="utf-8")
        assert (reused / rel).read_text(encoding="utf-8") == expected, rel
        assert (tmp_path / "three" / rel).read_text(encoding="utf-8") == expected, rel


def test_imports_can_be_shown_only_on_import_only_files_or_not_at_all(tmp_path):
    _tree(tmp_path)
    only = _build(tmp_path, Config(imports="import-only"), out="only")
    hub = (only / "Hub.lean.html").read_text(encoding="utf-8")
    assert _block(hub, "imports") is not None and _block(hub, "imported-by") is not None
    for rel in ("P/Def.lean.html", "User.lean.html"):
        page = (only / rel).read_text(encoding="utf-8")
        assert _block(page, "imports") is None and _block(page, "imported-by") is None, rel
    none = _build(tmp_path, Config(imports="none"), out="none")
    for rel in ("Hub.lean.html", "P/Def.lean.html"):
        page = (none / rel).read_text(encoding="utf-8")
        assert _block(page, "imports") is None and _block(page, "imported-by") is None, rel
    assert "No declarations listed." in (none / "Hub.lean.html").read_text(encoding="utf-8")


def test_the_imports_setting_is_checked(tmp_path):
    _tree(tmp_path)
    with pytest.raises(ExplainerError, match="imports"):
        build_site(tmp_path / "src", tmp_path / "out", Config(imports="some"), tmp_path / "idx", jobs=1)
    toml = tmp_path / "explainer.toml"
    toml.write_text('imports = "some"\n', encoding="utf-8")
    with pytest.raises(ExplainerError, match="'imports' must be"):
        load_config(toml)
    toml.write_text('imports = "import-only"\n', encoding="utf-8")
    assert load_config(toml).imports == "import-only"


def test_guillemet_module_names_find_their_file(tmp_path):
    _tree(tmp_path, user="import «P».«Def»\n\ntheorem uses : Kc = 7 := rfl\n")
    out = _build(tmp_path)
    page = (out / "User.lean.html").read_text(encoding="utf-8")
    assert _links(_block(page, "imports")) == [("P/Def.lean.html", "«P».«Def»")]
