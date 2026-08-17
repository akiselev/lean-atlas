import Atlas.Server.Oracle

namespace Atlas.Server
open Lean Server Lsp Meta Elab Term

private def oracleOf (value : Except LeanFailure α) : OracleResult α :=
  match value with
  | .ok x => { value := some x }
  | .error e => { failure := some e }

private def parseDeclName (name : String) : Name :=
  name.splitOn "." |>.foldl (fun acc part => Name.str acc part) Name.anonymous

private def lookupDeclCore (name : String) : CoreM (Except LeanFailure (Name × Expr × Expr)) :=
  captureMeta "unknown_declaration" do
    let n := parseDeclName name
    let env ← getEnv
    unless env.contains n do
      throwError "unknown declaration '{n}'"
    let expr ← instantiateMVars (← mkConstWithFreshMVarLevels n)
    let typeExpr ← instantiateMVars (← Meta.inferType expr)
    return (n, expr, typeExpr)

def lookupDecl (req : LookupDeclRequest) : RequestM (RequestTask (OracleResult LookupDeclResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runCoreM snap <| lookupDeclCore req.name
    match result with
    | .error e => return { failure := some e }
    | .ok (name, expr, typeExpr) =>
      let declaration ← WithRpcRef.mk name
      let expression ← WithRpcRef.mk expr
      let type_expr ← WithRpcRef.mk typeExpr
      return { value := some { declaration, expression, type_expr, name := name.toString } }

def getType (req : ExprRequest) : RequestM (RequestTask (OracleResult ExprResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runCoreM snap <| captureMeta "type_mismatch" do
      let e ← instantiateMVars (← Meta.inferType req.expr.val)
      return (e, ← prettyExpr e)
    match result with
    | .error e => return { failure := some e }
    | .ok (expr, pretty) =>
      let exprRef ← WithRpcRef.mk expr
      return { value := some { expr := exprRef, pretty } }

def inferType := getType

def whnfQuery (req : ExprRequest) : RequestM (RequestTask (OracleResult ExprResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runCoreM snap <| captureMeta "elaboration" do
      let e ← instantiateMVars (← whnf req.expr.val)
      return (e, ← prettyExpr e)
    match result with
    | .error e => return { failure := some e }
    | .ok (expr, pretty) =>
      let exprRef ← WithRpcRef.mk expr
      return { value := some { expr := exprRef, pretty } }

def defEq (req : PairRequest) : RequestM (RequestTask (OracleResult BoolResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runCoreM snap <| captureMeta "definitional_equality" do
      let saved ← saveState
      let ok ← isDefEq req.lhs.val req.rhs.val
      saved.restore
      return ok
    return oracleOf <| result.map fun value => { value }

def unify := defEq

def synthInstanceQuery (req : SynthInstanceRequest) : RequestM (RequestTask (OracleResult SynthInstanceResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runCoreM snap <| captureMeta "instance_synthesis" do
      let inst ← instantiateMVars (← synthInstance req.type_expr.val)
      let deps := (collectConstants inst).map Name.toString
      return (inst, deps, ← prettyExpr inst)
    match result with
    | .error e => return { failure := some e }
    | .ok (inst, dependencies, pretty) =>
      let instRef ← WithRpcRef.mk inst
      return { value := some { «instance» := instRef, dependencies, pretty } }

def applyQuery (req : ApplyRequest) : RequestM (RequestTask (OracleResult ApplyResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runCoreM snap <| captureMeta "unification" do
      let goal ← mkFreshExprMVar req.goal_type.val
      let goals ← goal.mvarId!.apply req.candidate.val
      let types ← goals.toArray.mapM fun g => do
        instantiateMVars (← g.getType)
      let rendered ← types.mapM prettyExpr
      return (types, rendered)
    match result with
    | .error e => return { failure := some e }
    | .ok (types, subgoal_types) =>
      let mut subgoals := #[]
      for typeExpr in types do
        let ref ← WithRpcRef.mk typeExpr
        subgoals := subgoals.push ref
      return { value := some { subgoals, subgoal_types } }

def elaborateQuery (req : ElaborateRequest) : RequestM (RequestTask (OracleResult ElaborateResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runTermElabM snap do
      try
        let stx ← parseTerm req.text
        let expr ← elabTerm stx (req.expected.map (·.val))
        synthesizeSyntheticMVarsNoPostponing
        let expr ← instantiateMVars expr
        let typeExpr ← instantiateMVars (← Meta.inferType expr)
        return Except.ok (expr, typeExpr, ← prettyExpr expr, ← prettyExpr typeExpr)
      catch ex =>
        return Except.error { kind := "elaboration", message := ← ex.toMessageData.toString }
    match result with
    | .error e => return { failure := some e }
    | .ok (expr, typeExpr, pretty, type_pretty) =>
      let exprRef ← WithRpcRef.mk expr
      let typeRef ← WithRpcRef.mk typeExpr
      return {
        value := some {
          expr := exprRef
          type_expr := typeRef
          pretty
          type_pretty
        }
      }

def checkProofQuery (req : CheckProofRequest) : RequestM (RequestTask (OracleResult BoolResponse)) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let result ← RequestM.runCoreM snap <| captureMeta "invalid_proof" do
      let proofType ← Meta.inferType req.proof.val
      let saved ← saveState
      let ok ← isDefEq proofType req.proposition.val
      saved.restore
      return ok
    return oracleOf <| result.map fun value => { value }

def batchDefEq (req : BatchDefEqRequest) : RequestM (RequestTask BatchDefEqResponse) :=
  RequestM.withWaitFindSnapAtPos req.position fun snap => do
    let results ← RequestM.runCoreM snap do
      req.pairs.mapM fun pair => do
        let result ← captureMeta "definitional_equality" do
          let saved ← saveState
          let ok ← isDefEq pair.1.val pair.2.val
          saved.restore
          return ok
        return oracleOf <| result.map fun value => { value }
    return { results }

end Atlas.Server
