# lean-atlas

Semantic indexes over elaborated Lean environments — read-only queries over a kernel-checked
corpus of declarations: what depends on what, what is secretly the same shape as what, what
generalizes, what transports, where the unexplored interfaces between theories lie, and
which changes of mathematical viewpoint may expose useful structure.

This repository is the Atlas, extracted to stand alone. It contains no theorem prover, no
front-end language, and no physics campaigns — only the instruments that read Lean and the
engine that answers queries over what they read.

The design documents in `docs/` (atlas.md, statement-hash.md, atlas-validation.md,
python-api.md, python-api-reference.md, intuition-engine.md) are the original specification
and the current research design; the code is the implemented subset of it.

## The pipeline

```
plain Lean  →  lake build  →  atlas_extract  →  JSONL  →  Rust engine (crates/atlas) / Python (crates/atlas-py)
```

1. **Extract** (`lean/`, the `atlasExtract` package). Imports **only `Lean`**, so it compiles
   under any toolchain. `lake exe atlas_extract <Module> > slice.jsonl` writes one JSONL row
   per declaration: name, kind, module, canonical statement encoding (`atlas-stmt-v1`), and
   the used constants, split into `uses_statement` (what the claim rests on) and `uses_proof`
   (what the argument rests on).

2. **Query** (`crates/atlas`, the Rust engine). `atlas <query> <slice.jsonl> …`:

   | query | answer |
   |---|---|
   | `why A B` | shortest citation chain from A down to B |
   | `foundations A` | everything A transitively rests on |
   | `impact A` | everything that transitively rests on A |
   | `walls` | declarations ranked by how many others cite them |
   | `honesty [axiom…]` | declarations resting on `sorryAx` or an axiom outside the whitelist |
   | `equivalent A` / `classes` | statement-equivalence classes |
   | `relations` | proved Iff/implication edges |
   | `dictionary A B` | skeleton-matched rows between two theory prefixes |
   | `transport l r s` | apply a dictionary row to a statement |
   | `frontier` | theory pairs that look alike and do not cite each other |
   | `similar A` | statements that anti-unify with A, ranked |
   | `skeleton A` | the rendered erasure of one statement |
   | `stats` | slice size and how much encodes |

   Queries take a `--lens statement|proof|both` (what the *claim* rests on vs. what the
   *argument* rests on) and, for the skeleton queries, a `--level
   exact|presentation|instances|carriers|shape` erasure depth.

