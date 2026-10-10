"""Implication edges: what one result could establish about another, each with an explicit contract.

A dependency (the map, the Lean extension's "Proof uses") records which declarations a proof actually invokes. An
implication edge records what a result could establish, even when the released proof goes another way. It is a claim,
so it keeps its contract and how far it has been checked.

The edges live in a sidecar TOML file, never in the Lean sources:

    [[edge]]
    id = "explicit-gap"             # unique: lowercase letters, digits and hyphens
    kind = "strengthens"            # strengthens | composes-with | specializes-to | supports-construction
    from = ["Ns.source"]            # the declarations it starts from (composes-with: two or more)
    to = "Ns.target"                # the declaration it reaches (optional for composes-with)
    hypotheses = ["(q : ℕ) ..."]    # the exact hypotheses, as Lean text ([] when the sources are all it takes)
    conclusion = "..."              # the derived conclusion, as Lean text
    commit = "fd4aeeb2ee4f"         # the source commit the statements were read at (7 to 40 hex digits)
    status = "argued"               # proposed | argued | proved | refuted
    origin = "..."                  # who proposed it, and when
    argument = "..."                # argued: the argument in words, and whose it is
    bridge = "Ns.edge_lemma"        # proved: a Lean declaration that states hypotheses -> conclusion and proves it
    evidence = "..."                # refuted: the counterexample or the step that fails
    note = "..."                    # optional

    [[candidate]]                   # a suggestion with no contract yet, shown apart from the edges
    id = "..."
    kind = "composes-with"
    from = ["Ns.a", "Ns.b"]
    to = "Ns.c"                     # optional
    phrase = "..."                  # the suggestion, in its proposer's words
    origin = "..."
    missing = "..."                 # what it needs to become an edge

Every key is checked: an unknown key, a missing one or a contract with a gap is an error, so a typo never passes as
a claim. Names are checked against the site when it is built.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass

KINDS = {
    # kind: (label, as the source says it, as the target says it, what the contract means)
    "strengthens": (
        "Strengthens",
        "strengthens",
        "is strengthened by",
        "From the sources and the hypotheses, the conclusion follows, and the conclusion gives the target's statement "
        "with more: an explicit constant, a weaker hypothesis, a wider range.",
    ),
    "composes-with": (
        "Composes with",
        "composes with",
        "is reached by composing",
        "The sources together give the conclusion, and it needs each of them.",
    ),
    "specializes-to": (
        "Specializes to",
        "specializes to",
        "is a special case of",
        "The target's statement is the source's general statement with particular values or in a narrower setting; "
        "the hypotheses say which.",
    ),
    "supports-construction": (
        "Supports an executable construction",
        "supports the construction",
        "is a construction supported by",
        "The sources justify a computable definition, the target, and the conclusion says what it computes.",
    ),
}
STATUSES = {
    "proposed": "Proposed: someone suggested it. No argument is recorded, and nothing has checked it.",
    "argued": "Argued: the argument is written out below. Lean has not checked it.",
    "proved": "Proved in Lean: the bridge declaration states the hypotheses and the conclusion, and proves them.",
    "refuted": "Refuted: the evidence below shows it does not hold as stated.",
}
_NEEDS = {"argued": "argument", "proved": "bridge", "refuted": "evidence"}
_EDGE_KEYS = {"id", "kind", "from", "to", "hypotheses", "conclusion", "commit", "status", "origin", "argument", "bridge", "evidence", "note"}
_EDGE_REQUIRED = ("id", "kind", "from", "hypotheses", "conclusion", "commit", "status", "origin")
_CANDIDATE_KEYS = {"id", "kind", "from", "to", "phrase", "origin", "missing", "note"}
_CANDIDATE_REQUIRED = ("id", "kind", "from", "phrase", "origin")
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
_NAME_RE = re.compile(r"^[^\s,]+$")
MAX_TEXT = 4000


@dataclass(frozen=True)
class Edge:
    id: str
    kind: str
    sources: tuple[str, ...]
    target: str
    hypotheses: tuple[str, ...]
    conclusion: str
    commit: str
    status: str
    origin: str
    argument: str = ""
    bridge: str = ""
    evidence: str = ""
    note: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        """Every declaration it names: the sources, the target, the bridge."""
        return self.sources + tuple(n for n in (self.target, self.bridge) if n)


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: str
    sources: tuple[str, ...]
    target: str
    phrase: str
    origin: str
    missing: str = ""
    note: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        return self.sources + ((self.target,) if self.target else ())


@dataclass(frozen=True)
class Found:
    edges: tuple[Edge, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    problems: tuple[str, ...] = ()  # each one an error: the file says something that is not a contract


@dataclass(frozen=True)
class Verification:
    state: str  # proposed | argued | unchecked | kernel-checked | fails | refuted
    detail: str


def load(text: str) -> Found:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return Found(problems=(f"not valid TOML: {exc}",))
    problems: list[str] = []
    for table in sorted(set(data) - {"edge", "candidate"}):
        problems.append(f"unknown table '{table}': the file has [[edge]] and [[candidate]] tables")
    edges, candidates, seen = [], [], set()
    for table, keys, required, make, into in (
        ("edge", _EDGE_KEYS, _EDGE_REQUIRED, _edge, edges),
        ("candidate", _CANDIDATE_KEYS, _CANDIDATE_REQUIRED, _candidate, candidates),
    ):
        rows = data.get(table, [])
        if not isinstance(rows, list):
            problems.append(f"'{table}' must be an array of tables: write [[{table}]]")
            continue
        for k, row in enumerate(rows, 1):
            where = f"{table} {row.get('id', k)!r}" if isinstance(row, dict) else f"{table} {k}"
            own = _check(row, keys, required)
            if not own:
                own = make(row)
            if isinstance(own, list):
                problems.extend(f"{where}: {p}" for p in own)
                continue
            if own.id in seen:
                problems.append(f"{where}: id '{own.id}' is used twice")
                continue
            seen.add(own.id)
            into.append(own)
    return Found(tuple(edges), tuple(candidates), tuple(problems))


def _check(row, keys, required) -> list[str]:
    if not isinstance(row, dict):
        return ["must be a table"]
    problems = [f"unknown key '{key}'" for key in sorted(set(row) - keys)]
    problems += [f"missing key '{key}'" for key in required if key not in row]
    return problems


def _text(row, key, problems, required=True) -> str:
    value = row.get(key, "")
    if not isinstance(value, str):
        problems.append(f"{key} must be text")
        return ""
    value = value.strip()
    if required and not value:
        problems.append(f"{key} must not be empty")
    if len(value) > MAX_TEXT:
        problems.append(f"{key} is longer than {MAX_TEXT} characters")
    return value


def _ends(row, problems) -> tuple[tuple[str, ...], str, str]:
    kind = row.get("kind")
    if kind not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}, not {kind!r}")
    ident = row.get("id")
    if not isinstance(ident, str) or not _ID_RE.match(ident):
        problems.append(f"id must be lowercase letters, digits and hyphens, not {ident!r}")
    sources = row.get("from")
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        problems.append("from must be a list of declaration names")
        sources = []
    elif not sources:
        problems.append("from must name at least one declaration")
    for name in sorted({s for s in sources if sources.count(s) > 1}):
        problems.append(f"from names {name} twice")
    target = row.get("to", "")
    if not isinstance(target, str):
        problems.append("to must be one declaration name")
        target = ""
    for name in list(sources) + ([target] if target else []):
        if not _NAME_RE.match(name):
            problems.append(f"{name!r} is not a declaration name")
    if kind == "composes-with" and len(sources) < 2:
        problems.append("a composes-with edge needs two or more names in `from`")
    elif kind in KINDS and kind != "composes-with" and not target:
        problems.append(f"a {kind} edge needs `to`")
    if target and target in sources:
        problems.append(f"{target} is both in `from` and `to`")
    return tuple(s.strip() for s in sources), target.strip(), kind or ""


def _edge(row) -> Edge | list[str]:
    problems: list[str] = []
    sources, target, kind = _ends(row, problems)
    hypotheses = row.get("hypotheses")
    if not isinstance(hypotheses, list) or not all(isinstance(h, str) and h.strip() for h in hypotheses):
        problems.append("hypotheses must be a list of Lean texts")
        hypotheses = []
    conclusion = _text(row, "conclusion", problems)
    commit = row.get("commit")
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        problems.append(f"commit must be 7 to 40 hexadecimal digits, not {commit!r}")
    status = row.get("status")
    if status not in STATUSES:
        problems.append(f"status must be one of {', '.join(STATUSES)}, not {status!r}")
    elif status in _NEEDS and not str(row.get(_NEEDS[status], "")).strip():
        problems.append(f"{'an' if status[0] in 'aeiou' else 'a'} {status} edge needs `{_NEEDS[status]}`")
    fields = {key: _text(row, key, problems, required=False) for key in ("argument", "bridge", "evidence", "note")}
    if fields["bridge"] and not _NAME_RE.match(fields["bridge"]):
        problems.append(f"{fields['bridge']!r} is not a declaration name")
    origin = _text(row, "origin", problems)
    if problems:
        return problems
    return Edge(row["id"], kind, sources, target, tuple(h.strip() for h in hypotheses), conclusion, commit, status, origin, **fields)


def _candidate(row) -> Candidate | list[str]:
    problems: list[str] = []
    sources, target, kind = _ends(row, problems)
    phrase = _text(row, "phrase", problems)
    origin = _text(row, "origin", problems)
    missing = _text(row, "missing", problems, required=False)
    note = _text(row, "note", problems, required=False)
    if problems:
        return problems
    return Candidate(row["id"], kind, sources, target, phrase, origin, missing, note)


def verify(edge: Edge, kernel: Callable[[str], tuple[str, str] | None]) -> Verification:
    """How far this build confirms the edge. `kernel(name)` is what a Lean run says of a declaration, None without one."""
    if edge.status != "proved":
        detail = {"proposed": "Nothing has checked it.", "argued": "The argument is written out below; Lean has not checked it.", "refuted": edge.evidence}[edge.status]
        return Verification(edge.status, detail)
    said = kernel(edge.bridge)
    bridge = edge.bridge.partition("@")[0]  # the name Lean knows, without an @path
    if said is None:
        return Verification("unchecked", f"Not checked in this build: Lean was not run. The edge file says {bridge} proves it.")
    kind, label = said
    if kind in ("none", "standard"):
        return Verification("kernel-checked", f"Lean's kernel checked {bridge} in this build: {label}.")
    if kind in ("sorry", "extra"):
        return Verification("fails", f"{bridge} does not prove it in this build ({label}).")
    return Verification("unchecked", f"Not checked in this build: {label}.")
