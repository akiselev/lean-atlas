# ADR-003: Domain-specific identities, snapshots and receipts

Status: accepted

Date: 2026-08-19

## Decision

Atlas uses domain-specific immutable identities rather than one global world hash: formal environment, source, document, local context, corpus, dataset, execution environment, plugin executable, policy, plan and run identities invalidate independently.

Lean `RpcRef` values are process-local leases. They never cross the daemon protocol, enter SQLite or appear in durable receipts. A lease is tied to a project session, Lean process generation, document snapshot and, where applicable, a local-context snapshot. Document change and process restart invalidate affected leases.

Every durable formal conclusion names a formal receipt or imported theorem identity. The receipt records the operation, request digest, formal environment, document/local-context snapshots, goals before and after, result or structured failure, used declarations, axiom footprint, diagnostics and replay recipe.

Every significant external activity uses a common outer receipt envelope containing producer identity, executable digest, environment, inputs, outputs, command and diagnostics. The payload remains producer-owned.

## Consequences

Changing a Lean toolchain invalidates formal receipts without invalidating an unrelated paper snapshot. Changing an executable or frozen input changes a computational run identity. Reproducibility is evidence about an activity, not automatic evidence for every scientific interpretation of its output.
