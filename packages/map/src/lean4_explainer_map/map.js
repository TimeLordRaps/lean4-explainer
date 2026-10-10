/* lean4-explainer map: draws how declarations (or files) build on each other, as a layered diagram.

   The layout is the classic one for dependency drawings (Sugiyama's): cycles are broken, every node gets a column
   so that each arrow points right, an arrow that skips columns is threaded through placeholder points, the order
   inside each column is chosen to cross as few arrows as possible, and rows are placed near their neighbours.
   Arrows run straight across a column (between the boxes) and curve only in the gaps between columns, so an arrow
   never passes through a box. Colours come from the page's theme. The same file runs under node for the tests. */
(function () {
  "use strict";

  // ---------------------------------------------------------------- layout
  // nodes: [{w, h}]; edges: [[from, to]], drawn as an arrow from -> to. Returns boxes, arrow paths and the size.
  function layout(nodes, edges, options) {
    const o = Object.assign({ gapX: 56, gapY: 14, dummyGap: 6, margin: 6, sweeps: 12 }, options || {});
    const n = nodes.length;
    const E = [];
    const seen = new Set();
    edges.forEach(([a, b], k) => {
      const key = a + ">" + b;
      if (a === b || seen.has(key) || a < 0 || b < 0 || a >= n || b >= n) return;
      seen.add(key);
      E.push({ a, b, k, rev: false });
    });

    // 1. cycles: a depth-first search turns each back edge around, which leaves a graph without cycles
    const out = Array.from({ length: n }, () => []);
    E.forEach((e, i) => out[e.a].push(i));
    const state = new Array(n).fill(0);
    const visit = new Array(n).fill(0);
    let clock = 0;
    for (let s = 0; s < n; s++) {
      if (state[s]) continue;
      const stack = [[s, 0]];
      state[s] = 1;
      visit[s] = clock++;
      while (stack.length) {
        const top = stack[stack.length - 1];
        if (top[1] < out[top[0]].length) {
          const e = E[out[top[0]][top[1]++]];
          if (state[e.b] === 1) e.rev = true;
          else if (state[e.b] === 0) { state[e.b] = 1; visit[e.b] = clock++; stack.push([e.b, 0]); }
        } else {
          state[top[0]] = 2;
          stack.pop();
        }
      }
    }
    const from = (e) => (e.rev ? e.b : e.a);
    const to = (e) => (e.rev ? e.a : e.b);

    // 2. columns: the longest path from a source, then each node pulled right next to the nearest node it feeds
    const preds = Array.from({ length: n }, () => []);
    const succs = Array.from({ length: n }, () => []);
    E.forEach((e) => { succs[from(e)].push(to(e)); preds[to(e)].push(from(e)); });
    const indeg = preds.map((p) => p.length);
    const topo = [];
    const queue = [];
    for (let v = 0; v < n; v++) if (!indeg[v]) queue.push(v);
    while (queue.length) {
      const v = queue.shift();
      topo.push(v);
      for (const w of succs[v]) if (--indeg[w] === 0) queue.push(w);
    }
    const layer = new Array(n).fill(0);
    for (const v of topo) for (const w of succs[v]) layer[w] = Math.max(layer[w], layer[v] + 1);
    for (let i = topo.length - 1; i >= 0; i--) {
      const v = topo[i];
      if (succs[v].length) layer[v] = Math.min.apply(null, succs[v].map((w) => layer[w])) - 1;
    }
    const L = n ? Math.max.apply(null, layer) + 1 : 0;

    // 3. arrows that skip columns go through one placeholder per column crossed
    const all = nodes.map((node, v) => ({ w: node.w, h: node.h, layer: layer[v], dummy: false, order: visit[v] }));
    const up = Array.from({ length: n }, () => []);
    const down = Array.from({ length: n }, () => []);
    const link = (u, v) => { down[u].push(v); up[v].push(u); };
    E.forEach((e) => {
      const chain = [from(e)];
      for (let l = layer[from(e)] + 1; l < layer[to(e)]; l++) {
        all.push({ w: 0, h: 0, layer: l, dummy: true, order: all[from(e)].order });
        up.push([]);
        down.push([]);
        chain.push(all.length - 1);
      }
      chain.push(to(e));
      for (let i = 0; i + 1 < chain.length; i++) link(chain[i], chain[i + 1]);
      e.chain = chain;
    });
    const layers = Array.from({ length: L }, () => []);
    all.forEach((node, v) => layers[node.layer].push(v));
    layers.forEach((col) => col.sort((a, b) => all[a].order - all[b].order));

    // 4. order inside each column: barycentre sweeps, keeping the order with the fewest crossings
    const pos = new Array(all.length).fill(0);
    const place = () => layers.forEach((col) => col.forEach((v, i) => { pos[v] = i; }));
    place();
    const crossings = () => {
      let count = 0;
      for (let l = 0; l + 1 < L; l++) {
        const segs = [];
        for (const u of layers[l]) for (const v of down[u]) segs.push([pos[u], pos[v]]);
        for (let i = 0; i < segs.length; i++) {
          for (let j = i + 1; j < segs.length; j++) {
            if ((segs[i][0] - segs[j][0]) * (segs[i][1] - segs[j][1]) < 0) count++;
          }
        }
      }
      return count;
    };
    let best = crossings();
    const initialCrossings = best;
    let bestOrder = layers.map((col) => col.slice());
    for (let sweep = 0; sweep < o.sweeps && best > 0; sweep++) {
      const downward = sweep % 2 === 0;
      const range = downward ? [...Array(L).keys()].slice(1) : [...Array(L).keys()].reverse().slice(1);
      for (const l of range) {
        const col = layers[l];
        const key = new Map();
        for (const v of col) {
          const near = downward ? up[v] : down[v];
          key.set(v, near.length ? near.reduce((s, u) => s + pos[u], 0) / near.length : pos[v]);
        }
        col.sort((a, b) => key.get(a) - key.get(b) || pos[a] - pos[b]);
        col.forEach((v, i) => { pos[v] = i; });
      }
      const c = crossings();
      if (c < best) { best = c; bestOrder = layers.map((col) => col.slice()); }
    }
    bestOrder.forEach((col, l) => { layers[l] = col; });
    place();

    // 5. coordinates: columns as wide as their widest box; rows pulled towards their neighbours, order kept
    const colW = layers.map((col) => Math.max(0, ...col.map((v) => all[v].w)));
    const colX = [];
    let x = o.margin;
    for (let l = 0; l < L; l++) { colX.push(x); x += colW[l] + o.gapX; }
    const width = x - o.gapX + o.margin;
    const cy = new Array(all.length).fill(0);
    const sep = (a, b) => all[a].h / 2 + all[b].h / 2 + (all[a].dummy && all[b].dummy ? o.dummyGap : o.gapY);
    const pack = (col, want) => {
      const k = col.length;
      if (!k) return;
      const f = want.slice();
      for (let i = 1; i < k; i++) f[i] = Math.max(want[i], f[i - 1] + sep(col[i - 1], col[i]));
      const b = want.slice();
      for (let i = k - 2; i >= 0; i--) b[i] = Math.min(want[i], b[i + 1] - sep(col[i], col[i + 1]));
      const mid = f.map((value, i) => (value + b[i]) / 2);
      for (let i = 1; i < k; i++) mid[i] = Math.max(mid[i], mid[i - 1] + sep(col[i - 1], col[i]));
      col.forEach((v, i) => { cy[v] = mid[i]; });
    };
    layers.forEach((col) => pack(col, col.map((v, i) => i * 40)));
    for (let pass = 0; pass < 8; pass++) {
      const order = pass % 2 === 0 ? [...Array(L).keys()] : [...Array(L).keys()].reverse();
      for (const l of order) {
        const col = layers[l];
        pack(col, col.map((v) => {
          const near = up[v].concat(down[v]);
          return near.length ? near.reduce((s, u) => s + cy[u], 0) / near.length : cy[v];
        }));
      }
    }
    const top = Math.min(...all.map((node, v) => cy[v] - node.h / 2));
    const bottom = Math.max(...all.map((node, v) => cy[v] + node.h / 2));
    const shift = o.margin - (Number.isFinite(top) ? top : 0);
    for (let v = 0; v < all.length; v++) cy[v] += shift;
    const height = (Number.isFinite(bottom) ? bottom - top : 0) + 2 * o.margin;
    const box = (v) => ({ x: colX[all[v].layer] + (colW[all[v].layer] - all[v].w) / 2, y: cy[v] - all[v].h / 2, w: all[v].w, h: all[v].h });

    // 6. arrows: straight inside a column, a curve across each gap; ports spread along each box's side
    const ports = (v, side) => {
      const list = E.filter((e) => (side === "out" ? e.chain[0] === v : e.chain[e.chain.length - 1] === v));
      const other = (e) => cy[side === "out" ? e.chain[1] : e.chain[e.chain.length - 2]];
      list.sort((p, q) => other(p) - other(q));
      const span = all[v].h * 0.6;
      list.forEach((e, i) => {
        const offset = list.length > 1 ? -span / 2 + (span * i) / (list.length - 1) : 0;
        e[side] = cy[v] + offset;
      });
    };
    for (let v = 0; v < n; v++) { ports(v, "out"); ports(v, "in"); }
    const routes = E.map((e) => {
      const pts = [];
      const first = box(e.chain[0]);
      pts.push([first.x + first.w, e.out], [colX[all[e.chain[0]].layer] + colW[all[e.chain[0]].layer], e.out]);
      for (const d of e.chain.slice(1, -1)) {
        const l = all[d].layer;
        pts.push([colX[l], cy[d]], [colX[l] + colW[l], cy[d]]);
      }
      const last = box(e.chain[e.chain.length - 1]);
      pts.push([colX[all[e.chain[e.chain.length - 1]].layer], e.in], [last.x, e.in]);
      let d = "M" + r(pts[0][0]) + " " + r(pts[0][1]);
      for (let i = 1; i < pts.length; i++) {
        const [px, py] = pts[i - 1];
        const [qx, qy] = pts[i];
        if (i % 2 === 0) {  // across a gap between columns
          const mx = (px + qx) / 2;
          d += " C" + r(mx) + " " + r(py) + " " + r(mx) + " " + r(qy) + " " + r(qx) + " " + r(qy);
        } else d += " L" + r(qx) + " " + r(qy);
      }
      return { edge: e.k, d, reversed: e.rev, points: pts };
    });
    return { boxes: nodes.map((node, v) => box(v)), layer: layer.slice(), routes, width, height, crossings: best, initialCrossings };
  }
  function r(value) {
    return Math.round(value * 10) / 10;
  }

  // ---------------------------------------------------------------- labels
  // The last part of each name; more parts where two boxes would otherwise read the same.
  function labels(names) {
    const parts = names.map((name) => String(name).split("."));
    const depth = parts.map(() => 1);
    for (let round = 0; round < 4; round++) {
      const shown = parts.map((p, i) => p.slice(-depth[i]).join("."));
      const count = new Map();
      shown.forEach((s) => count.set(s, (count.get(s) || 0) + 1));
      let changed = false;
      shown.forEach((s, i) => { if (count.get(s) > 1 && depth[i] < parts[i].length) { depth[i]++; changed = true; } });
      if (!changed) break;
    }
    return parts.map((p, i) => shorten(p.slice(-depth[i]).join("."), 34));
  }
  function shorten(s, max) {
    const chars = Array.from(s);
    if (chars.length <= max) return s;
    const keep = max - 1;
    return chars.slice(0, Math.ceil(keep / 2)).join("") + "…" + chars.slice(chars.length - Math.floor(keep / 2)).join("");
  }
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---------------------------------------------------------------- drawing
  let measureCtx = null;
  function textWidth(text) {
    if (typeof document !== "undefined") {
      if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
      if (measureCtx) {
        measureCtx.font = "13px system-ui, -apple-system, 'Segoe UI', sans-serif";
        return measureCtx.measureText(text).width;
      }
    }
    return Array.from(text).length * 7.4;
  }
  let drawn = 0;
  // items: [{name, label?, href, here, title}]; edges: [[from, to, declared]]
  function svg(items, edges, aria) {
    const shown = labels(items.map((item) => item.label || item.name));
    const nodes = shown.map((text) => ({ w: Math.max(56, Math.ceil(textWidth(text)) + 22), h: 26 }));
    const lay = layout(nodes, edges.map((e) => [e[0], e[1]]));
    const id = "dm" + (++drawn);
    const parts = [
      '<svg class="depmap-svg" xmlns="http://www.w3.org/2000/svg" width="' + Math.ceil(lay.width) + '" height="' + Math.ceil(lay.height) +
        '" viewBox="0 0 ' + Math.ceil(lay.width) + " " + Math.ceil(lay.height) + '" role="img" aria-label="' + esc(aria) + '">',
      '<defs><marker id="' + id + 'a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto-start-reverse">' +
        '<path class="tip" d="M0 0 L10 5 L0 10 z"/></marker></defs>',
    ];
    for (const route of lay.routes) {
      const e = edges[route.edge];
      const weight = e[3] > 1 ? ' style="--w:' + r(Math.min(4.5, 1.3 + Math.log2(e[3]) * 0.55)) + 'px"' : "";  // how many uses it stands for
      parts.push('<path class="e' + (e[2] ? " declared" : "") + '" data-a="' + e[0] + '" data-b="' + e[1] + '"' + weight + ' d="' + route.d + '" ' +
        (route.reversed ? 'marker-start="url(#' + id + 'a)"' : 'marker-end="url(#' + id + 'a)"') + "/>");
    }
    items.forEach((item, v) => {
      const b = lay.boxes[v];
      const node = '<g class="n' + (item.here ? " here" : "") + '" data-v="' + v + '"><title>' + esc(item.title || item.name) + "</title>" +
        '<rect x="' + r(b.x) + '" y="' + r(b.y) + '" width="' + r(b.w) + '" height="' + r(b.h) + '" rx="6"/>' +
        '<text x="' + r(b.x + b.w / 2) + '" y="' + r(b.y + b.h / 2) + '" text-anchor="middle" dominant-baseline="central">' + esc(shown[v]) + "</text></g>";
      parts.push(item.href && !item.here ? '<a href="' + esc(item.href) + '">' + node + "</a>" : node);
    });
    parts.push("</svg>");
    return parts.join("");
  }
  // light up a box's arrows while the pointer is on it; a drawing a little too wide is scaled to fit (a lot: it scrolls)
  const SHRINK = 0.8;
  function wire(root) {
    const drawing = root.querySelector("svg.depmap-svg");
    const room = root.clientWidth;
    if (drawing && room) {
      const natural = Number(drawing.getAttribute("width"));
      if (natural > room && room / natural >= SHRINK) {
        drawing.setAttribute("width", String(room));
        drawing.setAttribute("height", String(Math.round((Number(drawing.getAttribute("height")) * room) / natural)));
      }
    }
    root.querySelectorAll("g.n").forEach((g) => {
      const v = g.getAttribute("data-v");
      const lit = (on) => root.querySelectorAll('path.e[data-a="' + v + '"], path.e[data-b="' + v + '"]').forEach((p) => p.classList.toggle("lit", on));
      g.addEventListener("mouseenter", () => lit(true));
      g.addEventListener("mouseleave", () => lit(false));
    });
  }

  // ---------------------------------------------------------------- a declaration's map, on its file page
  function bootDeclarations() {
    const holder = document.getElementById("map-data");
    if (!holder) return;
    const data = JSON.parse(holder.textContent);
    for (const [line, here, flat, usesCount, usedByCount, moreUp, moreDown] of data.d) {
      const li = document.getElementById("L" + line);
      if (!li) continue;
      const box = document.createElement("details");
      box.className = "depmap";
      const parts = [];
      if (usesCount) parts.push("builds on " + usesCount);
      if (usedByCount) parts.push("used by " + usedByCount);
      box.innerHTML = "<summary>Map: " + parts.join(", ") + "</summary>";
      box.addEventListener("toggle", () => {
        if (box.dataset.drawn) return;
        box.dataset.drawn = "1";
        const ids = [];
        const local = new Map();
        const edges = [];
        for (let i = 0; i < flat.length; i += 3) {
          for (const g of [flat[i], flat[i + 1]]) if (!local.has(g)) { local.set(g, ids.length); ids.push(g); }
          edges.push([local.get(flat[i]), local.get(flat[i + 1]), flat[i + 2]]);
        }
        if (!local.has(here)) { local.set(here, ids.length); ids.push(here); }
        const items = ids.map((g) => ({ name: data.n[g][0], href: data.n[g][1], here: g === here }));
        const declared = edges.some((e) => e[2]);
        const wrap = document.createElement("div");
        wrap.className = "depmap-wrap";
        wrap.innerHTML = svg(items, edges, "Map around " + data.n[here][0]);
        box.appendChild(wrap);
        const legend = document.createElement("p");
        legend.className = "depmap-legend";
        const left = [];
        if (moreUp) left.push("the " + (usesCount - moreUp) + " most-used of the " + usesCount + " results it builds on");
        if (moreDown) left.push("the " + (usedByCount - moreDown) + " most-used of the " + usedByCount + " that use it");
        legend.textContent = "An arrow goes from a result to one that uses it, so what this builds on is to the left and what uses it to the right." +
          " The farther boxes are one more step away." +
          (declared ? " Dashed arrows are prerequisites named in the explanations." : "") +
          (left.length ? " Drawn: " + left.join(", and ") + "." : "") +
          " Boxes are links; point at one to light up its arrows.";
        box.appendChild(legend);
        wire(wrap);
      });
      li.appendChild(box);
    }
  }

  // ---------------------------------------------------------------- the project page: folders, and files around one
  const NEAR = 8, FAR = 6;
  function folderOf(rel, depth) {
    const dirs = rel.split("/").slice(0, -1);
    return dirs.slice(0, depth).join("/") || "(top level)";
  }
  function bootProject() {
    const holder = document.getElementById("project-map-data");
    const root = document.getElementById("project-map");
    if (!holder || !root) return;
    const data = JSON.parse(holder.textContent);
    const files = data.f;
    const edges = data.e;
    if (!edges.length) return;
    const used = new Map(), uses = new Map();
    for (const [a, b] of edges) {
      if (!used.has(a)) used.set(a, []);
      used.get(a).push(b);
      if (!uses.has(b)) uses.set(b, []);
      uses.get(b).push(a);
    }
    const degree = (f) => (used.get(f) || []).length + (uses.get(f) || []).length;

    // folders: as deep as keeps the drawing to about forty boxes
    let depth = 1;
    for (let d = 1; d <= 6; d++) {
      if (new Set(files.map((f) => folderOf(f[0], d))).size <= 40) depth = d;
      else break;
    }
    const folderIndex = new Map();
    const folders = [];
    files.forEach((f) => {
      const name = folderOf(f[0], depth);
      if (!folderIndex.has(name)) { folderIndex.set(name, folders.length); folders.push({ name, files: 0, decls: 0 }); }
      folders[folderIndex.get(name)].files++;
      folders[folderIndex.get(name)].decls += f[2];
    });
    const folderEdges = new Map();
    for (const [a, b, w] of edges) {
      const fa = folderIndex.get(folderOf(files[a][0], depth)), fb = folderIndex.get(folderOf(files[b][0], depth));
      if (fa !== fb) folderEdges.set(fa + ">" + fb, (folderEdges.get(fa + ">" + fb) || 0) + w);
    }
    const linked = new Set();
    folderEdges.forEach((w, key) => key.split(">").forEach((x) => linked.add(Number(x))));
    const shownFolders = folders.map((f, i) => i).filter((i) => linked.has(i));
    const local = new Map(shownFolders.map((f, i) => [f, i]));
    const folderItems = shownFolders.map((i) => ({
      name: folders[i].name, label: folders[i].name.split("/").slice(-2).join("/"),
      href: folders[i].name === "(top level)" ? "index.html" : folders[i].name.split("/").map(encodeURIComponent).join("/") + "/index.html",
      title: folders[i].name + ": " + folders[i].files + " files, " + folders[i].decls + " declarations",
    }));
    const folderLinks = [];
    folderEdges.forEach((w, key) => { const [a, b] = key.split(">").map(Number); folderLinks.push([local.get(a), local.get(b), 0, w]); });

    root.innerHTML = "<h2>Folders</h2><p class=\"muted\">Each box is a folder; an arrow means something in one folder is used in the other, and a thicker arrow stands for more uses. Boxes link to the folder.</p>" +
      '<div class="depmap-wrap" id="folder-map"></div>' +
      "<h2>Files around one file</h2>" +
      '<div class="controls"><label for="map-focus">File:</label><input type="search" id="map-focus" list="map-files" placeholder="type a file name"><datalist id="map-files"></datalist></div>' +
      '<div class="depmap-wrap" id="file-map"></div><p class="depmap-legend">Two steps back (what it builds on) and two steps on (what uses it); the most-connected files are drawn. A thicker arrow stands for more uses.</p>';
    const folderMap = root.querySelector("#folder-map");
    if (folderItems.length) { folderMap.innerHTML = svg(folderItems, folderLinks, "Folders and how they use each other"); wire(folderMap); }
    else folderMap.innerHTML = '<p class="muted">All the links are inside one folder.</p>';

    const list = root.querySelector("#map-files");
    const byPath = new Map(files.map((f, i) => [f[0], i]));
    list.innerHTML = files.filter((f, i) => degree(i)).map((f) => '<option value="' + esc(f[0]) + '">').join("");
    const rank = (xs) => xs.slice().sort((a, b) => degree(b) - degree(a) || a - b);
    const drawFile = (focus) => {
      const back1 = rank(uses.get(focus) || []).slice(0, NEAR);
      const on1 = rank(used.get(focus) || []).slice(0, NEAR);
      const taken = new Set([focus, ...back1, ...on1]);
      const back2 = rank([...new Set(back1.flatMap((f) => uses.get(f) || []))].filter((f) => !taken.has(f))).slice(0, FAR);
      back2.forEach((f) => taken.add(f));
      const on2 = rank([...new Set(on1.flatMap((f) => used.get(f) || []))].filter((f) => !taken.has(f))).slice(0, FAR);
      const chosen = [focus, ...back1, ...on1, ...back2, ...on2];
      const at = new Map(chosen.map((f, i) => [f, i]));
      const links = edges.filter(([a, b]) => at.has(a) && at.has(b)).map(([a, b, w]) => [at.get(a), at.get(b), 0, w]);
      const items = chosen.map((f) => ({ name: files[f][0], label: files[f][0].replace(/\.lean$/, "").split("/").slice(-2).join("/"), href: files[f][1], here: f === focus, title: files[f][0] + " (" + files[f][2] + " declarations)" }));
      const target = root.querySelector("#file-map");
      target.innerHTML = svg(items, links, "Files around " + files[focus][0]);
      wire(target);
    };
    const input = root.querySelector("#map-focus");
    const start = rank(files.map((f, i) => i))[0];
    input.value = files[start][0];
    drawFile(start);
    input.addEventListener("change", () => { if (byPath.has(input.value)) drawFile(byPath.get(input.value)); });
  }

  const api = { layout, labels, svg, shorten };
  if (typeof module === "object" && module.exports) module.exports = api;
  else if (typeof document !== "undefined") {
    const boot = () => { bootDeclarations(); bootProject(); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
  }
})();
