#!/usr/bin/env python3
"""Assemble research/data/cross-domain-hunt.json from the sweep, ranking and grades."""

from __future__ import annotations

import json
import os
import pathlib

SCRATCH = pathlib.Path(os.environ.get("HUNT_DIR", "."))  # work dir for hunt-*.json
OUT = pathlib.Path("/home/dev/research/lean-atlas/research/data/cross-domain-hunt.json")

# Grades assigned by the implementing agent (Claude), blind to the source field of the
# queue (control vs real) until after all 50 were graded; names were visible, so the
# blinding is procedural, not epistemic — stated in the report.
PRIMARY_GRADES = {
    0: ("B", "Both sides pure Fin/Finset combinatorics (Wick-contraction card lemma vs tensor-contraction helper); real structural kinship, zero physics."),
    1: ("C", "Field projection of LinSols instantiated; left is proved by `S.linearSol`."),
    2: ("D", "EM lagrangian shift identity vs causal-character criterion; the 1,567 shared nodes are the Minkowski inner-product instance apparatus, not shared claim."),
    3: ("D", "SUSY delta-tensor symmetry vs Weyl basis expansion; both contentful, unrelated."),
    4: ("D", "Controlled-gate zero block vs CKM element vanishing; 'some matrix entry is 0' is all they share."),
    5: ("C", "linearSol family."),
    6: ("C", "Auto-generated sizeOf_spec pair."),
    7: ("C", "Control: sizeOf_spec boilerplate."),
    8: ("C", "linearSol family."),
    9: ("C", "rfl-trivia on both sides (zero initial condition / identity has zero translation)."),
    10: ("C", "linearSol family."),
    11: ("C", "Left contentful (anomaly-free from hypercharge condition) but the match is to the definitional field."),
    12: ("C", "linearSol family."),
    13: ("C", "linearSol family."),
    14: ("C", "sizeOf_spec pair."),
    15: ("C", "Control: sizeOf_spec boilerplate."),
    16: ("B", "coordCLM_apply stated for Euclidean Space and for Lorentz.Vector — the same API lemma on two carriers; plumbing, mirrored."),
    17: ("C", "Control: sizeOf_spec boilerplate."),
    18: ("C", "linearSol family."),
    19: ("D", "Gauge-invariance of Hermitian inner product vs equal spatial norms of lightlike vectors; both contentful, unrelated."),
    20: ("D", "Magnetostatics fact vs curl/constantTime interchange plumbing; 43,774 shared nodes are the distribution-space apparatus."),
    21: ("D", "As queue 04."),
    22: ("C", "Control: sizeOf_spec boilerplate."),
    23: ("D", "Static configuration's potential vs generic dt-curl commute lemma."),
    24: ("C", "linearSol family (accGravSatisfied)."),
    25: ("C", "Control: sizeOf_spec boilerplate."),
    26: ("D", "Electrostatics fact vs curl plumbing; apparatus overlap."),
    27: ("C", "Control: injEq boilerplate."),
    28: ("C", "sizeOf_spec pair."),
    29: ("D", "Euler-equation ingredient (inviscid stress divergence) vs gradient linearity triviality."),
    30: ("C", "linearSol family."),
    31: ("C", "sizeOf_spec pair."),
    32: ("C", "linearSol family."),
    33: ("C", "rfl-trivia, as queue 09."),
    34: ("C", "Control: sizeOf_spec boilerplate."),
    35: ("B", "Purification-style isometry V^H V = 1 vs CKM standard parametrization unitary — same generic claim 'constructed matrix is an isometry'; no shared physics."),
    36: ("C", "sizeOf_spec pair."),
    37: ("C", "Control: sizeOf_spec boilerplate."),
    38: ("B", "As queue 35."),
    39: ("C", "Control: injEq boilerplate."),
    40: ("C", "sizeOf_spec pair."),
    41: ("D", "As queue 20."),
    42: ("C", "sizeOf_spec pair."),
    43: ("C", "Control: sizeOf_spec boilerplate."),
    44: ("C", "sizeOf_spec pair."),
    45: ("D", "As queue 20."),
    46: ("C", "linearSol family."),
    47: ("C", "linearSol family (accGrav from Q=0)."),
    48: ("C", "linearSol family."),
    49: ("B", "Cauchy momentum balance identity vs Ampere-Maxwell evolution law — both balance-law shaped (dt field + spatial flux = source); conservative B, the physics differs."),
}

