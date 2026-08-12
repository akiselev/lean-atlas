# atlas Python API Reference (Static Surface), v0.1-draft

**Scope:** the static API — everything defined by the package itself, independent of any loaded corpus. (Dynamically materialized namespaces — declaration accessors, per-library attribute trees generated at `Corpus.load` — are governed by §9's protocol contracts but not enumerated here.) Signatures are given in `.pyi` stub style; all public objects ship these stubs plus doctests. §10 is the research deliverable: the capability classes that are *structurally impractical* over a CLI+JSON boundary, which are where this API earns its existence.

---

## 1. Top level

```python
atlas.require(spec: str) -> None            # version gate: fa.require(">=0.3,<0.5"); raises VersionConflict
atlas.config(**kw) -> Config                # process-wide: cache dirs, lean toolchain pin, worker counts
atlas.campaign(name: str, *, resume: bool = True) -> Campaign   # context manager; §8
atlas.replay(journal: Path | Journal, *, strict: bool = True) -> ReplayReport
atlas.__version__: str
atlas.__corpus_abi__: int                   # bumped when index formats change; pinned into snapshots
```

## 2. Core value types

```python
class Decl:        # a declaration handle (theorem/def/instance); cheap, hashable, picklable (§9)
    name: str; kind: DeclKind; stmt: Stmt
    deps(self, *, transitive: bool = False) -> DeclSet
    dossier(self) -> Dossier | None            # validity dossier if one exists
    cost(self) -> Cost | None                  # S5 ledger entry if instrumented

class Stmt:        # a statement (elaborated, hash-carrying)
    hash: StmtHash; frozen: bool
    skeleton(self) -> Skeleton
    render(self, target: Literal["lang","lean","latex","english"]) -> str   # emit backends, in-process
    instantiate(self, **subst) -> Stmt

class Term:        # elaborated term handle; DAG view
    node_count: int
    walk(self, visitor: TermVisitor) -> None   # §10.2 — visitor callback into Rust traversal
    canonical(self, *, level: CanonLevel = CanonLevel.ALPHA) -> Term      # X6 layers
    to_dot(self) -> str

class GoalState:   # immutable, forkable proof state (see Session)
    goals: tuple[Goal, ...]; parent: GoalState | None
    apply(self, tactic: str, *, timeout_s: float | None = None) -> GoalState   # returns NEW state
    local_context(self) -> Sequence[Hyp]
    def __hash__(self): ...                    # canonical-form hash → proof-cache key (S1)

class RatMatrix:   # exact rational matrix; lossless bridge
    @staticmethod
    def from_fractions(rows: Sequence[Sequence[Fraction]]) -> RatMatrix
    @staticmethod
    def from_numpy(a: np.ndarray, *, max_denominator: int | None = None) -> RatMatrix
    def to_numpy(self) -> np.ndarray           # float view, lossy, for plotting only (warns)
    shape: tuple[int, int]

class Interval:    # certified enclosure
    lo: Fraction; hi: Fraction
    def __contains__(self, x) -> bool
    width: Fraction

class Budget:      # resource envelope for any search/prove call
    kernel_s: float | None; search_s: float | None; tokens: int | None; nodes: int | None

class Cost:        # what actually got spent; attached to every result object as .cost
    kernel_s: float; search_s: float; cache_hits: int; cache_misses: int
    def __add__(self, other: Cost) -> Cost     # campaign roll-up
```

## 3. `Corpus` — environments as values

```python
class Corpus:
    @staticmethod
    def load(pin: str, *, overlays: Sequence[Path] = ()) -> Corpus    # "mathlib@<rev>"; fingerprinted
    fingerprint: EnvFingerprint
    decls: DeclIndex                            # mapping-protocol + query methods
    graph(self, *, kind: Literal["deps","defs","instances"]) -> GraphHandle

    # --- copy-on-write environment algebra (§10.4) ---
    def without(self, *decls: Decl | str) -> Corpus       # deletion-benchmark primitive; O(1) layer
    def overlay(self, patch: Patch) -> Corpus             # speculative additions
    def diff(self, other: Corpus) -> EnvDiff

    # --- Atlas queries (all return .cost-carrying objects) ---
    def similar(self, q: Stmt | Goal | Term, *, index: IndexKind = "skeleton",
                k: int = 10, scorer: Scorer | None = None) -> list[Match]     # scorer: §10.2
    def home(self, s: Stmt) -> HomeReport       # .minimal_hyps, .deletable, .interp_position
    def transport(self, s: Stmt, *, dictionary: str | Dictionary) -> TransportResult
    def frontier(self, a: Cluster, b: Cluster) -> FrontierReport
    def resolve(self, r: Residual) -> Recognized | Attributed | Spectrum | Irreducible
    def envelope(self, system: SystemClass, observables: Sequence[Obs],
                 budget: ErrorBudget, *, rank_by: Literal["grade","cost"] = "grade") -> EnvelopeResult

    def elaborate_downstream(self, of: Decl) -> ElabReport   # .failures = stuck-goal stream (X1)
```

`DeclIndex` supports mapping protocol (`corpus.decls["Nat.add_comm"]`), rich queries (`.by_skeleton(sk)`, `.by_attr("rigor", "certified")`), and Arrow export (`.to_arrow()`, §10.6).

## 4. `Session` and proving

```python
class Session:     # a managed Lean REPL subprocess bound to a Corpus
    def __init__(self, corpus: Corpus, *, workers: int = 1): ...
    def __enter__(self) -> Session; def __exit__(...) -> None
    def goal(self, s: Stmt) -> GoalState
    def elaborate(self, src: str, *, lang: Literal["lang","lean"] = "lang") -> ElabResult
    def check(self, decls: Sequence[Decl] | Path) -> CheckReport   # fresh-env; H-audit included
    def prove(self, st: GoalState, *, budget: Budget,
              portfolio: Sequence[str] | TacticPolicy = DEFAULT_PORTFOLIO,   # policy: §10.2
              on_progress: ProgressCb | None = None,                          # §10.5
              cancel: CancelToken | None = None) -> Proof                     # raises ProofFailed
    def prove_many(self, sts: Sequence[GoalState], *, budget: Budget,
                   dedupe: bool = True) -> list[Proof | ProofFailed]          # shared-cache parallel (§10.3)

class SessionPool:                                # N subprocesses, one Corpus, work-stealing
    def __init__(self, corpus: Corpus, n: int): ...
    def map(self, fn: Callable[[Session], T], items: Iterable) -> Iterator[T]
```

## 5. Validity: `fa.vet`

```python
def vet(s: Stmt, *, probes: Sequence[ProbeId] = TIER_STATEMENT) -> Dossier
class Dossier:
    score: float; probes: Mapping[ProbeId, ProbeResult]; assumption_ledger: list[Assumption]
    def blockers(self) -> list[ProbeResult]

def mutate(s: Stmt, *, operators: Sequence[MutOp] = STANDARD_OPS,
           custom: Sequence[MutationOperator] = ()) -> Iterator[Mutant]       # custom: §10.2
class Mutant:
    patch: Patch
    def fate(self, session: Session, *, budget: Budget) -> Literal["killed","refuted","survived"]

def shrink(x: Statement | Counterexample, *, oracle: Oracle,
           order: ShrinkOrder | None = None) -> ShrinkResult                  # ddmin; order: §10.2
def bracket(s: Stmt, *, session: Session, budget: Budget) -> StatementBracket # .width, .sharp
```

## 6. Certificates, grading, mining, convergence

```python
fa.certs.ldlt(M: RatMatrix) -> LdltCert                    # .check() -> KernelReady
fa.certs.interval_eval(e: Expr, subst: Mapping[str, Interval]) -> Interval
fa.certs.exhaust(space: FiniteSpace, pred: DecidablePred, *, cancel=None) -> ExhaustCert

fa.grade(evaluator: AnytimeFn, *, eps_ladder=DEFAULT_LADDER) -> Grade   # POLY/EXP/TOWER/VOID + curve
fa.mine(d: Decl, *, interpretation: Literal["dialectica","monotone"]) -> MinedBound   # MN-stage gated
fa.converge.watch(loop_id: str, potential: float) -> None   # feed; stamps queried via
fa.converge.stamp(loop_id: str) -> LoopStamp                # CONVERGING(rate)|PLATEAUED|OSCILLATING|DIVERGING
```

## 7. Debugging: `fa.Trace`

```python
class Trace:
    @staticmethod
    def load(p: Path) -> Trace
    frames: Sequence[Frame]
    def blame(self, *, method: Literal["scan","mincut"] = "mincut") -> BlameReport   # X8
class Frame:
    span: Span; values: Mapping[str, Fraction]; enclosures: Mapping[str, Interval]
    def to_lean_context(self, s: Session) -> GoalState      # REPL-is-the-debugger
    def check_watch(self, pred: str) -> bool | Interval
```

## 8. Campaigns, ledger, experiments

```python
class Campaign:    # context manager; auto-journals every API call in scope
    name: str; journal: Journal
    def note(self, msg: str, **kv) -> None                  # ledger line
    def gate(self, gate_id: str, verdict: str, evidence: str) -> None
    cost: Cost                                              # live roll-up

fa.experiments.frozen_list(name: str) -> FrozenList         # pre-registered; hash-checked
fa.experiments.statement_match(cands: Sequence[Stmt], target: Stmt) -> MatchScore
fa.experiments.summarize(rs, *, baseline: str) -> Table     # to_arrow()/to_pandas()
fa.experiments.seed(n: int) -> None                          # all stochastic ops derive from this
```

## 9. Exceptions and protocol integration

Exception hierarchy — every exception carries the diagnostics payload where applicable:
```python
AtlasError
 ├─ ProofFailed(goal_state, candidates, instance_trace, falsification)  # .falsification.status/.witness
 ├─ FrozenStatementError(h_rule="H2")        # raised by ANY op that would mutate a frozen stmt
 ├─ RegimeViolation(regime, input)           # L-REGIME at the API layer
 ├─ BudgetExceeded(spent: Cost, budget)      # partial results attached where safe
 ├─ EnvConflict(diff: EnvDiff)               # overlay/merge collisions
 └─ VersionConflict / KernelUnavailable / ReplayDivergence(step, expected, got)
```
Protocols: all result collections are sized iterables; `Match`/`Mutant` sort by score; handles pickle **as journal references** (unpickling re-resolves against the pinned corpus — resumable scripts, §10.7); `RatMatrix` implements the buffer protocol; `Table.to_pandas()`/`.to_arrow()` everywhere tabular; context managers own every process/handle with deterministic teardown.

---

## 10. The CLI-impractical surface (the research section)

The analysis question: which capability classes cannot be sensibly delivered over a process-per-call, serialize-everything boundary? Seven classes; each is a place this API is not a convenience but a *capability expansion*.

**10.1 · Persistent state as values.** `GoalState` forking, `Corpus.without/overlay`, session pools: a CLI must re-serialize or re-derive state per call — for a 10⁵-declaration environment or a deep proof state, that's either impossible or dominates cost. In-process handles make *state-space search over environments* (the deletion benchmark, speculative what-if stacks, X1's per-lemma broken worlds) O(1)-per-branch copy-on-write operations. Whole experiment families exist only on this side of the boundary.

