I think there is a substantially more interesting project hiding inside Lean Atlas than “better dependency visualization.”

I inspected the current `NyxFoundation/lean-atlas` implementation and the old `ferris-howard` Atlas notes. The public implementation is currently a very good substrate: it extracts declaration-level dependencies, distinguishes type from value dependencies, records theorem/definition roles, axioms, source ranges, semantic-confidence metadata, and then Lean Compass essentially performs filtered reachability by removing theorem-proof value edges.    The public README describes essentially the same mission: semantic review and dependency reduction rather than scientific relationship discovery.

That gives us a clean point of departure:

> **Lean Atlas should become a multilayer scientific knowledge graph plus an intervention/discovery engine.**

Not merely “what depends on what?” but:

> What is structurally analogous to what?
> Which assumptions actually matter?
> Which mathematical structures play equivalent roles?
> Which theorem families have conspicuous missing members?
> Where do two theories almost line up but fail?
> Which transformations preserve results?
> Which invariants should exist but have not been stated?
> What new formally checkable conjectures are suggested by the topology of the existing mathematics?

That is much closer to something capable of assisting physics research.

### First: don't compete with dependency-graph projects

This area moved quickly in 2026. TheoremGraph/LeanGraph now extracts 388k+ Lean declarations and 11M+ typed formal edges across 25 projects, and bridges them to informal mathematical literature. ([arXiv][1]) So “extract the Mathlib dependency graph” is increasingly commodity infrastructure.

More importantly, recent network analysis of Mathlib found that naive graph statistics can be actively misleading: the network is heavily shaped by synthesized/infrastructural dependencies, and highly central declarations often reflect Lean machinery rather than mathematical importance. ([arXiv][2])

So I would not spend much effort adding PageRank, betweenness centrality, node2vec, etc. to the existing graph and calling the output insight. Those algorithms become interesting only after we split the graph into semantic layers.

## The graph I would actually build

Think of a declaration as having several simultaneous identities. `SchrodingerEvolution.foo` is a node in a proof graph, but it is also a consumer of assumptions, an instance of some mathematical pattern, a transformation of observables, a theorem about a particular physical regime, a proof strategy, and perhaps an incarnation of a generic statement appearing elsewhere.

I would therefore make the Atlas database multiplex rather than one graph.

| Layer          | Relations                                                            | What we can mine                    |
| -------------- | -------------------------------------------------------------------- | ----------------------------------- |
| Dependency     | statement-use, proof-use, definition-use                             | foundations, impact                 |
| Concept        | declaration ↔ operator/type/class/concept                            | theorem families, latent subjects   |
| Typeclass      | extends, instance, synthesis route                                   | generalization and abstraction      |
| Equivalence    | `Iff`, `Equiv`, `LinearEquiv`, `RingEquiv`, `Iso`, etc.              | reformulations and transports       |
| Rewrite        | simp/rewrite/definitional equality                                   | canonical forms                     |
| Assumption     | theorem ↔ hypotheses / structures                                    | sensitivity and minimal assumptions |
| Proof          | goal state → tactic/premise → goal state                             | proof strategies and motifs         |
| Transformation | specialization, limit, dual, opposite, conjugate, Fourier transform… | mathematical dictionaries           |
| Symmetry       | action, invariant, equivariant map                                   | physics structure                   |
| Regime         | model ↔ parameter/approximation assumptions                          | phase/regime relationships          |
| Provenance     | theorem ↔ paper/docstring/source/confidence                          | epistemic status                    |
| Negative       | attempted analogy/transport → refutation/failure                     | boundaries of analogies             |
| Temporal       | declaration version → declaration version                            | conceptual evolution                |

The key architectural point is that these are not merely different edge colors. Different layers deserve different algorithms.

And Lean can expose substantially more than Lean Atlas currently extracts. In particular, re-elaboration can provide `InfoTree`s containing tactic information, intermediate proof states, local contexts, term information and syntax mappings. ([Lean Language][3]) That gives us a useful division:

**Fast mode:** inspect imported `Environment`/`.olean` data, like Lean Atlas does now.

**Deep mode:** re-elaborate selected source files and extract `InfoTree`, tactic and proof-state information.

The fast database can cover Mathlib/Physlib-scale corpora; deep mode can be run selectively on promising regions.

---

# The algorithms I would add

These are roughly ordered from “I think this will produce useful results fairly quickly” to “research experiment, potentially very interesting.”

### 1. Formal Concept Analysis: build a theorem concept lattice

