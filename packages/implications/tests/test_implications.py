import json
import re
import shutil
from pathlib import Path

import pytest

from lean4_explainer import extensions
from lean4_explainer.build import build_site
from lean4_explainer.config import Config
from lean4_explainer_implications import edges as E
from lean4_explainer_implications.extension import ImplicationsExtension


@pytest.fixture(autouse=True)
def only_this_extension():
    """Builds here run this extension alone, whatever else is installed (a Lean run would check the bridges)."""
    extensions.activate([ImplicationsExtension()])
    yield
    extensions.activate(None)

DEMO = """\
namespace Demo

/-- A number above 7 is positive. -/
theorem pos_of_gt (x : Nat) (h : 7 < x) : 0 < x := Nat.lt_of_le_of_lt (Nat.zero_le 7) h

theorem gap (x : Nat) (h : 7 < x) : 1 ≤ x := pos_of_gt x h

theorem bridge (x : Nat) (h : 7 < x) : 1 ≤ x := pos_of_gt x h

theorem other : True := trivial

end Demo
"""

EDGES = """\
[[edge]]
id = "gap-from-pos"
kind = "strengthens"
from = ["Demo.pos_of_gt"]
to = "Demo.gap"
hypotheses = ["(x : Nat) (h : 7 < x)"]
conclusion = "1 ≤ x"
commit = "abc1234"
status = "argued"
origin = "a test, 2026-10-10"
argument = "For natural numbers, 0 < x is 1 ≤ x."

[[edge]]
id = "gap-proved"
kind = "specializes-to"
from = ["Demo.pos_of_gt"]
to = "Demo.gap"
hypotheses = ["(x : Nat) (h : 7 < x)"]
conclusion = "1 ≤ x"
commit = "abc1234"
status = "proved"
origin = "a test"
bridge = "Demo.bridge"

[[candidate]]
id = "pair"
kind = "composes-with"
from = ["Demo.pos_of_gt", "Demo.gap"]
phrase = "positivity plus the gap"
origin = "a test"
missing = "a stated conclusion"
"""


def _site(tmp_path, edges=EDGES, source=DEMO, **options):
    root = tmp_path / "src"
    root.mkdir(exist_ok=True)
    (root / "Demo.lean").write_text(source, encoding="utf-8")
    sidecar = tmp_path / "implications.toml"
    sidecar.write_text(edges, encoding="utf-8")
    opts = {"implications_file": str(sidecar), **options}
    summary = build_site(root, tmp_path / "out", Config(options=tuple(sorted(opts.items()))), tmp_path / "idx", jobs=1)
    return summary, tmp_path / "out"


# ---- the file format ----

GOOD = {"id": "a-b", "kind": "strengthens", "from": ["A.x"], "to": "A.y", "hypotheses": [], "conclusion": "P", "commit": "abcdef1", "status": "proposed", "origin": "me"}


def _toml(table: str, fields: dict) -> str:
    def value(v):
        return json.dumps(v, ensure_ascii=False)  # a JSON string or list of strings is valid TOML

    return f"[[{table}]]\n" + "".join(f"{k} = {value(v)}\n" for k, v in fields.items())


@pytest.mark.parametrize(
    "change, message",
    [
        ({"colour": "red"}, "unknown key 'colour'"),
        ({"kind": "implies"}, "kind must be one of"),
        ({"id": "Bad Id"}, "id must be lowercase letters, digits and hyphens"),
        ({"commit": "main"}, "commit must be 7 to 40 hexadecimal digits"),
        ({"conclusion": " "}, "conclusion must not be empty"),
        ({"from": "A.x"}, "from must be a list of declaration names"),
        ({"from": []}, "from must name at least one declaration"),
        ({"from": ["A.x", "A.x"]}, "from names A.x twice"),
        ({"to": None}, "a strengthens edge needs `to`"),
        ({"kind": "composes-with", "to": None}, "a composes-with edge needs two or more names in `from`"),
        ({"status": "argued"}, "an argued edge needs `argument`"),
        ({"status": "proved"}, "a proved edge needs `bridge`"),
        ({"status": "refuted"}, "a refuted edge needs `evidence`"),
        ({"status": "true"}, "status must be one of"),
        ({"origin": None}, "missing key 'origin'"),
        ({"hypotheses": "x"}, "hypotheses must be a list of Lean texts"),
    ],
)
def test_a_contract_with_a_gap_is_an_error(change, message):
    fields = {k: v for k, v in {**GOOD, **change}.items() if v is not None}
    found = E.load(_toml("edge", fields))
    assert not found.edges and any(message in p for p in found.problems), found.problems


