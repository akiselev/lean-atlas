# ADR-004: Open-world relations and typed equality

Status: accepted

Date: 2026-08-19

## Decision

Every relation schema declares argument roles and types, equality semantics, symmetry, execution class, scope policy, admissible evidence classes and world semantics.

Scientific relations are open-world by default. Absence of a row means unknown, unimported or unsearched, not false. Negation in derivation rules is allowed only for a relation declared closed-world with a frozen completeness witness such as a corpus snapshot, dataset snapshot, formal environment or enumerated experiment.

Equality is never an unqualified bridge between domains. Relation arguments name the required equality semantics, including exact identity, canonical syntax, Lean definitional equality, proposition equality, isomorphism, physical equivalence under scope or numerical agreement under a named policy.

## Consequences

The store rejects unknown relation schemas, wrong arity, wrong argument types, missing required scope and inadmissible evidence classes. A chain of individually valid transformations is not a valid composite until carriers, local contexts, side conditions and scopes are checked as a whole.
