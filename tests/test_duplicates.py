from pathlib import Path

from lean4_explainer.build import build_site
from lean4_explainer.cache import Note
from lean4_explainer.graph import build_learning_path, merge_notes
from lean4_explainer.objects import Copy, build_objects, resolve_exact
from lean4_explainer.scan import parse_source


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _by_name(name: str, *copies: tuple[str, int, str, str]) -> dict[str, list[Copy]]:
    return {name: [Copy(rel, line, code, header) for rel, line, code, header in copies]}


def test_digests_ignore_comments_and_whitespace():
    first = parse_source("namespace Demo\ntheorem t : True := trivial\nend Demo\n", "a.lean").declarations[0]
    second = parse_source(
        "namespace Demo\n-- note\ntheorem t : True :=   trivial  -- done\nend Demo\n", "b.lean"
    ).declarations[0]
    assert first.code_digest == second.code_digest
    assert first.header_digest == second.header_digest


def test_digests_separate_bodies_and_headers():
    base = parse_source("def v : Nat := 1\n", "a.lean").declarations[0]
    body = parse_source("def v : Nat := 2\n", "b.lean").declarations[0]
    header = parse_source("def v : Int := 1\n", "c.lean").declarations[0]
    assert base.header_digest == body.header_digest
    assert base.code_digest != body.code_digest
    assert base.header_digest != header.header_digest


def test_identical_copies_are_one_object():
    objects = build_objects(_by_name("A.x", ("a.lean", 1, "c", "h"), ("b.lean", 3, "c", "h")))
    assert objects.locations == {"A.x": ("a.lean", 1)}
    assert objects.ambiguous == frozenset()
    assert objects.identical == 1
    assert resolve_exact("A.x", objects) == "A.x"
    assert resolve_exact("A.x@b.lean", objects) == "A.x"
    assert resolve_exact("A.x@c.lean", objects) is None


def test_distinct_definitions_need_a_qualified_name():
    objects = build_objects(_by_name("A.x", ("a.lean", 1, "c1", "h"), ("b.lean", 3, "c2", "h")))
    assert objects.ambiguous == frozenset({"A.x"})
    assert objects.locations == {"A.x@a.lean": ("a.lean", 1), "A.x@b.lean": ("b.lean", 3)}
    assert objects.variant == 1
    assert resolve_exact("A.x", objects) is None
    assert resolve_exact("A.x@b.lean", objects) == "A.x@b.lean"


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
    assert "Demo.value@Var/A.lean" in summary.errors[0] and "Demo.value@Var/B.lean" in summary.errors[0]
    learning = (tmp_path / "docs" / "learning-path.html").read_text(encoding="utf-8")
    assert "after Demo.value@Var/B.lean, Demo.same_fact" in learning
    same_page = (tmp_path / "docs" / "Same" / "A.lean.html").read_text(encoding="utf-8")
    assert "Copy/A.lean:2</a> (identical)" in same_page
    var_page = (tmp_path / "docs" / "Var" / "A.lean.html").read_text(encoding="utf-8")
    assert "Distinct definitions of this name" in var_page
    assert "(same statement, different proof or body)" in var_page


def test_parallel_build_matches_serial(tmp_path):
    _write(
        tmp_path / "lean",
        {
            "Same/A.lean": "namespace Demo\ntheorem same_fact : True := trivial\nend Demo\n",
            "Copy/A.lean": "namespace Demo\ntheorem same_fact : True :=   trivial\nend Demo\n",
            "Var/A.lean": "namespace Demo\ndef value : Nat := 1\nend Demo\n",
            "Var/B.lean": "namespace Demo\ndef value : Nat := 2\nend Demo\n",
        },
    )
    serial = build_site(tmp_path / "lean", tmp_path / "serial", jobs=1)
    parallel = build_site(tmp_path / "lean", tmp_path / "parallel", jobs=2)
    assert (serial.identical_names, serial.variant_names) == (parallel.identical_names, parallel.variant_names)
    for page in ("Same/A.lean.html", "Var/A.lean.html", "Var/B.lean.html", "Copy/A.lean.html"):
        assert (tmp_path / "serial" / page).read_bytes() == (tmp_path / "parallel" / page).read_bytes()
