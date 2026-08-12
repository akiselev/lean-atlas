#!/usr/bin/env python3
"""Over-strong hypotheses in physlib, and whether Mathlib's family rates transfer.

§37-§45 built a generalization pipeline on Mathlib and ended at 387 kernel-verified
hypothesis weakenings. The interesting number in it is not 387; it is §42's observation
that confirmation rate is **bimodal by weakening family** — 68% of families at exactly 0%
or exactly 100% — because that is the shape of a *law* rather than of a detector's noise
floor. A law should transfer. A Mathlib artifact should not.

This script ports the pipeline to physlib and asks whether it does.

## The three questions

1. Do the same weakening families appear in physics, whose classes are `NormedAddCommGroup`,
   `InnerProductSpace`, `MeasurableSpace`, `Module`, `Algebra` rather than `Monoid` and
   `Preorder`?
2. Do the Mathlib-measured family rates *predict* physlib outcomes? Families are split into
   (a) measured on Mathlib and present in physlib, and (b) physlib-only. Stratum (a) carries
   a prediction; stratum (b) carries only the pooled rate.
3. Are there physics-specific over-hypotheses — a theorem stated for a Hilbert space that
   needs only an inner-product space, one stated for a Lorentzian metric that needs only a
   bilinear form?

## What a good answer looks like — written before the physlib closure existed

These are pre-registered. Each names what would show the pipeline does *not* transfer.

**R1 — the control, and it is load-bearing.** The physlib closure is Mathlib + Physlib +
QuantumInfo, so the sweep over it must reproduce §37's Mathlib candidates on the Mathlib
part. Recovery is measured only over §37 candidates whose declaration is *present in this
corpus*, since physlib imports a fraction of Mathlib and pins v4.32.0 against §35's v4.32.2.
Pass: >= 60% recovered with the same target. Below that the corpus or the sweep differs
enough that no physics number below is interpretable, and the script says so.

**R2 — yield.** Mathlib produces 2,704 candidates from 470,435 declarations (0.575%).
Physlib+QuantumInfo has 14,576 declarations; at Mathlib's rate that is 84. The prediction is
**fewer**: physics is largely stated over concrete carriers (`ℝ`, `EuclideanSpace ℝ (Fin 3)`)
with no typeclass polymorphism left to weaken. Predicted range 5-60. **Zero is a real answer**
and would mean the pipeline needs polymorphic source material, not that it is broken — which
is why the verdict histogram (multi-carrier, at-home, unused, no-instance-binder) is reported
beside the candidate count rather than after it.

**R3 — family overlap.** physlib defines few classes of its own and walks Mathlib's lattice,
so the *majority* of physics candidate families should already be measured on Mathlib. A
physics-only family needs a `Physlib.*`/`QuantumInfo.*` class as source or target.

**R4 — transfer.** For stratum (a), predicted confirmations = sum over families of
rate_Mathlib(f) x n_physlib(f). The Poisson-binomial 95% interval is reported with it. The
orchestrator runs the kernel; observed outside that interval falsifies "the family map is a
transferable law". Observed inside it does not prove the law, but is the only evidence
available at this sample size, and the interval is stated **before** the kernel runs.

**R5 — physics-specific.** Any candidate whose declared or target class is defined in
`Physlib.*`/`QuantumInfo.*` is a genuinely physics-specific over-hypothesis. Prediction: few
or none, for R3's reason. Reported separately from the Mathlib-class ones either way.

## Controls, because every filter here narrows

* **closure** — `Corpus.closure()` must be >= 95% before any number is reported (§31: an
  unclosed slice loses 34.5% of candidates and fabricates 11.0%). `--stage control-unclosed`
  runs the same sweep over the *unclosed* `--local` physlib slice and measures loss and
  fabrication on this corpus rather than assuming §31's figures carry over. That is the
  paired negative: the closed and unclosed runs must disagree, or the closure is decorative.
* **arity** (§38) — the askable/unaskable split is a narrowing filter, so it is reported with
  the families it removes and with a check that a known arity-preserving family survives.
* **family map** — the transfer prediction is re-run with the Mathlib rates *shuffled across
  families*. If shuffling does not move the prediction, the map carries no information about
  this candidate set and the transfer test is vacuous (§16's cautionary shape).
* **novelty screen** — run *before* probing, per §43: a high confirmation rate partly measures
  rediscovery, and screening after the kernel spends budget on already-stated generality.
  Its sensitivity is **not** re-measured on physics rows here, and that is a real gap:
  `screen-sensitivity.py` works by writing three copies of the corpus with injected rows,
  which at physics-closure size is three multi-gigabyte files and a corpus load each. §40's
  40/40 was measured on Mathlib rows; nothing here shows it holds on statements headed by
  `InnerProductSpace'`. Reported as unmeasured rather than assumed.

Nothing here confirms anything. `#atlas_home_refute` and the kernel do that, and this script
cannot run them; `--stage plan` emits the probe file and the index `score-probes.py` reads.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import random
import resource
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from atlas_home import telescope  # noqa: E402
from atlas_home_stream import StreamHomeIndex  # noqa: E402

PHYS_PREFIXES = ("Physlib", "QuantumInfo")

HEADER = """/-
Copyright (c) 2026 The lean-atlas contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
-/
import Physlib
import QuantumInfo
import Atlas.Home

