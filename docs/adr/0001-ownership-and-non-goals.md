# ADR-001: Project ownership and non-goals

Status: accepted

Date: 2026-08-19

## Decision

Lean owns elaboration, local contexts, definitional equality, unification, typeclass synthesis and proof checking. Lean-Atlas owns immutable semantic identities, structural retrieval, typed relations, research proposals, evidence circuits and explanations.

Artifactum owns immutable bytes, executable/action identity and replay. Outboard owns executable discovery, capability negotiation and worker isolation. Resolvent owns scientific symbolic meaning and transformations. Solverang owns numerical algorithms. Sinbad owns simulation runtime and state. Pi Lab owns frozen campaigns, blindness, adjudication and promotion.

Atlas consumes producer-owned receipts through adapters. No producer depends on Atlas as a foundational library.

## Non-goals

Atlas does not implement another theorem prover, CAS, simulator, solver, content-addressed store, remote scheduler, plugin loader, campaign engine, universal scientific expression language or universal confidence score.

## Consequences

Cross-repository integration shares versioned contracts and evidence, not internal expression trees, matrices, state stores or schedulers. A result can be formally valid, numerically converged, empirically supported or reproducible without those properties silently implying one another.
