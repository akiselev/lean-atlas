#!/usr/bin/env python3
"""Attach Lean source statements to the grading queue.

For each queue row, grep the physlib package for `theorem|lemma|def <last-component>`
inside the file whose module matches, and quote the declaration header (signature up to
`:=`/`by`, or a few lines). Auto-generated names (mk.inj, sizeOf_spec, ...) have no
source; those keep only the I3 statement and are marked generated.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess

SCRATCH = pathlib.Path(os.environ.get("HUNT_DIR", "."))  # work dir for hunt-*.json
PKG = pathlib.Path("/home/dev/research/lean-atlas/physics/.lake/packages/physlib")

GENERATED = re.compile(
    r"\.(mk\.(inj|injEq|sizeOf_spec)|noConfusion(Type)?|rec(On)?|casesOn|brecOn|below|"
    r"ibelow|ndrec|binductionOn|mk|sizeOf_spec|injEq|inj|eq_[0-9]+|match_[0-9]+|"
    r"proof_[0-9]+|eq_def|induct|sizeOf_eq)$"
)


def module_file(module: str) -> pathlib.Path | None:
    # The corpus stripped the Physlib./QuantumInfo. root; try both.
    rel = module.replace(".", "/") + ".lean"
    for root in ("Physlib", "QuantumInfo", ""):
        p = PKG / root / rel if root else PKG / rel
        if p.exists():
            return p
    return None


def find_stmt(name: str, module: str | None) -> dict:
    short = name.split(".")[-1]
    if GENERATED.search("." + name):
        return {"generated": True}
    # POSIX ERE — grep -E has no (?:...) groups.
    pat = (r"^[[:space:]]*(@\[[^]]*\][[:space:]]*)*"
           r"(protected[[:space:]]+|private[[:space:]]+|noncomputable[[:space:]]+)*"
           r"(theorem|lemma|def|abbrev|instance|structure|class|inductive)[[:space:]]+"
           + re.escape(short) + r"\b")
    files = []
    if module:
        f = module_file(module)
        if f:
            files.append(str(f))
    try:
        cmd = ["grep", "-rnH", "-E", pat]
        cmd += files if files else [str(PKG / "Physlib"), str(PKG / "QuantumInfo")]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        hits = [h for h in res.stdout.splitlines() if h.strip()]
        if not hits and files:  # fall back to the whole tree when the module file misses
            cmd = ["grep", "-rnH", "-E", pat, str(PKG / "Physlib"), str(PKG / "QuantumInfo")]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            hits = [h for h in res.stdout.splitlines() if h.strip()]
    except Exception as e:
        return {"error": str(e)}
    if not hits:
        return {"not_found": True}
    # Prefer a hit in the module's own file.
    hit = hits[0]
    fname, line, _ = hit.split(":", 2)
    text = pathlib.Path(fname).read_text().splitlines()
    i = int(line) - 1
    block = []
    for j in range(i, min(i + 20, len(text))):
        block.append(text[j])
        joined = " ".join(block)
        # Stop only once the *body* starts — a trailing ":" is the signature still going.
        if ":=" in joined or re.search(r"(:=| by\b|\bwhere\b)", joined):
            break
    src = "\n".join(block)
    return {"file": str(pathlib.Path(fname).relative_to(PKG)), "line": int(line),
            "source": src[:900], "ambiguous": len(hits) > 1, "n_hits": len(hits)}


def main() -> None:
    data = json.loads((SCRATCH / "hunt-ranked.json").read_text())
    for row in data["queue"]:
        for side in ("left", "right"):
            row[f"{side}_src"] = find_stmt(row[side], row.get(f"{side}_module"))
    (SCRATCH / "hunt-queue.json").write_text(
        json.dumps(data["queue"], ensure_ascii=False, indent=1))
    print(f"wrote hunt-queue.json with {len(data['queue'])} rows")


if __name__ == "__main__":
    main()
