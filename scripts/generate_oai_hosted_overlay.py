"""Expand the hosted openai/math overlay from the pinned repository's own notes.

The generator deliberately uses only source-controlled material from an
openai/math checkout:

* ``lean/docs/*.md`` for result titles, scope summaries, and comparator links;
* ``lean/ComparatorChallenges/*.json`` for the exact comparator declarations
  and solution module selected by the repository.
* declaration doc comments named by an exact-commit extraction JSONL.

Every candidate is re-parsed with the same source scanner as the site.  This
filters elaborator-generated declarations that have no source-level page
anchor, and identical copied declarations receive identical annotation text.

Existing hand-curated entries are preserved.  The generated block is replaced
deterministically on later runs.  This script never writes into a corpus
package; its output is a Pages-only hosted overlay.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from lean4_explainer.scan import Declaration, parse_source
from lean4_explainer_corpora.registry import installed


BEGIN = "# BEGIN GENERATED OPENAI/MATH FORMALIZATION-NOTE ANNOTATIONS"
END = "# END GENERATED OPENAI/MATH FORMALIZATION-NOTE ANNOTATIONS"
# Intuition for a comparator declaration whose formalization note covers several results and which has no doc comment.
MULTI_RESULT_FALLBACK = (
    "This declaration is an exact comparator-selected statement. "
    "Read the Lean statement below for its mathematical content."
)
_COMPARATOR_LINK = re.compile(r"\.\./ComparatorChallenges/([^/)]+)\.lean")
_MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]+\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Note:
    title: str
    scope: str
    comparators: tuple[str, ...]
    result_titles: tuple[str, ...]
    source: str


def _plain(text: str) -> str:
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def _bounded_scope(text: str, limit: int = 1800) -> str:
    text = _plain(text)
    if len(text) <= limit:
        return text
    candidate = text[: limit + 1]
    stop = max(candidate.rfind(". "), candidate.rfind("; "))
    if stop >= limit // 2:
        return candidate[: stop + 1].strip()
    return text[: limit - 1].rstrip() + "…"


def _note(path: Path) -> Note | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        return None
    title = _plain(lines[0][2:])
    try:
        scope_start = lines.index("## Scope") + 1
    except ValueError:
        return None
    scope_lines: list[str] = []
    for line in lines[scope_start:]:
        if line.startswith("## "):
            break
        if line.strip():
            scope_lines.append(line.strip())
    comparator_rows: dict[str, str] = {}
    for line in lines:
        for comparator in _COMPARATOR_LINK.findall(line):
            if comparator in comparator_rows:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            label = _plain(cells[0]) if cells else ""
            comparator_rows[comparator] = label or comparator
    comparators = tuple(comparator_rows)
    result_titles = tuple(comparator_rows[comparator] for comparator in comparators)
    scope = _bounded_scope(" ".join(scope_lines))
    if not title or not scope or not comparators:
        return None
    return Note(title, scope, comparators, result_titles, path.name)


def _existing_targets(text: str) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    current = ""
    for line in text.splitlines():
        if line.startswith("@file "):
            current = line[6:].strip().replace("\\", "/")
        elif line.startswith("@decl ") and current:
            targets.add((current, line[6:].strip()))
    return targets


def _base(text: str) -> str:
    if BEGIN not in text:
        return text.rstrip() + "\n"
    before, rest = text.split(BEGIN, 1)
    if END not in rest:
        raise ValueError(f"{BEGIN!r} is present without {END!r}")
    return before.rstrip() + "\n"


def _declarations(path: Path | None) -> list[dict] | None:
    if path is None:
        return None
    declarations: list[dict] = []
    with path.open(encoding="utf-8") as rows:
        for raw in rows:
            if not raw.strip():
                continue
            row = json.loads(raw)
            module = row.get("module")
            name = row.get("name")
            if isinstance(module, str) and isinstance(name, str):
                declarations.append(row)
    return declarations


def _doc_title(name: str, doc: str) -> str:
    text = _plain(doc).lstrip("#*- ")
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    if first and len(first) <= 180:
        return first.rstrip(".").rstrip()
    return f"Documented declaration: {name.rsplit('.', 1)[-1]}"


def _source_declarations(repo: Path, files: set[str]) -> dict[tuple[str, str], Declaration]:
    """Parse only candidate files and retain the first source-level declaration of each name."""
    extra_kinds = installed()["oai"].extra_kinds
    found: dict[tuple[str, str], Declaration] = {}
    for rel in sorted(files):
        path = repo / "lean" / rel
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
        for declaration in parse_source(text, rel, extra_kinds=extra_kinds).declarations:
            found.setdefault((rel, declaration.name), declaration)
    return found


def generate(repo: Path, current: str, declarations_jsonl: Path | None = None) -> tuple[str, int, int]:
    lean = repo / "lean"
    docs = lean / "docs"
    configs = lean / "ComparatorChallenges"
    if not docs.is_dir() or not configs.is_dir():
        raise ValueError(f"{repo} is not an openai/math checkout with lean/docs and ComparatorChallenges")

    base = _base(current)
    curated = _existing_targets(base)
    declarations = _declarations(declarations_jsonl)
    candidate_files = {
        str(row["path"]).removeprefix("lean/").replace("\\", "/")
        for row in declarations or ()
        if isinstance(row.get("doc"), str) and row["doc"].strip() and isinstance(row.get("path"), str)
    }
    note_rows: list[tuple[Note, str, Path, str, str, str]] = []
    for path in sorted(docs.glob("*.md")):
        note = _note(path)
        if note is None:
            continue
        for stem, result_title in zip(note.comparators, note.result_titles, strict=True):
            config_path = configs / f"{stem}.json"
            if not config_path.is_file():
                raise ValueError(f"{note.source}: missing comparator config {config_path.name}")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            module = config.get("challenge_module")
            solution = config.get("solution_module")
            if module != f"ComparatorChallenges.{stem}" or not isinstance(solution, str):
                raise ValueError(f"{config_path}: unexpected challenge or solution module")
            names = config.get("theorem_names", []) + config.get("definition_names", [])
            if not names:
                raise ValueError(f"{config_path}: comparator has no selected declarations")
            file = f"ComparatorChallenges/{stem}.lean"
            candidate_files.add(file)
            for name in names:
                if not isinstance(name, str):
                    raise ValueError(f"{config_path}: declaration names must be strings")
                note_rows.append((note, file, config_path, solution, name, result_title))

    source = _source_declarations(repo, candidate_files)
    # target -> (priority, annotation lines). Formalization notes take priority
    # over doc-comment condensations when both describe the same declaration.
    proposals: dict[tuple[str, str], tuple[int, tuple[str, ...]]] = {}
    notes_used = 0

    used_notes: set[str] = set()
    multi_result_targets: dict[tuple[str, str], tuple[Note, str, str]] = {}
    for note, file, config_path, solution, name, result_title in note_rows:
        target = (file, name)
        if target in curated or target not in source:
            continue
        if len(note.comparators) > 1:
            multi_result_targets[target] = (note, result_title, solution)
            continue
        proposals[target] = (
            0,
            (
                f"-- L4DEL: title: Challenge statement: {note.title}",
                f"-- L4DEL: intuition: {note.scope}",
                "-- L4DEL: step: This is an exact comparator target linked by the pinned repository's formalization note for this result.",
                f"-- L4DEL: step: The repository's comparator configuration selects {solution} as the released solution module checked against this declaration.",
            ),
        )
        used_notes.add(note.source)

    # The repository's own doc comments are the next safest source of explanatory
    # text.  Add every documented declaration that is not already covered by a
    # curated or formalization-note entry.  We retain only a bounded, normalized
    # rendering; the exact declaration and original doc comment remain on-page.
    if declarations is not None:
        for row in declarations:
            doc = row.get("doc")
            path = row.get("path")
            name = row.get("name")
            if not isinstance(doc, str) or not doc.strip() or not isinstance(path, str) or not isinstance(name, str):
                continue
            file = path.removeprefix("lean/").replace("\\", "/")
            target = (file, name)
            if target in curated or target in proposals or target not in source:
                continue
            # The extraction JSONL is an exact-target inventory, not textual
            # authority. Older inventories bounded ``doc`` at 300 characters
            # and can end mid-word. Once the target is located, always render
            # the full doc comment parsed from the pinned Lean source bytes.
            source_doc = source[target].doc
            if not source_doc:
                continue
            multi_result = multi_result_targets.get(target)
            if multi_result is None:
                proposals[target] = (
                    1,
                    (
                        f"-- L4DEL: title: {_doc_title(name, source_doc)}",
                        f"-- L4DEL: intuition: {_bounded_scope(source_doc)}",
                        "-- L4DEL: step: This explanation is a condensed rendering of the declaration's own doc comment at the pinned source commit; consult the exact Lean statement below for authority.",
                    ),
                )
            else:
                note, result_title, solution = multi_result
                proposals[target] = (
                    0,
                    (
                        f"-- L4DEL: title: Challenge statement: {result_title}",
                        f"-- L4DEL: intuition: {_bounded_scope(source_doc)}",
                        "-- L4DEL: step: This explanation is a condensed rendering of this declaration's own doc comment at the pinned source commit.",
                        f"-- L4DEL: step: The linked formalization note covers {len(note.comparators)} distinct comparator results, so its combined Scope prose is not copied onto this declaration.",
                        f"-- L4DEL: step: The repository's comparator configuration selects {solution} as the released solution module checked against this declaration.",
                    ),
                )
                used_notes.add(note.source)

    # A multi-result note is not target-specific prose. If its exact comparator
    # declaration has no source doc comment, retain only the row label and the
    # checked solution binding rather than publishing the combined note scope.
    for target, (note, result_title, solution) in multi_result_targets.items():
        if target in proposals:
            continue
        proposals[target] = (
            2,
            (
                f"-- L4DEL: title: Challenge statement: {result_title}",
                f"-- L4DEL: intuition: {MULTI_RESULT_FALLBACK}",
                f"-- L4DEL: step: The linked formalization note covers {len(note.comparators)} distinct comparator results, so its combined Scope prose is not copied onto this declaration.",
                f"-- L4DEL: step: The repository's comparator configuration selects {solution} as the released solution module checked against this declaration.",
            ),
        )
        used_notes.add(note.source)

    notes_used = len(used_notes)

    # The site collapses same-named, byte-identical declarations across files.
    # Their overlay payloads must therefore also be identical. Pick the
    # highest-priority, then lexicographically first, source-backed wording.
    groups: dict[tuple[str, int], list[tuple[str, str]]] = {}
    for target in proposals:
        groups.setdefault((target[1], source[target].code_digest), []).append(target)
    for targets in groups.values():
        chosen = min(targets, key=lambda target: (proposals[target][0], target[0].casefold()))
        lines = proposals[chosen][1]
        for target in targets:
            proposals[target] = (proposals[target][0], lines)

    blocks: list[tuple[str, str, str]] = []
    for (file, name), (_, lines) in proposals.items():
        body = "\n".join((f"@file {file}", f"@decl {name}", *lines))
        blocks.append((file, name, body))

    blocks.sort(key=lambda item: (item[0].casefold(), item[1].casefold()))
    generated = "\n\n".join(body for _, _, body in blocks)
    output = (
        base.rstrip()
        + "\n\n"
        + BEGIN
        + "\n"
        + "# Generated only from the pinned repository's lean/docs notes, ComparatorChallenges JSON, and declaration doc comments.\n"
        + "# The Pages disclosure labels this transformed text as mechanically source-derived and unreviewed.\n\n"
        + generated
        + "\n"
        + END
        + "\n"
    )
    return output, len(blocks), notes_used


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path, help="pinned openai/math checkout root")
    parser.add_argument("--overlay", required=True, type=Path, help="hosted oai.l4del output")
    parser.add_argument("--declarations-jsonl", type=Path, help="optional extracted declarations used as an exact-target gate")
    parser.add_argument("--check", action="store_true", help="fail if regenerating would change the overlay")
    args = parser.parse_args()

    current = args.overlay.read_text(encoding="utf-8")
    output, entries, notes = generate(args.repo, current, args.declarations_jsonl)
    if args.check:
        if output != current:
            print(f"{args.overlay}: generated overlay is stale")
            return 1
    else:
        args.overlay.write_text(output, encoding="utf-8", newline="\n")
    print(f"{entries} generated declaration annotations; {notes} formalization notes supplied main-result context")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
