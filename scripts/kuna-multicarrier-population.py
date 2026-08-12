#!/usr/bin/env python3
"""Freeze a source-only population for carrier-attached historical replay.

Selection deliberately stops before loading an Atlas row or constructing `HomeIndex`.
It uses E0's structurally retained events, Git chronology, and the parent/child source
telescope only. The resulting manifest can therefore be frozen before either the old row
detector or the new carrier-attached search lane sees a selected historical parent.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_E0 = ROOT / "research/data/kuna-e0-events.json"
DEFAULT_REPO = ROOT / "lean/.lake/packages/mathlib"
REPLAY_MANIFESTS = (
    ROOT / "research/data/kuna-e1-manifest.json",
    ROOT / "research/data/kuna-e1-replay2-manifest.json",
    ROOT / "research/data/kuna-e1-replay3-manifest.json",
    ROOT / "research/data/kuna-e1-replay4-manifest.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_kuna_truth():
    path = ROOT / "scripts/kuna-truth.py"
    spec = importlib.util.spec_from_file_location("atlas_kuna_truth", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True)


def replayed_children() -> set[str]:
    out: set[str] = set()
    for path in REPLAY_MANIFESTS:
        data = json.loads(path.read_text())
        for development in data.get("development", ()):
            child = development.get("child")
            if child:
                out.add(child)
    return out


def tagged_binders(decl: dict) -> collections.Counter:
    return collections.Counter(
        (stratum, head, " ".join(args.split()))
        for stratum in ("own", "inherited")
        for head, args in decl[stratum]
    )


def binder_rows(decl: dict) -> list[dict]:
    return [
        {"stratum": stratum, "class": head, "args": " ".join(args.split())}
        for stratum in ("own", "inherited")
        for head, args in decl[stratum]
    ]


def delta_rows(counter: collections.Counter) -> list[dict]:
    return [
        {"stratum": stratum, "class": head, "args": args}
        for (stratum, head, args), count in sorted(counter.items())
        for _ in range(count)
    ]


def module_of(path: str) -> str:
    return path.removesuffix(".lean").replace("/", ".")


def select(e0_path: Path, repo: Path, count: int) -> dict:
    kuna = load_kuna_truth()
    e0 = json.loads(e0_path.read_text())
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for move in e0["moves"]:
        groups[move["commit"]].append(move)

    excluded = replayed_children()
    blobs = kuna.Blobs(str(repo))
    accepted: list[dict] = []
    rejected: list[dict] = []

    for commit, moves in groups.items():
        if len(moves) != 1:
            continue
        event = moves[0]
        if event["stratum"] != "own" or event["kind"] not in ("theorem", "lemma"):
            continue
        meta = git(repo, "show", "-s", "--format=%P%x09%ct%x09%cI%x09%s", commit)
        parents, timestamp, date, subject = meta.rstrip().split("\t", 3)
        parent = parents.split()[0]
        base = {
            "child": commit,
            "parent": parent,
            "timestamp": int(timestamp),
            "date": date,
            "subject": subject,
            "module": module_of(event["parent_file"]),
            "parent_file": event["parent_file"],
            "child_file": event["file"],
            "declaration": event["decl"],
            "event": {
                "source": event["from"],
                "target": event["to"],
                "args": event["args"],
                "stratum": event["stratum"],
            },
        }
        if commit in excluded:
            rejected.append({**base, "rejected": "already used by E1 replay 1-4"})
            continue

        parent_source = blobs.get(parent, event["parent_file"])
        child_source = blobs.get(commit, event["file"])
        if parent_source is None or child_source is None:
            rejected.append({**base, "rejected": "parent or child source blob missing"})
            continue
        parent_decl = kuna.parse_file(parent_source).get(event["decl"])
        child_decl = kuna.parse_file(child_source).get(event["decl"])
        if parent_decl is None or child_decl is None:
            rejected.append({**base, "rejected": "declaration missing or ambiguous in source parser"})
            continue

        before = tagged_binders(parent_decl)
        after = tagged_binders(child_decl)
        removed = before - after
        added = after - before
        expected_removed = collections.Counter({
            ("own", event["from"], " ".join(event["args"].split())): 1
        })
        expected_added = collections.Counter({
            ("own", event["to"], " ".join(event["args"].split())): 1
        })
        if removed != expected_removed or added != expected_added:
            rejected.append({
                **base,
                "rejected": "whole parsed telescope changes more than the retained E0 event",
                "removed": delta_rows(removed),
                "added": delta_rows(added),
            })
            continue

        parent_binders = binder_rows(parent_decl)
        arg_groups = sorted({row["args"] for row in parent_binders if row["args"]})
        if len(arg_groups) < 2:
            rejected.append({
                **base,
                "rejected": "parent source has fewer than two distinct instance argument groups",
                "parent_argument_groups": arg_groups,
            })
            continue
        toolchain = blobs.get(parent, "lean-toolchain")
        accepted.append({
            **base,
            "parent_toolchain": toolchain.strip() if toolchain else None,
            "parent_binders": parent_binders,
            "parent_argument_groups": arg_groups,
            "source_telescope_delta": "exactly the retained E0 binder-head replacement",
        })

    accepted.sort(key=lambda row: (-row["timestamp"], row["child"], row["declaration"]))
    rejected.sort(key=lambda row: (-row["timestamp"], row["child"], row["declaration"]))
    population = accepted[:count]
    cutoff = population[-1]["timestamp"] if population else None
    screened = [row for row in rejected if cutoff is None or row["timestamp"] >= cutoff]
    for row in population:
        row.pop("timestamp", None)
    for row in screened:
        row.pop("timestamp", None)

    return {
        "schema": "atlas-kuna-e1-mc0-manifest-v1",
        "frozen_at": "2026-08-05",
        "source": {
            "e0_artifact": str(e0_path.relative_to(ROOT)),
            "e0_sha256": sha256(e0_path),
            "selector": "scripts/kuna-multicarrier-population.py",
            "selector_sha256": sha256(Path(__file__)),
            "extractor": "atlas-extract/Atlas/Extract.lean",
            "extractor_sha256": sha256(ROOT / "atlas-extract/Atlas/Extract.lean"),
            "search_method": "HomeIndex.carrier_statement_candidates",
            "detector": "scripts/atlas_home.py",
            "detector_sha256": sha256(ROOT / "scripts/atlas_home.py"),
        },
        "selection": {
            "unit": "one structurally retained own theorem-or-lemma E0 event",
            "rule": "newest commits first; exactly one retained E0 move in the commit; own theorem or lemma; whole parsed source telescope changes only by that binder-head replacement; parent has at least two distinct instance-binder argument groups; exclude E1 replay 1-4",
            "population_size": count,
            "ordering": "Git committer timestamp descending, then child hash and declaration",
            "detector_outputs_seen_before_freeze": False,
            "source_screening_seen_before_freeze": True,
            "not_blind": True,
            "screened_rejections_at_or_after_cutoff": screened,
        },
        "development": population,
        "outcomes": {
            "exact_proposal": "the carrier-attached method includes the expert target for the event binder",
            "wrong_target": "the method judges the event binder but excludes the expert target",
            "refused": "the method refuses before candidate generation",
            "no_attached_requirement": "the row has no retained statement requirement at the event carrier",
            "statement_failure": "the expert target cannot be re-elaborated as a standalone parent statement",
            "proof_success": "a proof of the exact expert target is kernel-accepted in the parent",
            "proof_search_failure": "the exact statement elaborates but the frozen tactic ladder finds no proof",
            "environment_failure": "the historical parent cannot be reconstructed or imported",
        },
        "claim_boundary": "a bounded source-selected replay population, not detector recall and not a sample of every historical opportunity",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--e0", type=Path, default=DEFAULT_E0)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")
    print(json.dumps(select(args.e0.resolve(), args.repo.resolve(), args.count),
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
