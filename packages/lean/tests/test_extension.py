import re
import shutil
from pathlib import Path

import pytest

from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer_lean import extension, runner

needs_lean = pytest.mark.skipif(shutil.which("lean") is None, reason="lean is not installed")

SAMPLE = """\
namespace Demo

theorem add_zero' (n : Nat) : n + 0 = n := by
  induction n with
  | zero => rfl
  | succ k ih => simp

theorem uses_sorry : 1 = 2 := by
  sorry

theorem uses_choice (p : Prop) : p ∨ ¬p := Classical.em p

theorem plain : True := trivial

end Demo
"""


def _site(tmp_path, source, **options):
    root = tmp_path / "src"
    root.mkdir(exist_ok=True)
    (root / "Demo.lean").write_text(source, encoding="utf-8")
    config = Config(options=tuple(sorted({"lean_cache": str(tmp_path / "cache"), **options}.items())))
    summary = build_site(root, tmp_path / "out", config, tmp_path / "idx")
    return summary, tmp_path / "out"


def test_without_lean_every_badge_says_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": None)

    summary, out = _site(tmp_path, SAMPLE)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert page.count("trust-unknown") == 4 and "was not found on the PATH" in page
    assert "All trust is UNKNOWN" in (out / "trust.html").read_text(encoding="utf-8")
    assert any("Lean not found" in line for line in summary.extension_lines)


def test_a_probe_that_crashes_marks_the_file_failed(tmp_path, monkeypatch):
    tc = runner.Toolchain(("lean",), None, "Lean (version 9.9)", "x")
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": tc)
    monkeypatch.setattr(runner, "run_probe", lambda tc, path, names, timeout: (1, "", "kaboom\nfinal line"))

    summary, out = _site(tmp_path, SAMPLE)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert "trust unknown: final line" in page
    assert "Files Lean could not elaborate" in (out / "trust.html").read_text(encoding="utf-8")
    assert any("final line" in issue for issue in summary.warnings)


@needs_lean
def test_real_lean_gives_badges_traces_and_a_trust_page(tmp_path):
    summary, out = _site(tmp_path, SAMPLE)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert "standard axioms: propext" in page  # Demo.add_zero'
    assert "depends on sorry" in page  # Demo.uses_sorry
    assert "standard axioms: Classical.choice, Quot.sound, propext" in page.replace("propext, Classical.choice, Quot.sound", "Classical.choice, Quot.sound, propext")
    assert "no axioms" in page  # Demo.plain
    assert "Statement uses:" in page and "Proof uses:" in page and "Classical.em" in page
    assert "left out" in page  # instances and coercions are counted, not listed
    assert "Tactic trace" in page and "induction n with" in page and "⊢ n + 0 = n" in page
    trust = (out / "trust.html").read_text(encoding="utf-8")
    assert "Depend on sorry (1)" in trust and "Demo.uses_sorry" in trust
    link = re.search(r'href="([^"#]+)#L(\d+)"><code>Demo.uses_sorry', trust)
    assert link and (out / link.group(1)).is_file() and link.group(2) == "8"  # the link lands on the declaration's page
    assert any("1 sorry" in line for line in summary.extension_lines)


@needs_lean
def test_second_build_reuses_cached_results(tmp_path):
    first, _ = _site(tmp_path, SAMPLE)
    (tmp_path / "out2").mkdir()
    root = tmp_path / "src"
    config = Config(options=(("lean_cache", str(tmp_path / "cache")),))

    second = build_site(root, tmp_path / "out2", config, tmp_path / "idx2")

    assert any("1 files elaborated" in line for line in first.extension_lines)
    assert any("0 files elaborated, 1 from cache" in line for line in second.extension_lines)


@needs_lean
def test_a_file_with_errors_is_not_trusted_silently(tmp_path):
    summary, out = _site(tmp_path, "theorem bad : 1 = 2 := rfl\n")

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert re.search(r"Lean reported \d+ error\(s\) in this file", page)  # the kernel sees the error as a sorry; the badge says why
    assert "Files where Lean reported errors" in (out / "trust.html").read_text(encoding="utf-8")


@needs_lean
def test_changing_a_file_changes_the_answer(tmp_path):
    _site(tmp_path, "theorem t : True := trivial\n")
    _, out = _site(tmp_path, "theorem t : 1 = 2 := by sorry\n")

    assert "depends on sorry" in (out / "Demo.lean.html").read_text(encoding="utf-8")


def test_probe_digest_tracks_the_probe_source():
    assert len(runner.probe_digest()) == 16 and Path(runner.PROBE).is_file()
    assert extension.LeanExtension().fingerprint({}).count(":") == 3