This may be the most underrated idea here.

Construct a binary relation:

[
\text{declaration} \times \text{features}
]

where features include:

* assumptions/typeclasses;
* operators appearing in the statement;
* structures involved;
* conclusion shape;
* quantifier pattern;
* algebraic properties;
* proof motifs;
* domain metadata.

Then run **Formal Concept Analysis (FCA)**.

Instead of fuzzy clusters, FCA gives an interpretable concept lattice:

> “These 47 theorems all require A+B+C and establish property X.”

and, critically,

> “A+B+C almost always entails X except for this one model where nobody has established X.”

That produces a genuine **missing-cell detector**.

Imagine an Atlas UI resembling a periodic table:

| Model   | positivity | conserved energy | unitary evolution | spectral bound | classical limit |
| ------- | ---------: | ---------------: | ----------------: | -------------: | --------------: |
| Model A |          ✓ |                ✓ |                 ✓ |              ✓ |               ✓ |
| Model B |          ✓ |                ✓ |                 ? |              ✓ |               ✓ |
| Model C |          ✓ |                ✓ |                 ✓ |              ? |               ✓ |

The `?` cells become research candidates.

This is much more interpretable than embedding similarity.

### 2. Assumption-intervention graph

The Ferris notes had a good underlying idea here, but overstated it as finding a theorem's “true home.”

Suppose:

```lean
theorem foo [CommRing R] ...
```

but the proof never needs commutativity.

Systematically perturb the context:

[
CommRing \rightarrow Ring \rightarrow Semiring \rightarrow \ldots
]

Likewise remove ordinary hypotheses individually and in groups.

This gives us an **assumption lattice**.

But there are two importantly different results:

**Proof-minimal context:** the existing proof term still works.

**Theorem-minimal context:** the theorem remains true, potentially with another proof.

Ferris blurred those. We should not.

For each theorem Atlas can perform something analogous to delta debugging:

[
H={h_1,h_2,\ldots,h_n}
]

and search for minimal sufficient subsets.

Successful proof replay gives strong cheap evidence. Failed replay doesn't mean the theorem is false; it becomes a candidate for reproving in the weaker context.

Now imagine aggregating this across physics:

> Which results genuinely require finite dimensionality?

> Which quantum results actually require unitarity rather than merely contractivity?

> Which PDE conclusions depend on smoothness versus only Sobolev regularity?

That is potentially scientifically useful.

### 3. Semantic hypergraphs rather than ordinary graphs

A theorem is naturally more like

[
{A,B,C,D}\rightarrow T
]

than four independent edges.

Model it as a directed hypergraph.

That unlocks:

**minimum hitting sets** — which concepts occur in every route to a result?

**minimal cut sets** — what assumptions sever an entire family of conclusions?

**dominator analysis** — what mathematical object must every derivation pass through?

**alternative derivation analysis** — are two proofs genuinely independent?

This would be a much better definition of “load-bearing mathematics” than ordinary betweenness centrality.

### 4. Equality saturation before similarity

One weakness in nearly every theorem-similarity system is syntactic representation.

These can mean essentially the same thing while having quite different ASTs:

[
a(b+c)=ab+ac
]

and some rearranged, coerced, unfolded equivalent.

Before structural comparison, normalize through an **e-graph/equality-saturation** layer using trusted equivalences:

* definitional reduction;
* `simp`;
* β/η normalization;
* associativity/commutativity normalization where appropriate;
* registered equivalences;
* coercion normalization.

Then compute structural fingerprints over equivalence classes rather than raw expressions.

This would dramatically improve everything downstream.

### 5. Typed higher-order anti-unification

The Ferris Atlas proposed Plotkin-style anti-unification.  The basic idea is worth retaining, but ordinary syntactic LGG is too weak for the ambitious examples in that document.

We need something closer to:

**typed + higher-order + modulo normalization + structure-aware anti-unification.**

For example:

```text
innerProduct x (A x) ≥ 0
```

and

```text
energy φ ≥ 0
```

should be allowed to abstract into something like:

[
Q(x)\geq 0
]

only if their type/operation relationships make the abstraction meaningful.

I would make this a multi-stage candidate pipeline:

[
\text{cheap fingerprint}
\rightarrow
\text{graph-role similarity}
\rightarrow
\text{typed anti-unification}
\rightarrow
\text{formal transport attempt}
]

Embeddings improve recall; symbolic comparison supplies precision.

### 6. Structural-role similarity

