"""The discovered catalogue on the site: a search page that loads its data lazily, a notes page, and the rows a
theorem's page shows.

The catalogue is what the pipeline recorded (`python -m lean4_explainer_implications.pipeline catalogue`): an index,
and one shard per family with the details. The site copies both and adds, for each theorem, where its page is. A
site build never runs the search and never runs Lean for the catalogue: every entry says it shows a recorded check.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from html import escape
from pathlib import Path
from urllib.parse import quote

GROUP_LABELS = {
    "connection": "connection",
    "same statement": "same statement as the source",
    "restatement": "the source restated (same proposition up to definitions)",
    "generated": "uses a lemma Lean generated (no stated result)",
    "one challenge": "within one challenge file",
    "in the released proof": "the released proof already goes this way",
    "source uses the target": "the source's released proof uses the target",
    "reverse direction": "other direction of an equivalence",
    "structure field": "through a structure's field (what its objects carry by definition)",
    "duplicate": "derives a statement already listed",
}
STATE_LABELS = {
    "checked-instantiated": "kernel-checked, applied to the released theorems",
    "checked-derivation": "kernel-checked, sources as hypotheses",
}
# what applying a checked derivation to the released theorems established: a run that ends without a proof establishes
# nothing either way, and says so
INSTANTIATION_LABELS = {
    "checked-instantiated": "checked: the derivation applied to the released theorems, each from the module that proves it",
    "instantiation-circular": "circular: the released proof of a source already uses the target",
    "budget": "not established: the attempt ran out of its time or heartbeat budget",
    "error": "not established: Lean stopped with an error",
    "no-proof": "not established: no proof was found within the rules",
    "audit-failed": "not established: the proof found did not pass the audit",
}


def load(directory: Path) -> dict | None:
    index = directory / "index.json"
    return json.loads(index.read_text(encoding="utf-8")) if index.is_file() else None


def site_rel(theorem: dict) -> str:
    """The theorem's file as the site names it: its module's path under the Lean root."""
    return theorem["module"].replace(".", "/") + ".lean"


def placed(index: dict, place: Callable[[str], tuple[str, int] | None]) -> dict[str, tuple[str, int]]:
    """Where each catalogue theorem is on the site, by key (a theorem the site does not have is left out)."""
    out = {}
    for key, t in index.get("theorems", {}).items():
        where = place(f"{t['name']}@{site_rel(t)}")
        if where is not None:
            out[key] = where
    return out


def rows_at(index: dict, places: Mapping[str, tuple[str, int]]) -> dict[tuple[str, int], list[tuple[str, dict]]]:
    """For each site place, the catalogue entries that name the theorem there: ("out", row) or ("in", row)."""
    at: dict[tuple[str, int], list[tuple[str, dict]]] = {}
    for row in index.get("implications", []):
        for key in row["sources"]:
            if key in places:
                at.setdefault(places[key], []).append(("out", row))
        for key in ([row["target"]] if row["target"] else []) + row.get("restates", []):
            if key in places:
                at.setdefault(places[key], []).append(("in", row))
    return at


def theorem_block(entries: list[tuple[str, dict]], here_keys: set[str], link: Callable[[str], str], up: str, limit: int = 6) -> str:
    """The block on a theorem's page: checked connections into and out of it, routine ones only counted."""
    shown = {"out": [], "in": []}
    routine = Counter()
    for direction, row in entries:
        if row["group"] != "connection":
            routine[direction] += 1
            continue
        shown[direction].append(row)
    if not shown["out"] and not shown["in"] and not routine:
        return ""
    cat = f"{up}implications/catalogue.html"

    def item(direction: str, row: dict) -> str:
        others = [k for k in row["sources"] if k not in here_keys]
        rules = ", ".join(row["rules"])
        if direction == "out":
            with_ = (" with " + " and ".join(link(k) for k in others)) if others else ""
            end = f"gives {link(row['target'])}" if row["target"] else f"gives <code>{escape(row['statement'])}</code>"
            text = f"{'together' + with_ + ', ' if others else ''}{end}"
        else:
            srcs = " and ".join(link(k) for k in row["sources"])
            text = f"follows from {srcs}" + (" together" if len(row["sources"]) > 1 else "")
        return (f'<li>{text} <span class="muted">({escape(rules)})</span> '
                f'<span class="imp imp-kernel-checked" title="{escape(STATE_LABELS.get(row["state"], row["state"]), quote=True)}">checked</span> '
                f'<a href="{escape(cat, quote=True)}#{escape(row["id"], quote=True)}">derivation</a></li>')

    parts = []
    for direction, title in (("out", "Gives"), ("in", "Follows from")):
        rows = shown[direction]
        if rows:
            more = f'<li class="muted">and {len(rows) - limit} more in the catalogue</li>' if len(rows) > limit else ""
            parts.append(f"<p class=\"refs\"><em>{title}</em></p><ul>{''.join(item(direction, r) for r in rows[:limit])}{more}</ul>")
    if routine:
        theorem_query = quote(next(iter(sorted(here_keys))), safe="")
        parts.append(f'<p class="muted">{sum(routine.values())} more checked entries are routine (the same statement, a restatement, a generated lemma, one challenge file, a field of a structure, a route the '
                     f'released proof already takes, a duplicate): <a href="{escape(cat, quote=True)}?theorem={theorem_query}">in the catalogue</a>.</p>')
    return (f'<div class="implications"><p class="refs"><strong>Checked implications</strong> <span class="muted">(found by the '
            f'pipeline and checked by Lean\'s kernel when it ran; a recorded result, not checked again in this build: '
            f'<a href="{escape(cat, quote=True)}">what these are</a>)</span></p>{"".join(parts)}</div>')


