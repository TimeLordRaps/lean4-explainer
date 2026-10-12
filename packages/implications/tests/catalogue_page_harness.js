// Runs the catalogue page's script under node, against a small stand-in for the DOM, and prints what it drew.
// usage: node catalogue_page_harness.js SCRIPT DATA_DIR ENTRY_ID [ACTIONS_JSON] [LOCATION_JSON]
// DATA_DIR holds catalogue/index.json and catalogue/shards/; the page opens ENTRY_ID as if its link were followed.
// ACTIONS_JSON is an optional array of {label, control, value, event}; controls are q/group/rule/state/layer/family.
"use strict";
const fs = require("fs");
const path = require("path");

const [script, dataDir, entry, actionsJson = "[]", locationJson = "{}"] = process.argv.slice(2);
const actions = JSON.parse(actionsJson);
const initialLocation = JSON.parse(locationJson);
const byId = {};
const windowListeners = {};

function detach(node) {
  (node.children || []).forEach(detach);
  if (node.id && byId[node.id] === node) delete byId[node.id];
}

function element(id, hidden) {
  let html = "";
  const out = {
    id: id || "", value: id === "cat-group" ? "connection" : "", hidden: !!hidden,
    textContent: "", children: [], listeners: {}, parts: {},
    appendChild(child) { this.children.push(child); if (child.id) byId[child.id] = child; return child; },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    // an element's parts are made when first asked for; the entry's detail box starts hidden, as the page's HTML has it
    querySelector(selector) { return this.parts[selector] || (this.parts[selector] = element("", selector === ".cat-detail")); },
    scrollIntoView() {},
  };
  Object.defineProperty(out, "innerHTML", {
    get() { return html; },
    set(value) {
      html = String(value);
      if (html === "") {
        out.children.forEach(detach);
        out.children = [];
      }
    },
  });
  return out;
}

global.document = {
  getElementById(id) { return byId[id] || (byId[id] = element(id)); },
  createElement() { return element(); },
};
global.window = { addEventListener(type, handler) { windowListeners[type] = handler; } };
global.location = {
  search: initialLocation.search || "",
  hash: Object.hasOwn(initialLocation, "hash") ? initialLocation.hash : "#" + entry,
};
global.fetch = (url) => Promise.resolve({ json: () => Promise.resolve(JSON.parse(fs.readFileSync(path.join(dataDir, url), "utf8"))) });

eval(fs.readFileSync(script, "utf8"));

function snapshot(label) {
  const visible = byId["cat-list"].children.map((child) => child.id);
  const selected = decodeURIComponent(global.location.hash.replace(/^#/, "")) || entry;
  const li = byId["cat-list"].children.find((child) => child.id === selected);
  return {
    ...(label ? { label } : {}),
    count: byId["cat-count"].textContent,
    visible,
    hash: global.location.hash,
    head: li ? li.innerHTML : null,
    detail: li ? li.querySelector(".cat-detail").innerHTML : null,
  };
}

setTimeout(async () => {
  const initial = snapshot();
  const observed = [];
  const controls = { q: "cat-q", group: "cat-group", rule: "cat-rule", state: "cat-state", layer: "cat-layer", family: "cat-family" };
  for (const action of actions) {
    if (action.control === "hash") {
      global.location.hash = action.value;
      if (windowListeners.hashchange) windowListeners.hashchange({ type: "hashchange" });
      await new Promise((resolve) => setTimeout(resolve, 0));
      observed.push(snapshot(action.label));
      continue;
    }
    const control = byId[controls[action.control]];
    if (!control) throw new Error("unknown catalogue control: " + action.control);
    control.value = action.value;
    const event = action.event || (action.control === "q" ? "input" : "change");
    if (!control.listeners[event]) throw new Error("catalogue control has no " + event + " listener: " + action.control);
    control.listeners[event]({ target: control });
    await new Promise((resolve) => setTimeout(resolve, 0));
    observed.push(snapshot(action.label));
  }
  // Keep the original top-level fields for callers that predate action support.
  process.stdout.write(JSON.stringify({ ...initial, initial, actions: observed }));
}, 300);
