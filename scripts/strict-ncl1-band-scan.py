#!/usr/bin/env python3
"""Independent exact confirmation of "strict NCL1 is not necessary for V4 >= 0".

Stdlib only (fractions, math, sys). This script is DELIBERATELY independent of
sinbad-fathom and of scripts/verify-certificate.py: V4 (paper Eq. 11) and NCL1
(paper Eq. 21, with b-bar Eq. 20 and e Eq. 22) are transcribed here from
arXiv:2603.23590 v3 directly. Agreement with the other transcriptions is a
differential check, not a tautology.

It certifies, over exact rationals:

  (A) at the headline R13 witness a=[1,1,1], b=[-1,0,0], c=d=0, eps=0:
        V4 >= 0 on a dense neutral grid AND on random full complex doublets,
        with the flat set {V4 = 0} located exactly (a whole RAY, not a point);
  (B) strict NCL1 (Eq. 21, all ">") is FALSE there (b-bar_1 = 0) while
        non-strict NCL1 (all ">=") HOLDS;
  (C) this is not a measure-zero fluke: a whole exact BAND of coupling points
        (the wall b-bar_1 = 0) has strict-NCL1-false ^ non-strict-NCL1-true ^
        V4 >= 0, and the two flanking controls show the wall is the genuine
        BFB boundary (b-bar_1 = +d: strict passes, BFB holds; b-bar_1 = -d:
        both fail AND V4 < 0 with an exact witness).

Exit 0 iff every assertion holds. Prints the measured band extent.
"""

import sys
from fractions import Fraction as F
from math import isqrt


# --------------------------------------------------------------------------
# Exact rational square root: returns F if x is the square of a rational,
# else None. (b-bar_k = b_k + sqrt(a_j a_l) is rational exactly when a_j a_l
# is a perfect rational square; the whole witness family is chosen so it is.)
# --------------------------------------------------------------------------
def exact_sqrt(x):
    if x < 0:
        return None
    n, d = x.numerator, x.denominator  # d > 0, gcd(n,d)=1
    rn, rd = isqrt(n), isqrt(d)
    if rn * rn == n and rd * rd == d:
        return F(rn, rd)
    return None


# --------------------------------------------------------------------------
# V4, paper Eq. (11), phase placement Eq. (13): eps1=eps, eps2=eps3=0.
# Doublets are 3 pairs of complex numbers, each complex as (re, im) rationals.
# Independent transcription (do not copy verify-certificate.py's structure).
# --------------------------------------------------------------------------
def cmul(u, v):
    return (u[0] * v[0] - u[1] * v[1], u[0] * v[1] + u[1] * v[0])


def cconj(u):
    return (u[0], -u[1])


def cabs2(u):
    return u[0] * u[0] + u[1] * u[1]


def inner(phi_j, phi_l):
    # Phi_j^dag Phi_l = sum_i conj(phi_j[i]) * phi_l[i]
    s = (F(0), F(0))
    for i in range(2):
        p = cmul(cconj(phi_j[i]), phi_l[i])
        s = (s[0] + p[0], s[1] + p[1])
    return s


def v4_general(cpl, phi):
    a, b, c, d = cpl["a"], cpl["b"], cpl["c"], cpl["d"]
    ce, se = cpl["cos_eps"], cpl["sin_eps"]
    n = [inner(phi[k], phi[k])[0] for k in range(3)]     # norms (real)
    K = [inner(phi[1], phi[2]), inner(phi[2], phi[0]), inner(phi[0], phi[1])]
    tot = F(0)
    for k in range(3):
        tot += a[k] * n[k] * n[k] / 2
    tot += b[0] * n[1] * n[2] + b[1] * n[2] * n[0] + b[2] * n[0] * n[1]
    for k in range(3):
        tot += c[k] * cabs2(K[k])
    for k in range(3):
        sq = cmul(K[k], K[k])
        re = (ce * sq[0] - se * sq[1]) if k == 0 else sq[0]
        tot += d[k] * re
    return tot


def v4_from_norms(cpl, n):
    # V4 as a function of the norms only -- valid whenever c=d=0 (Eq. 11c/11d
    # vanish). Used as the differential oracle against v4_general on c=d=0.
    a, b = cpl["a"], cpl["b"]
    return (a[0] * n[0] * n[0] / 2 + a[1] * n[1] * n[1] / 2
            + a[2] * n[2] * n[2] / 2
            + b[0] * n[1] * n[2] + b[1] * n[2] * n[0] + b[2] * n[0] * n[1])


