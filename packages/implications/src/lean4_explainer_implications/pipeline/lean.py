"""Run `Pipeline.lean` (extract, attempt, contract) in a workspace's environment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..edges import content_sha256
from . import processes as P
from .workspace import LEAN_COMMIT_GB

PIPELINE = Path(__file__).resolve().parent.parent / "lean" / "Pipeline.lean"


def pipeline_digest() -> str:
    """The rule set's identity: a change to the Lean side changes every cache key. Line endings do not count, so a
    Windows checkout and a Linux one of the same commit name the same rule set."""
    return content_sha256(PIPELINE.read_bytes())[:16]


@dataclass(frozen=True)
class LeanRun:
    code: int  # -1: timed out
    stdout: str
    stderr: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.code == 0

    def tail(self, n: int = 1200) -> str:
        return (self.stderr.strip() or self.stdout.strip())[-n:]


def run(env: dict[str, str], cwd: Path, args: list[str], timeout: int, log: Callable[[str], None] = print, commit_gb: float = LEAN_COMMIT_GB + 6.0,
        settle_seconds: float = 120.0) -> LeanRun:
    """Run Pipeline.lean with `args`. With `commit_gb` > 0 the launch waits until the system can commit that much more,
    and parallel launches go one at a time (`processes.launch`). A timeout stops the process tree."""
    proc, began = P.launch(["lean", "--run", str(PIPELINE), *args], cwd, env, commit_gb, 0.8 * LEAN_COMMIT_GB, settle_seconds, log)
    return LeanRun(*P.finish(proc, began, timeout))
