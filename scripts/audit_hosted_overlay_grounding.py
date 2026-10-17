"""Verify hosted explanations against the exact pinned source checkouts.

Generated annotations must reproduce source-controlled doc comments, leading
comments, or openai/math formalization notes. Curated annotations are checked
for an exact declaration target and durable reference links, but deliberately
remain unreviewed: this tool is not a mathematical peer reviewer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

from lean4_explainer.scan import Declaration, parse_source
from lean4_explainer_l4del.grammar import normalize_directive, parse_l4del
from lean4_explainer_l4del.overlay import parse_overlay

try:  # direct script execution puts scripts/ on sys.path; test imports put the repository root there
    from generate_documented_hosted_overlay import _bounded, _explanation, _title
    from generate_oai_hosted_overlay import MULTI_RESULT_FALLBACK, _bounded_scope, _note
except ModuleNotFoundError:  # pragma: no cover - the other branch is covered by the Pages command
    from scripts.generate_documented_hosted_overlay import _bounded, _explanation, _title
    from scripts.generate_oai_hosted_overlay import MULTI_RESULT_FALLBACK, _bounded_scope, _note


def _head(path: Path) -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def _source_path(checkout: Path, rel: str) -> Path:
    direct = checkout / rel
    if direct.is_file():
        return direct
    nested = checkout / "lean" / rel
    return nested


def _stable_reference(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    parts = parsed.path.strip("/").split("/")
    if host == "github.com" and len(parts) >= 5 and parts[2] in {"blob", "tree"}:
        return bool(re.fullmatch(r"[0-9a-f]{40}", parts[3]))
    if host == "arxiv.org":
        return bool(re.fullmatch(r"/abs/\d{4}\.\d{4,5}v\d+", parsed.path))
    if host == "doi.org":
        return bool(parsed.path.strip("/"))
    if host == "web.archive.org":
        return bool(re.match(r"^/web/\d{14}/", parsed.path))
    return False


def _oai_note_targets(checkout: Path) -> dict[tuple[str, str], set[str]]:
    found: dict[tuple[str, str], set[str]] = {}
    docs = checkout / "lean" / "docs"
    configs = checkout / "lean" / "ComparatorChallenges"
    if not docs.is_dir() or not configs.is_dir():
        return found
    for path in sorted(docs.glob("*.md")):
        note = _note(path)
        if note is None:
            continue
        for stem in note.comparators:
            config_path = configs / f"{stem}.json"
            if not config_path.is_file():
                continue
            config = json.loads(config_path.read_text(encoding="utf-8"))
            for name in config.get("theorem_names", []) + config.get("definition_names", []):
                if isinstance(name, str):
                    found.setdefault((f"ComparatorChallenges/{stem}.lean", name), set()).add(note.scope)
    return found


def _oai_multi_result_targets(checkout: Path) -> set[tuple[str, str]]:
    """Targets of formalization notes that cover several comparator results (their prose is not target-specific)."""
    found: set[tuple[str, str]] = set()
    docs = checkout / "lean" / "docs"
    configs = checkout / "lean" / "ComparatorChallenges"
    if not docs.is_dir() or not configs.is_dir():
        return found
    for path in sorted(docs.glob("*.md")):
        note = _note(path)
        if note is None or len(note.comparators) < 2:
            continue
        for stem in note.comparators:
            config_path = configs / f"{stem}.json"
            if not config_path.is_file():
                continue
            config = json.loads(config_path.read_text(encoding="utf-8"))
            for name in config.get("theorem_names", []) + config.get("definition_names", []):
                if isinstance(name, str):
                    found.add((f"ComparatorChallenges/{stem}.lean", name))
    return found


def _generated_line(text: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("# BEGIN GENERATED"):
            return number
    return len(text.splitlines()) + 1


def audit(manifest_path: Path, work_dir: Path) -> tuple[dict, list[str]]:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = document.get("overlays", {})
    errors: list[str] = []
    report: dict = {
        "schema": 1,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "status": "PASS",
        "corpora": {},
        "curated_entries": [],
        "limitations": (
            "Generated wording is checked against pinned source-controlled text. Curated wording is source-linked "
            "and target-checked but remains AI-generated-unreviewed until an identified human reviewer signs it off."
        ),
    }
    for corpus_name, entry in sorted(entries.items()):
        where = f"{corpus_name}"
        checkout = work_dir / corpus_name
        expected_commit = entry.get("commit", "")
        actual_commit = _head(checkout) if checkout.is_dir() else ""
        if actual_commit != expected_commit:
            errors.append(f"{where}: checkout HEAD {actual_commit or 'missing'} != {expected_commit}")
            continue
        overlay_path = manifest_path.parent / entry.get("file", "")
        text = overlay_path.read_text(encoding="utf-8")
        if hashlib.sha256(overlay_path.read_bytes()).hexdigest() != entry.get("sha256"):
            errors.append(f"{where}: overlay SHA-256 does not match manifest")
            continue
        shared = entry.get("sources", [])
        if not isinstance(shared, list) or len(shared) < 2:
            errors.append(f"{where}: fewer than two corpus-level reference links")
        for source in shared if isinstance(shared, list) else ():
            url = source.get("url") if isinstance(source, dict) else None
            parsed = urlsplit(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme != "https" or not parsed.netloc:
                errors.append(f"{where}: invalid corpus reference URL {url!r}")
            elif not _stable_reference(url):
                errors.append(f"{where}: corpus reference URL is not immutable {url!r}")

        overlay = parse_overlay(text, str(overlay_path))
        marker = _generated_line(text)
        declarations: dict[tuple[str, str], Declaration] = {}
        source_git_paths: dict[str, str] = {}
        by_digest: dict[tuple[str, int], set[str]] = {}
        for rel, targets in overlay.files.items():
            path = _source_path(checkout, rel)
            if not path.is_file():
                errors.append(f"{where}:{rel}: source file is missing")
                continue
            source_git_paths[rel] = path.relative_to(checkout).as_posix()
            extra = ("problem", "determine") if corpus_name == "compfiles" else ()
            source = path.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
            for declaration in parse_source(source, rel, extra_kinds=extra, statements=True).declarations:
                declarations.setdefault((rel, declaration.name), declaration)
                description = declaration.doc or declaration.comment
                if description:
                    value = _bounded_scope(description) if corpus_name == "oai" else _bounded(_explanation(description))
                    value = normalize_directive(value)
                    by_digest.setdefault((declaration.name, declaration.code_digest), set()).add(value)

        note_targets = _oai_note_targets(checkout) if corpus_name == "oai" else {}
        for target, scopes in note_targets.items():
            declaration = declarations.get(target)
            if declaration is not None:
                by_digest.setdefault((declaration.name, declaration.code_digest), set()).update(scopes)

        multi_result_targets = _oai_multi_result_targets(checkout) if corpus_name == "oai" else set()
        total = curated = generated = matched = 0
        for rel, targets in overlay.files.items():
            for name, directives in targets.items():
                total += 1
                declaration = declarations.get((rel, name))
                if declaration is None:
                    errors.append(f"{where}:{rel}:{name}: declaration target is missing")
                    continue
                notes = parse_l4del(directives)
                for diagnostic in notes.diagnostics:
                    if diagnostic.severity == "error":
                        errors.append(f"{where}:{rel}:{name}:{diagnostic.line}: {diagnostic.message}")
                if not notes.title or not notes.intuition:
                    errors.append(f"{where}:{rel}:{name}: annotation needs both title and intuition")
                first_line = min((line for line, _ in directives), default=0)
                if first_line < marker:
                    curated += 1
                    source_path = quote(source_git_paths[rel], safe="/")
                    report["curated_entries"].append(
                        {
                            "corpus": corpus_name,
                            "file": rel,
                            "declaration": name,
                            "line": declaration.line,
                            "title": notes.title,
                            "intuition": notes.intuition,
                            "source_statement": declaration.statement,
                            "source_statement_sha256": hashlib.sha256(
                                declaration.statement.encode("utf-8")
                            ).hexdigest(),
                            "review_state": "source-linked-unreviewed",
                            "exact_source_url": (
                                f"https://github.com/{entry.get('repo')}/blob/{expected_commit}/"
                                f"{source_path}#L{declaration.line}"
                            ),
                            "corpus_references": shared,
                        }
                    )
                    continue
                generated += 1
                candidates = by_digest.get((name, declaration.code_digest), set())
                if (
                    notes.intuition == normalize_directive(MULTI_RESULT_FALLBACK)
                    and (rel, name) in multi_result_targets
                    and not (declaration.doc or declaration.comment)
                ):
                    candidates = {notes.intuition}
                if notes.intuition not in candidates:
                    errors.append(f"{where}:{rel}:{name}: generated intuition no longer matches its pinned source text")
                    continue
                if corpus_name != "oai":
                    description = _explanation(declaration.doc or declaration.comment or "")
                    if notes.title != normalize_directive(_title(name, description)):
                        errors.append(f"{where}:{rel}:{name}: generated title no longer matches its pinned source text")
                        continue
                matched += 1
        report["corpora"][corpus_name] = {
            "repo": entry.get("repo"),
            "commit": expected_commit,
            "overlay_sha256": entry.get("sha256"),
            "annotations": total,
            "generated_source_matched": matched,
            "generated": generated,
            "curated_source_linked_unreviewed": curated,
            "shared_reference_links": len(shared) if isinstance(shared, list) else 0,
        }
    if errors:
        report["status"] = "FAIL"
        report["errors"] = errors
    report["totals"] = {
        "annotations": sum(row["annotations"] for row in report["corpora"].values()),
        "generated_source_matched": sum(row["generated_source_matched"] for row in report["corpora"].values()),
        "curated_source_linked_unreviewed": sum(
            row["curated_source_linked_unreviewed"] for row in report["corpora"].values()
        ),
    }
    return report, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report, errors = audit(args.manifest, args.work)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for error in errors[:50]:
        print(f"error: {error}")
    if len(errors) > 50:
        print(f"error: {len(errors) - 50} more")
    totals = report["totals"]
    print(
        f"hosted overlay grounding {report['status']}: {totals['annotations']} annotations; "
        f"{totals['generated_source_matched']} generated source matches; "
        f"{totals['curated_source_linked_unreviewed']} curated source-linked and still unreviewed"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
