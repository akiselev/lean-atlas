#!/usr/bin/env python3
"""atlas-cert/1 reference checker — see research/gpt/certificate-format.md.

One file, stdlib only (json, sys, fractions). Designed to be audited by eye:
an external referee should be able to read this top to bottom and agree that
a PASS verdict implies the certified statement, without trusting anything
else in this repository.

INDEPENDENCE NOTE. The Z2xZ2 3HDM quartic V4 embedded below is transcribed
from the source paper directly:

    D. Jurciukonis, L. Lavoura, A. Milagre, "Assessing boundedness from below
    in the Z2xZ2-symmetric three-Higgs-doublet model: algorithm and machine
    learning", arXiv:2603.23590 v3.

Equation numbers cited in comments are that paper's. The transcription was
made from the paper's equations, not from the Rust engine (sinbad-fathom)
whose outputs these certificates describe — agreement between the two is a
differential check across independent transcriptions, which is the point.

Usage:
    verify-certificate.py BUNDLE.json          verdict on one bundle
    verify-certificate.py --selftest [DIR]     replay the pinned kit

Exit codes: 0 = PASS (or selftest all-match), 1 = REJECT (or selftest
mismatch), 2 = malformed input / usage error.
"""

import json
import sys
from fractions import Fraction

SCHEMA = "atlas-cert/1"
MODEL_NAME = "Z2xZ2-3HDM-quartic-v4"


# --------------------------------------------------------------------------
# Verdicts. A certificate is REJECTed with a code; PASS carries no code.
# MALFORMED means the bundle could not even be interpreted (exit 2, so an
# operator can tell a broken file from a refuted certificate).
# --------------------------------------------------------------------------

class Reject(Exception):
    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Malformed(Reject):
    def __init__(self, detail):
        super().__init__("MALFORMED", detail)


# --------------------------------------------------------------------------
# Exact rationals. Mathematical numbers must be strings "n" or "n/d" (or JSON
# integers). JSON floats are rejected: a float in an exactness claim is a
# category error, not a tolerance question.
# --------------------------------------------------------------------------

def rat(x, where):
    if isinstance(x, bool):
        raise Malformed(f"{where}: boolean where a rational was expected")
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        raise Malformed(f"{where}: JSON float forbidden; use a string 'n/d'")
    if isinstance(x, str):
        try:
            return Fraction(x)  # Fraction("3"), Fraction("-9/4")
        except (ValueError, ZeroDivisionError):
            raise Malformed(f"{where}: unparseable rational {x!r}")
    raise Malformed(f"{where}: expected rational, got {type(x).__name__}")


def rat_list(xs, n, where):
    if not isinstance(xs, list) or len(xs) != n:
        raise Malformed(f"{where}: expected a list of {n} rationals")
    return [rat(x, f"{where}[{i}]") for i, x in enumerate(xs)]


# Complex rationals as (re, im) pairs; only +, *, conj are needed for V4.

def crat(x, where):
    if not isinstance(x, list) or len(x) != 2:
        raise Malformed(f"{where}: expected [re, im]")
    return (rat(x[0], f"{where}.re"), rat(x[1], f"{where}.im"))


def cadd(a, b):
    return (a[0] + b[0], a[1] + b[1])


def cmul(a, b):
    return (a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0])


def cconj(a):
    return (a[0], -a[1])


