import Atlas.Server.Handles
import Lean.Meta.Tactic.Apply
import Lean.Elab.Term
import Lean.Parser

namespace Atlas.Server
open Lean Server Lsp Meta Elab Term

private def failure (kind message : String) : LeanFailure := { kind, message }

def captureMeta (kind : String) (action : MetaM α) : MetaM (Except LeanFailure α) := do
  try
    return .ok (← action)
  catch ex =>
    return .error (failure kind (← ex.toMessageData.toString))

partial def collectConstants (e : Expr) (out : Array Name := #[]) : Array Name :=
  match e with
  | .const n _ => if out.contains n then out else out.push n
  | .app f a => collectConstants a (collectConstants f out)
  | .lam _ t b _ | .forallE _ t b _ => collectConstants b (collectConstants t out)
  | .letE _ t v b _ => collectConstants b (collectConstants v (collectConstants t out))
  | .mdata _ b => collectConstants b out
  | .proj _ _ b => collectConstants b out
  | _ => out

def prettyExpr (e : Expr) : MetaM String := do
  return toString (← ppExpr e)

def parseTerm (text : String) : CoreM Syntax := do
  let env ← getEnv
  match Parser.runParserCategory env `term text with
  | .ok stx => return stx
  | .error err => throwError err

end Atlas.Server
