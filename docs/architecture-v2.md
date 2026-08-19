# Lean-Atlas v2 architecture

Status: implemented through M5 (`atlasd` daemonized live index), 2026-08-19.

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

The scalar warrant model remains a compatibility boundary at M5. The next semantic milestone replaces it with immutable claim revisions, explicit scopes, typed evidence and support/challenge circuits. M5 does not silently freeze the old warrant hierarchy as the long-term scientific model.

## Store and logic

`atlas-store` is a local SQLite semantic database. Large scientific artifacts are deliberately not stored here. The schema includes entities, declarations, relation types, facts/arguments, evidence, origins, oracle receipts, artifact links, fingerprints, module versions, experiments and assays.

`atlas-logic` has no database dependency. `FactSource` is its narrow input seam. The reference evaluator is the executable specification; the optimized evaluator uses delta/semi-naive fixed-point evaluation, bounded deterministic result streams and cancellation. Generated differential tests compare the two.

## Live Lean boundary

`lean-server/` is a separate Lean package pinned for CI compatibility testing. Its shared plugin registers Atlas methods into Lean's builtin RPC procedure table, so user research files do not need to import Atlas modules.

`atlas-lean-client` owns a `lean --server` child/session and speaks Lean's LSP framing plus `$/lean/rpc/connect`, `call`, `keepAlive`, and `release`. Heavy Lean values cross requests only as native `WithRpcRef` handles. Session invalidation and invalid references become explicit stale-environment/stale-handle errors.

Lean server requests and notifications interleaved with client responses are classified before response IDs are matched. This includes Lean 4.30 numeric-ID requests such as `workspace/inlayHint/refresh`, which otherwise can alias an in-flight Atlas request and deserialize an absent result as `null`. Server requests receive a bounded headless-client response instead of blocking Lean's request queue.

The Lean child has kill-on-drop ownership. Shutdown attempts the normal LSP `shutdown`/`exit` sequence under a deadline, waits for the child under a second deadline, and force-reaps a process that does not exit. Cancelling a bounded shutdown therefore cannot detach a surviving `lean --server` process.

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

Not every Lean error is process death. Application-level JSON-RPC rejection, malformed method parameters, unknown Atlas methods and stale individual `RpcRef` values return a structured `oracle_failure` without changing the project generation or replacing the Lean PID. A stale RPC environment or an unusable transport (`closed`, I/O, framing or JSON-stream failure) takes the restart path. Successful recovery is surfaced as `lean_restarted`; failed recovery becomes `lean_unavailable`.

Project close and daemon shutdown are ownership boundaries, not best-effort drops. `atlasd` stops accepting work, cancels and drains active client tasks, removes project sessions from discovery, performs bounded Lean shutdown for every project and verifies that the children are reaped before daemonkit may report the generation stopped.

An unexpected `atlasd` process loss is repaired through daemonkit; persistent SQLite state survives, while editor overlays are intentionally process-local and must be republished by the editor after daemon loss.

`atlas-cli` is the live operator/agent frontend. The canonical `atlas-mcp` binary is the MCP frontend over the same client and daemon. The pre-M5 slice-only MCP server remains available as `atlas-static-mcp`, while the existing `atlas <query> <slice.jsonl>` commands remain unchanged as the explicit offline/export path and do not require `atlasd`.

## Deliberately deferred M4.1 semantic corrections

M5 establishes lifecycle and service ownership. It does not claim to solve the deeper durable-semantics boundary. The next stacked milestone must provide:

- document- and local-context-scoped handle leases, with `didChange` invalidation;
- explicit formal environment and document snapshot identities;
- replayable formal receipts containing goals, used declarations and axiom footprints;
- real proof-check semantics rather than only inferred-type definitional equality;
- real unification distinct from `isDefEq`;
- a meaningful distinction between declaration type lookup and expression type inference;
- complete structured failures when goals are populated;
- strict store enforcement for relation schemas, evidence links and non-empty derivations;
- immutable claims with explicit scopes and typed evidence rather than a universal scalar scientific warrant.

These corrections precede the first five user-facing semantic queries (`goal-match`, `why-not`, `instance-path`, `minimal-context`, `compose`). Artifactum/Outboard integration and scientific dataset/plugin layers follow those semantic gates.
