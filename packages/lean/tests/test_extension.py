import os
import gzip
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer.render import default_context
from lean4_explainer_lean import extension, facts, runner

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
    record = json.loads((out / "trust.json").read_text(encoding="utf-8"))
    assert record["provenance"] == "unavailable" and record["toolchain"] == ""
    assert record["files"] == {"ok": 0, "failed": 0, "unavailable": 1}
    assert record["declarations"]["total"] == 4 and record["declarations"]["unknown"] == 4
    assert any("Lean not found" in line for line in summary.extension_lines)


def test_a_hosted_build_can_keep_unknown_details_on_the_trust_page_without_repeating_them_per_declaration(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": None)

    _, out = _site(tmp_path, SAMPLE, lean_unknown_badges=False)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert "trust-unknown" not in page
    assert "All trust is UNKNOWN" in (out / "trust.html").read_text(encoding="utf-8")


def test_a_broken_lake_environment_never_falls_back_to_global_lean(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")
    monkeypatch.setattr(runner.shutil, "which", lambda name, path=None: f"/{name}")
    monkeypatch.setattr(runner, "_lake_environment", lambda lake, folder: {"PATH": "/pinned"})
    calls = []

    def version(prefix, folder, env=None):
        calls.append((prefix, folder, env))
        return ""

    monkeypatch.setattr(runner, "_version", version)
    with pytest.raises(runner.ToolchainError, match="no global Lean fallback"):
        runner.find_toolchain(root)
    assert calls == [(("/lean",), root.resolve(), {"PATH": "/pinned"})]


def test_lake_environment_is_applied_directly_to_the_probe(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")
    env = {"PATH": "/pinned", "LEAN_PATH": "/pinned/lib/lean"}
    monkeypatch.setattr(runner.shutil, "which", lambda name, path=None: f"/{name}")
    monkeypatch.setattr(runner, "_lake_environment", lambda lake, folder: env)
    monkeypatch.setattr(runner, "_version", lambda prefix, folder, found_env=None: "Lean (version 9.9)")

    tc = runner.find_toolchain(root)

    assert tc is not None and tc.prefix == ("/lean",) and tc.env is env


def test_a_broken_lake_environment_is_reported_as_the_reason_trust_is_unknown(tmp_path, monkeypatch):
    reason = "The pinned Lake environment could not start `lean --version`; no global Lean fallback was used."
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": (_ for _ in ()).throw(runner.ToolchainError(reason)))

    summary, out = _site(tmp_path, SAMPLE)

    trust = (out / "trust.html").read_text(encoding="utf-8")
    record = json.loads((out / "trust.json").read_text(encoding="utf-8"))
    assert "pinned Lake environment" in trust and "All trust is UNKNOWN" in trust
    assert record["unavailable_reason"] == reason
    assert any("pinned Lake environment" in line for line in summary.extension_lines)


def test_a_bounded_pass_marks_every_unselected_file_and_declaration_unknown(tmp_path, monkeypatch):
    root = tmp_path / "src"
    root.mkdir()
    (root / "A.lean").write_text("theorem a : True := trivial\n", encoding="utf-8")
    (root / "B.lean").write_text("theorem b : True := trivial\n", encoding="utf-8")
    tc = runner.Toolchain(("lean",), None, "Lean (version 9.9)", "x")
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": tc)
    called = []
    monkeypatch.setattr(
        runner, "run_probe", lambda tc, path, names, timeout, *bounds: (called.append(path.name) or (1, "", "failed"))
    )
    config = Config(options=(("lean_cache", str(tmp_path / "cache")), ("lean_file_limit", 1)))

    build_site(root, tmp_path / "out", config, tmp_path / "idx")

    record = json.loads((tmp_path / "out" / "trust.json").read_text(encoding="utf-8"))
    assert called == ["A.lean"]
    assert record["files"] == {"ok": 0, "failed": 1, "unavailable": 1}
    assert record["declarations"]["total"] == 2 and record["declarations"]["unknown"] == 2
    trust = (tmp_path / "out" / "trust.html").read_text(encoding="utf-8")
    assert "Files outside this Lean pass (1)" in trust and "B.lean" in trust


def test_a_catalogue_pass_queries_only_its_named_results_and_keeps_everything_else_unknown(tmp_path, monkeypatch):
    root = tmp_path / "src"
    root.mkdir()
    (root / "A.lean").write_text("theorem target : True := trivial\ntheorem helper : True := trivial\n", encoding="utf-8")
    (root / "B.lean").write_text("theorem other : True := trivial\n", encoding="utf-8")
    tc = runner.Toolchain(("lean",), None, "Lean (version 9.9)", "x")
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": tc)
    called = []

    def probe(tc, path, names, timeout, *bounds):
        called.append((path.name, names))
        return 0, json.dumps({"kind": "decl", "name": "target", "axioms": []}), ""

    monkeypatch.setattr(runner, "run_probe", probe)
    config = Config(options=tuple(sorted({
        "lean_cache": str(tmp_path / "cache"),
        "lean_targets": ["A.lean\ttarget"],
        "lean_selection_label": "upstream main results",
    }.items())))

    build_site(root, tmp_path / "out", config, tmp_path / "idx")

    record = json.loads((tmp_path / "out" / "trust.json").read_text(encoding="utf-8"))
    assert called == [("A.lean", ["target"])]
    assert record["selection"] == {
        "label": "upstream main results", "eligible_files": 1, "selected_files": 1,
        "requested_declarations": 1, "missing_targets": [],
    }
    assert record["declarations"]["total"] == 3
    assert record["declarations"]["kernel_checked"] == 1 and record["declarations"]["unknown"] == 2


def test_a_probe_that_crashes_marks_the_file_failed(tmp_path, monkeypatch):
    tc = runner.Toolchain(("lean",), None, "Lean (version 9.9)", "x")
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": tc)
    monkeypatch.setattr(runner, "run_probe", lambda tc, path, names, timeout, *bounds: (1, "", "kaboom\nfinal line"))

    summary, out = _site(tmp_path, SAMPLE)

    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert "trust unknown: final line" in page
    assert "Files Lean could not elaborate" in (out / "trust.html").read_text(encoding="utf-8")
    assert any("final line" in issue for issue in summary.warnings)


def test_a_failed_probe_is_never_cached(tmp_path, monkeypatch):
    tc = runner.Toolchain(("lean",), None, "Lean (version 9.9)", "x")
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": tc)
    calls = []

    def fail(tc, path, names, timeout, *bounds):
        calls.append(timeout)
        return -1, "", f"timed out after {timeout}s"

    monkeypatch.setattr(runner, "run_probe", fail)

    first, _ = _site(tmp_path, SAMPLE, lean_timeout=7)
    second, _ = _site(tmp_path, SAMPLE, lean_timeout=7)
    third, _ = _site(tmp_path, SAMPLE, lean_timeout=8)

    assert calls == [7, 7, 8]
    assert any("1 files elaborated, 0 from cache" in line for line in first.extension_lines)
    assert any("1 files elaborated, 0 from cache" in line for line in second.extension_lines)
    assert any("1 files elaborated, 0 from cache" in line for line in third.extension_lines)


def test_cache_only_rendering_never_runs_a_cache_miss(tmp_path, monkeypatch):
    tc = runner.Toolchain(("lean",), None, "Lean (version 9.9)", "x")
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": tc)
    monkeypatch.setattr(
        runner, "run_probe", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("probe started"))
    )

    summary, out = _site(tmp_path, SAMPLE, lean_cached_only=True)

    record = json.loads((out / "trust.json").read_text(encoding="utf-8"))
    assert record["execution"] == {
        "elaborated_now": 0,
        "reused_content_bound_cache": 0,
        "cache_only": True,
        "cache_misses": 1,
    }
    assert record["files"] == {"ok": 0, "failed": 0, "unavailable": 1}
    assert record["declarations"]["unknown"] == 4
    assert "No Lean process was started" in (out / "trust.html").read_text(encoding="utf-8")
    assert any("1 cache misses left UNKNOWN" in line for line in summary.extension_lines)


def test_a_clean_process_with_lean_errors_or_a_missing_constant_is_not_cached(tmp_path, monkeypatch):
    tc = runner.Toolchain(("lean",), None, "Lean (version 9.9)", "x")
    monkeypatch.setattr(runner, "find_toolchain", lambda root, project="": tc)
    calls = []

    def incomplete(tc, path, names, timeout, *bounds):
        calls.append(path.name)
        return 0, (
            '{"kind":"message","severity":"error","line":1,"text":"unknown namespace"}\n'
            '{"kind":"decl","name":"Demo.plain","axioms":null}\n'
        ), ""

    monkeypatch.setattr(runner, "run_probe", incomplete)

    first, _ = _site(tmp_path, SAMPLE)
    second, _ = _site(tmp_path, SAMPLE)

    assert calls == ["Demo.lean", "Demo.lean"]
    assert any("1 files elaborated, 0 from cache" in line for line in first.extension_lines)
    assert any("1 files elaborated, 0 from cache" in line for line in second.extension_lines)


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
    assert "Tactic trace" in page and "trace-lazy" in page
    trace_payload = json.loads(gzip.decompress((out / extension._trace_asset("Demo.lean")).read_bytes()))
    trace_text = json.dumps(trace_payload, ensure_ascii=False)
    assert "induction n with" in trace_text and "⊢ n + 0 = n" in trace_text
    trust = (out / "trust.html").read_text(encoding="utf-8")
    assert "Depend on sorry (1)" in trust and "Demo.uses_sorry" in trust
    link = re.search(r'href="([^"#]+)#L(\d+)"><code>Demo.uses_sorry', trust)
    assert link and (out / link.group(1)).is_file() and link.group(2) == "8"  # the link lands on the declaration's page
    record = json.loads((out / "trust.json").read_text(encoding="utf-8"))
    assert record["provenance"] == "local-lean-run" and record["toolchain"].startswith("Lean (version")
    assert record["files"] == {"ok": 1, "failed": 0, "unavailable": 0}
    assert record["declarations"]["kernel_checked"] == 3
    assert record["declarations"]["classified"] == 4
    assert any("1 sorry" in line for line in summary.extension_lines)


@needs_lean
def test_each_trace_step_has_an_anchor_its_source_line_and_a_link_to_it(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "Demo.lean").write_text(SAMPLE, encoding="utf-8")
    config = Config(source_url="https://example.org/src/{ref}/{path}#L{line}", source_ref="abc123", options=(("lean_cache", str(tmp_path / "cache")),))
    build_site(root, tmp_path / "out", config, tmp_path / "idx")

    page = (tmp_path / "out" / "Demo.lean.html").read_text(encoding="utf-8")
    trace = page[page.index('<details class="trace trace-lazy"') :]
    trace = trace[: trace.index("</details>")]
    assert "Open to load the checked before-and-after goal states" in trace
    payload = json.loads(gzip.decompress((tmp_path / "out" / extension._trace_asset("Demo.lean")).read_bytes()))
    steps = payload["d"]["3:Demo.add_zero'"]
    assert steps
    lines = SAMPLE.split("\n")
    for line, tactic, before, after, link in steps:
        assert tactic.split(" ")[0] in lines[int(line) - 1]  # the tactic is on that source line: the key the reader joins on
        assert link == f"https://example.org/src/abc123/Demo.lean#L{line}"
        assert isinstance(before, list) and isinstance(after, list)
    assert steps[0][1] == "induction n with" and steps[0][0] == 4
    trace_script = (tmp_path / "out" / extension.TRACE_SCRIPT).read_text(encoding="utf-8")
    assert 'item.id = "L" + declarationLine + "-step"' in trace_script
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


def test_zero_step_limit_suppresses_trace_markup_without_changing_the_facts():
    step = facts.Step(2, 3, "exact trivial", ("⊢ True",), ())
    found = facts.DeclFacts("Demo.t", 1, (), steps=(step,))

    assert extension._trace(found, 0, "Demo.lean", []) == ""
    rendered = extension._trace(found, 1, "Demo.lean", [])
    assert "Tactic trace: 1 steps" in rendered and extension._trace_asset("Demo.lean") in rendered
    assert found.axioms == ()


def test_trust_page_fallback_for_an_ambiguous_name_adds_html_only_once():
    result = facts.DeclFacts("Demo.duplicate", 7, ("Demo.extraAxiom",))
    analysis = extension.Analysis(
        {"Demo.lean": facts.FileFacts("ok", decls=(result,))},
        "Lean (version 9.9)",
        100,
    )

    trust = extension._trust_page(default_context(), analysis)

    assert 'href="Demo.lean.html#L7"' in trust
    assert ".lean.html.html" not in trust


def test_trust_page_lists_named_unknown_declarations_and_reasons():
    result = facts.DeclFacts("Demo.privateThing", 7, None)
    analysis = extension.Analysis(
        {"Demo.lean": facts.FileFacts("ok", decls=(result,))},
        "Lean (version 9.9)",
        100,
    )

    trust = extension._trust_page(default_context(), analysis)

    assert "Trust UNKNOWN declarations (1)" in trust
    assert "Demo.privateThing" in trust and "Lean has no constant by this name" in trust


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


def test_a_probe_stopped_by_a_resource_guard_is_unknown_not_a_process_failure(tmp_path, monkeypatch):
    tc = runner.Toolchain((sys.executable, "-c", "import time; time.sleep(60)"), None, "test", "x")
    monkeypatch.setattr(runner, "_resource_state", lambda proc: (2 * 1024**2, 20 * 1024**2))

    code, _, reason = runner.run_probe(
        tc, tmp_path / "A.lean", ["A.a"], 30, max_working_set_mb=1, min_free_virtual_mb=10
    )

    assert code == -2
    assert "1 MiB" in reason and ("working set" in reason or "process-memory ceiling" in reason)
