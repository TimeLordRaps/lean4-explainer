"""Find Lean and run the probe on one file."""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROBE = Path(__file__).with_name("Probe.lean")
_LAKEFILES = ("lakefile.toml", "lakefile.lean")


@dataclass(frozen=True)
class Toolchain:
    prefix: tuple[str, ...]  # command that runs `lean ARGS...`
    cwd: Path | None  # the Lake project to run in, if any
    version: str  # first line of `lean --version`
    probe_digest: str


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
    lean = shutil.which("lean")
    if lean is None:
        return None
    folder = find_project(root, project)
    lake = shutil.which("lake")
    use_lake = folder is not None and lake is not None
    prefix = (lake, "env", lean) if use_lake else (lean,)
    for attempt in ((prefix, folder), ((lean,), None)) if use_lake else (((lean,), None),):
        found = _version(*attempt)
        if found:
            return Toolchain(attempt[0], attempt[1], found, probe_digest())
    return None


def _version(prefix: tuple[str, ...], folder: Path | None) -> str:
    try:
        # ask through the same route the probe will take: a Lake project may pin another toolchain than the default
        done = subprocess.run(
            [*prefix, "--version"], cwd=folder, capture_output=True, text=True, timeout=1800, check=True
        )
        return done.stdout.strip().splitlines()[0]
    except (subprocess.SubprocessError, OSError, IndexError):
        return ""


def run_probe(tc: Toolchain, path: Path, names: list[str], timeout: int) -> tuple[int, str, str]:
    """Run the probe. Returns (exit code, stdout, stderr); exit code -1 means it timed out."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(names))
        names_path = handle.name
    try:
        proc = _start([*tc.prefix, "--run", str(PROBE), str(path.resolve()), names_path], tc.cwd)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_tree(proc)
            try:
                proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                pass
            return -1, "", f"timed out after {timeout}s"
        return proc.returncode, out, err
    finally:
        Path(names_path).unlink(missing_ok=True)


def _start(args: list[str], cwd: Path | None) -> subprocess.Popen:
    """Start a process in its own group, so that a timeout can stop it with everything it started: `lake env lean`
    starts lean, and elan's `lean` starts the toolchain's."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", **group)


def _stop_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.kill()


def cache_dir(explicit: str = "") -> Path:
    if explicit:
        return Path(explicit)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "lean4-explainer-lean"
