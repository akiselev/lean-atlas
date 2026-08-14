# Intuition Engine

Status: executable research substrate, not a discovery claim.

The intuition layer treats mathematical intuition operationally as the ability to choose a
productive change of representation. It deliberately does **not** equate statement
similarity with analogy, and it does not use a language model or embedding as a truth/value
oracle.

The implementation now has four separable layers:

1. `intuition.rs` — affordances, method ontology, one-step ranking, bridge proposals,
   auxiliary objects, negative experience, and method motifs;
2. `intuition_viewpoint.rs` — explicit multi-step viewpoint graphs and Pareto research taste;
3. `intuition_concept.rs` — formal concepts and exact corpus implications over extracted
   affordances;
4. `intuition_benchmark.rs` — pre-registered top-k/MRR benchmark harness for historical or
   counterfactual viewpoint rediscovery.

## 1. Core objects

For each encoded declaration Atlas parses the existing `atlas-stmt-v1` term into the same
hash-consed term arena used by the skeleton engine and walks the resulting AST. Constant
symbols are classified into coarse structural **affordances** such as:

- algebraic / polynomial;
- geometric / topological / quotient;
- linear / operator / inner-product / spectral;
- differential / integral / dynamical / variational;
- probabilistic / measure / entropic;
- symmetry / conservation;
- finite / discrete / continuous / limit-asymptotic / scaling;
- order / positivity / optimization.

The evidence is retained as the exact constant names that fired each affordance. There is no
pretty-printed Lean parsing and no hidden embedding vector.

A `MethodSpec` describes a research move by:

- `recognizes`: affordances that make the move structurally plausible;
- `native`: affordances where the method is already at home (used to estimate domain
  distance, not as a gate);
- `unlocks`: affordances a successful viewpoint change would expose;
- `auxiliary`: the object usually needed to realize the change;
- `obligations`: what must be proved before the move is trusted;
- `losses`: information the change commonly discards.

The bootstrap catalogue includes spectralization, Fourier transform, generating functions,
geometrization/algebraization, probabilization, variationalization, linearization, duality,
symmetry reduction, moduli, tropicalization, compactification, categorification,
cohomological reformulation, operator/energy introduction, scale/RG-style reformulation,
and several toy-world operations.

This is a human-seeded starting language, not a frozen ontology. The sleep/dream program is
supposed to propose additions after measured held-out wins.

## 2. Scoring contract

For problem/viewpoint `P` and method `M`, the first scorer exposes five independent terms:

1. **compatibility** — fraction of `M.recognizes` visible in `P`;
2. **domain distance** — how little of `M.native` is already present;
3. **bridge value** — fraction of `M.unlocks` that would be genuinely new;
4. **novelty-of-view** — how absent the output language currently is;
5. **representation breadth gain** — how many additional method specifications become
   structurally plausible after simulating the unlocked affordances.

Compatibility gates the score. This is deliberate: previous cross-domain experiments showed
that rewarding domain distance or shared apparatus without structural fit mostly finds
plumbing.

The current formula is deliberately simple and named in source rather than learned:

```
base = compatibility
     * (0.44
        + 0.18 * domain_distance
        + 0.16 * bridge_value
        + 0.10 * novelty
        + 0.12 * min(breadth_gain / 5, 1))
     * experience_factor
```

The ranking is then quality-diversity reranked: repeated methods from the same family receive
an exponential beam penalty. The purpose is to return one spectral, one geometric, one
probabilistic, one variational, etc. direction rather than ten close variants of the current
best-scoring language.

These constants are hypotheses to benchmark, not truths about mathematical creativity.

### Pareto taste

`pareto` exposes a second view that does not collapse research taste into the scalar above.
A method survives when no other candidate is at least as good on all of:

- compatibility;
- domain distance;
- bridge value;
- novelty of view;
- representation-breadth gain;
- experience factor.

This is useful when a conservative high-fit move and a riskier high-distance/high-breadth
move should both remain visible.