def site_index(index: dict, places: Mapping[str, tuple[str, int]], href_from_catalogue: Callable[[tuple[str, int]], str]) -> str:
    """The index as the site serves it: each theorem with the link to its page, from the catalogue page."""
    data = dict(index)
    data["theorems"] = {k: {**t, "page": href_from_catalogue(places[k]) if k in places else ""} for k, t in index.get("theorems", {}).items()}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def catalogue_body(index: dict) -> list[str]:
    c = index.get("counts", {})
    env = index.get("environment", {})
    seen_ids: set[str] = set()
    for row in index.get("implications", []):
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise ValueError("catalogue implication id must be a nonempty string")
        if row_id in seen_ids:
            raise ValueError(f"duplicate catalogue implication id {row_id}")
        seen_ids.add(row_id)
    groups = ", ".join(f"{escape(GROUP_LABELS.get(g) or g)} {n}" for g, n in sorted(c.get("checked_by_group", {}).items()))
    by_layer = index.get("extraction") or {}
    if not by_layer and (env.get("extract_policy") or env.get("policy")):  # older catalogues kept one, in the environment
        by_layer = {"": env.get("extract_policy") or env.get("policy")}
    layers_of: dict[str, list[str]] = {}  # each rule set once, with the layers extracted under it
    for layer, p in sorted(by_layer.items()):
        if p != index.get("policy"):
            layers_of.setdefault(str(p), []).append(layer)
    named = "; ".join(escape(p) + (f" ({escape(', '.join(ls))})" if any(ls) else "") for p, ls in layers_of.items())
    extracted = f" (declarations extracted under {named})" if named else ""
    shallow = (c.get("connections_by_link") or {}).get("positivity", 0)
    by_positivity = f" ({shallow} of them linked only by a quantity's positivity, such as <code>0 &lt; x</code>)" if shallow else ""
    # Keep every published fragment valid before JavaScript runs.  The first render clears these small fallbacks and
    # replaces them with the interactive rows, so the live DOM never contains duplicate ids.
    anchors = "".join(
        f'<li id="{escape(str(row["id"]), quote=True)}"><code>{escape(str(row["id"]))}</code> '
        '<span class="muted">(load JavaScript for details)</span></li>'
        for row in index.get("implications", [])
    )
    return [
        "<h1>Checked implications</h1>",
        "<p>What the discovery pipeline found and Lean's kernel checked: from the source statements, as hypotheses, a derivation "
        "of the target's statement (or, for a composition, of the statement it gives), within a fixed set of rules and depth. "
        "Each entry shows the exact statement Lean checked, the steps, the substitutions and the assumptions it discharged. "
        "The search never finds every implication, and an implication it did not find may still hold.</p>",
        f'<p class="imp-provenance"><strong>Provenance.</strong> {escape(index.get("provenance", ""))} Rule set: {escape(str(index.get("policy", "")))}{extracted}; '
        f'{escape(str(env.get("toolchain", "")))}; Mathlib {escape(str(env.get("mathlib", ""))[:12])}; {escape(str(env.get("corpus_repo", "")))} at '
        f'{escape(str(env.get("corpus_revision", ""))[:12])}.</p>',
        f'<p>{c.get("checked", 0)} checked: {groups}. {c.get("connections", 0)} are connections{by_positivity}; the rest are routine and grouped. '
        f'{c.get("dependencies", 0)} proof dependencies were read from elaborated proof terms (a separate record). '
        f'{c.get("unresolved", 0)} attempts established nothing and {c.get("rejected", 0)} were rejected: '
        '<a href="notes.html">notes</a>.</p>',
        '<div class="cat-controls">'
        '<input id="cat-q" type="search" placeholder="theorem, module, family or conclusion" aria-label="Search">'
        '<select id="cat-group" aria-label="Group"><option value="connection">connections</option><option value="">all checked</option></select>'
        '<select id="cat-rule" aria-label="Relationship"><option value="">any relationship</option></select>'
        '<select id="cat-state" aria-label="State"><option value="">any state</option></select>'
        '<select id="cat-layer" aria-label="Corpus layer"><option value="">any layer</option></select>'
        '<select id="cat-family" aria-label="Family"><option value="">any family</option></select>'
        "</div>",
        f'<p id="cat-count" class="muted">Loading…</p><div id="cat-chain"></div><ol id="cat-list" class="cat-list">{anchors}</ol>'
        '<p><button id="cat-more" type="button" hidden>more</button></p>',
        '<noscript><p>The catalogue needs JavaScript to search; the data is <a href="catalogue/index.json">catalogue/index.json</a>.</p></noscript>',
    ]


