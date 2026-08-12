#!/usr/bin/env python3
"""Rank budget-only dictionary rows and assemble the blind grading queue.

Input: hunt-on.json / hunt-off.json from hunt-sweep.py.

budget-only row = (left, right) present in the on-arm dictionary of a pair and absent
from the off-arm dictionary of the same pair. Per_decl=1 means a left re-partnered by
the budget also counts, and is flagged `repartnered` so the grader can see it.

support = `common` of the conclusion-anchored anti-unification of the two statements
(atlas.Corpus.generalize) — the number of shared concrete nodes. The ranking key is
retention x common. "support" is not a field the engine exports; this definition is
recorded in the report.

Output: hunt-ranked.json with every budget-only row scored, the pair table, and a
shuffled grading queue (top real rows + control-pair rows, seed pinned) with the I3
statements attached.
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import time

import atlas as fa

SCRATCH = pathlib.Path(os.environ.get("HUNT_DIR", "."))  # work dir for hunt-*.json
BASE = "/tmp/pfx-base.jsonl"

PHYSICS = {
    "Relativity", "Particles", "QFT", "SpaceAndTime", "QuantumMechanics",
    "ClassicalMechanics", "Electromagnetism", "Channels", "States", "StringTheory",
    "StatisticalMechanics", "Entropy", "ClassicalInfo", "ResourceTheory",
    "FluidDynamics", "Thermodynamics", "CondensedMatter",
}
INFRA = {"Meta", "Units", "ForMathlib", "Mathematics"}

# The NC3 precedent pairs (physlib-classical-quantum.md §2d), run through the identical
# pipeline; their budget-only rows are graded blind alongside the real ones.
CONTROL_PAIRS = {"ClassicalMechanics ~ Meta", "Meta ~ Thermodynamics",
                 "Meta ~ ClassicalMechanics", "Thermodynamics ~ Meta"}

# The four pre-registered correspondences (T1-T4) — known, therefore excluded from the
# hunt's numerator. The fifth known row from prefilter §4d is flagged, not silently kept.
KNOWN = {
    ("Hₛ_nonneg", "Sᵥₙ_nonneg"),
    ("Hₛ_constant_eq_zero", "Sᵥₙ_of_pure_zero"),
    ("H₁_nonneg", "Sᵥₙ_nonneg"),
    ("Hₛ_le_log_d", "Sᵥₙ_le_log_d"),
}
KNOWN_FLAGGED = {("Hₛ_uniform", "Sᵥₙ_le_log_d")}

TOP_REAL = 40
TOP_CONTROL = 10
SEED = 20260806


def main() -> None:
    on = json.loads((SCRATCH / "hunt-on.json").read_text())
    off = json.loads((SCRATCH / "hunt-off.json").read_text())
    assert on["pairs_covered"] == on["pairs_total"], "on arm truncated"
    assert off["pairs_covered"] == off["pairs_total"], "off arm truncated"

    t = time.time()
    c = fa.Corpus.load(BASE)
    print(f"loaded {len(c)} in {time.time()-t:.0f}s", flush=True)

    table = []
    budget_only = []
    for key, prec in sorted(on["pairs"].items()):
        orec = off["pairs"].get(key, {})
        on_rows = prec.get("rows", [])
        off_rows = orec.get("rows", [])
        off_set = {(r["left"], r["right"]) for r in off_rows}
        off_lefts = {r["left"] for r in off_rows}
        new = [r for r in on_rows if (r["left"], r["right"]) not in off_set]
        a, b = key.split(" ~ ")
        kind = ("control" if key in CONTROL_PAIRS
                else "physics" if a in PHYSICS and b in PHYSICS
                else "infra")
        table.append({
            "pair": key, "kind": kind,
            "rows_off": len(off_rows), "rows_on": len(on_rows),
            "budget_only": len(new),
            "on_s": prec.get("s"), "off_s": orec.get("s"),
            "error_on": prec.get("error"), "error_off": orec.get("error"),
        })
        for r in new:
            r2 = dict(r)
            r2["pair"] = key
            r2["kind"] = kind
            r2["repartnered"] = r["left"] in off_lefts
            lr = (r["left"], r["right"])
            r2["known"] = "T1-T4" if lr in KNOWN else (
                "prefilter-4d" if lr in KNOWN_FLAGGED else None)
            budget_only.append(r2)

    # support = common concrete nodes of the conclusion-anchored lgg.
    t = time.time()
    for r in budget_only:
        try:
            g = c.generalize(r["left"], r["right"], anchor="conclusion")
            r["common"] = g.common
            r["lgg_retention"] = round(g.retention, 4)
        except Exception as e:
            r["common"] = None
            r["lgg_error"] = f"{type(e).__name__}: {e}"
        r["rank_key"] = (r["retention"] * r["common"]) if r["common"] else 0.0
    print(f"generalize over {len(budget_only)} budget-only rows: "
          f"{time.time()-t:.0f}s", flush=True)

    budget_only.sort(key=lambda r: -r["rank_key"])

    real = [r for r in budget_only
            if r["kind"] == "physics" and r["known"] is None][:TOP_REAL]
    ctrl = [r for r in budget_only if r["kind"] == "control"][:TOP_CONTROL]

    queue = []
    for src, rows in (("real", real), ("control", ctrl)):
        for r in rows:
            queue.append({**r, "source": src})
    random.Random(SEED).shuffle(queue)
    for i, r in enumerate(queue):
        r["queue_id"] = i
        for side in ("left", "right"):
            d = c.get(r[side])
            r[f"{side}_module"] = d.module if d else None
            stmt = d.stmt if d else None
            r[f"{side}_stmt_i3"] = (stmt[:600] + "…") if stmt and len(stmt) > 600 else stmt

    out = {
        "seed": SEED,
        "support_def": "common concrete nodes of generalize(left,right,anchor=conclusion)",
        "rank_key": "retention * common",
        "table": table,
        "budget_only_total": len(budget_only),
        "budget_only_known": [r for r in budget_only if r["known"]],
        "budget_only_all": budget_only,
        "queue": queue,
    }
    (SCRATCH / "hunt-ranked.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"table pairs: {len(table)}; budget-only rows: {len(budget_only)}; "
          f"queue: {len(queue)} ({len(real)} real + {len(ctrl)} control)", flush=True)


if __name__ == "__main__":
    main()