This is subtly different from statement similarity.

Two theorems might use completely different vocabulary but occupy the same **position inside their respective theories**.

For example:

```text
Axiom-like foundation
       ↓
canonical construction
       ↓
invariant
       ↓
representation theorem
       ↓
classification
```

Find nodes occupying corresponding positions using:

* Weisfeiler–Lehman graph fingerprints;
* graphlets/motif counts;
* SimRank-like recursive similarity;
* relational WL;
* spectral neighborhood signatures.

Now we're looking for **functional analogy**, not textual analogy.

This is one of the areas where graph representation genuinely has empirical support: recent Lean premise-selection work found heterogeneous structural graph information materially improves retrieval over text-only representations. ([OpenReview][4])

For scientific discovery I'd turn the operation around:

> Don't ask “which existing premise helps prove T?”

Ask:

> “Which theorem elsewhere occupies the role that appears to be missing here?”

That is considerably more interesting.

### 7. Theory-to-theory graph alignment

This is the grown-up version of Ferris's proposed `atlas dictionary`.

Given two theory subgraphs (G_A,G_B), solve for a partial correspondence:

[
f:G_A\rightharpoonup G_B
]

that maximizes preservation of:

* types;
* theorem shapes;
* dependency neighborhoods;
* equivalences;
* algebraic roles;
* proof motifs.

Possible machinery:

* maximum common subgraphs;
* typed graph matching;
* optimal transport;
* Gromov–Wasserstein graph matching;
* seeded alignment when a few known correspondences exist.

Then the interesting output is not the matches.

It is the **residual**:

> A has objects X,Y,Z corresponding to B's X′,Y′,Z′, but A contains operation W for which B has no counterpart.

That is a mechanically generated “missing dictionary entry.”

This is one of the Ferris ideas I would definitely preserve.

### 8. Verified knowledge-graph completion

Once Atlas has multiple edge types, train a relational graph model to predict missing edges:

[
P(\text{relation}(A,B)\mid G)
]

Candidates might include:

```text
is_equivalent_to
generalizes
specializes
preserves
is_invariant_under
is_dual_to
has_limit
has_analogue
implies
```

R-GCN/CompGCN-style models, relational transformers, or even simpler tensor factorization are appropriate candidate generators.

But the key difference from an ordinary KG project is:

> **Every predicted formal relation enters a verification loop.**

Lean proves it → positive edge.

Counterexample/refutation → negative edge.

Unknown → conjectural edge.

That negative graph is extremely valuable. Most knowledge graphs throw failed predictions away. We should retain them because they map **where analogies stop working**.

### 9. Proof-state dynamics

Final proof terms are useful but throw away a lot of the human/prover strategy.

InfoTrees let us reconstruct sequences roughly resembling:

[
S_0
\xrightarrow{\text{rewrite}}
S_1
\xrightarrow{\text{introduce invariant}}
S_2
\xrightarrow{\text{bound}}
S_3
\xrightarrow{\text{linear arithmetic}}
\checkmark
]

Lean explicitly records tactic information, terms and active proof-state metadata in InfoTrees during elaboration. ([Lean Language][3])

Now perform sequence/motif mining.

We might discover recurring strategies such as:

```text
construct invariant
→ establish positivity
→ prove monotonicity
→ obtain bound
```

across apparently unrelated domains.

This gets much closer to “method transfer.”

---

# The physics-specific layer is where this gets particularly interesting

The generic Atlas should understand mathematics. A Physics Atlas plugin should understand additional relations that physicists actually care about.

### Symmetry → invariant → conservation graph

Explicitly recognize:

[
\text{GroupAction}
\rightarrow
\text{Equivariance}
\rightarrow
\text{Invariant}
\rightarrow
\text{ConservedQuantity}
]

Then mine missing links.

If a model has a formally registered continuous symmetry but no associated invariant/conservation result, flag it.

Conversely:

> Here is a conserved quantity whose corresponding symmetry isn't represented.

Once enough mechanics/QFT machinery exists, this becomes a Noether-structure miner.

The important point isn't automatically proving Noether's theorem again. It is looking for **incomplete instances of a known structural correspondence**.

### Limit/deformation graph

Physics is full of theories connected by limiting processes:

[
\hbar\rightarrow0
]

[
c\rightarrow\infty
]

[
N\rightarrow\infty
]

[
a_{\text{lattice}}\rightarrow0
]

[
g\rightarrow0
]

