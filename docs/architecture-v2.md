# Lean-Atlas v2 architecture

Status: implemented through the M6 live semantic-query service, 2026-08-19 PDT.

## Ownership

Lean is the authority for elaboration, definitional equality, typeclass synthesis, unification/application behavior and proof checking. Lean-Atlas owns the durable semantic graph, structural retrieval, relation/query logic and provenance. Artifact execution, scientific campaign freezing and promotion remain outside Atlas's authority.

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

`scripts/check-deps.py` enforces forbidden inward dependency edges and exact workspace-edge allowlists. `atlasd` reaches storage and Lean only through `atlas-engine`; it never depends on a client frontend. `atlas-client` is the sole workspace dependency of the live CLI and MCP frontends and re-exports the versioned daemon protocol types they need.

## Semantic data and v3 store

`atlas-schema::research` owns non-interchangeable identities for relation schemas, claim keys and revisions, scopes, producer receipts, evidence, support circuits, challenges, proposals, falsifiers, plans, runs and assessments. Relation signatures include typed arguments, equality semantics, scope policy, admissible evidence and open/closed-world behavior.

The old `FactRow` and scalar-warrant model remains a compatibility/import boundary. It is not the authority for new research semantics and legacy migration never strengthens a fact automatically.

The v3 SQLite store separates durable semantic/provenance records from provisional workflow state:

- relation schemas, completeness witnesses, scopes, receipts, claim revisions, evidence records/targets, support circuits and challenges are append-only;
- research proposals, falsifiers, plans, observed runs and claim assessments remain revisable and disposable while Atlas itself is being validated.

Persistence alone does not validate an experiment. A run can be stored, corrected or discarded without becoming evidence or a promoted scientific claim.

Large scientific artifacts are deliberately not stored in SQLite. Artifactum remains the intended authority for content-addressed bytes, transformations and replayable lineage.

## Store and logic

`atlas-logic` has no database dependency. `FactSource` is its narrow input seam. The reference evaluator is the executable specification; the optimized evaluator uses delta/semi-naive fixed-point evaluation, bounded deterministic result streams and cancellation. Generated differential tests compare the two.

The v3 store validates relation identity/signatures, scope and receipt existence, admissible evidence classes, support-expression integrity, proposal-local references and plan/run lineage. Multi-row evidence and proposal writes are transactional.

## Live Lean boundary

`lean-server/` is a separate Lean package pinned for CI compatibility testing. Its shared plugin registers Atlas methods into Lean's builtin RPC procedure table, so user research files do not need to import Atlas modules.

`atlas-lean-client` owns a `lean --server` child/session and speaks Lean's LSP framing plus `$/lean/rpc/connect`, `call`, `keepAlive`, and `release`. Heavy Lean values cross requests only as native `WithRpcRef` handles. Session invalidation and invalid references become explicit stale-environment/stale-handle errors.

Lean server requests and notifications interleaved with client responses are classified before response IDs are matched. This includes Lean 4.30 numeric-ID requests such as `workspace/inlayHint/refresh`, which otherwise can alias an in-flight Atlas request and deserialize an absent result as `null`. Server requests receive a bounded headless-client response instead of blocking Lean's request queue.

The Lean child has kill-on-drop ownership. Shutdown attempts the normal LSP `shutdown`/`exit` sequence under a deadline, waits for the child under a second deadline, and force-reaps a process that does not exit. Cancelling a bounded shutdown therefore cannot detach a surviving `lean --server` process.

The live oracle operation gate is:

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

Unsaved document text is recorded in the daemon before it is sent to Lean. A Lean-child restart increments the project Lean generation and deterministically replays every open overlay with `didOpen`, yielding fresh RPC sessions. Mutating and query requests may carry `expected_lean_generation`; stale generations are rejected rather than silently acting on a successor. Native Lean `RpcRef` values are deliberately absent from the daemon protocol, so process-local Lean handles cannot cross a restart or client boundary.

