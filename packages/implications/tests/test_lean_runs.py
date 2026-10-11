"""How Lean processes are started and stopped: the memory gate, and a timeout that stops the whole process tree.

A Lean process that imports Mathlib commits about 10 GB on Windows. These tests replace Lean with small Python
processes and the system's free commit with a model, so they run anywhere and fast."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from lean4_explainer_implications.pipeline import lean as L
from lean4_explainer_implications.pipeline import processes as P

SLEEP = "import time; time.sleep({})"


class Memory:
    """Free commit: `total` less `each` for every started process that has run for `lag` seconds (a process commits
    its memory a little after it starts, which is what lets two launches race)."""

    def __init__(self, total: float, each: float, lag: float):
        self.total, self.each, self.lag = total, each, lag
        self.started: list[tuple[float, subprocess.Popen]] = []

    def free(self) -> float:
        now = time.monotonic()
        return self.total - self.each * sum(1 for t, p in self.started if p.poll() is None and now - t >= self.lag)


def _fake(monkeypatch, memory: Memory, seconds: float):
    starts: list[float] = []
    real = P.start

    def start(args, cwd, env):
        p = real([sys.executable, "-c", SLEEP.format(seconds)], cwd, env)
        starts.append(time.monotonic())
        memory.started.append((time.monotonic(), p))
        return p

    monkeypatch.setattr(P, "start", start)
    monkeypatch.setattr(P, "free_commit_gb", memory.free)
    monkeypatch.setattr(P, "POLL_SECONDS", 0.05)
    return starts


def _together(n: int, **kw) -> list[L.LeanRun]:
    out: list[L.LeanRun] = []
    threads = [threading.Thread(target=lambda: out.append(L.run(dict(os.environ), Path.cwd(), [], 60, log=lambda s: None, **kw))) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_parallel_launches_do_not_count_the_same_free_memory_twice(monkeypatch):
    # found 2026-10-10: two attempt processes started together both saw 30 GB free, each committed 10 GB, and both
    # died within twenty seconds of each other once the rest of the machine took its share
    memory = Memory(total=30.0, each=10.0, lag=0.4)
    starts = _fake(monkeypatch, memory, seconds=1.5)
    runs = _together(2, commit_gb=16.0, settle_seconds=5.0)
    assert all(r.ok for r in runs)
    starts.sort()
    assert starts[1] - starts[0] >= 0.4  # the second waited until the first had committed its memory
    memory = Memory(total=30.0, each=10.0, lag=0.4)
    starts = _fake(monkeypatch, memory, seconds=1.0)
    _together(2, commit_gb=25.0, settle_seconds=5.0)  # room for one only: the second waits for the first to end
    starts.sort()
    assert starts[1] - starts[0] >= 1.0


def test_a_run_that_needs_no_memory_gate_starts_at_once(monkeypatch):
    memory = Memory(total=0.0, each=10.0, lag=0.0)  # nothing free: a gated run would wait
    _fake(monkeypatch, memory, seconds=0.1)
    started = time.monotonic()
    assert all(r.ok for r in _together(2, commit_gb=0))
    assert time.monotonic() - started < 5


def test_a_build_waits_for_memory_that_other_processes_hold(monkeypatch, tmp_path):
    # found 2026-10-10: started while an attempt process held 11 GB, the solutions build saw 14.5 GB free, needed 17,
    # and stopped at once without building anything, recording every module as "skipped-low-disk"
    from lean4_explainer_implications.pipeline import workspace as W

    corpus = tmp_path / "corpus"
    (corpus / "Z").mkdir(parents=True)
    (corpus / "Z" / "A.lean").write_text("def a := 1\n", encoding="utf-8")
    ws = W.Workspace(tmp_path / "ws", corpus, ("Z",))
    ws.root.mkdir()
    monkeypatch.setattr(W, "toolchain_version", lambda ws: "test")
    free = {"gb": 14.5}
    monkeypatch.setattr(P, "free_commit_gb", lambda: free["gb"])
    monkeypatch.setattr(P, "POLL_SECONDS", 0.05)
    real = P.start
    monkeypatch.setattr(P, "start", lambda args, cwd, env: real([sys.executable, "-c", f"open({args[-1]!r}, 'w').write('olean')"], cwd, env))
    later = threading.Timer(0.5, lambda: free.update(gb=40.0))  # the other process ends
    later.start()
    record = W.build(ws, ["Z.A"], jobs=1, lean_commit_gb=11.0, commit_reserve_gb=6.0, log=lambda s: None)
    later.cancel()
    assert record.stopped == "" and record.counts() == {"built": 1}, record.to_json()


def test_a_build_that_never_gets_memory_says_so(monkeypatch, tmp_path):
    from lean4_explainer_implications.pipeline import workspace as W

    corpus = tmp_path / "corpus"
    (corpus / "Z").mkdir(parents=True)
    (corpus / "Z" / "A.lean").write_text("def a := 1\n", encoding="utf-8")
    ws = W.Workspace(tmp_path / "ws", corpus, ("Z",))
    ws.root.mkdir()
    monkeypatch.setattr(W, "toolchain_version", lambda ws: "test")
    monkeypatch.setattr(P, "free_commit_gb", lambda: 2.0)
    monkeypatch.setattr(P, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(P, "MEMORY_WAIT_SECONDS", 0.3)
    record = W.build(ws, ["Z.A"], jobs=1, lean_commit_gb=11.0, commit_reserve_gb=6.0, log=lambda s: None)
    assert record.counts() == {"skipped": 1} and "commit only 2.0 GB" in record.stopped, record.to_json()


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_timeout_stops_the_whole_process_tree(monkeypatch, tmp_path):
    # elan's `lean` is a proxy that starts the toolchain's lean. Stopping only the proxy left the real process running
    # and holding the output pipes, so the run waited for it to end on its own: a 3 s timeout took 60 s (2026-10-10)
    pid_file = tmp_path / "grandchild.pid"
    proxy = ("import subprocess, sys, time; "
             f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
             f"open({str(pid_file)!r}, 'w').write(str(p.pid)); time.sleep(60)")
    real = P.start
    monkeypatch.setattr(P, "start", lambda args, cwd, env: real([sys.executable, "-c", proxy], cwd, env))
    began = time.monotonic()
    run = L.run(dict(os.environ), tmp_path, [], 3, log=lambda s: None, commit_gb=0)
    assert run.code == -1 and "timed out" in run.stderr
    assert time.monotonic() - began < 20, "the run waited for the process tree to end by itself"
    grandchild = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(grandchild), f"process {grandchild} outlived the timeout"


MEMINFO = """MemTotal:       16000000 kB
MemAvailable:   12000000 kB
SwapFree:        2000000 kB
CommitLimit:     9000000 kB
Committed_AS:   11000000 kB
"""


def test_on_linux_free_memory_is_the_commit_room_only_where_the_kernel_enforces_it():
    # the default overcommit modes (0 heuristic, 1 always) do not enforce CommitLimit, and on a desktop Committed_AS is
    # often above it: read that way, every launch would wait two hours for memory the system would give at once
    assert P.linux_free_gb(MEMINFO, "0") == 14.0  # available memory and free swap, in GB
    assert P.linux_free_gb(MEMINFO, "1") == 14.0
    assert P.linux_free_gb(MEMINFO, "2") == -2.0  # strict: CommitLimit - Committed_AS, as the kernel will refuse
    assert P.linux_free_gb("nothing useful", "0") is None
