"""The incremental cache lives beside the output and inside the Lean root's parent, so a repo can ship one.

A cache file is never trusted to run code: loading must not call anything the cache names.
"""

import os
import pickle

from lean4_explainer.build import CACHE_FILE, build_site, check_tree, default_cache_dir


class _CallsOnLoad:
    """Pickles as a call to os.mkdir(marker), so loading the payload would create the marker."""

    def __init__(self, marker):
        self.marker = str(marker)

    def __reduce__(self):
        return (os.mkdir, (self.marker,))


def _plant(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(_CallsOnLoad(marker)))


def _lean_root(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "A.lean").write_text("theorem t : True := trivial\n", encoding="utf-8")
    return root


def test_build_does_not_execute_a_planted_cache(tmp_path):
    root = _lean_root(tmp_path)
    out = tmp_path / "docs"
    marker = tmp_path / "executed"
    _plant(default_cache_dir(out) / CACHE_FILE, marker)

    summary = build_site(root, out)

    assert not marker.exists()
    assert summary.declarations == 1
    assert (out / "A.lean.html").is_file()


def test_check_does_not_execute_a_planted_cache(tmp_path):
    root = _lean_root(tmp_path)
    marker = tmp_path / "executed"
    _plant(root.parent / ".lean4-explainer-check" / CACHE_FILE, marker)

    tree = check_tree(root)

    assert not marker.exists()
    assert len(tree.sources) == 1


def test_unreadable_cache_is_ignored(tmp_path):
    root = _lean_root(tmp_path)
    out = tmp_path / "docs"
    cache = default_cache_dir(out) / CACHE_FILE
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"not a pickle")

    summary = build_site(root, out)

    assert summary.declarations == 1
