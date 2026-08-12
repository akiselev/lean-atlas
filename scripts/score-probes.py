#!/usr/bin/env python3
"""Score `#atlas_home_refute` output, keeping the three verdicts apart.

`#atlas_home_refute <decl> <class>` forces its class onto **every** instance binder of the
declaration, so a declaration with four binders emits four lines and only one of them is the
weakening that was actually proposed. Scoring the file as a whole counts the other three as
evidence about a claim nobody made; this matches each line back to the proposed
`(declared -> target)` pair from the candidate index and ignores the rest.

The three verdicts are not two:

* `CONFIRMED` — the term typechecks against the weaker hypothesis. Sound and final.
* `REFUTED` — it does not, *and* every instance argument was re-synthesised in the weakened
  context first. Evidence, though still not proof: the proof term at hand fails, which does
  not mean no proof exists.
* `INCONCLUSIVE` — re-elaboration itself failed, so the kernel saw the original term with
  its instance projections baked in. Says nothing either way.

Until this session the third was reported as the second, which put a claim of work that did
not happen on precisely the verdict that was already weakest. Precision computed over
`CONFIRMED + REFUTED` is the number that means something; over all three it is diluted by
lines that were never a test.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

LINE = re.compile(
    r"\[([^\]]+)\]\s*->\s*(\S+):\s*"
    r"(CONFIRMED|REFUTED|INCONCLUSIVE|could not rebuild the binder)")
HEADER = re.compile(r"atlas home confirm: `([^`]+)`")


def parse(text: str) -> dict[tuple[str, str, str], str]:
    """`(decl, declared, target) -> verdict` for every line the run emitted."""
    out: dict[tuple[str, str, str], str] = {}
    decl = None
    for line in text.splitlines():
        m = HEADER.search(line)
        if m:
            decl = m.group(1)
            continue
        m = LINE.search(line)
        if m and decl:
            v = m.group(3)
            # §38's refusal, normalised to a verdict name. It is a *fourth* outcome, not a
            # rejection: the weakening changes the class's arity, so the binder cannot be
            # rebuilt and no term was ever put in front of the kernel.
            out[(decl, m.group(1), m.group(2))] = (
                "UNASKABLE" if v.startswith("could not rebuild") else v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=pathlib.Path, required=True)
    ap.add_argument("--index", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-gen-index.json"))
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-gen-scored-v2.json"))
    args = ap.parse_args()

    verdicts = parse(args.log.read_text(errors="replace"))
    idx = json.loads(args.index.read_text())
    proposed = [(p["decl"], p["declared"], p["target"]) for p in idx["probes"]]
    print(f"{len(verdicts):,} verdict lines in the log; {len(proposed):,} proposed pairs")

    got = collections.Counter()
    scored: dict[str, list] = {"confirmed": [], "refuted": [], "inconclusive": [],
                               "unaskable": []}
    missing = []
    for decl, declared, target in proposed:
        v = verdicts.get((decl, declared, target))
        if v is None:
            missing.append((decl, declared, target))
            continue
        got[v] += 1
        scored[v.lower()].append([decl, declared, target])

    total_scored = sum(got.values())
    decisive = got["CONFIRMED"] + got["REFUTED"]
    print(f"\nproposed pairs with a line    : {total_scored:,}")
    print(f"  CONFIRMED                   : {got['CONFIRMED']:,}")
    print(f"  REFUTED (re-elaborated)     : {got['REFUTED']:,}")
    print(f"  INCONCLUSIVE (re-elab fail) : {got['INCONCLUSIVE']:,}")
    print(f"  UNASKABLE (arity mismatch)  : {got['UNASKABLE']:,}")
    print(f"  no line emitted             : {len(missing):,}")
    if total_scored:
        print(f"\nprecision over all verdicts   : "
              f"{got['CONFIRMED'] / total_scored * 100:.1f}%  (the diluted number)")
    if decisive:
        print(f"precision over decisive ones  : "
              f"{got['CONFIRMED'] / decisive * 100:.1f}%  "
              f"({got['CONFIRMED']:,} of {decisive:,})")
    if got["INCONCLUSIVE"] == 0:
        print("\nNOTE: the INCONCLUSIVE branch never fired. Either re-elaboration always "
              "succeeds on this sample — in which case the old two-verdict reading was "
              "right and the split costs nothing — or the branch is unreachable and this "
              "run is not evidence that it works.")

    # Lines the run emitted for binders nobody proposed. Not evidence, but their count is
    # what makes the difference between the raw file and the scored set legible.
    spurious = len(verdicts) - total_scored
    print(f"\nlines for binders that were never proposed: {spurious:,} "
          f"(discarded; `refute` forces its class onto every instance binder)")

    args.out.write_text(json.dumps(
        {"counts": dict(got), "precision_decisive":
            got["CONFIRMED"] / decisive if decisive else None,
         "spurious_lines": spurious, "missing": missing, **scored}, indent=1))
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