3. **Intuit** (`crates/atlas/src/intuition*.rs`, `atlas-intuition`). The intuition engine
   treats mathematical intuition as choosing productive changes of representation. It
   extracts auditable affordances from the elaborated statement AST, scores a bootstrap
   catalogue of methods/transforms, deliberately diversifies research beams, searches
   multi-step viewpoint graphs, mines formal concepts in declaration × affordance data, and
   keeps failed attempts as negative search-policy evidence rather than Lean facts.

   ```sh
   cargo run -p atlas --bin atlas-intuition -- profile slice.jsonl My.Theorem
   cargo run -p atlas --bin atlas-intuition -- rank slice.jsonl My.Theorem --top 12
   cargo run -p atlas --bin atlas-intuition -- pareto slice.jsonl My.Theorem
   cargo run -p atlas --bin atlas-intuition -- refract slice.jsonl My.Theorem
   cargo run -p atlas --bin atlas-intuition -- explore slice.jsonl My.Theorem --depth 3 --beam 12
   cargo run -p atlas --bin atlas-intuition -- auxiliary slice.jsonl My.Theorem
   cargo run -p atlas --bin atlas-intuition -- bridge slice.jsonl Algebra Geometry
   cargo run -p atlas --bin atlas-intuition -- toy-worlds slice.jsonl My.Theorem
   cargo run -p atlas --bin atlas-intuition -- concepts slice.jsonl Physics --top 100
   cargo run -p atlas --bin atlas-intuition -- implications slice.jsonl Physics --min-support 10
   cargo run -p atlas --bin atlas-intuition -- missing-cells slice.jsonl Classical Quantum
   cargo run -p atlas --bin atlas-intuition -- benchmark slice.jsonl historical-cases.jsonl
   cargo run -p atlas --bin atlas-intuition -- dream slice.jsonl --experience attempts.jsonl
   ```

   The main objects are:

   - **affordances** — structure visible in the elaborated statement: linear/operator,
     spectral, geometric, probabilistic, variational, symmetry, scaling, etc.;
   - **methods/viewpoint transforms** — e.g. spectralize, geometrize, algebraize,
     probabilize, variationalize, generating-function, Fourier transform, dualize,
     tropicalize, finite analogue, discretize, continuum limit;
   - **representation breadth** — how many mature method families become structurally
     plausible in a representation; proposals are rewarded when they enlarge that set;
   - **viewpoint graphs** — bounded quality-diversity search over sequences of representation
     changes; every path accumulates the proposed method's proof obligations and known
     information losses;
   - **Pareto taste** — a non-dominated frontier over compatibility, domain distance, bridge
     value, novelty, breadth gain, and experience, so one arbitrary scalar score is not the
     only research-policy view;
   - **bridge proposals** — a directed question of the form “method M fits theory A and
     exposes structure already useful in theory B”; this is not a claim that A and B are
     analogous;
   - **formal concepts and corpus implications** — exact regularities in the *extracted
     affordance context*. They are hypotheses about the corpus, not mathematical theorems;
   - **missing structural cells** — globally common affordances absent from a named theory;
     useful only when independent neighborhood/alignment evidence says the role should be
     occupied;
   - **negative experience** — optional JSONL records of succeeded/failed/refuted/blocked
     research actions; failures penalize but never silently delete a route;
   - **historical/counterfactual benchmarks** — frozen answer-key cases scored by top-k hit
     rate and MRR; meaningful only when the corpus itself is frozen before the hidden method;
   - **dream motifs** — recurrent ordered method transitions, a first substrate for later
     MDL/grammar induction and method invention.

   See `docs/intuition-engine.md` for the scoring contract and epistemic boundaries.

4. **Loop** (`crates/atlas-py`, the Python binding). `import atlas` loads a slice **once** and
   answers many queries against the in-memory graph — the CLI re-parses the whole slice per
   call, so scripts belong on the binding.

5. **Reason** (`lean/Atlas/Home.lean`, in the extractor). The carrier-abstraction lattice:
   `#atlas_home <decl>` reports where a declaration *actually* lives (the weakest instance
   binders its statement and proof reach), and `#atlas_home_confirm` / `#atlas_home_attempt`
   put weakening candidates in front of the kernel.

## Build and test

```sh
# Rust engine + tests (the golden ranking test needs ATLAS_SLICE to a JSONL slice, else skips)
cargo build
cargo test

# the extractor
cd lean && lake build

# Python binding + smoke test (differential against the CLI)
uv sync
uv run crates/atlas-py/tests/smoke.py --slice /path/to/slice.jsonl
```

`scripts/` holds the research harness (corpus building, slice closure, generalization
rounds, novelty screening). They are historical experiments: several reference absolute
paths to `/tmp` slices or corpora that must be re-extracted before they run.

## Things that keep it honest

- **A slice must be closed** under the constants its statements mention, or every query over
  it degrades silently toward "no information". `atlas closure <slice>` (or the MCP
  `atlas_closure` tool) reports the coverage fraction and the missing constants. Below ~95%,
  treat other answers as unsound.
- **The kernel is a soundness oracle, not a value oracle.** The Atlas certifies that a
  statement is *true* and *where it lives*; it cannot say *new*, *interesting*, or *already
  known*. Novelty claims still need a literature step.
- **An intuition proposal is a research action, not a mathematical fact.** Affordance
  extraction is auditable evidence from the elaborated term; method scoring is a heuristic
  policy over that evidence. A high score means “worth trying under this policy,” never
  “likely true” or “historically novel.”
- **Corpus implications are not theorem implications.** FCA closes over what the extracted
  library happens to contain. Any promoted implication needs held-out validation and, when
  meaningful, a formal proof/refutation step.
