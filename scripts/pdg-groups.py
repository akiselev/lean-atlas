#!/usr/bin/env python3
r"""Buckingham-pi from real papers: does the recovered grading contain the groups the paper names?

`scripts/paper-dim.py` turns a paper's LaTeX display equations into rows of
`dict[atom_id, Fraction]` ("this sum of exponents is zero"); `scripts/phys_dimlib.py` puts
them in RREF over ℚ. Neither file is edited here — both are imported.

The linear algebra of the question. A *grading* is an assignment D: atoms → ℚ^k satisfying
every row; the space of gradings is the **null space** of the row matrix. A monomial
∏ aᵢ^{eᵢ} is dimensionless under *every* valid grading exactly when e is orthogonal to that
null space, i.e. when **e lies in the row space** — which is what `Echelon.implies` decides.
So the recovered dimensionless groups are the row space of the paper's own equations, and
each pivot row printed by `render_relation` already *is* one. This file asks whether the
groups a paper **names in its prose** are in there.

===========================================================================================
PRE-REGISTRATION — written after reading the fifteen papers' prose and before running the
solver on any of them. Not edited afterwards.
===========================================================================================

SELECTION. Sixteen dimensionless groups were named up front (Ra Nu Re We Ca Ma Pe Kn Lu
beta Ro Ek Oh Toomre Eddington alpha). For each, the arXiv API was queried for papers whose
*abstract* names the group, in submittedDate-descending order, and the first paper was taken
whose source is usable LaTeX and which yields **>= 20 display equations**. No paper was
chosen by what it recovers; the Eddington query produced no paper meeting the equation floor
and that group is reported as excluded, not silently dropped.

THE ORACLE. For each paper, the groups it names were read out of its own prose, in its own
symbols, and written as a LaTeX identity below (`PREREG`). The identity is parsed with the
same parser and the same atom table as the paper, giving an exponent row; the question is
whether the paper's echelon `implies` that row.

WHAT A GOOD ANSWER LOOKS LIKE

  G1  Direct recall. I expect it to be **low**: 20-40% of the pre-registered groups. Half
      these papers are already non-dimensionalised, characteristic scales (L, U, D) usually
      occur in one equation and stay free, and the front end parses ~49% of display
      equations. Above 60% would be a surprise. **0% would mean the method does not work on
      papers at all.**

  G2  Echo versus derivation. A group the paper *defines* in a display equation is implied
      trivially — that is a regex, not a solver. The number that decides whether this is
      Buckingham-pi is **derived recall**: rebuild the system with every equation that alone
      implies the group deleted, and ask again. Pre-registered floor: **at least one** group
      must survive holdout, or the method is a lookup table. I expect at most three.
      The marquee prediction, stated before running: in `2606.22535` the displayed momentum
      and induction equations carry `\nu\nabla^2 v` and `\eta\nabla^2 B` against `\partial_t`
      terms, so **D(\nu) = D(\eta)** should be derivable and the magnetic Prandtl number
      `\nu/\eta` should come out dimensionless — although the paper defines `Pr_m` only in
      *inline* math, which the display extractor never sees.

  G3  Chance control (the one that decides whether a hit means anything). Random monomials
      over the same paper's own atom pool, same length as the true group, exponents drawn
      from {-2,-1,1,2}. Pre-registered ceiling: **< 5%** implied. If a random monomial is
      dimensionless as often as a named one, recall is measuring nothing.

  G4  Perturbation control. Each true group with its exponent on one atom shifted by +-1 must
      **not** be implied. A firing is diagnosable — it means that atom is forced
      dimensionless — and every firing is reported with its diagnosis. Ceiling: <= 10%.

  G5  Shuffle control. Re-point each row's entries at a random bijection of the atom pool,
      preserving row shapes and coefficients. Recall must go to **0** across 20 seeds. If
      shuffled recall matches real recall, every hit is an artifact of row shapes.

  G6  Collapse guard. The fraction of a paper's atoms *forced dimensionless* must stay small
      (< 10%). A collapsed lattice implies everything, including every named group, and would
      pass G1 while meaning nothing.

WHAT WOULD SHOW IT DOES NOT WORK

  * G3 above 5% — a named group is no more dimensionless than a random one.
  * G5 shuffled recall ~ real recall.
  * G2 derived recall 0 with all of G1 coming from echoes.
  * G6 above 10% on a paper whose groups were "recovered".

ARMS. Four reading choices are measured rather than assumed, each a recall/precision trade:
  base    display equations only, `paper-dim.py` defaults.
  inline  also harvest `$...$` / `\(...\)` math containing a relation. Papers put group
          *definitions* in inline math far more often than in displays — five of the fifteen
          do — so this is where the recall is, and the cost is noisier equations.
  sim     read `\sim` as a dimensional equality. `paper-dim.py` emits nothing for it, the
          safe direction; but in a scaling paper `A \sim B` does assert equal dimension.
  decor   make `\hat`, `\bar`, `\tilde` **name-changing** instead of transparent. The default
          reads `\hat{x} = x/L` as `D(x) = D(x) - D(L)`, i.e. `D(L) = 0` — a fabricated
          constraint, and non-dimensionalisation sections are full of exactly that form.

Usage:  uv run --no-sync scripts/pdg-groups.py --src <dir-of-flattened-tex> [--arm base|...]
        uv run --no-sync scripts/pdg-groups.py --selftest
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import random
import sys
from fractions import Fraction

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_spec = importlib.util.spec_from_file_location("pd", os.path.join(_HERE, "paper-dim.py"))
pd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pd)
from phys_dimlib import Echelon, eliminate_locals  # noqa: E402

ONE = Fraction(1)

# ---------------------------------------------------------------------------
# The pre-registration: what each paper names, in the paper's own symbols.
# `src` is where the identity was read from — a *display* equation (the parser can see it),
# *inline* math (it cannot, unless --arm inline), or the paper's running *prose*.
# ---------------------------------------------------------------------------

PREREG = [
    # id, group, LHS, RHS, where the identity was read
    ("2607.29276", "Ra", r"\ra", r"\frac{g\alpha\beta d^4}{\chi\nu}", "display"),
    ("2607.29276", "Pr", r"\pr", r"\frac{\nu}{\chi}", "display"),

    ("2607.09922", "Re-dimensionless", r"Re", r"1", "derived-only"),
    ("2607.09922", "Nu", r"Nu", r"\frac{2}{\Theta}", "display"),
    ("2607.09922", "Re-standard", r"Re", r"\frac{v_{r} \lambda}{\nu}", "standard"),

    ("2608.02779", "St", r"St", r"\Omega_0 \tau_p", "inline"),
    ("2608.02779", "tau_p", r"\tau_p", r"\frac{m_p}{6 \pi \eta r_p}", "inline"),

    ("2607.16367", "We", r"\mathrm{We}", r"\frac{\rho_l U_0^2 R_0}{\gamma}", "inline"),
    ("2607.16367", "Oh", r"\mathrm{Oh}", r"\frac{\sqrt{\mathrm{We}}}{\mathrm{Re}}", "inline"),
    ("2607.16367", "tau_0", r"\tau_0", r"\sqrt{\frac{\rho_l R_0^3}{\gamma}}", "prose"),

    ("2608.01803", "Ca", r"\mathrm{Ca}", r"\frac{\eta U}{\gamma}", "prose"),
    ("2608.01803", "Ca_c", r"\mathrm{Ca}_c", r"1", "display"),
    ("2608.01803", "phi", r"\phi", r"1", "prose"),

    ("2608.01542", "St", r"St", r"\frac{f D_j}{u_j}", "inline"),
    ("2608.01542", "M_j", r"M_j", r"\frac{u_j}{a_j}", "prose"),

    ("2607.29605", "Pe", r"\mathrm{Pe}", r"1", "prose"),

    ("2608.03236", "Kn", r"Kn", r"1", "prose"),

    ("2606.22535", "Pr_m", r"Pr_m", r"\frac{\nu}{\eta}", "inline"),
    ("2606.22535", "S", r"S", r"\frac{a v_A}{\eta}", "inline"),
    ("2606.22535", "nu-eta", r"\nu", r"\eta", "derived-only"),
    ("2606.22535", "alpha", r"\alpha", r"k a", "display"),

    ("2607.11789", "beta", r"\beta", r"\frac{8 \pi p}{B^2}", "inline"),

    ("2607.14257", "Ro", r"\mathrm{Ro}", r"1", "prose"),

    ("2607.29141", "Ek", r"\mathrm{Ek}", r"\frac{\nu}{\Omega R^2}", "display"),
    ("2607.29141", "Em", r"\mathrm{Em}", r"\frac{\eta}{\Omega R^2}", "display"),
    ("2607.29141", "Le", r"\mathrm{Le}",
     r"\frac{B_{\mathrm{amp}}}{\sqrt{\rho \mu_0}\Omega R}", "display"),
    ("2607.29141", "Pm", r"\mathrm{Pm}", r"\frac{\nu}{\eta}", "display"),
    ("2607.29141", "Em-derived", r"\mathrm{Em}", r"1", "derived-only"),

    ("2607.10164", "We", r"\mathrm{We}",
     r"\frac{\rho_\mathrm{c} U_{\mathrm{ref},x}^2 D}{\sigma}", "display"),
    ("2607.10164", "Oh", r"\mathrm{Oh}", r"\frac{\mu_d}{\sqrt{\rho_d \sigma R_0}}", "display"),
    ("2607.10164", "Re", r"\mathrm{Re}", r"\frac{\rho_c U_\mathrm{ref} R}{\mu_c}", "display"),
    ("2607.10164", "Ca", r"\mathrm{Ca}", r"\frac{\mu_c U_\mathrm{ref}}{\sigma_0}", "display"),
    ("2607.10164", "Bo", r"\mathrm{Bo}", r"\frac{g D^2 \rho_\mathrm{c}}{\sigma}", "display"),

    ("2606.31523", "Q", r"Q", r"\frac{\sigma_r \kappa}{G \Sigma}", "standard"),

    ("2607.12168", "alphaZ", r"\alpha Z", r"1", "prose"),
]

PAPERS = {
    "2607.29276": "Ra  turbulent convection, modal equations",
    "2607.09922": "Nu  forced convection past an isoflux cylinder",
    "2608.02779": "Re  particle trapping in vortex crystals",
    "2607.16367": "We  droplet rebound, anisotropic confinement",
    "2608.01803": "Ca  fluid-structure coupling in foam scraping",
    "2608.01542": "Ma  supersonic jet impingement on concave surfaces",
    "2607.29605": "Pe  reactive transport, dimension reduction",
    "2608.03236": "Kn  asymptotic-preserving adjoint UGKS",
    "2606.22535": "Lu  tearing instability in gyrotropic MHD",
    "2607.11789": "b   zonal-flow generation, electromagnetic gyrokinetics",
    "2607.14257": "Ro  singular limits of shallow water on the sphere",
    "2607.29141": "Ek  tidal dissipation in magnetised rotating stars",
    "2607.10164": "Oh  integral surface tension for front tracking",
    "2606.31523": "Q   normal modes in collisionless stellar disks",
    "2607.12168": "a   Wichmann-Kroll correction, He- and Li-like ions",
}

# ---------------------------------------------------------------------------
# Arms: each is a reversible patch of the imported front end.
# ---------------------------------------------------------------------------

_SAVED = {}


def set_arm(arm: str) -> None:
    if not _SAVED:
        _SAVED["silent"] = set(pd.SILENT_RELS)
        _SAVED["ord"] = set(pd.ORD_RELS)
        _SAVED["decor"] = set(pd.DECOR_CMDS)
        _SAVED["name"] = set(pd.NAME_CMDS)
    pd.SILENT_RELS.clear(); pd.SILENT_RELS.update(_SAVED["silent"])
    pd.ORD_RELS.clear(); pd.ORD_RELS.update(_SAVED["ord"])
    pd.DECOR_CMDS.clear(); pd.DECOR_CMDS.update(_SAVED["decor"])
    pd.NAME_CMDS.clear(); pd.NAME_CMDS.update(_SAVED["name"])
    parts = set(arm.split("+"))
    if "sim" in parts or "all" in parts:
        pd.SILENT_RELS.discard("\\sim")
        pd.ORD_RELS.add("\\sim")
    if "decor" in parts or "all" in parts:
        moved = {"\\hat", "\\bar", "\\tilde", "\\widetilde", "\\widehat", "\\overline"}
        pd.DECOR_CMDS -= moved
        pd.NAME_CMDS |= moved


INLINE_REL = ("=", "\\equiv", "\\sim", "\\approx", "\\simeq")


def inline_equations(tex: str) -> list[str]:
    r"""`$...$` and `\(...\)` segments that contain a relation.

    Papers put the *definitions* of their dimensionless groups in running text far more often
    than in a display: `We = \rho_l U_0^2 R_0/\gamma` in 2607.16367, `S=av_A/\eta` in
    2606.22535, `St = \Omega_0\tau_p` in 2608.02779 all live inline. The display extractor
    cannot see any of them, so a display-only recall number is measuring the typesetting
    convention as much as the physics.
    """
    import re
    out = []
    for m in re.finditer(r"(?<!\$)\$([^$]{2,400})\$(?!\$)", tex):
        s = m.group(1)
        if any(r in s for r in INLINE_REL) and "\\begin" not in s:
            out.append(s)
    for m in re.finditer(r"\\\((.{2,400}?)\\\)", tex, re.S):
        s = m.group(1)
        if any(r in s for r in INLINE_REL):
            out.append(s)
    return out


def load(path: str, arm: str):
    src = open(path, encoding="utf-8", errors="replace").read()
    macros = pd.collect_macros(src)
    eqs = pd.extract_display(src, macros)
    if "inline" in arm.split("+") or "all" in arm.split("+"):
        eqs = eqs + [pd.expand_macros(e, macros) for e in inline_equations(src)]
    return src, macros, eqs


def build(eqs, opts=None):
    sysm = pd.System()
    for i, e in enumerate(eqs):
        sysm.add(e, f"e{i}", opts)
    return sysm


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def probe_row(sysm, lhs, rhs, macros, opts):
    """The exponent row a pre-registered identity asserts, over the paper's own atoms.

    Returns `(row, novel_atoms, err)`. `novel_atoms` are symbols the identity mentions that
    the paper's parsed equations never produced — the group is then unrecoverable for a
    reason that has nothing to do with the solver, and must be reported separately from a
    genuine miss.
    """
    seen = set(sysm.table.ids)
    # `\pi`, not `1`, for "this is dimensionless": `paper-dim.py` gives a bare literal alone
    # on one side of a relation a free per-equation atom (so that `c = 1` is read as a choice
    # of units rather than a claim), and `eliminate_locals` then deletes the whole row. `\pi`
    # is in the front end's `DIMENSIONLESS` set and carries the assertion without the escape.
    lhs = r"\pi" if lhs.strip() == "1" else lhs
    rhs = r"\pi" if rhs.strip() == "1" else rhs
    try:
        src = pd.expand_macros(f"{lhs} = {rhs}", macros)
        rels, _, _ = pd.parse_equation(src, opts)
    except Exception as ex:                                    # noqa: BLE001
        return None, [], f"probe-parse:{getattr(ex, 'kind', type(ex).__name__)}"
    if not rels:
        return None, [], "probe-no-relation"
    w = pd.Walker(sysm.table, "probe")
    for op, l, r in rels:
        w.relation(op, l, r)
    rows = eliminate_locals(w.rows, lambda c: sysm.table.is_local[c])
    if len(rows) != 1:
        return None, [], f"probe-rows:{len(rows)}"
    novel = [k for k in sysm.table.ids if k not in seen and not k.startswith("?")]
    return rows[0], novel, None


def echelon_of(sysm):
    ech = Echelon(order=lambda c: sysm.table.keys[c])
    for r in sysm.global_rows:
        ech.add(r)
    return ech


def per_equation_echelons(sysm):
    """One echelon per source equation, so `holdout` can drop the equations that state it."""
    by = collections.defaultdict(list)
    for r, p in zip(sysm.global_rows, sysm.provenance):
        by[p].append(r)
    out = {}
    for p, rs in by.items():
        e = Echelon()
        for r in rs:
            e.add(r)
        out[p] = e
    return out


def holdout_echelon(sysm, row):
    """The echelon of every equation that does **not** on its own imply `row`."""
    per = per_equation_echelons(sysm)
    drop = {p for p, e in per.items() if e.implies(dict(row))}
    ech = Echelon(order=lambda c: sysm.table.keys[c])
    for r, p in zip(sysm.global_rows, sysm.provenance):
        if p not in drop:
            ech.add(r)
    return ech, sorted(drop)


def perturbations(row):
    for a in list(row):
        for d in (ONE, -ONE):
            r = dict(row)
            r[a] = r.get(a, Fraction(0)) + d
            if not r[a]:
                del r[a]
            if r and r != row:
                yield a, d, r


def random_monomials(sysm, k, n, rng):
    pool = [c for c in range(len(sysm.table.keys))
            if not sysm.table.is_local[c] and c in sysm_columns(sysm)]
    if len(pool) < k or k == 0:
        return []
    out = []
    for _ in range(n):
        pick = rng.sample(pool, k)
        out.append({c: Fraction(rng.choice([-2, -1, 1, 2])) for c in pick})
    return out


def sysm_columns(sysm):
    if not hasattr(sysm, "_cols"):
        sysm._cols = {c for r in sysm.global_rows for c in r}
    return sysm._cols


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run(srcdir, arm, seeds=20, nrandom=400, show=0, dump=None):
    set_arm(arm)
    opts = {"paren": "apply", "delta": "transparent"}
    rng = random.Random(20260804)
    tot = collections.Counter()
    per_paper = []
    results = []

    for pid, label in PAPERS.items():
        path = os.path.join(srcdir, f"{pid}.tex")
        if not os.path.exists(path):
            print(f"  MISSING {path}")
            continue
        _, macros, eqs = load(path, arm)
        sysm = build(eqs, opts)
        ech = echelon_of(sysm)
        cols = ech.columns()
        single = [c for c, r in ech.pivots.items() if len(r) == 1]
        rich = [(c, r) for c, r in ech.pivots.items() if len(r) >= 3]
        gdim = len(cols) - ech.rank
        forced = len(single) / max(len(cols), 1)

        probes = [p for p in PREREG if p[0] == pid]
        hits = miss = absent = broken = 0
        pert_fire = pert_tot = 0
        rows_for_random = []
        for _, gname, lhs, rhs, where in probes:
            row, novel, err = probe_row(sysm, lhs, rhs, macros, opts)
            rec = {"paper": pid, "group": gname, "where": where, "arm": arm}
            if err:
                broken += 1
                rec.update(verdict="probe-error", detail=err)
                results.append(rec)
                continue
            if novel:
                absent += 1
                rec.update(verdict="symbol-absent", detail=",".join(novel[:6]))
                results.append(rec)
                continue
            ok = ech.implies(dict(row))
            rec["verdict"] = "RECOVERED" if ok else "not-implied"
            # The sharper question, and the one Buckingham's theorem is actually about:
            # is the paper's *monomial* a pure number, rather than merely equal in dimension
            # to the symbol the paper hangs on it? A paper that writes `Bo = gD^2\rho/\sigma`
            # makes the first true by fiat; only the equation system can make the second true.
            # Matched exactly to the chance control, which asks the same of a random monomial.
            prow, pnovel, perr = probe_row(sysm, r"\pi", rhs, macros, opts)
            rec["pi_only"] = ("n/a" if (perr or pnovel or prow is None)
                              else ("DIMENSIONLESS" if ech.implies(dict(prow)) else "no"))
            if ok:
                hits += 1
                hech, dropped = holdout_echelon(sysm, row)
                rec["holdout"] = "DERIVED" if hech.implies(dict(row)) else "echo"
                rec["dropped"] = dropped
                for a, d, pr in perturbations(row):
                    pert_tot += 1
                    if ech.implies(dict(pr)):
                        pert_fire += 1
                        rec.setdefault("pert", []).append(
                            f"{sysm.table.keys[a]}{'+' if d > 0 else '-'}1"
                            f"{' [atom forced dimensionless]' if ech.implies({a: ONE}) else ''}")
                rows_for_random.append(row)
            else:
                miss += 1
            rec["natoms"] = len(row)
            results.append(rec)

        # G3: the chance control, matched in length to the true groups actually tested.
        rand_fire = rand_tot = 0
        for row in rows_for_random or [{}]:
            for m in random_monomials(sysm, len(row), nrandom // max(len(rows_for_random), 1),
                                      rng):
                rand_tot += 1
                rand_fire += ech.implies(m)
        # …and the same control at a fixed length, so that a paper with *no* recovered group
        # still gets a baseline. Without it the papers that recover nothing are also the
        # papers with no evidence about whether recovering something would have meant
        # anything, and the stratification below could not be applied to them.
        c4_fire = c4_tot = 0
        for m in random_monomials(sysm, 4, nrandom, rng):
            c4_tot += 1
            c4_fire += ech.implies(m)

        # G5: shuffle. Reported for both statistics because the pre-registered one turned
        # out to be invalid: a per-row bijection *raises* rank (it destroys the shared
        # structure that made rows dependent), so a shuffled system implies MORE, not less.
        # The grading dimension still collapses, which is the form of the control that works.
        sh_hits = sh_tot = 0
        sh_dims, sh_chance = [], []
        for s in range(seeds):
            r2 = random.Random(5000 + s)
            sh = pd.shuffle_rows(sysm.global_rows, r2)
            e2 = Echelon()
            for r in sh:
                e2.add(r)
            sh_dims.append(len(e2.columns()) - e2.rank)
            for row in rows_for_random:
                sh_tot += 1
                sh_hits += e2.implies(dict(row))
            if s < 3:
                sh_chance += [e2.implies(m)
                              for m in random_monomials(sysm, 4, nrandom // 3, rng)]

        per_paper.append(dict(
            pid=pid, label=label, eqs=sysm.attempted, parsed=sysm.parsed,
            rows=len(sysm.global_rows), cols=len(cols), rank=ech.rank, gdim=gdim,
            rich=len(rich), forced=forced, probes=len(probes), hits=hits, miss=miss,
            absent=absent, broken=broken, pert_fire=pert_fire, pert_tot=pert_tot,
            rand_fire=rand_fire, rand_tot=rand_tot, sh_hits=sh_hits, sh_tot=sh_tot,
            c4=c4_fire / max(c4_tot, 1), c4_fire=c4_fire, c4_tot=c4_tot,
            sh_dim=sorted(sh_dims)[len(sh_dims) // 2] if sh_dims else 0,
            sh_chance=sum(sh_chance) / max(len(sh_chance), 1)))
        tot.update(dict(probes=len(probes), hits=hits, miss=miss, absent=absent,
                        broken=broken, pert_fire=pert_fire, pert_tot=pert_tot,
                        rand_fire=rand_fire, rand_tot=rand_tot, sh_hits=sh_hits,
                        sh_tot=sh_tot, eqs=sysm.attempted, parsed=sysm.parsed,
                        rows=len(sysm.global_rows), rich=len(rich)))
        if show and pid == show:
            print(f"\n  multi-atom relations recovered for {pid}:")
            for c, r in sorted(rich, key=lambda kv: -len(kv[1]))[:40]:
                print("    ", pd.render_relation(sysm.table, c, r, width=8))

    print(f"\n{'=' * 100}\nARM {arm}\n{'=' * 100}")
    hdr = (f"{'paper':<12} {'eqs':>5} {'pars':>5} {'rows':>5} {'cols':>5} {'gdim':>5} "
           f"{'shdim':>5} {'rich':>5} {'forced':>7} {'chance':>7} {'probe':>6} {'HIT':>4} "
           f"{'miss':>5} {'abs':>4} {'pert':>7} {'rand':>8} {'shuf':>7}  verdict")
    print(hdr)
    for p in per_paper:
        v = "USABLE" if p["c4"] < 0.05 else "vacuous"
        print(f"{p['pid']:<12} {p['eqs']:>5} {p['parsed']:>5} {p['rows']:>5} {p['cols']:>5} "
              f"{p['gdim']:>5} {p['sh_dim']:>5} {p['rich']:>5} {p['forced']:>6.1%} "
              f"{p['c4']:>6.1%} {p['probes']:>6} "
              f"{p['hits']:>4} {p['miss']:>5} {p['absent']:>4} "
              f"{p['pert_fire']:>3}/{p['pert_tot']:<3} {p['rand_fire']:>3}/{p['rand_tot']:<4} "
              f"{p['sh_hits']:>3}/{p['sh_tot']:<3}  {v}")
    use = [p for p in per_paper if p["c4"] < 0.05]
    vac = [p for p in per_paper if p["c4"] >= 0.05]
    print(f"\n  STRATIFIED on the chance control (not filtered — both strata reported):")
    print(f"    chance < 5%  ({len(use)} papers): probes {sum(p['probes'] for p in use)}  "
          f"recovered {sum(p['hits'] for p in use)}  "
          f"absent {sum(p['absent'] for p in use)}  "
          f"chance {sum(p['c4_fire'] for p in use)}/{sum(p['c4_tot'] for p in use)}")
    print(f"    chance >= 5% ({len(vac)} papers): probes {sum(p['probes'] for p in vac)}  "
          f"recovered {sum(p['hits'] for p in vac)}  "
          f"absent {sum(p['absent'] for p in vac)}  "
          f"chance {sum(p['c4_fire'] for p in vac)}/{sum(p['c4_tot'] for p in vac)}   "
          f"<- everything is dimensionless here, so a hit means nothing")
    print(f"    shuffled grading dim vs real, per paper: "
          + " ".join(f"{p['gdim']}->{p['sh_dim']}" for p in per_paper))
    n = tot["probes"]
    print(f"\n  probes {n}   RECOVERED {tot['hits']} ({tot['hits'] / max(n, 1):.1%})   "
          f"not-implied {tot['miss']}   symbol-absent {tot['absent']}   "
          f"probe-error {tot['broken']}")
    der = sum(1 for r in results if r.get("holdout") == "DERIVED")
    echo = sum(1 for r in results if r.get("holdout") == "echo")
    print(f"  of the recovered: DERIVED under holdout {der}   echo of a stated equation {echo}")
    usable = {p["pid"] for p in per_paper if p["c4"] < 0.05}
    pu = [r for r in results if r["paper"] in usable]
    print(f"  USABLE stratum only: probes {len(pu)}  "
          f"RECOVERED {sum(1 for r in pu if r['verdict'] == 'RECOVERED')}  "
          f"DERIVED {sum(1 for r in pu if r.get('holdout') == 'DERIVED')}  "
          f"monomial itself dimensionless "
          f"{sum(1 for r in pu if r.get('pi_only') == 'DIMENSIONLESS')}")
    print(f"  G3 chance control   {tot['rand_fire']}/{tot['rand_tot']} random monomials "
          f"implied ({tot['rand_fire'] / max(tot['rand_tot'], 1):.2%})   [ceiling 5%]")
    print(f"  G4 perturbation     {tot['pert_fire']}/{tot['pert_tot']} "
          f"({tot['pert_fire'] / max(tot['pert_tot'], 1):.1%})   [ceiling 10%]")
    print(f"  G5 shuffle          {tot['sh_hits']}/{tot['sh_tot']} recovered under shuffle "
          f"({tot['sh_hits'] / max(tot['sh_tot'], 1):.2%})   [target 0]")
    print(f"  parse rate {tot['parsed']}/{tot['eqs']} = "
          f"{tot['parsed'] / max(tot['eqs'], 1):.1%}   global rows {tot['rows']}   "
          f"multi-atom relations {tot['rich']}")
    print("\n  every probe:")
    for r in results:
        extra = ""
        if r.get("holdout"):
            extra = f"  [{r['holdout']}"
            if r["holdout"] == "DERIVED":
                extra += "]"
            else:
                extra += f", stated by {len(r.get('dropped', []))} eq]"
        if r.get("pert"):
            extra += "  PERT " + "; ".join(r["pert"])
        if r.get("detail"):
            extra += f"  ({r['detail'][:60]})"
        pi = f"  pi={r['pi_only']}" if r.get("pi_only") else ""
        print(f"    {r['paper']:<12} {r['group']:<18} {r['where']:<12} "
              f"{r['verdict']:<14}{pi}{extra}")
    if dump:
        json.dump({"arm": arm, "papers": per_paper, "probes": results},
                  open(dump, "w"), indent=1, default=str)
    return per_paper, results, tot


def selftest() -> int:
    """The harness must find a group it should and refuse one it should not."""
    set_arm("base")
    fails = []
    sysm = build(pd.PHYS_BIG, {"paren": "apply", "delta": "transparent"})
    ech = echelon_of(sysm)
    for label, lhs, rhs, want in (
            ("E/(F x) dimensionless", r"E", r"F x", True),
            ("v/c dimensionless (Mach-like)", r"\beta", r"\frac{v}{c}", True),
            ("E/(m v) NOT dimensionless", r"E", r"m v", False),
            ("G M/(r v^2) dimensionless", r"1", r"\frac{G M}{r v^2}", True),
            ("G M/(r v) NOT dimensionless", r"1", r"\frac{G M}{r v}", False)):
        row, novel, err = probe_row(sysm, lhs, rhs, {}, None)
        got = (err is None and not novel and ech.implies(dict(row)))
        print(f"  {'ok  ' if got == want else 'FAIL'}  {label}: got {got}, want {want}"
              + (f"  [{err or novel}]" if err or novel else ""))
        if got != want:
            fails.append(label)
    # The chance control must be near zero on the corpus whose grading is known.
    rng = random.Random(7)
    row, _, _ = probe_row(sysm, r"E", r"F x", {}, None)
    fire = sum(ech.implies(m) for m in random_monomials(sysm, len(row), 400, rng))
    print(f"  {'ok  ' if fire / 400 < 0.05 else 'FAIL'}  G3 chance control on PHYS_BIG: "
          f"{fire}/400 = {fire / 400:.2%}  [<5%]")
    if fire / 400 >= 0.05:
        fails.append("chance control")
    # Holdout must call a stated law an echo and a derived one derived.
    small = build(pd.MECH_SMALL, None)
    se = echelon_of(small)
    for label, lhs, rhs, want in (("W = F x is stated -> echo", r"W", r"F x", "echo"),
                                  ("E = F x is not stated -> DERIVED", r"E", r"F x",
                                   "DERIVED")):
        row, _, err = probe_row(small, lhs, rhs, {}, None)
        assert err is None and se.implies(dict(row)), label
        h, dropped = holdout_echelon(small, row)
        got = "DERIVED" if h.implies(dict(row)) else "echo"
        print(f"  {'ok  ' if got == want else 'FAIL'}  {label}: got {got} "
              f"(dropped {dropped})")
        if got != want:
            fails.append(label)
    print("SELFTEST PASS" if not fails else f"SELFTEST FAIL: {fails}")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=".")
    ap.add_argument("--arm", default="base")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--random", type=int, default=400)
    ap.add_argument("--show", default="")
    ap.add_argument("--dump", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    run(a.src, a.arm, a.seeds, a.random, a.show or None, a.dump or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
