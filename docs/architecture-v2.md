# Lean-Atlas v2 architecture

Status: implemented through M4 (live Lean RPC), 2026-08-17.

## Ownership

Lean is the authority for elaboration, definitional equality, typeclass synthesis, unification, application and proof checking. Lean-Atlas owns the durable semantic graph, structural retrieval, relation/query logic and provenance. Bulk artifact execution and campaign promotion remain outside this milestone and outside Atlas's authority.

The portable `lean/` extractor remains unchanged. It is the archival/fallback JSONL path, not the primary interactive semantic boundary.

## Dependency layers

```text
atlas-schema
  ├─ atlas-index
  ├─ atlas-store
  ├─ atlas-logic
  └─ atlas-lean-protocol
       └─ atlas-lean-client

atlas-engine
  ├─ atlas-index
  ├─ atlas-store
  ├─ atlas-logic
  └─ atlas-lean-client

atlas (compatibility facade)
  └─ atlas-schema
```

`scripts/check-deps.py` enforces the forbidden inward dependency edges in CI.

## Semantic data

`atlas-schema` owns non-interchangeable IDs, relation execution classes, warrants, fact values and provenance. Relation execution (`materialized`, `derived`, `oracle`, `candidate`) is independent from scientific/formal warrant (`proved`, `structural`, `asserted`, `heuristic`).

The legacy relation enum/parser/registry has been replaced by one declarative relation table. Its stable v1 wire names are retained while `AssertedIff` and `AssertedImplies` are now included in parsing and `ALL`.

## Store and logic

`atlas-store` is a local SQLite semantic database. Large scientific artifacts are deliberately not stored here. The schema includes entities, declarations, relation types, facts/arguments, evidence, origins, oracle receipts, artifact links, fingerprints, module versions, experiments and assays.

`atlas-logic` has no database dependency. `FactSource` is its narrow input seam. The reference evaluator is the executable specification; the optimized evaluator uses delta/semi-naive fixed-point evaluation, bounded deterministic result streams and cancellation. Generated differential tests compare the two.

## Live Lean boundary

`lean-server/` is a separate Lean package pinned for CI compatibility testing. Its shared plugin registers Atlas methods into Lean's builtin RPC procedure table, so user research files do not need to import Atlas modules.

`atlas-lean-client` owns the `lean --server` child/session and speaks Lean's LSP framing plus `$/lean/rpc/connect`, `call`, `keepAlive`, and `release`. Heavy Lean values cross requests only as native `WithRpcRef` handles. Session invalidation and invalid references become explicit stale-environment/stale-handle errors.

The M4 operation gate is:

- `lookupDecl`
- `getType`
- `inferType`
- `whnf`
- `isDefEq`
- `unify`
- `synthInstance`
- `apply`
- `elaborate`
- `checkProof`
- batched `isDefEq`

The daemon/session manager (`atlasd`), first five user-facing semantic queries, Artifactum/Outboard integration and scientific dataset/plugin layers begin after this milestone.
