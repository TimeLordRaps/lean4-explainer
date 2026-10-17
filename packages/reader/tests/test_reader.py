"""The reader: pages carry the source (or where to fetch it), and reader.js turns a declaration into a reading."""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from lean4_explainer import extensions
from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer_reader import ReaderExtension
from lean4_explainer_reader.extension import KATEX, KATEX_DIR, LEAN2TEX_JS, READER_JS

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

DEMO = textwrap.dedent(
    """\
    import Mathlib

    namespace Demo

    /-- A doc comment. -/
    theorem two_mul_pos (n : ℕ) (hn : 0 < n) : 0 < 2 * n := by
      have h2 : (0 : ℕ) < 2 := by norm_num
      exact Nat.mul_pos h2 hn

    def double : ℕ → ℕ
      | 0 => 0
      | n + 1 => double n + 2

    theorem double_eq (n : ℕ) : double n = 2 * n := by
      induction n with
      | zero => rfl
      | succ k ih =>
        simp [double, ih]
        ring

    theorem odd_or_even (n : ℕ) : Even n ∨ Odd n := by
      rcases Nat.even_or_odd n with h | h
      · left
        exact h
      · right
        exact h

    theorem sq_le (a b : ℝ) (h : 0 ≤ a) (hab : a ≤ b) : a ^ 2 ≤ b ^ 2 := by
      calc a ^ 2 = a * a := by ring
        _ ≤ b * b := by nlinarith
        _ = b ^ 2 := by ring

    theorem forall_exists : ∀ n : ℕ, ∃ m, n < m := fun n => ⟨n + 1, Nat.lt_succ_self n⟩

    structure Point where
      x : ℝ
      y : ℝ

    inductive Color
      | red
      | green

    theorem unfinished (p : ℕ) (hp : p.Prime) : 2 ≤ p := by
      sorry

    end Demo
    """
)
LINES = {
    "two_mul_pos": 6, "double": 10, "double_eq": 14, "odd_or_even": 21,
    "sq_le": 28, "forall_exists": 33, "Point": 35, "Color": 39, "unfinished": 43,
}


@pytest.fixture(autouse=True)
def only_reader():
    extensions.activate([ReaderExtension()])
    yield
    extensions.activate(None)


def _build(tmp_path, text=DEMO, options=()):
    src = tmp_path / "src"
    (src / "Demo").mkdir(parents=True)
    (src / "Demo" / "Basic.lean").write_text(text, encoding="utf-8")
    build_site(src, tmp_path / "out", Config(options=tuple(options), source_ref="abc123"), tmp_path / "idx", jobs=1)
    return (tmp_path / "out" / "Demo" / "Basic.lean.html").read_text(encoding="utf-8"), tmp_path / "out"


def test_a_page_carries_its_source_and_loads_the_reader(tmp_path):
    page, out = _build(tmp_path)
    start = page.index('<script type="application/json" id="lean-source">') + len('<script type="application/json" id="lean-source">')
    carried = json.loads(page[start : page.index("</script>", start)])
    assert carried == DEMO
    # the translator loads first (deferred scripts run in order), then the reader
    assert page.index('<script src="../_assets/lean2tex.js" defer></script>') < page.index('<script src="../_assets/reader.js" defer></script>')
    assert (out / "_assets" / "reader.js").read_text(encoding="utf-8") == READER_JS
    assert (out / "_assets" / "lean2tex.js").read_text(encoding="utf-8") == LEAN2TEX_JS
    for rel in set(KATEX["sha256"]) - {"LICENSE"}:  # KaTeX ships with the site, byte for byte, so formulas draw offline
        assert (out / "_assets" / "katex" / rel).read_bytes() == (KATEX_DIR / rel).read_bytes()
    assert "MIT License" in (out / "_assets" / "katex" / "LICENSE.txt").read_text(encoding="utf-8")
    assert "Lean was not run" not in READER_JS
    assert "Any Lean-backed trust result is reported separately on the Trust page" in READER_JS


def test_readings_have_page_level_expand_and_collapse_controls():
    assert 'reader-controls' in READER_JS
    assert 'Expand all readings' in READER_JS
    assert 'Collapse all readings' in READER_JS
    assert 'document.querySelectorAll("details.reading")' in READER_JS
    assert 'document.createElement("details")' in READER_JS
    assert '<summary><strong>Reading guide</strong>' in READER_JS
    assert 'note.querySelector(".reader-note-body").appendChild(controls)' in READER_JS


def test_source_that_contains_a_closing_script_tag_cannot_end_the_block(tmp_path):
    text = DEMO.replace("/-- A doc comment. -/", '/-- see "</script><script>alert(1)</script>" -/')
    page, _ = _build(tmp_path, text)
    assert "<script>alert(1)" not in page
    start = page.index('id="lean-source">') + len('id="lean-source">')
    assert json.loads(page[start : page.index("</script>", start)]) == text


def test_a_tree_too_big_to_publish_twice_points_at_a_pinned_raw_url(tmp_path):
    template = "https://raw.githubusercontent.com/o/r/{ref}/lean/{path}"
    page, out = _build(tmp_path, options=[("reader_source_url", template)])
    assert '<div id="lean-source" hidden></div>' in page
    assert "data-src" not in page
    reader = (out / "_assets" / "reader.js").read_text(encoding="utf-8")
    assert 'const SOURCE_URL_TEMPLATE = "https://raw.githubusercontent.com/o/r/abc123/lean/{path}";' in reader
    assert 'document.querySelector(".path-title")' in reader
    assert 'type="application/json"' not in page
    assert "pinned commit on GitHub" in READER_JS


def test_a_file_over_the_embed_limit_gets_no_reading(tmp_path):
    page, _ = _build(tmp_path, options=[("reader_embed_limit", 10)])
    assert 'id="lean-source"' not in page


# ---- reader.js, run under node --------------------------------------------------------------------------------

def _readings(tmp_path, text, decls, references=None, traces=None):
    """`traces`: {declaration line: [[line, tactic, before, after, source], ...]}, what a Lean run put on the page."""
    script = tmp_path / "reader.cjs"
    script.write_text(READER_JS, encoding="utf-8")
    (tmp_path / "lean2tex.js").write_text(LEAN2TEX_JS, encoding="utf-8")  # reader.js finds the translator next to itself
    driver = tmp_path / "driver.cjs"
    driver.write_text(
        "const R = require(process.argv[2]);\n"
        "const fs = require('fs');\n"
        "const text = fs.readFileSync(process.argv[3], 'utf8');\n"
        "const decls = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));\n"
        "const refs = JSON.parse(fs.readFileSync(process.argv[5], 'utf8'));\n"
        "const traces = process.argv[6] ? new Map(Object.entries(JSON.parse(fs.readFileSync(process.argv[6], 'utf8'))).map(([k, v]) => [Number(k), v])) : undefined;\n"
        "const out = {};\n"
        "for (const [line, html] of R.pageReadings(text, decls, refs, traces)) out[line] = html;\n"
        "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.lean"
    source.write_bytes(text.encode("utf-8"))  # exactly these characters: no newline translation
    listing = tmp_path / "decls.json"
    listing.write_text(json.dumps(decls), encoding="utf-8")
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps(references or []), encoding="utf-8")
    args = [str(NODE), str(driver), str(script), str(source), str(listing), str(refs)]
    if traces is not None:
        trace_file = tmp_path / "traces.json"
        trace_file.write_text(json.dumps(traces, ensure_ascii=False), encoding="utf-8")
        args.append(str(trace_file))
    done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return {int(k): v for k, v in json.loads(done.stdout).items()}