SECONDARY = [
    ("Electromagnetism.ElectromagneticPotential.lagrangian_add_const", "Lorentz.Vector.timeLike_iff_norm_sq_pos", 0.8851, "D", "= primary queue 02."),
    ("sandwichedTraceFunctional_nonneg", "LinearPMap.variance_nonneg", 0.8571, "B", "0 <= Q~_a(rho||sigma) vs 0 <= variance T psi; nonnegativity of two real quantum quantities; shared math only."),
    ("sandwichedTraceFunctional_nonneg", "MState.fidelity_ge_zero", 0.8571, "B", "Same family: nonnegativity."),
    ("Matrix.Isometry.congr_simp", "MatrixMap.IsCompletelyPositive.congr_simp", 0.8462, "C", "Congruence plumbing lemmas."),
    ("TimeTransMan.diff_self", "StandardModel.HiggsField.Potential.toFun_zero", 0.8462, "D", "diff x t t = 0 vs P.toFun 0 x = 0; both 'evaluates to zero', unrelated."),
    ("Sᵥₙ_nonneg", "LinearPMap.variance_nonneg", 0.8421, "B", "Entropy nonneg vs variance nonneg; both quantum, same generic claim."),
    ("Sᵥₙ_nonneg", "MState.fidelity_ge_zero", 0.8421, "B", "Entropy nonneg vs fidelity nonneg."),
    ("CanonicalEnsemble.mathematicalPartitionFunction_nonneg", "LinearPMap.variance_nonneg", 0.8421, "C", "0 <= Z is measureReal_nonneg — content-free positivity."),
    ("CanonicalEnsemble.mathematicalPartitionFunction_nonneg", "MState.fidelity_ge_zero", 0.8421, "C", "As above."),
    ("ClassicalMechanics.HarmonicOscillator.AmplitudePhase.mk.sizeOf_spec", "ACCSystemLinear.mk.sizeOf_spec", 0.8254, "C", "sizeOf_spec."),
    ("ClassicalMechanics.SlidingPendulum.ConfigurationSpace.mk.sizeOf_spec", "ACCSystemLinear.mk.sizeOf_spec", 0.8254, "C", "sizeOf_spec."),
    ("Electromagnetism.EMSystem.mk.sizeOf_spec", "ACCSystemLinear.mk.sizeOf_spec", 0.8254, "C", "sizeOf_spec."),
    ("StandardModel.HiggsField.Potential.mk.sizeOf_spec", "ACCSystemLinear.mk.sizeOf_spec", 0.8254, "C", "sizeOf_spec."),
    ("ACCSystemLinear.mk.sizeOf_spec", "Fermion.Dirac.mk.sizeOf_spec", 0.8254, "C", "sizeOf_spec."),
    ("ACCSystemQuad.mk.sizeOf_spec", "Fermion.Dirac.mk.sizeOf_spec", 0.8254, "C", "sizeOf_spec."),
    ("FTheory.SU5.Fluxes.mk.sizeOf_spec", "ACCSystemLinear.mk.sizeOf_spec", 0.8254, "C", "sizeOf_spec."),
    ("Sᵥₙ_nonneg", "CKMMatrix.VAbs_ge_zero", 0.8235, "C", "Right side is norm_nonneg — content-free positivity."),
    ("Sᵥₙ_unit_zero", "StandardModel.HiggsField.EffectivePotential.termOfMassDim_eq_zero_of_max_lt", 0.8235, "D", "Trivial-system entropy zero vs EFT term vanishing; unrelated."),
    ("Sᵥₙ_nonneg", "Space.normPowerSeries_nonneg", 0.8235, "C", "Right side is Real.sqrt_nonneg — content-free positivity."),
    ("CanonicalEnsemble.mathematicalPartitionFunction_nonneg", "CKMMatrix.VAbs_ge_zero", 0.8235, "C", "Content-free positivity on both sides."),
]

