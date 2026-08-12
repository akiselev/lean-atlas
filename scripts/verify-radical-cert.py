#!/usr/bin/env python3
"""atlas-cert/1 radical checker — the ℚ(√a₀,√a₁,√a₂) companion to
scripts/verify-certificate.py.  See research/gpt/certificate-format.md §8.

WHY A SECOND CHECKER.  verify-certificate.py covers the two POLYNOMIAL species
of atlas-cert/1 (`counterexample`, `sos`): V₄ is a polynomial, and an SOS/Farkas
certificate is a rational Gram identity.  It cannot model the 3HDM condition
hierarchy, whose master inequality (paper Eq. jdp) carries the radicals

    Σ_k X_k √a_k + √(2 ∏_k (b̄_k + X_k))  >  −ā ,
    b̄_k = b_k + √(a_j a_l),   ā = √(a₀a₁a₂) + Σ_k b_k √a_k ,

i.e. sums of the square roots √a₀, √a₁, √a₂ (and one further square root per
inequality).  R12 (NCL2 ⟹ NCL3 on the spine) and the strict-NCL1 boundary are
statements ABOUT these radical atoms.  Until now their only exact instrument was
sinbad-fathom's own ℚ(√a) tower, so "the checker agrees with fathom" was not an
independent check — it was the same algorithm twice.  This file closes that gap:
it re-implements the ESSENCE of the tower (exact multiquadratic arithmetic plus
recursive conjugate-splitting sign determination) INDEPENDENTLY, from the
mathematics, in stdlib Python, so that agreement with fathom is evidence.

Stdlib only: json, sys, os.path, re, fractions.Fraction.  Auditable by eye.

Usage:
    verify-radical-cert.py BUNDLE.json          verdict on one bundle
    verify-radical-cert.py --selftest [DIR]     replay the pinned radical kit
    verify-radical-cert.py --fathom-crosscheck  compare the sign-decider against
                                                fathom's on-disk exact outputs

Exit codes: 0 = PASS (or selftest/crosscheck all-match), 1 = REJECT (or a
mismatch), 2 = malformed input / usage error.

INDEPENDENCE NOTE.  Every equation below is transcribed from the source paper

    D. Jurciukonis, L. Lavoura, A. Milagre, "Assessing boundedness from below in
    the Z2xZ2-symmetric three-Higgs-doublet model: algorithm and machine
    learning", arXiv:2603.23590 v3,

and the sign rule from its own soundness argument (documented in-line) — NOT
copied from crates/fathom/src/tower.rs.  The two share only the mathematics.
"""

import json
import math
import os.path
import re
import sys
from fractions import Fraction

SCHEMA = "atlas-cert/1"
MODEL_NAME = "Z2xZ2-3HDM-quartic-v4"


# ==========================================================================
# Verdicts.  REJECT carries a code; PASS carries none.  MALFORMED (exit 2)
# means the bundle could not be interpreted at all, so an operator can tell a
# broken file from a refuted certificate.
# ==========================================================================

class Reject(Exception):
    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Malformed(Reject):
    def __init__(self, detail):
        super().__init__("MALFORMED", detail)


# ==========================================================================
# Exact rationals.  Mathematical numbers are strings "n" or "n/d" (JSON ints
# accepted).  A JSON float in an exactness claim is a category error, rejected.
# ==========================================================================

def rat(x, where):
    if isinstance(x, bool):
        raise Malformed(f"{where}: boolean where a rational was expected")
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        raise Malformed(f"{where}: JSON float forbidden; use a string 'n/d'")
    if isinstance(x, str):
        try:
            return Fraction(x)
        except (ValueError, ZeroDivisionError):
            raise Malformed(f"{where}: unparseable rational {x!r}")
    raise Malformed(f"{where}: expected rational, got {type(x).__name__}")


def rat_list(xs, n, where):
    if not isinstance(xs, list) or len(xs) != n:
        raise Malformed(f"{where}: expected a list of {n} rationals")
    return [rat(x, f"{where}[{i}]") for i, x in enumerate(xs)]


# ==========================================================================
# The field ℚ(√a₀,√a₁,√a₂) — exact multiquadratic arithmetic.
#
# REPRESENTATION.  An element is 8 rationals `co[s]`, s = 0..7, where `co[s]`
# is the coefficient of the basis monomial ∏_{k : bit k of s} √a_k.  So the
# 8 basis elements, in index order, are
#
#     s=0 : 1              s=4 : √a₂
#     s=1 : √a₀            s=5 : √a₀√a₂ = √(a₀a₂)
#     s=2 : √a₁            s=6 : √a₁√a₂ = √(a₁a₂)
#     s=3 : √a₀√a₁ = √(a₀a₁)   s=7 : √a₀√a₁√a₂ = √(a₀a₁a₂)
#
# — the same eight monomials the format doc names, listed here in bitset order
# because that order makes the tower LEVELS nested prefixes: the first 2^L
# coefficients are exactly the subfield ℚ(√a₀,…,√a_{L-1}), so level recursion
# is slice splitting.
#
# The radicands a_k are GIVEN positive rationals.  √a_k·√a_k = a_k, so a basis
# product combines by XOR of the bitsets, each shared factor √a_k contributing
# a_k.
# ==========================================================================