@pytest.fixture
def demo(tmp_path):
    decls = [[line, f"Demo.{name}"] for name, line in LINES.items()]
    return _readings(tmp_path, DEMO, decls)


def _text(html):
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


@needs_node
def test_every_declaration_gets_a_reading(demo):
    assert set(demo) == set(LINES.values())
    assert all(html for html in demo.values())


@needs_node
def test_a_tactic_proof_reads_as_a_claim_assumptions_and_steps(demo):
    text = _text(demo[LINES["two_mul_pos"]])
    assert "It says: 0 is less than 2 * n" in text
    assert "assume hn : 0 is less than n" in text.replace("hn:", "hn :")
    assert "A proof in 2 steps" in text  # have (with its own one-line proof), exact
    assert "Establish an intermediate fact h2" in text
    assert "Do the arithmetic" in text
    assert "Finish: Nat.mul_pos h2 hn is exactly what is needed" in text
    assert "Nat.mul_pos" in text and "mathlib4_docs/find/?pattern=Nat.mul_pos" in demo[LINES["two_mul_pos"]]


@needs_node
def test_induction_bullets_and_calc_are_read_as_structure(demo):
    induction = _text(demo[LINES["double_eq"]])
    assert "A proof by induction" in induction and "Prove it by induction on n" in induction
    assert "Both sides are equal by algebra" in induction
    cases = _text(demo[LINES["odd_or_even"]])
    assert "Case 1:" in cases and "Case 2:" in cases and "Prove the left side" in cases and "Prove the right side" in cases
    assert "Even n , or Odd n" in cases.replace("n,", "n ,") or "n is even, or n is odd" in cases
    chain = _text(demo[LINES["sq_le"]])
    assert "A chain of steps" in chain
    assert "_ ≤ b * b" in chain and "multiplies assumptions together" in chain


@needs_node
def test_definitions_structures_types_and_term_proofs(demo):
    double = _text(demo[LINES["double"]])
    assert "Defines double" in double and "when the input is 0 , the result is 0" in double.replace("0,", "0 ,")
    quantified = _text(demo[LINES["forall_exists"]])
    assert "for every n" in quantified and "there is m such that n is less than m" in quantified
    assert "Built from its parts" in _text(demo[LINES["forall_exists"]]) or "Given n" in quantified
    point = _text(demo[LINES["Point"]])
    assert "A structure Point" in point and "x : a real number" in point.replace("x:", "x :")
    color = _text(demo[LINES["Color"]])
    assert "A new type Color" in color and "red" in color and "green" in color


@needs_node
def test_an_unfinished_proof_says_so(demo):
    text = _text(demo[LINES["unfinished"]])
    assert "This proof is not finished" in text and "Not proved yet" in text
    assert "p is a prime number" in text


@needs_node
def test_names_declared_on_the_page_link_to_their_anchor(demo):
    assert 'href="#L10">double</a>' in demo[LINES["double_eq"]]


@needs_node
def test_resolved_cross_file_references_link_in_the_use_list_and_lean_source(tmp_path):
    name = "MeasureTheory.BoundedCompactSupport.indicator_of_isCompact_closure"
    short = "BoundedCompactSupport.indicator_of_isCompact_closure"
    href = "ToMathlib/BoundedCompactSupport.lean.html#L388"
    text = f"theorem t : True := by\n  exact {short} (memLp_top_const _)\n"
    out = _readings(tmp_path, text, [[1, "t"]], [[name, href]])[1]
    link = f'href="{href}">{short}</a>'
    assert link in out
    assert out.count(link) == 2  # the dependency summary and the exact source occurrence


@needs_node
def test_an_ambiguous_short_reference_is_not_linked_to_the_wrong_declaration(tmp_path):
    text = "theorem t : Foo.item = Bar.item := by\n  exact item\n"
    out = _readings(
        tmp_path,
        text,
        [[1, "t"]],
        [["Foo.item", "Foo.lean.html#L1"], ["Bar.item", "Bar.lean.html#L1"]],
    )[1]
    assert 'href="Foo.lean.html#L1">Foo.item</a>' in out
    assert 'href="Bar.lean.html#L1">Bar.item</a>' in out
    assert '>item</a>' not in out


@needs_node
def test_lean_source_is_escaped_in_the_reading(tmp_path):
    text = 'theorem t : "<b>" = "<b>" := rfl\n'
    out = _readings(tmp_path, text, [[1, "t"]])
    assert "<b>" not in out[1].replace("<b>", "", 0) or "&lt;b&gt;" in out[1]
    assert '"<b>"' not in out[1]


# ---- defects found by running the reader over every declaration of the eight corpora -------------------------

@needs_node
def test_an_escaped_newline_in_a_string_keeps_the_lines_in_step(tmp_path):
    text = 'def s : String := "a' + "\\" + '\nb"\n\ntheorem after : True := trivial\n'  # a backslash, then a line break
    assert text.count("\n") == 4 and "\\\n" in text
    out = _readings(tmp_path, text, [[1, "s"], [4, "after"]])
    assert "It says: always true" in _text(out[4])


@needs_node
def test_a_let_in_a_statement_is_not_mistaken_for_the_proof(tmp_path):
    text = "theorem t (n : ℕ) :\n    let m := n + 1\n    n < m := by\n  simp\n"
    out = _text(_readings(tmp_path, text, [[1, "t"]])[1])
    assert "with m standing for n + 1 , n is less than m" in out.replace("1,", "1 ,")
    assert "Simplify" in out


@needs_node
def test_a_property_written_with_a_dot_reads_as_a_property_of_that_value(tmp_path):
    text = "theorem t : {p : ℕ | p.Prime}.Infinite := sorry\n\ntheorem u (G : SimpleGraph V) : G.IsBipartite := sorry\n"
    out = _readings(tmp_path, text, [[1, "t"], [3, "u"]])
    assert "{p : ℕ | p.Prime} is infinite" in _text(out[1])
    assert "G is bipartite" in _text(out[3])


@needs_node
def test_an_unknown_multi_argument_predicate_is_not_rewritten_as_a_property(tmp_path):
    text = "theorem t : ExistsAME 11 5 := sorry\n"
    rendered = _text(_readings(tmp_path, text, [[1, "t"]])[1])
    assert "ExistsAME(11, 5)" in rendered
    assert "property ExistsAME" not in rendered


