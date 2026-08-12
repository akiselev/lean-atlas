# atlas for Python: The Scriptable Research API

**Status:** Draft 0.1 · A PyO3-based Python package (`pip install atlas`) exposing the Rust Atlas core, Lean session management, certificates, vet battery, and debugger to agent-written Python scripts. The thesis: **a CLI+JSON interface makes every workflow an agentic loop (perceive → parse → decide → shell out, per step, per turn); a Python API makes the workflow a program** — written once, reviewed like code, replayed forever, with state as objects and control flow as control flow. The agent's job shifts from *executing* research loops to *authoring* them, which is both cheaper per iteration and auditable per artifact.

## 1. Architecture

One Rust core, three skins. The Atlas engine (indexes, anti-unification, dictionary/graph stores, resolve operations, certificate kernels) is a Rust workspace; the CLI and the JSON mode remain as thin wrappers; the Python package binds the same crates via PyO3 (maturin build, `abi3-py310` wheels — one wheel per platform, every Python ≥3.10). Lean itself is not linked: the package manages Lean REPL subprocesses behind `Session` objects (the process boundary is a feature — Lean crashes don't take the interpreter down, and sessions are poolable). Data discipline: **handles, not copies** — corpora, environments, and indexes live in Rust behind `Arc`, Python holds `#[pyclass]` handles with lazy accessors; matrices and traces cross via the buffer protocol / NumPy zero-copy where representable, with exact rationals mapping to `fractions.Fraction` (lossless by construction — the certificate currency never touches floats crossing the boundary). Long-running Rust operations release the GIL (`py.allow_threads`), so agent scripts get real parallelism from `ThreadPoolExecutor` without an async API to learn; free-threaded CPython compatibility is tracked as a forward item, not a dependency.

## 2. The API surface (sketch)

```python
import atlas as fa

# --- Corpus & Atlas queries -------------------------------------------
corpus = fa.Corpus.load("mathlib@pin")          # handle; env-fingerprinted
hits   = corpus.similar(goal, index="skeleton", k=10)   # -> list[Match]
report = corpus.home(stmt)                      # -> HomeReport(.minimal_hyps, .deletable)
tr     = corpus.transport(stmt, dictionary="Z<->Fp[x]") # -> .candidate, .missing_entries
res    = corpus.resolve(residual)               # -> Recognized|Attributed|Spectrum|Irreducible

# --- Lean sessions: state as objects ----------------------------------
with fa.Session(corpus) as s:
    st  = s.goal(stmt)                          # GoalState handle
    st2 = st.apply("induction n")               # states are immutable; forking is free
    ok  = s.prove(st2, budget=fa.Budget(kernel_s=60), portfolio=["exact?", "simp", "positivity"])

# --- Vet, certs, debug -------------------------------------------------
dossier = fa.vet(stmt, probes=["V1","V8","V10"])        # -> Dossier(.mutants, .score, ...)
cert    = fa.certs.ldlt(fa.RatMatrix.from_fractions(M)) # exact; .check() -> kernel-ready
frame   = fa.Trace.load("run17.trace").frames[42]
ctx     = frame.to_lean_context(s)              # the REPL-is-the-debugger, two lines
```

Namespaces: `fa.Corpus` (load/snapshot/graph, env fingerprint pinned in the handle), `fa.Session`/`GoalState` (immutable, forkable — persistent REPL states as first-class values), `fa.vet` (probes → `Dossier` objects; `mutate`/`shrink`/`bracket` as iterators), `fa.certs` (LDLᵀ, interval evaluation, exhaustion checkers — the extracted kernels, callable), `fa.grade` / `fa.converge` (ε-ladders and loop stamps, curves out as NumPy), `fa.Trace` (debugger integration), `fa.ledger` (below). Full `.pyi` type stubs ship with the wheel — agents lean on stubs harder than humans do — and every public docstring carries a doctest run in CI against a vendored mini-corpus (the S7 rule, applied to our own API).

## 3. The four design principles that make it agent-grade

**Exceptions carry the diagnostics payload.** A failed prove doesn't return `False`; it raises `ProofFailed` with the full agent payload attached — `e.goal_state`, `e.candidates` (retrieval pre-run), `e.instance_trace`, and decisively `e.falsification` — so the routing decision from the diagnostics design becomes literal control flow:

```python
try:
    s.prove(st, budget=b)
except fa.ProofFailed as e:
    if e.falsification.status == "FALSIFIED":
        raise fa.EscalateH2(witness=e.falsification.witness)   # statement suspicion: stop
    goals.extend(e.subgoals)                                    # else: decompose and continue
```

**Everything journals; journals replay.** `with fa.campaign("couette-g4") as c:` wraps a script scope: every API call is recorded (op, args-hash, result-hash, cost) into the ledger automatically — the ledger-everything rule enforced by the API rather than by agent virtue — and `fa.replay(journal)` re-executes deterministically against pinned corpora. A script plus its journal *is* the repeatable workflow artifact; memoization falls out (journal entries keyed by args-hash consult the S1 proof cache transparently, so `s.prove` on a previously-closed goal is a lookup).

**The hard rules live in the API.** Operations that would edit frozen statements raise `FrozenStatementError` citing H2; `native_decide` is not in the portfolio vocabulary; axiom-whitelist violations surface at `check()` — the CLAUDE.md contract compiled into the binding layer, so a script *cannot* be written that quietly violates it.

**Costs are visible.** Every result object carries `.cost` (kernel seconds, search compute, cache hits), aggregating up the campaign context into the S5 ledger — the per-theorem price sheet assembled as a side effect of normal scripting.

## 4. What it looks like in anger — the X1 experiment, complete

```python
import atlas as fa, random

corpus = fa.Corpus.load("mathlib@pin")
lemmas = fa.experiments.frozen_list("X1-targets")        # pre-registered, ledgered
results = []
with fa.campaign("X1-run1") as c:
    for lem in lemmas:
        broken = corpus.without(lem)                     # copy-on-write env handle
        stuck  = broken.elaborate_downstream(lem).failures   # the stuck-goal stream
        clusters   = fa.antiunify.cluster(stuck, by="skeleton")
        candidates = [cl.lgg() for cl in clusters][:3]
        results.append(fa.experiments.statement_match(candidates, target=lem))
print(fa.experiments.summarize(results, baseline="nearest-retrieval"))
```

Twenty lines, deterministic, journaled, replayable, and reviewable in a PR — versus the same experiment as several hundred agentic turns of CLI calls, each re-parsing JSON and re-deriving the loop. That ratio is the entire argument for this document.

## 5. Boundaries, packaging, milestones

Scoping honesty: the API is repo-scoped and permission-inherits from the harness (no ambient filesystem authority beyond the project); scripts are artifacts subject to the same review culture as any code; and the API is *not* a metaprogramming escape hatch — anything requiring new elaborator behavior goes through FH proper, keeping the trusted surface where it already is. Packaging: `maturin` from the workspace, wheels in CI, the vendored doctest mini-corpus, semver with the corpus fingerprint pinned per `Corpus` handle and `fa.require(">=0.3")` for scripts. Milestones: **PY0** — `Corpus.load` + `similar` + `Session.prove` + campaign journaling (the minimum that beats the CLI for real work); **PY1** — vet/certs/RatMatrix interop + exceptions-with-payload; **PY2** — replay, cache integration, cost surfaces; **PY3** — trace/debugger integration and the experiment-harness helpers used above. PY0 is small precisely because the Rust core already exists in the plan; the binding layer is thin by design, and thin is what keeps it honest — the API's job is to move *authority over the loop* from the conversation into the script, where it can be diffed, replayed, and judged like everything else this program builds.