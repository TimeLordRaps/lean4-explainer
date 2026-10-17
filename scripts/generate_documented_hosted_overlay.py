"""Add source-comment-backed annotations to a Pages-only corpus overlay.

This deliberately does not invent explanations from declaration names or types.
It transforms only a declaration's own doc comment or immediately leading
source comment, at the corpus package's pinned commit.  Existing curated L4DEL
entries are preserved and take precedence.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from lean4_explainer.build import _LAKE_EXCLUDE, _excluded
from lean4_explainer.lake import include_patterns, read_lake
from lean4_explainer.markdown import math_spans
from lean4_explainer.scan import iter_lean_files, parse_source
from lean4_explainer_corpora.registry import installed


BEGIN = "# BEGIN GENERATED SOURCE-COMMENT ANNOTATIONS"
END = "# END GENERATED SOURCE-COMMENT ANNOTATIONS"
_MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]+\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_WHITESPACE = re.compile(r"\s+")
_CONTROL_MARKER = re.compile(r"\b(?:EVOLVE-BLOCK-(?:START|END)|BEGIN GENERATED|END GENERATED)\b", re.IGNORECASE)
_DANGLING = frozenset(
    "a an and any as at be by each every for from given if in is let of on or so suppose that the then to we when where which while with".split()
)
# A full stop that closes one of these does not end the sentence: "a.e. point-wise", "i.e. the", "cf. Lemma 2".
_ABBREVIATION_END = re.compile(r"(?<![A-Za-z])(?:a\.e|i\.e|e\.g|cf|vs|resp|viz|Thm|Lem|Prop|Cor|Def|Eq|Fig)\.\s*$")
_SCAFFOLDING = re.compile(r"^(?:you can )?put (?:your )?definitions and lemmas here[.!]?$", re.IGNORECASE)


def _plain(text: str) -> str:
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def _bounded(text: str, limit: int = 1800) -> str:
    text = _plain(text)
    if len(text) <= limit:
        return text
    candidate = text[: limit + 1]
    stop = max(candidate.rfind(". "), candidate.rfind("; "))
    if stop >= limit // 2:
        return candidate[: stop + 1].strip()
    return text[: limit - 1].rstrip() + "…"


def _explanation(text: str) -> str:
    """Remove workflow markers while retaining any actual mathematical prose beside them."""
    cleaned = _plain(_CONTROL_MARKER.sub(" ", text))
    bare = cleaned.lstrip("#*- ")
    return "" if not bare or _SCAFFOLDING.fullmatch(bare) else cleaned


def _title(name: str, description: str) -> str:
    text = _plain(description).replace("**", "").lstrip("#*- ")
    spans = math_spans(text)
    stops = (
        match.end()
        for match in re.finditer(r"[.!?]\s+", text)
        if not any(start <= match.start() < end for start, end in spans)
        and not _ABBREVIATION_END.search(text[: match.end()])
    )
    stop = next(stops, len(text))
    first = text[:stop].strip()
    if first and len(first) <= 180:
        return first.rstrip(".").rstrip()
    if spans:
        before_math = first[: spans[0][0]].rstrip(" :,;")
        words = before_math.split()
        # A phrase that ends on a function word, or is a short fragment opening with one, is not a title.
        fragment = bool(words) and (
            words[-1].lower() in _DANGLING or (len(words) < 3 and words[0].lower() in _DANGLING)
        )
        if words and not fragment and len(before_math) <= 180:
            return before_math
    return f"Documented declaration: {name.rsplit('.', 1)[-1]}"


def _base(text: str) -> str:
    if BEGIN not in text:
        return text.rstrip() + "\n"
    before, rest = text.split(BEGIN, 1)
    if END not in rest:
        raise ValueError(f"{BEGIN!r} is present without {END!r}")
    return before.rstrip() + "\n"


def _targets(text: str) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    current = ""
    for line in text.splitlines():
        if line.startswith("@file "):
            current = line[6:].strip().replace("\\", "/")
        elif line.startswith("@decl ") and current:
            targets.add((current, line[6:].strip()))
    return targets


def generate(corpus_name: str, checkout: Path, current: str) -> tuple[str, int, int]:
    corpora = installed()
    if corpus_name not in corpora:
        raise ValueError(f"corpus {corpus_name!r} is not installed")
    corpus = corpora[corpus_name]
    lean_root = checkout / corpus.lean_root
    if not lean_root.is_dir():
        raise ValueError(f"Lean root does not exist: {lean_root}")

    project = read_lake(lean_root) if corpus.lake else None
    include = include_patterns(project) if project and project.libs else corpus.include
    patterns = (*corpus.exclude, *_LAKE_EXCLUDE)
    sources = [
        (rel, path)
        for rel, path in iter_lean_files(lean_root)
        if not _excluded(rel, patterns) and (not include or _excluded(rel, include))
    ]

    base = _base(current)
    existing = _targets(base)
    seen_source_targets: set[tuple[str, str]] = set()
    blocks: list[tuple[str, str, str]] = []
    source_described = 0
    for rel, path in sources:
        text = path.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
        lean_file = parse_source(text, rel, extra_kinds=corpus.extra_kinds)
        for declaration in lean_file.declarations:
            # L4DEL deliberately cannot attach annotations to synthesized anonymous
            # names such as ``(instance at line 95)``. Do not count or emit entries
            # that the renderer must ignore.
            if "(" in declaration.name:
                continue
            target = (rel, declaration.name)
            # An overlay selects by file and name, not by source occurrence. If a
            # file repeats a name, it attaches to the first occurrence; never use
            # a later occurrence's comment to describe that earlier declaration.
            if target in seen_source_targets:
                continue
            seen_source_targets.add(target)
            description = _explanation(declaration.doc or declaration.comment or "")
            if not description:
                continue
            source_described += 1
            if target in existing:
                continue
            body = "\n".join(
                [
                    f"@file {rel}",
                    f"@decl {declaration.name}",
                    f"-- L4DEL: title: {_title(declaration.name, description)}",
                    f"-- L4DEL: intuition: {_bounded(description)}",
                ]
            )
            blocks.append((rel, declaration.name, body))
            existing.add(target)

    blocks.sort(key=lambda item: (item[0].casefold(), item[1].casefold()))
    generated = "\n\n".join(body for _, _, body in blocks)
    output = (
        base.rstrip()
        + "\n\n"
        + BEGIN
        + "\n"
        + "# Generated only from declaration doc comments or immediately leading comments at the pinned commit.\n"
        + "# The Pages disclosure labels this transformed text as mechanically source-derived and unreviewed.\n\n"
        + generated
        + "\n"
        + END
        + "\n"
    )
    return output, len(blocks), source_described


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    current = args.overlay.read_text(encoding="utf-8")
    output, entries, described = generate(args.corpus, args.checkout, current)
    if args.check:
        if output != current:
            print(f"{args.overlay}: generated overlay is stale")
            return 1
    else:
        args.overlay.write_text(output, encoding="utf-8", newline="\n")
    print(f"{args.corpus}: {entries} generated annotations from {described} source-described declarations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
