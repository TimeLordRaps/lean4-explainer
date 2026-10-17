"""The Lean-run extension: elaborate each file with Lean and show what the kernel and the tactic framework report.

It adds to every declaration an axiom-based trust badge and a collapsible tactic trace (the goals before and after each
tactic step), plus a Trust page that lists declarations depending on `sorry` or non-standard axioms. Without Lean on the
PATH, or where a file does not elaborate, the badge says trust is unknown; nothing is guessed.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path
from typing import Any

from lean4_explainer.extensions import Extension, ParseResult, SourceView
from lean4_explainer.render import href, page, source_href

from . import facts as F
from . import runner

__version__ = "0.2.5"
TRACE_SCRIPT = "_assets/lean-traces.js"
TRACE_JS = Path(__file__).with_name("trace.js").read_text(encoding="utf-8")
_DEFAULT_TIMEOUT = 300
_DEFAULT_STEPS = 200
_MAX_JOBS = 4
_TRUST_ROWS = 2000

CSS = """
.trust { display: inline-block; margin: 0.2rem 0; padding: 0.05rem 0.5rem; font-size: 0.8rem; border-radius: 4px; border: 1px solid var(--line); }
.trust-none, .trust-standard { color: var(--fg); }
.trust-sorry, .trust-extra { color: var(--warn); background: var(--warn-bg); border-color: var(--warn); }
.trust-unknown { color: var(--muted); border-style: dashed; }
details.trace { margin: 0.3rem 0; }
details.trace summary { cursor: pointer; font-size: 0.85rem; color: var(--muted); }
details.trace ol { padding-left: 1.2rem; }
details.trace pre { margin: 0.2rem 0; }
.trace-loading, .trace-error { margin: 0.35rem 0; }
.trace-error { color: var(--warn); }
.goal-label { font-size: 0.75rem; color: var(--muted); }
.trust-more, .rd-goals, .rd-words { font-size: 0.75rem; margin-left: 0.4rem; }
dl.badges dt { font-weight: 600; margin-top: 0.4rem; }
dl.badges dd { margin-left: 1rem; }
"""


@dataclass(frozen=True)
class Analysis:
    files: Mapping[str, F.FileFacts]
    toolchain: str  # lean --version, or "" when Lean is unavailable
    max_steps: int
    ran: int = field(default=0, repr=False, compare=False)  # files elaborated this run
    reused: int = field(default=0, repr=False, compare=False)  # files answered from the cache
    unreported_declarations: int = 0  # declarations in failed, unavailable, or deliberately unselected files
    toolchain_issue: str = ""  # why the exact project environment could not run, if applicable
    environment_digest: str = ""  # public, path-free digest of the Lake configuration and dependency pins
    selection_label: str = ""
    eligible_files: int = 0
    selected_files: int = 0
    requested_declarations: int = 0
    missing_targets: tuple[str, ...] = ()
    timeout_seconds: int = 0
    max_working_set_mb: int = 0
    min_free_virtual_mb: int = 0
    cached_only: bool = False
    cache_misses: int = 0


class LeanExtension(Extension):
    name = "lean"
    version = __version__
    runs_lean = True
    config_keys = {
        "lean_timeout": int,
        "lean_jobs": int,
        "lean_steps": int,
        "lean_project": str,
        "lean_cache": str,
        "lean_unknown_badges": bool,
        "lean_file_limit": int,
        "lean_targets": list,
        "lean_selection_label": str,
        "lean_max_working_set_mb": int,
        "lean_min_free_virtual_mb": int,
        "lean_cached_only": bool,
    }

    # -- indexing: remember (name, line) of each named declaration, so the Lean run can ask about them --
    def parse(self, view: SourceView) -> ParseResult | None:
        return ParseResult({head.index: 1 for head in view.heads})  # a marker, so the render hooks run for every declaration

    def index_file(self, path, declarations, diagnostics):
        return tuple((d.name, d.line) for d in declarations if "(" not in d.name)

    def fingerprint(self, options: Mapping[str, Any]) -> str:
        return f"{self.name}:{self.version}:{runner.probe_digest()}:{options.get('lean_steps', _DEFAULT_STEPS)}"

    # -- the Lean run --
    def analyze(self, objects: Any, summaries: Mapping[str, Any], options: Mapping[str, Any]) -> Analysis:
        root = Path(str(options["_root"]))
        max_steps = int(options.get("lean_steps", _DEFAULT_STEPS))
        timeout = int(options.get("lean_timeout", _DEFAULT_TIMEOUT))
        max_working_set_mb = max(0, int(options.get("lean_max_working_set_mb", 0)))
        min_free_virtual_mb = max(0, int(options.get("lean_min_free_virtual_mb", 0)))
        cached_only = bool(options.get("lean_cached_only", False))
        try:
            tc = runner.find_toolchain(root, str(options.get("lean_project", "")))
            toolchain_issue = ""
        except runner.ToolchainError as exc:
            tc = None
            toolchain_issue = str(exc)
        if tc is None:
            reason = toolchain_issue or "Lean (the `lean` command) was not found on the PATH, so no file was elaborated"
            unknown = sum(len(rows or ()) for rows in summaries.values())
            return Analysis({rel: F.FileFacts("unavailable", reason) for rel in summaries}, "", max_steps,
                            unreported_declarations=unknown, toolchain_issue=toolchain_issue,
                            timeout_seconds=timeout, max_working_set_mb=max_working_set_mb,
                            min_free_virtual_mb=min_free_virtual_mb, cached_only=cached_only)
        cache = runner.cache_dir(str(options.get("lean_cache", "")))
        jobs = max(1, min(int(options.get("lean_jobs", min(_MAX_JOBS, os.cpu_count() or 1))), 16))
        counts = {"ran": 0, "reused": 0, "missed": 0}
        lock = threading.Lock()
        pins = _manifest(tc.cwd)
        environment_digest = hashlib.sha256(pins).hexdigest()[:16] if pins else ""
        targets: dict[str, set[str]] = {}
        for encoded in options.get("lean_targets", ()):
            rel, separator, name = str(encoded).partition("\t")
            if separator and rel and name:
                targets.setdefault(rel.replace("\\", "/"), set()).add(name)
        selection_label = str(options.get("lean_selection_label", "")) if targets else ""
        missing_targets = tuple(
            f"{rel}: {name}"
            for rel, names in sorted(targets.items())
            for name in sorted(names)
            if name not in {found_name for found_name, _ in summaries.get(rel, ())}
        )

        def one(rel: str) -> tuple[str, F.FileFacts]:
            declarations = list(summaries[rel] or ())
            requested = [row for row in declarations if not targets or row[0] in targets.get(rel, ())]
            path = root / rel
            names = [name for name, _ in requested]
            identity = [path.read_bytes(), tc.version.encode(), tc.probe_digest.encode(), "\n".join(names).encode(), pins]
            # Only successful elaborations are reusable. A failed probe can be caused by a dependency that has not
            # been built yet, transient resource pressure, or a timeout; none of those failures is content-stable.
            # The legacy key keeps successful records made before timeout was keyed.
            legacy_key = hashlib.sha256(b"\0".join(identity)).hexdigest()
            key = hashlib.sha256(b"\0".join([*identity, f"timeout={timeout}".encode()])).hexdigest()
            cached = cache / f"{key}.json"
            legacy = cache / f"{legacy_key}.json"
            for candidate in (cached, legacy):
                if not candidate.is_file():
                    continue
                try:
                    result = F.from_json(candidate.read_text(encoding="utf-8"))
                except (ValueError, KeyError, OSError):
                    continue
                if not _reusable(result):
                    continue
                if candidate != cached:
                    _write_cached(cached, result)
                with lock:
                    counts["reused"] += 1
                return rel, result
            if cached_only:
                with lock:
                    counts["missed"] += 1
                return rel, F.FileFacts(
                    "unavailable",
                    "no clean content-bound result in the selected Lean evidence cache; not rerun during cache-only rendering",
                )
            code, out, err = runner.run_probe(
                tc, path, names, timeout, max_working_set_mb, min_free_virtual_mb
            )
            with lock:
                counts["ran"] += 1
            if code != 0:
                text = (err or out).strip()
                result = F.FileFacts("failed", text.splitlines()[-1][:300] if text else f"lean exited with {code}")
            else:
                result = F.parse_probe(out, declarations)
                if targets:
                    requested_names = set(names)
                    result = replace(result, decls=tuple(decl for decl in result.decls if decl.name in requested_names))
            if _reusable(result):
                _write_cached(cached, result)
            return rel, result

        declaration_files = [rel for rel in sorted(summaries) if summaries[rel]]
        eligible_files = [rel for rel in sorted(targets) if rel in summaries] if targets else declaration_files
        limit = max(0, int(options.get("lean_file_limit", 0)))
        selected = eligible_files[:limit] if limit else eligible_files
        selected_set = set(selected)
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = dict(pool.map(one, selected))
        bounded_reason = f"outside this bounded local Lean pass (first {limit} eligible files selected)" if limit else ""
        selection_reason = f"outside the {selection_label}" if selection_label else ""
        files = {
            rel: (
                results[rel]
                if rel in selected_set
                else F.FileFacts("unavailable", bounded_reason if rel in eligible_files and bounded_reason else selection_reason)
                if summaries[rel]
                else F.FileFacts("ok")
            )
            for rel in sorted(summaries)
        }
        unreported = sum(
            len(summaries[rel] or ()) if facts.status != "ok" else len(summaries[rel] or ()) - len(facts.decls)
            for rel, facts in files.items()
        )
        return Analysis(
            files, tc.version, max_steps, counts["ran"], counts["reused"], unreported,
            environment_digest=environment_digest, selection_label=selection_label,
            eligible_files=len(eligible_files), selected_files=len(selected),
            requested_declarations=(
                sum(len(names) for names in targets.values())
                if targets
                else sum(len(summaries[rel]) for rel in eligible_files)
            ),
            missing_targets=missing_targets,
            timeout_seconds=timeout,
            max_working_set_mb=max_working_set_mb,
            min_free_virtual_mb=min_free_virtual_mb,
            cached_only=cached_only,
            cache_misses=counts["missed"],
        )

    def analysis_issues(self, analysis: Analysis) -> Sequence[str]:
        issues = [f"warning: lean could not elaborate {rel}: {f.reason}" for rel, f in analysis.files.items() if f.status == "failed"]
        issues.extend(f"warning: lean catalogue target was not found by the source scanner: {target}" for target in analysis.missing_targets)
        return issues

    # -- rendering --
    def css(self, options: Mapping[str, Any]) -> str:
        return CSS

    def declaration_blocks(self, decl, payload, rel, dirs, ctx, analysis: Analysis) -> tuple[str, str]:
        show_unknown = bool(dict(ctx.options).get("lean_unknown_badges", True))
        file_facts = analysis.files.get(rel)
        if file_facts is None:
            return "", ""
        if file_facts.status != "ok":
            return (_badge("unknown", f"trust unknown: {file_facts.reason}", dirs), "") if show_unknown else ("", "")
        found = file_facts.find(decl.name, decl.line)
        if found is None:
            reason = (
                "trust unknown: not selected in this verification scope"
                if analysis.selection_label
                else "trust unknown: not checked (anonymous declaration)"
            )
            return (_badge("unknown", reason, dirs), "") if show_unknown else ("", "")
        kind, label = F.classify(found.axioms)
        if file_facts.errors:
            label += f" (Lean reported {len(file_facts.errors)} error(s) in this file)"
            if kind in ("none", "standard"):
                kind = "unknown"
        if kind == "unknown" and not show_unknown:
            return "", ""
        return _badge(kind, label, dirs) + _uses(found, ctx, dirs), _trace(found, analysis.max_steps, rel, dirs)

    def kernel_trust(self, analysis: Analysis, name: str, rel: str, line: int) -> tuple[str, str] | None:
        """What the kernel says about one declaration: (kind, label) as `facts.classify` gives them, or None."""
        file_facts = analysis.files.get(rel)
        if file_facts is None:
            return None
        if file_facts.status != "ok":
            return "unknown", f"trust unknown: {file_facts.reason}"
        found = file_facts.find(name, line)
        if found is None:
            return "unknown", "trust unknown: not checked"
        kind, label = F.classify(found.axioms)
        if file_facts.errors:
            kind, label = "unknown" if kind in ("none", "standard") else kind, label + f" (Lean reported {len(file_facts.errors)} error(s) in this file)"
        return kind, label

    def nav_links(self, up: str, options: Mapping[str, Any]) -> Sequence[tuple[str, str]]:
        return [("Trust", f"{up}trust.html")]

    def scripts(self, options: Mapping[str, Any]) -> Sequence[str]:
        return (TRACE_SCRIPT,)

    def pages(self, ctx, analysis: Analysis) -> Mapping[str, str | bytes]:
        found: dict[str, str | bytes] = {
            "trust.html": _trust_page(ctx, analysis),
            "trust.json": json.dumps(_trust_record(analysis), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            TRACE_SCRIPT: TRACE_JS,
        }
        if analysis.max_steps > 0:
            for rel, file_facts in analysis.files.items():
                if file_facts.status != "ok" or not any(decl.steps for decl in file_facts.decls):
                    continue
                payload = _trace_payload(rel, file_facts, analysis.max_steps, ctx)
                found[_trace_asset(rel)] = gzip.compress(payload, compresslevel=9, mtime=0)
        return found

    def status(self, analysis: Analysis) -> str:
        if not analysis.toolchain:
            return (
                f"{analysis.toolchain_issue} Trust is UNKNOWN."
                if analysis.toolchain_issue
                else "Lean was not found: trust badges are UNKNOWN."
            )
        suffix = " (cache-only rendering)." if analysis.cached_only else "."
        return f"Lean run with {analysis.toolchain}{suffix}"

    def summary(self, analysis: Analysis) -> Sequence[str]:
        if not analysis.toolchain:
            return (
                (f"lean: {analysis.toolchain_issue}; no trust information.",)
                if analysis.toolchain_issue
                else ("lean: Lean not found; no trust information.",)
            )
        text = ", ".join(f"{n} {k}" for k, n in _tally(analysis).items() if n)
        mode = f", {analysis.cache_misses} cache misses left UNKNOWN" if analysis.cached_only else ""
        return (f"lean ({analysis.toolchain}): {text}; {analysis.ran} files elaborated, {analysis.reused} from cache{mode}.",)


def _write_cached(path: Path, result: F.FileFacts) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(F.to_json(result), encoding="utf-8")
    except OSError:
        pass  # an unwritable cache only costs time


def _reusable(result: F.FileFacts) -> bool:
    """A cache hit must prove the file and every requested constant elaborated cleanly."""
    return result.status == "ok" and not result.errors and all(decl.axioms is not None for decl in result.decls)


def _manifest(project: Path | None) -> bytes:
    """Path-free environment identity: project configuration, dependency pins and Lean toolchain."""
    if project is None:
        return b""
    blob = b""
    for name in ("lakefile.toml", "lakefile.lean", "lake-manifest.json", "lean-toolchain"):
        path = project / name
        if path.is_file():
            blob += name.encode() + b"\0" + path.read_bytes() + b"\0"
    return blob


BADGES = (
    ("no axioms", "Lean's kernel checked the proof, and it rests on nothing but Lean's rules."),
    ("standard axioms", "Checked by the kernel, using only propext, Classical.choice or Quot.sound: the three axioms nearly all of mathematics in Lean uses."),
    ("extra axioms", "Checked by the kernel, but it assumes something the project declared with `axiom`. It is only as true as those assumptions."),
    ("depends on sorry", "Not proved: somewhere in it, or in something it uses, a proof was left out (`sorry`)."),
    ("trust unknown", "Lean did not check it: Lean was not run, the file did not elaborate, or Lean has no constant by that name."),
)


def _badge(kind: str, label: str, dirs: list[str]) -> str:
    more = escape("../" * len(dirs) + "trust.html#badges", quote=True)
    return f'<p><span class="trust trust-{kind}">{escape(label)}</span> <a class="trust-more" href="{more}">what this means</a></p>'


_USES_LIMIT = 20


def _uses(found: F.DeclFacts, ctx, dirs: list[str]) -> str:
    """The constants the kernel term mentions. Names that are declared in this site link to it."""
    rows = []
    for label, names in (("Statement uses", found.statement_uses), ("Proof uses", found.proof_uses)):
        if not names:
            continue
        items = []
        for name in names[:_USES_LIMIT]:
            where = ctx.locations.get(name)
            if where is None:
                items.append(f"<code>{escape(name)}</code>")
            else:
                link = escape(href(dirs, where[0], f"#L{where[1]}"), quote=True)
                items.append(f'<a href="{link}">{escape(name)}</a>')
        more = f" and {len(names) - _USES_LIMIT} more" if len(names) > _USES_LIMIT else ""
        rows.append(f'<p class="refs">{label}: ' + ", ".join(items) + more + "</p>")
    if rows and found.hidden:
        rows.append(f'<p class="refs muted">{found.hidden} instances, coercions and auxiliary constants left out.</p>')
    return "".join(rows)


def _trace(found: F.DeclFacts, limit: int, rel: str, dirs: list[str]) -> str:
    """Each step is `L<declaration line>-step<k>`, with `data-line` the source line of its tactic: the reader joins its
    plain-English steps to these on that line."""
    if limit <= 0 or not found.steps:
        return ""
    more = f" (first {limit} of {len(found.steps)})" if len(found.steps) > limit else ""
    src = "../" * len(dirs) + _trace_asset(rel)
    key = f"{found.line}:{found.name}"
    return (
        f'<details class="trace trace-lazy" data-trace-src="{escape(src, quote=True)}" '
        f'data-trace-key="{escape(key, quote=True)}"><summary>Tactic trace: {len(found.steps)} steps{more}</summary>'
        '<p class="trace-loading muted">Open to load the checked before-and-after goal states.</p></details>'
    )


def _trace_asset(rel: str) -> str:
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:20]
    return f"_traces/{digest}.json.gz"


def _trace_payload(rel: str, file_facts: F.FileFacts, limit: int, ctx) -> bytes:
    declarations = {}
    for found in file_facts.decls:
        if not found.steps:
            continue
        declarations[f"{found.line}:{found.name}"] = [
            [
                step.line,
                step.tactic,
                list(step.before),
                list(step.after),
                source_href(rel, step.line, ctx) if ctx.source_url else "",
            ]
            for step in found.steps[:limit]
        ]
    return json.dumps({"v": 1, "d": declarations}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _tally(analysis: Analysis) -> dict[str, int]:
    counts = {"none": 0, "standard": 0, "sorry": 0, "extra": 0, "unknown": 0}
    for file_facts in analysis.files.values():
        if file_facts.status == "ok":
            for found in file_facts.decls:
                kind = F.classify(found.axioms)[0]
                # Errors can cause Lean to synthesize missing proof terms. Negative findings remain useful, but an
                # otherwise clean-looking theorem in that file is not a positive kernel check.
                if file_facts.errors and kind in ("none", "standard"):
                    kind = "unknown"
                counts[kind] += 1
    counts["unknown"] += analysis.unreported_declarations
    return {
        "no axioms": counts["none"],
        "standard axioms": counts["standard"],
        "sorry": counts["sorry"],
        "extra axioms": counts["extra"],
        "unknown": counts["unknown"],
    }


def _trust_record(analysis: Analysis) -> dict[str, object]:
    """Machine-readable release evidence, with no workstation paths or source text.

    The static site release gate consumes this record after a local build.  It is
    deliberately a summary: the declaration-level evidence remains in the badges
    and Trust page generated from the same ``Analysis`` object.
    """
    file_counts = {"ok": 0, "failed": 0, "unavailable": 0}
    declarations = analysis.unreported_declarations
    for facts in analysis.files.values():
        file_counts[facts.status if facts.status in file_counts else "failed"] += 1
        declarations += len(facts.decls)
    tally = _tally(analysis)
    kernel_checked = tally["no axioms"] + tally["standard axioms"]
    classified = kernel_checked + tally["sorry"] + tally["extra axioms"]
    return {
        "format": 1,
        "provenance": "local-lean-run" if analysis.toolchain else "unavailable",
        "toolchain": analysis.toolchain,
        "environment_sha256_16": analysis.environment_digest,
        "unavailable_reason": analysis.toolchain_issue or ("Lean was not found on the PATH." if not analysis.toolchain else ""),
        "probe_sha256_16": runner.probe_digest(),
        "files": file_counts,
        "declarations": {
            "total": declarations,
            "kernel_checked": kernel_checked,
            "classified": classified,
            **tally,
        },
        "execution": {
            "elaborated_now": analysis.ran,
            "reused_content_bound_cache": analysis.reused,
            "cache_only": analysis.cached_only,
            "cache_misses": analysis.cache_misses,
        },
        "probe_limits": {
            "seconds_per_file": analysis.timeout_seconds,
            "max_working_set_mb": analysis.max_working_set_mb,
            "minimum_free_virtual_mb": analysis.min_free_virtual_mb,
        },
        "selection": {
            "label": analysis.selection_label or "all declaration-bearing files",
            "eligible_files": analysis.eligible_files,
            "selected_files": analysis.selected_files,
            "requested_declarations": analysis.requested_declarations,
            "missing_targets": list(analysis.missing_targets),
        },
    }


def _trust_page(ctx, analysis: Analysis) -> str:
    body = ["<h1>Trust</h1>"]
    if not analysis.toolchain:
        reason = analysis.toolchain_issue or "Lean was not found on the PATH, so no declaration was checked."
        body.append(f'<p class="warn">{escape(reason)} All trust is UNKNOWN.</p>')
        return page("Trust", 0, body, ctx, canonical_path="trust.html")
    body.append(
        f'<p class="muted">Axioms come from the Lean kernel ({escape(analysis.toolchain)}): the constants each declaration '
        "depends on, as Lean's collectAxioms reports them. Standard axioms are propext, Classical.choice and Quot.sound.</p>"
    )
    if analysis.environment_digest:
        body.append(
            '<p class="muted">Lake environment and dependency-pin digest: '
            f'<code>{escape(analysis.environment_digest)}</code>.</p>'
        )
    body.append(
        '<p class="muted">Verification scope: '
        f'{escape(analysis.selection_label or "all declaration-bearing files")}; '
        f'{analysis.selected_files} of {analysis.eligible_files} eligible files selected, '
        f'{analysis.requested_declarations} declarations requested.</p>'
    )
    if analysis.cached_only:
        body.append(
            '<p class="muted">Rendering mode: clean content-bound cache results only; '
            f'{analysis.cache_misses} selected files had no reusable result and remain UNKNOWN. No Lean process was '
            'started for those misses during this static-site build.</p>'
        )
    body.append(
        '<p class="muted">Per-file probe bounds: '
        f'{analysis.timeout_seconds} seconds'
        + (f', {analysis.max_working_set_mb} MiB maximum working set' if analysis.max_working_set_mb else '')
        + (f', stop below {analysis.min_free_virtual_mb} MiB free virtual memory' if analysis.min_free_virtual_mb else '')
        + '. A resource stop is UNKNOWN, never a failed proof.</p>'
    )
    if analysis.missing_targets:
        body.append(f'<h2>Catalogue targets not found ({len(analysis.missing_targets)})</h2><ul class="list">')
        body.extend(f'<li><code>{escape(target)}</code></li>' for target in analysis.missing_targets[:_TRUST_ROWS])
        body.append("</ul>")
    body.append('<dl class="summary">' + "".join(f"<dt>{escape(k)}</dt><dd>{n}</dd>" for k, n in _tally(analysis).items()) + "</dl>")
    body.append('<h2 id="badges">What the badges mean</h2><dl class="badges">' + "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in BADGES) + "</dl>")
    failed = [(rel, f) for rel, f in analysis.files.items() if f.status == "failed"]
    if failed:
        body.append('<h2>Files Lean could not elaborate</h2><ul class="list">')
        body.extend(f"<li><code>{escape(rel)}</code>: {escape(f.reason)}</li>" for rel, f in failed)
        body.append("</ul>")
    unavailable = [(rel, f) for rel, f in analysis.files.items() if f.status == "unavailable"]
    if unavailable:
        body.append(f'<h2>Files outside this Lean pass ({len(unavailable)})</h2><ul class="list">')
        body.extend(f"<li><code>{escape(rel)}</code>: {escape(f.reason)}</li>" for rel, f in unavailable[:_TRUST_ROWS])
        if len(unavailable) > _TRUST_ROWS:
            body.append(f'<li class="muted">… and {len(unavailable) - _TRUST_ROWS} more</li>')
        body.append("</ul>")
    erroneous = [(rel, f) for rel, f in analysis.files.items() if f.status == "ok" and f.errors]
    if erroneous:
        body.append('<h2>Files where Lean reported errors</h2><ul class="list">')
        body.extend(
            f"<li><code>{escape(rel)}</code>: {escape(f.errors[0])} ({len(f.errors)} total)</li>" for rel, f in erroneous
        )
        body.append("</ul>")
    unknown = []
    for rel, file_facts in analysis.files.items():
        if file_facts.status != "ok":
            continue
        for found in file_facts.decls:
            kind, label = F.classify(found.axioms)
            if file_facts.errors and kind in ("none", "standard"):
                kind = "unknown"
                label = f"trust unknown: Lean reported {len(file_facts.errors)} error(s) in this file"
            if kind == "unknown":
                unknown.append((rel, found, label))
    if unknown:
        body.append(f'<h2>Trust UNKNOWN declarations ({len(unknown)})</h2><ol class="list">')
        for rel, found, label in unknown[:_TRUST_ROWS]:
            where = ctx.locations.get(found.name, (rel, found.line))[0]
            link = escape(href([], where, f"#L{found.line}"), quote=True)
            body.append(
                f'<li><a href="{link}"><code>{escape(found.name)}</code></a> '
                f'<span class="ln">{escape(rel)}</span> <span class="muted">{escape(label)}</span></li>'
            )
        if len(unknown) > _TRUST_ROWS:
            body.append(f'<li class="muted">… and {len(unknown) - _TRUST_ROWS} more</li>')
        body.append("</ol>")
    for heading, wanted in (("Depend on extra axioms", "extra"), ("Depend on sorry", "sorry")):
        rows = [
            (rel, d)
            for rel, f in analysis.files.items()
            if f.status == "ok"
            for d in f.decls
            if F.classify(d.axioms)[0] == wanted
        ]
        if not rows:
            continue
        body.append(f'<h2>{heading} ({len(rows)})</h2><ol class="list">')
        for rel, d in rows[:_TRUST_ROWS]:
            # ``href`` adds the rendered ``.html`` suffix. Ambiguous names are
            # deliberately absent from ``ctx.locations``, so their fallback must
            # remain the Lean-relative source path rather than an output filename.
            where = ctx.locations.get(d.name, (rel, d.line))[0]
            link = escape(href([], where, f"#L{d.line}"), quote=True)
            note = "" if wanted == "sorry" else f' <span class="muted">{escape(F.classify(d.axioms)[1])}</span>'
            body.append(f'<li><a href="{link}"><code>{escape(d.name)}</code></a> <span class="ln">{escape(rel)}</span>{note}</li>')
        if len(rows) > _TRUST_ROWS:
            body.append(f'<li class="muted">… and {len(rows) - _TRUST_ROWS} more</li>')
        body.append("</ol>")
    return page("Trust", 0, body, ctx, canonical_path="trust.html")
