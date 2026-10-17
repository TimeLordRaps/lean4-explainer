"""Doc comments are Markdown with TeX in them: they are drawn as HTML, and their formulas are marked for typesetting."""

import re
from html import unescape

import pytest

from lean4_explainer import extensions
from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer.markdown import doc_html, inline_html, math_spans

# formal-conjectures, FormalConjectures/ErdosProblems/1.lean line 38: shown raw on the site before (a user's screenshot)
SUM_DISTINCT = (
    "A finite set of naturals $A$ is said to be a sum-distinct set for $N \\in \\mathbb{N}$ if\n"
    "$A\\subseteq\\{1, ..., N\\}$ and the sums $\\sum_{a\\in S}a$ are distinct for all $S\\subseteq A$"
)


def _tex(text):
    return [text[a:b] for a, b in math_spans(text)]


@pytest.mark.parametrize(
    "text, formulas",
    [
        (SUM_DISTINCT, ["$A$", "$N \\in \\mathbb{N}$", "$A\\subseteq\\{1, ..., N\\}$", "$\\sum_{a\\in S}a$", "$S\\subseteq A$"]),
        ("Let $P(n, k)$ be the largest prime factor of $\\binom{n}{k}$.", ["$P(n, k)$", "$\\binom{n}{k}$"]),
        ("Display $$\\sum_i a_i$$ here", ["$$\\sum_i a_i$$"]),
        (r"Inline \(x + y\) and display \[x = y\]", [r"\(x + y\)", r"\[x = y\]"]),
        ("costs $5 and $6, not math", []),
        ("In [Er93] Erdős offers $100 for a proof of this and $1000 for a disproof, but says", []),
        ("an unclosed $x and a ` lone backtick", []),
        ("inside code `f $ x` stays code", []),
        ("escaped \\$ dollar and $a$", ["$a$"]),
        ("plain words", []),
        # a formula may run over a line break (authors wrap long ones), never over a blank line
        ("identity: $\\sum_{n=1}^\\infty \\frac{1}{t^n - 1} =\n\\sum_{n=1}^\\infty d(n)$ holds", ["$\\sum_{n=1}^\\infty \\frac{1}{t^n - 1} =\n\\sum_{n=1}^\\infty d(n)$"]),
        ("open $a +\n\nb$ shut", []),
        # doc-gen4 allows a space just inside the dollars: counted when the inside looks like TeX
        ("A set $A ⊆ ℕ $ has property P", ["$A ⊆ ℕ $"]),
        ("the set\n$ \\{a ∈ A | n + a\\text{ is squarefree}\\}$ is finite", ["$ \\{a ∈ A | n + a\\text{ is squarefree}\\}$"]),
        ("let $ a = \\frac{m}{n} $ where", ["$ a = \\frac{m}{n} $"]),
        ("I have $ and you have $.", []),
        # a dollar inside braces is math inside text inside math
        ("$F(n) := \\max\\{m + p(m) \\mid \\textrm{$m$ prime}\\}$ grows", ["$F(n) := \\max\\{m + p(m) \\mid \\textrm{$m$ prime}\\}$"]),
        ("two `` a ` b `` and $x$", ["$x$"]),
    ],
)
def test_formulas_are_found_by_the_dollar_rules(text, formulas):
    assert _tex(text) == formulas


def test_formulas_are_kept_as_written_for_the_reader_and_escaped():
    html = inline_html("Let $a<b$ and `x < y` & go")
    assert html == 'Let <span class="tex">$a&lt;b$</span> and <code>x &lt; y</code> &amp; go'
    assert inline_html(SUM_DISTINCT).count('<span class="tex">') == 5
    # TeX is not Markdown: underscores and stars inside a formula stay
    assert inline_html("$a_1 * b_1 * c$ and $x_i$") == '<span class="tex">$a_1 * b_1 * c$</span> and <span class="tex">$x_i$</span>'
    assert inline_html(r"\(a<b\) then \[c>d\]") == (
        '<span class="tex">\\(a&lt;b\\)</span> then <span class="tex">\\[c&gt;d\\]</span>'
    )