def elem_zero():
    return [Fraction(0)] * 8


def elem_from_rat(q):
    e = elem_zero()
    e[0] = q
    return e


def _mul_level(rad, x, y, level):
    """Product of two elements of the level-th subfield, each a slice of length
    2^level.  (x0 + x1·√d)(y0 + y1·√d) = (x0·y0 + d·x1·y1) + (x0·y1 + x1·y0)√d,
    d = rad[level-1], recursing on the halves."""
    if level == 0:
        return [x[0] * y[0]]
    half = 1 << (level - 1)
    x0, x1 = x[:half], x[half:2 * half]
    y0, y1 = y[:half], y[half:2 * half]
    d = rad[level - 1]
    p00 = _mul_level(rad, x0, y0, level - 1)
    p11 = _mul_level(rad, x1, y1, level - 1)
    p01 = _mul_level(rad, x0, y1, level - 1)
    p10 = _mul_level(rad, x1, y0, level - 1)
    lo = [p00[i] + p11[i] * d for i in range(half)]
    hi = [p01[i] + p10[i] for i in range(half)]
    return lo + hi


def tower_mul(rad, x, y):
    """Product of two full elements of ℚ(√a₀,√a₁,√a₂)."""
    return _mul_level(rad, x, y, 3)


# --------------------------------------------------------------------------
# EXACT SIGN DETERMINATION — the crux.  This must be provably correct, not
# heuristic.  The rule, and its soundness, for a real x = u + v·√d with d > 0
# (√d the positive real root) and u, v real:
#
#   • v = 0            ⇒ sign(x) = sign(u).
#   • u = 0            ⇒ sign(x) = sign(v)          (√d > 0).
#   • sign(u)=sign(v)≠0 ⇒ sign(x) = sign(u)         (both terms pull one way).
#   • sign(u)=−sign(v)≠0 ⇒ sign(x) = sign(u)·sign(u² − v²d), BECAUSE
#         x·(u − v√d) = u² − v²d,
#     and the conjugate (u − v√d) has the sign of u: when u and v have opposite
#     signs, u and (−v√d) have the SAME sign, so their sum is sign(u).  Hence
#         sign(x) = sign(u² − v²d) / sign(u − v√d) = sign(u)·sign(u² − v²d).
#
# Applied with d = a_{level-1}, u and v are the two halves of the coefficient
# array — elements of the subfield ONE LEVEL DOWN — and u² − v²d also lives one
# level down, so the recursion terminates at ℚ (level 0), where the rational's
# sign is decided by Fraction comparison.
#
# SOUNDNESS UNDER DEGENERACY (the honest degenerate cases).  The argument uses
# ONLY the real value of the represented number; it never assumes the tower is a
# genuine degree-8 extension.  If some a_k is a perfect square, or a product
# a_j·a_l is (so the representation is redundant, e.g. √a₀√a₁ and √a₂ denote the
# same real when a₀a₁ = a₂), the computed sign is still the sign of the
# represented REAL number.  Concretely √2·√3 − √6 over radicands (2,3,6): the
# rule squares to (2·3) − 6 = 0 and reports sign 0, exactly.  And a perfect
# square collapses a level to a rational whose sign ℚ decides directly.  This is
# why the checker never needs to know whether the extension is proper — coupling
# points are arbitrary positive rationals and are FREQUENTLY degenerate.
#
# ZERO IS REPORTED HONESTLY.  sign returns 0 exactly when the represented real
# is 0 — which is what lets the STRICT hierarchy inequalities refuse a boundary
# point instead of guessing across it (paper's V₄ > 0 convention, footnote 1).
# --------------------------------------------------------------------------

def _sign_level(rad, x, level):
    """Sign (−1/0/+1) of the first 2^level coefficients read as an element of
    the level-th subfield (level 0 = ℚ)."""
    if level == 0:
        c = x[0]
        return 1 if c > 0 else (-1 if c < 0 else 0)
    half = 1 << (level - 1)
    u, v = x[:half], x[half:2 * half]
    su = _sign_level(rad, u, level - 1)
    sv = _sign_level(rad, v, level - 1)
    if sv == 0:
        return su
    if su == 0:
        return sv
    if su == sv:
        return su
    # Opposite nonzero signs: multiply by the conjugate and recurse on
    # u² − v²·d, which lives one level down.
    d = rad[level - 1]
    u2 = _mul_level(rad, u, u, level - 1)
    v2 = _mul_level(rad, v, v, level - 1)
    diff = [u2[i] - v2[i] * d for i in range(half)]
    return su * _sign_level(rad, diff, level - 1)


def tower_sign(rad, x):
    """Exact sign of the represented real number: −1, 0, or +1."""
    return _sign_level(rad, x, 3)


