// The reader's words for the glossary page, made from the tables in reader.js.
//
//   node packages/reader/tools/vocabulary.cjs > packages/reader/src/lean4_explainer_reader/vocabulary.json
//
// Run it after changing a table in reader.js; a test checks that the committed file is what this makes. The table
// entries are functions of what they are applied to, so each one is shown on a sample use: a tactic with no argument
// when that reads well, otherwise with the sample below. A new table entry with no good reading and no sample stops
// this script, so nothing is published half-explained.
"use strict";
const path = require("path");
const R = require(path.join(__dirname, "..", "src", "lean4_explainer_reader", "reader.js"));
const { TYPES, TYPE_FORMS, CLASSES, PREDICATES, SYMBOLS, TACTICS } = R.tables;

const BAD = /<code><\/code>|<code>\?<\/code>|undefined|NaN/;

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
// Typeset spans need KaTeX, which the glossary page does not load: keep the Lean code they carry.
function plain(html) {
  return html.replace(/<span class="m" data-tex="[^"]*" title="[^"]*">(<code>[\s\S]*?<\/code>)<\/span>/g, "$1");
}
function checked(where, html) {
  html = plain(html);
  if (BAD.test(html)) throw new Error(where + ": no good reading: " + html);
  return html;
}

// [word, sample use] for each TYPE_FORMS pattern, plus the two forms typeWords reads without a pattern
const FORM_SAMPLES = [
  ["Fin", "Fin n"], ["Finset", "Finset α"], ["Set", "Set α"], ["List", "List α"], ["Multiset", "Multiset α"],
  ["Option", "Option α"], ["ZMod", "ZMod n"], ["Polynomial, R[X]", "Polynomial R"], ["Matrix", "Matrix m n R"],
  ["Equiv.Perm", "Equiv.Perm α"], ["SimpleGraph", "SimpleGraph V"], ["Measure", "Measure α"],
  ["EuclideanSpace", "EuclideanSpace ℝ (Fin n)"], ["Ideal", "Ideal R"], ["Subgroup", "Subgroup G"],
  ["Submodule", "Submodule R M"], ["Subring", "Subring R"], ["Subfield", "Subfield K"],
  ["IntermediateField", "IntermediateField K L"],
];
const ARROW_SAMPLES = [["→ (function type)", "α → β"], ["× (pair type)", "α × β"]];

// [what goes in the brackets, what the reading is about] for each class; the rest take a type α
const CLASS_SAMPLES = {
  Field: ["K", "K"], CommRing: ["R", "R"], Ring: ["R", "R"], CommSemiring: ["R", "R"], Semiring: ["R", "R"],
  Group: ["G", "G"], CommGroup: ["G", "G"], AddGroup: ["G", "G"], AddCommGroup: ["G", "G"], Monoid: ["M", "M"],
  Module: ["R M", "M"], NormedAddCommGroup: ["E", "E"], NormedSpace: ["ℝ E", "E"], InnerProductSpace: ["ℝ E", "E"],
  MetricSpace: ["X", "X"], TopologicalSpace: ["X", "X"], MeasurableSpace: ["X", "X"],
  DecidablePred: ["p", "p"], NeZero: ["n", "n"], Fact: ["(Nat.Prime p)", "Nat.Prime p"],
};

