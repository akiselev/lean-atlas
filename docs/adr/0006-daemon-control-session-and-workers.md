# ADR-006: Daemon control session and speculative workers

Status: accepted

Date: 2026-08-19

## Decision

`daemonkit` owns the authenticated `atlasd` lifecycle. `atlasd` owns project stores, live document overlays and Lean children. Frontends reach the service only through `atlas-client`; they do not access storage or Lean directly.

Each project initially has one interactive Lean control session that tracks unsaved editor state. The public protocol must not make one process a permanent invariant. Later speculative workers operate only on frozen snapshots or checkpoints under explicit budgets and cannot mutate the interactive control session.

The daemon protocol exposes typed task-level commands and structured failures. It does not expose an unbounded `method: String, params: JSON` tunnel. Native Lean handles remain inside the formal backend implementation.

Ordinary JSON-RPC application rejection does not restart Lean. Stale environments and unusable transports do. Project close and daemon shutdown drain active work and reap all owned children before reporting completion.

## Consequences

A speculative proof search can be cancelled or crash without corrupting the editor session. A daemon or Lean generation transition is observable and fences stale requests. Static JSONL extraction remains an explicit archival and differential-testing path rather than the primary interactive boundary.
