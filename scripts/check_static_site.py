"""Fail closed on the public proofsite's small but consequential release contract.

This is deliberately a smoke gate rather than an exhaustive crawler: it checks
the landing page, recovery/discovery files, every corpus home and the feature
pages that exist. It never requests external URLs.
"""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.etree import ElementTree

if __package__:
    from .finalize_local_site import collect_trust
else:  # `python scripts/check_static_site.py ...`
    from finalize_local_site import collect_trust


class Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.meta: dict[tuple[str, str], str] = {}
        self.ids: set[str] = set()
        self.classes: set[str] = set()
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        self.classes.update((values.get("class") or "").split())
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"] or "")
        if tag == "link" and values.get("rel") and values.get("href"):
            self.meta[("link", values["rel"] or "")] = values["href"] or ""
        if tag == "meta":
            key = values.get("name") or values.get("property")
            if key and values.get("content"):
                self.meta[("meta", key)] = values["content"] or ""

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())


def _document(path: Path) -> Document:
    doc = Document()
    doc.feed(path.read_text(encoding="utf-8"))
    return doc


def _local_target(site: Path, page: Path, href: str, base_path: str) -> Path | None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or href.startswith(("mailto:", "javascript:")):
        return None
    raw = unquote(parsed.path)
    if not raw:
        return None
    directory = raw.endswith("/")
    if raw.startswith("/"):
        if base_path and raw.startswith(base_path):
            raw = raw[len(base_path) :]
        else:
            return None
        target = site / raw
    else:
        target = page.parent / raw
    if directory:
        target /= "index.html"
    try:
        target.resolve().relative_to(site.resolve())
    except ValueError:
        return Path("__outside_site__")
    return target


def _sample_pages(site: Path) -> list[Path]:
    pages = [site / "index.html", site / "404.html"]
    for corpus in sorted(path for path in site.iterdir() if path.is_dir() and (path / "index.html").is_file()):
        pages.append(corpus / "index.html")
        for name in ("search.html", "glossary.html", "learning-path.html", "map.html", "annotate.html", "trust.html"):
            if (corpus / name).is_file():
                pages.append(corpus / name)
    featured = site / "flt" / "FLT" / "Proof.lean.html"
    if featured.is_file():
        pages.append(featured)
    return list(dict.fromkeys(pages))


