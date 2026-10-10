import pytest

from lean4_explainer.build import build_site
from lean4_explainer.cache import Note
from lean4_explainer.config import Config, load_config
from lean4_explainer.errors import ExplainerError
from lean4_explainer.graph import build_glossary, build_learning_path, resolve, unresolved_links
from lean4_explainer.objects import plain_objects
from lean4_explainer.l4del import parse_l4del
from lean4_explainer.render import file_page, term_pattern
from lean4_explainer.scan import parse_source
from lean4_explainer.search import shard_key, write_search


def _note(name, rel, line, title=None, prereqs=(), terms=()):
    return Note(name=name, rel=rel, line=line, title=title, prereqs=tuple(prereqs), see=(), terms=tuple(terms))


def _tree(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_l4del_structured_keys():
    notes = parse_l4del(
        [
            (1, "title: Pigeonhole"),
            (2, "intuition: Boxes and balls."),
            (3, "step: Count."),
            (4, "step: Compare."),
            (5, "prereq: A.b, C.d"),
            (6, "see: E.f"),
            (7, "term: box = a container"),
        ]
    )
    assert notes.title == "Pigeonhole"
    assert notes.intuition == "Boxes and balls."
    assert notes.steps == ("Count.", "Compare.")
    assert notes.prereqs == ("A.b", "C.d")
    assert notes.see == ("E.f",)
    assert notes.terms == (("box", "a container"),)
    assert notes.diagnostics == ()


def test_l4del_bad_directives_are_errors():
    notes = parse_l4del([(1, "colour: blue"), (2, "no colon here"), (3, "term: missing equals"), (4, "prereq:")])
    assert [str(d) for d in notes.diagnostics] == [
        "error: line 1: unknown key: colour",
        "error: line 2: malformed directive: no colon here",
        "error: line 3: term needs the form 'word = definition'",
        "error: line 4: empty value for prereq",
    ]


def test_config_rejects_unknown_key(tmp_path):
    path = tmp_path / "lean4-explainer.toml"
    path.write_text('colour = "blue"\n', encoding="utf-8")
    with pytest.raises(ExplainerError, match="unknown config keys"):
        load_config(path)


def test_config_rejects_wrong_type(tmp_path):
    path = tmp_path / "lean4-explainer.toml"
    path.write_text('search = "yes"\n', encoding="utf-8")
    with pytest.raises(ExplainerError, match="must be bool"):
        load_config(path)


def test_config_loads_values(tmp_path):
    path = tmp_path / "lean4-explainer.toml"
    path.write_text('title = "Demo"\nexclude = ["Scratch/*"]\nsearch = false\nbyte_budget = 5000\n', encoding="utf-8")
    config = load_config(path)
    assert config.title == "Demo"
    assert config.exclude == ("Scratch/*",)
    assert config.search is False
    assert config.byte_budget == 5000


def test_search_shards_group_names_by_prefix():
    written = {}

    def write(parts, text):
        written["/".join(parts)] = text
        return len(text.encode("utf-8"))

    locations = {"Nat.add": ("a.lean", 1), "Nat.sub": ("a.lean", 2), "Foo.x": ("b/c.lean", 3)}
    entries, total = write_search(locations, write)
    assert entries == 3
    assert shard_key("Nat.add") == "na"
    assert '"Nat.add"' in written["_assets/search/s_na.js"]
    assert '"Nat.sub"' in written["_assets/search/s_na.js"]
    assert "b/c.lean.html" in written["_assets/search/files.js"]
    assert total == sum(len(text.encode("utf-8")) for text in written.values())


def test_learning_path_puts_prerequisites_first():
    locations = {"A.basic": ("a.lean", 1), "A.next": ("a.lean", 5)}
    notes = [
        _note("A.next", "a.lean", 5, title="Next", prereqs=("A.basic",)),
        _note("A.basic", "a.lean", 1, title="Basics"),
    ]
    steps, issues = build_learning_path(notes, plain_objects(locations))
    assert [step.name for step in steps] == ["A.basic", "A.next"]
    assert steps[1].prereqs == ("A.basic",)
    assert issues == []


def test_learning_path_reports_cycles():
    locations = {"A.x": ("a.lean", 1), "A.y": ("a.lean", 2)}
    notes = [
        _note("A.x", "a.lean", 1, title="X", prereqs=("A.y",)),
        _note("A.y", "a.lean", 2, title="Y", prereqs=("A.x",)),
    ]
    steps, issues = build_learning_path(notes, plain_objects(locations))
    assert {step.name for step in steps} == {"A.x", "A.y"}
    assert any("cycle" in message for message in issues)


def test_unresolved_references_are_reported():
    notes = [_note("A.x", "a.lean", 1, title="X", prereqs=("Missing",))]
    assert unresolved_links(notes, plain_objects({"A.x": ("a.lean", 1)})) == [
        "warning: a.lean:1: unresolved reference Missing"
    ]


def test_resolve_prefers_innermost_namespace():
    locations = {"A.B.x": ("a.lean", 1), "x": ("a.lean", 2)}
    assert resolve("x", ["A", "B"], locations) == "A.B.x"
    assert resolve("x", ["A", "C"], locations) == "x"


def test_glossary_keeps_first_definition():
    notes = [
        _note("A.x", "a.lean", 1, terms=(("box", "first"),)),
        _note("A.y", "a.lean", 2, terms=(("box", "second"),)),
    ]
    terms, warnings = build_glossary(notes)
    assert terms["box"] == ("first", "A.x", ("a.lean", 1))
    assert len(warnings) == 1


def test_glossary_terms_are_linked_in_intuition(make_context):
    text = "/-- Doc. -/\n-- L4DEL: intuition: An empty set has no members.\ntheorem t : True := trivial\n"
    ctx = make_context(
        glossary={"empty set": ("no members", "A.t", ("a.lean", 3))},
        term_anchors={"empty set": "t0"},
        term_pattern=term_pattern(["empty set"]),
    )
    html = file_page(parse_source(text, "a.lean"), ctx)
    assert '<a class="term" href="glossary.html#t0">empty set</a>' in html


def test_statement_mentions_link_to_declarations(make_context):
    text = "theorem helper : True := trivial\n\n/-- Uses the helper. -/\ntheorem user (h : helper) : True := trivial\n"
    ctx = make_context(locations={"helper": ("a.lean", 1), "user": ("a.lean", 4)})
    html = file_page(parse_source(text, "a.lean"), ctx)
    assert "Mentions: " in html
    assert 'href="a.lean.html#L1"' in html


def test_source_links_use_template(make_context):
    ctx = make_context(source_url="https://example.com/src/{path}#L{line}?ref={ref}", source_ref="v1")
    html = file_page(parse_source("def f : Nat := 0\n", "a.lean"), ctx)
    assert 'href="https://example.com/src/a.lean#L1?ref=v1"' in html


def test_second_build_reuses_every_page(tmp_path):
    lean = tmp_path / "lean"
    _tree(lean, {"A.lean": "def a : Nat := 1\n", "B.lean": "def b : Nat := 2\n"})
    out = tmp_path / "docs"
    first = build_site(lean, out)
    assert (first.pages_written, first.pages_reused) == (2, 0)
    second = build_site(lean, out)
    assert (second.pages_written, second.pages_reused) == (0, 2)


def test_body_edit_rerenders_only_that_page(tmp_path):
    lean = tmp_path / "lean"
    _tree(lean, {"A.lean": "def a : Nat := 1\n", "B.lean": "def b : Nat := 2\n"})
    out = tmp_path / "docs"
    build_site(lean, out)
    _tree(lean, {"A.lean": "def a : Nat := 1 + 0\n"})
    summary = build_site(lean, out)
    assert (summary.pages_written, summary.pages_reused) == (1, 1)


def test_new_declaration_rerenders_every_page(tmp_path):
    lean = tmp_path / "lean"
    _tree(lean, {"A.lean": "def a : Nat := 1\n", "B.lean": "def b : Nat := 2\n"})
    out = tmp_path / "docs"
    build_site(lean, out)
    _tree(lean, {"B.lean": "def b : Nat := 2\ndef c : Nat := 3\n"})
    summary = build_site(lean, out)
    assert (summary.pages_written, summary.pages_reused) == (2, 0)


def test_build_collects_unresolved_reference_warning(tmp_path):
    lean = tmp_path / "lean"
    _tree(lean, {"A.lean": "-- L4DEL: see: Missing.thing\ndef a : Nat := 1\n"})
    summary = build_site(lean, tmp_path / "docs")
    assert any("unresolved reference Missing.thing" in message for message in summary.warnings)


def test_over_budget_is_flagged(tmp_path):
    lean = tmp_path / "lean"
    _tree(lean, {"A.lean": "def a : Nat := 1\n"})
    summary = build_site(lean, tmp_path / "docs", Config(byte_budget=10))
    assert summary.over_budget


def test_anonymous_declarations_are_not_indexed(tmp_path):
    lean = tmp_path / "lean"
    _tree(
        lean,
        {
            "A.lean": "namespace Nat\nexample : True := trivial\nend Nat\n",
            "B.lean": "namespace Nat\nexample : True := trivial\nend Nat\n",
        },
    )
    summary = build_site(lean, tmp_path / "docs")
    assert not any("duplicate declaration" in message for message in summary.warnings)
