#!/usr/bin/env python3
"""What is actually in the relationship layer? A survey, not a demo.

atlas.md's differentiator claim is that retrieval tools answer "find me a lemma" and none
answer "find me a relationship". This script asks what the relationship layer contains on a
real slice, and is written so that "almost nothing" is a reportable answer rather than an
embarrassing one.

Every section prints the *shape* of what it found before any example, because a survey that
opens with a hand-picked example is an advertisement. Where a result is dominated by one
uninteresting family, the script says so and shows the family.

Sections, each answering one question:

1. **Proved edges** — how many `Iff`/implication edges does the corpus actually state?
   This is the reformulation layer's raw material; if it is thin, everything built on it is
   thin, and no amount of query design fixes that.
2. **Reformulation hubs** — which heads accumulate edges? A hub is where a concept has many
   equivalent phrasings, which is where "state this differently" has somewhere to go.
3. **Equivalence classes** — sets of declarations whose statements normalize together. The
   interesting question is not how many, but *what they are*: duplicated API, `to_additive`
   pairs, or genuine reformulation.
4. **Analogy** — cross-theory `similar` hits, with the same-theory rate as the control. If
   cross-theory hits are as common as same-theory ones, "cross-theory" is not selecting.
5. **Frontier** — theory pairs that look alike and do not cite each other.
6. **Citation structure** — what the slice rests on, and how deep the load-bearing walls go.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import sys
import time

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

INFRA = ["Aesop", "Qq", "ProofWidgets", "Plausible", "Batteries", "Lean", "Init", "Std",
         "Cli", "ImportGraph", "LeanSearchClient", "Mathlib.Tactic", "Mathlib.Util",
         "Mathlib.Lean", "Mathlib.Testing", "Mathlib.Deprecated"]


def section(n: str) -> None:
    print(f"\n{'=' * 74}\n{n}\n{'=' * 74}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-relationships.json"))
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20260803)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    report: dict = {}

    t = time.time()
    c = fa.Corpus.load(str(args.slice))
    print(f"{len(c):,} declarations loaded in {time.time() - t:.1f} s")

    # -- 1. proved edges ---------------------------------------------------------------
    section("1. Proved edges — the reformulation layer's raw material")
    st = c.logical_stats()
    print(f"  theorems scanned      {st.theorems_scanned:,}")
    print(f"  edges extracted       {st.edges:,}")
    print(f"    of which Iff        {st.iff_edges:,}")
    print(f"    of which implication{st.implication_edges:,}")
    print(f"  distinct heads        {st.heads:,}")
    print(f"  prop-headed sides     {st.prop_heads:,}")
    print(f"  skipped: flex head    {st.flex_head_sides:,}  (bound-variable head — "
          f"needs higher-order matching, not looked at)")
    print(f"  skipped: non-prop     {st.non_prop_sides:,}")
    yield_rate = st.edges / max(st.theorems_scanned, 1)
    print(f"\n  edge yield            {100 * yield_rate:.2f}% of theorems state a relation")
    report["logical_stats"] = {
        "theorems": st.theorems_scanned, "edges": st.edges, "iff": st.iff_edges,
        "impl": st.implication_edges, "heads": st.heads,
        "flex_head_sides": st.flex_head_sides, "non_prop_sides": st.non_prop_sides,
        "yield": yield_rate,
    }

    # -- 2. hubs ------------------------------------------------------------------------
    section("2. Reformulation hubs — where equivalent phrasings accumulate")
    hubs = c.busiest_heads(top=25)
    print(f"  {'head':44s} {'arity':>5s} {'edges':>7s}")
    for h, arity, n in hubs:
        print(f"  {h[:44]:44s} {arity:5d} {n:7,}")
    report["hubs"] = [(h, a, n) for h, a, n in hubs]

    # -- 3. equivalence classes ---------------------------------------------------------
    section("3. Equivalence classes — and what they actually are")
    for level in ("exact", "instances", "carriers"):
        try:
            cls = c.classes(level=level, theorems_only=True)
        except Exception as e:
            print(f"  level={level}: {type(e).__name__}: {e}")
            continue
        sizes = [s for s, _ in cls]
        tot = sum(sizes)
        print(f"\n  level={level:12s} {len(cls):,} classes covering {tot:,} declarations"
              f"  (largest {max(sizes) if sizes else 0})")
        for size, members in cls[:6]:
            print(f"    [{size}] {', '.join(m[:34] for m in members[:5])}"
                  + (" …" if size > 5 else ""))
        report.setdefault("classes", {})[level] = {
            "count": len(cls), "covered": tot,
            "top": [(s, m[:8]) for s, m in cls[:20]],
        }

    # -- 4. analogy ---------------------------------------------------------------------
    section("4. Analogy — cross-theory hits, with same-theory as the control")
    names = [n for n in c.names() if (d := c.get(n)) and d.kind == "theorem" and d.stmt]
    rnd.shuffle(names)
    probe = names[:args.sample]
    cross = same = none_ = 0
    examples = []
    t = time.time()
    for n in probe:
        try:
            nbs = c.similar(n, top=10, level="carriers", min_retention=0.30, min_common=6)
        except Exception:
            continue
        if not nbs:
            none_ += 1
            continue
        mine = (c.get(n).module or "").split(".")[:2]
        xs = [b for b in nbs if (b.module or "").split(".")[:2] != mine]
        if xs:
            cross += 1
            if len(examples) < 15:
                examples.append((n, xs[0].name, round(xs[0].score, 3),
                                 round(xs[0].retention, 3)))
        else:
            same += 1
    print(f"  probed {len(probe):,} theorems in {time.time() - t:.1f} s")
    print(f"    no neighbour at all        {none_:,} ({100*none_/max(len(probe),1):.1f}%)")
    print(f"    only same-theory neighbours{same:,} ({100*same/max(len(probe),1):.1f}%)")
    print(f"    has a cross-theory hit     {cross:,} ({100*cross/max(len(probe),1):.1f}%)")
    print("\n  sample cross-theory hits:")
    for a, b, s, r in examples:
        print(f"    {a[:38]:38s} ~ {b[:38]:38s} score {s} ret {r}")
    report["analogy"] = {"probed": len(probe), "none": none_, "same": same,
                         "cross": cross, "examples": examples}

    # -- 5. frontier --------------------------------------------------------------------
    section("5. Frontier — theory pairs that look alike and do not cite each other")
    for label, exclude in (("unrestricted (control)", ()), ("mathematics only", INFRA)):
        try:
            fr = c.frontier(min_theory_size=200, top=12, theorems_only=True,
                            exclude=list(exclude))
        except Exception as e:
            print(f"  {label}: {type(e).__name__}: {e}")
            continue
        print(f"\n  {label}: {len(fr)} pairs")
        for p in fr:
            print(f"    {p.left[:26]:26s} ~ {p.right[:26]:26s} sim {p.similarity:.3f} "
                  f"cross-cites {p.cross_citations:5d}  sizes {p.left_size}/{p.right_size}")
        report.setdefault("frontier", {})[label] = [
            (p.left, p.right, p.similarity, p.cross_citations, p.left_size, p.right_size)
            for p in fr]

    # -- 6. citation structure ----------------------------------------------------------
    section("6. Citation structure — what the slice rests on")
    for lens in ("statement", "proof"):
        w = c.walls(lens=lens, top=12)
        print(f"\n  walls --lens {lens}:")
        for n, k in w:
            print(f"    {k:7,}  {n}")
        report.setdefault("walls", {})[lens] = w

    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