POSTHOC = {
    "found_by": "token scan of the 3,029 physics budget-only rows for named physics "
                "structures, then direct measurement; NOT surfaced by either ranking",
    "rows": [
        {
            "left": "Sᵥₙ_nonneg", "right": "CanonicalEnsemble.entropy_nonneg",
            "pair": "Entropy ~ StatisticalMechanics",
            "left_stmt": "theorem Sᵥₙ_nonneg (ρ : MState d) : 0 ≤ Sᵥₙ ρ",
            "right_stmt": "lemma entropy_nonneg [...] (T : Temperature) : 0 ≤ 𝓒.shannonEntropy T   -- S = -kB ∑ p log p of the canonical distribution",
            "lgg_conclusion": {"common": 23, "retention": 0.7931},
            "similar_budget_2000": {"above_floors": 379, "rank": 92, "retention": 0.6842},
            "similar_shipped": {"above_floors": 3, "rank": None},
            "grade": "A",
            "note": "E16 extended to the canonical ensemble: entropy nonnegativity across the StatMech/quantum-information divide. Same standard as T1 (Hₛ_nonneg ~ Sᵥₙ_nonneg), and the shallowest member of its family. No citation link between the two formalizations in physlib.",
        },
        {
            "left": "Hₛ_nonneg", "right": "CanonicalEnsemble.entropy_nonneg",
            "pair": "ClassicalInfo ~ StatisticalMechanics",
            "left_stmt": "theorem Hₛ_nonneg (d : ProbDistribution α) : 0 ≤ Hₛ d",
            "right_stmt": "lemma entropy_nonneg [...] : 0 ≤ 𝓒.shannonEntropy T",
            "lgg_conclusion": {"common": 22, "retention": 0.7586},
            "similar_budget_2000": {"above_floors": 108, "rank": 56, "retention": 0.6316},
            "similar_shipped": {"above_floors": 13, "rank": None},
            "grade": "A",
            "note": "Same functional -Σ p log p on both sides (abstract vs Boltzmann-weighted with kB). Divide crossed is information theory vs thermodynamics, not classical vs quantum.",
        },
        {
            "left": "Sᵥₙ_relabel", "right": "CanonicalEnsemble.phase_space_unit_congr",
            "pair": "Entropy ~ StatisticalMechanics", "budget_only_dictionary_row": True,
            "lgg_conclusion": {"common": 28, "retention": 0.7179},
            "grade": "B",
            "note": "Entropy invariant under relabeling vs ensemble quantities invariant under phase-space unit change; invariance-under-reparametrization on both sides, no shared physics beyond that.",
        },
        {
            "left": "Sᵥₙ_unit_zero", "right": "CanonicalEnsemble.partitionFunction_dof_zero",
            "pair": "Entropy ~ StatisticalMechanics", "budget_only_dictionary_row": True,
            "lgg_conclusion": {"common": 15, "retention": 0.6},
            "grade": "B",
            "note": "The trivial system is trivial, on both sides.",
        },
        {
            "left": "Sᵥₙ_subadditivity", "right": "CanonicalEnsemble.mathematicalPartitionFunction_add",
            "pair": "Entropy ~ StatisticalMechanics", "budget_only_dictionary_row": False,
            "lgg_conclusion": {"common": 46, "retention": 0.4071},
            "grade": "B",
            "note": "Subadditivity of entropy vs additivity of the partition function under composition — the extensivity family. Already returned at the shipped cutoff, so not a repair finding.",
        },
    ],
}


