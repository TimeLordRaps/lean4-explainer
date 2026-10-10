"""The Lean repositories lean4-explainer explains out of the box, each pinned to a commit.

The names double as the pip extras: `pip install lean4-explainer[conjectures]`, `[tutorials]`, `[oai]`, `[all]`.
An extra marks which corpora you care about. The corpus sources are not bundled: `lean4-explainer fetch` and
`lean4-explainer showcase` clone the pinned commit from GitHub and say so before they do.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ExplainerError


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
    source_links: str = "declaration"  # "file" for corpora too large to carry a link per declaration


CORPORA: dict[str, Corpus] = {
    corpus.name: corpus
    for corpus in (
        Corpus(
            "formal-conjectures",
            "Formal Conjectures",
            "google-deepmind/formal-conjectures",
            "1646ca16afd6cc7a693d3bdc9f066c4d3cc01a89",
            "main",
            "conjectures",
            "Open and solved conjectures stated in Lean, one statement per problem.",
        ),
        Corpus(
            "carleson",
            "Carleson's theorem",
            "fpvandoorn/carleson",
            "8972acdfd953c63bb2501ace20d61ced7c0697ec",
            "master",
            "formalization",
            "The formalization of Carleson's theorem on the convergence of Fourier series.",
        ),
        Corpus(
            "flt",
            "Fermat's Last Theorem (FLT)",
            "ImperialCollegeLondon/FLT",
            "f6c6a2fe9796d6d89cd2a0d24e8a453729d881ff",
            "main",
            "formalization",
            "The Imperial College project to formalize a proof of Fermat's Last Theorem.",
        ),
        Corpus(
            "pfr",
            "Polynomial Freiman-Ruzsa (PFR)",
            "teorth/pfr",
            "ce7ac95e620afe0ae448df63477de0b29e4dcf4d",
            "master",
            "formalization",
            "The formalization of the polynomial Freiman-Ruzsa conjecture over characteristic 2.",
        ),
        Corpus(
            "compfiles",
            "Compfiles",
            "dwrensha/compfiles",
            "47b19bbfe5f38dc49379a6b53008d2909c4d71c5",
            "main",
            "competition",
            "Formalized statements and solutions of olympiad-style problems.",
        ),
        Corpus(
            "mil",
            "Mathematics in Lean",
            "leanprover-community/mathematics_in_lean",
            "dd6d752fedb14082f557913c2dccb2d4851e5173",
            "master",
            "tutorial",
            "The tutorial that teaches Lean 4 and mathlib through mathematics. Exercises and solutions share names.",
        ),
        Corpus(
            "tpil",
            "Theorem Proving in Lean 4",
            "leanprover/theorem_proving_in_lean4",
            "4e28129fdd58037f8f5857548d5e99fe4fb0cc57",
            "master",
            "tutorial",
            "The book on Lean 4 itself: dependent types, tactics, inductive types.",
            lake=False,
            include=("book/TPiL.lean", "book/TPiL/*", "examples/Examples.lean", "examples/Examples/*"),
        ),
        Corpus(
            "oai",
            "openai/math",
            "openai/math",
            "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb",
            "main",
            "oai",
            "Lean formalizations that accompany the openai/math manuscripts.",
            lean_root="lean",
            lake=False,
            source_links="file",  # 3.5 million declarations: a link on each would push the site past 1 GB
        ),
    )
}

# pip extra -> corpus names. `lft` and `flt` both name the Fermat's Last Theorem project.
EXTRAS: dict[str, tuple[str, ...]] = {
    "conjectures": ("formal-conjectures",),
    "carleson": ("carleson",),
    "lft": ("flt",),
    "flt": ("flt",),
    "pfr": ("pfr",),
    "compfiles": ("compfiles",),
    "tutorials": ("mil", "tpil"),
    "oai": ("oai",),
    "all": tuple(CORPORA),
}


def select(*names: str | None) -> list[Corpus]:
    """Corpora for extras or corpus names, without repeats, in the order first named. No names means all."""
    wanted = [name for name in names if name]
    if not wanted:
        wanted = ["all"]
    chosen: dict[str, Corpus] = {}
    for name in wanted:
        key = name.strip().lower()
        members = EXTRAS.get(key) or ((key,) if key in CORPORA else None)
        if members is None:
            options = ", ".join(sorted({*EXTRAS, *CORPORA}))
            raise ExplainerError(f"unknown corpus '{name}'; choose from: {options}")
        for member in members:
            chosen.setdefault(member, CORPORA[member])
    return list(chosen.values())