def plus_sqrt_sign(rad, q, r):
    """Exact sign of  q + √r  for tower elements q and r with r representing a
    NON-negative real (callers must establish r ≥ 0 first).  If q ≥ 0 the sum is
    positive unless both parts vanish; if q < 0 the comparison squares once:
    sign(q + √r) = sign(r − q²), because q + √r > 0 ⟺ √r > −q = |q| ⟺ r > q²,
    and the three cases r ≷ q² give the three signs."""
    sr = tower_sign(rad, r)
    if sr < 0:
        raise Malformed("internal: √ of a negative radicand requested")
    sq = tower_sign(rad, q)
    if sr == 0:
        return sq
    if sq >= 0:
        return 1
    q2 = tower_mul(rad, q, q)
    diff = [r[i] - q2[i] for i in range(8)]
    return tower_sign(rad, diff)


# ==========================================================================
# The 3HDM couplings and the exact condition hierarchy, transcribed from
# arXiv:2603.23590 v3.  Indices are 0-based (k ∈ {0,1,2}); the paper is 1-based.
# Phase placement Eq. (13): ε₁ = ε, ε₂ = ε₃ = 0, ε carried as (cos ε, sin ε).
# ==========================================================================

def pair(k):
    """The index pair (j,l) complementary to k: k=0→(1,2), 1→(2,0), 2→(0,1)."""
    return ((k + 1) % 3, (k + 2) % 3)


def parse_couplings(obj, where="couplings"):
    if not isinstance(obj, dict):
        raise Malformed(f"{where}: expected an object")
    out = {}
    for key in ("a", "b", "c", "d"):
        out[key] = rat_list(obj.get(key), 3, f"{where}.{key}")
    out["cos_eps"] = rat(obj.get("cos_eps"), f"{where}.cos_eps")
    out["sin_eps"] = rat(obj.get("sin_eps"), f"{where}.sin_eps")
    return out


def couplings_lit(a, b, c=(0, 0, 0), d=(0, 0, 0), cos_eps=1, sin_eps=0):
    """A couplings dict from literal values (for the fathom cross-check)."""
    F = Fraction
    return {"a": [F(v) for v in a], "b": [F(v) for v in b],
            "c": [F(v) for v in c], "d": [F(v) for v in d],
            "cos_eps": F(cos_eps), "sin_eps": F(sin_eps)}


def e_k(cpl, k):
    """e_k := c_k − |d_k|  (paper Eq. 22)."""
    return cpl["c"][k] - abs(cpl["d"][k])


def b_bar_elem(cpl, k):
    """b̄_k := b_k + √(a_j a_l) as a tower element  (paper Eq. 20).
    √(a_j a_l) = √a_j·√a_l is the basis monomial with bits j and l set."""
    j, l = pair(k)
    e = elem_from_rat(cpl["b"][k])
    e[(1 << j) | (1 << l)] += 1
    return e


def a_bar_elem(cpl):
    """ā := √(a₀a₁a₂) + Σ_k b_k √a_k  as a tower element  (below Eq. jdp)."""
    e = elem_zero()
    e[0b111] = Fraction(1)          # √(a₀a₁a₂)
    for k in range(3):
        e[1 << k] += cpl["b"][k]    # b_k √a_k
    return e


def jdp_eval(rad, cpl, x):
    """Evaluate the master inequality (Eq. jdp) at orbit point X exactly.

    Rearranged so the whole thing is one  q + √R > 0  test:
        Σ_k X_k √a_k + √(2 ∏(b̄_k+X_k)) > −ā
      ⟺ Σ_k (b_k+X_k)√a_k + √(a₀a₁a₂) + √(2 ∏(b̄_k+X_k)) > 0.
    So q = Σ_k (b_k+X_k)√a_k + √(a₀a₁a₂) and R = 2 ∏_k (b̄_k+X_k).

    A non-positive factor b̄_k + X_k is itself a copositivity failure (paper
    Eqs. ur4–ur6) at the same orbit point, so jdp is FALSE there and no square
    root of a negative is taken.  Returns a dict describing the evaluation."""
    factor_signs = []
    radicand = elem_from_rat(Fraction(2))
    factors_ok = True
    for k in range(3):
        j, l = pair(k)
        factor = elem_from_rat(cpl["b"][k] + x[k])   # (b_k + X_k) + √(a_j a_l)
        factor[(1 << j) | (1 << l)] += 1
        s = tower_sign(rad, factor)
        factor_signs.append(s)
        if s <= 0:
            factors_ok = False
        radicand = tower_mul(rad, radicand, factor)
    if not factors_ok:
        return {"holds": False, "factors_ok": False,
                "factor_signs": factor_signs, "margin_sign": None}
    q = elem_zero()
    q[0b111] = Fraction(1)                            # √(a₀a₁a₂)
    for k in range(3):
        q[1 << k] += cpl["b"][k] + x[k]               # (b_k + X_k) √a_k
    margin = plus_sqrt_sign(rad, q, radicand)
    return {"holds": margin > 0, "factors_ok": True,
            "factor_signs": factor_signs, "margin_sign": margin}


def jdp_holds(rad, cpl, x):
    return jdp_eval(rad, cpl, x)["holds"]