def test_a_good_file_loads_and_ids_are_unique_across_edges_and_candidates():
    found = E.load(EDGES)
    assert not found.problems
    assert [e.id for e in found.edges] == ["gap-from-pos", "gap-proved"] and found.candidates[0].id == "pair"
    assert found.edges[0].names == ("Demo.pos_of_gt", "Demo.gap")
    clash = E.load(EDGES + _toml("candidate", {"id": "pair", "kind": "strengthens", "from": ["A.x"], "to": "A.y", "phrase": "p", "origin": "o"}))
    assert any("id 'pair' is used twice" in p for p in clash.problems)
    assert any("unknown table 'edges'" in p for p in E.load("[[edges]]\nid = 'x'\n").problems)
    assert any("not valid TOML" in p for p in E.load("[[edge]\n").problems)


def test_what_the_kernel_says_decides_a_proved_edge():
    edge = E.load(EDGES).edges[1]
    assert E.verify(edge, lambda name: None).state == "unchecked"  # Lean was not run
    assert E.verify(edge, lambda name: ("standard", "standard axioms: propext")).state == "kernel-checked"
    failing = E.verify(edge, lambda name: ("sorry", "depends on sorry"))
    assert failing.state == "fails" and "depends on sorry" in failing.detail
    assert E.verify(edge, lambda name: ("unknown", "trust unknown: x")).state == "unchecked"
    assert E.verify(E.load(EDGES).edges[0], lambda name: ("none", "no axioms")).state == "argued"  # no bridge to check


def test_an_argued_edge_claims_no_check_by_anyone():
    # the one who suggested an edge is often not the one who argued it: the status line must not say who checked it
    detail = E.verify(E.load(EDGES).edges[0], lambda name: None).detail
    assert "checked by" not in detail.lower()
    assert "argument" in detail and "Lean has not checked it" in detail


# ---- the site ----


def test_edges_show_on_both_ends_on_their_own_page_and_as_data(tmp_path):
    summary, out = _site(tmp_path, implications_commit="abc1234def")
    assert not summary.errors, summary.errors
    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    source = page[page.index('id="L4"') : page.index('id="L6"')]
    target = page[page.index('id="L6"') : page.index('id="L8"')]
    assert '<span class="imp-kind">strengthens</span> <a href="Demo.lean.html#L6"><code>Demo.gap</code></a>' in source
    assert '<span class="imp imp-argued">argued</span> <a href="implications.html#gap-from-pos">contract</a>' in source
    assert '<span class="imp-kind">is strengthened by</span> <a href="Demo.lean.html#L4"><code>Demo.pos_of_gt</code></a>' in target
    assert "is the bridge" in page[page.index('id="L8"') : page.index('id="L10"')]  # the bridge says what it proves
    assert "Implications" not in page[page.index('id="L10"') :]  # a declaration with no edge gets no block
    assert '<a href="implications.html">Implications</a>' in page  # the nav

    index = (out / "implications.html").read_text(encoding="utf-8")
    edge = index[index.index('<article class="edge" id="gap-from-pos">') :]
    edge = edge[: edge.index("</article>")]
    assert "<pre>(x : Nat) (h : 7 &lt; x)</pre>" in edge and "<pre>1 ≤ x</pre>" in edge
    assert "For natural numbers, 0 &lt; x is 1 ≤ x." in edge and "a test, 2026-10-10" in edge
    assert "abc1234" in edge and "stale" not in edge  # read at the commit this site shows
    proved = index[index.index('<article class="edge" id="gap-proved">') :]
    assert "Not checked in this build" in proved[: proved.index("</article>")]  # no Lean run here
    assert '<section class="candidates">' in index and "positivity plus the gap" in index and "a stated conclusion" in index
    assert "A dependency records which declarations a proof uses" in index

    data = json.loads((out / "implications.json").read_text(encoding="utf-8"))
    first = data["edges"][0]
    assert first["id"] == "gap-from-pos" and first["status"] == "argued" and first["verification"]["state"] == "argued"
    assert first["from"] == [{"name": "Demo.pos_of_gt", "page": "Demo.lean.html#L4"}] and first["to"]["page"] == "Demo.lean.html#L6"
    assert first["hypotheses"] == ["(x : Nat) (h : 7 < x)"] and first["conclusion"] == "1 ≤ x" and first["commit"] == "abc1234"
    assert data["edges"][1]["verification"]["state"] == "unchecked" and data["candidates"][0]["id"] == "pair"

    glossary = (out / "glossary.html").read_text(encoding="utf-8")
    assert "Implication edges" in glossary and "Supports an executable construction" in glossary and "argued" in glossary


