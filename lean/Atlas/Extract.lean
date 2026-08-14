/-
Copyright (c) 2026 The lean-atlas contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
-/
import Atlas.Statement

/-!
# The extractor (B1)

One pass over an elaborated environment, emitting a JSONL row per declaration: name, kind,
module, explicit instance-registry status, the canonical statement encoding (I3), the
constants it uses, and any statement-level class requirements that can be attached directly
to an outer carrier binder. That is `atlas.md` §6's Channel 2, and deliberately short of a
whole-`Expr` dump, which only the skeleton index (B4) needs.

Two used-constant lists, not one. `uses_statement` is what the *claim* rests on and
`uses_proof` is what the *argument* rests on; conflating them would blur exactly the
distinction `atlas why` and the foundations/impact queries are about. Both are sorted, and
rows are emitted in name order, so a diff between two extractions is readable.

Carrier requirements are statement-only. A proof-side prototype made a 135-row historical
module take 18.6 seconds instead of under one second; the Replay-4 candidate needs statement
evidence, so imposing that closure-wide cost would solve a problem this schema does not
have. Proof carrier evidence needs its own indexed pass if a later verdict requires it.

Declarations whose statement cannot be encoded (a metavariable, `sorryAx` in the type)
carry `stmt_error` instead of `stmt` rather than being dropped: an extractor that silently
omits rows is indistinguishable from one that missed them.
-/

namespace Atlas
open Lean

/-- Version of the JSONL row envelope. This is separate from `atlas-stmt-v1`, whose tag
lives inside each statement encoding: changing row fields must not masquerade as changing
the canonical statement language. -/
def rowSchema : String := "atlas-row-v2"

/-- One class requirement observed at a concrete use site.

`carrier` is the zero-based position of the declaration's outer binder that the required
class constrains. `source` is retained because downstream policy must distinguish a real
operation or lemma from a forgetful instance; flattening to `(class, carrier)` would lose
the provenance needed to make that decision. -/
structure ClassRequirement where
  /-- The constant whose application carries the instance argument. -/
  source : Name
  /-- The class at that instance-implicit parameter. -/
  className : Name
  /-- The constrained declaration binder, counting every outer forall. -/
  carrier : Nat
  deriving BEq, Inhabited

/-- One extracted declaration. -/
structure Row where
  /-- The declaration's name. -/
  name : Name
  /-- `theorem`, `def`, `axiom`, `inductive`, `constructor`, `recursor`, `opaque`, `quot`. -/
  kind : String
  /-- The module it was declared in. -/
  module : Name
  /-- Whether Lean's imported instance registry contains this declaration. -/
  isInstance : Bool
  /-- The canonical statement encoding (I3), if it could be produced. -/
  stmt : Option String
  /-- Why the statement could not be encoded, if it could not. -/
  stmtError : Option String
  /-- Constants appearing in the statement. -/
  usesStatement : Array Name
  /-- Constants appearing in the proof or definition body. -/
  usesProof : Array Name
  /-- Carrier-attached class requirements found in statement use sites. -/
  requirementsStatement : Array ClassRequirement
  deriving Inhabited

/-- The declaration kind, as a stable string. -/
def kindOf : ConstantInfo → String
  | .axiomInfo _ => "axiom"
  | .defnInfo _ => "def"
  | .thmInfo _ => "theorem"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quot"
  | .inductInfo _ => "inductive"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"

/-- JSON for one row. Field order is fixed so that two extractions diff cleanly. -/
def Row.toJson (r : Row) : Json :=
  let requirementsJson (rs : Array ClassRequirement) : Json :=
    Json.arr <| rs.map fun req => Json.mkObj
      [("source", Json.str req.source.toString),
       ("class", Json.str req.className.toString),
       ("carrier", Json.num req.carrier)]
  Json.mkObj <|
    [("schema", rowSchema), ("name", toString r.name), ("kind", r.kind),
      ("module", toString r.module)].map
      (fun (k, v) => (k, Json.str v))
    ++ [("is_instance", Json.bool r.isInstance)]
    ++ (match r.stmt with | some s => [("stmt", Json.str s)] | none => [])
    ++ (match r.stmtError with | some e => [("stmt_error", Json.str e)] | none => [])
    ++ [("requirements_statement", requirementsJson r.requirementsStatement)]
    ++ [("uses_statement", Json.arr (r.usesStatement.map (Json.str <| toString ·))),
        ("uses_proof", Json.arr (r.usesProof.map (Json.str <| toString ·)))]