@pytest.mark.parametrize(
    "text, html",
    [
        ("**strong** and *em* and _em too_", "<strong>strong</strong> and <em>em</em> and <em>em too</em>"),
        ("snake_case_name and 2*3*4 and a * b", "snake_case_name and 2*3*4 and a * b"),
        ("\\*not em\\* and \\_x\\_", "*not em* and _x_"),
        ("*the $x$ value*", '<em>the <span class="tex">$x$</span> value</em>'),
        ("see [Er93](https://www.erdosproblems.com/1).", 'see <a href="https://www.erdosproblems.com/1">Er93</a>.'),
        (
            "[Wiki](https://en.wikipedia.org/wiki/Sidon_sequence_(math)) here",
            '<a href="https://en.wikipedia.org/wiki/Sidon_sequence_(math)">Wiki</a> here',
        ),
        ("at <https://arxiv.org/abs/1234.5678>.", 'at <a href="https://arxiv.org/abs/1234.5678">https://arxiv.org/abs/1234.5678</a>.'),
        ("see https://oeis.org/A000001, and (https://example.org/x).", 'see <a href="https://oeis.org/A000001">https://oeis.org/A000001</a>, and (<a href="https://example.org/x">https://example.org/x</a>).'),
        (
            "a bad link: [example][https://example.com].",
            'a bad link: [example][<a href="https://example.com">https://example.com</a>].',
        ),
        ("see [https://example.org/a_(b)] there", 'see [<a href="https://example.org/a_(b)">https://example.org/a_(b)</a>] there'),
        ("a [`Finset`](https://x.org/F) link", 'a <a href="https://x.org/F"><code>Finset</code></a> link'),
        ("[x](javascript:alert(1)) and [y](data:text/html,hi)", "[x](javascript:alert(1)) and [y](data:text/html,hi)"),
        ('[q](https://x.org/?a=1&b="2")', '<a href="https://x.org/?a=1&amp;b=&quot;2&quot;">q</a>'),
        ("<script>alert(1)</script> & <b>", "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;"),
        ("a  0  b", "a � 0 � b"),
        ("[Er93] Erdős, P., *Some problems*", "[Er93] Erdős, P., <em>Some problems</em>"),
        # Carleson: letters of a name in bold, as CommonMark allows inside a word
        ("(**d**ens₁ **a**nti**c**hain **h**)", "(<strong>d</strong>ens₁ <strong>a</strong>nti<strong>c</strong>hain <strong>h</strong>)"),
        # formal-conjectures: spaces inside the parentheses, a title over two lines
        (
            "[Erdős Problem\n306 ]( https://github.com/x/erdos-306 ), which",
            '<a href="https://github.com/x/erdos-306">Erdős Problem\n306 </a>, which',
        ),
        ("[Kanold](No references found)", "[Kanold](No references found)"),
    ],
)
def test_inline_markdown(text, html):
    assert inline_html(text) == html


def test_blocks_headings_paragraphs_lists_code_quotes_and_rules():
    text = """# Erdős Problem 1

*Reference:* [erdosproblems.com/1](https://www.erdosproblems.com/1)

The conditions:
- the set is finite
- its sums are distinct:
  1. every subset
  2. counted once

3. three
4. four

```lean
theorem x : 1 < 2 := by decide
```

> quoted *text*

---
Setext title
============
last
line"""
    html = doc_html(text)
    assert html == (
        "<h3>Erdős Problem 1</h3>"
        '<p><em>Reference:</em> <a href="https://www.erdosproblems.com/1">erdosproblems.com/1</a></p>'
        "<p>The conditions:</p>"
        "<ul><li>the set is finite</li><li>its sums are distinct:<ol><li>every subset</li><li>counted once</li></ol></li></ul>"
        '<ol start="3"><li>three</li><li>four</li></ol>'
        "<pre><code>theorem x : 1 &lt; 2 := by decide</code></pre>"
        "<blockquote><p>quoted <em>text</em></p></blockquote>"
        "<hr>"
        "<h3>Setext title</h3>"
        "<p>last\nline</p>"
    )


