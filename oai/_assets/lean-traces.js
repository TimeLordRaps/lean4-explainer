(function () {
  "use strict";
  const cache = new Map();

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function decode(response) {
    if (!response.ok) throw new Error("HTTP " + response.status);
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    if (bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
      if (typeof DecompressionStream === "undefined") {
        throw new Error("this browser cannot open gzip trace data");
      }
      const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
      return JSON.parse(await new Response(stream).text());
    }
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  function traceFile(url) {
    if (!cache.has(url)) cache.set(url, fetch(url).then(decode));
    return cache.get(url);
  }

  function goals(parent, label, values, empty) {
    parent.appendChild(element("div", "goal-label", label));
    if (!values.length) {
      parent.appendChild(element("p", "muted", empty));
      return;
    }
    for (const value of values) parent.appendChild(element("pre", "", value));
  }

  function render(details, steps) {
    const list = element("ol");
    const key = details.dataset.traceKey || "";
    const declarationLine = key.split(":", 1)[0];
    steps.forEach((step, index) => {
      const [line, tactic, before, after, source] = step;
      const item = element("li");
      item.id = "L" + declarationLine + "-step" + (index + 1);
      item.dataset.line = String(line);
      item.appendChild(element("code", "", tactic));
      item.appendChild(document.createTextNode(" "));
      const where = element(source ? "a" : "span", "ln", "line " + line);
      if (source) where.href = source;
      item.appendChild(where);
      goals(item, "before", before, "no goals");
      goals(item, "after", after, "no goals remain");
      list.appendChild(item);
    });
    details.querySelector(".trace-loading")?.replaceWith(list);
  }

  async function load(details) {
    if (details.dataset.traceState) return;
    details.dataset.traceState = "loading";
    try {
      const payload = await traceFile(details.dataset.traceSrc);
      const steps = payload.d[details.dataset.traceKey];
      if (!steps) throw new Error("trace entry is missing");
      render(details, steps);
      details.dataset.traceState = "loaded";
    } catch (error) {
      const message = element("p", "trace-error", "The checked trace could not be loaded: " + error.message);
      details.querySelector(".trace-loading")?.replaceWith(message);
      details.dataset.traceState = "error";
    }
  }

  document.addEventListener("toggle", (event) => {
    const details = event.target;
    if (details instanceof HTMLDetailsElement && details.open && details.classList.contains("trace-lazy")) load(details);
  }, true);
})();
