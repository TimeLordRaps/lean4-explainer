
(function () {
  "use strict";
  var list = document.getElementById("cat-list");
  if (!list) return;
  var q = document.getElementById("cat-q"), count = document.getElementById("cat-count"), more = document.getElementById("cat-more");
  var sel = { group: document.getElementById("cat-group"), rule: document.getElementById("cat-rule"), state: document.getElementById("cat-state"),
              layer: document.getElementById("cat-layer"), family: document.getElementById("cat-family") };
  var chainBox = document.getElementById("cat-chain");
  var index = null, shards = {}, shown = 0, rows = [], theoremKey = "";
  var LABELS = {"group": {"connection": "connection", "same statement": "same statement as the source", "restatement": "the source restated (same proposition up to definitions)", "generated": "uses a lemma Lean generated (no stated result)", "one challenge": "within one challenge file", "in the released proof": "the released proof already goes this way", "source uses the target": "the source's released proof uses the target", "reverse direction": "other direction of an equivalence", "structure field": "through a structure's field (what its objects carry by definition)", "duplicate": "derives a statement already listed"}, "state": {"checked-instantiated": "kernel-checked, applied to the released theorems", "checked-derivation": "kernel-checked, sources as hypotheses"}, "instantiation": {"checked-instantiated": "checked: the derivation applied to the released theorems, each from the module that proves it", "instantiation-circular": "circular: the released proof of a source already uses the target", "budget": "not established: the attempt ran out of its time or heartbeat budget", "error": "not established: Lean stopped with an error", "no-proof": "not established: no proof was found within the rules", "audit-failed": "not established: the proof found did not pass the audit"}};
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
