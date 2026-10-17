import Lean
open Lean Elab Meta

/-!
Elaborates one Lean file and prints one JSON object per line:
  {"kind":"tactic", line, column, tactic, before, after,   goal states around each info node that holds a tactic's state;
   isTactic, endLine, endColumn}                          isTactic: the node's syntax kind is in the `tactic` category
  {"kind":"decl", name, axioms, statement_uses, proof_uses, hidden}  kernel axioms; constants used in its type and in its proof/value, with instances,
                                                          coercions and auxiliary definitions left out (counted in `hidden`)
  {"kind":"message", severity, line, text}                errors and warnings Lean reported
Usage: lean --run Probe.lean FILE NAMES_FILE   (NAMES_FILE lists one declaration name per line)
-/

partial def walk (ctx? : Option ContextInfo) (fileMap : FileMap) (t : InfoTree) (acc : IO.Ref (Array Json)) : IO Unit := do
  match t with
  | .context c t => walk (c.mergeIntoOuter? ctx?) fileMap t acc
  | .node i cs =>
    if let some ctx := ctx? then
      if let .ofTacticInfo ti := i then
        if let some pos := ti.stx.getPos? (canonicalOnly := true) then
          let p := fileMap.toPosition pos
          let before ← ctx.runMetaM {} (do
            let mut r := #[]
            for g in ti.goalsBefore do
              r := r.push (toString (← withMCtx ti.mctxBefore (ppGoal g)))
            return r)
          let after ← ctx.runMetaM {} (do
            let mut r := #[]
            for g in ti.goalsAfter do
              r := r.push (toString (← withMCtx ti.mctxAfter (ppGoal g)))
            return r)
          let text := (ti.stx.reprint.getD "").trimAscii.toString
          -- Lean records info nodes for more than tactics (the `by` block, a tactic sequence, a rewrite rule, a binder name
          -- inside a macro expansion). Only a syntax kind registered in the `tactic` category is a step an author wrote.
          let isTactic := match ((Parser.parserExtension.getState ctx.env).categories.find? `tactic) with
            | some c => c.kinds.contains ti.stx.getKind
            | none => false
          let stop := match ti.stx.getTailPos? (canonicalOnly := true) with
            | some e => fileMap.toPosition e
            | none => p
          acc.modify (·.push (Json.mkObj [("kind", "tactic"), ("line", p.line), ("column", p.column),
            ("isTactic", isTactic), ("endLine", stop.line), ("endColumn", stop.column),
            ("tactic", text), ("before", toJson before), ("after", toJson after)]))
    for c in cs do walk ctx? fileMap c acc
  | .hole _ => pure ()

def severityName : MessageSeverity → String
  | .error => "error"
  | .warning => "warning"
  | .information => "information"

def printMessage (m : Message) : IO Unit := do
  if m.severity != .information then
    IO.println (Json.mkObj [("kind", "message"), ("severity", severityName m.severity),
      ("line", m.pos.line), ("text", (← m.data.toString))]).compress

unsafe def main (args : List String) : IO UInt32 := do
  let [path, namesPath] := args | IO.eprintln "usage: Probe FILE NAMES_FILE"; return 2
  enableInitializersExecution
  initSearchPath (← findSysroot)
  let input ← IO.FS.readFile path
  let ictx := Parser.mkInputContext input path
  let (header, pstate, msgs) ← Parser.parseHeader ictx
  let (env, msgs) ← processHeader header {} msgs ictx
  -- An unavailable import invalidates the entire source replay. Emit the primary header diagnostics and avoid
  -- hundreds of downstream parser/elaborator errors that would hide the real missing environment evidence.
  if msgs.hasErrors then
    for m in msgs.toList do printMessage m
    let names := (← IO.FS.readFile namesPath).splitOn "\n" |>.filter (· ≠ "")
    for n in names do
      IO.println (Json.mkObj [("kind", "decl"), ("name", n), ("axioms", Json.null)]).compress
    return 0
  let s ← IO.processCommands ictx pstate (Command.mkState env msgs {})
  let acc ← IO.mkRef #[]
  for t in s.commandState.infoState.trees do
    walk none ictx.fileMap t acc
  for j in ← acc.get do IO.println j.compress
  for m in s.commandState.messages.toList do printMessage m
  let names := (← IO.FS.readFile namesPath).splitOn "\n" |>.filter (· ≠ "")
  let env := s.commandState.env
  for n in names do
    let nm := n.toName
    if env.contains nm then
      let act : CoreM (Array Name × Array Name × Array Name × Nat) := do
        let axs ← collectAxioms nm
        let ci ← getConstInfo nm
        let valueUsed : Array Name := match ci with
          | .thmInfo t => t.value.getUsedConstants
          | .defnInfo d => d.value.getUsedConstants
          | .opaqueInfo d => d.value.getUsedConstants
          | _ => #[]
        let mut stmt : Array Name := #[]
        let mut proof : Array Name := #[]
        let mut hidden := 0
        for (u, inType) in (ci.type.getUsedConstants.map (·, true)) ++ (valueUsed.map (·, false)) do
          if u == nm || stmt.contains u || proof.contains u then continue
          let noise ← pure (u.isInternal || isAuxRecursor (← getEnv) u || isNoConfusion (← getEnv) u
            || Lean.Meta.isInstanceCore (← getEnv) u || (← Lean.Meta.getCoeFnInfo? u).isSome)
          if noise then hidden := hidden + 1
          else if inType then stmt := stmt.push u else proof := proof.push u
        return (axs, stmt, proof, hidden)
      let ((axs, stmt, proof, hidden), _) ← Core.CoreM.toIO act { fileName := path, fileMap := ictx.fileMap } { env }
      IO.println (Json.mkObj [("kind", "decl"), ("name", n), ("axioms", toJson (axs.map toString)),
        ("statement_uses", toJson (stmt.map toString)), ("proof_uses", toJson (proof.map toString)),
        ("hidden", hidden)]).compress
    else
      IO.println (Json.mkObj [("kind", "decl"), ("name", n), ("axioms", Json.null)]).compress
  return 0
