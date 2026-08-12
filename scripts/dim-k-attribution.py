#!/usr/bin/env -S uv run --no-sync python
"""k-attribution of recovered dimensional relations (corpus-atlas-findings.md §65).

Run:  uv run --no-sync scripts/dim-k-attribution.py            # writes the JSON below

===========================================================================
THE QUESTION, AND THE PRE-REGISTRATION
===========================================================================

§65 of `research/corpus-atlas-findings.md`: for each recovered dimensional relation (an
RREF pivot row with >=3 atoms), is it implied by the dimensional rows of a SINGLE
declaration (k=1), of two (k=2), or of k>2 declarations jointly? If most are k=1, the
method is a per-statement dimensional type checker with the constraint printed instead of
discarded. If a meaningful fraction needs k>=2, the corpus jointly entails dimensional
facts no single statement states.

The pre-registration — populations, the 20% threshold on the powered subset, and the bias
directions — is in `research/dim-k-attribution.md` §0 and was written before this ran.

===========================================================================
WHY THE UNIT OF ATTRIBUTION IS EXACT
===========================================================================

Local atoms are declaration-keyed (`?<decl>#...`), so `eliminate_locals` is an exact
blockwise Schur complement: a declaration's post-elimination global rows carry exactly the
constraints its own statement imposes on global atoms, and entailment from a subset of
declarations is row-space membership over the union of their global rows, over Q.

  * k=1 is EXACT: supp(r) <= atoms(d) is necessary for membership (a combination's support
    is contained in the union of the combined rows' supports), so testing the covering
    declarations tests all of them.
  * k=2 is EXACT via covering-pair enumeration: a pair implying r must jointly cover
    supp(r); and when d1 alone covers it, write r = u + w with u in span(R1) and
    0 != w in span(R2) — then supp(w) <= supp(r) | atoms(d1) and supp(w) <= atoms(d2), so
    d2 shares an atom with atoms(d1) | supp(r). Enumeration over pairs passing these
    necessary conditions is complete. A per-relation budget guards runtime; exhausting it
    would bias the k=2/k>=3 split UPWARD and is reported per relation. (Measured: the
    budget was never approached — max 50 pairs tested against 60,000.)
  * k>=3 is exact as a CLASS (both smaller tests are exhaustive). Minimal k above 2 is
    not computed (set-cover-shaped); instead a coefficient-tracking elimination yields an
    explicit certificate — the pivot row as a rational combination of source rows — whose
    provenance declarations entail the relation by construction, and greedy
    inclusion-pruning (drop a declaration iff the rest still entails) leaves an
    inclusion-minimal witness set. Its size is an UPPER bound on minimal k.

The witness lists printed by `scripts/phys-calculus.py --witness` are a labelled
over-approximation (share->=2-atoms attribution) and are not used here.

===========================================================================
GATES
===========================================================================

  * Reproduction: the harness must reproduce `research/physlib-calculus.md` §3 on
    /tmp/atlas-physlib.jsonl at --cap 200000 — 21 relations / 4 powered at
    (rules none, bvar local) and 154 / 24 at (calculus, type-nonscalar) — or this exits
    non-zero and nothing is written.
  * Every certificate witness set is re-checked to entail its relation before pruning,
    and every reported k=2 pair is checked by construction.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import os
import sys
import time
from fractions import Fraction

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
sys.setrecursionlimit(20000)

_spec = importlib.util.spec_from_file_location(
    "phys_calculus", os.path.join(SCRIPTS, "phys-calculus.py"))
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)
from phys_dimlib import Echelon  # noqa: E402

SLICE = "/tmp/atlas-physlib.jsonl"
CAP = 200000
PAIR_BUDGET = 60000
OUT = os.path.join(os.path.dirname(SCRIPTS), "research", "data",
                   "dim-k-attribution.json")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class TrackedEch:
    """Forward (triangular) elimination recording, for every pivot row, its expression as a
    combination of the original inserted rows. No back-substitution, so an inserted pivot
    row is never edited and tracking is only carried through `reduce`. Termination: a
    pivot's stored row can only mention pivot columns inserted after it, so eliminating
    pivots in insertion order is well-founded."""

    def __init__(self):
        self.piv = {}          # col -> (row, combo, insertion_index)
        self.n = 0

    def reduce(self, row, combo):
        row = dict(row)
        combo = dict(combo)
        while True:
            hit, hit_ord = None, None
            for c in row:
                p = self.piv.get(c)
                if p is not None and (hit is None or p[2] < hit_ord):
                    hit, hit_ord = c, p[2]
            if hit is None:
                return row, combo
            f = row[hit]
            prow, pcombo, _ = self.piv[hit]
            for c, v in prow.items():
                nv = row.get(c, 0) - f * v
                if nv:
                    row[c] = nv
                else:
                    row.pop(c, None)
            for i, v in pcombo.items():
                nv = combo.get(i, 0) - f * v
                if nv:
                    combo[i] = nv
                else:
                    combo.pop(i, None)

    def add(self, row, idx):
        row, combo = self.reduce(row, {idx: Fraction(1)})
        if not row:
            return
        col = min(row)
        f = row[col]
        self.piv[col] = ({c: v / f for c, v in row.items()},
                         {i: v / f for i, v in combo.items()}, self.n)
        self.n += 1


def entails(decl_rows, decls, target):
    e = Echelon()
    for d in decls:
        for r in decl_rows[d]:
            e.add(r)
    return e.implies(target)


def analyze(label, rows, rules, bvar, expect_rich, expect_powered):
    t0 = time.time()
    log(f"--- {label}: building system")
    table, grows, prov, st, ex = pc.build_system(
        rows, keying="fine", literals="dimensionless", rules=rules, bvar=bvar)
    ech, connected = pc.solve(table, grows)
    single, pairs, rich, powered = pc.classify(ech)
    powered_cols = {c for c, _ in powered}
    log(f"{label}: decls {st['decls_with_rows']:,} global rows {st['global_rows']:,} "
        f"|C| {len(connected):,} rank {ech.rank:,} dim {len(connected)-ech.rank:,} "
        f"relations {len(rich)} powered {len(powered)}  [{time.time()-t0:.0f}s]")

    gate_ok = (len(rich) == expect_rich and len(powered) == expect_powered)
    if not gate_ok:
        log(f"{label}: REPRODUCTION GATE FAILED — expected "
            f"{expect_rich}/{expect_powered}, got {len(rich)}/{len(powered)}")
        return None

    decl_rows = collections.defaultdict(list)
    for r, name in zip(grows, prov):
        decl_rows[name].append(r)
    decl_atoms = {d: frozenset().union(*(frozenset(r) for r in rs))
                  for d, rs in decl_rows.items()}
    postings = collections.defaultdict(set)
    for d, atoms in decl_atoms.items():
        for a in atoms:
            postings[a].add(d)

    tracked = TrackedEch()
    for i, r in enumerate(grows):
        tracked.add(r, i)

    relations = []
    for c, r in sorted(rich, key=lambda cr: table.keys[cr[0]]):
        A = frozenset(r)

        # ---- exact k=1 ---------------------------------------------------
        cands1 = None
        for a in A:
            p = postings.get(a, set())
            cands1 = set(p) if cands1 is None else (cands1 & p)
            if not cands1:
                break
        cands1 = cands1 or set()
        k1_wits = [d for d in sorted(cands1) if entails(decl_rows, [d], r)]

        k2_pair, k2_complete, pairs_tested = None, True, 0
        witness_set = witness_upper = cert_rows = None
        if not k1_wits:
            # ---- exact k=2 via covering pairs ------------------------------
            astar = min(A, key=lambda a: len(postings.get(a, ())))
            tested, done = set(), False
            for d1 in sorted(postings.get(astar, ()),
                             key=lambda d: len(decl_atoms[d])):
                miss = A - decl_atoms[d1]
                if miss:
                    cand2 = None
                    for a in miss:
                        p = postings.get(a, set())
                        cand2 = set(p) if cand2 is None else (cand2 & p)
                        if not cand2:
                            break
                    cand2 = cand2 or set()
                else:
                    cand2 = set()
                    for a in (A | decl_atoms[d1]):
                        cand2 |= postings.get(a, set())
                for d2 in sorted(cand2):
                    if d2 == d1:
                        continue
                    key = (d1, d2) if d1 < d2 else (d2, d1)
                    if key in tested:
                        continue
                    if len(tested) >= PAIR_BUDGET:
                        k2_complete, done = False, True
                        break
                    tested.add(key)
                    if entails(decl_rows, key, r):
                        k2_pair, done = key, True
                        break
                if done:
                    break
            pairs_tested = len(tested)

            # ---- certificate witness set for the k>=3 class ----------------
            if k2_pair is None:
                residual, combo = tracked.reduce(dict(r), {})
                assert not residual, f"certificate failed for {table.keys[c]}"
                wit = sorted({prov[i] for i in combo})
                assert entails(decl_rows, wit, r), "certificate set does not entail"
                changed = True
                while changed:
                    changed = False
                    for d in sorted(wit, key=lambda d: -len(decl_rows[d])):
                        rest = [x for x in wit if x != d]
                        if rest and entails(decl_rows, rest, r):
                            wit, changed = rest, True
                cert_rows, witness_set, witness_upper = len(combo), wit, len(wit)

        k_class = ("1" if k1_wits else
                   "2" if k2_pair is not None else
                   ">=3" if k2_complete else ">=2_incomplete")
        relations.append({
            "pivot": table.keys[c],
            "rendered": pc.render_relation(table, c, r, width=6),
            "n_atoms": len(A),
            "powered": c in powered_cols,
            "coefficients": sorted(str(v) for v in r.values()),
            "k_class": k_class,
            "k1": bool(k1_wits),
            "k1_witnesses": k1_wits[:6],
            "k1_witness_count": len(k1_wits),
            "k1_candidates_tested": len(cands1),
            "k2": k2_pair is not None,
            "k2_pair": list(k2_pair) if k2_pair else None,
            "k2_pairs_tested": pairs_tested,
            "k2_enumeration_complete": k2_complete,
            "certificate_rows": cert_rows,
            "witness_set": witness_set,
            "witness_upper_bound": witness_upper,
        })

    def dist(rel):
        n = len(rel)
        cnt = collections.Counter(x["k_class"] for x in rel)
        return {"n": n, "k1": cnt["1"], "k2": cnt["2"], "k_ge3": cnt[">=3"],
                "k2_incomplete": cnt[">=2_incomplete"],
                "frac_k1": (cnt["1"] / n) if n else None,
                "frac_k_ge2": ((n - cnt["1"]) / n) if n else None,
                "frac_k_gt2": (cnt[">=3"] / n) if n else None}

    ub = collections.Counter(x["witness_upper_bound"] for x in relations
                             if x["k_class"] == ">=3")
    out = {
        "label": label,
        "config": {"slice": SLICE, "cap": CAP,
                   "rules": sorted(rules) if rules else "none", "bvar": bvar,
                   "keying": "fine", "literals": "dimensionless"},
        "system": {"decls_with_rows": st["decls_with_rows"],
                   "raw_rows": st["raw_rows"], "global_rows": st["global_rows"],
                   "connected": len(connected), "rank": ech.rank,
                   "dim": len(connected) - ech.rank,
                   "relations": len(rich), "powered": len(powered)},
        "reproduction_gate": {"expected": [expect_rich, expect_powered],
                              "got": [len(rich), len(powered)], "ok": gate_ok},
        "distribution_all": dist(relations),
        "distribution_powered": dist([x for x in relations if x["powered"]]),
        "witness_upper_bounds_k_ge3": {str(k): v for k, v in sorted(ub.items())},
        "relations": relations,
        "seconds": round(time.time() - t0, 1),
    }
    log(f"{label}: ALL {out['distribution_all']}")
    log(f"{label}: POWERED {out['distribution_powered']}")
    log(f"{label}: k>=3 witness-set sizes {out['witness_upper_bounds_k_ge3']}")
    return out


def main():
    t0 = time.time()
    log(f"loading {SLICE} cap={CAP}")
    rows, st, _dropped = pc.load_rows(SLICE, CAP)
    log(f"rows {st['rows']:,} kept {st['kept']:,} over-cap {st['over_cap']:,} "
        f"parse-failed {st['parse_failed']:,} [{st['seconds']}s]")

    results = {"pair_budget": PAIR_BUDGET, "load": dict(st)}
    results["baseline"] = analyze("baseline (rules none, bvar local)",
                                  rows, set(), "local", 21, 4)
    results["calculus"] = analyze("calculus (all rules, type-nonscalar)",
                                  rows, set(pc.FAMILIES), "type-nonscalar", 154, 24)
    if results["baseline"] is None or results["calculus"] is None:
        log("a reproduction gate failed; writing nothing")
        sys.exit(1)

    dp = results["calculus"]["distribution_powered"]
    frac = dp["frac_k_ge2"]
    results["preregistered_verdict"] = {
        "criterion": "fraction of powered calculus-config relations at k>=2, "
                     "threshold 0.20 (research/dim-k-attribution.md §0)",
        "measured_frac_k_ge2_powered": frac,
        "verdict": "discovery" if frac >= 0.20 else "transcription",
    }
    log(f"VERDICT (pre-registered): {results['preregistered_verdict']}")

    with open(OUT, "w") as f:
        json.dump(results, f, indent=1, default=str)
    log(f"json -> {OUT}   total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
