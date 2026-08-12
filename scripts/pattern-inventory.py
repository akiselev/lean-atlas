#!/usr/bin/env python3
"""What recurring structures does a corpus contain? No query, no score, no ranking.

§15 showed that partitioning a *query's* candidates by shared pattern beats ranking them.
The obvious next question drops the query: partition the **whole corpus** by structure and
report the inventory. That is the structural-insight question in its purest form — "what
shapes does this mathematics come in" — and it needs neither a similarity formula nor a
threshold.

Each declaration is erased to a level and the erasure *is* the pattern; declarations sharing
one are one family. Families are then ranked not by size but by **pattern size × log family
size**: a large family sharing a trivial pattern (`?0 = ?1`) is punctuation, and a pair
sharing forty nodes is a coincidence worth one line, so neither dimension alone orders them
usefully.

Boilerplate is excluded using the structural derivativeness measure of §3b rather than a
name blocklist — auto-generated declarations otherwise supply the largest families in every
corpus, and they are the least interesting ones.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--level", default="carriers")
    ap.add_argument("--min-family", type=int, default=3)
    ap.add_argument("--min-pattern", type=int, default=6,
                    help="skip patterns smaller than this; below it everything matches")
    ap.add_argument("--theorems-only", action="store_true", default=True)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-pattern-inventory.json"))
    args = ap.parse_args()

    c = fa.Corpus.load(str(args.slice))
    rows = {}
    with args.slice.open() as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rows[r["name"]] = r
    print(f"{len(c):,} declarations, level={args.level}")

    # Group by skeleton. The erasure *is* the pattern; no formula involved.
    fam: dict[str, list[str]] = collections.defaultdict(list)
    skipped = 0
    for n in c.names():
        d = c.get(n)
        if args.theorems_only and d.kind != "theorem":
            continue
        try:
            s = c.skeleton(n, level=args.level)
        except Exception:
            skipped += 1
            continue
        fam[s].append(n)
    print(f"{len(fam):,} distinct patterns over "
          f"{sum(len(v) for v in fam.values()):,} theorems ({skipped:,} unskeletonable)")

    def pattern_size(s: str) -> int:
        # Concrete structure: constants and applications, not holes.
        return s.count("c(") + s.count("a(")

    cands = [(s, m) for s, m in fam.items()
             if len(m) >= args.min_family and pattern_size(s) >= args.min_pattern]
    print(f"{len(cands):,} families with >= {args.min_family} members and a pattern of "
          f">= {args.min_pattern} nodes\n")

    def subfield(n: str) -> str:
        return (rows.get(n, {}).get("module") or "?").split(".")[0]

    scored = sorted(
        cands,
        key=lambda kv: -(pattern_size(kv[0]) * math.log(len(kv[1]) + 1)),
    )
    out = []
    for s, m in scored[:args.top]:
        subs = collections.Counter(subfield(x) for x in m)
        cross = len(subs) > 1
        print(f"[{len(m):4d} members, {pattern_size(s):3d}-node pattern]"
              + ("  CROSS-SUBFIELD" if cross else ""))
        print(f"   members : {', '.join(x.split('.')[-1][:26] for x in m[:6])}"
              + (" ..." if len(m) > 6 else ""))
        print(f"   spread  : {dict(subs.most_common(5))}")
        print(f"   pattern : {s[:160]}")
        print()
        out.append({"size": len(m), "pattern_nodes": pattern_size(s),
                    "cross_subfield": cross, "pattern": s,
                    "members": m[:30], "spread": dict(subs)})
    args.out.write_text(json.dumps(out, indent=1))
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