@needs_node
def test_induction_arms_and_calc_lines_at_the_calc_indentation(tmp_path):
    text = (
        "theorem t (n : ℕ) : n + 0 = n := by\n"
        "  induction n with\n"
        "  | zero => rfl\n"
        "  | succ k ih => lia\n"
        "\n"
        "theorem c (a b : ℕ) (h : a = b) : a + 0 = b := by\n"
        "  calc a + 0 = a := by simp\n"
        "  _ = b := h\n"
    )
    out = _readings(tmp_path, text, [[1, "t"], [6, "c"]])
    arms = _text(out[1])
    assert "Starting case zero" in arms and "Step case: from k to k + 1" in arms and "called ih" in arms
    assert "lia: linear integer arithmetic" in arms and "Run the tactic" not in arms
    chain = _text(out[6])
    assert "_ = b — by h" in chain and "Run the tactic" not in chain and "A one-step proof" in chain


# ---- mathematics: lean2tex writes LaTeX, KaTeX draws it --------------------------------------------------------

TEX_CASES = {
    # the definition that started it: BallPacking's capacity
    "Real.pi * ∑ j, Complex.normSq (z j)": r"\pi \sum_{j} \lvert z_{j} \rvert^{2}",
    "∑ i ∈ Finset.range (n + 1), i ^ 2 = n * (n + 1) * (2 * n + 1) / 6":
        r"\sum_{i=0}^{n} i^{2} = \frac{n (n + 1) (2 n + 1)}{6}",
    "∀ ε > 0, ∃ δ > 0, ∀ x, |x - a| < δ → |f x - f a| < ε":
        r"\forall \varepsilon > 0,\ \exists \delta > 0,\ \forall x,\ \lvert x - a \rvert < \delta \to \lvert f(x) - f(a) \rvert < \varepsilon",
    "(n.choose k : ℝ) / 2 ^ n": r"\frac{\binom{n}{k}}{2^{n}}",
    "{p : ℕ | p.Prime}": r"\{p \in \mathbb{N} \mid p \text{ prime}\}",
    "∫ x in (0 : ℝ)..1, x ^ 2": r"\int_{0}^{1} x^{2}\, dx",
    "a ≡ b [ZMOD n]": r"a \equiv b \pmod{n}",
    "Real.cos θ ^ 2 + Real.sin θ ^ 2 = 1": r"\cos^{2} \theta + \sin^{2} \theta = 1",
    "‖v - w‖ ≤ ‖v‖ + ‖w‖": r"\lVert v - w \rVert \le \lVert v \rVert + \lVert w \rVert",
    "Real.sqrt (x ^ 2 + y ^ 2)": r"\sqrt{x^{2} + y^{2}}",
    "if x < 0 then -x else x": r"\begin{cases} -x & \text{if } x < 0 \\ x & \text{otherwise} \end{cases}",
    "(∑ j, a j) * 2": r"\left(\sum_{j} a_{j}\right) \cdot 2",
    "a - (b - c)": r"a - (b - c)",
    "(a + b) / (c - d)": r"\frac{a + b}{c - d}",
    "↑n + 1": "n + 1",
    "s.card": r"\lvert s \rvert",
    # notation found by running it over the eight example projects
    "∀ᶠ n : ℕ in atTop, (F n : ℝ) ≤ n ^ 2": r"\text{for all large enough } n,\ F_{n} \le n^{2}",
    "∃ᶠ m in Filter.atTop, m.Prime": r"\text{for infinitely many } m,\ m \text{ prime}",
    "∀ᵐ x ∂volume, f x = 0": r"\text{for almost every } x,\ f(x) = 0",
    "∀ᵉ (c₁ > 0) (c₂ > 0), c₁ * c₂ > 0": r"\forall c_{1} > 0, c_{2} > 0,\ c_{1} c_{2} > 0",
    "∀ (k : ℕ) (hk : 2 ≤ k), 0 < k": r"\forall k \in \mathbb{N}, 2 \le k,\ 0 < k",
    "∃ L : AffineSubspace ℝ ℝ², IsLine L": r"\exists L,\ \operatorname{IsLine}(L)",
    "(fun n : ℕ => (F n : ℝ)) ~[atTop] (fun n : ℕ => (n.choose (n / 2) : ℝ))": r"F_{n} \sim \binom{n}{\frac{n}{2}}",
    "f =O[atTop] fun n ↦ (n : ℝ) ^ 2": r"f = O(n^{2})",
    "(fun n => (H n : ℝ)) ≪ (fun n : ℕ => (n : ℝ) ^ (3 / 2 : ℝ))": r"H_{n} \ll n^{\frac{3}{2}}",
    "answer(sorry) ↔ ∀ n > 1, n.Prime": r"\boxed{\,?\,} \iff \forall n > 1,\ n \text{ prime}",
    "IsGood {p ^ 2 | (p : ℕ) (_ : p.Prime)}": r"\operatorname{IsGood}(\{p^{2} \mid p \in \mathbb{N}, p \text{ prime}\})",
    "(SimpleGraph.completeGraph (Fin 6)).edgeSet.ncard = 15": r"\lvert \operatorname{edgeSet}(\operatorname{completeGraph}(\operatorname{Fin}(6))) \rvert = 15",
    "Tendsto (fun n => 1 / (n : ℝ)) atTop (𝓝 0)": r"\lim_{n \to \infty} \frac{1}{n} = 0",
    "∀ f : ℕ+ → ℕ+, f 1 = 1": r"\forall f \colon \mathbb{N}^{+} \to \mathbb{N}^{+},\ f(1) = 1",
    "let m := n + 1\nn < m": r"n < m \quad \text{where } m = n + 1",
    "x⁻¹ ^ (k + 1)": r"(x^{-1})^{k + 1}",
    # one subscript and one superscript per base (KaTeX rejected these before)
    "(z n).1 + (z n).2": r"{z_{n}}_{1} + {z_{n}}_{2}",
    "g⁻¹⁻¹": r"(g^{-1})^{-1}",
    "hp₀₁": r"\mathrm{hp}_{01}",
    "v₀ n": r"v_{0}(n)",
    "P n k = 2": r"P(n, k) = 2",
    "f (a / b)": r"f\left(\frac{a}{b}\right)",
}
# what it cannot read is left to the Lean code, never guessed
TEX_DECLINES = ["by simp", "match n with | 0 => 1 | _ => 2", "f x y )", "⟨a, b", "let ⟨a, b⟩ := p\na"]