def check_site(site: Path, site_url: str) -> list[str]:
    errors: list[str] = []
    site = site.resolve()
    parsed_url = urlsplit(site_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.query or parsed_url.fragment:
        return ["site URL must be HTTPS without a query or fragment"]
    site_url = site_url.rstrip("/") + "/"
    base_path = parsed_url.path.rstrip("/") + "/"
    required = ("index.html", "404.html", "robots.txt", "sitemap.xml", "_assets/favicon.svg", "build-info.json")
    for rel in required:
        if not (site / rel).is_file():
            errors.append(f"missing {rel}")
    if errors:
        return errors

    samples = _sample_pages(site)
    for page in samples:
        rel = page.relative_to(site).as_posix()
        doc = _document(page)
        if rel != "404.html":
            required_meta = [("meta", "description")]
            if not rel.endswith(".lean.html"):
                required_meta.extend((("meta", "og:title"), ("meta", "og:description"), ("meta", "twitter:card")))
            for key in required_meta:
                if not doc.meta.get(key):
                    errors.append(f"{rel}: missing {key[1]}")
            if "skip-link" not in doc.classes or "content" not in doc.ids:
                errors.append(f"{rel}: missing skip navigation or #content")
            if not doc.meta.get(("link", "canonical")):
                errors.append(f"{rel}: missing canonical link")
        for href in doc.hrefs:
            target = _local_target(site, page, href, base_path)
            if target is not None and not target.is_file():
                errors.append(f"{rel}: broken local link {href}")

    landing = _document(site / "index.html")
    landing_text = " ".join(landing.text)
    if "Start exploring" not in landing_text or "All corpora" not in landing_text:
        errors.append("index.html: missing reader onboarding")
    if "Lean4 Domain Explanation Language (L4DEL)" not in landing_text:
        errors.append("index.html: explanation language is not introduced by its full name")
    if "Report a site issue" not in landing_text:
        errors.append("index.html: missing feedback route")
    if "Lean-backed trust results produced locally" not in landing_text:
        errors.append("index.html: missing local Lean verification disclosure")
    if "Built from the source text only" in landing_text or "Lean was not run" in landing_text:
        errors.append("index.html: source-only release cannot be published as the verified showcase")
    if landing.meta.get(("link", "canonical")) != site_url:
        errors.append("index.html: canonical URL does not match --site-url")

    try:
        actual_trust = collect_trust(site)
    except ValueError as exc:
        errors.append(str(exc))
        actual_trust = None
    try:
        build_info = json.loads((site / "build-info.json").read_text(encoding="utf-8"))
        if build_info.get("format") != 1 or build_info.get("build_mode") != "local-lean":
            errors.append("build-info.json: release was not finalized as a local Lean build")
        if not re.fullmatch(r"[0-9a-f]{40}", str(build_info.get("repository_sha", ""))):
            errors.append("build-info.json: invalid repository SHA")
        if actual_trust is not None and build_info.get("trust") != actual_trust:
            errors.append("build-info.json: trust totals do not match the corpus records")
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"build-info.json: cannot parse: {exc}")
    if "annotation-audit.json" in landing.hrefs:
        audit_path = site / "annotation-audit.json"
        if not audit_path.is_file():
            errors.append("index.html: linked annotation audit is missing")
        else:
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                curated = audit.get("curated_entries", [])
                expected_curated = audit.get("totals", {}).get("curated_source_linked_unreviewed")
                if audit.get("status") != "PASS":
                    errors.append("annotation-audit.json: status is not PASS")
                if expected_curated != len(curated):
                    errors.append("annotation-audit.json: curated entry count is inconsistent")
                if any(
                    item.get("review_state") != "source-linked-unreviewed"
                    or not re.match(r"https://github\.com/.+/blob/[0-9a-f]{40}/", item.get("exact_source_url", ""))
                    or not item.get("source_statement_sha256")
                    for item in curated
                ):
                    errors.append("annotation-audit.json: a curated entry lacks fail-closed source evidence")
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"annotation-audit.json: cannot parse: {exc}")

    not_found = " ".join(_document(site / "404.html").text)
    if "Return to all corpora" not in not_found:
        errors.append("404.html: missing recovery link")

    featured = site / "flt" / "FLT" / "Proof.lean.html"
    if featured.is_file():
        text = featured.read_text(encoding="utf-8")
        featured_doc = _document(featured)
        if not featured_doc.meta.get(("meta", "og:title")) or not featured_doc.meta.get(("meta", "twitter:card")):
            errors.append("flt/FLT/Proof.lean.html: featured annotation lacks full share metadata")
        if "Sources and attribution:" not in text or not re.search(r"github\.com/[^/]+/[^/]+/blob/[0-9a-f]{40}/", text):
            errors.append("flt/FLT/Proof.lean.html: hosted annotation lacks an exact pinned grounding link")
        featured_text = " ".join(featured_doc.text)
        if "Explanation legend" not in featured_text or "Lean4 Domain Explanation Language" not in featured_text:
            errors.append("flt/FLT/Proof.lean.html: annotation lacks its page-top explanation legend")
        if "Credit:" not in featured_text or "Project sources:" not in featured_text:
            errors.append("flt/FLT/Proof.lean.html: annotation lacks author credit or project sources")

    sitemap_files: set[str] = set()
    try:
        index = ElementTree.parse(site / "sitemap.xml").getroot()
        for node in index.findall("{*}sitemap/{*}loc"):
            name = PurePosixPath(urlsplit(node.text or "").path).name
            if name:
                sitemap_files.add(name)
    except (ElementTree.ParseError, OSError) as exc:
        errors.append(f"sitemap.xml: cannot parse: {exc}")
    listed: set[str] = set()
    for name in sitemap_files:
        path = site / name
        if not path.is_file():
            errors.append(f"sitemap.xml: missing referenced {name}")
            continue
        try:
            root = ElementTree.parse(path).getroot()
            for node in root.findall("{*}url/{*}loc"):
                url = node.text or ""
                if url.startswith(site_url):
                    listed.add(unquote(url[len(site_url) :]))
        except ElementTree.ParseError as exc:
            errors.append(f"{name}: cannot parse: {exc}")
    expected = {
        path.relative_to(site).as_posix()
        for path in site.rglob("*.html")
        if path.name != "404.html"
    }
    missing = expected - listed
    extra = listed - expected
    if missing:
        errors.append(f"sitemaps omit {len(missing)} HTML page(s), first: {sorted(missing)[0]}")
    if extra:
        errors.append(f"sitemaps list {len(extra)} missing page(s), first: {sorted(extra)[0]}")

    robots = (site / "robots.txt").read_text(encoding="utf-8")
    if f"Sitemap: {urljoin(site_url, 'sitemap.xml')}" not in robots:
        errors.append("robots.txt: sitemap URL does not match --site-url")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--site-url", required=True)
    args = parser.parse_args()
    errors = check_site(args.site, args.site_url)
    for error in errors:
        print(f"error: {error}")
    if errors:
        return 1
    pages = sum(1 for _ in args.site.rglob("*.html"))
    print(f"static site smoke gate passed: {pages} HTML pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