Not every Lean error is process death. Application-level JSON-RPC rejection, malformed method parameters, unknown Atlas methods and stale individual `RpcRef` values return a structured `oracle_failure` without changing the project generation or replacing the Lean PID. A stale RPC environment or an unusable transport (`closed`, I/O, framing or JSON-stream failure) takes the restart path. Successful recovery is surfaced as `lean_restarted`; failed recovery becomes `lean_unavailable`.

Project close and daemon shutdown are ownership boundaries, not best-effort drops. `atlasd` stops accepting work, cancels and drains active client tasks, removes project sessions from discovery, performs bounded Lean shutdown for every project and verifies that the children are reaped before daemonkit may report the generation stopped.

An unexpected `atlasd` process loss is repaired through daemonkit; persistent SQLite state survives, while editor overlays are intentionally process-local and must be republished by the editor after daemon loss.

`atlas-cli` is the live operator/agent frontend. The canonical `atlas-mcp` binary is the MCP frontend over the same client and daemon. The pre-M5 slice-only MCP server remains available as `atlas-static-mcp`, while the existing `atlas <query> <slice.jsonl>` commands remain unchanged as the explicit offline/export path and do not require `atlasd`.

## M6 semantic-query boundary

`atlas-engine::query` implements the first five typed operations through the existing Lean oracle. The daemon protocol is versioned and contains concrete query request/response types rather than an unrestricted method/JSON tunnel. Both CLI and MCP lower to those same protocol types.

### `goal-match`

Atlas receives a bounded candidate set, elaborates the goal, resolves each declaration and asks Lean to apply it. Only successful Lean applications are returned as matches; generated subgoals and structured rejections remain inspectable. Persistent-index candidate generation and ranking are the next retrieval integration, not approximated by accepting structurally similar declarations as final results.

### `why-not`

The same lookup/application path records the first failing stage and maps Lean failures into non-generic obstruction classes such as unknown declaration, type mismatch, unification, missing hypothesis, instance synthesis, metavariable, universe, stale context and invalid proof. The committed live fixture proves the structured path; the planned curated near-miss corpus must still measure the original 90% classification target.

### `instance-path`

Atlas calls actual Lean typeclass synthesis and returns the synthesized term plus constants occurring in that construction. This is not inferred from static dependency edges. A nested synthesis trace remains a later protocol extension.

### `minimal-context`

Atlas enumerates a bounded cardinality-ordered subset search over explicit, implicit and instance binders. Every accepted frontier member is re-elaborated against its reconstructed forall goal and independently checked by Lean. Module/import minimization is deliberately separate because it requires replay against controlled environment snapshots rather than deleting binders in one live document.

### `compose`

Atlas constructs the default function composition or accepts an explicit proof candidate, elaborates it against the requested proposition and performs a separate `checkProof` call. Only that successful final check produces `status = proved`. Failed composition remains a candidate with its obstruction and does not write a claim, evidence record or assessment.

## Remaining semantic hardening

The service is usable, but these corrections still precede broad scientific claims:

- document- and local-context-scoped handle leases with precise `didChange` invalidation;
- formal environment and document snapshot identities carried through every query receipt;
- richer replayable proof receipts containing goals, used declarations and axiom footprints;
- a dedicated unification operation whose semantics are tested distinctly from `isDefEq`;
- fuller structured Lean failures with populated goal and missing-instance detail;
- persistent index population and automatic candidate generation for live queries;
- benchmarked `why-not` coverage and Mathlib-scale query performance;
- Artifactum lineage, normalized scientific datasets, units, plugin execution and Pi Lab campaign export.

The next vertical slice is the Artifactum-backed EXFOR 1/v case. It should connect immutable input data and normalization lineage to Atlas claims/scopes, execute the numerical/scaling assay through a plugin, retain Lean for formal checks, and export a provisional result for Pi Lab adjudication without automatic promotion.