# --- The β-option X-vectors (paper Eqs. nc3 / Branc_nc3). ------------------

def ncl3_x_options(cpl, placement):
    """The seven Weinberg β-vectors for one phase placement (0-based: which
    index carries ε).  Slot s maps to coupling index (placement+s) mod 3;
    built in slot order, scattered to index order — exactly paper Eq. (nc3)."""
    idx = lambda s: (placement + s) % 3
    c = lambda s: cpl["c"][idx(s)]
    d = lambda s: cpl["d"][idx(s)]
    e = lambda s: cpl["c"][idx(s)] - abs(cpl["d"][idx(s)])
    dcos = d(0) * cpl["cos_eps"]
    dsin_abs = abs(d(0) * cpl["sin_eps"])
    slot_rows = [
        [c(0) + dcos,      c(1) + d(1), c(2) + d(2)],
        [c(0) + dcos,      c(1) - d(1), c(2) - d(2)],
        [c(0) - dcos,      c(1) - d(1), c(2) + d(2)],
        [c(0) - dcos,      c(1) + d(1), c(2) - d(2)],
        [c(0) - abs(dcos), c(1),        c(2)],
        [c(0) - dsin_abs,  c(1),        e(2)],
        [c(0) - dsin_abs,  e(1),        c(2)],
    ]
    out = []
    for row in slot_rows:
        x = [Fraction(0), Fraction(0), Fraction(0)]
        for s in range(3):
            x[idx(s)] = row[s]
        out.append(x)
    return out


def ncl2_corners(cpl):
    """P₀=(e₀,0,0), P₁=(0,e₁,0), P₂=(0,0,e₂)  (paper Eq. points)."""
    corners = []
    for k in range(3):
        x = [Fraction(0), Fraction(0), Fraction(0)]
        x[k] = e_k(cpl, k)
        corners.append(x)
    return corners


def a_all_positive(cpl):
    return all(cpl["a"][k] > 0 for k in range(3))


def _plus_sqrt_positive_rat(q, r):
    """Rational single-radical test  q + √r > 0  (r ≥ 0): q > 0, or r > q²."""
    if q > 0:
        return True
    return r > q * q


def exact_ncl1(cpl):
    """NCL1 (paper Eq. 21), strict: a_k>0, b̄_k>0, b̄_k+e_k>0.  Single radical
    per row (√(a_j a_l)), decided rationally — no tower needed."""
    if not a_all_positive(cpl):
        return False
    for k in range(3):
        j, l = pair(k)
        prod = cpl["a"][j] * cpl["a"][l]
        if not _plus_sqrt_positive_rat(cpl["b"][k], prod):
            return False
        if not _plus_sqrt_positive_rat(cpl["b"][k] + e_k(cpl, k), prod):
            return False
    return True


def exact_ncl2(cpl):
    if not a_all_positive(cpl):
        return False
    rad = cpl["a"]
    return all(jdp_holds(rad, cpl, x) for x in ncl2_corners(cpl))


def exact_ncl3(cpl):
    if not a_all_positive(cpl):
        return False
    rad = cpl["a"]
    for placement in range(3):
        for x in ncl3_x_options(cpl, placement):
            if not jdp_holds(rad, cpl, x):
                return False
    return True


# ==========================================================================
# Species: jdp-domination  (R12 — NCL2 ⟹ NCL3 on the spine).
#
# The certified statement, re-derived here from the tower and NOT from fathom:
# on the spine {ε=0, e_k ≥ 0 ∀k}, the single NCL2 corner P₀ = (e₀,0,0) is
# componentwise ≤ every NCL3 β-vector, and jdp is monotone in X, so jdp(P₀)
# alone forces jdp at all 21 β-vectors — i.e. NCL2 ⟹ NCL3.  The checker:
#   (i)   evaluates jdp exactly at the three NCL2 corners and all β-vectors;
#   (ii)  checks P_c ≤ every β-vector componentwise (the domination);
#   (iii) RE-DERIVES the implication: from jdp(P_c) it PREDICTS jdp(V) for every
#         dominated V by monotonicity, then confirms the prediction against the
#         DIRECT tower evaluation of jdp(V) — a disagreement is a REJECT, so the
#         monotonicity argument is checked, not assumed.
# It also cross-checks NCL2/NCL3 against the bundle's asserted verdicts.
# ==========================================================================

