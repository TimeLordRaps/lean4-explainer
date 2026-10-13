
(function () {
  window.L4 = window.L4 || {};
  window.l4shard = function (key, entries) {
    window.L4[key] = entries;
  };

  for (const box of document.querySelectorAll("input[data-filter]")) {
    const scope = box.closest("main");
    const status = document.createElement("p");
    status.className = "filter-status";
    status.setAttribute("aria-live", "polite");
    box.insertAdjacentElement("afterend", status);
    function filter() {
      const q = box.value.trim().toLowerCase();
      const rows = Array.from(scope.querySelectorAll("[data-filter-rows] > li, [data-filter-rows] > div, [data-filter-rows] > tr"));
      let shown = 0;
      for (const el of rows) {
        el.hidden = q !== "" && !el.textContent.toLowerCase().includes(q);
        if (!el.hidden) shown += 1;
      }
      for (const section of scope.querySelectorAll("[data-filter-section]")) {
        const sectionRows = Array.from(section.querySelectorAll("[data-filter-rows] > li, [data-filter-rows] > div, [data-filter-rows] > tr"));
        section.hidden = q !== "" && sectionRows.length > 0 && !sectionRows.some(function (row) { return !row.hidden; });
      }
      status.textContent = q === "" ? "" : (shown === 0 ? "No matches." : shown + (shown === 1 ? " match." : " matches."));
    }
    box.addEventListener("input", filter);
    box.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && box.value !== "") {
        box.value = "";
        filter();
      }
    });
  }

  for (const row of document.querySelectorAll("ol.decls > li[id]")) {
    const code = row.querySelector(":scope > code");
    if (!code) continue;
    const link = document.createElement("a");
    link.className = "decl-link";
    link.href = "#" + row.id;
    link.setAttribute("aria-label", "Permanent link to " + code.textContent);
    code.replaceWith(link);
    link.appendChild(code);
  }

  const search = document.getElementById("q");
  if (!search) return;
  const root = document.body.dataset.root || "";
  const out = document.getElementById("results");

  const searchStatus = document.getElementById("search-status");

  function rememberQuery(value) {
    if (!window.history || !window.URL) return;
    const url = new URL(window.location.href);
    if (value) url.searchParams.set("q", value);
    else url.searchParams.delete("q");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }

  function show(words, key) {
    out.textContent = "";
    let shown = 0;
    for (const [name, file, line] of window.L4[key] || []) {
      const lower = name.toLowerCase();
      if (!words.every(function (word) { return lower.includes(word); })) continue;
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = root + window.L4F[file] + "#L" + line;
      link.textContent = name;
      item.appendChild(link);
      out.appendChild(item);
      shown += 1;
      if (shown === 200) break;
    }
    searchStatus.textContent = shown === 0 ? "No matches." : shown + (shown === 1 ? " result." : (shown === 200 ? "+ results." : " results."));
  }

  search.addEventListener("input", function () {
    const raw = search.value.trim();
    const q = raw.toLowerCase();
    rememberQuery(raw);
    out.textContent = "";
    searchStatus.textContent = "";
    if (q.length < 2) {
      searchStatus.textContent = "Type at least two characters.";
      return;
    }
    const words = q.split(/\s+/).filter(Boolean);
    const key = words[0].slice(0, 2).replace(/[^a-z0-9]/g, "_").padEnd(2, "_");
    if (window.L4[key]) {
      show(words, key);
      return;
    }
    const script = document.createElement("script");
    script.src = root + "_assets/search/s_" + key + ".js";
    script.onload = function () {
      if (search.value.trim().toLowerCase() === q) show(words, key);
    };
    script.onerror = function () {
      if (search.value.trim().toLowerCase() === q) searchStatus.textContent = "No matches.";
    };
    document.head.appendChild(script);
  });
  const initial = new URLSearchParams(window.location.search).get("q");
  if (initial) {
    search.value = initial;
    search.dispatchEvent(new Event("input"));
  }
})();
