"""Lake's own files say which directories are library source and which toolchain and dependencies a project pins.

The explainer reads them as text. It never runs Lean or Lake.
"""

import json

from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer.lake import include_patterns, read_lake

TOML = """\
name = "demo"

[[require]]
name = "mathlib"
git = "https://github.com/leanprover-community/mathlib4.git"
rev = "v4.30.0"

[[lean_lib]]
name = "Demo"

[[lean_lib]]
name = "Extra"
roots = ["Extra.One", "Other"]
srcDir = "src"

[[lean_lib]]
name = "Globbed"
globs = ["Globbed.*", "Solo"]
"""


def _write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_toml_project_is_read(tmp_path):
    _write(
        tmp_path,
        {
            "lakefile.toml": TOML,
            "lean-toolchain": "leanprover/lean4:v4.30.0\n",
            "lake-manifest.json": json.dumps(
                {"packages": [{"name": "mathlib", "rev": "abc123", "url": "https://example.org/mathlib"}]}
            ),
        },
    )

    project = read_lake(tmp_path)

    assert project is not None
    assert project.name == "demo"
    assert project.toolchain == "leanprover/lean4:v4.30.0"
    assert [lib.name for lib in project.libs] == ["Demo", "Extra", "Globbed"]
    assert project.requires == (("mathlib", "v4.30.0"),)
    assert project.pinned == (("mathlib", "abc123"),)


def test_library_roots_become_include_patterns(tmp_path):
    _write(tmp_path, {"lakefile.toml": TOML})

    patterns = include_patterns(read_lake(tmp_path))

    assert "Demo.lean" in patterns and "Demo/*" in patterns
    # explicit roots replace the name-based default, so the library name alone is not a root
    assert "src/Extra/One.lean" in patterns and "src/Extra/One/*" in patterns
    assert "src/Other.lean" in patterns
    assert "src/Extra.lean" not in patterns
    assert "Globbed.lean" in patterns and "Globbed/*" in patterns
    assert "Solo.lean" in patterns


def test_lakefile_lean_is_read_for_library_names(tmp_path):
    _write(
        tmp_path,
        {
            "lakefile.lean": "import Lake\nopen Lake DSL\n\npackage demo\n\nlean_lib Foo where\n  srcDir := \"lib\"\n\nlean_lib «Bar»\n",
        },
    )

    project = read_lake(tmp_path)

    assert project is not None
    assert [lib.name for lib in project.libs] == ["Foo", "Bar"]
    assert "lib/Foo/*" in include_patterns(project)
    assert "Bar.lean" in include_patterns(project)


def test_no_lake_files_means_no_project(tmp_path):
    _write(tmp_path, {"A.lean": "theorem a : True := trivial\n"})

    assert read_lake(tmp_path) is None


def test_unreadable_lake_files_do_not_stop_the_read(tmp_path):
    _write(tmp_path, {"lakefile.toml": "this is = = not toml", "lean-toolchain": "x\n"})

    project = read_lake(tmp_path)

    assert project is not None
    assert project.libs == ()
    assert project.issues


def test_include_limits_the_listed_files(tmp_path):
    root = tmp_path / "proj"
    _write(
        root,
        {
            "Demo.lean": "theorem top : True := trivial\n",
            "Demo/A.lean": "theorem a : True := trivial\n",
            "Scripts/Tool.lean": "theorem tool : True := trivial\n",
        },
    )

    summary = build_site(root, tmp_path / "docs", Config(include=("Demo.lean", "Demo/*")))

    assert summary.files == 2
    assert not (tmp_path / "docs" / "Scripts" / "Tool.lean.html").exists()
