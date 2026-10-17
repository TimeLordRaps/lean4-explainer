"""Find Lean and run the probe on one file."""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
import ctypes
from ctypes import Structure, byref, c_longlong, c_size_t, c_ulong, c_ulonglong, c_void_p, sizeof
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path

PROBE = Path(__file__).with_name("Probe.lean")
_LAKEFILES = ("lakefile.toml", "lakefile.lean")


@dataclass(frozen=True)
class Toolchain:
    prefix: tuple[str, ...]  # command that runs `lean ARGS...`
    cwd: Path | None  # the Lake project to run in, if any
    version: str  # first line of `lean --version`
    probe_digest: str
    env: Mapping[str, str] | None = None  # exact Lake environment, without credentials in rendered output


class ToolchainError(RuntimeError):
    """A project declares a Lean environment, but that exact environment cannot start."""


def probe_digest() -> str:
    return hashlib.sha256(PROBE.read_bytes()).hexdigest()[:16]


def find_project(root: Path, explicit: str = "") -> Path | None:
    """The Lake project that holds `root`: the explicit directory, else the nearest ancestor with a lakefile."""
    if explicit:
        return Path(explicit).resolve()
    resolved = root.resolve()
    for folder in (resolved, *resolved.parents[:4]):
        if any((folder / name).is_file() for name in _LAKEFILES):
            return folder
    return None


def find_toolchain(root: Path, project: str = "") -> Toolchain | None:
    folder = find_project(root, project)
    if folder is not None:
        lake = shutil.which("lake")
        if lake is None:
            raise ToolchainError(
                "A Lake project was found, but the `lake` command is unavailable; "
                "no global Lean fallback was used."
            )
        env = _lake_environment(lake, folder)
        lean = shutil.which("lean", path=env.get("PATH"))
        if lean is None:
            raise ToolchainError(
                "The pinned Lake environment does not provide a `lean` executable; "
                "no global Lean fallback was used."
            )
        prefix = (lean,)
        found = _version(prefix, folder, env)
        if found:
            return Toolchain(prefix, folder, found, probe_digest(), env)
        raise ToolchainError(
            "The pinned Lake environment could not start `lean --version`; "
            "no global Lean fallback was used."
        )
    lean = shutil.which("lean")
    if lean is None:
        return None
    found = _version((lean,), None)
    if found:
        return Toolchain((lean,), None, found, probe_digest())
    return None


