#!/usr/bin/env python3
"""Candidate generalizations over a slice too large for `generalization-run.py`.

Same evidence rule, streamed. Two things this script does that the in-memory one cannot:

* `--verify <small-slice>` runs both implementations on a slice that fits and asserts the
  candidate sets are **identical**. A streaming rewrite that quietly judged differently
  would be indistinguishable from a real change in the answer, so this runs first and the
  script exits non-zero if they disagree.
* `--restrict-to` keeps candidates whose declaration lives in a named module prefix, so the
  expensive downstream stages can be pointed at a region without re-running the sweep.

The novelty screen is *not* here: `fa.Corpus.load` on the full slice is a separate memory
question, and the point of this stage is to learn how many candidates the other 62% of
Mathlib contributes before paying for it.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import resource
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import atlas_home  # noqa: E402
from atlas_home_stream import StreamHomeIndex  # noqa: E402


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def stream_candidates(path: str, t0: float, quiet: bool = False):
    def prog(tag):
        return None if quiet else (lambda i: print(
            f"  [{tag}] {i:,} rows  {rss_gb():.1f} GB  {time.time() - t0:.0f}s", flush=True))

    idx = StreamHomeIndex(path, progress=prog("scan"))
    if not quiet:
        print(f"lattice: {len(idx.classes):,} classes, "
              f"{sum(len(v) for v in idx.parents.values()):,} edges, "
              f"{len(idx.forgetful):,} forgetful  "
              f"[{idx.parse_errors:,} unparseable]  {rss_gb():.1f} GB", flush=True)

    stat: collections.Counter = collections.Counter()
    cands = []
    for name, verdict, cls, home in idx.verdicts(progress=prog("judge")):
        stat[verdict] += 1
        if verdict == "over-hypothesis":
            cands.append((name, cls, home))
    return idx, stat, cands


def inmemory_candidates(path: str):
    """`generalization-run.py`'s path, for the differential check."""
    rows = {}
    with open(path) as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rows[r["name"]] = r
    idx = atlas_home.HomeIndex(rows)
    out = []
    for n, r in rows.items():
        if r.get("kind") != "theorem":
            continue
        v = idx.home(n)
        if v is None or "skipped" in v or v["projection_like"]:
            continue
        for b in v["binders"]:
            if b["verdict"] == "over-hypothesis" and b.get("home"):
                out.append((n, b["class"], b["home"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--verify", type=pathlib.Path,
                    help="slice to cross-check the streaming rule against the in-memory one")
    ap.add_argument("--restrict-to", nargs="*", default=None,
                    help="keep candidates whose module starts with one of these")
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-gen-full-candidates.json"))
    args = ap.parse_args()
    t0 = time.time()

    if args.verify:
        print(f"=== differential: streaming vs in-memory on {args.verify.name} ===",
              flush=True)
        _i, _s, streamed = stream_candidates(str(args.verify), t0, quiet=True)
        mem = inmemory_candidates(str(args.verify))
        a, b = set(streamed), set(mem)
        print(f"  streaming : {len(a):,} candidates")
        print(f"  in-memory : {len(b):,} candidates")
        if a != b:
            print(f"  DISAGREE  : {len(a - b):,} only-streaming, {len(b - a):,} only-memory")
            for x in sorted(a - b)[:5]:
                print(f"    +{x}")
            for x in sorted(b - a)[:5]:
                print(f"    -{x}")
            return 1
        print(f"  IDENTICAL — streaming rule verified ({time.time() - t0:.0f}s)\n", flush=True)

    print(f"=== sweep: {args.slice} ===", flush=True)
    idx, stat, cands = stream_candidates(str(args.slice), t0)
    print(f"\nverdicts ({time.time() - t0:.0f}s, peak {rss_gb():.1f} GB):")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v:9,}")
    print(f"  {'CANDIDATES':24s} {len(cands):9,}")

    if args.restrict_to:
        before = len(cands)
        cands = [c for c in cands
                 if any((idx.module.get(c[0]) or "").startswith(p) for p in args.restrict_to)]
        print(f"\nrestricted to {args.restrict_to}: {len(cands):,} of {before:,}")

    by_mod = collections.Counter(
        (idx.module.get(n) or "?").split(".")[0] for n, _c, _h in cands)
    print(f"\ncandidates by top-level module:")
    for k, v in by_mod.most_common(12):
        print(f"  {k:24s} {v:9,}")

    by_pair = collections.Counter((c, h) for _n, c, h in cands)
    print(f"\nmost common (declared -> target) weakenings:")
    for (c, h), v in by_pair.most_common(15):
        print(f"  {v:6,}  {c} -> {h}")

    args.out.write_text(json.dumps(
        {"slice": str(args.slice), "stat": dict(stat), "candidates": len(cands),
         "rows": [{"decl": n, "declared": c, "target": h,
                   "module": idx.module.get(n)} for n, c, h in cands]}, indent=1))
    print(f"\n-> {args.out}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