def _node(tmp_path, driver, *args):
    (tmp_path / "lean2tex.cjs").write_text(LEAN2TEX_JS, encoding="utf-8")
    script = tmp_path / "driver.cjs"
    script.write_text(driver, encoding="utf-8")
    done = subprocess.run([str(NODE), str(script), *map(str, args)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


TRANSLATE = (
    "const L = require(require('path').join(__dirname, 'lean2tex.cjs'));\n"
    "const katex = require(process.argv[2]);\n"
    "const cases = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));\n"
    "const out = {};\n"
    "for (const c of cases) {\n"
    "  const tex = L.toTex(c);\n"
    "  let error = null;\n"
    "  if (tex !== null) { try { katex.renderToString(tex, { throwOnError: true, displayMode: true }); } catch (e) { error = e.message; } }\n"
    "  out[c] = [tex, error];\n"
    "}\n"
    "process.stdout.write(JSON.stringify(out));\n"
)


def _translate(tmp_path, cases):
    listing = tmp_path / "cases.json"
    listing.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return _node(tmp_path, TRANSLATE, KATEX_DIR / "katex.min.js", listing)


@needs_node
def test_lean_terms_become_the_usual_mathematical_notation(tmp_path):
    got = _translate(tmp_path, list(TEX_CASES) + TEX_DECLINES)
    for lean, want in TEX_CASES.items():
        assert got[lean][0] == want, lean
        assert got[lean][1] is None, (lean, got[lean][1])  # KaTeX accepts it
    for lean in TEX_DECLINES:
        assert got[lean][0] is None, lean


@needs_node
def test_a_definition_shows_its_value_as_a_formula(tmp_path):
    text = (
        "noncomputable def capacity {n : ℕ} (z : Phase n) : ℝ := Real.pi * ∑ j, Complex.normSq (z j)\n"
        "\n"
        "def square : ℕ → ℕ := fun n => n ^ 2\n"
        "\n"
        "theorem t (n : ℕ) (hn : 0 < n) : 0 < 2 * n := by\n"
        "  omega\n"
    )
    out = _readings(tmp_path, text, [[1, "capacity"], [3, "square"], [5, "t"]])
    assert r'data-tex="\operatorname{capacity}(z) = \pi \sum_{j} \lvert z_{j} \rvert^{2}"' in out[1]
    assert "Apply" not in _text(out[1])  # the old reading: "Apply Real.pi to *, ∑, j,, …"
    assert r'data-tex="\operatorname{square}(n) = n^{2}"' in out[3]
    statement = out[5]
    assert 'class="rd-math" data-tex="0 &lt; 2 n"' in statement  # the statement, displayed
    assert '<span class="m" data-tex="2 n" title="Lean: 2 * n"><code>2 * n</code></span>' in statement  # and inside the words
    assert "It says: 0 is less than 2 * n" in _text(statement)  # the Lean code is the fallback text


# Terms that are not a function applied to arguments. The old reading split each of them at its spaces and said
# "Apply A to ⊆, Finset.Icc, 1, N, ∧, …" (formal-conjectures' Erdős 1, from a user's screenshot); a sweep of all eight
# corpora found 1,615 such readings, in every corpus.
NOT_APPLICATIONS = (
    "def IsSumDistinctSet (A : Finset ℕ) (N : ℕ) : Prop :=\n"  # 1
    "  A ⊆ Finset.Icc 1 N ∧ (fun (⟨S, _⟩ : A.powerset) => S.sum id).Injective\n"
    "\n"
    "def Good : ℕ → Prop := fun n => n.Prime ∧ n % 4 = 1\n"  # 4
    "\n"
    "def seq (n : ℕ) : List ℤ :=\n"  # 6
    "  match n with\n"
    "  | 0 => []\n"
    "  | n + 1 => seq n ++ [k (seq n)]\n"
    "\n"
    "def pick (p : ℕ) : ℕ :=\n"  # 11
    "  if p.Prime then p else 0\n"
    "\n"
    "def total (s : Finset ℕ) : ℕ :=\n"  # 14
    "  open scoped Classical in ∑ i ∈ s, (if i ∈ t then i else 0)\n"
    "\n"
    "def corners : Fin 4 → ℝ × ℝ := ![(0, 0), (1, 0), (1, 1), (0, 1)]\n"  # 17
    "\n"
    "theorem symm' (a b : ℕ) (h : a = b) : b = a :=\n"  # 19
    "  h ▸ rfl\n"
    "\n"
    "theorem step (n : ℕ) : n ≤ n + 1 :=\n"  # 22
    "  Nat.le_of_lt <| Nat.lt_succ_self n\n"
    "\n"
    "theorem sums (f : ℕ → ℝ) : True :=\n"  # 25
    "  not_summable_iff (f := fun m : ℕ => f m) fun _ => le_refl _\n"
    "\n"
    "theorem plain (a b : ℕ) (h : a ≤ b) : a ≤ b + 1 :=\n"  # 28
    "  Nat.le_succ_of_le h\n"
    "\n"
    "theorem either (p : ℕ) : 0 ≤ p :=\n"  # 31
    "  if h : p.Prime then Nat.zero_le p else Nat.zero_le _\n"
    "\n"
    "def tricky (A : Finset ℕ) : ℕ := A.card + (fun (⟨S, _⟩ : A.powerset) => S.card) ⟨∅, by simp⟩\n"  # 34
)


@needs_node
def test_a_term_that_is_not_an_application_is_not_read_as_one(tmp_path):
    lines = {"IsSumDistinctSet": 1, "Good": 4, "seq": 6, "pick": 11, "total": 14, "corners": 17, "symm'": 19, "step": 22, "sums": 25, "plain": 28, "either": 31, "tricky": 34}
    import re

    got = _readings(tmp_path, NOT_APPLICATIONS, [[line, name] for name, line in lines.items()])
    out = {name: _text(re.sub(r"(</[^>]+>)+(?=[.,;:])", "", got[line])) for name, line in lines.items()}  # "<code>N</code>, and" reads "N, and"
    for name in ("IsSumDistinctSet", "Good", "seq", "pick", "total", "corners", "symm'"):
        assert "Apply" not in out[name], (name, out[name])
    # A definition whose value is a statement: what it means, in words, under its name and inputs.
    assert "IsSumDistinctSet A N means: A is a subset of Finset.Icc 1 N, and" in out["IsSumDistinctSet"]
    assert "Good n means:" in out["Good"]
    assert "Its value" not in out["Good"]
    # match and if: case by case.
    assert "Case by case on n: when it is 0, the result is []; when it is n + 1, the result is seq n ++ [k (seq n)]." in out["seq"]
    assert 'class="rd-math" data-tex=' in got[lines["pick"]]  # lean2tex draws this `if` as a formula
    assert "The proof: If p is a prime number, use Nat.zero_le p; otherwise use Nat.zero_le _." in out["either"]
    # `open … in` only scopes names: the reading is of the term after it.
    formula = re.search(r'class="rd-math" data-tex="([^"]*)"', got[lines["total"]])
    assert formula and formula.group(1).startswith(r"\operatorname{total}(s) = ") and "open" not in formula.group(1)
    # A type with a top-level arrow is a function type, whatever its first word: not "a number from 0 up to 4 → ℝ × ℝ − 1".
    assert "Defines corners: a function that takes Fin 4 and gives ℝ × ℝ." in out["corners"]
    # A value lean2tex cannot draw is shown as written.
    assert "Its value: It is A.card + (fun (⟨S, _⟩ : A.powerset) => S.card) ⟨∅, by simp⟩." in out["tricky"]
    assert "The proof: Use rfl, rewritten with h (▸)." in out["symm'"]
    # What follows `<|`, and a `fun` given last, are one argument each.
    assert "The proof: Apply Nat.le_of_lt to Nat.lt_succ_self n." in out["step"]
    assert "The proof: Apply not_summable_iff to (f := fun m : ℕ => f m), fun _ => le_refl _." in out["sums"]
    # An application is still read as one.
    assert "The proof: Apply Nat.le_succ_of_le to h." in out["plain"]


TRACED = (
    "-- a comment\n"  # 1
    "theorem two (a b : ℕ) (h : a = b) : b = a ∧ True := by\n"  # 2
    "  constructor\n"  # 3
    "  · exact h.symm\n"  # 4
    "  · trivial\n"  # 5
    "\n"
    "theorem one : 1 = 1 := by rfl\n"  # 7
    "\n"
    "theorem three (n : ℕ) : n + 0 = n := by\n"  # 9
    "  induction n with\n"  # 10
    "  | zero => rfl\n"  # 11
    "  | succ k ih =>\n"  # 12
    "    simp\n"  # 13
)


@needs_node
def test_each_step_of_a_reading_carries_the_source_line_of_its_tactic(tmp_path):
    # the Lean extension's trace keeps the same line for each step: the two are joined on it in the browser
    import re

    got = _readings(tmp_path, TRACED, [[2, "two"], [7, "one"], [9, "three"]])
    steps = [(int(line), tactic) for html in got.values() for line, tactic in re.findall(r'<li data-line="(\d+)"><code class="rd-tac">([^<]*)</code>', html)]
    assert steps == [(3, "constructor"), (4, "exact h.symm"), (5, "trivial"), (7, "rfl"), (10, "induction n with"), (11, "rfl"), (13, "simp")]
    lines = TRACED.split("\n")
    assert all(tactic.split(" ")[0] in lines[line - 1] for line, tactic in steps)
    assert '<li data-line="4"><span class="rd-case">Case 1:' in got[2]  # cases and arms carry their line too
    assert '<li data-line="12"><span class="rd-case">Step case' in got[9]


@needs_node
def test_a_reading_step_joins_the_trace_step_on_its_line(tmp_path):
    driver = (
        "const R = require(process.argv[2]);\n"
        "const reading = [['10', 'induction n with'], ['11', 'rfl'], ['13', 'simp'], ['20', 'omega']];\n"
        "const trace = [['L9-step1', '10', 'induction n with'], ['L9-step2', '11', '| zero =>'], ['L9-step3', '11', 'rfl'], ['L9-step4', '12', '| succ k ih =>'], ['L9-step5', '13', 'simp']];\n"
        "process.stdout.write(JSON.stringify(R.traceLinks(reading, trace)));\n"
    )
    reader = tmp_path / "reader.cjs"
    reader.write_text(READER_JS, encoding="utf-8")
    assert _node(tmp_path, driver, reader) == ["L9-step1", "L9-step3", "L9-step5", None]  # same line, same tactic first


def test_a_page_with_a_lean_trace_links_readings_to_goals():
    boot = READER_JS[READER_JS.index("function boot() {") :]
    assert 'document.querySelector("details.trace")' in boot  # the note says goals are linked, not "Lean was not run"
    fill = boot[boot.index("const fill = () => {") :]
    assert "linkTrace(li)" in fill[: fill.index("};")]  # a lazily filled reading links when it is filled


def test_a_reading_filled_at_once_is_in_its_declaration_before_it_links_to_the_trace():
    # found in Edge, 2026-10-10: on a page of 40 or fewer declarations the reading was filled (and linkTrace looked for
    # its steps inside the declaration) before it was put in the declaration, so no step got a "goals" link
    boot = READER_JS[READER_JS.index("function boot() {") :]
    assert boot.index("li.insertBefore(box") < boot.index("if (eager) { fill();")


def test_on_a_long_page_opening_a_trace_fills_its_reading_so_the_steps_link_back():
    # more than 40 declarations: readings fill when opened. A trace opened first must still get its "in words" links,
    # so opening it fills the reading too (left closed); "in words" then opens the reading at that step.
    boot = READER_JS[READER_JS.index("function boot() {") :]
    lazy = boot[boot.index("if (eager)") :]
    lazy = lazy[: lazy.index("\n")]
    assert 'box.addEventListener("toggle", fill)' in lazy
    assert 'trace.addEventListener("toggle", fill)' in boot


@needs_node
def test_every_formula_on_the_demo_page_parses_in_katex(tmp_path, demo):
    import html
    import re

    formulas = sorted({html.unescape(t) for reading in demo.values() for t in re.findall(r'data-tex="([^"]*)"', reading)})
    assert len(formulas) >= 10
    listing = tmp_path / "tex.json"
    listing.write_text(json.dumps(formulas, ensure_ascii=False), encoding="utf-8")
    errors = _node(
        tmp_path,
        "const katex = require(process.argv[2]);\n"
        "const all = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));\n"
        "const bad = {};\n"
        "for (const t of all) { try { katex.renderToString(t, { throwOnError: true }); } catch (e) { bad[t] = e.message; } }\n"
        "process.stdout.write(JSON.stringify(bad));\n",
        KATEX_DIR / "katex.min.js",
        listing,
    )
    assert errors == {}


@needs_node
def test_a_calc_chain_leaves_the_carried_side_blank(tmp_path):
    text = "theorem c (a b : ℕ) (h : a = b) : a + 0 = b := by\n  calc a + 0 = a := by simp\n  _ = b := h\n"
    out = _readings(tmp_path, text, [[1, "c"]])[1]
    assert 'data-tex="= b"' in out and 'data-tex="a + 0 = a"' in out


@needs_node
def test_unclosed_brackets_give_up_instead_of_hanging(tmp_path):
    # found by the corpus sweep: `∀ (a, b` with no `)` looped forever reading past the end
    broken = ["∀ (a, b", "∑ (i, j", "{x : ℕ | (a, b", "fun (x, y", "∃ ⟨a, b", "((((((((((", "{{{{{{{{{{{{{{{{{{{{{{{{a"]
    (tmp_path / "lean2tex.cjs").write_text(LEAN2TEX_JS, encoding="utf-8")
    driver = tmp_path / "broken.cjs"
    driver.write_text(
        "const L = require(require('path').join(__dirname, 'lean2tex.cjs'));\n"
        f"process.stdout.write(JSON.stringify({json.dumps(broken, ensure_ascii=False)}.map((s) => L.toTex(s))));\n",
        encoding="utf-8",
    )
    done = subprocess.run([str(NODE), str(driver)], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [None] * len(broken)


def test_the_vendored_katex_is_the_published_release():
    import hashlib

    assert KATEX["name"] == "katex" and KATEX["license"] == "MIT"
    assert set(KATEX["sha256"]) == {p.relative_to(KATEX_DIR).as_posix() for p in KATEX_DIR.rglob("*") if p.is_file()} - {"VENDOR.json"}
    for rel, digest in KATEX["sha256"].items():
        assert hashlib.sha256((KATEX_DIR / rel).read_bytes()).hexdigest() == digest, rel


# ---------------------------------------------------------------- the reader's words in the glossary
VOCABULARY_FILE = Path(__file__).resolve().parents[1] / "src" / "lean4_explainer_reader" / "vocabulary.json"
GENERATOR = Path(__file__).resolve().parents[1] / "tools" / "vocabulary.cjs"
READER_FILE = Path(__file__).resolve().parents[1] / "src" / "lean4_explainer_reader" / "reader.js"


@needs_node
def test_explanatory_lean_applications_use_conventional_function_notation(tmp_path):
    driver = (
        "const R = require(process.argv[2]);\n"
        "const cases = JSON.parse(process.argv[3]);\n"
        "process.stdout.write(JSON.stringify(cases.map((x) => R.proseApplicationText(x))));\n"
    )
    cases = [
        "Fin r",
        "Monomial r",
        "h_seq m d",
        "f (a + b)",
        "Nat.fib n",
        "Fin r →₀ ℕ",
        "r = 3",
        "A ∈ s",
        "Monomial",
    ]
    assert _node(tmp_path, driver, READER_FILE, json.dumps(cases, ensure_ascii=False)) == [
        "Fin(r)",
        "Monomial(r)",
        "h_seq(m, d)",
        "f(a + b)",
        "Nat.fib(n)",
        None,
        None,
        None,
        None,
    ]


def test_application_presentation_is_confined_to_explanatory_prose():
    assert '".doc code", ".title code", ".intuition code", ".steps code", ".l4term code"' in READER_JS
    assert 'el.closest("pre")' in READER_JS
    assert 'el.closest(".l4del-quote")' in READER_JS
    assert 'el.title = "Lean syntax: " + source' in READER_JS


@needs_node
def test_application_presentation_mutates_only_the_explanatory_elements(tmp_path):
    driver = r"""
const R = require(process.argv[2]);
function element(text, blocked) {
  return {
    textContent: text,
    title: "",
    classes: [],
    classList: { add(name) { this.owner.classes.push(name); }, owner: null },
    closest(selector) { return blocked.includes(selector) ? {} : null; }
  };
}
const rows = [
  element("Fin r", []),
  element("h_seq m d", []),
  element("Fin r →₀ ℕ", []),
  element("f x", ["pre"]),
  element("g y", [".l4del-quote"])
];
for (const row of rows) row.classList.owner = row;
R.drawProseApplications({ querySelectorAll() { return rows; } });
process.stdout.write(JSON.stringify(rows.map((row) => [row.textContent, row.title, row.classes])));
"""
    assert _node(tmp_path, driver, READER_FILE) == [
        ["Fin(r)", "Lean syntax: Fin r", ["prose-application"]],
        ["h_seq(m, d)", "Lean syntax: h_seq m d", ["prose-application"]],
        ["Fin r →₀ ℕ", "", []],
        ["f x", "", []],
        ["g y", "", []],
    ]


def _glossary_section(html, key):
    import re

    match = re.search(rf'<h2 id="g-{key}">(.*?)(?=<h2 |</main>)', html, re.S)
    assert match, key
    return match.group(1)


def test_the_glossary_lists_the_words_the_reader_explains(tmp_path):
    _, out = _build(tmp_path)
    html = (out / "glossary.html").read_text(encoding="utf-8")
    tactics = _glossary_section(html, "reader-tactics")
    assert '<dt id="r-tactics-rw">rw</dt><dd><code>rw [h]</code> — Rewrite using <code>h</code>.</dd>' in tactics
    # with no argument the general meaning reads best, and an example would only repeat the word
    assert "<dt id=\"r-tactics-simp\">simp</dt><dd>Simplify with Lean's standard simplification rules.</dd>" in tactics
    properties = _glossary_section(html, "reader-properties")
    assert "<code>Injective f</code> — <code>f</code> is injective: different inputs always give different outputs" in properties
    assert "ℕ, Nat" in _glossary_section(html, "reader-types")
    assert "<code>[Field K]</code> — <code>K</code> is a field" in _glossary_section(html, "reader-classes")
    assert "the norm (length) of x" in _glossary_section(html, "reader-symbols")


def test_the_vocabulary_uses_only_plain_markup_and_unique_anchors():
    import re

    data = json.loads(VOCABULARY_FILE.read_text(encoding="utf-8"))
    anchors = [e["anchor"] for s in data["sections"] for e in s["entries"]]
    assert len(anchors) == len(set(anchors))
    for section in data["sections"]:
        assert section["entries"], section["key"]
        for entry in section["entries"]:
            tags = re.findall(r"<(/?)([a-z]+)([^>]*)>", entry["meaning"])
            assert {name for _, name, _ in tags} <= {"code", "strong", "em"}, entry
            assert all(not attrs for _, _, attrs in tags), entry
            assert not re.search(r"<code></code>|<code>\?</code>|undefined|NaN", entry["meaning"]), entry


@needs_node
def test_the_vocabulary_is_generated_from_reader_js_and_covers_every_table(tmp_path):
    done = subprocess.run([str(NODE), str(GENERATOR)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    fresh = json.loads(done.stdout)
    # the committed file is what the generator makes from the current reader.js: regenerate it after changing a table
    assert fresh == json.loads(VOCABULARY_FILE.read_text(encoding="utf-8"))
    # every entry of every table has a glossary entry
    count = tmp_path / "count.cjs"
    count.write_text(
        f"const R = require({json.dumps(str(READER_FILE))});\n"
        "const t = R.tables;\n"
        "process.stdout.write(JSON.stringify({classes: Object.keys(t.CLASSES), properties: Object.keys(t.PREDICATES),\n"
        "  tactics: Object.keys(t.TACTICS), symbols: t.SYMBOLS.map((s) => s[1]), types: Object.keys(t.TYPES), forms: t.TYPE_FORMS.length}));\n",
        encoding="utf-8",
    )
    done = subprocess.run([str(NODE), str(count)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    tables = json.loads(done.stdout)
    terms = {s["key"]: [e["term"] for e in s["entries"]] for s in fresh["sections"]}
    assert sorted(terms["reader-classes"]) == sorted(tables["classes"])
    assert sorted(terms["reader-properties"]) == sorted(tables["properties"])
    assert sorted(terms["reader-tactics"]) == sorted(tables["tactics"])
    assert sorted(terms["reader-symbols"]) == sorted(tables["symbols"])
    listed_types = {name for term in terms["reader-types"] for name in term.split(", ")}
    assert set(tables["types"]) <= listed_types
    assert len(fresh["forms"]) == tables["forms"]  # each TYPE_FORMS pattern was matched by a sample


DOC_TEX = (
    "const R = require(process.argv[2]);\n"
    "const katex = require(process.argv[3]);\n"
    "const cases = JSON.parse(require('fs').readFileSync(process.argv[4], 'utf8'));\n"
    "const out = {};\n"
    "for (const tex of cases) {\n"
    "  let plain = null, drawn = null, error = null;\n"
    "  try { plain = katex.renderToString(tex, { throwOnError: true, strict: 'ignore' }); } catch (e) { plain = null; }\n"
    "  try { drawn = R.docTex(katex, tex, false); } catch (e) { error = e.message; }\n"
    "  out[tex] = [plain, drawn, error];\n"
    "}\n"
    "process.stdout.write(JSON.stringify(out));\n"
)


def _doc_tex(tmp_path, reader_js, cases):
    (tmp_path / "reader.cjs").write_text(reader_js, encoding="utf-8")
    (tmp_path / "lean2tex.js").write_text(LEAN2TEX_JS, encoding="utf-8")
    listing = tmp_path / "doc-cases.json"
    listing.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return _node(tmp_path, DOC_TEX, tmp_path / "reader.cjs", KATEX_DIR / "katex.min.js", listing)


@needs_node
def test_doc_tex_draws_what_tex_takes_and_katex_alone_does_not(tmp_path):
    # each of these stayed raw in the doc comment sweep over the pinned projects (formal-conjectures, Erdős problems)
    repaired = [
        r"f_\max(n)",  # 694.lean: a command as a subscript
        r"\max_{n\leq x}\frac{f_\max(n)}{f_\min(n)}",
        r"\omega\sp{\omega }",  # 590.lean: plain TeX's \sp and \sb
        r"B\sb{2}",
        r"p_n\\# + m",  # FortuneConjecture.lean: a Markdown escape left in the TeX
        r"w \in \Sigma^\*",  # CernyConjecture.lean
    ]
    broken = [r"2K^{11", r"\mathbb^2", r"n!\pmd m!=x^p"]  # the author's TeX is wrong: it stays as written
    valid = [r"\begin{aligned} a &= b \\ c &= d \end{aligned}", r"\{1, \dots, N\}", r"x^\alpha_\beta"]
    got = _doc_tex(tmp_path, READER_JS, repaired + broken + valid)
    for tex in repaired:
        plain, drawn, error = got[tex]
        assert plain is None and drawn and error is None, tex
    for tex in broken:
        assert got[tex][1] is None and got[tex][2], tex
    for tex in valid:  # TeX that KaTeX takes as written is drawn exactly as written
        plain, drawn, error = got[tex]
        assert drawn == plain and plain, tex


def test_the_reader_typesets_the_formulas_the_core_marks():
    draw = READER_JS[READER_JS.index("function drawDocs(root) {") :]
    draw = draw[: draw.index("\n  }\n") + 4]
    assert 'querySelectorAll(".tex:not(.m)")' in draw and "data-doc" in draw and "typeset(root)" in draw
    assert "docPieces" not in READER_JS  # the core finds the formulas now: one dollar rule, in one place


@needs_node
def test_doc_formula_accepts_dollar_and_latex_delimiters(tmp_path):
    driver = (
        "const R = require(process.argv[2]);\n"
        "const cases = JSON.parse(process.argv[3]);\n"
        "process.stdout.write(JSON.stringify(cases.map((x) => R.docFormula(x))));\n"
    )
    assert _node(
        tmp_path,
        driver,
        READER_FILE,
        json.dumps(["$x$", "$$x$$", r"\(x\)", r"\[x\]", r"\[unclosed"]),
    ) == [
        {"display": False, "tex": "x"},
        {"display": True, "tex": "x"},
        {"display": False, "tex": "x"},
        {"display": True, "tex": "x"},
        None,
    ]


BLUEPRINT = r"""
% comment: \newcommand{\ignored}{x}
\newcommand{\bbH}{\mathbb{H}}
\newcommand*{\bbI}{\mathbb{I}}
\newcommand{\abs}[1]{\left\lvert #1\right\rvert}
\renewcommand\epsilon{\varepsilon}
\DeclareMathOperator{\dist}{dist}
\DeclareMathOperator*{\argmax}{arg\,max}
\def\pair#1#2{\langle #1, #2\rangle}
\newcommand{\opt}[2][x]{#1 + #2}
\newcommand{\pct}{50\%}
\providecommand{\bbH}{\mathbb{W}}
\newcommand{\inner}{\makeatletter\foo@bar}
"""


def test_blueprint_macros_are_read_as_katex_takes_them():
    from lean4_explainer_reader.macros import parse_macros

    assert parse_macros(BLUEPRINT) == {
        r"\bbH": r"\mathbb{H}",
        r"\bbI": r"\mathbb{I}",
        r"\abs": r"\left\lvert #1\right\rvert",
        r"\epsilon": r"\varepsilon",
        r"\dist": r"\operatorname{dist}",
        r"\argmax": r"\operatorname*{arg\,max}",
        r"\pair": r"\langle #1, #2\rangle",
        r"\pct": r"50\%",
    }  # no \ignored (a comment), no \opt (an optional argument), \providecommand keeps the first, no internals


@needs_node
def test_a_site_typesets_doc_tex_with_its_blueprints_macros(tmp_path):
    src = tmp_path / "proj"
    (src / "blueprint" / "src" / "macros").mkdir(parents=True)
    (src / "blueprint" / "src" / "macros" / "common.tex").write_text(BLUEPRINT, encoding="utf-8")
    (src / "blueprint" / "src" / "macros" / "web.tex").write_text(r"\newcommand{\bbI}{\mathbf{I}}", encoding="utf-8")
    (src / "Ent.lean").write_text("/-- Entropy $\\bbH[X] - \\bbI[X : Y] \\le \\abs{x}$. -/\ndef ent : Nat := 1\n", encoding="utf-8")
    summary = build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    assert not summary.errors
    page = (tmp_path / "out" / "Ent.lean.html").read_text(encoding="utf-8")
    assert '<span class="tex">$\\bbH[X] - \\bbI[X : Y] \\le \\abs{x}$</span>' in page
    written = (tmp_path / "out" / "_assets" / "reader.js").read_text(encoding="utf-8")
    assert '"\\\\bbI": "\\\\mathbf{I}"' in written  # web.tex has the last word
    got = _doc_tex(tmp_path, written, [r"\bbH[X] - \bbI[X : Y] \le \abs{x}", r"\dist(x, y)"])
    for tex, (_plain, drawn, error) in got.items():
        assert drawn and error is None, (tex, error)
    assert "mathbf" in got[r"\bbH[X] - \bbI[X : Y] \le \abs{x}"][1]  # web.tex's \bbI: drawn bold
    # off by config: the site's reader.js has no project macros
    off = build_site(src, tmp_path / "off", Config(options=(("reader_blueprint_macros", False),)), tmp_path / "idx2", jobs=1)
    assert not off.errors
    assert "const PROJECT_MACROS = {};" in (tmp_path / "off" / "_assets" / "reader.js").read_text(encoding="utf-8")


def test_the_reader_draws_doc_text_on_every_page_it_loads_on():
    # the glossary has no source to read, so drawing the docs must not wait for one
    boot = READER_JS[READER_JS.index("function boot() {") :]
    assert boot.index("drawDocs(document)") < boot.index('document.getElementById("lean-source")')


# ---- readings derived from the goals Lean reports ----------------------------------------------------------------
# tests/data/demo-goals.lean was run through the lean extension's probe with Lean 4.35.0; the trace is what that
# extension puts on the page ({"v": 1, "d": {"<declaration line>:<name>": [[line, tactic, goals before, goals after, href]]}}).
# A step's words are read off how its goals change. Where no Lean step matches, the words come from the tactic's text,
# and the step says so.
DATA = Path(__file__).with_name("data")
GOALS_LEAN = (DATA / "demo-goals.lean").read_text(encoding="utf-8")
GOALS_TRACE = json.loads((DATA / "demo-goals.lean-4.35.0.trace.json").read_text(encoding="utf-8"))["d"]
GOAL_DECLS = [[1, "and_swap'"], [6, "add_zero_comm"], [13, "imp_chain"], [18, "or_comm'"], [24, "has_step"]]


def _by_line(trace):
    return {int(key.split(":", 1)[0]): steps for key, steps in trace.items()}


@pytest.fixture
def goals(tmp_path):
    return _readings(tmp_path, GOALS_LEAN, GOAL_DECLS, traces=_by_line(GOALS_TRACE))


def _prose(html):
    """_text, with the space a removed tag leaves before , . ; ? ! ) and after ( closed up (a colon keeps its spaces: `h : p`)."""
    import re

    return re.sub(r"\(\s+", "(", re.sub(r"\s+([,.;?!)])", r"\1", _text(html)))


def _step_text(html, line):
    """The words of the reading step on a source line (up to the next step), tags removed."""
    import re

    (found,) = re.findall(r'<li data-line="%d"[^>]*>(.*?)(?=<li data-line=|</ol>)' % line, html, flags=re.S)
    return _prose(found)


@needs_node
def test_a_step_is_read_from_how_the_goals_lean_reports_change(goals):
    imp = goals[13]
    assert "Introduces hpq : p → q, hqr : q → r and hp : p" in _step_text(imp, 14)
    assert "The goal becomes r" in _step_text(imp, 14)
    assert "The goal becomes q" in _step_text(imp, 15)  # apply hqr: r is shown by showing q
    assert "Closes the goal" in _step_text(imp, 16)
    rewrite = _step_text(goals[6], 10)
    assert "ih becomes 0 + k = k" in rewrite and "The goal becomes 0 + (k + 1) = k + 1" in rewrite
    have = _step_text(goals[24], 25)
    assert "Introduces h2 : b < b + 1" in have and "The goal does not change" in have


@needs_node
def test_a_step_that_splits_the_goal_says_what_each_goal_is(goals):
    split = _step_text(goals[1], 2)
    assert "Splits the goal into 2 goals" in split
    assert "left : q" in split and "right : p" in split


@needs_node
def test_a_bullet_names_the_goal_it_works_on_and_a_block_the_goal_it_starts_from(goals):
    assert "Case 1 (left, to show q)" in _prose(goals[1])
    assert "Works on the goal 0 + n = n + 0" in _step_text(goals[6], 7)  # induction: its alternatives are its sub-steps


@needs_node
def test_each_step_says_where_its_words_come_from(goals):
    html = goals[13]
    assert html.count('data-basis="goals"') == 3  # all three tactics have a Lean step
    assert 'class="rd-how"' in html  # the tactic's own words stay beside the goals, as the how
    assert 'data-basis="source"' not in html


@needs_node
def test_a_tactic_that_differs_from_the_traced_one_on_its_line_is_not_given_its_goals(tmp_path):
    other = {key: [list(step) for step in steps] for key, steps in GOALS_TRACE.items()}
    other["13:imp_chain"][0][1] = "simp"  # Lean's step on line 14 is not the `intro` the reading reads there
    got = _readings(tmp_path, GOALS_LEAN, GOAL_DECLS, traces=_by_line(other))
    intro = _step_text(got[13], 14)
    assert "Introduces" not in intro and "goal becomes" not in intro
    assert 'data-line="14" data-basis="source"' in got[13]
    assert 'data-line="15" data-basis="goals"' in got[13]  # its neighbours keep theirs


@needs_node
def test_without_a_trace_a_reading_makes_no_claim_about_goals(tmp_path):
    got = _readings(tmp_path, GOALS_LEAN, GOAL_DECLS)
    for html in got.values():
        assert "data-basis" not in html and "rd-fact" not in html


@needs_node
def test_a_declaration_without_a_trace_entry_is_read_from_source_and_says_so(tmp_path):
    only = _by_line({key: steps for key, steps in GOALS_TRACE.items() if key.startswith("13:")})
    got = _readings(tmp_path, GOALS_LEAN, GOAL_DECLS, traces=only)
    assert 'data-basis="goals"' in got[13]
    assert 'data-basis="source"' in got[18] and 'data-basis="goals"' not in got[18]


@needs_node
def test_the_note_says_which_kind_of_reading_the_page_has(tmp_path):
    driver = (
        "const R = require(process.argv[2]);\n"
        "const out = {};\n"
        "out.source = R.readingNote('source', {});\n"
        "out.goals = R.readingNote('goals', {derived: 12, total: 15, fetched: true});\n"
        "out.failed = R.readingNote('failed', {reason: 'HTTP 404', fetched: false});\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    reader = tmp_path / "reader.cjs"
    reader.write_text(READER_JS, encoding="utf-8")
    note = _node(tmp_path, driver, reader)
    assert "derived from source text" in note["source"] and "does not reconstruct Lean's intermediate goals" in note["source"]
    assert "does not reconstruct" not in note["goals"] and "12 of 15 steps" in note["goals"]
    assert "goals Lean reports" in note["goals"]
    assert "could not be loaded" in note["failed"] and "HTTP 404" in note["failed"] and "source text" in note["failed"]
    assert "does not reconstruct" not in note["failed"]  # it did run Lean; saying it did not would be wrong the other way


@needs_node
def test_a_reading_can_link_to_goals_before_the_trace_is_drawn(tmp_path):
    # trace.js draws a trace when it is opened, and numbers its steps L<declaration line>-step<k> in the order of the data
    # (packages/lean tests pin that numbering). So the reader works the ids out from the data it already holds, instead of
    # waiting for the page to draw them: a trace opened later left every "goals" and "in words" link missing.
    driver = (
        "const R = require(process.argv[2]);\n"
        "const steps = [[14, 'intro hpq hqr hp', [], [], ''], [15, 'apply hqr', [], [], ''], [16, 'exact hpq hp', [], [], '']];\n"
        "const memory = R.memoryTrace(13, steps);\n"
        "const reading = [['15', 'apply hqr'], ['16', 'exact hpq hp'], ['17', 'omega']];\n"
        "process.stdout.write(JSON.stringify([memory, R.traceLinks(reading, memory)]));\n"
    )
    reader = tmp_path / "reader.cjs"
    reader.write_text(READER_JS, encoding="utf-8")
    memory, links = _node(tmp_path, driver, reader)
    assert memory == [["L13-step1", "14", "intro hpq hqr hp"], ["L13-step2", "15", "apply hqr"], ["L13-step3", "16", "exact hpq hp"]]
    assert links == ["L13-step2", "L13-step3", None]


def test_links_are_made_again_when_a_trace_that_was_opened_later_has_been_drawn():
    boot = READER_JS[READER_JS.index("function boot() {") :]
    assert 'attributeFilter: ["data-trace-state"]' in boot  # trace.js sets data-trace-state=loaded once its steps are drawn
    link = READER_JS[READER_JS.index("function linkTrace(li) {") : READER_JS.index("function readingNote(")]
    assert "traceMemory.get(li.id)" in link  # without a drawn trace, the links come from the data
    assert "e.preventDefault()" in link and "whenDrawn(" in link  # a "goals" link opens the trace and scrolls once it is drawn
