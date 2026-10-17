from argparse import Namespace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_PATH = Path(__file__).parents[1] / "scripts" / "build_lean_catalogue.py"
_SPEC = spec_from_file_location("build_lean_catalogue", _PATH)
catalogue = module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(catalogue)


def test_catalogue_files_are_paired_deduplicated_and_module_safe(tmp_path):
    path = tmp_path / "formalization.yaml"
    path.write_text(
        "status:\n  main_results:\n"
        "    - declaration: A.main\n      file: A/Main.lean\n"
        "    - declaration: A.other\n      file: A/Main.lean\n"
        "    - declaration: B.main\n      file: B/Result.lean\n",
        encoding="utf-8",
    )

    assert catalogue.catalogue_files(path) == ("A/Main.lean", "B/Result.lean")
    assert catalogue.module_name("A/Main.lean") == "A.Main"


def test_smaller_missing_internal_closures_are_built_first(tmp_path):
    root = tmp_path / "source"
    output = tmp_path / "build"
    (root / "A").mkdir(parents=True)
    (root / "B").mkdir()
    (root / "A" / "Leaf.lean").write_text("import Mathlib\n", encoding="utf-8")
    (root / "A" / "Main.lean").write_text("import A.Leaf\n", encoding="utf-8")
    (root / "B" / "Main.lean").write_text("import Mathlib\n", encoding="utf-8")
    (output / "A").mkdir(parents=True)
    (output / "A" / "Leaf.olean").write_bytes(b"built")

    ordered = catalogue.order_by_missing_closure(root, output, ("A/Main.lean", "B/Main.lean"))

    assert ordered == ["B/Main.lean", "A/Main.lean"]  # both miss one; the smaller total closure wins


def test_a_target_is_not_complete_when_an_internal_dependency_output_is_missing(tmp_path):
    root = tmp_path / "source"
    output = tmp_path / "build"
    (root / "A").mkdir(parents=True)
    (root / "A" / "Leaf.lean").write_text("theorem leaf : True := trivial\n", encoding="utf-8")
    (root / "A" / "Main.lean").write_text("import A.Leaf\ntheorem main : True := trivial\n", encoding="utf-8")
    (output / "A").mkdir(parents=True)
    (output / "A" / "Main.olean").write_bytes(b"stale target")

    closures = catalogue.internal_dependency_closures(root, ("A/Main.lean",))

    assert closures["A/Main.lean"] == frozenset({"A/Main.lean", "A/Leaf.lean"})
    assert catalogue.internal_dependency_order(root, "A/Main.lean") == ("A/Leaf.lean", "A/Main.lean")
    assert catalogue.order_by_missing_closure(root, output, ("A/Main.lean",)) == ["A/Main.lean"]


def test_driver_records_a_built_target_and_resumes_without_relaunching(tmp_path):
    root = tmp_path / "source"
    project = tmp_path / "project"
    output = project / ".lake" / "build" / "lib" / "lean"
    state = tmp_path / "progress.json"
    root.mkdir()
    project.mkdir()
    (root / "A.lean").write_text("theorem a : True := trivial\n", encoding="utf-8")
    formalization = root / "formalization.yaml"
    formalization.write_text(
        "status:\n  main_results:\n    - declaration: a\n      file: A.lean\n", encoding="utf-8"
    )
    launcher = tmp_path / "fake-lake.py"
    launcher.write_text(
        "import pathlib, sys\n"
        f"p=pathlib.Path({str(output / 'A.olean')!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'ok')\n",
        encoding="utf-8",
    )
    args = Namespace(
        source_root=root, project=project, catalogue=formalization, output_root=output,
        state=state, launcher=Path(sys.executable), launcher_arg=[str(launcher)],
        min_free_bytes=0, timeout=30, limit=0, keep_going=False,
    )

    assert catalogue.build(args) == 0
    launcher.unlink()  # a second launch would now fail
    assert catalogue.build(args) == 0


def test_driver_relaunches_a_leaf_with_a_missing_internal_dependency(tmp_path):
    root = tmp_path / "source"
    project = tmp_path / "project"
    output = project / ".lake" / "build" / "lib" / "lean"
    state = tmp_path / "progress.json"
    (root / "A").mkdir(parents=True)
    project.mkdir()
    (root / "A" / "Leaf.lean").write_text("theorem leaf : True := trivial\n", encoding="utf-8")
    (root / "A" / "Main.lean").write_text("import A.Leaf\ntheorem main : True := trivial\n", encoding="utf-8")
    formalization = root / "formalization.yaml"
    formalization.write_text(
        "status:\n  main_results:\n    - declaration: A.main\n      file: A/Main.lean\n", encoding="utf-8"
    )
    (output / "A").mkdir(parents=True)
    (output / "A" / "Main.olean").write_bytes(b"stale target")
    launcher = tmp_path / "fake-lake.py"
    launcher.write_text(
        "import pathlib\n"
        f"p=pathlib.Path({str(output / 'A' / 'Leaf.olean')!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'ok')\n",
        encoding="utf-8",
    )
    args = Namespace(
        source_root=root, project=project, catalogue=formalization, output_root=output,
        state=state, launcher=Path(sys.executable), launcher_arg=[str(launcher)],
        min_free_bytes=0, timeout=30, limit=0, keep_going=False,
    )

    assert catalogue.build(args) == 0
    saved = __import__("json").loads(state.read_text(encoding="utf-8"))
    assert saved["targets"]["A/Main.lean"]["status"] == "built"
    assert saved["targets"]["A/Main.lean"]["missing_dependencies"] == 0
    assert saved["targets"]["A/Main.lean"]["modules_attempted"] == 1
