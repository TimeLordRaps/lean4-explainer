"""Starting Lean processes within the machine's memory, and stopping them with everything they started.

A Lean process that imports Mathlib commits about 11 GB on Windows. Past the commit limit Windows grows the page file
on the system disk, and when it cannot, allocations fail in every process on the machine, not only Lean's. So a
launch waits until the system can commit what it needs. Launches from parallel threads go one at a time, and each
holds its turn until its process has committed its memory: otherwise two launches see the same free memory. The
turn is per Python process: two pipeline commands run at once do not take turns with each other (TD-14).

elan's `lean` is a proxy that starts the toolchain's lean, so stopping a run means stopping the process tree.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

POLL_SECONDS = 10.0
MEMORY_WAIT_SECONDS = 7200.0  # how long a launch waits for memory before giving up
_TURN = threading.Lock()


def linux_free_gb(meminfo: str, overcommit: str) -> float | None:
    """Memory Linux will still give, in GB, from /proc/meminfo and vm.overcommit_memory. Only in strict mode (2) does
    the kernel refuse past CommitLimit; in the default modes Committed_AS is often above it while allocations still
    succeed, so there it is available memory plus free swap."""
    try:
        info = {k.strip(): int(v.split()[0]) for k, v in (line.split(":", 1) for line in meminfo.splitlines() if ":" in line)}
        if overcommit.strip() == "2":
            return (info["CommitLimit"] - info["Committed_AS"]) / 1e6
        return (info["MemAvailable"] + info.get("SwapFree", 0)) / 1e6
    except (KeyError, ValueError, IndexError):
        return None


def free_commit_gb() -> float | None:
    """Memory the system can still commit, in GB, where the platform says (Windows: physical memory plus page file,
    which Windows grows on the system disk when it runs short; Linux: `linux_free_gb`). None where unknown."""
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullAvailPageFile / 1e9
        return None
    try:
        meminfo = Path("/proc/meminfo").read_text()
    except OSError:
        return None
    try:
        overcommit = Path("/proc/sys/vm/overcommit_memory").read_text()
    except OSError:
        overcommit = "0"
    return linux_free_gb(meminfo, overcommit)


def wait_for_memory(need_gb: float, log: Callable[[str], None], max_wait: float | None = None) -> None:
    """Wait until the system can commit `need_gb` more; RuntimeError after `max_wait` seconds (MEMORY_WAIT_SECONDS)."""
    max_wait = MEMORY_WAIT_SECONDS if max_wait is None else max_wait
    waited = 0.0
    while True:
        free = free_commit_gb()
        if free is None or free >= need_gb:
            return
        if waited >= max_wait:
            raise RuntimeError(f"the system could commit only {free:.1f} GB for {max_wait:.0f}s; a Lean run needs {need_gb:.0f} GB")
        if waited == 0:
            log(f"lean: waiting for memory ({free:.1f} GB free to commit, {need_gb:.0f} GB needed)")
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS


def start(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    """Start a process in its own group, so that it can be stopped with everything it started."""
    if os.name == "nt":
        return subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            start_new_session=True)


def stop_tree(proc: subprocess.Popen) -> None:
    """Stop a process and every process it started."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.kill()


def _settle(proc: subprocess.Popen, before: float | None, expect_gb: float, max_seconds: float) -> None:
    """Wait until a process just started has committed `expect_gb` (free commit fell by that much), or it ended, or
    `max_seconds` passed."""
    if before is None or expect_gb <= 0:
        return
    began = time.monotonic()
    while proc.poll() is None and time.monotonic() - began < max_seconds:
        now = free_commit_gb()
        if now is None or before - now >= expect_gb:
            return
        time.sleep(min(1.0, POLL_SECONDS))


def launch(args: list[str], cwd: Path, env: dict[str, str], need_gb: float = 0.0, expect_gb: float = 0.0, settle_seconds: float = 120.0,
           log: Callable[[str], None] = print) -> tuple[subprocess.Popen, float]:
    """Start `args`, and say when. With `need_gb` > 0 the launch takes its turn: it waits until the system can commit
    `need_gb` more, starts, and keeps the turn until the process has committed `expect_gb`."""
    if need_gb <= 0:
        return start(args, cwd, env), time.monotonic()
    with _TURN:
        wait_for_memory(need_gb, log)
        before = free_commit_gb()
        began = time.monotonic()
        proc = start(args, cwd, env)
        _settle(proc, before, expect_gb, settle_seconds)
    return proc, began


def finish(proc: subprocess.Popen, began: float, timeout: float) -> tuple[int, str, str, float]:
    """Wait for a process until `timeout` seconds after `began`: (exit code, stdout, stderr, seconds). On timeout the
    tree is stopped and the code is -1."""
    try:
        out, err = proc.communicate(timeout=max(1.0, timeout - (time.monotonic() - began)))
    except subprocess.TimeoutExpired:
        stop_tree(proc)
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            out = ""
        return -1, out or "", f"timed out after {timeout:.0f}s", time.monotonic() - began
    return proc.returncode, out, err, time.monotonic() - began
