"""A subsite inside a showcase links back to the landing page; a standalone site does not."""

from lean4_explainer.build import build_site
from lean4_explainer.config import Config


def _tree(tmp_path):
    root = tmp_path / "lean"
    (root / "Sub").mkdir(parents=True)
    (root / "Sub" / "A.lean").write_text("theorem a : True := trivial\n", encoding="utf-8")
    return root


def test_home_link_reaches_every_page_depth(tmp_path):
    root = _tree(tmp_path)
    out = tmp_path / "site" / "demo"

    build_site(root, out, Config(home="../index.html"))

    assert 'href="../index.html">All corpora<' in (out / "index.html").read_text(encoding="utf-8")
    assert 'href="../../index.html">All corpora<' in (out / "Sub" / "A.lean.html").read_text(encoding="utf-8")


def test_no_home_link_by_default(tmp_path):
    out = tmp_path / "docs"

    build_site(_tree(tmp_path), out)

    assert "All corpora" not in (out / "index.html").read_text(encoding="utf-8")
