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
from lean4_explainer.scan import iter_lean_files, parse_source
from lean4_explainer_corpora.registry import installed


BEGIN = "# BEGIN GENERATED SOURCE-COMMENT ANNOTATIONS"
END = "# END GENERATED SOURCE-COMMENT ANNOTATIONS"
_MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]+\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_WHITESPACE = re.compile(r"\s+")


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


def _title(name: str, description: str) -> str:
    text = _plain(description).lstrip("#*- ")
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    if first and len(first) <= 180:
        return first.rstrip(".").rstrip()
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
            target = (rel, declaration.name)
            # An overlay selects by file and name, not by source occurrence. If a
            # file repeats a name, it attaches to the first occurrence; never use
            # a later occurrence's comment to describe that earlier declaration.
            if target in seen_source_targets:
                continue
            seen_source_targets.add(target)
            description = declaration.doc or declaration.comment
            if not description:
                continue
            source_described += 1
            if target in existing:
                continue
            kind = "doc comment" if declaration.doc else "leading source comment"
            body = "\n".join(
                [
                    f"@file {rel}",
                    f"@decl {declaration.name}",
                    f"-- L4DEL: title: {_title(declaration.name, description)}",
                    f"-- L4DEL: intuition: {_bounded(description)}",
                    f"-- L4DEL: step: This explanation is a condensed rendering of the declaration's own {kind} at the pinned source commit; consult the exact Lean statement below for authority.",
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
        + "# The Pages disclosure labels this transformed explanatory text AI-generated and unreviewed.\n\n"
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