def test_a_name_the_site_does_not_have_is_an_error(tmp_path):
    summary, _ = _site(tmp_path, EDGES.replace('to = "Demo.gap"', 'to = "Demo.nowhere"', 1))
    assert any("gap-from-pos" in e and "no declaration named Demo.nowhere" in e for e in summary.errors), summary.errors


def test_a_name_declared_in_two_files_is_named_with_its_path(tmp_path):
    # found on openai/math, 2026-10-10: it restates its results under the same names (ComparatorChallenges/), so an
    # edge must say which copy it means, and it is still shown and linked by the name Lean knows
    root = tmp_path / "src"
    (root / "Challenges").mkdir(parents=True)
    (root / "Demo.lean").write_text(DEMO, encoding="utf-8")
    (root / "Challenges" / "Demo.lean").write_text(DEMO.replace(":= pos_of_gt x h", ":= sorry"), encoding="utf-8")
    sidecar = tmp_path / "e.toml"
    sidecar.write_text(EDGES, encoding="utf-8")
    config = Config(source_url="https://example.org/{ref}/{path}#L{line}", options=(("implications_file", str(sidecar)),))

    summary = build_site(root, tmp_path / "out", config, tmp_path / "idx", jobs=1)
    assert any("Demo.gap names distinct declarations" in e and "Demo.gap@Demo.lean" in e for e in summary.errors), summary.errors

    for name in ("Demo.gap", "Demo.bridge", "Demo.pos_of_gt"):  # pos_of_gt is the same in both: the path still picks one
        sidecar.write_text(sidecar.read_text(encoding="utf-8").replace(f'"{name}"', f'"{name}@Demo.lean"'), encoding="utf-8")
    summary = build_site(root, tmp_path / "out", config, tmp_path / "idx", jobs=1)
    assert not summary.errors, summary.errors
    page = (tmp_path / "out" / "Demo.lean.html").read_text(encoding="utf-8")
    assert '<span class="imp-kind">strengthens</span> <a href="Demo.lean.html#L6"><code>Demo.gap</code></a>' in page[page.index('id="L4"') : page.index('id="L6"')]
    assert 'class="implications"' not in (tmp_path / "out" / "Challenges" / "Demo.lean.html").read_text(encoding="utf-8")
    index = (tmp_path / "out" / "implications.html").read_text(encoding="utf-8")
    assert "@Demo.lean" not in index and ">pos_of_gt</a>" in index  # names as Lean knows them; the links say where
    data = json.loads((tmp_path / "out" / "implications.json").read_text(encoding="utf-8"))
    assert data["edges"][0]["from"] == [{"name": "Demo.pos_of_gt", "page": "Demo.lean.html#L4"}]


def test_the_kernel_is_asked_about_the_name_lean_knows():
    from lean4_explainer.extensions import Extension
    from lean4_explainer_implications.extension import Analysis, _kernel

    asked = []

    class Lean(Extension):
        name = "lean"

        def kernel_trust(self, analysis, name, rel, line):
            asked.append((name, rel, line))
            return ("none", "no axioms")

    me = ImplicationsExtension()
    analysis = Analysis("e.toml", places={"Demo.bridge@Demo.lean": ("Demo.lean", 8)})
    assert _kernel(analysis, [(me, analysis), (Lean(), None)], me)("Demo.bridge@Demo.lean") == ("none", "no axioms")
    assert asked == [("Demo.bridge", "Demo.lean", 8)]


