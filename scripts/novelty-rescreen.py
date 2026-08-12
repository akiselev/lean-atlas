#!/usr/bin/env python3
"""Re-run the novelty screen for confirmed generalizations against a whole closed corpus.

## The caveat this closes

The kernel-confirmed weakenings were screened for prior art against the 131k-declaration
algebra slice — a genuine import closure, but the closure of *one module*. "No general
version exists" therefore meant "none in the part we looked at". This re-runs the screen
against the 470,435-declaration whole-Mathlib closure of §35.

## Why the obvious shortcut is unsound

The first version of this script restricted the corpus to declarations sharing a candidate's
conclusion head, on the reasoning that a general version proves the same conclusion. The
filter is sound; loading the result is not. `Level::Instances` holes arguments in
`InstImplicit` positions *of the head constant's signature*, so dropping declarations drops
signatures and the erasure silently degrades toward the identity (§31). **The corpus must be
loaded whole.** `Corpus.closure()` is asserted first, so a slice that would degrade the
erasure is refused rather than screened against.

## Why `equivalent`, not a retention threshold

A general version differs from its candidate in **binder domains only** — that is what
"weaker hypothesis, same statement" means — and `Instances` holes exactly those. So prior
art is *equal* at that level, not merely similar, and `equivalent(level="instances")` is
the screen that matches the question.

Retention thresholding is not. Measured at the 0.85 floor it matched `div_le_iff₀'` to
`div_lt_iff₀` (the `<` version) and `npow_eq_pow` to `zpow_eq_pow` (natural against integer
power) — sibling lemmas, neither generalizing the other, differing in one constant out of
dozens.

## Sensitivity, measured

`scripts/screen-sensitivity.py` injects the row a general version *would* have and asks
whether the screen finds it: 40/40 for a version stated the obvious way, 40/40 for one with
the stronger class's coercion collapsed away, and 0 spurious hits on the un-injected
control. An earlier draft of this file predicted the second case would be missed; it is not,
because that coercion sits in an `InstImplicit` argument position and `Instances` holes it
either way.

On real data the screen finds prior art in 7.0% of kernel-confirmed weakenings —
`max_min_distrib_left` against `sup_inf_left`, `csSup_one` against `sSup_one` — so it is
neither vacuous nor merely theoretical.

What it still cannot see is a general version stated in a structurally *different* form: a
different variable order, an `Iff` where the candidate is an implication, a formulation
equivalent but not equal. That bound is unmeasured.
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
from atlas_home import telescope  # noqa: E402

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def lattice(c, t0: float) -> dict[str, set]:
    """The typeclass lattice, from parent projections, without re-parsing the slice.

    `CommRing.toRing` requires `CommRing` and concludes something headed by `Ring`, which
    is the edge `CommRing -> Ring`. `Corpus.requires` gives the left side straight from the
    arena; only the conclusion head still needs the encoding, and only for declarations
    whose name carries `.to`.

    This used to telescope all 470,435 statements in Python to build the same table — 35
    minutes, on a corpus already fully parsed in memory a few feet away. That cost is why
    the pipeline was run in the wrong order.
    """
    parents: dict[str, set[str]] = collections.defaultdict(set)
    n_proj = 0
    for name in c.names():
        if ".to" not in name:
            continue
        d = c.get(name)
        if d is None or not d.stmt:
            continue
        try:
            _b, concl = telescope(d.stmt)
        except Exception:
            continue
        owner = name.rsplit(".to", 1)[0]
        if concl and concl != owner:
            parents[owner].add(concl)
            n_proj += 1
    print(f"  lattice: {n_proj:,} projections, {len(parents):,} classes with a parent "
          f"({time.time() - t0:.0f}s)", flush=True)
    return parents


def ancestors(parents, cls, _cache={}):
    if cls in _cache:
        return _cache[cls]
    out, stack = set(), list(parents.get(cls, ()))
    while stack:
        p = stack.pop()
        if p in out or p == cls:
            continue
        out.add(p)
        stack.extend(parents.get(p, ()))
    _cache[cls] = out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--confirmed", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-gen-scored-v2.json"))
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-novelty-rescreen.json"))
    args = ap.parse_args()
    t0 = time.time()

    conf = [tuple(x) for x in json.loads(args.confirmed.read_text())["confirmed"]]
    print(f"re-screening {len(conf):,} confirmed weakenings against {args.slice}\n",
          flush=True)

    c = fa.Corpus.load(str(args.slice))
    known, unknown, coverage, worst = c.closure(top=5)
    print(f"\n{len(c):,} declarations loaded; closure coverage {coverage * 100:.2f}% "
          f"({time.time() - t0:.0f}s, {rss_gb():.1f} GB)", flush=True)
    if coverage < args.min_coverage:
        print(f"ABORT: coverage below {args.min_coverage * 100:.0f}%. The erasure would "
              f"degrade toward the identity and 'no prior art' would be an artifact.\n"
              f"  most-cited missing: {worst}")
        return 1

    parents = lattice(c, t0)

    def reqs_of(name: str) -> list[str]:
        try:
            return c.requires(name)
        except Exception:
            return []

    novel, rediscovery, unscreenable = [], [], []
    for i, (decl, declared, target) in enumerate(conf):
        if c.get(decl) is None:
            unscreenable.append([decl, declared, target, "absent from corpus"])
            continue
        try:
            eq = c.equivalent(decl, level="instances")
        except Exception as e:
            unscreenable.append([decl, declared, target, type(e).__name__])
            continue
        hit = None
        for other in eq:
            need = set(reqs_of(other))
            if declared in need:
                continue                      # equally strong: not a generalization
            # At or below the target: it requires the target, or something the target
            # is an ancestor of — i.e. nothing stronger than the proposed weakening.
            if not need or any(r == target or target in ancestors(parents, r)
                               for r in need):
                hit = other
                break
        if hit is not None:
            rediscovery.append([decl, declared, target, hit])
        else:
            novel.append([decl, declared, target])
        if (i + 1) % 25 == 0:
            print(f"  ..{i + 1}/{len(conf)}  novel={len(novel)} "
                  f"prior-art={len(rediscovery)}  {time.time() - t0:.0f}s", flush=True)

    print(f"\n=== re-screen against {len(c):,} declarations "
          f"({args.slice.name}, coverage {coverage * 100:.2f}%) ===")
    print(f"  kernel-confirmed weakenings : {len(conf):,}")
    print(f"  survive as novel            : {len(novel):,}")
    print(f"  prior art found             : {len(rediscovery):,}")
    print(f"  unscreenable                : {len(unscreenable):,}")
    for d, dc, tg, by in rediscovery[:25]:
        print(f"    {d}  [{dc}->{tg}]  already stated as: {by}")
    args.out.write_text(json.dumps(
        {"corpus": str(args.slice), "screened_against": len(c), "coverage": coverage,
         "novel": novel, "rediscovery": rediscovery, "unscreenable": unscreenable},
        indent=1))
    print(f"\n-> {args.out}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