# --------------------------------------------------------------------------
# NCL1, paper Eq. (21): a_k > 0, b-bar_k > 0, b-bar_k + e_k > 0.
# b-bar_1 = b1 + sqrt(a2 a3), b-bar_2 = b2 + sqrt(a3 a1), b-bar_3 = b3 + sqrt(a1 a2).
# e_k = c_k - |d_k|.  Returns (strict_ok, nonstrict_ok, b_bar list, e list).
# Requires the three a_j a_l products to be perfect rational squares (else the
# radical is irrational and this exact evaluator refuses rather than guesses).
# --------------------------------------------------------------------------
def ncl1(cpl):
    a, b, c, d = cpl["a"], cpl["b"], cpl["c"], cpl["d"]
    prods = [a[1] * a[2], a[2] * a[0], a[0] * a[1]]  # for k=1,2,3 (0-indexed)
    roots = []
    for pr in prods:
        r = exact_sqrt(pr)
        if r is None:
            raise ValueError(f"a_j a_l = {pr} is not a perfect rational square")
        roots.append(r)
    b_bar = [b[k] + roots[k] for k in range(3)]
    e = [c[k] - abs(d[k]) for k in range(3)]
    strict = (all(a[k] > 0 for k in range(3))
              and all(b_bar[k] > 0 and b_bar[k] + e[k] > 0 for k in range(3)))
    nonstrict = (all(a[k] >= 0 for k in range(3))
                 and all(b_bar[k] >= 0 and b_bar[k] + e[k] >= 0 for k in range(3)))
    return strict, nonstrict, b_bar, e


def neutral(x1, x2, x3):
    # neutral doublets Phi_k = (0, x_k); norms n_k = x_k^2.
    z = (F(0), F(0))
    return [[z, (x1, F(0))], [z, (x2, F(0))], [z, (x3, F(0))]]


def couplings(a, b, c=(0, 0, 0), d=(0, 0, 0), cos_eps=1, sin_eps=0):
    return {"a": [F(v) for v in a], "b": [F(v) for v in b],
            "c": [F(v) for v in c], "d": [F(v) for v in d],
            "cos_eps": F(cos_eps), "sin_eps": F(sin_eps)}


FAILS = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILS.append(msg)


