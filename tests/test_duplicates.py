from pathlib import Path

from lean4_explainer.build import build_site
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
