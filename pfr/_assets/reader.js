/* lean4-explainer reader: a plain-English reading of each declaration.

   For every declaration on a file page it says what the statement claims in words, lists what is given and assumed,
   and walks through the proof one tactic at a time, saying what each step does. The statement and the assumptions are
   read from the source text. Each proof step is read from the goals Lean reports before and after it when the Lean
   extension ran for the site (its tactic traces are on the page); otherwise, or for a step Lean has no goals for, from the
   text of the tactic, and the step says so. This script never runs Lean. The same code runs in the browser and under
   node for the tests. */
(function () {
  "use strict";
  const SOURCE_URL_TEMPLATE = "";

  // ---------------------------------------------------------------- text helpers
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function squash(s) {
    return String(s).replace(/\s+/g, " ").trim();
  }
  function code(s) {
    return "<code>" + esc(squash(s)) + "</code>";
  }

  // Typeset mathematics: lean2tex turns a Lean term into LaTeX, and the page draws it with KaTeX. The Lean code stays
  // inside as the fallback (no JavaScript for KaTeX, or a term lean2tex cannot read) and as the hover title.
  let lean2tex = null;
  function translator() {
    if (!lean2tex) {
      if (typeof module === "object" && module.exports) { try { lean2tex = require("./lean2tex.js"); } catch (e) { lean2tex = false; } }
      else lean2tex = (typeof self !== "undefined" && self.Lean2TeX) || false;
    }
    return lean2tex || null;
  }
  function texOf(s, options) {
    const t = translator();
    return t ? t.toTex(String(s), options) : null;  // line breaks kept: they end `let` lines
  }
  function math(s, options) {
    const tex = texOf(s, options);
    return tex ? "<span class=\"m\" data-tex=\"" + esc(tex) + "\" title=\"Lean: " + esc(squash(s)) + "\">" + code(s) + "</span>" : code(s);
  }
  function displayMath(tex, s) {
    return "<div class=\"rd-math\" data-tex=\"" + esc(tex) + "\" title=\"Lean: " + esc(squash(s)) + "\">" + code(s) + "</div>";
  }

  // Blank out comments and string contents, keeping every newline and every code unit's position.
  function mask(text) {
    const out = [];
    const n = text.length;
    let i = 0;
    while (i < n) {
      const c = text[i];
      if (c === "-" && text[i + 1] === "-") {
        while (i < n && text[i] !== "\n") { out.push(" "); i++; }
        continue;
      }
      if (c === "/" && text[i + 1] === "-") {
        let depth = 0;
        while (i < n) {
          if (text[i] === "/" && text[i + 1] === "-") { depth++; out.push("  "); i += 2; continue; }
          if (text[i] === "-" && text[i + 1] === "/") { depth--; out.push("  "); i += 2; if (depth === 0) break; continue; }
          out.push(text[i] === "\n" ? "\n" : " ");
          i++;
        }
        continue;
      }
      if (c === '"' && !(text[i - 1] === "'" && text[i + 1] === "'")) {
        out.push('"');
        i++;
        while (i < n && text[i] !== '"') {
          if (text[i] === "\\") { out.push(text[i + 1] === "\n" ? " \n" : "  "); i += 2; continue; }
          out.push(text[i] === "\n" ? "\n" : " ");
          i++;
        }
        if (i < n) { out.push('"'); i++; }
        continue;
      }
      out.push(c);
      i++;
    }
    return out.join("");
  }

  const OPEN = "([{⟨⦃";
  const CLOSE = ")]}⟩⦄";

  // Index of the first position at bracket depth 0 where `test(i)` holds, or -1.
  function scanTop(s, test, from) {
    let depth = 0;
    for (let i = from || 0; i < s.length; i++) {
      const c = s[i];
      if (OPEN.indexOf(c) >= 0) { depth++; continue; }
      if (CLOSE.indexOf(c) >= 0) { depth = Math.max(0, depth - 1); continue; }
      if (depth === 0 && test(i)) return i;
    }
    return -1;
  }
  function matching(s, at) {
    let depth = 0;
    for (let i = at; i < s.length; i++) {
      if (OPEN.indexOf(s[i]) >= 0) depth++;
      else if (CLOSE.indexOf(s[i]) >= 0) { depth--; if (depth === 0) return i; }
    }
    return -1;
  }
  function stripParens(s) {
    s = s.trim();
    while (s[0] === "(" && matching(s, 0) === s.length - 1) s = s.slice(1, -1).trim();
    return s;
  }
  function startsWord(s, i, word) {
    if (s.substr(i, word.length) !== word) return false;
    const before = i === 0 ? " " : s[i - 1];
    const after = s[i + word.length] === undefined ? " " : s[i + word.length];
    return !/[\w'.]/.test(before) && !/[\w'!?]/.test(after);
  }
  // Split on a top-level separator (a fixed string), keeping brackets intact.
  function splitTop(s, sep) {
    const parts = [];
    let last = 0;
    let at = scanTop(s, (i) => s.substr(i, sep.length) === sep);
    while (at >= 0) {
      parts.push(s.slice(last, at));
      last = at + sep.length;
      at = scanTop(s, (i) => s.substr(i, sep.length) === sep, last);
    }
    parts.push(s.slice(last));
    return parts;
  }
  // Where a binder (∀, ∃, fun, λ) starts at top level: everything after it is its body.
  function binderLimit(s) {
    const at = scanTop(s, (i) => /[∀∃λ]/.test(s[i]) || startsWord(s, i, "fun"));
    return at < 0 ? s.length : at;
  }

  // ---------------------------------------------------------------- words for types, classes and predicates
  const TYPES = {
    "ℕ": "a natural number (0, 1, 2, …)", "Nat": "a natural number (0, 1, 2, …)",
    "ℤ": "an integer", "Int": "an integer",
    "ℚ": "a rational number (a fraction)", "Rat": "a rational number (a fraction)",
    "ℝ": "a real number", "Real": "a real number",
    "ℂ": "a complex number", "Complex": "a complex number",
    "ℕ+": "a positive whole number", "ℝ≥0": "a real number that is at least 0", "NNReal": "a real number that is at least 0",
    "ℝ≥0∞": "a number from 0 to ∞, ∞ included", "ENNReal": "a number from 0 to ∞, ∞ included",
    "EReal": "a real number or ±∞", "Prop": "a statement (something true or false)", "Bool": "true or false",
    "Type": "a type (a collection of objects)", "Type*": "a type (a collection of objects)",
    "Type _": "a type (a collection of objects)", "Type u": "a type (a collection of objects)",
    "Type v": "a type (a collection of objects)", "Sort*": "a type (a collection of objects)", "String": "a piece of text",
  };
  const TYPE_FORMS = [
    [/^Fin\s+(.+)$/, (m) => "a number from 0 up to " + code(m[1]) + " − 1"],
    [/^Finset\s+(.+)$/, (m) => "a finite set of elements of " + code(m[1])],
    [/^Set\s+(.+)$/, (m) => "a set of elements of " + code(m[1])],
    [/^List\s+(.+)$/, (m) => "a list of elements of " + code(m[1])],
    [/^Multiset\s+(.+)$/, (m) => "a finite collection of elements of " + code(m[1]) + ", repeats allowed"],
    [/^Option\s+(.+)$/, (m) => "either nothing or an element of " + code(m[1])],
    [/^ZMod\s+(.+)$/, (m) => "an integer modulo " + code(m[1])],
    [/^(?:Polynomial\s+(.+)|(.+)\[X\])$/, (m) => "a polynomial with coefficients in " + code(m[1] || m[2])],
    [/^Matrix\s+(\S+)\s+(\S+)\s+(.+)$/, (m) => "a matrix with rows " + code(m[1]) + ", columns " + code(m[2]) + " and entries in " + code(m[3])],
    [/^Equiv\.Perm\s+(.+)$/, (m) => "a permutation (reordering) of " + code(m[1])],
    [/^SimpleGraph\s+(.+)$/, (m) => "a graph whose vertices are the elements of " + code(m[1])],
    [/^(?:MeasureTheory\.)?Measure\s+(.+)$/, (m) => "a measure on " + code(m[1]) + " (a way to give sets a size)"],
    [/^EuclideanSpace\s+ℝ\s+\(Fin\s+(.+)\)$/, (m) => "a point in " + code(m[1]) + "-dimensional space"],
    [/^(?:Ideal|Subgroup|Submodule|Subring|Subfield|IntermediateField)\b/, (m, t) => "a " + t.split(/\s/)[0].toLowerCase().replace("intermediatefield", "intermediate field") + " (" + code(t) + ")"],
  ];
  function typeWords(t) {
    t = stripParens(squash(t));
    if (TYPES[t]) return TYPES[t];
    if (/^(Type|Sort)\b/.test(t)) return TYPES["Type"];
    // Top-level → and × first: `Fin 4 → ℝ × ℝ` is a function, not a `Fin` of "4 → ℝ × ℝ".
    const arrows = splitTop(t, "→");
    if (arrows.length > 1 && arrows.every((p) => p.trim()))
      return "a function that takes " + arrows.slice(0, -1).map((p) => code(p)).join(", then ") + " and gives " + code(arrows[arrows.length - 1]);
    const pair = splitTop(t, "×");
    if (pair.length > 1 && pair.every((p) => p.trim())) return "a pair (" + pair.map((p) => code(p)).join(", ") + ")";
    for (const [re, say] of TYPE_FORMS) {
      const m = t.match(re);
      if (m) return say(m, t);
    }
    return "a value of type " + code(t);
  }

  const CLASSES = {
    Fintype: (a) => code(a) + " has finitely many elements",
    Finite: (a) => code(a) + " has finitely many elements",
    DecidableEq: (a) => "equality between elements of " + code(a) + " can be checked",
    DecidablePred: (a) => "whether " + code(a) + " holds can be checked",
    Field: (a) => code(a) + " is a field: you can add, subtract, multiply and divide (except by 0)",
    CommRing: (a) => code(a) + " is a commutative ring: you can add, subtract and multiply, and order of multiplication does not matter",
    Ring: (a) => code(a) + " is a ring: you can add, subtract and multiply",
    CommSemiring: (a) => code(a) + " has addition and commutative multiplication",
    Semiring: (a) => code(a) + " has addition and multiplication",
    Group: (a) => code(a) + " is a group: you can multiply and undo multiplication",
    CommGroup: (a) => code(a) + " is a commutative group",
    AddGroup: (a) => code(a) + " is a group under addition",
    AddCommGroup: (a) => code(a) + " is a commutative group under addition",
    Monoid: (a) => code(a) + " has a multiplication with a 1",
    Module: (a) => code(a) + " is a module (a vector space when the scalars form a field)",
    NormedAddCommGroup: (a) => code(a) + " has a length (norm) for its elements",
    NormedSpace: (a) => code(a) + " is a vector space with lengths",
    InnerProductSpace: (a) => code(a) + " has angles and lengths (an inner product)",
    MetricSpace: (a) => code(a) + " has a distance between any two points",
    TopologicalSpace: (a) => code(a) + " has a notion of nearness (open sets)",
    MeasurableSpace: (a) => code(a) + " has measurable sets",
    LinearOrder: (a) => "any two elements of " + code(a) + " can be compared",
    PartialOrder: (a) => code(a) + " has an order (some pairs may be incomparable)",
    Nontrivial: (a) => code(a) + " has at least two different elements",
    CharZero: (a) => "in " + code(a) + ", 1 + 1 + … + 1 is never 0",
    NeZero: (a) => code(a) + " is not 0",
    Fact: (a) => "it is known that " + code(a),
    Nonempty: (a) => code(a) + " has at least one element",
    Inhabited: (a) => code(a) + " has a chosen default element",
    Countable: (a) => code(a) + " is countable",
  };

  function fnName(f) { return code(f); }
  const PREDICATES = {
    Injective: (a) => fnName(a[a.length - 1]) + " is injective: different inputs always give different outputs",
    Surjective: (a) => fnName(a[a.length - 1]) + " is surjective: every possible output is reached",
    Bijective: (a) => fnName(a[a.length - 1]) + " is a bijection: a perfect one-to-one pairing",
    Continuous: (a) => fnName(a[a.length - 1]) + " is continuous: no jumps or breaks",
    ContinuousOn: (a) => fnName(a[0]) + " is continuous on " + code(a[1] || "?"),
    ContinuousAt: (a) => fnName(a[0]) + " is continuous at " + code(a[1] || "?"),
    Differentiable: (a) => fnName(a[a.length - 1]) + " is differentiable: it has a derivative everywhere",
    DifferentiableAt: (a) => fnName(a[a.length - 2] || "?") + " has a derivative at " + code(a[a.length - 1]),
    DifferentiableOn: (a) => fnName(a[a.length - 2] || "?") + " has a derivative at every point of " + code(a[a.length - 1]),
    HasDerivAt: (a) => fnName(a[0]) + " has derivative " + code(a[1] || "?") + " at " + code(a[2] || "?"),
    Monotone: (a) => fnName(a[a.length - 1]) + " never decreases: a bigger input gives an output at least as big",
    StrictMono: (a) => fnName(a[a.length - 1]) + " is strictly increasing: a bigger input gives a bigger output",
    Antitone: (a) => fnName(a[a.length - 1]) + " never increases",
    StrictAnti: (a) => fnName(a[a.length - 1]) + " is strictly decreasing",
    MonotoneOn: (a) => fnName(a[0]) + " never decreases on " + code(a[1] || "?"),
    Prime: (a) => code(a[a.length - 1]) + " is a prime number",
    Even: (a) => code(a[a.length - 1]) + " is even",
    Odd: (a) => code(a[a.length - 1]) + " is odd",
    IsSquare: (a) => code(a[a.length - 1]) + " is a perfect square",
    Squarefree: (a) => code(a[a.length - 1]) + " is squarefree: no square bigger than 1 divides it",
    Irrational: (a) => code(a[a.length - 1]) + " is irrational: not a fraction of two integers",
    Coprime: (a) => code(a[0]) + " and " + code(a[1] || "?") + " are coprime: no common factor bigger than 1",
    Tendsto: (a) => fnName(a[0]) + " tends to " + limitWords(a[2]) + " " + approachWords(a[1]),
    Summable: (a) => "the series of the terms " + code(a[a.length - 1]) + " adds up to a finite value",
    HasSum: (a) => "the terms " + code(a[0]) + " add up to " + code(a[1] || "?"),
    IsLeast: (a) => code(a[1] || "?") + " is the least element of " + code(a[0]),
    IsGreatest: (a) => code(a[1] || "?") + " is the greatest element of " + code(a[0]),
    IsLUB: (a) => code(a[1] || "?") + " is the least upper bound of " + code(a[0]),
    IsGLB: (a) => code(a[1] || "?") + " is the greatest lower bound of " + code(a[0]),
    BddAbove: (a) => code(a[a.length - 1]) + " is bounded above",
    BddBelow: (a) => code(a[a.length - 1]) + " is bounded below",
    Finite: (a) => code(a[a.length - 1]) + " is finite",
    Infinite: (a) => code(a[a.length - 1]) + " is infinite",
    Nonempty: (a) => code(a[a.length - 1]) + " is not empty",
    Countable: (a) => code(a[a.length - 1]) + " is countable",
    Measurable: (a) => fnName(a[a.length - 1]) + " is measurable",
    Integrable: (a) => fnName(a[0]) + " is integrable (its integral is finite)",
    IntervalIntegrable: (a) => fnName(a[0]) + " can be integrated from " + code(a[2] || "?") + " to " + code(a[3] || "?"),
    IsOpen: (a) => code(a[a.length - 1]) + " is an open set",
    IsClosed: (a) => code(a[a.length - 1]) + " is a closed set",
    IsCompact: (a) => code(a[a.length - 1]) + " is compact (closed and bounded, in ℝⁿ)",
    Dense: (a) => code(a[a.length - 1]) + " is dense: it comes arbitrarily close to every point",
    Periodic: (a) => fnName(a[0]) + " repeats every " + code(a[1] || "?"),
    IsUnit: (a) => code(a[a.length - 1]) + " has a multiplicative inverse",
    Irreducible: (a) => code(a[a.length - 1]) + " is irreducible: it cannot be factored into smaller non-units",
    MeasurableSet: (a) => code(a[a.length - 1]) + " is a measurable set (one that has a size)",
    Disjoint: (a) => code(a[0]) + " and " + code(a[1] || "?") + " have nothing in common",
    ContDiff: (a) => fnName(a[a.length - 1]) + " is smooth: it can be differentiated " + code(a[a.length - 2] || "n") + " times, continuously",
    ContDiffAt: (a) => fnName(a[a.length - 2] || "?") + " is smooth at " + code(a[a.length - 1]),
    ContinuousWithinAt: (a) => fnName(a[0]) + " is continuous at " + code(a[2] || "?") + " within " + code(a[1] || "?"),
    UniformContinuous: (a) => fnName(a[a.length - 1]) + " is uniformly continuous",
    IntegrableOn: (a) => fnName(a[0]) + " is integrable on " + code(a[1] || "?"),
    MemLp: (a) => fnName(a[0]) + " is in Lᵖ for p = " + code(a[1] || "?") + " (the p-th power of |f| has a finite integral)",
    AEMeasurable: (a) => fnName(a[0]) + " is measurable, apart from a set of measure zero",
    AEStronglyMeasurable: (a) => fnName(a[0]) + " is (strongly) measurable, apart from a set of measure zero",
    StronglyMeasurable: (a) => fnName(a[0]) + " is strongly measurable",
    MeasurePreserving: (a) => fnName(a[0]) + " preserves the measure: sets keep their size",
    Transcendental: (a) => code(a[a.length - 1]) + " is transcendental: not a root of any nonzero polynomial with integer coefficients",
    IsAlgebraic: (a) => code(a[a.length - 1]) + " is algebraic: a root of a nonzero polynomial",
    IsCoprime: (a) => code(a[0]) + " and " + code(a[1] || "?") + " are coprime",
    Collinear: (a) => "the points " + code(a[a.length - 1]) + " lie on one line",
    Commute: (a) => code(a[0]) + " and " + code(a[1] || "?") + " commute: their product is the same in either order",
    Pairwise: (a) => "every two different elements are related by " + code(a[a.length - 1]),
    Perm: (a) => code(a[0]) + " is a rearrangement of " + code(a[1] || "?"),
    InjOn: (a) => fnName(a[0]) + " is injective on " + code(a[1] || "?") + ": different inputs there give different outputs",
    SurjOn: (a) => fnName(a[0]) + " maps " + code(a[1] || "?") + " onto all of " + code(a[2] || "?"),
    BijOn: (a) => fnName(a[0]) + " pairs " + code(a[1] || "?") + " one-to-one with " + code(a[2] || "?"),
    MapsTo: (a) => fnName(a[0]) + " sends every element of " + code(a[1] || "?") + " into " + code(a[2] || "?"),
    LipschitzWith: (a) => fnName(a[1] || "?") + " never stretches distances by more than a factor " + code(a[0]),
    Involutive: (a) => "applying " + fnName(a[a.length - 1]) + " twice gives back the input",
    LeftInverse: (a) => code(a[0]) + " undoes " + code(a[1] || "?") + ": applying " + code(a[1] || "?") + " then " + code(a[0]) + " gives back the input",
    RightInverse: (a) => code(a[0]) + " is a right inverse of " + code(a[1] || "?"),
    IndepFun: (a) => "the random variables " + code(a[0]) + " and " + code(a[1] || "?") + " are independent",
    iIndepFun: (a) => "the random variables " + code(a[a.length - 2] || a[0]) + " are independent",
    IdentDistrib: (a) => code(a[0]) + " and " + code(a[1] || "?") + " have the same distribution",
    Reachable: (a) => "there is a path from " + code(a[0]) + " to " + code(a[1] || "?"),
    Primrec: (a) => fnName(a[a.length - 1]) + " is primitive recursive (computable by a simple kind of program)",
    Computable: (a) => fnName(a[a.length - 1]) + " is computable",
    Colorable: (a) => "the graph can be colored with " + code(a[a.length - 1]) + " colors so that neighbors get different colors",
    IsProbabilityMeasure: (a) => code(a[a.length - 1]) + " is a probability measure: the whole space has size 1",
    Sbtw: (a) => code(a[2] || "?") + " lies strictly between " + code(a[1] || "?") + " and " + code(a[3] || "?"),
    Wbtw: (a) => code(a[2] || "?") + " lies between " + code(a[1] || "?") + " and " + code(a[3] || "?"),
    LinearIndependent: (a) => "the vectors " + code(a[a.length - 1]) + " are linearly independent",
    Convex: (a) => code(a[a.length - 1]) + " is convex: it contains the segment between any two of its points",
    ConvexOn: (a) => fnName(a[a.length - 1]) + " is convex on " + code(a[a.length - 2] || "?") + ": its graph bends upward",
    ConcaveOn: (a) => fnName(a[a.length - 1]) + " is concave on " + code(a[a.length - 2] || "?") + ": its graph bends downward",
    IsBigO: (a) => fnName(a[1] || "?") + " is at most a constant times " + fnName(a[2] || "?") + " (big O)",
    IsLittleO: (a) => fnName(a[1] || "?") + " is negligible compared with " + fnName(a[2] || "?") + " (little o)",
    IsConnected: (a) => code(a[a.length - 1]) + " is connected: it is all in one piece",

  };
  const NAMESPACES = new Set(["Nat", "Int", "Rat", "Real", "Complex", "Set", "Finset", "List", "Function", "Polynomial", "Matrix", "Filter", "MeasureTheory", "ProbabilityTheory", "Group", "Algebra", "Module", "Ideal", "Subgroup", "Finite", "Fintype", "Fin", "ZMod", "Asymptotics", "Topology", "Metric", "EuclideanGeometry", "SimpleGraph", "Equiv", "Multiset", "Order", "Monotone", "Continuous", "Differentiable", "HasDerivAt", "IsLocalMin", "IsLocalMax", "ENNReal", "NNReal", "EReal", "Std", "Lean", "Mathlib"]);
  function limitWords(l) {
    if (!l) return "a limit";
    l = stripParens(l);
    if (l === "atTop") return "infinity";
    if (l === "atBot") return "minus infinity";
    const m = l.match(/^(?:𝓝|nhds)\s+(.+)$/);
    if (m) return code(m[1]);
    return code(l);
  }
  function approachWords(l) {
    if (!l) return "";
    l = stripParens(l);
    if (l === "atTop") return "as the input grows without bound";
    if (l === "atBot") return "as the input goes to minus infinity";
    const m = l.match(/^(?:𝓝|nhds)\s+(.+)$/);
    if (m) return "as the input approaches " + code(m[1]);
    const w = l.match(/^(?:𝓝\[[^\]]*\]|nhdsWithin)\s+(.+)$/);
    if (w) return "as the input approaches " + code(w[1]) + " (from one side or within a set)";
    return "along " + code(l);
  }

  // ---------------------------------------------------------------- statements in words
  const RELATIONS = [
    ["≠", "is not equal to"], ["≤", "is at most"], ["≥", "is at least"], ["<=", "is at most"], [">=", "is at least"],
    ["=", "equals"], ["<", "is less than"], [">", "is greater than"], ["∣", "divides"], ["∈", "is an element of"],
    ["∉", "is not an element of"], ["⊆", "is a subset of"], ["⊂", "is a proper subset of"], ["≡", "is congruent to"],
  ];
  function findRelation(s, limit) {
    let best = null;
    scanTop(s, (i) => {
      if (i >= limit) return true;
      for (const [op, words] of RELATIONS) {
        if (s.substr(i, op.length) !== op) continue;
        const prev = s[i - 1], next = s[i + op.length];
        if (op === "=" && (prev === ":" || prev === "=" || prev === "<" || prev === ">" || prev === "!" || next === ">" || next === "=")) continue;
        if (op === "<" && (next === "|" || next === ";" || next === "$" || next === "*" || next === "-" || next === "=" || next === ">")) continue;
        if (op === ">" && (prev === "-" || prev === "=" || prev === "|" || prev === "<" || next === "=")) continue;
        best = { at: i, op, words };
        return true;
      }
      return false;
    });
    return best;
  }
  function headArgs(s) {
    const args = [];
    let i = 0;
    while (i < s.length) {
      while (s[i] === " ") i++;
      if (i >= s.length) break;
      if (OPEN.indexOf(s[i]) >= 0) {
        const j = matching(s, i);
        const end = j < 0 ? s.length - 1 : j;
        args.push(s.slice(i, end + 1));
        i = end + 1;
      } else {
        let j = i;
        while (j < s.length && s[j] !== " " && OPEN.indexOf(s[j]) < 0) j++;
        args.push(s.slice(i, j));
        i = j;
      }
    }
    return args;
  }
  function humanize(pred) {
    return pred.replace(/'/g, "").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/([A-Z])([A-Z][a-z])/g, "$1 $2").toLowerCase();
  }
  const ADJECTIVE = /^(Is|Has)?[A-Z][a-z]*(able|ible|ive|al|ic|ent|ant|ous|ar|ed|ite|ete|ary|ory|free|less)$/;
  function propertyWords(pred, subject, more) {
    const tail = more.length ? " (with " + more.map((a) => code(a)).join(", ") + ")" : "";
    if (/^Is[A-Z]/.test(pred)) return code(subject) + " is " + humanize(pred.slice(2)) + tail;
    if (/^Has[A-Z]/.test(pred)) return code(subject) + " has " + humanize(pred.slice(3)) + tail;
    if (ADJECTIVE.test(pred)) return code(subject) + " is " + humanize(pred) + tail;
    return "the property " + code(pred) + " holds for " + code(subject) + tail;
  }
  function predicateWords(s) {
    const args = glueCalls(headArgs(s));
    if (!args.length) return null;
    let head = args[0].replace(/^@/, "");
    let rest = args.slice(1);
    // a property of a value written with a dot: `S.Finite`, `G.Reachable u v`, `{n | …}.Infinite`
    const prop = head.match(/^([\s\S]+)\.([A-Z][\w']*)$/);
    if (prop && (/^[a-z({⟨↑]/.test(prop[1]) || (!rest.length && !NAMESPACES.has(prop[1])) || /^[A-Z][\w₀-₉']{0,2}$/.test(prop[1]) && !NAMESPACES.has(prop[1]))) {
      const say = PREDICATES[prop[2]];
      if (say) return say([prop[1]].concat(rest));
      return propertyWords(prop[2], prop[1], rest);
    }
    // dot notation: `p.Prime`, `f.Injective`, `a.Coprime b`
    const dot = head.match(/^(.+)\.([A-Z][\w']*)$/);
    if (dot && PREDICATES[dot[2]] && /^[a-z(]/.test(dot[1])) {
      rest = [dot[1]].concat(rest);
      head = dot[2];
    }
    const last = head.split(".").pop();
    const say = PREDICATES[last];
    if (!say || !rest.length) {
      // Only the conventional `IsFoo x`/`HasFoo x` shapes justify property prose.
      // An unknown multi-argument predicate such as `ExistsAME 11 5` must remain
      // `ExistsAME(11, 5)`: choosing its last argument as a subject changes meaning.
      if (rest.length && /^(Is|Has)[A-Z]/.test(last)) return propertyWords(last, rest[rest.length - 1], rest.slice(0, -1));
      if (rest.length && /^[A-Z]/.test(last)) return code(head + "(" + rest.join(", ") + ")") + " holds";
      return null;
    }
    // explicit type arguments (Differentiable ℝ f): drop number-type words
    const filtered = rest.filter((a) => !/^(ℝ|ℂ|ℚ|ℤ|ℕ|𝕜)$/.test(a));
    return say(filtered.length ? filtered : rest);
  }
  function quantifierVars(v) {
    v = squash(v);
    const groups = [];
    if (/^[([{⦃]/.test(v)) {
      let i = 0;
      while (i < v.length) {
        if (OPEN.indexOf(v[i]) >= 0) {
          const j = matching(v, i);
          groups.push(v.slice(i + 1, j < 0 ? v.length : j));
          i = j < 0 ? v.length : j + 1;
        } else i++;
      }
    } else groups.push(v);
    return groups.map((g) => {
      const colon = scanTop(g, (i) => g[i] === ":" && g[i + 1] !== "=");
      if (colon >= 0) return names(g.slice(0, colon)) + " (" + typeWords(g.slice(colon + 1)) + ")";
      const rel = findRelation(g, g.length);
      if (rel) return math(g.slice(0, rel.at)) + " " + (rel.op === "∈" ? "in" : rel.words) + " " + math(g.slice(rel.at + rel.op.length));
      return names(g);
    }).join(" and ");
  }
  function names(s) {
    const parts = squash(s).split(" ").filter(Boolean);
    return parts.map((p) => code(p)).join(", ");
  }

  // `let x := v; body` (or a new line for the `;`): x, v and the body.
  const LET_RE = /^\s*let(?:I)?\s+([^\n;:=]*?)\s*(?::[^\n;=]*)?:=\s*([^\n;]*?)\s*(?:;|\n)([\s\S]*)$/;
  // `open Foo in term` only makes Foo's names short inside the term.
  const OPEN_IN = /^\s*open\s+(?:scoped\s+)?[^\n()]*?(?:\([^)]*\)\s*)?\bin\s+/;

  function sayProp(s, depth) {
    depth = depth || 0;
    const lt = String(s).match(LET_RE);
    if (lt && depth < 6) return "with " + math(lt[1]) + " standing for " + math(lt[2]) + ", " + sayProp(lt[3], depth + 1);
    s = stripParens(squash(s));
    if (!s) return "";
    if (depth > 5) return code(s);
    const q = s.match(/^(∀|∃!|∃)\s*/);
    if (q) {
      const comma = scanTop(s, (i) => s[i] === ",", q[0].length);
      if (comma > 0) {
        const vars = quantifierVars(s.slice(q[0].length, comma));
        const body = sayProp(s.slice(comma + 1), depth + 1);
        if (q[1] === "∀") return "for every " + vars + ", " + body;
        if (q[1] === "∃!") return "there is exactly one " + vars + " such that " + body;
        return "there is " + vars + " such that " + body;
      }
    }
    const limit = binderLimit(s);
    const before = (sep) => splitTop(s, sep).length > 1 && s.indexOf(sep) < limit;
    for (const sep of ["↔", "<->"]) {
      if (before(sep)) {
        const at = scanTop(s, (i) => s.substr(i, sep.length) === sep);
        return sayProp(s.slice(0, at), depth + 1) + " exactly when " + sayProp(s.slice(at + sep.length), depth + 1);
      }
    }
    for (const sep of ["→", "->"]) {
      if (before(sep)) {
        const parts = [];
        let rest = s;
        let at = scanTop(rest, (i) => rest.substr(i, sep.length) === sep);
        while (at >= 0 && at < binderLimit(rest)) {
          parts.push(rest.slice(0, at));
          rest = rest.slice(at + sep.length);
          at = scanTop(rest, (i) => rest.substr(i, sep.length) === sep);
        }
        return "if " + parts.map((p) => sayProp(p, depth + 1)).join(", and ") + ", then " + sayProp(rest, depth + 1);
      }
    }
    for (const [sep, word] of [["∨", "or"], ["∧", "and"]]) {
      if (before(sep)) {
        const parts = splitTop(s.slice(0, limit), sep);
        parts[parts.length - 1] += s.slice(limit);
        return parts.map((p) => sayProp(p, depth + 1)).join(", " + word + " ");
      }
    }
    if (/^¬/.test(s)) return "it is not true that " + sayProp(s.slice(1), depth + 1);
    const mod = s.match(/^(.+?)≡(.+)\[(Z?MOD|PMOD|SMOD)\s+(.+)\]$/);
    if (mod) return math(mod[1]) + " and " + math(mod[2]) + " leave the same remainder when divided by " + math(mod[4]);
    const rel = findRelation(s, limit);
    if (rel) return math(s.slice(0, rel.at)) + " " + rel.words + " " + math(s.slice(rel.at + rel.op.length));
    if (s === "True") return "always true";
    if (s === "False") return "false: a contradiction";
    const pred = predicateWords(s);
    if (pred) return pred;
    return math(s) + " holds";
  }

  // ---------------------------------------------------------------- symbols a beginner may not know
  const SYMBOLS = [
    [/ℕ/, "ℕ", "the natural numbers 0, 1, 2, … (in Lean ℕ starts at 0)"],
    [/ℤ/, "ℤ", "the integers …, −2, −1, 0, 1, 2, …"],
    [/ℚ/, "ℚ", "the rational numbers (fractions)"],
    [/ℝ/, "ℝ", "the real numbers"],
    [/ℂ/, "ℂ", "the complex numbers"],
    [/∀/, "∀", "“for every”"],
    [/∃!/, "∃!", "“there is exactly one”"],
    [/∃(?!!)/, "∃", "“there exists”"],
    [/¬/, "¬", "“not”"],
    [/∧/, "∧", "“and”"],
    [/∨/, "∨", "“or”"],
    [/→/, "→", "“implies”, or for functions “to”"],
    [/↔/, "↔", "“if and only if”: both directions hold"],
    [/∣/, "∣", "“divides”: a ∣ b means b is a multiple of a"],
    [/∑/, "∑", "a sum over a range or a finite set"],
    [/∏/, "∏", "a product over a range or a finite set"],
    [/∫/, "∫", "an integral"],
    [/(^|[^\w])deriv\b/, "deriv", "the derivative"],
    [/√|Real\.sqrt/, "√", "square root"],
    [/‖/, "‖x‖", "the norm (length) of x"],
    [/\|[^|]+\|/, "|x|", "absolute value"],
    [/⌊/, "⌊x⌋", "floor: the largest integer at most x"],
    [/⌈/, "⌈x⌉", "ceiling: the smallest integer at least x"],
    [/⁻¹/, "x⁻¹", "the inverse, 1 / x for numbers"],
    [/∘/, "f ∘ g", "composition: first g, then f"],
    [/↑/, "↑x", "x viewed in a bigger number system, such as a natural number as a real number"],
    [/%/, "%", "remainder after division"],
    [/ \/ /, "/", "division; on ℕ and ℤ it rounds down"],
    [/\^/, "^", "a power"],
    [/!/, "n !", "factorial: 1 · 2 · … · n"],
    [/choose/, "choose", "binomial coefficient: the number of ways to pick k things from n"],
    [/Finset\.range/, "Finset.range n", "the numbers 0, 1, …, n − 1"],
    [/Set\.Icc/, "Set.Icc a b", "the closed interval [a, b]"],
    [/Set\.Ioo/, "Set.Ioo a b", "the open interval (a, b)"],
    [/#|Finset\.card|\.card/, "#s, card", "the number of elements"],
    [/𝓝|nhds/, "𝓝 x", "“near x”: used for limits"],
    [/atTop/, "atTop", "“as the input goes to infinity”"],
    [/fun |λ/, "fun x ↦ …", "a function: send x to …"],
    [/π|Real\.pi/, "π", "pi"],
    [/Real\.exp|rexp/, "exp", "the exponential function eˣ"],
    [/Real\.log/, "log", "the natural logarithm"],
    [/gcd/, "gcd", "greatest common divisor"],
    [/lcm/, "lcm", "least common multiple"],
    [/≡/, "≡ [MOD n]", "same remainder when divided by n"],
    [/\{[^}|]*\|/, "{x | p x}", "the set of all x with property p"],
    [/answer\(/, "answer(…)", "marks the answer the problem asks for; answer(sorry) means the answer is not filled in"],
    [/≪/, "f ≪ g", "f is at most a constant times g (for large inputs)"],
    [/=O\[/, "f =O[l] g", "big O: f is at most a constant times g, along l"],
    [/=o\[/, "f =o[l] g", "little o: f is negligible compared with g, along l"],
    [/\.Infinite|Set\.Infinite/, ".Infinite", "the set has infinitely many elements"],
    [/\.Finite|Set\.Finite/, ".Finite", "the set has finitely many elements"],
    [/×/, "A × B", "pairs (a, b) with a from A and b from B"],
    [/∩/, "∩", "intersection: what both sets have in common"],
    [/∪/, "∪", "union: everything in either set"],
    [/ᶜ/, "sᶜ", "the complement: everything not in s"],
    [/⁻¹'/, "f ⁻¹' s", "the preimage: all inputs that f sends into s"],
    [/''/, "f '' s", "the image: all outputs f gives on s"],
  ];
  function symbolsIn(s) {
    return SYMBOLS.filter(([re]) => re.test(s)).map(([, sym, words]) => [sym, words]);
  }

  // ---------------------------------------------------------------- declaration header
  const HEAD_RE = /^\s*((?:@\[[^\]]*\]\s*)*)((?:(?:private|protected|noncomputable|partial|unsafe|nonrec|scoped|local)\s+)*)(theorem|lemma|def|abbrev|structure|class inductive|class|inductive|instance|axiom|opaque|example|problem|determine|irreducible_def)\b/;

  function splitHeader(m) {
    const head = m.match(HEAD_RE);
    if (!head) return null;
    const kind = head[3];
    let p = head[0].length;
    let name = "";
    const nm = m.slice(p).match(/^[ \t]+([^\s:(){}\[\]⦃|⟨]+)/);
    if (nm && !(kind === "instance" && /^\(priority/.test(m.slice(p).trim()))) {
      name = nm[1];
      p += nm[0].length;
    }
    if (kind === "instance" && /^\s*\(priority/.test(m.slice(p))) {
      const open = m.indexOf("(", p);
      p = matching(m, open) + 1;
      const again = m.slice(p).match(/^[ \t]+([^\s:(){}\[\]⦃|⟨]+)/);
      if (again) { name = again[1]; p += again[0].length; }
    }
    // the body: `:=`, `where`, or match arms `|` starting a line
    const ownedByLet = (i) => {
      const from = Math.max(m.lastIndexOf("\n", i), m.lastIndexOf(";", i), m.lastIndexOf(",", i), p);
      return /(^|[\s(])(let|letI|have|set)\s+[^;\n]*$/.test(m.slice(from, i));
    };
    const bodyAt = scanTop(m, (i) =>
      (m[i] === ":" && m[i + 1] === "=" && !ownedByLet(i)) || startsWord(m, i, "where") ||
      (m[i] === "|" && /\n\s*$/.test(m.slice(Math.max(p, i - 200), i))), p);
    const header = bodyAt < 0 ? m.slice(p) : m.slice(p, bodyAt);
    let body = "", bodyKind = "none";
    if (bodyAt >= 0) {
      if (m[bodyAt] === ":") { body = m.slice(bodyAt + 2); bodyKind = "term"; }
      else if (m[bodyAt] === "w") { body = m.slice(bodyAt + 5); bodyKind = "where"; }
      else { body = m.slice(bodyAt); bodyKind = "arms"; }
    }
    // binders, then the type after a top-level colon
    const binders = [];
    let type = "", extendsPart = "";
    let i = 0;
    while (i < header.length) {
      const c = header[i];
      if (/\s/.test(c)) { i++; continue; }
      if ("([{⦃".indexOf(c) >= 0) {
        const j = matching(header, i);
        if (j < 0) break;
        binders.push({ bracket: c, inner: header.slice(i + 1, j) });
        i = j + 1;
        continue;
      }
      if (c === ":") { type = header.slice(i + 1); break; }
      if (startsWord(header, i, "extends")) {
        const colon = scanTop(header, (k) => header[k] === ":", i);
        extendsPart = colon < 0 ? header.slice(i + 7) : header.slice(i + 7, colon);
        if (colon >= 0) type = header.slice(colon + 1);
        break;
      }
      i++;
    }
    return { kind, name, binders, type: type.trim(), body, bodyKind, extendsPart: squash(extendsPart) };
  }

  function looksLikeProp(t, name) {
    t = squash(t);
    if (/^(∀|∃|¬)/.test(t)) return true;
    if (findRelation(t, binderLimit(t))) return true;
    if (/[↔∧∨]/.test(t)) return true;
    const head = t.split(/[\s(]/)[0].split(".").pop();
    if (PREDICATES[head]) return true;
    if (/\.(Prime|Coprime|Injective|Surjective|Bijective)\b/.test(t)) return true;
    return /^h([A-Z0-9_'₀-₉]|[a-z]{0,3}$|$)/.test(name || "") && !/^(Type|Sort)/.test(t);
  }

  function givenItems(binders) {
    const items = [];
    for (const b of binders) {
      const inner = squash(b.inner);
      const colon = scanTop(inner, (i) => inner[i] === ":" && inner[i + 1] !== "=");
      if (b.bracket === "[") {
        const cls = colon >= 0 ? inner.slice(colon + 1).trim() : inner;
        const args = headArgs(cls);
        const say = CLASSES[(args[0] || "").split(".").pop()];
        items.push(say ? "using that " + say(args.slice(1).join(" ") || "it") : "using the structure " + code(cls) + " (Lean finds it automatically)");
        continue;
      }
      if (colon < 0) { items.push(names(inner) + " (its type is worked out from the rest)"); continue; }
      const who = inner.slice(0, colon);
      let type = inner.slice(colon + 1);
      const dflt = scanTop(type, (i) => type[i] === ":" && type[i + 1] === "=");
      if (dflt >= 0) type = type.slice(0, dflt);
      const first = squash(who).split(" ")[0];
      if (looksLikeProp(type, first)) items.push("assume " + names(who) + ": " + sayProp(type));
      else items.push(names(who) + ": " + typeWords(type) + (b.bracket === "{" || b.bracket === "⦃" ? " (filled in automatically)" : ""));
    }
    return items;
  }

  // ---------------------------------------------------------------- proofs: tactic steps
  // `first`: the source line of the text's first line, so each row knows its own (the key a Lean trace is joined on).
  function linesOf(text, first) {
    return text.split("\n").map((raw, k) => ({ indent: raw.length - raw.replace(/^\s+/, "").length, text: raw.trim(), line: first ? first + k : 0 }));
  }

  function rwRules(args) {
    const m = args.match(/\[([\s\S]*?)\]/);
    if (!m) return code(args);
    return splitTop(m[1], ",").map((r) => {
      r = r.trim();
      return r.startsWith("←") || r.startsWith("<-") ? code(r.replace(/^(←|<-)\s*/, "")) + " (right to left)" : code(r);
    }).join(", then ");
  }
  function atPart(args) {
    const m = args.match(/\bat\s+([^\]]+)$/);
    if (!m) return "";
    return m[1].trim() === "*" ? " everywhere (goal and assumptions)" : " in " + names(m[1]);
  }
  function simpSet(args) {
    const m = args.match(/\[([\s\S]*?)\]/);
    return m ? splitTop(m[1], ",").map((r) => code(r.trim().replace(/^(←|<-)\s*/, ""))).filter((r) => r !== "<code></code>").join(", ") : "";
  }
  function usingPart(args) {
    const m = args.match(/\busing\s+([\s\S]+)$/);
    return m ? m[1].trim() : "";
  }

  const TACTICS = {
    intro: (a) => a ? "Introduce " + names(a) + (squash(a).split(" ").length === 1 ? ": take it as arbitrary (or, if the goal says “if …”, assume it)." : ": take them as arbitrary, and assume what the goal says about them.") : "Move the next variable or assumption of the goal into view.",
    intros: (a) => "Introduce everything the goal starts with" + (a ? ": " + names(a) : "") + ".",
    rintro: (a) => "Introduce and unpack in one go: " + code(a) + ".",
    apply: (a) => "Work backwards with " + code(a) + ": it gives the goal once its own conditions hold, so those conditions become the new goals.",
    exact: (a) => "Finish: " + code(a) + " is exactly what is needed.",
    exacts: (a) => "Finish each remaining goal with " + code(a) + ".",
    refine: (a) => "Fill in the goal with " + code(a) + "; every ?_ hole becomes a new goal.",
    "refine'": (a) => "Fill in the goal with " + code(a) + "; every _ hole becomes a new goal.",
    rw: (a) => "Rewrite using " + rwRules(a) + atPart(a) + ".",
    rewrite: (a) => "Rewrite using " + rwRules(a) + atPart(a) + ".",
    rwa: (a) => "Rewrite using " + rwRules(a) + atPart(a) + ", and then the goal is one of the assumptions.",
    nth_rw: (a) => "Rewrite one chosen occurrence using " + rwRules(a) + ".",
    nth_rewrite: (a) => "Rewrite one chosen occurrence using " + rwRules(a) + ".",
    simp: (a) => /^only\b/.test(a) ? "Simplify using only " + (simpSet(a) || "the listed facts") + atPart(a) + "." : "Simplify with Lean's standard simplification rules" + (simpSet(a) ? ", also using " + simpSet(a) : "") + atPart(a) + ".",
    simp_all: (a) => "Simplify the goal and all the assumptions together" + (simpSet(a) ? ", also using " + simpSet(a) : "") + ".",
    simpa: (a) => "Simplify" + (simpSet(a) ? " (also using " + simpSet(a) + ")" : "") + (usingPart(a) ? ", then finish with " + code(usingPart(a)) : ", and the goal closes") + ".",
    dsimp: (a) => "Simplify by unfolding definitions" + (simpSet(a) ? " (" + simpSet(a) + ")" : "") + atPart(a) + ".",
    simp_arith: () => "Simplify, including arithmetic on natural numbers.",
    norm_num: (a) => "Do the arithmetic: norm_num proves number facts such as 2 + 2 = 4, 7 ≠ 0 or that 13 is prime" + (simpSet(a) ? ", also using " + simpSet(a) : "") + atPart(a) + ".",
    ring: () => "Both sides are equal by algebra: expand and collect like terms (ring).",
    ring_nf: (a) => "Put the expressions into a standard algebraic form" + atPart(a) + ".",
    field_simp: (a) => "Clear the denominators" + atPart(a) + ".",
    linarith: (a) => "It follows by adding up the linear inequalities in the assumptions (linarith)" + (simpSet(a) ? ", using also " + simpSet(a) : "") + ".",
    nlinarith: (a) => "Like linarith, but also multiplies assumptions together, which handles squares and products" + (simpSet(a) ? "; hints: " + simpSet(a) : "") + ".",
    positivity: () => "The expression is positive (or at least 0), checked term by term (positivity).",
    polyrith: () => "The goal is a combination of the equations in the assumptions (polyrith).",
    linear_combination: (a) => "The goal is exactly this combination of the assumptions: " + code(a) + ".",
    omega: () => "Whole-number arithmetic with +, −, constants and comparisons, decided automatically (omega).",
    decide: () => "Lean checks it by direct computation (decide).",
    native_decide: () => "Checked by running compiled code (native_decide). This also trusts the compiler, an extra axiom.",
    norm_cast: (a) => "Move the statement between number systems (ℕ, ℤ, ℚ, ℝ) to where it is simplest" + atPart(a) + ".",
    push_cast: (a) => "Push the number-system conversions (↑) inward" + atPart(a) + ".",
    lia: () => "Whole-number arithmetic, decided automatically (lia: linear integer arithmetic).",
    simp_rw: (a) => "Rewrite using " + rwRules(a) + ", also inside “for every” and “there is”" + atPart(a) + ".",
    erw: (a) => "Rewrite using " + rwRules(a) + ", matching up to unfolding definitions" + atPart(a) + ".",
    grw: (a) => "Rewrite with an inequality (or another relation) instead of an equation: " + rwRules(a) + atPart(a) + ".",
    classical: () => "Allow classical reasoning from here on (every statement is true or false, even if we cannot compute which).",
    convert: (a) => "Close the goal with " + code(a.replace(/\s+using[\s\S]*$/, "")) + ", which almost matches; any differences become new goals.",
    push: (a) => "Push " + (a ? code(a.split(/\s+at\s+/)[0]) : "the operation") + " inward" + atPart(a) + ".",
    revert: (a) => "Put " + names(a) + " back into the goal, so the goal is about every possible value of it.",
    conv_lhs: () => "Rewrite inside the left-hand side only:",
    conv_rhs: () => "Rewrite inside the right-hand side only:",
    abel: () => "Both sides are equal by rearranging sums (abel: algebra in commutative groups).",
    group: () => "Both sides are equal by the rules of a group (group).",
    noncomm_ring: () => "Both sides are equal by algebra where multiplication need not commute (noncomm_ring).",
    module: () => "Both sides are equal by algebra with vectors and scalars (module).",
    field: () => "Both sides are equal by algebra with division (field).",
    finiteness: () => "The quantity is finite (not ∞), checked automatically (finiteness).",
    order: () => "It follows from the order facts in the assumptions (order).",
    constructorm: () => "Split every “and”-like assumption or goal into its parts.",
    and_intros: () => "Split the “and” goal into its parts.",
    ext1: (a) => "Two functions (or sets) are equal when they agree at every input" + (a ? ": take an arbitrary " + names(a) : "") + ".",
    rename_i: (a) => "Name the unnamed variables " + names(a) + ".",
    letI: (a) => "Give a name to a structure for Lean to use: " + code(a) + ".",
    if: () => "Split on a condition, if-then-else:",
    exact_mod_cast: (a) => "Finish with " + code(a) + ", ignoring conversions between number systems.",
    zify: () => "Move the statement from ℕ to ℤ, where subtraction behaves normally.",
    qify: () => "Move the statement to ℚ, where division behaves normally.",
    gcongr: () => "Compare the two sides piece by piece: if each part on the left is at most the matching part on the right, so is the whole (gcongr).",
    bound: () => "Prove the bound by combining standard inequalities.",
    aesop: () => "Search automatically for a proof using many small rules (aesop).",
    tauto: () => "Pure logic: it follows from the assumptions by the rules of and, or, not and implies (tauto).",
    grind: () => "Automated reasoning that combines equalities, cases and arithmetic (grind).",
    trivial: () => "This goal is immediate.",
    rfl: () => "Both sides are the same by definition (rfl).",
    constructor: () => "Split the goal into its parts: for “A and B” prove A and B, for “A iff B” prove both directions.",
    use: (a) => "Give " + code(a) + " as the example that exists; what remains is to check it works.",
    exists: (a) => "Give " + code(a) + " as the example that exists.",
    existsi: (a) => "Give " + code(a) + " as the example that exists.",
    left: () => "Prove the left side of the “or”.",
    right: () => "Prove the right side of the “or”.",
    exfalso: () => "Switch to proving False: this case is impossible.",
    contradiction: () => "Two assumptions contradict each other, so this case is done.",
    absurd: (a) => "Two facts contradict each other: " + code(a) + ".",
    by_contra: (a) => "Proof by contradiction: assume the opposite" + (a ? " (call it " + code(a.split(/\s|:/)[0]) + ")" : "") + " and reach something false.",
    "by_contra!": (a) => "Proof by contradiction, with the assumed opposite already simplified" + (a ? " (call it " + code(a.split(/\s|:/)[0]) + ")" : "") + ".",
    push_neg: (a) => "Push the “not” inward: not-for-every becomes there-is-a-counterexample, and so on" + atPart(a) + ".",
    by_cases: (a) => "Split into two cases: " + code(a.replace(/^[^\s:]+\s*:\s*/, "")) + " is true, or it is false.",
    obtain: (a) => { const p = a.split(":="); return p.length > 1 ? "Unpack " + code(p.slice(1).join(":=")) + " into its pieces " + code(p[0]) + "." : "State and name the fact " + code(a) + " (proved next)."; },
    rcases: (a) => { const m = a.match(/^(.*?)\s+with\s+(.*)$/); return m ? "Unpack " + code(m[1]) + " into its pieces " + code(m[2]) + ", one case per alternative." : "Unpack " + code(a) + "."; },
    cases: (a) => "Split into cases on how " + code(a.replace(/\s+with[\s\S]*$/, "")) + " can be built.",
    "cases'": (a) => "Split into cases on how " + code(a.replace(/\s+with[\s\S]*$/, "")) + " can be built.",
    induction: (a) => "Prove it by induction on " + code(a.split(/\s+(with|using|generalizing)\b/)[0]) + ": first a starting case, then a step from each case to the next.",
    "induction'": (a) => "Prove it by induction on " + code(a.split(/\s+(with|using|generalizing)\b/)[0]) + ": a starting case, then the step to the next case.",
    match: (a) => "Split on the shape of " + code(a.replace(/\s+with\s*$/, "")) + ", one case per pattern.",
    split: () => "Split into one case for each branch of the if-then-else or match.",
    split_ifs: (a) => "Split into a case for each branch of every if-then-else" + (a ? " (" + code(a) + ")" : "") + ".",
    interval_cases: (a) => "Try every possible value of " + code(a) + " in its known range, one case each.",
    fin_cases: (a) => "Try each of the finitely many values of " + code(a) + ", one case each.",
    ext: (a) => "Two functions (or sets) are equal when they agree at every input" + (a ? ": take an arbitrary " + names(a) : "") + ".",
    funext: (a) => "Two functions are equal when they agree at every input" + (a ? ": take an arbitrary " + names(a) : "") + ".",
    congr: () => "Reduce to showing the matching parts of both sides are equal.",
    symm: () => "Swap the two sides.",
    trans: (a) => "Go through a middle point" + (a ? " " + code(a) : "") + ".",
    subst: (a) => "Replace " + code(a) + " by what it equals, everywhere.",
    unfold: (a) => "Expand the definition of " + names(a.replace(/\bat\b[\s\S]*/, "")) + atPart(a) + ".",
    delta: (a) => "Expand the definition of " + names(a) + ".",
    change: (a) => "Restate the goal as " + code(a.replace(/\s+at\s+.*$/, "")) + " (the same thing, written differently).",
    show: (a) => "Restate the goal as " + code(a.replace(/\s+from[\s\S]*$/, "")) + ".",
    have: haveWords,
    haveI: haveWords,
    "have'": haveWords,
    replace: (a) => "Replace an assumption with a stronger form: " + haveWords(a).replace(/^Establish an intermediate fact/, "the fact"),
    suffices: (a) => "It is enough to prove " + code(a.replace(/^\w+\s*:\s*/, "").replace(/\s+(by|from)[\s\S]*$/, "")) + "; that is shown next, then used to finish.",
    let: (a) => "Give a name to a value: " + code(a) + ".",
    set: (a) => "Give a name to an expression and use the name from now on: " + code(a.replace(/\s+with[\s\S]*$/, "")) + ".",
    specialize: (a) => { const p = a.split(/\s+/); return "Use the assumption " + code(p[0]) + " for the specific " + code(p.slice(1).join(" ")) + "."; },
    generalize: (a) => "Replace a specific expression by a general variable: " + code(a) + ".",
    clear: (a) => "Forget the assumptions " + names(a) + "; they are not needed any more.",
    assumption: () => "The goal is exactly one of the assumptions.",
    calc: () => "A chain of steps, each one justified on its own line:",
    conv: () => "Rewrite inside one chosen part of the goal:",
    filter_upwards: () => "Reduce a statement about “eventually” or “almost everywhere” to one about each point.",
    apply_fun: (a) => "Apply " + code(a.replace(/\s+at[\s\S]*$/, "")) + " to both sides" + atPart(a) + ".",
    continuity: () => "Built automatically from the rules for continuous functions.",
    measurability: () => "Built automatically from the rules for measurable functions.",
    fun_prop: () => "Built automatically from the rules for continuity, differentiability or measurability (fun_prop).",
    infer_instance: () => "Lean finds this automatically from known structures.",
    sorry: () => "<strong>Not proved yet:</strong> sorry is a placeholder, so this proof is unfinished.",
    admit: () => "<strong>Not proved yet:</strong> admit is a placeholder, so this proof is unfinished.",
    all_goals: (a) => "On every remaining goal: " + tacticWords(a),
    any_goals: (a) => "On every goal where it works: " + tacticWords(a),
    repeat: (a) => "Repeat as long as it works: " + tacticWords(a),
    try: (a) => "Try this, and carry on if it fails: " + tacticWords(a),
    first: (a) => "Try these in order until one works: " + splitTop(a.replace(/^\|\s*/, ""), "|").map((t) => code(t)).join(", "),
    focus: () => "Work on the first goal only:",
    next: () => "The next case:",
    case: (a) => "The case " + code(a.replace(/\s*=>[\s\S]*$/, "")) + ":",
    on_goal: (a) => "On one chosen goal: " + code(a) + ".",
    swap: () => "Work on the second goal first.",
    rotate_left: () => "Change the order of the goals.",
    contrapose: (a) => "Prove the contrapositive: if the conclusion fails, then so does the assumption" + (a ? " " + code(a) : "") + ".",
    "contrapose!": (a) => "Prove the contrapositive, with the negations pushed inward" + (a ? " (" + code(a) + ")" : "") + ".",
    lift: (a) => "Treat " + code(a) + " as a value of a smaller number system, since it is known to fit.",
    choose: (a) => "From “for every x there is a y”, pick a function giving such a y: " + code(a) + ".",
    peel: (a) => "Strip matching quantifiers from both sides: " + code(a) + ".",
    wlog: (a) => "Without loss of generality, " + code(a.replace(/\s+with[\s\S]*$/, "")) + "; the other case follows the same way.",
    norm_num1: () => "Do the arithmetic.",
    nofun: () => "No case can occur, so there is nothing to prove.",
    nomatch: (a) => "No case of " + code(a) + " can occur.",
  };
  function haveWords(a) {
    let rest = a;
    let how = "";
    const by = scanTop(rest, (i) => startsWord(rest, i, "by") || (rest[i] === ":" && rest[i + 1] === "="));
    if (by >= 0) {
      how = rest.slice(by).trim();
      rest = rest.slice(0, by);
    }
    rest = rest.trim();
    let name = "", claim = rest;
    const colon = scanTop(rest, (i) => rest[i] === ":" && rest[i + 1] !== "=");
    if (colon >= 0) { name = rest.slice(0, colon).trim(); claim = rest.slice(colon + 1); }
    else if (/^:=/.test(how)) { name = rest; claim = ""; }
    let out = "Establish an intermediate fact" + (name ? " " + code(name) : "") + (claim.trim() ? ": " + sayProp(claim) : "");
    if (/^:=/.test(how)) {
      const term = how.slice(2).trim();
      const cong = term.match(/^congrArg\s+(\S+|\([^)]*\))\s+(\S+)$/);
      if (cong) out += ", by applying " + code(cong[1]) + " to both sides of " + code(cong[2]);
      else if (!/^by\b/.test(term)) {
        const use = glueCalls(headArgs(squash(term)));
        if (use.length > 1 && /^(h[\w'₀-₉]*|this|ih[\w'₀-₉]*)$/.test(use[0])) out += ", by using " + code(use[0]) + " for " + use.slice(1).map((a) => code(a)).join(", ");
        else out += ", directly from " + code(short(term));
      }
      else if (term.slice(2).trim()) out += ". Proved by: " + tacticWords(term.slice(2)).replace(/\.$/, "");
    } else if (/^by\b/.test(how) && how.slice(2).trim()) {
      out += ". Proved by: " + tacticWords(how.slice(2)).replace(/\.$/, "");
    }
    return out + ".";
  }

  function tacticWords(t) {
    t = squash(t);
    if (!t) return "";
    const combo = splitTop(t, "<;>");
    if (combo.length > 1) return tacticWords(combo[0]) + " Then, on every goal that produces: " + combo.slice(1).map(tacticWords).join(" Then: ");
    const semi = splitTop(t, ";");
    if (semi.length > 1 && semi.every((p) => p.trim())) return semi.map(tacticWords).join(" Then: ");
    const m = t.match(/^([A-Za-z_][\w'!?]*)\s*([\s\S]*)$/);
    if (!m) return "Run " + code(t) + ".";
    let name = m[1];
    let args = m[2].trim();
    if (name.endsWith("?") && TACTICS[name.slice(0, -1)]) name = name.slice(0, -1);
    const say = TACTICS[name] || (name.endsWith("!") && TACTICS[name.slice(0, -1)]);
    if (say) return say(args);
    return "Run the tactic " + code(name) + (args ? " with " + code(args) : "") + ".";
  }

  // Group tactic lines into steps; deeper lines either continue a step or form its sub-steps.
  function tacticSteps(lines, depth) {
    depth = depth || 0;
    const rows = lines.filter((l) => l.text);
    const steps = [];
    let i = 0;
    while (i < rows.length) {
      const base = rows[i].indent;
      const line = rows[i].line;
      let text = rows[i].text;
      let j = i + 1;
      const deeper = [];
      while (j < rows.length && rows[j].indent > base) { deeper.push(rows[j]); j++; }
      if (/(^|\s)calc\b/.test(text)) {
        while (j < rows.length && rows[j].indent === base && /^_\s/.test(rows[j].text)) {
          deeper.push({ indent: base + 2, text: rows[j].text, line: rows[j].line });
          j++;
          while (j < rows.length && rows[j].indent > base) { deeper.push(rows[j]); j++; }
        }
      }
      const arm = text.match(/^\|\s*([\s\S]*?)\s*=>\s*([\s\S]*)$/);
      if (arm) {
        const inner = (arm[2] ? [{ indent: base + 2, text: arm[2], line }] : []).concat(deeper);
        steps.push({ text: "|", arm: arm[1], line, children: depth < 6 ? tacticSteps(inner, depth + 1) : [] });
        i = j;
        continue;
      }
      const bullet = text.match(/^[·.]\s*([\s\S]*)$/);
      const opens = bullet || /(\bby|\bwith|=>|\bdo|\bcalc|\bconv\b.*)$/.test(text) || /^(case|next|focus|calc|conv)\b/.test(text);
      let children = [];
      if (bullet) {
        const inner = [{ indent: base + 2, text: bullet[1], line }].concat(deeper);
        children = depth < 6 ? tacticSteps(inner, depth + 1) : [];
        steps.push({ text: "·", bullet: true, line, children });
      } else if (opens && deeper.length && depth < 6) {
        if (/^calc\b/.test(text) || /\bcalc$/.test(text)) {
          const first = text.replace(/^.*?\bcalc\b\s*/, "");
          const calcRows = (first ? [{ indent: base + 2, text: first, line }] : []).concat(deeper);
          steps.push({ text: text.replace(/\s*calc\b.*$/, " calc").trim(), calc: calcLinks(calcRows), line, children: [] });
        } else {
          steps.push({ text, line, children: tacticSteps(deeper, depth + 1) });
        }
      } else {
        for (const row of deeper) text += " " + row.text;
        if (/^calc\b/.test(text)) steps.push({ text: "calc", calc: calcLinks([{ indent: base + 2, text: text.slice(4) }]), line, children: [] });
        else steps.push({ text, line, children: [] });
      }
      i = j;
    }
    return steps;
  }
  function calcLinks(rows) {
    const links = [];
    for (const row of rows) {
      if (!row.text) continue;
      if (links.length && !/^_\s/.test(row.text) && !/:=/.test(row.text) && row.indent > rows[0].indent) { links[links.length - 1].raw += " " + row.text; continue; }
      if (links.length && !/^_\s/.test(row.text) && !/:=/.test(row.text)) { links[links.length - 1].raw += " " + row.text; continue; }
      links.push({ raw: row.text });
    }
    return links.map((l) => {
      const at = scanTop(l.raw, (i) => l.raw[i] === ":" && l.raw[i + 1] === "=");
      const claim = at < 0 ? l.raw : l.raw.slice(0, at);
      const why = at < 0 ? "" : l.raw.slice(at + 2).trim();
      return { claim: squash(claim), why: /^by\b/.test(why) ? tacticWords(why.slice(2)) : why ? "by " + code(why) : "" };
    });
  }

  // ---------------------------------------------------------------- steps read from the goals Lean reports
  // A Lean run (the lean extension) ships every tactic step with the goals Lean showed before and after it, in the text
  // Lean prints: an optional `case tag` line, the hypotheses (`a b : T`; a long type goes on in indented lines), then
  // `⊢ target`. A step's words are read off how those goals change. What the tactic's own text says stays beside them
  // as the "how". A step with no Lean step to read gets the words of its text and says so.
  function parseGoal(raw) {
    const groups = [];
    const goal = { tag: "", hyps: [], target: "", raw: String(raw) };
    let last = null;  // what the indented lines that follow belong to: a hypothesis group or the target
    for (const line of goal.raw.split("\n")) {
      let m;
      if (/^\s/.test(line) && last) {
        if (last === "target") goal.target += " " + line.trim(); else last.type += " " + line.trim();
      } else if ((m = line.match(/^case (.+)$/))) {
        goal.tag = m[1].trim();
        last = null;
      } else if ((m = line.match(/^⊢ ?([\s\S]*)$/))) {
        goal.target = m[1];
        last = "target";
      } else if ((m = line.match(/^(\S.*?) : ([\s\S]*)$/))) {
        last = { names: m[1].split(/\s+/), type: m[2] };
        groups.push(last);
      } else {
        last = null;
      }
    }
    for (const g of groups) for (const name of g.names) goal.hyps.push({ name, type: squash(g.type) });
    goal.target = squash(goal.target);
    return goal;
  }

  // What the step did to the goals: `before` and `after` are the goals Lean listed (strings). The first goal is the one
  // the tactic works on; goals after it that the step left alone stay at the end of `after`. null: Lean had no goal there.
  function goalChange(before, after) {
    const b = before.map(parseGoal);
    const a = after.map(parseGoal);
    if (!b.length) return null;
    const same = (x, y) => x.length === y.length && x.every((g, k) => g.raw === y[k].raw);
    if (same(a, b)) return { kind: "same", from: b[0] };
    if (a.length === b.length && same(a.slice().sort((x, y) => (x.raw < y.raw ? -1 : 1)), b.slice().sort((x, y) => (x.raw < y.raw ? -1 : 1)))) return { kind: "reordered", from: b[0] };
    const rest = b.slice(1);
    let left = rest.length;
    let upTo = a.length;
    while (left > 0 && upTo > 0 && a[upTo - 1].raw === rest[left - 1].raw) { left--; upTo--; }
    const made = a.slice(0, upTo);
    if (!made.length) return { kind: "closed", from: b[0], others: left };
    return { kind: made.length === 1 ? "one" : "split", from: b[0], made, others: left };
  }

  const GOAL_CHARS = 140;
  // A term out of a goal: typeset when it is short; cut, with the whole of it on hover, when it is not.
  function goalTerm(s) {
    s = squash(s);
    if (s.length > GOAL_CHARS) return "<code title=\"" + esc(s) + "\">" + esc(s.slice(0, GOAL_CHARS - 1)) + "…</code>";
    try { return math(s); } catch (e) { return code(s); }
  }
  function hypCode(h) {
    const full = squash(h.name + " : " + h.type);
    return full.length > GOAL_CHARS ? "<code title=\"" + esc(full) + "\">" + esc(full.slice(0, GOAL_CHARS - 1)) + "…</code>" : "<code>" + esc(full) + "</code>";
  }
  function andList(items) {
    return items.length < 2 ? items.join("") : items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
  }
  function someOf(items, limit) {
    return items.length > limit ? items.slice(0, limit).concat(["" + (items.length - limit) + " more"]) : items;
  }
  function hypChanges(from, to) {
    const was = new Map(from.hyps.map((h) => [h.name, h.type]));
    const now = new Map(to.hyps.map((h) => [h.name, h.type]));
    return {
      added: to.hyps.filter((h) => !was.has(h.name)),
      removed: from.hyps.filter((h) => !now.has(h.name)),
      changed: to.hyps.filter((h) => was.has(h.name) && was.get(h.name) !== h.type),
    };
  }
  // The sentences for one goal turning into another.
  function movedWords(from, to) {
    const d = hypChanges(from, to);
    const out = [];
    if (d.added.length) out.push("Introduces " + andList(someOf(d.added.map(hypCode), 5)));
    if (d.changed.length) out.push(andList(someOf(d.changed.map((h) => "<code>" + esc(h.name) + "</code> becomes " + goalTerm(h.type)), 4)));
    if (d.removed.length) out.push("Removes " + andList(someOf(d.removed.map((h) => "<code>" + esc(h.name) + "</code>"), 5)));
    out.push(from.target === to.target ? "The goal does not change" : "The goal becomes " + goalTerm(to.target));
    return out.map((s) => s + ".").join(" ");
  }
  // The words for a step read off its goals; `container`: the step has sub-steps that do the work.
  function goalWords(change, container) {
    if (!change) return "";
    const from = change.from;
    if (change.kind === "closed") {
      if (container) return "Works on " + (from.tag ? "the case <code>" + esc(from.tag) + "</code>: " : "the goal ") + goalTerm(from.target) + ".";
      return "Closes the goal" + (change.others ? " and " + change.others + " other goal" + (change.others === 1 ? "" : "s") + " with it" : "") + ".";
    }
    if (change.kind === "same") return "Leaves the goals as they were.";
    if (change.kind === "reordered") return "Reorders the goals.";
    if (change.kind === "one") return movedWords(from, change.made[0]);
    const shown = change.made.slice(0, 6).map((g) => {
      const added = hypChanges(from, g).added;
      return (g.tag ? "<code>" + esc(g.tag) + "</code>: " : "") + goalTerm(g.target) + (added.length ? " (with " + andList(someOf(added.map(hypCode), 3)) + ")" : "");
    });
    return "Splits the goal into " + change.made.length + " goals: " + shown.join("; ") + (change.made.length > 6 ? "; and " + (change.made.length - 6) + " more" : "") + ".";
  }
  function sameTactic(reading, traced) {
    const a = squash(reading);
    const b = squash(traced);
    if (!a || !b) return false;
    if (/^[·.]$/.test(a)) return /^[·.]/.test(b);  // a bullet: the trace step is `· first tactic`
    return a === b || a.startsWith(b) || b.startsWith(a);  // the trace keeps a tactic's first line only
  }
  // The Lean step for a reading step: on its line, the same tactic, not already given to an earlier step.
  function takeTrace(step, context) {
    if (!context || !step.line) return null;
    for (let k = 0; k < context.trace.length; k++) {
      const t = context.trace[k];
      if (context.used.has(k) || t[0] !== step.line || !sameTactic(step.text, t[1])) continue;
      context.used.add(k);
      return t;
    }
    return null;
  }

  // `context` is null for a page with no Lean run: the reading is the source's alone and says nothing about goals.
  // Otherwise {trace: this declaration's Lean steps, used: the ones already given to a step}.
  function stepHtml(step, counter, context) {
    const open = (basis) => "<li" + (step.line ? " data-line=\"" + step.line + "\"" : "") + (basis ? " data-basis=\"" + basis + "\"" : "") + ">";
    if (step.arm !== undefined) {
      return open() + "<span class=\"rd-case\">" + armWords(step.arm) + "</span>" + (step.children.length ? stepsHtml(step.children, context) : "") + "</li>";
    }
    const lean = takeTrace(step, context);
    const goals = lean && lean[2].length ? goalChange(lean[2], lean[3]) : null;
    if (step.bullet) {
      counter.n++;
      if (goals) {
        const g = goals.from;
        return open("goals") + "<span class=\"rd-case\">Case " + counter.n + "</span> <span class=\"rd-fact\" title=\"" + FROM_GOALS + "\">(" +
          (g.tag ? "<code>" + esc(g.tag) + "</code>, " : "") + "to show " + goalTerm(g.target) + "):</span>" + stepsHtml(step.children, context) + "</li>";
      }
      return open(context ? "source" : "") + "<span class=\"rd-case\">Case " + counter.n + ":</span>" + stepsHtml(step.children, context) + "</li>";
    }
    const how = tacticWords(step.text.replace(/\s*(=>|\bwith)\s*$/, ""));
    const tactic = "<code class=\"rd-tac\">" + esc(step.text.length > 160 ? step.text.slice(0, 157) + "…" : step.text) + "</code> ";
    let out;
    // A step that holds sub-steps, or opens alternatives (`induction n with | zero => …`, whose arms sit beside it), does
    // not close the goal by itself: Lean's "no goals after" is the whole block's.
    const fact = goals && goalWords(goals, step.children.length > 0 || /\bwith\s*$/.test(step.text));
    if (fact) out = open("goals") + tactic + "<span class=\"rd-fact\" title=\"" + FROM_GOALS + "\">" + fact + "</span> <span class=\"rd-how\">" + how + "</span>";
    else if (context) out = open("source") + tactic + how + " <span class=\"rd-basis\">(read from the source text: no Lean goals matched this step)</span>";
    else out = open() + tactic + how;
    if (step.calc) {
      out += "<ol class=\"rd-calc\">" + step.calc.map((l) => "<li>" + math(l.claim, { calc: true }) + (l.why ? " — " + l.why : "") + "</li>").join("") + "</ol>";
    }
    if (step.children.length) out += stepsHtml(step.children, context);
    return out + "</li>";
  }
  const FROM_GOALS = "Read from the goals Lean reports before and after this step";
  function stepsHtml(steps, context) {
    const counter = { n: 0 };
    return "<ol class=\"rd-steps\">" + steps.map((s) => { if (!s.bullet) counter.n = 0; return stepHtml(s, counter, context || null); }).join("") + "</ol>";
  }
  function armWords(pat) {
    const p = squash(pat);
    if (/^(zero|nil|0)$/.test(p)) return "Starting case " + code(p) + ":";
    const succ = p.match(/^succ\s+(\S+)(?:\s+(\S+))?$/);
    if (succ) return "Step case: from " + code(succ[1]) + " to " + code(succ[1] + " + 1") + (succ[2] ? ", assuming the claim for " + code(succ[1]) + " (called " + code(succ[2]) + ")" : "") + ":";
    const cons = p.match(/^cons\s+(\S+)\s+(\S+)(?:\s+(\S+))?$/);
    if (cons) return "Case of a list " + code(cons[1] + " :: " + cons[2]) + (cons[3] ? ", assuming the claim for " + code(cons[2]) + " (called " + code(cons[3]) + ")" : "") + ":";
    return "Case " + code(p) + ":";
  }
  function countSteps(steps) {
    return steps.reduce((n, s) => n + (s.bullet ? 0 : 1) + countSteps(s.children), 0);
  }
  function proofShape(steps) {
    const first = steps[0] ? steps[0].text : "";
    const all = JSON.stringify(steps);
    if (/"(sorry|admit)\b/.test(all)) return "This proof is not finished: it still contains sorry.";
    if (/^induction/.test(first)) return "A proof by induction.";
    if (/^(by_contra|contrapose)/.test(first)) return "A proof by contradiction.";
    if (/^(rcases|cases|obtain|by_cases|interval_cases|fin_cases|split)/.test(first) && steps.length <= 2) return "A proof by cases.";
    const n = countSteps(steps);
    if (n === 1) return "A one-step proof: " + tacticWords(first).replace(/^Finish: /, "").replace(/\.$/, "") + ".";
    return "A proof in " + n + " steps.";
  }

  // ---------------------------------------------------------------- term proofs and definitions
  // Pieces that cannot be arguments of a function: keywords, operators (⊆, +, ∑, <|), the end of a binder list ("x,").
  const TERM_KEYWORDS = new Set(["fun", "λ", "match", "with", "if", "then", "else", "let", "letI", "have", "haveI", "show", "from", "by", "do", "open", "in", "where", "calc"]);
  const OPERATOR = /^[^\p{L}\p{N}_?([{⟨⦃«@.'"`]+$/u;
  function notAnArgument(a) {
    return TERM_KEYWORDS.has(a) || OPERATOR.test(a) || /[,;]$/.test(a) || /^\|>/.test(a);
  }
  // The pieces of an application `f a (b c) ⟨d, e⟩`. What touches without a space is one piece (`xs[i]`, `(f x).2`,
  // `![…]`); a `fun` or a `by`, and what follows `<|`, run to the end as one argument.
  function appArgs(s) {
    const args = [];
    let i = 0;
    while (i < s.length) {
      const from = i;
      while (s[i] === " ") i++;
      if (i >= s.length) break;
      let j = i;
      if (OPEN.indexOf(s[i]) >= 0) { const m = matching(s, i); j = m < 0 ? s.length : m + 1; }
      else while (j < s.length && s[j] !== " " && OPEN.indexOf(s[j]) < 0) j++;
      const piece = s.slice(i, j);
      if (args.length && i === from) args[args.length - 1] += piece;
      else if (args.length && /^(fun|λ|by)$/.test(piece)) { args.push(s.slice(i).trim()); break; }
      else if (args.length && /^(<\||\$)$/.test(piece)) { if (s.slice(j).trim()) args.push(s.slice(j).trim()); break; }
      else args.push(piece);
      i = j;
    }
    return args;
  }
  function lowerFirst(s) {
    return s[0] === "<" ? s : s.charAt(0).toLowerCase() + s.slice(1);
  }
  function termCode(s, value) {
    s = squash(s);
    return value && s.length <= 140 ? math(s) : code(short(s));
  }
  // `match x with | p => v | …`: each case in turn.
  function matchWords(t, value) {
    const w = scanTop(t, (i) => startsWord(t, i, "with"));
    if (w < 0) return null;
    const arms = splitTop(t.slice(w + 4).trim().replace(/^\|/, ""), " | ").map((a) => {
      const at = scanTop(a, (i) => a.substr(i, 2) === "=>" || a[i] === "↦");
      return at < 0 ? null : { pat: a.slice(0, at).trim(), val: a.slice(at + (a[at] === "↦" ? 1 : 2)).trim() };
    });
    if (!arms.length || arms.length > 12 || arms.some((a) => !a || !a.pat || !a.val || /\bmatch\b/.test(a.val))) return null;
    return "Case by case on " + code(t.slice(5, w)) + ": " +
      arms.map((a) => "when it is " + math(a.pat) + ", " + (value ? "the result is " : "use ") + termCode(a.val, value)).join("; ") + ".";
  }
  // `if c then a else b`, with `if h : c` naming the condition.
  function ifWords(t, value) {
    let depth = 0, then = -1, other = -1;
    scanTop(t, (i) => {
      if (startsWord(t, i, "if")) { if (i > 0) depth++; }
      else if (startsWord(t, i, "then")) { if (then < 0 && depth === 0) then = i; }
      else if (startsWord(t, i, "else")) { if (depth === 0) { other = i; return true; } depth--; }
      return false;
    });
    if (then < 0 || other < then) return null;
    const cond = t.slice(2, then).trim().replace(/^[\w'₀-₉]+\s*:(?!=)\s*/, "");
    const say = value ? "it is " : "use ";
    return "If " + sayProp(cond) + ", " + say + termCode(t.slice(then + 4, other), value) + "; otherwise " + say + termCode(t.slice(other + 4), value) + ".";
  }
  function termWords(t, value) {
    const opened = String(t).match(OPEN_IN);
    if (opened) return termWords(String(t).slice(opened[0].length), value);
    const lt = String(t).match(LET_RE);
    if (lt) return "With " + math(lt[1]) + " standing for " + termCode(lt[2], value) + ", " + lowerFirst(termWords(lt[3], value));
    t = stripParens(squash(t));
    if (!t) return "";
    if (/^(fun|λ)\b/.test(t)) {
      const arrow = t.search(/=>|↦/);
      if (arrow > 0) return "Given " + names(t.slice(t.indexOf(" "), arrow).replace(/[()]/g, " ").replace(/:.*$/, "")) + ", it gives " + code(t.slice(arrow + 2)) + ".";
    }
    if (t[0] === "⟨") return "Built from its parts: " + splitTop(t.slice(1, -1), ",").map((p) => code(p)).join(", ") + ".";
    if (t === "rfl") return "Both sides are the same by definition (rfl).";
    if (/^(absurd|False\.elim|nomatch)/.test(t)) return "This case cannot happen: " + code(t) + ".";
    const cong = t.match(/^congrArg\s+(\S+|\([^)]*\))\s+(\S+)$/);
    if (cong) return "Apply " + code(cong[1]) + " to both sides of " + code(cong[2]) + ".";
    if (/^match\b/.test(t)) { const w = matchWords(t, value); if (w) return w; }
    if (/^if\b/.test(t)) { const w = ifWords(t, value); if (w) return w; }
    const args = glueCalls(appArgs(t));
    if (args.length > 1 && !args.some(notAnArgument)) return "Apply " + code(short(args[0])) + " to " + args.slice(1).map((a) => code(short(a))).join(", ") + ".";
    const rw = splitTop(t, "▸");
    if (rw.length === 2 && rw[0].trim() && rw[1].trim()) return "Use " + code(short(rw[1])) + ", rewritten with " + code(short(rw[0])) + " (▸).";
    return "It is " + termCode(t, value) + ".";
  }
  // A definition whose value is a statement (`def IsGood (n : ℕ) : Prop := …`): what `IsGood n` means, in words, and as
  // a formula when one can be drawn.
  function propMeaning(h, body) {
    const type = squash(h.type);
    let rest = String(body);
    const opened = rest.match(OPEN_IN);
    if (opened) rest = rest.slice(opened[0].length);
    const inputs = explicitInputs(h.binders);
    if (type !== "Prop") {
      if (!/(→|->)\s*Prop$/.test(type)) return null;
      const f = squash(rest).match(/^(?:fun|λ)\s+([^=↦]*?)\s*(?:=>|↦)\s*([\s\S]*)$/);
      if (!f) return null;
      const vars = f[1].replace(/\(([^():]*):[^()]*\)/g, " $1 ").replace(/:.*$/, "").split(" ").filter(Boolean);
      if (!vars.length || vars.some((v) => v === "_" || !/^[^\s,:()⟨⟩{}[\]⦃⦄|]+$/.test(v))) return null;
      inputs.push(...vars);
      rest = f[2];
    }
    const said = squash(rest);
    if (!said || /^(sorry|match|if)\b/.test(said)) return null;
    const name = (h.name || "").split(".").pop();
    const t = translator();
    const tex = t && t.definitionTex(name, explicitInputs(h.binders), body.replace(OPEN_IN, ""), "\\iff");
    return "<p class=\"rd-say\"><strong>" + code([name].concat(inputs).join(" ")) + " means:</strong> " + sayProp(rest) + ".</p>" + (tex ? displayMath(tex, body) : "");
  }
  function glueCalls(args) {
    const out = [];
    for (const a of args) {
      if (a[0] === "." && out.length) out[out.length - 1] += a;
      else out.push(a);
    }
    return out;
  }
  function short(s) {
    s = squash(s);
    return s.length > 140 ? s.slice(0, 137) + "…" : s;
  }
  function armsOf(body) {
    const arms = [];
    for (const raw of body.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      if (line[0] === "|") arms.push(line.slice(1).trim());
      else if (arms.length) arms[arms.length - 1] += " " + line;
    }
    return arms.map((a) => {
      const at = a.indexOf("=>");
      return at < 0 ? { pat: a, val: "" } : { pat: a.slice(0, at), val: a.slice(at + 2) };
    });
  }
  function fieldsOf(body) {
    const fields = [];
    for (const raw of body.split("\n")) {
      let line = raw.trim();
      if (!line || /^(deriving|mk\s*::|\w+\s*::\s*$)/.test(line)) continue;
      line = line.replace(/^\w+\s*::\s*/, "");
      const bracketed = line.match(/^\((.*)\)$/);
      if (bracketed) line = bracketed[1];
      const colon = scanTop(line, (i) => line[i] === ":" && line[i + 1] !== "=");
      if (colon > 0 && /^[\w'.₀-₉ ]+$/.test(line.slice(0, colon).trim())) fields.push({ name: line.slice(0, colon).trim(), type: line.slice(colon + 1).replace(/:=[\s\S]*$/, "") });
      else if (fields.length) fields[fields.length - 1].type += " " + line;
    }
    return fields;
  }

  // ---------------------------------------------------------------- one declaration
  // The names a definition takes explicitly, in order: (z : Phase n) gives z; assumptions such as (h : 0 < n) are left out.
  function explicitInputs(binders) {
    const out = [];
    for (const b of binders) {
      if (b.bracket !== "(") continue;
      const inner = squash(b.inner);
      const c = inner.indexOf(":");
      if (c >= 0 && looksLikeProp(inner.slice(c + 1), inner.slice(0, c).trim().split(" ")[0])) continue;
      (c < 0 ? inner : inner.slice(0, c)).split(" ").forEach((n) => n && out.push(n));
    }
    return out;
  }
  // `startLine`: the source line the declaration starts on, when known; each proof step then carries its own line.
  // `context`: see stepHtml; omit it for a page that has no Lean run.
  function readDeclaration(original, masked, links, startLine, context) {
    const fromMasked = splitHeader(masked);
    const h = fromMasked || splitHeader(original);
    if (!h) return null;
    const text = fromMasked ? masked : original;  // the body is the end of this text
    const out = [];
    const given = givenItems(h.binders);
    const used = new Set();
    const local = new Set();
    for (const b of h.binders) {
      const inner = squash(b.inner);
      const colon = inner.indexOf(":");
      (colon >= 0 ? inner.slice(0, colon) : inner).split(" ").forEach((n) => n && local.add(n));
    }
    (h.body.match(/\b(?:intro|intros|rintro|obtain|rcases|cases|induction|set|let|have|by_contra|by_cases|ext|funext|choose)\s+([^:=\n]*)/g) || []).forEach((m) =>
      (m.replace(/^\S+\s+/, "").match(/[A-Za-z_][\w'₀-₉]*/g) || []).forEach((n) => local.add(n)));
    (h.body.match(/fun\s+([^=↦]*)(=>|↦)/g) || []).forEach((m) => (m.match(/[A-Za-z_][\w'₀-₉]*/g) || []).forEach((n) => n !== "fun" && local.add(n)));
    const isProof = /^(theorem|lemma|example|problem|instance)$/.test(h.kind) && h.type && looksLikeProp(h.type, "");
    if (h.kind === "axiom") {
      out.push("<p class=\"rd-say\"><strong>Assumed without proof:</strong> " + sayProp(h.type) + ". Anything that uses it depends on this assumption.</p>");
    } else if (/^(theorem|lemma|problem|example)$/.test(h.kind) || isProof) {
      out.push("<p class=\"rd-say\"><strong>It says:</strong> " + (h.type ? sayProp(h.type) : "(no statement found)") + ".</p>");
      const tex = h.type && texOf(h.type);
      if (tex) out.push(displayMath(tex, h.type));
    } else if (h.kind === "determine") {
      out.push("<p class=\"rd-say\"><strong>The answer to find:</strong> " + code(h.name) + (h.type ? ", " + typeWords(h.type) : "") + ".</p>");
    } else if (h.kind === "structure" || h.kind === "class") {
      out.push("<p class=\"rd-say\"><strong>" + (h.kind === "class" ? "A class" : "A structure") + "</strong> " + code(h.name) +
        (h.kind === "class" ? ": a kind of structure Lean finds automatically when it is needed." : ": a bundle of data and facts kept together.") +
        (h.extendsPart ? " It extends " + splitTop(h.extendsPart, ",").map((e) => code(e)).join(" and ") + ", so it has everything they have." : "") + "</p>");
    } else if (/inductive/.test(h.kind)) {
      out.push("<p class=\"rd-say\"><strong>A new type</strong> " + code(h.name) + ". Its values are built in exactly these ways:</p>");
    } else if (h.kind === "instance") {
      out.push("<p class=\"rd-say\"><strong>An instance:</strong> it tells Lean that " + code(h.type) + " holds or is available, so Lean can use it automatically.</p>");
    } else {
      const inputs = explicitInputs(h.binders).join(" ");
      out.push("<p class=\"rd-say\"><strong>Defines</strong> " + code(h.name || "(unnamed)") + (h.type ? (inputs.trim() ? ": from " + names(inputs) + " it gives " : ": ") + typeWords(h.type) : "") + "." +
        (h.kind === "abbrev" ? " It is an abbreviation, so Lean unfolds it freely." : "") + "</p>");
    }
    if (given.length) out.push("<div class=\"rd-given\"><strong>Given</strong><ul>" + given.map((g) => "<li>" + g + "</li>").join("") + "</ul></div>");

    const body = h.body.replace(/^\s+/, "");
    if (h.bodyKind === "term" && /^by\b/.test(body)) {
      const at = text.length - h.body.length + h.body.indexOf("by") + 2;
      const after = h.body.slice(h.body.indexOf("by") + 2);
      const firstLine = after.split("\n")[0];
      const lines = linesOf(after, startLine ? startLine + text.slice(0, at).split("\n").length - 1 : 0);
      if (firstLine.trim()) lines[0].indent = 1e6; // a tactic on the `by` line itself
      const rows = lines.filter((l) => l.text);
      if (rows.length && rows[0].indent === 1e6) rows[0].indent = rows.length > 1 ? Math.min.apply(null, rows.slice(1).map((r) => r.indent)) : 2;
      const steps = tacticSteps(rows);
      if (steps.length) {
        out.push("<p class=\"rd-shape\"><strong>" + (isProof || /^(theorem|lemma|problem|example)$/.test(h.kind) ? "How the proof goes" : "How it is built") + ":</strong> " + proofShape(steps) + "</p>");
        out.push(stepsHtml(steps.length > 200 ? steps.slice(0, 200) : steps, context));
      }
    } else if (h.bodyKind === "term" && body) {
      const isValue = !(/^(theorem|lemma|problem|example)$/.test(h.kind) || isProof);
      const meaning = isValue && propMeaning(h, body);
      const t = isValue && !meaning && translator();
      const tex = t && t.definitionTex((h.name || "").split(".").pop(), explicitInputs(h.binders), body.replace(OPEN_IN, ""));
      if (meaning) out.push(meaning);
      else if (tex) out.push("<p class=\"rd-shape\"><strong>Its value:</strong></p>" + displayMath(tex, body));
      else out.push("<p class=\"rd-shape\"><strong>" + (isValue ? "Its value" : "The proof") + ":</strong> " + termWords(body.length > 600 ? body.slice(0, 600) : body, isValue) + "</p>");
    } else if (h.bodyKind === "arms") {
      const arms = armsOf(h.body);
      if (/inductive/.test(h.kind)) out.push("<ul class=\"rd-arms\">" + arms.map((a) => "<li>" + code(a.pat) + "</li>").join("") + "</ul>");
      else out.push("<p class=\"rd-shape\"><strong>Case by case:</strong></p><ul class=\"rd-arms\">" + arms.map((a) => "<li>when the input is " + math(a.pat) + ", the result is " + math(a.val) + "</li>").join("") + "</ul>");
    } else if (h.bodyKind === "where") {
      if (/^(structure|class)$/.test(h.kind)) {
        const fields = fieldsOf(h.body);
        if (fields.length) out.push("<p class=\"rd-shape\"><strong>It holds:</strong></p><ul class=\"rd-arms\">" + fields.map((f) => "<li>" + code(f.name) + ": " + (looksLikeProp(f.type, f.name) ? "the fact that " + sayProp(f.type) : typeWords(f.type)) + "</li>").join("") + "</ul>");
      } else if (/inductive/.test(h.kind)) {
        out.push("<ul class=\"rd-arms\">" + armsOf(h.body).map((a) => "<li>" + code(a.pat) + "</li>").join("") + "</ul>");
      } else {
        const fields = fieldsOf(h.body.replace(/:=/g, ":"));
        out.push("<p class=\"rd-shape\"><strong>It provides:</strong> " + (fields.length ? fields.map((f) => code(f.name)).join(", ") : "the pieces listed in the source") + ".</p>");
      }
    }

    // results the declaration leans on
    const idents = (h.type + " " + h.body).match(/[A-Za-z_][\w'!?₀-₉]*(?:\.[A-Za-z_][\w'!?₀-₉]*)*/g) || [];
    for (const id of idents) {
      if (local.has(id) || local.has(id.split(".")[0]) || id === h.name || KEYWORDS.has(id) || TACTICS[id] || id.length < 3) continue;
      if (id.indexOf(".") < 0 && id.indexOf("_") < 0 && !links.has(id)) continue;
      used.add(id);
      if (used.size >= 30) break;
    }
    if (used.size) {
      out.push("<p class=\"rd-uses\"><strong>Results and definitions it uses:</strong> " + Array.from(used).map((id) => {
        const here = links.get(id);
        if (here) return "<a href=\"" + esc(here) + "\">" + esc(id) + "</a>";
        return "<a href=\"https://leanprover-community.github.io/mathlib4_docs/find/?pattern=" + encodeURIComponent(id) + "#doc\" title=\"look it up in the Mathlib documentation\">" + esc(id) + "</a>";
      }).join(", ") + "</p>");
    }
    const symbols = symbolsIn(h.type + " " + h.binders.map((b) => b.inner).join(" "));
    if (symbols.length) {
      out.push("<details class=\"rd-symbols\"><summary>Symbols in the statement</summary><dl>" +
        symbols.map(([s, w]) => "<dt>" + esc(s) + "</dt><dd>" + esc(w) + "</dd>").join("") + "</dl></details>");
    }
    const lines = original.split("\n").length;
    out.push("<details class=\"rd-src\"><summary>The Lean source (" + lines + " line" + (lines === 1 ? "" : "s") + ")</summary><pre>" + linkedCode(original, links) + "</pre></details>");
    return out.join("");
  }
  const KEYWORDS = new Set(["fun", "by", "with", "have", "show", "from", "then", "else", "match", "let", "using", "only", "at", "this", "Type", "Prop", "Sort", "where", "theorem", "lemma", "def", "instance", "structure", "class", "inductive", "abbrev", "example", "calc", "do", "return", "if", "for", "in", "mut", "true", "false", "True", "False", "Nat", "Int", "Real", "Set", "Finset", "List", "Fin", "noncomputable", "private", "protected", "termination_by", "decreasing_by", "deriving"]);

  // ---------------------------------------------------------------- a whole file
  // The source span of each declaration: from its line up to the next one's, cut at the first top-level command.
  const CONTINUES = /^(\||where\b|termination_by|decreasing_by|deriving|with\b|[)\]}⟩]|:=|·)/;
  function spans(text, lineNumbers) {
    const lines = text.split("\n");
    const maskedLines = mask(text).split("\n");
    const sorted = lineNumbers.slice().sort((a, b) => a - b);
    return sorted.map((line, k) => {
      const start = line - 1;
      const stop = k + 1 < sorted.length ? sorted[k + 1] - 1 : lines.length;
      let end = stop;
      for (let i = start + 1; i < stop; i++) {
        const m = maskedLines[i];
        if (m && m.trim() && !/^\s/.test(m) && !CONTINUES.test(m)) { end = i; break; }
      }
      while (end > start + 1 && !maskedLines[end - 1].trim()) end--;
      return { line, original: lines.slice(start, end).join("\n"), masked: maskedLines.slice(start, end).join("\n") };
    });
  }
  function suffixLinks(names) {
    const links = new Map();
    for (const [full, href] of names) {
      const parts = full.split(".");
      for (let i = 0; i < parts.length; i++) {
        const suffix = parts.slice(i).join(".");
        if (!links.has(suffix)) links.set(suffix, href);
        else if (links.get(suffix) !== href) links.set(suffix, null);
      }
    }
    return links;
  }
  function nameLinks(declarations, references) {
    const links = suffixLinks(references || []);
    // A declaration on this page is the authoritative destination for its suffix.  Ambiguous local suffixes stay
    // unlinked rather than inheriting an unrelated external declaration with the same short name.
    for (const [suffix, href] of suffixLinks(declarations).entries()) {
      if (href) links.set(suffix, href); else links.delete(suffix);
    }
    for (const [suffix, href] of Array.from(links.entries())) if (!href) links.delete(suffix);
    return links;
  }
  function linkedCode(text, links) {
    const pattern = /[A-Za-z_][\w'!?₀-₉]*(?:\.[A-Za-z_][\w'!?₀-₉]*)*/g;
    let out = "";
    let start = 0;
    for (const found of text.matchAll(pattern)) {
      const id = found[0];
      const href = links.get(id);
      out += esc(text.slice(start, found.index));
      out += href ? "<a href=\"" + esc(href) + "\">" + esc(id) + "</a>" : esc(id);
      start = found.index + id.length;
    }
    return out + esc(text.slice(start));
  }
  function pageReadings(text, declarations, references, traces) {
    // declarations: [[line, qualified name], ...]; references: [[qualified name, href], ...]
    // traces: Map(declaration line -> the Lean steps [line, tactic, goals before, goals after, href]) when Lean was run for
    // the page, else undefined. With it, each step is read from its goals; a declaration the Map lacks is read from source.
    const links = nameLinks(declarations.map(([line, name]) => [name, "#L" + line]), references || []);
    const byLine = new Map();
    for (const span of spans(text, declarations.map((d) => d[0]))) {
      let html = null;
      const context = traces ? { trace: traces.get(span.line) || [], used: new Set() } : null;
      try { html = readDeclaration(span.original, span.masked, links, span.line, context); } catch (e) { html = null; }
      byLine.set(span.line, html);
    }
    return byLine;
  }

  // A Lean run (the lean extension) puts a tactic trace on the page: each step `L<line>-step<k>` with `data-line`, the
  // source line of its tactic. A reading step carries the same line. For each reading step [line, tactic]: the id of
  // the trace step on that line with the same tactic, else the first on that line, else null.
  function traceLinks(reading, trace) {
    return reading.map(([line, tactic]) => {
      const here = trace.filter((t) => t[1] === line);
      const same = here.find((t) => squash(t[2]).slice(0, 40) === squash(tactic).slice(0, 40));
      return (same || here[0] || [null])[0];
    });
  }
  // The lean extension draws a declaration's trace when it is opened, and numbers its steps L<declaration line>-step<k> in
  // the order of its data. The reader holds that data, so it knows the ids before they are on the page.
  const traceMemory = new Map();  // declaration element id -> memoryTrace(...)
  function memoryTrace(declarationLine, steps) {
    return steps.map((s, k) => ["L" + declarationLine + "-step" + (k + 1), String(s[0]), s[1]]);
  }
  // Resolves with the element once the page has drawn it (the trace is fetched and drawn after it is opened), else null.
  function whenDrawn(trace, id) {
    const now = document.getElementById(id);
    if (now || typeof MutationObserver !== "function") return Promise.resolve(now);
    return new Promise((resolve) => {
      const done = (el) => { observer.disconnect(); clearTimeout(timer); resolve(el); };
      const observer = new MutationObserver(() => { const el = document.getElementById(id); if (el) done(el); });
      const timer = setTimeout(() => done(document.getElementById(id)), 15000);
      observer.observe(trace, { childList: true, subtree: true });
    });
  }
  // Idempotent: it runs when a reading is filled and again when a trace has been drawn.
  function linkTrace(li) {
    const trace = li.querySelector("details.trace");
    if (!trace) return;
    const drawn = Array.prototype.map.call(trace.querySelectorAll("li[data-line]"), (t) => {
      const c = t.querySelector(":scope > code");
      return [t.id, t.getAttribute("data-line"), c ? c.textContent : ""];
    });
    const steps = drawn.length ? drawn : (traceMemory.get(li.id) || []);
    const rows = Array.prototype.filter.call(li.querySelectorAll(".rd-steps li[data-line]"), (r) => r.querySelector(":scope > code.rd-tac"));
    const ids = traceLinks(rows.map((r) => [r.getAttribute("data-line"), r.querySelector(":scope > code.rd-tac").textContent]), steps);
    const reading = li.querySelector("details.reading");
    rows.forEach((r, k) => {
      const id = ids[k];
      if (!id) return;
      const target = document.getElementById(id);
      r.id = r.id || id + "-words";
      if (!r.querySelector(":scope > a.rd-goals")) {
        const goals = document.createElement("a");
        goals.className = "rd-goals";
        goals.href = "#" + id;
        goals.textContent = "goals";
        goals.addEventListener("click", (e) => {
          trace.open = true;
          if (document.getElementById(id)) return;  // drawn: the link goes there
          e.preventDefault();
          whenDrawn(trace, id).then((el) => {
            if (!el) return;
            el.scrollIntoView({ block: "center" });
            try { history.replaceState(null, "", "#" + id); } catch (x) { /* a page without history still shows the step */ }
          });
        });
        r.querySelector(":scope > code.rd-tac").after(goals);
      }
      if (target && !target.querySelector(":scope > .rd-words")) {
        const words = document.createElement("a");
        words.className = "rd-words";
        words.href = "#" + r.id;
        words.textContent = "in words";
        words.addEventListener("click", () => { if (reading) reading.open = true; });
        const c = target.querySelector(":scope > code");
        if (c) c.after(words); else target.prepend(words);
      }
    });
  }

  // What the note at the top of a page says about where its readings come from. state: "source" (no Lean run for this
  // site), "pending" (Lean's goals are loading), "goals" (steps are read from them) or "failed" (Lean was run but its
  // goals could not be loaded). info: {derived, total, reason, source}.
  function readingNote(state, info) {
    info = info || {};
    const lead = "Each declaration has a reading: what it says in words, what it assumes, and what each proof step does.";
    const tail = info.source ? " This page loads its source from the pinned commit on GitHub to make them." : "";
    if (state === "goals") {
      return lead + " Lean was run over this site's source, and each step is read from the goals Lean reports before and after it" +
        (info.total ? " (" + info.derived + " of " + info.total + " steps on this page)" : "") + ": the words say how the goals change. " +
        "A step Lean has no goals for is read from the text of its tactic, and says so. A step's “goals” link opens those goals, " +
        "and each step of a tactic trace links back to its words." + tail;
    }
    if (state === "failed") {
      return lead + " Lean was run for this site, but the goals it reported could not be loaded here" +
        (info.reason ? " (" + info.reason + ")" : "") + ", so this reading falls back to the source text." + tail;
    }
    if (state === "pending") return lead + " Loading the goals Lean reported for this site…" + tail;
    return lead + " The reading is derived from source text; it does not reconstruct Lean's intermediate goals. " +
      "Any Lean-backed trust result is reported separately on the Trust page." + tail;
  }

  // The lean extension's trace files: {"v": 1, "d": {"<declaration line>:<name>": [[line, tactic, before, after, href]]}},
  // gzipped. This is the same format trace.js reads when a trace is opened; a payload of another version is refused.
  const traceFiles = new Map();
  function fetchTrace(url) {
    if (!traceFiles.has(url)) {
      const abort = typeof AbortController === "function" ? new AbortController() : null;
      const timer = abort ? setTimeout(() => abort.abort(), 30000) : 0;
      traceFiles.set(url, fetch(url, abort ? { signal: abort.signal } : undefined).then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.arrayBuffer();
      }).then((buffer) => {
        const bytes = new Uint8Array(buffer);
        if (bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
          if (typeof DecompressionStream === "undefined") throw new Error("this browser cannot open gzip trace data");
          return new Response(new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
        }
        return new TextDecoder().decode(bytes);
      }).then((text) => {
        const payload = JSON.parse(text);
        if (!payload || payload.v !== 1 || typeof payload.d !== "object") throw new Error("unknown trace format");
        return payload;
      }).then((payload) => { clearTimeout(timer); return payload; }, (e) => { clearTimeout(timer); throw e; }));
    }
    return traceFiles.get(url);
  }
  // Map(declaration line -> steps) for the declarations on the page, and the first reason a trace could not be read.
  function loadTraces(items) {
    const byLine = new Map();
    let failure = "";
    return Promise.all(items.map((li) => {
      const details = li.querySelector("details.trace[data-trace-src]");
      if (!details) return null;
      return fetchTrace(details.getAttribute("data-trace-src")).then((payload) => {
        const steps = payload.d[details.getAttribute("data-trace-key")];
        if (Array.isArray(steps)) byLine.set(parseInt(li.id.slice(1), 10), steps);
      }, (e) => { failure = failure || (e && e.name === "AbortError" ? "timed out" : e.message); });
    })).then(() => ({ byLine, failure }));
  }

  // ---------------------------------------------------------------- the browser side
  function boot() {
    drawDocs(document);  // descriptions on file pages, gists on the glossary: every page, source or not
    const holder = document.getElementById("lean-source");
    const list = document.querySelector("ol.decls");
    if (!holder || !list) return;
    const pathTitle = document.querySelector(".path-title");
    const sourcePath = pathTitle
      ? pathTitle.textContent.trim().split("/").map((part) => encodeURIComponent(part)).join("/")
      : "";
    // The pinned template belongs to this corpus's shared reader.js, rather
    // than being repeated in every file page. Keep data-src support for older
    // generated pages and custom integrations.
    const source = holder.getAttribute("data-src") ||
      (holder.tagName === "DIV" && SOURCE_URL_TEMPLATE && sourcePath
        ? SOURCE_URL_TEMPLATE.replace("{path}", sourcePath)
        : "");
    const note = document.createElement("details");
    note.id = "reader-note";
    const traced = !!document.querySelector("details.trace");  // the lean extension ran: its tactic traces are on the page
    note.innerHTML = "<summary><strong>Reading guide</strong><span class=\"reader-status\"></span></summary>" +
      "<div class=\"reader-note-body\"><p></p></div>";
    const say = (state, info) => { note.querySelector(".reader-note-body p").textContent = readingNote(state, Object.assign({ source: !!source }, info)); };
    say(traced ? "pending" : "source");
    list.parentNode.insertBefore(note, list);
    const items = Array.prototype.slice.call(list.children).filter((li) => /^L\d+$/.test(li.id));
    const decls = items.map((li) => {
      const c = li.querySelector("code");
      return [parseInt(li.id.slice(1), 10), c ? c.textContent : ""];
    });
    const status = (msg) => { note.querySelector(".reader-status").textContent = msg; };
    const got = source
      ? (status("Loading the source from GitHub to read it…"), fetch(source).then((r) => (r.ok ? r.text() : Promise.reject(new Error("HTTP " + r.status)))))
      : Promise.resolve(JSON.parse(holder.textContent));
    // The goals Lean reported, one fetch per trace file. A trace that cannot be read leaves the reading to the source
    // text, and the note says so; it is never filled in from a guess.
    const gotTraces = traced ? loadTraces(items) : Promise.resolve(null);
    Promise.all([got, gotTraces]).then(([text, found]) => {
      const traces = found && found.byLine.size ? found.byLine : undefined;
      let references = [];
      const mapHolder = document.getElementById("map-data");
      if (mapHolder) {
        try {
          const map = JSON.parse(mapHolder.textContent);
          references = (map.r || []).map((index) => map.n[index]).filter((row) => row && row.length >= 2);
        } catch (e) { /* a broken optional map must not prevent the readings */ }
      }
      const readings = pageReadings(text.replace(/\r\n/g, "\n"), decls, references, traces);
      if (traced) {
        const all = Array.from(readings.values()).join("");
        const derived = (all.match(/data-basis="goals"/g) || []).length;
        say(traces ? "goals" : "failed", { derived, total: derived + (all.match(/data-basis="source"/g) || []).length, reason: found && found.failure });
      }
      const eager = items.length <= 40;
      items.forEach((li, k) => {
        const html = readings.get(decls[k][0]);
        if (!html) return;
        if (traces && traces.get(decls[k][0])) traceMemory.set(li.id, memoryTrace(decls[k][0], traces.get(decls[k][0])));
        const box = document.createElement("details");
        box.className = "reading";
        box.innerHTML = "<summary>Reading: what it says, step by step</summary>";
        const fill = () => {
          if (box.dataset.filled) return;
          box.insertAdjacentHTML("beforeend", "<div class=\"rd\">" + html + "</div>");
          box.dataset.filled = "1";
          typeset(box);
          linkTrace(li);
        };
        // in the declaration first: linkTrace finds the reading's steps there
        li.insertBefore(box, li.querySelector(":scope > details.depmap"));  // the reading comes before the map
        if (eager) { fill(); box.open = true; } else box.addEventListener("toggle", fill);
        // a trace opened first gets its "in words" links too: opening it fills the reading, which stays closed
        const trace = li.querySelector("details.trace");
        if (trace && !eager) trace.addEventListener("toggle", fill);
        // the lean extension sets data-trace-state to "loaded" once it has drawn the steps: they get their "in words" links
        if (trace && typeof MutationObserver === "function") {
          new MutationObserver(() => { if (trace.dataset.traceState === "loaded" && box.dataset.filled) linkTrace(li); })
            .observe(trace, { attributes: true, attributeFilter: ["data-trace-state"] });
        }
      });
      if (document.querySelector("details.reading")) {
        const controls = document.createElement("span");
        controls.className = "reader-controls";
        [["Expand all readings", true], ["Collapse all readings", false]].forEach(([label, open]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = label;
          button.addEventListener("click", () => {
            document.querySelectorAll("details.reading").forEach((reading) => { reading.open = open; });
          });
          controls.appendChild(button);
        });
        note.querySelector(".reader-note-body").appendChild(controls);
      }
      status(eager ? "" : "Open any “Reading” to see it.");
    }).catch((e) => status("Could not load the source (" + e.message + "). The source links still work."));
  }

  // KaTeX ships with the site (in _assets/katex next to this script) and loads the first time a reading has mathematics.
  const ASSETS = typeof document !== "undefined" && document.currentScript ? document.currentScript.src.replace(/[^/]*$/, "") : "";
  let katexLoad = null;
  function loadKatex() {
    if (!katexLoad) {
      katexLoad = new Promise((resolve, reject) => {
        if (self.katex) { resolve(self.katex); return; }
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = ASSETS + "katex/katex.min.css";
        document.head.appendChild(css);
        const js = document.createElement("script");
        js.src = ASSETS + "katex/katex.min.js";
        js.onload = () => (self.katex ? resolve(self.katex) : reject(new Error("no katex")));
        js.onerror = () => reject(new Error("KaTeX did not load"));
        document.head.appendChild(js);
      });
    }
    return katexLoad;
  }
  function typeset(root) {
    const spots = root.querySelectorAll("[data-tex]:not(.typeset)");
    if (!spots.length) return;
    loadKatex().then((katex) => {
      spots.forEach((el) => {
        try {
          // TeX an author wrote may use macros KaTeX lacks: then their text stays, instead of KaTeX's red error
          const display = el.tagName === "DIV" || el.hasAttribute("data-display");
          if (el.hasAttribute("data-doc")) el.innerHTML = docTex(katex, el.getAttribute("data-tex"), display);
          else katex.render(el.getAttribute("data-tex"), el, { displayMode: display, throwOnError: false, strict: "ignore" });
          el.classList.add("typeset");
        } catch (e) { /* the Lean code stays */ }
      });
    }).catch(() => { /* without KaTeX the Lean code stays */ });
  }

  // Doc comments: the core draws their Markdown and marks each $…$, $$…$$, \(…\) or \[…\] as <span class="tex">,
  // written as the author wrote it. The reader typesets those. TeX an author wrote may use macros KaTeX lacks: then it stays as
  // written, never KaTeX's red error. PROJECT_MACROS are the project's own (from its blueprint), filled in when the
  // site is written.
  const PROJECT_MACROS = {"\\C": "\\mathbb{C}", "\\Z": "\\mathbb{Z}", "\\bbc": "\\mathbb{C}", "\\E": "\\mathbb{E}", "\\bbe": "\\mathbb{E}", "\\F": "\\mathbb{F}", "\\bbf": "\\mathbb{F}", "\\bbH": "\\mathbb{H}", "\\bbP": "\\mathbb{P}", "\\bbI": "\\mathbb{I}", "\\bbn": "\\mathbb{N}", "\\bbq": "\\mathbb{Q}", "\\bbr": "\\mathbb{R}", "\\bbt": "\\mathbb{T}", "\\bbz": "\\mathbb{Z}", "\\N": "\\mathbb{N}", "\\lo": "\\mathcal{L}{#1}", "\\abs": "\\left\\lvert #1\\right\\rvert", "\\Abs": "\\lvert #1 \\rvert", "\\brac": "\\left( #1\\right)", "\\norm": "\\lVert #1\\rVert", "\\inn": "\\left\\langle #1 \\right\\rangle", "\\dist": "\\operatorname{dist}", "\\ind": "1_{#1}", "\\tup": "{\\vec{#1}}"};
  const DOC_MACROS = Object.assign({ "\\sp": "^", "\\sb": "_" }, PROJECT_MACROS);  // plain TeX's names for ^ and _
  // What to try when KaTeX refuses the TeX as written: Markdown escapes left in it (`\\#` for \#, `\*` for *), and a
  // command as a sub- or superscript (`f_\max`), which TeX takes and KaTeX wants in braces.
  function docTexTries(tex) {
    const tries = [tex];
    const unescaped = tex.replace(/\\\\(?=[#$%&_{}])/g, "\\").replace(/\\\*/g, "*");
    if (unescaped !== tex) tries.push(unescaped);
    const last = tries[tries.length - 1];
    const braced = last.replace(/([_^])\s*(\\[A-Za-z]+)/g, "$1{$2}");
    if (braced !== last) tries.push(braced);
    return tries;
  }
  function docTex(katex, tex, display) {
    let failure = null;
    for (const t of docTexTries(tex)) {
      try {
        return katex.renderToString(t, { displayMode: display, throwOnError: true, strict: "ignore", macros: Object.assign({}, DOC_MACROS) });
      } catch (e) { failure = failure || e; }
    }
    throw failure;
  }
  function docFormula(text) {
    let display = false, tex = null;
    if (text.startsWith("$$") && text.endsWith("$$") && text.length > 4) {
      display = true; tex = text.slice(2, -2);
    } else if (text.startsWith("$") && text.endsWith("$") && text.length > 2) {
      tex = text.slice(1, -1);
    } else if (text.startsWith("\\[") && text.endsWith("\\]") && text.length > 4) {
      display = true; tex = text.slice(2, -2);
    } else if (text.startsWith("\\(") && text.endsWith("\\)") && text.length > 4) {
      tex = text.slice(2, -2);
    }
    return tex === null || !tex.trim() ? null : { display, tex: tex.trim() };
  }
  // Inline code in explanatory prose often retains Lean's whitespace application syntax (`f x y`).
  // Use the same parser that reads declarations to recognize actual applications, then present them as
  // conventional mathematics (`f(x, y)`). The exact Lean spelling remains in the hover title.
  // Quoted source, declaration statements and fenced code are deliberately outside this surface.
  function proseApplicationText(text) {
    const source = squash(text);
    const t = translator();
    if (!t) return null;
    try {
      const tree = t.parse(source);
      if (!tree || tree.t !== "app") return null;
      const pieces = glueCalls(appArgs(source));
      if (pieces.length < 2) return null;  // already written f(x), or not whitespace application
      const argument = (raw) => {
        let shown = squash(raw);
        if (OPEN.indexOf(shown[0]) >= 0 && matching(shown, 0) === shown.length - 1) {
          shown = shown.slice(1, -1).trim();
        }
        return proseApplicationText(shown) || shown;
      };
      return pieces[0] + "(" + pieces.slice(1).map(argument).join(", ") + ")";
    } catch (e) {
      return null;
    }
  }
  function drawProseApplications(root) {
    const selector = [
      ".doc code", ".title code", ".intuition code", ".steps code", ".l4term code",
      "dl.glossary dd code", "ol.path .title code"
    ].join(", ");
    root.querySelectorAll(selector).forEach((el) => {
      if (el.closest("pre") || el.closest(".l4del-quote") || el.closest("[data-tex]")) return;
      const source = squash(el.textContent);
      const readable = proseApplicationText(source);
      if (!readable) return;
      el.textContent = readable;
      el.classList.add("prose-application");
      el.title = "Lean syntax: " + source;
    });
  }
  function drawDocs(root) {
    drawProseApplications(root);
    let drew = false;
    root.querySelectorAll(".tex:not(.m)").forEach((el) => {
      const formula = docFormula(el.textContent);
      if (!formula) return;
      el.classList.add("m");
      el.setAttribute("data-tex", formula.tex);
      el.setAttribute("data-doc", "");
      if (formula.display) el.setAttribute("data-display", "");
      el.title = "TeX: " + formula.tex;
      drew = true;
    });
    if (drew) typeset(root);
  }

  // `tables`: what tools/vocabulary.cjs turns into the glossary's sections (vocabulary.json)
  const tables = { TYPES, TYPE_FORMS, CLASSES, PREDICATES, SYMBOLS, TACTICS };
  const api = { mask, spans, splitHeader, sayProp, typeWords, givenItems, tacticWords, tacticSteps, readDeclaration, pageReadings, symbolsIn, docFormula, docTex, docTexTries, proseApplicationText, drawProseApplications, tables, DOC_MACROS, traceLinks, memoryTrace, parseGoal, goalChange, goalWords, readingNote };
  if (typeof module === "object" && module.exports) module.exports = api;
  else if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
  }
})();
