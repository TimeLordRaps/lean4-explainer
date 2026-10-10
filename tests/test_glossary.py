"""The glossary page: every word the site uses, with what it means and where it is defined."""

import re
from html import unescape
from pathlib import Path

import pytest

from lean4_explainer import extensions, glossary
from lean4_explainer.build import build_site
from lean4_explainer.config import Config, load_config
from lean4_explainer.errors import ExplainerError
from lean4_explainer.extensions import Extension, GlossaryEntry, GlossarySection

README = Path(__file__).resolve().parents[1] / "README.md"

PROJECT = """\
namespace Geo

/-- A point in the plane, given by two coordinates.

The second paragraph is not part of the gist. -/
structure Point where
  x : Nat
  y : Nat

/-- The sum of the coordinates. -/
def Point.size (p : Point) : Nat := p.x + p.y

def double (n : Nat) : Nat :=
  2 * n

abbrev Pair := Nat × Nat

-- Things that can be measured.
class Measured (α : Type) where
  measure : α → Nat

inductive Color
  | red
  | green

theorem size_zero : (Point.mk 0 0).size = 0 := rfl

lemma helper : True := trivial

instance : Measured Point := ⟨Point.size⟩

example : 1 + 1 = 2 := rfl

end Geo
"""


def _site(tmp_path, files, config=None):
    root = tmp_path / "lean"
    root.mkdir()
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    out = tmp_path / "site"
    summary = build_site(root, out, config)
    return out, summary


def _section(html, key):
    """The HTML of one glossary section, from its heading to the next one."""
    match = re.search(rf'<h2 id="{key}">(.*?)(?=<h2 |</main>)', html, re.S)
    assert match, f"no section {key}"
    return match.group(1)


def _terms(section_html):
    return [unescape(re.sub(r"<[^>]+>", "", t)).strip() for t in re.findall(r"<dt[^>]*>(.*?)</dt>", section_html, re.S)]


def test_every_definition_of_the_project_is_in_the_glossary(tmp_path):
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT})
    html = (out / "glossary.html").read_text(encoding="utf-8")
    project = _section(html, "g-project")

    names = re.findall(r'<a class="where" href="[^"]*">([^<]*)</a>', project)
    # definitions are words; theorems, lemmas, instances and examples are not
    assert sorted(names) == ["Geo.Color", "Geo.Measured", "Geo.Pair", "Geo.Point", "Geo.Point.size", "Geo.double"]
    # listed under the word itself, sorted without regard to case or namespace
    assert _terms(project) == ["Color inductive", "double def", "Measured class", "Pair abbrev", "Point structure", "size def"]
    # the gist is the first paragraph of the doc comment (or the plain comment), and the entry links to the source
    assert "A point in the plane, given by two coordinates." in project
    assert "second paragraph" not in project
    assert "Things that can be measured." in project
    assert 'href="Geo.lean.html#L6"' in project
    # an undescribed definition shows its signature instead
    assert "<code>def double (n : Nat) : Nat</code>" in project
    assert "<code>abbrev Pair</code>" in project


def test_every_page_links_to_the_glossary_without_any_extension(tmp_path):
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT, "Sub/B.lean": "def b : Nat := 1\n"})
    for page in ("index.html", "Geo.lean.html", "Sub/B.lean.html", "Sub/index.html", "search.html", "glossary.html"):
        html = (out / page).read_text(encoding="utf-8")
        nav = re.search(r'<nav class="top">(.*?)</nav>', html).group(1)
        assert nav.count(">Glossary<") == 1, page
    assert 'href="../glossary.html"' in (out / "Sub" / "B.lean.html").read_text(encoding="utf-8")


def test_the_lean_words_cover_the_readme_list(tmp_path):
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT})
    words = " | ".join(_terms(_section((out / "glossary.html").read_text(encoding="utf-8"), "g-lean"))).lower()
    listed = re.search(r"## Words you will meet\n(.*?)\n## ", README.read_text(encoding="utf-8"), re.S).group(1)
    bold = re.findall(r"^- \*\*(.+?):\*\*", listed, re.M)
    assert len(bold) >= 9
    for item in bold:
        for word in re.split(r",\s*", item.replace("`", "")):
            word = word.split(" (")[0].strip().lower()
            assert word in words, word


def test_described_scope_lists_only_described_definitions(tmp_path):
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT}, Config(glossary="described"))
    project = _section((out / "glossary.html").read_text(encoding="utf-8"), "g-project")
    assert _terms(project) == ["Measured class", "Point structure", "size def"]


def test_none_scope_leaves_the_project_out_but_keeps_the_page(tmp_path):
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT}, Config(glossary="none"))
    html = (out / "glossary.html").read_text(encoding="utf-8")
    assert 'id="g-project"' not in html
    assert 'id="g-lean"' in html


def test_the_glossary_setting_is_validated(tmp_path):
    good = tmp_path / "good.toml"
    good.write_text('glossary = "described"\n', encoding="utf-8")
    assert load_config(good).glossary == "described"
    bad = tmp_path / "bad.toml"
    bad.write_text('glossary = "everything"\n', encoding="utf-8")
    with pytest.raises(ExplainerError, match="glossary"):
        load_config(bad)


def test_identical_copies_are_one_entry_and_differing_ones_are_two(tmp_path):
    same = "/-- Same. -/\ndef twin : Nat := 1\n"
    out, _ = _site(
        tmp_path,
        {"A.lean": same + "/-- One. -/\ndef split : Nat := 1\n", "B.lean": same + "/-- Two. -/\ndef split : Nat := 2\n"},
    )
    project = _section((out / "glossary.html").read_text(encoding="utf-8"), "g-project")
    assert _terms(project) == ["split def", "split def", "twin def"]
    assert project.count("Same.") == 1
    assert "One." in project and "Two." in project


