#!/usr/bin/env python3
"""Freeze a family-balanced sample of MC1 theorem-claim proposals.

This selector reads the frozen historical closure and reruns only the already accepted,
default-off carrier proposal method.  It does not elaborate a weakened statement and it
does not invoke a prover.  That separation is deliberate: the manifest must exist before
any outcome-bearing historical Lean command is run.

The sampling unit is an exact candidate-bearing instance binder and target class.  Families
are ``source class -> target class`` pairs.  Projection-like and non-projection declarations
are crossed with three within-status family-frequency bins, then a SHA-256 rank chooses
eight families per cell and one proposal per family.  The result is family-balanced evidence,
not a population-weighted estimate over all raw proposals.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import resource
import sys
import time

from atlas_home import HomeIndex


DEFAULT_SEED = "atlas-kuna-e1-mc2-family-balanced-v1-2026-08-07"


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def rank(seed: str, *parts: object) -> str:
    material = "\x1f".join([seed, *(str(part) for part in parts)])
    return hashlib.sha256(material.encode()).hexdigest()


def frequency_bin(events: int) -> str:
    if events == 1:
        return "singleton"
    if events <= 4:
        return "small-2-4"
    return "recurrent-5-plus"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", required=True, type=pathlib.Path)
    parser.add_argument("--detector", default=pathlib.Path("scripts/atlas_home.py"),
                        type=pathlib.Path)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--families-per-cell", default=8, type=int)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    started = time.monotonic()
    rows: dict[str, dict] = {}
    with args.closure.open("rb") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["name"]] = row
            if line_number % 50_000 == 0:
                print(f"[load] {line_number} rows", file=sys.stderr)
    loaded = time.monotonic()

    def progress(count: int) -> None:
        print(f"[index] {count}/{len(rows)} rows", file=sys.stderr)

    index = HomeIndex(rows, progress=progress)
    indexed = time.monotonic()

    proposals: list[dict] = []
    candidate_declarations = 0
    for name in sorted(index.produces_class):
        result = index.carrier_statement_candidates(name)
        if result is None or "skipped" in result:
            continue
        binders = result["binders"]
        raw_instance_binders: list[tuple[str, int]] = []
        raw_instance_index = 0
        for binder_info, head, _args, _depth in index.binders[name]:
            if binder_info != "t":
                continue
            if head:
                raw_instance_binders.append((head, raw_instance_index))
            raw_instance_index += 1
        if [head for head, _raw in raw_instance_binders] != [
            binder["class"] for binder in binders
        ]:
            raise SystemExit(f"binder-order drift in {name}")
        source_totals = collections.Counter(binder["class"] for binder in binders)
        source_seen: collections.Counter[str] = collections.Counter()
        declaration_has_candidate = False
        for binder_index, binder in enumerate(binders):
            source = binder["class"]
            source_occurrence = source_seen[source]
            source_seen[source] += 1
            for target in binder.get("candidates") or ():
                declaration_has_candidate = True
                proposals.append({
                    "declaration": name,
                    "module": result.get("module"),
                    "projection_like": bool(result.get("projection_like")),
                    "binder_index": binder_index,
                    "raw_instance_binder_index": raw_instance_binders[binder_index][1],
                    "source_occurrence": source_occurrence,
                    "source_occurrences": source_totals[source],
                    "carrier": binder.get("carrier"),
                    "source": source,
                    "target": target,
                    "reached": binder.get("reached") or [],
                })
        candidate_declarations += int(declaration_has_candidate)

    # These counts are the frozen MC1 population contract.  A mismatch means the selector
    # is no longer sampling the experiment MC1 described, so fail before emitting a manifest.
    if len(rows) != 106_733:
        raise SystemExit(f"closure drift: expected 106733 rows, found {len(rows)}")
    if candidate_declarations != 133 or len(proposals) != 834:
        raise SystemExit(
            "proposal drift: expected 133 declarations / 834 proposals, found "
            f"{candidate_declarations} / {len(proposals)}"
        )

    by_family: dict[tuple[bool, str, str], list[dict]] = collections.defaultdict(list)
    for proposal in proposals:
        key = (proposal["projection_like"], proposal["source"], proposal["target"])
        by_family[key].append(proposal)

    cells: dict[tuple[bool, str], list[tuple[tuple[bool, str, str], list[dict]]]] = \
        collections.defaultdict(list)
    for family, events in by_family.items():
        cells[(family[0], frequency_bin(len(events)))].append((family, events))

    expected_cells = {
        (projection_like, bin_name)
        for projection_like in (False, True)
        for bin_name in ("singleton", "small-2-4", "recurrent-5-plus")
    }
    if set(cells) != expected_cells:
        raise SystemExit(f"sampling-cell drift: {sorted(cells)}")

    selected: list[dict] = []
    strata: list[dict] = []
    for projection_like, bin_name in sorted(expected_cells):
        eligible = cells[(projection_like, bin_name)]
        if len(eligible) < args.families_per_cell:
            raise SystemExit(
                f"underfilled cell projection_like={projection_like}, bin={bin_name}: "
                f"{len(eligible)} families"
            )
        ranked_families = sorted(
            eligible,
            key=lambda item: (
                rank(args.seed, "family", projection_like, bin_name,
                     item[0][1], item[0][2]),
                item[0][1],
                item[0][2],
            ),
        )
        chosen_families = ranked_families[: args.families_per_cell]
        stratum_rows = []
        for family, events in chosen_families:
            ranked_events = sorted(
                events,
                key=lambda event: (
                    rank(args.seed, "proposal", event["declaration"],
                         event["binder_index"], event["source"], event["target"]),
                    event["declaration"],
                    event["binder_index"],
                ),
            )
            chosen = dict(ranked_events[0])
            chosen["family_events_in_status"] = len(events)
            chosen["frequency_bin"] = bin_name
            chosen["proposal_rank_sha256"] = rank(
                args.seed, "proposal", chosen["declaration"], chosen["binder_index"],
                chosen["source"], chosen["target"]
            )
            selected.append(chosen)
            stratum_rows.append({
                "source": family[1],
                "target": family[2],
                "family_events_in_status": len(events),
                "eligible_proposals": len(events),
                "selected_declaration": chosen["declaration"],
                "selected_binder_index": chosen["binder_index"],
            })
        strata.append({
            "projection_like": projection_like,
            "frequency_bin": bin_name,
            "eligible_families": len(eligible),
            "selected_families": len(chosen_families),
            "families": stratum_rows,
        })

    # Probe order is separate from selection rank.  Keeping it lexical makes logs and a
    # partial rerun easy to audit without changing who was selected.
    selected.sort(key=lambda row: (
        row["projection_like"], row["frequency_bin"], row["source"], row["target"],
        row["declaration"], row["binder_index"]
    ))
    for probe_index, proposal in enumerate(selected, 1):
        proposal["probe_index"] = probe_index
        proposal["proposal_id"] = (
            f"mc2-{probe_index:02d}:" + canonical_sha256({
                key: proposal[key]
                for key in ("declaration", "binder_index", "source", "target")
            })[:16]
        )

    population_fingerprint_rows = [{
        key: proposal[key]
        for key in ("declaration", "binder_index", "raw_instance_binder_index",
                    "source_occurrence",
                    "carrier", "source", "target", "projection_like")
    } for proposal in proposals]
    population_fingerprint_rows.sort(key=lambda row: (
        row["declaration"], row["binder_index"], row["source"], row["target"]
    ))
    selected_fingerprint = [{
        key: proposal[key]
        for key in ("declaration", "binder_index", "source", "target")
    } for proposal in selected]

    completed = time.monotonic()
    manifest = {
        "schema": "atlas-kuna-e1-mc2-manifest-v1",
        "status": "frozen-before-historical-statement-or-proof-probing",
        "executed_at": dt.date.today().isoformat(),
        "question": (
            "On a deterministic family-balanced sample of MC1 theorem-claim proposals, "
            "which weakenings form type-correct historical statements and which are "
            "proved by the frozen bounded tactic ladder and accepted by the Lean kernel?"
        ),
        "outcome_blinding": {
            "statement_or_proof_outputs_seen_before_freeze": False,
            "selection_inputs": "MC1 closure rows and default-off detector outputs only",
        },
        "historical_environment": {
            "parent": "71f079f9d2860606575d65f12a9ad4e34d80a841",
            "toolchain": "leanprover/lean4:v4.12.0-rc1",
            "module": "Mathlib.RingTheory.Finiteness",
            "worktree": "/tmp/atlas-kuna-mc0-p2-71f079f9",
        },
        "inputs": {
            "closure": str(args.closure),
            "closure_rows": len(rows),
            "closure_sha256": sha256_file(args.closure),
            "detector": str(args.detector),
            "detector_sha256": sha256_file(args.detector),
            "method": "HomeIndex.carrier_statement_candidates",
        },
        "population": {
            "candidate_declarations": candidate_declarations,
            "raw_proposals": len(proposals),
            "family_status_cells": len(by_family),
            "source_target_families_ignoring_projection_status": len({
                (proposal["source"], proposal["target"]) for proposal in proposals
            }),
            "projection_like_proposals": sum(
                proposal["projection_like"] for proposal in proposals
            ),
            "non_projection_proposals": sum(
                not proposal["projection_like"] for proposal in proposals
            ),
            "canonical_sha256": canonical_sha256(population_fingerprint_rows),
        },
        "selection": {
            "estimand": "family-balanced diagnostic surface, not raw-proposal prevalence",
            "seed": args.seed,
            "rank": "lexical SHA-256 of seed and stable family/proposal identity",
            "frequency_bins": {
                "singleton": "1 proposal in this source-target/projection-status cell",
                "small-2-4": "2 through 4 proposals",
                "recurrent-5-plus": "5 or more proposals",
            },
            "families_per_projection_frequency_cell": args.families_per_cell,
            "sample_proposals": len(selected),
            "sample_canonical_sha256": canonical_sha256(selected_fingerprint),
            "strata": strata,
            "proposals": selected,
        },
        "probe_protocol": {
            "source_binder_identity": (
                "exact raw instance-binder index and source-class occurrence recorded in "
                "the manifest; duplicate source classes must never be silently collapsed"
            ),
            "statement_gate": (
                "rewrite exactly the selected instance binder, re-synthesise instance "
                "arguments across the full telescope, and require isTypeCorrect"
            ),
            "kernel_gate": (
                "try rfl, simp, aesop, exact? in that order; reject sorryAx and unresolved "
                "metavariables; accept success only when addDeclCore accepts the theorem"
            ),
            "ladder": ["rfl", "simp", "aesop", "exact?"],
            "max_heartbeats_per_command": 1_000_000,
            "controls_per_shard": {
                "atlas_mc2_plant_easy": "PROVED",
                "atlas_mc2_plant_hard": "not proved by the ladder",
                "atlas_mc2_plant_no_statement": "NO STATEMENT",
            },
            "failure_semantics": {
                "PROVED": "sound theorem for the exact sampled weakening",
                "not proved by the ladder": "bounded search miss, not evidence of falsehood",
                "NO STATEMENT": "proposal-lane refusal, not evidence of falsehood",
                "environment_failure": "no semantic verdict",
            },
        },
        "preregistered_decision_rule": {
            "valid_run": "every shard has all three expected controls and all 48 data verdicts",
            "statement_gate_good": (
                "at least 90% statable overall and at least 80% statable separately in "
                "projection-like and non-projection strata"
            ),
            "proof_signal_good": "at least one kernel-proved proposal in each projection status",
            "if_both_good": (
                "advance to a population-weighted historical validation; do not activate "
                "the detector by default from this family-balanced sample"
            ),
            "if_statement_gate_bad": (
                "keep the lane default-off and localize statement-generation failures "
                "before increasing the campaign"
            ),
            "if_proof_signal_bad": (
                "report that the frozen ladder adds no measured confirmation in the missing "
                "status; do not interpret its misses as false proposals"
            ),
        },
        "timing_seconds": {
            "load": round(loaded - started, 3),
            "index": round(indexed - loaded, 3),
            "selection": round(completed - indexed, 3),
            "total_before_output": round(completed - started, 3),
        },
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"frozen {len(selected)} proposals -> {args.output}")
    print(f"sample sha256: {manifest['selection']['sample_canonical_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
