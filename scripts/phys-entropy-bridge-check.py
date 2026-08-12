#!/usr/bin/env python3
"""The §74 entropy-bridge gate, paired (findings §74, cross-domain-hunt.md §7).

The cross-domain hunt found an unregistered A-caliber correspondence — von Neumann
entropy nonnegativity against the Gibbs ensemble's Shannon entropy nonnegativity, no
citation link between the formalizations — and the pipeline manufactured its false
negative twice *after* retrieval got it right: `per_decl=1` winner-take-all handed the
slot to a content-free positivity lookalike (`0 ≤ Z`, retention 0.9412 against the
bridge's 0.684), and the scored rank key buried the family under apparatus mass.

This gate replays that scenario on the real corpus, one arm per invocation because the
conclusion-anchored index is ~7.4 GB resident:

    uv run scripts/phys-entropy-bridge-check.py --arm baseline   # bridge ABSENT (defect)
    uv run scripts/phys-entropy-bridge-check.py --arm repaired   # bridge PRESENT

Paired on purpose: the baseline arm asserts the burial still reproduces, so the repaired
arm's pass cannot come from the fixture having gone soft — if the bridge ever surfaces
with the knobs off, this script fails and the knobs' rationale needs re-measuring. The
repaired arm runs `rank_by_retention` + `per_decl_keep_displaced` (the §74 asks) and
must find both bridge rows in their dictionaries. T1-T4 regression is
`phys-budget-check.py --arm on --rank-by-retention --keep-displaced`, not this script.

Exits non-zero when the invoked arm misses its expectation. Every number printed is
measured in this process.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

try:
    import atlas as fa
except ImportError:  # pragma: no cover - the script is useless without it
    sys.exit("atlas is not importable — run under `uv run`")

BASE = pathlib.Path("/tmp/pfx-base.jsonl")

# The study's reference point, same as phys-budget-check.py: the bridge is budget-only,
# so both arms run with the budget ON — what separates them is the assembly knobs.
W = 2_000

# (left, right, left theory, right theory) — hunt JSON `posthoc_entropy_bridge`.
BRIDGES = [
    ("Sᵥₙ_nonneg", "CanonicalEnsemble.entropy_nonneg", "Entropy", "StatisticalMechanics"),
    ("Hₛ_nonneg", "CanonicalEnsemble.entropy_nonneg", "ClassicalInfo", "StatisticalMechanics"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["baseline", "repaired"], required=True)
    ap.add_argument("--slice", type=pathlib.Path, default=BASE)
    ap.add_argument("--budget", type=int, default=W)
    args = ap.parse_args()

    if not args.slice.exists():
        # A skipped gate says so; a green one that measured nothing would not.
        print(f"SKIPPED: no corpus at {args.slice}")
        return 0

    knobs = args.arm == "repaired"
    rec: dict = {
        "arm": args.arm,
        "posting_work_budget": args.budget,
        "rank_by_retention": knobs,
        "per_decl_keep_displaced": knobs,
        "slice": str(args.slice),
    }

    t = time.time()
    c = fa.Corpus.load(args.slice)
    rec["declarations"] = len(c)
    rec["load_s"] = round(time.time() - t, 1)

    ok = True
    out = {}
    for left, right, lth, rth in BRIDGES:
        entry: dict = {}

        # The retrieval fact both arms share: where `similar` puts the bridge, under the
        # engine's scored order and re-ranked by retention. Knob-free either way, so a
        # dictionary-side miss below is the assembly's fault, not retrieval's.
        ns = c.similar(
            left,
            top=10**7,
            level="carriers",
            anchor="conclusion",
            min_retention=0.30,
            min_common=6,
            posting_work_budget=args.budget,
        )
        entry["above_floors"] = len(ns)
        by_score = next((i + 1 for i, n in enumerate(ns) if n.name == right), None)
        rr = sorted(ns, key=lambda n: (-n.retention, -n.common, n.vars, n.name))
        by_ret = next((i + 1 for i, n in enumerate(rr) if n.name == right), None)
        entry["similar_rank_by_score"] = by_score
        entry["similar_rank_by_retention"] = by_ret
        if by_score is None:
            # Not proposed at all: no assembly knob can recover it, and the arm cannot
            # say anything about the §74 defect. That is a broken premise, not a verdict.
            print(f"PREMISE BROKEN: `{left} ~ {right}` is not proposed by similar")
            ok = False

        d = c.dictionary(
            lth,
            rth,
            per_decl=1,
            theorems_only=True,
            anchor="conclusion",
            posting_work_budget=args.budget,
            rank_by_retention=knobs,
            per_decl_keep_displaced=knobs,
        )
        entry["dictionary_rows"] = len(d.rows)
        hit = next(
            ((i + 1, r) for i, r in enumerate(d.rows) if r.left == left and r.right == right),
            None,
        )
        entry["bridge_row_rank"] = hit[0] if hit else None
        if hit:
            entry["bridge_row_retention"] = round(hit[1].retention, 4)
        # What won the left's slot instead (or as well) — §7's lookalike, named.
        entry["partners_of_left"] = [r.right for r in d.rows if r.left == left]

        expect_present = args.arm == "repaired"
        found = hit is not None
        entry["expected"] = "present" if expect_present else "absent"
        if found != expect_present:
            ok = False
        out[f"{left} ~ {right}"] = entry

    rec["bridges"] = out
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    print(
        f"VERDICT: {'PASS' if ok else 'FAIL'} — arm={args.arm}, "
        f"bridge rows expected {'present' if args.arm == 'repaired' else 'absent (defect reproduced)'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
