#!/usr/bin/env python3
"""Build research/data/B2-batch.json 1:1 from B2-batch-draft.md.

Freeze protocol (B2-batch-draft.md, "Freeze protocol"): the machine manifest is
GENERATED from the draft document, never hand-written, so the claims stay
verbatim. This script parses the draft's own field bullets into a raw `fields`
dict per entry (verbatim text), then adds only:

  - normalized tuple-role POINTERS (which draft field serves which role of the
    frontier-loop tuple (claim, assumption delta, regime, falsifier, witness))
    -- pointers, not paraphrases;
  - an `instruments` annotation naming the sextant items an entry's pass-1
    falsifier uses (validated to resolve by scripts/b2-manifest-check.py).

Nothing in an entry's claim text is synthesized here. Exit 0 on success.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / "research/gpt/campaigns/B2-batch-draft.md"
OUT = ROOT / "research/data/B2-batch.json"

# --- the instruments annotation layer (sextant items must resolve in the crate) ---
# Names are `Type::method`, bare `fn`, or bare `struct`/`const` in
# ~/sinbad/crates/sextant/src. Entries not listed carry an empty sextant list.
INSTRUMENTS = {
    "B2-M06": {
        "sextant": ["Fq::try_frob_pow", "SymplecticSpace::try_isotropic",
                     "SymplecticSpace::try_pairing", "Subspace::try_vector_set"],
        "driver": "F_p-additive isotropic enumeration in V_q (trace form), driver-side; "
                  "phased-group arm deferred to B1",
    },
    "B2-M07": {
        "sextant": ["Fq::try_frob_pow", "Fq::try_mul", "Fq::try_add"],
        "driver": "expandB/assembleB (REP-3) + trace-dual bases, driver-side; "
                  "all ordered bases of F_4/F_2 and F_8/F_2",
    },
    "B2-M08": {
        "sextant": ["Fq", "SymplecticSpace::try_isotropic", "Subspace::try_vector_set"],
        "driver": "(B,B) same-basis expansion Gram check over all 48 ordered bases of F_9/F_3",
    },
    "B2-M11": {
        "sextant": ["SymplecticSpace::try_lagrangians", "try_sp_order", "Fq::try_frob_pow"],
        "driver": "GL(2,q) x Gal sweep for (q+1)-cycles on striations, per OC rung",
    },
    "B2-M12": {
        "sextant": ["SymplecticSpace::try_isotropic",
                     "SymplecticSpace::try_label_frobenius_image", "Subspace::try_from_spanning"],
        "driver": "EQ-C generator closure (local SL(2,q) + qudit permutations); "
                  "sign level deferred to B1",
    },
    "B2-M15": {
        "sextant": ["Fq"],
        "driver": "derived-field construction F_16 = F_2[x]/(x^4+x+1) driver-side per OD-3 "
                  "(sextant's frozen bounds stop at m = 3); tower expand maps",
    },
    "B2-M16": {
        "sextant": ["Fq::try_frob_pow", "Fq::try_mul"],
        "driver": "trace-orthonormal (self-dual) basis exhaust; BMS structural half deferred",
    },
    "B2-X05": {
        "sextant": ["SymplecticSpace::try_pairing", "Fq::try_frob_pow"],
        "driver": "twisted form sigma_l(u,v) = Tr(sigma_q(u, sigma^l v)) label-level census; "
                  "unitary intertwiner arm deferred to B1",
    },
    "B2-X06": {
        "sextant": ["SymplecticSpace::try_isotropic", "Subspace::try_vector_set",
                     "Fq::try_frob_pow", "Fq::try_is_in_subfield"],
        "driver": "trace image vs subfield restriction per code; phase correction deferred to B1",
    },
    "B2-X07": {
        "sextant": ["SymplecticSpace::try_isotropic", "Fq::try_frob_pow"],
        "driver": "label-geometry arm shares B2-M08's instrument; CSS parameter arm deferred",
    },
    "B2-X11": {
        "sextant": ["Fq::try_frob_pow", "SymplecticSpace::try_pairing"],
        "driver": "Hermitian / trace-alternating / conjugation-fixed triple census, "
                  "F_q^2-linear codes, length <= 3 (length 4 needs a recorded BND extension)",
    },
    "B2-C01": {
        "sextant": ["SymplecticSpace::try_pairing", "Fq::try_frob_pow"],
        "driver": "monomial Weyl commutator differential (exact, phase-convention-free), "
                  "q^n <= 1024 per OD-4",
    },
    "B2-C02": {
        "sextant": ["SymplecticSpace::try_isotropic", "Subspace::try_vector_set"],
        "driver": "(B,B*) trace-descent distance comparison per basis",
    },
    "B2-C04": {
        "sextant": ["SymplecticSpace::try_lagrangians",
                     "SymplecticSpace::try_label_frobenius_image",
                     "SymplecticSpace::try_fix_indices"],
        "driver": None,
    },
    "B2-C05": {
        "sextant": ["try_wrong_frobenius_vector_image", "try_is_vector_set_a_subspace",
                     "try_column0_twist_on_canonical_form"],
        "driver": None,
    },
    "B2-C06": {
        "sextant": ["Fq"],
        "driver": "exact monomial-matrix computation of W'(1,1)^dagger vs omega W'(-1,-1) at (3,1,1)",
    },
    "B2-C07": {
        "sextant": ["SymplecticSpace::corrupted", "lagrangian_count", "gaussian_binomial"],
        "driver": "J' = [[0,I],[I,0]] (odd p) and rank-deficient J'' (p = 2) census, driver-side "
                  "generic-Gram pairing",
    },
    "B2-C08": {
        "sextant": ["lagrangian_count"],
        "driver": "Z_d maximal-isotropic-submodule census (d = 4, 8, 9), driver-side; "
                  "prime-d agreement positive arm",
    },
}

# Entries the composition summary lists as carrying the mandatory Pi_B line.
PI_B_MANDATORY = ["B2-M03", "B2-M04", "B2-M05", "B2-M06", "B2-M07", "B2-M12",
                  "B2-M13", "B2-M14", "B2-M15", "B2-X04", "B2-X06", "B2-X08",
                  "B2-X14", "B2-C04", "B2-C08"]


def parse_sections(text):
    """Split the draft into ### entry sections (M and X blocks)."""
    out = {}
    pat = re.compile(r"^### (B2-[MX]\d\d) · (.+)$", re.M)
    matches = list(pat.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end]
        # stop each section body at a block separator that begins a new part
        body = body.split("\n---\n")[0]
        out[m.group(1)] = (m.group(2).strip(), body)
    return out


