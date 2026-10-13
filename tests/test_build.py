import pytest

from lean4_explainer.build import ExplainerError, build_site
from lean4_explainer.cli import main
from lean4_explainer.extensions import Extension
from lean4_explainer.render import SITE_CSS, SITE_JS, default_context, file_page, search_page
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


def test_filter_targets_structural_rows_without_repeating_an_attribute_per_declaration():
    html = file_page(parse_source("theorem t : True := trivial\n", "a.lean"))
    assert "data-filterable" not in html
    assert "data-filter-rows" in html
    assert "[data-filter-rows] > li" in SITE_JS
    assert "[data-filter-rows] > div" in SITE_JS
    assert 'aria-label="Filter declarations"' in html
    assert "No matches." in SITE_JS


def test_file_path_is_a_linked_hierarchy_as_well_as_a_breadcrumb():
    html = file_page(parse_source("theorem t : True := trivial\n", "FLT/AutomorphicForm/Abstract.lean"))

    assert '<nav class="crumbs" aria-label="Breadcrumb">' in html
    assert '>Corpus home</a> / <a href="../index.html">FLT</a>' in html
    assert '<h1 class="path-title"><code><a href="../index.html">FLT</a>/<a href="index.html">AutomorphicForm</a>/<span>Abstract.lean</span></code></h1>' in html
    assert "scroll-margin-top" in SITE_CSS  # sticky navigation must not cover a declaration reached by #L123


def test_search_explains_word_search_and_has_an_accessible_status():
    html = search_page(default_context())

    assert '<label for="q">Search declarations</label>' in html
    assert 'aria-describedby="search-help search-status"' in html
    assert 'id="search-status"' in html and 'aria-live="polite"' in html
    assert "Matches words anywhere in qualified names" in html
    assert ".every(function (word)" in SITE_JS
    assert 'new URLSearchParams(window.location.search).get("q")' in SITE_JS
    assert 'url.searchParams.set("q", value)' in SITE_JS


def test_pages_have_metadata_skip_navigation_and_compact_file_pages(make_context):
    ctx = make_context(
        site_url="https://example.org/proofs/",
        description="A trustworthy Lean proof explorer.",
        project_url="https://github.com/example/project",
        report_url="https://github.com/example/site/issues/new",
    )

    html = file_page(parse_source("theorem t : True := trivial\n", "A.lean"), ctx)

    assert '<meta name="description"' not in html  # generic metadata stays on richer navigation/feature pages
    assert '<link rel="canonical" href="https://example.org/proofs/A.lean.html">' in html
    assert '<link rel="icon"' not in html
    assert '<body data-root=' not in html
    assert ">\n<" not in html
    assert '<a class="skip-link" href="#content">Skip to content</a>' in html
    assert '<main id="content" tabindex="-1">' in html
    assert '<meta property="og:title"' not in html and '<meta name="twitter:card"' not in html
    assert ">Project source</a>" not in html and ">Report a site issue</a>" not in html

    feature = search_page(ctx)
    assert '<meta name="description" content="Search declarations in Test.">' in feature
    assert '<link rel="icon"' in feature and '<body data-root="">' in feature
    assert '<meta property="og:title" content="Search — Test">' in feature
    assert '<meta name="twitter:card" content="summary">' in feature
    assert ">Project source</a>" in feature and ">Report a site issue</a>" in feature


def test_an_extension_can_promote_an_important_file_to_full_share_metadata(make_context):
    class Promoter(Extension):
        def promote_file_page(self, lean_file):
            return True

    ctx = make_context(
        site_url="https://example.org/proofs/",
        project_url="https://github.com/example/project",
        extensions=((Promoter(), None),),
    )

    html = file_page(parse_source("theorem t : True := trivial\n", "A.lean"), ctx)

    assert '<meta property="og:title" content="A.lean — Test">' in html
    assert '<meta name="twitter:card" content="summary">' in html
    assert ">Project source</a>" in html


def test_declaration_rows_keep_text_and_anchors_with_thirty_fewer_bytes_of_markup():
    html = file_page(parse_source("theorem t : True := trivial\n", "a.lean"))
    old = '<li id="L1"><span class="kind">theorem</span> <code>t</code> <span class="ln">line 1</span>'
    compact = '<li id=L1><b>theorem</b> <code>t</code> <small>line 1</small>'

    assert compact in html
    assert old not in html
    assert len(old.encode()) - len(compact.encode()) == 30


def test_statement_shown_only_for_described_declarations():
    text = "theorem bare : True := trivial\n\n/-- Documented. -/\ntheorem described : True := trivial\n"
    html = file_page(parse_source(text, "a.lean"))
    bare_row = html.split("id=L1", 1)[1].split("</li>", 1)[0]
    described_row = html.split("id=L4", 1)[1].split("</li>", 1)[0]
    assert "<pre>" not in bare_row
    assert "<pre>" in described_row


def test_plain_comment_appears_as_description():
    html = file_page(parse_source("-- Adds one.\ndef inc (n : Nat) : Nat := n + 1\n", "a.lean"))
    assert '<div class="doc plain">Adds one.</div>' in html


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


def test_extra_kinds_come_from_the_config_and_change_the_cache_key(tmp_path):
    from lean4_explainer.config import Config

    root = tmp_path / "src"
    root.mkdir()
    (root / "A.lean").write_text("problem p1 : True := trivial\n", encoding="utf-8")

    plain = build_site(root, tmp_path / "o1", Config(), tmp_path / "idx")
    extra = build_site(root, tmp_path / "o2", Config(extra_kinds=("problem",)), tmp_path / "idx")  # same cache dir

    assert plain.declarations == 0 and extra.declarations == 1


def test_extra_kinds_config_key_is_validated(tmp_path):
    from lean4_explainer.config import load_config
    from lean4_explainer.errors import ExplainerError

    good = tmp_path / "ok.toml"
    good.write_text('extra_kinds = ["problem"]\n', encoding="utf-8")
    assert load_config(good).extra_kinds == ("problem",)
    for bad in ('extra_kinds = ["has space"]\n', 'extra_kinds = [1]\n', 'extra_kinds = "problem"\n'):
        path = tmp_path / "bad.toml"
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(ExplainerError):
            load_config(path)