/-!
# Kernel probes over the physlib candidate set

Generated by `scripts/phys-hypothesis-min.py`. Every line is a *candidate* weakening found
by the evidence rule over a verified-closed physlib corpus; only the kernel settles them.

Allocation is per weakening *family*, per §37: rates are bimodal, so a first probe into an
unmeasured family is worth more than an nth probe into one already measured.

`Atlas.Home`, not `Atlas.Home` — the physics workspace pins v4.32.0 and
cannot depend on the Atlas package (v4.32.2). See the report's engine-change spec:
`Atlas/Home.lean` has to move into the shared `atlas-extract` package for this file to
build at all.
-/

set_option maxHeartbeats 1000000
"""


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


# ---------------------------------------------------------------------------
# A row reader that drops the half of each row the current pass does not use.
# ---------------------------------------------------------------------------

class FastStreamHomeIndex(StreamHomeIndex):
    """`StreamHomeIndex` with the JSON parse narrowed to the fields each pass reads.

    The verdict rule is **not** touched — only `_rows`. Duplicating `verdicts` to make it
    faster would put a third copy of the evidence rule in the tree, and the streaming rule
    exists only because `generalization-full.py --verify` proves it equals the in-memory
    one; a copy nobody verifies is worse than a slow run.

    **It does not make the sweep faster, and that is the point of keeping it documented.**
    The reasoning that produced it was: a physics row is 10-40 KB, both passes `json.loads`
    it whole, and each pass reads only half the fields — so trim the other half. Measured on
    30,000 large rows, trimmed against untrimmed:

        untrimmed  scan 292.2s  judge  5.5s
        trimmed    scan 290.5s  judge  4.6s

    0.6%. The scan is not JSON-bound at all: pass two `json.loads` the *same* 664 MB file in
    5.5 s. Essentially all of the 292 s is `atlas_home.telescope` walking the encoding in
    Python — and `Reader.head_and_args` re-reads the function half of every application
    spine through a fresh sub-`Reader`, which is quadratic in spine depth on exactly the
    deeply-applied terms physics writes.

    So the real optimisation, if the physics corpus ever needs one, is a head-only spine
    walk for the conclusion (the carrier rule needs the argument list, the `produces_class`
    rule needs only the head), or moving the telescope into the Rust arena beside
    `Corpus.requires`. Trimming the JSON is not it. This class is kept because it is
    verified identical (`--stage verify-fast`) and marginally faster, and because the
    measurement above is worth more than the code.

    The splice keys on `,"uses_proof":`, which is safe because `atlas_extract` writes the
    row's fields in sorted order — `kind, module, name, stmt, uses_proof, uses_statement` —
    so that marker separates the two halves. `rfind` rather than `find` in case a French-
    quoted declaration name embeds it. Any splice that does not re-parse falls back to the
    original line, so a pathological name costs speed and never correctness.
    """

    strip_for_verdicts = False

    def _rows(self):
        strip = self.strip_for_verdicts
        with open(self.path, "rb") as fh:
            for line in fh:
                if not line.strip():
                    continue
                i = line.rfind(b',"uses_proof":')
                if i < 0:
                    yield json.loads(line)
                    continue
                if strip:
                    j = line.find(b',"stmt":"')
                    trimmed = line if j < 0 else line[:j] + b"," + line[i + 1:]
                else:
                    trimmed = line[:i] + b"}"
                try:
                    yield json.loads(trimmed)
                except Exception:
                    yield json.loads(line)

    def verdicts(self, progress=None):
        self.strip_for_verdicts = True
        try:
            yield from super().verdicts(progress=progress)
        finally:
            self.strip_for_verdicts = False


def is_phys(module: str | None) -> bool:
    m = module or ""
    return any(m == p or m.startswith(p + ".") for p in PHYS_PREFIXES)


# ---------------------------------------------------------------------------
# Stage: sweep
# ---------------------------------------------------------------------------

def run_sweep(path: str, t0: float, quiet: bool = False, plain: bool = False):
    """The streaming evidence rule, plus the class-arity table it can produce for free.

    `probe-plan.py` re-streams the whole slice to learn class arities. The binders are
    already in hand here, so arity is read off the same pass — which on a multi-gigabyte
    physics closure is a pass saved, not a micro-optimisation.
    """
    def prog(tag):
        if quiet:
            return None
        return lambda i: print(
            f"  [{tag}] {i:,} rows  {rss_gb():.1f} GB  {time.time() - t0:.0f}s", flush=True)

    idx = (StreamHomeIndex if plain else FastStreamHomeIndex)(path, progress=prog("scan"))
    if not quiet:
        print(f"lattice: {len(idx.classes):,} classes, "
              f"{sum(len(v) for v in idx.parents.values()):,} edges, "
              f"{len(idx.forgetful):,} forgetful  "
              f"[{idx.parse_errors:,} unparseable]  {rss_gb():.1f} GB", flush=True)

    arity_obs: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for b in idx.binders.values():
        for _bi, h, args, _d in b:
            arity_obs[h][len(args)] += 1
    arity = {c: k.most_common(1)[0][0] for c, k in arity_obs.items()}

    # The physics-restricted histogram is gathered in the *same* pass. A second judging
    # pass re-reads a multi-gigabyte file to answer a question this loop already has the
    # answer to, which on the algebra slice is 4 s and on the physics closure is minutes.
    stat: collections.Counter = collections.Counter()
    phys_stat: collections.Counter = collections.Counter()
    cands = []
    for name, verdict, cls, home in idx.verdicts(progress=prog("judge")):
        stat[verdict] += 1
        if is_phys(idx.module.get(name)):
            phys_stat[verdict] += 1
        if verdict == "over-hypothesis":
            cands.append((name, cls, home))
    return idx, stat, cands, arity, phys_stat


def stage_sweep(args) -> int:
    t0 = time.time()
    print(f"=== sweep: {args.slice} ===", flush=True)
    idx, stat, cands, arity, phys_stat = run_sweep(str(args.slice), t0)

    print(f"\nverdicts ({time.time() - t0:.0f}s, peak {rss_gb():.1f} GB):")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v:9,}")
    print(f"  {'CANDIDATES':24s} {len(cands):9,}")

    n_phys_decl = sum(1 for m in idx.module.values() if is_phys(m))
    phys = [(n, c, h) for n, c, h in cands if is_phys(idx.module.get(n))]
    print(f"\nphysics-authored declarations in corpus : {n_phys_decl:,}")
    print(f"physics-authored candidates             : {len(phys):,}")
    if n_phys_decl:
        print(f"  yield                                 : "
              f"{len(phys) / n_phys_decl * 100:.3f}%  "
              f"(Mathlib §37: 2,704/470,435 = 0.575%)")

    # The verdict histogram restricted to physics is the diagnostic R2 asks for: it says
    # *why* the yield is what it is rather than only that it is.
    print("\nphysics-only verdict histogram:")
    for k, v in phys_stat.most_common():
        print(f"  {k:24s} {v:9,}")

    by_fam = collections.Counter((c, h) for _n, c, h in phys)
    print(f"\nphysics candidate families ({len(by_fam):,}):")
    for (c, h), v in by_fam.most_common(25):
        print(f"  {v:5,}  {c} -> {h}")

    args.out.write_text(json.dumps({
        "slice": str(args.slice),
        "stat": dict(stat),
        "phys_stat": dict(phys_stat),
        "n_phys_decl": n_phys_decl,
        "candidates": len(cands),
        "arity": arity,
        "rows": [{"decl": n, "declared": c, "target": h,
                  "module": idx.module.get(n),
                  "phys": is_phys(idx.module.get(n))} for n, c, h in cands],
    }, indent=1))
    print(f"\n-> {args.out}  ({time.time() - t0:.0f}s)")

    if args.mathlib_candidates and args.mathlib_candidates.exists():
        _control_mathlib_recovery(idx, cands, args.mathlib_candidates)
    return 0


def _control_mathlib_recovery(idx, cands, mathlib_path: pathlib.Path) -> None:
    """R1. Does this corpus reproduce §37's Mathlib candidates on the Mathlib part?

    Restricted to §37 candidates whose declaration is present here — physlib imports a
    fraction of Mathlib, so absence is expected and is not a disagreement.
    """
    try:
        ref = json.loads(mathlib_path.read_text())["rows"]
    except Exception as e:
        print(f"\n=== R1 control: SKIPPED — {mathlib_path} unreadable ({e}) ===")
        return
    here = {(n, c): h for n, c, h in cands}
    present = [r for r in ref if r["decl"] in idx.binders]
    same = sum(1 for r in present
               if here.get((r["decl"], r["declared"])) == r["target"])
    found_diff = sum(1 for r in present
                     if (r["decl"], r["declared"]) in here
                     and here[(r["decl"], r["declared"])] != r["target"])
    print("\n=== R1 control: recovery of the Mathlib candidate set ===")
    print(f"  §37 candidates                      : {len(ref):,}")
    print(f"  …whose declaration is in this corpus: {len(present):,}")
    print(f"  recovered with the same target      : {same:,} "
          f"({same / len(present) * 100:.1f}%)" if present else "  none present")
    print(f"  recovered with a different target   : {found_diff:,}")
    if present:
        ok = same / len(present) >= 0.60
        print(f"  VERDICT: {'PASS' if ok else 'FAIL'} against the pre-registered 60% floor")
        if not ok:
            print("  -> the physics numbers in this run are NOT interpretable.")


# ---------------------------------------------------------------------------
# Stage: control-unclosed
# ---------------------------------------------------------------------------

def stage_control_unclosed(args) -> int:
    """§31's measurement, taken on this corpus instead of inherited from Mathlib's.

    The closed run is the reference. The unclosed `--local` slice is the same physics
    declarations with their foundation filtered out of the *output*. Loss and fabrication
    are measured over physics-authored candidates only, since those are the ones the
    unclosed slice even contains.
    """
    t0 = time.time()
    closed = json.loads(args.out.read_text())
    good = {(r["decl"], r["declared"]): r["target"] for r in closed["rows"] if r["phys"]}

    print(f"=== control: the same sweep over the UNCLOSED slice {args.unclosed} ===",
          flush=True)
    idx, stat, cands, _ar, _ps = run_sweep(str(args.unclosed), t0)
    bad = {(n, c): h for n, c, h in cands if is_phys(idx.module.get(n))}

    both = set(good) & set(bad)
    agree = sum(1 for k in both if good[k] == bad[k])
    lost = len(set(good) - set(bad))
    fab = len(set(bad) - set(good))
    print("\n=== §31 on physics, measured rather than inherited ===")
    print(f"  closed corpus candidates (physics)  : {len(good):,}")
    print(f"  unclosed slice candidates (physics) : {len(bad):,}")
    print(f"  present in both                     : {len(both):,}")
    print(f"  …agreeing on the target             : {agree:,}")
    print(f"  LOST by removing the foundation     : {lost:,}"
          + (f"  ({lost / len(good) * 100:.1f}% of the correct set)" if good else ""))
    print(f"  FABRICATED by removing it           : {fab:,}"
          + (f"  ({fab / len(bad) * 100:.1f}% of its own output)" if bad else ""))
    if lost == 0 and fab == 0:
        print("\n  ABORT-WORTHY: the two corpora produced the same answer, so closure is "
              "not doing anything here and the closed/unclosed distinction is untested.")
    for k in sorted(set(bad) - set(good))[:10]:
        print(f"    fabricated: {k[0]}  [{k[1]}] -> {bad[k]}")
    return 0


# ---------------------------------------------------------------------------
# The Mathlib family map
# ---------------------------------------------------------------------------

def shrunk(conf, dec, pooled: float, alpha: float):
    """A family's confirmation rate, pulled toward the pooled rate by `alpha` pseudo-probes.

    The raw rate is what §42 reports, and on held-out Mathlib probes it is **biased low**:
    fit on runs 1+2 it predicts 106.9 confirmations where 146 occurred, because a family
    measured on three probes that all failed reads as exactly 0% and mostly is not. The
    pooled rate is biased the other way (228.6). `alpha = 4` — roughly the median family's
    probe count — minimises Brier on that held-out set at 0.1084 and predicts 145.6.

    `alpha` was chosen *on* that held-out set, so its optimality is mildly optimistic; the
    ordering it is used for (raw < shrunk, pooled < shrunk) is not, since both endpoints
    are worse by a wide margin.
    """
    return lambda f: (conf[f] + alpha * pooled) / (dec[f] + alpha)


def family_map(paths: list[pathlib.Path]):
    """`(declared, target) -> (confirmed, decisive)` from the Mathlib scored runs."""
    conf: collections.Counter = collections.Counter()
    dec: collections.Counter = collections.Counter()
    for p in paths:
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        for _decl, dc, tg in d.get("confirmed", []):
            conf[(dc, tg)] += 1
            dec[(dc, tg)] += 1
        for _decl, dc, tg in d.get("refuted", []):
            dec[(dc, tg)] += 1
    return conf, dec


# ---------------------------------------------------------------------------
# Stage: screen  (novelty, before probing — §43)
# ---------------------------------------------------------------------------

def stage_verify_fast(args) -> int:
    """The trimmed reader must produce the *identical* candidate set to the untrimmed one.

    A reader that silently drops a row looks exactly like a domain difference once it is
    pointed at physics, and there is no way to tell the two apart from the output. So this
    runs both on a slice that fits and compares the whole set, not a count — two sets can
    agree in size and disagree in membership.

    Run it on the algebra closure, where the answer is also independently known: 727.
    """
    t0 = time.time()
    print(f"=== differential: trimmed vs untrimmed reader on {args.slice.name} ===",
          flush=True)
    _i, sf, cf, af, _p = run_sweep(str(args.slice), t0, quiet=True, plain=False)
    print(f"  trimmed   : {len(cf):,} candidates, {len(af):,} classes with an arity "
          f"({time.time() - t0:.0f}s)", flush=True)
    t1 = time.time()
    _i, sp, cp, ap, _p = run_sweep(str(args.slice), t0, quiet=True, plain=True)
    print(f"  untrimmed : {len(cp):,} candidates, {len(ap):,} classes with an arity "
          f"({time.time() - t1:.0f}s)")
    ok = True
    if set(cf) != set(cp):
        ok = False
        print(f"  DISAGREE on candidates: {len(set(cf) - set(cp)):,} only-trimmed, "
              f"{len(set(cp) - set(cf)):,} only-untrimmed")
        for x in sorted(set(cf) ^ set(cp))[:5]:
            print(f"    {x}")
    if af != ap:
        ok = False
        diff = [k for k in set(af) | set(ap) if af.get(k) != ap.get(k)]
        print(f"  DISAGREE on arity for {len(diff):,} classes: {diff[:5]}")
    if sf != sp:
        ok = False
        print(f"  DISAGREE on the verdict histogram: {sf} vs {sp}")
    print("  IDENTICAL — the trimmed reader is verified" if ok else "  FAILED")
    return 0 if ok else 1


def stage_selftest(args) -> int:
    """Does the family map predict *held-out Mathlib* probes?

    Before asking whether the map transfers to physics it has to be shown to predict at
    all, and the three Mathlib runs make that measurable without any new kernel time: fit
    the map on runs 1+2 and score run 3, which was allocated by `--all-remaining` over
    candidates the first two had not touched.

    Two baselines, because "the prediction was close" means nothing on its own:

    * the **pooled** rate — one number for every family. Beating it is the whole claim.
    * the **shuffled** map — the same rates permuted across families. This is the §16
      control: a map that predicts no better than its own permutation is measuring family
      *size*, not family identity.

    Scored by Brier score (mean squared error of the per-probe probability), which is
    proper — it cannot be gamed by predicting the base rate everywhere.
    """
    fit_paths = args.mathlib_scored[:-1]
    test_path = args.mathlib_scored[-1]
    conf, dec = family_map(fit_paths)
    print(f"fit on {[p.name for p in fit_paths]}: {len(dec):,} families, "
          f"{sum(dec.values()):,} decisive")
    d = json.loads(test_path.read_text())
    held = ([(tuple(x), 1) for x in d.get("confirmed", [])]
            + [(tuple(x), 0) for x in d.get("refuted", [])])
    print(f"held out {test_path.name}: {len(held):,} decisive probes, "
          f"{sum(y for _t, y in held):,} confirmed")

    pooled = sum(conf.values()) / sum(dec.values())
    known = [(t, y) for t, y in held if dec[(t[1], t[2])] >= args.min_prior]
    print(f"\n=== held-out probes in families with >={args.min_prior} prior probes ===")
    print(f"  probes    : {len(known):,}")
    if not known:
        print("  nothing to score.")
        return 1
    obs = sum(y for _t, y in known)
    ps = [conf[(t[1], t[2])] / dec[(t[1], t[2])] for t, _y in known]
    mu, lo, hi = poisson_binomial_interval(ps)
    print(f"  observed confirmed         : {obs}")
    print(f"  predicted by the family map: {mu:.1f}  95% [{lo:.1f}, {hi:.1f}]  "
          f"{'HIT' if lo <= obs <= hi else 'MISS'}")
    pooled_mu, p_lo, p_hi = poisson_binomial_interval([pooled] * len(known))
    print(f"  predicted by pooled rate   : {pooled_mu:.1f}  95% [{p_lo:.1f}, {p_hi:.1f}]  "
          f"{'HIT' if p_lo <= obs <= p_hi else 'MISS'}")

    sh = shrunk(conf, dec, pooled, args.alpha)
    s_ps = [sh((t[1], t[2])) for t, _y in known]
    s_mu, s_lo, s_hi = poisson_binomial_interval(s_ps)
    print(f"  predicted by shrunk map    : {s_mu:.1f}  95% [{s_lo:.1f}, {s_hi:.1f}]  "
          f"{'HIT' if s_lo <= obs <= s_hi else 'MISS'}   (alpha={args.alpha})")

    brier_map = sum((p - y) ** 2 for p, (_t, y) in zip(ps, known)) / len(known)
    brier_pool = sum((pooled - y) ** 2 for _t, y in known) / len(known)
    brier_sh = sum((p - y) ** 2 for p, (_t, y) in zip(s_ps, known)) / len(known)
    print(f"\n  Brier, raw family map : {brier_map:.4f}")
    print(f"  Brier, pooled         : {brier_pool:.4f}")
    print(f"  Brier, shrunk map     : {brier_sh:.4f}")
    print(f"  shrunk skill vs pooled: {(1 - brier_sh / brier_pool) * 100:+.1f}%")

    # How well does a family's fitted rate order its held-out rate? Brier skill can come
    # entirely from the large near-zero families, so the rank correlation is reported
    # separately — it is the part of §42's bimodality claim that has to replicate.
    n_h: collections.Counter = collections.Counter()
    o_h: collections.Counter = collections.Counter()
    for t, y in known:
        n_h[(t[1], t[2])] += 1
        o_h[(t[1], t[2])] += y
    big = [f for f in n_h if n_h[f] >= 5]
    if len(big) >= 5:
        a = [conf[f] / dec[f] for f in big]
        b = [o_h[f] / n_h[f] for f in big]
        print(f"\n  families with >=5 held-out probes: {len(big)}")
        print(f"  Spearman(fitted rate, held-out rate) = {_spearman(a, b):.3f}")
        z = [f for f in big if conf[f] == 0]
        if z:
            print(f"  families fitted at exactly 0%: {len(z)}; their held-out rate is "
                  f"{sum(o_h[f] for f in z) / sum(n_h[f] for f in z) * 100:.1f}% "
                  f"over {sum(n_h[f] for f in z):,} probes")
        o = [f for f in big if conf[f] == dec[f]]
        if o:
            print(f"  families fitted at exactly 100%: {len(o)}; their held-out rate is "
                  f"{sum(o_h[f] for f in o) / sum(n_h[f] for f in o) * 100:.1f}% "
                  f"over {sum(n_h[f] for f in o):,} probes")

    fams = sorted({(t[1], t[2]) for t, _y in known})
    rates = [conf[f] / dec[f] for f in fams]
    idx_of = {f: i for i, f in enumerate(fams)}
    rng = random.Random(20260804)
    worse = 0
    for _ in range(2000):
        perm = rates[:]
        rng.shuffle(perm)
        b = sum((perm[idx_of[(t[1], t[2])]] - y) ** 2 for t, y in known) / len(known)
        worse += b <= brier_map
    print(f"  shuffled maps at least as good: {worse}/2000  (p = {worse / 2000:.4f})")
    if worse / 2000 > 0.05:
        print("  -> the map is NOT distinguishable from a permutation of itself. Any "
              "transfer claim below rests on the pooled rate only.")
    else:
        print("  -> family identity carries real predictive information within Mathlib. "
              "That is the baseline the physics transfer is measured against.")
    return 0


def stage_screen(args) -> int:
    try:
        import atlas as fa
    except ImportError:
        sys.exit("atlas is not importable — run under `uv run`")
    t0 = time.time()
    cands = json.loads(args.out.read_text())
    phys = [r for r in cands["rows"] if r["phys"]]
    print(f"loading {args.slice} …", flush=True)
    c = fa.Corpus.load(str(args.slice))
    print(f"  loaded in {time.time() - t0:.0f}s, {rss_gb():.1f} GB", flush=True)

    heads, missing, cov, top = c.closure(top=12)
    print(f"\n=== closure gate ===")
    print(f"  application heads : {heads:,}")
    print(f"  missing           : {missing:,}")
    print(f"  coverage          : {cov * 100:.2f}%")
    for name, n in top:
        print(f"    {name}  ({n:,} statements)")
    if cov < 0.95:
        print("\n  ABORT: below the 95% floor. §31 — an unclosed corpus loses 34.5% of "
              "candidates and fabricates 11.0%, silently. No number below is reportable.")
        return 1
    print("  PASS")

    # --- novelty screen, before the kernel sees anything (§43) -----------------
    novel, prior, unscreenable = [], [], []
    for i, r in enumerate(phys):
        if i % 50 == 0:
            print(f"  [screen] {i}/{len(phys)}  {time.time() - t0:.0f}s", flush=True)
        try:
            eq = c.equivalent(r["decl"], level="instances")
        except Exception:
            unscreenable.append(r)
            continue
        others = [e for e in eq if e != r["decl"]]
        (prior if others else novel).append({**r, "prior_art": others[:5]})
    print(f"\n=== novelty screen (before probing, per §43) ===")
    print(f"  physics candidates : {len(phys):,}")
    print(f"  no equivalent      : {len(novel):,}")
    print(f"  prior art found    : {len(prior):,}")
    print(f"  unscreenable       : {len(unscreenable):,}")
    for r in prior[:12]:
        print(f"    {r['decl']}  [{r['declared']} -> {r['target']}]  already: "
              f"{', '.join(r['prior_art'][:2])}")

    args.screened.write_text(json.dumps(
        {"novel": novel, "prior": prior,
         "unscreenable": [r["decl"] for r in unscreenable],
         "closure": {"heads": heads, "missing": missing, "coverage": cov}}, indent=1))
    print(f"\n-> {args.screened}")
    return 0


# ---------------------------------------------------------------------------
# Stage: plan
# ---------------------------------------------------------------------------

def _spearman(a: list[float], b: list[float]) -> float:
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for j, i in enumerate(s):
            r[i] = float(j)
        return r
    ra, rb = rank(a), rank(b)
    m = len(a)
    ma = (m - 1) / 2
    num = sum((ra[i] - ma) * (rb[i] - ma) for i in range(m))
    den = math.sqrt(sum((ra[i] - ma) ** 2 for i in range(m))
                    * sum((rb[i] - ma) ** 2 for i in range(m)))
    return num / den if den else 0.0


def poisson_binomial_interval(ps: list[float]) -> tuple[float, float, float]:
    """Mean and a 95% normal interval for a sum of independent Bernoullis.

    Normal rather than exact because the point of the interval is to be stated *before*
    the kernel runs and to be wide enough that a genuine transfer failure is what breaks
    it — an exact convolution would be narrower and would over-claim at n ~ 100.
    """
    mu = sum(ps)
    var = sum(p * (1 - p) for p in ps)
    sd = math.sqrt(var)
    return mu, max(0.0, mu - 1.96 * sd), mu + 1.96 * sd


def stage_plan(args) -> int:
    cands = json.loads(args.out.read_text())
    arity = cands["arity"]
    if args.screened.exists():
        sc = json.loads(args.screened.read_text())
        rows = sc["novel"]
        print(f"using the screened set: {len(rows):,} novel of "
              f"{len(rows) + len(sc['prior']):,} physics candidates")
    else:
        rows = [r for r in cands["rows"] if r["phys"]]
        print(f"NO SCREEN RUN — planning over all {len(rows):,} physics candidates. "
              "§43: screening after probing spends kernel budget on rediscovery.")

    conf, dec = family_map(args.mathlib_scored)
    print(f"\nMathlib family map: {len(dec):,} families, {sum(dec.values()):,} decisive "
          f"probes, {sum(conf.values()):,} confirmed "
          f"({sum(conf.values()) / sum(dec.values()) * 100:.1f}% pooled)")

    # --- askability (§38), a narrowing filter, so it is reported with its control ----
    askable, unaskable = [], []
    for r in rows:
        a, b = arity.get(r["declared"]), arity.get(r["target"])
        (unaskable if (a is not None and b is not None and a != b) else askable).append(r)
    print(f"\n=== askability split (§38) ===")
    print(f"  askable                    : {len(askable):,}")
    print(f"  arity-changing (unaskable) : {len(unaskable):,}")
    ua_fams = collections.Counter((r["declared"], r["target"]) for r in unaskable)
    for (c, h), n in ua_fams.most_common(8):
        print(f"    {n:4,}  {c}({arity.get(c)}) -> {h}({arity.get(h)})")
    if rows and not askable:
        print("  ABORT: the filter removed everything, which is a filter with no control.")
        return 1

    # --- family strata and the transfer prediction (R4) ------------------------------
    by_fam: dict[tuple[str, str], list] = collections.defaultdict(list)
    for r in askable:
        by_fam[(r["declared"], r["target"])].append(r)

    strat_a, strat_a_weak, strat_b = [], [], []
    for f, rs in by_fam.items():
        if dec[f] >= args.min_prior:
            strat_a.append(f)
        elif dec[f] > 0:
            strat_a_weak.append(f)
        else:
            strat_b.append(f)
    pooled = sum(conf.values()) / sum(dec.values())
    sh = shrunk(conf, dec, pooled, args.alpha)

    def block(fams, label, use_rate):
        n = sum(len(by_fam[f]) for f in fams)
        ps = [use_rate(f) for f in fams for _ in by_fam[f]]
        mu, lo, hi = poisson_binomial_interval(ps) if ps else (0, 0, 0)
        print(f"  {label:52s} families {len(fams):4,}  candidates {n:5,}  "
              f"predicted {mu:6.1f}  95% [{lo:.1f}, {hi:.1f}]")
        return n, mu, lo, hi

    print(f"\n=== R4: transfer prediction (pre-registered; the kernel has not run) ===")
    print(f"  rates are shrunk toward the pooled Mathlib rate {pooled * 100:.1f}% with "
          f"alpha={args.alpha}; the raw map under-predicts held-out Mathlib probes by 27% "
          f"and the pooled rate over-predicts by 57% (--stage selftest).")
    a_n, a_mu, a_lo, a_hi = block(
        strat_a, f"(a) measured on Mathlib, >={args.min_prior} probes", sh)
    aw_n, aw_mu, aw_lo, aw_hi = block(
        strat_a_weak, "(a') measured on Mathlib, 1-2 probes", sh)
    b_n, b_mu, b_lo, b_hi = block(
        strat_b, "(b) physlib-only, no Mathlib measurement", lambda _f: pooled)
    tot_ps = ([sh(f) for f in strat_a for _ in by_fam[f]]
              + [sh(f) for f in strat_a_weak for _ in by_fam[f]]
              + [pooled for f in strat_b for _ in by_fam[f]])
    t_mu = t_lo = t_hi = 0.0
    if tot_ps:
        t_mu, t_lo, t_hi = poisson_binomial_interval(tot_ps)
        print(f"  {'TOTAL over askable physics candidates':52s} "
              f"{'':16s}{len(tot_ps):5,}  predicted {t_mu:6.1f}  95% [{t_lo:.1f}, {t_hi:.1f}]")
        # Power, stated before the kernel runs. An interval wide enough to contain every
        # rate worth distinguishing is not a test, and saying so now is the difference
        # between a pre-registration and a post-hoc rationalisation.
        n = len(tot_ps)
        print(f"  discriminating power: the interval spans "
              f"{t_lo / n * 100:.1f}%-{t_hi / n * 100:.1f}% observed rate over {n:,} probes; "
              f"pooled Mathlib is {pooled * 100:.1f}%")
        if t_lo / n <= pooled <= t_hi / n:
            print("  NOTE: the pooled Mathlib rate lies inside the family-map interval, so "
                  "this run CANNOT separate 'the family map transfers' from 'only the "
                  "overall rate transfers'. It can still falsify both at once.")

    # --- the control the prediction needs: shuffle the map ---------------------------
    # If permuting Mathlib's rates across families leaves the prediction where it was, the
    # map is not carrying information about *this* candidate set and R4 is vacuous. §16.
    if strat_a:
        rates = [conf[f] / dec[f] for f in strat_a]
        sizes = [len(by_fam[f]) for f in strat_a]
        rng = random.Random(20260804)
        sims = []
        for _ in range(2000):
            perm = rates[:]
            rng.shuffle(perm)
            sims.append(sum(p * n for p, n in zip(perm, sizes)))
        sims.sort()
        print(f"\n=== control: Mathlib rates shuffled across stratum-(a) families ===")
        print(f"  real prediction        : {a_mu:.1f}")
        print(f"  shuffled, median       : {sims[len(sims) // 2]:.1f}")
        print(f"  shuffled, 95% spread   : [{sims[int(.025 * len(sims))]:.1f}, "
              f"{sims[int(.975 * len(sims))]:.1f}]")
        outside = a_mu < sims[int(.025 * len(sims))] or a_mu > sims[int(.975 * len(sims))]
        verdict = ("OUTSIDE the shuffled spread -> the family map carries information "
                   "about which physlib families are large"
                   if outside else
                   "INSIDE the shuffled spread -> the map is NOT distinguishable from a "
                   "random assignment on this candidate set, so R4 tests only the "
                   "pooled rate")
        print(f"  the real prediction is {verdict}")

    # --- R5: physics-specific classes -------------------------------------------------
    def phys_class(x: str) -> bool:
        return any(x == p or x.startswith(p + ".") for p in PHYS_PREFIXES)

    r5 = [r for r in rows if phys_class(r["declared"]) or phys_class(r["target"])]
    print(f"\n=== R5: candidates over a physics-defined class ===")
    print(f"  {len(r5):,} of {len(rows):,}")
    for r in r5[:25]:
        print(f"    {r['decl']}  [{r['declared']}] -> {r['target']}")

    # --- allocation: per family, round-robin (§41) -------------------------------------
    fams = sorted(by_fam, key=lambda f: (dec[f], -len(by_fam[f]), f))
    for f in fams:
        by_fam[f].sort(key=lambda r: r["decl"])
    if args.all_remaining:
        chosen = [r for f in fams for r in by_fam[f]][:args.budget]
    else:
        chosen, rnd = [], 0
        while len(chosen) < args.budget and rnd < args.per_family:
            moved = False
            for f in fams:
                if len(by_fam[f]) > rnd and len(chosen) < args.budget:
                    chosen.append(by_fam[f][rnd])
                    moved = True
            if not moved:
                break
            rnd += 1

    fam_chosen = collections.Counter((r["declared"], r["target"]) for r in chosen)
    print(f"\n=== probe plan ===")
    print(f"  probes           : {len(chosen):,}")
    print(f"  families covered : {len(fam_chosen):,} of {len(by_fam):,} askable")

    # Names are emitted verbatim. `atlas_extract` already French-quotes a component that
    # needs it (`«term|_⟩»`), and Lean's `isLetterLike` covers the script letters physics
    # uses — `Dimension.L𝓭_mass` is a legal identifier, not a hazard. What is *not* legal
    # is whitespace or a bracket outside French quotes, so those are flagged rather than
    # silently emitted: a probe file that fails to parse takes the whole run with it, and
    # a name that cannot be probed is a candidate lost, which is the expensive direction.
    risky = [r for r in chosen
             if any(ch in r["decl"] for ch in " \t()[],")
             and "«" not in r["decl"]]
    if risky:
        print(f"  WARNING: {len(risky)} chosen names may not lex as identifiers:")
        for r in risky[:10]:
            print(f"    {r['decl']}")

    args.probe_out.parent.mkdir(parents=True, exist_ok=True)
    args.probe_out.write_text(
        HEADER + "\n"
        + "\n".join(f"#atlas_home_refute {r['decl']} {r['target']}" for r in chosen) + "\n")
    args.index.write_text(json.dumps({
        "probes": [{"decl": r["decl"], "declared": r["declared"], "target": r["target"]}
                   for r in chosen],
        "askable": len(askable), "unaskable": len(unaskable),
        "families_covered": len(fam_chosen),
        "families_new": sum(1 for f in fam_chosen if dec[f] == 0),
        "prediction": {
            "stratum_a": {"n": a_n, "mu": a_mu, "lo": a_lo, "hi": a_hi},
            "stratum_a_weak": {"n": aw_n, "mu": aw_mu, "lo": aw_lo, "hi": aw_hi},
            "stratum_b": {"n": b_n, "mu": b_mu, "lo": b_lo, "hi": b_hi},
            "pooled_mathlib_rate": pooled,
            "alpha": args.alpha,
        },
        "family_rates_mathlib": {f"{a}|{b}": [conf[(a, b)], dec[(a, b)]]
                                 for (a, b) in by_fam},
    }, indent=1))
    print(f"  -> {args.probe_out}")
    print(f"  -> {args.index}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True,
                    choices=("sweep", "control-unclosed", "screen", "plan", "selftest",
                             "verify-fast"))
    ap.add_argument("--slice", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-physlib-closure.jsonl"))
    ap.add_argument("--unclosed", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-physlib.jsonl"))
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/phys-candidates.json"))
    ap.add_argument("--screened", type=pathlib.Path,
                    default=pathlib.Path("/tmp/phys-screened.json"))
    ap.add_argument("--mathlib-candidates", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-gen-closure-candidates.json"))
    ap.add_argument("--mathlib-scored", type=pathlib.Path, nargs="*",
                    default=[pathlib.Path("/tmp/atlas-gen-scored-v2.json"),
                             pathlib.Path("/tmp/atlas-probeplan-scored.json"),
                             pathlib.Path("/tmp/atlas-proberest-scored.json")])
    ap.add_argument("--min-prior", type=int, default=3,
                    help="Mathlib decisive probes needed for a family to carry a rate")
    ap.add_argument("--alpha", type=float, default=4.0,
                    help="pseudo-probes of shrinkage toward the pooled rate; 4 minimises "
                         "Brier on the held-out Mathlib run (--stage selftest)")
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--per-family", type=int, default=4)
    ap.add_argument("--all-remaining", action="store_true")
    ap.add_argument("--probe-out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/phys-probe-plan.lean"))
    ap.add_argument("--index", type=pathlib.Path,
                    default=pathlib.Path("/tmp/phys-probe-index.json"))
    args = ap.parse_args()

    return {"sweep": stage_sweep, "control-unclosed": stage_control_unclosed,
            "screen": stage_screen, "plan": stage_plan,
            "selftest": stage_selftest,
            "verify-fast": stage_verify_fast}[args.stage](args)


if __name__ == "__main__":
    raise SystemExit(main())