def notes_body(index: dict, argued: list[tuple[str, str]], candidates: list[tuple[str, str]]) -> list[str]:
    c = index.get("counts", {}) if index else {}
    body = ["<h1>Implication notes</h1>",
            "<p>What is not a checked implication: attempts that established nothing, derivations rejected as routine, and the "
            "curated suggestions still without a Lean check. None of it is a claim; nothing here says an implication is false.</p>"]
    if index:
        body.append(f"<h2>Unresolved attempts ({c.get('unresolved', 0)})</h2><p class=\"muted\">No derivation within the rules and depth, "
                    "a time or heartbeat limit reached, or an environment that would not import. A limit reached means not established, "
                    "never false.</p><table><tr><th>status</th><th>reason</th><th>attempts</th></tr>")
        body += [f"<tr><td>{escape(r['status'])}</td><td>{escape(r['reason'])}</td><td>{r['count']}</td></tr>" for r in index.get("unresolved_summary", [])[:40]]
        body.append("</table>")
        body.append(f"<h2>Rejected derivations ({c.get('rejected', 0)})</h2><p class=\"muted\">Lean checked these, but they are not counted: "
                    "a source the derivation does not use, or a statement that holds without any source.</p><ul>")
        body += [f"<li>{escape(k)}: {n}</li>" for k, n in sorted(c.get("rejected_by_reason", {}).items())]
        body.append("</ul>")
        body.append('<p class="muted">Every attempt, with its reason and cost, is in the catalogue data: '
                    '<a href="catalogue/index.json">the index</a> and its shards.</p>')
    if argued:
        body.append("<h2>Argued, not checked</h2><p class=\"muted\">Curated edges whose argument is written out in words. Lean has not "
                    "checked them, so they carry no check mark.</p><ul>")
        body += [f'<li><a href="../implications.html#{escape(i, quote=True)}">{escape(i)}</a>: {escape(t)}</li>' for i, t in argued]
        body.append("</ul>")
    if candidates:
        body.append("<h2>Candidates</h2><ul>")
        body += [f'<li><a href="../implications.html#{escape(i, quote=True)}">{escape(i)}</a>: {escape(t)}</li>' for i, t in candidates]
        body.append("</ul>")
    return body


