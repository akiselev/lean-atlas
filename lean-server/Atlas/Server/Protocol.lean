import Lean.Server.Rpc

namespace Atlas.Server
open Lean Server

-- `TypeName.mk` is unsafe because Lean cannot prove that the supplied name
-- denotes exactly the supplied type. Keep the *instance declaration* safe and
-- confine that escape hatch to the value, matching Lean's own RPC code. An
-- `unsafe instance` would make every derived `RpcEncodable` containing a
-- `WithRpcRef` unsafe and is rejected by the kernel/compiler.
instance : TypeName Lean.Name := unsafe (TypeName.mk Lean.Name ``Lean.Name)
instance : TypeName Lean.Expr := unsafe (TypeName.mk Lean.Expr ``Lean.Expr)

structure HelloRequest where
  atlas_protocol : String
  requested_features : Array String := #[]
  position : Lsp.Position
  deriving RpcEncodable

structure EnvironmentFingerprint where
  lean_version : String
  plugin_version : String
  project_root : String
  modules_digest : String
  options_digest : String
  document_version : Option Int
  deriving RpcEncodable

structure HelloResponse where
  atlas_protocol : String
  lean_version : String
  plugin_version : String
  features : Array String
  environment_fingerprint : EnvironmentFingerprint
  deriving RpcEncodable

structure LeanFailure where
  kind : String
  message : String
  goals : Array String := #[]
  missing_instances : Array String := #[]
  metavariables : Array String := #[]
  trace : Option Json := none
  deriving RpcEncodable

structure OracleResult (α : Type) where
  value : Option α := none
  failure : Option LeanFailure := none
  deriving RpcEncodable

structure LookupDeclRequest where
  name : String
  position : Lsp.Position
  deriving RpcEncodable

structure LookupDeclResponse where
  declaration : WithRpcRef Lean.Name
  expression : WithRpcRef Lean.Expr
  type_expr : WithRpcRef Lean.Expr
  name : String
  deriving RpcEncodable

structure ExprRequest where
  expr : WithRpcRef Lean.Expr
  position : Lsp.Position
  deriving RpcEncodable

structure ExprResponse where
  expr : WithRpcRef Lean.Expr
  pretty : String
  deriving RpcEncodable

structure PairRequest where
  lhs : WithRpcRef Lean.Expr
  rhs : WithRpcRef Lean.Expr
  position : Lsp.Position
  deriving RpcEncodable

structure BoolResponse where
  value : Bool
  deriving RpcEncodable

structure SynthInstanceRequest where
  type_expr : WithRpcRef Lean.Expr
  position : Lsp.Position
  deriving RpcEncodable

structure SynthInstanceResponse where
  «instance» : WithRpcRef Lean.Expr
  dependencies : Array String
  pretty : String
  deriving RpcEncodable

structure ApplyRequest where
  candidate : WithRpcRef Lean.Expr
  goal_type : WithRpcRef Lean.Expr
  position : Lsp.Position
  deriving RpcEncodable

structure ApplyResponse where
  subgoals : Array (WithRpcRef Lean.Expr)
  subgoal_types : Array String
  deriving RpcEncodable

structure ElaborateRequest where
  text : String
  expected : Option (WithRpcRef Lean.Expr)
  position : Lsp.Position
  deriving RpcEncodable

structure ElaborateResponse where
  expr : WithRpcRef Lean.Expr
  type_expr : WithRpcRef Lean.Expr
  pretty : String
  type_pretty : String
  deriving RpcEncodable

structure CheckProofRequest where
  proof : WithRpcRef Lean.Expr
  proposition : WithRpcRef Lean.Expr
  position : Lsp.Position
  deriving RpcEncodable

structure BatchDefEqRequest where
  pairs : Array (WithRpcRef Lean.Expr × WithRpcRef Lean.Expr)
  position : Lsp.Position
  deriving RpcEncodable

structure BatchDefEqResponse where
  results : Array (OracleResult BoolResponse)
  deriving RpcEncodable

end Atlas.Server
