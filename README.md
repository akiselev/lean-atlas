# lean-atlas

Semantic indexes over elaborated Lean environments — read-only queries over a kernel-checked
corpus of declarations: what depends on what, what is secretly the same shape as what, what
generalizes, what transports, and where the unexplored interfaces between theories lie.

This repository is the Atlas, extracted to stand alone. It contains no theorem prover, no
front-end language, and no physics campaigns — only the instruments that read Lean and the
engine that answers queries over what they read.

The design documents in `docs/` (atlas.md, statement-hash.md, atlas-validation.md,
python-api.md, python-api-reference.md) are the original specification; the code is the
implemented subset of it.

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

3. **Loop** (`crates/atlas-py`, the Python binding). `import atlas` loads a slice **once** and
   answers many queries against the in-memory graph — the CLI re-parses the whole slice per
   call, so scripts belong on the binding.

4. **Reason** (`lean/Atlas/Home.lean`, in the extractor). The carrier-abstraction lattice:
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

## Two things that keep it honest

- **A slice must be closed** under the constants its statements mention, or every query over
  it degrades silently toward "no information". `atlas closure <slice>` (or the MCP
  `atlas_closure` tool) reports the coverage fraction and the missing constants. Below ~95%,
  treat other answers as unsound.
- **The kernel is a soundness oracle, not a value oracle.** The Atlas certifies that a
  statement is *true* and *where it lives*; it cannot say *new*, *interesting*, or *already
  known*. Novelty claims still need a literature step.
