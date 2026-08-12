#!/usr/bin/env python3
"""witness-brief.py — render an atlas-cert/1 counterexample into a physicist brief.

One file, stdlib only (json, sys). This is a *renderer*, not a checker: it turns
a machine-checkable certificate bundle into a two-page brief a model-builder can
read, in the paper's own a/b/c/d/ε notation, cross-referenced to the fathom API
on the other side. The arithmetic is verified separately and independently by
`scripts/verify-certificate.py BUNDLE` — this brief points the referee there and
never asks them to trust it (or our stack) for the truth of the numbers.

Usage:
    witness-brief.py [BUNDLE.json] [-o OUT.md]
Default BUNDLE: the F0.0 known-false witness under research/data/referee-kits/cert/.
Exit: 0 rendered; 2 malformed bundle / usage.
"""

import json
import os
import sys
from fractions import Fraction

# --------------------------------------------------------------------------
# The a/b/c/d/ε mapping, transcribed from the paper AND from fathom so the
# brief can cite BOTH sides. Paper: arXiv:2603.23590 v3 (Jurciukonis-Lavoura-
# Milagre), Eq. labels are the paper's own \labels. fathom: sinbad-fathom
# crates/fathom/src/{lib.rs mapping table, couplings.rs}.
# --------------------------------------------------------------------------

COUPLING_ROWS = [
    # (paper symbol, paper Eq/label, fathom field, note)
    ("a_k", "Eq. (11) line 1 (uty)", "Couplings.a[k]", "coefficient of ½(Φ_k†Φ_k)²"),
    ("b_k", "Eq. (11) line 2 (uty)", "Couplings.b[k]", "(Φ_j†Φ_j)(Φ_l†Φ_l), (j,l) complementary to k"),
    ("c_k", "Eq. (11) line 3 (uty)", "Couplings.c[k]", "(Φ_j†Φ_l)(Φ_l†Φ_j)"),
    ("d_k", "Eq. (11) (jbu)", "Couplings.d[k]", "modulus of the (Φ_j†Φ_l)² coupling"),
]

# Level name -> (paper Eq label, direction, fathom entry). Necessary: fail =>
# not BFB. Sufficient: pass => BFB. From ledger-f0.0.md §1 and fathom lib.rs.
LEVELS = {
    "NCL1": ("Eq. (2hdm), 9 ineqs a_k>0, b̄_k>0, b̄_k+e_k>0", "necessary",
             "hierarchy::ncl1 / exact::ncl1"),
    "NCL2": ("Eq. (nc2), (jdp) at orbit corners P₁,P₂,P₃", "necessary",
             "hierarchy::ncl2 / exact::ncl2"),
    "NCL3": ("Eqs. (ncl3)+(nc3), 21 ineqs at corner P₄ (Branco: (Branc_nc3), 7)",
             "necessary", "hierarchy::ncl3 / ncl3_branco"),
    "NCL4": ("scans of Eqs. (mee),(err),(mfw), footnote-17 grids", "necessary",
             "hierarchy::ncl4 / Ncl4Grid"),
    "SC-GOO": ("Eqs. (suffGOO_1–4), Ref. [GOO]", "sufficient", "hierarchy::sc_goo"),
    "SC-Boto": ("Eqs. (suffBoto_1–3), Ref. [boto]", "sufficient", "hierarchy::sc_boto"),
}

# The published order of increasing stringency (necessary levels), for deciding
# what a witness "separates".
NCL_ORDER = ["NCL1", "NCL2", "NCL3", "NCL4"]


class Bad(Exception):
    pass


def frac(x):
    if isinstance(x, bool):
        raise Bad("boolean where a rational was expected")
    if isinstance(x, Fraction):
        return x
    if isinstance(x, (int, str)):
        return Fraction(x)
    raise Bad(f"non-rational {x!r} (floats are forbidden in atlas-cert/1)")


def fmt_q(x):
    """A rational for humans: integer if whole, else n/d."""
    f = frac(x)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def fmt_complex(pair):
    re, im = frac(pair[0]), frac(pair[1])
    if im == 0:
        return fmt_q(re)
    if re == 0:
        return f"{fmt_q(im)}i"
    sign = "+" if im > 0 else "−"
    return f"{fmt_q(re)} {sign} {fmt_q(abs(im))}i"


def eps_description(cos_eps, sin_eps):
    c, s = frac(cos_eps), frac(sin_eps)
    if (c, s) == (Fraction(1), Fraction(0)):
        return "ε = 0 (CP-conserving **Branco** case; the phase drops out)"
    return (f"(cos ε, sin ε) = ({fmt_q(c)}, {fmt_q(s)}) — a rational point on the "
            "unit circle (Pythagorean phase); ε is the single physical phase "
            "(Eq. (12)), placed at k=1 (Eq. (13))")


