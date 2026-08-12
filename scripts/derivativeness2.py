#!/usr/bin/env python3
"""Round two: what a proof *cites the kind of*, plus statement shape.

Round one tested skeleton multiplicity and spread and they failed — spread scored AUC
0.509, literally no information, because `.injEq` gets a *distinct* skeleton per structure
(the field types differ) while genuine definition families like `CKMMatrix.{c_row,
cb_element, cd_element}` all share one. Multiplicity measures "same type signature", which
real families have in abundance.

This round uses signals round one left on the table.

**The one that should have been first.** Every row carries `kind`, so the *kinds of thing a
proof cites* are available without touching a name. A human-written proof cites
**theorems**. A generated lemma is proved by the type's own recursor and constructors, or
by `rfl`. So the fraction of `uses_proof` whose kind is `theorem` should separate them, and
it is structural rather than nominal.

**Statement shape.** The encoding is a tree and round one only ever looked at it through
erasure. Its raw size, its binder count, and the mix of binder kinds are all free.

**Ratios rather than sizes.** `-proof size` scored 0.786 but is confounded with how hard a
theorem is. The proof-to-statement ratio asks a scale-free question: is the argument large
*for this claim*?

Everything is fitted jointly by logistic regression as well as scored individually, because
the interesting question is whether any *combination* separates the classes, not whether
some single column does.

Labels remain the name-based blocklist, used only to score. A metric that recovers them
from structure can replace them.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import atlas_home  # noqa: E402
from derivativeness import auc, labelled_derived  # noqa: E402


def features(rows: dict) -> dict[str, dict[str, float]]:
    kind = {n: r.get("kind", "") for n, r in rows.items()}
    indeg: collections.Counter = collections.Counter()
    for r in rows.values():
        for u in r.get("uses_statement", ()) + r.get("uses_proof", ()):
            indeg[u] += 1

    def ns(n: str) -> str:
        return n.split(".")[0]

    out: dict[str, dict[str, float]] = {}
    for n, r in rows.items():
        up = list(r.get("uses_proof") or [])
        us = list(r.get("uses_statement") or [])
        stmt = r.get("stmt") or ""

        # What kinds does the proof cite? Unknown citations (outside the slice) are
        # counted separately rather than silently treated as one of the known kinds.
        kc: collections.Counter = collections.Counter()
        for u in up:
            kc[kind.get(u, "?")] += 1
        n_up = max(len(up), 1)

        try:
            binders, concl = atlas_home.telescope(stmt) if stmt else ([], None)
        except Exception:
            binders, concl = [], None
        bkinds = collections.Counter(bi for bi, _h, _a, _d in binders)

        out[n] = {
            # --- the new idea: kinds a proof cites -------------------------------------
            "proof_frac_theorem": kc["theorem"] / n_up,
            "proof_frac_recursor": kc["recursor"] / n_up,
            "proof_frac_ctor": kc["constructor"] / n_up,
            "proof_frac_def": kc["def"] / n_up,
            "proof_frac_struct": (kc["recursor"] + kc["constructor"]) / n_up,
            # --- scale-free size ratios --------------------------------------------------
            "proof_over_stmt": len(up) / max(len(us), 1),
            "proof_size": float(len(up)),
            "stmt_size": float(len(us)),
            # --- statement shape, straight off the encoding ------------------------------
            "enc_len": float(len(stmt)),
            "n_binders": float(len(binders)),
            "frac_inst_binders": bkinds["t"] / max(len(binders), 1),
            "frac_impl_binders": bkinds["i"] / max(len(binders), 1),
            # --- graph position ----------------------------------------------------------
            "in_degree": float(indeg[n]),
            "foreign_proof": (sum(1 for u in up if ns(u) != ns(n)) / n_up) if up else 0.0,
            # --- kind of the declaration itself -------------------------------------------
            "is_theorem": 1.0 if kind[n] == "theorem" else 0.0,
        }
    return out


def standardize(feat: dict[str, dict[str, float]], cols: list[str]):
    n = len(feat)
    mu = {c: sum(f[c] for f in feat.values()) / n for c in cols}
    sd = {}
    for c in cols:
        v = sum((f[c] - mu[c]) ** 2 for f in feat.values()) / n
        sd[c] = math.sqrt(v) or 1.0
    return mu, sd


def logistic(feat, labels, cols, epochs=260, lr=0.35):
    mu, sd = standardize(feat, cols)
    names = list(feat)
    X = [[(feat[n][c] - mu[c]) / sd[c] for c in cols] for n in names]
    y = [1.0 if labels[n] else 0.0 for n in names]
    w = [0.0] * len(cols)
    b = 0.0
    m = len(X)
    for _ in range(epochs):
        gw = [0.0] * len(cols)
        gb = 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            e = p - yi
            gb += e
            for j, xj in enumerate(xi):
                gw[j] += e * xj
        b -= lr * gb / m
        for j in range(len(cols)):
            w[j] -= lr * gw[j] / m
    scores = {}
    for n, xi in zip(names, X):
        scores[n] = b + sum(wj * xj for wj, xj in zip(w, xi))
    return w, b, scores


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-derivativeness2.json"))
    args = ap.parse_args()

    rows = {}
    with args.slice.open() as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rows[r["name"]] = r
    print(f"{len(rows):,} declarations")

    feat = features(rows)
    labels = {n: labelled_derived(n) for n in rows}
    npos = sum(labels.values())
    print(f"labels: {npos:,} derivative / {len(labels):,} "
          f"({100*npos/len(labels):.1f}%)\n")

    cols = list(next(iter(feat.values())).keys())
    print(f"{'feature':26s} {'AUC':>7s}  {'AUC(flipped)':>13s}")
    singles = {}
    for c in cols:
        a = auc([(feat[n][c], labels[n]) for n in rows])
        singles[c] = max(a, 1 - a)
        print(f"{c:26s} {a:7.3f}  {1-a:13.3f}")

    print("\nbest single:",
          max(singles.items(), key=lambda kv: kv[1]))

    w, b, sc = logistic(feat, labels, cols)
    a = auc([(sc[n], labels[n]) for n in rows])
    print(f"\nlogistic on all {len(cols)} features: AUC {a:.3f}")
    order = sorted(zip(cols, w), key=lambda kv: -abs(kv[1]))
    print("  weights (standardized), largest first:")
    for c, wi in order[:10]:
        print(f"    {c:26s} {wi:+.3f}")

    ranked = sorted(rows, key=lambda n: -sc[n])
    called = set(ranked[:npos])
    tp = sum(1 for n in called if labels[n])
    print(f"\nat prevalence threshold: precision {tp/len(called):.3f} "
          f"recall {tp/npos:.3f}")

    # Precision at the top of the ranking — what a *downweighting* prior actually needs.
    for k in (100, 500, 1000, 2000):
        top = ranked[:k]
        p = sum(1 for n in top if labels[n]) / k
        print(f"  precision@{k:<5d} {p:.3f}")

    args.out.write_text(json.dumps(
        {"singles": singles, "logistic_auc": a,
         "weights": dict(zip(cols, w))}, indent=1))
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
