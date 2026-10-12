"""Reject hosted annotation content from Python release archives."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path


def _members(path: Path) -> list[str]:
    if path.suffix in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return archive.getnames()
    raise ValueError(f"unsupported release archive: {path}")


def audit_archives(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        for raw in _members(path):
            name = raw.replace("\\", "/")
            lowered = name.lower()
            basename = lowered.rsplit("/", 1)[-1]
            if (
                lowered.endswith(".l4del")
                or "/hosted/overlays/" in f"/{lowered}"
                or basename in {"annotation-manifest.json", "overlay-manifest.json"}
            ):
                failures.append(f"{path}: forbidden hosted annotation material: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()
    failures = audit_archives(args.archives)
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