# --------------------------------------------------------------------------
# The model: V4 of the Z2xZ2 3HDM, transcribed from arXiv:2603.23590 v3.
#
# Eq. (11):  V4 = sum_k (a_k/2) (Phi_k^dag Phi_k)^2
#                + b_1 (Phi_2^dag Phi_2)(Phi_3^dag Phi_3)
#                + b_2 (Phi_3^dag Phi_3)(Phi_1^dag Phi_1)
#                + b_3 (Phi_1^dag Phi_1)(Phi_2^dag Phi_2)
#                + c_1 (Phi_2^dag Phi_3)(Phi_3^dag Phi_2)
#                + c_2 (Phi_3^dag Phi_1)(Phi_1^dag Phi_3)
#                + c_3 (Phi_1^dag Phi_2)(Phi_2^dag Phi_1)
#                + [ e^{i eps_1} (d_1/2) (Phi_2^dag Phi_3)^2
#                  + e^{i eps_2} (d_2/2) (Phi_3^dag Phi_1)^2
#                  + e^{i eps_3} (d_3/2) (Phi_1^dag Phi_2)^2 + H.c. ]
#
# so the d-line contributes Re[e^{i eps_k} d_k K_k^2] for each k, with
# K_1 = Phi_2^dag Phi_3, K_2 = Phi_3^dag Phi_1, K_3 = Phi_1^dag Phi_2
# (z/2 + conj(z)/2 = Re z). Note (Phi_j^dag Phi_l)(Phi_l^dag Phi_j) = |K_k|^2.
#
# Eq. (12): only eps := eps_1 + eps_2 + eps_3 is physical.
# Eq. (13): canonical placement eps_1 = eps, eps_2 = eps_3 = 0 — the fixed
# convention of atlas-cert/1 bundles; the phase enters only the k=1 d-term.
# --------------------------------------------------------------------------

def parse_couplings(obj, where="couplings"):
    if not isinstance(obj, dict):
        raise Malformed(f"{where}: expected an object")
    out = {}
    for key in ("a", "b", "c", "d"):
        out[key] = rat_list(obj.get(key), 3, f"{where}.{key}")
    out["cos_eps"] = rat(obj.get("cos_eps"), f"{where}.cos_eps")
    out["sin_eps"] = rat(obj.get("sin_eps"), f"{where}.sin_eps")
    return out


def parse_direction(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("phi"), list) \
            or len(obj["phi"]) != 3:
        raise Malformed("direction.phi: expected three doublets")
    phi = []
    for k, dbl in enumerate(obj["phi"]):
        if not isinstance(dbl, list) or len(dbl) != 2:
            raise Malformed(f"direction.phi[{k}]: expected two components")
        phi.append([crat(dbl[0], f"direction.phi[{k}][0]"),
                    crat(dbl[1], f"direction.phi[{k}][1]")])
    return phi


def v4_exact(cpl, phi):
    """V4 per Eq. (11) with the Eq. (13) phase placement, exact over Q."""
    # Bilinears: n_k = Phi_k^dag Phi_k (real), K_k the cross bilinears above.
    def inner(j, l):  # Phi_j^dag Phi_l = sum_i conj(phi[j][i]) * phi[l][i]
        s = (Fraction(0), Fraction(0))
        for i in range(2):
            s = cadd(s, cmul(cconj(phi[j][i]), phi[l][i]))
        return s

    n = [inner(k, k)[0] for k in range(3)]  # imaginary part is 0 by construction
    K = [inner(1, 2), inner(2, 0), inner(0, 1)]  # K_1, K_2, K_3 (0-indexed)

    total = Fraction(0)
    # a-line of Eq. (11): sum_k (a_k/2) n_k^2.
    for k in range(3):
        total += cpl["a"][k] * n[k] * n[k] / 2
    # b-line: b_k couples the complementary pair of norms.
    total += cpl["b"][0] * n[1] * n[2]
    total += cpl["b"][1] * n[2] * n[0]
    total += cpl["b"][2] * n[0] * n[1]
    # c-line: c_k |K_k|^2.
    for k in range(3):
        total += cpl["c"][k] * (K[k][0] * K[k][0] + K[k][1] * K[k][1])
    # d-line: Re[e^{i eps_k} d_k K_k^2], eps_1 = eps, eps_2 = eps_3 = 0.
    for k in range(3):
        sq = cmul(K[k], K[k])
        if k == 0:
            re = cpl["cos_eps"] * sq[0] - cpl["sin_eps"] * sq[1]
        else:
            re = sq[0]
        total += cpl["d"][k] * re
    return total


