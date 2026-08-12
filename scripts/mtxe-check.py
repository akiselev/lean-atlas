#!/usr/bin/env python3
"""Independent checker for the KIT 3 GAP/QDistRnd differential bundle.

One file, stdlib only. This is the *second* implementation of everything the
sextant example asserts — written from the mathematics, not from the Rust — so
that agreement between them is a differential check, and a shared bug cannot
make both pass. It is also the bundle's negative control: it must REJECT the
planted-invalid corrupted matrix (a stabilizer generator set that is not
self-orthogonal), and it aborts if that control fails to fire.

It requires nothing of the lean-atlas/sinbad stack: it reads the shipped
files and recomputes.

What it checks:
  1. manifest.json — for every (p, m, n) case, recompute the Lagrangian count
     prod_{i=1..n}(q^i+1), the isotropic counts, and the label-Frobenius orbit
     count (1/m) sum_{d|m} phi(m/d) prod_{i}(p^{d i}+1) from (p, m, n) alone,
     and compare to the stated values.
  2. lagrangians/*.mtxe — parse each as a matrix over GF(p) (prime-field MTXE),
     confirm it is n x 2n of full row rank n, and confirm total isotropy under
     the declared symplectic form J = [[0, I_n], [-I_n, 0]] (M J M^T == 0), i.e.
     the rows are commuting stabilizer generators. Count must match manifest.
  3. corrupted/*.mtxe — confirm it PARSES as a valid MTXE matrix but is NOT
     isotropic: a planted-invalid the referee's tool must flag. If it were
     isotropic the control could not fire, and this script exits non-zero.
  4. orbits/*.json — rebuild the finite field from the shipped frozen modulus
     and independently replay the vector-set label-Frobenius partition (line
     case), confirming the orbit count, the orbit sizes, that σ maps each
     subspace to a same-orbit subspace, and that the singleton (fixed) orbits
     are exactly the subfield-defined Lagrangians.

Usage:
    mtxe-check.py [BUNDLE_DIR]     (default: research/data/referee-kits/gap)
Exit: 0 all checks pass; 1 a check failed; 2 malformed bundle / usage.
"""

import json
import os
import sys
from math import gcd


class Fail(Exception):
    pass


class Malformed(Exception):
    pass


# --------------------------------------------------------------------------
# Closed-form counts, recomputed independently of sextant.
# --------------------------------------------------------------------------

def lagrangian_count(q, n):
    acc = 1
    for i in range(1, n + 1):
        acc *= q**i + 1
    return acc


def isotropic_count(q, n, k):
    if k == 0:
        return 1
    if k > n:
        return 0
    num = den = 1
    for i in range(1, k + 1):
        num *= q ** (2 * n - i + 1) - q ** (i - 1)
        den *= q**k - q ** (i - 1)
    assert num % den == 0
    return num // den


def euler_phi(x):
    return sum(1 for i in range(1, x + 1) if gcd(i, x) == 1)


