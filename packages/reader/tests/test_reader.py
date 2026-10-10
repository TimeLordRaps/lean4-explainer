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
    assert "Lean was not run" in READER_JS  # the note is written by the script, so pages stay small


def test_source_that_contains_a_closing_script_tag_cannot_end_the_block(tmp_path):
    text = DEMO.replace("/-- A doc comment. -/", '/-- see "</script><script>alert(1)</script>" -/')
    page, _ = _build(tmp_path, text)
    assert "<script>alert(1)" not in page
    start = page.index('id="lean-source">') + len('id="lean-source">')
    assert json.loads(page[start : page.index("</script>", start)]) == text


def test_a_tree_too_big_to_publish_twice_points_at_a_pinned_raw_url(tmp_path):
    template = "https://raw.githubusercontent.com/o/r/{ref}/lean/{path}"
    page, _ = _build(tmp_path, options=[("reader_source_url", template)])
    assert 'data-src="https://raw.githubusercontent.com/o/r/abc123/lean/Demo/Basic.lean"' in page
    assert 'type="application/json"' not in page
    assert "pinned commit on GitHub" in READER_JS


def test_a_file_over_the_embed_limit_gets_no_reading(tmp_path):
    page, _ = _build(tmp_path, options=[("reader_embed_limit", 10)])
    assert 'id="lean-source"' not in page


# ---- reader.js, run under node --------------------------------------------------------------------------------

