"""Which declarations of the project each declaration uses, read from its source text.

Lean is not run. A declaration uses another when a name in its text resolves, the way Lean looks names up, to a
declaration of the same project that its file can see:

- a name is tried inside each enclosing namespace (innermost first), as written, then inside each `open` namespace;
- a file sees its own declarations and those of the project files it imports, directly or through other imports;
- a local name hides a project name of the same spelling: the declaration's own parameters, `variable`s, the names
  `fun`, `∀`, `∃`, `∑`, … bind, names that tactics introduce (`intro`, `obtain`, `have`, `rcases … with`, …), the
  variables of `| pattern =>` arms, and argument names written as `(name := …)`.

Names from libraries (Mathlib) do not resolve here and are left out, so the map shows how the project is built on
itself. Comments and strings are already blanked out of the code Lean extensions see, so names in them never count.
One-letter names are not followed: they are nearly always local, and a project that names a constant `D` loses
those links rather than gaining false ones.

Missed, because they need Lean's elaborator: a project name reached through a value's field (`P.freyCurve` written as
a method on a value of type `FreyPackage`), names that macros build, and a global used inside a declaration that
also binds a local of the same spelling.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

# a Lean identifier with its dotted parts, where a part may be «quoted» (kept as written, as the index keeps it);
# `@` and `_root_.` are stripped later
_PART = r"(?:(?:[^\W\d]|_)[\w'!?]*|«[^»\n]*»)"
IDENT = re.compile(rf"(?<![\w.'!?»])@?({_PART}(?:\.{_PART})*)")
_ATOM = re.compile(r"(?<![\w.'!?»])(?:(?:[^\W\d]|_)[\w'!?]*|«[^»\n]*»)(?![\w'!?]|\.[\w«])")
_OPEN = re.compile(r"^[ \t]*open[ \t]+(?:scoped[ \t]+)?([^\n]*)$", re.M)
# after these come the names an `open` selects, hides or renames, or what it is scoped to: not namespaces
_OPEN_END = frozenset(("in", "hiding", "renaming"))
# `import X`, and the module system's `public import X`, `meta import X`, `import all X`
_IMPORT = re.compile(r"^(?:(?:public|private|meta)[ \t]+)*import[ \t]+(?:all[ \t]+)?([^\n]*)$", re.M)
# a top-level command after a declaration ends it; what follows belongs to no declaration
_COMMAND = re.compile(
    r"^(?:variable|omit|include|open|section|namespace|end|universe|set_option|attribute|mutual|noncomputable[ \t]+section"
    r"|#\w+|(?:local[ \t]+|scoped[ \t]+)?(?:notation|infix|infixl|infixr|prefix|postfix|macro|syntax|elab"
    r"|macro_rules|elab_rules))\b"
)
# words that are never project declarations; leaving them out keeps the index small
STOP = frozenset(
    """
    fun by have show from at with if then else match let in do return theorem lemma def abbrev structure class
    inductive instance example where deriving extends namespace section end open variable universe noncomputable
    private protected partial unsafe mutual termination_by decreasing_by calc using only this Type Prop Sort
    true false True False sorry simp simp_all exact apply intro intros rw rwa refine constructor cases rcases obtain
    induction use exists linarith nlinarith positivity norm_num ring ring_nf field_simp omega decide aesop gcongr
    congr ext funext unfold dsimp simpa specialize contradiction exfalso by_contra by_cases push_neg trivial rfl
    assumption tauto split_ifs split left right subst set change convert filter_upwards interval_cases fin_cases
    """.split()
)
_MAX_NAMES = 400  # per declaration; a giant proof still gets its first few hundred names

# ---- binders --------------------------------------------------------------------------------------------------
_OPENERS = {"(": ")", "{": "}", "⦃": "⦄", "[": "]", "⟨": "⟩"}
_RUN_END = frozenset(STOP | {"in", "at", "using", "with", "then", "else", "do", "from", "generalizing"})
_HEAD = re.compile(
    r"(?<![\w.'])(?:theorem|lemma|def|abbrev|instance|structure|class|inductive|opaque|axiom|example)[ \t]+"
    rf"(?:{_PART}(?:\.{_PART})*[ \t]*)?"
)
_BINDS = re.compile(r"(?<![\w.'!?])(?:fun|λ|∀|∃!?|Π|Σ|∑|∏|⋃|⋂|⨆|⨅|∫⁻?|∮)(?![\w'!?])")
_TACTIC_RUN = re.compile(
    r"(?<![\w.'!?])(?:intro|intros|rintro|introv|rename_i|ext|funext|choose!?|obtain|case'?|next|with|variable"
    r"|have|haveI|let|letI|set|replace|by_cases|by_contra!?|generalize)(?![\w'!?])"
)
_NAMED_ARG = re.compile(rf"\([ \t]*({_PART})[ \t]*:=")
_ARM = re.compile(r"(?:^|[\s(])\|[ \t]+([^|\n]*?)[ \t]*=>")
_SET_BUILDER = re.compile(rf"\{{[ \t]*({_PART}(?:[ \t]+{_PART})*)[ \t]*(?:\||:(?!=)|∈|//)")


def _group_end(code: str, start: int, limit: int = 2000) -> int:
    """The index just past the bracket that closes the one at `start` (or -1 if it does not close soon)."""
    depth = 0
    for i in range(start, min(len(code), start + limit)):
        c = code[i]
        if c in _OPENERS:
            depth += 1
        elif c in _OPENERS.values():
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _top_level_colon(inner: str) -> int:
    """Where `(x y : T)` has its `:` (not `:=`), at the group's own depth; -1 if none."""
    depth = 0
    for i, c in enumerate(inner):
        if c in _OPENERS:
            depth += 1
        elif c in _OPENERS.values():
            depth -= 1
        elif c == ":" and depth == 0 and inner[i + 1 : i + 2] != "=":
            return i
    return -1


