# Lean-Atlas architecture decisions

These ADRs govern the v3 semantic model introduced after the M5 daemon boundary.

Precedence:

1. accepted ADRs;
2. `docs/architecture-v2.md` for implemented lifecycle and dependency boundaries;
3. other design documents;
4. historical plans and experiment scripts.

An ADR is changed by a new superseding ADR, not by silently editing its decision. Compatibility code may retain older wire formats while migration is in progress, but it must label them as legacy semantics.

- [ADR-001: ownership and non-goals](0001-ownership-and-non-goals.md)
- [ADR-002: claim, scope, evidence and assessment](0002-claim-scope-evidence-assessment.md)
- [ADR-003: identities, snapshots and receipts](0003-identities-snapshots-and-receipts.md)
- [ADR-004: open-world relations and typed equality](0004-open-world-relations-and-typed-equality.md)
- [ADR-005: proposals, falsifiers, plans and runs](0005-proposals-falsifiers-plans-runs.md)
- [ADR-006: daemon control session and workers](0006-daemon-control-session-and-workers.md)
