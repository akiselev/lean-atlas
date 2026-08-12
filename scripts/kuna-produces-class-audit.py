#!/usr/bin/env python3
"""Audit the explicit instance-status split on one frozen historical closure."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import resource
import sys
import time

from atlas_home import HomeIndex


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", required=True, type=pathlib.Path)
    parser.add_argument("--target", default="Module.Finite.finite_basis")
    parser.add_argument("--example-limit", type=int, default=50)
    args = parser.parse_args()

    started = time.monotonic()
    rows: dict[str, dict] = {}
    metadata_unknown = 0
    with args.closure.open("rb") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["name"]] = row
            if not isinstance(row.get("is_instance"), bool):
                metadata_unknown += 1
            if line_number % 50_000 == 0:
                print(f"[load] {line_number} rows", file=sys.stderr)
    loaded = time.monotonic()

    def progress(count: int) -> None:
        print(f"[index] {count}/{len(rows)} rows", file=sys.stderr)

    index = HomeIndex(rows, progress=progress)
    indexed = time.monotonic()

    population = sorted(index.produces_class)
    by_kind_status: collections.Counter[tuple[str, str]] = collections.Counter()
    conclusion_classes: collections.Counter[str] = collections.Counter()
    method_outcomes: collections.Counter[str] = collections.Counter()
    method_outcomes_by_kind: collections.Counter[tuple[str, str]] = collections.Counter()
    binder_verdicts: collections.Counter[str] = collections.Counter()
    candidate_families: collections.Counter[tuple[str, str]] = collections.Counter()
    candidate_declarations_by_kind: collections.Counter[str] = collections.Counter()
    candidate_binders_by_kind: collections.Counter[str] = collections.Counter()
    raw_proposals_by_kind: collections.Counter[str] = collections.Counter()
    registered_leaks: list[str] = []
    examples: list[dict] = []
    candidate_declarations = 0
    candidate_binders = 0
    raw_proposals = 0
    projection_like_candidates = 0

    for name in population:
        row = rows[name]
        kind = row.get("kind") or "missing"
        status = "registered-instance" if row["is_instance"] else "non-instance"
        by_kind_status[(kind, status)] += 1
        conclusion_classes[index.concl.get(name) or "missing"] += 1
        result = index.carrier_statement_candidates(name)
        if result is None:
            method_outcomes["not-judgeable"] += 1
            method_outcomes_by_kind[(kind, "not-judgeable")] += 1
            continue
        if "skipped" in result:
            method_outcomes[result["skipped"]] += 1
            method_outcomes_by_kind[(kind, result["skipped"])] += 1
            continue

        method_outcomes["judged"] += 1
        method_outcomes_by_kind[(kind, "judged")] += 1
        if row["is_instance"]:
            registered_leaks.append(name)
        event_rows = []
        for binder in result["binders"]:
            binder_verdicts[binder["verdict"]] += 1
            candidates = binder.get("candidates") or []
            if not candidates:
                continue
            candidate_binders += 1
            candidate_binders_by_kind[kind] += 1
            raw_proposals += len(candidates)
            raw_proposals_by_kind[kind] += len(candidates)
            for candidate in candidates:
                candidate_families[(binder["class"], candidate)] += 1
            event_rows.append({
                "class": binder["class"],
                "carrier": binder.get("carrier"),
                "reached": binder.get("reached") or [],
                "candidates": candidates,
            })
        if event_rows:
            candidate_declarations += 1
            candidate_declarations_by_kind[kind] += 1
            if result.get("projection_like"):
                projection_like_candidates += 1
            if len(examples) < args.example_limit:
                examples.append({
                    "name": name,
                    "kind": row.get("kind"),
                    "conclusion_class": index.concl.get(name),
                    "projection_like": result.get("projection_like"),
                    "binders": event_rows,
                })

    target = {
        "home": index.home(args.target),
        "statement_candidates": index.statement_candidates(args.target),
        "carrier_statement_candidates": index.carrier_statement_candidates(args.target),
        "is_instance": rows[args.target].get("is_instance"),
        "conclusion_class": index.concl.get(args.target),
    }
    audited = time.monotonic()

    result = {
        "schema": "atlas-kuna-e1-mc1-audit-v1",
        "closure": str(args.closure),
        "closure_sha256": sha256_file(args.closure),
        "rows": len(rows),
        "metadata_unknown_rows": metadata_unknown,
        "index": {
            "classes": len(index.classes),
            "parent_edges": sum(len(parents) for parents in index.parents.values()),
            "forgetful": len(index.forgetful),
            "parse_errors": index.parse_errors,
        },
        "class_producing_population": {
            "rows": len(population),
            "registered_instances": sum(
                count for (kind, status), count in by_kind_status.items()
                if status == "registered-instance"
            ),
            "non_instances": sum(
                count for (kind, status), count in by_kind_status.items()
                if status == "non-instance"
            ),
            "by_kind_and_status": [
                {"kind": kind, "status": status, "rows": count}
                for (kind, status), count in sorted(by_kind_status.items())
            ],
            "top_conclusion_classes": [
                {"class": cls, "rows": count}
                for cls, count in conclusion_classes.most_common(30)
            ],
        },
        "carrier_policy": {
            "method_outcomes": dict(sorted(method_outcomes.items())),
            "method_outcomes_by_kind": [
                {"kind": kind, "outcome": outcome, "rows": count}
                for (kind, outcome), count in sorted(method_outcomes_by_kind.items())
            ],
            "registered_instances_entering_judgment": len(registered_leaks),
            "registered_instance_leaks": registered_leaks,
            "candidate_declarations": candidate_declarations,
            "candidate_declarations_by_kind": dict(
                sorted(candidate_declarations_by_kind.items())
            ),
            "candidate_binders": candidate_binders,
            "candidate_binders_by_kind": dict(sorted(candidate_binders_by_kind.items())),
            "raw_proposals": raw_proposals,
            "raw_proposals_by_kind": dict(sorted(raw_proposals_by_kind.items())),
            "projection_like_candidate_declarations": projection_like_candidates,
            "binder_verdicts": dict(sorted(binder_verdicts.items())),
            "candidate_families": [
                {"source": source, "target": target, "events": count}
                for (source, target), count in candidate_families.most_common()
            ],
            "candidate_examples": examples,
        },
        "target": target,
        "timing_seconds": {
            "load": round(loaded - started, 3),
            "index": round(indexed - loaded, 3),
            "audit": round(audited - indexed, 3),
            "total_before_hash": round(audited - started, 3),
        },
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