def parse_fields(body):
    """Parse '- **Label:** text' bullets (multi-line) into an ordered dict."""
    fields = {}
    current = None
    for line in body.splitlines():
        m = re.match(r"^- \*\*(.+?):?\*\*:?\s*(.*)$", line)
        if m:
            label = m.group(1).rstrip(":").strip()
            fields[label] = m.group(2).strip()
            current = label
        elif current is not None and line.startswith("  "):
            fields[current] += " " + line.strip()
        elif line.strip() == "":
            continue
        else:
            current = None
    return fields


def find_field(fields, *names):
    for n in names:
        for k, v in fields.items():
            if k == n:
                return k
    return None


def find_pi_b(fields):
    for k in fields:
        if k.startswith("Π_B line"):
            return k
    return None


def tokenize_b0_refs(raw):
    """Split a B0 refs string into resolved tokens (prefix-inheriting on '/')."""
    tokens = []
    cleaned = re.sub(r"\([^)]*\)", "", raw)
    cleaned = cleaned.rstrip(". ")
    for part in cleaned.split(","):
        part = part.strip().rstrip(".")
        if not part:
            continue
        if part == "OC ladder":
            tokens += ["OC-1", "OC-2", "OC-3"]
            continue
        subs = part.split("/")
        prev = None
        for s in subs:
            s = s.strip()
            if not s:
                continue
            if re.match(r"^(REP|ACT|PH|CH2|FORM|EQ|OC|BND|ANC|CTL|HYG|OD|CONV|INT|FROB)-", s) \
               or s in ("CLIF",):
                tokens.append(s)
                prev = s
            elif prev is not None:
                prefix = prev.rsplit("-", 1)[0] + "-"
                tokens.append(prefix + s)
            else:
                tokens.append(s)
                prev = s
    return tokens


