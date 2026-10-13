"""Bind a locally Lean-checked static tree to one publishable release manifest."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _corpus_roots(site: Path) -> list[Path]:
    return sorted(path for path in site.iterdir() if path.is_dir() and (path / "index.html").is_file())


def _count(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} is not a non-negative integer")
    return value


def collect_trust(site: Path) -> dict[str, object]:
    corpora = _corpus_roots(site)
    if not corpora:
        raise ValueError("site has no corpus roots")
    kernel_checked = ok_files = unknown_files = 0
    names: list[str] = []
    for corpus in corpora:
        if not (corpus / "trust.html").is_file():
            raise ValueError(f"{corpus.name}: missing public Trust page")
        path = corpus / "trust.json"
        if not path.is_file():
            raise ValueError(f"{corpus.name}: missing local Lean trust record")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"{corpus.name}: unreadable local Lean trust record: {exc}") from exc
        if record.get("format") != 1 or record.get("provenance") != "local-lean-run":
            raise ValueError(f"{corpus.name}: trust record is not from a local Lean run")
        if not str(record.get("toolchain", "")).startswith("Lean (version"):
            raise ValueError(f"{corpus.name}: trust record has no exact Lean toolchain")
        files = record.get("files") if isinstance(record.get("files"), dict) else {}
        declarations = record.get("declarations") if isinstance(record.get("declarations"), dict) else {}
        ok_files += _count(files.get("ok"), f"{corpus.name}: files.ok")
        unknown_files += _count(files.get("failed"), f"{corpus.name}: files.failed")
        unknown_files += _count(files.get("unavailable"), f"{corpus.name}: files.unavailable")
        kernel_checked += _count(
            declarations.get("kernel_checked"), f"{corpus.name}: declarations.kernel_checked"
        )
        names.append(corpus.name)
    if kernel_checked == 0:
        raise ValueError("local Lean records contain zero positively kernel-checked declarations")
    return {
        "corpora": names,
        "kernel_checked_declarations": kernel_checked,
        "ok_files": ok_files,
        "unknown_files": unknown_files,
    }


def write_build_info(site: Path, repository_sha: str, built_at: str | None = None) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", repository_sha):
        raise ValueError("repository SHA must be 40 lowercase hexadecimal characters")
    trust = collect_trust(site)
    when = built_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    info = {
        "format": 1,
        "repository_sha": repository_sha,
        "built_at": when,
        "build_mode": "local-lean",
        "trust": trust,
    }
    (site / "build-info.json").write_text(json.dumps(info, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--repository-sha", required=True)
    parser.add_argument("--built-at")
    args = parser.parse_args()
    try:
        info = write_build_info(args.site.resolve(), args.repository_sha, args.built_at)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    trust = info["trust"]
    print(
        f"local Lean release manifest: {trust['kernel_checked_declarations']} positively kernel-checked declarations, "
        f"{trust['ok_files']} checked files, {trust['unknown_files']} UNKNOWN files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
