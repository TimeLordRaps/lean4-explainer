"""A corpus is a Lean repository pinned to a commit. Each one is its own installable package.

`pip install lean4-explainer[conjectures]` (or `[carleson]`, `[pfr]`, `[compfiles]`, `[tutorials]`, `[oai]`,
`[all]`) installs the matching `lean4-explainer-<name>` packages. Each holds the pinned description of one
repository: its commit, library roots, license and license notes. The sources are not bundled: `fetch` and
`showcase` clone the pinned commit from GitHub, and say so before they do.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from lean4_explainer.errors import ExplainerError


@dataclass(frozen=True)
class Corpus:
    name: str
    title: str
    repo: str  # "owner/name" on GitHub
    commit: str  # full 40-hex commit the site is built from
    branch: str
    kind: str  # formalization | conjectures | competition | tutorial | oai
    blurb: str
    lean_root: str = ""  # subdirectory of the checkout that holds the Lean sources
    lake: bool = True  # read library roots from the Lake files
    include: tuple[str, ...] = ()  # patterns relative to the checkout, used when `lake` is false
    exclude: tuple[str, ...] = ()
    license: str = "Apache-2.0"  # SPDX id of the repository LICENSE file, read from the pinned checkout
    license_note: str = ""  # extra terms the repository states for part of its content
    accent: str = "#555555"  # card and link colour on the landing page
    theme_css: str = ""  # appended to this corpus's stylesheet (see themes.make_theme)
    extra_kinds: tuple[str, ...] = ()  # declaration keywords beyond Lean's own, such as compfiles' `problem`
    overlay: str = ""  # path to an L4DEL sidecar overlay for this corpus (annotations kept outside the upstream sources)
    source_links: str = "declaration"  # "file" for corpora too large to carry a link per declaration
    options: tuple[tuple[str, object], ...] = ()  # extension settings for this corpus, such as ("map_dependencies", False)


def package_file(module_file: str, name: str) -> str:
    """Path of a data file that sits beside a corpus package's __init__.py, or "" when it is absent."""
    path = Path(module_file).with_name(name)
    return str(path) if path.is_file() else ""


GROUP = "lean4_explainer.corpora"

# pip extra -> corpus names.
EXTRAS: dict[str, tuple[str, ...]] = {
    "conjectures": ("formal-conjectures",),
    "carleson": ("carleson",),
    "flt": ("flt",),
    "pfr": ("pfr",),
    "compfiles": ("compfiles",),
    "tutorials": ("mil", "tpil"),
    "oai": ("oai",),
    "all": ("formal-conjectures", "carleson", "flt", "pfr", "compfiles", "mil", "tpil", "oai"),
}

_active: dict[str, Corpus] | None = None


def activate(corpora: list[Corpus] | None) -> None:
    """Use exactly these corpora (tests and embedding); `None` goes back to the installed packages."""
    global _active
    _active = None if corpora is None else {c.name: c for c in corpora}


def installed() -> dict[str, Corpus]:
    """Corpora from installed `lean4-explainer-<name>` packages, in the order of `EXTRAS['all']`."""
    if _active is not None:
        return dict(_active)
    found: dict[str, Corpus] = {}
    for entry in metadata.entry_points(group=GROUP):
        try:
            corpus = entry.load()
        except Exception as exc:  # a broken corpus package must not hide the others
            import sys

            print(f"warning: corpus {entry.name} could not be loaded: {exc}", file=sys.stderr)
            continue
        found[corpus.name] = corpus
    order = {name: i for i, name in enumerate(EXTRAS["all"])}
    return dict(sorted(found.items(), key=lambda item: (order.get(item[0], len(order)), item[0])))


def select(*names: str | None) -> list[Corpus]:
    """Installed corpora for extras or corpus names, without repeats, in the order first named. No names: all installed."""
    available = installed()
    wanted = [name for name in names if name]
    if not wanted:
        if not available:
            raise ExplainerError("no corpus is installed; try: pip install lean4-explainer[all]")
        return list(available.values())
    chosen: dict[str, Corpus] = {}
    for name in wanted:
        key = name.strip().lower()
        members = EXTRAS.get(key) or ((key,) if key in EXTRAS["all"] else None)
        if members is None:
            options = ", ".join(sorted({*EXTRAS, *EXTRAS["all"]}))
            raise ExplainerError(f"unknown corpus '{name}'; choose from: {options}")
        for member in members:
            if member not in available:
                extra = key if key in EXTRAS else next(e for e, group in EXTRAS.items() if member in group and e != "all")
                raise ExplainerError(f"corpus '{member}' is not installed; try: pip install lean4-explainer[{extra}]")
            chosen.setdefault(member, available[member])
    return list(chosen.values())
