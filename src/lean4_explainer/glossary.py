"""The glossary page: every word the site uses, in one place.

The core lists the project's own definitions and the words of the Lean language. Extensions add sections of their
own through `Extension.glossary`; the section keys "project" and "lean" are the core's. The project's entries come
from the incremental cache (one record per definition, made when a file is indexed), so a rebuild that reuses every
file still lists them all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from html import escape

from .extensions import GlossaryEntry, GlossarySection
from .markdown import inline_html
from .render import Context, filter_box, href, page
from .scan import Declaration

PAGE = "glossary.html"
# Definitions are the words of a project. Theorems, lemmas, instances and examples are results, not words.
VOCABULARY_KINDS = frozenset({"def", "abbrev", "structure", "class", "class inductive", "inductive", "opaque"})
SPLIT_AT = 2000  # with more project entries than this, they go on one page per first letter
GROUP_AT = 40  # with more than this on a page, they get letter headings and a row of letters to jump with
_GIST_MAX = 240
_SIGNATURE_MAX = 200
_DECLARATION_END = re.compile(r":=|\bwhere\b")

Record = tuple[str, str, int, str, str]  # (name, kind, line, gist, signature), kept in the cache per file

LEAN_WORDS: tuple[tuple[str, str, str], ...] = (
    # (word, meaning, example). The README's "Words you will meet" are all here; a test checks that.
    ("theorem", "A statement that has been proved. The proof follows :=.", "theorem two_pos : 0 < 2 := by norm_num"),
    ("lemma", "A theorem, usually a smaller helper for a bigger one.", "lemma helper (n : ℕ) : n ≤ n + 1 := by omega"),
    ("def (definition)", "A name for a precise idea or a computation, such as “continuous” or “double a number”.", "def double (n : ℕ) : ℕ := 2 * n"),
    ("abbrev", "A definition that Lean unfolds freely, like a shorthand.", "abbrev Point := ℝ × ℝ"),
    ("structure", "A new kind of object made of named parts (its fields).", "structure Point where\n  x : ℝ\n  y : ℝ"),
    ("class", "A structure that Lean finds by itself when it is needed (a type class), such as “this type has an addition”.", "class Zero (α : Type) where\n  zero : α"),
    ("instance", "A proof or construction that a type belongs to a class. Lean then finds it by itself.", "instance : Zero ℕ := ⟨0⟩"),
    ("inductive", "A new type given by the ways to build its elements. The natural numbers are 0, or one more than a natural number.", "inductive Color\n  | red\n  | green"),
    ("class inductive", "A class given by the ways to build it, like inductive.", "class inductive Decidable (p : Prop)"),
    ("opaque", "A definition whose value Lean keeps hidden: only its type is known.", "opaque secret : ℕ"),
    ("axiom", "Something assumed without proof. Lean's three standard axioms (propext, Classical.choice, Quot.sound) are normal; anything beyond them is worth a closer look.", "axiom my_assumption : 1 = 1"),
    ("example", "A statement proved without a name, to show that something works.", "example : 2 + 2 = 4 := rfl"),
    ("sorry", "Lean's “I have not proved this yet”. A result that uses it is not finished, and the site flags it.", "theorem later : 1 = 1 := sorry"),
    ("proof", "The argument. In Lean, a proof is code, and Lean checks every step of it.", ""),
    ("tactic", "One command inside a proof that starts with by, such as “rewrite using this equation”. The Reading explains each one.", "by\n  rw [h]\n  ring"),
    ("by", "Starts a proof made of tactics.", "theorem t : 1 + 1 = 2 := by norm_num"),
    (":=", "“is defined as” or “is proved by”: what comes after it is the value or the proof.", "def two : ℕ := 2"),
    ("goal", "What is left to prove at a point in a proof. Each tactic changes the goal.", ""),
    ("hypothesis (assumption)", "A named fact you may use in a proof, such as h : 0 < n.", "(h : 0 < n)"),
    ("declaration", "Any named thing in Lean: a theorem, a definition, and so on. Each one has a line on its file page.", ""),
    ("Mathlib", "The big shared library of formalized mathematics that many Lean projects build on.", "import Mathlib"),
    ("kernel", "The small core of Lean that finally accepts or rejects a proof.", ""),
    ("import", "Brings in the declarations of another file or library.", "import Mathlib.Data.Real.Basic"),
    ("namespace", "A family name for declarations: inside namespace Nat, succ_le means Nat.succ_le.", "namespace Nat\n…\nend Nat"),
    ("open", "Lets you use short names: after open Real, pi means Real.pi.", "open Real"),
    ("section", "A part of a file whose variables and open commands end with it.", "section\n…\nend"),
    ("variable", "Names (and assumptions) used by every result below it, until its section ends.", "variable (n : ℕ) (hn : 0 < n)"),
    ("Prop", "The type of statements. A statement is true or false; its proofs are its elements.", "(p : Prop)"),
    ("explicit argument ( )", "An argument you write when you use the result.", "(n : ℕ)"),
    ("implicit argument { }", "An argument Lean works out by itself from the others.", "{α : Type}"),
    ("instance argument [ ]", "An argument Lean finds by itself among the class instances it knows.", "[Field K]"),
    ("anonymous constructor ⟨ ⟩", "Builds an object from its parts: a pair, a structure, or a proof of “and” or “there exists”.", "⟨2, by norm_num⟩"),
    ("h.1, h.2", "The first and second part of h, for example of an “and”.", "h.1"),
    ("dot notation", "x.foo means Foo.foo x, where Foo is the type of x: n.succ is Nat.succ n.", "n.succ"),
    ("· (focusing dot)", "Starts the proof of one goal when there are several.", "constructor\n· norm_num\n· simp"),
    ("_ and ?_", "A hole: Lean fills in _ by itself, and ?_ becomes a new goal to prove.", "refine ⟨?_, ?_⟩"),
    ("@[simp] (attribute)", "Attributes add information to a declaration: @[simp] tells the simp tactic to use it.", "@[simp] theorem add_zero' (n : ℕ) : n + 0 = n := rfl"),
    ("noncomputable", "Marks a definition Lean cannot run as a program, usually because it uses choice or real numbers.", "noncomputable def half : ℝ := 1 / 2"),
    ("private, protected", "private: usable only in this file. protected: must always be written with its full name.", "private theorem helper : True := trivial"),
    ("termination_by", "Says why a recursive definition stops: something gets smaller each time.", "termination_by n"),
    ("#check, #eval", "Commands that ask Lean a question while you write: the type of a term, or its value.", "#eval 2 + 2"),
    ("universe", "The size level of types (Type u). You can usually ignore it.", "universe u"),
    ("Lake", "Lean's build tool. A project's lakefile says which libraries it has and which it needs.", "lake build"),
)


_MARKDOWN_PUNCT = re.compile(r"[\\`*_\[\]$<>#~|!]")


def gist(text: str | None) -> str:
    """The first paragraph of a description, on one line and cut to at most `_GIST_MAX` characters."""
    if not text:
        return ""
    first = re.split(r"\n[ \t]*\n", text.strip(), maxsplit=1)[0]
    first = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+", "", first)  # a heading's text, without its marks
    words = " ".join(first.split())
    if len(words) <= _GIST_MAX:
        return words
    return words[:_GIST_MAX].rsplit(" ", 1)[0] + " …"


def signature(decl: Declaration) -> str:
    """How a definition is declared: from its keyword to its `:=` or `where`, or to its first `|` line."""
    lines: list[str] = []
    for line in decl.statement.split("\n"):
        if lines and line.lstrip().startswith(("|", "…")):
            break
        lines.append(line)
    text = " ".join(" ".join(lines).split())
    start = re.search(rf"(?<![\w.]){re.escape(decl.kind.split()[0])}\b", text)
    text = text[start.start() :] if start else text
    end = _DECLARATION_END.search(text)
    text = (text[: end.start()] if end else text).rstrip()
    if len(text) > _SIGNATURE_MAX:
        text = text[:_SIGNATURE_MAX].rsplit(" ", 1)[0] + " …"
    return text


def record(decl: Declaration, described_by_extension: str) -> Record:
    """The cache record for one definition: its own comment's gist, else an extension's, else its signature. A doc
    comment's gist is Markdown, drawn as such; a plain comment or an extension's line is kept as written."""
    text = gist(decl.doc) or literal(gist(decl.comment)) or literal(gist(described_by_extension))
    return (decl.name, decl.kind, decl.line, text, "" if text else signature(decl))


def literal(text: str) -> str:
    """Text that Markdown shows exactly as it is: its punctuation backslash-escaped."""
    return _MARKDOWN_PUNCT.sub(lambda m: "\\" + m.group(0), text)


def glossary_pages(
    ctx: Context, records: Iterable[tuple[str, Record]], sections: Sequence[GlossarySection], scope: str
) -> dict[str, str]:
    """glossary.html, plus glossary-<letter>.html when the project's list is split. Keys are site-relative paths."""
    project = _project_entries(records) if scope != "none" else []
    split = len(project) > SPLIT_AT
    letters = _by_letter(project)
    shown = [section for section in sections if section.entries]
    lean = GlossarySection(
        key="lean",
        title="Lean words",
        intro="Words of the Lean language itself, and of how its projects are organized.",
        entries=tuple(
            GlossaryEntry(term=word, meaning=escape(meaning), example=example, anchor="lean-" + _slug(word))
            for word, meaning, example in LEAN_WORDS
        ),
    )
    parts = [("project", "Defined in this project", len(project))] * bool(project)
    parts += [(section.key, section.title, len(section.entries)) for section in (*shown, lean)]
    body = [
        "<h1>Glossary</h1>",
        '<p class="muted">Every word this site uses, in one place: what this project defines, the words its '
        "explanations and readings use, and Lean's own words. Type in the box to filter.</p>",
        filter_box("Filter glossary terms"),
        '<nav class="toc">In this glossary: '
        + " · ".join(f'<a href="#g-{escape(key, quote=True)}">{escape(title)}</a> ({count})' for key, title, count in parts)
        + "</nav>",
    ]
    if project:
        body.append('<section data-filter-section>')
        body.append('<h2 id="g-project">Defined in this project</h2>')
        body.append(f'<p class="muted">{escape(_project_intro(scope, split))}</p>')
        if split:
            body.append(_letter_row(letters, lambda letter: f"glossary-{letter}.html", counts=True))
        else:
            body.extend(_project_list(project, letters))
        body.append("</section>")
    for section in (*shown, lean):
        body.append('<section data-filter-section>')
        body.append(f'<h2 id="g-{escape(section.key, quote=True)}">{escape(section.title)}</h2>')
        if section.intro:
            body.append(f'<p class="muted">{escape(section.intro)}</p>')
        entries = sorted(section.entries, key=lambda e: (e.term.casefold(), e.term, e.where or ("", 0, "")))
        body.append('<dl class="glossary" data-filter-rows>' + "".join(_entry_item(entry) for entry in entries) + "</dl>")
        body.append("</section>")
    pages = {PAGE: page("Glossary", 0, body, ctx, canonical_path=PAGE)}
    if split:
        for letter, entries in letters.items():
            label = _label(letter)
            shard = [
                f"<h1>Glossary: {escape(label)}</h1>",
                f'<p class="muted">Definitions in this project whose names start with {escape(label)}. '
                f'<a href="{PAGE}">The whole glossary</a> has the other sections.</p>',
                _letter_row(letters, lambda other: f"glossary-{other}.html", counts=False),
                filter_box("Filter glossary terms"),
                '<dl class="glossary" data-filter-rows>' + "".join(_project_item(entry) for entry in entries) + "</dl>",
            ]
            name = f"glossary-{letter}.html"
            pages[name] = page(f"Glossary: {label}", 0, shard, ctx, canonical_path=name)
    return pages


