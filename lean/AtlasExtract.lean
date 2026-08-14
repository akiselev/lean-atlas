/-
Copyright (c) 2026 The lean-atlas contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
-/
import Atlas.Extract

/-!
# `atlas_extract` — the B1 extractor as a program

```
lake exe atlas_extract Mathlib.Data.Nat.Prime.Basic > rows.jsonl
lake exe atlas_extract --local Tests.M0.Fn          # only that module's own declarations
lake exe atlas_extract --statement-closure Mathlib.Algebra.Group.Basic > closed.jsonl
```

Imports the named modules and writes one JSONL row per declaration to stdout. Whole-Mathlib
runs are the point (`lake exe atlas_extract Mathlib`), but they take as long as importing
Mathlib does. `--local` exists for inspecting one module and is intentionally not closed.
`--statement-closure` emits the named modules plus the transitive closure of constants in
their statements, which is suitable for structural queries after the normal closure/canary
gate and substantially smaller than an entire imported environment.

Rows are in name order and their fields are in a fixed order, so two extractions diff.
-/

open Lean Atlas

def usage : String :=
  "usage: atlas_extract [--local | --statement-closure] <module>...\n\
   \n\
   Writes one JSONL row per declaration to stdout: name, kind, module, instance-registry\n\
   status, canonical statement encoding (statement-hash.md), and used constants.\n\
   \n\
     --local               only declarations of the modules named; not a closed slice\n\
     --statement-closure   named declarations plus their transitive statement constants"

unsafe def main (args : List String) : IO UInt32 := do
  let localOnly := args.contains "--local"
  let statementClosure := args.contains "--statement-closure"
  if localOnly && statementClosure then
    IO.eprintln "atlas_extract: --local and --statement-closure are mutually exclusive"
    return 1
  let moduleArgs := args.filter (!·.startsWith "--")
  if moduleArgs.isEmpty then
    IO.eprintln usage
    return 1
  let imports := moduleArgs.toArray.map fun m => ({ module := m.toName } : Import)
  initSearchPath (← findSysroot)
  -- `Environment.importModules` defaults to `loadExts := false`. That is sufficient for
  -- reading constants, but it leaves scoped/persistent extensions at their empty initial
  -- state. In particular, `Meta.isInstanceCore` would then report `false` for every
  -- declaration, silently turning authoritative registry metadata into an all-negative
  -- column. The ordinary Lean frontend enables initializers and imports with extensions;
  -- this standalone frontend must do the same. The executable is compiled under the
  -- target workspace's toolchain, so the imported native code and its oleans match.
  enableInitializersExecution
  -- Phase timings on stderr. An extraction that sits at 100% CPU for twenty minutes is
  -- indistinguishable from a hung one without them, and the two phases below have entirely
  -- different cost models: selection is linear in the imported environment, encoding is
  -- linear in what was selected. Diagnosing this by guessing cost three rebuild cycles.
  let t0 ← IO.monoMsNow
  let env ← importModules (loadExts := true) imports {}
  let t1 ← IO.monoMsNow
  -- A schema field that is uniformly wrong is worse than a failed extraction. Keep one
  -- stable Prelude instance as a live canary for the extension state; if Lean changes the
  -- name and the declaration is absent, the guard is intentionally inapplicable rather
  -- than guessing. Under the supported toolchains the declaration exists and is
  -- registered. This caught `loadExts := false`, which emitted plausible v2 rows with
  -- `is_instance: false` for every declaration.
  if (env.find? `instOfNatNat).isSome && !Meta.isInstanceCore env `instOfNatNat then
    IO.eprintln "atlas_extract: instance registry is not loaded (`instOfNatNat` canary failed)"
    return 2
  -- No constant count here. `env.constants.toList.length` walks the whole map, and it sits
  -- *after* `t1`, so its cost was reported as part of nothing and the import figure was
  -- flattering by however long the walk took. The counts below are free — the selection
  -- pass is already iterating.
  IO.eprintln s!"[import] closure imported in {t1 - t0} ms"
  let names ←
    if localOnly then do
      let ns := selectNames env (moduleArgs.toArray.map (·.toName))
      IO.eprintln s!"[select] {ns.size} declarations of the named modules in \
                    {(← IO.monoMsNow) - t1} ms"
      pure ns
    else if statementClosure then do
      let roots := selectNames env (moduleArgs.toArray.map (·.toName))
      let ns := statementClosureNames env roots
      IO.eprintln s!"[select] {roots.size} declarations of the named modules; \
                    {ns.size} in statement closure in {(← IO.monoMsNow) - t1} ms"
      pure ns
    else do
      let ns := allNames env
      IO.eprintln s!"[select] {ns.size} extractable constants in \
                    {(← IO.monoMsNow) - t1} ms"
      pure ns
  let out ← IO.getStdout
  let t2 ← IO.monoMsNow
  -- **Encode and write one row at a time.** Not `let rows := allRows env` followed by a
  -- write loop: a `Row` carries its statement encoding, so materialising the array first
  -- costs tens of gigabytes and emits nothing until the last row is built. Measured on the
  -- physlib closure — 818,835 constants, 8 GB resident, fifty minutes, **zero bytes
  -- written**, indistinguishable from a hang.
  --
  -- Streaming makes memory flat in the corpus size, lets a consumer read the file while it
  -- grows, and leaves usable output if the run is killed. The old `[encode-all] … in N ms`
  -- line measured the *binding* rather than the work, because `t2` was read before the
  -- string interpolation forced the array — it reported 1,295 ms for a job that took half
  -- an hour.
  let mut written := 0
  for n in names do
    if let some info := env.find? n then
      out.putStrLn (rowOf env n info).toJson.compress
      written := written + 1
      -- Flush often enough that the file is readable as it grows, and report progress often
      -- enough that a long run is visibly alive.
      if written % 1000 == 0 then out.flush
      if written % 20000 == 0 then
        IO.eprintln s!"[write] {written}/{names.size} rows in {(← IO.monoMsNow) - t2} ms"
  out.flush
  IO.eprintln s!"[done] {written} rows in {(← IO.monoMsNow) - t2} ms"
  return 0
