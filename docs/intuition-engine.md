# Intuition Engine

Status: first executable substrate, not a discovery claim.

The intuition layer treats mathematical intuition operationally as the ability to choose a
productive change of representation. It deliberately does **not** equate statement
similarity with analogy, and it does not use a language model or embedding as a truth/value
oracle.

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

A `MethodSpec` then describes a research move by:

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

## 2. Scoring contract

For problem/viewpoint `P` and method `M`, the first scorer exposes five independent terms:

1. **compatibility** — fraction of `M.recognizes` visible in `P`;
2. **domain distance** — how little of `M.native` is already present;
3. **bridge value** — fraction of `M.unlocks` that would be genuinely new;
4. **novelty-of-view** — how absent the output language currently is;
5. **representation breadth gain** — how many additional method specifications become
   structurally plausible after simulating the unlocked affordances.

Compatibility gates the score. This is deliberate: the previous cross-domain experiments
showed that rewarding domain distance or shared apparatus without structural fit mostly
finds plumbing.

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

## 3. Negative knowledge

An optional experience ledger is intentionally stored outside the formal graph:

```json
{"problem":"My.Theorem","method":"spectralize","outcome":"failed","reason":"no self-adjoint realization","step":3}
```

Outcomes are `succeeded`, `failed`, `refuted`, `blocked`, or `inconclusive`.

Prior failure reduces the score but never deletes a method. A later theorem, better auxiliary
object, or different representation can resurrect a failed route. Refutation receives the
strongest penalty. This makes the boundary of failed analogies available to search without
pretending that a research failure is a kernel fact.

## 4. Bridge search

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

## 5. Auxiliary-object search

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

## 6. Toy worlds

`toy-worlds` filters the research policy toward controlled simplifications:

- linearization;
- finite analogue;
- discretization;
- continuum limit;
- large-parameter/asymptotic limit.

Every proposal carries an explicit loss and a preservation obligation. The benchmark target
is not “the toy model looks similar”; it is whether the system can identify which invariant
survives the toy world and where the correspondence breaks.

## 7. Dreaming / method invention

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

## 8. What this does not do yet

The first substrate deliberately leaves several stronger ideas for measured follow-ups:

- higher-order/normalization-aware structural alignment between whole derivation DAGs;
- formal-concept-analysis implication bases over theorem × affordance × regime contexts;
- learned bridge-language invention by corpus compression;
- auxiliary-object type synthesis from graph-role holes;
- historical cutoff benchmarks for rediscovering viewpoint shifts;
- proof-state/InfoTree method traces;
- MCP/Python surfaces once the Rust scoring contract is stable;
- a learned value/interestingness model.

The intended progression is: explicit heuristic -> benchmark -> failure analysis -> learned
or symbolic replacement. No layer graduates because its output sounds insightful.

## 9. CLI

```
atlas-intuition profile <slice> <decl>
atlas-intuition methods <slice>
atlas-intuition rank <slice> <decl> [--top N] [--experience attempts.jsonl]
atlas-intuition refract <slice> <decl> [--top N] [--experience attempts.jsonl]
atlas-intuition auxiliary <slice> <decl>
atlas-intuition bridge <slice> <theory-A> <theory-B>
atlas-intuition toy-worlds <slice> <decl>
atlas-intuition dream <slice> --experience attempts.jsonl
```

Every score should be treated as provenance-bearing search-policy output. The next action on
a high-ranked proposal is normally to construct/refute the proposed translation, not to cite
the ranking as evidence.