def check_jdp_domination(bundle, log):
    cpl = parse_couplings(bundle.get("couplings"))
    claim = bundle.get("claim")
    if not isinstance(claim, dict):
        raise Malformed("claim: expected an object")

    unit = cpl["cos_eps"] ** 2 + cpl["sin_eps"] ** 2
    if unit != 1:
        raise Reject("PHASE_NOT_UNIT", f"cos^2+sin^2 = {unit}, not 1")
    if not a_all_positive(cpl):
        raise Reject("A_NOT_POSITIVE", "the tower requires a_k > 0 for all k")
    log("CHECK phase-on-unit-circle, a_k>0: ok (exact)")

    rad = cpl["a"]
    c_idx = claim.get("dominating_corner", 0)
    if c_idx not in (0, 1, 2):
        raise Malformed("claim.dominating_corner must be 0, 1 or 2")
    spine = bool(claim.get("spine", False))
    es = [e_k(cpl, k) for k in range(3)]

    if spine:
        if not (cpl["cos_eps"] == 1 and cpl["sin_eps"] == 0):
            raise Reject("NOT_ON_SPINE", "spine requires eps = 0 "
                         "(cos_eps=1, sin_eps=0)")
        if any(es[k] < 0 for k in range(3)):
            raise Reject("NOT_ON_SPINE",
                         f"spine requires e_k = c_k-|d_k| >= 0; e = "
                         f"{[str(v) for v in es]}")
        log(f"CHECK spine: ok — eps=0 and e = {[str(v) for v in es]} (all >= 0)")

    # (i) jdp at the three NCL2 corners and the 21 β-vectors.
    corners = ncl2_corners(cpl)
    corner_holds = [jdp_eval(rad, cpl, x) for x in corners]
    ncl2 = all(h["holds"] for h in corner_holds)

    betas = []
    for placement in range(3):
        betas.extend(ncl3_x_options(cpl, placement))
    beta_holds = [jdp_eval(rad, cpl, v) for v in betas]
    ncl3 = all(h["holds"] for h in beta_holds)
    log(f"CHECK jdp evaluated exactly: NCL2(3 corners)={ncl2}, "
        f"NCL3(21 beta-vectors)={ncl3}")

    # (ii) domination: P_c <= every beta-vector, componentwise (exact).
    pc = corners[c_idx]
    dominated = [all(pc[k] <= v[k] for k in range(3)) for v in betas]
    dominates_all = all(dominated)
    log(f"CHECK domination: P{c_idx} = {[str(v) for v in pc]} <= all "
        f"{len(betas)} beta-vectors? {dominates_all}")

    if spine and not dominates_all:
        raise Reject("DOMINATION_BROKEN",
                     f"spine claim, but P{c_idx} does not dominate every "
                     "beta-vector (proof step ii fails)")
    if "dominates_all" in claim and bool(claim["dominates_all"]) != dominates_all:
        raise Reject("DOMINATION_BROKEN",
                     f"claim.dominates_all={claim['dominates_all']} but "
                     f"computed {dominates_all}")

    # (iii) monotonicity re-derivation.  If jdp(P_c) holds, then for every V
    # >= P_c the factors b̄_k+V_k >= b̄_k+(P_c)_k > 0 and the linear part is no
    # smaller, so jdp(V) MUST hold.  Confirm the prediction against the direct
    # evaluation; any disagreement means the inputs are internally inconsistent.
    pc_holds = corner_holds[c_idx]["holds"]
    if pc_holds:
        for v, dom, h in zip(betas, dominated, beta_holds):
            if dom and not h["holds"]:
                raise Reject("MONOTONICITY_BROKEN",
                             f"jdp(P{c_idx}) holds and P{c_idx} <= "
                             f"{[str(t) for t in v]}, so monotonicity predicts "
                             "jdp there, but direct evaluation says it FAILS")
        derived_ncl3 = dominates_all  # jdp(P_c) ⟹ jdp(V) for every V >= P_c
        if dominates_all:
            log(f"CHECK monotonicity: ok — jdp(P{c_idx}) holds and dominates "
                f"all beta-vectors, so jdp(P{c_idx}) alone RE-DERIVES NCL3 "
                "(21 -> 1 compression), matching direct evaluation")
    else:
        derived_ncl3 = None
        log(f"CHECK monotonicity: jdp(P{c_idx}) does NOT hold — the "
            "domination lemma does not apply from this corner (boundary case)")

    # Cross-check asserted verdicts.
    if "ncl2" in claim and bool(claim["ncl2"]) != ncl2:
        raise Reject("CLAIM_MISMATCH",
                     f"claim.ncl2={claim['ncl2']} but exact NCL2={ncl2}")
    if "ncl3" in claim and bool(claim["ncl3"]) != ncl3:
        raise Reject("CLAIM_MISMATCH",
                     f"claim.ncl3={claim['ncl3']} but exact NCL3={ncl3}")
    log(f"CHECK asserted verdicts: ok — NCL2={ncl2}, NCL3={ncl3}")

    # Implication summary.
    if ncl2 and ncl3 and spine and dominates_all and pc_holds:
        log(f"RESULT jdp-domination: on the spine, NCL2 => NCL3 witnessed "
            f"exactly — jdp(P{c_idx}) alone implies all 21 NCL3 inequalities")
    elif ncl2 and not ncl3:
        bad = next(i for i, h in enumerate(beta_holds) if not h["holds"])
        log(f"RESULT jdp-domination: NCL2 holds but NCL3 FAILS at beta-vector "
            f"{[str(t) for t in betas[bad]]} (jdp margin sign "
            f"{beta_holds[bad]['margin_sign']}) — the implication BREAKS here, "
            "so the spine hypothesis is load-bearing")

    not_checked = [
        "the GENERAL theorem (NCL2 => NCL3 for ALL spine couplings): this "
        "certificate re-derives the monotonicity/domination MECHANISM at the "
        "cited coupling point; the all-couplings proof is prose "
        "(research/gpt/3hdm/promotion-r12.md)",
        "the tie between jdp and physical BFB (that jdp encodes strict "
        "copositivity of the paper's matrix M) — that is the paper's Eq. (dop)",
    ]
    return not_checked


