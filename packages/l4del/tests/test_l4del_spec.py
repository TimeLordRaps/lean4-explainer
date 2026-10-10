from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer_l4del.grammar import normalize_directive
from lean4_explainer.scan import parse_source
from lean4_explainer_l4del.templates import annotation_state, notes_of, placeholder_block


def issues(text):
    lean_file = parse_source(text, "a.lean")
    found = [str(d) for d in lean_file.diagnostics.get("l4del", ())]
    for decl in lean_file.declarations:
        found += [str(d) for d in notes_of(decl).diagnostics]
    return found


def _tree(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_clean_annotation_has_no_issues():
    text = (
        "/-- Doc. -/\n"
        "-- L4DEL: title: Pigeonhole\n"
        "-- L4DEL: intuition: Two items share a box.\n"
        "-- L4DEL: step: Count the boxes.\n"
        "-- L4DEL: term: box = a container\n"
        "theorem t : True := trivial\n"
    )
    assert issues(text) == []


def test_keys_are_case_sensitive():
    assert issues("-- L4DEL: Title: X\ntheorem t : True := trivial\n") == ["error: line 1: unknown key: Title"]


def test_title_given_twice_is_error():
    text = "-- L4DEL: title: A\n-- L4DEL: title: B\ntheorem t : True := trivial\n"
    assert any("title given twice" in message for message in issues(text))


def test_empty_value_is_error():
    assert issues("-- L4DEL: title:\ntheorem t : True := trivial\n") == [
        "error: line 1: empty value for title"
    ]


def test_prereq_names_must_be_single_tokens():
    assert issues("-- L4DEL: prereq: A B\ntheorem t : True := trivial\n") == [
        "error: line 1: invalid name in prereq: 'A B'"
    ]


def test_repeated_name_is_error():
    assert issues("-- L4DEL: prereq: A.b, A.b\ntheorem t : True := trivial\n") == [
        "error: line 1: name 'A.b' repeated in prereq"
    ]


def test_space_before_directive_is_required():
    assert issues("-- L4DEL:title: X\ntheorem t : True := trivial\n") == [
        "error: line 1: L4DEL: needs a space before the directive"
    ]


def test_block_carrier_is_error():
    assert issues("/- L4DEL: title: X -/\ntheorem t : True := trivial\n") == [
        "error: line 1: L4DEL is allowed only in line comments"
    ]


def test_doc_comment_carrier_is_error():
    assert issues("/-- L4DEL: title: X -/\ntheorem t : True := trivial\n") == [
        "error: line 1: L4DEL is allowed only in line comments"
    ]


def test_orphan_directive_is_error():
    text = "-- L4DEL: title: X\nopen Nat\ntheorem t : True := trivial\n"
    assert issues(text) == ["error: line 1: orphan L4DEL directive: no declaration follows it"]


def test_directive_crosses_blank_and_attribute_lines():
    text = "-- L4DEL: title: X\n\n@[simp]\ntheorem t : True := trivial\n"
    lean_file = parse_source(text, "a.lean")
    assert lean_file.diagnostics == {"l4del": ()}
    assert lean_file.declarations[0].ext["l4del"].title == "X"


def test_anonymous_declaration_rejects_directive():
    assert issues("-- L4DEL: title: X\nexample : True := trivial\n") == [
        "error: line 1: anonymous declarations cannot carry L4DEL"
    ]


def test_placeholder_is_a_warning():
    assert issues("-- L4DEL: title: TODO_short_result_name\ntheorem t : True := trivial\n") == [
        "warning: line 1: placeholder left in title; replace the TODO_ text"
    ]


def test_value_length_limit():
    text = "-- L4DEL: intuition: " + "x" * 2001 + "\ntheorem t : True := trivial\n"
    assert issues(text) == ["error: line 1: value is longer than 2000 characters"]


def test_unicode_is_normalized_to_nfc():
    text = "-- L4DEL: title: cafe\u0301\ntheorem t : True := trivial\n"
    assert parse_source(text, "a.lean").declarations[0].ext["l4del"].title == "caf\u00e9"
    assert normalize_directive("  e\u0301  ") == "\u00e9"


def test_unannotated_declaration_state_and_valid_template():
    text = "theorem t : True := trivial\n"
    decl = parse_source(text, "a.lean").declarations[0]
    assert annotation_state(decl) == "unannotated"
    block = placeholder_block(decl, {})
    parsed = parse_source(block + "\ntheorem t : True := trivial\n", "a.lean").declarations[0]
    assert [d.severity for d in notes_of(parsed).diagnostics] == ["warning"] * 4
    assert all("placeholder" in d.message for d in notes_of(parsed).diagnostics)


def test_ambiguous_reference_is_error(tmp_path):
    _tree(
        tmp_path / "lean",
        {
            "A.lean": "namespace Demo\ndef x : Nat := 1\nend Demo\n",
            "B.lean": "namespace Demo\ndef x : Nat := 2\nend Demo\n",
            "C.lean": "-- L4DEL: prereq: Demo.x\ntheorem y : True := trivial\n",
        },
    )
    summary = build_site(tmp_path / "lean", tmp_path / "docs")
    assert any("ambiguous" in message for message in summary.errors)


def test_exact_names_only_for_references(tmp_path):
    _tree(
        tmp_path / "lean",
        {
            "A.lean": "namespace Demo\ndef x : Nat := 1\nend Demo\n",
            "B.lean": "namespace Demo\n-- L4DEL: prereq: x\ntheorem y : True := trivial\nend Demo\n",
        },
    )
    summary = build_site(tmp_path / "lean", tmp_path / "docs")
    assert summary.errors == ()
    assert any("unresolved reference x" in message for message in summary.warnings)


def test_prerequisite_cycle_is_error(tmp_path):
    _tree(
        tmp_path / "lean",
        {
            "A.lean": "namespace Demo\n-- L4DEL: title: X\n-- L4DEL: prereq: Demo.y\ntheorem x : True := trivial\nend Demo\n",
            "B.lean": "namespace Demo\n-- L4DEL: title: Y\n-- L4DEL: prereq: Demo.x\ntheorem y : True := trivial\nend Demo\n",
        },
    )
    summary = build_site(tmp_path / "lean", tmp_path / "docs")
    assert any("prerequisite cycle" in message for message in summary.errors)


def test_term_defined_twice_across_files_is_error(tmp_path):
    _tree(
        tmp_path / "lean",
        {
            "A.lean": "-- L4DEL: term: box = a container\ntheorem a : True := trivial\n",
            "B.lean": "-- L4DEL: term: box = another thing\ntheorem b : True := trivial\n",
        },
    )
    summary = build_site(tmp_path / "lean", tmp_path / "docs", Config())
    assert any("already defined" in message for message in summary.errors)