# --------------------------------------------------------------------------
# Species: counterexample.
# --------------------------------------------------------------------------

def check_counterexample(bundle, log):
    cpl = parse_couplings(bundle.get("couplings"))
    phi = parse_direction(bundle.get("direction"))
    claim = bundle.get("claim_violated")
    if not isinstance(claim, dict):
        raise Malformed("claim_violated: expected an object")
    asserted = rat(claim.get("asserted_value"), "claim_violated.asserted_value")
    strict = claim.get("type") == "BFB-strict"

    # (1) The phase must be a point on the unit circle, exactly — otherwise
    # the bundle does not describe a phase and Eq. (13) does not apply.
    unit = cpl["cos_eps"] ** 2 + cpl["sin_eps"] ** 2
    if unit != 1:
        raise Reject("PHASE_NOT_UNIT", f"cos^2+sin^2 = {unit}, not 1")
    log("CHECK phase-on-unit-circle: ok (exact)")

    # (2) The direction must be a nonzero field configuration.
    if all(c == 0 for dbl in phi for comp in dbl for c in comp):
        raise Reject("ZERO_DIRECTION", "all field components are zero")
    log("CHECK direction-nonzero: ok")

    # (3) Exact evaluation must reproduce the asserted value...
    value = v4_exact(cpl, phi)
    if value != asserted:
        raise Reject("WRONG_ARITHMETIC",
                     f"V4 evaluates to {value}, bundle asserts {asserted}")
    log(f"CHECK exact-evaluation: ok — V4(direction) = {value}")

    # (4) ...and that value must actually violate positivity. A strict claim
    # (V4 > 0) is violated by <= 0; a non-strict one needs < 0.
    if strict:
        violated = value <= 0
    else:
        violated = value < 0
    if not violated:
        raise Reject("NOT_NEGATIVE",
                     f"V4 = {value} does not violate the cited claim")
    log("CHECK sign: ok — value violates "
        + ("V4 > 0 (strict BFB)" if strict else "V4 >= 0"))

    return [
        "condition-level annotations in claim_violated.levels "
        "(campaign metadata for the physics brief, not verified here)",
        "any statement about population percentages or other points",
    ]


# --------------------------------------------------------------------------
# Polynomials over Q: dict {exponent-tuple: coefficient}. Zero coefficients
# are dropped so equality of dicts is equality of polynomials.
# --------------------------------------------------------------------------

def parse_poly(obj, nvars, where):
    if not isinstance(obj, dict) or not isinstance(obj.get("terms"), list):
        raise Malformed(f"{where}: expected {{'terms': [...]}}")
    poly = {}
    for i, term in enumerate(obj["terms"]):
        w = f"{where}.terms[{i}]"
        if not isinstance(term, dict):
            raise Malformed(f"{w}: expected an object")
        exps = term.get("exps")
        if (not isinstance(exps, list) or len(exps) != nvars
                or any(not isinstance(e, int) or e < 0 for e in exps)):
            raise Malformed(f"{w}.exps: expected {nvars} nonneg integers")
        poly_add(poly, tuple(exps), rat(term.get("coeff"), f"{w}.coeff"))
    return poly


def poly_add(poly, exps, coeff):
    c = poly.get(exps, Fraction(0)) + coeff
    if c == 0:
        poly.pop(exps, None)
    else:
        poly[exps] = c


def poly_str(poly, variables):
    if not poly:
        return "0"
    parts = []
    for exps in sorted(poly, reverse=True):
        mono = "*".join(f"{v}^{e}" if e > 1 else v
                        for v, e in zip(variables, exps) if e > 0)
        parts.append(f"({poly[exps]}){'*' + mono if mono else ''}")
    return " + ".join(parts)


