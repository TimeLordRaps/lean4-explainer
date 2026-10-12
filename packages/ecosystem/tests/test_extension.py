import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lean4_explainer import cli
from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer_ecosystem import snapshot as S

V1 = """\
namespace Demo
theorem keep : True := trivial
theorem proof_changes (n : Nat) : n = n := by rfl
theorem statement_changes : 1 = 1 := rfl
theorem removed_later : True := trivial
end Demo
"""
V2 = """\
namespace Demo
theorem keep : True := trivial
theorem proof_changes (n : Nat) : n = n := by simp
theorem statement_changes : 2 = 2 := rfl
theorem added_later : True := trivial
end Demo
"""


def _build(tmp_path, source, name, **options):
    root = tmp_path / name / "src"
    root.mkdir(parents=True)
    (root / "Demo.lean").write_text(source, encoding="utf-8")
    out = tmp_path / name / "out"
    summary = build_site(root, out, Config(options=tuple(sorted(options.items()))), tmp_path / name / "idx")
    return summary, out


def test_every_build_publishes_a_snapshot_and_a_find_page(tmp_path):
    _, out = _build(tmp_path, V1, "one")

    snap = S.loads((out / "snapshot.json").read_text(encoding="utf-8"))
    names = [e[0] for e in snap["files"]["Demo.lean"]]
    assert names == ["Demo.keep", "Demo.proof_changes", "Demo.statement_changes", "Demo.removed_later"]
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Find" in index and "Changes" not in index  # no baseline, no changes page
    assert not (out / "changes.html").exists()


def test_find_table_points_at_the_declaration_page(tmp_path):
    _, out = _build(tmp_path, V1, "one")

    script = (out / "_assets" / "find-names.js").read_text(encoding="utf-8")
    table = json.loads(script[script.index("{") : script.rindex("}") + 1])
    target, anchor = table["Demo.proof_changes"].split("#")
    assert (out / target).is_file() and anchor == "L3"
    assert "id=L3" in (out / target).read_text(encoding="utf-8")
    assert (out / "_assets" / "find.js").is_file() and "find-names.js" in (out / "find.html").read_text(encoding="utf-8")


def test_find_limit_truncates_the_table_and_says_so(tmp_path):
    _, out = _build(tmp_path, V1, "one", find_limit=2)

    script = (out / "_assets" / "find-names.js").read_text(encoding="utf-8")
    assert script.startswith("/* 2 names beyond find_limit=2")
    assert script.count('":"') == 2  # two name -> page entries


def test_comparing_with_an_earlier_build_lists_what_changed(tmp_path):
    _, first = _build(tmp_path, V1, "one")

    summary, out = _build(tmp_path, V2, "two", compare_to=str(first / "snapshot.json"))

    changes = (out / "changes.html").read_text(encoding="utf-8")
    assert re.search(r"Proof changed \(statement the same\) \(1\).*Demo.proof_changes", changes, re.S)
    assert re.search(r"Statement changed \(1\).*Demo.statement_changes", changes, re.S)
    assert "Added (1)" in changes and "Demo.added_later" in changes
    assert "Removed (1)" in changes and "Demo.removed_later" in changes
    assert "Demo.keep" not in changes
    assert any("1 added, 1 removed, 1 statements changed, 1 proofs changed" in line for line in summary.extension_lines)
    assert "Changes" in (out / "index.html").read_text(encoding="utf-8")


def test_comparing_a_build_with_itself_changes_nothing(tmp_path):
    _, first = _build(tmp_path, V1, "one")

    _, out = _build(tmp_path, V1, "two", compare_to=str(first / "snapshot.json"))

    assert "Nothing changed." in (out / "changes.html").read_text(encoding="utf-8")


def test_an_unreadable_baseline_is_a_warning_not_a_crash(tmp_path):
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")

    summary, out = _build(tmp_path, V1, "one", compare_to=str(tmp_path / "bad.json"))

    assert any("could not read the baseline" in w for w in summary.warnings)
    assert "could not read the baseline" in (out / "changes.html").read_text(encoding="utf-8")


def test_lake_facet_command_prints_and_writes_the_snippet(tmp_path, capsys):
    assert cli.main(["lake-facet"]) == 0
    printed = capsys.readouterr().out
    assert "package_facet explain pkg" in printed and "lean4-explainer" in printed

    target = tmp_path / "facet.lean"
    assert cli.main(["lake-facet", "--out", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == printed


@pytest.mark.skipif(shutil.which("lake") is None or shutil.which("lean") is None, reason="lake is not installed")
def test_lake_build_explain_writes_a_site(tmp_path):
    from lean4_explainer_ecosystem.lakefacet import LAKEFILE_SNIPPET

    version = subprocess.run(["lean", "--version"], capture_output=True, text=True).stdout
    release = re.search(r"version (\d+\.\d+\.\d+)", version).group(1)
    project = tmp_path / "proj"
    (project / "Demo").mkdir(parents=True)
    (project / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\n\npackage demo\n\nlean_lib Demo\n\n" + LAKEFILE_SNIPPET, encoding="utf-8"
    )
    (project / "lean-toolchain").write_text(f"leanprover/lean4:v{release}\n", encoding="utf-8")
    (project / "Demo.lean").write_text("import Demo.Basic\n", encoding="utf-8")
    (project / "Demo" / "Basic.lean").write_text("theorem t : True := trivial\n", encoding="utf-8")
    scripts = str(Path(sys.executable).parent)
    env = {**os.environ, "PATH": scripts + os.pathsep + os.environ["PATH"]}

    done = subprocess.run(["lake", "build", ":explain"], cwd=project, env=env, capture_output=True, text=True, timeout=600)

    assert done.returncode == 0, done.stdout + done.stderr
    site = project / ".lake" / "build" / "explain"
    assert (site / "Demo" / "Basic.lean.html").is_file() and (site / "find.html").is_file()
