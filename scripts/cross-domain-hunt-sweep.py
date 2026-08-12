#!/usr/bin/env python3
"""Cross-theory dictionary sweep over the 95,268-row physics corpus, one arm per process.

    uv run hunt-sweep.py --arm on    # posting_work_budget = 2000 (the repaired channel)
    uv run hunt-sweep.py --arm off   # shipped cutoff (budget = None)

Theory partition: top-level module prefix (the corpus /tmp/pfx-base.jsonl already has the
Physlib./QuantumInfo. roots stripped, so each physics subfield is its own theory —
scripts/phys-prefilter.py prepare_base). Eligibility: >= 50 declarations on both sides,
excluding the non-physlib infrastructure roots (Mathlib, Init, Lean, Std, Batteries, Aesop).

Direction: one call per unordered pair, left = the side with fewer theorems (tie:
alphabetical), identical in both arms so the row sets are comparable. `dictionary`
iterates left theorems, so this is also the cheap direction; the asymmetry is reported,
not hidden.

Everything else is the shipped call: per_decl=1, theorems_only=True, score=retention,
anchor="conclusion" (physlib-prefilter.md: root-anchored cross-theory dictionaries are
empty where it matters).

Progress goes to a JSONL work file per pair, so a crash loses one pair, not the sweep.
A --max-seconds guard stops cleanly and records coverage — no silent truncation.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

import atlas as fa

BASE = pathlib.Path("/tmp/pfx-base.jsonl")
SCRATCH = pathlib.Path(os.environ.get("HUNT_DIR", "."))  # work dir for hunt-*.json
W = 2_000  # physlib-prefilter.md §10's reference point, as in scripts/phys-budget-check.py

NON_PHYSLIB = {"Mathlib", "Init", "Lean", "Std", "Batteries", "Aesop"}
MIN_DECLS = 50

NAME_RE = re.compile(r'"name":"((?:[^"\\]|\\.)*)"')
MODULE_RE = re.compile(r'"module":"((?:[^"\\]|\\.)*)"')
KIND_RE = re.compile(r'"kind":"([a-z]*)"')


def census() -> dict[str, list[int]]:
    """theory -> [declarations, theorems], by top-level module prefix."""
    out: dict[str, list[int]] = {}
    for line in BASE.open():
        if not line.strip():
            continue
        m = MODULE_RE.search(line)
        k = KIND_RE.search(line)
        top = (m.group(1).split(".")[0] if m else "") or ""
        if not top:
            continue
        row = out.setdefault(top, [0, 0])
        row[0] += 1
        if k and k.group(1) == "theorem":
            row[1] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["on", "off"], required=True)
    ap.add_argument("--max-seconds", type=int, default=6 * 3600)
    args = ap.parse_args()
    budget = W if args.arm == "on" else None

    work = SCRATCH / f"hunt-{args.arm}.work.jsonl"
    final = SCRATCH / f"hunt-{args.arm}.json"
    done_pairs: set[str] = set()
    if work.exists():
        for line in work.open():
            try:
                done_pairs.add(json.loads(line)["pair"])
            except Exception:
                pass

    t0 = time.time()
    cens = census()
    print(f"census: {len(cens)} top-level theories, {time.time()-t0:.0f}s", flush=True)

    theories = {
        t: (d, th)
        for t, (d, th) in cens.items()
        if t not in NON_PHYSLIB and d >= MIN_DECLS
    }
    names = sorted(theories)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            # left = fewer theorems; the tie-break keeps both arms on one direction.
            la, lb = theories[a][1], theories[b][1]
            left, right = (a, b) if (la, a) <= (lb, b) else (b, a)
            pairs.append((left, right))
    print(f"eligible theories: {len(names)}; unordered pairs: {len(pairs)}", flush=True)

    t = time.time()
    c = fa.Corpus.load(str(BASE))
    load_s = time.time() - t
    print(f"loaded {len(c)} declarations in {load_s:.1f}s", flush=True)

    covered = 0
    stopped_early = False
    with work.open("a") as out:
        for left, right in pairs:
            key = f"{left} ~ {right}"
            if key in done_pairs:
                covered += 1
                continue
            if time.time() - t0 > args.max_seconds:
                stopped_early = True
                print(f"STOPPING at --max-seconds; covered {covered}/{len(pairs)}", flush=True)
                break
            t = time.time()
            try:
                d = c.dictionary(
                    left,
                    right,
                    per_decl=1,
                    theorems_only=True,
                    anchor="conclusion",
                    posting_work_budget=budget,
                )
                rows = [
                    {
                        "left": r.left,
                        "right": r.right,
                        "retention": round(r.retention, 4),
                        "status": r.status,
                    }
                    for r in d.rows
                ]
                rec = {
                    "pair": key,
                    "rows": rows,
                    "n_rows": len(rows),
                    "missing_left": len(d.missing_left),
                    "missing_right": len(d.missing_right),
                    "s": round(time.time() - t, 1),
                }
            except Exception as e:  # a pair that raises is a datum, not a crash
                rec = {"pair": key, "error": f"{type(e).__name__}: {e}",
                       "s": round(time.time() - t, 1)}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            covered += 1
            print(f"[{covered}/{len(pairs)}] {key}: "
                  f"{rec.get('n_rows', 'ERR')} rows in {rec['s']}s", flush=True)

    by_pair = {}
    for line in work.open():
        r = json.loads(line)
        by_pair[r["pair"]] = r
    result = {
        "arm": args.arm,
        "posting_work_budget": budget,
        "slice": str(BASE),
        "declarations": len(c),
        "load_s": round(load_s, 1),
        "min_decls": MIN_DECLS,
        "excluded_roots": sorted(NON_PHYSLIB),
        "theories": {t: {"decls": d, "theorems": th} for t, (d, th) in sorted(theories.items())},
        "direction_rule": "left = fewer theorems, tie alphabetical",
        "pairs_total": len(pairs),
        "pairs_covered": len(by_pair),
        "stopped_early": stopped_early,
        "wall_s": round(time.time() - t0, 1),
        "pairs": by_pair,
    }
    final.write_text(json.dumps(result, ensure_ascii=False))
    print(f"wrote {final} — covered {len(by_pair)}/{len(pairs)}, wall {result['wall_s']}s",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
