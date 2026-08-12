#!/usr/bin/env python3
"""Persist the final, control-gated MC2 measurement with artifact provenance."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=pathlib.Path,
                        default=pathlib.Path("research/data/kuna-e1-mc2-manifest.json"))
    parser.add_argument("--index", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-probe-index.json"))
    parser.add_argument("--scored", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-scored.json"))
    parser.add_argument("--log-dir", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-logs"))
    parser.add_argument("--output", type=pathlib.Path,
                        default=pathlib.Path("research/data/kuna-e1-mc2-result.json"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    index = json.loads(args.index.read_text())
    scored = json.loads(args.scored.read_text())
    if index["manifest_sha256"] != sha256_file(args.manifest):
        raise SystemExit("probe index does not name the frozen manifest bytes")
    if not scored["valid"] or scored["sample"] != 48:
        raise SystemExit("refusing to persist an invalid or incomplete MC2 score")

    logs = []
    for shard in index["shards"]:
        path = args.log_dir / f"{shard['name']}.log"
        text = path.read_text(errors="replace")
        if not text.rstrip().endswith("EXIT=0"):
            raise SystemExit(f"unclean final log: {path}")
        logs.append({
            "shard": shard["name"],
            "path": str(path),
            "sha256": sha256_file(path),
            "probe_source": shard["file"],
            "probe_source_sha256": shard["file_sha256"],
            "proposals": len(shard["proposals"]),
            "exit": 0,
        })

    statement_good = scored["preregistered_gates"]["statement_gate_good"]
    proof_good = scored["preregistered_gates"]["proof_signal_good"]
    result = {
        "schema": "atlas-kuna-e1-mc2-result-v1",
        "status": "completed-family-balanced-statement-and-kernel-probe",
        "executed_at": dt.date.today().isoformat(),
        "manifest": {
            "path": str(args.manifest),
            "sha256": sha256_file(args.manifest),
            "sample_canonical_sha256": manifest["selection"]["sample_canonical_sha256"],
            "sample_proposals": manifest["selection"]["sample_proposals"],
            "outcome_blinding": manifest["outcome_blinding"],
        },
        "claim_boundary": (
            "a deterministic family-balanced diagnostic sample over one historical closure; "
            "not a raw-proposal prevalence estimate, detector recall estimate, or proof of "
            "falsehood for bounded tactic misses"
        ),
        "historical_environment": {
            "parent": "71f079f9d2860606575d65f12a9ad4e34d80a841",
            "toolchain": "leanprover/lean4:v4.12.0-rc1",
            "lean_version": "4.12.0-rc1, commit e9e858a44849",
            "module": "Mathlib.RingTheory.Finiteness",
            "reconstructed_worktree": "/tmp/atlas-kuna-mc2-p2-71f079f9",
            "target_build": "1059/1059 jobs, exit 0",
            "environment_failures": 0,
        },
        "probe": {
            "support": index["support"],
            "support_sha256": index["support_sha256"],
            "index": str(args.index),
            "index_sha256": sha256_file(args.index),
            "scored": str(args.scored),
            "scored_sha256": sha256_file(args.scored),
            "ladder": index["ladder"],
            "max_heartbeats_per_command": index["max_heartbeats_per_command"],
            "shards": logs,
            "controls": (
                "all four shards returned PROVED / not proved / NO STATEMENT for the "
                "easy / hard / malformed plants and exited 0"
            ),
            "final_valid": scored["valid"],
        },
        "probe_repairs_before_final_run": [
            {
                "issue": "five selected proposals have repeated source-class binders",
                "repair": (
                    "address the exact raw instance-binder index frozen in the manifest "
                    "and assert its source-class head"
                ),
                "selection_or_ladder_change": False,
            },
            {
                "issue": (
                    "same-total-arity rebuilding falsely refused ancestors whose source "
                    "class has hidden instance parameters, such as MulAction -> SMul"
                ),
                "repair": (
                    "align source and target class telescopes on structural parameters and "
                    "synthesize target instance parameters in the historical context"
                ),
                "selection_or_ladder_change": False,
            },
            {
                "issue": "failed target-instance synthesis escaped as a shard-level error",
                "repair": (
                    "isolate its message and InfoTree channels and record the expected "
                    "failure as NO STATEMENT"
                ),
                "selection_or_ladder_change": False,
            },
        ],
        "statement_refusal_localization": {
            "diagnostic_source": "research/probes/kuna-mc2-refusal-check.lean",
            "diagnostic_source_sha256": sha256_file(
                pathlib.Path("research/probes/kuna-mc2-refusal-check.lean")
            ),
            "diagnostic_log": "/tmp/atlas-kuna-mc2-refusal-check.log",
            "diagnostic_log_sha256": sha256_file(
                pathlib.Path("/tmp/atlas-kuna-mc2-refusal-check.log")
            ),
            "diagnostic_exit": 1,
            "diagnostic_exit_expected": True,
            "dependent_statement_failures": [
                {
                    "probe_index": 9,
                    "proposal": "AddCommGroup -> AddCancelCommMonoid",
                    "missing_instance": "SMul Int M",
                },
                {
                    "probe_index": 16,
                    "proposal": "Preorder -> LE",
                    "missing_instance": "LE (WithZero alpha)",
                },
                {
                    "probe_index": 19,
                    "proposal": "DistribMulAction -> SMul",
                    "missing_instance": "SMul alpha (AddSubmonoid A)",
                },
            ],
            "unqualified_lattice_edge_failures": [
                {
                    "probe_index": 23,
                    "proposal": "NoZeroDivisors -> IsDomain",
                    "edge_source": "NoZeroDivisors.to_isDomain",
                    "independent_premises": ["Ring alpha", "Nontrivial alpha"],
                },
                {
                    "probe_index": 39,
                    "proposal": "SMulMemClass -> MulAction",
                    "edge_source": "SMulMemClass.toModule then Module ancestry",
                    "failure": (
                        "toModule has independent algebraic premises and concludes Module "
                        "on a subtype rather than the source carrier"
                    ),
                },
                {
                    "probe_index": 46,
                    "proposal": "IsRightCancelMulZero -> IsDomain",
                    "edge_source": (
                        "IsRightCancelMulZero.to_noZeroDivisors then "
                        "NoZeroDivisors.to_isDomain"
                    ),
                    "independent_premises": ["NonUnitalNonAssocRing alpha", "Ring alpha", "Nontrivial alpha"],
                },
            ],
            "finding": (
                "all six refusals reproduce outside the probe: three exact weakened "
                "signatures lack dependent instances, and three traverse HomeIndex parent "
                "edges inferred from .to names that carry extra premises or change carriers"
            ),
        },
        "measurement": {
            "overall": scored["overall"],
            "by_projection_like": scored["by_projection_like"],
            "by_frequency": scored["by_frequency"],
            "by_cell": scored["by_cell"],
            "tactic_wins": scored["tactic_wins"],
            "no_statement_reasons": scored["no_statement_reasons"],
            "proposals": scored["proposals"],
        },
        "preregistered_gates": {
            "statement_gate_good": statement_good,
            "statement_gate_observed": (
                "42/48 statable overall (87.5%); 20/24 non-projection (83.3%); "
                "22/24 projection-like (91.7%)"
            ),
            "proof_signal_good": proof_good,
            "proof_signal_observed": (
                "1/42 statable proposals kernel-proved (2.4%), projection-like only; "
                "zero non-projection proofs"
            ),
        },
        "decision": {
            "default_activation": "rejected",
            "population_weighted_campaign": "not yet authorized by the preregistered rule",
            "reason": (
                "the overall statement rate missed the 90% gate and the bounded ladder "
                "found no non-projection proof; both preregistered signals therefore failed"
            ),
            "sound_positive": {
                "declaration": "IsLeftCancelMulZero.to_isCancelMulZero",
                "source": "IsLeftCancelMulZero",
                "target": "IsRightCancelMulZero",
                "tactic": "exact?",
                "kernel": "accepted",
            },
            "negative_semantics": (
                "the 41 statable ladder misses are inconclusive, while the six NO STATEMENT "
                "rows are proposal-lane refusals to localize rather than false theorems"
            ),
            "next_refinement": (
                "freeze a qualified parent-edge ablation that retains conversion "
                "preconditions and carrier mappings, then rerun this exact 48-proposal "
                "sample before increasing it or changing default behavior"
            ),
        },
        "runners": {
            "selector": "scripts/kuna-proposal-sample.py",
            "selector_sha256": sha256_file(pathlib.Path("scripts/kuna-proposal-sample.py")),
            "generator": "scripts/kuna-proposal-probes.py",
            "generator_sha256": sha256_file(pathlib.Path("scripts/kuna-proposal-probes.py")),
            "scorer": "scripts/kuna-proposal-score.py",
            "scorer_sha256": sha256_file(pathlib.Path("scripts/kuna-proposal-score.py")),
        },
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"persisted final MC2 result -> {args.output}")
    print(f"sha256: {sha256_file(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
