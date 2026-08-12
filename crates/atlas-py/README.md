# atlas — the Atlas core, from Python

One load, many queries.

```python
import atlas as fa

corpus = fa.Corpus.load("/tmp/mathlib-algebra.jsonl")    # ~5 s, once
len(corpus)                                              # 131062
corpus.walls(lens="proof", top=3)                        # [('Eq', 53282), ('Nat', 39552), …]
[n.name for n in corpus.similar("le_trans", top=4)]      # ['LE.le.trans', "ge_trans'", 'Dvd.dvd.trans', …]
corpus.equivalent("le_antisymm", level="exact")          # ['LE.le.antisymm', 'eq_of_le_of_ge']
corpus.transport("le_trans", "dvd_trans", "le_trans")    # Transported(exists=True, name="Dvd.dvd.trans")
```

Every `atlas` CLI invocation re-reads and re-parses the whole slice before answering
anything — measured at 6.0 s per call on the 131,062-declaration algebra slice — and a B4
or B6 query then rebuilds a 14 s index on top of that. A script that asks twenty questions
pays it twenty times. Measured by `tests/smoke.py` on that slice, same twenty questions,
same release binary, both paths asserted to return the same answers:

| | time |
|---|---|
| 20 × `atlas foundations … --lens proof` | **211.2 s** |
| `Corpus.load` + 20 × `.foundations(…)` | **7.8 s** (7.8 s load + 5.7 ms of queries) |

**27.0× end to end, 36,904× per query**, and the twenty-first question is free. Both figures
are from one run on a machine that was simultaneously doing a full `atlas_extract Mathlib`
at 10 GB resident, so both sides are inflated: an earlier session on an idle machine
measured 118.6 s against 4.27 s. What survives the machine is the *ratio* — 25× to 28×
across five runs in two sessions — which is why the end-to-end number is a floor rather than
a headline.

`scripts/atlas-mathlib-experiment.py` runs nine experiments against B1, B2, B4, B5, B6 and
C5 off a single handle in 38 s idle and 57 s under that extraction, of which 24–37 s is the
three index builds. The same nine through the CLI would be nine re-parses and four index
rebuilds.

## From a clean clone

```sh
uv sync                                       # builds the extension into .venv
uv run scripts/atlas-mathlib-experiment.py    # any script; `import atlas` just works
```

`uv sync` reads the repository-root `pyproject.toml`, whose one dependency is this crate
through `[tool.uv.sources]`. It installs into `.venv` and touches nothing outside the
repository — no `pip install --user`, no global site-packages. The first sync fetches
maturin (10 MB) from PyPI to build with and caches it; nothing else is downloaded, because
nothing else is depended on. Because the module is *installed*, `scripts/*.py` say
`import atlas` with no `sys.path` surgery and no `PYTHONPATH`; `uv run` selects that
venv, and so does a plain `. .venv/bin/activate` if you prefer a shell you can poke at.
Both were checked from an `env -i` shell.

maturin's PEP 517 backend builds in release mode by default — verified rather than assumed,
by looking: the artifact lands in `target/release/libatlas.so`. That is worth checking
again if the build backend is ever changed, because a debug engine would not fail, it would
just make every index build unusable. The wheel is `abi3-py310`, so one build serves every
Python ≥ 3.10.

**After editing Rust, `uv run` rebuilds on its own.** That is `[tool.uv] cache-keys` in this
crate's `pyproject.toml` doing its job: uv keys a path dependency on its `pyproject.toml`
alone unless told otherwise, so without those keys an edit to `src/*.rs` — or to the engine
crate this one wraps — leaves `uv run` reinstalling the wheel it built the first time, and
the symptom is the compiler apparently ignoring you. `uv run maturin develop --release -m
crates/atlas-py/Cargo.toml` is the faster loop when iterating hard, but note that the
next `uv run` will replace what it installed with uv's own build.

