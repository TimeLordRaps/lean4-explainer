"""The relationship map: a small SVG per declaration and one for the whole project."""

import re

from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer_l4del.drawing import layers, neighborhood_svg

LEAN = """\
-- L4DEL: title: The base
theorem base : True := trivial

-- L4DEL: title: The middle
-- L4DEL: prereq: base
theorem middle : True := base

-- L4DEL: title: The top
-- L4DEL: prereq: middle
-- L4DEL: see: base
theorem top : True := middle
"""


def _build(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.lean").write_text(LEAN, encoding="utf-8")
    summary = build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    return summary, tmp_path / "out"


def test_each_declaration_with_neighbours_gets_a_map(tmp_path):
    summary, out = _build(tmp_path)
    assert not summary.errors
    html = (out / "A.lean.html").read_text(encoding="utf-8")
    maps = re.findall(r'<svg class="relmap".*?</svg>', html, re.S)
    assert len(maps) == 3, "base, middle and top are all connected"
    middle = next(m for m in maps if 'aria-label="Map around middle"' in m)
    assert "base" in middle and "top" in middle  # what it builds on, and what builds on it
    assert "<a " in middle and "#L" in middle


def test_the_whole_project_map_page_exists_and_is_linked(tmp_path):
    _summary, out = _build(tmp_path)
    page = (out / "map.html").read_text(encoding="utf-8")
    assert page.count('class="relmap"') == 1
    for name in ("base", "middle", "top"):
        assert f">{name}</text>" in page
    assert 'href="map.html"' in (out / "A.lean.html").read_text(encoding="utf-8")


def test_a_declaration_with_no_links_gets_no_map(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.lean").write_text("-- L4DEL: title: Alone\ntheorem alone : True := trivial\n", encoding="utf-8")
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    assert "relmap" not in (tmp_path / "out" / "A.lean.html").read_text(encoding="utf-8")


def test_layers_put_prerequisites_to_the_left():
    assert layers({"a": [], "b": ["a"], "c": ["b", "a"]}) == {"a": 0, "b": 1, "c": 2}


def test_layers_survive_a_cycle():
    found = layers({"a": ["b"], "b": ["a"]})
    assert set(found) == {"a", "b"}


def test_names_are_escaped_in_the_svg():
    svg = neighborhood_svg(
        "x", ["<script>"], [], [], label=lambda key: key, link=lambda key: "#" + key
    )
    assert "<script>" not in svg and "&lt;script&gt;" in svg
