"""A Lake project root holds build configuration and dependency code next to its library sources.

Lake's own files are never library source, so they are not listed. The explainer never runs Lean or Lake.
"""

from lean4_explainer.build import build_site
from lean4_explainer.config import Config


def _write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_root_lakefile_is_not_listed_as_source(tmp_path):
    root = tmp_path / "lean"
    _write(
        root,
        {
            "lakefile.lean": "import Lake\nopen Lake DSL\n\nprivate def helper : Nat := 1\n\npackage demo\n",
            "A.lean": "theorem a_fact : True := trivial\n",
        },
    )
    out = tmp_path / "docs"

    summary = build_site(root, out)

    assert summary.files == 1
    assert summary.declarations == 1
    assert not (out / "lakefile.lean.html").exists()


def test_nested_lakefile_is_not_listed_as_source(tmp_path):
    root = tmp_path / "lean"
    _write(
        root,
        {
            "Sub/lakefile.lean": "import Lake\npackage sub\n",
            "A.lean": "theorem a_fact : True := trivial\n",
        },
    )

    summary = build_site(root, tmp_path / "docs")

    assert summary.files == 1


def test_lake_packages_directory_is_not_listed(tmp_path):
    root = tmp_path / "lean"
    _write(
        root,
        {
            "lake-packages/dep/Dep.lean": "theorem dep_fact : True := trivial\n",
            "A.lean": "theorem a_fact : True := trivial\n",
        },
    )

    summary = build_site(root, tmp_path / "docs")

    assert summary.files == 1
    assert summary.declarations == 1


def test_user_exclude_still_applies_alongside_the_lake_defaults(tmp_path):
    root = tmp_path / "lean"
    _write(
        root,
        {
            "lakefile.lean": "import Lake\npackage demo\n",
            "Skip.lean": "theorem skipped : True := trivial\n",
            "A.lean": "theorem a_fact : True := trivial\n",
        },
    )

    summary = build_site(root, tmp_path / "docs", Config(exclude=("Skip.lean",)))

    assert summary.files == 1


def test_lake_manifest_toolchain_and_dot_lake_are_ignored(tmp_path):
    root = tmp_path / "lean"
    _write(
        root,
        {
            "lakefile.toml": 'name = "demo"\n',
            "lake-manifest.json": "{}\n",
            "lean-toolchain": "leanprover/lean4:v4.0.0\n",
            ".lake/packages/dep/Dep.lean": "theorem dep_fact : True := trivial\n",
            "A.lean": "theorem a_fact : True := trivial\n",
        },
    )
    out = tmp_path / "docs"

    summary = build_site(root, out)

    assert summary.files == 1
    assert summary.declarations == 1
    assert not any(path.name in {"lakefile.toml", "lake-manifest.json", "lean-toolchain"} for path in out.rglob("*"))