def main():
    text = DRAFT.read_text(encoding="utf-8")
    sections = parse_sections(text)

    entries = []

    # --- mutations and transports ---
    for eid in [f"B2-M{i:02d}" for i in range(1, 17)] + [f"B2-X{i:02d}" for i in range(1, 17)]:
        header, body = sections[eid]
        fields = parse_fields(body)
        block = "mutation" if "-M" in eid else "transport"
        meta = {}
        if block == "mutation":
            hm = re.match(r"^(A\d) · (.+)$", header)
            meta["axis"] = hm.group(1)
            meta["target_line"] = hm.group(2)
        else:
            parts = [p.strip() for p in header.split("·")]
            if parts[0] == "ANCHOR":
                meta["anchor"] = True
                meta["seam"] = parts[1]
                meta["target_line"] = " · ".join(parts[2:])
            else:
                meta["anchor"] = False
                meta["seam"] = parts[0]
                meta["target_line"] = " · ".join(parts[1:])

        refs_key = find_field(fields, "B0 refs")
        pi_b_key = find_pi_b(fields)
        roles = {
            "claim": find_field(fields, "Claim"),
            "assumption_delta": find_field(fields, "Assumption delta", "Mutation", "Source"),
            "regime": find_field(fields, "Regime", "Regime/bounds", "Exclusions/bounds/witness"),
            "falsifier": find_field(fields, "Falsifier", "Falsifier/witness",
                                     "Exclusions/bounds/witness"),
            "witness": find_field(fields, "Witness sought", "Falsifier/witness",
                                   "Exclusions/bounds/witness"),
        }
        entries.append({
            "id": eid,
            "block": block,
            **meta,
            "fields": fields,
            "tuple_roles": roles,
            "pi_b_line": fields.get(pi_b_key) if pi_b_key else None,
            "b0_refs_raw": fields.get(refs_key, ""),
            "b0_refs": tokenize_b0_refs(fields.get(refs_key, "")),
            "instruments": INSTRUMENTS.get(eid, {"sextant": [], "driver": None}),
        })

    # --- reserved slots ---
    res_m = re.search(r"## \(c\) Eight reserved cluster slots — B2-R01\.\.R08\n(.*?)\n---\n",
                      text, re.S)
    fill_rule = res_m.group(1).strip()
    for i in range(1, 9):
        entries.append({
            "id": f"B2-R{i:02d}",
            "block": "reserved",
            "status": "empty",
            "fields": {},
            "tuple_roles": {k: None for k in
                            ("claim", "assumption_delta", "regime", "falsifier", "witness")},
            "pi_b_line": None,
            "b0_refs_raw": "",
            "b0_refs": [],
            "fill_rule": fill_rule,
            "instruments": {"sextant": [], "driver": None},
        })

    # --- controls ---
    ctl_m = re.search(r"## \(d\) Eight controls — B2-C01\.\.C08\n(.*?)\n---\n", text, re.S)
    ctl_text = ctl_m.group(1)
    kind_of = {**{f"B2-C{i:02d}": "known_true" for i in (1, 2, 3)},
               **{f"B2-C{i:02d}": "known_false" for i in (4, 5, 6)},
               **{f"B2-C{i:02d}": "corrupted_convention" for i in (7, 8)}}
    cpat = re.compile(r"^- \*\*(B2-C\d\d)\.\*\*\s*(.*?)(?=^- \*\*B2-C|^###|\Z)", re.M | re.S)
    seen_controls = {}
    for m in cpat.finditer(ctl_text):
        cid = m.group(1)
        body = re.sub(r"\s+", " ", m.group(2)).strip()
        seen_controls[cid] = body
    for i in range(1, 9):
        cid = f"B2-C{i:02d}"
        body = seen_controls[cid]
        refs = re.search(r"\*\*B0 refs:\*\*\s*(.+?)$", body)
        planted = re.search(r"\*\*Planted witness:\*\*\s*(.+?)(?=\*\*|$)", body)
        pib = re.search(r"\*\*Π_B line \(CTL-3\):\*\*\s*(.+?)(?=\*\*|$)", body)
        claim = re.split(r"\*\*(?:Planted witness|Π_B line|B0 refs)", body)[0].strip()
        raw_refs = refs.group(1).strip() if refs else ""
        entries.append({
            "id": cid,
            "block": "control",
            "control_kind": kind_of[cid],
            "fields": {"body": body},
            "tuple_roles": {"claim": "body", "assumption_delta": None, "regime": "body",
                            "falsifier": "body", "witness": "body"},
            "claim_head": claim,
            "planted_witness": planted.group(1).strip() if planted else None,
            "pi_b_line": pib.group(1).strip() if pib else None,
            "b0_refs_raw": raw_refs,
            "b0_refs": tokenize_b0_refs(raw_refs),
            "instruments": INSTRUMENTS.get(cid, {"sextant": [], "driver": None}),
        })

    # --- top-level metadata ---
    od_deps = re.search(r"Open-decision dependencies: (.+?)\n\n", text, re.S)
    reverif = re.search(r"\*\*Re-verification queries to re-run at freeze time\*\*(.*?)\n\n\*\*Post-freeze",
                        text, re.S)

    manifest = {
        "schema": "atlas-b2-batch-v1",
        "generated_from": "research/gpt/campaigns/B2-batch-draft.md",
        "generated_by": "scripts/b2-manifest-build.py",
        "b0_interface": "research/gpt/campaigns/B0-representation.md",
        "date": "2026-08-07",
        "authorization": ("user 2026-08-07 — B0-representation.md §12: OD-1..4 accepted as "
                          "proposed, §11 ratified, B0 FROZEN; batch freeze executed under the "
                          "same-day directive citing that authorization"),
        "draft_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "composition": {"mutations": 16, "transports": 16, "reserved": 8, "controls": 8},
        "axis_distribution": {"A1": ["B2-M01", "B2-M02", "B2-M03", "B2-M09"],
                               "A2": ["B2-M04", "B2-M05", "B2-M06"],
                               "A3": ["B2-M07", "B2-M08"],
                               "A4": ["B2-M10", "B2-M11", "B2-M12"],
                               "A5": ["B2-M13", "B2-M14"],
                               "A6": ["B2-M15", "B2-M16"]},
        "pi_b_mandatory": PI_B_MANDATORY,
        "od_dependencies": re.sub(r"\s+", " ", od_deps.group(1)).strip() if od_deps else "",
        "freeze_reverification": re.sub(r"[ \t]+", " ", reverif.group(1)).strip() if reverif else "",
        "entries": entries,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} with {len(entries)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