# --------------------------------------------------------------------------
# Species: sos (SOS / Farkas). Soundness: lambda_i >= 0, exact identity
# target - sum lambda_i g_i = m^T G m, G symmetric PSD  ==>  target >= 0
# wherever all g_i >= 0 (format doc section 4 states the one-line proof).
# --------------------------------------------------------------------------

def check_sos(bundle, log):
    variables = bundle.get("variables")
    if (not isinstance(variables, list) or not variables
            or any(not isinstance(v, str) for v in variables)):
        raise Malformed("variables: expected a nonempty list of names")
    nv = len(variables)

    target = parse_poly(bundle.get("target"), nv, "target")

    constraints = bundle.get("constraints", [])
    multipliers = bundle.get("multipliers", [])
    if not isinstance(constraints, list) or not isinstance(multipliers, list):
        raise Malformed("constraints/multipliers: expected lists")
    if len(constraints) != len(multipliers):
        raise Malformed("constraints and multipliers differ in length")
    gs, lams = [], []
    for i, con in enumerate(constraints):
        if not isinstance(con, dict):
            raise Malformed(f"constraints[{i}]: expected an object")
        gs.append(parse_poly(con, nv, f"constraints[{i}]"))
        lams.append(rat(multipliers[i], f"multipliers[{i}]"))

    basis = bundle.get("basis")
    if not isinstance(basis, list) or not basis:
        raise Malformed("basis: expected a nonempty list of monomials")
    mons = []
    for i, exps in enumerate(basis):
        if (not isinstance(exps, list) or len(exps) != nv
                or any(not isinstance(e, int) or e < 0 for e in exps)):
            raise Malformed(f"basis[{i}]: expected {nv} nonneg integers")
        mons.append(tuple(exps))

    s = len(mons)
    gram_rows = bundle.get("gram")
    if not isinstance(gram_rows, list) or len(gram_rows) != s:
        raise Malformed(f"gram: expected a {s}x{s} matrix")
    G = [rat_list(row, s, f"gram[{i}]") for i, row in enumerate(gram_rows)]

    # (1) Farkas multipliers must be nonnegative.
    for i, lam in enumerate(lams):
        if lam < 0:
            raise Reject("NEG_MULTIPLIER", f"multipliers[{i}] = {lam} < 0")
    log(f"CHECK multipliers-nonnegative: ok ({len(lams)} multiplier(s))")

    # (2) The exact polynomial identity: target - sum lambda_i g_i == m^T G m.
    lhs = dict(target)
    for lam, g in zip(lams, gs):
        for exps, coeff in g.items():
            poly_add(lhs, exps, -lam * coeff)
    rhs = {}
    for i in range(s):
        for j in range(s):
            if G[i][j] != 0:
                prod = tuple(a + b for a, b in zip(mons[i], mons[j]))
                poly_add(rhs, prod, G[i][j])
    if lhs != rhs:
        diff = dict(lhs)
        for exps, coeff in rhs.items():
            poly_add(diff, exps, -coeff)
        raise Reject("CLAIM_MISMATCH",
                     "Gram expansion does not equal the stated polynomial; "
                     f"difference = {poly_str(diff, variables)}")
    log("CHECK gram-identity: ok — target - sum(lambda*g) == m^T G m exactly")

    # (3) Symmetry, then exact PSD via LDL^T with the semidefinite pivot rule
    # (format doc section 4: sound AND complete for rational symmetric
    # matrices, including singular/boundary PSD).
    for i in range(s):
        for j in range(i + 1, s):
            if G[i][j] != G[j][i]:
                raise Reject("GRAM_NOT_SYMMETRIC",
                             f"G[{i}][{j}] = {G[i][j]} != G[{j}][{i}] = {G[j][i]}")
    log("CHECK gram-symmetric: ok")

    # Full-row elimination keeps the trailing (Schur) block symmetric by
    # itself; do NOT mirror-write entries back into earlier rows. The first
    # draft of this function did, clobbered the pivot row mid-update, and
    # passed the planted non-PSD bundle — the planted control caught it.
    A = [row[:] for row in G]
    pivots = []
    for i in range(s):
        if A[i][i] < 0:
            raise Reject("GRAM_NOT_PSD", f"negative diagonal pivot at step "
                         f"{i}: {A[i][i]}")
        if A[i][i] == 0:
            bad = next((j for j in range(i + 1, s) if A[i][j] != 0), None)
            if bad is not None:
                raise Reject("GRAM_NOT_PSD",
                             f"zero pivot at step {i} with nonzero "
                             f"off-diagonal A[{i}][{bad}] = {A[i][bad]} "
                             "(2x2 minor is negative)")
            pivots.append(Fraction(0))
            continue
        piv = A[i][i]
        pivots.append(piv)
        for r in range(i + 1, s):
            if A[r][i] != 0:
                f = A[r][i] / piv
                for c in range(i, s):
                    A[r][c] -= f * A[i][c]
    log("CHECK gram-psd: ok — LDL^T pivots "
        + ", ".join(str(p) for p in pivots))

    # (4) Optional binding of the stated target to the cited quartic slice —
    # after internal validation, so a mismatch verdict certifies "internally
    # valid SOS for the WRONG polynomial", the sharpest reading.
    slice_note = ("slice binding: NONE — the tie between this polynomial and "
                  "the 3HDM quartic rests on provenance prose only")
    sc = bundle.get("slice_check")
    if sc is not None:
        if not isinstance(sc, dict) or sc.get("slice") != "neutral-real-squares":
            raise Malformed("slice_check: only 'neutral-real-squares' exists in v1")
        if variables != ["z1", "z2", "z3"]:
            raise Malformed("slice_check: variables must be [z1, z2, z3]")
        cpl = parse_couplings(sc.get("couplings"), "slice_check.couplings")
        unit = cpl["cos_eps"] ** 2 + cpl["sin_eps"] ** 2
        if unit != 1:
            raise Reject("PHASE_NOT_UNIT", f"cos^2+sin^2 = {unit}, not 1")
        # V4 on Phi_k = (0, x_k), z_k = x_k^2 — derived from Eq. (11)+(13) in
        # the format doc section 4: squares a_k/2, crosses b_k+c_k+d_k (the
        # k=1 cross carrying cos(eps)).
        derived = {}
        sq = [(2, 0, 0), (0, 2, 0), (0, 0, 2)]
        cross = [(0, 1, 1), (1, 0, 1), (1, 1, 0)]  # z2z3, z3z1, z1z2
        for k in range(3):
            poly_add(derived, sq[k], cpl["a"][k] / 2)
            d_eff = cpl["d"][k] * (cpl["cos_eps"] if k == 0 else 1)
            poly_add(derived, cross[k],
                     cpl["b"][k] + cpl["c"][k] + d_eff)
        if derived != target:
            diff = dict(derived)
            for exps, coeff in target.items():
                poly_add(diff, exps, -coeff)
            raise Reject("CLAIM_MISMATCH",
                         "stated target is not V4 of the cited couplings on "
                         f"the neutral-real slice; difference = "
                         f"{poly_str(diff, variables)}")
        slice_note = None
        log("CHECK slice-binding: ok — target == V4|neutral-real-squares of "
            "the cited couplings (independently derived)")

    not_checked = [
        "that a certificate on the neutral-real slice implies full BFB "
        "(it does not; see claim.scope)",
    ]
    if slice_note:
        not_checked.append(slice_note)
    return not_checked