**10.2 · Inversion of control: Python callbacks inside Rust engines.** `Scorer` (custom similarity scoring inside `similar`'s ranking loop), `TacticPolicy` (a Python object choosing the next tactic per state — bandit/learned policies driving Rust search), `MutationOperator`/`ShrinkOrder` (domain-specific mutants and shrink strategies), `TermVisitor` (analyses over term DAGs without materializing them). A CLI cannot call *back into the agent's code mid-algorithm*; this is the difference between configuring a search and *authoring* one. Design note: callbacks are invoked with the GIL re-acquired per call and are documented as the performance tax they are — hot loops should graduate winning policies into Rust, and the API is the prototyping bench that decides which deserve it.

**10.3 · Shared-handle concurrency with cross-attempt deduplication.** `prove_many(dedupe=True)` runs parallel attempts against one corpus handle and one proof cache: attempts share closed subgoals *live* (attempt A closing a lemma makes it a cache hit for concurrent attempt B). Over a CLI, parallel calls are isolated processes that duplicate work by construction. For campaign-scale proving, this is a multiplicative, not incremental, difference.

**10.4 · The environment algebra.** `without`/`overlay`/`diff` as cheap layered values enable speculative reasoning about *counterfactual libraries* — "what breaks if this axiom leaves," "does this candidate lemma shorten anything downstream" (X5's scoring), trust-graph what-ifs. Environments become a data structure the script computes over, which has no CLI analogue at all.

**10.5 · Steering: progress, cancellation, streaming.** `on_progress` callbacks, `CancelToken`, and generator-protocol result streams let scripts *stop early on sufficiency* (kill the exhaustive scan when the first counterexample lands; abandon a prove the moment falsification triage fires elsewhere). CLI streams are fire-and-forget; steering mid-computation is the difference between budget-shaped search and budget-wasting search, and it composes with 10.3 into portfolio schedulers written in twenty lines of Python.

**10.6 · Zero-copy data planes.** Buffer-protocol matrices, Arrow tables of declarations/results, memory-mapped indexes: the experiment battery (X1–X8) is dataframe-shaped work, and serializing Mathlib-scale tables as JSON per call is a non-starter. Lossless `Fraction` interop keeps the certificate currency exact across the boundary — the one place "just use floats" would be a soundness bug, not a performance choice.

**10.7 · Resumability as pickling semantics.** Handles pickle as journal references; a campaign interrupted at step 3,000 resumes by replay-to-checkpoint against the pinned fingerprint. Long-running research scripts become durable processes with exactly-once semantics over cached operations — the dynamic-workflow resumability guarantee, extended down into arbitrary agent-authored Python.

**Summary judgment:** 10.1–10.4 are new capabilities (experiments and methods that cannot be expressed otherwise); 10.5–10.7 are order-of-magnitude economics. Together they justify the standing rule from the design doc: the CLI remains for humans and shell pipelines; *agents author against this surface* — because the loop belongs in a diffable script, and the script deserves a real language.