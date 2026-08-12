#!/usr/bin/env python3
"""A graph-driven measure of whether a declaration is boilerplate — no name matching.

## The problem this replaces

Every layer of the Atlas, on every corpus tried, is dominated by auto-generated
declarations. `Relativity ~ QFT`'s best dictionary rows are
`CausalCharacter.lightLike ~ CreateAnnihilate.annihilate.sizeOf_spec`. Cross-theory
`similar` on Mathlib returns `.mk.inj` pairs. The standing workaround is a hand-written
blocklist of name suffixes (`.injEq`, `.sizeOf_spec`, `.noConfusion`, …), which is brittle,
library-specific, and — the real objection — *name matching*, which is precisely the thing
the Atlas exists to replace. A name is a convention, not a fact about a statement.

## The observation that makes an objective metric possible

Auto-generated declarations are **templates**. Lean emits `Foo.mk.injEq` with the same
shape for every structure `Foo`, so its skeleton recurs identically across hundreds of
unrelated declarations in unrelated subfields. A real theorem's skeleton does not: it may
be shared by a handful of siblings, but not by half the library.

So "is this boilerplate" becomes a question about the *distribution* of a skeleton, which
the index already computes, rather than about spelling.

## The four candidate signals, each from the row data alone

* **multiplicity** — how many declarations share this skeleton.
* **spread** — how many *distinct subfields* those declarations span. A template is
  library-wide; a genuine family (the `le_trans` of eighteen concrete types) is not.
* **foreign proof fraction** — the share of `uses_proof` lying outside the declaration's own
  top-level namespace. Generated lemmas cite only their own type's constructor and
  recursor; a theorem cites lemmas from elsewhere.
* **in-degree** — how many declarations cite this one.

## How this is validated rather than asserted

The name-based blocklist is used **as held-out labels, never as an input**. Each metric is
scored on how well it separates the labelled classes, by ROC AUC. A metric that recovers
the labels from graph structure alone can replace the blocklist — and will additionally
catch boilerplate the blocklist misses, which is the whole point, since the blocklist was
only ever a list of the cases someone happened to notice.

Reported alongside: the disagreements. Declarations the metric calls derivative but the
blocklist calls authored are the interesting ones, because they are either metric failures
or boilerplate nobody had named yet.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

# ---------------------------------------------------------------------------
# Labels. Used ONLY to score the metrics below, never as an input to them.
# ---------------------------------------------------------------------------
DERIVED_SUFFIX = (
    ".eq_def", ".below", ".ibelow", ".brecOn", ".binductionOn", ".rec", ".recOn",
    ".casesOn", ".noConfusion", ".noConfusionType", ".toCtorIdx", ".ctorIdx",
    ".sizeOf_spec", ".injEq", ".inj", ".induct", ".fun_cases", ".elim", ".ctorElim",
    ".ctorElimType", ".ofNat", ".ext", ".ext_iff", ".congr_simp",
)
DERIVED_SUB = ("._", ".match_", ".proof_", ".eq_", "_example", ".«", ".mk.")


def labelled_derived(n: str) -> bool:
    if n.startswith("_"):
        return True
    if n.endswith(DERIVED_SUFFIX):
        return True
    return any(s in n for s in DERIVED_SUB)


def auc(scores: list[tuple[float, bool]]) -> float:
    """ROC AUC by rank, ties averaged. `True` is the positive (derivative) class."""
    scores = sorted(scores, key=lambda t: t[0])
    n = len(scores)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[j + 1][0] == scores[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    pos = [ranks[k] for k in range(n) if scores[k][1]]
    npos, nneg = len(pos), n - len(pos)
    if npos == 0 or nneg == 0:
        return float("nan")
    return (sum(pos) - npos * (npos + 1) / 2.0) / (npos * nneg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--level", default="carriers")
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-derivativeness.json"))
    args = ap.parse_args()

    rows = {}
    with args.slice.open() as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rows[r["name"]] = r
    print(f"{len(rows):,} declarations")

    c = fa.Corpus.load(str(args.slice))

    # ---- skeletons -------------------------------------------------------------------
    skel: dict[str, str] = {}
    for n in rows:
        try:
            skel[n] = c.skeleton(n, level=args.level)
        except Exception:
            pass
    print(f"{len(skel):,} skeletons at level={args.level}")

    by_skel: dict[str, list[str]] = collections.defaultdict(list)
    for n, s in skel.items():
        by_skel[s].append(n)

    def subfield(n: str) -> str:
        return (rows[n].get("module") or "").split(".")[0]

    mult = {n: len(by_skel[skel[n]]) for n in skel}
    spread = {n: len({subfield(m) for m in by_skel[skel[n]]}) for n in skel}

    # ---- citation structure ----------------------------------------------------------
    indeg: collections.Counter = collections.Counter()
    for r in rows.values():
        for u in r.get("uses_statement", ()) + r.get("uses_proof", ()):
            indeg[u] += 1

    def own_ns(n: str) -> str:
        return n.split(".")[0]

    foreign = {}
    proofsize = {}
    for n, r in rows.items():
        up = r.get("uses_proof") or []
        proofsize[n] = len(up)
        if up:
            foreign[n] = sum(1 for u in up if own_ns(u) != own_ns(n)) / len(up)
        else:
            foreign[n] = 0.0

    # ---- score each candidate signal --------------------------------------------------
    labels = {n: labelled_derived(n) for n in skel}
    npos = sum(labels.values())
    print(f"labels: {npos:,} derivative, {len(labels) - npos:,} authored "
          f"({100 * npos / max(len(labels), 1):.1f}% positive)\n")

    signals = {
        "skeleton multiplicity": lambda n: float(mult[n]),
        "skeleton spread (subfields)": lambda n: float(spread[n]),
        "mult x spread": lambda n: float(mult[n] * spread[n]),
        "1 - foreign proof fraction": lambda n: 1.0 - foreign[n],
        "-proof size": lambda n: -float(proofsize[n]),
        "-in-degree": lambda n: -float(indeg[n]),
    }
    results = {}
    print(f"{'signal':32s} {'AUC':>7s}   (0.5 = no information, 1.0 = perfect)")
    for name, fn in signals.items():
        a = auc([(fn(n), labels[n]) for n in skel])
        results[name] = a
        print(f"{name:32s} {a:7.3f}")

    # ---- the combination, and where it disagrees with the blocklist ------------------
    print()
    combo = {n: (mult[n] * spread[n], 1.0 - foreign[n]) for n in skel}
    # Rank by multiplicity*spread, and report the decision at a threshold that matches the
    # label prevalence, so precision and recall are comparable.
    ranked = sorted(skel, key=lambda n: -(mult[n] * spread[n]))
    cut = npos
    called = set(ranked[:cut])
    tp = sum(1 for n in called if labels[n])
    fp = len(called) - tp
    fn_ = npos - tp
    print(f"at a threshold matching label prevalence ({cut:,} called derivative):")
    print(f"  precision {tp / max(len(called),1):.3f}   recall {tp / max(npos,1):.3f}")
    print(f"  {fp:,} called derivative that the blocklist calls authored")
    print(f"  {fn_:,} called authored that the blocklist calls derivative")

    print("\n  highest mult x spread the blocklist calls AUTHORED "
          "(boilerplate nobody named, or metric failures):")
    shown = 0
    for n in ranked:
        if not labels[n] and shown < 15:
            print(f"    mult {mult[n]:5d} spread {spread[n]:3d}  {n[:62]}")
            shown += 1

    print("\n  lowest mult x spread the blocklist calls DERIVATIVE "
          "(the metric would keep these):")
    shown = 0
    for n in reversed(ranked):
        if labels[n] and shown < 10:
            print(f"    mult {mult[n]:5d} spread {spread[n]:3d}  {n[:62]}")
            shown += 1

    args.out.write_text(json.dumps(
        {"auc": results, "n": len(skel), "positives": npos,
         "top_unlabelled": [(n, mult[n], spread[n]) for n in ranked[:200]
                            if not labels[n]]}, indent=1))
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
