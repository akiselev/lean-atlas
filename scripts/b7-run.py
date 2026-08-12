#!/usr/bin/env python3
"""B7 — run the Atlas against the validation clusters and report, target by target.

Scored against `atlas-validation.md` §3's published development targets V1–V9. The private
held-out key is **not** consulted, located, or searched for: this script emits what the
Atlas found so its owner can score it.

Each target below states its pass condition as the document states it, before any output is
read. Where a target needs machinery that does not exist (V9's proof-shape index), it is
reported as unrunnable rather than quietly skipped — "we did not look" and "there is nothing
there" are different answers.

Controls, per §3 and §4: the twelve atlas corpus groups are background noise. Group 12's
termination/monovariant patterns must match nothing in the RH cluster. A control that fires
means the ranking is measuring punctuation.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

CLUSTER = re.compile(r"^Validation\.([A-Za-z]+)\.")


def prepare(sources: list[pathlib.Path], out: pathlib.Path) -> dict:
    """One row per declaration, with `module` set to the cluster it belongs to.

    `theory_of` takes the depth-1 prefix outside Mathlib, so every validation declaration
    would otherwise file under `Validation` and the whole benchmark would be one theory —
    making a dictionary between two clusters a dictionary from a theory to itself.
    """
    census: dict[str, int] = {}
    n = 0
    with out.open("w") as o:
        for src in sources:
            if not src.exists():
                continue
            for line in src.open():
                if not line.strip():
                    continue
                row = json.loads(line)
                m = CLUSTER.match(row.get("name", ""))
                if m:
                    row["module"] = m.group(1)
                elif row.get("module", "").startswith("Tests.corpus."):
                    row["module"] = "CorpusControl"
                census[row["module"]] = census.get(row["module"], 0) + 1
                n += 1
                o.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    return {"rows": n, "clusters": census}


def show(c, name, top=8, **kw):
    try:
        return c.similar(name, top=top, **kw)
    except Exception as e:
        print(f"      ({type(e).__name__}: {e})")
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", type=pathlib.Path, default=pathlib.Path("/tmp/atlas-rh.jsonl"))
    ap.add_argument("--controls", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-corpus-nomathlib.jsonl"))
    ap.add_argument("--prepared", type=pathlib.Path, default=pathlib.Path("/tmp/atlas-b7.jsonl"))
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("/tmp/atlas-b7-report.json"))
    args = ap.parse_args()

    meta = prepare([args.clusters, args.controls], args.prepared)
    print(f"{meta['rows']} declarations")
    for k, v in sorted(meta["clusters"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:18s} {v:4d}")

    c = fa.Corpus.load(str(args.prepared))
    report: dict = {"census": meta["clusters"]}
    LOOSE = dict(level="carriers", min_retention=0.05, min_common=3)

    def cluster_of(n):
        d = c.get(n)
        return (d.module if d else "?") or "?"

    # ---- V2 — Hilbert–Pólya ---------------------------------------------------------
    print("\n" + "=" * 74)
    print("V2 (T1) Hilbert–Polya — `similar` on RH must surface spectrum-is-real, top-5")
    print("=" * 74)
    v2 = {}
    for q in ["Validation.RH.zeros_on_critical_line", "Validation.RH.no_zero_off_line",
              "Validation.RH.no_zeros_right_half"]:
        print(f"\n  query: {q}")
        nbs = show(c, q, top=8, **LOOSE)
        rows = []
        for i, nb in enumerate(nbs, 1):
            mark = "  <== SPECTRAL" if cluster_of(nb.name) == "Spectral" else ""
            print(f"    {i}. [{cluster_of(nb.name):14s}] {nb.name[:46]:46s} "
                  f"ret {nb.retention:.2f} score {nb.score:.2f}{mark}")
            rows.append((nb.name, cluster_of(nb.name), round(nb.score, 3)))
        hit = next((i for i, r in enumerate(rows, 1) if r[1] == "Spectral"), None)
        print(f"    -> spectral hit at rank {hit}" if hit else "    -> NO spectral hit")
        v2[q] = {"rows": rows, "spectral_rank": hit}
    report["V2"] = v2

    # ---- V3 — Weil positivity --------------------------------------------------------
    print("\n" + "=" * 74)
    print("V3 (T1) Weil positivity — link the Weil criterion to FF-side positivity")
    print("=" * 74)
    v3 = {}
    for q in ["Validation.Positivity.weil_criterion",
              "Validation.Positivity.intersection_positivity",
              "Validation.FF.castelnuovo_severi"]:
        print(f"\n  query: {q}")
        nbs = show(c, q, top=8, **LOOSE)
        rows = [(nb.name, cluster_of(nb.name), round(nb.score, 3)) for nb in nbs]
        for i, (n_, cl, s) in enumerate(rows, 1):
            print(f"    {i}. [{cl:14s}] {n_[:46]:46s} {s}")
        v3[q] = rows
    report["V3"] = v3

    # ---- V6 — reformulation cluster --------------------------------------------------
    print("\n" + "=" * 74)
    print("V6 (T1) Reformulation cluster — RH, Lambda<=0 and Weil in one cluster")
    print("=" * 74)
    st = c.logical_stats()
    print(f"  proved edges: {st.edges} (iff {st.iff_edges}, impl {st.implication_edges}); "
          f"flex {st.flex_head_sides}, same-head {st.same_head_sides}")
    v6 = {}
    for q in ["Validation.Deformation.rh_iff_lambda_nonpos",
              "Validation.Positivity.weil_criterion",
              "Validation.Spectral.symmetric_iff_inner"]:
        try:
            rels = c.relations(q)
        except Exception as e:
            rels = []
            print(f"    {q}: {type(e).__name__}")
        print(f"    {q.split('.')[-1]:26s} {len(rels)} edge(s)"
              + (f"  {rels[0].kind}: {rels[0].left} ~ {rels[0].right}" if rels else ""))
        v6[q] = [(r.kind, r.left, r.right, r.warrant) for r in rels]
    print("\n  busiest heads (where reformulations accumulate):")
    for h, ar, k in c.busiest_heads(top=8):
        print(f"    {h:34s} arity {ar}  {k} edge(s)")
    report["V6"] = {"stats": {"edges": st.edges, "iff": st.iff_edges,
                              "same_head": st.same_head_sides},
                    "relations": v6}

    # ---- V7 — GRH as anti-unification output -----------------------------------------
    print("\n" + "=" * 74)
    print("V7 (T2) GRH as lgg — anti-unify RH-for-zeta with the L-function statement")
    print("=" * 74)
    for a, b in [("Validation.RH.zeros_on_critical_line",
                  "Validation.LFamily.grh_zeros_on_line"),
                 ("Validation.RH.no_zero_off_line",
                  "Validation.LFamily.grh_no_zero_off_line")]:
        try:
            g = c.generalize(a, b)
            print(f"\n  {a.split('.')[-1]} x {b.split('.')[-1]}")
            print(f"    common {g.common}  vars {g.vars}  retention {g.retention:.3f}")
            print(f"    lgg: {g.skeleton[:300]}")
            report.setdefault("V7", {})[f"{a}|{b}"] = {
                "common": g.common, "vars": g.vars,
                "retention": g.retention, "skeleton": g.skeleton}
        except Exception as e:
            print(f"    {type(e).__name__}: {e}")

    # ---- V8 — pair correlation --------------------------------------------------------
    print("\n" + "=" * 74)
    print("V8 (T2) Pair correlation — Montgomery must match the GUE density")
    print("=" * 74)
    for q in ["Validation.PairCorrelation.montgomery",
              "Validation.PairCorrelation.gue_eigenvalue_spacing"]:
        print(f"\n  query: {q}")
        nbs = show(c, q, top=6, **LOOSE)
        for i, nb in enumerate(nbs, 1):
            print(f"    {i}. [{cluster_of(nb.name):14s}] {nb.name[:46]:46s} "
                  f"ret {nb.retention:.2f}")
        report.setdefault("V8", {})[q] = [(nb.name, cluster_of(nb.name),
                                           round(nb.retention, 3)) for nb in nbs]

    # ---- V1 / V4 — the Z~FF dictionary and its missing entries ------------------------
    print("\n" + "=" * 74)
    print("V1/V4 (T1) The Z~FF dictionary and the missing-entry report")
    print("=" * 74)
    try:
        d = c.dictionary("Z", "FF", per_decl=3, theorems_only=False)
        print(f"  {len(d.rows)} rows; {len(d.missing_left)} unmatched left, "
              f"{len(d.missing_right)} unmatched right")
        for r in d.rows[:10]:
            print(f"    {r.left.split('.')[-1][:30]:30s} ~ {r.right.split('.')[-1][:30]:30s}"
                  f"  ret {r.retention:.2f} {r.status}")
        print(f"  missing on the Z side : "
              f"{', '.join(x.split('.')[-1] for x in d.missing_left[:10])}")
        print(f"  missing on the FF side: "
              f"{', '.join(x.split('.')[-1] for x in d.missing_right[:10])}")
        report["V1V4"] = {
            "rows": [(r.left, r.right, r.retention, r.status) for r in d.rows],
            "missing_left": list(d.missing_left), "missing_right": list(d.missing_right)}
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")

    # ---- Controls ---------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("CONTROLS — the corpus groups must not match the RH cluster (section 3/4)")
    print("=" * 74)
    fired = []
    for q in ["Validation.RH.zeros_on_critical_line", "Validation.RH.mertens_bound",
              "Validation.Deformation.rh_iff_lambda_nonpos"]:
        nbs = show(c, q, top=12, **LOOSE)
        ctrl = [nb.name for nb in nbs if cluster_of(nb.name) == "CorpusControl"]
        print(f"  {q.split('.')[-1]:26s} control hits: {len(ctrl)}"
              + (f"  {ctrl[:3]}" if ctrl else ""))
        if ctrl:
            fired.append((q, ctrl))
    print(f"\n  -> {'CONTROL FIRED (bad)' if fired else 'controls silent (good)'}")
    report["controls"] = fired

    # ---- V9 — declared unrunnable -----------------------------------------------------
    print("\n" + "=" * 74)
    print("V9 (T2) Zero-density as proof-shape retrieval: UNRUNNABLE")
    print("  The proof-shape index (atlas.md 1e) does not exist. Reported rather than")
    print("  skipped, so a later pass means something.")
    print("=" * 74)
    report["V9"] = "unrunnable: no proof-shape index"

    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