def render(bundle, bundle_path):
    if bundle.get("schema") != "atlas-cert/1":
        raise Bad(f"schema is {bundle.get('schema')!r}, expected 'atlas-cert/1'")
    if bundle.get("species") != "counterexample":
        raise Bad("witness-brief renders species 'counterexample' only")

    cpl = bundle["couplings"]
    direction = bundle["direction"]
    claim = bundle["claim_violated"]
    model = bundle.get("model", {})
    prov = bundle.get("provenance", {})
    bid = bundle.get("id", "<no id>")

    a, b, c, d = cpl["a"], cpl["b"], cpl["c"], cpl["d"]
    asserted = fmt_q(claim["asserted_value"])
    strict = claim.get("type") == "BFB-strict"
    levels = claim.get("levels", {})
    fails = levels.get("fails", [])
    passes = levels.get("passes", [])

    out = []
    w = out.append

    # --- header -----------------------------------------------------------
    w(f"# Counterexample brief — `{bid}`")
    w("")
    w("**A referee kit is verifiable without trusting our stack.** This brief is a "
      "*reading* of a machine-checkable certificate; the numbers are verified "
      "independently by")
    w("")
    w(f"```sh\npython3 scripts/verify-certificate.py {os.path.relpath(bundle_path)}\n```")
    w("")
    w("(stdlib-only, transcribes the potential from the paper directly — see "
      "`research/gpt/certificate-format.md`). Nothing below asks you to trust "
      "sinbad-fathom or this renderer for the truth of the arithmetic.")
    w("")
    w(f"- **Model:** {model.get('name','?')} — {model.get('source','')}")
    if prov:
        camp = prov.get("campaign", "")
        ledg = prov.get("ledger", "")
        w(f"- **Provenance:** {camp}" + (f"; {ledg}" if ledg else ""))
    w("")

    # --- the claim refuted -----------------------------------------------
    w("## 1. What is refuted")
    w("")
    stmt = claim.get("statement", "")
    w(f"> {stmt}")
    w("")
    w(f"The certificate exhibits an **exact** field direction on which the quartic "
      f"V₄ equals **{asserted}**. V₄ is homogeneous of degree 4, so one "
      f"non-positive direction decides unboundedness-from-below along that ray"
      + (" (strict BFB, the paper's footnote-4 convention: V₄>0 is violated by "
         "V₄ ≤ 0)." if strict else " (V₄ < 0)."))
    w("")

    # --- coupling point in both notations --------------------------------
    w("## 2. The coupling point (paper ⟷ fathom)")
    w("")
    w("The 13-parameter tuple {a₁..a₃, b₁..b₃, c₁..c₃, d₁..d₃, ε} of Eq. (11)+(12), "
      "canonical phase placement Eq. (13). Each row cites the paper symbol and the "
      "fathom field that carries it.")
    w("")
    w("| k | a_k | b_k | c_k | d_k |")
    w("|---|-----|-----|-----|-----|")
    for k in range(3):
        w(f"| {k+1} | {fmt_q(a[k])} | {fmt_q(b[k])} | {fmt_q(c[k])} | {fmt_q(d[k])} |")
    w("")
    w(f"- **Phase:** {eps_description(cpl['cos_eps'], cpl['sin_eps'])}.")
    w("")
    w("| paper symbol | paper location | fathom field | meaning |")
    w("|---|---|---|---|")
    for sym, loc, field, note in COUPLING_ROWS:
        w(f"| {sym} | {loc} | `{field}` | {note} |")
    w("| ε | Eq. (12)/(13) | `Couplings.cos_eps`, `Couplings.sin_eps` | single physical phase |")
    w("")
    w("*(mapping transcribed from arXiv:2603.23590 v3 Eq. (11) and from "
      "`crates/fathom/src/lib.rs` / `couplings.rs`; k is 1-based in the paper, "
      "0-based in the array.)*")
    w("")

    # --- field direction --------------------------------------------------
    w("## 3. The field direction")
    w("")
    w("Three SU(2) doublets Φ₁, Φ₂, Φ₃ (paper Eq. (jbp)), exact rational "
      "components (a+bi):")
    w("")
    w("| doublet | upper component | lower component |")
    w("|---|---|---|")
    phi = direction["phi"]
    for k, dbl in enumerate(phi):
        w(f"| Φ{k+1} | {fmt_complex(dbl[0])} | {fmt_complex(dbl[1])} |")
    w("")
    desc = direction.get("description")
    if desc:
        w(f"*{desc}*")
        w("")

    # --- what it separates -----------------------------------------------
    w("## 4. Which condition levels it separates")
    w("")
    w("Direction of the published hierarchy: **necessary** levels (NCLn) fail ⟹ "
      "not BFB; **sufficient** sets (SC) pass ⟹ BFB. A witness *separates* two "
      "levels when it passes the weaker and fails the stronger.")
    w("")
    w("| level | verdict here | paper | direction | fathom |")
    w("|---|---|---|---|---|")
    for name in NCL_ORDER + ["SC-GOO", "SC-Boto"]:
        if name not in LEVELS:
            continue
        eq, direction_kind, fn = LEVELS[name]
        if name in fails:
            verdict = "**FAILS**"
        elif name in passes:
            verdict = "passes"
        else:
            verdict = "—"
        w(f"| {name} | {verdict} | {eq} | {direction_kind} | `{fn}` |")
    w("")
    # Interpret.
    failed_ncls = [n for n in NCL_ORDER if n in fails]
    passed_ncls = [n for n in NCL_ORDER if n in passes]
    if passed_ncls and failed_ncls:
        w(f"**Separates** {passed_ncls[-1]} from {failed_ncls[0]}: it satisfies "
          f"every necessary level up to {passed_ncls[-1]} yet fails {failed_ncls[0]}, "
          "so it lives in the gap the stronger level closes.")
    elif failed_ncls == ["NCL1"] and not passed_ncls:
        w("This point fails at the **first** necessary level (NCL1). It is a "
          "**known-non-BFB control**, not a level-separating witness: it certifies "
          "that the checker and the encoding agree on a case whose answer is not in "
          "doubt (the 2HDM-sub-model argument, ledger-f0.0 §3). Level-separating "
          "witnesses — NCL1∧¬NCL2, NCL1∧NCL2∧¬NCL3, … — are the F0.1 deliverable.")
    else:
        w("Verdict pattern recorded from the bundle's `levels` block; see the "
          "note below on what is and is not machine-checked.")
    if levels.get("note"):
        w("")
        w(f"> Ledger note: {levels['note']}")
    w("")

    # --- which models live here (BLANK) -----------------------------------
    w("## 5. Which models live here — *template, for the model-builder*")
    w("")
    w("*Left deliberately blank. To be filled by a discrete-symmetry model builder "
      "(collaborators-la.md §1: M.-C. Chen / M. Ratz at UCI, E. Ma at UCR).*")
    w("")
    w("- **Which BSM constructions sit at or near this coupling point?** "
      "(dark-doublet / inert, scotogenic, A₄ or Δ(54) flavon vacuum, …)")
    w("  \n  _______________________________________________")
    w("- **Is this coupling region phenomenologically reachable** "
      "(after RGE running from a plausible high scale)?")
    w("  \n  _______________________________________________")
    w("- **What breaks if V₄ is unbounded below here** "
      "(vacuum stability, domain walls / GW signatures)?")
    w("  \n  _______________________________________________")
    w("- **Nearest solved neighbour** (U(1)×U(1), ℤ₂×U(1) [faro1,faro2]; S₄/SO(3) "
      "per footnote 8) and does the counterexample transport there?")
    w("  \n  _______________________________________________")
    w("")

    # --- trust boundary ---------------------------------------------------
    w("## 6. What is machine-checked, and what is not")
    w("")
    w("`verify-certificate.py` checks, exactly over ℚ: the phase is on the unit "
      "circle; the direction is nonzero; V₄(direction) equals the asserted value; "
      "and that value violates the cited positivity claim. It **does not** verify "
      "the condition-level annotations of §4 (ledger metadata — levels beyond NCL1 "
      "involve nested radicals, out of scope for a by-eye checker) nor any claim "
      "about population percentages. Those are the reading; the sign of V₄ is the "
      "result.")
    w("")
    w("**Routing (collaborators-la.md §5):** certificate soundness "
      "(Nie/Chandrasekaran) before any physics claim leaves the building; then "
      "physical relevance (Ma/Chen); the paper's authors only per E7 if a "
      "*published* condition falls.")
    w("")
    return "\n".join(out) + "\n"


def main(argv):
    here = os.path.dirname(os.path.abspath(argv[0]))
    default = os.path.normpath(os.path.join(
        here, "..", "research", "data", "referee-kits", "cert",
        "counterexample-known-false.json"))
    args = [a for a in argv[1:]]
    out_path = None
    if "-o" in args:
        i = args.index("-o")
        try:
            out_path = args[i + 1]
        except IndexError:
            print("usage: witness-brief.py [BUNDLE.json] [-o OUT.md]")
            return 2
        del args[i:i + 2]
    bundle_path = args[0] if args else default
    try:
        with open(bundle_path, "r", encoding="utf-8") as fh:
            bundle = json.load(fh)
        text = render(bundle, bundle_path)
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read bundle: {e}")
        return 2
    except Bad as e:
        print(f"malformed bundle: {e}")
        return 2
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {out_path}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