// The arguments each property is shown applied to, in Lean's order
const PROPERTY_SAMPLES = {
  Injective: ["f"], Surjective: ["f"], Bijective: ["f"], Continuous: ["f"], ContinuousOn: ["f", "s"],
  ContinuousAt: ["f", "x"], Differentiable: ["ℝ", "f"], DifferentiableAt: ["ℝ", "f", "x"],
  DifferentiableOn: ["ℝ", "f", "s"], HasDerivAt: ["f", "f'", "x"], Monotone: ["f"], StrictMono: ["f"],
  Antitone: ["f"], StrictAnti: ["f"], MonotoneOn: ["f", "s"], Prime: ["p"], Even: ["n"], Odd: ["n"],
  IsSquare: ["n"], Squarefree: ["n"], Irrational: ["x"], Coprime: ["a", "b"], Tendsto: ["f", "atTop", "(𝓝 0)"],
  Summable: ["a"], HasSum: ["a", "s"], IsLeast: ["S", "m"], IsGreatest: ["S", "m"], IsLUB: ["S", "m"],
  IsGLB: ["S", "m"], BddAbove: ["S"], BddBelow: ["S"], Finite: ["S"], Infinite: ["S"], Nonempty: ["S"],
  Countable: ["S"], Measurable: ["f"], Integrable: ["f"], IntervalIntegrable: ["f", "volume", "a", "b"],
  IsOpen: ["U"], IsClosed: ["F"], IsCompact: ["K"], Dense: ["S"], Periodic: ["f", "c"], IsUnit: ["a"],
  Irreducible: ["p"], MeasurableSet: ["S"], Disjoint: ["s", "t"], ContDiff: ["ℝ", "n", "f"],
  ContDiffAt: ["ℝ", "n", "f", "x"], ContinuousWithinAt: ["f", "s", "x"], UniformContinuous: ["f"],
  IntegrableOn: ["f", "s"], MemLp: ["f", "p"], AEMeasurable: ["f"], AEStronglyMeasurable: ["f"],
  StronglyMeasurable: ["f"], MeasurePreserving: ["f"], Transcendental: ["ℤ", "x"], IsAlgebraic: ["ℤ", "x"],
  IsCoprime: ["a", "b"], Collinear: ["ℝ", "S"], Commute: ["a", "b"], Pairwise: ["r"], Perm: ["l₁", "l₂"],
  InjOn: ["f", "s"], SurjOn: ["f", "s", "t"], BijOn: ["f", "s", "t"], MapsTo: ["f", "s", "t"],
  LipschitzWith: ["K", "f"], Involutive: ["f"], LeftInverse: ["g", "f"], RightInverse: ["g", "f"],
  IndepFun: ["X", "Y"], iIndepFun: ["m", "X", "μ"], IdentDistrib: ["X", "Y"], Reachable: ["u", "v"],
  Primrec: ["f"], Computable: ["f"], Colorable: ["G", "n"], IsProbabilityMeasure: ["μ"],
  Sbtw: ["ℝ", "x", "y", "z"], Wbtw: ["ℝ", "x", "y", "z"], LinearIndependent: ["K", "v"], Convex: ["ℝ", "s"],
  ConvexOn: ["ℝ", "s", "f"], ConcaveOn: ["ℝ", "s", "f"], IsBigO: ["l", "f", "g"], IsLittleO: ["l", "f", "g"],
  IsConnected: ["S"],
};

// Arguments for the tactics whose reading needs one
const TACTIC_SAMPLES = {
  rintro: "⟨x, hx⟩", apply: "h", exact: "h", exacts: "[h₁, h₂]", refine: "⟨?_, ?_⟩", "refine'": "⟨_, _⟩",
  rw: "[h]", rewrite: "[h]", rwa: "[h] at h₁", nth_rw: "2 [h]", nth_rewrite: "2 [h]", linear_combination: "h₁ - h₂",
  simp_rw: "[h]", erw: "[h]", grw: "[h]", convert: "h using 1", revert: "x", rename_i: "x y",
  letI: "inst := Classical.decEq α", exact_mod_cast: "h", use: "2", exists: "2", existsi: "2", absurd: "h h'",
  by_cases: "h : x = 0", obtain: "⟨x, hx⟩ := h", rcases: "h with ⟨x, hx⟩", cases: "h", "cases'": "h with x hx",
  induction: "n with", "induction'": "n with n ih", match: "n with", interval_cases: "n", fin_cases: "i",
  trans: "b", subst: "h", unfold: "f", delta: "f", change: "a + 0 = a", show: "a + 0 = a",
  have: "h : 0 < 2 := by norm_num", haveI: "h : 0 < 2 := by norm_num", "have'": "h : 0 < 2 := by norm_num",
  replace: "h : 0 < x := by linarith", suffices: "h : 0 < x by linarith", let: "y := x + 1", set: "y := x + 1 with hy",
  specialize: "h 2", generalize: "e : f x = y", clear: "h", apply_fun: "f at h", all_goals: "simp",
  any_goals: "simp", repeat: "rw [h]", try: "linarith", first: "| simp | ring", case: "zero => simp",
  on_goal: "2 => simp", lift: "n to ℕ using hn", choose: "f hf using h", peel: "h with x hx",
  wlog: "h : a ≤ b with H", nomatch: "h",
};

