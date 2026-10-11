import os
import re
import shutil
import subprocess
import sys
import time
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
def test_each_trace_step_has_an_anchor_its_source_line_and_a_link_to_it(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "Demo.lean").write_text(SAMPLE, encoding="utf-8")
    config = Config(source_url="https://example.org/src/{ref}/{path}#L{line}", source_ref="abc123", options=(("lean_cache", str(tmp_path / "cache")),))
    build_site(root, tmp_path / "out", config, tmp_path / "idx")

    page = (tmp_path / "out" / "Demo.lean.html").read_text(encoding="utf-8")
    trace = page[page.index('<details class="trace">') :]
    trace = trace[: trace.index("</details>")]
    steps = re.findall(r'<li id="L3-step(\d+)" data-line="(\d+)"><code>([^<]*)</code> <a class="ln" href="([^"]*)">line (\d+)</a>', trace)
    assert steps, trace[:600]
    lines = SAMPLE.split("\n")
    for k, (index, line, tactic, link, shown) in enumerate(steps, 1):
        assert int(index) == k and line == shown  # anchors in order; the line shown is the line kept
        assert tactic.split(" ")[0].replace("&gt;", ">") in lines[int(line) - 1]  # the tactic is on that source line: the key the reader joins on
        assert link == f"https://example.org/src/abc123/Demo.lean#L{line}"
    assert [s[2] for s in steps][:1] == ["induction n with"] and steps[0][1] == "4"
    # a badge links to what the badges mean
    assert '<span class="trust trust-standard">standard axioms: propext</span> <a class="trust-more" href="trust.html#badges">' in page
    trust = (tmp_path / "out" / "trust.html").read_text(encoding="utf-8")
    assert '<h2 id="badges">What the badges mean</h2>' in trust and "<dt>depends on sorry</dt>" in trust


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


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_probe_that_times_out_is_stopped_with_every_process_it_started(tmp_path):
    # `lake env lean` starts lean, and elan's `lean` starts the toolchain's: stopping only the first process on a timeout
    # leaves the real one running and holding the pipes, so the run waits for it (seen in the implications pipeline:
    # a 3 s timeout took 60 s, 2026-10-10; TD-17)
    pid_file = tmp_path / "grandchild.pid"
    proxy = ("import subprocess, sys, time; "
             "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
             f"open({str(pid_file)!r}, 'w').write(str(p.pid)); time.sleep(60)")
    tc = runner.Toolchain((sys.executable, "-c", proxy), None, "test", "x")
    began = time.monotonic()
    code, _, err = runner.run_probe(tc, tmp_path / "A.lean", ["A.a"], 3)
    assert code == -1 and "timed out" in err
    assert time.monotonic() - began < 20, "the probe waited for its process tree to end by itself"
    grandchild = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(grandchild), f"process {grandchild} outlived the timeout"
