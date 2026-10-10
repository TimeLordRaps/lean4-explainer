"""The extension interface, exercised with a toy extension. The core must also work with none installed."""

import pickle
from dataclasses import dataclass

import pytest

from lean4_explainer import cli, extensions
from lean4_explainer.build import build_site
from lean4_explainer.cache import Cache, FileIndex, load_cache, save_cache
from lean4_explainer.config import Config, load_config
from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import Diagnostic, Extension, ParseResult
from lean4_explainer.scan import parse_source


@dataclass(frozen=True)
class Tag:
    text: str


@dataclass(frozen=True)
class TagSummary:
    tags: tuple[str, ...]


class TagExtension(Extension):
    """Reads `-- TAG: text` line comments."""

    name = "tag"
    version = "1"
    cache_types = frozenset({(Tag.__module__, "Tag"), (TagSummary.__module__, "TagSummary")})
    config_keys = {"tag_color": str}

    def hides_comment(self, body):
        return body.strip().startswith("TAG:")

    def is_described(self, payload):
        return True

    def parse(self, view):
        found = {}
        for comment in view.comments:
            if comment.kind == "line" and comment.body.strip().startswith("TAG:"):
                following = next((h for h in view.heads if h.index >= comment.start_line), None)
                if following:
                    found[following.index] = Tag(comment.body.strip()[4:].strip())
        return ParseResult(found, [Diagnostic("warning", 1, "toy diagnostic")] if found else [])

    def index_file(self, path, declarations, diagnostics):
        tags = tuple(d.ext["tag"].text for d in declarations if "tag" in d.ext)
        return TagSummary(tags) if tags else None

    def issues(self, path, summary):
        return [f"warning: {path}: {len(summary.tags)} tag(s)"]

    def analyze(self, objects, summaries, options):
        return {"total": sum(len(s.tags) for s in summaries.values() if s), "color": options.get("tag_color")}

    def declaration_title(self, decl, payload):
        return f' <span class="tag">{payload.text}</span>'

    def declaration_blocks(self, decl, payload, rel, dirs, ctx, analysis):
        return '<p class="tag-top">top</p>', '<p class="tag-bottom">bottom</p>'

    def pages(self, ctx, analysis):
        return {"tags.html": f"<html>tags: {analysis['total']}</html>"}

    def nav_links(self, up, options):
        return [("Tags", f"{up}tags.html")]

    def css(self, options):
        return ".tag { color: red; }\n"

    def status(self, analysis):
        return f"{analysis['total']} tags."

    def summary(self, analysis):
        return [f"tag extension saw {analysis['total']} tags"]

    def register_cli(self, commands):
        commands.add_parser("tagcount", help="toy")

    def run_cli(self, args):
        if args.command == "tagcount":
            print("tagcount ran")
            return 0
        return None


SOURCE = "-- TAG: first\ntheorem a : True := trivial\n\ntheorem b : True := trivial\n"


@pytest.fixture
def lean(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "A.lean").write_text(SOURCE, encoding="utf-8")
    return root


@pytest.fixture
def tagged():
    extensions.activate([TagExtension()])
    yield
    extensions.activate([])


def test_the_core_builds_a_complete_site_with_no_extension(tmp_path, lean):
    out = tmp_path / "docs"

    summary = build_site(lean, out)

    page = (out / "A.lean.html").read_text(encoding="utf-8")
    assert "theorem" in page and "<code>a</code>" in page
    assert summary.extension_lines == ()
    assert not (out / "tags.html").exists()


def test_without_the_extension_its_comment_syntax_is_an_ordinary_comment(tmp_path, lean):
    decl = parse_source(SOURCE, "A.lean").declarations[0]

    assert decl.comment == "TAG: first"  # shown like any plain comment
    assert decl.ext == {}


def test_extension_parses_and_hides_its_comments(tagged):
    decl = parse_source(SOURCE, "A.lean").declarations[0]

    assert decl.comment is None  # hidden from the plain-comment description
    assert decl.ext["tag"] == Tag("first")
    assert "tag" not in parse_source(SOURCE, "A.lean").declarations[1].ext


def test_extension_adds_blocks_pages_nav_css_and_status(tagged, tmp_path, lean):
    out = tmp_path / "docs"

    summary = build_site(lean, out, Config(options=(("tag_color", "red"),)))

    page = (out / "A.lean.html").read_text(encoding="utf-8")
    assert '<span class="tag">first</span>' in page
    assert page.index("tag-top") < page.index("tag-bottom")
    assert 'href="tags.html">Tags<' in page
    assert (out / "tags.html").read_text(encoding="utf-8") == "<html>tags: 1</html>"
    assert ".tag { color: red; }" in (out / "_assets" / "site.css").read_text(encoding="utf-8")
    assert "1 tags." in (out / "index.html").read_text(encoding="utf-8")
    assert summary.extension_lines == ("tag extension saw 1 tags",)
    assert any("1 tag(s)" in warning for warning in summary.warnings)


def test_extension_described_declarations_are_searchable_and_show_statements(tagged, tmp_path, lean):
    out = tmp_path / "docs"

    build_site(lean, out)

    shards = "".join(p.read_text(encoding="utf-8") for p in (out / "_assets" / "search").glob("s_*.js"))
    assert '"a"' in shards  # described through the extension
    assert '"b"' not in shards