/-- Should this constant be extracted? Internal details — matcher equations, `_example`,
closed-term lifts — are noise for every downstream consumer. -/
def isExtractable (n : Name) : Bool :=
  !n.isInternalDetail

/-- Used constants, sorted by their printed form. `Name.lt` is deterministic but orders by
prefix depth, which reads as unsorted in a JSONL row; consumers and humans both want the
lexicographic order of the strings they actually see. -/
private def sortedConstants (e : Expr) : Array Name :=
  e.getUsedConstants.qsort (fun a b => a.toString < b.toString)

/-! ## Carrier-attached requirements

The statement encoding preserves every application argument, but `uses_statement` and
`uses_proof` deliberately flatten each lens to names. That loses the fact needed to judge a
multi-carrier theorem: whether a cited requirement was instantiated at `R` or at `S`.

This extraction is syntactic and stays in the Lean-only shared package. For an application
of a constant, its elaborated argument spine aligns with the constant's forall telescope.
At each instance-implicit parameter, previous arguments are substituted into the domain;
the result is the actual class application at that use site. Its class declaration tells us
which arguments are structural rather than synthesized instances. The last structural
argument that is directly an outer declaration bvar supplies the carrier index. Concrete,
composite, or locally-bound carriers are omitted, never guessed.
-/

/-- Binder infos in a constant or class declaration's leading telescope. -/
private partial def leadingBinderInfos : Expr → List BinderInfo
  | .forallE _ _ body bi => bi :: leadingBinderInfos body
  | _ => []

/-- Number of outer binders whose indices define this row's carrier namespace. -/
private partial def leadingForallCount : Expr → Nat
  | .forallE _ _ body _ => leadingForallCount body + 1
  | _ => 0

/-- Map a bvar in the current traversal scope to an outer declaration binder. -/
private def outerBinderIndex? (depth outerCount idx : Nat) : Option Nat :=
  if idx < depth then
    let absolute := depth - 1 - idx
    if absolute < outerCount then some absolute else none
  else none

/-- An expression that is directly an outer declaration binder, modulo metadata.

Do not search inside applications. If a requirement is about `Submodule R S`, the carrier
is that composite type—not whichever instance projection happens to be its last bvar.
Attributing it to `R`, `S`, or an instance binder would create cross-carrier evidence. -/
private partial def directOuterBinder? (e : Expr) (depth outerCount : Nat) : Option Nat :=
  match e with
  | .bvar idx => outerBinderIndex? depth outerCount idx
  | .mdata _ body => directOuterBinder? body depth outerCount
  | _ => none

/-- Carrier binder for an instantiated class application.

Class applications may end in their own synthesized instance parameters (`Algebra R S`
is the motivating case), so the final raw argument is not a carrier. Align with the class
declaration, discard instance-implicit parameters, and search structural arguments from
right to left. `OfNat R 0` consequently skips the literal and retains `R`. -/
private def classCarrierIndex? (env : Environment) (type : Expr)
    (depth outerCount : Nat) : Option Nat := do
  let .const cls _ := type.getAppFn | none
  let some ci := env.find? cls | none
  let args := type.getAppArgs
  let infos := (leadingBinderInfos ci.type).toArray
  let mut carrier := none
  for i in [0 : min args.size infos.size] do
    if infos[i]! != .instImplicit then
      if let some idx := directOuterBinder? args[i]! depth outerCount then
        carrier := some idx
  carrier

