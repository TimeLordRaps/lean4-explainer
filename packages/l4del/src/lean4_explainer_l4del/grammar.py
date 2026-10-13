"""L4DEL: the directive syntax by which a Lean line comment carries explanation metadata.

Grammar (EBNF; text is Unicode NFC-normalized and LF-normalized before parsing):

    carrier   = "--" , { " " | "\t" } , "L4DEL:" , ( " " | "\t" ) , directive ;
    directive = key , ":" , value ;
    key       = "title" | "intuition" | "step" | "prereq" | "see" | "term" | "acronym" | "source" | "quote" ;

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
- acronym: "SHORT = expansion". SHORT is two or more uppercase letters, digits, or hyphens, starting
  with a letter. Definitions are collected into the explanation legend at the top of each affected page.
- source: "label = https://url". Labels and URLs must be non-empty, URLs must use HTTPS, and the
  same URL may appear only once on a declaration. Source may be repeated to cite independent material.
- quote: "source label = exact excerpt". The label must name a source on the annotation. Hosted
  overlays may use the reserved label "Pinned Lean source", which the renderer binds to the exact
  declaration at the configured commit. Quote may be repeated.
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
from urllib.parse import urlsplit

from lean4_explainer.extensions import Diagnostic

KEYS = ("title", "intuition", "step", "prereq", "see", "term", "acronym", "source", "quote")
PLACEHOLDER = "TODO_"
MAX_VALUE = 2000
_BLANK = " \t"
_DIRECTIVE_RE = re.compile(r"^(?P<key>[A-Za-z]+):(?P<value>.*)$")
_NAME_RE = re.compile(r"^[^\s,:=()\[\]{}]+$")
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9-]+$")


@dataclass(frozen=True)
class L4Notes:
    title: str | None = None
    intuition: str | None = None
    steps: tuple[str, ...] = ()
    prereqs: tuple[str, ...] = ()
    see: tuple[str, ...] = ()
    terms: tuple[tuple[str, str], ...] = ()
    acronyms: tuple[tuple[str, str], ...] = ()
    sources: tuple[tuple[str, str], ...] = ()
    quotes: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    origin: str = "source"

    @property
    def is_empty(self) -> bool:
        return not (
            self.title
            or self.intuition
            or self.steps
            or self.prereqs
            or self.see
            or self.terms
            or self.acronyms
            or self.sources
            or self.quotes
        )


def normalize_directive(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip(_BLANK)


def parse_l4del(directives: Iterable[tuple[int, str]]) -> L4Notes:
    title: str | None = None
    intuition: str | None = None
    steps: list[str] = []
    prereqs: list[str] = []
    see: list[str] = []
    terms: list[tuple[str, str]] = []
    acronyms: list[tuple[str, str]] = []
    sources: list[tuple[str, str]] = []
    quotes: list[tuple[str, str]] = []
    quote_lines: list[int] = []
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
        elif key == "acronym":
            short, separator, expansion = value.partition("=")
            short, expansion = short.strip(_BLANK), expansion.strip(_BLANK)
            if not separator or not short or not expansion:
                fail(line, "acronym needs the form 'SHORT = expansion'")
            elif PLACEHOLDER not in short and not _ACRONYM_RE.fullmatch(short):
                fail(line, "acronym name must start with A-Z and contain only uppercase letters, digits, or hyphens")
            elif short in {existing for existing, _ in acronyms}:
                fail(line, f"acronym '{short}' given twice for one declaration")
            else:
                acronyms.append((short, expansion))
        elif key == "source":
            label, separator, url = value.partition("=")
            label, url = label.strip(_BLANK), url.strip(_BLANK)
            parsed = urlsplit(url)
            if not separator or not label or not url:
                fail(line, "source needs the form 'label = https://url'")
            elif parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                fail(line, "source URL must be an HTTPS URL without credentials")
            elif label in {existing for existing, _ in sources}:
                fail(line, f"source label repeated: {label}")
            elif url in {existing for _, existing in sources}:
                fail(line, f"source URL repeated: {url}")
            else:
                sources.append((label, url))
        elif key == "quote":
            label, separator, excerpt = value.partition("=")
            label, excerpt = label.strip(_BLANK), excerpt.strip(_BLANK)
            if not separator or not label or not excerpt:
                fail(line, "quote needs the form 'source label = exact excerpt'")
            elif (label, excerpt) in quotes:
                fail(line, f"quote from '{label}' repeated")
            else:
                quotes.append((label, excerpt))
                quote_lines.append(line)
        else:
            target = prereqs if key == "prereq" else see
            for name in (part.strip(_BLANK) for part in value.split(",")):
                if not _NAME_RE.match(name):
                    fail(line, f"invalid name in {key}: '{name}'")
                elif name in target:
                    fail(line, f"name '{name}' repeated in {key}")
                else:
                    target.append(name)
    source_labels = {label for label, _ in sources}
    for (label, _), line in zip(quotes, quote_lines, strict=True):
        if label != "Pinned Lean source" and label not in source_labels:
            diagnostics.append(
                Diagnostic("error", line, f"quote source label '{label}' has no matching source directive")
            )
    return L4Notes(
        title=title,
        intuition=intuition,
        steps=tuple(steps),
        prereqs=tuple(prereqs),
        see=tuple(see),
        terms=tuple(terms),
        acronyms=tuple(acronyms),
        sources=tuple(sources),
        quotes=tuple(quotes),
        diagnostics=tuple(diagnostics),
    )