def orbit_count(p, m, n):
    total = 0
    for d in range(1, m + 1):
        if m % d:
            continue
        total += euler_phi(m // d) * lagrangian_count(p**d, n)
    assert total % m == 0
    return total // m


# --------------------------------------------------------------------------
# A minimal exact GF(p^m) from a low-to-high monic modulus, elements indexed by
# polynomial-basis digits in base p (sextant's convention). Only needed for the
# orbit replay; kept tiny.
# --------------------------------------------------------------------------

class GF:
    def __init__(self, p, m, modulus_low_to_high):
        self.p = p
        self.m = m
        self.q = p**m
        self.mod = modulus_low_to_high  # coeffs c_0..c_m, monic degree m

    def digits(self, e):
        d = []
        for _ in range(self.m):
            d.append(e % self.p)
            e //= self.p
        return d

    def index(self, digs):
        x = 0
        for c in reversed(digs[: self.m]):
            x = x * self.p + (c % self.p)
        return x

    def add(self, a, b):
        da, db = self.digits(a), self.digits(b)
        return self.index([(x + y) % self.p for x, y in zip(da, db)])

    def mul(self, a, b):
        da, db = self.digits(a), self.digits(b)
        prod = [0] * (2 * self.m)
        for i in range(self.m):
            for j in range(self.m):
                prod[i + j] = (prod[i + j] + da[i] * db[j]) % self.p
        # reduce by the monic modulus (leading coeff at index m is 1)
        for deg in range(2 * self.m - 1, self.m - 1, -1):
            lead = prod[deg]
            if lead == 0:
                continue
            prod[deg] = 0
            for i in range(self.m):
                prod[deg - self.m + i] = (
                    prod[deg - self.m + i] - lead * self.mod[i]
                ) % self.p
        return self.index(prod[: self.m])

    def inv(self, a):
        if a == 0:
            raise Malformed("inverse of zero")
        for b in range(1, self.q):
            if self.mul(a, b) == 1:
                return b
        raise Malformed("no inverse: modulus not irreducible?")

    def frob(self, a):  # x -> x^p
        acc = 1
        for _ in range(self.p):
            acc = self.mul(acc, a)
        return acc

    def in_prime_subfield(self, a):
        return a < self.p


# --------------------------------------------------------------------------
# MTXE parsing (QDistRnd extended MatrixMarket, prime-field variant).
# --------------------------------------------------------------------------

def parse_mtxe_prime(path):
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines or not lines[0].startswith("%%MatrixMarket matrix coordinate"):
        raise Malformed(f"{path}: missing MatrixMarket banner")
    p = None
    body = []
    for ln in lines[1:]:
        if ln.startswith("%"):
            s = ln.lstrip("%").strip()
            if s.startswith("Field:"):
                spec = s[len("Field:"):].strip()
                # prime-field only in this bundle: "GF(p)" with p prime
                if spec.startswith("GF(") and spec.endswith(")") and "^" not in spec:
                    p = int(spec[3:-1])
            continue
        if ln.strip() == "":
            continue
        body.append(ln.strip())
    if p is None:
        raise Malformed(f"{path}: no prime-field 'Field: GF(p)' header")
    if not body:
        raise Malformed(f"{path}: no dimension line")
    dims = body[0].split()
    if len(dims) != 3:
        raise Malformed(f"{path}: dimension line is not 'rows cols entries'")
    rows, cols, nnz = (int(x) for x in dims)
    mat = [[0] * cols for _ in range(rows)]
    triples = body[1:]
    if len(triples) != nnz:
        raise Malformed(f"{path}: declared {nnz} entries, found {len(triples)}")
    for t in triples:
        parts = t.split()
        if len(parts) != 3:
            raise Malformed(f"{path}: bad triple {t!r}")
        r, c, v = (int(x) for x in parts)  # 1-indexed
        if not (1 <= r <= rows and 1 <= c <= cols):
            raise Malformed(f"{path}: triple out of range {t!r}")
        if not (0 <= v < p):
            raise Malformed(f"{path}: value {v} not in GF({p})")
        mat[r - 1][c - 1] = v
    return p, rows, cols, mat


def symplectic_gram_is_zero(p, mat, cols):
    """M J M^T == 0 over GF(p), J=[[0,I_n],[-I_n,0]], coords (x_1..x_n,y_1..y_n)."""
    if cols % 2:
        raise Malformed("odd ambient dimension")
    n = cols // 2
    for u in mat:
        for v in mat:
            acc = 0
            for i in range(n):
                acc = (acc + u[i] * v[n + i] - u[n + i] * v[i]) % p
            if acc % p != 0:
                return False
    return True


def row_rank_mod_p(mat, p):
    rows = [row[:] for row in mat]
    r = 0
    ncols = len(rows[0]) if rows else 0
    for col in range(ncols):
        piv = next((i for i in range(r, len(rows)) if rows[i][col] % p != 0), None)
        if piv is None:
            continue
        rows[r], rows[piv] = rows[piv], rows[r]
        inv = pow(rows[r][col], p - 2, p)  # p prime => Fermat inverse
        rows[r] = [(x * inv) % p for x in rows[r]]
        for i in range(len(rows)):
            if i != r and rows[i][col] % p != 0:
                f = rows[i][col]
                rows[i] = [(a - f * b) % p for a, b in zip(rows[i], rows[r])]
        r += 1
        if r == len(rows):
            break
    return r


# --------------------------------------------------------------------------
# Checks.
# --------------------------------------------------------------------------

def check_manifest(bundle):
    path = os.path.join(bundle, "manifest.json")
    with open(path, "r", encoding="utf-8") as fh:
        man = json.load(fh)
    if man.get("schema") != "atlas-gap-differential/1":
        raise Malformed("manifest: unexpected schema")
    n_cases = 0
    for case in man["cases"]:
        p, m, n, q = case["p"], case["m"], case["n"], int(case["q"])
        if p**m != q:
            raise Fail(f"({p},{m},{n}): q={q} != p^m={p**m}")
        want_l = int(case["lagrangian_count"])
        got_l = lagrangian_count(q, n)
        if want_l != got_l:
            raise Fail(f"({p},{m},{n}): Lagrangian count manifest {want_l} != recomputed {got_l}")
        iso = [int(x) for x in case["isotropic_count_k1_to_n"]]
        for k in range(1, n + 1):
            r = isotropic_count(q, n, k)
            if iso[k - 1] != r:
                raise Fail(f"({p},{m},{n}): isotropic_count[k={k}] {iso[k-1]} != {r}")
        want_o = int(case["orbit_count"])
        got_o = orbit_count(p, m, n)
        if want_o != got_o:
            raise Fail(f"({p},{m},{n}): orbit count manifest {want_o} != recomputed {got_o}")
        # orbit-size distribution (where present) must sum consistently.
        if "orbit_size_distribution" in case:
            dist = case["orbit_size_distribution"]
            total_orbits = sum(int(d["count"]) for d in dist)
            total_members = sum(int(d["size"]) * int(d["count"]) for d in dist)
            if total_orbits != want_o:
                raise Fail(f"({p},{m},{n}): size dist has {total_orbits} orbits != {want_o}")
            if total_members != want_l:
                raise Fail(f"({p},{m},{n}): size dist covers {total_members} != {want_l} Lagrangians")
            for d in dist:
                if m % int(d["size"]) != 0:
                    raise Fail(f"({p},{m},{n}): orbit size {d['size']} does not divide m={m}")
        n_cases += 1
    print(f"  manifest: {n_cases} cases, all counts recomputed and matched")
    return man


def check_matrices(bundle, man):
    ldir = os.path.join(bundle, "lagrangians")
    files = sorted(f for f in os.listdir(ldir) if f.endswith(".mtxe"))
    if not files:
        raise Malformed("no lagrangians/*.mtxe files")
    checked = 0
    p_seen = cols_seen = None
    for f in files:
        p, rows, cols, mat = parse_mtxe_prime(os.path.join(ldir, f))
        p_seen, cols_seen = p, cols
        n = cols // 2
        if rows != n:
            raise Fail(f"{f}: {rows} rows, expected n={n} (Lagrangian)")
        if row_rank_mod_p(mat, p) != n:
            raise Fail(f"{f}: row rank != {n}; not a Lagrangian basis")
        if not symplectic_gram_is_zero(p, mat, cols):
            raise Fail(f"{f}: rows are NOT mutually isotropic (should be)")
        checked += 1
    # count must match the manifest's (p, m=1, n) case for this prime field
    n = cols_seen // 2
    case = next(
        (c for c in man["cases"] if c["p"] == p_seen and c["m"] == 1 and c["n"] == n),
        None,
    )
    if case is None:
        raise Fail(f"no manifest case for the exported MTXE field GF({p_seen}), n={n}")
    if checked != int(case["lagrangian_count"]):
        raise Fail(f"exported {checked} Lagrangians, manifest says {case['lagrangian_count']}")
    print(f"  lagrangians: {checked} MTXE matrices, all n x 2n, full-rank, isotropic")


def check_corrupted(bundle):
    cdir = os.path.join(bundle, "corrupted")
    files = sorted(f for f in os.listdir(cdir) if f.endswith(".mtxe"))
    if not files:
        raise Malformed("no corrupted/*.mtxe files (the planted control is missing)")
    fired = 0
    for f in files:
        p, rows, cols, mat = parse_mtxe_prime(os.path.join(cdir, f))
        # It must parse (well-formed MTXE) but fail isotropy.
        if symplectic_gram_is_zero(p, mat, cols):
            raise Fail(f"{f}: planted-invalid is isotropic — the control did NOT fire")
        fired += 1
    print(f"  corrupted: {fired} planted-invalid matrix(es), all correctly non-isotropic (flagged)")


def canon_line(gf, v):
    """RREF canonical form of the line spanned by a 2-vector v over gf."""
    a, b = v
    if a != 0:
        inv = gf.inv(a)
        return (1, gf.mul(inv, b))
    if b != 0:
        return (0, 1)
    raise Malformed("zero vector is not a line")


def check_orbits(bundle):
    odir = os.path.join(bundle, "orbits")
    if not os.path.isdir(odir):
        print("  orbits: none shipped")
        return
    files = sorted(f for f in os.listdir(odir) if f.endswith(".json"))
    for f in files:
        with open(os.path.join(odir, f), "r", encoding="utf-8") as fh:
            rec = json.load(fh)
        p, m, n = rec["p"], rec["m"], rec["n"]
        if n != 1:
            print(f"  orbits/{f}: n={n} replay not implemented (only line case checked)")
            continue
        gf = GF(p, m, [int(c) for c in rec["frozen_modulus_low_to_high"]])
        if gf.q != int(rec["q"]):
            raise Fail(f"{f}: field q mismatch")
        subs = rec["subspaces"]
        orbits = rec["orbits"]
        if len(subs) != lagrangian_count(gf.q, 1):
            raise Fail(f"{f}: {len(subs)} lines != {lagrangian_count(gf.q,1)}")
        if len(orbits) != orbit_count(p, m, n):
            raise Fail(f"{f}: {len(orbits)} orbits != {orbit_count(p,m,n)}")
        # map canonical line -> its declared subspace index and orbit
        by_canon = {}
        orbit_of = {}
        for s in subs:
            v = tuple(int(x) for x in s["basis"][0])
            by_canon[canon_line(gf, v)] = s["index"]
            orbit_of[s["index"]] = s["orbit"]
        # 1) applying Frobenius to each line lands on a line in the same orbit
        for s in subs:
            v = tuple(int(x) for x in s["basis"][0])
            img = (gf.frob(v[0]), gf.frob(v[1]))
            img_idx = by_canon.get(canon_line(gf, img))
            if img_idx is None:
                raise Fail(f"{f}: Frobenius image of line {s['index']} not among the lines")
            if orbit_of[img_idx] != s["orbit"]:
                raise Fail(f"{f}: Frobenius moved line {s['index']} out of its orbit")
        # 2) singleton (fixed) orbits are exactly the subfield-defined lines
        fixed_by_frob = set()
        for s in subs:
            v = tuple(int(x) for x in s["basis"][0])
            img = (gf.frob(v[0]), gf.frob(v[1]))
            if canon_line(gf, img) == canon_line(gf, v):
                fixed_by_frob.add(s["index"])
        singletons = {o["members"][0] for o in orbits if int(o["size"]) == 1}
        if fixed_by_frob != singletons:
            raise Fail(f"{f}: fixed lines {fixed_by_frob} != singleton orbits {singletons}")
        # subfield check: a line [1,t] is fixed iff t in F_p (plus [0,1])
        subfield_lines = set()
        for s in subs:
            v = tuple(int(x) for x in s["basis"][0])
            c = canon_line(gf, v)
            if c == (0, 1) or gf.in_prime_subfield(c[1]):
                subfield_lines.add(s["index"])
        if subfield_lines != singletons:
            raise Fail(f"{f}: subfield lines {subfield_lines} != singleton orbits {singletons}")
        # orbit sizes must divide m and sum to the Lagrangian count
        if sum(int(o["size"]) for o in orbits) != len(subs):
            raise Fail(f"{f}: orbit sizes do not cover every line")
        for o in orbits:
            if m % int(o["size"]) != 0:
                raise Fail(f"{f}: orbit size {o['size']} does not divide m={m}")
        print(
            f"  orbits/{f}: {len(subs)} lines -> {len(orbits)} Frobenius orbits, "
            "replayed independently; singletons == subfield lines"
        )


def main(argv):
    here = os.path.dirname(os.path.abspath(argv[0]))
    default = os.path.normpath(os.path.join(here, "..", "research", "data", "referee-kits", "gap"))
    bundle = argv[1] if len(argv) >= 2 else default
    if not os.path.isdir(bundle):
        print(f"bundle dir not found: {bundle}")
        return 2
    print(f"mtxe-check: {bundle}")
    try:
        man = check_manifest(bundle)
        check_matrices(bundle, man)
        check_corrupted(bundle)
        check_orbits(bundle)
    except Malformed as e:
        print(f"MALFORMED: {e}")
        return 2
    except Fail as e:
        print(f"FAIL: {e}")
        return 1
    print("mtxe-check: PASS — bundle self-consistent; planted-invalid rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