## 3. Explicit viewpoint graphs

A problem is not one node. `explore` builds a bounded graph of successive representations.
The root is the affordance set recovered from the actual theorem statement. Applying a method
creates a synthetic child state in which `MethodSpec.unlocks` become available, while the
method's obligations and losses are accumulated on the path.

For example, the search can represent a sequence such as:

```
nonlinear dynamics
   --linearize--> tangent/operator problem
   --spectralize--> spectral problem
   --variationalize--> extremal/positivity problem
```

The existence of that path means only that the transformations are structurally plausible.
It does **not** assert that the required operator, equivalence, or error bound exists. Those
are printed as obligations.

The graph search uses:

- a compatibility floor;
- bounded depth and node count;
- a quality-diversity beam by method family;
- multiplicative path score so every speculative translation pays a cost;
- state deduplication by the resulting affordance set;
- best-path metadata if several transformations reach the same state.

This is the executable version of “change viewpoint when the current language is fighting
you.”

## 4. Negative knowledge

An optional experience ledger is intentionally stored outside the formal graph:

```json
{"problem":"My.Theorem","method":"spectralize","outcome":"failed","reason":"no self-adjoint realization","step":3}
```

Outcomes are `succeeded`, `failed`, `refuted`, `blocked`, or `inconclusive`.

Prior failure reduces the score but never deletes a method. A later theorem, better auxiliary
object, or different representation can resurrect a failed route. Refutation receives the
strongest penalty. This makes the boundary of failed analogies available to search without
pretending that a research failure is a kernel fact.

Failures recorded against the root formulation are not blindly propagated to deeper
synthetic viewpoints: a failed spectralization of the original problem is not evidence that
spectralization after a successful linearization is equally bad.

## 5. Bridge search

`bridge A B` is **not** another theorem-similarity query. It aggregates affordances over two
theory/module prefixes and asks for a directed language transfer:

> Is there a method that fits the source structure and whose output language is already
> productive on the target side?

A result such as `geometrize A -> B` means “try viewing A through a geometric representation
because A has algebraic/symmetry affordances and B demonstrates that the geometric output
language is present.” It does not say the theories are equivalent or analogous.

This is the executable seed of the “invent a bridge language” program. A later stage should
measure whether a proposed bridge actually increases proof compression, transport success,
or conjecture quality.

## 6. Auxiliary-object search

Many viewpoint changes are realized by inventing the right object rather than applying a
lemma. `auxiliary` turns a ranked method into a typed research question such as:

- construct an operator whose spectrum encodes the target;
- construct a generating function carrying a family as coefficients;
- construct an energy/Lyapunov functional;
- construct a moduli space or quotient;
- construct a group action/representation decomposition;
- construct a chain complex/cohomology class;
- construct a scale flow or finite analogue.

This is intentionally a role description, not automatic object synthesis yet. The next
stage can combine these roles with structural graph alignment to infer candidate types and
constructors.

## 7. Toy worlds

`toy-worlds` filters the research policy toward controlled simplifications:

- linearization;
- finite analogue;
- discretization;
- continuum limit;
- large-parameter/asymptotic limit.

Every proposal carries an explicit loss and a preservation obligation. The benchmark target
is not “the toy model looks similar”; it is whether the system can identify which invariant
survives the toy world and where the correspondence breaks.

## 8. Formal Concept Analysis

`ConceptContext` is the exact binary incidence relation:

```
declaration × extracted-affordance
```

It fits the current affordance ontology into a `u64` and supports an exact FCA closure
operation. `concepts` enumerates closed intents with Ganter's NextClosure algorithm up to a
caller-supplied cap, then materializes the declaration extent of each concept and the
immediate cover relations among the enumerated concepts.

This gives us an interpretable concept lattice rather than an embedding cluster. For
example, if every declaration carrying `polynomial` in a frozen corpus also carries
`algebraic`, that relationship is visible as closure structure.

