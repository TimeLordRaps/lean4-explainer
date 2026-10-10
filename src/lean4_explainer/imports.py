"""What each file imports and what imports it. Lean module names are matched to the project's files (`A.B` is
`A/B.lean` under the Lean root); a module from Mathlib or its dependencies links to the Mathlib documentation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

SCOPES = ("all", "import-only", "none")

DOCS = "https://leanprover-community.github.io/mathlib4_docs/"
# Libraries whose modules have a page there (each root's page answered on 2026-10-10)
DOCUMENTED = frozenset({"Mathlib", "Init", "Std", "Lean", "Batteries", "Aesop", "Qq", "Plausible", "ProofWidgets", "LeanSearchClient"})


def module_key(name: str) -> str:
    """`«P».«Def»` and `P.Def` are the same module."""
    return name.replace("«", "").replace("»", "")


def module_of(rel: str) -> str:
    return rel.removesuffix(".lean").replace("/", ".")


def docs_url(name: str) -> str | None:
    key = module_key(name)
    if key.split(".", 1)[0] not in DOCUMENTED:
        return None
    return DOCS + key.replace(".", "/") + ".html"


@dataclass(frozen=True)
class Modules:
    imports: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # file -> the modules it imports, as written
    local: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # file -> the project files it imports
    imported_by: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # file -> the project files importing it
    files: Mapping[str, str] = field(default_factory=dict)  # module key -> file

    def file_of(self, name: str) -> str | None:
        return self.files.get(module_key(name))


def modules(imports: Mapping[str, Sequence[str]]) -> Modules:
    files = {module_key(module_of(rel)): rel for rel in imports}
    local: dict[str, tuple[str, ...]] = {}
    importers: dict[str, list[str]] = {}
    for rel, names in imports.items():
        targets = tuple(dict.fromkeys(target for name in names if (target := files.get(module_key(name))) and target != rel))
        local[rel] = targets
        for target in targets:
            importers.setdefault(target, []).append(rel)
    return Modules(
        imports={rel: tuple(names) for rel, names in imports.items()},
        local=local,
        imported_by={rel: tuple(sorted(users)) for rel, users in importers.items()},
        files=files,
    )
