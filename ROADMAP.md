# Lean Atlas roadmap

**Status:** research and implementation roadmap, 2026-08-12  
**Baseline inspected:** `c045d99`  
**Current execution:** M0 started in this worktree (`atlas-row-v2` and core role/requirement
parsing)  
**Scope:** the extractor in `lean/`, the Rust query engine and MCP server in
`crates/atlas`, the Python binding in `crates/atlas-py`, and replayable research
harnesses in `scripts/`.

Lean Atlas should become a **typed, temporal, provenance-bearing relation engine over
exact Lean objects**. Its purpose is not merely to draw dependency graphs or retrieve
nearby theorems. It should expose:

- which assumptions and capabilities a result actually uses;
- which statements and proofs instantiate the same structural pattern;
- which transformations systematically carry one family of mathematics into another;
- where a theory-to-theory correspondence is coherent and where it breaks;
- which theorem families, transformation diagrams, or abstractions have conspicuous
  missing members;
- eventually, how these structures evolve through library history; and
- exactly what evidence warrants every reported relation.

The system may generate conjectures and research leads. It must never present a graph
pattern, ranking, failed proof search, or kernel-checked theorem as evidence of novelty or
scientific importance.

---

## 1. North star

The north-star workflow is:

```text
closed, versioned Lean corpus
          |
          v
exact structural and dependency facts
          |
          v
interpretable candidate relation or missing diagram
          |
          +----> counterexample / proved negation
          |             |
          |             v
          |       recorded boundary
          |
          +----> Lean proof or replay
          |             |
          |             v
          |       warranted formal relation
          |
          +----> inconclusive / environment failure / stale corpus
                        |
                        v
                 distinct recorded outcome

formal truth -> external prior-art search -> significance assessment
```

The flagship experiment is **hidden transformation recovery and missing-square
completion**:

1. Hide known additive/multiplicative, order-dual, opposite, or related correspondences,
   including their names and attributes.
2. Learn the repeated typed substitutions from the remaining exact statements and graph
   neighborhoods.
3. Recover the hidden correspondences.
4. Find diagrams with three known corners and propose the missing fourth corner.
5. Elaborate and prove, refute, or leave each proposal explicitly unresolved.

This experiment is difficult enough to measure useful progress, but exact enough to audit.
It exercises the assets that distinguish Atlas from a generic graph database.

---

## 2. Non-negotiable research contract

Every milestone in this roadmap inherits the repository operating contract.

### 2.1 Exact expressions, not reconstructed syntax

All statement structure comes from elaborated Lean `Expr` trees through the versioned
`atlas-stmt-v1` encoding. Never render a Lean term and parse the rendered surface string
back into a purported semantic object. A future proof encoding must follow the same rule:
it is either produced directly from `Expr`/elaboration state or not claimed as exact.

The version tag remains inside every encoded payload. Rust-side digests are over the exact
UTF-8 payload. Version skew remains distinct from statement change.

### 2.2 Closed slices and restriction witnesses

Every experiment records `atlas closure` for its input slice. A slice not extracted by the
same experiment must additionally name a known-holed statement and assert that its
skeleton remains holed after restriction. Without that sentinel, a missing head constant
can silently weaken normalization and change the answer.

No downstream score repairs an open slice.

### 2.3 Claims are a deliberate population

Metaprogramming declarations, recursors, projections, generated instances, and ordinary
mathematical claims answer different questions. Every experiment declares its:

- `--lens` (`statement`, `proof`, or `both`);
- erasure `--level`;
- declaration-kind gate;
- instance/generated-role gate;
- theory/module population; and
- corpus digest.

The default discovery population is mathematical claims. `--all-kinds` is an explicit
ablation, not an innocent default.

### 2.4 Warrant and status are separate

Every relation has both a semantic kind and an evidence grade. At minimum, preserve:

- **proved:** a named Lean theorem or checked certificate warrants the relation;
- **structural:** a decidable comparison of exact encodings warrants the relation;
- **asserted:** the source corpus states the relation as an axiom or conjectural fact;
- **heuristic:** an algorithm ranked or proposed the relation.

Search outcomes are also distinct:

- `PROVED`;
- `COUNTEREXAMPLE` or `PROVED_NEGATION`;
- `NOT_PROVED_WITH_BUDGET`;
- `NO_WELL_TYPED_CANDIDATE`;
- `ENVIRONMENT_FAILURE`;
- `STALE_CORPUS`;
- `UNTESTED`.

In particular, failure of a proof term, tactic, solver, or timeout is not refutation.

### 2.5 Four independent scientific questions

Atlas reports these separately:

1. **Calibration:** did the method recover frozen known relationships or future expert
   edits without leakage?
2. **Truth:** did Lean check the exact proposed statement and proof under the declared
   assumptions?
3. **Novelty:** does an external literature and current-library search find prior art?
4. **Significance:** does the result simplify theory, transfer a method, explain data, or
   matter to domain experts?

The kernel answers only the second question.

### 2.6 Controls operate at the causal level

If a component acts on theory alignment, its negative control must break theory alignment.
If it acts on transformations, hide or permute transformations. If it acts on proof shape,
control proof shape rather than merely renaming declarations. Identity-level exclusions do
not control a higher-level mechanism.

The exit status of the gate itself is always recorded.

---

## 3. Current implementation baseline

The roadmap is grounded in the live repository, not only the older design documents or the
related public projects discussed in research notes.

### 3.1 Implemented now

- The Lean extractor emits the versioned `atlas-row-v2` envelope: declaration name, kind,
  module, instance-registry status, canonical statement encoding, statement encoding
  errors, separate statement/proof used constants, and source-attributed statement-level
  class requirements. The Rust and Python declaration models now preserve these fields;
  untagged legacy rows report missing metadata as unknown.
- Batch extraction loads Lean's environment extensions and refuses output if a stable
  Prelude instance-registry canary fails. This prevents a structurally valid v2 corpus with
  a silently all-false `is_instance` column.
- The extractor also has a storage-conscious `--statement-closure` mode: it emits the
  named modules plus the fixed point of constants mentioned in their statements. This is
  appropriate for structural/statement-lens experiments after the ordinary closure and
  known-holed-canary gate; it does not claim proof-lens closure.
