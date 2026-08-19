# ADR-002: Claim, scope, evidence and assessment

Status: accepted

Date: 2026-08-19

## Context

The v2 compatibility model orders `Proved`, `Structural`, `Asserted` and `Heuristic` on one scalar ladder. That cannot represent physics: a Lean theorem, a converged computation, an experiment and a literature assertion establish different things.

## Decision

The durable semantic unit is an immutable `ClaimRevision` under a content-addressed `ClaimScope`. Claims do not contain acceptance state.

Evidence is immutable, typed and produced by an identified activity receipt. Each `EvidenceTarget` states whether evidence supports, challenges or merely contextualizes a particular claim and how its applicability scope relates to the claim scope.

Multiple support routes are retained as inspectable circuits. Inputs inside one derivation are conjunctive; alternative derivations are disjunctive. Challenges are first-class and scoped.

`ClaimAssessment` is a separate, versioned, policy-dependent view over an immutable evidence snapshot. Atlas may calculate and explain assessments; Pi Lab owns frozen campaign promotion.

## Migration

The old `FactRow` and scalar warrant types remain readable during migration. Import is conservative:

- formal becomes formal evidence only with a replayable receipt or imported theorem identity;
- structural becomes structural evidence only with non-empty retained support;
- asserted becomes documentary evidence only with a source anchor;
- heuristic becomes proposal/search metadata, never accepted evidence.

Migration never strengthens semantics.
