"""L4DEL: the directive syntax by which a Lean line comment carries explanation metadata.

Grammar (EBNF; text is Unicode NFC-normalized and LF-normalized before parsing):

    carrier   = "--" , { " " | "\t" } , "L4DEL:" , ( " " | "\t" ) , directive ;
    directive = key , ":" , value ;
    key       = "title" | "intuition" | "step" | "prereq" | "see" | "term" ;

Rules:
- Only line comments are carriers. "L4DEL:" inside a block, doc, or module comment is an error.
- Keys are case-sensitive. Any other key is an error.
- title and intuition: at most one per declaration. A second one is an error.
- step: any number, kept in source order.
- prereq and see: comma-separated names. A name is a non-empty run of characters with no whitespace
  and none of , : = ( ) [ ] { }. A name may end in @path, where path is the file relative to the lean
  root (Demo.value@Var/B.lean). An empty or invalid name, or a name repeated within one key on one
  declaration, is an error.
- term: "word = definition". word is the text before the first "=", trimmed. definition is the rest,
  trimmed. Both must be non-empty. A word may be defined only once in the whole project.
- A value is trimmed of spaces and tabs, must be non-empty, and is at most 2000 characters.
- A directive attaches to the next declaration header. Between them only blank lines, comments,
  attribute lines, set_option lines, and other directives may appear. Any other code makes the
  directive an orphan, which is an error.
- Anonymous declarations (example, unnamed instance) cannot carry directives; that is an error.
- Identical copies of a name are one object, so a plain name refers to it. A name with distinct
  definitions is ambiguous: a plain reference is an error, and Name@path must be used instead.
- A prereq or see name that matches no declaration is a warning.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

KEYS = ("title", "intuition", "step", "prereq", "see", "term")
PLACEHOLDER = "TODO_"
MAX_VALUE = 2000
_BLANK = " \t"
_DIRECTIVE_RE = re.compile(r"^(?P<key>[A-Za-z]+):(?P<value>.*)$")
_NAME_RE = re.compile(r"^[^\s,:=()\[\]{}]+$")


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: line {self.line}: {self.message}"


@dataclass(frozen=True)
class L4Notes:
    title: str | None = None
    intuition: str | None = None
    steps: tuple[str, ...] = ()
    prereqs: tuple[str, ...] = ()
    see: tuple[str, ...] = ()
    terms: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.title or self.intuition or self.steps or self.prereqs or self.see or self.terms)


def normalize_directive(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip(_BLANK)


def parse_l4del(directives: Iterable[tuple[int, str]]) -> L4Notes:
    title: str | None = None
    intuition: str | None = None
    steps: list[str] = []
    prereqs: list[str] = []
    see: list[str] = []
    terms: list[tuple[str, str]] = []
    diagnostics: list[Diagnostic] = []

    def fail(line: int, message: str) -> None:
        diagnostics.append(Diagnostic("error", line, message))

    for line, raw in directives:
        text = normalize_directive(raw)
        match = _DIRECTIVE_RE.match(text)
        if match is None:
            fail(line, f"malformed directive: {text}")
            continue
        key, value = match["key"], match["value"].strip(_BLANK)
        if key in KEYS and PLACEHOLDER in value:
            diagnostics.append(
                Diagnostic("warning", line, f"placeholder left in {key}; replace the {PLACEHOLDER} text")
            )
        if key not in KEYS:
            fail(line, f"unknown key: {key}")
        elif not value:
            fail(line, f"empty value for {key}")
        elif len(value) > MAX_VALUE:
            fail(line, f"value is longer than {MAX_VALUE} characters")
        elif key == "title":
            if title is None:
                title = value
            else:
                fail(line, "title given twice for one declaration")
        elif key == "intuition":
            if intuition is None:
                intuition = value
            else:
                fail(line, "intuition given twice for one declaration")
        elif key == "step":
            steps.append(value)
        elif key == "term":
            word, separator, definition = value.partition("=")
            word, definition = word.strip(_BLANK), definition.strip(_BLANK)
            if not separator or not word or not definition:
                fail(line, "term needs the form 'word = definition'")
            elif word in {existing for existing, _ in terms}:
                fail(line, f"term '{word}' given twice for one declaration")
            else:
                terms.append((word, definition))
        else:
            target = prereqs if key == "prereq" else see
            for name in (part.strip(_BLANK) for part in value.split(",")):
                if not _NAME_RE.match(name):
                    fail(line, f"invalid name in {key}: '{name}'")
                elif name in target:
                    fail(line, f"name '{name}' repeated in {key}")
                else:
                    target.append(name)
    return L4Notes(
        title=title,
        intuition=intuition,
        steps=tuple(steps),
        prereqs=tuple(prereqs),
        see=tuple(see),
        terms=tuple(terms),
        diagnostics=tuple(diagnostics),
    )