// In a Reading a phrase like "A chain of steps, each one justified on its own line:" introduces what follows; here it
// stands alone. The anchor is the first spelling of the word ("ℕ" of "ℕ, Nat").
function entry(key, term, example, meaning) {
  return { term, example, meaning: meaning.replace(/:$/, "."), anchor: "r-" + key + "-" + term.split(", ")[0].replace(/\s+/g, "_") };
}

function types() {
  const byMeaning = new Map();
  for (const [word, meaning] of Object.entries(TYPES)) {
    if (!byMeaning.has(meaning)) byMeaning.set(meaning, []);
    byMeaning.get(meaning).push(word);
  }
  const entries = [...byMeaning].map(([meaning, words]) => entry("types", words.join(", "), "", esc(meaning)));
  const forms = TYPE_FORMS.map(([re], index) => {
    const hit = FORM_SAMPLES.find(([, sample]) => re.test(sample));
    if (!hit) throw new Error("TYPE_FORMS[" + index + "] " + re + ": no sample in FORM_SAMPLES");
    return [index, hit[1]];
  });
  for (const [word, sample] of [...FORM_SAMPLES, ...ARROW_SAMPLES])
    entries.push(entry("types", word, sample, checked(sample, R.typeWords(sample))));
  return { entries, forms };
}

function classes() {
  return Object.entries(CLASSES).map(([word, say]) => {
    const [inside, about] = CLASS_SAMPLES[word] || ["α", "α"];
    return entry("classes", word, "[" + word + " " + inside + "]", checked(word, say(about)));
  });
}

function properties() {
  return Object.entries(PREDICATES).map(([word, say]) => {
    const args = PROPERTY_SAMPLES[word];
    if (!args) throw new Error("PREDICATES." + word + ": no sample in PROPERTY_SAMPLES");
    return entry("properties", word, word + " " + args.join(" "), checked(word, say(args)));
  });
}

function symbols() {
  return SYMBOLS.map(([, symbol, words]) => entry("symbols", symbol, "", esc(words)));
}

function tactics() {
  return Object.entries(TACTICS).map(([word, say]) => {
    const bare = plain(say(""));
    if (!BAD.test(bare) && !(word in TACTIC_SAMPLES)) return entry("tactics", word, "", bare);
    const sample = TACTIC_SAMPLES[word];
    if (sample === undefined) throw new Error("TACTICS." + word + ": no good reading without an argument, and no sample");
    return entry("tactics", word, word + " " + sample, checked(word, say(sample)));
  });
}

const typed = types();
const sections = [
  { key: "reader-types", title: "Types", intro: "What kind of object something is. The Reading says these in words wherever they appear.", entries: typed.entries },
  { key: "reader-classes", title: "Structures a type can have", intro: "Written in square brackets, such as [Field K]. Lean finds them by itself (they are type classes).", entries: classes() },
  { key: "reader-properties", title: "Properties", intro: "Statements about functions, numbers and sets that the Reading puts in words, each shown on a sample use.", entries: properties() },
  { key: "reader-symbols", title: "Symbols", intro: "Notation a newcomer may not know. A Reading lists the ones its statement uses.", entries: symbols() },
  { key: "reader-tactics", title: "Tactics", intro: "Steps inside a proof that starts with by. Each says what the tactic does in general; the goal it leaves depends on the proof.", entries: tactics() },
];
const anchors = new Set();
for (const s of sections) for (const e of s.entries) {
  if (anchors.has(e.anchor)) throw new Error("two entries with the anchor " + e.anchor);
  anchors.add(e.anchor);
}
process.stdout.write(JSON.stringify({ made_by: "packages/reader/tools/vocabulary.cjs from reader.js", forms: typed.forms, sections }, null, 1) + "\n");