/-- One instance parameter in a cited constant, keyed to the constant argument that carries
its class. This depends only on the constant declaration, so a row scan caches it by source
name instead of rebuilding dependent telescopes at every use site. -/
private structure RequirementSpec where
  className : Name
  carrierParam : Nat

/-- Requirement roles in one cited constant's own telescope. -/
private partial def requirementSpecsCore (env : Environment) (type : Expr) (depth : Nat)
    (out : Array RequirementSpec) : Array RequirementSpec :=
  match type with
  | .forallE _ domain body bi =>
    let out :=
      if bi == .instImplicit then
        match domain.getAppFn, classCarrierIndex? env domain depth depth with
        | .const cls _, some carrierParam => out.push { className := cls, carrierParam }
        | _, _ => out
      else out
    requirementSpecsCore env body (depth + 1) out
  | _ => out

private def requirementSpecs (env : Environment) (source : Name) : Array RequirementSpec :=
  match env.find? source with
  | some ci => requirementSpecsCore env ci.type 0 #[]
  | none => #[]

/-- Accumulator and per-row source cache for the expression walk. -/
private structure RequirementScan where
  requirements : Array ClassRequirement := #[]
  specs : Std.HashMap Name (Array RequirementSpec) := {}

/-- Requirements contributed by one fully elaborated constant application. -/
private def scanApplication (env : Environment) (source : Name) (args : Array Expr)
    (depth outerCount : Nat) (scan : RequirementScan) : RequirementScan := Id.run do
  let (specs, cache) :=
    match scan.specs[source]? with
    | some specs => (specs, scan.specs)
    | none =>
      let specs := requirementSpecs env source
      (specs, scan.specs.insert source specs)
  let mut requirements := scan.requirements
  for spec in specs do
    if let some arg := args[spec.carrierParam]? then
      if let some carrier := directOuterBinder? arg depth outerCount then
        requirements := requirements.push { source, className := spec.className, carrier }
  return { requirements, specs := cache }

/-- Carrier-attached requirements in an expression, before sorting and deduplication. -/
private partial def requirementsInCore (env : Environment) (outerCount : Nat)
    (e : Expr) (depth : Nat) (scan : RequirementScan) : RequirementScan :=
  match e with
  | .app _ _ =>
    let fn := e.getAppFn
    let args := e.getAppArgs
    let scan := match fn with
      | .const source _ => scanApplication env source args depth outerCount scan
      | _ => scan
    let scan := requirementsInCore env outerCount fn depth scan
    args.foldl (fun scan arg => requirementsInCore env outerCount arg depth scan) scan
  | .lam _ domain body _ | .forallE _ domain body _ =>
    requirementsInCore env outerCount body (depth + 1)
      (requirementsInCore env outerCount domain depth scan)
  | .letE _ type value body _ =>
    requirementsInCore env outerCount body (depth + 1) <|
      requirementsInCore env outerCount value depth <|
        requirementsInCore env outerCount type depth scan
  | .mdata _ body | .proj _ _ body => requirementsInCore env outerCount body depth scan
  | _ => scan

