#!/usr/bin/env python3
"""Benchmark scoring functions by **retrieval**, not by pairwise separability.

§13 compared six formulas by ROC AUC over `generalize` on labelled pairs, and that measured
the wrong thing: a scorer's job is to put the right candidate near the top of a ranked list
for a *query*, not to separate a pair from a random pair. The two can disagree — a score can
separate well pairwise and still lose to the floors or to competing candidates in a real
ranking. Twice this session a pairwise improvement failed to become a retrieval improvement
(§9's arity transform, §12's null result), so the metric is the retrieval one.

For each labelled pair `(a, b)` the query is `a`, the correct answer is `b`, and the measure
is the rank of `b` in `similar(a)`. Reported as recall@1, @5, @10 and mean reciprocal rank
across the whole label set, for every (scorer, anchor) combination.

Label sets are declared in this file so a run cannot be tuned to them after the fact, and
each says where it came from — the ones I wrote and the ones Mathlib wrote are kept apart,
because a formula that only wins on the labels its author also wrote has not been measured.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

SCORES = ["retention", "min_normalised", "dice", "jaccard", "geometric_mean", "common",
          "info_weighted", "info_dice"]
ANCHORS = ["root", "conclusion"]

# --- Label set A: B7's Z/FF parallels. Written by me, so carries authorship bias --------
B7_PAIRS = [
    ("Validation.Z.euclid_lemma", "Validation.FF.poly_euclid_lemma"),
    ("Validation.Z.crt", "Validation.FF.poly_crt"),
    ("Validation.Z.gcd_comm", "Validation.FF.poly_gcd_comm"),
    ("Validation.Z.gcd_dvd_left", "Validation.FF.poly_gcd_dvd_left"),
    ("Validation.Z.gcd_dvd_right", "Validation.FF.poly_gcd_dvd_right"),
    ("Validation.Z.dvd_gcd", "Validation.FF.poly_dvd_gcd"),
    ("Validation.Z.irreducible_iff_prime", "Validation.FF.poly_irreducible_iff_prime"),
    ("Validation.Z.int_unique_factorization", "Validation.FF.poly_unique_factorization"),
    ("Validation.Z.bezout", "Validation.FF.poly_bezout"),
    ("Validation.Z.euclidean_division", "Validation.FF.poly_euclidean_division"),
    ("Validation.Z.int_division_via_norm", "Validation.FF.poly_division_via_norm"),
    ("Validation.Z.primes_infinite", "Validation.FF.poly_irreducibles_infinite"),
    ("Validation.Z.zeta_functional_equation", "Validation.FF.zeta_functional_equation"),
    # cross-cluster, less constructed: these were not written as a matched pair
    ("Validation.RH.zeros_on_critical_line", "Validation.LFamily.grh_zeros_on_line"),
    ("Validation.RH.zeros_on_critical_line", "Validation.Spectral.symmetric_eigenvalue_real"),
    ("Validation.RH.zeros_subset_critical_line", "Validation.FF.eigenvalues_subset_circle"),
    ("Validation.Positivity.intersection_positivity", "Validation.FF.castelnuovo_severi"),
    ("Validation.PairCorrelation.montgomery",
     "Validation.PairCorrelation.gue_eigenvalue_spacing"),
]

# --- Label set B: Mathlib's own families. Not written by me -----------------------------
MATHLIB_PAIRS = [
    ("Nat.add_comm", "Nat.mul_comm"), ("Nat.lcm_comm", "Nat.gcd_comm"),
    ("Nat.add_assoc", "Nat.mul_assoc"), ("Nat.add_zero", "Nat.mul_one"),
    ("Nat.zero_add", "Nat.one_mul"), ("Int.add_comm", "Int.mul_comm"),
    ("Nat.le_trans", "Int.le_trans"), ("Nat.le_refl", "Int.le_refl"),
    ("Nat.le_antisymm", "Int.le_antisymm"), ("Nat.gcd_comm", "Int.gcd_comm"),
    ("Nat.add_comm", "Int.add_comm"), ("Nat.mul_comm", "Int.mul_comm"),
    # the cross-notation seam, which is the regime the whole question is about
    ("g01_peano.add_comm", "Nat.add_comm"), ("g01_peano.add_comm", "Nat.gcd_comm"),
    ("g01_peano.zero_add", "Nat.zero_add"), ("g01_peano.add_zero", "Nat.add_zero"),
    ("g03_order.POrder.trans", "Preorder.le_trans"),
    ("g03_order.POrder.refl", "Preorder.le_refl"),
]

LABEL_SETS = {"B7 (self-authored)": B7_PAIRS, "Mathlib (independent)": MATHLIB_PAIRS}


def bench(corpus, pairs, score, anchor, top, floor, min_common):
    ranks = []
    for a, b in pairs:
        if corpus.get(a) is None or corpus.get(b) is None:
            continue
        try:
            nbs = corpus.similar(a, top=top, level="carriers", min_retention=floor,
                                 min_common=min_common, anchor=anchor, score=score)
        except Exception:
            ranks.append(None)
            continue
        r = next((i for i, nb in enumerate(nbs, 1) if nb.name == b), None)
        ranks.append(r)
    n = len(ranks)
    if n == 0:
        return None
    at = lambda k: sum(1 for r in ranks if r and r <= k) / n
    mrr = sum(1.0 / r for r in ranks if r) / n
    return {"n": n, "r@1": at(1), "r@5": at(5), "r@10": at(10), "mrr": mrr}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--labels", default=None, help="restrict to one label set by name")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--floor", type=float, default=0.02,
                    help="min_retention; low on purpose so the *ranking* is measured "
                         "rather than the floor")
    ap.add_argument("--min-common", type=int, default=2)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-score-bench.json"))
    args = ap.parse_args()

    c = fa.Corpus.load(str(args.slice))
    print(f"{len(c):,} declarations from {args.slice}")
    print(f"floor={args.floor} min_common={args.min_common} top={args.top}\n")

    report = {}
    for name, pairs in LABEL_SETS.items():
        if args.labels and args.labels not in name:
            continue
        present = [(a, b) for a, b in pairs
                   if c.get(a) is not None and c.get(b) is not None]
        if not present:
            print(f"--- {name}: no pairs present in this slice, skipped ---\n")
            continue
        print(f"--- {name}: {len(present)}/{len(pairs)} pairs present ---")
        print(f"  {'scorer':16s} {'anchor':11s} {'r@1':>6s} {'r@5':>6s} {'r@10':>6s} {'MRR':>6s}")
        best = None
        for score in SCORES:
            for anchor in ANCHORS:
                r = bench(c, present, score, anchor, args.top, args.floor, args.min_common)
                if r is None:
                    continue
                print(f"  {score:16s} {anchor:11s} {r['r@1']:6.2f} {r['r@5']:6.2f} "
                      f"{r['r@10']:6.2f} {r['mrr']:6.3f}")
                report[f"{name}|{score}|{anchor}"] = r
                if best is None or r["mrr"] > best[2]["mrr"]:
                    best = (score, anchor, r)
        if best:
            print(f"  -> best: {best[0]} / {best[1]} (MRR {best[2]['mrr']:.3f})\n")
    args.out.write_text(json.dumps(report, indent=1))
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