_Entry = tuple[str, str, str, str, int, str, str]  # (word, name, kind, file, line, gist, signature)


def _project_entries(records: Iterable[tuple[str, Record]]) -> list[_Entry]:
    seen: set[tuple[str, str, str, str]] = set()
    found: list[_Entry] = []
    for rel, (name, kind, line, text, sig) in records:
        key = (name, kind, text, sig)
        if key in seen:  # an identical copy in another file: listed once, at the first copy
            continue
        seen.add(key)
        found.append((name.rsplit(".", 1)[-1], name, kind, rel, line, text, sig))
    found.sort(key=lambda e: (e[0].casefold(), e[0], e[1].casefold(), e[3], e[4]))
    return found


def _letter(word: str) -> str:
    first = word[:1].lower()
    return first if "a" <= first <= "z" else "other"


def _label(letter: str) -> str:
    return "Other" if letter == "other" else letter.upper()


def _by_letter(entries: list[_Entry]) -> dict[str, list[_Entry]]:
    groups: dict[str, list[_Entry]] = {}
    for entry in entries:
        groups.setdefault(_letter(entry[0]), []).append(entry)
    return dict(sorted(groups.items(), key=lambda item: (item[0] == "other", item[0])))


def _letter_row(letters: dict[str, list[_Entry]], target, counts: bool) -> str:
    links = [
        f'<a href="{escape(target(letter), quote=True)}">{_label(letter)}</a>' + (f" ({len(entries)})" if counts else "")
        for letter, entries in letters.items()
    ]
    return '<p class="letters">' + " · ".join(links) + "</p>"