Without uv at all:

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install maturin && maturin develop --release -m crates/atlas-py/Cargo.toml
```

`cargo build -p atlas-py` also works and is what CI should type-check; it produces a
`cdylib` with undefined Python symbols, which is what an extension module is. The crate
declares `test = false` — an `extension-module` cdylib cannot be linked into a Rust test
binary — so **the tests are Python**:

```sh
cargo build -p atlas --bins --release        # the differential oracle
uv run crates/atlas-py/tests/smoke.py        # --slice defaults to /tmp/mathlib-algebra.jsonl
```

`tests/smoke.py` checks the binding against the CLI on the queries both expose, checks the
properties no oracle can see (the lens separating claim from argument, erasure levels
forming a chain, a class member seeing its siblings, a bad lens raising rather than
guessing), and prints the measurement in the table above.

## What is bound

`research/python-api.md` §1's architecture, and the `fa.Corpus` namespace of §2 — every
query `atlas` itself exposes:

| Python | CLI | |
|---|---|---|
| `Corpus.load(path)` | (the re-parse every invocation pays) | |
| `len(corpus)`, `corpus.names()`, `corpus.get(name)` | `atlas stats` | |
| `corpus.why(source, target, lens=…)` | `atlas why` | B2 |
| `corpus.foundations(name, lens=…)` | `atlas foundations` | B2 |
| `corpus.impact(name, lens=…)` | `atlas impact` | B2 |
| `corpus.walls(lens=…, top=…)` | `atlas walls` | B2 |
| `corpus.honesty(whitelist=…)` | `atlas honesty` | C5 |
| `corpus.skeleton(name, level=…)` | `atlas skeleton` | B4 |
| `corpus.generalize(left, right)` | — | B4 |
| `corpus.similar(name, top=…, level=…, min_retention=…, min_common=…, theorems_only=…)` | `atlas similar` | B4 |
| `corpus.scorer_id(level=…, …)` | `atlas similar`'s `# scorer:` line | B4 |
| `corpus.relations(theorem)`, `.busiest_heads(top=…)`, `.relation_path(…)`, `.logical_stats()` | `atlas relations` | M2 |
| `corpus.similar_brute(name, top=…, level=…)` | `atlas similar --brute` | B4 |
| `corpus.equivalent(name, level=…)` | `atlas equivalent` | B5 |
| `corpus.classes(level=…, theorems_only=…, top=…)` | `atlas classes` | B5 |
| `corpus.dictionary(left, right, per_decl=…, theorems_only=…)` | `atlas dictionary` | B6 |
| `corpus.transport(row_left, row_right, subject, level=…)` | `atlas transport` | B6 |
| `corpus.frontier(min_theory_size=…, top=…, theorems_only=…, exclude=…)` | `atlas frontier` | B6 |

