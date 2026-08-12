/-
Copyright (c) 2026 The lean-atlas contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
-/
import Lean

/-!
# Canonical statement encoding (I3)

The implementation of `statement-hash.md`. A declaration's **statement** is its elaborated
type; this module turns that type into a canonical, deterministic string.

The encoding — not a digest — is the normative artifact. It is inspectable and diffable,
which is what you want the first time a freeze check fails and someone has to find out
why. The digest is SHA-256 of these bytes, computed Rust-side (`crates/atlas`), because
the toolchain ships no cryptographic hash and anti-cheat needs collision resistance
against an adversary holding the target. B8's overlay keys on the encoding itself, so
nothing on the Lean side ever needs the digest.

Normalization, decision by decision (the table in `statement-hash.md` §Normalization):

* binder **names** erased — `Expr` is already de Bruijn;
* binder **info** kept — it is the declared interface;
* universe parameter names canonically renumbered by first occurrence, after
  `Level.normalize`; `levelParams` order is therefore irrelevant;
* `mdata` stripped;
* numeric literals kept exactly as elaborated, no canonicalisation;
* **no** definitional unfolding of any kind — encoding equality is strictly stronger than
  defeq, which is the safe direction: a false rejection is possible, a false acceptance is
  not;
* metavariables, free variables and `sorryAx` are refused outright.

The version tag is the encoding's first field, so payload and version cannot be separated.
Any change to the list above bumps it.
-/

namespace Atlas
open Lean

/-- The encoding version. Bump on any normalization change; consumers must refuse to
compare across versions rather than report a difference. -/
def encodingVersion : String := "atlas-stmt-v1"

/-- Universe parameters are renumbered in order of first occurrence, so the encoder
carries that map. -/
structure EncodeState where
  /-- Universe parameter name → canonical index. -/
  levels : Std.HashMap Name Nat := {}
  deriving Inhabited

abbrev EncodeM := StateT EncodeState (Except String)

/-- Length-prefixed name, so no name's contents can forge a delimiter. -/
private def encName (n : Name) : String :=
  let s := n.toString
  s!"{s.utf8ByteSize}:{s}"

/-- Canonical index of a universe parameter, assigned on first sight. -/
private def levelIndex (n : Name) : EncodeM Nat := do
  let st ← get
  match st.levels[n]? with
  | some i => return i
  | none =>
    let i := st.levels.size
    set { st with levels := st.levels.insert n i }
    return i

/-- Encode a universe level. `Level.normalize` first, so `max u (max u v)` and `max u v`
agree. -/
private partial def encLevelCore : Level → EncodeM String
  | .zero => return "0"
  | .succ l => return s!"+({← encLevelCore l})"
  | .max a b => return s!"M({← encLevelCore a},{← encLevelCore b})"
  | .imax a b => return s!"I({← encLevelCore a},{← encLevelCore b})"
  | .param n => return s!"u{← levelIndex n}"
  | .mvar _ => throw "statement contains a universe metavariable"

private def encLevel (l : Level) : EncodeM String :=
  encLevelCore l.normalize

/-- Binder info, kept: `(n : Nat)` and `{n : Nat}` are different statements. -/
private def encBinderInfo : BinderInfo → String
  | .default => "d"
  | .implicit => "i"
  | .instImplicit => "t"
  | .strictImplicit => "s"

/-- Encode an expression. -/
private partial def encExpr : Expr → EncodeM String
  | .bvar i => return s!"b{i}"
  | .sort u => return s!"s({← encLevel u})"
  | .const n us => do
    if n == ``sorryAx then throw "statement mentions `sorryAx`"
    let us ← us.mapM encLevel
    return s!"c({encName n},{us.length}{us.foldl (fun acc u => acc ++ "," ++ u) ""})"
  | .app f a => return s!"a({← encExpr f},{← encExpr a})"
  | .lam _ t b bi => return s!"l{encBinderInfo bi}({← encExpr t},{← encExpr b})"
  | .forallE _ t b bi => return s!"p{encBinderInfo bi}({← encExpr t},{← encExpr b})"
  | .letE _ t v b _ => return s!"e({← encExpr t},{← encExpr v},{← encExpr b})"
  | .lit (.natVal n) => return s!"n{n}"
  | .lit (.strVal s) => return s!"t{s.utf8ByteSize}:{s}"
  | .proj s i e => return s!"j({encName s},{i},{← encExpr e})"
  | .mdata _ e => encExpr e            -- stripped
  | .fvar _ => throw "statement contains a free variable"
  | .mvar _ => throw "statement contains a metavariable"

/-- Encode a statement (an elaborated type). -/
def encodeType (type : Expr) : Except String String := do
  let (body, _) ← (encExpr type).run {}
  return s!"{encodingVersion};{body}"

/-- Encode the statement of a declaration in `env`. The declaration's *name* is not part
of the encoding: renaming a theorem does not change what it claims, which is what makes
B8's rebind-by-hash possible. -/
def encodeConst (env : Environment) (n : Name) : Except String String := do
  let some info := env.find? n | throw s!"unknown constant `{n}`"
  encodeType info.type

end Atlas

namespace Atlas
open Lean Elab Command

/-- Resolve an identifier to the single constant it names. -/
private def theConst (id : Ident) : CommandElabM Name := do
  let cs ← liftCoreM <| realizeGlobalConstWithInfos id
  match cs with
  | [c] => return c
  | _ => throwErrorAt id "atlas: `{id}` does not name exactly one constant"

/-- Report whether two declarations have the same statement encoding. The property tests
in `statement-hash.md` are about *invariance and sensitivity*, so they assert this rather
than pinning an encoding that any normalization change would churn. -/
elab "#atlas_statement_eq " a:ident b:ident : command => do
  let ea := encodeConst (← getEnv) (← theConst a)
  let eb := encodeConst (← getEnv) (← theConst b)
  match ea, eb with
  | .ok ea, .ok eb => logInfo (if ea == eb then "same statement" else "different statements")
  | .error e, _ | _, .error e => logError s!"atlas: cannot encode: {e}"

/-- Log the canonical statement encoding of a declaration (I3). -/
elab "#atlas_statement " id:ident : command => do
  let cs ← liftCoreM <| realizeGlobalConstWithInfos id
  for c in cs do
    match encodeConst (← getEnv) c with
    | .ok s => logInfo s
    | .error e => logError s!"atlas: cannot encode `{c}`: {e}"

end Atlas