def test_entries_come_back_the_same_from_the_cache(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    (root / "Geo.lean").write_text(PROJECT, encoding="utf-8")
    out = tmp_path / "site"
    build_site(root, out)
    first = (out / "glossary.html").read_text(encoding="utf-8")
    second_summary = build_site(root, out)
    assert second_summary.pages_reused == 1  # the file came from the cache, not a fresh parse
    assert (out / "glossary.html").read_text(encoding="utf-8") == first
    (root / "Geo.lean").write_text(PROJECT.replace("The sum of the coordinates.", "Adds the coordinates."), encoding="utf-8")
    build_site(root, out)
    third = (out / "glossary.html").read_text(encoding="utf-8")
    assert "Adds the coordinates." in third and "The sum of the coordinates." not in third


def test_a_large_project_list_is_split_into_one_page_per_letter(tmp_path, monkeypatch):
    monkeypatch.setattr(glossary, "SPLIT_AT", 4)
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT, "Sub/More.lean": "def apple : Nat := 1\ndef _hidden : Nat := 2\ndef πfun : Nat := 3\n"})
    html = (out / "glossary.html").read_text(encoding="utf-8")
    project = _section(html, "g-project")
    assert "<dt" not in project
    letters = re.findall(r'<a href="(glossary-[^"]+\.html)">', project)
    assert letters == ["glossary-a.html", "glossary-c.html", "glossary-d.html", "glossary-m.html", "glossary-p.html", "glossary-s.html", "glossary-other.html"]
    seen = []
    for name in letters:
        shard = (out / name).read_text(encoding="utf-8")
        assert re.search(r'<nav class="top">.*>Glossary<', shard)
        seen += _terms(shard)
    assert sorted(seen, key=str.lower) == sorted(
        ["apple def", "_hidden def", "πfun def", "Color inductive", "double def", "Measured class", "Pair abbrev", "Point structure", "size def"],
        key=str.lower,
    )
    other = (out / "glossary-other.html").read_text(encoding="utf-8")
    assert 'href="Sub/More.lean.html#L2"' in other

    # back under the limit, the letter pages of the bigger build are removed
    monkeypatch.setattr(glossary, "SPLIT_AT", 2000)
    build_site(tmp_path / "lean", out)
    assert not list(out.glob("glossary-*.html"))
    assert "<dt" in _section((out / "glossary.html").read_text(encoding="utf-8"), "g-project")


def test_ids_on_the_page_are_unique_and_letter_headings_group_a_long_list(tmp_path, monkeypatch):
    monkeypatch.setattr(glossary, "GROUP_AT", 3)
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT})
    html = (out / "glossary.html").read_text(encoding="utf-8")
    ids = re.findall(r' id="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    assert "lean-sorry" in ids and "g-project-p" in ids
    project = _section(html, "g-project")
    assert re.findall(r'<a href="#g-project-([a-z]+)">', project) == ["c", "d", "m", "p", "s"]


def test_several_worker_processes_give_the_same_glossary(tmp_path):
    root = tmp_path / "lean"
    root.mkdir()
    for k in range(4):
        (root / f"F{k}.lean").write_text(PROJECT.replace("namespace Geo", f"namespace Geo{k}").replace("end Geo", f"end Geo{k}"), encoding="utf-8")
    build_site(root, tmp_path / "one", jobs=1)
    build_site(root, tmp_path / "two", Config(), tmp_path / "two-cache", jobs=2)
    assert (tmp_path / "one" / "glossary.html").read_bytes() == (tmp_path / "two" / "glossary.html").read_bytes()


class WordsExtension(Extension):
    name = "words"
    version = "1"

    def glossary(self, ctx, analysis):
        return [
            GlossarySection(
                key="words",
                title="Toy <words>",
                intro="Words from a toy extension.",
                entries=(
                    GlossaryEntry(term="b<i>", meaning="the letter <code>b</code>", example="b <i>", anchor="w1"),
                    GlossaryEntry(term="a", meaning="first", where=("Geo.lean", 6, "Geo.Point")),
                ),
            ),
            GlossarySection(key="empty", title="Nothing", entries=()),
        ]


def test_extensions_add_sections_of_their_own(tmp_path):
    extensions.activate([WordsExtension()])
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT})
    html = (out / "glossary.html").read_text(encoding="utf-8")
    words = _section(html, "g-words")
    assert "Toy &lt;words&gt;" in words
    assert _terms(words) == ["a", "b<i>"]
    assert '<dt id="w1">b&lt;i&gt;</dt>' in words
    assert "the letter <code>b</code>" in words  # meanings are HTML the extension made
    assert "<code>b &lt;i&gt;</code>" in words  # examples are Lean text
    assert '<a class="where" href="Geo.lean.html#L6">Geo.Point</a>' in words
    assert 'id="g-empty"' not in html  # an empty section is left out
    contents = re.search(r'<nav class="toc">(.*?)</nav>', html, re.S).group(1)
    assert [unescape(t) for t in re.findall(r'href="#g-[^"]+">([^<]*)<', contents)] == [
        "Defined in this project", "Toy <words>", "Lean words"
    ]


def test_every_entry_can_be_filtered(tmp_path):
    out, _ = _site(tmp_path, {"Geo.lean": PROJECT})
    html = (out / "glossary.html").read_text(encoding="utf-8")
    assert "data-filter" in html
    dts = html.count("<dt")
    assert dts > 10
    assert html.count("<div data-filterable>") == dts
