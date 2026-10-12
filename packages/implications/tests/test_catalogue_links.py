from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from lean4_explainer import extensions
from lean4_explainer_implications import catalogue_site as CS
from lean4_explainer_implications.extension import ImplicationsExtension
from test_implications import _recorded_site


class _LinksAndAnchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []
        self.anchors: set[str] = set()
        self.duplicate_anchors: set[str] = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values and values["id"] is not None:
            if values["id"] in self.anchors:
                self.duplicate_anchors.add(values["id"])
            self.anchors.add(values["id"])
        if tag == "a" and values.get("name"):
            if values["name"] in self.anchors:
                self.duplicate_anchors.add(values["name"])
            self.anchors.add(values["name"])
        if "href" in values and values["href"] is not None:
            self.hrefs.append(values["href"])

    handle_startendtag = handle_starttag


@pytest.fixture(autouse=True)
def _implications_extension_only():
    extensions.activate([ImplicationsExtension()])
    yield
    extensions.activate(None)


def _html(path: Path) -> _LinksAndAnchors:
    parsed = _LinksAndAnchors()
    parsed.feed(path.read_text(encoding="utf-8"))
    return parsed


def _local_target(site: Path, page: Path, href: str) -> tuple[Path, str] | None:
    url = urlsplit(href)
    if url.scheme or url.netloc:
        return None
    relative = unquote(url.path)
    if not relative:
        target = page
    elif relative.startswith("/"):
        target = site / relative.lstrip("/")
    else:
        target = page.parent / relative
    target = target.resolve()
    try:
        target.relative_to(site.resolve())
    except ValueError:
        pytest.fail(f"local link escapes the generated site: {page.relative_to(site)} -> {href}")
    if target.is_dir():
        target /= "index.html"
    return target, unquote(url.fragment)


def test_every_local_link_and_deep_anchor_in_the_recorded_catalogue_site_resolves(tmp_path):
    summary, site = _recorded_site(tmp_path)
    assert not summary.errors, summary.errors

    pages = sorted(site.rglob("*.html"))
    assert pages
    parsed = {page: _html(page) for page in pages}
    for page, document in parsed.items():
        assert not document.duplicate_anchors, (
            f"duplicate anchors in {page.relative_to(site)}: {sorted(document.duplicate_anchors)}"
        )
    checked = 0
    for page, document in parsed.items():
        for href in document.hrefs:
            local = _local_target(site, page, href)
            if local is None:
                continue
            target, fragment = local
            assert target.is_file(), f"missing local link: {page.relative_to(site)} -> {href}"
            checked += 1
            if fragment:
                assert target.suffix == ".html", (
                    f"fragment points outside an HTML document: {page.relative_to(site)} -> {href}"
                )
                target_document = parsed.get(target) or _html(target)
                assert fragment in target_document.anchors, (
                    f"missing deep-link anchor: {page.relative_to(site)} -> {href}"
                )

    assert checked > 0


def test_the_catalogue_page_refuses_duplicate_fragment_ids():
    index = {"counts": {}, "environment": {}, "implications": [{"id": "same"}, {"id": "same"}]}
    with pytest.raises(ValueError, match="duplicate catalogue implication id same"):
        CS.catalogue_body(index)
