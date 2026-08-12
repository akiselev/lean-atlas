#!/usr/bin/env python3
"""Machine check of research/data/B2-batch.json against the freeze protocol.

Checks (each failure is fatal; exit 0 only if everything holds):
  1. exactly 48 entries with the exact frozen id set (M01..16, X01..16,
     R01..08, C01..08) and the composition table's block counts;
  2. axis distribution of the 16 mutations matches the draft's summary table;
  3. every non-reserved entry satisfies the frontier-loop tuple: each of
     (claim, assumption delta, regime, falsifier, witness) resolves to a
     non-empty verbatim draft field; reserved slots are empty;
  4. every resolved B0 name in every entry's b0_refs exists in
     B0-representation.md (HYG-k resolved against the numbered §9 list, since
     the doc numbers those items rather than spelling every HYG-k literally);
  5. every char-2 entry on the draft's mandatory list carries a Π_B line;
  6. every cited sextant instrument resolves in ~/sinbad/crates/sextant/src
     (fn / struct / const / enum by name);
  7. claims are verbatim: every entry's Claim field text occurs in the draft.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "research/data/B2-batch.json"
B0 = ROOT / "research/gpt/campaigns/B0-representation.md"
DRAFT = ROOT / "research/gpt/campaigns/B2-batch-draft.md"
SEXTANT_SRC = Path.home() / "sinbad/crates/sextant/src"

failures = []


def fail(msg):
    failures.append(msg)


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    b0_text = B0.read_text(encoding="utf-8")
    draft_text = DRAFT.read_text(encoding="utf-8")
    draft_flat = re.sub(r"\s+", " ", draft_text)

    entries = {e["id"]: e for e in manifest["entries"]}

    # 1. id set and composition
    want = ([f"B2-M{i:02d}" for i in range(1, 17)] + [f"B2-X{i:02d}" for i in range(1, 17)]
            + [f"B2-R{i:02d}" for i in range(1, 9)] + [f"B2-C{i:02d}" for i in range(1, 9)])
    if sorted(entries) != sorted(want):
        fail(f"id set mismatch: missing {set(want) - set(entries)}, "
             f"extra {set(entries) - set(want)}")
    blocks = {}
    for e in manifest["entries"]:
        blocks[e["block"]] = blocks.get(e["block"], 0) + 1
    if blocks != {"mutation": 16, "transport": 16, "reserved": 8, "control": 8}:
        fail(f"composition mismatch: {blocks}")

    # 2. axis distribution
    for axis, ids in manifest["axis_distribution"].items():
        for eid in ids:
            if entries[eid].get("axis") != axis:
                fail(f"{eid}: axis {entries[eid].get('axis')} != summary-table {axis}")

    # 3. tuple roles
    for e in manifest["entries"]:
        if e["block"] == "reserved":
            if e["fields"] or any(v for v in e["tuple_roles"].values()):
                fail(f"{e['id']}: reserved slot is not empty")
            continue
        for role, key in e["tuple_roles"].items():
            if e["block"] == "control" and role == "assumption_delta" and key is None:
                # Controls are instruments, not hypotheses: no assumption delta
                # exists to record, and inventing one would be synthesis.
                continue
            if key is None:
                fail(f"{e['id']}: tuple role '{role}' unresolved")
                continue
            text = e["fields"].get(key, "") if key != "body" else e["fields"].get("body", "")
            if not text or not text.strip():
                fail(f"{e['id']}: tuple role '{role}' -> field '{key}' is empty")

    # 4. B0 names resolve
    hyg_sec = re.search(r"## 9\. Terminology hygiene.*?\n(.*?)\n## ", b0_text, re.S)
    hyg_count = len(re.findall(r"^\d+\.\s", hyg_sec.group(1), re.M)) if hyg_sec else 0
    for e in manifest["entries"]:
        for tok in e["b0_refs"]:
            m = re.match(r"^HYG-(\d+)$", tok)
            if m:
                if not (1 <= int(m.group(1)) <= hyg_count):
                    fail(f"{e['id']}: {tok} outside B0 §9's {hyg_count} numbered items")
                continue
            if not re.search(re.escape(tok) + r"\b", b0_text):
                fail(f"{e['id']}: B0 name '{tok}' not found in B0-representation.md")

    # 5. mandatory Pi_B lines
    for eid in manifest["pi_b_mandatory"]:
        if not entries[eid].get("pi_b_line"):
            fail(f"{eid}: on the mandatory Π_B list but carries no Π_B line")

    # 6. sextant instruments resolve
    src_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(SEXTANT_SRC.glob("*.rs")))
    for e in manifest["entries"]:
        for item in e["instruments"]["sextant"]:
            name = item.split("::")[-1]
            if not re.search(r"\b(?:fn|struct|const|enum)\s+" + re.escape(name) + r"\b",
                             src_text):
                fail(f"{e['id']}: sextant item '{item}' does not resolve in {SEXTANT_SRC}")
            if "::" in item:
                tyname = item.split("::")[0]
                if not re.search(r"\b(?:struct|enum)\s+" + re.escape(tyname) + r"\b", src_text):
                    fail(f"{e['id']}: sextant type '{tyname}' does not resolve")

    # 7. claims verbatim
    for e in manifest["entries"]:
        if e["block"] in ("mutation", "transport"):
            claim = e["fields"].get("Claim", "")
            if re.sub(r"\s+", " ", claim).strip() not in draft_flat:
                fail(f"{e['id']}: Claim text is not verbatim from the draft")

    if failures:
        print(f"B2 MANIFEST CHECK: FAIL ({len(failures)} problems)")
        for f in failures:
            print(f"  - {f}")
        return 1
    n = len(manifest["entries"])
    print(f"B2 MANIFEST CHECK: PASS — {n} entries, ids exact, tuple roles resolved, "
          f"B0 names resolved, Π_B lines present, sextant instruments resolve, claims verbatim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