def main() -> None:
    on = json.loads((SCRATCH / "hunt-on.json").read_text())
    off = json.loads((SCRATCH / "hunt-off.json").read_text())
    ranked = json.loads((SCRATCH / "hunt-ranked.json").read_text())
    queue = json.loads((SCRATCH / "hunt-queue.json").read_text())

    for row in queue:
        g, why = PRIMARY_GRADES[row["queue_id"]]
        row["grade"] = g
        row["grade_note"] = why
        # Keep the JSON light: drop the raw I3 where Lean source was found and graded —
        # but a generated/no-source row has no other statement record, so its I3 stays.
        for side in ("left", "right"):
            if (row.get(f"{side}_src") or {}).get("source"):
                row.pop(f"{side}_stmt_i3", None)

    real = [r for r in queue if r["source"] == "real"]
    ctrl = [r for r in queue if r["source"] == "control"]

    def tally(rows):
        t = {"A": 0, "B": 0, "C": 0, "D": 0}
        for r in rows:
            t[r["grade"]] += 1
        return t

    # The off arm's full row lists, and the rows the budget *displaced* (present off,
    # absent on: per_decl=1 re-assigned their left) — without these the on arm cannot be
    # audited from this file alone.
    off_rows = {k: p.get("rows", []) for k, p in off["pairs"].items() if p.get("rows")}
    displaced = []
    for key, orec in off["pairs"].items():
        on_set = {(r["left"], r["right"]) for r in on["pairs"].get(key, {}).get("rows", [])}
        for r in orec.get("rows", []):
            if (r["left"], r["right"]) not in on_set:
                displaced.append({**r, "pair": key})

    out = {
        "date": "2026-08-06",
        "corpus": {"path": "/tmp/pfx-base.jsonl", "declarations": on["declarations"]},
        "method": {
            "arms": {"on": {"posting_work_budget": 2000}, "off": {"posting_work_budget": None}},
            "dictionary_call": "per_decl=1, theorems_only=True, anchor='conclusion', score='retention' (shipped floors: min_common=6, min_retention=0.30)",
            "theory_partition": "top-level module prefix (Physlib./QuantumInfo. roots pre-stripped)",
            "eligibility": "both sides >= 50 declarations; Mathlib/Init/Lean/Std/Batteries/Aesop excluded",
            "direction": on["direction_rule"],
            "pairs_total": on["pairs_total"],
            "pairs_covered_on": on["pairs_covered"],
            "pairs_covered_off": off["pairs_covered"],
            "wall_s": {"on": on["wall_s"], "off": off["wall_s"]},
            "support_def": ranked["support_def"],
            "rank_key": ranked["rank_key"],
            "grader": "Claude (implementing agent), grading alone by reading both statements; procedural blinding only — names remained visible",
            "queue_shuffle_seed": ranked["seed"],
        },
        "theories": on["theories"],
        "pair_table": ranked["table"],
        "budget_only": {
            "total": ranked["budget_only_total"],
            "by_kind": {"physics": 3029, "infra": 1608, "control": 15},
            "known_rows_recovered": ranked["budget_only_known"],
            "all_rows": ranked["budget_only_all"],
        },
        "off_rows_by_pair": off_rows,
        "displaced_rows": displaced,
        "known_row_ranks_under_assigned_key": {
            "note": "rank among 3,029 physics budget-only rows under retention*common vs retention alone",
            "rows": [
                {"row": "Hₛ_constant_eq_zero ~ Sᵥₙ_of_pure_zero", "by_key": 437, "by_retention": 124},
                {"row": "Hₛ_nonneg ~ Sᵥₙ_nonneg", "by_key": 438, "by_retention": 17},
                {"row": "Hₛ_le_log_d ~ Sᵥₙ_le_log_d", "by_key": 661, "by_retention": 212},
                {"row": "Hₛ_uniform ~ Sᵥₙ_le_log_d", "by_key": 855, "by_retention": 413},
                {"row": "H₁_nonneg ~ Sᵥₙ_nonneg", "by_key": 1150, "by_retention": 525},
            ],
        },
        "primary_queue": queue,
        "primary_tally": {"real": tally(real), "control": tally(ctrl)},
        "secondary_by_retention": [
            {"left": l, "right": r, "retention": ret, "grade": g, "note": n}
            for l, r, ret, g, n in SECONDARY
        ],
        "secondary_tally": {
            "A": 0,
            "B": sum(1 for x in SECONDARY if x[3] == "B"),
            "C": sum(1 for x in SECONDARY if x[3] == "C"),
            "D": sum(1 for x in SECONDARY if x[3] == "D"),
        },
        "posthoc_entropy_bridge": POSTHOC,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")
    print("primary real tally:", tally(real), " control tally:", tally(ctrl))


if __name__ == "__main__":
    main()