- The Rust graph preserves separate statement and proof dependency lenses and implements
  `why`, `foundations`, `impact`, direct citation ranking, honesty checks, and closure.
- The skeleton engine parses the exact encoding into a typed term arena and implements
  erasure levels, indexed anti-unification, similarity, motifs, variants, adjacency, and
  vocabulary adjacency.
- Statement equivalence, proved `Iff`/implication extraction, candidate dictionaries,
  transport, and theory frontiers exist.
- Lean-side `#atlas_home`, confirmation, refutation controls, and directed proof attempts
  implement a bounded carrier-weakening workflow.
- The relation type already prevents several category errors by separating relation kind,
  direction, warrant, and evidence.
- CLI, MCP, and Python surfaces exist over the same Rust core.

At the time this roadmap was written, the Rust workspace's 125 tests and the Lean
extractor build passed.

### 3.2 Important gaps in the live boundary

- Carrier requirements are now present in the core declaration model, but no core
  capability/incidence graph consumes them yet.
- Dictionary assembly can now exclude registered instances from authoritative metadata,
  but broader generated/coercion/projection roles are not yet represented and severe
  many-to-one collision behavior remains.
- `uses_proof` is a set of cited names. It does not preserve order, nesting, repeated use,
  eliminator structure, local subproofs, or tactic states.
- The implemented logical graph is deliberately carrier-blind. Each edge is proved, but a
  multi-edge path is a lead rather than a composable proof.
- Current “bridge centrality” is transitive impact, not articulation or cut centrality.
  Whole-corpus transitive ranking still needs SCC condensation and dynamic programming.
- Relation kinds exist as an API contract, but there is no universal persistent,
  queryable relation/experiment store joining every engine.
- Dictionary assembly is primarily pairwise/local rather than a globally coherent theory
  alignment.
- Historical scripts encode valuable experiments and failures, but they are not production
  commands and several refer to corpus paths that must be freshly extracted.

### 3.3 Reconciliation with the external feedback

The feedback's multiplex-graph vision is adopted, with four corrections:

1. This repository currently separates **statement-use and proof-use**, not a generic
   type/value graph with source ranges and confidence metadata.
2. The extractor already emits some v2-worthy fields; the immediate job is to carry them
   through the core rather than replace the extractor wholesale.
3. Equality saturation is a useful bounded experiment, not a prerequisite for all
   similarity. Unrestricted `simp`/rewrite saturation can change with imports, explode the
   search space, and erase useful distinctions.
4. Physics-aware relations belong in plugins or domain schemas after the mathematical core
   is calibrated. Formal metadata alone does not establish a physical model's adequacy or
   an empirical law.

---

## 4. Position in the ecosystem

Dependency extraction and generic graph analytics are useful, but no longer a distinctive
research program:

- [TheoremGraph](https://arxiv.org/abs/2606.25363) reports 388,105 formal declaration
  nodes and 11.3 million typed edges across 25 Lean projects, plus an informal/formal
  bridge.
- [MathlibGraph](https://huggingface.co/datasets/MathNetwork/MathlibGraph) publishes
  PageRank, betweenness, Louvain communities, SCC/DAG layers, module and namespace graphs,
  tactic summaries, instance/coercion roles, and `to_additive` pairs over a large Mathlib
  snapshot.
- [ProofGraph](https://proofgraph.org/) has run full-Mathlib spectral analysis.
- [LeanDojo](https://proceedings.neurips.cc/paper_files/paper/2023/hash/4441469427094f8873d0fecb0c4e1cee-Abstract-Datasets_and_Benchmarks.html)
  provides fine-grained premise data and a novel-premise benchmark.
- Structure-aware premise retrieval already uses expression trees, graph kernels, and
  heterogeneous dependency graphs. See
  [Tree-Based Premise Selection for Lean4](https://papers.neurips.cc/paper_files/paper/2025/hash/2ee86e3e9315027920ff2f205f4c3b3a-Abstract-Conference.html)
  and
  [Combining Textual and Structural Information for Premise Selection in Lean](https://arxiv.org/abs/2510.23637).

Atlas should interoperate with these resources where useful. External retrieval or
literature links enter as provenance-bearing heuristic relations. Atlas should not rebuild
their bulk graph products and call scale alone a discovery.

Its differentiators should be:

- exact, typed, multiple-level structural comparisons;
- capability and carrier intervention;
- transformations and theory dictionaries;
- proof-pattern structure;
- compositional verification;
- reproducible hidden-relation and intervention benchmarks;
- explicit negative and incomplete evidence; and
- one relation algebra spanning all of those outputs.

---

## 5. Target data architecture

The database is a multiplex knowledge graph plus hypergraph views. “Multiplex” does not
mean arbitrary edge colors: each layer has its own semantics, composition rules, controls,
and warranted queries.

### 5.1 Entity types

- corpus, project, module, namespace, declaration, declaration revision;
- canonical statement and statement digest;
- proof body and optional proof-expression skeleton;
- carrier binder, local hypothesis, typeclass, instance, structure, operation;
- exact skeleton, anti-unification pattern, proof motif;
- theory/cluster and formal concept;
- transformation and transformation application;
- candidate statement, proof attempt, counterexample, certificate;
- external document or literature assertion.

### 5.2 Core relation layers

| Layer | Representative relations | Principal questions |
|---|---|---|
| Dependency | statement-use, proof-use, definitional-use | What does a claim say, and what does its selected proof use? |
| Declaration role | instance, coercion, constructor, recursor, projection, generated | Is this mathematical content or infrastructure for this query? |
| Typeclass | extends, registered-instance, synthesis-route | What capabilities imply or construct what others? |
| Assumption | requires, proof-survives-without, reproved-under | Which capabilities or hypotheses are sufficient? |
| Structural | exact, presentation-equal, skeleton, anti-unifies | How are statements alike at a declared erasure level? |
| Logical | proved-Iff, proved-implies, asserted-Iff | Which reformulations and consequences are actually stated? |
| Proof | proof-subterm, cites-at-position, proof-motif, tactic-transition | Which arguments use the same method? |
| Transformation | dual-of, additive-of, specialization-of, limit-of | What systematic operation carries one object or result to another? |
| Alignment | candidate-row, confirmed-row, unmatched, collision | How do two theories correspond globally? |
| Temporal | unchanged, renamed, generalized, specialized, split, merged | How did the formalized mathematics evolve? |
| Experiment | proposed, attempted, proved, refuted, timed-out, stale | What was tested, with what outcome and budget? |
| External | described-by, cites, prior-art-candidate | What informal mathematics may correspond to this formal object? |

### 5.3 Relation envelope

Every persisted relation should include:

```text
schema_version
relation_kind
direction
warrant
source_entity
target_entity or targets
evidence_payload
corpus_digest
extractor_version
lean_toolchain
query_scope { lens, level, kinds, prefixes }
closure_manifest
algorithm + parameters + seed
created_at
supersedes / invalidates
```

Candidates and experiment outcomes need additional fields for budgets, exact generated
statements, proof logs, counterexamples, and environment failures. Prose explanations are
rendered from this evidence; prose is not itself the evidence.

### 5.4 Two extraction modes

**Fast corpus mode** remains the default. It reads imported environments and produces
rebuildable, deterministic facts at Mathlib/Physlib scale:

- current statement encodings and dependency lists;
- declaration roles and precise requirement records;
- structure inheritance, instances, coercions, projections, and registered equivalences;
- optional canonical proof-expression summaries extracted directly from values.

**Deep source mode** re-elaborates selected source regions and records `InfoTree` data:

- tactic syntax and macro-expanded identity where available;
- pre/post goal states and local contexts;
- source-to-term mappings;
- proof patches and branching structure;
- tactic execution outcome and cost.

Lean's official API describes `InfoTree` as elaboration-time information used to look up
objects and render tactic state. Deep mode therefore requires the exact source revision and
toolchain and cannot be reconstructed from `.olean` dependency sets alone. See the
[Lean `InfoTree` API](https://lean-lang.org/doc/api/Lean/Elab/InfoTree/Types.html).

Proof-expression mining comes before InfoTree mining: it covers imported corpora and is
independent of how the proof was originally scripted. InfoTree mining is the later,
strategy-oriented layer.

---

## 6. Graph products

Atlas should provide explicit graph projections with documented semantics.

### G1. Multiplex declaration dependency graph

Nodes are declarations. Statement, proof, definitional, instance, coercion, and structure
edges remain separate. Queries may combine layers, but never silently.

Algorithms:

- SCC condensation and topological layering;
- exact transitive impact on the condensation DAG;
- dominators and post-dominators relative to declared roots;
- articulation/biconnected analysis on explicitly named undirected projections;
- vertex/edge cuts and edge-disjoint paths;
- k-shortest explanatory paths;
- typed personalized PageRank as a retrieval baseline.

Caveat: a cut in the selected-proof graph means those recorded proofs break. It does not
show that the affected theorems are logically unprovable by another argument.

### G2. Theorem-capability incidence hypergraph

A theorem may jointly require several capabilities on several carriers. Model the complete
requirement set as a hyperedge rather than replacing it with independent binary edges.

Queries:

- Pareto-minimal capability tuples;
- recurring bundles and implication bases;
- minimal transversals/hitting sets;
- capability bundles with no named abstraction;
- theorems whose declared context strictly dominates every observed minimal tuple.

### G3. Typeclass/home Hasse graph

Nodes are typeclasses or capability tuples. Edges are immediate implication/extension
steps. A declaration occurrence is attached to all confirmed minimal homes, not forced into
one ancestor when the result is an antichain.

### G4. Statement-pattern incidence graph

One side contains claims; the other contains exact skeletons, operator roles, conclusion
forms, requirements, and other declared structural features. This is the input to formal
concept analysis and closed-itemset mining.

### G5. Proof-expression DAG and proof-motif graph

The proof DAG preserves typed applications, binders, repeated subterms, and cited constants.
Derived motif nodes represent recurring exact or anti-unified sub-DAGs. A later InfoTree
graph adds proof-state transitions but remains a distinct projection.

### G6. Carrier-aware logical graph

The current carrier-blind logical graph is retained as a useful reformulation map. A second
graph records enough context—carrier unification, hypotheses, universe/type constraints—to
test whether paths compose. A composed path earns `Proved` only after Lean reconstructs and
checks the composite proof.

### G7. Claim-equivalence/proof-variant graph

One side contains exact or proved-equivalent claims; the other contains their observed proof
variants. Annotate proofs with:

- transitive axiom profile;
- dependency count and proof-expression size;
- constructive/classical indicators;
- confirmed home/capability tuple;
- compilation or replay cost.

The query returns a Pareto front of **observed** proofs. It does not claim intrinsic proof
minimality.

### G8. Transformation action graph

Transformations are nodes or first-class labeled morphisms, not loose similarity edges.
Examples include additive/multiplicative, order duality, opposite structures, conjugation,
specialization, scalar restriction, completion, and parameter limits.

The graph supports composition, inverses where justified, fixed points, orbit detection,
and missing commuting squares or cubes.

### G9. Theory alignment graph

Two theory subgraphs are connected by candidate and confirmed dictionary rows. The graph
also retains contested right-hand targets, unmatched nodes, and row residuals. A family of
pairwise alignments carries cycle-consistency information across three or more theories.

### G10. Temporal lineage graph

Nodes are declaration revisions keyed by corpus/toolchain and statement digest. Edges are
classified as unchanged, renamed/moved, generalized, specialized, statement-changed,
proof-only-changed, split, merged, or dependency-replaced.

### G11. Candidate-experiment-outcome graph

Candidates, assays, generated Lean files, solver/prover attempts, certificates,
counterexamples, environment failures, and literature screens are nodes. This graph is the
durable memory of what Atlas has learned—including where an analogy fails.

### G12. Formal-informal bridge

External systems such as TheoremGraph can supply paper statements and candidate links.
These remain external, heuristic or asserted edges with source provenance. They support
prior-art search and explanation; they do not become formal equivalences without a formal
witness.

---

## 7. Algorithm program

The following programs are ordered by expected value and dependency, not novelty.

### A1. Schema completion and role-aware filtering

Carry `is_instance` and source-attributed carrier requirements into the Rust core, Python,
CLI, MCP, and tests. Add precise roles for coercions, projections, recursors, constructors,
generated declarations, and explicit claims where Lean exposes them reliably.

Immediate benefits:

- eliminate the dictionary's instance-name heuristic;
- make concept and capability incidence exact;
- support role-matched negative controls;
- report what was excluded from a result rather than silently filtering it.

This is the first milestone because every later graph is biased if the engine cannot see
metadata the extractor already knows.

### A2. Multi-home and assumption intervention

The existing home analysis asks whether a declared class binder can be weakened along the
class hierarchy. Extend it to multiple carriers and incomparable capability sets.

Algorithms:

- class-lattice reachability and transitive reduction;
- antichain enumeration of Pareto-minimal homes;
- SAT/SMT or ILP enumeration of minimal sufficient capability sets;
- QuickXplain/delta-debugging-style removal of ordinary hypotheses;
- monotonicity-aware branch-and-bound;
- minimal transversal computation over successful proof routes.

Report three different statements:

1. `OBSERVED_UNUSED`: a binder/hypothesis is absent from the present proof term.
2. `PROOF_REPLAYS_UNDER`: the present proof survives a changed context.
3. `THEOREM_REPROVED_UNDER`: a new proof was found for the weakened statement.

Failure at one tier does not negate the next proposition. The generated weakened statement,
dependent telescope, proof term, and exact source/target classes are part of the evidence.

Hidden known weakenings and synthetic multi-carrier mutations provide the current
benchmark. Historical class-introduction and theorem-generalization commits could later
provide a temporal benchmark, but selected commits would not be a recall denominator.

### A3. Formal concept analysis and missing cells

Construct a declaration-feature relation from exact attributes such as:

- confirmed and candidate capability requirements;
- typed operator heads and structural roles;
- conclusion/quantifier skeletons;
- proved logical relations;
- proof motifs;
- domain annotations, kept separate from computed features.

Use NextClosure/Close-by-One or scalable iceberg-lattice variants to compute formal
concepts, closed itemsets, and implication bases. The main output is not a cluster label but
an interpretable statement:

> These declarations share exactly features F, and the closure normally also contains X.

[Ganter and Wille's formal-concept foundation](https://link.springer.com/book/10.1007/978-3-642-59830-2)
defines the object–attribute context and concept lattice this proposal relies on. Atlas's
extra obligation is to keep carrier/source provenance in the attributes and to benchmark
whether lattice closure predicts anything beyond frequency and module membership.

A missing cell is initially one of:

- `ABSENT_FROM_CLOSED_CORPUS`;
- `PRESENT_UNDER_DIFFERENT_REPRESENTATION`;
- `GENERATED_WELL_TYPED_CANDIDATE`;
- `PROVED`, `REFUTED`, or `UNRESOLVED` after intervention.

Absence is not falsity and is not novelty.

### A4. Proof-expression motifs

Add a versioned proof-expression representation extracted directly from elaborated values.
Preserve sharing and binder scope. Then use:

- exact subtree/sub-DAG hashing;
- bottom-up typed fingerprints;
- Plotkin-style anti-unification over proof fragments;
- Weisfeiler–Lehman graph kernels;
- constrained tree/DAG edit distance;
- frequent connected subgraph or closed motif mining;
- anomaly detection within a fixed statement family.

Outputs include:

- `proof-similar` families with their shared sub-DAG, not only a scalar score;
- repeated subproofs that may deserve a helper lemma;
- theorem families whose claims align while proof strategies diverge;
- proof outliers worth simplification or review.

[ML4PG](https://arxiv.org/abs/1402.0081) provides precedent for recurrent proof clustering,
proof patches, and automaton-shaped proof patterns. Atlas should improve on this by keeping
exact typed expressions and explicit warrant.

### A5. Proof-state dynamics

After proof-expression motifs are calibrated, run deep extraction on selected files. Encode
a proof attempt as a branching state-transition graph rather than a flat tactic-name list:

```text
(local context, goal multiset)
    -- tactic + premises + cost -->
(new local context, new goal multiset)
```

Normalize metavariable and local names without erasing binder types or goal relationships.
Mine recurring proof patches, branching signatures, and strategy transitions. Compare
proof-expression motifs with tactic-state motifs: agreement strengthens interpretation;
disagreement explains tactic elaboration or automation hiding the final term structure.

### A6. Transformation discovery

Start from high-confidence exact statement pairs and discover repeated typed substitutions.
Candidate generation can use:

- shared anti-unification substitutions;
- role-aware Weisfeiler–Lehman colors;
- constrained bipartite matching between constants;
- graph automorphism and orbit detection;
- VF2-style verification on small induced theory graphs;
- support/confidence mining of consistent substitutions.

A transformation record includes domain/codomain predicates, constant mapping, binder and
universe constraints, applicability failures, support, counterexamples, and known witnesses.

Do not infer transformations from names such as `_add`, `_mul`, `op`, or `dual` during blind
evaluation. Those names and attributes are useful labels only after recovery.

### A7. Commuting-square and cube completion

Given transformations `T` and `U`, enumerate diagrams where three corners and the relevant
edges are known:

```text
A --T--> B
|         |
U         U
v         v
C --T-->  ?
```

Apply the exact substitutions to generate the fourth statement. Before proof search:

1. verify that the source slices are closed;
2. check types, binders, universes, and carrier constraints;
3. search exact/presentation/proved-equivalence classes;
4. run bounded counterexample and model checks where applicable;
5. ask Lean for a proof with a declared budget.

Square completion should become the main directed conjecture generator. It generates a
specific missing consequence of learned structure rather than arbitrary plausible text.

### A8. Global theory alignment

Replace independent nearest-neighbor dictionary assembly with a global optimization over
two induced theory graphs.

Candidate node features:

- exact/erased skeleton compatibility;
- confirmed homes and capability tuples;
- logical and proof-motif roles;
- declaration roles;
- local typed dependency neighborhoods.

Candidate edge/topology features:

- preservation of statement/proof dependencies;
- preservation of proved equivalences and implications;
- transformation compatibility;
- consistency with existing confirmed seeds.

Algorithms to compare:

- maximum-weight bipartite matching or min-cost flow;
- quadratic assignment approximations;
- seeded/fused Gromov–Wasserstein optimal transport;
- maximum common typed subgraph on bounded neighborhoods;
- cycle-consistent multi-graph matching.

[Gromov–Wasserstein graph matching](https://proceedings.mlr.press/v97/xu19b.html) is a candidate
optimizer, not a source of warrant. Every row retains its exact structural explanation and
must be separately confirmed by transport or a named theorem.

The most interesting output is the residual:

- unmatched but structurally expected nodes;
- collisions where several left nodes claim one generic right node;
- mapped statements whose dependency neighborhoods fail to transport;
- alignment cycles that do not return to the starting declaration.

### A9. Structural-role similarity

Statement similarity asks whether two claims look alike. Role similarity asks whether they
occupy analogous positions inside their respective theories.

Use:

- typed local graphlets and motif counts;
- relational WL fingerprints;
- SimRank-like recursion with layer-specific transitions;
- spectral neighborhood signatures only on controlled projections;
- aligned ancestor/descendant role profiles.

The output must show the matched neighborhoods. An embedding or scalar alone is not an
explanation. Structural role is most useful as a candidate prefilter for global alignment
and missing-role detection.

### A10. Temporal lineage and future-event prediction — deferred

This is scientifically useful but is **not on the current implementation path**. A faithful
historical replay needs the original Mathlib/Physlib source revision, dependency cache, and
Lean/Lake toolchain; maintaining several such worktrees consumes many gigabytes. Do not
create historical clones or caches for current Atlas work.

Re-extract each historical revision under its actual Lean/Lake toolchain. Match revisions
using statement digests, deprecated aliases, exact structural similarity, module movement,
and dependency overlap. Never compare cross-version digests as though the encoding or Lean
version were irrelevant.

Evaluate discovery algorithms forward in time:

- Did a missing concept-lattice cell become a theorem?
- Did a proposed weakening match a later human generalization?
- Did an unmatched dictionary residual receive an analogue?
- Did a repeated proof motif become a helper lemma or abstraction?
- Did a predicted dependency appear in the next revision?

This would be stronger than random edge holdout because it respects the information
available at prediction time. Until storage is deliberately budgeted for it, use frozen
hidden relationships, synthetic mutations, declaration-level holdouts, and one current
corpus instead. Environment reconstruction failures would remain a named loss class.

### A11. Typed link and relation prediction

Once the exact baselines and temporal benchmark exist, compare:

- common-neighbor, Adamic–Adar, Katz, and personalized PageRank baselines;
- tensor factorization and rule mining;
- relational GNNs/CompGCN-style models;
- relational transformers;
- hybrids using exact skeleton and proof features.

Predicted links are candidates. A missing edge may mean “not imported,” “not used by this
proof,” “not formalized,” “false,” or “represented differently.” Evaluation therefore uses
future edges, hidden known relations, well-typed hard negatives, and proof/counterexample
outcomes—not random nonexistent pairs as presumed false facts.

### A12. Equality saturation and provenance Datalog

Use equality saturation as a bounded candidate and proof-reconstruction layer:

- admit only named proved Eq/Iff rules with explicit direction/context policy;
- track each rewrite's theorem and substitution;
- keep definitional equality separate from theorem rewrites;
- cap e-class/node/time growth;
- extract a concrete proof path and ask Lean to check it.

The [`egg` POPL paper](https://popl21.sigplan.org/details/POPL-2021-research-papers/23/egg-Fast-and-Extensible-Equality-Saturation)
shows why rebuilding and e-class analyses make equality saturation practical, but it also
reinforces that domain-specific analysis and rewrite policy are part of the design. Atlas
therefore treats e-graphs as a capped relation-specific experiment, not a universal
normalizer.

A Lean prototype shows that partially unsound search can still yield sound automation when
Lean checks the reconstructed proof; Atlas must likewise distinguish search soundness from
proof soundness. See
[Bridging Syntax and Semantics of Lean Expressions in E-Graphs](https://arxiv.org/abs/2405.10188).

Provenance-bearing Datalog or egglog-style rules are also attractive for composing exact
relation facts. Neither mechanism replaces the present exact skeleton index. Associative,
commutative, coercion, and `simp` normalization are relation-specific policies, not one
universal canonical form.

### A13. Minimum-description-length abstraction mining

Treat the corpus as data encoded by its current vocabulary and proof DAGs. Search for a new
lemma, definition, structure, or typeclass whose introduction decreases total description
length:

```text
gain = DL(corpus before)
     - DL(new abstraction)
     - DL(corpus rewritten through abstraction)
```

Candidate abstractions come from repeated exact or anti-unified statement/proof motifs.
They are accepted only if:

- their definition and replacement sites elaborate;
- all affected proofs replay;
- the measured gain survives a held-out module or future revision;
- the abstraction is not just generated boilerplate or a renamed existing declaration.

[DreamCoder](https://arxiv.org/abs/2006.08381) motivates compositional library learning;
Atlas's contribution would be exact Lean replay and theory-level evidence.
For a simpler graph-side baseline, [VoG](https://epubs.siam.org/doi/10.1137/1.9781611973440.11)
includes a subgraph in a summary only when it reduces total MDL cost. Atlas should first
test that explicit accounting on frozen motifs before attempting learned library induction.

### A14. Active discovery and diversified review

Candidate generators should compete through a common experiment API. Allocate proof,
counterexample, and human-review budget by expected information gain, calibrated success
probability, verification cost, and diversity.

Do not return a top-k list dominated by one clone family. Compare submodular facility
location, maximal marginal relevance, and determinantal point processes. DPP-based
diversification has improved Lean tactic selection in
[3D-Prover](https://proceedings.neurips.cc/paper_files/paper/2025/hash/5d9d078006840c0643b62013981ad195-Abstract-Conference.html);
Atlas should test whether the same principle improves theorem-review yield. The direct
batch-active-learning precedent is
[Bıyık et al.](https://arxiv.org/abs/1906.07975); random, uncertainty-only, and greedy
farthest-first batches remain required baselines because diversity alone need not improve
the downstream decision.

### A15. Topological data analysis

This is an exploratory late-stage experiment. Build a filtration from a calibrated semantic
distance and compute persistent components and cycles. Stable holes might identify theorem
families connected around a missing correspondence.

No topological feature is a mathematical result. Proceed only after:

- the distance has independent retrieval/alignment calibration;
- exact duplicates and infrastructure are controlled;
- degree/kind/module-preserving null filtrations are run;
- candidate holes can be decompiled into concrete declarations and relations.

---

## 8. Community and network analysis

Atlas should support standard graph metrics for diagnosis and interoperability, but not use
them as a discovery claim by default.

### 8.1 Required exact infrastructure

- Tarjan/Kosaraju SCCs and condensation DAGs;
- reachability counts on the DAG;
- dominator trees;
- biconnected components and articulation points on declared projections;
- exact or sampled betweenness with the approximation labeled;
- k-core/core-periphery summaries;
- typed motif census.

### 8.2 Community models

Prefer algorithms that respect direction and layers:

- multiplex/directed Infomap;
- degree-corrected stochastic block models;
- nested SBM with minimum-description-length model selection;
- overlapping communities where declarations legitimately bridge domains.

The [Infomap review](https://arxiv.org/abs/2311.04036) emphasizes that community meaning
depends on the represented flow process. Atlas must therefore declare the projection and
transition policy.

Every community run gets null models preserving at least degree, role/kind, and preferably
module or layer marginals. Compare cluster stability across seeds and corpus perturbations.
Labels are assigned after fitting and are reported as annotations, not ground truth.

---

## 9. Domain plugins and physics research

The core Atlas should remain domain-neutral. Plugins add relations whose extraction and
verification require a domain ontology. They use the same relation envelope and evidence
grades as the core.

### 9.1 Symmetry, invariant, and conservation plugin

Represent group actions, equivariance, invariants, flows, generators, and conserved
quantities explicitly. Mine incomplete instances of known schemas such as:

```text
action -> equivariance -> invariant -> conserved quantity
```

A missing formal edge is a candidate for a theorem or missing model structure. It is not a
claim that a physical conservation law exists until the theorem's hypotheses model the
system and are physically justified.

### 9.2 Limits, deformations, and special regimes

Make `specialization_of`, `limit_of`, `deformation_of`, `linearization_of`, and
`approximation_of` first-class transformations. Ask whether theorem transport commutes with
the limit and record the analytic side conditions required for that interchange.

Examples may include nonrelativistic, classical, weak-coupling, continuum, thermodynamic,
or large-parameter limits, but only when those limits are formalized rather than inferred
from declaration names.

### 9.3 Assumption phase diagrams

Treat regimes—finite volume, regularity, temperature, coupling, equilibrium, symmetry—as
capability coordinates. Plot confirmed theorem validity across the resulting partial order.
Boundaries between regions are useful targets for counterexamples or theorem strengthening.

### 9.4 Dimensional analysis

Where dimensions are represented in types or certified metadata, assemble the integer
dimension matrix and compute its exact kernel to obtain candidate dimensionless groups.
Relate these groups to scaling transformations, invariants, and theorem families.

The kernel calculation is an exact algebraic result about the declared units. Its physical
interpretation and completeness remain separate questions.

### 9.5 Observable/constraint hypergraphs

Represent a model equation as a hyperedge among observables, parameters, and latent
quantities. Use exact elimination appropriate to the theory—linear algebra, Gröbner bases,
quantifier elimination, interval certificates, SMT, or differential elimination—to propose
relations among observables.

Any proposed relation must carry:

- the original formal model and assumptions;
- an exact elimination certificate where available;
- a Lean theorem proving the relation from that model;
- a separate model-to-experiment adequacy assessment.

### 9.6 Scaling, Lyapunov, energy, and entropy motifs

Mine typed structural families such as fixed points, monotones, energy decay, entropy
production, and Lyapunov inequalities across dynamical systems, PDEs, probability, control,
optimization, and quantum information. Transformation and proof-motif evidence should make
the shared structure inspectable despite vocabulary differences.

These plugins begin only after the core transformation and proof-motif benchmarks pass on
ordinary mathematics.

---

## 10. Query and API direction

Existing commands remain stable where possible. Proposed commands describe capabilities,
not a commitment to exact spelling.

| Query | Result |
|---|---|
| `atlas audit-corpus` | version, closure, role coverage, encoding failures, known-hole sentinel |
| `atlas graph --view …` | typed projection plus manifest, not an unqualified edge list |
| `atlas cuts <decl>` | dominators/cuts in a named lens and projection |
| `atlas assumptions <decl>` | declared assumptions, observed uses, minimal candidate and confirmed antichains |
| `atlas proof-similar <decl>` | proof families with shared exact/anti-unified motifs |
| `atlas concepts` | formal concepts, implication bases, and missing cells |
| `atlas transformations` | supported typed substitutions and their evidence |
| `atlas squares --missing` | incomplete transformation diagrams and generated fourth corners |
| `atlas align <A> <B>` | global dictionary, collisions, residuals, and cycle consistency |
| `atlas pareto-proofs <claim>` | observed proof variants and tradeoffs |
| `atlas lineage <decl>` | version history and classified changes |
| `atlas experiments <candidate>` | complete proof/refutation/environment history |

All query results should be serializable as stable data before they receive a UI. Python
gets handles over shared Rust indexes rather than copied graph objects. MCP results should
return compact summaries plus evidence handles for drill-down.

---

## 11. Visualizations

Visualizations are views of declared graph products, not independent evidence.

| View | Representation | Primary use |
|---|---|---|
| Dependency subway | layered DAG with statement/proof tracks | explain foundations without a hairball |
| Load-bearing map | dominator tree and cut annotations | show which selected proofs share dependencies |
| Concept lattice | Hasse diagram | inspect exact shared feature closures |
| Theorem periodic table | theory/model × structural property matrix | expose absent or unresolved family members |
| Assumption phase diagram | partial-order cells or slices | show where results survive context weakening |
| Proof strategy map | motif clusters and transition paths | retrieve alternate approaches |
| Theory alignment | two-sided matching plus residuals | inspect coherent rows, collisions, and gaps |
| Transformation groupoid | labeled action graph | inspect orbits, fixed points, and compositions |
| Commuting diagram | square/cube grid | expose a specific missing transported claim |
| Proof Pareto plot | multiobjective scatter linked to claims | compare observed proof tradeoffs |
| Temporal alluvial map | revision lineages | inspect generalization, splitting, and refactoring |
| Experiment provenance | candidate-assay-outcome DAG | preserve positive, negative, and incomplete work |
| Discovery frontier | evidence/utility/cost axes | allocate review without one magic score |

Proved, structural, asserted, heuristic, refuted, and unresolved edges must be visually
distinct. Filtering controls and corpus/version information remain visible or one click
away.

---

## 12. Validation program

### 12.1 Universal experiment manifest

Every result directory contains:

```text
objective and predeclared claim
git revisions and dirty-state boundary
Lean/Lake/Rust/Python versions
extractor and relation schema versions
corpus sources and SHA-256 digests
closure report and known-hole witness
lens, level, role/kind gates, prefixes
algorithm, parameters, random seeds, budgets
positive, negative, mutation, and shuffle controls
machine-readable outputs including failures
gate command and its own exit status
```

### 12.2 Validation matrix

| Engine | Calibration target | Required controls | Warrant for an individual result |
|---|---|---|---|
| Schema/closure | Lean JSON versus Rust/Python round trip | missing fields, version skew, removed head constant | exact field equality and closure witness |
| Multi-home | hidden historical weakenings and synthetic multi-carrier fixtures | ambiguous binders, incomparable classes, dependent telescopes | replayed old proof or newly checked proof, labeled separately |
| FCA/missing cells | hide members of known theorem families | role-matched absent cells, shuffled features, infrastructure-only population | structural closure first; Lean proof/refutation separately |
| Proof motifs | hide known proof families or later helper lemmas | same statement/different proof, same citations/different structure | exact shared motif; any strategy interpretation labeled heuristic |
| Transformations | hide `to_additive`, dual, opposite, and specialization pairs | names/attributes removed, permuted substitutions, false carrier maps | exact mapping plus checked transported theorem |
| Diagram completion | remove known fourth corners | noncommuting squares, type-correct false images | Lean proof or checked counterexample |
| Theory alignment | hide known dictionaries | shuffled rights, generic recursors/instances, one-to-many collisions | confirmed rows individually; global score remains heuristic |
| Communities | known annotations used only after fitting | degree/kind/module-preserving nulls and seed perturbation | descriptive structural result only |
| Link prediction | hidden known relations in one frozen corpus | declaration-level holdout, hard structural near-misses, and no full-graph leakage | candidate until independently proved |
| Lineage | manually audited renames/generalizations | encoding/toolchain changes, split/merge cases | exact digest or audited structural match |
| Equality saturation | known rewrite consequences | context-mismatched rules, resource caps, unprovable extraction | reconstructed Lean proof |
| MDL abstractions | later human refactors and held-out modules | generated boilerplate, renamed existing abstractions | full refactor replay plus measured held-out compression |
| Physics plugins | known formal relations and exact certificates | charge/regime/units mutations, nonphysical models | Lean proof about model; empirical claim remains external |

### 12.3 Metrics

Candidate systems report at least:

- recall@k and precision@k on frozen targets;
- family coverage and family purity;
- calibration by confidence band;
- candidate uniqueness after exact/presentation equivalence collapse;
- proof, counterexample, inconclusive, and environment-failure rates;
- verification time and human-review yield;
- per-target losses, not only aggregate scores.

Ranking metrics are insufficient when exact grouping is the useful product. Existing
experiments found several scalar formulas statistically indistinguishable while exact
structure remained informative; future work should therefore compare ranking with
partitioning and explicit pattern explanations.

### 12.4 Benchmark hygiene

- Development targets may guide implementation but cannot support a cold-discovery claim.
- Held-out targets are frozen before algorithm work, stored out of reach of implementing
  sessions, hashed, evaluated once, published whether they pass or fail, and then burned.
- Names, attributes, module paths, and comments that reveal an answer are masked when they
  are not part of the tested signal.
- While historical replay is deferred, evaluations use frozen hidden relations,
  declaration-level splits, and mutation controls in one current corpus. Random edge splits
  alone are diagnostic only.
- A selected positive history corpus is not an opportunity denominator and does not yield
  recall without enumerating expressible opportunities.

The existing RH rediscovery suite remains a development/regression specification. It earns
no cold-rediscovery claim unless its held-out custody and leakage protocol are actually
executed and the corpus contains the required exact formal ingredients.

---

## 13. Milestones

### M0 — Corpus and schema integrity

Deliverables:

- versioned corpus manifest and audit command;
- `is_instance` and `requirements_statement` in the Rust/Python core **(implemented in the
  current worktree)**;
- registered-instance filtering without name heuristics **(implemented as an explicit
  dictionary option)**, followed by broader role-aware filtering;
- relation-store schema and evidence envelope;
- differential tests across Lean JSON, Rust, CLI, MCP, and Python;
- closure plus known-hole sentinel in every research harness.

Exit gate:

- all current tests pass;
- every extractor field either has a documented core consumer or a documented reason for
  remaining sidecar-only;
- corrupt/missing/version-skewed fields fail distinctly;
- a dictionary role-filter ablation demonstrates removal of the current instance heuristic.

### M1 — Exact graph substrate

Deliverables:

- typed multiplex graph export;
- SCC condensation and exact reachability ranking;
- dominators, declared-projection articulation/cuts, and alternative paths;
- carrier-aware logical composition prototype;
- provenance-rich graph query results.

Exit gate:

- graph algorithms pass synthetic and real-slice differential tests;
- every result names its lens and projection;
- composed logical paths either produce checked Lean proofs or remain labeled leads.

### M2 — Capability and concept engine

Deliverables:

- multi-carrier requirement hypergraph;
- Pareto-minimal home antichains;
- ordinary-hypothesis intervention prototype;
- FCA/closed-itemset index and missing-cell report;
- exact distinction between observed unused, old-proof replay, and theorem reproving.

Exit gate:

- synthetic incomparable-home fixtures pass;
- historical parent replay is completed for a frozen sample;
- controls detect carrier conflation and dependent-telescope errors;
- missing-cell results retain absent/unresolved/refuted distinctions.

### M3 — Proof structure

Deliverables:

- versioned proof-expression DAG encoding;
- exact and anti-unified proof motif index;
- proof-similar and proof-outlier queries;
- observed proof Pareto fronts;
- a selective InfoTree/deep-extraction feasibility report.

Exit gate:

- motif recovery beats citation-set and statement-only baselines on held-out proof families;
- no tactic-sequence claims are made from proof terms alone;
- repeated-subproof candidates decompile to exact Lean expressions.

### M4 — Transformations and diagrams

Deliverables:

- transformation schema, learner, and support audit;
- action/orbit queries;
- commuting-square/cube enumeration;
- candidate generation and Lean verification harness;
- negative-edge and experiment store integration.

Exit gate:

- blind recovery of frozen additive/multiplicative, dual, opposite, and specialization pairs;
- names/attributes contribute zero signal during evaluation;
- noncommuting and false-carrier controls fail correctly;
- recovered fourth corners are individually proved, refuted, or unresolved.

### M5 — Global theory alignment

Deliverables:

- global matching baseline and at least one topology-aware matcher;
- collision, residual, and cycle-consistency reports;
- structural-role similarity with neighborhood explanations;
- transformation-aware dictionaries.

Exit gate:

- improves held-out row recovery or collision rate over current pairwise assembly;
- reports all sacrificed/contested rows;
- shuffled-dictionary and generic-infrastructure controls remain negative;
- no global alignment score is promoted to a proved row.

### M6 — Temporal Atlas — deferred until storage is budgeted

Deliverables:

- revision corpus format and toolchain reconstruction protocol;
- lineage matching and change classification;
- time-respecting evaluation harness;
- future-event benchmarks for weakening, transformations, missing cells, and abstractions.

Exit gate:

- audited sample precision for rename/generalize/split/merge classes;
- current/future leakage tests pass;
- environment failures and stale encodings remain distinct from detector losses.

No M0–M5 or current research campaign depends on M6. Do not create historical
Mathlib/Physlib worktrees or dependency caches merely to make progress on earlier
milestones.

### M7 — Learned and active discovery

Deliverables:

- exact graph/link baselines;
- learned prefilters or relation predictors;
- calibrated uncertainty and candidate diversification;
- expected-information-gain experiment scheduler;
- review-yield reports.

Exit gate:

- learned methods beat exact baselines on temporal held-out utility, not merely random AUC;
- ablations identify which data layers contribute;
- candidate explanations survive without the learned score;
- proof/refutation outcomes feed back without erasing unresolved history.

### M8 — Experimental reasoning and abstraction

Deliverables:

- bounded proof-producing e-graph/Datalog prototype;
- MDL abstraction/refactoring experiment;
- optional persistent-homology experiment after distance calibration;
- deep proof-state motif mining if M3 feasibility succeeds.

Exit gate:

- e-graph outputs reconstruct checked proofs;
- abstraction gains survive exact replay and held-out modules;
- topology results beat declared null models and decompile to concrete candidates.

### M9 — Domain plugins

Deliverables begin with one well-formalized domain, not a universal physics ontology:

- typed domain schema;
- symmetry/invariant or dimension/constraint pilot;
- assumption-regime visualization;
- exact certificates and model-scope documentation;
- external literature/empirical handoff.

Exit gate:

- core mathematical benchmarks already pass;
- every plugin relation states what formal model it belongs to;
- formal truth, physical adequacy, novelty, and empirical support are reported separately.

---

## 14. Immediate implementation sequence

The next work should be narrow enough to finish and strong enough to support later research.

1. Add a corpus-manifest type and schema versioning for extractor rows.
2. Parse `is_instance` and `requirements_statement` into the Rust graph/corpus model.
3. Replace dictionary instance-name filtering with the explicit role; retain the old
   heuristic only as a measured ablation during migration.
4. Add a persistent relation/experiment envelope that can represent current relation kinds
   and incomplete outcomes without stringly typed status.
5. Implement SCC condensation, exact transitive ranking, and dominators for named graph
   projections.
6. Promote the existing script-level multi-carrier requirement logic into a tested core
   capability graph.
7. Build the hidden-transformation benchmark before implementing the transformation learner.
8. Implement an exact substitution-support miner and missing-square enumerator.
9. Add global bipartite matching over current dictionary candidates before trying optimal
   transport or neural models.
10. Specify and prototype the proof-expression encoding only after the statement/role schema
    is stable.

The first three measured research campaigns should be:

1. **Hidden transformations:** recover known transformations and missing fourth corners.
2. **Multi-home interventions:** recover hidden known weakenings and synthetic
   multi-carrier cases in one current closed corpus, with old-proof replay and new-proof
   search reported separately.
3. **Global dictionaries:** show whether global alignment reduces collisions and exposes
   meaningful residuals compared with pairwise rows.

FCA/missing-family mining follows as soon as the capability and role incidence matrix is
reliable; otherwise its concepts will mostly rediscover extractor omissions and Lean
infrastructure.

---

## 15. Explicit non-goals

- Another undifferentiated Mathlib graph dump.
- A universal “mathematical importance” or “discovery” scalar.
- Calling high similarity plus low citation a research frontier.
- Calling a proof-search failure a refutation.
- Calling the current proof's dependencies logically necessary.
- Calling a single home the theorem's unique weakest setting when minimal homes are
  incomparable or only proof-relative.
- Treating embeddings, graph alignment, e-graphs, or topology as warrant.
- Reconstructing semantic terms by printing and reparsing Lean surface syntax.
- Mixing statement encodings or toolchains and comparing their digests as stable identity.
- Inferring physical truth or empirical novelty from a formal theorem alone.
- Replacing external literature search with internal corpus absence.

---

## 16. Decision rules

When choosing among possible expansions:

1. Prefer a missing exact data field over a clever model trained around its absence.
2. Prefer an interpretable family/pattern over a barely separated scalar ranking.
3. Prefer a directed, well-typed conjecture from a transformation or residual over free-form
   conjecture generation.
4. Prefer frozen hidden-relationship and mutation evaluation over random held-out edges;
   add historical replay only when storage is explicitly budgeted.
5. Prefer algorithms whose output can be decompiled into exact expressions and evidence.
6. Preserve negative and inconclusive outcomes as first-class data.
7. Add learning only after an exact baseline and an ablation exist.
8. Stop at “candidate” until the warranted next stage succeeds.

If followed, this roadmap turns Atlas into an experimental instrument rather than a graph
demo: it can propose structural hypotheses at scale, determine precisely which ones Lean
supports, record where analogies fail, and hand only the surviving claims to literature and
domain review.