`implications` currently emits exact observed implications with singleton or pair
antecedents. This is deliberately **not** advertised as a Duquenne–Guigues canonical basis.
The restricted antecedent size keeps the first experiment scalable and legible.

An implication means:

> in this extracted corpus, every declaration with affordances A also has affordances B.

It does **not** mean `A -> B` is a theorem of mathematics. Promotion requires held-out
validation and, if the statement can be made mathematically meaningful, a proof/refutation
step.

`missing-cells` provides the corresponding negative-space view: an affordance that is common
globally but absent from a named theory. This is only a structural absence. It becomes a
serious research question when an independent alignment, dictionary, or neighboring theorem
family predicts that the role should exist there.

## 9. Historical/counterfactual benchmark

The benchmark harness reads frozen JSONL answer keys such as:

```json
{"id":"rh-spectral","problem":"RiemannHypothesis","expected_methods":["spectralize","introduce-operator"],"top_k":5}
```

and reports:

- per-case rank;
- top-k hit/miss;
- aggregate hit rate;
- mean reciprocal rank.

This only becomes a **historical prediction** experiment if the supplied Lean/literature
corpus itself is frozen to a date before the hidden viewpoint was known. Running today's
corpus against yesterday's discovery is leakage, not rediscovery.

The harness exists now so target lists, alternatives, exclusions, and `top_k` can be frozen
before the system output is inspected.

## 10. Dreaming / method invention

`Experience::motifs` is a deliberately small first sleep-phase primitive. Ordered research
traces are grouped by problem and recurrent adjacent method transitions are counted. For
example:

```
linearize -> spectralize
construct-energy -> prove-positivity
geometrize -> cohomologize
```

Frequent motifs are **candidates** for later MDL/grammar induction. The current code does not
claim that a frequent pair is a new mathematical method. A proper promotion criterion should
measure held-out compression/search-depth reduction before adding a learned method back into
the catalogue.

## 11. What this does not do yet

The current substrate deliberately leaves several stronger ideas for measured follow-ups:

- higher-order/normalization-aware structural alignment between whole derivation DAGs;
- triadic FCA over theorem × affordance × regime once regime metadata exists;
- the full canonical implication basis if the restricted FCA experiment warrants it;
- learned bridge-language invention by corpus compression;
- auxiliary-object type synthesis from graph-role holes;
- a curated historical-cutoff benchmark corpus (the runner exists; the data does not yet);
- proof-state/InfoTree method traces;
- MCP/Python surfaces once the Rust scoring contract is stable;
- a learned value/interestingness model;
- MDL promotion of recurrent traces into new `MethodSpec`s.

The intended progression is: explicit heuristic -> pre-registered benchmark -> failure
analysis -> learned or symbolic replacement. No layer graduates because its output sounds
insightful.

## 12. CLI

```
atlas-intuition profile <slice> <decl>
atlas-intuition methods <slice>
atlas-intuition rank <slice> <decl> [--top N] [--experience attempts.jsonl]
atlas-intuition pareto <slice> <decl>
atlas-intuition refract <slice> <decl> [--top N]
atlas-intuition explore <slice> <decl> [--depth N] [--beam N]
atlas-intuition auxiliary <slice> <decl>
atlas-intuition bridge <slice> <theory-A> <theory-B>
atlas-intuition toy-worlds <slice> <decl>
atlas-intuition concepts <slice> [theory-prefix] [--top N]
atlas-intuition implications <slice> [theory-prefix] [--min-support N]
atlas-intuition missing-cells <slice> <theory-A> [theory-B ...] [--min-global F]
atlas-intuition benchmark <slice> <cases.jsonl>
atlas-intuition dream <slice> --experience attempts.jsonl
```

Every score should be treated as provenance-bearing search-policy output. The next action on
a high-ranked proposal is normally to construct/refute the proposed translation, not to cite
the ranking as evidence.
