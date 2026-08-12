#!/usr/bin/env python3
"""Group candidates by the pattern they share with a query, instead of ranking them.

## The argument

Anti-unification computes a *pattern* — `?R a b -> ?R b c -> ?R a c` — plus the
substitutions specialising it to each side. That is the structural content. The ranking
pipeline collapses it to one float and sorts, discarding *how* two statements are alike and
keeping *how much*, which is the less useful question and the one this session could not get
to work: eight scoring formulas, MRR 0.16-0.30, differences inside noise.

Meanwhile every result that held up came from exact structure rather than a score —
statement identity (`POrder.refl == Preorder.le_refl`), proved `Iff` edges, aggregate
frontier similarity.

So: for a query, compute the lgg against every candidate and **partition candidates by the
skeleton they share**. No floor, no formula, no arbitrary `k`. The output is a set of
families, each with its shared pattern written out, which is what an agent triaging
thousands of candidates actually needs — it can discard a whole family at a glance instead
of scanning a ranked list.

## What a good answer looks like, before the run

For `g01_peano.add_comm` the corpus contains a commutativity family (`Nat.lcm_comm`,
`Nat.gcd_comm`, `Int.gcd_comm`, ...). A useful grouping puts those in **one** group under a
pattern that is recognisably `?f a b = ?f b a`, and puts the unrelated matches in other
groups. A useless grouping either lumps everything together or splits every candidate into
its own singleton — both are reported, since either would settle the question.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")


def groups_for(c, query, anchor, level, top, floor, min_common):
    """Candidates for `query`, partitioned by the skeleton each shares with it."""
    try:
        nbs = c.similar(query, top=top, level=level, min_retention=floor,
                        min_common=min_common, anchor=anchor)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    by: dict[str, list] = collections.defaultdict(list)
    for nb in nbs:
        by[nb.skeleton].append(nb)
    # Order groups by how much structure the pattern carries, then by size: a family
    # sharing a large pattern is a stronger statement than a large family sharing little.
    ordered = sorted(by.items(),
                     key=lambda kv: (-max(n.common for n in kv[1]), -len(kv[1])))
    return ordered, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--queries", nargs="*", default=[
        "g01_peano.add_comm", "g03_order.POrder.trans", "Nat.add_comm", "Nat.gcd_comm"])
    ap.add_argument("--anchor", default="conclusion")
    ap.add_argument("--level", default="carriers")
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--floor", type=float, default=0.02)
    ap.add_argument("--min-common", type=int, default=2)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-structure-groups.json"))
    args = ap.parse_args()

    c = fa.Corpus.load(str(args.slice))
    print(f"{len(c):,} declarations; anchor={args.anchor} level={args.level} "
          f"top={args.top}\n")
    report = {}
    for q in args.queries:
        if c.get(q) is None:
            print(f"=== {q}: not in slice ===\n")
            continue
        ordered, err = groups_for(c, q, args.anchor, args.level, args.top, args.floor,
                                  args.min_common)
        if err:
            print(f"=== {q}: {err} ===\n")
            continue
        n = sum(len(v) for _k, v in ordered)
        print(f"=== {q} — {n} candidates in {len(ordered)} structural groups ===")
        singletons = sum(1 for _k, v in ordered if len(v) == 1)
        for skel, members in ordered[:6]:
            common = max(m.common for m in members)
            names = ", ".join(m.name.split(".")[-1][:24] for m in members[:6])
            print(f"  [{len(members):3d} members, {common:3d} shared nodes] {names}"
                  + (" ..." if len(members) > 6 else ""))
            print(f"       pattern: {skel[:150]}")
        print(f"  ({singletons} singleton groups of {len(ordered)})\n")
        report[q] = {
            "candidates": n, "groups": len(ordered), "singletons": singletons,
            "top": [{"size": len(v), "common": max(m.common for m in v),
                     "skeleton": k, "members": [m.name for m in v[:12]]}
                    for k, v in ordered[:10]],
        }
    args.out.write_text(json.dumps(report, indent=1))
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
