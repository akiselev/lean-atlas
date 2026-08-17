import Atlas.Server.Queries

namespace Atlas.Server
open Lean Server Lsp

private def features : Array String := #[
  "lookupDecl", "getType", "inferType", "whnf", "isDefEq", "unify",
  "synthInstance", "apply", "elaborate", "checkProof", "batchDefEq"
]

def hello (req : HelloRequest) : RequestM (RequestTask HelloResponse) :=
  RequestM.withWaitFindSnapAtPos req.position fun _ => do
    let root ← IO.currentDir
    return {
      atlas_protocol := "2.0.0"
      lean_version := Lean.versionString
      plugin_version := "0.1.0"
      features
      environment_fingerprint := {
        lean_version := Lean.versionString
        plugin_version := "0.1.0"
        project_root := root.toString
        modules_digest := "live-server-session"
        options_digest := "default"
        document_version := none
      }
    }

def registerAtlasRpc : IO Unit := do
  registerBuiltinRpcProcedure `Atlas.Server.hello HelloRequest HelloResponse hello
  registerBuiltinRpcProcedure `Atlas.Server.lookupDecl LookupDeclRequest (OracleResult LookupDeclResponse) lookupDecl
  registerBuiltinRpcProcedure `Atlas.Server.getType ExprRequest (OracleResult ExprResponse) getType
  registerBuiltinRpcProcedure `Atlas.Server.inferType ExprRequest (OracleResult ExprResponse) inferType
  registerBuiltinRpcProcedure `Atlas.Server.whnf ExprRequest (OracleResult ExprResponse) whnfQuery
  registerBuiltinRpcProcedure `Atlas.Server.isDefEq PairRequest (OracleResult BoolResponse) defEq
  registerBuiltinRpcProcedure `Atlas.Server.unify PairRequest (OracleResult BoolResponse) unify
  registerBuiltinRpcProcedure `Atlas.Server.synthInstance SynthInstanceRequest (OracleResult SynthInstanceResponse) synthInstanceQuery
  registerBuiltinRpcProcedure `Atlas.Server.apply ApplyRequest (OracleResult ApplyResponse) applyQuery
  registerBuiltinRpcProcedure `Atlas.Server.elaborate ElaborateRequest (OracleResult ElaborateResponse) elaborateQuery
  registerBuiltinRpcProcedure `Atlas.Server.checkProof CheckProofRequest (OracleResult BoolResponse) checkProofQuery
  registerBuiltinRpcProcedure `Atlas.Server.batchDefEq BatchDefEqRequest BatchDefEqResponse batchDefEq

end Atlas.Server
