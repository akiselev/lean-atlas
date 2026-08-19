# ADR-005: Research proposals, falsifiers, plans and runs

Status: accepted

Date: 2026-08-19

## Decision

Generators—including the intuition engine, structural completion, symbolic enumeration and agent planners—emit `ResearchProposal` records. They never write accepted claims directly.

A proposal contains scoped claim drafts, mechanism edges, assumptions, predicted observations, explicit falsifiers, alternatives, obligations, resource estimates, generator receipt and search-score vector. Search scores are policy metadata and cannot be attached as evidence for the proposed claim.

A falsifier prospectively names its target, applicability scope, evaluator, procedure, decisive condition, effect, independence requirement, budget and stop policy. Budget exhaustion, solver failure or implementation failure do not automatically refute the underlying mathematical claim.

A proposal may compile into an immutable prospective `ResearchPlan`. A separate `ResearchRun` records actual events, failures, retries, receipts, artifacts, human interventions and deviations. The plan is never overwritten with the run.

## Consequences

Negative results remain reusable and scoped: failed proof attempts, counterexamples, wrong regimes, nonconvergence, data-quality failures and stale receipts constrain later search without creating an unscoped global prohibition. Novelty review occurs only after prospective outputs are committed.
