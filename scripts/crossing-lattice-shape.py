#!/usr/bin/env python3
"""Crossing 1: the instance lattice against statement shape.

## Why a crossing rather than a signal

Bound minimization on its own re-derives what Mathlib's `#lint` generalization checks
already do, and Mathlib runs those. Anti-unification on its own is similarity without a
warrant. Neither will find something a mathematician missed for a decade, and a tool that
claims otherwise from one signal is selling noise.

What is not routine is the *conjunction*, because the two signals here are derived from
disjoint evidence:

**Signal L (lattice).** From the citation graph: the classes a declaration's cited
constants require, walked down the typeclass hierarchy. Never looks at the statement's
shape.

**Signal S (shape).** From the statement encoding: two theorems land in one equivalence
class at the `instances` level exactly when their statements agree once instance arguments
are erased. If they then *declare* different classes, one of them is proving the same
thing under a stronger hypothesis. Never looks at the citation graph.

A declaration flagged by both is flagged by two methods that share no input, which is a
much stronger position than either alone. A declaration flagged by one and cleared by the
other is not noise to discard — it is where a method is wrong, and it localizes which one.
That disagreement already paid once: L reported `Add` unused for `AddOpposite.op_add`,
whose statement is an addition, and the disagreement located a severed instance path.

## What a good answer looks like, stated before the run

1. Signal S must find classes whose members declare *different* strengths. If every
   equivalence class is binder-uniform, S carries no information and the crossing is empty
   for reasons that have nothing to do with L.
2. The agreement set (L and S both flag) must be **smaller** than either signal alone —
   a conjunction that does not narrow is not a conjunction.
3. The disagreement sets must be non-empty and inspectable, because their whole purpose is
   to localize which method is wrong.
4. The negative control: pairing each L-flagged declaration with a *random* equivalence
   class must not reproduce the agreement rate. If it does, the agreement is an artifact of
   how many things each signal flags rather than of the two agreeing about anything.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import atlas_home  # noqa: E402

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--level", default="instances")
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-crossing-lattice-shape.json"))
    ap.add_argument("--seed", type=int, default=20260803)
    args = ap.parse_args()

    rows = {}
    t = time.time()
    with args.slice.open() as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rows[r["name"]] = r
    print(f"{len(rows):,} rows read in {time.time() - t:.1f} s")

    # ---- Signal L ------------------------------------------------------------------
    t = time.time()
    idx = atlas_home.HomeIndex(rows)
    L: dict[str, list] = {}
    judged_names: set[str] = set()
    for n, r in rows.items():
        if r.get("kind") != "theorem":
            continue
        v = idx.home(n)
        if v is None or "skipped" in v:
            continue
        judged_names.add(n)
        if v["projection_like"]:
            continue
        weak = [b for b in v["binders"] if b["verdict"] in ("over-hypothesis", "unused")]
        if weak:
            L[n] = weak
    judged = len(judged_names)
    print(f"signal L: {len(L):,} flagged of {judged:,} judged  ({time.time() - t:.1f} s)")

    # ---- Signal S ------------------------------------------------------------------
    t = time.time()
    c = fa.Corpus.load(str(args.slice))
    classes = c.classes(level=args.level, theorems_only=True)
    print(f"  {len(classes):,} equivalence classes at level={args.level} "
          f"({time.time() - t:.1f} s)")

    S: dict[str, dict] = {}
    uniform = 0
    for size, members in classes:
        # The declared instance-binder classes of each member.
        decl = {m: tuple(sorted({cls for cls, _ in idx.instance_binders(m)}))
                for m in members if m in idx.binders}
        distinct = {v for v in decl.values() if v}
        if len(distinct) < 2:
            uniform += 1
            continue
        # Rank members by how strong their declared binders are: a member is *stronger*
        # than another when every class the other declares is an ancestor-or-equal of one
        # this member declares, and the two are not the same set.
        for m, mine in decl.items():
            if not mine:
                continue
            weaker_siblings = []
            for o, theirs in decl.items():
                if o == m or not theirs or theirs == mine:
                    continue
                if all(any(t == s or t in idx.ancestors(s) for s in mine) for t in theirs):
                    weaker_siblings.append((o, theirs))
            if weaker_siblings:
                S[m] = {"declares": list(mine), "class_size": size,
                        "weaker": [{"name": o, "declares": list(t)}
                                   for o, t in weaker_siblings[:5]]}
    print(f"signal S: {len(S):,} flagged; {uniform:,} classes were binder-uniform "
          f"({time.time() - t:.1f} s)")

    # ---- The crossing ---------------------------------------------------------------
    both = sorted(set(L) & set(S))
    only_l = sorted(set(L) - set(S))
    only_s = sorted(set(S) - set(L))
    print()
    print(f"agree (L and S) : {len(both):,}")
    print(f"L only          : {len(only_l):,}")
    print(f"S only          : {len(only_s):,}")

    # ---- Negative control ------------------------------------------------------------
    #
    # The control must condition on the population where *both* signals could have fired.
    # An earlier version drew from the equivalence-class pool while L ranged over every
    # judged theorem — and since most judged theorems sit in no class at all, that compared
    # two different populations and made the crossing look worse than chance. The number it
    # produced was an artifact of the sampling frame, not a fact about the signals.
    #
    # So: restrict to declarations L actually judged *and* that sit in a class where S was
    # able to discriminate, then ask whether being L-flagged raises the odds of being
    # S-flagged above the base rate in that same population.
    eligible = {m for _s, ms in classes for m in ms if m in judged_names}
    if eligible:
        base = len(set(S) & eligible) / len(eligible)
        l_in = set(L) & eligible
        lift = (len(set(S) & l_in) / len(l_in)) if l_in else 0.0
        print()
        print(f"control population : {len(eligible):,} declarations L judged and in a class")
        print(f"  base rate P(S)          = {base:.4f} "
              f"({len(set(S) & eligible):,}/{len(eligible):,})")
        print(f"  P(S | L flagged)        = {lift:.4f} "
              f"({len(set(S) & l_in):,}/{len(l_in):,})")
        print(f"  lift                    = {(lift / base) if base else float('nan'):.2f}x "
              f"— above 1 means the signals agree more than chance")
        rnd = random.Random(args.seed)
        pool = sorted(eligible)
        draws = {rnd.choice(pool) for _ in range(len(l_in))} if l_in else set()
        print(f"  sham draw of the same size hits S {len(draws & set(S)):,} times "
              f"(genuine {len(set(S) & l_in):,})")

    # ---- What the agreement set actually says ---------------------------------------
    print()
    print("--- agreement set: both signals flag the same declaration ---")
    for n in both[:25]:
        lb = ", ".join(f"{b['class']}"
                       + (f"→{b['home']}" if b.get("home") else " unused")
                       for b in L[n])
        s = S[n]
        print(f"  {n[:52]:52s} L[{lb}]  S[declares {'+'.join(s['declares'])}, "
              f"weaker sibling {s['weaker'][0]['name'][:30]}]")

    print()
    print("--- disagreement: S flags, L clears (a shape says over-strong, "
          "citations say at home) ---")
    for n in only_s[:12]:
        s = S[n]
        print(f"  {n[:52]:52s} declares {'+'.join(s['declares'])} vs "
              f"{s['weaker'][0]['name'][:34]} ({'+'.join(s['weaker'][0]['declares'])})")

    payload = {
        "level": args.level,
        "counts": {"L": len(L), "S": len(S), "both": len(both),
                   "only_l": len(only_l), "only_s": len(only_s), "judged": judged},
        "agree": {n: {"L": L[n], "S": S[n]} for n in both},
        "only_s": {n: S[n] for n in only_s[:2000]},
        "only_l": {n: L[n] for n in only_l[:2000]},
    }
    args.out.write_text(json.dumps(payload, indent=1))
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