# --------------------------------------------------------------------------
# Driver.
# --------------------------------------------------------------------------

def verify(path, log):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            bundle = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        raise Malformed(f"cannot read bundle: {e}")
    if not isinstance(bundle, dict):
        raise Malformed("bundle is not a JSON object")
    if bundle.get("schema") != SCHEMA:
        raise Malformed(f"schema is {bundle.get('schema')!r}, expected {SCHEMA!r}")
    model = bundle.get("model", {})
    if not isinstance(model, dict) or model.get("name") != MODEL_NAME:
        raise Reject("UNSUPPORTED_MODEL",
                     f"model.name is {model.get('name')!r}; this checker "
                     f"embeds only {MODEL_NAME!r} and will not guess")
    species = bundle.get("species")
    log(f"bundle: {bundle.get('id', '<no id>')} ({species}) — {path}")
    if species == "counterexample":
        return check_counterexample(bundle, log)
    if species == "sos":
        return check_sos(bundle, log)
    raise Malformed(f"unknown species {species!r}")


def run_one(path):
    lines = []
    try:
        not_checked = verify(path, lines.append)
    except Malformed as e:
        for ln in lines:
            print(ln)
        print(f"VERDICT: REJECT {e.code} — {e.detail}")
        return 2, e.code
    except Reject as e:
        for ln in lines:
            print(ln)
        print(f"VERDICT: REJECT {e.code} — {e.detail}")
        return 1, e.code
    for ln in lines:
        print(ln)
    for item in not_checked:
        print(f"NOT CHECKED: {item}")
    print("VERDICT: PASS")
    return 0, None


