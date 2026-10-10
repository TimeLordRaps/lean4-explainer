"""L4DEL notes found by the scanner."""

from lean4_explainer.scan import parse_source


def declarations(text):
    return parse_source(text, "T.lean").declarations


def test_doc_and_line_l4del_attach_to_next_declaration():
    text = "/-- The main fact. -/\n-- L4DEL: intuition: Claim P holds.\ntheorem main : True := trivial\n"
    decl = declarations(text)[0]
    assert decl.doc == "The main fact."
    assert decl.ext["l4del"].intuition == "Claim P holds."


def test_module_doc_and_line_directive():
    text = "/-! Module overview. -/\n-- L4DEL: title: Scope note\ndef f : Nat := 0\n"
    lean_file = parse_source(text, "x.lean")
    assert lean_file.module_doc == "Module overview."
    assert lean_file.declarations[0].ext["l4del"].title == "Scope note"
    assert lean_file.declarations[0].doc is None
    assert lean_file.diagnostics == {"l4del": ()}


def test_l4del_is_absent_by_default():
    decl = declarations("/-- Doc. -/\ntheorem t : True := trivial\n")[0]
    assert "l4del" not in decl.ext
