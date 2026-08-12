#!/usr/bin/env python3
"""Generate historical Lean shards for the frozen MC2 proposal sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib


CONTROLS = """
set_option maxHeartbeats 1000000
set_option linter.unusedTactic false
set_option linter.unreachableTactic false

theorem atlas_mc2_plant_easy {R : Type} [CommRing R] (a b : R) : a + b = b + a := add_comm a b
theorem atlas_mc2_plant_hard {R : Type} [CommRing R] (a b c : R)
    (h : a + b = a + c) : b = c := add_left_cancel h
theorem atlas_mc2_plant_no_statement {R : Type} [CommRing R] (a b : R) : a * b = b * a :=
  mul_comm a b

#atlas_mc2_attempt atlas_mc2_plant_easy CommRing @ 0 => AddCommMagma by rfl, simp, aesop, exact?
#atlas_mc2_attempt atlas_mc2_plant_hard CommRing @ 0 => AddCommMagma by rfl, simp, aesop, exact?
#atlas_mc2_attempt atlas_mc2_plant_no_statement CommRing @ 0 => AddCommMagma by rfl, simp, aesop, exact?
"""


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=pathlib.Path,
                        default=pathlib.Path("research/data/kuna-e1-mc2-manifest.json"))
    parser.add_argument("--support", type=pathlib.Path,
                        default=pathlib.Path("research/probes/kuna-mc2-support.lean"))
    parser.add_argument("--out-dir", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-probes"))
    parser.add_argument("--index", type=pathlib.Path,
                        default=pathlib.Path("/tmp/atlas-kuna-mc2-probe-index.json"))
    parser.add_argument("--shard-size", type=int, default=12)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    if manifest.get("status") != "frozen-before-historical-statement-or-proof-probing":
        raise SystemExit("refusing an MC2 manifest that is not frozen before probing")
    proposals = manifest["selection"]["proposals"]
    if len(proposals) != manifest["selection"]["sample_proposals"] or len(proposals) != 48:
        raise SystemExit("MC2 sample count drift")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    support = args.support.read_text().rstrip() + "\n"
    shards = []
    for start in range(0, len(proposals), args.shard_size):
        selected = proposals[start:start + args.shard_size]
        shard_number = len(shards) + 1
        name = f"MC2Probe{shard_number:02d}"
        path = args.out_dir / f"{name}.lean"
        lines = [support, CONTROLS.rstrip(), ""]
        for proposal in selected:
            lines.append(f"-- {proposal['proposal_id']}")
            lines.append(
                "#atlas_mc2_attempt "
                f"{proposal['declaration']} {proposal['source']} @ "
                f"{proposal['raw_instance_binder_index']} => {proposal['target']} "
                "by rfl, simp, aesop, exact?"
            )
        path.write_text("\n".join(lines) + "\n")
        shards.append({
            "name": name,
            "file": str(path),
            "file_sha256": sha256_file(path),
            "proposals": selected,
        })

    index = {
        "schema": "atlas-kuna-e1-mc2-probe-index-v1",
        "manifest": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "support": str(args.support),
        "support_sha256": sha256_file(args.support),
        "historical_worktree": "/tmp/atlas-kuna-mc2-p2-71f079f9",
        "toolchain": "leanprover/lean4:v4.12.0-rc1",
        "ladder": ["rfl", "simp", "aesop", "exact?"],
        "max_heartbeats_per_command": 1_000_000,
        "total": len(proposals),
        "shard_size": args.shard_size,
        "shards": shards,
    }
    args.index.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(f"generated {len(shards)} shards / {len(proposals)} proposals -> {args.out_dir}")
    print(f"index -> {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
