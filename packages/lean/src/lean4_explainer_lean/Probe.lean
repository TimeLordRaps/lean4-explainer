import Lean
open Lean Elab Meta

/-!
Elaborates one Lean file and prints one JSON object per line:
  {"kind":"tactic", line, column, tactic, before, after}   goal states around each tactic step
  {"kind":"decl", name, axioms}                           kernel axioms a declaration depends on (null: no such constant)
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
          acc.modify (·.push (Json.mkObj [("kind", "tactic"), ("line", p.line), ("column", p.column),
            ("tactic", text), ("before", toJson before), ("after", toJson after)]))
    for c in cs do walk ctx? fileMap c acc
  | .hole _ => pure ()

def severityName : MessageSeverity → String
  | .error => "error"
  | .warning => "warning"
  | .information => "information"

unsafe def main (args : List String) : IO UInt32 := do
  let [path, namesPath] := args | IO.eprintln "usage: Probe FILE NAMES_FILE"; return 2
  enableInitializersExecution
  initSearchPath (← findSysroot)
  let input ← IO.FS.readFile path
  let ictx := Parser.mkInputContext input path
  let (header, pstate, msgs) ← Parser.parseHeader ictx
  let (env, msgs) ← processHeader header {} msgs ictx
  let s ← IO.processCommands ictx pstate (Command.mkState env msgs {})
  let acc ← IO.mkRef #[]
  for t in s.commandState.infoState.trees do
    walk none ictx.fileMap t acc
  for j in ← acc.get do IO.println j.compress
  for m in s.commandState.messages.toList do
    if m.severity != .information then
      IO.println (Json.mkObj [("kind", "message"), ("severity", severityName m.severity),
        ("line", m.pos.line), ("text", (← m.data.toString))]).compress
  let names := (← IO.FS.readFile namesPath).splitOn "\n" |>.filter (· ≠ "")
  let env := s.commandState.env
  for n in names do
    let nm := n.toName
    if env.contains nm then
      let (axs, _) ← Core.CoreM.toIO (collectAxioms nm) { fileName := path, fileMap := ictx.fileMap } { env }
      IO.println (Json.mkObj [("kind", "decl"), ("name", n), ("axioms", toJson (axs.map toString))]).compress
    else
      IO.println (Json.mkObj [("kind", "decl"), ("name", n), ("axioms", Json.null)]).compress
  return 0