# The pinned kit: file -> (expected verdict, expected reject code). The
# selftest is the kit's one-command replay AND its negative control: it fails
# if a planted-invalid bundle is accepted, per the house rule that a checker
# never seen rejecting anything is not a checker.
SELFTEST_EXPECT = {
    "counterexample-known-false.json": ("PASS", None),
    "sos-neutral-slice-demo.json": ("PASS", None),
    "farkas-neutral-slice-demo.json": ("PASS", None),
    "planted-wrong-arithmetic.json": ("REJECT", "WRONG_ARITHMETIC"),
    "planted-gram-not-psd.json": ("REJECT", "GRAM_NOT_PSD"),
    "planted-claim-mismatch.json": ("REJECT", "CLAIM_MISMATCH"),
}
PLANTED = {name for name, (v, _) in SELFTEST_EXPECT.items() if v == "REJECT"}


def selftest(kit_dir):
    import os.path
    failures = []
    planted_rejected = 0
    print(f"selftest kit: {kit_dir}")
    for name, (want_verdict, want_code) in sorted(SELFTEST_EXPECT.items()):
        path = os.path.join(kit_dir, name)
        print(f"\n--- {name} (expect {want_verdict}"
              + (f" {want_code}" if want_code else "") + ")")
        if not os.path.exists(path):
            failures.append(f"{name}: bundle missing from kit")
            print("MISSING")
            continue
        code, reject_code = run_one(path)
        got_verdict = "PASS" if code == 0 else "REJECT"
        if got_verdict != want_verdict or reject_code != want_code:
            failures.append(f"{name}: expected {want_verdict} {want_code}, "
                            f"got {got_verdict} {reject_code}")
        elif name in PLANTED:
            planted_rejected += 1
    print("\n=== selftest summary ===")
    for name in sorted(SELFTEST_EXPECT):
        status = "MISMATCH" if any(f.startswith(name + ":") for f in failures) \
            else "as pinned"
        print(f"  {name}: {status}")
    print(f"planted-invalid bundles rejected: {planted_rejected}/{len(PLANTED)}")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        print("SELFTEST: FAIL")
        return 1
    print("SELFTEST: PASS — all six outcomes match the pinned table")
    return 0


def main(argv):
    import os.path
    if len(argv) == 2 and argv[1] not in ("--selftest", "-h", "--help"):
        code, _ = run_one(argv[1])
        return code
    if len(argv) >= 2 and argv[1] == "--selftest":
        if len(argv) == 3:
            kit = argv[2]
        else:
            here = os.path.dirname(os.path.abspath(argv[0]))
            kit = os.path.normpath(os.path.join(
                here, "..", "research", "data", "referee-kits", "cert"))
        return selftest(kit)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
