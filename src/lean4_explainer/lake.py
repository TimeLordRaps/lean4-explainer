"""Read a Lake project's own files as text: library roots, pinned toolchain, dependencies.

Lean and Lake are never run. `lakefile.toml` is parsed as TOML. `lakefile.lean` is Lean code, so it is
scanned for `package` and `lean_lib` lines only, which is a best-effort read and says so in `issues`.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LakeLib:
    name: str
    roots: tuple[str, ...]  # module names such as "PFRPalomar.Challenge"
    globs: tuple[str, ...]
    src_dir: str = ""


@dataclass(frozen=True)
class LakeProject:
    name: str
    toolchain: str | None
    libs: tuple[LakeLib, ...]
    requires: tuple[tuple[str, str], ...]  # (package, rev or "" when unpinned in the lakefile)
    pinned: tuple[tuple[str, str], ...]  # (package, commit) from lake-manifest.json
    source_file: str
    issues: tuple[str, ...] = ()


def read_lake(root: Path) -> LakeProject | None:
    toml_path, lean_path = root / "lakefile.toml", root / "lakefile.lean"
    if not toml_path.is_file() and not lean_path.is_file():
        return None
    issues: list[str] = []
    name, libs, requires = "", (), ()
    if toml_path.is_file():
        source = "lakefile.toml"
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8-sig"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
            issues.append(f"warning: could not read lakefile.toml: {exc}")
        else:
            name, libs, requires = _from_toml(data)
    else:
        source = "lakefile.lean"
        issues.append("warning: lakefile.lean is Lean code; only package and lean_lib lines were read")
        try:
            name, libs = _from_lean(lean_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"warning: could not read lakefile.lean: {exc}")
    return LakeProject(
        name=name or root.resolve().name,
        toolchain=_toolchain(root),
        libs=tuple(libs),
        requires=tuple(requires),
        pinned=_manifest(root, issues),
        source_file=source,
        issues=tuple(issues),
    )


def include_patterns(project: LakeProject) -> tuple[str, ...]:
    """Glob patterns, relative to the Lake root, for the files of every library.

    A root or glob `A.B` names `A/B.lean`; roots and `.*`/`.+` globs also take the folder `A/B/`.
    A plain glob names its module only.
    """
    found: dict[str, None] = {}
    for lib in project.libs:
        prefix = f"{lib.src_dir.strip('/')}/" if lib.src_dir.strip("/") not in ("", ".") else ""
        for module, folder in [(root, True) for root in lib.roots] + [_glob(glob) for glob in lib.globs]:
            path = prefix + module.replace(".", "/")
            found[path + ".lean"] = None
            if folder:
                found[path + "/*"] = None
    return tuple(found)


def _glob(glob: str) -> tuple[str, bool]:
    for suffix in (".*", ".+"):
        if glob.endswith(suffix):
            return glob[: -len(suffix)], True
    return glob, False


def _from_toml(data: dict) -> tuple[str, tuple[LakeLib, ...], tuple[tuple[str, str], ...]]:
    top_src = str(data.get("srcDir", ""))
    libs = []
    for entry in data.get("lean_lib", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        lib_name = entry["name"]
        roots = tuple(str(item) for item in entry.get("roots", [lib_name]))
        globs = tuple(str(item) for item in entry.get("globs", []))
        libs.append(LakeLib(lib_name, roots, globs, str(entry.get("srcDir", top_src))))
    requires = tuple(
        (str(entry["name"]), str(entry.get("rev", "")))
        for entry in data.get("require", [])
        if isinstance(entry, dict) and "name" in entry
    )
    return str(data.get("name", "")), tuple(libs), requires


_PACKAGE_RE = re.compile(r"^package\s+(?:«([^»]+)»|([A-Za-z_][\w.]*))", re.MULTILINE)
_LIB_RE = re.compile(r"^lean_lib\s+(?:«([^»]+)»|([A-Za-z_][\w.]*))([^\n]*(?:\n[ \t]+[^\n]*)*)", re.MULTILINE)
_SRC_DIR_RE = re.compile(r'srcDir\s*:=\s*"([^"]+)"')
_ROOTS_RE = re.compile(r"roots\s*:=\s*#\[([^\]]*)\]")


def _from_lean(text: str) -> tuple[str, tuple[LakeLib, ...]]:
    package = _PACKAGE_RE.search(text)
    libs = []
    for match in _LIB_RE.finditer(text):
        lib_name = match.group(1) or match.group(2)
        body = match.group(3)
        src = _SRC_DIR_RE.search(body)
        roots = _ROOTS_RE.search(body)
        root_names = tuple(re.findall(r"`([\w.]+)", roots.group(1))) if roots else (lib_name,)
        libs.append(LakeLib(lib_name, root_names or (lib_name,), (), src.group(1) if src else ""))
    return (package.group(1) or package.group(2)) if package else "", tuple(libs)


def _toolchain(root: Path) -> str | None:
    try:
        text = (root / "lean-toolchain").read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def _manifest(root: Path, issues: list[str]) -> tuple[tuple[str, str], ...]:
    path = root / "lake-manifest.json"
    if not path.is_file():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return tuple((str(p["name"]), str(p.get("rev", ""))) for p in data.get("packages", []))
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        issues.append(f"warning: could not read lake-manifest.json: {exc}")
        return ()
