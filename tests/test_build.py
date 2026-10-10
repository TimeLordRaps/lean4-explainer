import pytest

from lean4_explainer.build import ExplainerError, build_site
from lean4_explainer.cli import main
from lean4_explainer.render import file_page
from lean4_explainer.scan import parse_source


def test_file_page_escapes_source_text():
    text = "/-- <script>alert(1)</script> -/\ntheorem t : True := trivial\n"
    html = file_page(parse_source(text, "a.lean"))
    assert "&lt;script&gt;alert(1)" in html
    assert "<script>alert" not in html


def test_pages_load_nothing_external():
    html = file_page(parse_source("theorem t : True := trivial\n", "a.lean"))
    assert "https://" not in html
    assert "http://" not in html


def test_statement_shown_only_for_described_declarations():
    text = "theorem bare : True := trivial\n\n/-- Documented. -/\ntheorem described : True := trivial\n"
    html = file_page(parse_source(text, "a.lean"))
    bare_row = html.split('id="L1"', 1)[1].split("</li>", 1)[0]
    described_row = html.split('id="L4"', 1)[1].split("</li>", 1)[0]
    assert "<pre>" not in bare_row
    assert "<pre>" in described_row


def test_plain_comment_appears_as_description():
    html = file_page(parse_source("-- Adds one.\ndef inc (n : Nat) : Nat := n + 1\n", "a.lean"))
    assert '<div class="doc">Adds one.</div>' in html


def test_build_writes_pages_for_files_and_folders(tmp_path):
    root = tmp_path / "lean"
    (root / "Sub").mkdir(parents=True)
    (root / "A.lean").write_text("theorem a : True := by\n  sorry\n", encoding="utf-8")
    (root / "Sub" / "B.lean").write_text("axiom ax : True\n", encoding="utf-8")
    (root / "Sub" / "index.lean").write_text("def i : Nat := 0\n", encoding="utf-8")
    out = tmp_path / "docs"

    summary = build_site(root, out)

    assert (summary.files, summary.declarations, summary.sorry, summary.axioms) == (3, 3, 1, 1)
    assert (out / "A.lean.html").is_file()
    assert (out / "Sub" / "B.lean.html").is_file()
    assert (out / "Sub" / "index.lean.html").is_file()
    assert (out / "Sub" / "index.html").is_file()
    assert (out / "index.html").is_file()
    assert (out / "_assets" / "site.css").is_file()
    assert (out / ".nojekyll").exists()
    assert 'href="Sub/index.html"' in (out / "index.html").read_text(encoding="utf-8")


def test_file_names_with_spaces_are_encoded_in_links(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "My File.lean").write_text("def x : Nat := 1\n", encoding="utf-8")
    out = tmp_path / "docs"
    build_site(root, out)
    assert (out / "My File.lean.html").is_file()
    assert 'href="My%20File.lean.html"' in (out / "index.html").read_text(encoding="utf-8")


def test_builds_without_any_l4del_notes(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "A.lean").write_text("/-- Doc only. -/\ntheorem a : True := trivial\n", encoding="utf-8")
    out = tmp_path / "docs"
    build_site(root, out)
    pages = list(out.rglob("*.html"))
    assert pages
    assert not any('class="l4del"' in page.read_text(encoding="utf-8") for page in pages)


def test_empty_tree_is_rejected(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(ExplainerError, match="no .lean files"):
        build_site(root, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_cli_returns_1_for_empty_tree(tmp_path, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    assert main(["build", "--lean-root", str(root), "--out", str(tmp_path / "o")]) == 1
    assert "no .lean files" in capsys.readouterr().err


def test_cli_build_reports_summary(tmp_path, capsys):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "A.lean").write_text("def x : Nat := 1\n", encoding="utf-8")
    assert main(["build", "--lean-root", str(root), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "1 declarations" in out
    assert "Lean not run" in out