def _readings(tmp_path, text, decls):
    script = tmp_path / "reader.cjs"
    script.write_text(READER_JS, encoding="utf-8")
    (tmp_path / "lean2tex.js").write_text(LEAN2TEX_JS, encoding="utf-8")  # reader.js finds the translator next to itself
    driver = tmp_path / "driver.cjs"
    driver.write_text(
        "const R = require(process.argv[2]);\n"
        "const fs = require('fs');\n"
        "const text = fs.readFileSync(process.argv[3], 'utf8');\n"
        "const decls = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));\n"
        "const out = {};\n"
        "for (const [line, html] of R.pageReadings(text, decls)) out[line] = html;\n"
        "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.lean"
    source.write_bytes(text.encode("utf-8"))  # exactly these characters: no newline translation
    listing = tmp_path / "decls.json"
    listing.write_text(json.dumps(decls), encoding="utf-8")
    done = subprocess.run([str(NODE), str(driver), str(script), str(source), str(listing)], capture_output=True, text=True, encoding="utf-8", timeout=60)
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
        r"\sum_{i=0}^{n} i^{2} = \frac{n \left(n + 1\right) \left(2 n + 1\right)}{6}",
    "∀ ε > 0, ∃ δ > 0, ∀ x, |x - a| < δ → |f x - f a| < ε":
        r"\forall \varepsilon > 0,\ \exists \delta > 0,\ \forall x,\ \lvert x - a \rvert < \delta \to \lvert f\left(x\right) - f\left(a\right) \rvert < \varepsilon",
    "(n.choose k : ℝ) / 2 ^ n": r"\frac{\binom{n}{k}}{2^{n}}",
    "{p : ℕ | p.Prime}": r"\{p \in \mathbb{N} \mid p \text{ prime}\}",
    "∫ x in (0 : ℝ)..1, x ^ 2": r"\int_{0}^{1} x^{2}\, dx",
    "a ≡ b [ZMOD n]": r"a \equiv b \pmod{n}",
    "Real.cos θ ^ 2 + Real.sin θ ^ 2 = 1": r"\cos^{2} \theta + \sin^{2} \theta = 1",
    "‖v - w‖ ≤ ‖v‖ + ‖w‖": r"\lVert v - w \rVert \le \lVert v \rVert + \lVert w \rVert",
    "Real.sqrt (x ^ 2 + y ^ 2)": r"\sqrt{x^{2} + y^{2}}",
    "if x < 0 then -x else x": r"\begin{cases} -x & \text{if } x < 0 \\ x & \text{otherwise} \end{cases}",
    "(∑ j, a j) * 2": r"\left(\sum_{j} a_{j}\right) \cdot 2",
    "a - (b - c)": r"a - \left(b - c\right)",
    "(a + b) / (c - d)": r"\frac{a + b}{c - d}",
    "↑n + 1": "n + 1",
    "s.card": r"\lvert s \rvert",
    # notation found by running it over the eight example projects
    "∀ᶠ n : ℕ in atTop, (F n : ℝ) ≤ n ^ 2": r"\text{for all large enough } n,\ F_{n} \le n^{2}",
    "∃ᶠ m in Filter.atTop, m.Prime": r"\text{for infinitely many } m,\ m \text{ prime}",
    "∀ᵐ x ∂volume, f x = 0": r"\text{for almost every } x,\ f\left(x\right) = 0",
    "∀ᵉ (c₁ > 0) (c₂ > 0), c₁ * c₂ > 0": r"\forall c_{1} > 0, c_{2} > 0,\ c_{1} c_{2} > 0",
    "∀ (k : ℕ) (hk : 2 ≤ k), 0 < k": r"\forall k \in \mathbb{N}, 2 \le k,\ 0 < k",
    "∃ L : AffineSubspace ℝ ℝ², IsLine L": r"\exists L,\ \operatorname{IsLine}\left(L\right)",
    "(fun n : ℕ => (F n : ℝ)) ~[atTop] (fun n : ℕ => (n.choose (n / 2) : ℝ))": r"F_{n} \sim \binom{n}{\frac{n}{2}}",
    "f =O[atTop] fun n ↦ (n : ℝ) ^ 2": r"f = O\left(n^{2}\right)",
    "(fun n => (H n : ℝ)) ≪ (fun n : ℕ => (n : ℝ) ^ (3 / 2 : ℝ))": r"H_{n} \ll n^{\frac{3}{2}}",
    "answer(sorry) ↔ ∀ n > 1, n.Prime": r"\boxed{\,?\,} \iff \forall n > 1,\ n \text{ prime}",
    "IsGood {p ^ 2 | (p : ℕ) (_ : p.Prime)}": r"\operatorname{IsGood}\left(\{p^{2} \mid p \in \mathbb{N}, p \text{ prime}\}\right)",
    "(SimpleGraph.completeGraph (Fin 6)).edgeSet.ncard = 15": r"\lvert \operatorname{edgeSet}\left(\operatorname{completeGraph}\left(\operatorname{Fin}\left(6\right)\right)\right) \rvert = 15",
    "Tendsto (fun n => 1 / (n : ℝ)) atTop (𝓝 0)": r"\lim_{n \to \infty} \frac{1}{n} = 0",
    "∀ f : ℕ+ → ℕ+, f 1 = 1": r"\forall f \colon \mathbb{N}^{+} \to \mathbb{N}^{+},\ f\left(1\right) = 1",
    "let m := n + 1\nn < m": r"n < m \quad \text{where } m = n + 1",
    "x⁻¹ ^ (k + 1)": r"\left(x^{-1}\right)^{k + 1}",
    # one subscript and one superscript per base (KaTeX rejected these before)
    "(z n).1 + (z n).2": r"{z_{n}}_{1} + {z_{n}}_{2}",
    "g⁻¹⁻¹": r"\left(g^{-1}\right)^{-1}",
    "hp₀₁": r"\mathrm{hp}_{01}",
    "v₀ n": r"v_{0}\left(n\right)",
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
    assert r'data-tex="\operatorname{capacity}\left(z\right) = \pi \sum_{j} \lvert z_{j} \rvert^{2}"' in out[1]
    assert "Apply" not in _text(out[1])  # the old reading: "Apply Real.pi to *, ∑, j,, …"
    assert r'data-tex="\operatorname{square}\left(n\right) = n^{2}"' in out[3]
    statement = out[5]
    assert 'class="rd-math" data-tex="0 &lt; 2 n"' in statement  # the statement, displayed
    assert '<span class="m" data-tex="2 n" title="Lean: 2 * n"><code>2 * n</code></span>' in statement  # and inside the words
    assert "It says: 0 is less than 2 * n" in _text(statement)  # the Lean code is the fallback text


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
