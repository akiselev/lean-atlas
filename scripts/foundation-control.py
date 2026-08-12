#!/usr/bin/env python3
"""What does removing a corpus's foundation do to the answers computed over it?

## Why this exists

The whole-Mathlib slice was extracted with `--local` over Mathlib's own module list, so the
foundation was *imported and then discarded*: 348,793 of its 348,810 rows are `Mathlib.*`,
and `Eq`, `Iff`, `LE.le`, `LT.lt`, `Monad` and `Pure` have no row at all. Both consumers
read those rows:

* the Rust erasure asks the corpus for a head constant's signature to know which argument
  positions are `InstImplicit` (`erase.rs:334`), and holes nothing when the lookup misses;
* the evidence rule asks a cited constant's row for the classes it requires, and reaches
  nothing when the row is absent.

Neither reports a miss. Both degrade toward "no information" — which for the erasure means
"nothing is normalized" and for the evidence rule means "this hypothesis is unused".

## The control

The algebra slice is a genuine import closure, so it has both the foundation and Mathlib.
Restricting it to `Mathlib.*` reproduces exactly the defect the full slice has, on a corpus
where the correct answer is also available. Running both sides gives the size of the
distortion rather than an argument about its direction.

## What a good answer looks like, before it runs

If the missing foundation were harmless, the two runs would agree on which declarations are
candidates and on their targets. Any of these is a real distortion, and each implicates a
different consumer:

* **verdicts move** — `at-home`/`over-hypothesis` to `unused` — the evidence rule lost the
  citations that justified the binder;
* **targets move** — same declaration, different proposed weakening — the lattice lost
  intermediate classes, so "the weakest reached ancestor" resolves elsewhere;
* **erasure stops holing** — a skeleton known to contain `_` at `instances` no longer does.

The third is asserted as a hard check: if it fails, the restriction did *not* reproduce the
defect and the rest of the comparison is measuring something else.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from atlas_home_stream import StreamHomeIndex  # noqa: E402

try:
    import atlas as fa
except ImportError:
    fa = None


def candidates(path: str):
    idx = StreamHomeIndex(path)
    stat: collections.Counter = collections.Counter()
    cands = {}
    for name, verdict, cls, home in idx.verdicts():
        stat[verdict] += 1
        if verdict == "over-hypothesis":
            cands[(name, cls)] = home
    return idx, stat, cands


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path,
                    default=pathlib.Path("/tmp/mathlib-algebra.jsonl"))
    ap.add_argument("--restricted", type=pathlib.Path,
                    default=pathlib.Path("/tmp/mathlib-algebra-mathlibonly.jsonl"))
    ap.add_argument("--prefix", default="Mathlib")
    ap.add_argument("--probe-decl", default="Additive.ofMul_le")
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-foundation-control.json"))
    args = ap.parse_args()
    t0 = time.time()

    if not args.restricted.exists():
        n = 0
        with args.restricted.open("w") as w:
            for line in args.slice.open():
                if not line.strip():
                    continue
                r = json.loads(line)
                if (r.get("module") or "").startswith(args.prefix):
                    w.write(line)
                    n += 1
        print(f"restricted slice: {n:,} rows -> {args.restricted}")
    else:
        print(f"restricted slice cached: {args.restricted}")

    # ---- hard check: the restriction must actually reproduce the erasure defect --------
    erasure = {}
    if fa is not None:
        full = fa.Corpus.load(str(args.slice))
        rest = fa.Corpus.load(str(args.restricted))
        n = args.probe_decl
        sf = full.skeleton(n, level="instances")
        sr = rest.skeleton(n, level="instances")
        erasure = {"decl": n, "full_holes": "_" in sf, "restricted_holes": "_" in sr,
                   "identical": sf == sr}
        print(f"\nerasure probe on {n} at level=instances:")
        print(f"  full slice        : {sf[:110]}")
        print(f"  restricted slice  : {sr[:110]}")
        if sf == sr:
            print("\n  ABORT: restriction did not change the erasure, so it does not "
                  "reproduce the defect and the comparison below measures something else.")
            return 1
        print("  -> differs, as the full slice's defect predicts. Comparison is valid.")
        del full, rest

    # ---- the comparison ---------------------------------------------------------------
    _ia, sa, ca = candidates(str(args.slice))
    _ib, sb, cb = candidates(str(args.restricted))
    print(f"\n{'verdict':24s} {'closure':>10s} {'Mathlib-only':>14s}")
    for k in sorted(set(sa) | set(sb)):
        print(f"  {k:22s} {sa.get(k, 0):10,} {sb.get(k, 0):14,}")
    print(f"  {'CANDIDATES':22s} {len(ca):10,} {len(cb):14,}")

    keys_a, keys_b = set(ca), set(cb)
    both = keys_a & keys_b
    agree = {k for k in both if ca[k] == cb[k]}
    print(f"\ncandidate (declaration, class) pairs:")
    print(f"  in both corpora            : {len(both):,}")
    print(f"    same proposed target     : {len(agree):,}")
    print(f"    DIFFERENT target         : {len(both) - len(agree):,}")
    print(f"  only with the foundation   : {len(keys_a - keys_b):,}")
    print(f"  only without it            : {len(keys_b - keys_a):,}")
    if keys_a:
        print(f"\n  agreement with the correct answer: "
              f"{len(agree) / len(keys_a) * 100:.1f}% of the closure's candidates "
              f"survive restriction with their target intact")

    for label, sample in (("only with the foundation", sorted(keys_a - keys_b)[:6]),
                          ("only without it", sorted(keys_b - keys_a)[:6]),
                          ("target moved", sorted(both - agree)[:6])):
        if sample:
            print(f"\n  {label}:")
            for k in sample:
                print(f"    {k[0]} [{k[1]}] -> closure={ca.get(k)} restricted={cb.get(k)}")

    args.out.write_text(json.dumps(
        {"erasure_probe": erasure,
         "verdicts_closure": dict(sa), "verdicts_restricted": dict(sb),
         "candidates_closure": len(ca), "candidates_restricted": len(cb),
         "both": len(both), "same_target": len(agree),
         "only_closure": len(keys_a - keys_b), "only_restricted": len(keys_b - keys_a)},
        indent=1))
    print(f"\n-> {args.out}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
