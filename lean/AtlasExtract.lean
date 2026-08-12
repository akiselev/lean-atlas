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
```

Imports the named modules and writes one JSONL row per declaration to stdout. Whole-Mathlib
runs are the point (`lake exe atlas_extract Mathlib`), but they take as long as importing
Mathlib does, so the `--local` form exists for looking at one module in isolation.

Rows are in name order and their fields are in a fixed order, so two extractions diff.
-/

open Lean Atlas

def usage : String :=
  "usage: atlas_extract [--local] <module>...\n\
   \n\
   Writes one JSONL row per declaration to stdout: name, kind, module, instance-registry\n\
   status, canonical statement encoding (statement-hash.md), and used constants.\n\
   \n\
     --local   only declarations of the modules named, not of their imports"

def main (args : List String) : IO UInt32 := do
  let localOnly := args.contains "--local"
  let moduleArgs := args.filter (!·.startsWith "--")
  if moduleArgs.isEmpty then
    IO.eprintln usage
    return 1
  let imports := moduleArgs.toArray.map fun m => ({ module := m.toName } : Import)
  initSearchPath (← findSysroot)
  -- Phase timings on stderr. An extraction that sits at 100% CPU for twenty minutes is
  -- indistinguishable from a hung one without them, and the two phases below have entirely
  -- different cost models: selection is linear in the imported environment, encoding is
  -- linear in what was selected. Diagnosing this by guessing cost three rebuild cycles.
  let t0 ← IO.monoMsNow
  let env ← importModules imports {}
  let t1 ← IO.monoMsNow
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
