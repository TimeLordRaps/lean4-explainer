from lean4_explainer.scan import parse_source


def declarations(text):
    return parse_source(text, "x.lean").declarations


def names(text):
    return [decl.name for decl in declarations(text)]


def test_declarations_are_qualified_by_namespace():
    text = "namespace Foo.Bar\n\ntheorem baz : True := trivial\n\nend Foo.Bar\n\ndef top : Nat := 0\n"
    assert names(text) == ["Foo.Bar.baz", "top"]


def test_namespace_end_restores_scope():
    text = "namespace A\nend A\ntheorem t : True := trivial\n"
    assert names(text) == ["t"]


def test_attributes_and_modifiers_are_skipped():
    text = "@[simp] private theorem t : True := trivial\n@[simp]\nlemma u : True := trivial\n"
    assert names(text) == ["t", "u"]
    assert [decl.kind for decl in declarations(text)] == ["theorem", "lemma"]


def test_comments_and_strings_do_not_create_declarations_or_sorry():
    text = '-- theorem fake : True := sorry\n/- theorem fake2 := sorry -/\ndef s : String := "sorry theorem fake3"\n'
    found = declarations(text)
    assert [decl.name for decl in found] == ["s"]
    assert found[0].has_sorry is False


def test_nested_block_comments_hide_their_contents():
    text = "/- outer /- inner -/ still comment theorem hidden := sorry -/\ntheorem seen : True := trivial\n"
    assert names(text) == ["seen"]


def test_sorry_flag_is_per_declaration():
    text = "theorem a : True := by\n  sorry\n\ntheorem b : True := trivial\n"
    found = declarations(text)
    assert [(decl.name, decl.has_sorry) for decl in found] == [("a", True), ("b", False)]






def test_statement_stops_at_assignment_and_marks_omitted_proof():
    text = "/-- Doc. -/\ntheorem t (n : Nat) : n + 0 = n := by\n  simp\n  rfl\n"
    assert declarations(text)[0].statement == "theorem t (n : Nat) : n + 0 = n := by\n…"


def test_char_literal_quote_does_not_open_a_string():
    text = "def q : Char := '\"'\ntheorem after : True := trivial\n"
    assert names(text) == ["q", "after"]


def test_crlf_line_endings_are_normalized():
    text = "theorem a : True := trivial\r\ntheorem b : True := trivial\r\n"
    found = declarations(text)
    assert [decl.name for decl in found] == ["a", "b"]
    assert "\r" not in found[0].statement


def test_indented_declarations_are_not_listed():
    assert names("namespace N\n  theorem hidden : True := trivial\n") == []


def test_imports_are_recorded():
    lean_file = parse_source("import Mathlib.Logic.Basic\nimport Foo\n\ndef x := 1\n", "x.lean")
    assert lean_file.imports == ("Mathlib.Logic.Basic", "Foo")


def test_module_system_imports_and_several_per_line_are_recorded():
    # most of the pinned corpora use Lean's module system: `module`, then `public import`, `meta import`, `import all`
    text = "module\n\npublic import A.B\npublic meta import C\nimport all D\nimport E F\nprivate import G\n\ndef x := 1\n"
    assert parse_source(text, "x.lean").imports == ("A.B", "C", "D", "E", "F", "G")


def test_plain_comment_is_used_when_no_doc_comment():
    decl = declarations("-- Adds one.\ndef inc (n : Nat) : Nat := n + 1\n")[0]
    assert decl.comment == "Adds one."
    assert decl.description == "Adds one."


def test_plain_comment_separated_by_blank_line_is_ignored():
    decl = declarations("-- Stray note.\n\ndef f : Nat := 0\n")[0]
    assert decl.comment is None
    assert decl.description is None


def test_doc_comment_takes_precedence_over_plain_comment():
    decl = declarations("-- Note.\n/-- Doc. -/\ndef g : Nat := 0\n")[0]
    assert decl.description == "Doc."
    assert decl.comment == "Note."


def test_consecutive_line_comments_join():
    decl = declarations("-- one\n-- two\ndef h : Nat := 0\n")[0]
    assert decl.comment == "one\ntwo"


def test_extra_kinds_list_a_project_specific_declaration_keyword():
    source = "namespace P\n\nproblem p1 : True := trivial\n\ntheorem t : True := trivial\n"

    plain = parse_source(source, "P.lean")
    extra = parse_source(source, "P.lean", extra_kinds=("problem",))

    assert [d.name for d in plain.declarations] == ["P.t"]
    assert [(d.kind, d.name) for d in extra.declarations] == [("problem", "P.p1"), ("theorem", "P.t")]


def test_class_inductive_is_one_kind_and_keeps_its_name():
    # Carleson's `class inductive CoveredByBalls …` was listed as a class named `inductive`
    found = declarations("class inductive Covered (n : Nat) : Prop where\n  | mk : Covered n\n\nclass  inductive  Two : Prop\n  | a\n\nclass inductiveish : Type\n")
    assert [(d.kind, d.name) for d in found] == [("class inductive", "Covered"), ("class inductive", "Two"), ("class", "inductiveish")]


def test_extra_kinds_do_not_match_longer_words():
    source = "problems : Nat := 1\nproblem_x : Nat := 2\n"

    assert not parse_source(source, "P.lean", extra_kinds=("problem",)).declarations
