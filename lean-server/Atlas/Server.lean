import Lean
import Lean.Server.Rpc.RequestHandling
import Lean.Server.FileWorker.RequestHandling

/-!
# Atlas live semantic RPC plugin

This module is compiled as a shared Lean plugin and loaded by `lean --server --plugin=...`.
It keeps heavyweight `Expr` values inside Lean through `WithRpcRef` and exposes a small,
versioned semantic surface to the Rust index/query process.

The portable JSONL extractor under `../lean` remains independent and is not replaced by
this package.
-/

namespace Atlas.Server

open Lean
open Lean.Server
open Lean.Server.RequestM
open Lean.Server.Snapshots

private def protocolVersion : Nat := 1
private def protocolSchema : String := "atlas-lean-rpc-v1"
private def pluginVersion : String := "0.1.0"

structure HelloRequest where
  protocol : Nat
  deriving RpcEncodable

structure HelloResponse where
  protocol : Nat
  schema : String
  leanVersion : String
  pluginVersion : String
  features : Array String
  deriving RpcEncodable

structure AtPosition where
  position : Lsp.Position
  deriving RpcEncodable

structure LookupDeclarationRequest extends AtPosition where
  name : String
  deriving RpcEncodable

structure DeclarationRef where
  name : String
  kind : String
  typeRef : WithRpcRef Expr
  uses : Array String
  deriving RpcEncodable

structure LookupDeclarationResponse where
  declaration : Option DeclarationRef
  deriving RpcEncodable

structure ExprRequest extends AtPosition where
  expr : WithRpcRef Expr
  deriving RpcEncodable

structure UsedConstantsResponse where
  constants : Array String
  deriving RpcEncodable

structure ExprResponse where
  expr : WithRpcRef Expr
  deriving RpcEncodable

structure DefEqRequest extends AtPosition where
  lhs : WithRpcRef Expr
  rhs : WithRpcRef Expr
  deriving RpcEncodable

structure DefEqResponse where
  equal : Bool
  deriving RpcEncodable

private def nameOfString (value : String) : Name :=
  value.splitOn "." |>.foldl (init := Name.anonymous) fun name component =>
    match component.toNat? with
    | some index => Name.num name index
    | none => Name.str name component

private def kindOf : ConstantInfo → String
  | .axiomInfo _ => "axiom"
  | .defnInfo _ => "def"
  | .thmInfo _ => "theorem"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quot"
  | .inductInfo _ => "inductive"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"

private def sortedConstants (expr : Expr) : Array String :=
  expr.getUsedConstants
    |>.qsort (fun left right => left.toString < right.toString)
    |>.map (·.toString)

private def withSnapshotAt (position : Lsp.Position)
    (onSnapshot : Snapshots.Snapshot → FileWorker.EditableDocument → RequestM α)
    (notFound : RequestM α) : RequestM (RequestTask α) := do
  let doc ← readDoc
  let utf8Position := doc.meta.text.lspPosToUtf8Pos position
  withWaitFindSnap doc (fun snapshot => snapshot.endPos >= utf8Position)
    (notFoundX := notFound) fun snapshot => onSnapshot snapshot doc

private def hello (_ : HelloRequest) : RequestM (RequestTask HelloResponse) :=
  pureTask do
    return {
      protocol := protocolVersion
      schema := protocolSchema
      leanVersion := Lean.versionString
      pluginVersion := pluginVersion
      features := #[
        "rpc-ref",
        "lookup-declaration",
        "used-constants",
        "infer-type",
        "whnf",
        "defeq"
      ]
    }

private def lookupDeclaration (request : LookupDeclarationRequest) :
    RequestM (RequestTask LookupDeclarationResponse) :=
  withSnapshotAt request.position (notFound := pure { declaration := none }) fun snapshot _doc => do
    let name := nameOfString request.name
    let some info := snapshot.env.find? name
      | return { declaration := none }
    let typeRef ← WithRpcRef.mk info.type
    return {
      declaration := some {
        name := name.toString
        kind := kindOf info
        typeRef
        uses := sortedConstants info.type
      }
    }

private def usedConstants (request : ExprRequest) : RequestM (RequestTask UsedConstantsResponse) :=
  pureTask do
    return { constants := sortedConstants request.expr.val }

private def inferType (request : ExprRequest) : RequestM (RequestTask ExprResponse) :=
  withSnapshotAt request.position (notFound := throw .fileChanged) fun snapshot doc => do
    let type ← snapshot.runTermElabM doc.meta do
      Meta.inferType request.expr.val
    return { expr := ← WithRpcRef.mk type }

private def whnf (request : ExprRequest) : RequestM (RequestTask ExprResponse) :=
  withSnapshotAt request.position (notFound := throw .fileChanged) fun snapshot doc => do
    let reduced ← snapshot.runTermElabM doc.meta do
      Meta.whnf request.expr.val
    return { expr := ← WithRpcRef.mk reduced }

private def defEq (request : DefEqRequest) : RequestM (RequestTask DefEqResponse) :=
  withSnapshotAt request.position (notFound := throw .fileChanged) fun snapshot doc => do
    let equal ← snapshot.runTermElabM doc.meta do
      Meta.isDefEq request.lhs.val request.rhs.val
    return { equal }

builtin_initialize
  registerBuiltinRpcProcedure `Atlas.Server.hello HelloRequest HelloResponse hello

builtin_initialize
  registerBuiltinRpcProcedure
    `Atlas.Server.lookupDeclaration LookupDeclarationRequest LookupDeclarationResponse lookupDeclaration

builtin_initialize
  registerBuiltinRpcProcedure
    `Atlas.Server.usedConstants ExprRequest UsedConstantsResponse usedConstants

builtin_initialize
  registerBuiltinRpcProcedure `Atlas.Server.inferType ExprRequest ExprResponse inferType

builtin_initialize
  registerBuiltinRpcProcedure `Atlas.Server.whnf ExprRequest ExprResponse whnf

builtin_initialize
  registerBuiltinRpcProcedure `Atlas.Server.defEq DefEqRequest DefEqResponse defEq

end Atlas.Server
