/-
Copyright (c) 2026 The lean-atlas contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
-/
import Lean

/-!
# `atlas home` — carrier abstraction and the lattice walk (B3, atlas.md §1b)

This module lives in `atlas-extract` — the package both workspaces share — because it
imports only `Lean`, and that is load-bearing: the physics workspace is pinned to a
*different* toolchain (physlib on v4.32.0 against the main package's v4.32.2), so
`#atlas_home_refute`/`#atlas_home_attempt` can only reach physics declarations from here. The
old location, `lean/Atlas/Home.lean`, is a one-line re-export shim so every
existing import site and generated probe file keeps working. The Lean *namespace* stays
`Atlas` while the module path is `Atlas.Home`, per the package's naming
rule (see `atlas-extract/lakefile.toml`).

Where does a theorem actually *live*?

A statement written for `CommRing` whose argument only ever adds is not a theorem about
commutative rings; it is a theorem about additive commutative monoids that happens to have
been written down in the wrong place. Mathlib's generalization linter exists because this
happens constantly, and finding it is one of the two things atlas.md claims the Atlas is
for.

## How the home is computed

Not by guessing, and not by name. Every constant an argument uses carries its own instance
binders, and those binders are a *statement* of what that constant needs. So:

> the classes a declaration needs at a carrier = the union of the instance-binder classes
> of every constant its statement and proof use, restricted to that carrier.

The restriction to instance *binders* is what makes this work. The elaborated statement
also contains the projection chain from the declared class down — `CommRing.toCommSemiring`,
`CommSemiring.toSemiring`, and so on — but that chain is an artifact of having declared
`CommRing` in the first place. Counting it would make every declaration look at home.

`a + b = b + a` proved by `add_comm` reaches `AddCommMonoid`, whatever the declaration
says it assumes. The lattice walk then asks which of the declared class's ancestors
dominates that set — and if the answer is a strict ancestor, the declaration is
over-hypothesised and the report names the weaker home.

## What this is and is not

It is a **candidate** detector, which is what a generalization linter is. Two limits, both
real and both stated in the report rather than buried:

* It reads the *elaborated* statement and proof term. A proof that goes through `simp`
  leaves whatever `simp` used, which is a fair account of the argument but not always the
  smallest one — a differently-written proof may live lower still.
* Class *ancestry* is Lean's structure-parent relation. A carrier can also be abstracted
  by routes that are not ancestry (a `Fintype` replaced by a `Finite`, say); those are
  outside this walk and B4's business.

A candidate is confirmed by moving the declaration and re-checking it. The report says so.
-/

namespace Atlas

open Lean Meta Elab Command

/-- Every class `n` extends, transitively, including `n` itself. -/
partial def ancestors (env : Environment) (n : Name) : NameSet :=
  go n {}
where
  go (n : Name) (acc : NameSet) : NameSet :=
    if acc.contains n then acc
    else
      (getStructureParentInfo env n).foldl (fun acc p => go p.structName acc) (acc.insert n)

/-- The classes a constant declares it needs, as instance binders, paired with the argument
each is *about*.

This is the load-bearing observation: an instance binder is a constant's own written
statement of what it requires, so reading them off is not inference. -/
def instanceClasses (env : Environment) (n : Name) : MetaM NameSet := do
  let some ci := env.find? n | return {}
  let levels ← ci.levelParams.mapM fun _ => mkFreshLevelMVar
  forallTelescopeReducing (ci.instantiateTypeLevelParams levels) fun xs _ => do
    let mut out : NameSet := {}
    for x in xs do
      let d ← x.fvarId!.getDecl
      if d.binderInfo == .instImplicit then
        if let .const c _ := (← whnf d.type).getAppFn then
          out := out.insert c
    return out

/-- The classes a declaration's statement and proof actually reach. -/
def reachedClasses (env : Environment) (ci : ConstantInfo) : MetaM NameSet := do
  let mut used := ci.type.getUsedConstants
  -- `value?` is `none` for a theorem on this toolchain — the same trap B1 fell into, so
  -- the constructor is matched directly. A proof is most of the evidence here.
  if let .thmInfo v := ci then used := used ++ v.value.getUsedConstants
  else if let .defnInfo v := ci then used := used ++ v.value.getUsedConstants
  -- Parent projections (`CommRing.toCommSemiring`) are themselves instances taking the
  -- *child* as an instance binder, so counting their binders reintroduces exactly the
  -- chain artifact this function exists to exclude. They are skipped.
  let isParentProjection (u : Name) : Bool :=
    let owner := u.getPrefix
    isStructure env owner && (getStructureParentInfo env owner).any (·.projFn == u)
  let mut out : NameSet := {}
  for u in used do
    -- Instances are *plumbing*: `instCommSemiringOfCommRing` takes `[CommRing R]` and
    -- says only that the elaborator threaded the declared binder somewhere, not that the
    -- argument needed it. A *lemma*'s instance binder is a real requirement, and lemmas
    -- are not instances. Dropping instances is what separates the two.
    if isParentProjection u || (← isInstance u) then continue
    -- Only a constant's *own* instance binders count as evidence. The projection chain
    -- (`CommRing.toCommSemiring`, `CommSemiring.toSemiring`, …) is in the elaborated
    -- statement too, but it is an artifact of how the statement was elaborated *given* the
    -- declared binder — counting it would make every declaration look at home, which is
    -- exactly the bug this rule replaced.
    for c in (← instanceClasses env u) do
      out := out.insert c
  return out

/-! ## Carrier-aware evidence (C4 D3)

`reachedClasses` answers *which* classes a declaration reaches and can never answer *at
which carrier*, because `getUsedConstants` flattens the term to a set of names before the
question is asked. That is not a cosmetic loss. A declaration binding `[CommRing R]` and
`[CommRing S]` and using `R` only additively gets both binders' evidence pooled, so neither
resolves to a home and two genuine findings are lost — pinned as `twocarrier` in
`Tests/Atlas/Home.lean`.

The fix reads the evidence where it actually lives. **An instance argument's type is
exactly `SomeClass carrier`**, so every argument of every application whose type is a class
application is one piece of carrier-attached evidence, and no binder-info lookup on the
head constant is needed to find it.

`Meta.transform` does the walking because it opens binders through `withLocalDecl`, so
`inferType` is valid on every subterm it visits — a hand-rolled recursion would meet loose
de Bruijn indices under the first lambda and infer nothing.
-/

/-- The structural free variable a class application is about.

The final application argument is not generally the carrier. A class may quantify over
instances after its structural parameters: the elaborated type of `[Algebra R S]`, for
example, ends in the `Semiring S` instance even though the carrier is `S`. Align the
application spine with the class declaration's telescope, discard instance-implicit
parameters, and retain the last structural argument that is one of the open declaration's
free variables. This is also the useful convention for multi-parameter classes such as
`SMul R M`, which are keyed to `M`; for `OfNat R 0`, the literal is skipped and `R` wins.

The fallback preserves the old behavior for a class whose declaration cannot be read or
whose application spine does not align with it. -/
private partial def classBinderInfos : Expr → List BinderInfo
  | .forallE _ _ body bi => bi :: classBinderInfos body
  | _ => []

private def classCarrierArg? (env : Environment) (ty : Expr) : MetaM (Option Expr) := do
  let ty ← whnf ty
  let args := ty.getAppArgs
  let .const cls _ := ty.getAppFn | return args.back?
  let some ci := env.find? cls | return args.back?
  let binderInfos := (classBinderInfos ci.type).toArray
  let mut carrier : Option Expr := none
  for i in [0 : min args.size binderInfos.size] do
    let arg := args[i]!
    if binderInfos[i]! != .instImplicit && arg.fvarId?.isSome then
      carrier := some arg
  if carrier.isSome then return carrier
  -- Be conservative when the class metadata is incomplete: prefer the old last argument
  -- rather than manufacturing a relationship the open declaration does not expose.
  return args.back?

/-- Classes the declaration reaches, each paired with the carrier it was reached *at*.
`none` is a carrier that is not one of the declaration's own binders — a class about `ℕ`
says nothing about a binder over `R`, and conflating the two is what invents findings. -/
def reachedWithCarrier (env : Environment) (e : Expr) :
    MetaM (Array (Name × Option FVarId)) := do
  let isParentProjection (u : Name) : Bool :=
    let owner := u.getPrefix
    isStructure env owner && (getStructureParentInfo env owner).any (·.projFn == u)
  let found ← IO.mkRef (#[] : Array (Name × Option FVarId))
  let _ ← Meta.transform e (pre := fun sub => do
    if sub.isApp then
      -- The same exclusion `reachedClasses` applies, moved to where the evidence is read.
      -- An instance argument handed to *another instance* or to a parent projection is
      -- plumbing: `CommRing.toCommSemiring inst` says only that the elaborator threaded
      -- the declared binder somewhere. An instance argument handed to a **lemma** is a
      -- real requirement, and lemmas are not instances. Without this the binder's own
      -- class is recorded as evidence for itself and every binder reads "at home".
      let skip ← match sub.getAppFn with
        | .const u _ => pure (isParentProjection u) <||> isInstance u
        | _ => pure false
      unless skip do
        for a in sub.getAppArgs do
          -- The type is the evidence: `AddCommMagma R` names both class and carrier.
          let ty ← try inferType a catch _ => pure (mkSort Level.zero)
          if let some cls ← isClass? ty then
            let carrier := (← classCarrierArg? env ty).bind (·.fvarId?)
            found.modify (·.push (cls, carrier))
    return .continue)
  found.get

/-- One binder's verdict. -/
structure Verdict where
  /-- The class as declared. -/
  declared : Name
  /-- The ancestors of `declared` the declaration actually reaches. -/
  reached : Array Name
  /-- The weakest ancestor that dominates everything reached, when there is a single one. -/
  home : Option Name

/-- Walk one instance binder down the lattice. -/
def walk (env : Environment) (declared : Name) (reached : NameSet) : Verdict :=
  -- Strict ancestors only. The declared class reaches *itself* through Mathlib's derived
  -- shortcut instances (`instCommSemiringOfCommRing` and friends take `[CommRing R]`), and
  -- counting that would make every declaration look at home — which is the bug this rule
  -- replaced. A binder is at home when nothing weaker covers what is used.
  let anc := (ancestors env declared).erase declared
  -- Only ancestors matter: a class reached at *another* carrier says nothing about this
  -- binder, and including it would invent findings.
  let hit := anc.toList.filter (reached.contains ·) |>.toArray
  let hit := hit.qsort (fun a b => a.toString < b.toString)
  -- The home is the reached class that implies every other reached class — i.e. the one
  -- whose own ancestry covers the set. If several are incomparable there is no single
  -- home, and saying so beats picking one.
  let home := hit.find? fun candidate =>
    hit.all fun other => (ancestors env candidate).contains other
  { declared, reached := hit, home }

/-- `#atlas_home <decl>` — where does this declaration actually live?

Reports, per instance binder, the classes its statement and proof reach and the weakest
ancestor that covers them. A home strictly weaker than the declared class is an
over-hypothesis **candidate**, confirmed by moving the declaration and re-checking it. -/
elab "#atlas_home " n:ident : command => do
  let name ← liftCoreM <| realizeGlobalConstNoOverload n
  let env ← getEnv
  let some ci := env.find? name | throwErrorAt n s!"unknown declaration `{name}`"
  liftTermElabM do
    -- `reachedClasses` is superseded here by `reachedWithCarrier`: same evidence and the
    -- same two exclusions, but attached to the carrier it was found at. The flat version
    -- stays exported — it is the cheaper answer when a caller has one carrier and knows it.
    let levels ← ci.levelParams.mapM fun _ => mkFreshLevelMVar
    let (lines, candidates, carriers) : Array String × Nat × Array String ←
      forallTelescopeReducing (ci.instantiateTypeLevelParams levels) fun xs concl => do
      -- D3: the same evidence, but attached to the carrier it was found at. Gathered
      -- inside this telescope so the binders are fvars and `inferType` can see them; the
      -- value is instantiated with the *same* fvars, or its carriers would be a different
      -- set of variables that could never match a binder.
      let mut ev ← reachedWithCarrier env concl
      if let some v := (match ci with
          | .thmInfo t => some t.value
          | .defnInfo t => some t.value
          | _ => none) then
        let body ← try instantiateLambda v xs catch _ => pure v
        ev := ev ++ (← reachedWithCarrier env body)
      let mut lines : Array String := #[]
      let mut candidates := 0
      let mut carriers : Array String := #[]
      for x in xs do
        let d ← x.fvarId!.getDecl
        unless d.binderInfo == .instImplicit do continue
        let ty ← whnf d.type
        let .const cls _ := ty.getAppFn | continue
        -- The carrier the constraint is *about*. `instanceClasses`'s own doc comment has
        -- always promised this pairing; the implementation returned a bare `NameSet` and
        -- dropped it, which is what "home loses carrier identity" means concretely.
        -- The carrier is the class's last structural free-variable argument — the `R` of
        -- `CommRing R`, the `S` rather than a synthesized instance in `Algebra R S` — and
        -- *not* the instance binder's own fvar. Comparing evidence against the latter was
        -- the first version's bug: `add_comm`'s `AddCommMagma R` argument is carried by
        -- `R`, so nothing ever matched and every binder read as unused.
        let carrierArg ← classCarrierArg? env ty
        let carrierFv := carrierArg.bind (·.fvarId?)
        let carrier : String ← match carrierArg with
          | some c => do pure (toString (← ppExpr c))
          | none => pure "?"
        carriers := carriers.push carrier
        -- Only evidence found *at this binder's carrier* counts. This is the whole of D3:
        -- with a flat set, a class reached at `S` was indistinguishable from one reached
        -- at `R`, and both binders were judged on the union.
        let here : NameSet := ev.foldl (init := {}) fun acc (c, fv) =>
          if fv.isSome && fv == carrierFv then acc.insert c else acc
        let v := walk env cls here
        -- Asked first, and about the declared class itself: if some *lemma* requires it
        -- at this carrier, nothing weaker covers the use and the walk has no verdict to
        -- give. Asking this after the lattice walk reported an at-home binder as unused,
        -- because the walk deliberately looks only at strict ancestors.
        if here.contains cls then
          lines := lines.push s!"  [{cls} {carrier}] — at home"
        else match v.home with
        | some h =>
            candidates := candidates + 1
            lines := lines.push
              s!"  [{cls} {carrier}] — CANDIDATE: reaches only {h}; weaken and re-check"
        | none =>
            if v.reached.isEmpty then
              -- The strongest finding there is: nothing needs this binder at all.
              candidates := candidates + 1
              lines := lines.push
                s!"  [{cls} {carrier}] — CANDIDATE: unused; nothing in the statement or proof needs it"
            else
              lines := lines.push
                s!"  [{cls} {carrier}] — reaches {v.reached.toList}, no single weakest ancestor"
      return (lines, candidates, carriers)
    let header :=
      if candidates == 0 then s!"atlas home: `{name}` is at home"
      else s!"atlas home: `{name}` has {candidates} over-hypothesis candidate(s) — \
             a candidate is confirmed by moving the declaration and re-checking it"
    -- The verdicts above share one `reached` set, which is a set of class *names* with no
    -- carrier attached. That is sound only while every binder is about the same carrier:
    -- with two, a class reached at `R` is indistinguishable from one reached at `S`, and a
    -- binder can be told it is over-strong on evidence belonging to its neighbour. Said
    -- rather than left for a reader to discover, because the walk's own comment already
    -- claims "a class reached at another carrier says nothing about this binder" — which
    -- the evidence cannot currently support.
    -- The caveat this used to carry — "the reached set is carrier-blind, so these
    -- verdicts are approximate" — is retired by D3: each binder is now judged only on
    -- evidence found at its own carrier. What is still worth saying is which carriers are
    -- in play, because a multi-carrier declaration is where the distinction does work.
    let distinct := carriers.toList.eraseDups
    let caveat :=
      if distinct.length > 1 then
        s!"\n  (binders span {distinct.length} carriers ({distinct}); each verdict uses \
           only its own carrier's evidence)"
      else ""
    logInfo (header ++ "\n" ++ String.intercalate "\n" lines.toList ++ caveat)


/-! ## Confirmation — C4's second stage

`#atlas_home` reports *candidates*. A candidate is a claim about what a proof needs, and the
only thing that settles it is putting the weaker hypothesis in front of the kernel. Until
now that was done by hand: `Tests/Atlas/Home.lean` carries `overh_confirmed` beside
`overh`, written out and compiled by a human.

The construction is deliberately blunt. The declaration's type is a nest of `forallE`;
walk it, replace the candidate binder's domain `C args` with `H args` for the weaker class
`H`, and leave everything else alone. Binder *count* and *order* are untouched, so every de
Bruijn index in the body still resolves to what it did and the proof term needs no
rewriting at all — which is what makes this one kernel call rather than a re-elaboration.

The kernel then answers the real question. A proof that only ever used the weaker class's
operations typechecks; one that projects a field `H` does not have is rejected, and that
rejection is the evidence that the binder is *not* an over-hypothesis. Both outcomes are
findings.
-/

/-- Replace the domain of the `i`-th instance-implicit binder with `repl`, keeping the
binder structure identical so the body's de Bruijn indices stay valid. -/
private def weakenBinder (ty : Expr) (i : Nat) (repl : Name) (replArity : Nat)
    (expectedSource : Option Name := none) : Option Expr :=
  go ty 0
where
  go (e : Expr) (seen : Nat) : Option Expr :=
    match e with
    | .forallE n d b bi =>
      if bi == .instImplicit then
        if seen == i then
          let sourceMatches :=
            match expectedSource, d.getAppFn with
            | none, _ => true
            | some expected, .const actual _ => expected == actual
            | some _, _ => false
          if !sourceMatches then none else
          -- Refuse when the two classes take different numbers of arguments.
          --
          -- The rebuild below reuses the *source* class's arguments, so weakening
          -- `[Zero α]` to `OfNat` produced `OfNat α` where `OfNat α 0` was needed. That is
          -- ill-typed, the kernel rejects it, and the caller then reported REFUTED — a
          -- verdict about a term nobody meant to ask about. Measured over 578 probes: all
          -- 134 arity-changing ones were "refuted" and none could have been anything else,
          -- while the 444 arity-preserving ones confirmed at 32.4%. The aggregate 24.9%
          -- was that dilution.
          --
          -- Refusing is the honest branch and the caller already prints it. Supplying the
          -- missing arguments is not generically possible — `OfNat`'s second argument is
          -- the literal being denoted, which no rule recovers from `Zero`.
          --
          -- The comment below records the same mismatch for universe *levels* and fixes it
          -- there; this is that bug's twin in the argument list.
          if d.getAppArgs.size != replArity then none else
          -- Same arguments, weaker head: `CommRing R` becomes `AddCommMagma R`.
          -- `constLevels!` *panics* on a non-constant domain and, because `panic!`
          -- returns the `Inhabited` default, execution continues and the verdict looks
          -- ordinary while a backtrace goes to stderr where `#guard_msgs` cannot see it.
          -- Refusing to rebuild is the honest branch, and the caller already prints it.
          --
          -- The levels are the replacement's own, obtained by instantiating it fresh.
          -- Pasting the source class's level list onto the target is wrong whenever the
          -- two differ in arity; it survived because ancestors of a given class almost
          -- always share one.
          match d.getAppFn with
          | .const _ ls => some (.forallE n (mkAppN (.const repl ls) d.getAppArgs) b bi)
          | _ => none
        else (go b (seen + 1)).map (.forallE n d · bi)
      else (go b seen).map (.forallE n d · bi)
    | _ => none

/-- Rebuild a term, re-synthesising every instance argument in the current context.

This is what "re-elaborate in an isolated environment" (§6 C4) requires and what retyping
alone cannot do. When a declaration is first elaborated its instance arguments are resolved
against the binders it was written with, and those choices are *baked into the proof term*:
`add_comm a b` under `[CommRing R]` carries `CommRing.toAddCommMagma inst`. Weakening the
binder breaks that projection whether or not the proof needed the strength, which is why
the kernel rejects even a genuine over-hypothesis.

So the projections are discarded and re-derived. Walking the head's type alongside its
arguments gives each instance position's *expected* type with all earlier arguments already
substituted — and because those earlier arguments have themselves been rebuilt, the
expected type is the one the weakened context should satisfy. `synthInstance?` then answers
the real question: can this context supply what the lemma needs?

A position that cannot be synthesised keeps its original argument rather than failing, so
the kernel stays the judge of the whole term instead of this function guessing halfway. -/
partial def resynthInstances (e : Expr) : MetaM Expr := do
  match e with
  | .app .. =>
    let f ← resynthInstances e.getAppFn
    let mut fty ← inferType f
    let mut out := #[]
    for a in e.getAppArgs do
      match (← whnf fty) with
      | .forallE _ d b bi =>
        let a' ←
          if bi == .instImplicit then
            match ← (try synthInstance? d catch _ => pure none) with
            | some inst => pure inst
            | none => resynthInstances a
          else resynthInstances a
        out := out.push a'
        fty := b.instantiate1 a'
      | _ =>
        -- The head's type ran out of binders before its arguments did. Nothing sound to
        -- say about the remaining positions, so they pass through untouched.
        out := out.push (← resynthInstances a)
    return mkAppN f out
  | .lam n d b bi =>
    let d' ← resynthInstances d
    withLocalDecl n bi d' fun x => do
      mkLambdaFVars #[x] (← resynthInstances (b.instantiate1 x))
  | .forallE n d b bi =>
    let d' ← resynthInstances d
    withLocalDecl n bi d' fun x => do
      mkForallFVars #[x] (← resynthInstances (b.instantiate1 x))
  | .letE n t v b _ =>
    let t' ← resynthInstances t
    let v' ← resynthInstances v
    withLetDecl n t' v' fun x => do
      mkLetFVars #[x] (← resynthInstances (b.instantiate1 x))
  | .mdata _ b => resynthInstances b
  | _ => return e

/-- Put a declaration's weakening candidates in front of the kernel.

`forced` names a target class the caller insists on, which is how a *refusal* gets
demonstrated rather than promised: left to itself this only tries weakenings the evidence
proposed, so it confirms nearly always, and a tool that only says yes is indistinguishable
from one that cannot say no.

Reports, per candidate binder, whether the declaration's own proof still typechecks with
the weaker class, and how long the attempt took. The timing is the point as much as the
verdict: it is the number that decides whether confirmation can run over a corpus or only
over a shortlist, and scoping that milestone without it would be inventing a cost. -/
def confirmCore (name : Name) (forced : Option Name) : CommandElabM Unit := do
  let env ← getEnv
  let some ci := env.find? name | throwError s!"unknown declaration `{name}`"
  let some value := (match ci with
    | .thmInfo v => some v.value
    | .defnInfo v => some v.value
    | _ => none) | throwError s!"`{name}` has no value to re-check"
  liftTermElabM do
    let levels ← ci.levelParams.mapM fun _ => mkFreshLevelMVar
    -- Evidence and binders come out of **one** telescope. Two calls to
    -- `forallTelescopeReducing` mint two disjoint sets of fvars, so a carrier recorded in
    -- the first can never equal a binder's carrier from the second and every match fails
    -- silently — the symptom being "no candidate to confirm" for a declaration the report
    -- had just listed candidates for.
    --
    -- The evidence source is `reachedWithCarrier`, the same one `#atlas_home` uses. The two
    -- surfaces disagreed until now: D3 moved the report onto carrier-attached evidence and
    -- left the confirmer on the flat `reachedClasses`, so a candidate the report proposed
    -- was often not one the confirmer would try — measured at 16 of 18 declarations.
    let (evAll, binders) :
        Array (Name × Option FVarId) × Array (Nat × Name × Option FVarId) ←
      forallTelescopeReducing (ci.instantiateTypeLevelParams levels) fun xs concl => do
        let mut ev ← reachedWithCarrier env concl
        if let some v := (match ci with
            | .thmInfo t => some t.value
            | .defnInfo t => some t.value
            | _ => none) then
          let body ← try instantiateLambda v xs catch _ => pure v
          ev := ev ++ (← reachedWithCarrier env body)
        -- Each kept binder carries its position among **all** instance-implicit foralls,
        -- not among those that survived the filter. A binder whose domain head is not a
        -- constant — `DecidableEq`, `DecidablePred`, any `[∀ i, C (f i)]` — is skipped
        -- here while `weakenBinder` counts every `instImplicit` forall, so a free-running
        -- counter drifted by one per skipped binder and the kernel was asked about a
        -- binder the report did not name. That was a soundness bug and it landed in the
        -- negative control: `theorem skew2 {R} [DecidableEq R] [CommRing R] (a b : R) :
        -- a - b = a - b := rfl` answered CONFIRMED to "typechecks without CommRing", for a
        -- statement that cannot be written without `Sub R`. Roughly 10% of Mathlib
        -- theorems have two or more instance binders.
        let mut out : Array (Nat × Name × Option FVarId) := #[]
        let mut raw := 0
        for x in xs do
          let d ← x.fvarId!.getDecl
          unless d.binderInfo == .instImplicit do continue
          let ty ← whnf d.type
          if let .const cls _ := ty.getAppFn then
            out := out.push (raw, cls, (← classCarrierArg? env ty).bind (·.fvarId?))
          raw := raw + 1
        return (ev, out)
    let mut lines : Array String := #[]
    for (raw, cls, carrierFv) in binders do
      let here : NameSet := evAll.foldl (init := {}) fun acc (c, fv) =>
        if fv.isSome && fv == carrierFv then acc.insert c else acc
      let v := walk env cls here
      if forced.isSome || !here.contains cls then
        if let some h := forced.orElse (fun _ => v.home) then
          -- How many arguments the target class itself takes, read off its own type.
          -- `Zero : Type u -> Type u` is 1; `OfNat : (a : Type u) -> Nat -> Type u` is 2.
          let replArity :=
            match env.find? h with
            | some d => d.type.getForallBinderNames.length
            | none => 0
          match weakenBinder ci.type raw h replArity with
          | none =>
            lines := lines.push
              s!"  [{cls}] -> {h}: could not rebuild the binder — {h} takes {replArity} \
                 argument(s) and the binder supplies a different number, or the domain is \
                 not a constant application. NO VERDICT: this weakening cannot be stated, \
                 which is not evidence that it is false."
          | some ty' =>
            -- No timing in the verdict. It was D1's deliverable and is recorded there;
            -- printing it here makes the output non-deterministic and the command
            -- untestable, which is CLAUDE.md's "pin the verdict, never the witness" in
            -- another costume. Measured once: ~15-25ms to confirm, ~650ms to refute, the
            -- gap being the instance searches that fail before the kernel is reached.
            -- Anonymous constructor rather than named fields: `type` lexes as a token
            -- in structure-instance position, so `type := ty'` will not parse here.
            -- `TheoremVal` extends `ConstantVal`, hence the nesting.
            let probe := name ++ `atlas_weakened
            -- D1b: rebuild the value in the *weakened* telescope before the kernel sees
            -- it. Opening `ty'` gives fvars whose instance binder is the weaker class, so
            -- `synthInstance?` inside `resynthInstances` is asked exactly the question
            -- that matters — can this context supply what each lemma needs — instead of
            -- being handed projections that assume the answer.
            -- Both halves, not just the value. The *type*'s body carries baked
            -- projections too — `a - a` needs `Sub R`, which the original elaboration
            -- resolved through `CommRing.toSub`. Rebuilding only the value leaves a
            -- weakened type that is itself ill-formed, and the kernel then complains about
            -- the type while the value looks innocent.
            -- Whether re-elaboration actually ran, carried out of the `try`.
            --
            -- The fallback returns the *original* type and value, which is the right thing
            -- to do — a failed re-synthesis should still put something in front of the
            -- kernel — but it means the probe below may be the pre-D1b one, whose negative
            -- result is inconclusive for exactly the reason D1b exists. Reporting both
            -- paths as "REFUTED — even with every instance argument re-synthesised" claims
            -- work that did not happen, and it is the *rejection* message, so the
            -- overstatement lands precisely where the verdict is already weakest.
            let (ty'', value', resynthesised) ←
              try
                forallTelescope ty' fun xs concl => do
                  let concl' ← resynthInstances concl
                  let body ← instantiateLambda value xs
                  let body' ← resynthInstances body
                  return (← mkForallFVars xs concl', ← mkLambdaFVars xs body', true)
              catch _ => pure (ty', value, false)
            let decl := Declaration.thmDecl
              ⟨⟨probe, ci.levelParams, ty''⟩, value', [probe]⟩
            -- The kernel is the oracle. `addDecl` on a throwaway name, and the environment
            -- is discarded either way: this asks a question, it does not extend anything.
            -- `addDecl` does **not** answer this question. Its kernel check surfaces as a
            -- separately-logged error rather than as an exception a `try` can see, so the
            -- first version of this command reported CONFIRMED for a declaration the
            -- kernel had just rejected — including for `needsit`, whose proof genuinely
            -- needs `CommRing`. A confirmation tool that says "confirmed" when the kernel
            -- refuses is worse than no tool.
            --
            -- `addDeclCore` returns an `Except` instead, so the verdict is a value and
            -- cannot escape. The environment it returns is discarded: this asks a
            -- question, it does not extend anything.
            let ok := ((← getEnv).addDeclCore 0 0 decl none).toOption.isSome
            -- The asymmetry is real and must not be flattened. Acceptance is a proof:
            -- the declaration's own term typechecks against the weaker hypothesis, so the
            -- binder was an over-hypothesis. **Rejection proves nothing**, because the
            -- elaborator baked instance projections into the value when it was first
            -- checked — `add_comm a b` under `[CommRing R]` carries
            -- `CommRing.toCommSemiring`, and retyping the binder breaks that chain whether
            -- or not the proof needed the strength. Measured on B3's own fixture: `overh`
            -- is a *known* over-hypothesis (`overh_confirmed` compiles by hand) and this
            -- test rejects it.
            --
            -- Settling a rejection means re-synthesising the value's instance arguments in
            -- the weakened context, which is C4's re-elaboration proper. Until that exists
            -- the negative outcome is INCONCLUSIVE, and calling it "refuted" would be
            -- reporting a false negative as a finding.
            lines := lines.push <|
              if ok then
                s!"  [{cls}] -> {h}: CONFIRMED — the term typechecks without {cls}"
              else if resynthesised then
                s!"  [{cls}] -> {h}: REFUTED — even with every instance argument \
                   re-synthesised in the weakened context, the term does not typecheck"
              else
                s!"  [{cls}] -> {h}: INCONCLUSIVE — re-elaboration in the weakened \
                   context failed, so the kernel saw the original term with its instance \
                   projections still baked in; this says nothing about {cls}"
    if lines.isEmpty then
      logInfo s!"atlas home: `{name}` has no candidate to confirm"
    else
      logInfo <| s!"atlas home confirm: `{name}`\n" ++ "\n".intercalate lines.toList

elab "#atlas_home_confirm " n:ident : command => do
  confirmCore (← liftCoreM <| realizeGlobalConstNoOverload n) none

/-- `#atlas_home_refute <decl> <class>` — insist on a weakening and watch it fail.

The negative control the confirmer needs. Every candidate `#atlas_home_confirm` tries came
from the evidence, so it confirms nearly always, and a tool that only ever says yes is
indistinguishable from one that cannot say no. Naming a class the proof cannot possibly be
built from exercises the refusal path on demand. -/
elab "#atlas_home_refute " n:ident c:ident : command => do
  let name ← liftCoreM <| realizeGlobalConstNoOverload n
  let cls ← liftCoreM <| realizeGlobalConstNoOverload c
  confirmCore name (some cls)

/-! ## Attempting a weakening, rather than re-checking one

`#atlas_home_confirm` and `#atlas_home_refute` ask whether the declaration's **own proof term**
survives a weaker hypothesis. That question has an important limit: a `REFUTED` verdict means
*this proof* fails, never that the weakened statement is false. Measured across 2,305 probes,
1,858 came back refuted — 1,858 well-formed statements whose truth is simply unknown, because
nothing in this project has ever tried to prove one.

`#atlas_home_attempt` closes that. It builds the weakened statement and hands it to a **tactic
ladder**, cheapest first. A success is a new theorem: the generalization holds, and it holds
by an argument the original declaration did not use.

This is the first place the Atlas searches for a proof rather than checking one it was given.
The asymmetry is the reverse of `refute`'s — a success here is sound and final, and a failure
means only that this ladder did not find it within its budget.
-/

/-- Try one tactic against a goal, returning whether it closed it.

Elaborating `(by tac : T)` is how a tactic gets run from metaprogramming — it goes through
the real elaborator, so the tactic behaves exactly as it would inside a proof.

`withoutErrToSorry` is load-bearing: without it a failed elaboration yields a term containing
`sorryAx` and *reports success*, which would turn every unproved statement into a discovery.
The result is then checked for `sorryAx` and for leftover metavariables rather than trusted,
because neither makes elaboration fail, and finally handed to the kernel — the same arbiter
every other verdict in this file uses. -/
private def tryTactic (ty : Expr) (levelParams : List Name)
    (tac : TSyntax `tactic) : TermElabM Bool := do
  let (savedMessages, savedTrees) ← modifyGetThe Core.State fun st =>
    ((st.messages, st.infoState.trees), { st with messages := {}, infoState.trees := {} })
  try
    -- `tryCatchRuntimeEx`, because a deterministic heartbeat timeout is a *runtime*
    -- exception and ordinary `catch` deliberately rethrows those. Without it, a ladder
    -- tactic that burned its budget errored the whole command and the verdict line
    -- vanished — caught by the per-shard `atlas_plant_hard` control on the first census
    -- round, when `exact?` timed out inside `isDefEq`. A within-budget failure is this
    -- command's ordinary data path, so a timeout converts to `false` like any other miss;
    -- interrupts still propagate, which is what distinguishes a budget from a hang.
    tryCatchRuntimeEx (do
      let e ← Term.withoutErrToSorry <| Term.withSynthesize <|
        Term.elabTermEnsuringType (← `(by $tac:tactic)) ty
      let e ← instantiateMVars e
      if e.hasSorry || e.hasExprMVar then return false
      let probe := `_atlas_attempt
      -- `ty` is the original declaration's rewritten type and still names its universe
      -- parameters. Declaring the throwaway theorem with `[]` here made every polymorphic
      -- success fail only at the kernel boundary: tactic elaboration closed the goal, then
      -- `addDeclCore` rejected the undeclared levels. Monomorphic `Type` fixtures could not
      -- expose it; `attemptUniverse` does.
      let decl := Declaration.thmDecl ⟨⟨probe, levelParams, ty⟩, e, [probe]⟩
      return ((← getEnv).addDeclCore 0 0 decl none).toOption.isSome)
      fun _ => return false
  catch _ => return false
  finally
    -- A failed tactic logs its unsolved goal before throwing. Keeping that message makes
    -- the enclosing file fail even though failure is this command's ordinary data path.
    -- Its InfoTree also drives unused/unreachable-tactic linters after the command ends, so
    -- both channels must be restored together.
    modifyThe Core.State fun st =>
      { st with messages := savedMessages, infoState.trees := savedTrees }

/-- `#atlas_home_attempt <decl> <source> => <target> by tac, tac, …` — state the exact
weakening and try to *prove* it.

The ladder is supplied by the caller, cheapest first, and that is deliberate rather than
lazy: this module imports only core Lean — that is what lets it live in the shared
`atlas-extract` package both workspaces path-depend on, physics included. `aesop` and
`exact?` live in Mathlib and Aesop, so they can only be named in a file that imports
them — which the probe file does and this one must not.

Which tactic wins is reported, because it says how deep the result is: a generalization
closed by `rfl` is bookkeeping, one that needs `aesop` is an argument. -/
elab "#atlas_home_attempt " n:ident source:ident " => " c:ident " by " tacs:tactic,+ : command => do
  let name ← liftCoreM <| realizeGlobalConstNoOverload n
  let source ← liftCoreM <| realizeGlobalConstNoOverload source
  let cls ← liftCoreM <| realizeGlobalConstNoOverload c
  let env ← getEnv
  let some ci := env.find? name | throwError "unknown declaration {name}"
  let replArity :=
    match env.find? cls with
    | some d => d.type.getForallBinderNames.length
    | none => 0
  -- A target class and an arity do not identify a binder. The first version silently
  -- rewrote the first same-arity instance binder, which can prove a different statement
  -- while printing the intended target's name. Require the source class too, and refuse if
  -- it occurs more than once; an index is needed to distinguish that case.
  let mut built : Array Expr := #[]
  for raw in [0 : 64] do
    if let some ty := weakenBinder ci.type raw cls replArity (some source) then
      built := built.push ty
  let ty0 ←
    match built with
    | #[ty] => pure ty
    | #[] =>
      logInfo s!"atlas attempt `{name}`: {source} -> {cls}: source binder not found or the target cannot be applied to its arguments — NO STATEMENT"
      return
    | _ =>
      logInfo s!"atlas attempt `{name}`: {source} -> {cls}: {built.size} source binders match; name a binder index before asking for a verdict — NO STATEMENT"
      return
  -- Re-synthesise the statement's own instance arguments before proving anything.
  --
  -- `weakenBinder` swaps the binder's *type* and leaves the body alone, so a statement
  -- written under `[CommRing R]` still says `CommRing.toAddCommGroup inst` where `inst` is
  -- now an `AddCommMagma R`. That type is ill-formed, and the failure is silent in the worst
  -- way: Lean still pretty-prints the goal as `a + b = b + a`, so the tactic sees something
  -- that looks right, fails, and the verdict reads "not proved" instead of "not stated".
  --
  -- Caught by a smoke fixture whose `easy` case is provable by `exact?` at top level and was
  -- coming back unproved here. `confirmCore` already does this for the same reason.
  let ty? ←
    try
      -- Walk the whole dependent telescope.  Re-synthesising only the final conclusion
      -- leaves operation-bearing hypotheses (for example `a + b = a + c`) referring to
      -- projections from the old, stronger instance. Runtime exceptions (heartbeats)
      -- are caught here and below for the same reason as in `tryTactic`: a statement
      -- that cannot be established within budget is a refusal, not a file error.
      liftTermElabM <| tryCatchRuntimeEx
        (some <$> (Term.withoutErrToSorry <| resynthInstances ty0))
        fun _ => pure none
    catch _ => pure none
  let some ty := ty?
    | logInfo s!"atlas attempt `{name}`: {source} -> {cls}: the rewritten statement could not re-synthesise its instance arguments — NO STATEMENT"
      return
  unless ← liftTermElabM (tryCatchRuntimeEx (isTypeCorrect ty) fun _ => pure false) do
    logInfo s!"atlas attempt `{name}`: {source} -> {cls}: the rewritten statement is not type-correct after instance re-synthesis — NO STATEMENT"
    return
  let mut won : Option String := none
  for tac in tacs.getElems do
    if won.isNone then
      if ← liftTermElabM (tryTactic ty ci.levelParams tac) then
        won := some (tac.raw.reprint.getD (toString tac)).trimAscii.toString
  match won with
  | some tac => logInfo s!"atlas attempt `{name}`: {source} -> {cls}: PROVED by {tac}"
  | none => logInfo s!"atlas attempt `{name}`: {source} -> {cls}: not proved by the ladder"

end Atlas
