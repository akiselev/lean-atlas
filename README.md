# lean-atlas

> **Experimental.** Extraction schemas, query semantics, and research-oriented ranking methods may change while the implementation is validated on larger Lean corpora.

`lean-atlas` builds semantic indexes over elaborated Lean environments. It extracts kernel-checked declarations and supports read-only queries over dependency structure, statement equivalence, generalization, transport, theory boundaries, and related structural relationships.

This repository contains the standalone Atlas components: a Lean extractor, a Rust query engine, and Python bindings. It does not include a theorem prover, a separate front-end language, or application-specific physics code.

The design documents in `docs/` (`atlas.md`, `statement-hash.md`, `atlas-validation.md`, `python-api.md`, `python-api-reference.md`, `intuition-engine.md`) describe the original specification and current research design. The code implements a subset of that design.

## Pipeline

```
plain Lean  →  lake build  →  atlas_extract  →  JSONL  →  Rust engine (crates/atlas) / Python (crates/atlas-py)
```

1. **Extract** (`lean/`, the `atlasExtract` package). Imports **only `Lean`**, so it compiles under any toolchain. `lake exe atlas_extract <Module> > slice.jsonl` writes one JSONL row per declaration: name, kind, module, canonical statement encoding (`atlas-stmt-v1`), and used constants split into `uses_statement` (dependencies of the statement) and `uses_proof` (dependencies of the proof).

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

   Queries take a `--lens statement|proof|both` to select statement dependencies, proof dependencies, or both. Skeleton queries also take `--level exact|presentation|instances|carriers|shape` to control erasure depth.

3. **Intuit** (`crates/atlas/src/intuition*.rs`, `atlas-intuition`). The intuition engine evaluates changes of mathematical representation as search actions. It extracts auditable structural features from elaborated statement ASTs, scores a catalogue of methods and transforms, searches bounded viewpoint graphs, mines formal concepts in declaration × affordance data, and records failed attempts as negative search-policy evidence rather than Lean facts.

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

   - **affordances**: structure visible in the elaborated statement, including linear/operator, spectral, geometric, probabilistic, variational, symmetry, and scaling features;
   - **methods/viewpoint transforms**: transformations such as spectralize, geometrize, algebraize, probabilize, variationalize, generating-function, Fourier transform, dualize, tropicalize, finite analogue, discretize, and continuum limit;
   - **representation breadth**: the number of method families that become structurally plausible in a representation;
   - **viewpoint graphs**: bounded quality-diversity search over sequences of representation changes, retaining proof obligations and known information losses along each path;
   - **Pareto taste**: a non-dominated frontier over compatibility, domain distance, bridge value, novelty, breadth gain, and experience rather than a single scalar ranking;
   - **bridge proposals**: directed proposals that a method fitting one theory may expose structure useful in another; these are search hypotheses, not claims that the theories are analogous;
   - **formal concepts and corpus implications**: exact regularities in the extracted affordance context, treated as corpus hypotheses rather than mathematical theorems;
   - **missing structural cells**: common affordances absent from a named theory, considered only when independent neighborhood/alignment evidence supports the comparison;
   - **negative experience**: optional JSONL records of succeeded, failed, refuted, or blocked research actions; failures affect ranking but do not remove routes;
   - **historical/counterfactual benchmarks**: frozen answer-key cases scored by top-k hit rate and MRR, meaningful only when the evaluated corpus predates the hidden method;
   - **dream motifs**: recurrent ordered method transitions used as input to later MDL/grammar-induction experiments.

   See `docs/intuition-engine.md` for the scoring contract and epistemic boundaries.

4. **Loop** (`crates/atlas-py`, the Python binding). `import atlas` loads a slice once and answers repeated queries against the in-memory graph. The CLI reparses a slice per invocation, so long-running scripts should use the binding.

5. **Reason** (`lean/Atlas/Home.lean`, in the extractor). The carrier-abstraction lattice: `#atlas_home <decl>` reports the weakest instance binders reached by a declaration's statement and proof, while `#atlas_home_confirm` / `#atlas_home_attempt` submit weakening candidates to the kernel.

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

`scripts/` holds the research harness for corpus building, slice closure, generalization rounds, and novelty screening. These are historical experiments; several reference absolute `/tmp` paths or corpora that must be re-extracted before use.

## Interpretation and validity

- **Slices must be closed** under constants referenced by their statements. `atlas closure <slice>` (or the MCP `atlas_closure` tool) reports coverage and missing constants. Below roughly 95% coverage, other query results should not be treated as reliable.
- **Kernel checking establishes validity, not research value.** Atlas can establish that a statement is accepted by Lean and analyze where it lives in the dependency structure; novelty or significance requires separate evidence.
- **Intuition proposals are search actions, not mathematical facts.** Affordance extraction comes from the elaborated term; method scoring is a heuristic policy over that evidence. A high score means the route ranks highly under that policy, not that the resulting claim is true or novel.
- **Corpus implications are not theorem implications.** FCA closes over the contents of the extracted library. Any promoted implication needs held-out validation and, where meaningful, formal proof or refutation.