# ==========================================================================
# Species: radical-witness  (strict-NCL1 boundary, and radical sign claims).
#
# Verifies a claimed EXACT SIGN of a radical expression over ℚ(√a₀,√a₁,√a₂) at
# a rational coupling point.  Expression kinds:
#   coeffs      — a raw element given by its 8 bitset-basis coefficients;
#   b_bar       — b̄_k = b_k + √(a_j a_l) for cited couplings (paper Eq. 20);
#   a_bar       — ā = √(a₀a₁a₂) + Σ b_k √a_k;
#   jdp_margin  — the margin L(X)+ā = q + √R of the master inequality at X;
#                 its sign > 0 ⟺ jdp holds there (paper Eq. jdp).
# ==========================================================================

def _radicands_from(bundle):
    tw = bundle.get("tower")
    if not isinstance(tw, dict):
        raise Malformed("tower: expected {'radicands': [a0,a1,a2]}")
    rad = rat_list(tw.get("radicands"), 3, "tower.radicands")
    if any(r <= 0 for r in rad):
        raise Reject("A_NOT_POSITIVE",
                     f"tower radicands must be > 0; got {[str(r) for r in rad]}")
    return rad


def _expr_couplings(expr, rad):
    cpl = parse_couplings(expr.get("couplings"), "expr.couplings")
    unit = cpl["cos_eps"] ** 2 + cpl["sin_eps"] ** 2
    if unit != 1:
        raise Reject("PHASE_NOT_UNIT", f"cos^2+sin^2 = {unit}, not 1")
    if cpl["a"] != rad:
        raise Reject("CLAIM_MISMATCH",
                     "tower.radicands must equal expr.couplings.a "
                     f"({[str(r) for r in rad]} vs {[str(v) for v in cpl['a']]})")
    return cpl


def check_radical_witness(bundle, log):
    rad = _radicands_from(bundle)
    expr = bundle.get("expr")
    if not isinstance(expr, dict):
        raise Malformed("expr: expected an object with a 'kind'")
    claim = bundle.get("claim")
    if not isinstance(claim, dict) or claim.get("sign") not in (-1, 0, 1):
        raise Malformed("claim.sign: expected -1, 0 or 1")
    claimed = claim["sign"]
    kind = expr.get("kind")
    log(f"tower radicands a = {[str(r) for r in rad]}")

    if kind == "coeffs":
        elem = rat_list(expr.get("coeffs"), 8, "expr.coeffs")
        computed = tower_sign(rad, elem)
        desc = "raw element (8 bitset-basis coefficients)"
    elif kind == "b_bar":
        cpl = _expr_couplings(expr, rad)
        k = expr.get("k")
        if k not in (0, 1, 2):
            raise Malformed("expr.k must be 0, 1 or 2")
        elem = b_bar_elem(cpl, k)
        computed = tower_sign(rad, elem)
        desc = f"b_bar[{k}] = b[{k}] + sqrt(a_j a_l)"
    elif kind == "a_bar":
        cpl = _expr_couplings(expr, rad)
        elem = a_bar_elem(cpl)
        computed = tower_sign(rad, elem)
        desc = "a_bar = sqrt(a0 a1 a2) + sum b_k sqrt(a_k)"
    elif kind == "jdp_margin":
        cpl = _expr_couplings(expr, rad)
        x = rat_list(expr.get("x"), 3, "expr.x")
        ev = jdp_eval(rad, cpl, x)
        if not ev["factors_ok"]:
            raise Reject("FACTOR_NONPOSITIVE",
                         "a factor b_bar_k + X_k <= 0: the jdp radicand is not "
                         f"real here; factor signs {ev['factor_signs']}")
        computed = ev["margin_sign"]
        desc = f"jdp margin L(X)+a_bar at X = {[str(t) for t in x]}"
    else:
        raise Malformed(f"expr.kind: unknown kind {kind!r}")

    log(f"CHECK exact sign of {desc}: computed {computed:+d}, claimed {claimed:+d}")
    if computed != claimed:
        raise Reject("SIGN_MISMATCH",
                     f"exact sign is {computed:+d}, bundle claims {claimed:+d}")

    # Degeneracy note: report when the tower is redundant, so the referee sees
    # the checker did not silently assume a proper extension.
    def _is_square(fr):
        n, d = fr.numerator, fr.denominator
        return math.isqrt(n) ** 2 == n and math.isqrt(d) ** 2 == d

    degen = []
    for k in range(3):
        if _is_square(rad[k]):
            degen.append(f"a{k}={rad[k]} is a perfect square")
    for (j, l), nm in (((0, 1), "a0*a1"), ((0, 2), "a0*a2"), ((1, 2), "a1*a2")):
        pr = rad[j] * rad[l]
        if _is_square(pr):
            degen.append(f"{nm}={pr} is a perfect square (a level collapses)")
    if degen:
        log("NOTE degenerate tower handled exactly: " + "; ".join(degen))

    not_checked = [
        "any statement beyond the sign of this one expression at this one "
        "rational point",
    ]
    return not_checked


