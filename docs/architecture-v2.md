# Lean-Atlas v2 architecture

Status: implemented through M5 (`atlasd` daemonized live index/session boundary), 2026-08-17.

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

atlas-daemon-protocol
  ├─ atlas-client ── daemonkit
  └─ atlasd
       ├─ atlas-engine
       ├─ atlas-store
       ├─ atlas-lean-client
       └─ daemonkit

atlas (compatibility facade)
  └─ atlas-schema
```

`scripts/check-deps.py` enforces the forbidden inward dependency edges in CI.

## Semantic data

`atlas-schema` owns non-interchangeable IDs, relation execution classes, warrants, fact values and provenance. Relation execution (`materialized`, `derived`, `oracle`, `candidate`) is independent from scientific/formal warrant (`proved`, `structural`, `asserted`, `heuristic`).

The legacy relation enum/parser/registry has been replaced by one declarative relation table. Its stable v1 wire names are retained while `AssertedIff` and `AssertedImplies` are now included in parsing and `ALL`.

## Store and logic

`atlas-store` is a local SQLite semantic database. Large scientific artifacts are deliberately not stored here. The schema includes entities, declarations, relation types, facts/arguments, evidence, origins, oracle receipts, artifact links, fingerprints, module versions, experiments and assays.

M5 makes the daemon the process owner of the persistent semantic store. The default database is in the user's state directory (`$XDG_STATE_HOME/lean-atlas`, `%LOCALAPPDATA%/lean-atlas`, or `$HOME/.local/state/lean-atlas`) and can be overridden with `ATLAS_STORE_PATH`. Daemon lifecycle metadata remains daemonkit-owned and is not used as the semantic database.

`atlas-logic` has no database dependency. `FactSource` is its narrow input seam. The reference evaluator is the executable specification; the optimized evaluator uses delta/semi-naive fixed-point evaluation, bounded deterministic result streams and cancellation. Generated differential tests compare the two.

## Live Lean boundary

`lean-server/` is a separate Lean package pinned for CI compatibility testing. Its shared plugin registers Atlas methods into Lean's builtin RPC procedure table, so user research files do not need to import Atlas modules.

`atlas-lean-client` owns a `lean --server` child/session and speaks Lean's LSP framing plus `$/lean/rpc/connect`, `call`, `keepAlive`, and `release`. Heavy Lean values cross requests only as native `WithRpcRef` handles. Session invalidation and invalid references become explicit stale-environment/stale-handle errors.

Lean 4.30 also sends server-to-client JSON-RPC requests while Atlas calls are in flight. The transport classifies messages by `method` before matching response IDs and responds to these requests; a numeric server-request ID therefore cannot alias the numeric ID of an Atlas request.

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

## M5 daemon/session boundary

`daemonkit` owns `atlasd` lifecycle, startup serialization, local endpoint security and authenticated application streams. It does **not** supervise Lean as a managed child:

```text
daemonkit -> atlasd -> lean --server stdio
```

`atlasd` owns a map of project sessions. Each project session owns:

- one Lean stdio process;
- one monotonically increasing Atlas session generation;
- the current unsaved/open-document text overlay;
- its health/degradation state.

The project generation is part of every handle-bearing daemon request. Any explicit or crash-driven Lean restart increments that generation before new oracle traffic can proceed. Requests carrying a pre-restart token are rejected as `stale_session` before their Lean `RpcRef`s can be forwarded to a new process. A transport crash returns `lean_restarted` with old/new generations; a failed respawn leaves the project explicitly `degraded`.

The overlay is retained by `atlasd` and replayed when it respawns Lean. Atlas therefore preserves the interactive unsaved-file view across a Lean child failure without pretending old handles survived it.

`atlas-client` is the authenticated local client library. `atlas-live` is the direct CLI over daemon/session targets, and `atlas-live-mcp` exposes the same typed daemon protocol to MCP clients. The legacy `atlas`/`atlas-mcp` static-slice surfaces remain available during migration so exported JSONL remains an explicit fallback rather than being silently reinterpreted as live state.

The observational M5 acceptance and crash/race validation procedure is in `docs/validation/m5-atlasd-manual.md`.

The first five user-facing semantic queries, Artifactum/Outboard integration and scientific dataset/plugin layers begin after this milestone.
