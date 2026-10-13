import json

import pytest

from scripts.finalize_local_site import collect_trust, write_build_info


def _trust(checked=2, ok=1, failed=0, unavailable=0):
    return {
        "format": 1,
        "provenance": "local-lean-run",
        "toolchain": "Lean (version 4.34.1, test)",
        "probe_sha256_16": "a" * 16,
        "files": {"ok": ok, "failed": failed, "unavailable": unavailable},
        "declarations": {"total": checked, "kernel_checked": checked, "classified": checked},
        "execution": {"elaborated_now": ok, "reused_content_bound_cache": 0},
    }


def test_finalizer_binds_local_trust_records_to_the_release(tmp_path):
    for name, checked in (("one", 2), ("two", 3)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "index.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / name / "trust.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / name / "trust.json").write_text(json.dumps(_trust(checked)), encoding="utf-8")

    info = write_build_info(tmp_path, "b" * 40, "2026-10-13T00:00:00Z")

    assert info["build_mode"] == "local-lean"
    assert info["trust"] == {"corpora": ["one", "two"], "kernel_checked_declarations": 5, "ok_files": 2, "unknown_files": 0}
    assert json.loads((tmp_path / "build-info.json").read_text(encoding="utf-8")) == info


def test_finalizer_rejects_missing_or_empty_lean_evidence(tmp_path):
    (tmp_path / "one").mkdir()
    (tmp_path / "one" / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "one" / "trust.html").write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="missing local Lean trust record"):
        collect_trust(tmp_path)

    (tmp_path / "one" / "trust.json").write_text(json.dumps(_trust(checked=0, ok=0, unavailable=1)), encoding="utf-8")
    with pytest.raises(ValueError, match="zero positively kernel-checked declarations"):
        collect_trust(tmp_path)
