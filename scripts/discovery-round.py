#!/usr/bin/env python3
"""One refuter-lane round, no human between the arrows — the L2 orchestrator.

`research/discovery-loop.md` §2 lists the arrows a human stood between: emit -> compile,
sweep -> plan (a filename), REFUTED -> attempt, scored -> next allocation. This chains the
attempt lane's stages out of one round directory:

    plan   attempt-plan.py          -> shards + index
    run    atlas_batch, N workers      -> per-shard logs, one Mathlib import per worker
    score  score-attempts.py        -> scored ledger, plant audit
    screen novelty-rescreen.py      -> novel / prior-art split over the PROVED set

Each stage's own exit status is read and recorded (CLAUDE.md §2 — a red gate read through
a pipe went green once already), the manifest carries what was run with what inputs, and
a failed stage stops the round rather than feeding the next stage a partial artifact.

What this does not do, on purpose: no `lake build` while workers run (the shared
`atlas-extract` build directory makes concurrent builds a race, CLAUDE.md §5) — binaries
are built once, serialized, before any worker starts; and the screen stage is optional
per-invocation because it needs the 470k closure resident (~15 GB), which does not fit
next to three Mathlib workers.

Resumable by stage: `--from score` reuses the round directory's existing shards and logs.
The acceptance test is a replay — `--from score` over round 1's frozen logs must
reproduce §68's totals (155 / 1,002 / 626; then 142 / 13) — which exercises everything
except the kernel, whose verdicts are already on disk.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
LEAN = REPO / "lean"
STAGES = ["plan", "run", "score", "screen"]


def sh(manifest: dict, stage: str, cmd: list[str], cwd: pathlib.Path = REPO,
       log: pathlib.Path | None = None) -> None:
    """Run one child, record its exact command and exit status, stop the round on red."""
    t0 = time.time()
    print(f"[{stage}] {' '.join(map(str, cmd))}", flush=True)
    if log:
        with open(log, "w") as fh:
            r = subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=fh,
                               stderr=subprocess.STDOUT)
    else:
        r = subprocess.run([str(c) for c in cmd], cwd=cwd)
    manifest.setdefault("stages", {}).setdefault(stage, []).append(
        {"cmd": [str(c) for c in cmd], "exit": r.returncode,
         "seconds": round(time.time() - t0, 1)})
    if r.returncode != 0:
        manifest["failed"] = stage
        raise SystemExit(f"[{stage}] exit {r.returncode} — round stopped, nothing "
                         f"downstream ran on a partial artifact")


def interleave(names: list[str], workers: int) -> list[list[str]]:
    return [names[i::workers] for i in range(workers)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round_dir", type=pathlib.Path,
                    help="the round's ledger directory; created if absent")
    ap.add_argument("--from", dest="from_stage", choices=STAGES, default="plan")
    ap.add_argument("--until", choices=STAGES, default="screen")
    # plan inputs, passed through to attempt-plan.py
    ap.add_argument("--from-attempts", type=pathlib.Path)
    ap.add_argument("--key", default="not_proved")
    ap.add_argument("--scored", type=pathlib.Path, nargs="*")
    ap.add_argument("--triples", type=pathlib.Path)
    ap.add_argument("--exclude", type=pathlib.Path, nargs="*")
    ap.add_argument("--ladder", default="rfl, simp, aesop, exact?")
    ap.add_argument("--plant-ladder", default=None)
    ap.add_argument("--heartbeats", type=int, default=1000000)
    ap.add_argument("--shard-size", type=int, default=80)
    ap.add_argument("--prefix", default="Round")
    # run inputs
    ap.add_argument("--workers", type=int, default=3,
                    help="atlas_batch processes; each holds Mathlib resident (~9 GB)")
    ap.add_argument("--imports", nargs="+",
                    default=["Mathlib", "Atlas.Home"])
    # screen inputs
    ap.add_argument("--closure", type=pathlib.Path,
                    default=pathlib.Path("/tmp/mathlib-closure.jsonl"))
    args = ap.parse_args()

    rd = args.round_dir
    (rd / "logs").mkdir(parents=True, exist_ok=True)
    manifest_path = rd / "round.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    index = rd / "plan-index.json"
    scored = rd / "scored.json"
    novelty = rd / "novelty.json"
    run_stage = lambda s: STAGES.index(args.from_stage) <= STAGES.index(s) \
        <= STAGES.index(args.until)  # noqa: E731

    try:
        if run_stage("plan"):
            cmd = [sys.executable, REPO / "scripts" / "attempt-plan.py",
                   "--batch", "--prefix", args.prefix, "--index", index,
                   "--out-dir", LEAN / "Scratch",
                   "--ladder", args.ladder, "--heartbeats", str(args.heartbeats),
                   "--shard-size", str(args.shard_size)]
            if args.plant_ladder:
                cmd += ["--plant-ladder", args.plant_ladder]
            if args.triples:
                cmd += ["--triples", args.triples]
            elif args.from_attempts:
                cmd += ["--from-attempts", args.from_attempts, "--key", args.key]
            elif args.scored:
                cmd += ["--scored", *args.scored]
            if args.exclude:
                cmd += ["--exclude", *args.exclude]
            sh(manifest, "plan", cmd)

        if run_stage("run"):
            # One serialized build before any worker: `lake env` does not rebuild, so a
            # stale binary would silently run old code (the pre-fix olean did exactly
            # that once); and two concurrent lake *builds* are the CLAUDE.md §5 race.
            sh(manifest, "run", ["lake", "build", "atlas_batch",
                                 "Atlas.Home"], cwd=LEAN,
               log=rd / "logs" / "build.log")
            shard_names = [s["name"] for s in
                           json.loads(index.read_text())["shards"]]
            procs = []
            for w, names in enumerate(interleave(shard_names, args.workers)):
                if not names:
                    continue
                cmd = ["lake", "env", str(LEAN / ".lake" / "build" / "bin" / "atlas_batch")]
                for m in args.imports:
                    cmd += ["--import", m]
                cmd += ["--out-dir", str(rd / "logs"), "--log-prefix", "atlas-attempt-"]
                cmd += [str(LEAN / "Scratch" / f"{n}.lean") for n in names]
                lp = open(rd / "logs" / f"worker{w}.log", "w")
                print(f"[run] worker {w}: {len(names)} shard(s): {' '.join(names)}",
                      flush=True)
                procs.append((w, subprocess.Popen([str(c) for c in cmd], cwd=LEAN,
                                                  stdout=lp, stderr=subprocess.STDOUT)))
            t0 = time.time()
            failed = [w for w, p in procs if p.wait() != 0]
            manifest.setdefault("stages", {})["run-workers"] = [
                {"worker": w, "exit": p.returncode} for w, p in procs]
            manifest["run_seconds"] = round(time.time() - t0, 1)
            if failed:
                manifest["failed"] = "run"
                raise SystemExit(f"[run] worker(s) {failed} exited nonzero")

        if run_stage("score"):
            sh(manifest, "score", [sys.executable,
                                   REPO / "scripts" / "score-attempts.py",
                                   "--index", index, "--log-dir", rd / "logs",
                                   "--out", scored])

        if run_stage("screen"):
            proved = json.loads(scored.read_text())["proved"]
            triples = rd / "proved-triples.json"
            triples.write_text(json.dumps(
                {"confirmed": [[r["decl"], r["source"], r["target"]] for r in proved]}))
            if not proved:
                print("[screen] zero PROVED — nothing to screen")
            else:
                sh(manifest, "screen", ["uv", "run", "scripts/novelty-rescreen.py",
                                        "--slice", args.closure,
                                        "--confirmed", triples, "--out", novelty])
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=1))
        print(f"manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