# ==========================================================================
# Driver.
# ==========================================================================

SPECIES = {
    "jdp-domination": check_jdp_domination,
    "radical-witness": check_radical_witness,
}


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
                     f"model.name is {model.get('name')!r}; this checker embeds "
                     f"only {MODEL_NAME!r} and will not guess")
    species = bundle.get("species")
    log(f"bundle: {bundle.get('id', '<no id>')} ({species}) — {path}")
    handler = SPECIES.get(species)
    if handler is None:
        raise Malformed(f"unknown/unsupported radical species {species!r} "
                        f"(this checker handles {sorted(SPECIES)})")
    return handler(bundle, log)


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


# ==========================================================================
# The pinned radical kit: file -> (expected verdict, expected reject code).
# The selftest is the one-command replay AND the negative control: it fails if
# any planted-invalid is accepted or any worked bundle is rejected.
# ==========================================================================

SELFTEST_EXPECT = {
    # Worked (must PASS):
    "r12-spine-domination.json": ("PASS", None),
    "r12-boundary-tight.json": ("PASS", None),
    "strict-ncl1-bbar-zero.json": ("PASS", None),
    "radical-degenerate-collapse.json": ("PASS", None),
    # Planted-invalid (must REJECT with the pinned code):
    "planted-radical-sign-flip.json": ("REJECT", "SIGN_MISMATCH"),
    "planted-radical-wrong-coeff.json": ("REJECT", "SIGN_MISMATCH"),
    "planted-degenerate-collapse.json": ("REJECT", "SIGN_MISMATCH"),
    "planted-beta-not-dominated.json": ("REJECT", "DOMINATION_BROKEN"),
    "planted-r12-wrong-verdict.json": ("REJECT", "CLAIM_MISMATCH"),
}
PLANTED = {name for name, (v, _) in SELFTEST_EXPECT.items() if v == "REJECT"}


def selftest(kit_dir):
    failures = []
    planted_rejected = 0
    print(f"selftest radical kit: {kit_dir}")
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
    print("\n=== radical selftest summary ===")
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
    print(f"SELFTEST: PASS — all {len(SELFTEST_EXPECT)} outcomes match the "
          "pinned table")
    return 0


# ==========================================================================
# Fathom cross-check.  The house rule: agreement between an independent checker
# and the engine is evidence only if the two are independent.  This reads
# fathom's EXACT outputs ALREADY ON DISK (research/data/f0-tier1-results.json,
# and the R12 §3 witness verdicts recorded in promotion-r12.md) and confirms our
# independent sign-decider reproduces each one.  We do NOT run fathom.
# ==========================================================================

def _parse_construction(s):
    """Extract a,b,c,d (eps assumed 0 for these ε=0 boundary witnesses) from a
    free-form 'construction' string like
        'a=[1,1,1],b=[-1,1,1],c=[1/2,0,0],d=[1/2,0,0],eps=0; ...'
    handling the 'c=d=0' shorthand.  Returns a couplings dict or None."""
    def arr(name):
        m = re.search(name + r"=\[([^\]]*)\]", s)
        if not m:
            return None
        return [Fraction(t.strip()) for t in m.group(1).split(",")]
    a = arr("a")
    b = arr("b")
    c = arr("c")
    d = arr("d")
    if "c=d=0" in s.replace(" ", ""):
        c = [Fraction(0)] * 3
        d = [Fraction(0)] * 3
    if a is None or b is None:
        return None
    if c is None:
        c = [Fraction(0)] * 3
    if d is None:
        d = [Fraction(0)] * 3
    return couplings_lit([str(v) for v in a], [str(v) for v in b],
                         [str(v) for v in c], [str(v) for v in d])


