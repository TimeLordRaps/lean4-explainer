// Checks map.js's layout from the outside: argv[2] is map.js, argv[3] a JSON file of cases. Prints JSON results.
// Each path is sampled point by point (the curves included), so "no arrow through a box" is measured, not assumed.
"use strict";
const fs = require("fs");
const M = require(process.argv[2]);
const input = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function sample(points) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    const [px, py] = points[i - 1];
    const [qx, qy] = points[i];
    for (let s = 0; s <= 24; s++) {
      const t = s / 24;
      if (i % 2 === 0) {  // the curve across a gap: control points at the middle of the gap, at each end's height
        const mx = (px + qx) / 2;
        const u = 1 - t;
        out.push([u * u * u * px + 3 * u * u * t * mx + 3 * u * t * t * mx + t * t * t * qx,
                  u * u * u * py + 3 * u * u * t * py + 3 * u * t * t * qy + t * t * t * qy]);
      } else out.push([px + (qx - px) * t, py + (qy - py) * t]);
    }
  }
  return out;
}

function check(c) {
  const nodes = c.sizes.map(([w, h]) => ({ w, h }));
  const lay = M.layout(nodes, c.edges);
  const boxes = lay.boxes;
  const overlaps = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlaps.push([i, j]);
    }
  }
  const through = [];
  const leftward = [];
  for (const route of lay.routes) {
    const pts = sample(route.points);
    for (let k = 1; k < route.points.length; k++) {
      if (route.points[k][0] < route.points[k - 1][0] - 1e-6) { leftward.push(route.edge); break; }
    }
    const hit = boxes.findIndex((b) => pts.some(([x, y]) => x > b.x + 0.5 && x < b.x + b.w - 0.5 && y > b.y + 0.5 && y < b.y + b.h - 0.5));
    if (hit >= 0) through.push([route.edge, hit]);
  }
  const inside = boxes.every((b) => b.x >= 0 && b.y >= 0 && b.x + b.w <= lay.width + 1e-6 && b.y + b.h <= lay.height + 1e-6);
  return { overlaps, through, leftward, inside, crossings: lay.crossings, initialCrossings: lay.initialCrossings };
}

if (Array.isArray(input)) {
  process.stdout.write(JSON.stringify(input.map(check)));
} else {
  const names = input.labels;
  const items = names.map((name, i) => ({ name, href: "#L" + (i + 1), here: i === 2 }));
  const svg = M.svg(items, [[0, 2, 0], [1, 2, 1], [2, 3, 0]], "a test");
  process.stdout.write(JSON.stringify({ labels: M.labels(names), svg }));
}