/-- Stable order and exact deduplication for a row's requirement evidence. -/
private def sortedRequirements (requirements : Array ClassRequirement) :
    Array ClassRequirement :=
  let sorted := requirements.qsort fun a b =>
    if a.source != b.source then a.source.toString < b.source.toString
    else if a.className != b.className then a.className.toString < b.className.toString
    else a.carrier < b.carrier
  sorted.foldl (init := #[]) fun out req =>
    if out.back? == some req then out else out.push req

/-- Carrier-attached requirements in one statement or proof body. -/
private def requirementsIn (env : Environment) (outerCount : Nat) (e : Expr) :
    Array ClassRequirement :=
  sortedRequirements (requirementsInCore env outerCount e 0 {}).requirements

/-- The value a declaration was defined by, if it has one.

**Not `ConstantInfo.value?`**, which returns `none` for a theorem on this toolchain — Lean
does not hand out proof terms through that accessor. Using it made `uses_proof` empty for
every theorem in the environment, which is exactly backwards: a theorem's proof is where
the interesting dependencies are, and `atlas why --lens proof` is the query they exist for.
Found by B2, whose first real run over `Mathlib.Logic.Basic` reported 33,521 theorems and
not one proof edge.

`opaqueInfo` is deliberately excluded. An `opaque` declaration's whole content is that
nothing may look at its value, and the Atlas should not be the thing that does. -/
private def valueOf? : ConstantInfo → Option Expr
  | .defnInfo v => some v.value
  | .thmInfo v => some v.value
  | _ => none

/-- The module a declaration was compiled in. Absent from the module index means the
current file, which is the `#atlas_extract` case. -/
def moduleOf (env : Environment) (n : Name) : Name :=
  (env.getModuleIdxFor? n).bind (env.header.moduleNames[·.toNat]?) |>.getD env.mainModule

/-- Extract one declaration. -/
def rowOf (env : Environment) (n : Name) (info : ConstantInfo) : Row :=
  let (stmt, stmtError) :=
    match encodeType info.type with
    | .ok s => (some s, none)
    | .error e => (none, some e)
  let outerCount := leadingForallCount info.type
  { name := n
    kind := kindOf info
    module := moduleOf env n
    isInstance := Lean.Meta.isInstanceCore env n
    stmt, stmtError
    usesStatement := sortedConstants info.type
    usesProof := ((valueOf? info).map sortedConstants).getD #[]
    requirementsStatement := requirementsIn env outerCount info.type }

/-- Sort names by their printed form, computing each string **once**.

`qsort (fun a b => a.toString < b.toString)` calls `Name.toString` inside the comparator, so
it allocates a fresh string on every one of the O(n log n) comparisons rather than O(n)
times. On a whole-library extraction that is the dominant cost and it looks exactly like a
hang: the process sits at 100% CPU with a flat resident set, because it is allocating and
freeing short-lived strings instead of building rows. Decorate–sort–undecorate instead. -/
def sortedByString (names : Array Name) : Array Name :=
  let decorated := names.map fun n => (n.toString, n)
  (decorated.qsort (fun a b => a.1 < b.1)).map (·.2)

/-- Extract every extractable declaration of the *current module*, in name order. Used by
`#atlas_extract`, where "current module" is the file being elaborated. -/
def localRows (env : Environment) : Array Row := Id.run do
  let mut names := #[]
  for (n, _) in env.constants.map₂.toList do
    if isExtractable n then names := names.push n
  return (sortedByString names).filterMap fun n => (env.find? n).map (rowOf env n)

/-- Every extractable name in the environment, in name order — **names only**.

The whole-closure pass must not build an `Array Row`. A `Row` holds its statement encoding,
so 818,835 of them is tens of gigabytes: measured on the physlib closure, the process sat at
8 GB for fifty minutes and wrote *nothing*, because every row was encoded before the first
byte reached stdout. Names are small, and the caller can encode-and-write one at a time,
which makes memory flat and output incremental.

That also makes a long extraction observable. A consumer can start reading, a crash leaves
usable partial output, and progress is visible instead of being indistinguishable from a
hang — which it was, and which cost a full run. -/
def allNames (env : Environment) : Array Name := Id.run do
  let mut names := #[]
  for (n, _) in env.constants.toList do
    if isExtractable n then names := names.push n
  return sortedByString names

/-- Extract every extractable declaration in the environment, in name order.

Retained for callers that genuinely want the whole array; the extractor executable does
**not** use it, and should not — see `allNames`. -/
def allRows (env : Environment) : Array Row :=
  (allNames env).filterMap fun n => (env.find? n).map (rowOf env n)

/-- Extract the declarations belonging to any of the named modules of the import closure,
in name order.

The module test runs **before** `rowOf`, and that is the whole point. The previous spelling
filtered `allRows`, so asking for one file's declarations encoded every statement in the
closure and discarded all but a handful — a `--local` on a Mathlib-importing module cost a
full Mathlib extraction, which is tens of minutes. Importing the closure still costs what
it costs; only the encoding is now proportional to what was asked for.

Split from the encoding so a caller can time the two separately. They have completely
different cost models — selection is linear in the *imported environment*, encoding is
linear in what was *selected* — and when an extraction sits at 100% CPU for twenty minutes,
which of the two is running is the whole diagnosis. -/
def selectNames (env : Environment) (ms : Array Name) : Array Name := Id.run do
  -- Iterate the **modules asked for**, not every constant in the environment.
  --
  -- The obvious spelling walks `env.constants` and asks `moduleOf` per declaration. That
  -- is linear in the closure rather than in the request, and the closure here is 818,835
  -- constants — physlib pulls Mathlib, Batteries, Qq, Aesop, ProofWidgets and doc-gen4.
  -- Measured: **30 minutes and still running**, against an 8.3 s import. The environment
  -- walk, not the import and not the encoding, was the whole cost.
  --
  -- Lean already stores the inverse relation. `moduleData[i].constNames` is exactly the
  -- declarations compiled in module `i`, so selecting 608 modules touches only their own
  -- names and never the 810k belonging to something else.
  let wanted : NameSet := ms.foldl (·.insert ·) {}
  let mut names := #[]
  for i in [0 : env.header.moduleNames.size] do
    if wanted.contains env.header.moduleNames[i]! then
      for n in env.header.moduleData[i]!.constNames do
        if isExtractable n then names := names.push n
  -- Declarations elaborated in *this* process rather than loaded from an olean carry no
  -- module index. `atlas_extract` imports everything, so this is empty for it, but
  -- `#atlas_extract` runs inside a file being elaborated and its declarations live only here.
  if wanted.contains env.mainModule then
    for (n, _) in env.constants.map₂.toList do
      if isExtractable n then names := names.push n
  return sortedByString names

/-- The smallest extractable slice containing `roots` and every constant mentioned by the
statements in that slice.

This is the storage-conscious alternative to `allNames`. A local-only slice is not sound
for instance/carrier erasure because the signature of an application head may be absent;
serialising the entire imported environment repairs that but can add hundreds of thousands
of unrelated declarations. This work-list follows `ConstantInfo.type` only until a fixed
point, which is exactly the closure the skeleton eraser requires. Proof dependencies are
deliberately not followed: callers studying the proof or combined dependency lenses still
need a whole-environment extraction (or a future explicitly proof-closed mode).

Internal-detail names reached from a statement are emitted even though they are omitted
from ordinary root populations: their signatures can still determine which arguments the
eraser holes. Names without a declaration remain visible as missing heads to
`atlas_closure`, so this helper cannot turn an unrepresentable slice into a false pass. -/
def statementClosureNames (env : Environment) (roots : Array Name) : Array Name := Id.run do
  let mut seen : NameSet := {}
  let mut frontier := roots
  let mut names := #[]
  while !frontier.isEmpty do
    let current := frontier
    frontier := #[]
    for n in current do
      if !seen.contains n then
        seen := seen.insert n
        if let some info := env.find? n then
          names := names.push n
          for dependency in info.type.getUsedConstants do
            if !seen.contains dependency then
              frontier := frontier.push dependency
  return sortedByString names

/-- Encode a chosen set of names. -/
def rowsOfNames (env : Environment) (names : Array Name) : Array Row :=
  names.filterMap fun n => (env.find? n).map (rowOf env n)

/-- Extract the declarations belonging to any of the named modules. -/
def modulesRows (env : Environment) (ms : Array Name) : Array Row :=
  rowsOfNames env (selectNames env ms)

/-- Extract the declarations belonging to one named module of the import closure. -/
def moduleRows (env : Environment) (m : Name) : Array Row :=
  modulesRows env #[m]

end Atlas

namespace Atlas
open Lean Elab Command

/-- Emit the extractor's JSONL rows for the declarations of the current module. -/
elab "#atlas_extract" : command => do
  for row in localRows (← getEnv) do
    logInfo row.toJson.compress

end Atlas