def _project_intro(scope: str, split: bool) -> str:
    which = (
        "Every definition in this project that has a description, under its own name, with the first paragraph of it. "
        "The others are on their file pages."
        if scope == "described"
        else "Every definition in this project, under its own name: the first paragraph of its description, or how it "
        "is declared when it has none."
    )
    tail = " Theorems are not listed here: they are results, not words."
    return which + tail + (" There are too many for one page, so there is one page per first letter." if split else "")


def _project_list(entries: list[_Entry], letters: dict[str, list[_Entry]]) -> list[str]:
    if len(entries) <= GROUP_AT:
        return ['<dl class="glossary" data-filter-rows>' + "".join(_project_item(entry) for entry in entries) + "</dl>"]
    out = [_letter_row(letters, lambda letter: f"#g-project-{letter}", counts=False)]
    for letter, group in letters.items():
        out.append(f'<h3 id="g-project-{letter}">{_label(letter)}</h3>')
        out.append('<dl class="glossary" data-filter-rows>' + "".join(_project_item(entry) for entry in group) + "</dl>")
    return out


def _project_item(entry: _Entry) -> str:
    word, name, kind, rel, line, text, sig = entry
    meaning = inline_html(text) if text else f"<code>{escape(sig)}</code>"
    link = escape(href([], rel, f"#L{line}"), quote=True)
    return (
        f'<div><dt>{escape(word)} <span class="kind">{escape(kind)}</span></dt>'
        f'<dd>{meaning} <span class="muted">· <a class="where" href="{link}">{escape(name)}</a></span></dd></div>'
    )


def _entry_item(entry: GlossaryEntry) -> str:
    anchor = f' id="{escape(entry.anchor, quote=True)}"' if entry.anchor else ""
    example = f"<code>{escape(entry.example)}</code> — " if entry.example else ""
    where = ""
    if entry.where:
        rel, line, label = entry.where
        link = escape(href([], rel, f"#L{line}"), quote=True)
        where = f' <span class="muted">· <a class="where" href="{link}">{escape(label)}</a></span>'
    return f'<div><dt{anchor}>{escape(entry.term)}</dt><dd>{example}{entry.meaning}{where}</dd></div>'


def _slug(word: str) -> str:
    return re.sub(r"[^0-9a-z]+", "-", word.lower()).strip("-") or str(sum(map(ord, word)))
