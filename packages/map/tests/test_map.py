"""The map: who uses whom, read from the code, and the drawings built from it."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lean4_explainer import extensions
from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer_map import MapExtension
from lean4_explainer_map.deps import Resolver, bound_in, candidates, imports_in, names_in, opens_in, variables_in, visible_files
from lean4_explainer_map.extension import MAP_JS

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
HERE = Path(__file__).parent

BASE = """\
namespace Demo

def base : ℕ := 1

-- `top` is only named in this comment, so it is no use of `top`
theorem base_pos : 0 < base := by
  unfold base
  norm_num

end Demo
"""

TOP = """\
import Demo.Base

open Demo

namespace Demo.More

def middle : ℕ := base + 1

theorem top : 0 < middle := by
  have := base_pos
  unfold middle
  omega

/-- A string mentioning "middle" is not a use. -/
def lonely : String := "middle"

end Demo.More
"""


@pytest.fixture(autouse=True)
def only_map():
    extensions.activate([MapExtension()])
    yield
    extensions.activate(None)


def _build(tmp_path, options=()):
    src = tmp_path / "src"
    (src / "Demo").mkdir(parents=True)
    (src / "Demo" / "Base.lean").write_text(BASE, encoding="utf-8")
    (src / "Demo" / "More.lean").write_text(TOP, encoding="utf-8")
    summary = build_site(src, tmp_path / "out", Config(options=tuple(options)), tmp_path / "idx", jobs=1)
    return summary, tmp_path / "out"


def _data(page, element="map-data"):
    start = page.index(f'<script type="application/json" id="{element}">') + len(f'<script type="application/json" id="{element}">')
    return json.loads(page[start : page.index("</script>", start)])


def _edges(data):
    """{line: {(user-name, target-name), ...}} as drawn: arrows go from what is used to what uses it."""
    found = {}
    for line, _here, flat, *_ in data["d"]:
        found[line] = {(data["n"][flat[i]][0], data["n"][flat[i + 1]][0], flat[i + 2]) for i in range(0, len(flat), 3)}
    return found


# ---- reading names ---------------------------------------------------------------------------------------------

def test_names_are_read_without_keywords_or_tactics():
    found = names_in("theorem top : 0 < middle := by\n  have := Demo.base_pos\n  unfold middle\n  exact @Nat.le_refl _")
    assert found == ("top", "middle", "Demo.base_pos", "Nat.le_refl")


def test_opens_are_read_with_scoped_in_hiding_and_selected_forms():
    code = (
        "open Real Finset\nopen scoped BigOperators\nopen Nat in\ntheorem x : True := trivial\n"
        "open Foo hiding bar baz\nopen Qux (quux) renaming a → b\nopen Lean.Elab -- a comment left by the mask\n"
    )
    # after `hiding`, `renaming` or a parenthesised list come names, not namespaces
    assert opens_in(code) == ("Real", "Finset", "BigOperators", "Nat", "Foo", "Qux", "Lean.Elab")


def test_names_are_looked_up_innermost_namespace_first_then_opens():
    assert list(candidates("f", ["A", "B"], ["C"])) == ["A.B.f", "A.f", "f", "C.f"]


def test_the_resolver_prefers_the_variant_in_the_same_file_and_leaves_out_itself():
    where = {"A.f": ("X.lean", 1), "g@X.lean": ("X.lean", 2), "g@Y.lean": ("Y.lean", 1), "A.h": ("X.lean", 3)}
    resolver = Resolver(where)
    assert resolver.key_of("g", "Y.lean") == "g@Y.lean"
    assert resolver.key_of("g", "Z.lean") == "g@X.lean"
    assert resolver.uses("A.h", "X.lean", ["f", "h", "g", "Mathlib.thing"], ()) == ["A.f", "g@X.lean"]
    # a file that imports only Y.lean means Y's g, and cannot mean X's f at all
    seeing = Resolver(where, {"Z.lean": frozenset({"Z.lean", "Y.lean"})})
    assert seeing.uses("A.k", "Z.lean", ["f", "g"], ()) == ["g@Y.lean"]


def test_binders_are_read_from_headers_quantifiers_tactics_and_arms():
    assert bound_in("theorem t {α' : Type*} [inst : Group α'] (a bb : α') : bb = a := by\n  intro x hx") >= {
        "α'", "inst", "a", "bb", "x", "hx"}
    assert "t" not in bound_in("theorem t (n : ℕ) : n = n := rfl")  # the declaration's own name is not local
    assert bound_in("def f : ℕ → ℕ\n  | succ kk => kk\n  | .inl hh => 0") >= {"kk", "hh"}
    assert "succ" not in bound_in("def f : ℕ → ℕ\n  | succ kk => kk")  # the constructor is a name being used
    assert bound_in("theorem t : ∀ ε > 0, ∃ δ > 0, δ < ε := by\n  obtain ⟨u, hu⟩ | hv := foo") >= {"ε", "δ", "u", "hu", "hv"}
    assert "foo" not in bound_in("theorem t : True := by\n  have hh : foo = foo := rfl\n  exact (bar := foo) trivial")
    assert variables_in("variable {α β : Type*} [Group α]\nvariable (n : ℕ) in\n") == ("n", "α", "β")
    # a group with no type binds only the names it starts with: `I` here, not the `Grid` and `pp` it ranges over
    union = bound_in("theorem t : ss ⊆ ⋃ (I ∈ {J : Grid X | pp J}), I := sorry")
    assert "I" in union and not union & {"Grid", "pp", "X"}


def test_imports_are_read_in_every_form():
    code = "module\n\npublic import A.B\nimport C D\nmeta import E\nimport all F\npublic meta import G -- why\n"
    assert imports_in(code) == ("A.B", "C", "D", "E", "F", "G")
    assert visible_files({"A.lean": ["B"], "B.lean": ["C", "Mathlib"], "C.lean": [], "D.lean": ["A"]}) == {
        "A.lean": frozenset({"A.lean", "B.lean", "C.lean"}),
        "B.lean": frozenset({"B.lean", "C.lean"}),
        "C.lean": frozenset({"C.lean"}),
        "D.lean": frozenset({"D.lean", "A.lean", "B.lean", "C.lean"}),
    }


# ---- the built site --------------------------------------------------------------------------------------------

def test_each_declaration_carries_its_neighbourhood_across_files(tmp_path):
    summary, out = _build(tmp_path)
    assert not summary.errors
    base_page = (out / "Demo" / "Base.lean.html").read_text(encoding="utf-8")
    more_page = (out / "Demo" / "More.lean.html").read_text(encoding="utf-8")
    assert '<script src="../_assets/map.js" defer></script>' in more_page
    edges = _edges(_data(more_page))
    middle_line = TOP.splitlines().index("def middle : ℕ := base + 1") + 1
    top_line = TOP.splitlines().index("theorem top : 0 < middle := by") + 1
    assert ("Demo.base", "Demo.More.middle", 0) in edges[middle_line]  # through `open Demo`
    assert ("Demo.More.middle", "Demo.More.top", 0) in edges[top_line]  # through the enclosing namespace
    assert ("Demo.base_pos", "Demo.More.top", 0) in edges[top_line]
    assert ("Demo.base", "Demo.base_pos", 0) in edges[top_line]  # two steps back
    lonely_line = TOP.splitlines().index('def lonely : String := "middle"') + 1
    assert lonely_line not in edges  # a name in a string or doc comment is no use
    links = {name: link for name, link in _data(more_page)["n"]}
    assert links["Demo.base"] == "Base.lean.html#L3" and links["Demo.More.middle"].startswith("#L")
    refs = {_data(more_page)["n"][index][0] for index in _data(more_page)["r"]}
    assert {"Demo.base", "Demo.base_pos", "Demo.More.middle"} <= refs
    base_edges = _edges(_data(base_page))
    assert all("Demo.More.top" != user or target != "Demo.base" for target, user, _ in base_edges[3])
    assert not any(("Demo.More.top", "Demo.base_pos", 0) == e for e in base_edges[6])  # only named in a comment


def test_reference_index_keeps_direct_uses_omitted_from_the_small_drawing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    names = [f"value{k}" for k in range(12)]
    (src / "Values.lean").write_text(
        "\n".join(f"def {name} : ℕ := {k}" for k, name in enumerate(names)) + "\n",
        encoding="utf-8",
    )
    (src / "Total.lean").write_text(
        "import Values\n\ndef total : ℕ := " + " + ".join(names) + "\n",
        encoding="utf-8",
    )
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    data = _data((tmp_path / "out" / "Total.lean.html").read_text(encoding="utf-8"))
    refs = {data["n"][index][0] for index in data["r"]}
    assert set(names) <= refs
    drawn = {data["n"][index][0] for entry in data["d"] for index in entry[2][::3] + entry[2][1::3]}
    assert set(names) - drawn  # direct references beyond the NEAR display limit remain linkable


SHADOW_DEF = "def Kc : ℕ := 7\n"
# every way a local name can shadow the project's `Kc`; only `real` uses the definition
SHADOWS = {
    "in_variable": "variable {Kc : Type*}\n\ntheorem in_variable (f : Kc → ℕ) : True := trivial\n",
    "in_binder": "theorem in_binder (Kc : ℕ) : Kc = Kc := rfl\n",
    "in_implicit": "theorem in_implicit {Kc L : ℕ} (h : Kc = L) : L = Kc := h.symm\n",
    "in_fun": "def in_fun : ℕ → ℕ := fun Kc => Kc + 1\n",
    "in_forall": "theorem in_forall : ∀ Kc : ℕ, Kc = Kc := fun _ => rfl\n",
    "in_exists": "theorem in_exists : ∃ Kc, Kc = 0 := ⟨0, rfl⟩\n",
    "in_intro": "theorem in_intro : ∀ n : ℕ, n = n := by\n  intro Kc\n  rfl\n",
    "in_obtain": "theorem in_obtain (h : ∃ n : ℕ, n = 0) : True := by\n  obtain ⟨Kc, hK⟩ := h\n  trivial\n",
    "in_have": "theorem in_have : True := by\n  have Kc : 1 = 1 := rfl\n  trivial\n",
    "in_match": "def in_match : ℕ → ℕ\n  | 0 => 0\n  | Kc + 1 => Kc\n",
    "in_rcases": "theorem in_rcases (h : 0 = 0 ∨ 1 = 1) : True := by\n  rcases h with hc | Kc\n  all_goals trivial\n",
    "in_named_arg": "theorem in_named_arg : True := foo (Kc := 3) trivial\n",
    "in_set_builder": "def in_set_builder : Set ℕ := {Kc | Kc > 2}\n",
    "real": "theorem real : Kc = 7 := rfl\n",
}


def test_a_local_name_shadows_a_project_name_of_the_same_spelling(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Def.lean").write_text(SHADOW_DEF, encoding="utf-8")
    for name, text in SHADOWS.items():
        (src / f"{name}.lean").write_text("import Def\n\n" + text, encoding="utf-8")
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    data = _data((tmp_path / "out" / "Def.lean.html").read_text(encoding="utf-8"))
    users = {user for target, user, _ in _edges(data)[1] if target == "Kc"}
    assert users == {"real"}  # not one of the declarations where Kc is a local name


def test_a_file_sees_only_what_it_imports_directly_or_through_others(tmp_path):
    src = tmp_path / "src"
    (src / "P").mkdir(parents=True)
    (src / "P" / "Def.lean").write_text("module\n\ndef Kc : ℕ := 7\n", encoding="utf-8")
    (src / "P" / "Mid.lean").write_text("module\n\npublic import P.Def\npublic import Mathlib\n\ndef mid : ℕ := 1\n", encoding="utf-8")
    (src / "P" / "Far.lean").write_text("import all P.Mid\n\ntheorem far : Kc = 7 := rfl\n", encoding="utf-8")
    (src / "P" / "Apart.lean").write_text("import Mathlib\n\ntheorem apart (Kc' : ℕ) : Kc = 7 := rfl\n", encoding="utf-8")
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    data = _data((tmp_path / "out" / "P" / "Def.lean.html").read_text(encoding="utf-8"))
    users = {user for target, user, _ in _edges(data)[3] if target == "Kc"}
    assert users == {"far"}  # through P.Mid; P.Apart imports neither, so its `Kc` is something else


def test_a_file_sees_through_a_file_that_only_imports(tmp_path):
    # formal-conjectures: 1,469 problem files `import FormalConjecturesUtil`, a file with no declarations of its own
    src = tmp_path / "src"
    (src / "P").mkdir(parents=True)
    (src / "P" / "Def.lean").write_text("module\n\ndef Kc : ℕ := 7\n", encoding="utf-8")
    (src / "Hub.lean").write_text("module\n\npublic import P.Def\npublic import Mathlib\n\n/-! # Standard imports -/\n", encoding="utf-8")
    (src / "Problem.lean").write_text("import Hub\n\ntheorem problem : Kc = 7 := rfl\n", encoding="utf-8")
    (src / "Apart.lean").write_text("import Mathlib\n\ntheorem apart : Kc = 7 := rfl\n", encoding="utf-8")
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    data = _data((tmp_path / "out" / "P" / "Def.lean.html").read_text(encoding="utf-8"))
    assert {user for target, user, _ in _edges(data)[3] if target == "Kc"} == {"problem"}


def test_a_file_sees_its_own_copy_of_a_declaration_that_is_identical_elsewhere(tmp_path):
    # tutorials ship each exercise twice (exercise and solution): the copies fold into one key, located at the first
    src = tmp_path / "src"
    (src / "A").mkdir(parents=True)
    (src / "B").mkdir()
    for folder, value in (("A", 1), ("B", 2)):
        (src / folder / "Ex.lean").write_text(
            f"structure Gauss where\n  re : ℤ\n\ndef helper : ℕ := {value}\n\n"
            "theorem uses_it (x : Gauss) : helper = helper := rfl\n",
            encoding="utf-8",
        )
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    for folder in ("A", "B"):
        page = (tmp_path / "out" / folder / "Ex.lean.html").read_text(encoding="utf-8")
        data = _data(page)  # each copy's page has the map, not only the first copy's
        assert {("Gauss", "uses_it", 0), ("helper", "uses_it", 0)} <= _edges(data)[6], folder
        links = dict(data["n"])
        assert links["Gauss"] == "#L1" and links["helper"] == "#L4", folder  # the copies in this file


def test_a_second_build_reads_the_map_back_from_the_cache(tmp_path):
    from lean4_explainer.build import CACHE_FILE, _fingerprint
    from lean4_explainer.cache import load_cache

    _summary, out = _build(tmp_path)
    first = (out / "Demo" / "More.lean.html").read_text(encoding="utf-8")
    # a cache the loader refuses is silently rebuilt, so look at what it loads, not only at the result
    cache = load_cache(tmp_path / "idx" / CACHE_FILE, _fingerprint(Config()))
    imports, declarations = dict(cache.files["Demo/More.lean"].ext)["map"]
    assert imports == ("Demo.Base",) and ("Demo.More.middle", ("middle", "base"), ("Demo",)) in declarations
    again = build_site(tmp_path / "src", tmp_path / "out2", Config(), tmp_path / "idx", jobs=1)
    assert again.files == 2 and not again.errors
    # the index (with the names each declaration uses) came back from the cache, and gives the same map
    assert _data((tmp_path / "out2" / "Demo" / "More.lean.html").read_text(encoding="utf-8")) == _data(first)


def test_the_counts_say_how_many_there_are_beyond_the_drawing(tmp_path):
    _summary, out = _build(tmp_path)
    data = _data((out / "Demo" / "Base.lean.html").read_text(encoding="utf-8"))
    entry = next(d for d in data["d"] if d[0] == 3)  # base: used by base_pos and middle, builds on nothing
    assert entry[3:5] == [0, 2]


def test_the_project_map_links_files_and_is_in_the_navigation(tmp_path):
    _summary, out = _build(tmp_path)
    page = (out / "map.html").read_text(encoding="utf-8")
    data = _data(page, "project-map-data")
    files = {f[0]: (i, f) for i, f in enumerate(data["f"])}
    assert files["Demo/Base.lean"][1][1] == "Demo/Base.lean.html" and files["Demo/Base.lean"][1][2] == 2
    a, b = files["Demo/Base.lean"][0], files["Demo/More.lean"][0]
    assert data["e"] == [[a, b, 2]]  # middle uses base, top uses base_pos: two uses, all one way
    assert '<div id="project-map">' in page and 'src="_assets/map.js"' in page
    assert '<caption>Files and cross-file dependency counts</caption>' in page
    assert 'aria-label="Filter map files"' in page
    assert '>Demo/Base.lean</a></td><td>2</td><td>0</td><td>1</td>' in page
    assert "Text version of this map" in MAP_JS
    assert 'href="../map.html">Map</a>' in (out / "Demo" / "Base.lean.html").read_text(encoding="utf-8")
    assert (out / "_assets" / "map.js").read_text(encoding="utf-8") == MAP_JS


def test_guillemet_names_are_followed_and_cannot_close_the_data_block(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.lean").write_text("def «</script>x» : ℕ := 1\n\ndef y : ℕ := «</script>x» + 1\n", encoding="utf-8")
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    page = (tmp_path / "out" / "A.lean.html").read_text(encoding="utf-8")
    data = _data(page)  # parses only if the block was not cut short by the name
    assert ["«</script>x»", "#L1"] in data["n"]  # the quoted name is read as written, and resolves
    assert "<script>alert" not in page and page.count("</script>x") == 0


def test_the_map_can_be_switched_off(tmp_path):
    _summary, out = _build(tmp_path, options=[("map_dependencies", False)])
    page = (out / "Demo" / "More.lean.html").read_text(encoding="utf-8")
    assert "map-data" not in page and "map.js" not in page and ">Map</a>" not in page
    assert not (out / "map.html").exists()


def test_l4del_prerequisites_are_drawn_as_declared_links(tmp_path):
    l4del = pytest.importorskip("lean4_explainer_l4del")
    extensions.activate([l4del.L4delExtension(), MapExtension()])
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.lean").write_text(
        "def a : ℕ := 1\n\n-- L4DEL: title: B\n-- L4DEL: prereq: a\ntheorem b : True := trivial\n", encoding="utf-8"
    )
    build_site(src, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    page = (tmp_path / "out" / "A.lean.html").read_text(encoding="utf-8")
    assert ("a", "b", 1) in _edges(_data(page))[5]  # not in the code: named as a prerequisite in the notes
    assert page.count('href="map.html">Map</a>') == 1  # one map, not one per extension


# ---- map.js, run under node --------------------------------------------------------------------------------------

def _node(tmp_path, cases):
    script = tmp_path / "map.cjs"
    script.write_text(MAP_JS, encoding="utf-8")
    inputs = tmp_path / "cases.json"
    inputs.write_text(json.dumps(cases), encoding="utf-8")
    driver = HERE / "layout_check.cjs"
    done = subprocess.run([str(NODE), str(driver), str(script), str(inputs)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _random_graphs():
    import random

    rng = random.Random(20261010)
    cases = []
    for k in range(60):
        n = rng.randint(2, 26)
        density = rng.choice([0.05, 0.12, 0.25])
        edges = [[a, b] for a in range(n) for b in range(n) if a != b and rng.random() < density / 2]
        sizes = [[rng.randint(40, 260), 26] for _ in range(n)]
        cases.append({"sizes": sizes, "edges": edges})
    # shapes a declaration's map really has: a centre, what it builds on, what uses it, second steps, and a cycle
    star = [[i, 0] for i in range(1, 8)] + [[0, i] for i in range(8, 15)] + [[15 + i, 1 + i % 7] for i in range(5)] + [[0, 3]]
    cases.append({"sizes": [[120, 26]] * 20, "edges": star})
    cases.append({"sizes": [[60, 26]] * 3, "edges": [[0, 1], [1, 2], [2, 0]]})
    cases.append({"sizes": [[60, 26]], "edges": []})
    return cases


@needs_node
def test_the_layout_points_arrows_right_keeps_boxes_apart_and_never_crosses_one(tmp_path):
    results = _node(tmp_path, _random_graphs())
    for k, r in enumerate(results):
        assert not r["overlaps"], (k, r["overlaps"])
        assert not r["through"], (k, r["through"])  # no arrow passes through a box it does not start or end at
        assert not r["leftward"], (k, r["leftward"])  # every arrow not turned round to break a cycle points right
        assert r["inside"], k  # everything is inside the drawing
        assert r["crossings"] <= r["initialCrossings"], k  # the ordering never makes it worse than where it started


@needs_node
def test_labels_are_short_distinct_and_escaped(tmp_path):
    result = _node(tmp_path, {"labels": ["A.B.foo", "C.B.foo", "Demo.bar", "<script>alert(1)</script>"]})
    assert result["labels"][:3] == ["A.B.foo", "C.B.foo", "bar"]
    assert "<script>" not in result["svg"] and "&lt;script&gt;" in result["svg"]
    assert result["svg"].count("<a href=") == 3  # the box for "here" is not a link to itself