def test_a_numbered_line_inside_a_paragraph_is_not_a_list():
    assert doc_html("It was proved in\n1999. Then more.") == "<p>It was proved in\n1999. Then more.</p>"
    assert doc_html("Steps:\n1. one\n2. two") == "<p>Steps:</p><ol><li>one</li><li>two</li></ol>"


def test_a_formula_over_several_lines_is_not_cut_by_a_line_that_looks_like_markdown():
    # PFR, FirstEstimate.lean line 93: the second line of the formula starts with "- "
    text = "is at least\n$$ k - \\eta (d[X; Y])\n  - \\eta(d[Z; W]).$$\nso"
    html = doc_html(text)
    assert html == '<p>is at least\n<span class="tex">$$ k - \\eta (d[X; Y])\n- \\eta(d[Z; W]).$$</span>\nso</p>'
    # once the formula is closed, a list may start again
    assert "<ul><li>item</li></ul>" in doc_html("$$a$$ then\n- item")


def test_a_loose_list_keeps_its_paragraphs():
    assert doc_html("- one\n\n- two\n\n  more") == "<ul><li><p>one</p></li><li><p>two</p><p>more</p></li></ul>"


PROJECT = """\
/-!
# Sum-distinct sets

See [Erdős #1](https://www.erdosproblems.com/1).
-/

/-- A finite set of naturals $A$ is *sum-distinct* when
its subset sums $\\sum_{a\\in S}a$ differ.

- finite
- distinct -/
def IsSumDistinct (A : List Nat) : Prop := True

-- A plain comment: *not* Markdown, `kept` as written.
def plain : Nat := 1
"""


def test_pages_and_the_glossary_draw_doc_comments(tmp_path):
    extensions.activate([])
    try:
        src = tmp_path / "src"
        src.mkdir()
        (src / "Sum.lean").write_text(PROJECT, encoding="utf-8")
        summary = build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
        assert not summary.errors
        page = (tmp_path / "out" / "Sum.lean.html").read_text(encoding="utf-8")
        assert '<div class="doc"><h3>Sum-distinct sets</h3><p>See <a href="https://www.erdosproblems.com/1">Erdős #1</a>.</p></div>' in page
        assert (
            '<div class="doc"><p>A finite set of naturals <span class="tex">$A$</span> is <em>sum-distinct</em> when\n'
            'its subset sums <span class="tex">$\\sum_{a\\in S}a$</span> differ.</p><ul><li>finite</li><li>distinct</li></ul></div>'
        ) in page
        assert '<div class="doc plain">A plain comment: *not* Markdown, `kept` as written.</div>' in page
        glossary = (tmp_path / "out" / "glossary.html").read_text(encoding="utf-8")
        entry = re.search(r'<dt>IsSumDistinct <span class="kind">def</span></dt><dd>(.*?)</dd>', glossary, re.S)
        assert entry, glossary
        assert '<span class="tex">$A$</span> is <em>sum-distinct</em>' in entry.group(1)
        # a plain comment is not Markdown here either
        assert '<dd>A plain comment: *not* Markdown, `kept` as written. <span class="muted">' in glossary
    finally:
        extensions.activate(None)


def test_text_made_literal_shows_exactly_as_written():
    from lean4_explainer.glossary import literal

    for text in (r"the set \{1, 2\} and *x* and `y`", r"a \\ b \* c $d$ [e](f) <g> #h", "plain"):
        assert unescape(inline_html(literal(text))) == text


def test_a_glossary_gist_leaves_out_heading_marks():
    from lean4_explainer.glossary import gist

    assert gist("# Title\n\nBody") == "Title"
    assert gist("## Sub title here") == "Sub title here"
    assert gist("A #hashtag stays") == "A #hashtag stays"
    assert unescape(inline_html(gist("# The $x$ thing"))) == 'The <span class="tex">$x$</span> thing'
