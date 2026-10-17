#!/usr/bin/env python3
"""Verify manuscript-backed L4DEL quotations against pinned local checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

from lean4_explainer_l4del.grammar import parse_l4del
from lean4_explainer_l4del.overlay import parse_overlay


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "hosted" / "overlays" / "manuscript-sources.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument(
        "--checkout",
        action="append",
        default=[],
        metavar="CORPUS=PATH",
        help="pinned source checkout; repeat once for every corpus named by the ledger",
    )
    parser.add_argument(
        "--external-cache",
        type=Path,
        help="optional directory containing the external PDF cache files named by the ledger",
    )
    return parser.parse_args()


def _checkouts(values: list[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for value in values:
        corpus, separator, raw_path = value.partition("=")
        if not separator or not corpus.strip() or not raw_path.strip():
            raise ValueError(f"--checkout needs CORPUS=PATH, got {value!r}")
        if corpus in found:
            raise ValueError(f"checkout repeated for {corpus}")
        found[corpus] = Path(raw_path).resolve()
    return found


def _normalise_quote(text: str) -> str:
    # Poppler preserves visual line wrapping, including discretionary word
    # hyphens inserted at the right margin. Remove only a hyphen followed by a
    # physical line break between letters; semantic hyphens remain intact.
    dehyphenated = re.sub(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", "", text)
    decomposed = unicodedata.normalize("NFKD", dehyphenated)
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    ascii_quotes = without_marks.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "−": "-"}))
    return re.sub(r"\s+", "", ascii_quotes).casefold()


def _git_head(checkout: Path) -> str:
    process = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


def _page_text(pdf: Path, page: int) -> str:
    process = subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout


def main() -> int:
    args = _arguments()
    if shutil.which("git") is None or shutil.which("pdftotext") is None:
        print("audit requires git and pdftotext", file=sys.stderr)
        return 2
    try:
        checkouts = _checkouts(args.checkout)
        ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 2

    sources = ledger.get("sources") if isinstance(ledger, dict) and ledger.get("schema") == 1 else None
    if not isinstance(sources, list):
        print(f"{args.ledger}: expected schema 1 with a sources list", file=sys.stderr)
        return 2
    external_sources = ledger.get("external_sources", [])
    if not isinstance(external_sources, list):
        print(f"{args.ledger}: external_sources must be a list", file=sys.stderr)
        return 2

    required = {source.get("corpus") for source in sources if isinstance(source, dict)}
    missing = sorted(corpus for corpus in required if corpus not in checkouts)
    if missing:
        print(f"missing --checkout for: {', '.join(missing)}", file=sys.stderr)
        return 2

    overlays = {}
    errors: list[str] = []
    citation_count = 0
    for corpus in sorted(required):
        corpus_sources = [source for source in sources if source.get("corpus") == corpus]
        expected_commits = {source.get("commit") for source in corpus_sources}
        if len(expected_commits) != 1:
            errors.append(f"{corpus}: ledger does not have one commit")
            continue
        checkout = checkouts[corpus]
        try:
            actual_commit = _git_head(checkout)
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"{corpus}: cannot read git HEAD: {exc}")
            continue
        expected_commit = expected_commits.pop()
        if actual_commit != expected_commit:
            errors.append(f"{corpus}: HEAD {actual_commit} != pinned {expected_commit}")
        overlay_path = ROOT / "hosted" / "overlays" / f"{corpus}.l4del"
        overlays[corpus] = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))

    for source in sources:
        corpus = source["corpus"]
        pdf = checkouts[corpus] / Path(source["path"])
        where = f"{corpus}:{source['path']}"
        if not pdf.is_file():
            errors.append(f"{where}: PDF missing")
            continue
        actual_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if actual_hash != source["sha256"]:
            errors.append(f"{where}: sha256 {actual_hash} != {source['sha256']}")
            continue
        for citation in source["citations"]:
            citation_count += 1
            page = citation["page"]
            quote = citation["quote"]
            try:
                extracted = _page_text(pdf, page)
            except (OSError, subprocess.CalledProcessError) as exc:
                errors.append(f"{where}: cannot extract page {page}: {exc}")
                continue
            if _normalise_quote(quote) not in _normalise_quote(extracted):
                errors.append(f"{where}: page {page} does not contain quote {quote!r}")

            relative_path = citation["file"]
            declaration = citation["declaration"]
            try:
                notes = parse_l4del(overlays[corpus].files[relative_path][declaration])
            except KeyError:
                errors.append(f"{where}: overlay target missing: {relative_path}:{declaration}")
                continue
            source_label = citation.get("source_label", source["source_label"])
            source_pair = (source_label, source["url"])
            quote_pair = (source_label, quote)
            if source_pair not in notes.sources:
                errors.append(f"{where}: overlay target does not bind source {source_pair!r}")
            if quote_pair not in notes.quotes:
                errors.append(f"{where}: overlay target does not bind quote {quote_pair!r}")

    external_citation_count = 0
    external_verified = 0
    external_cache = args.external_cache.resolve() if args.external_cache else None
    for source in external_sources:
        if not isinstance(source, dict):
            errors.append("external source entry is not an object")
            continue
        corpus = source.get("corpus")
        cache_file = source.get("cache_file")
        url = source.get("url")
        pdf_url = source.get("pdf_url")
        expected_hash = source.get("sha256")
        where = f"external:{cache_file}"
        if not isinstance(corpus, str) or not corpus:
            errors.append(f"{where}: corpus missing")
            continue
        if not isinstance(cache_file, str) or Path(cache_file).name != cache_file or not cache_file.endswith(".pdf"):
            errors.append(f"{where}: cache_file must be one PDF basename")
            continue
        if not isinstance(url, str) or not url.startswith("https://"):
            errors.append(f"{where}: URL must use https")
        if not isinstance(pdf_url, str) or not pdf_url.startswith("https://"):
            errors.append(f"{where}: PDF URL must use https")
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            errors.append(f"{where}: sha256 must be 64 lowercase hexadecimal characters")
            continue
        if corpus not in overlays:
            overlay_path = ROOT / "hosted" / "overlays" / f"{corpus}.l4del"
            try:
                overlays[corpus] = parse_overlay(
                    overlay_path.read_text(encoding="utf-8"), str(overlay_path)
                )
            except OSError as exc:
                errors.append(f"{where}: cannot load overlay: {exc}")
                continue

        pdf = external_cache / cache_file if external_cache else None
        if pdf is not None:
            if not pdf.is_file():
                errors.append(f"{where}: cached PDF missing")
                continue
            actual_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                errors.append(f"{where}: sha256 {actual_hash} != {expected_hash}")
                continue
            external_verified += 1

        citations = source.get("citations")
        if not isinstance(citations, list):
            errors.append(f"{where}: citations must be a list")
            continue
        for citation in citations:
            external_citation_count += 1
            page = citation.get("page")
            quote = citation.get("quote")
            source_label = citation.get("source_label")
            if not isinstance(page, int) or page < 1 or not isinstance(quote, str) or not quote:
                errors.append(f"{where}: citation needs a positive page and nonempty quote")
                continue
            if not isinstance(source_label, str) or not source_label:
                errors.append(f"{where}: citation source_label missing")
                continue
            if pdf is not None:
                try:
                    extracted = _page_text(pdf, page)
                except (OSError, subprocess.CalledProcessError) as exc:
                    errors.append(f"{where}: cannot extract page {page}: {exc}")
                    continue
                if _normalise_quote(quote) not in _normalise_quote(extracted):
                    errors.append(f"{where}: page {page} does not contain quote {quote!r}")

            relative_path = citation.get("file")
            declaration = citation.get("declaration")
            try:
                notes = parse_l4del(overlays[corpus].files[relative_path][declaration])
            except KeyError:
                errors.append(f"{where}: overlay target missing: {relative_path}:{declaration}")
                continue
            source_pair = (source_label, url)
            quote_pair = (source_label, quote)
            if source_pair not in notes.sources:
                errors.append(f"{where}: overlay target does not bind source {source_pair!r}")
            if quote_pair not in notes.quotes:
                errors.append(f"{where}: overlay target does not bind quote {quote_pair!r}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    external_status = (
        f"verified {external_verified} external PDFs"
        if external_cache is not None
        else f"recorded {len(external_sources)} external PDF hashes"
    )
    print(
        f"verified {len(sources)} pinned manuscript PDFs and {citation_count} page-bound quotations; "
        f"{external_status} with {external_citation_count} bound quotations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