def fathom_crosscheck():
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    root = os.path.normpath(os.path.join(here, ".."))
    results_path = os.path.join(root, "research", "data",
                                "f0-tier1-results.json")
    print("fathom cross-check — our independent tower vs fathom's on-disk "
          "exact outputs")
    print(f"  source: {results_path}")

    comparisons = []   # (label, ours, fathom, agree)

    try:
        with open(results_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  CANNOT READ f0-tier1-results.json: {e}")
        return 2
    by_id = {c["id"]: c for c in data.get("candidates", []) if "id" in c}

    # --- Named boundary witnesses with fathom's exact fields recorded. ---
    for cid in ("R2", "R6", "R13", "R14", "T4"):
        cand = by_id.get(cid)
        if cand is None:
            print(f"  [{cid}] not found in results — skipped")
            continue
        cpl = _parse_construction(cand.get("construction", ""))
        if cpl is None:
            print(f"  [{cid}] construction unparseable — skipped")
            continue
        # b̄₁ (paper 1-based) = our b_bar(0): compare its exact sign to fathom's
        # recorded value, when present.
        if "bbar1_exact" in cand:
            fv = Fraction(cand["bbar1_exact"])
            ours = tower_sign(cpl["a"], b_bar_elem(cpl, 0))
            fs = (1 if fv > 0 else (-1 if fv < 0 else 0))
            comparisons.append((f"{cid}: sign(b_bar_1)", ours, fs, ours == fs))
        # strict / non-strict NCL1.
        if "strict_ncl1" in cand:
            ours = exact_ncl1(cpl)
            comparisons.append((f"{cid}: strict NCL1", ours,
                                bool(cand["strict_ncl1"]),
                                ours == bool(cand["strict_ncl1"])))
        if "exact_ncl1" in cand:
            ours = exact_ncl1(cpl)
            comparisons.append((f"{cid}: exact NCL1", ours,
                                bool(cand["exact_ncl1"]),
                                ours == bool(cand["exact_ncl1"])))
        if "exact_ncl2_boundary_false" in cand:
            # fathom records NCL2 is false (a boundary equality) => our NCL2
            # must be false.
            ours_false = (exact_ncl2(cpl) is False)
            comparisons.append((f"{cid}: NCL2 is boundary-false", ours_false,
                                bool(cand["exact_ncl2_boundary_false"]),
                                ours_false == bool(cand["exact_ncl2_boundary_false"])))
        # Boto's ḡ₁ = g₁ + √(a₂a₀), g₁ = b₁+min(0,c₁)-|d₁| (a tower element):
        # compare its exact sign to fathom's recorded value.
        if "gbar1_exact" in cand:
            g0 = cpl["b"][0] + min(Fraction(0), cpl["c"][0]) - abs(cpl["d"][0])
            gbar0 = elem_from_rat(g0)
            j, l = pair(0)
            gbar0[(1 << j) | (1 << l)] += 1     # + √(a_j a_l)
            ours = tower_sign(cpl["a"], gbar0)
            fv = Fraction(cand["gbar1_exact"])
            fs = (1 if fv > 0 else (-1 if fv < 0 else 0))
            comparisons.append((f"{cid}: sign(g_bar_1)", ours, fs, ours == fs))

    # --- The R12 §3 witness, verdicts recorded in promotion-r12.md §4. ---
    #     (Independent transcription of the couplings; fathom verdicts are the
    #     on-disk reference.)  a=[1,1,1],b=[0,0,0],c=[1,-9/10,-9/10],d=[1,0,0].
    r12 = couplings_lit([1, 1, 1], [0, 0, 0],
                        ["1", "-9/10", "-9/10"], [1, 0, 0])
    r12_path = os.path.join(root, "research", "gpt", "3hdm", "promotion-r12.md")
    r12_fathom = {"ncl1": None, "ncl2": None, "ncl3": None}
    try:
        with open(r12_path, "r", encoding="utf-8") as fh:
            md = fh.read()
        for key in ("ncl1", "ncl2", "ncl3"):
            m = re.search(key + r"\s*=\s*(true|false)", md)
            if m:
                r12_fathom[key] = (m.group(1) == "true")
    except OSError:
        pass
    ours_r12 = {"ncl1": exact_ncl1(r12), "ncl2": exact_ncl2(r12),
                "ncl3": exact_ncl3(r12)}
    for key in ("ncl1", "ncl2", "ncl3"):
        fv = r12_fathom[key]
        if fv is None:
            print(f"  [R12 §3 witness] fathom {key} not found in doc — skipped")
            continue
        comparisons.append((f"R12 §3 witness: {key}", ours_r12[key], fv,
                            ours_r12[key] == fv))

    print()
    agree = 0
    for label, ours, fv, ok in comparisons:
        print(f"  {'AGREE ' if ok else 'DIFFER'}  {label}: "
              f"ours={ours}  fathom={fv}")
        if ok:
            agree += 1
    total = len(comparisons)
    print(f"\n  agreement: {agree}/{total}")
    if total == 0:
        print("  CROSS-CHECK: NO COMPARISONS (inputs missing) — FAIL")
        return 2
    if agree == total:
        print("  CROSS-CHECK: PASS — independent tower reproduces every fathom "
              "exact output on disk")
        return 0
    print("  CROSS-CHECK: FAIL — a disagreement is a finding; investigate")
    return 1


def main(argv):
    if len(argv) >= 2 and argv[1] == "--fathom-crosscheck":
        return fathom_crosscheck()
    if len(argv) >= 2 and argv[1] == "--selftest":
        if len(argv) == 3:
            kit = argv[2]
        else:
            here = os.path.dirname(os.path.abspath(argv[0]))
            kit = os.path.normpath(os.path.join(
                here, "..", "research", "data", "referee-kits", "cert"))
        return selftest(kit)
    if len(argv) == 2 and argv[1] not in ("-h", "--help"):
        code, _ = run_one(argv[1])
        return code
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