def test_extension_config_keys_are_accepted_and_typed(tagged, tmp_path):
    good = tmp_path / "good.toml"
    good.write_text('tag_color = "blue"\n', encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text("tag_color = 3\n", encoding="utf-8")

    assert dict(load_config(good).options) == {"tag_color": "blue"}
    with pytest.raises(ExplainerError):
        load_config(bad)


def test_extension_config_keys_are_unknown_without_the_extension(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('tag_color = "blue"\n', encoding="utf-8")

    with pytest.raises(ExplainerError):
        load_config(path)


def test_installed_extensions_change_the_cache_key(tagged, tmp_path, lean):
    out = tmp_path / "docs"
    build_site(lean, out)

    extensions.activate([])
    summary = build_site(lean, out)

    assert summary.pages_written == 1  # a different extension set is a full rebuild, not a reuse


def test_extension_summaries_in_the_cache_are_loaded_only_if_the_extension_listed_them(tagged, tmp_path):
    path = tmp_path / "index.pickle"
    cache = Cache("f")
    cache.files["A.lean"] = FileIndex(
        sha="x", declarations=0, sorry=0, axioms=0, names="", lines=None, codes=None, headers=None,
        diagnostics=(), ext=(("tag", TagSummary(("a",))),),
    )
    save_cache(path, cache)

    assert load_cache(path, "f").files["A.lean"].ext[0][1] == TagSummary(("a",))

    extensions.activate([])  # the type is no longer allowed
    assert load_cache(path, "f").files == {}


def test_a_planted_cache_cannot_use_an_extension_to_run_code(tagged, tmp_path):
    class Boom:
        def __reduce__(self):
            import os

            return (os.mkdir, (str(tmp_path / "pwned"),))

    path = tmp_path / "index.pickle"
    path.write_bytes(pickle.dumps(Boom()))

    load_cache(path, "f")

    assert not (tmp_path / "pwned").exists()


def test_extension_adds_cli_commands_and_core_reports_unclaimed_ones(tagged, capsys):
    assert cli.main(["tagcount"]) == 0
    assert "tagcount ran" in capsys.readouterr().out


def test_extensions_command_lists_what_is_active(tagged, capsys):
    assert cli.main(["extensions"]) == 0
    assert "tag 1" in capsys.readouterr().out


def test_bare_command_with_no_extension_prints_help(capsys):
    assert cli.main([]) == 2
    assert "build" in capsys.readouterr().out


def test_a_broken_extension_does_not_stop_discovery(monkeypatch, capsys):
    class Entry:
        name = "broken"

        def load(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(extensions.metadata, "entry_points", lambda group: [Entry()])
    extensions.activate(None)
    extensions._discover.cache_clear()
    try:
        assert extensions.extensions() == ()
    finally:
        extensions._discover.cache_clear()
        extensions.activate([])
    assert "broken" in capsys.readouterr().err



def test_notice_says_lean_was_not_run_unless_an_extension_runs_it(tmp_path, capsys):
    root = tmp_path / "src"
    root.mkdir()
    (root / "A.lean").write_text("def x : Nat := 1\n", encoding="utf-8")

    cli.main(["build", "--lean-root", str(root), "--out", str(tmp_path / "plain")])
    plain = (tmp_path / "plain" / "index.html").read_text(encoding="utf-8")
    assert "Lean was not run" in plain and "Lean not run" in capsys.readouterr().out

    class Runner(Extension):
        name = "runner"
        version = "1"
        runs_lean = True

    extensions.activate([Runner()])
    cli.main(["build", "--lean-root", str(root), "--out", str(tmp_path / "ran")])
    ran = (tmp_path / "ran" / "index.html").read_text(encoding="utf-8")
    assert "Lean was not run" not in ran and "Trust page" in ran
    assert "Lean not run" not in capsys.readouterr().out


def test_parse_hook_sees_the_site_options(tmp_path):
    seen = []

    class Spy(Extension):
        name = "spy"
        version = "1"
        config_keys = {"flavor": str}

        def parse(self, view):
            seen.append((view.path, dict(view.options)))

    extensions.activate([Spy()])
    root = tmp_path / "src"
    root.mkdir()
    (root / "A.lean").write_text("def x : Nat := 1\n", encoding="utf-8")
    build_site(root, tmp_path / "out", Config(options=(("flavor", "mint"),)), tmp_path / "idx")

    assert seen and all(item == ("A.lean", {"flavor": "mint"}) for item in seen)  # indexing and rendering both get them


class FileLevelExtension(Extension):
    name = "filelevel"

    def file_blocks(self, lean_file, text, ctx, analysis):
        return f'<div class="whole">{len(text)} chars of {lean_file.path}</div>'

    def scripts(self, options):
        return ("_assets/extra.js",)


def test_extension_adds_a_file_level_block_with_the_source_text_and_page_scripts(tmp_path):
    root = tmp_path / "lean"
    (root / "Sub").mkdir(parents=True)
    (root / "Sub" / "A.lean").write_text(SOURCE, encoding="utf-8")
    extensions.activate([FileLevelExtension()])
    try:
        build_site(root, tmp_path / "docs")
    finally:
        extensions.activate([])
    page = (tmp_path / "docs" / "Sub" / "A.lean.html").read_text(encoding="utf-8")
    assert f'<div class="whole">{len(SOURCE.replace(chr(13), ""))} chars of Sub/A.lean</div>' in page
    assert '<script src="../_assets/extra.js" defer></script>' in page
    assert '<script src="../_assets/extra.js" defer></script>' in (tmp_path / "docs" / "Sub" / "index.html").read_text(encoding="utf-8")