def _lake_environment(lake: str, folder: Path) -> dict[str, str]:
    """Read Lake's environment and apply it ourselves.

    This avoids a Windows failure mode where `lake env lean ...` starts Lean but
    the child does not receive Lake's long `LEAN_PATH`.  A direct process with
    the same environment is both observable and works for `--run` probes.
    """
    try:
        done = subprocess.run(
            [lake, "env"], cwd=folder, capture_output=True, text=True, timeout=1800, check=True
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ToolchainError(
            "The pinned Lake environment could not be resolved; no global Lean fallback was used."
        ) from exc
    env = dict(os.environ)
    for line in done.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            env[key] = value
    return env


def _version(prefix: tuple[str, ...], folder: Path | None, env: Mapping[str, str] | None = None) -> str:
    try:
        # ask through the same route the probe will take: a Lake project may pin another toolchain than the default
        done = subprocess.run(
            [*prefix, "--version"], cwd=folder, env=env, capture_output=True, text=True, timeout=1800, check=True
        )
        return done.stdout.strip().splitlines()[0]
    except (subprocess.SubprocessError, OSError, IndexError):
        return ""


def run_probe(
    tc: Toolchain,
    path: Path,
    names: list[str],
    timeout: int,
    max_working_set_mb: int = 0,
    min_free_virtual_mb: int = 0,
) -> tuple[int, str, str]:
    """Run the probe with explicit time and optional Windows resource bounds.

    Exit code ``-1`` is a timeout and ``-2`` is a resource-bound stop.  Neither is a theorem
    result.  Resource bounds protect other workstation jobs while a large elaboration runs.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(names))
        names_path = handle.name
    try:
        proc = _start([*tc.prefix, "--run", str(PROBE), str(path.resolve()), names_path], tc.cwd, tc.env)
        job_handle = None
        if os.name == "nt" and max_working_set_mb:
            job_handle = _assign_process_memory_limit(proc, max_working_set_mb * 1024**2)
            if job_handle is None:
                _stop_tree(proc)
                return -2, "", "stopped because the requested Windows process-memory limit could not be applied"
        try:
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_tree(proc)
                    try:
                        proc.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        pass
                    return -1, "", f"timed out after {timeout}s"
                try:
                    out, err = proc.communicate(timeout=min(0.25, remaining))
                except subprocess.TimeoutExpired:
                    working_set, free_virtual = _resource_state(proc)
                    reason = ""
                    if max_working_set_mb and working_set is not None and working_set > max_working_set_mb * 1024**2:
                        reason = (
                            f"stopped at {working_set / 1024**2:.0f} MiB working set "
                            f"(limit {max_working_set_mb} MiB)"
                        )
                    elif (
                        min_free_virtual_mb
                        and free_virtual is not None
                        and free_virtual < min_free_virtual_mb * 1024**2
                    ):
                        reason = (
                            f"stopped with {free_virtual / 1024**2:.0f} MiB free virtual memory "
                            f"(minimum {min_free_virtual_mb} MiB)"
                        )
                    if reason:
                        _stop_tree(proc)
                        try:
                            proc.communicate(timeout=30)
                        except subprocess.TimeoutExpired:
                            pass
                        return -2, "", reason
                    continue
                unsigned_code = proc.returncode & 0xFFFFFFFF
                memory_exit = unsigned_code in (0xC0000017, 0xC000012D) or "out of memory" in (err or out).lower()
                if os.name == "nt" and max_working_set_mb and memory_exit:
                    return -2, "", f"stopped at the {max_working_set_mb} MiB process-memory ceiling"
                return proc.returncode, out, err
        finally:
            if job_handle is not None:
                ctypes.windll.kernel32.CloseHandle(job_handle)
    finally:
        Path(names_path).unlink(missing_ok=True)


def _start(args: list[str], cwd: Path | None, env: Mapping[str, str] | None = None) -> subprocess.Popen:
    """Start Lean in its own group, so a timeout can stop it and every child it started."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **group)


def _stop_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.kill()


class _MemoryStatus(Structure):
    _fields_ = [
        ("length", c_ulong),
        ("memory_load", c_ulong),
        ("total_physical", c_ulonglong),
        ("available_physical", c_ulonglong),
        ("total_page_file", c_ulonglong),
        ("available_page_file", c_ulonglong),
        ("total_virtual", c_ulonglong),
        ("available_virtual", c_ulonglong),
        ("available_extended_virtual", c_ulonglong),
    ]


class _ProcessMemoryCounters(Structure):
    _fields_ = [
        ("cb", c_ulong),
        ("page_fault_count", c_ulong),
        ("peak_working_set_size", c_size_t),
        ("working_set_size", c_size_t),
        ("quota_peak_paged_pool_usage", c_size_t),
        ("quota_paged_pool_usage", c_size_t),
        ("quota_peak_nonpaged_pool_usage", c_size_t),
        ("quota_nonpaged_pool_usage", c_size_t),
        ("pagefile_usage", c_size_t),
        ("peak_pagefile_usage", c_size_t),
    ]


class _JobBasicLimitInformation(Structure):
    _fields_ = [
        ("per_process_user_time_limit", c_longlong),
        ("per_job_user_time_limit", c_longlong),
        ("limit_flags", c_ulong),
        ("minimum_working_set_size", c_size_t),
        ("maximum_working_set_size", c_size_t),
        ("active_process_limit", c_ulong),
        ("affinity", c_size_t),
        ("priority_class", c_ulong),
        ("scheduling_class", c_ulong),
    ]


class _IoCounters(Structure):
    _fields_ = [
        ("read_operation_count", c_ulonglong),
        ("write_operation_count", c_ulonglong),
        ("other_operation_count", c_ulonglong),
        ("read_transfer_count", c_ulonglong),
        ("write_transfer_count", c_ulonglong),
        ("other_transfer_count", c_ulonglong),
    ]


class _JobExtendedLimitInformation(Structure):
    _fields_ = [
        ("basic_limit_information", _JobBasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", c_size_t),
        ("job_memory_limit", c_size_t),
        ("peak_process_memory_used", c_size_t),
        ("peak_job_memory_used", c_size_t),
    ]


def _assign_process_memory_limit(proc: subprocess.Popen, limit_bytes: int) -> int | None:
    """Put a Windows process in a job with an OS-enforced per-process commit limit."""
    kernel = ctypes.windll.kernel32
    kernel.CreateJobObjectW.restype = c_void_p
    kernel.SetInformationJobObject.argtypes = (c_void_p, c_ulong, c_void_p, c_ulong)
    kernel.AssignProcessToJobObject.argtypes = (c_void_p, c_void_p)
    kernel.CloseHandle.argtypes = (c_void_p,)
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _JobExtendedLimitInformation()
    # JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info.basic_limit_information.limit_flags = 0x100 | 0x2000
    info.process_memory_limit = limit_bytes
    if not kernel.SetInformationJobObject(job, 9, byref(info), sizeof(info)):
        kernel.CloseHandle(job)
        return None
    if not kernel.AssignProcessToJobObject(job, proc._handle):
        kernel.CloseHandle(job)
        return None
    return job


def _resource_state(proc: subprocess.Popen) -> tuple[int | None, int | None]:
    """Return (process working set, globally available page-file commit) when observable."""
    if os.name != "nt":
        return None, None
    counters = _ProcessMemoryCounters()
    counters.cb = sizeof(counters)
    working_set = None
    if ctypes.windll.psapi.GetProcessMemoryInfo(proc._handle, byref(counters), sizeof(counters)):
        working_set = int(counters.working_set_size)
    status = _MemoryStatus()
    status.length = sizeof(status)
    free_virtual = None
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(status)):
        free_virtual = int(status.available_page_file)
    return working_set, free_virtual


def cache_dir(explicit: str = "") -> Path:
    if explicit:
        return Path(explicit)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "lean4-explainer-lean"