def _binder_run(code: str, pos: int, bound: set[str]) -> None:
    """Names bound by what follows a binding word: bare names, `(x y : T)`, `{α}`, `[inst : C]`, `⟨a, b⟩`, `_`."""
    n = len(code)
    for _ in range(64):
        while pos < n and code[pos] in " \t\n":
            pos += 1
        if pos >= n:
            return
        c = code[pos]
        if c in _OPENERS:
            end = _group_end(code, pos)
            if end < 0:
                return
            inner = code[pos + 1 : end - 1]
            if c == "⟨":
                _all_atoms(inner, bound)
            else:
                colon = _top_level_colon(inner)
                if colon >= 0:
                    _all_atoms(inner[:colon], bound)
                elif c != "[":
                    _leading_atoms(inner, bound)  # `(x y)`, `{α}`, or `(I ∈ s)`: the names before anything else
            pos = end
            continue
        if c in "_@|":  # a hole, an explicit-argument marker, or the next alternative of an rcases pattern
            pos += 1
            continue
        match = _ATOM.match(code, pos)
        if match is None or match.group(0) in _RUN_END:
            return
        bound.add(match.group(0))
        pos = match.end()


def _leading_atoms(text: str, bound: set[str]) -> None:
    pos = 0
    while True:
        while pos < len(text) and text[pos] in " \t\n":
            pos += 1
        match = _ATOM.match(text, pos)
        if match is None or match.group(0) in _RUN_END:
            return
        bound.add(match.group(0))
        pos = match.end()


def _all_atoms(text: str, bound: set[str]) -> None:
    bound.update(atom for atom in (m.group(0) for m in _ATOM.finditer(text)) if atom not in _RUN_END)


def bound_in(code: str) -> frozenset[str]:
    """The local names a declaration's text binds (its parameters, and every binder in its statement and proof)."""
    bound: set[str] = set()
    for match in _HEAD.finditer(code):
        _binder_run(code, match.end(), bound)
    for match in _BINDS.finditer(code):
        _binder_run(code, match.end(), bound)
    for match in _TACTIC_RUN.finditer(code):
        _binder_run(code, match.end(), bound)
    for match in _NAMED_ARG.finditer(code):
        bound.add(match.group(1))
    for match in _SET_BUILDER.finditer(code):
        _all_atoms(match.group(1), bound)
    for match in _ARM.finditer(code):
        for piece in match.group(1).split(","):
            atoms = list(_ATOM.finditer(piece))
            if not atoms:
                continue
            # `| succ k ih =>`: `succ` is a constructor being matched, the rest are new names; `| K + 1 =>`: K is new
            first = atoms[0]
            applied = len(atoms) > 1 and piece[first.end() : atoms[1].start()].strip() == ""
            bound.update(a.group(0) for a in (atoms[1:] if applied else atoms) if a.group(0) not in _RUN_END)
    return frozenset(bound)


def variables_in(code: str) -> tuple[str, ...]:
    """Names declared by `variable` commands (in scope for the declarations after them)."""
    bound: set[str] = set()
    for match in re.finditer(r"^variable\b", code, re.M):
        _binder_run(code, match.end(), bound)
    return tuple(sorted(bound))


def imports_in(code: str) -> tuple[str, ...]:
    """The modules a file imports, in order (`import A B`, `public import A`, `import all A`)."""
    found: dict[str, None] = {}
    for match in _IMPORT.finditer(code):
        for module in match.group(1).split():
            if module.startswith("--"):
                break
            found.setdefault(module, None)
    return tuple(found)


def declaration_end(lines: Sequence[str], first: int, stop: int) -> int:
    """Where a declaration starting at `first` ends: at the next top-level command, or at `stop`."""
    for i in range(first + 1, stop):
        if _COMMAND.match(lines[i]):
            return i
    return stop


