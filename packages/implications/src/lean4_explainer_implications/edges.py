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
    bridge_file = "bridges/X.lean"  # proved, optional: the file that declares the bridge (beside the edge file), checked
                                    #   by `python -m lean4_explainer_implications.pipeline contracts`, which records
                                    #   the result in <edge file stem>.verified.json; without it the bridge is a site
                                    #   declaration, checked when the same build runs Lean
    relation = "x_gives_target"     # strengthens with a bridge file: proves (the contract) -> the target's statement
    improvement = "..."             # strengthens with a bridge file: what the contract gives that the target does not
    construction = "Ns.f"           # supports-construction with a bridge file: the computable definition it is about
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
a claim. Names are checked against the site when it is built (a bridge in a bridge file is checked by Lean instead).

A recorded check counts only while what it checked is unchanged: the edge's contract, the bridge file, the commit and
the corpus files the bridge imports (`fingerprint`, and the record's `inputs`). Any difference makes it stale.
"""

from __future__ import annotations

import hashlib
import json
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
_EDGE_KEYS = {"id", "kind", "from", "to", "hypotheses", "conclusion", "commit", "status", "origin", "argument", "bridge", "evidence", "note",
              "bridge_file", "relation", "improvement", "construction"}
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
    bridge_file: str = ""
    relation: str = ""
    improvement: str = ""
    construction: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        """Every site declaration it names: the sources, the target, and the bridge unless a bridge file declares it."""
        return self.sources + tuple(n for n in (self.target, "" if self.bridge_file else self.bridge) if n)


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
    state: str  # proposed | argued | unchecked | kernel-checked | stale | fails | refuted
    detail: str
    provenance: str = ""  # kernel-checked: "this build" (Lean ran here) or "recorded" (a recorded check this build compared)


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
    fields = {key: _text(row, key, problems, required=False)
              for key in ("argument", "bridge", "evidence", "note", "bridge_file", "relation", "improvement", "construction")}
    for key in ("bridge", "relation", "construction"):
        if fields[key] and not _NAME_RE.match(fields[key]):
            problems.append(f"{fields[key]!r} is not a declaration name")
    if fields["bridge_file"]:
        parts = fields["bridge_file"].replace("\\", "/").split("/")
        if not fields["bridge"]:
            problems.append("a bridge file needs `bridge`, the declaration in it that proves the contract")
        if fields["bridge_file"].startswith(("/", "\\")) or ":" in fields["bridge_file"] or ".." in parts or not fields["bridge_file"].endswith(".lean"):
            problems.append("bridge_file must be a .lean file beside the edge file: a relative path, without ..")
        if status == "proved" and kind == "strengthens":
            for key, what in (("relation", "the declaration that proves the contract gives the target's statement"),
                              ("improvement", "what the contract gives that the target does not")):
                if not fields[key]:
                    problems.append(f"a proved strengthens edge with a bridge file needs `{key}`: {what}")
        if status == "proved" and kind == "supports-construction" and not fields["construction"]:
            problems.append("a proved supports-construction edge with a bridge file needs `construction`, the computable definition")
    else:
        for key in ("relation", "construction"):
            if fields[key]:
                problems.append(f"`{key}` is checked with the bridge file: name `bridge_file` too")
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


def content_sha256(data: bytes) -> str:
    """The SHA-256 of a source file's text with its line endings made LF: a Windows checkout (CRLF) and a Linux one
    (LF) of the same commit give the same digest, and Lean reads both the same way."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def fingerprint(edge: Edge, bridge_sha256: str) -> str:
    """What a recorded check of this edge depended on: the edge's contract and the bridge file's digest."""
    blob = json.dumps({
        "kind": edge.kind, "sources": [_bare(n) for n in edge.sources], "target": _bare(edge.target),
        "hypotheses": list(edge.hypotheses), "conclusion": edge.conclusion, "commit": edge.commit,
        "bridge": edge.bridge, "relation": edge.relation, "construction": edge.construction, "bridge_sha256": bridge_sha256,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _bare(name: str) -> str:
    return name.partition("@")[0]


def verify(
    edge: Edge,
    kernel: Callable[[str], tuple[str, str] | None],
    record: dict | None = None,
    bridge_sha256: str | None = None,
    inputs: dict[str, str | None] | None = None,
) -> Verification:
    """How far this build confirms the edge.

    Without a bridge file, `kernel(name)` is what a Lean run in this build says of the bridge (None without one).
    With one, `record` is its recorded check (from the .verified.json file), `bridge_sha256` the bridge file's digest
    now (None when the file is missing), and `inputs` the digests now of the corpus files the record names (None for a
    file this build cannot read)."""
    if edge.status != "proved":
        detail = {"proposed": "Nothing has checked it.", "argued": "The argument is written out below; Lean has not checked it.", "refuted": edge.evidence}[edge.status]
        return Verification(edge.status, detail)
    bridge = _bare(edge.bridge)  # the name Lean knows, without an @path
    if edge.bridge_file:
        return _recorded(edge, bridge, record, bridge_sha256, inputs or {})
    said = kernel(edge.bridge)
    if said is None:
        return Verification("unchecked", f"Not checked in this build: Lean was not run. The edge file says {bridge} proves it.")
    kind, label = said
    if kind in ("none", "standard"):
        return Verification("kernel-checked", f"Lean's kernel checked {bridge} in this build: {label}.", "this build")
    if kind in ("sorry", "extra"):
        return Verification("fails", f"{bridge} does not prove it in this build ({label}).")
    return Verification("unchecked", f"Not checked in this build: {label}.")


def _recorded(edge: Edge, bridge: str, record: dict | None, bridge_sha256: str | None, inputs: dict[str, str | None]) -> Verification:
    if bridge_sha256 is None:
        return Verification("fails", f"The bridge file {edge.bridge_file} is missing.")
    if not record:
        return Verification("unchecked", f"No recorded check: the edge file says {bridge} in {edge.bridge_file} proves it, "
                            "and nothing has run Lean on it (python -m lean4_explainer_implications.pipeline contracts).")
    when = record.get("checked_at", "")
    if record.get("fingerprint") != fingerprint(edge, bridge_sha256):
        return Verification("stale", f"The check recorded on {when} was of another contract or another bridge file: "
                            "the edge or its bridge changed since, so it says nothing now.")
    rev = str(record.get("corpus_revision", ""))
    if not rev or not (rev.startswith(edge.commit) or edge.commit.startswith(rev)):
        return Verification("stale", f"The check recorded on {when} read the corpus at {rev[:12] or 'an unknown commit'}, not at {edge.commit}.")
    changed = sorted(path for path, digest in (record.get("inputs") or {}).items() if inputs.get(path) not in (None, digest))
    if changed:
        return Verification("stale", f"The check recorded on {when} read {', '.join(changed)}, which differ in this build.")
    if record.get("status") != "checked":
        return Verification("fails", f"The check recorded on {when} failed ({record.get('status')}): {record.get('reason', '')}")
    unread = sorted(path for path in (record.get("inputs") or {}) if inputs.get(path) is None)
    axioms = ", ".join(record.get("axioms") or []) or "none"
    detail = (f"Lean's kernel checked {bridge} against this contract on {when} ({record.get('toolchain', '')}, Mathlib "
              f"{str(record.get('mathlib', ''))[:12]}, corpus {rev[:12]}; axioms: {axioms}). This build did not run Lean: it "
              "shows that record, after comparing the contract, the bridge file and the commit with it")
    detail += f"; it could not read {', '.join(unread)} to compare." if unread else ", and the corpus files it read."
    return Verification("kernel-checked", detail, "recorded")