def test_an_edge_read_at_another_commit_is_marked_stale(tmp_path):
    summary, out = _site(tmp_path, implications_commit="0123456789")
    assert any("gap-from-pos" in w and "read at commit abc1234" in w for w in summary.warnings), summary.warnings
    edge = (out / "implications.html").read_text(encoding="utf-8")
    assert '<p class="imp-stale">' in edge
    assert json.loads((out / "implications.json").read_text(encoding="utf-8"))["edges"][0]["stale"] is True


def test_a_file_named_implications_toml_in_the_project_is_found(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "Demo.lean").write_text(DEMO, encoding="utf-8")
    (root / "implications.toml").write_text(EDGES, encoding="utf-8")
    summary = build_site(root, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    assert not summary.errors and (tmp_path / "out" / "implications.html").is_file()


def test_without_edges_nothing_is_added(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "Demo.lean").write_text(DEMO, encoding="utf-8")
    summary = build_site(root, tmp_path / "out", Config(), tmp_path / "idx", jobs=1)
    assert not summary.errors and not (tmp_path / "out" / "implications.html").exists()
    assert "Implications" not in (tmp_path / "out" / "Demo.lean.html").read_text(encoding="utf-8")


def test_changing_the_edges_changes_the_fingerprint(tmp_path):
    sidecar = tmp_path / "e.toml"
    sidecar.write_text(EDGES, encoding="utf-8")
    first = ImplicationsExtension().fingerprint({"implications_file": str(sidecar)})
    sidecar.write_text(EDGES.replace("abc1234", "abc1235"), encoding="utf-8")
    assert ImplicationsExtension().fingerprint({"implications_file": str(sidecar)}) != first


@pytest.mark.skipif(shutil.which("lean") is None, reason="lean is not installed")
def test_with_lean_run_a_bridge_is_checked_by_the_kernel(tmp_path):
    lean = pytest.importorskip("lean4_explainer_lean")
    extensions.activate([ImplicationsExtension(), lean.LeanExtension()])
    summary, out = _site(tmp_path, lean_cache=str(tmp_path / "cache"))
    assert not summary.errors, summary.errors
    index = (out / "implications.html").read_text(encoding="utf-8")
    proved = index[index.index('id="gap-proved"') :]
    proved = proved[: proved.index("</article>")]
    assert "kernel checked Demo.bridge in this build: no axioms" in proved and re.search(r"Demo\.bridge", proved)
    page = (out / "Demo.lean.html").read_text(encoding="utf-8")
    assert '<span class="imp imp-kernel-checked">kernel-checked</span>' in page  # the declarations say so too
    assert json.loads((out / "implications.json").read_text(encoding="utf-8"))["edges"][1]["verification"]["state"] == "kernel-checked"
    # a bridge that depends on sorry fails the edge, and the build says so
    summary, out = _site(tmp_path, source=DEMO.replace("theorem bridge (x : Nat) (h : 7 < x) : 1 ≤ x := pos_of_gt x h", "theorem bridge (x : Nat) (h : 7 < x) : 1 ≤ x := sorry"), lean_cache=str(tmp_path / "cache"))
    assert any("gap-proved" in w and "depends on sorry" in w for w in summary.warnings), summary.warnings


# ---- recorded checks and the discovered catalogue on the site ----


def _recorded_site(tmp_path, record_change=None, bridge_change=None, checkout=lambda data: data):
    """The fixture as a site, with a bridge file, a recorded check of it and a small catalogue (no Lean run here). The
    record is made from the files as git stores them (LF); `checkout` is what the site's checkout has on disk."""
    from lean4_explainer_implications.pipeline import catalogue as K

    lean = Path(__file__).resolve().parent / "lean"
    root = tmp_path / "src"
    root.mkdir(exist_ok=True)
    fixture = (lean / "ImplicationsFixture.lean").read_bytes().replace(b"\r\n", b"\n")
    (root / "ImplicationsFixture.lean").write_bytes(checkout(fixture))
    side = tmp_path / "side"
    (side / "bridges").mkdir(parents=True, exist_ok=True)
    bridge = (lean / "bridges" / "Good.lean").read_bytes().replace(b"\r\n", b"\n")
    (side / "bridges" / "Good.lean").write_bytes(checkout(bridge_change(bridge) if bridge_change else bridge))
    (side / "implications.toml").write_text((lean / "edges.toml").read_text(encoding="utf-8"), encoding="utf-8")
    found = E.load((side / "implications.toml").read_text(encoding="utf-8"))
    assert not found.problems, found.problems
    sha = E.content_sha256(bridge)  # the file as it was checked
    fixture_sha = E.content_sha256(fixture)
    records = {}
    for e in found.edges:
        records[e.id] = {"status": "checked", "fingerprint": E.fingerprint(e, sha), "corpus_revision": "abcdef1234", "checked_at": "2026-10-10T00:00:00Z",
                         "inputs": {"ImplicationsFixture.lean": fixture_sha}, "toolchain": "Lean (version 4.34.1)", "mathlib": "", "axioms": [],
                         "expected": "∀ (source1 : …), …", "environment": "e1", "imports": ["ImplicationsFixture"], "bridge_sha256": sha, "command": "test",
                         "target_conclusion": "1 ≤ Fx.size n", "contract_conclusion": "n + 1 ≤ Fx.size n", "target_only_hypotheses": []}
        records[e.id].update((record_change or {}).get(e.id, {}))
    (side / "implications.verified.json").write_text(json.dumps({"format": 1, "edges": records}), encoding="utf-8")

    def key(n):
        return f"test/fixture@abcdef123456:ImplicationsFixture:{n}"

    def decl(n, line):
        return {"key": key(n), "name": n, "module": "ImplicationsFixture", "path": "ImplicationsFixture.lean", "range": {"line": line},
                "role": "statement", "kind": "theorem", "prop": True, "family": "Fixture", "type": n, "type_hash": n,
                "norm": {"conclusion_head": "Fx.Fine", "hyp_heads": [], "uses": []}}

    decls = [decl("Fx.good_of_two", 15), decl("Fx.fine_of_good", 18), decl("Fx.fine_of_two", 21), decl("Fx.size_pos", 39)]
    results = [{"id": "a1", "status": "checked-instantiated", "rule": "target", "source_keys": [key("Fx.good_of_two"), key("Fx.fine_of_good")],
                "target_key": key("Fx.fine_of_two"), "sources": ["Fx.good_of_two", "Fx.fine_of_good"], "statement": "∀ (n : Nat), 2 ≤ n → Fx.Fine n",
                "derived": "(∀ n, 2 ≤ n → Fx.Good n) → (∀ n, Fx.Good n → Fx.Fine n) → ∀ (n : Nat), 2 ≤ n → Fx.Fine n", "statement_hash": "h1",
                "used": [True, True], "steps": [{"step": "apply", "fact": "source 2", "substitutions": [{"variable": "n", "value": "n"}]}], "layer": "fixture"},
               {"id": "a2", "status": "no-proof", "rule": "target", "source_keys": [key("Fx.size_pos")], "target_key": key("Fx.fine_of_two"),
                "reason": "no derivation within the rules and depth"}]
    cat = K.build(decls, results, {"provenance": "Recorded in a test.", "environment": {"policy": "rules-1:test"}})
    K.write(cat, side / "catalogue")
    opts = {"implications_file": str(side / "implications.toml"), "implications_commit": "abcdef1234"}
    summary = build_site(root, tmp_path / "out", Config(options=tuple(sorted(opts.items()))), tmp_path / "idx", jobs=1)
    return summary, tmp_path / "out"


def test_a_recorded_check_shows_with_its_provenance_and_the_exact_contract(tmp_path):
    summary, out = _recorded_site(tmp_path)
    assert not summary.errors, summary.errors
    index = (out / "implications.html").read_text(encoding="utf-8")
    chain = index[index.index('id="chain"') :]
    chain = chain[: chain.index("</article>")]
    assert "kernel-checked (recorded)" in chain and "This build did not run Lean" in chain
    assert "The exact contract, as Lean states it" in chain and "Recorded check" in chain
    assert 'href="implications/bridges/Good.lean.html#L5"' in chain  # the bridge, on its own page, at its line
    size = index[index.index('id="size-bound"') :]
    assert "What it adds to the target" in size and "a lower bound that grows with n" in size
    assert "Hypotheses the target has" not in size and "<code>n + 1 ≤ Fx.size n</code>" in size
    bridge = (out / "implications" / "bridges" / "Good.lean.html").read_text(encoding="utf-8")
    assert 'id="L5"' in bridge and "theorem bridge_good" in bridge
    data = json.loads((out / "implications.json").read_text(encoding="utf-8"))
    v = data["edges"][0]["verification"]
    assert v["state"] == "kernel-checked" and v["provenance"] == "recorded" and v["record"]["checked_at"] == "2026-10-10T00:00:00Z"


def test_a_changed_bridge_file_makes_the_recorded_check_stale(tmp_path):
    summary, out = _recorded_site(tmp_path, bridge_change=lambda data: data.replace(b"fun n h => source2 n (source1 n h)", b"fun n h => source2 _ (source1 _ h)"))
    assert any("chain" in w and "changed since" in w for w in summary.warnings), summary.warnings
    index = (out / "implications.html").read_text(encoding="utf-8")
    chain = index[index.index('id="chain"') :]
    assert '<span class="imp imp-stale">check is stale</span>' in chain[: chain.index("</article>")]


def test_a_record_made_on_one_checkout_holds_on_another_with_other_line_endings(tmp_path):
    # found 2026-10-10: the record was made on Windows (core.autocrlf, CRLF) and Pages builds on Linux (LF); the same
    # commit must not read as changed
    summary, out = _recorded_site(tmp_path, checkout=lambda data: data.replace(b"\n", b"\r\n"))
    assert not [w for w in summary.warnings if "stale" in w or "changed since" in w or "differ" in w], summary.warnings
    data = json.loads((out / "implications.json").read_text(encoding="utf-8"))
    assert {e["id"]: e["verification"]["state"] for e in data["edges"]} == {"chain": "kernel-checked", "size-bound": "kernel-checked"}


def test_a_failed_record_fails_the_edge(tmp_path):
    summary, out = _recorded_site(tmp_path, record_change={"chain": {"status": "mismatch", "reason": "type mismatch"}})
    assert any("chain" in w and "failed (mismatch)" in w for w in summary.warnings), summary.warnings


def test_the_catalogue_is_searchable_and_on_the_theorem_pages(tmp_path):
    summary, out = _recorded_site(tmp_path)
    assert not summary.errors, summary.errors
    page = (out / "implications" / "catalogue.html").read_text(encoding="utf-8")
    assert "Provenance." in page and "Recorded in a test." in page and 'src="catalogue.js"' in page
    data = json.loads((out / "implications" / "catalogue" / "index.json").read_text(encoding="utf-8"))
    t = data["theorems"]["test/fixture@abcdef123456:ImplicationsFixture:Fx.fine_of_two"]
    assert t["page"] == "../ImplicationsFixture.lean.html#L19"
    assert [i["id"] for i in data["implications"]] == ["a1"] and data["implications"][0]["layer"] == "fixture"
    shard = data["implications"][0]["shard"]
    assert (out / "implications" / "catalogue" / "shards" / f"{shard}.json").is_file()
    assert (out / "implications" / "catalogue.js").is_file()
    notes = (out / "implications" / "notes.html").read_text(encoding="utf-8")
    assert "Unresolved attempts (1)" in notes and "never false" in notes
    fixture = (out / "ImplicationsFixture.lean.html").read_text(encoding="utf-8")
    target = fixture[fixture.index('id="L19"') : fixture.index('id="L22"')]
    assert "Checked implications" in target and "Follows from" in target and "implications/catalogue.html#a1" in target
    assert "kernel-checked (recorded)" in target  # the curated edge's badge says where its check comes from
    assert 'href="implications/notes.html"' in (out / "implications.html").read_text(encoding="utf-8")
    source = fixture[fixture.index('id="L13"') : fixture.index('id="L16"')]
    assert "Gives" in source and "together with" in source
    assert "Checked implications" not in fixture[fixture.index('id="L37"') :]  # size_pos: only an unresolved attempt