def names_in(code: str, local: frozenset[str] | set[str] = frozenset()) -> tuple[str, ...]:
    """The distinct identifiers in a stretch of (masked) code, in first-seen order, without its local names."""
    seen: dict[str, None] = {}
    for match in IDENT.finditer(code):
        name = match.group(1)
        if len(name) < 2 or name in STOP or name in local:
            continue
        seen.setdefault(name.removeprefix("_root_."), None)
        if len(seen) >= _MAX_NAMES:
            break
    return tuple(seen)


def opens_in(code: str) -> tuple[str, ...]:
    """Namespaces opened by `open A B` lines (scoped and `open … in` too), in order."""
    found: dict[str, None] = {}
    for match in _OPEN.finditer(code):
        for part in match.group(1).split():
            if part in _OPEN_END or part.startswith(("(", "[", "--")):
                break
            found.setdefault(part, None)
    return tuple(found)


def candidates(name: str, namespace: Sequence[str], opens: Sequence[str]) -> Iterable[str]:
    """Where Lean would look for `name` written inside `namespace`, with `opens` open: innermost first."""
    for depth in range(len(namespace), -1, -1):
        yield ".".join((*namespace[:depth], name))
    for opened in opens:
        yield f"{opened}.{name}"


def visible_files(imports: Mapping[str, Sequence[str]]) -> dict[str, frozenset[str]]:
    """For each file, itself and every project file it imports, directly or not. Modules outside the project are
    skipped. Only the files in `imports` are followed: give it every file, including ones that only import."""
    module_of = {rel.removesuffix(".lean").replace("/", "."): rel for rel in imports}
    return reachable({rel: [module_of[m] for m in modules if m in module_of] for rel, modules in imports.items()})


def reachable(direct: Mapping[str, Sequence[str]]) -> dict[str, frozenset[str]]:
    """For each file, itself and every file reachable from it through `direct` (file -> the files it imports)."""
    seen: dict[str, frozenset[str]] = {}
    for start in direct:
        if start in seen:
            continue
        found = {start}
        stack = [start]
        while stack:
            for target in direct.get(stack.pop(), ()):
                if target in seen:
                    found |= seen[target]
                elif target not in found:
                    found.add(target)
                    stack.append(target)
        seen[start] = frozenset(found)
    return seen


class Resolver:
    """Resolves names to declaration keys of one project (a plain name, or name@file for one with variants)."""

    def __init__(
        self,
        locations: Mapping[str, Sequence[object]],
        visible: Mapping[str, frozenset[str]] | None = None,
        copies: Mapping[str, Sequence[object]] | None = None,
    ) -> None:
        self.plain: dict[str, str] = {}
        self.variants: dict[str, dict[str, str]] = {}
        self.files: dict[str, frozenset[str]] = {}  # the files that hold a declaration (identical copies fold into one key)
        self.visible = visible
        for key in locations:
            held = {str(locations[key][0])}
            if "@" not in key and copies and key in copies:
                held.update(str(getattr(copy, "rel")) for copy in copies[key])
            self.files[key] = frozenset(held)
            name, sep, rel = key.partition("@")
            if sep:
                self.variants.setdefault(name, {})[rel] = key
            else:
                self.plain[name] = key

    def key_of(self, name: str, rel: str) -> str | None:
        if name in self.plain:
            return self.plain[name]
        variants = self.variants.get(name)
        if variants:
            return variants.get(rel) or next(iter(variants.values()))
        return None

    def _seen_from(self, name: str, rel: str) -> str | None:
        """The key `name` means in file `rel`: one that file can see (its own variant first), or None."""
        sees = self.visible.get(rel) if self.visible is not None else None
        if name in self.plain:
            key = self.plain[name]
            return key if sees is None or not self.files[key].isdisjoint(sees) else None
        variants = self.variants.get(name)
        if not variants:
            return None
        if rel in variants:
            return variants[rel]
        return next((key for other, key in variants.items() if sees is None or other in sees), None)

    def uses(self, owner: str, rel: str, names: Iterable[str], opens: Sequence[str]) -> list[str]:
        """The project declarations `owner` (a full name in file `rel`) refers to, without itself."""
        namespace = owner.split(".")[:-1]
        own = {self.key_of(owner, rel), owner}
        found: dict[str, None] = {}
        for name in names:
            for candidate in candidates(name, namespace, opens):
                key = self._seen_from(candidate, rel)
                if key is not None:
                    if key not in own:
                        found.setdefault(key, None)
                    break
        return list(found)


def reverse(uses: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    used_by: dict[str, list[str]] = {}
    for user, targets in uses.items():
        for target in targets:
            used_by.setdefault(target, []).append(user)
    return used_by
