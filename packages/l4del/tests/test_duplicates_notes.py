"""L4DEL notes on same-named declarations."""

from lean4_explainer.build import build_site
from lean4_explainer.objects import Copy, build_objects
from lean4_explainer_l4del.graph import build_learning_path, merge_notes
from lean4_explainer_l4del.model import Note


def _by_name(name, *copies):
    return {name: [Copy(rel, line, code, header) for rel, line, code, header in copies]}


def _write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

def test_learning_path_uses_qualified_keys_for_variants():
    objects = build_objects(
        {
            **_by_name("A.x", ("a.lean", 1, "c1", "h"), ("b.lean", 3, "c2", "h")),
            "A.y": [Copy("c.lean", 1, "d", "d")],
        }
    )
    notes = [
        Note("A.x", "b.lean", 3, "Second", (), (), ()),
        Note("A.x", "a.lean", 1, "First", (), (), ()),
        Note("A.y", "c.lean", 1, "Uses", ("A.x@a.lean",), (), ()),
    ]
    steps, issues = build_learning_path(notes, objects)
    assert issues == []
    assert [step.name for step in steps] == ["A.x@a.lean", "A.x@b.lean", "A.y"]
    assert steps[-1].prereqs == ("A.x@a.lean",)


def test_identical_copies_must_share_one_annotation():
    objects = build_objects(_by_name("A.x", ("a.lean", 1, "c", "h"), ("b.lean", 3, "c", "h")))
    notes = [Note("A.x", "a.lean", 1, "One", (), (), ()), Note("A.x", "b.lean", 3, "Two", (), (), ())]
    merged, issues = merge_notes(notes, objects)
    assert [note.rel for note in merged] == ["a.lean"]
    assert len(issues) == 1 and "differs from its copy at a.lean:1" in issues[0]


def test_identical_copies_with_the_same_annotation_merge_quietly():
    objects = build_objects(_by_name("A.x", ("a.lean", 1, "c", "h"), ("b.lean", 3, "c", "h")))
    notes = [Note("A.x", "a.lean", 1, "One", (), (), ()), Note("A.x", "b.lean", 3, "One", (), (), ())]
    merged, issues = merge_notes(notes, objects)
    assert len(merged) == 1
    assert issues == []


def test_build_collapses_copies_and_qualifies_variants(tmp_path):
    _write(
        tmp_path / "lean",
        {
            "Same/A.lean": "namespace Demo\ntheorem same_fact : True := trivial\nend Demo\n",
            "Copy/A.lean": "namespace Demo\ntheorem same_fact : True :=   trivial\nend Demo\n",
            "Var/A.lean": "namespace Demo\ndef value : Nat := 1\nend Demo\n",
            "Var/B.lean": "namespace Demo\ndef value : Nat := 2\nend Demo\n",
            "Var/C.lean": 'namespace Demo\ndef value : String := "two"\nend Demo\n',
            "Use/A.lean": "namespace Demo\n-- L4DEL: prereq: Demo.value\ntheorem use_plain : True := trivial\nend Demo\n",
            "Use/B.lean": (
                "namespace Demo\n"
                "-- L4DEL: prereq: Demo.value@Var/B.lean, Demo.same_fact\n"
                "-- L4DEL: title: Uses one variant\n"
                "theorem use_qualified : True := trivial\nend Demo\n"
            ),
        },
    )
    summary = build_site(tmp_path / "lean", tmp_path / "docs")
    assert summary.identical_names == 1
    assert summary.variant_names == 1
    assert summary.warnings == ()
    assert len(summary.errors) == 1
    assert "reference Demo.value is ambiguous" in summary.errors[0]
    assert all(f"Demo.value@Var/{name}.lean" in summary.errors[0] for name in ("A", "B", "C"))
    learning = (tmp_path / "docs" / "learning-path.html").read_text(encoding="utf-8")
    assert "after Demo.value@Var/B.lean, Demo.same_fact" in learning
    same_page = (tmp_path / "docs" / "Same" / "A.lean.html").read_text(encoding="utf-8")
    assert "Copy/A.lean:2</a> (same declaration text)" in same_page
    var_page = (tmp_path / "docs" / "Var" / "A.lean.html").read_text(encoding="utf-8")
    assert "Distinct definitions of this name" in var_page
    assert "(same statement text; different proof or body)" in var_page
    assert "Var/C.lean:2</a> (different declaration text)" in var_page