`lens` is `"statement" | "proof" | "both"` (default `"both"`); `level` is one of
`skel::erase::Level`'s five names. The defaults are the engine's own and several are
deliberate: `similar` reports at `carriers`, `equivalent` and `classes` normalize at
`instances` (and `equivalent` refuses `shape`, where "equivalent" would mean "has the same
skeleton" — `similar`'s question), `transport` applies at `carriers`.

Results are `Decl`, `Generalization`, `Neighbour`, `ScoreFactors`, `ScorerId`, `Relation`,
`LogicalStats`, `Row`, `Dictionary`, `Transported` and `FrontierPair` pyclasses with read-only attributes and a `__repr__` worth printing. Type
stubs ship in the wheel (`atlas.pyi`, `py.typed`), and `tests/smoke.py` asserts they
describe the module that actually shipped.

Four deliberate departures from the sketch in §2:

* **`Decl` carries `uses_statement` and `uses_proof`.** They are the row as B1 extracted
  it, and the B1 regression claim in `scripts/atlas-mathlib-experiment.py` — "theorems
  carry proof dependencies" — is about *direct* edges. Answering it through the transitive
  closure instead costs 2.4 ms × 66,700 theorems ≈ 157 s; answering it off the row costs
  1.0 s. Without these two fields the gate would have had to re-read the JSONL in Python,
  which is the thing this package exists to stop.
* **`corpus.get` returns `None` for an unknown name; everything else raises.** "Is it
  here" is `get`'s question, so `None` is its answer. For `foundations`, `why`, `skeleton`,
  `similar` and the rest a missing declaration is a mistake, and they raise
  `UnknownDeclaration` naming it. `impact` deliberately accepts names outside the slice:
  asking what rests on something not extracted is a fair question, and the answer is the
  part of the slice that cites it.
* **`Transported` is one class with `.exists`, not two classes.** §2 sketches a sum type.
  `if t.exists:` is what every caller writes, and a two-state answer does not earn an
  `isinstance` dispatch or a union in the stubs; `.name` is `None` exactly when `.exists`
  is false, and `tests/smoke.py` asserts that rather than documenting it. The refusals —
  the row does not apply, the row is scoped — are exceptions (`NoMatch`, `ScopedRow`),
  because they are not outcomes of a transport, they are reasons there was none.
* **`Neighbour.sources` is a list, not the CLI's `"shape+subterm"` string.** Which of the
  three index sources found a candidate is the field a caller filters on, and grepping a
  joined string for `"shape-subterm"` would also match `"shape"`.

### Errors

`AtlasError` is the base. `FileNotFoundError` for a missing slice, `SliceError` for one
whose rows do not parse (naming the line), `UnknownDeclaration` for a name not in the
slice, `NoStatement` for a declaration whose statement is absent or unparseable (naming the
reason B1 gave), `NotAProposition` for asking equivalence of a definition, `NoMatch` and
`ScopedRow` for the two ways `transport` refuses, `ValueError` for a lens or level that
does not exist (listing the ones that do). None of these are `None` returns: a script that
mistyped a lens should stop, not quietly get `both`.

The index queries raise `NoStatement`, not `UnknownDeclaration`, for a row the slice has
and the index skipped — B1 keeps rows whose statement could not be encoded, the indexes
drop them, and "in the slice, carrying nothing to compare" is a different problem from a
typo.

### The `&mut Arena` problem

`skel::erase::erase` and `skel::lgg::generalize` both take `&mut Arena` — erasure interns
the holed nodes it produces and anti-unification interns its variables, so a *query*
mutates. Python has no `&mut` to hand out.

The arenas therefore live **inside the handle behind a `Mutex`**, and the pyclass is
`frozen`: Python sees a shared handle, Rust does the locking. Consequences, stated rather
than discovered:

* Statement queries from several Python threads serialize on that lock. The graph queries
  touch no arena, take no lock, and run genuinely in parallel — every operation releases
  the GIL (`py.detach`, which is what PyO3 ≥ 0.26 calls `py.allow_threads`).
* The arenas grow monotonically. Erasure is cached per `(term, level)`, so a repeated level
  is free; `generalize` interns fresh variables per call.

### Three layers, built when first asked for

B4's `SkeletonIndex` and B5's `EquivIndex` each parse the slice into an arena of their own,
so the handle carries three lazily-built layers rather than one. Measured on the 131,062-row
algebra slice:

| layer | built by | cost | resident after |
|---|---|---|---|
| graph | `Corpus.load` | 4.8–9.7 s | 723 MB |
| statement arena | `skeleton`, `generalize` | 4.3 s | 851 MB |
| equivalence index (B5) | `equivalent`, `classes` | 6.3 s | 869 MB |
| skeleton index (B4/B6) | `similar`, `dictionary`, `transport`, `frontier` | 13.7 s | 1,095 MB |

The times are from an otherwise idle machine and roughly double under load; the resident
figures are the same to the megabyte every run. All three layers at once is 1,442 MB, and
the handle also retains the slice's 146 MB of source text —
the B4 and B5 builds each parse the JSONL themselves, and re-reading the file instead would
make a handle's answers depend on whether the file changed underneath it. Merging the
layers would mean charging a `skeleton()` caller the 21 s index build, which is the wrong
trade; a session that asks graph questions only builds none of them.

## What is *not* bound, and why

**No Rust behind it yet:**

* **`corpus.home`, `corpus.resolve`** — the residual/home-theory operations of §2. The
  `#atlas_home` side of this is Lean, not Rust: there is nothing in `crates/atlas` to bind.
* **`fa.Session` / `GoalState`** — no Lean REPL subprocess management exists yet. §1 puts
  the process boundary here deliberately; nothing of it is written.
* **`fa.vet`, `fa.certs`, `fa.grade`, `fa.converge`, `fa.Trace`, `fa.ledger`** — Tracks C,
  D and E. No kernels to call, no traces to load, no ledger to write.
* **Campaign journaling, replay, `.cost` on results, `fa.require`** — §3's four principles.
  They are properties of an API with something to journal.
* **NumPy / buffer-protocol interop and `fractions.Fraction` rationals** — §1's zero-copy
  discipline. No matrix or trace crosses the boundary yet, so the package has no NumPy
  dependency at all.

**Bound here, not in `atlas mcp`.** CLAUDE.md §6 wants a new query in five places, and the
fifth is the MCP tool list in `crates/atlas/src/bin/atlas-mcp.rs`. B4, B5 and B6 are absent
from it, so an agent talking to the MCP server can ask `why`/`foundations`/`impact` and not
`similar`/`equivalent`/`dictionary`. That is the remaining half of the same debt this change
paid down.

**Knobs the engine has and this does not expose:**

* `IndexConfig`'s *build-time* knobs — the posting-key size floors, the posting-list cutoff,
  the shape-bucket cap, the candidate budget. They change what the index *contains*, so a
  per-call value would mean a rebuild, and the handle caches one index for every level and
  every threshold. `min_common`, `min_retention` and `level` are per-query and are exposed.
* `equiv::ladder`, `equiv::flex_head_count`, `equiv::rule_index_stats`, and
  `SkeletonIndex::degraded_spines` — the measurement surface behind B5's design notes. Not
  queries, and no script has wanted them.
* `classes(prop_only=…)`. Hardcoded on, because the *only* thing turning it off produces is
  the 1,859-member class of declarations whose type is literally `Type`, which is the
  failure mode CLAUDE.md §5 records rather than a knob anyone wants.

**Doctests in CI against a vendored mini-corpus** — §2's S7 rule applied to the API. The
docstrings here carry no `>>>` examples yet; `tests/smoke.py` is the gate instead, and it
needs a real slice rather than a vendored one.

`Corpus.load` also does not take a corpus *pin* (`"mathlib@pin"`) or carry an environment
fingerprint: it takes a path to a B1 JSONL slice, because that is what the extractor
produces today.

## Fixed, and worth knowing about

**`transport` used to misreport `exists` at `exact`, `presentation` and `shape`.**
`SkeletonIndex::build` ends with `Arena::seal()`, which drops the interner to save a third
of the footprint. Terms built *after* the build therefore no longer shared `TermId`s with
terms built during it, and `SkeletonIndex::name_with_term` is `TermId` equality — so
`corpus.transport("le_trans", "dvd_trans", "le_trans", level="exact")` reported an open
target whose `.image` was byte-identical to `corpus.skeleton("dvd_trans", level="exact")`.
`instances` and `carriers` — the CLI's and this binding's defaults — were right only by
accident, because those erasures are computed lazily and so landed in the same interner
generation as the image. A false "open target" is the worst failure mode B6 has: it
invents research.

`Arena::seal` now marks the arena instead of merely emptying the maps, and the next
`intern` rebuilds them from the arena's own vectors. The pure-query path still pays
nothing; anything that builds a new term pays one `O(nodes)` pass. The gate is a level
sweep in `crates/atlas/examples/dictcheck.rs`, which asserts the transport lands on a
name at *all five* levels — checking only the default was what kept this quiet.
