"""Release archives must contain tooling and pinned corpus facts, never hosted L4DEL claims."""

import io
import tarfile
import zipfile

import pytest

from scripts.audit_release_artifacts import audit_archives


def _wheel(path, *names):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "x")


def _sdist(path, *names):
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            data = b"x"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_release_archive_audit_accepts_tooling_only(tmp_path):
    _wheel(tmp_path / "tool.whl", "lean4_explainer_l4del/overlay.py")
    _sdist(tmp_path / "tool.tar.gz", "tool/src/lean4_explainer_l4del/overlay.py")

    assert audit_archives(sorted(tmp_path.iterdir())) == []


@pytest.mark.parametrize(
    "name",
    [
        "lean4_explainer_corpus_oai/overlay.l4del",
        "project/hosted/overlays/manifest.json",
        "project/generated/annotation-manifest.json",
    ],
)
def test_release_archive_audit_rejects_hosted_annotation_material(tmp_path, name):
    archive = tmp_path / "bad.whl"
    _wheel(archive, name)

    assert name in "\n".join(audit_archives([archive]))