Atlas should make `limit_of`, `perturbation_of`, `deformation_of`, and `special_case_of` first-class relations.

Then we can build a **theory genealogy**:

```text
relativistic theory
       │ c → ∞
       ▼
classical theory
       │ small oscillation
       ▼
linearized theory
```

and ask whether theorems commute with these transformations.

A fascinating query becomes:

> T holds in model A and the A→B limit is established. Where is the corresponding limiting theorem in B?

### Assumption phase diagrams

Represent physical regimes explicitly:

```text
weak coupling
high temperature
finite volume
nonrelativistic
adiabatic
equilibrium
translation invariant
...
```

Then each theorem occupies a region of assumption space.

Atlas can draw a literal **mathematical phase diagram of theorem validity**.

Adjacent regions where the theorem's status changes are particularly interesting because they identify which idealization creates the result.

### Dimensional-analysis miner

If dimensions are encoded either in Lean types or in Atlas metadata, build the dimension exponent matrix.

For (n) physical quantities with (k) fundamental dimensions:

[
D\in\mathbb Z^{k\times n}
]

then

[
\ker D
]

gives candidate dimensionless combinations.

That's Buckingham-(\Pi) analysis, but now tied directly to the formal model.

Atlas could automatically say:

> These 9 observables admit 4 independent dimensionless combinations.

And then cross-reference those combinations against:

* invariants;
* scaling limits;
* empirical/simulation data;
* existing theorem families.

That's one of the clearest routes from formal metadata toward actual physics hypothesis generation.

### Observable/constraint hypergraph

Treat equations as hyperedges among physical quantities.

For example:

[
F(q_1,q_2,q_3,\theta)=0
]

becomes a constraint relating observables and parameters.

Then use:

* Gröbner elimination for polynomial systems;
* linear elimination;
* symbolic solving;
* interval methods;
* SMT;
* differential elimination where applicable;

to eliminate latent quantities and produce relations directly among observables.

The generated relation can then be stated in Lean and verified from the original model.

Now Atlas has generated something with potential empirical meaning:

> Given assumptions A/B/C, observables (X,Y,Z) must satisfy relation (R).

That is much more scientifically significant than theorem similarity.

### Renormalization/scaling motifs

Make transformations themselves nodes.

Then detect patterns like:

[
T_\lambda(x)
]

with:

* fixed points;
* invariants;
* monotones;
* relevant/irrelevant directions;
* asymptotic behavior.

Even outside literal RG, the same mathematical pattern occurs in dynamical systems and iterative maps.

Atlas could identify “RG-shaped” structures elsewhere.

### Universal energy/entropy/Lyapunov structures

Search for proof motifs:

[
E(x)\ge0
]

[
\frac{dE}{dt}\le0
]

[
E(t)\le E(0)
]

and their discrete analogues.

Then align these across:

* PDEs;
* thermodynamics;
* Markov processes;
* quantum information;
* control theory;
* optimization.

There are potentially useful mathematical transfers hiding here because the vocabulary differs greatly while the formal structure can be strikingly similar.

---

# One especially interesting research direction: mathematics as compression

This is more speculative, but I would test it.

Use **Minimum Description Length / graph grammar induction**.

Suppose Atlas encounters 400 proofs sharing some elaborate repeated structure. Introducing abstraction (A) lets them all be described much more compactly.

Then:

[
DL(G\mid A)+DL(A)\ll DL(G)
]

is evidence that (A) captures real recurring structure.

This gives us an algorithmic way to ask:

> “What concept should exist?”

rather than merely:

> “What theorem should exist?”

The system could propose:

```text
There appears to be an unnamed structure consisting of
  operation f
  invariant I
  compatibility law P
because introducing it collapses 183 near-duplicate theorem patterns.
```

That is automated abstraction discovery.

For a research system, I think this could ultimately be more valuable than conjecture generation.

---

## Another strange-but-promising one: topological data analysis

Take an increasingly permissive theorem-similarity relation and form a filtration:

[
G_{\epsilon_1}\subseteq G_{\epsilon_2}\subseteq\dots
]

Compute persistent components/cycles.

Stable holes could indicate families of mathematics that are almost connected except for missing correspondences.

I would regard this strictly as exploratory signal — a persistent homology class in theorem space is not automatically mathematically meaningful — but it could reveal multi-scale organization that ordinary clustering misses.

Worth experimenting with once we have good semantic distances.

---

# What from `ferris-howard` survives scrutiny?

Quite a lot of the high-level direction does.

