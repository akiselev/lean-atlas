#!/usr/bin/env python3
"""Score `#atlas_home_attempt` shard logs — the refuter lane's scorer.

Verdicts are three, and their asymmetry is the reverse of `score-probes.py`'s:

* `PROVED by <tac>`  — sound and final. The rewritten statement elaborated, the tactic
  closed it, the result was rejected on `sorryAx`/metavariables, and the kernel accepted
  the term. Which tactic won is kept, because it says how deep the result is: `rfl` is
  bookkeeping, `aesop` is an argument.
* `not proved by the ladder` — this ladder, within this heartbeat budget. Nothing more.
* `NO STATEMENT` — the weakening could not even be stated (source binder missing or
  ambiguous, instance re-synthesis failed, or the rewritten type is ill-formed). A refusal,
  not a failure; counted separately because it is evidence about the *lane*, not the claim.

**A shard's results exist only if its plants pass.** Every shard opens with three planted
controls (`attempt-plan.py`): `atlas_plant_easy` must be PROVED, `atlas_plant_hard` must be not
proved, `atlas_plant_no_statement` must be NO STATEMENT. A shard whose plants are wrong or
missing is discarded whole and reported — the lesson of the 55-case wrong-binder run
(`kuna-math-loop.md` §1), which produced plausible verdicts about questions nobody asked.

A shard whose log lacks a final `EXIT=0` is scored for the lines it printed (each verdict
line is complete in itself) but flagged incomplete, and the missing triples stay missing —
CLAUDE.md §2: read the gate's own exit status, never the pipe's.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

LINE = re.compile(r"atlas attempt `([^`]+)`: (\S+) -> (\S+): (.*)")
PLANTS = {
    "atlas_plant_easy": "proved",
    "atlas_plant_hard": "not_proved",
    "atlas_plant_no_statement": "no_statement",
}


def classify(tail: str) -> tuple[str, str]:
    """(verdict, detail) — detail is the winning tactic or the refusal reason."""
    if tail.startswith("PROVED by "):
        return "proved", tail[len("PROVED by "):].strip()
    if tail.startswith("not proved"):
        return "not_proved", ""
    if "NO STATEMENT" in tail:
        return "no_statement", tail.split("— NO STATEMENT")[0].strip(" —")
    return "unrecognised", tail


def parse_log(text: str) -> tuple[dict[tuple[str, str, str], tuple[str, str]], bool]:
    """Verdicts keyed by (decl, source, target), plus whether the log ended EXIT=0."""
    out: dict[tuple[str, str, str], tuple[str, str]] = {}
    for line in text.splitlines():
        m = LINE.search(line)
        if m:
            out[(m.group(1), m.group(2), m.group(3))] = classify(m.group(4))
    return out, bool(re.search(r"^EXIT=0\s*$", text, re.M))


def check_plants(verdicts: dict) -> list[str]:
    """Empty list when every plant answered as required; else what went wrong."""
    bad = []
    for name, want in PLANTS.items():
        got = [v for (d, _s, _t), (v, _x) in verdicts.items() if d == name]
        if not got:
            bad.append(f"{name}: no verdict line")
        elif got[0] != want:
            bad.append(f"{name}: {got[0]} (must be {want})")
    return bad


SELFTEST_GOOD = """
atlas attempt `atlas_plant_easy`: CommRing -> AddCommMagma: PROVED by exact?
atlas attempt `atlas_plant_hard`: CommRing -> AddCommMagma: not proved by the ladder
atlas attempt `atlas_plant_no_statement`: CommRing -> AddCommMagma: the rewritten statement is not type-correct after instance re-synthesis — NO STATEMENT
atlas attempt `Foo.bar`: Monoid -> MulOneClass: PROVED by simp
atlas attempt `Foo.baz`: Monoid -> MulOneClass: not proved by the ladder
atlas attempt `Foo.qux`: Monoid -> MulOneClass: 2 source binders match; name a binder index before asking for a verdict — NO STATEMENT
EXIT=0
"""

# Identical data lines under a lying plant: every one of them must be discarded.
SELFTEST_BAD_PLANT = SELFTEST_GOOD.replace(
    "atlas attempt `atlas_plant_hard`: CommRing -> AddCommMagma: not proved by the ladder",
    "atlas attempt `atlas_plant_hard`: CommRing -> AddCommMagma: PROVED by aesop")


def selftest() -> int:
    v, clean = parse_log(SELFTEST_GOOD)
    assert clean, "EXIT=0 not recognised"
    assert check_plants(v) == [], f"good plants rejected: {check_plants(v)}"
    assert v[("Foo.bar", "Monoid", "MulOneClass")] == ("proved", "simp")
    assert v[("Foo.baz", "Monoid", "MulOneClass")] == ("not_proved", "")
    assert v[("Foo.qux", "Monoid", "MulOneClass")][0] == "no_statement"
    v2, _ = parse_log(SELFTEST_BAD_PLANT)
    assert check_plants(v2) == ["atlas_plant_hard: proved (must be not_proved)"], \
        f"lying plant not caught: {check_plants(v2)}"
    _, dirty = parse_log(SELFTEST_GOOD.replace("EXIT=0", "EXIT=143"))
    assert not dirty, "nonzero exit read as clean"
    print("selftest: all assertions hold — the scorer can say no")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-attempt-plan.json"))
    ap.add_argument("--log-dir", type=pathlib.Path, default=pathlib.Path("/tmp"),
                    help="where shard logs live, as atlas-attempt-<shard name>.log")
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-attempt-scored.json"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    idx = json.loads(args.index.read_text())
    scored: dict[str, list] = {"proved": [], "not_proved": [], "no_statement": []}
    tactic_wins: Counter = Counter()
    invalid, incomplete, pending, missing = [], [], [], []
    unrecognised = 0

    for shard in idx["shards"]:
        log = args.log_dir / f"atlas-attempt-{shard['name']}.log"
        if not log.exists():
            pending.append(shard["name"])
            missing.extend(shard["probes"])
            continue
        text = log.read_text(errors="replace")
        # No EXIT line at all means the runner has not finished this shard (lean
        # block-buffers stdout into a pipe, so an in-flight log can even be empty).
        # Judging its plants now would report a live run as a lying one; the strict
        # plant gate applies to logs that claim to be done.
        if not re.search(r"^EXIT=\d+\s*$", text, re.M):
            pending.append(shard["name"])
            missing.extend(shard["probes"])
            continue
        verdicts, clean = parse_log(text)
        bad = check_plants(verdicts)
        if bad:
            invalid.append({"shard": shard["name"], "plants": bad})
            continue
        if not clean:
            incomplete.append(shard["name"])
        for p in shard["probes"]:
            got = verdicts.get((p["decl"], p["source"], p["target"]))
            if got is None:
                missing.append(p)
                continue
            verdict, detail = got
            if verdict == "unrecognised":
                unrecognised += 1
                continue
            row = dict(p)
            if verdict == "proved":
                row["tactic"] = detail
                tactic_wins[detail] += 1
            elif verdict == "no_statement":
                row["reason"] = detail
            scored[verdict].append(row)

    n = sum(len(v) for v in scored.values())
    print(f"shards: {len(idx['shards'])} total, {len(pending)} pending, "
          f"{len(invalid)} INVALID (plants), {len(incomplete)} incomplete")
    for inv in invalid:
        print(f"  INVALID {inv['shard']}: {'; '.join(inv['plants'])} "
              f"— every verdict in it discarded")
    print(f"\nscored attempts               : {n:,}")
    print(f"  PROVED                      : {len(scored['proved']):,}")
    print(f"  not proved by the ladder    : {len(scored['not_proved']):,}")
    print(f"  NO STATEMENT (refusals)     : {len(scored['no_statement']):,}")
    print(f"  missing / pending           : {len(missing):,}")
    if unrecognised:
        print(f"  unrecognised verdict lines  : {unrecognised:,}  <- investigate before "
              f"trusting this run")
    if tactic_wins:
        print("\nwhich tactic won (depth of the result):")
        for tac, k in tactic_wins.most_common():
            print(f"  {tac:<10} {k:,}")
    asked = len(scored["proved"]) + len(scored["not_proved"])
    if asked:
        print(f"\nPROVED rate over asked statements: "
              f"{len(scored['proved']) / asked * 100:.1f}% "
              f"({len(scored['proved']):,} of {asked:,})")

    args.out.write_text(json.dumps(
        {"counts": {k: len(v) for k, v in scored.items()},
         "tactic_wins": dict(tactic_wins), "invalid_shards": invalid,
         "incomplete_shards": incomplete, "pending_shards": pending,
         "missing": missing, "unrecognised": unrecognised, **scored}, indent=1))
    print(f"\n-> {args.out}")
    # Bad plants are a red gate even when other shards scored: something in the lane lies.
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
