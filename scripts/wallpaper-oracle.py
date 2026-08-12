#!/usr/bin/env python3
"""The wallpaper census's differential oracle — the frozen reference table (W0).

The census will be proven in Lean; this file holds what it is diffed against: the
seventeen plane groups as standard crystallography records them (International Tables
for Crystallography, Vol. A, plane groups 1-17 — 130-year-old settled reference data,
here as data, not as truth: the whole point of the census is that the kernel, not this
table, becomes the authority, and a disagreement with this table is a finding in either
direction). The CARAT/GAP computational enumeration is the richer oracle for W3+ and
needs those tools installed; this table is the part every milestone can diff against
today.

Selftest invariants (run `--selftest`): seventeen rows; exactly 4 non-symmorphic
(pg, pmg, pgg, p4g); exactly 5 chiral / orientation-preserving-only (p1 p2 p3 p4 p6);
point-group orders drawn from {1,2,3,4,6,8,12}; and — the honest one — the coarse
invariant tuple (point-group order, chiral, symmorphic, lattice) does NOT separate all
pairs: p3m1 and p31m collide on every column of this table. That collision is pinned
deliberately: it proves the W5 separation battery needs finer invariants than this
table carries, and a Lean census that "separated" the seventeen using only these
columns would be wrong by construction.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys

# (IT number, name, point-group order, chiral, symmorphic, lattice class)
TABLE = [
    (1,  "p1",   1,  True,  True,  "oblique"),
    (2,  "p2",   2,  True,  True,  "oblique"),
    (3,  "pm",   2,  False, True,  "rectangular"),
    (4,  "pg",   2,  False, False, "rectangular"),
    (5,  "cm",   2,  False, True,  "centered-rectangular"),
    (6,  "pmm",  4,  False, True,  "rectangular"),
    (7,  "pmg",  4,  False, False, "rectangular"),
    (8,  "pgg",  4,  False, False, "rectangular"),
    (9,  "cmm",  4,  False, True,  "centered-rectangular"),
    (10, "p4",   4,  True,  True,  "square"),
    (11, "p4m",  8,  False, True,  "square"),
    (12, "p4g",  8,  False, False, "square"),
    (13, "p3",   3,  True,  True,  "hexagonal"),
    (14, "p3m1", 6,  False, True,  "hexagonal"),
    (15, "p31m", 6,  False, True,  "hexagonal"),
    (16, "p6",   6,  True,  True,  "hexagonal"),
    (17, "p6m",  12, False, True,  "hexagonal"),
]


def selftest() -> int:
    assert len(TABLE) == 17, len(TABLE)
    assert [r[0] for r in TABLE] == list(range(1, 18))
    non_symmorphic = [r[1] for r in TABLE if not r[4]]
    assert non_symmorphic == ["pg", "pmg", "pgg", "p4g"], non_symmorphic
    chiral = [r[1] for r in TABLE if r[3]]
    assert chiral == ["p1", "p2", "p4", "p3", "p6"], chiral
    assert all(r[2] in {1, 2, 3, 4, 6, 8, 12} for r in TABLE)
    # The pinned collision: coarse invariants must NOT separate p3m1 from p31m.
    coarse = collections.Counter((r[2], r[3], r[4], r[5]) for r in TABLE)
    collisions = {k: v for k, v in coarse.items() if v > 1}
    assert (6, False, True, "hexagonal") in collisions, collisions
    print("selftest: 17 rows, 4 non-symmorphic, 5 chiral, and the p3m1/p31m coarse "
          "collision is present — the W5 battery must be finer than this table")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true", help="emit the table as JSON")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.json:
        print(json.dumps([
            {"it": r[0], "name": r[1], "point_group_order": r[2], "chiral": r[3],
             "symmorphic": r[4], "lattice": r[5]} for r in TABLE], indent=1))
        return 0
    for r in TABLE:
        print(f"{r[0]:2}  {r[1]:5} |P|={r[2]:2}  chiral={str(r[3]):5} "
              f"symmorphic={str(r[4]):5}  {r[5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
