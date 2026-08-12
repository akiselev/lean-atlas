#!/usr/bin/env python3
"""Score historical Lean logs for the frozen MC2 proposal sample."""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re


LINE = re.compile(r"Atlas MC2 `([^`]+)` \[(\d+)\] (\S+) -> (\S+): (.*)")
CONTROLS = {
    ("atlas_mc2_plant_easy", 0, "CommRing", "AddCommMagma"): "proved",
    ("atlas_mc2_plant_hard", 0, "CommRing", "AddCommMagma"): "not_proved",
    ("atlas_mc2_plant_no_statement", 0, "CommRing", "AddCommMagma"): "no_statement",
}


def classify(tail: str) -> tuple[str, str]:
    if tail.startswith("PROVED by "):
        return "proved", tail.removeprefix("PROVED by ").strip()
    if tail.startswith("not proved by the ladder"):
        return "not_proved", ""
    if tail.endswith("NO STATEMENT"):
        return "no_statement", tail.rsplit("— NO STATEMENT", 1)[0].strip()
    return "unrecognised", tail


def parse_log(text: str) -> dict[tuple[str, int, str, str], tuple[str, str]]:
    verdicts = {}
    for line in text.splitlines():
        if match := LINE.search(line):
            key = (match.group(1), int(match.group(2)), match.group(3), match.group(4))
            verdicts[key] = classify(match.group(5))
    return verdicts


def summarize(rows: list[dict]) -> dict:
    counts = collections.Counter(row["verdict"] for row in rows)
    statable = counts["proved"] + counts["not_proved"]
    return {
        "sample": len(rows),
        "proved": counts["proved"],
        "not_proved": counts["not_proved"],
        "no_statement": counts["no_statement"],
        "statable": statable,
        "statable_rate": round(statable / len(rows), 6) if rows else None,
        "proved_rate_among_statable": (
            round(counts["proved"] / statable, 6) if statable else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-probe-index.json"))
    parser.add_argument("--log-dir", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-logs"))
    parser.add_argument("--output", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-scored.json"))
    args = parser.parse_args()

    index = json.loads(args.index.read_text())
    scored = []
    invalid_shards = []
    incomplete_shards = []
    missing = []
    for shard in index["shards"]:
        log_path = args.log_dir / f"{shard['name']}.log"
        if not log_path.exists():
            incomplete_shards.append({"shard": shard["name"], "reason": "missing log"})
            missing.extend(p["proposal_id"] for p in shard["proposals"])
            continue
        text = log_path.read_text(errors="replace")
        exit_match = re.search(r"^EXIT=(\d+)\s*$", text, re.MULTILINE)
        if not exit_match:
            incomplete_shards.append({"shard": shard["name"], "reason": "missing exit"})
        elif exit_match.group(1) != "0":
            incomplete_shards.append({
                "shard": shard["name"], "reason": f"exit {exit_match.group(1)}"
            })
        verdicts = parse_log(text)
        bad_controls = []
        for key, expected in CONTROLS.items():
            got = verdicts.get(key)
            if got is None:
                bad_controls.append(f"{key[0]} missing")
            elif got[0] != expected:
                bad_controls.append(f"{key[0]}={got[0]}, expected {expected}")
        if bad_controls:
            invalid_shards.append({"shard": shard["name"], "controls": bad_controls})
            missing.extend(p["proposal_id"] for p in shard["proposals"])
            continue
        for proposal in shard["proposals"]:
            key = (
                proposal["declaration"], proposal["raw_instance_binder_index"],
                proposal["source"], proposal["target"]
            )
            got = verdicts.get(key)
            if got is None:
                missing.append(proposal["proposal_id"])
                continue
            row = dict(proposal)
            row["verdict"], detail = got
            if row["verdict"] == "proved":
                row["tactic"] = detail
            elif row["verdict"] == "no_statement":
                row["reason"] = detail
            scored.append(row)

    by_projection = {}
    for projection_like in (False, True):
        rows = [row for row in scored if row["projection_like"] == projection_like]
        by_projection[str(projection_like).lower()] = summarize(rows)
    by_frequency = {
        frequency: summarize([row for row in scored if row["frequency_bin"] == frequency])
        for frequency in ("singleton", "small-2-4", "recurrent-5-plus")
    }
    by_cell = []
    for projection_like in (False, True):
        for frequency in ("singleton", "small-2-4", "recurrent-5-plus"):
            rows = [
                row for row in scored
                if row["projection_like"] == projection_like
                and row["frequency_bin"] == frequency
            ]
            by_cell.append({
                "projection_like": projection_like,
                "frequency_bin": frequency,
                **summarize(rows),
            })

    overall = summarize(scored)
    valid = (
        not invalid_shards and not incomplete_shards and not missing
        and len(scored) == index["total"]
        and all(row["verdict"] != "unrecognised" for row in scored)
    )
    statement_good = (
        valid and overall["statable_rate"] >= 0.9
        and all(by_projection[key]["statable_rate"] >= 0.8 for key in ("false", "true"))
    )
    proof_good = (
        valid and all(by_projection[key]["proved"] >= 1 for key in ("false", "true"))
    )
    tactic_wins = collections.Counter(
        row["tactic"] for row in scored if row["verdict"] == "proved"
    )
    refusal_reasons = collections.Counter(
        row["reason"] for row in scored if row["verdict"] == "no_statement"
    )
    result = {
        "schema": "atlas-kuna-e1-mc2-scored-v1",
        "index": str(args.index),
        "sample": index["total"],
        "valid": valid,
        "invalid_shards": invalid_shards,
        "incomplete_shards": incomplete_shards,
        "missing": missing,
        "overall": overall,
        "by_projection_like": by_projection,
        "by_frequency": by_frequency,
        "by_cell": by_cell,
        "tactic_wins": dict(tactic_wins),
        "no_statement_reasons": dict(refusal_reasons),
        "preregistered_gates": {
            "statement_gate_good": statement_good,
            "proof_signal_good": proof_good,
        },
        "proposals": sorted(scored, key=lambda row: row["probe_index"]),
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"valid: {valid}")
    print(json.dumps(overall, sort_keys=True))
    print(f"statement gate: {statement_good}; proof signal: {proof_good}")
    print(f"-> {args.output}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