# ==========================================================================
def main():
    print("=" * 72)
    print("(A) headline witness a=[1,1,1], b=[-1,0,0], c=d=0, eps=0")
    print("=" * 72)
    W = couplings([1, 1, 1], [-1, 0, 0])

    # V4 >= 0 on a dense exact neutral grid; locate the flat set {V4 = 0}.
    step = F(1, 4)
    vals = [step * i for i in range(0, 13)]  # 0, 1/4, ..., 3   (13 values)
    total, zeros, min_v = 0, 0, None
    neg = None
    diff_mismatch = 0
    for x1 in vals:
        for x2 in vals:
            for x3 in vals:
                phi = neutral(x1, x2, x3)
                v = v4_general(W, phi)
                # differential oracle: norm-only formula must agree (c=d=0).
                if v != v4_from_norms(W, [x1 * x1, x2 * x2, x3 * x3]):
                    diff_mismatch += 1
                total += 1
                if v < 0:
                    neg = (x1, x2, x3, v)
                if v == 0:
                    zeros += 1
                if min_v is None or v < min_v:
                    min_v = v
    check(neg is None, f"V4 >= 0 on all {total} neutral grid points "
          f"(min V4 = {min_v}, first negative = {neg})")
    check(diff_mismatch == 0,
          f"norm-only oracle agrees with full V4 on all grid points "
          f"({diff_mismatch} mismatches)")
    check(min_v == 0 and zeros > 0,
          f"the boundary is FLAT: {zeros} grid points hit V4 = 0 exactly "
          "(a ray n1=0, n2=n3, not an isolated point)")

    # Exact flat-ray witness = fathom's orthogonal ray: Phi2=(0,1), Phi3=(1,0).
    z = (F(0), F(0))
    ray = [[z, z], [z, (F(1), F(0))], [(F(1), F(0)), z]]
    check(v4_general(W, ray) == 0,
          f"orthogonal-ray witness Phi2=(0,1), Phi3=(1,0): V4 = "
          f"{v4_general(W, ray)} (exact)")

    # Random-ish full COMPLEX doublets: c=d=0 => V4 depends only on norms, so
    # V4 >= 0 must still hold even off the neutral slice (the "full BFB" bridge).
    rng = 1234567
    full_total, full_neg = 0, None
    for _ in range(4000):
        comps = []
        for _k in range(3):
            dbl = []
            for _i in range(2):
                rng = (1103515245 * rng + 12345) % (2 ** 31)
                re = F(rng % 21 - 10, (rng % 3) + 1)
                rng = (1103515245 * rng + 12345) % (2 ** 31)
                im = F(rng % 21 - 10, (rng % 5) + 1)
                dbl.append((re, im))
            comps.append(dbl)
        v = v4_general(W, comps)
        full_total += 1
        if v < 0:
            full_neg = v
            break
    check(full_neg is None,
          f"V4 >= 0 on {full_total} random full complex doublets "
          f"(charged + CP directions); first negative = {full_neg}")

    print()
    print("=" * 72)
    print("(B) strict vs non-strict NCL1 (Eq. 21) at the witness")
    print("=" * 72)
    strict, nonstrict, b_bar, e = ncl1(W)
    print(f"  b-bar = {[str(x) for x in b_bar]},  e = {[str(x) for x in e]}")
    check(b_bar[0] == 0, f"b-bar_1 = b1 + sqrt(a2 a3) = {b_bar[0]} (exactly 0)")
    check(strict is False, "strict NCL1 (Eq. 21, all '>') is FALSE")
    check(nonstrict is True, "non-strict NCL1 (all '>=') HOLDS")

    print()
    print("=" * 72)
    print("(C) the exact BAND: the flat wall b-bar_1 = 0, and its two controls")
    print("=" * 72)
    # Band = { a1=p^2, a2=m^2, a3=n^2, b1=-m*n, b2=b3=0, c=d=0 }.
    # Then b-bar_1 = -mn + mn = 0 (strict-fail row), b-bar_2 = n*p > 0,
    # b-bar_3 = p*m > 0. V4 = (p^2/2)n1^2 + (1/2)(m*n2 - n*n3)^2 >= 0.
    # p, m, n range over positive rationals => a genuine 3-parameter family.
    base_vals = [F(1), F(2), F(3), F(1, 2), F(3, 2), F(5, 2), F(1, 3), F(4, 3)]
    band_pts = 0
    band_bad = 0
    field_grid = [F(k, 2) for k in range(0, 7)]  # 0,1/2,...,3
    ex_p = ex_m = ex_n = None
    for p in base_vals:
        for m in base_vals:
            for nn in base_vals:
                cpl = couplings([p * p, m * m, nn * nn], [-(m * nn), 0, 0])
                st, ns, bb, _e = ncl1(cpl)
                # BFB on this point: min V4 over the field grid must be 0.
                mn_v = None
                for x1 in field_grid:
                    for x2 in field_grid:
                        for x3 in field_grid:
                            v = v4_from_norms(cpl, [x1 * x1, x2 * x2, x3 * x3])
                            if mn_v is None or v < mn_v:
                                mn_v = v
                ok = (bb[0] == 0 and st is False and ns is True and mn_v == 0)
                if ok:
                    band_pts += 1
                    ex_p, ex_m, ex_n = p, m, nn
                else:
                    band_bad += 1
    check(band_bad == 0,
          f"every one of {band_pts} exact wall points has "
          "b-bar_1=0 ^ strict-NCL1-false ^ non-strict-NCL1-true ^ V4>=0")
    print(f"  BAND EXTENT: {band_pts} distinct exact rational coupling points "
          f"on the codim-1 wall b-bar_1 = 0")
    print(f"               spanned by 3 free parameters (sqrt-a1, sqrt-a2, "
          f"sqrt-a3) over {len(base_vals)} rational values each")

    # --- Control 1 (interior): b-bar_1 = +delta  ->  strict passes, BFB holds.
    delta = F(1, 7)
    inp = couplings([1, 1, 1], [-1 + delta, 0, 0])
    st_i, ns_i, bb_i, _ = ncl1(inp)
    mn_i = None
    for x1 in field_grid:
        for x2 in field_grid:
            for x3 in field_grid:
                v = v4_from_norms(inp, [x1 * x1, x2 * x2, x3 * x3])
                if mn_i is None or v < mn_i:
                    mn_i = v
    check(bb_i[0] == delta and st_i is True and mn_i >= 0,
          f"interior control b-bar_1 = +{delta}: strict NCL1 PASSES, V4 >= 0 "
          f"(grid min = {mn_i})")

    # --- Control 2 (exterior): b-bar_1 = -delta  ->  both fail AND V4 < 0.
    outp = couplings([1, 1, 1], [-1 - delta, 0, 0])
    st_o, ns_o, bb_o, _ = ncl1(outp)
    # exact negative witness on the (formerly flat) ray n1=0, n2=n3=1:
    wit = v4_from_norms(outp, [F(0), F(1), F(1)])
    check(bb_o[0] == -delta and st_o is False and ns_o is False and wit < 0,
          f"exterior control b-bar_1 = -{delta}: strict AND non-strict NCL1 "
          f"FAIL, and V4 = {wit} < 0 on the ray n=(0,1,1) -> NOT BFB")
    print("  => the wall is the genuine BFB boundary: strict NCL1 is exactly")
    print("     right for V4 > 0; non-strict NCL1 is exactly right for V4 >= 0.")

    print()
    print("=" * 72)
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)} check(s) failed)")
        for m in FAILS:
            print(f"  - {m}")
        return 1
    print("RESULT: PASS -- all exact checks hold. strict NCL1 is not necessary")
    print("        for V4 >= 0; the phenomenon is a robust codim-1 boundary")
    print("        (a flat wall), certified exactly, with genuine flanking")
    print("        controls. This SHARPENS the paper's convention (V4 > 0 vs")
    print("        V4 >= 0); it is not an error in the paper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
