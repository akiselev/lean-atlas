#!/usr/bin/env python3
"""Gate: is a slice closed under the constants its statements mention?

An unclosed slice does not fail. It answers, with a normalization that quietly did not
happen — `erase_spine` looks a head constant up to learn which of its argument positions are
`InstImplicit`, and a head the slice lacks holes nothing and degrades that spine to
`presentation`. Every downstream quantity is computed over the result.

That is why this is a gate and not a report. It runs on two corpora and asserts opposite
verdicts:

* the **algebra slice** is a genuine import closure and must pass;
* the same slice restricted to `Mathlib.*` reproduces exactly the defect the `--local`
  extraction has, and must **fail**.

Without the second case the check could be vacuous — a threshold no corpus can miss is not a
check — and this repo has shipped a dead normalization behind a green suite before (§5's
source B). The control is the point.

`--slice` runs the check on one corpus and exits non-zero below `--min-coverage`; with no
arguments it runs the paired gate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

ALGEBRA = pathlib.Path("/tmp/mathlib-algebra.jsonl")
RESTRICTED = pathlib.Path("/tmp/mathlib-algebra-mathlibonly.jsonl")


def report(path: pathlib.Path, top: int = 12):
    c = fa.Corpus.load(str(path))
    known, unknown, coverage, worst = c.closure(top=top)
    print(f"{path.name}: {len(c):,} declarations")
    print(f"  application heads  : {known + unknown:,}")
    print(f"  with a signature   : {known:,}")
    print(f"  missing            : {unknown:,}")
    print(f"  COVERAGE           : {coverage * 100:.2f}%")
    if worst:
        print(f"  most-cited missing : "
              + ", ".join(f"{n} ({df:,})" for n, df in worst[:8]))
    return {"slice": str(path), "declarations": len(c), "known": known,
            "unknown": unknown, "coverage": coverage,
            "worst": [{"name": n, "statements": df} for n, df in worst]}


def restrict(src: pathlib.Path, dst: pathlib.Path, prefix: str = "Mathlib") -> None:
    if dst.exists():
        return
    with dst.open("w") as w:
        for line in src.open():
            if line.strip() and (json.loads(line).get("module") or "").startswith(prefix):
                w.write(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path)
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-slice-closure.json"))
    args = ap.parse_args()
    t0 = time.time()

    if args.slice:
        r = report(args.slice)
        args.out.write_text(json.dumps(r, indent=1))
        ok = r["coverage"] >= args.min_coverage
        print(f"\n{'PASS' if ok else 'FAIL'} — coverage "
              f"{r['coverage'] * 100:.2f}% against a {args.min_coverage * 100:.0f}% floor")
        if not ok:
            print("  Extract the import closure: drop `--local`, which filters the "
                  "extractor's output rather than its import.")
        return 0 if ok else 1

    if not ALGEBRA.exists():
        sys.exit(f"{ALGEBRA} not found — see CLAUDE.md §4 for the extraction command")
    restrict(ALGEBRA, RESTRICTED)

    print("=== positive: a genuine import closure ===")
    good = report(ALGEBRA)
    print("\n=== negative control: the same slice with its foundation removed ===")
    bad = report(RESTRICTED)

    print(f"\n=== gate ({time.time() - t0:.0f}s) ===")
    ok_pos = good["coverage"] >= args.min_coverage
    ok_neg = bad["coverage"] < args.min_coverage
    print(f"  closure passes the floor      : {ok_pos}  "
          f"({good['coverage'] * 100:.2f}% >= {args.min_coverage * 100:.0f}%)")
    print(f"  restricted slice is caught    : {ok_neg}  "
          f"({bad['coverage'] * 100:.2f}%)")
    args.out.write_text(json.dumps({"closure": good, "restricted": bad,
                                    "min_coverage": args.min_coverage}, indent=1))
    if not (ok_pos and ok_neg):
        print("\nFAIL — the check is not discriminating and cannot be trusted.")
        return 1
    print(f"\nPASS -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
