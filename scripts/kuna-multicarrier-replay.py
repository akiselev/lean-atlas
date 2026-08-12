#!/usr/bin/env python3
"""Run the three frozen Home search lanes on one historical Atlas closure.

This is deliberately a one-parent-at-a-time runner.  Historical closures are large,
and keeping more than one ``HomeIndex`` resident would turn a semantic replay into an
avoidable memory-pressure experiment.
"""

from __future__ import annotations

import argparse
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
    parser.add_argument("--declaration", required=True)
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
    if args.declaration not in rows:
        raise SystemExit(f"declaration not found: {args.declaration}")

    result = {
        "schema": "atlas-kuna-e1-mc0-search-v1",
        "closure": str(args.closure),
        "closure_sha256": sha256_file(args.closure),
        "rows": len(rows),
        "declaration": args.declaration,
        "target_requirements_statement": rows[args.declaration].get(
            "requirements_statement"
        ),
        "instance_binders": index.instance_binders(args.declaration),
        "parameter_aware_instance_binders": index.parameter_aware_instance_binders(
            args.declaration
        ),
        "home": index.home(args.declaration),
        "statement_candidates": index.statement_candidates(args.declaration),
        "carrier_statement_candidates": index.carrier_statement_candidates(
            args.declaration
        ),
        "index": {
            "classes": len(index.classes),
            "parent_edges": sum(len(parents) for parents in index.parents.values()),
            "forgetful": len(index.forgetful),
            "parse_errors": index.parse_errors,
        },
        "timing_seconds": {
            "load": round(loaded - started, 3),
            "index": round(indexed - loaded, 3),
            "total_before_hash": round(indexed - started, 3),
        },
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
