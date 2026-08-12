#!/usr/bin/env python3
"""Merge per-group corpus extractions with a Mathlib background into one Atlas slice.

## Why this script exists at all

Lean's `importModules` refuses to merge two modules that define the same root-level name,
and the corpus groups do collide — `g01_peano.add_comm` against Mathlib's `add_comm`,
`sp` in both `g07` and `g10`. So the twelve groups cannot be extracted in one pass; each
is extracted separately and merged here.

That is a logistics fact. The *architectural* fact it exposes is the reason this script
does more than concatenate: **a declaration's identity in the Atlas is its name string.**
`graph.rs` keys its edge maps `HashMap<String, Vec<String>>`, and the skeleton arena
interns a constant as `HashMap<Box<str>, SymId>`. Inside one Lean environment that is
sound, because Lean enforces uniqueness. Across merged slices it is not, and it fails
*silently*: two different declarations sharing a name become one node, their edge sets
union, and a `sorry` under one propagates to the other through `honesty`. Nothing errors.

CLAUDE.md §7 already licenses merging slices ("slices from different workspaces
concatenate"), which is exactly the operation that breaks the assumption.

## What this script does about it

It gives every corpus declaration a qualified name, `<group>.<name>`, and rewrites the
three places a name carries identity:

1. the `name` field,
2. `uses_statement` / `uses_proof`, for references to the group's own declarations,
3. **the I3 statement encoding**, whose `c(...)` nodes carry constant names — the one that
   is easy to miss, because a slice merged without it looks fine and quietly interns two
   different constants to one `SymId`.

References *out* of the group are left alone: a corpus theorem citing `Nat.add` means
Mathlib's `Nat.add`, and that is precisely the identification worth keeping.

Usage:
    uv run scripts/corpus-slice.py --slices /tmp/atlas-slices --out /tmp/atlas-merged.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import atlas_encoding  # noqa: E402

CORPUS_MODULE = re.compile(r"^Tests\.corpus\.(g\d\d_\w+)$")

# Names Lean synthesizes for a declaration. They stay in the slice — they are real
# constants and real edge targets — but they are excluded from any *coverage* claim,
# because "the Atlas found neighbours for 400 declarations" means nothing when 350 of them
# are `add.eq_1`.
DERIVED_EXACT_SUFFIX = (
    ".eq_def", ".below", ".ibelow", ".brecOn", ".binductionOn", ".rec", ".recOn",
    ".casesOn", ".noConfusion", ".noConfusionType", ".toCtorIdx", ".ctorIdx",
    ".sizeOf_spec", ".injEq", ".inj", ".induct", ".fun_cases", ".elim", ".ctorElim",
    ".ctorElimType", ".mk", ".ofNat", ".brecOn.eq", ".brecOn.go",
)
DERIVED_SUBSTRING = ("._", ".match_", ".proof_", ".eq_", "_example", ".«")


def is_authored(name: str) -> bool:
    """Did a corpus author write this name, or did Lean synthesize it?

    Biased toward calling a name authored: a false "authored" shows up as an unanswered
    probe in the benchmark, which is visible, while a false "derived" silently shrinks the
    denominator of every coverage claim.
    """
    if name.startswith("_"):
        return False
    if name.endswith(DERIVED_EXACT_SUFFIX):
        return False
    if any(s in name for s in DERIVED_SUBSTRING):
        return False
    return True


def load(path: pathlib.Path) -> list[dict]:
    rows = []
    with path.open() as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slices", type=pathlib.Path, required=True,
                    help="directory of per-group .jsonl extractions plus background.jsonl")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--manifest", type=pathlib.Path, default=None)
    args = ap.parse_args()

    files = sorted(args.slices.glob("*.jsonl"))
    if not files:
        sys.exit(f"no .jsonl under {args.slices}")

    # ---- pass 1: read everything, split corpus rows from background rows -------------
    background: dict[str, dict] = {}
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for f in files:
        for row in load(f):
            g = CORPUS_MODULE.match(row.get("module", ""))
            if g:
                groups[g.group(1)].append(row)
            else:
                # A declaration can appear in several extractions (every group's closure
                # holds Mathlib). Identical by construction, so first wins.
                background.setdefault(row["name"], row)

    if not groups:
        sys.exit("no corpus rows found — check that the extractions name Tests.corpus.*")

    # ---- pass 2: qualify every corpus name, and measure what that was hiding ---------
    exposure = {}
    merged: list[dict] = list(background.values())
    census: dict[str, dict] = {}

    group_names = {g: {r["name"] for r in rows} for g, rows in groups.items()}

    for g, rows in sorted(groups.items()):
        own = group_names[g]
        mapping = {n: f"{g}.{n}" for n in own}

        clash_background = sorted(own & background.keys())
        clash_groups = {
            other: sorted(own & group_names[other])
            for other in groups if other != g and (own & group_names[other])
        }

        enc_rewrites = 0
        authored: list[str] = []
        derived = 0
        for row in rows:
            if is_authored(row["name"]):
                authored.append(mapping[row["name"]])
            else:
                derived += 1
            row["module"] = g
            row["name"] = mapping[row["name"]]
            for field in ("uses_statement", "uses_proof"):
                row[field] = [mapping.get(u, u) for u in row.get(field, [])]
            if row.get("stmt"):
                row["stmt"], hits = atlas_encoding.rename(row["stmt"], mapping)
                enc_rewrites += hits
            merged.append(row)

        # How many *distinct* colliding names actually occur inside some statement — the
        # occurrences that a name-keyed merge would have interned to one symbol.
        conflatable = set()
        for row in rows:
            if row.get("stmt"):
                for c in atlas_encoding.constants(row["stmt"]):
                    bare = c[len(g) + 1:] if c.startswith(g + ".") else c
                    if bare in clash_background or any(
                            bare in v for v in clash_groups.values()):
                        conflatable.add(bare)

        exposure[g] = {
            "declared": len(own),
            "clash_with_background": clash_background,
            "clash_with_groups": clash_groups,
            "encoding_names_rewritten": enc_rewrites,
            "would_have_conflated": sorted(conflatable),
        }
        census[g] = {"authored": sorted(authored), "derived_count": derived}

    with args.out.open("w") as out:
        for row in merged:
            out.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")

    manifest_path = args.manifest or args.out.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(census, indent=2) + "\n")
    (args.out.parent / "atlas-merge-exposure.json").write_text(json.dumps(exposure, indent=2))

    print(f"background declarations : {len(background):,}")
    print(f"corpus groups           : {len(groups)}")
    print(f"merged rows             : {len(merged):,}  → {args.out}")
    print(f"manifest                : {manifest_path}")
    print()
    print(f"{'group':24s} {'decls':>6s} {'authored':>9s} {'clash/bg':>9s} "
          f"{'clash/grp':>10s} {'enc rewr':>9s} {'conflatable':>12s}")
    for g, e in sorted(exposure.items()):
        print(f"{g:24s} {e['declared']:6d} {len(census[g]['authored']):9d} "
              f"{len(e['clash_with_background']):9d} "
              f"{sum(len(v) for v in e['clash_with_groups'].values()):10d} "
              f"{e['encoding_names_rewritten']:9d} "
              f"{len(e['would_have_conflated']):12d}")
    print()
    for g, e in sorted(exposure.items()):
        if e["clash_with_background"]:
            print(f"{g} collides with the background on: "
                  f"{', '.join(e['clash_with_background'][:12])}")
        for other, names in e["clash_with_groups"].items():
            print(f"{g} collides with {other} on: {', '.join(names[:12])}")
        if e["would_have_conflated"]:
            print(f"  {g}: {len(e['would_have_conflated'])} of those occur inside a "
                  f"statement encoding and would have interned to one symbol: "
                  f"{', '.join(e['would_have_conflated'][:8])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
