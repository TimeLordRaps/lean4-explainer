/* lean2tex: Lean 4 term syntax -> LaTeX, for showing statements and definitions as typeset mathematics.

   A Pratt parser with Lean's precedences reads a term from its source text, and a renderer turns the tree into
   LaTeX with the usual mathematical notation for common Mathlib functions (√, |z|², ∑ with bounds, ∫ with dx,
   binomials, floors, intervals, limits, "for all large enough n", …). It reads text only, so it cannot know types:
   casts (↑, `(x : ℝ)`) are dropped, and `/` is a fraction even on ℕ. Anything it cannot parse returns null, and the
   caller shows the Lean code instead. Every parse is bounded: each loop consumes a token or spends from a budget
   proportional to the input, so malformed input ends quickly. The same file runs in the browser (as
   window.Lean2TeX) and under node for the tests. */
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- tokens
  const SYMBOLS = [
    "<;>", "<->", "∑'", "×ˢ", "⁻¹'", "⌋₊", "⌉₊", "|>.", "∃!", "⌈/⌉", "≃+*", "→+*", "!![",
    "∀ᶠ", "∃ᶠ", "∀ᵐ", "∃ᵐ", "∀ᵉ", "∃ᵉ", "~[", "=O[", "=o[", "=Θ[", "=ᶠ[", "⋃₀", "⋂₀", "![", "→*", "→+", "≃*", "≃+",
    "<|", "|>", "::", ":=", "=>", "->", "<=", ">=", "!=", "==", "''", "..", "//",
    "≠", "≤", "≥", "↔", "→", "←", "∧", "∨", "¬", "∀", "∃", "∑", "∏", "⋃", "⋂", "⨆", "⨅", "∫", "∈", "∉", "⊆", "⊂", "⊇", "⊃",
    "∩", "∪", "∖", "∣", "•", "∘", "×", "⁻¹", "ᶜ", "ˣ", "^", "*", "/", "%", "+", "-", "=", "<", ">", "|", "‖", "⌊", "⌋", "⌈", "⌉",
    "(", ")", "[", "]", "{", "}", "⟨", "⟩", "⦃", "⦄", ",", ";", ":", "↑", "⇑", "↥", "√", "∂", "·", "!", "≡", "↦", "∞", "∅", "#", "@",
    "$", "⊤", "⊥", "\\", "≃", "≅", "⊓", "⊔", "∆", "⬝", "∗", "⊗", "⊕", "′", "≪", "≫", "□", "↪",
  ];
  // first character -> the symbols starting with it, longest first
  const SYMBOL_TABLE = new Map();
  for (const s of SYMBOLS.map((x) => Array.from(x)).sort((a, b) => b.length - a.length)) {
    if (!SYMBOL_TABLE.has(s[0])) SYMBOL_TABLE.set(s[0], []);
    SYMBOL_TABLE.get(s[0]).push(s);
  }
  const IDENT_START = /[A-Za-z_\u0370-\u03BA\u03BC-\u03FF\u1F00-\u1FFF\u2100-\u214F\u{1D400}-\u{1D7FF}ℓ]/u;
  const IDENT_REST = /[A-Za-z0-9_'!?\u0370-\u03FF\u1F00-\u1FFF\u2080-\u209C\u1D62-\u1D6A\u2100-\u214F\u{1D400}-\u{1D7FF}ℓ]/u;
  const SUBSCRIPTS = "₀₁₂₃₄₅₆₇₈₉";
  const SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹";
  const KEYWORDS = new Set(["fun", "if", "then", "else", "let", "have", "by", "in", "with", "match", "do", "show", "from", "at", "using", "where", "MOD", "ZMOD", "PMOD"]);

  function tokenize(src) {
    const out = [];
    const chars = Array.from(src);
    let i = 0;
    const at = (k) => chars[k] || "";
    const last = () => out[out.length - 1];
    while (i < chars.length) {
      const c = chars[i];
      if (/\s/.test(c)) { i++; continue; }
      if (/[0-9]/.test(c)) {
        let j = i;
        while (/[0-9]/.test(at(j))) j++;
        if (at(j) === "." && /[0-9]/.test(at(j + 1))) { j++; while (/[0-9]/.test(at(j))) j++; }
        out.push({ k: "num", v: chars.slice(i, j).join("") });
        i = j;
        continue;
      }
      if (c === "«") {
        let j = i + 1;
        while (j < chars.length && chars[j] !== "»") j++;
        out.push({ k: "id", v: chars.slice(i + 1, j).join("") });
        i = j + 1;
        continue;
      }
      if (IDENT_START.test(c) && c !== "λ") {
        let j = i + 1;
        for (;;) {
          while (j < chars.length && IDENT_REST.test(chars[j])) j++;
          if (at(j) === "." && IDENT_START.test(at(j + 1)) && at(j + 1) !== "λ") { j++; continue; }
          break;
        }
        let word = chars.slice(i, j).join("");
        if ((word === "Type" || word === "Sort") && at(j) === "*") { word += "*"; j++; }  // Type*
        if (word === "ℕ" && at(j) === "+") { word = "ℕ+"; j++; }  // the positive naturals
        const token = { k: KEYWORDS.has(word) ? "kw" : "id", v: word };
        if (word === "answer" && at(j) === "(") token.tight = true;  // answer(…): the answer a problem asks for
        out.push(token);
        i = j;
        continue;
      }
      // a field or projection written right after a name or a closing bracket: `(z j).re`, `x.1`, `G.edgeSet.ncard`
      if (c === "." && out.length && !/\s/.test(chars[i - 1]) && (last().k === "id" || last().k === "field" || /^[)\]⟩}]$/.test(last().v))) {
        let j = i + 1;
        if (/[0-9]/.test(at(j))) { while (/[0-9]/.test(at(j))) j++; }
        else if (IDENT_START.test(at(j))) { while (j < chars.length && IDENT_REST.test(chars[j])) j++; }
        if (j > i + 1) { out.push({ k: "field", v: chars.slice(i + 1, j).join("") }); i = j; continue; }
      }
      let matched = null;
      for (const s of SYMBOL_TABLE.get(c) || []) {
        if (s.every((x, k) => chars[i + k] === x)) { matched = s; break; }
      }
      if (matched) {
        out.push({ k: "op", v: matched.join("") });
        i += matched.length;
        continue;
      }
      if (c === "λ") { out.push({ k: "kw", v: "fun" }); i++; continue; }
      const sub = SUBSCRIPTS.indexOf(c);
      if (sub >= 0 && out.length) { out.push({ k: "op", v: "_sub", n: String(sub) }); i++; continue; }
      const sup = SUPERSCRIPTS.indexOf(c);
      if (sup >= 0 && out.length) { out.push({ k: "op", v: "_sup", n: String(sup) }); i++; continue; }  // ℝ², x³
      throw new Error("unexpected character " + c);
    }
    return out;
  }

  // ---------------------------------------------------------------- parser
  const INFIX = {
    "↔": [20, "n"], "<->": [20, "n"], "→": [25, "r"], "->": [25, "r"], "∨": [30, "r"], "∧": [35, "r"],
    "=": [50, "n"], "≠": [50, "n"], "<": [50, "n"], ">": [50, "n"], "≤": [50, "n"], "≥": [50, "n"], "<=": [50, "n"], ">=": [50, "n"],
    "!=": [50, "n"], "==": [50, "n"], "∈": [50, "n"], "∉": [50, "n"], "⊆": [50, "n"], "⊂": [50, "n"], "⊇": [50, "n"], "⊃": [50, "n"],
    "∣": [50, "n"], "≡": [50, "n"], "≪": [50, "n"], "≫": [50, "n"],
    "≃": [25, "r"], "≅": [25, "r"], "↪": [25, "r"], "≃+*": [25, "r"], "→+*": [25, "r"], "→*": [25, "r"], "→+": [25, "r"], "≃*": [25, "r"], "≃+": [25, "r"],
    "∪": [65, "l"], "∩": [70, "l"], "∖": [70, "l"], "\\": [70, "l"], "⊔": [68, "l"], "⊓": [69, "l"], "∆": [100, "l"],
    "+": [65, "l"], "-": [65, "l"], "*": [70, "l"], "/": [70, "l"], "%": [70, "l"], "⌈/⌉": [70, "l"], "□": [70, "l"], "•": [73, "r"], "∘": [90, "r"],
    "^": [75, "r"], "×ˢ": [82, "r"], "×": [35, "r"], "''": [80, "l"], "⁻¹'": [80, "l"], "::": [67, "r"], "⬝": [70, "l"],
    "<|": [10, "r"], "$": [10, "r"], "|>": [10, "l"], "⊗": [100, "r"], "⊕": [30, "r"],
  };
  // asymptotic comparisons with their filter in brackets: f ~[atTop] g, f =O[atTop] g
  const ASYMPTOTIC = { "~[": 1, "=O[": 1, "=o[": 1, "=Θ[": 1, "=ᶠ[": 1 };
  const BINDER_RELATIONS = ["∈", "∉", "<", "≤", ">", "≥", "⊆", "⊂", "∣", "≠"];
  const QUANTIFIERS = ["∀", "∃", "∃!", "∀ᶠ", "∃ᶠ", "∀ᵐ", "∃ᵐ", "∀ᵉ", "∃ᵉ"];
  const APP = 1024;

  function Parser(tokens) {
    this.t = tokens;
    this.i = 0;
    this.bars = { "|": 0, "‖": 0 };  // open |…| and ‖…‖: inside one, the same bar closes it instead of starting an argument
    this.blocked = [];  // symbols that end the current binder (`|` in {x : T | p}), so they are not arguments either
    this.budget = 64 * tokens.length + 256;  // every loop consumes a token or spends budget, so a parse always ends
  }
  Parser.prototype.spend = function () { if (--this.budget < 0) throw new Error("too complex"); };
  Parser.prototype.peek = function (o) { return this.t[this.i + (o || 0)]; };
  Parser.prototype.next = function () {
    if (this.i >= this.t.length) throw new Error("end");
    this.spend();
    return this.t[this.i++];
  };
  Parser.prototype.isOp = function (v, o) { const t = this.peek(o); return t && t.k === "op" && t.v === v; };
  Parser.prototype.isKw = function (v) { const t = this.peek(); return t && t.k === "kw" && t.v === v; };
  Parser.prototype.expect = function (v) {
    const t = this.next();
    if (!t || t.v !== v) throw new Error("expected " + v);
    return t;
  };
  Parser.prototype.withBlocked = function (symbols, f) {
    const outer = this.blocked;
    this.blocked = outer.concat(symbols);
    try { return f(); } finally { this.blocked = outer; }
  };
  Parser.prototype.startsArg = function () {
    const t = this.peek();
    if (!t) return false;
    if (t.k === "id" || t.k === "num") return true;
    if (t.k === "kw") return t.v === "fun";
    if (this.blocked.indexOf(t.v) >= 0) return false;
    if (t.v === "|" || t.v === "‖") return this.bars[t.v] === 0;
    return ["(", "⟨", "↑", "⇑", "↥", "⌊", "⌈", "∅", "∞", "·", "@", "⊤", "⊥", "{", "![", "!!["].indexOf(t.v) >= 0 ||
      (t.v === "[" && !(this.peek(1) && this.peek(1).k === "kw" && /MOD$/.test(this.peek(1).v)));
  };

  Parser.prototype.expr = function (rbp) {
    let left = this.prefix();
    for (;;) {
      this.spend();
      const t = this.peek();
      if (!t) break;
      // postfix
      if (t.k === "op" && (t.v === "⁻¹" || t.v === "ᶜ" || t.v === "′" || t.v === "ˣ" || t.v === "!") && 1100 > rbp) { this.next(); left = { t: "post", op: t.v, e: left }; continue; }
      if (t.k === "op" && t.v === "_sub") { this.next(); left = { t: "sub", e: left, n: t.n }; continue; }
      if (t.k === "op" && t.v === "_sup") { this.next(); left = { t: "bin", op: "^", a: left, b: { t: "num", v: t.n } }; continue; }
      if (t.k === "field") { this.next(); left = { t: "field", e: left, f: t.v }; continue; }
      if (t.k === "op" && t.v === "|>." && 10 > rbp) {
        this.next();
        const name = this.next();
        if (name.k !== "id") throw new Error("|>.");
        for (const f of name.v.split(".")) left = { t: "field", e: left, f };
        continue;
      }
      if (t.k === "op" && ASYMPTOTIC[t.v]) {
        if (50 <= rbp) break;
        this.next();
        const filter = this.expr(0);
        this.expect("]");
        left = { t: "asym", op: t.v, a: left, b: this.expr(51), l: filter };
        continue;
      }
      if (t.k === "op" && INFIX[t.v]) {
        const [lbp, assoc] = INFIX[t.v];
        if (lbp <= rbp) break;
        this.next();
        const right = this.expr(assoc === "r" ? lbp - 1 : lbp);
        if (t.v === "≡" && this.isOp("[") && this.peek(1) && /MOD$/.test(this.peek(1).v)) {
          this.next();
          const kind = this.next().v;
          const mod = this.expr(0);
          this.expect("]");
          left = { t: "mod", a: left, b: right, n: mod, kind };
          continue;
        }
        left = { t: "bin", op: t.v, a: left, b: right };
        continue;
      }
      if (APP > rbp && this.startsArg()) {
        const arg = this.expr(APP);
        if (arg.t === "named") continue;  // (α := α): an explicit choice of an implicit argument, not shown
        left = left.t === "app" ? { t: "app", f: left.f, args: left.args.concat([arg]) } : { t: "app", f: left, args: [arg] };
        continue;
      }
      break;
    }
    return left;
  };

  Parser.prototype.until = function (closer) {
    const items = [];
    if (this.isOp(closer)) { this.next(); return items; }
    for (;;) {
      items.push(this.expr(0));
      if (this.isOp(",")) { this.next(); continue; }
      this.expect(closer);
      return items;
    }
  };

  // Binders before `,` (∀ ∃ ∑ ∫ …), `=>`/`↦` (fun) or `|` (set-builder). Each bracketed group keeps its own type or
  // bound, so `∀ (k : ℕ) (hk : 2 ≤ k)` reads as "k ∈ ℕ, 2 ≤ k"; `in l` is a range, a set or a filter; `∂μ` a measure.
  Parser.prototype.binders = function (stops) {
    const groups = [];
    let bareGroup = null, lo = null, hi = null, measure = null, within = null, filter = null;
    const open = () => {
      if (!bareGroup) { bareGroup = { names: [], type: null, rel: null, bound: null }; groups.push(bareGroup); }
      return bareGroup;
    };
    const atStop = () => { const t = this.peek(); return !t || (t.k === "op" && stops.indexOf(t.v) >= 0); };
    this.withBlocked(stops, () => {
      while (!atStop()) {
        const t = this.peek();
        if (t.k === "id" || (t.k === "op" && t.v === "·")) { open().names.push(this.next().v); continue; }
        if (t.k === "op" && (t.v === "(" || t.v === "{" || t.v === "[" || t.v === "⦃" || t.v === "⟨")) {
          const close = { "(": ")", "{": "}", "[": "]", "⦃": "⦄", "⟨": "⟩" }[t.v];
          this.next();
          const g = { names: [], type: null, rel: null, bound: null };
          while (this.peek() && this.peek().k === "id") g.names.push(this.next().v);
          if (this.isOp(",")) {  // a pattern such as ⟨a, b⟩ or (a, b): its names
            while (!this.isOp(close)) { const x = this.next(); if (x.k === "id") g.names.push(x.v); }
          }
          if (this.isOp(":")) { this.next(); g.type = this.expr(0); }
          else if (this.peek() && this.peek().k === "op" && BINDER_RELATIONS.indexOf(this.peek().v) >= 0) { g.rel = this.next().v; g.bound = this.expr(51); }
          this.expect(close);
          if (t.v !== "[") groups.push(g);  // an instance argument [Group G] is found by Lean, not shown
          bareGroup = null;
          continue;
        }
        if (t.k === "op" && t.v === ":") { this.next(); open().type = this.expr(0); continue; }
        if (t.k === "kw" && t.v === "in") {
          this.next();
          const e = this.expr(0);
          if (this.isOp("..")) { this.next(); lo = e; hi = this.expr(0); }
          else { open().rel = "∈"; open().bound = e; within = e; }
          continue;
        }
        if (t.k === "op" && t.v === "∂") { this.next(); measure = this.expr(APP); continue; }
        if (t.k === "op" && BINDER_RELATIONS.indexOf(t.v) >= 0) { open().rel = this.next().v; open().bound = this.expr(51); continue; }
        if (t.k === "kw" && t.v === "with") { this.next(); filter = this.expr(0); continue; }
        throw new Error("binder");
      }
    });
    // the flat view used by ∑, ∫ and fun: every name, and the first type and bound given
    const names = [].concat.apply([], groups.map((g) => g.names));
    const typed = groups.find((g) => g.type) || {};
    const bounded = groups.find((g) => g.rel) || {};
    return { groups, names, type: typed.type || null, rel: bounded.rel || null, bound: bounded.bound || null, lo, hi, filter, measure, within };
  };

  Parser.prototype.prefix = function () {
    const t = this.next();
    if (t.k === "num") return { t: "num", v: t.v };
    if (t.k === "id") {
      if (t.v === "sorry") return { t: "sorry" };
      if (t.tight) {
        this.expect("(");
        const e = this.expr(0);
        this.expect(")");
        return { t: "answer", e };
      }
      const parts = t.v.split(".");
      if (parts.length > 1 && /^[a-zα-ω]/u.test(parts[0]) && parts.every((x) => x)) {
        let node = { t: "id", v: parts[0] };  // p.Prime, s.card: a local value and its fields
        for (const f of parts.slice(1)) node = { t: "field", e: node, f };
        return node;
      }
      return { t: "id", v: t.v };
    }
    if (t.k === "kw") {
      if (t.v === "fun") {
        const b = this.binders(["=>", "↦"]);
        this.next();
        return { t: "fun", b, body: this.expr(0) };
      }
      if (t.v === "if") {
        if (this.peek() && this.peek().k === "id" && this.isOp(":", 1)) { this.next(); this.next(); }
        const c = this.expr(0);
        if (!this.isKw("then")) throw new Error("then");
        this.next();
        const a = this.expr(0);
        if (!this.isKw("else")) throw new Error("else");
        this.next();
        return { t: "ite", c, a, b: this.expr(0) };
      }
      throw new Error("keyword " + t.v);
    }
    if (QUANTIFIERS.indexOf(t.v) >= 0) {
      const b = this.binders([","]);
      this.expect(",");
      return { t: "quant", q: t.v, b, body: this.expr(0) };
    }
    switch (t.v) {
      case "(": {
        if (this.isOp(")")) { this.next(); return { t: "unit" }; }
        if (this.peek() && this.peek().k === "id" && this.isOp(":=", 1)) {  // (α := α)
          let depth = 1;
          while (depth) { const x = this.next(); if (x.v === "(") depth++; else if (x.v === ")") depth--; }
          return { t: "named" };
        }
        const e = this.expr(0);
        if (this.isOp(":")) { this.next(); const ty = this.expr(0); this.expect(")"); return { t: "ascr", e, ty }; }
        if (this.isOp(",")) { this.next(); const rest = this.until(")"); return { t: "tuple", items: [e].concat(rest) }; }
        this.expect(")");
        return { t: "paren", e };
      }
      case "⟨": return { t: "anon", items: this.until("⟩") };
      case "[": return { t: "list", items: this.until("]") };
      case "![": return { t: "vec", items: this.until("]") };
      case "!![": {
        const rows = [[]];
        while (!this.isOp("]")) {
          rows[rows.length - 1].push(this.expr(0));
          if (this.isOp(",")) this.next();
          else if (this.isOp(";")) { this.next(); rows.push([]); }
          else if (!this.isOp("]")) throw new Error("matrix");
        }
        this.next();
        return { t: "matrix", rows };
      }
      case "{": {
        // {x | p}, {x : T | p}, {x ∈ s | p}, {x // p}; then {f x | x ∈ s}; then a literal {a, b}
        const save = this.i;
        try {
          const b = this.binders(["|", "//"]);
          const bar = this.next().v;
          const body = this.expr(0);
          this.expect("}");
          return { t: "setOf", b, body, subtype: bar === "//" };
        } catch (e) {
          this.i = save;
        }
        try {
          const e = this.withBlocked(["|"], () => this.expr(0));
          this.expect("|");
          const b = this.binders(["}"]);
          this.expect("}");
          return { t: "setImage", e, b };
        } catch (e) {
          this.i = save;
        }
        return { t: "setLit", items: this.until("}") };
      }
      case "|": case "‖": {
        this.bars[t.v]++;
        let e;
        try { e = this.expr(0); } finally { this.bars[t.v]--; }
        this.expect(t.v);
        return { t: t.v === "|" ? "abs" : "norm", e };
      }
      case "⌊": { const e = this.expr(0); const c = this.next(); if (c.v !== "⌋" && c.v !== "⌋₊") throw new Error("⌋"); return { t: "floor", e }; }
      case "⌈": { const e = this.expr(0); const c = this.next(); if (c.v !== "⌉" && c.v !== "⌉₊") throw new Error("⌉"); return { t: "ceil", e }; }
      case "-": return { t: "neg", e: this.expr(74) };
      case "¬": return { t: "not", e: this.expr(40) };
      case "↑": case "⇑": case "↥": return { t: "cast", e: this.expr(APP) };
      case "√": return { t: "sqrt", e: this.expr(APP) };
      case "#": return { t: "card", e: this.expr(APP) };
      case "⋃₀": case "⋂₀": return { t: "sUnion", op: t.v, e: this.expr(110) };
      case "@": return this.prefix();
      case "∅": return { t: "sym", tex: "\\emptyset" };
      case "∞": return { t: "sym", tex: "\\infty" };
      case "⊤": return { t: "sym", tex: "\\top" };
      case "⊥": return { t: "sym", tex: "\\bot" };
      case "·": return { t: "sym", tex: "\\cdot" };
      case "∑": case "∏": case "∑'": case "⋃": case "⋂": case "⨆": case "⨅": {
        const b = this.binders([","]);
        this.expect(",");
        return { t: "big", op: t.v, b, body: this.expr(67) };
      }
      case "∫": {
        const b = this.binders([","]);
        this.expect(",");
        const body = this.expr(60);
        let measure = null;
        if (this.isOp("∂")) { this.next(); measure = this.expr(APP); }
        return { t: "integral", b, body, measure };
      }
    }
    throw new Error("unexpected " + t.v);
  };

  function parse(src) {
    const p = new Parser(tokenize(src));
    const e = p.expr(0);
    if (p.i !== p.t.length) throw new Error("trailing " + p.peek().v);
    return e;
  }

  // ---------------------------------------------------------------- rendering
  const GREEK = {
    α: "alpha", β: "beta", γ: "gamma", δ: "delta", ε: "varepsilon", ζ: "zeta", η: "eta", θ: "theta", ι: "iota", κ: "kappa",
    μ: "mu", ν: "nu", ξ: "xi", π: "pi", ρ: "rho", σ: "sigma", τ: "tau", υ: "upsilon", φ: "varphi", χ: "chi", ψ: "psi", ω: "omega",
    Γ: "Gamma", Δ: "Delta", Θ: "Theta", Λ: "Lambda", Ξ: "Xi", Π: "Pi", Σ: "Sigma", Φ: "Phi", Ψ: "Psi", Ω: "Omega", ϕ: "phi", ϵ: "epsilon",
  };
  const BLACKBOARD = {
    "ℕ": "\\mathbb{N}", "ℤ": "\\mathbb{Z}", "ℚ": "\\mathbb{Q}", "ℝ": "\\mathbb{R}", "ℂ": "\\mathbb{C}", "ℍ": "\\mathbb{H}",
    "ℕ+": "\\mathbb{N}^{+}",
  };
  const CONSTANTS = {
    "Real.pi": "\\pi", "π": "\\pi", "Complex.I": "i", "True": "\\mathrm{True}", "False": "\\mathrm{False}",
    "Nat": "\\mathbb{N}", "Int": "\\mathbb{Z}", "Rat": "\\mathbb{Q}", "Real": "\\mathbb{R}", "Complex": "\\mathbb{C}", "PNat": "\\mathbb{N}^{+}",
    "NNReal": "\\mathbb{R}_{\\ge 0}", "ENNReal": "[0, \\infty]", "ℝ≥0": "\\mathbb{R}_{\\ge 0}", "ℝ≥0∞": "[0,\\infty]",
    "Polynomial.X": "X", "X": "X", "Set.univ": "\\mathrm{univ}", "Finset.univ": "\\mathrm{univ}", "id": "\\mathrm{id}",
    "atTop": "\\infty", "Filter.atTop": "\\infty", "atBot": "-\\infty", "Filter.atBot": "-\\infty",
  };

  function texText(s) {
    return s.replace(/\\/g, "\\textbackslash{}").replace(/([_%#&{}$^])/g, "\\$1").replace(/~/g, "\\textasciitilde{}");
  }
  // Unicode letters Lean names use: 𝓝 (script), 𝔽 (double-struck), 𝔤 (fraktur), bold and italic letters, ℱ, ℓ, ℵ.
  const ALPHABETS = [
    [0x1D400, "\\mathbf"], [0x1D434, ""], [0x1D468, "\\boldsymbol"], [0x1D49C, "\\mathcal"], [0x1D4D0, "\\mathcal"],
    [0x1D504, "\\mathfrak"], [0x1D538, "\\mathbb"], [0x1D56C, "\\mathfrak"], [0x1D5A0, "\\mathsf"], [0x1D5D4, "\\mathsf"],
  ];
  const LETTERLIKE = {
    "ℬ": "\\mathcal{B}", "ℰ": "\\mathcal{E}", "ℱ": "\\mathcal{F}", "ℋ": "\\mathcal{H}", "ℐ": "\\mathcal{I}", "ℒ": "\\mathcal{L}",
    "ℳ": "\\mathcal{M}", "ℛ": "\\mathcal{R}", "ℓ": "\\ell", "ℭ": "\\mathfrak{C}", "ℌ": "\\mathfrak{H}", "ℑ": "\\mathfrak{I}", "ℜ": "\\mathfrak{R}",
    "ℙ": "\\mathbb{P}", "𝕜": "\\Bbbk", "ℵ": "\\aleph",
  };
  function letterTex(ch) {
    if (GREEK[ch]) return "\\" + GREEK[ch];
    if (BLACKBOARD[ch]) return BLACKBOARD[ch];
    if (LETTERLIKE[ch]) return LETTERLIKE[ch];
    if (/^[A-Za-z]$/.test(ch)) return ch;
    const cp = ch.codePointAt(0);
    for (const [start, command] of ALPHABETS) {
      if (cp >= start && cp < start + 52) {
        const letter = cp < start + 26 ? String.fromCharCode(65 + cp - start) : String.fromCharCode(97 + cp - start - 26);
        return command ? command + "{" + letter + "}" : letter;
      }
    }
    return null;
  }
  // a longer name, e.g. hμ or ε₀pos: ASCII runs upright, Greek and other letters as themselves, subscript digits lowered
  function wordTex(word, inOperator) {
    let out = "", run = "";
    const flush = () => { if (run) { out += inOperator ? texText(run) : "\\mathrm{" + texText(run) + "}"; run = ""; } };
    let digits = "";
    const lower = () => { if (digits) { out = script(out.trim() || "{}", "_", digits) + " "; digits = ""; } };
    for (const ch of Array.from(word)) {
      const digit = SUBSCRIPTS.indexOf(ch);
      if (digit >= 0) { flush(); digits += digit; continue; }
      lower();
      if (/[A-Za-z0-9'_!?.*+]/.test(ch)) { run += ch; continue; }
      flush();
      const letter = letterTex(ch);
      out += letter ? letter + " " : "\\text{" + texText(ch) + "}";
    }
    flush();
    lower();
    return out.trim();
  }
  function identTex(name) {
    if (name === "_") return "\\_";
    if (CONSTANTS[name]) return CONSTANTS[name];
    if (BLACKBOARD[name]) return BLACKBOARD[name];
    const last = name.split(".").pop();
    if (CONSTANTS[last] && /^(Real|Complex|Nat|Int|Filter)\./.test(name)) return CONSTANTS[last];
    const m = Array.from(last);
    // x, x', x₁, x_1, α, α', 𝓝
    const base = m[0];
    const rest = m.slice(1).join("");
    const subscript = rest.match(/^([₀-₉]+|_\d+)('*)$/);
    const primes = rest.match(/^'+$/);
    const one = letterTex(base);
    if (one && (rest === "" || primes)) return one + (primes ? rest : "");
    if (one && subscript) {
      const digits = Array.from(subscript[1].replace(/^_/, "")).map((d) => SUBSCRIPTS.indexOf(d) >= 0 ? String(SUBSCRIPTS.indexOf(d)) : d).join("");
      return one + "_{" + digits + "}" + subscript[2];
    }
    return wordTex(last, false);
  }
  function operatorTex(last) {
    return "\\operatorname{" + wordTex(last, true) + "}";
  }
  function opName(name) {
    const last = name.split(".").pop();
    if (Array.from(last).length === 1) return identTex(last);
    return operatorTex(last);
  }
  // The scripts already at the end of a piece of TeX: "x_{n}^{2}" ends with _ and ^.
  function trailingScripts(s) {
    const marks = [];
    let end = s.length;
    while (s[end - 1] === "}") {
      let depth = 0, i = end - 1;
      for (; i >= 0; i--) { if (s[i] === "}") depth++; else if (s[i] === "{" && --depth === 0) break; }
      if (i <= 0 || (s[i - 1] !== "^" && s[i - 1] !== "_")) break;
      marks.push(s[i - 1]);
      end = i - 1;
    }
    return marks;
  }
  // Attach a subscript or superscript. TeX allows one of each per base, so `(z n).1` is {z_n}_1 and `x⁻¹ ^ k` is (x^{-1})^k.
  function script(base, mark, s) {
    const clash = trailingScripts(base).indexOf(mark) >= 0;
    return (clash ? (mark === "^" ? parens(base) : "{" + base + "}") : base) + mark + "{" + s + "}";
  }

  const PREC = { quant: 0, fun: 0, ite: 0, big: 67, integral: 60, neg: 75, not: 40, mod: 50, asym: 50 };
  function precOf(n) {
    if (n.t === "bin") return INFIX[n.op][0];
    if (n.t === "app") return APP;
    if (PREC[n.t] !== undefined) return PREC[n.t];
    return 2000;
  }
  function bare(n) {
    while (n.t === "paren" || n.t === "ascr" || n.t === "cast") n = n.e;
    return n;
  }
  function wrap(n, min) {
    return precOf(bare(n)) < min ? parens(tex(bare(n))) : tex(n);
  }
  const ATOMS = ["id", "num", "sym", "abs", "norm", "floor", "ceil", "setLit", "setOf", "setImage", "anon", "tuple", "list", "vec", "matrix", "sqrt", "card", "sub", "answer"];
  function atomic(n) {
    n = bare(n);
    return ATOMS.indexOf(n.t) >= 0 || (n.t === "app" && isFunctionCall(n)) || (n.t === "post" && n.op !== "!");
  }
  function isFunctionCall(n) {
    return n.t === "app" && !(n.f.t === "id" && SPECIAL[n.f.v.split(".").pop()]);
  }
  function argTex(n) {
    return tex(bare(n));
  }
  function groupTex(n) {
    // an argument written next to a function or as an exponent base: parenthesize anything not atomic
    const b = bare(n);
    return atomic(b) ? tex(b) : parens(tex(b));
  }
  const INDEX_FUNCS = /^[a-eu-zA-Z]$/;
  const INDEX_ARGS = /^([i-n]|[i-n]\s*[+-]\s*\d|\d+)$/;

  // Mathlib functions with a mathematical notation of their own; keyed by the last part of the name.
  const SPECIAL = {
    sqrt: (a) => a.length === 1 && "\\sqrt{" + argTex(a[0]) + "}",
    exp: (a) => a.length === 1 && (atomic(a[0]) ? "e^{" + argTex(a[0]) + "}" : "\\exp" + parens(argTex(a[0]))),
    log: (a) => a.length === 1 && "\\log " + groupTex(a[0]),
    logb: (a) => a.length === 2 && "\\log_{" + argTex(a[0]) + "} " + groupTex(a[1]),
    sin: (a) => a.length === 1 && "\\sin " + groupTex(a[0]),
    cos: (a) => a.length === 1 && "\\cos " + groupTex(a[0]),
    tan: (a) => a.length === 1 && "\\tan " + groupTex(a[0]),
    arctan: (a) => a.length === 1 && "\\arctan " + groupTex(a[0]),
    arcsin: (a) => a.length === 1 && "\\arcsin " + groupTex(a[0]),
    arccos: (a) => a.length === 1 && "\\arccos " + groupTex(a[0]),
    sinh: (a) => a.length === 1 && "\\sinh " + groupTex(a[0]),
    cosh: (a) => a.length === 1 && "\\cosh " + groupTex(a[0]),
    tanh: (a) => a.length === 1 && "\\tanh " + groupTex(a[0]),
    normSq: (a) => a.length === 1 && "\\lvert " + argTex(a[0]) + " \\rvert^{2}",
    abs: (a) => a.length === 1 && "\\lvert " + argTex(a[0]) + " \\rvert",
    natAbs: (a) => a.length === 1 && "\\lvert " + argTex(a[0]) + " \\rvert",
    norm: (a) => a.length === 1 && "\\lVert " + argTex(a[0]) + " \\rVert",
    choose: (a) => a.length === 2 && "\\binom{" + argTex(a[0]) + "}{" + argTex(a[1]) + "}",
    factorial: (a) => a.length === 1 && groupTex(a[0]) + "!",
    gcd: (a) => a.length === 2 && "\\gcd" + parens(argTex(a[0]) + ", " + argTex(a[1])),
    lcm: (a) => a.length === 2 && "\\operatorname{lcm}" + parens(argTex(a[0]) + ", " + argTex(a[1])),
    max: (a) => a.length === 2 && "\\max" + parens(argTex(a[0]) + ", " + argTex(a[1])),
    min: (a) => a.length === 2 && "\\min" + parens(argTex(a[0]) + ", " + argTex(a[1])),
    floor: (a) => a.length === 1 && "\\lfloor " + argTex(a[0]) + " \\rfloor",
    ceil: (a) => a.length === 1 && "\\lceil " + argTex(a[0]) + " \\rceil",
    deriv: (a) => a.length === 1 ? groupTex(a[0]) + "'" : a.length === 2 && groupTex(a[0]) + "'" + parens(argTex(a[1])),
    iteratedDeriv: (a) => a.length >= 2 && groupTex(a[1]) + "^{(" + argTex(a[0]) + ")}" + (a[2] ? parens(argTex(a[2])) : ""),
    card: (a) => a.length === 1 && "\\lvert " + argTex(a[0]) + " \\rvert",
    ncard: (a) => a.length === 1 && "\\lvert " + argTex(a[0]) + " \\rvert",
    encard: (a) => a.length === 1 && "\\lvert " + argTex(a[0]) + " \\rvert",
    range: (a) => a.length === 1 && "\\{0, \\dots, " + minusOne(a[0]) + "\\}",
    Icc: (a) => a.length === 2 && "[" + argTex(a[0]) + ", " + argTex(a[1]) + "]",
    Ico: (a) => a.length === 2 && "[" + argTex(a[0]) + ", " + argTex(a[1]) + ")",
    Ioc: (a) => a.length === 2 && "(" + argTex(a[0]) + ", " + argTex(a[1]) + "]",
    Ioo: (a) => a.length === 2 && "(" + argTex(a[0]) + ", " + argTex(a[1]) + ")",
    Ici: (a) => a.length === 1 && "[" + argTex(a[0]) + ", \\infty)",
    Ioi: (a) => a.length === 1 && "(" + argTex(a[0]) + ", \\infty)",
    Iic: (a) => a.length === 1 && "(-\\infty, " + argTex(a[0]) + "]",
    Iio: (a) => a.length === 1 && "(-\\infty, " + argTex(a[0]) + ")",
    succ: (a) => a.length === 1 && groupTex(a[0]) + " + 1",
    re: (a) => a.length === 1 && "\\operatorname{Re} " + groupTex(a[0]),
    im: (a) => a.length === 1 && "\\operatorname{Im} " + groupTex(a[0]),
    eval: (a) => a.length === 2 && groupTex(a[1]) + parens(argTex(a[0])),
    degree: (a) => a.length === 1 && "\\deg " + groupTex(a[0]),
    natDegree: (a) => a.length === 1 && "\\deg " + groupTex(a[0]),
    rpow: (a) => a.length === 2 && script(groupTex(a[0]), "^", argTex(a[1])),
    dist: (a) => a.length === 2 && "\\operatorname{dist}" + parens(argTex(a[0]) + ", " + argTex(a[1])),
    inner: (a) => a.length >= 2 && "\\langle " + argTex(a[a.length - 2]) + ", " + argTex(a[a.length - 1]) + " \\rangle",
    sum: (a) => a.length === 2 && bigFromLambda("\\sum", a[0], a[1]),
    prod: (a) => a.length === 2 && bigFromLambda("\\prod", a[0], a[1]),
    tsum: (a) => a.length === 1 && bigFromLambda("\\sum", null, a[0]),
    Tendsto: (a) => a.length === 3 && tendstoTex(a),
    toReal: (a) => a.length === 1 && argTex(a[0]),
    toNNReal: (a) => a.length === 1 && argTex(a[0]),
    ofNat: (a) => a.length === 1 && argTex(a[0]),
    cast: (a) => a.length === 1 && argTex(a[0]),
  };
  // properties read as words after their subject: p.Prime, Nat.Prime p, Function.Injective f
  const PRED = {
    Prime: "prime", Even: "even", Odd: "odd", Squarefree: "squarefree", Infinite: "infinite", Finite: "finite",
    Countable: "countable", Nonempty: "nonempty", Continuous: "continuous", Differentiable: "differentiable",
    Injective: "injective", Surjective: "surjective", Bijective: "bijective", Monotone: "increasing", StrictMono: "strictly increasing",
    Antitone: "decreasing", StrictAnti: "strictly decreasing", IsSquare: "a perfect square", Irrational: "irrational",
    IsUnit: "a unit", IsCompact: "compact", IsOpen: "open", IsClosed: "closed", Summable: "summable",
    Integrable: "integrable", Measurable: "measurable", Bounded: "bounded",
  };
  function predTex(name, subject) {
    const word = Object.prototype.hasOwnProperty.call(PRED, name) && PRED[name];
    return word ? groupTex(subject) + " \\text{ " + word + "}" : null;
  }
  // where a filter goes: atTop is ∞, 𝓝 a is a
  function limitPoint(l) {
    const x = bare(l);
    const name = x.t === "id" ? x.v.split(".").pop() : x.t === "app" && x.f.t === "id" ? x.f.v.split(".").pop() : "";
    if (name === "atTop") return "\\infty";
    if (name === "atBot") return "-\\infty";
    if ((name === "𝓝" || name === "nhds") && x.t === "app" && x.args.length === 1) return tex(bare(x.args[0]));
    return null;
  }
  // Tendsto f atTop (𝓝 a): the limit of f at infinity is a. Written as a method (atTop.Tendsto f l), the filter comes first.
  function tendstoTex(a) {
    let [f, from, to] = a;
    if (limitPoint(f) !== null && limitPoint(from) === null) [f, from] = [from, f];
    const p = limitPoint(from), q = limitPoint(to);
    if (p === null || q === null) return null;
    const g = bare(f);
    if (g.t === "fun" && g.b.names.length === 1) return "\\lim_{" + identTex(g.b.names[0]) + " \\to " + p + "} " + wrap(g.body, 67) + " = " + q;
    return groupTex(f) + "(x) \\to " + q + " \\text{ as } x \\to " + p;
  }
  function bigFromLambda(sym, set, f) {
    const g = bare(f);
    if (g.t === "fun" && g.b.names.length === 1) {
      const v = identTex(g.b.names[0]);
      return sym + bigLimits(v, set ? { rel: "∈", bound: set } : { rel: null }) + " " + wrap(g.body, 67);
    }
    return null;
  }
  function bigLimits(v, b) {
    if (b.lo && b.hi) return "_{" + v + "=" + tex(b.lo) + "}^{" + tex(b.hi) + "}";
    if (b.rel === "∈" && b.bound) {
      const s = bare(b.bound);
      if (s.t === "app" && s.f.t === "id") {
        const fn = s.f.v.split(".").pop();
        if (fn === "range" && s.args.length === 1) return "_{" + v + "=0}^{" + minusOne(s.args[0]) + "}";
        if (fn === "Icc" && s.args.length === 2) return "_{" + v + "=" + tex(bare(s.args[0])) + "}^{" + tex(bare(s.args[1])) + "}";
        if (fn === "Ico" && s.args.length === 2) return "_{" + v + "=" + tex(bare(s.args[0])) + "}^{" + minusOne(s.args[1]) + "}";
      }
      return "_{" + v + " \\in " + tex(s) + "}";
    }
    if (b.rel && b.bound) return "_{" + v + " " + REL[b.rel] + " " + tex(bare(b.bound)) + "}";
    if (b.type) {
      const ty = bare(b.type);
      if (ty.t === "app" && ty.f.t === "id" && ty.f.v === "Fin" && ty.args.length === 1) return "_{" + v + "=0}^{" + minusOne(ty.args[0]) + "}";
    }
    return "_{" + v + "}";
  }
  // the last index of `range n`: n - 1, written without the `+ 1 - 1` when n is `m + 1`
  function minusOne(n) {
    const b = bare(n);
    if (b.t === "num" && /^\d+$/.test(b.v)) return String(Math.max(0, Number(b.v) - 1));
    if (b.t === "bin" && b.op === "+" && bare(b.b).t === "num" && bare(b.b).v === "1") return tex(bare(b.a));
    return wrap(b, 66) + " - 1";
  }
  const REL = {
    "=": "=", "≠": "\\neq", "<": "<", ">": ">", "≤": "\\le", "≥": "\\ge", "<=": "\\le", ">=": "\\ge", "!=": "\\neq", "==": "=",
    "∈": "\\in", "∉": "\\notin", "⊆": "\\subseteq", "⊂": "\\subset", "⊇": "\\supseteq", "⊃": "\\supset", "∣": "\\mid",
    "↔": "\\iff", "<->": "\\iff", "→": "\\to", "->": "\\to", "∧": "\\land", "∨": "\\lor", "≃": "\\simeq", "≅": "\\cong",
    "↪": "\\hookrightarrow", "≃+*": "\\cong", "→+*": "\\to", "→*": "\\to", "→+": "\\to", "≃*": "\\cong", "≃+": "\\cong",
    "∪": "\\cup", "∩": "\\cap", "∖": "\\setminus", "\\": "\\setminus", "⊔": "\\sqcup", "⊓": "\\sqcap", "∆": "\\mathbin{\\triangle}",
    "+": "+", "-": "-", "%": "\\bmod", "•": "\\cdot", "∘": "\\circ", "×ˢ": "\\times", "×": "\\times", "::": "::", "⊗": "\\otimes", "⊕": "\\oplus", "⬝": "\\cdot",
    "□": "\\mathbin{\\square}", "≪": "\\ll", "≫": "\\gg",
  };
  const LOGIC = ["↔", "<->", "→", "->", "∧", "∨", "=", "≠", "<", ">", "≤", "≥", "∈", "∉", "⊆", "⊂", "⊇", "⊃", "∣", "≡", "≪", "≫"];
  // a binder that only states a condition: (_ : p.Prime), (hk : 2 ≤ k)
  function isCondition(g) {
    if (!g.type) return false;
    const shown = g.names.filter((x) => x !== "_");
    const ty = bare(g.type);
    const prop = (ty.t === "bin" && LOGIC.indexOf(ty.op) >= 0) || ["quant", "not", "mod", "asym"].indexOf(ty.t) >= 0 ||
      ((ty.t === "field" || ty.t === "app") && predTex(ty.t === "field" ? ty.f : (ty.f.t === "id" ? ty.f.v.split(".").pop() : ""), ty.t === "field" ? ty.e : ty.args[0]) !== null);
    return shown.length === 0 || (prop && shown.every((x) => /^h/.test(x)));
  }
  function binderGroupTex(g) {
    if (isCondition(g)) return tex(bare(g.type));
    const names = g.names.filter((x) => x !== "_").map(identTex).join(", ");
    if (!names) return "";
    if (g.rel && g.bound) return names + " " + REL[g.rel] + " " + tex(bare(g.bound));
    if (g.type) {
      const ty = bare(g.type);
      if (ty.t === "id" && (BLACKBOARD[ty.v] || CONSTANTS[ty.v])) return names + " \\in " + tex(ty);
      if (ty.t === "app" && ty.f.t === "id" && /^(Set|Finset)$/.test(ty.f.v) && ty.args.length === 1) return names + " \\subseteq " + tex(bare(ty.args[0]));
      if (ty.t === "bin" && ty.op === "→") return names + " \\colon " + tex(ty);
    }
    return names;
  }
  function bindersTex(b) {
    return (b.groups || [b]).map(binderGroupTex).filter(Boolean).join(", ");
  }
  // ∀ᶠ n in atTop: "for all large enough n"; ∃ᶠ: "for infinitely many n"; ∀ᵐ x ∂μ: "for almost every x"
  function quantTex(n) {
    const b = n.b;
    const vars = b.names.filter((x) => x !== "_").map(identTex).join(", ");
    const point = b.within ? limitPoint(b.within) : null;
    const body = ",\\ " + tex(n.body);
    switch (n.q) {
      case "∀ᶠ":
        if (point === "\\infty") return "\\text{for all large enough } " + vars + body;
        if (point !== null) return "\\text{for all } " + vars + " \\text{ near } " + point + body;
        return "\\text{eventually" + (b.within ? " along } " + tex(bare(b.within)) + "\\text{" : "") + ", for } " + vars + body;
      case "∃ᶠ":
        if (point === "\\infty") return "\\text{for infinitely many } " + vars + body;
        return "\\text{frequently" + (b.within ? " along } " + tex(bare(b.within)) + "\\text{" : "") + ", for } " + vars + body;
      case "∀ᵐ": return "\\text{for almost every } " + vars + body;
      case "∃ᵐ": return "\\text{for a positive-measure set of } " + vars + body;
    }
    const q = { "∀": "\\forall", "∃": "\\exists", "∃!": "\\exists!", "∀ᵉ": "\\forall", "∃ᵉ": "\\exists" }[n.q];
    return q + " " + bindersTex(b) + body;
  }
  // f ~[atTop] g, f =O[atTop] g: comparing two functions, shown through their values
  function sideTex(x) {
    const y = bare(x);
    return y.t === "fun" ? tex(y.body) : tex(y);
  }

  function tex(n) {
    switch (n.t) {
      case "num": return n.v;
      case "id": return n.v === "_" ? hole : identTex(n.v);
      case "sym": return n.tex;
      case "sorry": return "\\text{sorry}";
      case "answer": return "\\boxed{" + (bare(n.e).t === "sorry" ? "\\,?\\," : tex(bare(n.e))) + "}";
      case "unit": return "()";
      case "paren": return atomic(n.e) ? tex(bare(n.e)) : parens(tex(bare(n.e)));
      case "ascr": return tex(n.e);
      case "cast": return tex(n.e);
      case "tuple": return parens(n.items.map((x) => tex(bare(x))).join(", "));
      case "vec": return parens(n.items.map((x) => tex(bare(x))).join(", "));
      case "matrix": return "\\begin{pmatrix} " + n.rows.map((r) => r.map((x) => tex(bare(x))).join(" & ")).join(" \\\\ ") + " \\end{pmatrix}";
      case "anon": return "\\langle " + n.items.map((x) => tex(bare(x))).join(", ") + " \\rangle";
      case "list": return "[" + n.items.map((x) => tex(bare(x))).join(", ") + "]";
      case "setLit": return "\\{" + n.items.map((x) => tex(bare(x))).join(", ") + "\\}";
      case "setOf": return "\\{" + bindersTex(n.b) + " \\mid " + tex(n.body) + "\\}";
      case "setImage": return "\\{" + tex(bare(n.e)) + " \\mid " + bindersTex(n.b) + "\\}";
      case "abs": return "\\lvert " + tex(bare(n.e)) + " \\rvert";
      case "norm": return "\\lVert " + tex(bare(n.e)) + " \\rVert";
      case "floor": return "\\lfloor " + tex(bare(n.e)) + " \\rfloor";
      case "ceil": return "\\lceil " + tex(bare(n.e)) + " \\rceil";
      case "sqrt": return "\\sqrt{" + tex(bare(n.e)) + "}";
      case "card": return "\\lvert " + tex(bare(n.e)) + " \\rvert";
      case "sUnion": return (n.op === "⋃₀" ? "\\bigcup " : "\\bigcap ") + groupTex(n.e);
      case "neg": return "-" + wrap(n.e, 75);
      case "not": return "\\neg " + wrap(n.e, 40);
      case "sub": return script(groupTex(n.e), "_", n.n);
      case "post":
        if (n.op === "⁻¹") return script(groupTex(n.e), "^", "-1");
        if (n.op === "ᶜ") return script(groupTex(n.e), "^", "\\complement");
        if (n.op === "ˣ") return script(groupTex(n.e), "^", "\\times");
        if (n.op === "!") return groupTex(n.e) + "!";
        return groupTex(n.e) + "'";
      case "field": {
        const f = n.f;
        if (/^\d+$/.test(f)) return script(groupTex(n.e), "_", f);
        const special = SPECIAL[f] && SPECIAL[f]([n.e]);
        if (special) return special;
        const pred = predTex(f, n.e);
        if (pred) return pred;
        return operatorTex(f) + parens(tex(bare(n.e)));
      }
      case "mod": return wrap(n.a, 51) + " \\equiv " + wrap(n.b, 51) + " \\pmod{" + tex(bare(n.n)) + "}";
      case "asym": {
        const a = sideTex(n.a), b = sideTex(n.b);
        if (n.op === "~[") return a + " \\sim " + b;
        if (n.op === "=ᶠ[") return a + " = " + b + " \\text{ eventually}";
        return a + " = " + { "=O[": "O", "=o[": "o", "=Θ[": "\\Theta" }[n.op] + parens(b);
      }
      case "bin": return binTex(n);
      case "app": return appTex(n);
      case "fun": return bindersTex(n.b) + " \\mapsto " + tex(n.body);
      case "ite": return "\\begin{cases} " + tex(n.a) + " & \\text{if } " + tex(n.c) + " \\\\ " + tex(n.b) + " & \\text{otherwise} \\end{cases}";
      case "quant": return quantTex(n);
      case "big": {
        const sym = { "∑": "\\sum", "∏": "\\prod", "∑'": "\\sum", "⋃": "\\bigcup", "⋂": "\\bigcap", "⨆": "\\sup", "⨅": "\\inf" }[n.op];
        const v = n.b.names.map(identTex).join(", ");
        let lim = bigLimits(v, n.b);
        if (n.op === "∑'" && lim === "_{" + v + "}" && n.b.type && bare(n.b.type).t === "id" && /^(ℕ|Nat)$/.test(bare(n.b.type).v)) lim = "_{" + v + "=0}^{\\infty}";
        if (n.b.filter) lim = lim.replace(/\}$/, ",\\ " + tex(n.b.filter) + "}");
        return sym + lim + " " + wrap(n.body, 67);
      }
      case "integral": {
        const v = n.b.names.map(identTex).join(", ") || "x";
        let lim = "";
        if (n.b.lo && n.b.hi) lim = "_{" + tex(bare(n.b.lo)) + "}^{" + tex(bare(n.b.hi)) + "}";
        else if (n.b.bound) lim = "_{" + tex(bare(n.b.bound)) + "}";
        const d = n.measure ? "\\, d" + groupTex(n.measure) + parens(v) : "\\, d" + v;
        return "\\int" + lim + " " + wrap(n.body, 61) + d;
      }
    }
    throw new Error("no rendering for " + n.t);
  }

  function binTex(n) {
    const [p, assoc] = INFIX[n.op];
    const lmin = assoc === "l" ? p : p + 1;
    const rmin = assoc === "r" ? p : p + 1;
    if (n.op === "/") return "\\frac{" + tex(bare(n.a)) + "}{" + tex(bare(n.b)) + "}";
    if (n.op === "⌈/⌉") return "\\left\\lceil \\frac{" + tex(bare(n.a)) + "}{" + tex(bare(n.b)) + "} \\right\\rceil";
    if (n.op === "^") {
      const base = bare(n.a);
      const fn = base.t === "app" && base.f.t === "id" && base.args.length === 1 && base.f.v.split(".").pop();
      if (fn && /^(sin|cos|tan|sinh|cosh|tanh)$/.test(fn) && bare(n.b).t === "num") return "\\" + fn + "^{" + bare(n.b).v + "} " + groupTex(base.args[0]);
      return script(groupTex(n.a), "^", tex(bare(n.b)));
    }
    if (n.op === "<|" || n.op === "$") return appTex({ t: "app", f: n.a, args: [n.b] });
    if (n.op === "|>") return appTex({ t: "app", f: n.b, args: [n.a] });
    if (n.op === "''") return groupTex(n.a) + parens(tex(bare(n.b)));
    if (n.op === "⁻¹'") return script(groupTex(n.a), "^", "-1") + parens(tex(bare(n.b)));
    if (n.op === "≪" || n.op === "≫") return sideTex(n.a) + " " + REL[n.op] + " " + sideTex(n.b);
    const right = bare(n.b);
    // ∀, ∑, fun… written without brackets on the right reach to the end of their group, so they need none here;
    // brackets the author wrote are kept (they are a paren node, not the binder itself)
    let unwrapped = n.b;
    while (unwrapped.t === "cast") unwrapped = unwrapped.e;
    const openRight = ["quant", "fun", "big", "integral", "ite"].indexOf(unwrapped.t) >= 0;
    const a = wrap(n.a, lmin), b = openRight ? tex(unwrapped) : wrap(n.b, rmin);
    if (n.op === "*") {
      // 2n, πr, x(y + z): a number, a letter or a constant is written right next to what it multiplies
      const shortLeft = /^(\d+(\.\d+)?|[A-Za-z]'*(_\{[^{}]*\})?|\\[a-zA-Z]+)$/.test(a) ||
        (bare(n.a).t === "bin" && bare(n.a).op === "*" && a.indexOf("\\cdot") < 0);  // n(n + 1)(2n + 1)
      const joinable = ["id", "app", "abs", "norm", "sqrt", "big", "integral", "sub", "post", "sym", "field", "floor", "ceil"].indexOf(right.t) >= 0 ||
        /^(\\left)?\(/.test(b);
      return a + (shortLeft && joinable && !/^[0-9-]/.test(b) ? " " : " \\cdot ") + b;
    }
    return a + " " + (REL[n.op] || texText(n.op)) + " " + b;
  }

  // \left( … \right) is an "inner" atom in TeX: after a name or a factor it leaves a thin gap ("P (n, k)").
  // Plain parentheses read right; \left and \right only grow them around something tall.
  const TALL = /\\(?:frac|dfrac|tfrac|binom|sum|prod|int|oint|bigcup|bigcap|sqrt|begin|left|lim|limsup|liminf|underbrace|overbrace|substack)(?![a-zA-Z])|\\(?:sup|inf|max|min)_/;
  function parens(s) {
    return TALL.test(s) ? "\\left(" + s + "\\right)" : "(" + s + ")";
  }
  function appTex(n) {
    let f = bare(n.f);
    let args = n.args;
    // `n.choose k`, `x.log`: a method call on a value is the function applied to that value first
    if (f.t === "field" && !/^\d+$/.test(f.f)) { args = [f.e].concat(args); f = { t: "id", v: f.f }; }
    if (f.t === "id") {
      const last = f.v.split(".").pop();
      const special = SPECIAL[last] && SPECIAL[last](args);
      if (special) return special;
      const pred = args.length === 1 && predTex(last, args[0]);
      if (pred) return pred;
      const name = identTex(f.v);
      // a sequence indexed by a variable: z j -> z_j
      if (args.length === 1 && INDEX_FUNCS.test(name) && INDEX_ARGS.test(squashTex(args[0]))) return name + "_{" + tex(bare(args[0])) + "}";
      const head = Array.from(last).length === 1 || /^\\[a-zA-Z]+$/.test(name) || /_\{\d+\}$/.test(name) ? name : operatorTex(last);
      return head + parens(args.map((x) => tex(bare(x))).join(", "));
    }
    return groupTex(f) + parens(args.map((x) => tex(bare(x))).join(", "));
  }
  function squashTex(n) {
    const b = bare(n);
    if (b.t === "id") return b.v;
    if (b.t === "num") return b.v;
    if (b.t === "bin" && (b.op === "+" || b.op === "-") && bare(b.a).t === "id" && bare(b.b).t === "num") return bare(b.a).v + b.op + bare(b.b).v;
    return "?";
  }

  // ---------------------------------------------------------------- entry points
  // options.calc: a line of a calc chain, `_ ≤ b * b`, whose `_` stands for the previous right-hand side and is left blank
  let hole = "\\_";
  const LET = /^\s*let(I)?\s+([^\n;:=]*?)\s*(?::[^\n;=]*)?:=\s*([^\n;]*?)\s*(?:;|\n)([\s\S]*)$/;
  function readable(src) {
    const s = String(src).trim();
    return s && !/\b(by|match|do|let|have|show|calc)\b/.test(s) && s.length <= 1500 ? s : null;
  }
  // `let m := n + 1` before a statement: the statement, then "where m = n + 1". The source keeps its line breaks.
  function withLets(src, render) {
    const lets = [];
    let body = String(src);
    for (let m = body.match(LET); m && lets.length < 8; m = body.match(LET)) {
      if (m[2]) lets.push([m[2], m[3]]);  // `letI := …` names nothing: an instance for Lean, not part of the statement
      body = m[4];
    }
    const s = readable(body);
    if (!s) return null;
    const main = render(parse(s));
    if (!lets.length) return main;
    const where = lets.map(([name, value]) => {
      if (!/^[^\s()⟨⟩,]+$/.test(name)) throw new Error("pattern let");
      return identTex(name) + " = " + tex(parse(readable(value) || "("));
    });
    return main + " \\quad \\text{where } " + where.join(",\\ ");
  }
  function toTex(src, options) {
    try {
      hole = options && options.calc ? "" : "\\_";
      const out = withLets(src, tex);
      return out === null ? null : out.trim();
    } catch (e) {
      return null;
    } finally {
      hole = "\\_";
    }
  }
  // `f(x, y) = body` for a definition with explicit arguments, or `f = body`; a value written `fun n => …` gives `f(n) = …`.
  // `relation` replaces the `=`: a statement is defined with `\iff`.
  function definitionTex(name, args, body, relation) {
    if (!name) return null;
    try {
      return withLets(body, (tree) => {
        let inputs = args.slice();
        while (bare(tree).t === "fun" && bare(tree).b.names.length && bare(tree).b.names.every((x) => x !== "_" && x !== "·")) {
          inputs = inputs.concat(bare(tree).b.names);
          tree = bare(tree).body;
        }
        const head = inputs.length ? appTex({ t: "app", f: { t: "id", v: name }, args: inputs.map((a) => ({ t: "id", v: a })) }) : opName(name);
        return head + " " + (relation || "=") + " " + tex(tree);
      });
    } catch (e) {
      return null;
    }
  }

  const api = { toTex, definitionTex, tokenize, parse };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Lean2TeX = api;
})(typeof self !== "undefined" ? self : this);