SCRIPT = r"""
(function () {
  "use strict";
  var list = document.getElementById("cat-list");
  if (!list) return;
  var q = document.getElementById("cat-q"), count = document.getElementById("cat-count"), more = document.getElementById("cat-more");
  var sel = { group: document.getElementById("cat-group"), rule: document.getElementById("cat-rule"), state: document.getElementById("cat-state"),
              layer: document.getElementById("cat-layer"), family: document.getElementById("cat-family") };
  var chainBox = document.getElementById("cat-chain");
  var index = null, shards = {}, shown = 0, rows = [], theoremKey = "";
  var LABELS = %LABELS%;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function thm(key) { return (index.theorems || {})[key] || { name: key.split(":").pop(), page: "" }; }
  function link(key) { var t = thm(key); return t.page ? '<a href="' + esc(t.page) + '"><code>' + esc(t.name) + "</code></a>" : "<code>" + esc(t.name) + "</code>"; }
  function fill(select, values) { values.sort().forEach(function (v) { var o = document.createElement("option"); o.value = v; o.textContent = v; select.appendChild(o); }); }
  function text(row) {
    var parts = [row.statement, row.group, row.rules.join(" "), (row.families || []).join(" ")];
    row.sources.concat(row.target ? [row.target] : []).concat(row.restates || []).forEach(function (k) { var t = thm(k); parts.push(k, t.name, t.module || "", t.statement || ""); });
    return parts.join(" ").toLowerCase();
  }
  function matches(row) {
    if (theoremKey && row.sources.indexOf(theoremKey) < 0 && row.target !== theoremKey &&
        (row.restates || []).indexOf(theoremKey) < 0) return false;
    if (sel.group.value && row.group !== sel.group.value) return false;
    if (sel.rule.value && row.rules.indexOf(sel.rule.value) < 0) return false;
    if (sel.state.value && row.state !== sel.state.value) return false;
    if (sel.layer.value && row.layer !== sel.layer.value) return false;
    if (sel.family.value && (row.families || []).indexOf(sel.family.value) < 0) return false;
    var words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    var t = row._text || (row._text = text(row));
    return words.every(function (w) { return t.indexOf(w) >= 0; });
  }
  function ends(row) {
    var srcs = row.sources.map(link).join(row.sources.length > 1 ? " <em>and</em> " : "");
    var joint = row.sources.length > 1 ? ' <span class="muted">(jointly: the derivation uses each)</span>' : "";
    var to = row.target ? link(row.target) : "<code>" + esc(row.statement) + "</code>" + ((row.restates || []).length ? ' <span class="muted">(the statement of ' + row.restates.map(link).join(", ") + ")</span>" : "");
    return srcs + joint + " ⟹ " + to;
  }
  function render() {
    rows = (index.implications || []).filter(matches);
    shown = 0; list.innerHTML = ""; page();
  }
  function page() {
    var stop = Math.min(rows.length, shown + 100);
    for (var i = shown; i < stop; i++) {
      var r = rows[i], li = document.createElement("li");
      li.id = r.id;
      li.innerHTML = '<div class="cat-head">' + ends(r) + '</div><div class="muted">' + esc(r.rules.join(", ")) + " · " +
        esc(LABELS.group[r.group] || r.group) + " · " + esc(LABELS.state[r.state] || r.state) +
        (r.link ? " · " + esc(r.link === "positivity" ? "linked only by a positivity fact" : "linked by " + r.link) : "") +
        ' · <button type="button" class="cat-open">details</button> <a href="#' + esc(r.id) + '">link</a></div><div class="cat-detail" hidden></div>';
      list.appendChild(li);
    }
    shown = stop;
    count.textContent = rows.length + " of " + (index.implications || []).length + " checked entries" + (rows.length > shown ? " (showing " + shown + ")" : "");
    more.hidden = shown >= rows.length;
  }
  function shard(name) {
    if (!shards[name]) shards[name] = fetch("catalogue/shards/" + name + ".json").then(function (r) { return r.json(); });
    return shards[name];
  }
  function stepText(s) {
    var subst = (s.substitutions || []).map(function (x) { return x.variable + " := " + x.value; }).join(", ");
    var what = { "apply": "apply " + (s.fact || ""), "assumption": "a hypothesis", "discharge": "discharged by " + (s.by || ""),
                 "bound transfer": "bound transfer from " + (s.fact || "") + " (" + (s.bound || "") + "), closed by " + (s["closed by"] || ""),
                 "witness transport": "the witness of " + (s.fact || ""), "rewrite": "rewrite with " + (s.fact || ""),
                 "supply": (s.from || "") + " supplies a hypothesis of " + (s.of || "") }[s.step] || s.step;
    var shown = s.goal || s.hypothesis;
    return "<li>" + esc(what) + (subst ? " <span class=\"muted\">with " + esc(subst) + "</span>" : "") + (shown ? ": <code>" + esc(shown) + "</code>" : "") + "</li>";
  }
  function open(li, row) {
    var box = li.querySelector(".cat-detail");
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false; box.textContent = "Loading…";
    shard(row.shard).then(function (data) {
      var d = (data.implications || []).filter(function (x) { return x.id === row.id; })[0];
      if (!d) { box.textContent = "Not in its shard."; return; }
      var used = d.used || [];
      box.innerHTML =
        "<dl><dt>Statement checked</dt><dd><pre>" + esc(d.statement) + "</pre></dd>" +
        "<dt>The exact contract</dt><dd><pre>" + esc(d.derived) + "</pre><span class=\"muted\">Lean's kernel checked a proof of this, with each source as a hypothesis" +
        (d.state === "checked-instantiated" ? ", then applied it to the released theorems and checked that too" : "") + ".</span></dd>" +
        "<dt>In words</dt><dd>" + d.sources.map(function (k, i) { return link(k) + (used[i] === false ? " (unused)" : ""); }).join(" and ") +
        (d.sources.length > 1 ? ", together," : "") + " give" + (d.sources.length > 1 ? "" : "s") + " " + (d.target ? link(d.target) + "'s statement" : "the statement above") +
        ", by " + esc(d.rules.join(", ")) + (d.directions.length ? " (" + esc(d.directions.join("; ")) + ")" : "") + ".</dd>" +
        "<dt>Steps</dt><dd><ol>" + (d.steps || []).map(stepText).join("") + "</ol></dd>" +
        (d.group !== "connection" ? "<dt>Grouped</dt><dd>" + esc(d.group_reason) + "</dd>" : "") +
        "<dt>Axioms</dt><dd>" + esc((d.axioms || []).join(", ") || "none") + (d.instantiated_axioms && d.instantiated_axioms.length ? "; applied to the released theorems: " + esc(d.instantiated_axioms.join(", ")) : "") + "</dd>" +
        (d.instantiation ? "<dt>Instantiation attempt</dt><dd>" + esc(LABELS.instantiation[d.instantiation.status] || "not established (" + d.instantiation.status + ")") +
          (d.instantiation.reason ? " <span class=\"muted\">(" + esc(d.instantiation.reason) + ")</span>" : "") +
          (d.instantiation.verification_sources && d.instantiation.verification_sources.length ?
            "<br><span class=\"muted\">verification inputs — source declarations: " + d.instantiation.verification_sources.map(link).join(", ") +
            (d.instantiation.verification_target ? "; target statement: " + link(d.instantiation.verification_target) : "") + "</span>" : "") +
          "; environment <code>" + esc(d.instantiation.environment.id) + "</code>, " + esc(d.instantiation.environment.modules) + " modules imported; " +
          esc(d.instantiation.cost.ms) + " ms, " + esc(d.instantiation.cost.heartbeats_thousands) + "k heartbeats</dd>" : "") +
        "<dt>Found by</dt><dd>" + esc(d.match) + (d.shared && d.shared.length ? " <span class=\"muted\">(shared constants: " + esc(d.shared.slice(0, 8).join(", ")) + ")</span>" : "") + "</dd>" +
        "<dt>Environment</dt><dd><code>" + esc(d.environment.id) + "</code>, " + esc(d.environment.modules) + " modules imported, layer " + esc(d.environment.layer) +
        "; " + esc(d.cost.ms) + " ms, " + esc(d.cost.heartbeats_thousands) + "k heartbeats</dd>" +
        "<dt>Proof term</dt><dd><details><summary>show</summary><pre>" + esc(d.proof) + "</pre></details></dd></dl>" +
        '<p><button type="button" class="cat-chain-from">chains from ' + esc(d.target ? thm(d.target).name : thm(d.sources[0]).name) + "</button></p>";
      box.querySelector(".cat-chain-from").onclick = function () { chain(d.target || d.sources[0]); };
    }, function () { box.textContent = "Could not load the details."; });
  }
  function chain(start) {
    // bounded: three steps out and three in, connections only, each multi-source step shown as a joint requirement
    var out = {}, inc = {};
    (index.implications || []).forEach(function (r) {
      if (r.group !== "connection" || !r.target) return;
      r.sources.forEach(function (s) { (out[s] = out[s] || []).push(r); });
      (inc[r.target] = inc[r.target] || []).push(r);
    });
    function walk(key, depth, seen, forward) {
      if (depth === 0) return "";
      var next = (forward ? out[key] : inc[key]) || [];
      var items = next.slice(0, 8).map(function (r) {
        var other = forward ? r.target : null;
        var joint = r.sources.length > 1 ? ' <span class="muted">(jointly with ' + r.sources.filter(function (s) { return s !== key; }).map(link).join(", ") + ")</span>" : "";
        if (forward) {
          if (seen[other]) return "<li>" + link(other) + " (already above)</li>";
          var s2 = Object.assign({}, seen); s2[other] = 1;
          return '<li><a href="#' + esc(r.id) + '">⟹</a> ' + link(other) + joint + "<ul>" + walk(other, depth - 1, s2, true) + "</ul></li>";
        }
        return '<li><a href="#' + esc(r.id) + '">⟸</a> ' + r.sources.map(link).join(" and ") + (r.sources.length > 1 ? ' <span class="muted">(both needed)</span>' : "") + "<ul>" +
          r.sources.filter(function (s) { return !seen[s]; }).map(function (s) { var s2 = Object.assign({}, seen); s2[s] = 1; return walk(s, depth - 1, s2, false); }).join("") + "</ul></li>";
      });
      return items.join("") + (next.length > 8 ? '<li class="muted">and ' + (next.length - 8) + " more</li>" : "");
    }
    var seen = {}; seen[start] = 1;
    var o = walk(start, 3, seen, true), i = walk(start, 3, seen, false);
    chainBox.innerHTML = '<div class="cat-chainbox"><p><strong>Chains around ' + link(start) + '</strong> <span class="muted">(connections only, three steps at most)</span> ' +
      '<button type="button" id="cat-chain-close">close</button></p>' +
      "<p><em>Gives</em></p><ul>" + (o || '<li class="muted">nothing found</li>') + "</ul><p><em>Follows from</em></p><ul>" + (i || '<li class="muted">nothing found</li>') + "</ul></div>";
    document.getElementById("cat-chain-close").onclick = function () { chainBox.innerHTML = ""; };
  }
  list.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest(".cat-open") : null;
    if (!b) return;
    var li = b.closest("li"), row = (index.implications || []).filter(function (r) { return r.id === li.id; })[0];
    if (row) open(li, row);
  });
  more.onclick = page;
  function showHash() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id || !(index.implications || []).some(function (r) { return r.id === id; })) return;
    var at = rows.findIndex(function (r) { return r.id === id; });
    if (at < 0) {
      theoremKey = ""; q.value = "";
      Object.keys(sel).forEach(function (k) { sel[k].value = ""; });
      render();
      at = rows.findIndex(function (r) { return r.id === id; });
    }
    while (at >= shown && shown < rows.length) page();
    var li = document.getElementById(id);
    if (li) {
      li.scrollIntoView();
      if (li.querySelector(".cat-detail").hidden) open(li, rows[at]);
    }
  }
  fetch("catalogue/index.json").then(function (r) { return r.json(); }).then(function (data) {
    index = data;
    var rules = {}, states = {}, layers = {}, fams = {};
    (index.implications || []).forEach(function (r) {
      r.rules.forEach(function (x) { rules[x] = 1; }); states[r.state] = 1; layers[r.layer] = 1; (r.families || []).forEach(function (f) { fams[f] = 1; });
    });
    fill(sel.rule, Object.keys(rules)); fill(sel.state, Object.keys(states)); fill(sel.layer, Object.keys(layers).filter(Boolean)); fill(sel.family, Object.keys(fams));
    var params = new URLSearchParams(location.search);
    if (params.get("q")) q.value = params.get("q");
    if (params.get("theorem")) { theoremKey = params.get("theorem"); sel.group.value = ""; q.value = ""; chain(theoremKey); }
    function userRender() { theoremKey = ""; render(); }
    [q].concat(Object.keys(sel).map(function (k) { return sel[k]; })).forEach(function (el) { el.addEventListener("input", userRender); el.addEventListener("change", userRender); });
    render();
    window.addEventListener("hashchange", showHash);
    showHash();
  }, function () { count.textContent = "Could not load catalogue/index.json."; });
})();
"""


def script() -> str:
    return SCRIPT.replace("%LABELS%", json.dumps({"group": GROUP_LABELS, "state": STATE_LABELS, "instantiation": INSTANTIATION_LABELS}, ensure_ascii=False))


CSS = """
.cat-controls { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.6rem 0; }
.cat-controls input { flex: 1 1 16rem; min-width: 0; }
.cat-controls select { max-width: 100%; }
ol.cat-list { padding-left: 1.4rem; }
ol.cat-list > li { margin: 0.5rem 0; overflow-wrap: anywhere; }
.cat-detail dl dt { font-weight: 600; margin-top: 0.4rem; }
.cat-detail dl dd { margin-left: 1rem; }
.cat-detail pre, .cat-chainbox pre { white-space: pre-wrap; }
.cat-chainbox { border: 1px solid var(--line); border-radius: 6px; padding: 0.4rem 0.8rem; margin: 0.6rem 0; }
.imp-provenance { border-left: 3px solid var(--line); padding-left: 0.6rem; }
"""
