import Lean
open Lean Meta Elab

/-!
# Pipeline

The Lean side of the implication pipeline. Everything is read from Lean's own environment: compiled modules through
`importModules` (nothing here parses `.olean` files), bridge files through Lean's frontend.

    lean --run Pipeline.lean extract OUT.jsonl MODULE...
    lean --run Pipeline.lean attempt PLAN.json OUT.jsonl
    lean --run Pipeline.lean contract PLAN.json OUT.jsonl

`extract` prints one JSON object per declaration the modules define:

  name, kind, module, levels, range        identity and where it is
  type, binders, conclusion                the elaborated type, each binder with how it is passed
  conclusion_head, arg_heads, hyp_heads    the formal structure the candidate index is built from
  statement_uses, proof_uses               constants in the type, and in the elaborated proof term (direct uses,
                                           looking through the auxiliary declarations Lean makes for one proof)
  axioms                                   every axiom the declaration depends on (memoized, like `collectAxioms`)
  doc                                      the start of its doc string, if any
  projection                               for a structure's field: the structure, the field, its index, and
                                           whether the structure is a class (Lean's projection info); else null

`attempt` runs bounded derivations. The sources are local hypotheses (`source1 : S₁`), never the released proofs,
so a derivation depends on what the sources state and nothing else of theirs. A found proof is added through the
kernel as `∀ (source1 : S₁) …, D`, its axioms are audited, its dependency closure must not reach the target, and
each source must occur in it. With `instantiate`, the derivation is then applied to the released theorems and
audited again.

`contract` checks a curated edge: the proposition its text states (sources as hypotheses, then its hypotheses, then
its conclusion) is elaborated, and the bridge's proof term is checked against it by the kernel.
-/

def binderInfoName : BinderInfo → String
  | .default => "explicit"
  | .implicit => "implicit"
  | .strictImplicit => "strict-implicit"
  | .instImplicit => "instance"

def kindName : ConstantInfo → String
  | .axiomInfo _ => "axiom"
  | .defnInfo _ => "def"
  | .thmInfo _ => "theorem"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quot"
  | .inductInfo _ => "inductive"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"

def headName (e : Expr) : String :=
  match e.getAppFn with
  | .const n _ => n.toString
  | .fvar _ => "<local>"
  | .sort _ => "<sort>"
  | .forallE .. => "<pi>"
  | .lam .. => "<lambda>"
  | .lit _ => "<literal>"
  | _ => "<other>"

/-- An auxiliary declaration Lean made while elaborating another one (`foo._proof_1`, `_auxLemma`, …). A private
declaration's name starts with `_private` too, but it is a real declaration, so its user name is what is tested. -/
def isAux (n : Name) : Bool :=
  (privateToUserName n).isInternal

/-- Declarations Lean makes on its own: they are not results anyone states. -/
def isNoise (env : Environment) (n : Name) : Bool :=
  isAux n || isAuxRecursor env n || isNoConfusion env n || isRecCore env n || Meta.isMatcherCore env n

/-! ## Common to the search and the contract checks -/

structure Cfg where
  corpus : Array Name := #[`OAI, `ComparatorChallenges]  -- module prefixes whose definitions are unfolded and audited
  heartbeats : Nat := 200000          -- per attempt, in units of the `maxHeartbeats` option
  ms : Nat := 20000                   -- per attempt, wall clock
  depth : Nat := 2                    -- backward steps through the sources
  dischargers : Array String := #["omega", "norm_num", "positivity", "linarith"]
  boundClosers : Array String := #["linarith", "nlinarith", "omega"]
  dischargeHeartbeats : Nat := 20000  -- per tactic call
  allowedAxioms : Array Name := #[``propext, ``Quot.sound, ``Classical.choice]

def jsonStrs (j : Json) (k : String) : Array String := (j.getObjValAs? (Array String) k).toOption.getD #[]
def jsonStr (j : Json) (k : String) : String := (j.getObjValAs? String k).toOption.getD ""
def jsonNat (j : Json) (k : String) (d : Nat) : Nat := (j.getObjValAs? Nat k).toOption.getD d

def parseCfg (j : Json) : Cfg :=
  let d : Cfg := {}
  { corpus := match (j.getObjValAs? (Array String) "corpus").toOption with
      | some xs => xs.map String.toName
      | none => d.corpus
    heartbeats := jsonNat j "heartbeats" d.heartbeats
    ms := jsonNat j "ms" d.ms
    depth := jsonNat j "depth" d.depth
    dischargers := match (j.getObjValAs? (Array String) "dischargers").toOption with
      | some xs => xs
      | none => d.dischargers
    boundClosers := match (j.getObjValAs? (Array String) "bound_closers").toOption with
      | some xs => xs
      | none => d.boundClosers
    dischargeHeartbeats := jsonNat j "discharge_heartbeats" d.dischargeHeartbeats }

def moduleOf (env : Environment) (n : Name) : Option Name :=
  (env.getModuleIdxFor? n).map fun idx => env.allImportedModuleNames[idx.toNat]!

/-- A constant of the corpus (or declared by this run), as opposed to Mathlib or Lean. -/
def isCorpusConst (cfg : Cfg) (env : Environment) (n : Name) : Bool :=
  match moduleOf env n with
  | some m => cfg.corpus.any (·.isPrefixOf m)
  | none => true

def ppStr (e : Expr) : MetaM String := do return toString (← ppExpr e)

/-- Unfold corpus definitions at the head of a proposition, a bounded number of times: statements are often stated
through one (`theorem main : MainStatement`). Mathlib's definitions are left as they are. -/
partial def unfoldHead (cfg : Cfg) (e : Expr) (fuel : Nat := 4) : MetaM Expr := do
  let e := (← instantiateMVars e).headBeta
  if fuel == 0 then return e
  match e.getAppFn with
  | .const c _ =>
    if isCorpusConst cfg (← getEnv) c then
      if let some e' ← unfoldDefinition? e then return ← unfoldHead cfg e' (fuel - 1)
    return e
  | _ => return e

/-- `forallTelescope` through corpus definitions that unfold to further binders. -/
partial def telescopeNorm (cfg : Cfg) (e : Expr) (k : Array Expr → Expr → MetaM α) (fuel : Nat := 4) : MetaM α := do
  let e ← unfoldHead cfg e
  forallTelescope e fun xs body => do
    let body' ← unfoldHead cfg body
    if fuel > 0 && body'.isForall then
      telescopeNorm cfg body' (fun ys b => k (xs ++ ys) b) (fuel - 1)
    else k xs body'

partial def metaTelescopeNorm (cfg : Cfg) (e : Expr) (fuel : Nat := 4) : MetaM (Array Expr × Array BinderInfo × Expr) := do
  let e ← unfoldHead cfg e
  let (ms, bis, body) ← forallMetaTelescope e
  let body' ← unfoldHead cfg body
  if fuel > 0 && body'.isForall then
    let (ms2, bis2, b2) ← metaTelescopeNorm cfg body' (fuel - 1)
    return (ms ++ ms2, bis ++ bis2, b2)
  return (ms, bis, body')

abbrev Memo := IO.Ref (Std.HashMap Name (Array Name))

def union (acc : Array Name) (xs : Array Name) : Array Name :=
  xs.foldl (fun a x => if a.contains x then a else a.push x) acc

/-- Axioms a constant depends on, memoized across the whole run. An inductive type counts its constructors; a
constructor or a recursor counts its inductive types. -/
partial def axiomsOf (memo : Memo) (n : Name) : CoreM (Array Name) := do
  if let some r := (← memo.get)[n]? then return r
  memo.modify (·.insert n #[])  -- a cycle (an inductive and its constructors) reads the partial set
  let env ← getEnv
  let ofExpr (acc : Array Name) (e : Expr) : CoreM (Array Name) := do
    let mut acc := acc
    for u in e.getUsedConstants do
      acc := union acc (← axiomsOf memo u)
    return acc
  let result ← match env.find? n with
    | some (.axiomInfo _) => pure #[n]
    | some (.defnInfo v) => do ofExpr (← ofExpr #[] v.type) v.value
    | some (.thmInfo v) => do ofExpr (← ofExpr #[] v.type) v.value
    | some (.opaqueInfo v) => do ofExpr (← ofExpr #[] v.type) v.value
    | some (.quotInfo _) => pure #[]
    | some (.inductInfo v) => do
        let mut acc ← ofExpr #[] v.type
        for c in v.ctors do
          if let some ci := env.find? c then acc ← ofExpr acc ci.type
        pure acc
    | some (.ctorInfo v) => do pure (union (← ofExpr #[] v.type) (← axiomsOf memo v.induct))
    | some (.recInfo v) => do
        let mut acc ← ofExpr #[] v.type
        for i in v.all do acc := union acc (← axiomsOf memo i)
        pure acc
    | none => pure #[]
  memo.modify (·.insert n result)
  return result

/-- Direct uses of a proof or value, looking through the auxiliary declarations Lean made while elaborating it. -/
partial def directUses (env : Environment) (owner : Name) (e : Expr) (seen : NameSet := {}) : Array Name × NameSet := Id.run do
  let mut out : Array Name := #[]
  let mut seen := seen
  for u in e.getUsedConstants do
    if seen.contains u then continue
    seen := seen.insert u
    if u != owner && isAux u then
      if let some ci := env.find? u then
        if let some v := ci.value? (allowOpaque := true) then
          let (more, s) := directUses env owner v seen
          seen := s
          for m in more do
            if !out.contains m then out := out.push m
          continue
    if u != owner && !out.contains u then out := out.push u
  return (out, seen)

def filtered (env : Environment) (xs : Array Name) : Array String :=
  (xs.filter fun u => !isNoise env u).map Name.toString

def describe (cfg : Cfg) (memo : Memo) (ci : ConstantInfo) (moduleName : Name) : MetaM Json := do
  let env ← getEnv
  let n := ci.name
  let axs ← axiomsOf memo n
  let range ← findDeclarationRanges? n
  let doc ← findDocString? env n
  let typeStr := toString (← ppExpr ci.type)
  let (binders, conclusion, head, argHeads, hypHeads) ← forallTelescope ci.type fun xs body => do
    let mut bs : Array Json := #[]
    let mut hyps : Array String := #[]
    for x in xs do
      let d ← x.fvarId!.getDecl
      let isP ← isProp d.type
      bs := bs.push (Json.mkObj [("name", toJson d.userName.toString), ("info", toJson (binderInfoName d.binderInfo)),
        ("type", toJson (toString (← ppExpr d.type))), ("prop", toJson isP)])
      if isP && !d.binderInfo.isInstImplicit then hyps := hyps.push (headName d.type)
    let args := body.getAppArgs
    let lastTwo := (args.extract (args.size - min 2 args.size) args.size).map headName
    return (bs, toString (← ppExpr body), headName body, lastTwo, hyps)
  let value? := ci.value? (allowOpaque := true)
  let proofUses := match value? with
    | some v => filtered env (directUses env n v).1
    | none => #[]
  let isPropType ← isProp ci.type
  let isInst := (← isInstance n)
  -- the statement as the search reads it: corpus definitions at the head unfolded, binders introduced
  let norm ← if !isPropType then pure Json.null else telescopeNorm cfg ci.type fun xs body => do
    let mut hyps := #[]
    for x in xs do
      let d ← x.fvarId!.getDecl
      if (← isProp d.type) && !d.binderInfo.isInstImplicit then hyps := hyps.push (headName (← unfoldHead cfg d.type))
    let mut parts := #[]
    if body.isAppOfArity ``And 2 || body.isAppOfArity ``Iff 2 then
      parts := #[headName (← unfoldHead cfg (body.getArg! 0)), headName (← unfoldHead cfg (body.getArg! 1))]
    let ex ← if body.isAppOfArity ``Exists 2 then
        lambdaTelescope (body.getArg! 1) fun _ b => do
          let b ← unfoldHead cfg b
          let inner := if b.isAppOfArity ``And 2 then #[headName (b.getArg! 0), headName (b.getArg! 1)] else #[]
          pure (Json.mkObj [("witness_type", toJson (headName (body.getArg! 0))), ("body_head", toJson (headName b)),
            ("body_parts", toJson inner)])
      else pure Json.null
    let whole ← instantiateMVars (← mkForallFVars xs body)
    return Json.mkObj [("conclusion_head", toJson (headName body)), ("hyp_heads", toJson hyps), ("part_heads", toJson parts),
      ("exists", ex), ("binders", toJson xs.size), ("uses", toJson (filtered env whole.getUsedConstants))]
  let rangeJson := match range with
    | some r => Json.mkObj [("line", toJson r.range.pos.line), ("column", toJson r.range.pos.column),
        ("end_line", toJson r.range.endPos.line)]
    | none => Json.null
  -- a structure's field: what every object of the structure carries by its definition
  let projection := match env.getProjectionFnInfo? n with
    | some info => Json.mkObj [("structure", toJson info.ctorName.getPrefix.toString),
        ("field", toJson (match n with | .str _ s => s | _ => n.toString)), ("index", toJson info.i),
        ("class", toJson info.fromClass)]
    | none => Json.null
  return Json.mkObj [
    ("name", toJson n.toString), ("user_name", toJson (privateToUserName n).toString),
    ("private", toJson (isPrivateName n)), ("kind", toJson (kindName ci)), ("module", toJson moduleName.toString),
    ("levels", toJson (ci.levelParams.map Name.toString)), ("range", rangeJson), ("projection", projection),
    ("prop", toJson isPropType), ("instance", toJson isInst),
    ("type", toJson typeStr), ("type_hash", toJson (toString (hash ci.type))),
    ("binders", Json.arr binders), ("conclusion", toJson conclusion), ("conclusion_head", toJson head),
    ("arg_heads", toJson argHeads), ("hyp_heads", toJson hypHeads),
    ("statement_uses", toJson (filtered env ci.type.getUsedConstants)), ("proof_uses", toJson proofUses),
    ("norm", norm), ("axioms", toJson (axs.map Name.toString)), ("sorry", toJson (axs.contains ``sorryAx)),
    ("doc", match doc with | some d => toJson (d.take 300) | none => Json.null)]

def extractMain (args : List String) : IO UInt32 := do
  let out :: modules := args | IO.eprintln "usage: Pipeline extract OUT.jsonl [--corpus=P,Q] MODULE..."; return 2
  -- the corpus's module prefixes (whose definitions the normal form unfolds), when not the default
  let (cfg, modules) : Cfg × List String := match modules with
    | m :: rest => if m.startsWith "--corpus=" then
        ({ corpus := (((m.drop 9).toString.splitOn ",").filter (· ≠ "")).toArray.map String.toName }, rest) else ({}, modules)
    | [] => ({}, [])
  -- one argument may name a file listing the modules, one per line
  let modules ← if let [m] := modules then
      if m.startsWith "@" then
        let text ← IO.FS.readFile ⟨(m.drop 1).toString⟩
        pure (text.splitOn "\n" |>.map (fun l => l.trimAscii.toString) |>.filter (· ≠ ""))
      else pure [m]
    else pure modules
  if modules.isEmpty then IO.eprintln "no modules"; return 2
  let started ← IO.monoMsNow
  let env ← importModules (modules.toArray.map fun m => { module := m.toName }) {} (trustLevel := 1024) (loadExts := true)
  let loaded ← IO.monoMsNow
  let wanted : Std.HashMap Nat Name := Id.run do
    let mut m := {}
    for m' in modules do
      if let some idx := env.getModuleIdx? m'.toName then m := m.insert idx.toNat m'.toName
    return m
  -- the declarations of the wanted modules
  let mut decls : Array (ConstantInfo × Name) := #[]
  for (n, ci) in env.constants.map₁.toList do
    if let some idx := env.getModuleIdxFor? n then
      if let some mod := wanted[idx.toNat]? then
        unless isNoise env n do decls := decls.push (ci, mod)
  let handle ← IO.FS.Handle.mk out .write
  let ctx : Core.Context := { fileName := "<extract>", fileMap := default, maxHeartbeats := 0, options := {} }
  let memo ← IO.mkRef {}
  let act : CoreM Nat := do
    let mut failed := 0
    for (ci, mod) in decls do
      try
        let j ← (describe cfg memo ci mod).run'
        handle.putStrLn j.compress
      catch e =>
        failed := failed + 1
        handle.putStrLn (Json.mkObj [("name", toJson ci.name.toString), ("module", toJson mod.toString),
          ("error", toJson (← e.toMessageData.toString))]).compress
    return failed
  let (failed, _) ← act.toIO ctx { env }
  let done ← IO.monoMsNow
  IO.println (Json.mkObj [("modules", toJson modules), ("declarations", toJson decls.size), ("failed", toJson failed),
    ("import_ms", toJson (loaded - started)), ("extract_ms", toJson (done - loaded))]).compress
  return 0

/-- Whether the corpus constants reachable from `roots` through types and values include a forbidden one; the walk
stops at Mathlib and Lean, which cannot refer to the corpus. Returns the path to the first one reached. -/
partial def reaches (cfg : Cfg) (roots : Array Name) (forbidden : Array Name) : CoreM (Option (List Name)) := do
  if forbidden.isEmpty then return none
  let env ← getEnv
  let visited ← IO.mkRef ({} : NameSet)
  let rec go (n : Name) (path : List Name) : CoreM (Option (List Name)) := do
    if forbidden.contains n then return some (n :: path).reverse
    if (← visited.get).contains n then return none
    visited.modify (·.insert n)
    unless isCorpusConst cfg env n do return none
    let some ci := env.find? n | return none
    let mut uses := ci.type.getUsedConstants
    if let some v := ci.value? (allowOpaque := true) then uses := uses ++ v.getUsedConstants
    match ci with
    | .inductInfo v => uses := uses ++ v.ctors.toArray
    | .ctorInfo v => uses := uses.push v.induct
    | .recInfo v => uses := uses ++ v.all.toArray
    | _ => pure ()
    for u in uses do
      if let some p ← go u (n :: path) then return some p
    return none
  for r in roots do
    if let some p ← go r [] then return some p
  return none

/-- Add a theorem through the kernel. Returns the kernel's complaint, if it has one. -/
def kernelAdd (name : Name) (levels : List Name) (type value : Expr) : CoreM (Option String) := do
  try
    addDecl (.thmDecl { name, levelParams := levels, type, value, all := [name] })
    return none
  catch e => return some (← e.toMessageData.toString)

def auditAxioms (cfg : Cfg) (n : Name) : CoreM (Array Name × Array Name) := do
  let axs ← collectAxioms n
  return (axs, axs.filter (!cfg.allowedAxioms.contains ·))

def outcome (id status reason : String) (extra : List (String × Json) := []) : Json :=
  Json.mkObj ([("id", toJson id), ("status", toJson status), ("reason", toJson reason)] ++ extra)

def coreCtx (name : String) : Core.Context :=
  { fileName := name, fileMap := default, maxHeartbeats := 0,
    options := (({} : Options).setBool `autoImplicit false).setBool `Elab.async false }

/-! ## The search -/

structure Fact where
  label : String  -- which source, and which view of it
  src : Nat       -- 1-based source index
  value : Expr
  type : Expr

structure Search where
  cfg : Cfg
  facts : Array Fact
  steps : IO.Ref (Array Json)
  budgetHit : IO.Ref (Option String)

/-- A source, and the implications its conclusion contains: an `↔` read in each direction, an `∧` in each part. -/
def views (cfg : Cfg) (label : String) (src : Nat) (h : Expr) : MetaM (Array Fact) := do
  let ty ← instantiateMVars (← inferType h)
  let base : Fact := { label, src, value := h, type := ty }
  let extra ← telescopeNorm cfg ty fun xs body => do
    let applied := mkAppN h xs
    let mk (lbl : String) (fn : Name) : MetaM (Option Fact) := do
      try
        let v ← mkLambdaFVars xs (← mkAppM fn #[applied])
        return some { label := s!"{label}, {lbl}", src, value := v, type := ← inferType v }
      catch _ => return none
    if body.isAppOfArity ``Iff 2 then
      return #[← mk "left to right" ``Iff.mp, ← mk "right to left" ``Iff.mpr].filterMap id
    if body.isAppOfArity ``And 2 then
      return #[← mk "first part" ``And.left, ← mk "second part" ``And.right].filterMap id
    return #[]
  return #[base] ++ extra

/-- `(relation, carrier, lhs, rhs)` of an order statement, with `≥` and `>` read as `≤` and `<` reversed. -/
def ineqParts (e : Expr) : Option (Name × Expr × Expr × Expr) :=
  match e.getAppFnArgs with
  | (``LE.le, #[α, _, a, b]) => some (``LE.le, α, a, b)
  | (``LT.lt, #[α, _, a, b]) => some (``LT.lt, α, a, b)
  | (``GE.ge, #[α, _, a, b]) => some (``LE.le, α, b, a)
  | (``GT.gt, #[α, _, a, b]) => some (``LT.lt, α, b, a)
  | _ => none

def logStep (s : Search) (fields : List (String × Json)) : MetaM Unit :=
  s.steps.modify (·.push (Json.mkObj fields))

/-- Run one tactic on a goal under its own heartbeat budget. A tactic this environment lacks counts as failing. -/
def runTactic (s : Search) (goal : MVarId) (tac : String) : MetaM Bool := do
  let stx ← match Parser.runParserCategory (← getEnv) `tactic tac with
    | .ok stx => pure stx
    | .error _ => return false
  let st ← saveState
  let closed ← withTheReader Core.Context (fun c => { c with maxHeartbeats := s.cfg.dischargeHeartbeats * 1000 }) <|
    withCurrHeartbeats <| tryCatchRuntimeEx
      (do
        let gs ← Term.TermElabM.run' (Term.withoutErrToSorry (Tactic.run goal (Tactic.evalTactic stx)))
        pure gs.isEmpty)
      (fun e => do
        if e.isInterrupt then throw e
        if e.isRuntime then s.budgetHit.set (some s!"{tac} reached its heartbeat limit")
        pure false)
  unless closed do st.restore
  return closed

/-- What proves the statement with no source at all: its own hypotheses, or one of the dischargers. A derivation of
such a statement says nothing about its sources, so it is not counted as one. -/
def holdsAlone (cfg : Cfg) (stmt : Expr) : MetaM (Option String) := do
  if stmt.hasFVar then return none  -- it mentions something outside itself: it cannot be checked alone
  let st ← saveState
  let s : Search := { cfg, facts := #[], steps := ← IO.mkRef #[], budgetHit := ← IO.mkRef none }
  -- an empty local context: the sources are in scope where this is called, and must not count as its hypotheses
  let found ← withLCtx {} {} <| try
      (do
        let g ← mkFreshExprMVar stmt
        let (_, g) ← g.mvarId!.intros
        let g ← (try g.casesAnd catch _ => pure g)
        if ← g.withContext g.assumptionCore then return some "its own hypotheses"
        for tac in cfg.dischargers do
          if ← g.withContext (runTactic s g tac) then return some tac
        return none : MetaM (Option String))
    catch e => if e.isInterrupt then throw e else pure none
  st.restore
  return found

def discharge (s : Search) (goal : MVarId) (tactics : Array String) : MetaM Bool := goal.withContext do
  let tgt ← instantiateMVars (← goal.getType)
  if tgt.hasExprMVar then return false
  for tac in tactics do
    if ← runTactic s goal tac then
      logStep s [("step", "discharge"), ("by", toJson tac), ("goal", toJson (← ppStr tgt))]
      return true
  return false

def substitutions (ms : Array Expr) (bis : Array BinderInfo) : MetaM Json := do
  let mut out := #[]
  for m in ms, bi in bis do
    if bi.isInstImplicit then continue
    if ← isProp (← instantiateMVars (← inferType m)) then continue
    out := out.push (Json.mkObj [("variable", toJson (← m.mvarId!.getDecl).userName.toString),
      ("value", toJson (← ppStr (← instantiateMVars m)))])
  return Json.arr out

/-- Keep a step's own log entry ahead of the entries its sub-goals added. -/
def placeStep (s : Search) (from_ : Nat) (entry : Json) : MetaM Unit :=
  s.steps.modify fun a => (a.extract 0 from_).push entry ++ a.extract from_ a.size

mutual

partial def tryStep (s : Search) (x : MetaM Bool) : MetaM Bool := do
  let st ← saveState
  let n := (← s.steps.get).size
  let ok ← try x catch e => if e.isInterrupt || e.isRuntime then throw e else pure false
  unless ok do
    st.restore
    s.steps.modify (·.extract 0 n)
  return ok

/-- Prove `goal` from the context and the sources, `depth` backward steps deep. -/
partial def solve (s : Search) (depth : Nat) (goal : MVarId) : MetaM Bool := goal.withContext do
  Core.checkSystem "implication search"
  let tgt ← unfoldHead s.cfg (← instantiateMVars (← goal.getType))
  if tgt.isForall then
    -- the statement's own binder names, so the recorded steps read like the statement
    let g ← goal.replaceTargetDefEq tgt
    let (_, g) ← g.introNP (getIntrosSize tgt)
    -- a hypothesis `a ∧ b` becomes `a` and `b`
    let g ← (try g.casesAnd catch _ => pure g)
    return ← solve s depth g
  if ← goal.assumptionCore then
    logStep s [("step", "assumption"), ("goal", toJson (← ppStr tgt))]
    return true
  if tgt.isAppOfArity ``And 2 then
    let ok ← tryStep s do
      let l ← mkFreshExprMVar (tgt.getArg! 0)
      let r ← mkFreshExprMVar (tgt.getArg! 1)
      if (← solve s depth l.mvarId!) then
        if (← solve s depth r.mvarId!) then
          goal.assign (mkApp4 (mkConst ``And.intro) (tgt.getArg! 0) (tgt.getArg! 1) l r)
          return true
      return false
    if ok then return true
  if depth > 0 then
    for f in s.facts do
      if ← tryStep s (applyFact s depth goal f) then return true
    if tgt.isAppOfArity ``Exists 2 then
      for f in s.facts do
        if ← tryStep s (witnessTransport s depth goal f) then return true
    if (ineqParts tgt).isSome then
      for f in s.facts do
        for left in [true, false] do
          if ← tryStep s (boundTransfer s depth goal f left) then return true
    for f in s.facts do
      for symm in [false, true] do
        if ← tryStep s (rewriteWith s depth goal f symm) then return true
  discharge s goal s.cfg.dischargers

/-- Solve a step's hypotheses, then its instance arguments; every variable must end up determined. -/
partial def fillPremises (s : Search) (depth : Nat) (ms : Array Expr) (bis : Array BinderInfo) : MetaM Bool := do
  for m in ms, bi in bis do
    let mv := m.mvarId!
    if (← mv.isAssigned) || bi.isInstImplicit then continue
    if ← isProp (← instantiateMVars (← mv.getType)) then
      unless ← solve s (depth - 1) mv do return false
  for m in ms, bi in bis do
    let mv := m.mvarId!
    if bi.isInstImplicit && !(← mv.isAssigned) then
      let ty ← instantiateMVars (← mv.getType)
      if ty.hasExprMVar then return false
      let some inst ← (try some <$> synthInstance ty catch _ => pure none) | return false
      unless ← isDefEq m inst do return false
  for m in ms do
    unless ← m.mvarId!.isAssigned do return false  -- no substitution the step does not determine
  return true

/-- Use a fact backward: its conclusion matches the goal, its hypotheses become goals. -/
partial def applyFact (s : Search) (depth : Nat) (goal : MVarId) (f : Fact) : MetaM Bool := goal.withContext do
  let tgt ← instantiateMVars (← goal.getType)
  let (ms, bis, concl) ← metaTelescopeNorm s.cfg (← instantiateMVars f.type)
  if concl.getAppFn.isMVar then return false  -- a conclusion that matches anything is not a rule
  unless ← isDefEq concl tgt do return false
  let n := (← s.steps.get).size
  unless ← fillPremises s depth ms bis do return false
  goal.assign (mkAppN f.value ms)
  placeStep s n (Json.mkObj [("step", "apply"), ("fact", toJson f.label), ("source", toJson f.src),
    ("goal", toJson (← ppStr tgt)), ("substitutions", ← substitutions ms bis)])
  return true

/-- Bound transfer: a fact bounds the same side of an inequality as the goal (`left`: the goals's left side matches
the fact's); arithmetic closes the gap, and it must use the fact. -/
partial def boundTransfer (s : Search) (depth : Nat) (goal : MVarId) (f : Fact) (left : Bool) : MetaM Bool := goal.withContext do
  let tgt ← instantiateMVars (← goal.getType)
  let some (_, αt, lt, rt) := ineqParts tgt | return false
  let (ms, bis, concl) ← metaTelescopeNorm s.cfg (← instantiateMVars f.type)
  let some (_, αf, lf, rf) := ineqParts concl | return false
  unless ← isDefEq αf αt do return false
  unless ← (if left then isDefEq lf lt else isDefEq rf rt) do return false
  let side := if left then "left" else "right"
  let n := (← s.steps.get).size
  unless ← fillPremises s depth ms bis do return false
  let fact ← instantiateMVars (mkAppN f.value ms)
  if fact.hasExprMVar then return false
  let factTy ← instantiateMVars (← inferType fact)
  let (h, g) ← (← goal.assert `bound factTy fact).intro1P
  let closed ← g.withContext do
    for tac in s.cfg.boundClosers do
      if ← runTactic s g tac then
        -- the closing arithmetic must use the bound, or the source did no work
        if (← instantiateMVars (mkMVar g)).containsFVar h then return some tac
    return none
  let some tac := closed | return false
  placeStep s n (Json.mkObj [("step", "bound transfer"), ("fact", toJson f.label), ("source", toJson f.src),
    ("goal", toJson (← ppStr tgt)), ("bound", toJson (← ppStr factTy)), ("shared side", toJson side),
    ("closed by", toJson tac), ("substitutions", ← substitutions ms bis)])
  return true

/-- Witness transport: the goal and a fact both say there is an `x` of the same type with some property; the
fact's witness is the goal's, and its property is a new fact for proving the goal's. No witness is invented. -/
partial def witnessTransport (s : Search) (depth : Nat) (goal : MVarId) (f : Fact) : MetaM Bool := goal.withContext do
  let tgt ← instantiateMVars (← goal.getType)
  unless tgt.isAppOfArity ``Exists 2 do return false
  let (ms, bis, concl) ← metaTelescopeNorm s.cfg (← instantiateMVars f.type)
  unless concl.isAppOfArity ``Exists 2 do return false
  let α := tgt.getArg! 0
  unless ← isDefEq (concl.getArg! 0) α do return false
  let n := (← s.steps.get).size
  unless ← fillPremises s depth ms bis do return false
  let fact ← instantiateMVars (mkAppN f.value ms)
  if fact.hasExprMVar then return false
  let p := (← instantiateMVars concl).getArg! 1
  let q := tgt.getArg! 1
  let u ← getLevel α
  let k ← withLocalDeclD `w α fun a => withLocalDeclD `hw (mkApp p a).headBeta fun ha => do
    let body ← mkFreshExprMVar (mkApp q a).headBeta
    let hviews ← views s.cfg s!"{f.label}, its witness's property" f.src ha
    if ← solve { s with facts := s.facts ++ hviews } (depth - 1) body.mvarId! then
      return some (← mkLambdaFVars #[a, ha] (mkApp4 (mkConst ``Exists.intro [u]) α q a body))
    return none
  let some k := k | return false
  goal.assign (mkApp5 (mkConst ``Exists.elim [u]) α p tgt fact k)
  placeStep s n (Json.mkObj [("step", "witness transport"), ("fact", toJson f.label), ("source", toJson f.src),
    ("goal", toJson (← ppStr tgt)), ("substitutions", ← substitutions ms bis)])
  return true

/-- Rewrite the goal once with an equation the fact gives, then prove what is left. -/
partial def rewriteWith (s : Search) (depth : Nat) (goal : MVarId) (f : Fact) (symm : Bool) : MetaM Bool := goal.withContext do
  let tgt ← instantiateMVars (← goal.getType)
  let (ms, bis, concl) ← metaTelescopeNorm s.cfg (← instantiateMVars f.type)
  unless concl.isAppOfArity ``Eq 3 do return false
  let r ← goal.rewrite tgt (mkAppN f.value ms) symm
  let eNew ← instantiateMVars r.eNew
  if eNew == tgt then return false
  let g ← goal.replaceTargetEq eNew r.eqProof
  let n := (← s.steps.get).size
  unless ← solve s (depth - 1) g do return false
  unless ← fillPremises s depth ms bis do return false
  placeStep s n (Json.mkObj [("step", "rewrite"), ("fact", toJson f.label), ("source", toJson f.src),
    ("direction", toJson (if symm then "right to left" else "left to right")), ("goal", toJson (← ppStr tgt)),
    ("becomes", toJson (← ppStr eNew)), ("substitutions", ← substitutions ms bis)])
  return true

end

/-! ## Attempts -/

/-- A source's universe level that the derivation leaves free (a composition fixes no target's levels, and a
source's own universe need not occur in the target) becomes a universe parameter of the derived theorem, as it is
one of the source: `u_1`, `u_2`, … after the names already taken. -/
def generalizeLevels (levels : List Name) (type value : Expr) : MetaM (List Name) := do
  let st := collectLevelMVars (collectLevelMVars {} type) value
  let mut levels := levels
  let mut k := 1
  for mv in st.result do
    if (← isLevelMVarAssigned mv) then continue
    while levels.contains (Name.mkSimple s!"u_{k}") do k := k + 1
    let n := Name.mkSimple s!"u_{k}"
    assignLevelMVar mv (mkLevelParam n)
    levels := levels ++ [n]
  return levels

/-- Check a found proof: kernel, axioms, what it reaches, which sources it uses. `stmt` is what is derived, in the
context of the source hypotheses `hs`. -/
def finish (cfg : Cfg) (id : String) (hs : Array Expr) (srcLevels : Array (List Level)) (proofBody stmt : Expr)
    (levels : List Name) (forbidden : Array Name) (sources : Array Name) (instantiate : Bool) :
    MetaM (List (String × Json) × String × String) := do
  let proofBody ← instantiateMVars proofBody
  if proofBody.hasExprMVar then return ([], "error", "the proof has unfilled holes")
  let used := hs.map fun h => proofBody.containsFVar h.fvarId!
  let value ← instantiateMVars (← mkLambdaFVars hs proofBody)
  let type ← instantiateMVars (← mkForallFVars hs stmt)
  let levels ← generalizeLevels levels type value
  let value ← instantiateMVars value
  let type ← instantiateMVars type
  if type.hasLevelMVar || value.hasLevelMVar then return ([], "error", "universe levels are not determined")
  let stmt ← instantiateMVars stmt
  let name := (`LeanExplainer.derived).str id
  let mut info : List (String × Json) := [("statement", toJson (← ppStr stmt)), ("derived", toJson (← ppStr type)),
    ("statement_hash", toJson (toString (hash stmt))), ("used", toJson used),
    ("proof", toJson ((← withOptions (fun o => o.setBool `pp.proofs true) (ppStr value)).take 4000))]
  if let some err ← kernelAdd name levels type value then
    return (info, "kernel-rejected", err)
  let (axs, bad) ← auditAxioms cfg name
  info := info ++ [("axioms", toJson (axs.map toString))]
  if !bad.isEmpty then return (info, "audit-failed", s!"uses axioms outside the allowed set: {bad}")
  if let some path ← reaches cfg #[name] forbidden then
    return (info ++ [("reaches", toJson (path.map toString))], "audit-failed", s!"the proof reaches the target: {path}")
  if used.any (!·) then
    let unused := (sources.zip used).filterMap fun (n, u) => if u then none else some n.toString
    return (info, "rejected", s!"does not use {unused}: not a result of all its sources")
  if let some by_ ← holdsAlone cfg stmt then
    return (info, "rejected", s!"the statement holds without the sources (by {by_}): it says nothing about them")
  if instantiate then
    -- the same derivation, applied to the released theorems themselves
    let us ← srcLevels.mapM fun ls => ls.mapM instantiateLevelMVars
    if us.any (·.any (·.hasMVar)) then return (info, "error", "universe levels of a source are not determined")
    let inst := (`LeanExplainer.instantiated).str id
    let instValue := mkAppN (mkConst name (levels.map mkLevelParam)) ((sources.zip us).map fun (n, ls) => mkConst n ls)
    if let some err ← kernelAdd inst levels stmt instValue then
      return (info, "instantiation-failed", err)
    let (iaxs, ibad) ← auditAxioms cfg inst
    info := info ++ [("instantiated_axioms", toJson (iaxs.map toString))]
    if !ibad.isEmpty then
      return (info, "instantiation-failed", s!"the released sources use axioms outside the allowed set: {ibad}")
    if let some path ← reaches cfg #[inst] forbidden then
      return (info ++ [("reaches", toJson (path.map toString))], "instantiation-circular",
        s!"a released source's proof already reaches the target: {path}")
    return (info, "checked-instantiated", "")
  return (info, "checked", "")

/-- Sources as local hypotheses `source1 : S₁`, …, their universe levels left to the search. -/
def withSources [Inhabited α] (sources : Array Name) (k : Array Expr → Array (List Level) → MetaM α) : MetaM α := do
  let mut types := #[]
  let mut levels := #[]
  for n in sources do
    let ci ← getConstInfo n
    let us ← mkFreshLevelMVarsFor ci
    types := types.push (ci.instantiateTypeLevelParams us)
    levels := levels.push us
  let decls := (List.range sources.size).toArray.map fun i =>
    (Name.mkSimple s!"source{i+1}", BinderInfo.default, fun (_ : Array Expr) => (pure types[i]! : MetaM Expr))
  withLocalDecls decls fun hs => k hs levels

def attemptTarget (cfg : Cfg) (id : String) (sources : Array Name) (target : Name) (instantiate : Bool)
    (steps : IO.Ref (Array Json)) (budgetHit : IO.Ref (Option String)) : MetaM Json := do
  if sources.contains target then return outcome id "rejected" "the target is one of the sources"
  let tci ← getConstInfo target
  withSources sources fun hs levels => do
    let mut facts := #[]
    for h in hs, i in [0:hs.size] do
      facts := facts ++ (← views cfg s!"source {i+1}" (i+1) h)
    let s : Search := { cfg, facts, steps, budgetHit }
    let goal ← mkFreshExprMVar tci.type
    if !(← solve s cfg.depth goal.mvarId!) then
      if let some why ← budgetHit.get then return outcome id "budget" why
      return outcome id "no-proof" "no derivation within the rules and depth"
    let (info, status, reason) ← finish cfg id hs levels goal tci.type tci.levelParams #[target] sources instantiate
    return outcome id status reason info

/-- Whether a hypothesis says only that a quantity is positive or nonnegative (`0 < x`, `0 ≤ x`, `x > 0`, `x ≥ 0`):
a composition linked by one says less than its two sources might suggest, and the catalogue says which it is. -/
def isPositivity (e : Expr) : MetaM Bool := do
  let e ← instantiateMVars e
  let zero (z : Expr) : Bool := z.nat? == some 0 || z.isAppOfArity ``Zero.zero 2
  if e.isAppOfArity ``LT.lt 4 || e.isAppOfArity ``LE.le 4 then return zero (e.getArg! 2)
  if e.isAppOfArity ``GT.gt 4 || e.isAppOfArity ``GE.ge 4 then return zero (e.getArg! 3)
  return false

/-- Bind a step's undetermined variables and unproved hypotheses as binders of the derived statement, in order. -/
partial def bindRest [Inhabited α] (s : Search) (ms : Array Expr) (bis : Array BinderInfo) (i : Nat) (acc : Array Expr)
    (k : Array Expr → MetaM α) : MetaM α := do
  if h : i < ms.size then
    let m := ms[i].mvarId!
    if ← m.isAssigned then return ← bindRest s ms bis (i + 1) acc k
    let ty ← instantiateMVars (← m.getType)
    if bis[i]!.isInstImplicit && !ty.hasExprMVar then
      if let some inst ← (try some <$> synthInstance ty catch _ => pure none) then
        if ← isDefEq ms[i] inst then return ← bindRest s ms bis (i + 1) acc k
    if (← isProp ty) && !ty.hasExprMVar then
      -- checked here, not in `m`'s own context: the variables bound so far are locals of this one, and `ty` may
      -- mention them
      let g ← mkFreshExprMVar ty
      if ← g.mvarId!.assumptionCore then
        m.assign (← instantiateMVars g)
        logStep s [("step", "assumption"), ("goal", toJson (← ppStr ty))]
        return ← bindRest s ms bis (i + 1) acc k
      if ← discharge s g.mvarId! s.cfg.dischargers then
        m.assign (← instantiateMVars g)
        return ← bindRest s ms bis (i + 1) acc k
    withLocalDecl (← m.getDecl).userName bis[i]! ty fun x => do
      m.assign x
      bindRest s ms bis (i + 1) (acc.push x) k
  else k acc

/-- Short composition: the first source's conclusion supplies a hypothesis of the second. The derived statement
is the first source's binders, then whatever of the second is left, then the second's conclusion. -/
def attemptCompose (cfg : Cfg) (id : String) (sources : Array Name) (instantiate : Bool)
    (steps : IO.Ref (Array Json)) (budgetHit : IO.Ref (Option String)) : MetaM Json := do
  let #[a, b] := sources | return outcome id "error" "a composition takes two sources"
  withSources sources fun hs levels => do
    let s : Search := { cfg, facts := #[], steps, budgetHit }
    let tyA ← instantiateMVars (← inferType hs[0]!)
    let tyB ← instantiateMVars (← inferType hs[1]!)
    let r? ← telescopeNorm cfg tyA fun xs concA => do
      if concA.isConstOf ``True || concA.isConstOf ``False || (concA.getAppFn.isFVar && xs.contains concA.getAppFn) then
        return none
      let aTerm := mkAppN hs[0]! xs
      let mut supplies : Array (String × Expr × Expr) := #[("conclusion", aTerm, concA)]
      if concA.isAppOfArity ``And 2 then
        supplies := supplies.push ("first part", ← mkAppM ``And.left #[aTerm], concA.getArg! 0)
        supplies := supplies.push ("second part", ← mkAppM ``And.right #[aTerm], concA.getArg! 1)
      let (ms, bis, concB) ← metaTelescopeNorm cfg tyB
      if concB.getAppFn.isMVar then return none
      for j in [0:ms.size] do
        if bis[j]!.isInstImplicit then continue
        let pj ← instantiateMVars (← inferType ms[j]!)
        unless ← isProp pj do continue
        if pj.isConstOf ``True then continue
        for (lbl, t, ty) in supplies do
          let st ← saveState
          if ← isDefEq pj ty then
            ms[j]!.mvarId!.assign t
            logStep s [("step", "supply"), ("from", toJson s!"source 1, {lbl}"), ("hypothesis", toJson (← ppStr ty)),
              ("of", toJson "source 2"), ("hypothesis_head", toJson (headName ty)), ("positivity", toJson (← isPositivity ty))]
            let res ← bindRest s ms bis 0 #[] fun rest => do
              let stmt ← mkForallFVars (xs ++ rest) (← instantiateMVars concB)
              let body ← mkLambdaFVars (xs ++ rest) (← instantiateMVars (mkAppN hs[1]! ms))
              return (stmt, body, ← substitutions ms bis)
            let (stmt, body, subst) := res
            -- the derived statement must say more than either source alone
            if (← withReducible (isDefEq stmt tyA)) || (← withReducible (isDefEq stmt tyB)) then
              return some (Except.error "the derived statement is one of the sources")
            return some (Except.ok (stmt, body, subst))
          st.restore
      return none
    match r? with
    | none => return outcome id "no-proof" "the first source's conclusion supplies no hypothesis of the second"
    | some (.error why) => return outcome id "rejected" why
    | some (.ok (stmt, body, subst)) =>
      let (info, status, reason) ← finish cfg id hs levels body stmt [] #[] #[a, b] instantiate
      return outcome id status reason (info ++ [("substitutions", subst)])

/-- Run `x`, returning any exception it throws, interrupts included. `tryCatchRuntimeEx` rethrows interrupts, and
an attempt's wall-clock limit is one: caught any higher, it ends the whole process. Only the attempt driver uses this,
around a whole attempt. -/
def catchAll (x : CoreM α) : CoreM (Except Exception α) := fun ctx s => do
  match ← (x ctx s).toBaseIO with
  | .ok a => pure (.ok a)
  | .error e => pure (.error e)

def runAttempt (cfg : Cfg) (a : Json) : CoreM Json := do
  -- an attempt may carry its own budget
  let cfg : Cfg := { cfg with
    heartbeats := jsonNat a "heartbeats" cfg.heartbeats
    ms := jsonNat a "ms" cfg.ms
    depth := jsonNat a "depth" cfg.depth }
  let id := jsonStr a "id"
  let rule := jsonStr a "rule"
  let sources := (jsonStrs a "sources").map String.toName
  let target := (jsonStr a "target").toName
  let instantiate := (a.getObjValAs? Bool "instantiate").toOption.getD false
  let steps ← IO.mkRef #[]
  let budgetHit ← IO.mkRef none
  let tk ← IO.CancelToken.new
  let _ ← IO.asTask (do IO.sleep cfg.ms.toUInt32; tk.set)
  let started ← IO.monoMsNow
  let hb0 ← IO.getNumHeartbeats
  let body : CoreM Json := withoutModifyingEnv do
    for n in sources.push target do
      if !n.isAnonymous && !(← getEnv).contains n then return outcome id "error" s!"unknown declaration {n}"
    MetaM.run' <| match rule with
      | "target" => attemptTarget cfg id sources target instantiate steps budgetHit
      | "compose" => attemptCompose cfg id sources instantiate steps budgetHit
      | r => pure (outcome id "error" s!"unknown rule {r}")
  let r ← withTheReader Core.Context (fun c => { c with maxHeartbeats := cfg.heartbeats * 1000, cancelTk? := some tk }) <|
    withCurrHeartbeats <| catchAll body
  tk.set
  let j ← match r with
    | .ok j => pure j
    | .error e =>
      if e.isInterrupt then pure (outcome id "budget" s!"wall-clock limit of {cfg.ms} ms")
      else if e.isRuntime then do pure (outcome id "budget" (← e.toMessageData.toString))
      else do pure (outcome id "error" (← e.toMessageData.toString))
  let ms := (← IO.monoMsNow) - started
  let hb := ((← IO.getNumHeartbeats) - hb0) / 1000
  return j.mergeObj (Json.mkObj [("rule", toJson rule), ("sources", toJson (sources.map toString)),
    ("target", toJson (if target.isAnonymous then "" else target.toString)), ("steps", Json.arr (← steps.get)),
    ("ms", toJson ms), ("heartbeats", toJson hb)])

def attemptMain (args : List String) : IO UInt32 := do
  let [planPath, outPath] := args | IO.eprintln "usage: Pipeline attempt PLAN.json OUT.jsonl"; return 2
  let plan ← IO.ofExcept (Json.parse (← IO.FS.readFile planPath))
  let cfg := parseCfg plan
  let imports := jsonStrs plan "imports"
  let attempts := (plan.getObjValAs? (Array Json) "attempts").toOption.getD #[]
  let started ← IO.monoMsNow
  let env ← importModules (imports.map fun m => { module := m.toName }) {} (trustLevel := 1024) (loadExts := true)
  let loaded ← IO.monoMsNow
  let handle ← IO.FS.Handle.mk outPath .write
  -- first line: the environment imported (so a process that stops later is not taken for an import failure)
  handle.putStrLn (Json.mkObj [("imported", toJson imports.size), ("import_ms", toJson (loaded - started))]).compress
  handle.flush
  let act : CoreM Unit := do
    for a in attempts do
      let j ← runAttempt cfg a
      handle.putStrLn j.compress
      handle.flush
  let _ ← act.toIO (coreCtx "<attempt>") { env }
  IO.println (Json.mkObj [("imports", toJson imports), ("attempts", toJson attempts.size),
    ("import_ms", toJson (loaded - started)), ("attempt_ms", toJson ((← IO.monoMsNow) - loaded))]).compress
  return 0

/-! ## Contracts -/

def elabProp (text : String) : TermElabM Expr := do
  let stx ← match Parser.runParserCategory (← getEnv) `term text with
    | .ok s => pure s
    | .error e => throwError "the contract does not parse: {e}"
  let e ← Term.elabTerm stx (some (mkSort Level.zero))
  Term.synthesizeSyntheticMVarsNoPostponing
  let e ← instantiateMVars e
  if e.hasMVar then throwError "the contract leaves something undetermined: {e}"
  return e

/-- The hypotheses a statement states and its conclusion, read through `∃` (its witness becomes a variable) and
into the last part of a conjunction, as in `∃ c, 0 < c ∧ ∀ …`; with what was read through, in order. -/
partial def hypothesesOf (cfg : Cfg) (e : Expr) (path : Array String := #[]) : MetaM (Array String × String × Array String) :=
  telescopeNorm cfg e fun xs body => do
    let mut hs := #[]
    for x in xs do
      let d ← x.fvarId!.getDecl
      if (← isProp d.type) && !d.binderInfo.isInstImplicit then hs := hs.push (← ppStr d.type)
    if body.isAppOfArity ``Exists 2 && (body.getArg! 1).isLambda then
      let (h2, c, p) ← lambdaTelescope (body.getArg! 1) fun ws inner => do
        let names ← ws.mapM fun w => return (← w.fvarId!.getDecl).userName.toString
        hypothesesOf cfg inner (path.push ("∃ " ++ " ".intercalate names.toList))
      return (hs ++ h2, c, p)
    if body.isAppOfArity ``And 2 then
      let (h2, c, p) ← hypothesesOf cfg (body.getArg! 1) (path.push ((← ppStr (body.getArg! 0)) ++ " ∧"))
      return (hs ++ h2, c, p)
    return (hs, ← ppStr body, path)

/-- Which of the first `n` lambda-bound variables of a proof term occur in its body ([] when it is not a lambda). -/
def usedBinders (v : Expr) (n : Nat) : MetaM (Array Bool) :=
  lambdaTelescope v fun xs body => do
    if xs.size < n then return #[]
    let rest ← mkLambdaFVars (xs.extract n xs.size) body
    return (xs.extract 0 n).map fun x => rest.containsFVar x.fvarId!

def checkContract (cfg : Cfg) (c : Json) : CoreM Json := do
  let id := jsonStr c "id"
  let sources := (jsonStrs c "sources").map String.toName
  let hyps := jsonStrs c "hypotheses"
  let conclusion := jsonStr c "conclusion"
  let bridge := (jsonStr c "bridge").toName
  let target := (jsonStr c "target").toName
  let relation := (jsonStr c "relation").toName      -- strengthens: proves (contract) → the target's statement
  let construction := (jsonStr c "construction").toName  -- supports-construction: the computable definition
  let env ← getEnv
  for n in sources.push bridge do
    unless env.contains n do return outcome id "error" s!"unknown declaration {n}"
  if !target.isAnonymous && !env.contains target then
    return outcome id "error" s!"unknown declaration {target}"
  MetaM.run' do
    -- the proposition the edge states: its sources as hypotheses, then its own hypotheses, then its conclusion
    let text := if hyps.isEmpty then conclusion else s!"∀ {" ".intercalate hyps.toList}, {conclusion}"
    let elaborated ← try pure (Except.ok (← Term.TermElabM.run' (elabProp text)))
      catch e => pure (Except.error (← e.toMessageData.toString))
    let contract ← match elaborated with
      | .ok e => pure e
      | .error msg => return outcome id "contract-error" msg
    let mut srcTypes := #[]
    for n in sources do
      let ci ← getConstInfo n
      unless ci.levelParams.isEmpty do return outcome id "error" s!"{n} is universe polymorphic; a contract takes closed statements"
      srcTypes := srcTypes.push ci.type
    let expected := (List.range sources.size).foldr
      (fun i acc => mkForall (Name.mkSimple s!"source{i+1}") .default srcTypes[i]! acc) contract
    let bci ← getConstInfo bridge
    let mut info : List (String × Json) := [("expected", toJson (← ppStr expected)), ("bridge_type", toJson (← ppStr bci.type)),
      ("identical_up_to_names", toJson (bci.type == expected))]
    let some bvalue := bci.value? (allowOpaque := true) | return outcome id "mismatch" "the bridge has no proof term" info
    unless bci.levelParams.isEmpty do return outcome id "mismatch" "the bridge is universe polymorphic; the contract is not" info
    -- the kernel checks the bridge's proof term against the stated proposition itself
    if let some err ← kernelAdd ((`LeanExplainer.contract).str id) [] expected bvalue then
      return outcome id "mismatch" s!"the bridge's proof does not prove the stated contract: {err}" info
    let (axs, bad) ← auditAxioms cfg bridge
    info := info ++ [("axioms", toJson (axs.map toString))]
    if !bad.isEmpty then return outcome id "audit-failed" s!"the bridge uses axioms outside the allowed set: {bad}" info
    let forbidden := if target.isAnonymous then #[] else #[target]
    if let some path ← reaches cfg #[bridge] forbidden then
      return outcome id "audit-failed" s!"the bridge reaches the target: {path}" (info ++ [("reaches", toJson (path.map toString))])
    let used ← usedBinders bvalue sources.size
    info := info ++ [("used", toJson used)]
    if used.size != sources.size then
      return outcome id "rejected" "the bridge's use of every source could not be determined" info
    if used.any (!·) then return outcome id "rejected" "the bridge does not use every source it names" info
    if !relation.isAnonymous then
      unless (← getEnv).contains relation && (← getEnv).contains target do
        return outcome id "error" "a relation needs both the relation declaration and the target" info
      let tci ← getConstInfo target
      let rci ← getConstInfo relation
      let some rvalue := rci.value? (allowOpaque := true) | return outcome id "relation-mismatch" "the relation has no proof term" info
      let relExpected := mkForall `contract .default contract tci.type
      if let some err ← kernelAdd ((`LeanExplainer.relation).str id) tci.levelParams relExpected rvalue then
        return outcome id "relation-mismatch" s!"the relation does not prove contract → target: {err}" info
      let (raxs, rbad) ← auditAxioms cfg relation
      info := info ++ [("relation_axioms", toJson (raxs.map toString))]
      if !rbad.isEmpty then return outcome id "audit-failed" s!"the relation uses axioms outside the allowed set: {rbad}" info
      if let some path ← reaches cfg #[relation] #[target] then
        return outcome id "audit-failed" s!"the relation reaches the target: {path}" info
      let rused ← usedBinders rvalue 1
      if rused.size != 1 then return outcome id "rejected" "the relation's use of the contract could not be determined" info
      if rused.any (!·) then return outcome id "rejected" "the relation does not use the contract" info
      let (th, tc, tp) ← hypothesesOf cfg tci.type
      let (ch, cc, cp) ← hypothesesOf cfg contract
      info := info ++ [("target_hypotheses", toJson th), ("contract_hypotheses", toJson ch),
        ("target_conclusion", toJson tc), ("contract_conclusion", toJson cc),
        ("target_path", toJson tp), ("contract_path", toJson cp),
        ("target_only_hypotheses", toJson (th.filter (!ch.contains ·)))]
    if !construction.isAnonymous then
      let some cci := (← getEnv).find? construction | return outcome id "error" s!"unknown declaration {construction}" info
      unless cci.isDefinition do return outcome id "rejected" "the construction must be a definition" info
      if isNoncomputable (← getEnv) construction then return outcome id "rejected" "the construction is noncomputable" info
      unless contract.getUsedConstants.contains construction do
        return outcome id "rejected" "the contract does not say anything about the construction" info
    return outcome id "checked" "" info

/-- Elaborates one bridge file (a process imports once: a second import in the same process is not reliable), then
checks each of the plan's contracts in the environment it gives. -/
def contractMain (args : List String) : IO UInt32 := do
  let [planPath, outPath] := args | IO.eprintln "usage: Pipeline contract PLAN.json OUT.jsonl"; return 2
  let plan ← IO.ofExcept (Json.parse (← IO.FS.readFile planPath))
  let cfg := parseCfg plan
  let file := jsonStr plan "bridge_file"
  let handle ← IO.FS.Handle.mk outPath .write
  let opts := (({} : Options).setBool `autoImplicit false).setBool `Elab.async false
  let input ← IO.FS.readFile file
  let ictx := Parser.mkInputContext input file
  let (header, pstate, msgs) ← Parser.parseHeader ictx
  let (env, msgs) ← processHeader header opts msgs ictx (trustLevel := 1024)
  let s ← IO.processCommands ictx pstate (Command.mkState env msgs opts)
  let mut errors := #[]
  for m in s.commandState.messages.toList do
    if m.severity == .error then errors := errors.push s!"line {m.pos.line}: {← m.data.toString}"
  for c in (plan.getObjValAs? (Array Json) "contracts").toOption.getD #[] do
    let id := jsonStr c "id"
    let j ← if !errors.isEmpty then
        pure (outcome id "bridge-error" s!"the bridge file does not elaborate: {errors.toList.take 3}")
      else
        Prod.fst <$> (checkContract cfg c).toIO (coreCtx file) { env := s.commandState.env }
    handle.putStrLn (j.mergeObj (Json.mkObj [("bridge_file", toJson file)])).compress
    handle.flush
  return 0

/-- The constants each module declares, read from its compiled file with Lean's own reader and without importing it,
so that modules declaring the same name can be kept out of one environment before any import fails. -/
def namesMain (args : List String) : IO UInt32 := do
  let [out, listing] := args | IO.eprintln "usage: Pipeline names OUT.jsonl MODULES.txt"; return 2
  let modules := (← IO.FS.readFile listing).splitOn "\n" |>.map (fun l => l.trimAscii.toString) |>.filter (· ≠ "")
  let handle ← IO.FS.Handle.mk out .write
  for m in modules do
    try
      let (data, _) ← readModuleData (← findOLean m.toName)
      handle.putStrLn (Json.mkObj [("module", toJson m), ("names", toJson (data.constNames.map Name.toString))]).compress
    catch e =>
      handle.putStrLn (Json.mkObj [("module", toJson m), ("error", toJson (toString e))]).compress
  handle.flush
  return 0

unsafe def main (args : List String) : IO UInt32 := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  match args with
  | "extract" :: rest => extractMain rest
  | "attempt" :: rest => attemptMain rest
  | "contract" :: rest => contractMain rest
  | "names" :: rest => namesMain rest
  | _ => IO.eprintln "usage: Pipeline (extract|attempt|contract|names) ..."; return 2
