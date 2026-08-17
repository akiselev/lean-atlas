import Lean.Server.Rpc

namespace Atlas.Server
open Lean Server

unsafe instance : TypeName Name := TypeName.mk Name ``Name
unsafe instance : TypeName Expr := TypeName.mk Expr ``Expr

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
  declaration : WithRpcRef Name
  expression : WithRpcRef Expr
  type_expr : WithRpcRef Expr
  name : String
  deriving RpcEncodable

structure ExprRequest where
  expr : WithRpcRef Expr
  position : Lsp.Position
  deriving RpcEncodable

structure ExprResponse where
  expr : WithRpcRef Expr
  pretty : String
  deriving RpcEncodable

structure PairRequest where
  lhs : WithRpcRef Expr
  rhs : WithRpcRef Expr
  position : Lsp.Position
  deriving RpcEncodable

structure BoolResponse where
  value : Bool
  deriving RpcEncodable

structure SynthInstanceRequest where
  type_expr : WithRpcRef Expr
  position : Lsp.Position
  deriving RpcEncodable

structure SynthInstanceResponse where
  instance : WithRpcRef Expr
  dependencies : Array String
  pretty : String
  deriving RpcEncodable

structure ApplyRequest where
  candidate : WithRpcRef Expr
  goal_type : WithRpcRef Expr
  position : Lsp.Position
  deriving RpcEncodable

structure ApplyResponse where
  subgoals : Array (WithRpcRef Expr)
  subgoal_types : Array String
  deriving RpcEncodable

structure ElaborateRequest where
  text : String
  expected : Option (WithRpcRef Expr)
  position : Lsp.Position
  deriving RpcEncodable

structure ElaborateResponse where
  expr : WithRpcRef Expr
  type_expr : WithRpcRef Expr
  pretty : String
  type_pretty : String
  deriving RpcEncodable

structure CheckProofRequest where
  proof : WithRpcRef Expr
  proposition : WithRpcRef Expr
  position : Lsp.Position
  deriving RpcEncodable

structure BatchDefEqRequest where
  pairs : Array (WithRpcRef Expr × WithRpcRef Expr)
  position : Lsp.Position
  deriving RpcEncodable

structure BatchDefEqResponse where
  results : Array (OracleResult BoolResponse)
  deriving RpcEncodable

end Atlas.Server
