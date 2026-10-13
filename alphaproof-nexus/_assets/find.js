
(function () {
  var box = document.getElementById("name");
  var out = document.getElementById("result");
  function go(name) {
    name = decodeURIComponent((name || "").replace(/^[#?]/, "").replace(/^name=/, "")).trim();
    if (!name) { return; }
    box.value = name;
    var table = window.L4Names || {};
    var at = table[name];
    if (at) { location.replace(at); return; }
    out.textContent = "No declaration named " + name + " on this site.";
  }
  window.addEventListener("hashchange", function () { go(location.hash); });
  document.getElementById("go").addEventListener("submit", function (e) { e.preventDefault(); go(box.value); });
  go(location.hash || location.search);
})();
