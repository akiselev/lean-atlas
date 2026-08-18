# Lean-Atlas v2 architecture

Status: implemented through M5 (`atlasd` daemonized live index), 2026-08-17.

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
  │    ├─ atlas-cli
  │    └─ atlas-mcp
  └─ atlasd
       ├─ atlas-engine
       └─ daemonkit

atlas (compatibility facade / static JSONL tools)
  └─ atlas-schema
```

`scripts/check-deps.py` enforces the forbidden inward dependency edges in CI, including exact workspace-edge allowlists for the M5 daemon crates. `atlasd` reaches storage and Lean only through `atlas-engine`; it never depends on the client frontend. `atlas-client` is the sole workspace dependency of the live CLI and MCP frontends and re-exports the versioned daemon protocol types they need.

## Semantic data

`atlas-schema` owns non-interchangeable IDs, relation execution classes, warrants, fact values and provenance. Relation execution (`materialized`, `derived`, `oracle`, `candidate`) is independent from scientific/formal warrant (`proved`, `structural`, `asserted`, `heuristic`).

The legacy relation enum/parser/registry has been replaced by one declarative relation table. Its stable v1 wire names are retained while `AssertedIff` and `AssertedImplies` are now included in parsing and `ALL`.

## Store and logic

`atlas-store` is a local SQLite semantic database. Large scientific artifacts are deliberately not stored here. The schema includes entities, declarations, relation types, facts/arguments, evidence, origins, oracle receipts, artifact links, fingerprints, module versions, experiments and assays.

`atlas-logic` has no database dependency. `FactSource` is its narrow input seam. The reference evaluator is the executable specification; the optimized evaluator uses delta/semi-naive fixed-point evaluation, bounded deterministic result streams and cancellation. Generated differential tests compare the two.

## Live Lean boundary

`lean-server/` is a separate Lean package pinned for CI compatibility testing. Its shared plugin registers Atlas methods into Lean's builtin RPC procedure table, so user research files do not need to import Atlas modules.

`atlas-lean-client` owns a `lean --server` child/session and speaks Lean's LSP framing plus `$/lean/rpc/connect`, `call`, `keepAlive`, and `release`. Heavy Lean values cross requests only as native `WithRpcRef` handles. Session invalidation and invalid references become explicit stale-environment/stale-handle errors. Lean server requests interleaved with client responses are demultiplexed before response IDs are matched, including Lean 4.30's refresh requests.

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

## M5 daemon and live index boundary

`daemonkit` owns the lifecycle of one authenticated, global `atlasd` instance. `atlasd` owns project sessions and their Lean stdio children; daemonkit does not manage Lean directly. CLI and MCP frontends both use `atlas-client`, so they converge on the same authenticated daemon generation and cannot accidentally create private semantic worlds.

A project session is keyed by a stable digest of its canonical root. It owns:

- the project-local persistent SQLite semantic store (default `.lean-atlas/atlas.sqlite`);
- one Lean child and an explicit Lean-process generation;
- a map of unsaved open-file overlays with editor versions;
- structured `ready`, `degraded`, `restarting`, or `stopped` Lean state.

Unsaved document text is recorded in the daemon before it is sent to Lean. A Lean-child restart increments the project Lean generation and deterministically replays every open overlay with `didOpen`, yielding fresh RPC sessions. Mutating requests may carry `expected_lean_generation`; stale generations are rejected rather than silently acting on a successor. Native Lean `RpcRef` values are deliberately absent from the daemon protocol, so process-local Lean handles cannot cross a restart or client boundary.

Unexpected Lean transport failure is surfaced as a structured `lean_restarted` event when replay succeeds, or `lean_unavailable` when recovery fails. An unexpected `atlasd` process loss is repaired through daemonkit; persistent SQLite state survives, while editor overlays are intentionally process-local and must be republished by the editor after daemon loss.

`atlas-cli` is the live operator/agent frontend. The canonical `atlas-mcp` binary is the MCP frontend over the same client and daemon. The pre-M5 slice-only MCP server remains available as `atlas-static-mcp`, while the existing `atlas <query> <slice.jsonl>` commands remain unchanged as the explicit offline/export path and do not require `atlasd`.

The first five user-facing semantic queries (`goal-match`, `why-not`, `instance-path`, `minimal-context`, `compose`), Artifactum/Outboard integration, and scientific dataset/plugin layers begin after M5.
