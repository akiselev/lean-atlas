#!/usr/bin/env python3
"""A quantum-physics answer key, and the run against it.

Unlike B7, the corpus already exists: physlib carries 2,287 declarations across
`QuantumMechanics`, `States`, `Channels`, `Entropy`, `ResourceTheory`, `Capacity` and
`ClassicalInfo`. So the key names **real declarations** rather than statements written for
the occasion, which removes the largest weakness of the RH run — that its corpus and its
answer key were authored by the same hand in the same hour.

## The key, written before the run

Each target names a pairing a physicist would expect, a query to issue, and what counts as
a hit. Fragments rather than exact names: `MState.exp_val_pure_eq_one_iff` and
`MState.pure_iff` are both right answers to "what is this state statement about", and a key
that demanded one of them would be scoring spelling.

* **Q1 correspondence principle** — the classical harmonic oscillator against the quantum
  one. The one pairing already seen (retention 0.92-0.95) before this key existed, so it
  is a *calibration* target: if it fails here the harness is broken.
* **Q2 self-adjointness ⇒ real spectrum** — the same shape as B7's V2, inside one corpus.
  Query an adjoint/symmetric statement; expect a spectrum or eigenvalue statement.
* **Q3 data processing** — a channel cannot increase distinguishability, and entropy is
  monotone under it. Query `Channels`; expect `Entropy`.
* **Q4 positivity family** — `HermitianMat.PosDef` statements should cohere, and should
  reach the free-state convexity statements, because both are "this form is ≥ 0".
* **Q5 Stein's lemma** — the deepest: the optimal hypothesis-testing error exponent *is* a
  relative entropy. Query `OptimalHypothesisRate`; expect `Entropy`.
* **Q6 ℏ** — the constants should attach to the operator statements that use them.
* **Control** — the RH/number-theory clusters must not match quantum statements. A hit
  means the ranking is measuring punctuation.

## The second thing this run measures

Every query is issued twice: **root-anchored** (the shipped behaviour) and
**conclusion-anchored** (statements transformed so each one *is* its conclusion). B7 showed
the root anchor is why cross-theory analogy fails — a hypothesis prefix makes two identical
conclusions unalignable — and that conclusion-anchoring fixed V2. That was one corpus and
one target. This run asks whether it holds on an independent corpus, and what it costs in
precision, which is the evidence needed before it becomes a shipped mode.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from atlas_home import Reader  # noqa: E402

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

TAG = "atlas-stmt-v1;"

KEY = [
    ("Q1 correspondence principle",
     ["ClassicalMechanics.HarmonicOscillator.equationOfMotion",
      "ClassicalMechanics.HarmonicOscillator.Trajectory"],
     ["QuantumMechanics"], "a quantum harmonic-oscillator statement"),
    ("Q2 self-adjoint => real spectrum",
     ["LinearPMap.HasDenseDomain.orthogonal_adjoint_ker",
      "LinearPMap.HasDenseDomain.adjoint_add_continuous"],
     ["QuantumMechanics"], "a spectrum/eigenvalue/adjoint statement"),
    ("Q3 data processing",
     ["CPTPMap.IsTracePreserving", "CPTPMap.Tr_of_choi_of_CPTP"],
     ["Entropy", "States"], "an entropy or state statement"),
    ("Q4 positivity family",
     ["HermitianMat.PosDef_kronecker", "HermitianMat.PosDef_reindex"],
     ["ResourceTheory", "States", "Entropy"], "another positivity statement"),
    ("Q5 Stein's lemma",
     ["OptimalHypothesisRate.exists_min", "OptimalHypothesisRate.iInf_IsConvex"],
     ["Entropy"], "a relative-entropy statement"),
    ("Q6 hbar attaches to operators",
     ["Constants.ℏ_pos", "Constants.ℏ_ne_zero"],
     ["QuantumMechanics"], "an operator statement using it"),
]

CONTROL_SUBFIELDS = {"Relativity", "SpaceAndTime", "Particles", "StringTheory",
                     "Cosmology", "FluidDynamics", "Electromagnetism"}


def conclusion_only(enc: str) -> str | None:
    r = Reader(enc)
    n = 0
    while r.i < len(r.b) and r.b[r.i] == 0x70:
        r.i += 3
        r.skip()
        r.i += 1
        n += 1
    if n == 0:
        return enc
    tail = r.b[r.i:]
    if len(tail) <= n:
        return None
    body = tail[: len(tail) - n]
    return TAG + body.decode("utf-8", "replace") if body else None


def transform(src: pathlib.Path, dst: pathlib.Path) -> int:
    k = 0
    with dst.open("w") as o:
        for line in src.open():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("stmt"):
                c = conclusion_only(row["stmt"])
                if c:
                    row["stmt"] = c
                    k += 1
            o.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    return k


def run(corpus, label: str, resolve) -> dict:
    out = {}
    print(f"\n{'=' * 74}\n{label}\n{'=' * 74}")
    for tag, queries, want, desc in KEY:
        print(f"\n  {tag}   (expect: {desc} from {'/'.join(want)})")
        best = None
        for q in queries:
            name = resolve(q)
            if name is None:
                print(f"    {q[:52]:52s} not in slice")
                continue
            try:
                nbs = corpus.similar(name, top=10, level="carriers",
                                     min_retention=0.05, min_common=3)
            except Exception as e:
                print(f"    {q[:52]:52s} {type(e).__name__}")
                continue
            hit = None
            for i, nb in enumerate(nbs, 1):
                d = corpus.get(nb.name)
                sub = ((d.module if d else "") or "").split(".")[0]
                if sub in want and hit is None:
                    hit = (i, nb.name, sub, round(nb.retention, 3))
            shown = ", ".join(f"{corpus.get(nb.name).module.split('.')[0]}" for nb in nbs[:4])
            print(f"    {name.split('.')[-1][:40]:40s} top: {shown}")
            if hit:
                print(f"       HIT rank {hit[0]}: [{hit[2]}] {hit[1][:52]} ret {hit[3]}")
                if best is None or hit[0] < best[0]:
                    best = hit
        out[tag] = {"hit": best}
        print(f"    -> {'PASS rank ' + str(best[0]) if best and best[0] <= 5 else ('partial rank ' + str(best[0]) if best else 'MISS')}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-physlib-theories.jsonl"))
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-quantum-report.json"))
    args = ap.parse_args()

    concl = pathlib.Path("/tmp/atlas-physlib-concl.jsonl")
    k = transform(args.slice, concl)
    print(f"conclusion-anchored transform: {k} statements rewritten -> {concl}")

    root = fa.Corpus.load(str(args.slice))
    names = root.names()
    index = {n.split(".")[-1]: n for n in names}
    full = set(names)

    def resolve(q):
        if q in full:
            return q
        for n in names:
            if n.endswith("." + q) or n == q:
                return n
        return index.get(q.split(".")[-1])

    report = {"root": run(root, "ROOT-ANCHORED (shipped behaviour)", resolve)}
    conc = fa.Corpus.load(str(concl))
    report["conclusion"] = run(conc, "CONCLUSION-ANCHORED (the B7 fix)", resolve)

    # ---- control ---------------------------------------------------------------------
    print(f"\n{'=' * 74}\nCONTROL — quantum queries must not pull in relativity/particles\n{'=' * 74}")
    for label, corpus in (("root", root), ("conclusion", conc)):
        fired = 0
        total = 0
        for _tag, queries, _w, _d in KEY:
            for q in queries:
                n = resolve(q)
                if n is None:
                    continue
                try:
                    nbs = corpus.similar(n, top=10, level="carriers",
                                         min_retention=0.05, min_common=3)
                except Exception:
                    continue
                for nb in nbs:
                    total += 1
                    d = corpus.get(nb.name)
                    if ((d.module if d else "") or "").split(".")[0] in CONTROL_SUBFIELDS:
                        fired += 1
        print(f"  {label:11s} {fired}/{total} neighbours came from an unrelated subfield "
              f"({100 * fired / max(total, 1):.0f}%)")
        report.setdefault("control", {})[label] = {"fired": fired, "total": total}

    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
