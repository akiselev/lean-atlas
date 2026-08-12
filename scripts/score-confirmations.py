#!/usr/bin/env python3
"""Score the kernel's answers, per stratum.

## Two corrections without which the rate is wrong

**`#atlas_home_refute` forces its class onto every instance binder.** `div_le_one` has three,
so forcing `GroupWithZero` produces `[Semifield] -> GroupWithZero`,
`[PartialOrder] -> GroupWithZero` and `[PosMulReflectLT] -> GroupWithZero`. Only the first
was ever proposed; the other two ask whether a partial order can be replaced by a group
with zero, which nobody claimed and which is meaningless. Counting all three would report
two false refutations per multi-binder declaration and drag every rate down. So a line
counts only when its declared class is the one the detector actually named.

**REFUTED is not a disproof.** Home.lean says so directly: the elaborator baked instance
projections into the value at first check, and retyping a binder can break that chain
whether or not the proof needed the strength. So the denominator here is "candidates the
kernel gave a verdict on" and the rate is a *lower bound* on precision — the true rate is
this or better, never worse.

**The strata are not symmetric, and the report says so.** The citation detector names a
specific binder and a specific target, so its claim is pinned and scored exactly. The shape
detector says "this declaration looks weakenable toward that sibling" without naming which
binder, so it is scored as satisfied if any binder confirms. That is a weaker claim tested
more leniently, and its rate is therefore not directly comparable to the citation
detector's. Stated rather than quietly averaged.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re

BLOCK = re.compile(r"^atlas home confirm: `(.+?)`$")
LINE = re.compile(r"^\s+\[(.+?)\] -> (.+?): (CONFIRMED|REFUTED|could not rebuild)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("/tmp/atlas-confirm.out"))
    ap.add_argument("--index", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-confirm-index.json"))
    ap.add_argument("--crossing", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-crossing-lattice-shape.json"))
    ap.add_argument("--report", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-precision.json"))
    args = ap.parse_args()

    index = {e["decl"]: e for e in json.loads(args.index.read_text())}
    crossing = json.loads(args.crossing.read_text())

    # The binder class the citation detector actually named, per declaration.
    proposed: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for bucket in ("agree", "only_l"):
        for name, v in crossing.get(bucket, {}).items():
            binders = v["L"] if bucket == "agree" else v
            for b in binders:
                if b.get("verdict") == "over-hypothesis" and b.get("home"):
                    proposed[name].add((b["class"], b["home"]))

    # Parse the kernel's transcript.
    results: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    cur = None
    for raw in args.out.read_text().splitlines():
        m = BLOCK.match(raw)
        if m:
            cur = m.group(1)
            continue
        m = LINE.match(raw)
        if m and cur:
            results[cur].append((m.group(1), m.group(2), m.group(3)))

    strata: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    detail: dict[str, list] = collections.defaultdict(list)
    spurious = 0

    for decl, entry in index.items():
        stratum, forced = entry["stratum"], entry["forced"]
        lines = results.get(decl)
        if not lines:
            strata[stratum]["no-verdict"] += 1
            continue
        if stratum in ("BOTH", "L_ONLY"):
            want = proposed.get(decl, set())
            scored = [(c, t, v) for c, t, v in lines if (c, t) in want]
            spurious += len(lines) - len(scored)
            if not scored:
                strata[stratum]["no-verdict"] += 1
                continue
            verdict = "CONFIRMED" if any(v == "CONFIRMED" for _c, _t, v in scored) \
                else scored[0][2]
        else:
            scored = [(c, t, v) for c, t, v in lines if t == forced]
            verdict = "CONFIRMED" if any(v == "CONFIRMED" for _c, _t, v in scored) \
                else (scored[0][2] if scored else "no-verdict")
        strata[stratum][verdict] += 1
        detail[stratum].append((decl, forced, verdict))

    print(f"spurious lines ignored (forced class applied to an unproposed binder): "
          f"{spurious:,}\n")
    print(f"{'stratum':10s} {'confirmed':>10s} {'refuted':>9s} {'no verdict':>11s} "
          f"{'precision (lower bound)':>26s}")
    report = {}
    for s in ("BOTH", "L_ONLY", "S_ONLY"):
        cnt = strata.get(s)
        if not cnt:
            continue
        conf, ref = cnt["CONFIRMED"], cnt["REFUTED"]
        nov = cnt["no-verdict"] + cnt["could not rebuild"]
        dec = conf + ref
        rate = conf / dec if dec else float("nan")
        print(f"{s:10s} {conf:10d} {ref:9d} {nov:11d} {100 * rate:24.1f}%")
        report[s] = {"confirmed": conf, "refuted": ref, "no_verdict": nov,
                     "precision_lower_bound": rate}

    print("\nconfirmed weakenings (these are theorems that now exist):")
    for s in ("BOTH", "L_ONLY", "S_ONLY"):
        got = [d for d in detail[s] if d[2] == "CONFIRMED"]
        print(f"\n  {s}: {len(got)}")
        for decl, forced, _v in got[:20]:
            print(f"    {decl[:52]:52s} → {forced}")

    report["detail"] = {s: detail[s] for s in detail}
    args.report.write_text(json.dumps(report, indent=1))
    print(f"\n→ {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