The useful ideas are the equivalence graph, systematic generalization attempts, theory dictionaries, negative-space/frontier detection, proof-shape retrieval, and especially recording failed transports.  The old validation document also had a good methodological instinct: blind rediscovery benchmarks plus explicit negative controls are exactly how we should validate this kind of system.

I would discard or heavily modify three claims.

First, **“true home”** becomes “proof-minimal assumptions,” unless Atlas actually reproves the theorem in the weakened setting.

Second, ordinary **anti-unification won't magically rediscover Hilbert–Pólya**. That example depends on choosing a fairly sophisticated abstraction of what the two statements mean. If we encode that abstraction into the benchmark, we risk putting the answer into the representation.

Third, **high similarity + no citation does not equal research frontier**. It can mean duplicated formalization, generic shared machinery, bad representation, or a completely false analogy.

The proper frontier score should look more like:

[
F=
\frac{
S_\text{symbolic}
S_\text{structural}
N_\text{domain}
I_\text{information}
}{
1+C_\text{existing}+C_\text{verification}
}
]

with separate epistemic status:

```text
PROVEN
REFUTED
OPEN
UNTESTED
```

rather than one magic numerical “discovery score.”

---

# The visualizations I would build

The existing node-link graph should become only one view.

A **Theory Alignment View** would put two theories on opposite sides and show discovered correspondences between them. Proven correspondences are solid; conjectural are dashed; refuted correspondences remain visible in red. Unmatched nodes form the visually obvious research frontier.

A **Theorem Periodic Table** would show models/theories on one axis and structural properties on the other. Empty cells become candidate research questions.

A **Concept Lattice View** would expose FCA's hierarchy of assumptions and conclusions. Clicking a concept would answer “what exactly do these theorems have in common?”

An **Assumption Phase Diagram** would let you move through increasingly strong physical assumptions and see when results appear/disappear.

A **Proof Strategy Map** would cluster proof-state trajectories rather than declarations. You could literally ask “show me other arguments that begin like this proof but then take a different route.”

And a **Discovery Frontier View** could plot structural familiarity against domain distance and verification status. The interesting objects are often not nearest neighbors; they're structurally strong matches separated by a large conceptual distance.

---

# What I would build next

1. **Atlas Extraction v2.** Preserve the existing extractor, but export normalized expression structure, precise occurrence roles, typeclass/instance relations, coercions, structure inheritance, equivalences, rewrites and generated-vs-explicit provenance. Add optional InfoTree extraction as a separate “deep” pass. Lean's InfoTree architecture is explicitly intended to preserve elaboration-time information such as proof states and term metadata, so this doesn't require abusing proof terms. ([Lean Language][3])

2. **Semantic Graph v1.** Add the concept hypergraph, infrastructure-stripped mathematical graph, equivalence graph and assumption graph. Then implement FCA, dominators/min-cuts, semantic community detection and assumption ablation. These give us interpretable discoveries before introducing ML.

3. **Analogy Engine.** Equality saturation → fingerprints → typed anti-unification → structural-role matching → theory graph alignment. Crucially, build the negative-edge store and verification harness at the same time.

4. **Physics Discovery plugins.** Start with symmetry/invariants, assumptions/regimes, limits/deformations and dimensions. These relations are much closer to physicists' conceptual vocabulary than Lean's declaration taxonomy.

5. **Active Discovery Loop.** Candidate generators compete to suggest relations. Atlas selects candidates based on novelty and expected information gain, attempts proof/refutation, records the result, and updates the models. This turns Atlas from a static index into an experimental system.

My first three actual experiments would be **FCA/missing theorem families**, **assumption intervention**, and **cross-theory structural alignment**. They are interpretable, measurable, kernel-checkable, and much harder for an LLM to fake than vague semantic similarity.

The larger scientific vision would then be:

[
\boxed{
\text{Formal corpus}
\rightarrow
\text{structural hypotheses}
\rightarrow
\text{mathematical verification}
\rightarrow
\text{physical predictions}
\rightarrow
\text{simulation/experiment}
}
]

Lean metadata by itself is unlikely to discover a new empirical law of nature. What it can plausibly do is something narrower but still powerful: **systematically expose mathematical regularities, missing correspondences, unnecessary assumptions, invariant structures, unexplored regimes, and formally implied observable relations at a scale no individual physicist can inspect manually.** That is a credible route from proof-assistant metadata to scientific exploration.

And I think that is a much better North Star for Lean Atlas than turning it into another theorem search engine.
