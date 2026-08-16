# Lean Atlas in the formal-to-simulation stack

Lean Atlas remains a **read-only relation/intelligence engine over checked Lean objects**.
Resolvent, Sinbad and research laboratories add valuable external context, but that context
must not blur Atlas's existing distinction between proof, structure, assertion and heuristic
ranking.

## Data flow

```text
Lean corpus ---------------------------> Atlas core relations
    |                                         |
    |                                         | candidate theorem / representation
    v                                         v
Resolvent formal/spec locators <------ scientific refinement index
    |
    v
Resolvent lowerings -> Sinbad results -> Pi Lab / project evidence
```

The new `atlas::scientific` module indexes **external refinement records** separately from the
existing `relation` algebra. It supports questions such as:

- which simulation/operator artifact derives from this formal declaration?
- where did a refinement change scope?
- which refinement chains still have open obligations?
- which imported scientific claims have no formal warrant?
- which formal theorem/certificate is named as warrant for a compiler transformation?

## Hard epistemic rules

1. Numerical convergence, oracle agreement, mutation testing and experimental agreement do
   not create a `Warrant::Proved` Atlas relation.
2. A refinement may name a Lean theorem; Atlas can then link to/query that theorem, but the
   theorem itself remains the source of formal warrant.
3. Scope is explicit. A restriction/specialization is queryable and may not disappear during
   projection or summarization.
4. `Lean Atlas -> Resolvent` is advisory until a proposed theorem/transport is actually checked
   in Lean.
5. `Resolvent/Sinbad -> Lean Atlas` imports provenance/evidence, not mathematical truth.

## Research loop

The productive closed loop is:

```text
Resolvent model/form structure
        |
        v
Atlas finds analogous theorem / weaker home / representation change
        |
        v
Ferris-Howard/Lean attempts proof or instance
        |
       checked
        v
Resolvent receives a new theorem/certificate/refinement fact
        |
        v
new generated validator or safer lowering
```

This lets Atlas's existing dictionary/transport/intuition machinery participate in simulator
development without teaching its mathematical core that a finite-element mesh or experimental
campaign is itself a proof object.

## Project-lab process data

Pi Lab/project laboratories may export process events and refinement/evidence references for
analysis. Those remain a separate experiment/process layer. Agent agreement, repeated
exploration, literature retrieval, or a successful simulation is never silently promoted into
a theorem relation.

The intended long-term join key is content-addressed identity plus stable Lean declaration and
statement hashes, not human names alone.
