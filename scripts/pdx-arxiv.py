#!/usr/bin/env python3
r"""Point the validated LaTeX dimensional front end at real arXiv physics papers.

`scripts/paper-dim.py` is imported unchanged (it in turn imports `scripts/phys_dimlib.py`
unchanged). Nothing here reimplements a parser or a solver. This file adds only the thing
the front end does not have: **a per-equation consistency verdict on a real document, and
the control that decides whether that verdict means anything.**

===========================================================================================
PRE-REGISTRATION — written before any paper in this run was parsed, and not edited after
===========================================================================================

THE PROBLEM THIS HAS TO SOLVE FIRST

  A dimensional system is a set of *homogeneous* linear rows over ℚ. Such a system is never
  inconsistent: the all-zero grading always solves it. So "this paper contains a
  dimensionally inconsistent equation" cannot mean "the linear system has no solution". It
  has to mean: *this equation removes grading freedom that the rest of the paper needs.*

  Which forces the detector to be relative to the rest of the document. For equation `e`
  with global rows `R_e`, write `R_-e` for every other equation's rows.

    new(e)        atoms that occur in `R_e` and nowhere in `R_-e`
    residual(e)   `eliminate_locals(R_e, is_new)` — what `e` says about symbols the rest of
                  the paper also uses, after its private symbols are projected away
    checkable(e)  residual(e) is non-empty
    confirmed(e)  checkable and every residual row is implied by rowspace(R_-e)
    flagged(e)    checkable and some residual row is NOT implied by rowspace(R_-e)

  `confirmed` is a cross-check the paper passes: the rest of the document already derives
  what this equation asserts. `flagged` is the only candidate an error can ever be.

  An equation that is not checkable cannot be wrong: its private symbol absorbs whatever
  dimension the equation demands. `E = m v` is unfalsifiable if `E` occurs nowhere else.

WHAT A GOOD ANSWER LOOKS LIKE, STATED BEFORE THE RUN

  A1  The checkability census is the ceiling on everything else, so it is measured first and
      reported whatever it says. Prediction on the record: **the confirmed fraction will be
      small — under 15% of row-yielding equations** — because a paper introduces symbols as
      it goes and rarely restates a dimensional relation the reader could re-derive. If it
      is near zero the honest conclusion is that the method cannot audit papers, and that
      conclusion is to be reported as the result rather than worked around.

  A2  Detection is claimed only where it is possible. `D-flag` fires on `e` iff `e` was not
      flagged before the injection and is flagged after. Note (proved, not assumed — see
      `explain_equivalence` below and the assertion in `--selftest`) that this is *the same
      event* as the front end's own N1 rule "the grading dimension strictly drops": the
      grading dimension can only drop when a confirmed equation stops being implied. So the
      new rule adds localisation, not sensitivity.

      Pre-registered targets:
        * on the `confirmed` subset, where detection is possible at all: **≥ 90%**
        * on a uniformly random row-yielding equation: no target — it is *predicted* to be
          approximately the confirmed fraction, and a materially higher number would mean
          the flag rule is firing for a reason I have not modelled.

  A3  An injection only counts if it is genuinely wrong. A perturbation whose residual is
      still implied by the *full* original system changed nothing dimensional (it hit a
      symbol the paper already forces dimensionless, say). Those are discarded before the
      rate is computed, and the discard count is reported. Without this filter the miss
      column silently fills with injections that were never errors.

  A4  Two injection modes, because they fail differently:
        * row-level — add ±1 to one coefficient of one row. Systematic, hits every
          confirmed equation, cannot be blamed on the parser.
        * LaTeX-level — multiply everything after the first `=` by a symbol the equation
          already contains, then **re-parse from source**. Realistic ("a factor of r went
          missing") and it exercises the whole pipeline. Its detection rate may be lower
          than row-level for a parser reason; that gap is itself a measurement.

  A5  Every flagged equation on the *unperturbed* papers is read by hand and classified.
      The false-positive rate is `1 - (genuine errors / flags)`. Predicted to be high:
      natural units, index notation, implicit constants and a 50%-ish parse rate all
      manufacture flags. A flag is a candidate, never a finding.

  N2  The shuffle control is re-run on this independent paper set. If the grading dimension
      does not fall under a per-row bijection of the atom pool, the recovered structure is
      an artifact of row shapes and every number above is uninterpretable.

WHAT WOULD SHOW THIS DOES NOT WORK

  * Detection materially below 90% on the confirmed subset — the flag rule cannot see an
    error even where the paper states one redundantly, so a clean paper is unfalsifiable.
  * A confirmed fraction of zero across all papers — nothing in a real paper is checkable
    and the tool has no reach, however good the parser gets.
  * A flag list that is entirely parser artifacts — the detector is measuring the front end
    rather than the physics.
  * N2 failing to collapse the grading on real papers.
  * A detection rate on random equations far above the confirmed fraction — the flag is
    firing for an unmodelled reason and the causal story above is wrong.

WHAT THIS CANNOT DO, KNOWN IN ADVANCE

  It cannot distinguish "this equation is wrong" from "this equation is new physics stated
  among symbols that already appear". Both add an independent constraint. Only a hand read
  separates them, which is why A5 is a hand classification and not a number the script
  prints.

===========================================================================================
AMENDMENTS — made after the first run, each with the observation that forced it
===========================================================================================

The pre-registration above is left exactly as written. These are the corrections, recorded
rather than folded in, because a pre-registration that gets edited to match the result is
not one.

  * **A3's validity filter was wrong and had to be replaced.** As written it discarded an
    injection whose perturbed residual was still implied by the full system. That is very
    nearly the detector's own test, so it made the detection rate close to a tautology; and
    it also swallowed every injection into an *unfalsifiable* equation, since an empty
    residual is vacuously implied. The first run reported 100% detection with 1,140
    "harmless" discards, which is the shape of a filter manufacturing its own success —
    exactly the failure CLAUDE.md §3 warns a narrowing filter produces.

    The replacement test reads only the perturbed atom: the injection is genuine iff that
    atom is not forced dimensionless by the paper's own full system (`classify_injection`
    carries the proof). It never consults `R_-e`, which is what the detector reads.
    Undetectable injections are now counted as the false negatives they are, and the
    honest detection rate on the confirmed set fell from "100%" to 73%.

  * **A2's equivalence claim holds only for atom-preserving injections.** A perturbation
    that drives a coefficient to zero deletes a *symbol* from the document, so a column can
    vanish and the grading dimension move with no constraint tightened. Measured
    separately; the two modes disagree at very different rates and the gap is reported.

  * **N2 needed a control the shuffle cannot be.** A per-row bijection densifies the system
    until its row space is nearly everything, at which point every row is trivially implied
    and the shuffled `confirmed` fraction goes *up*. That makes it useless as a null for the
    census, though it remains valid for the grading dimension. `foreign_census` is the
    replacement: confirm each equation against a *different real paper's* rows, matching
    atoms by name.

Usage:

    uv run --no-sync scripts/pdx-arxiv.py --selftest
    uv run --no-sync scripts/pdx-arxiv.py --dir <flat-tex-dir> --out <json>
    uv run --no-sync scripts/pdx-arxiv.py --dir <flat-tex-dir> --flags   # hand-check list
"""

from __future__ import annotations

import argparse
import collections
import glob
import importlib.util
import json
import os
import random
import sys
from fractions import Fraction

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pd = _load("paper_dim", "paper-dim.py")
from phys_dimlib import AtomTable, Echelon, eliminate_locals  # noqa: E402


# ---------------------------------------------------------------------------
# Per-equation verdicts
# ---------------------------------------------------------------------------

class Doc:
    """A parsed paper plus the per-equation bookkeeping the verdicts need."""

    def __init__(self, paper_id: str, sources: list[str], opts=None) -> None:
        self.paper_id = paper_id
        self.sysm = pd.System()
        self.src_of: dict[str, str] = {}
        for i, e in enumerate(sources):
            eq_id = f"e{i}"
            self.src_of[eq_id] = e
            self.sysm.add(e, eq_id, opts)
        # rows grouped by the equation that produced them
        self.rows_of: dict[str, list[dict]] = collections.defaultdict(list)
        for row, prov in zip(self.sysm.global_rows, self.sysm.provenance):
            self.rows_of[prov].append(row)
        self.eq_ids = [k for k in self.src_of if k in self.rows_of]

    # -- solver views ------------------------------------------------------

    def echelon(self, rows=None):
        ech = Echelon()
        for r in (self.sysm.global_rows if rows is None else rows):
            ech.add(r)
        return ech

    def dim(self, rows=None):
        rows = self.sysm.global_rows if rows is None else rows
        ech = self.echelon(rows)
        return len(ech.columns()) - ech.rank

    def forced_zero(self, rows=None):
        """Atoms every valid grading sends to exponent 0 — a pivot row of length one."""
        ech = self.echelon(rows)
        return {c for c, r in ech.pivots.items() if len(r) == 1}

    # -- the verdict -------------------------------------------------------

    def residual(self, eq_id: str, rows=None, others=None):
        """What `eq_id` says about symbols the rest of the paper also uses.

        Its private atoms are eliminated blockwise rather than dropped: dropping a column
        would change the remaining exponents, which is the direction that invents a
        constraint (`phys_dimlib.py`'s own warning about a collision).
        """
        mine = self.rows_of[eq_id] if rows is None else rows
        rest = self._others(eq_id) if others is None else others
        seen = {c for r in rest for c in r}
        return eliminate_locals(mine, lambda c: c not in seen)

    def _others(self, eq_id: str):
        return [row for row, prov in zip(self.sysm.global_rows, self.sysm.provenance)
                if prov != eq_id]

    def verdict(self, eq_id: str, rows=None):
        rest = self._others(eq_id)
        res = self.residual(eq_id, rows=rows, others=rest)
        if not res:
            return "unfalsifiable", []
        ech = self.echelon(rest)
        bad = [r for r in res if not ech.implies(r)]
        return ("flagged" if bad else "confirmed"), bad

    def census(self):
        out = {"unfalsifiable": [], "confirmed": [], "flagged": []}
        for eq_id in self.eq_ids:
            v, _ = self.verdict(eq_id)
            out[v].append(eq_id)
        return out


# ---------------------------------------------------------------------------
# A2's claim that the flag rule and the front end's N1 rule are the same event
# ---------------------------------------------------------------------------

def explain_equivalence(doc: Doc, eq_id: str, new_rows) -> dict:
    """Measure, rather than assert, that `D-flag` and `dim drops` coincide on one swap."""
    rest = doc._others(eq_id)
    before = len(doc.sysm.global_rows)
    old_dim = doc.dim(rest + doc.rows_of[eq_id])
    new_dim = doc.dim(rest + new_rows)
    v_before, _ = doc.verdict(eq_id)
    v_after, _ = doc.verdict(eq_id, rows=new_rows)
    return {"rows": before, "dim_before": old_dim, "dim_after": new_dim,
            "dim_dropped": new_dim < old_dim,
            "was": v_before, "now": v_after,
            "d_flag": v_before != "flagged" and v_after == "flagged"}


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------

def perturb_row(row: dict, atom: int, delta=Fraction(1)) -> dict:
    out = dict(row)
    out[atom] = out.get(atom, Fraction(0)) + delta
    if out[atom] == 0:
        del out[atom]
    return out


def classify_injection(doc: Doc, eq_id: str, new_rows, atom: int, zeroed: set) -> str:
    """The outcome of one injection, on a validity test independent of the detector.

    The first version of this asked whether the *perturbed residual* was still implied by
    the full system, and discarded the injection if so. That was very nearly the same test
    as the detector itself, which would have made a 100% detection rate a tautology rather
    than a measurement — and worse, it swallowed every undetectable injection into the
    discard pile, manufacturing exactly the false negatives CLAUDE.md §3 warns that a
    narrowing filter manufactures.

    The validity test used instead is local and provably independent. Perturbing coefficient
    `atom` by `delta` adds `delta * e_atom` to one row. If some grading `g` in the paper's
    null space has `g(atom) != 0`, then `g` satisfies the original row and violates the
    perturbed one, so the perturbation is a genuine dimensional error. Such a `g` exists iff
    `atom` is not forced dimensionless by the paper's own full system. That is a property of
    the atom alone — it never consults `R_-e`, which is what the detector reads.
    """
    if atom in zeroed:
        return "neutral"          # the paper already makes this symbol dimensionless
    res = doc.residual(eq_id, rows=new_rows)
    if not res:
        # A real error the document cannot see: after its private symbols are projected
        # away this equation says nothing. A false negative, and counted as one.
        return "undetectable"
    v_after, _ = doc.verdict(eq_id, rows=new_rows)
    if v_after == "flagged":
        return "hit"
    # Two very different reasons to miss, and lumping them would hide which one this is.
    # If the perturbed symbol occurs nowhere else in the paper, the equation is not wrong
    # at all afterwards — the private symbol simply absorbs the change, and no dimensional
    # method whatever could object. If the symbol IS shared, the detector genuinely failed.
    seen = {c for r in doc._others(eq_id) for c in r}
    return "miss-private" if atom not in seen else "miss"


def inject_rows(doc: Doc, eq_id: str, rng, tries=6, keep_atoms=True):
    """Row-level injections for one equation.

    `keep_atoms` refuses a delta that would drive a coefficient to zero. Deleting a symbol
    from a row is a different experiment: it can shrink the *column* count, which moves the
    grading dimension for a reason that has nothing to do with a tightened constraint. That
    case is measured separately by `--deletion-mode` rather than mixed in here.
    """
    zeroed = doc.forced_zero()
    mine = doc.rows_of[eq_id]
    cand = [(i, c) for i, r in enumerate(mine) for c in r]
    rng.shuffle(cand)
    out = []
    for i, c in cand[:tries]:
        for delta in (Fraction(rng.choice([1, -1, 2])), Fraction(1), Fraction(2)):
            if not keep_atoms or mine[i][c] + delta != 0:
                break
        else:
            continue
        new_rows = [perturb_row(r, c, delta) if j == i else dict(r)
                    for j, r in enumerate(mine)]
        out.append({"atom": doc.sysm.table.keys[c], "delta": str(delta),
                    "deleted": mine[i][c] + delta == 0,
                    "status": classify_injection(doc, eq_id, new_rows, c, zeroed)})
    return out


def mutate_latex(src: str, sym: str) -> str | None:
    """`LHS = RHS` -> `LHS = sym ( RHS )`, i.e. a factor that should not be there.

    Only the first top-level `=` is used; a chained relation keeps its later parts inside
    the parenthesis, which is still exactly one dimensional error.
    """
    depth = 0
    for i, ch in enumerate(src):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "=" and depth == 0:
            if i and src[i - 1] in "<>!:+-*/\\^_&":
                continue
            if i + 1 < len(src) and src[i + 1] == "=":
                continue
            return src[:i + 1] + " " + sym + r" \left( " + src[i + 1:] + r" \right) "
    return None


def inject_latex(doc: Doc, eq_id: str, rng, opts=None, tries=4):
    """Re-parse a source-level injection, so the parser is in the loop (A4)."""
    src = doc.src_of[eq_id]
    zeroed = doc.forced_zero()
    pool = [c for r in doc.rows_of[eq_id] for c in r if c not in zeroed]
    pool = [c for c in dict.fromkeys(pool)
            if doc.sysm.table.keys[c].isalnum()
            or (doc.sysm.table.keys[c].startswith("\\")
                and doc.sysm.table.keys[c][1:].isalpha())]
    rng.shuffle(pool)
    out = []
    for atom in pool[:tries]:
        sym = doc.sysm.table.keys[atom]
        mutated = mutate_latex(src, sym)
        if mutated is None:
            continue
        probe = pd.System()
        if not probe.add(mutated, eq_id, opts):
            out.append({"sym": sym, "status": "parse-failed",
                        "kind": next(iter(probe.failures), "?")})
            continue
        # Re-key the probe's atoms into the document's table so the rows are comparable.
        new_rows = []
        for r in probe.global_rows:
            new_rows.append({doc.sysm.table.intern(probe.table.keys[c], False): v
                             for c, v in r.items()})
        # Multiplying one side by `sym` shifts that side's exponent of `sym` by one, so the
        # same validity argument applies: the injection is real iff `sym` is not forced
        # dimensionless, which `pool` already required.
        out.append({"sym": sym, "status": classify_injection(doc, eq_id, new_rows,
                                                             atom, zeroed),
                    "src": mutated[:160]})
    return out


# ---------------------------------------------------------------------------
# How strong is a confirmation, and does it survive the shuffle
# ---------------------------------------------------------------------------

def confirm_strength(doc: Doc, eq_id: str) -> str:
    """Grade one confirmation, because they are not worth the same.

    `single-atom`  the residual only says "this symbol is dimensionless", which the paper
                   already said. True, and nearly free.
    `restatement`  some *one* other equation alone implies it — the paper wrote the same
                   relation twice (a substitution into a chained equality is the common
                   case, and it is a real cross-check, just a local one).
    `derived`      no single other equation implies it; the confirmation needed at least two,
                   so the paper's equations agree across a step of reasoning.
    """
    res = doc.residual(eq_id)
    best = "single-atom"
    for row in res:
        if len(row) < 2:
            continue
        alone = False
        for other in doc.eq_ids:
            if other == eq_id:
                continue
            if doc.echelon(doc.rows_of[other]).implies(row):
                alone = True
                break
        if not alone:
            return "derived"
        best = "restatement"
    return best


def foreign_census(doc: Doc, other: Doc) -> tuple[int, int]:
    """Confirm each of `doc`'s equations against a DIFFERENT paper's rows.

    The control the shuffle cannot be: a per-row bijection densifies the system until its
    row space is nearly everything, at which point every row is implied and `confirmed`
    rises for a reason that has nothing to do with the paper. This one keeps both sides
    real. Physics papers share symbol names — `c`, `G`, `t`, `\\rho`, `\\omega` — so a
    foreign document produces some confirmations by coincidence. If it produces as many as
    the paper's own equations do, `confirmed` is measuring the alphabet rather than the
    document.

    Atoms are matched **by name** across the two tables, which is exactly the coincidence
    being measured.
    """
    tab = AtomTable()

    def port(rows, src_table):
        return [{tab.intern(src_table.keys[c], False): v for c, v in r.items()}
                for r in rows]

    rest = port(other.sysm.global_rows, other.sysm.table)
    seen = {c for r in rest for c in r}
    ech = Echelon()
    for r in rest:
        ech.add(r)
    conf = tot = 0
    for eq_id in doc.eq_ids:
        mine = port(doc.rows_of[eq_id], doc.sysm.table)
        res = eliminate_locals(mine, lambda c: c not in seen)
        if not res:
            continue
        tot += 1
        if all(ech.implies(r) for r in res):
            conf += 1
    return conf, tot


def shuffled_confirmed_fraction(doc: Doc, srows) -> float:
    """The census recomputed on shuffled rows, keeping each equation's row *count*.

    N2 for the verdicts rather than for the grading dimension. If the confirmed fraction
    does not fall, `confirmed` is measuring row shapes and not the paper.
    """
    grouped, i = {}, 0
    for eq_id in doc.eq_ids:
        n = len(doc.rows_of[eq_id])
        grouped[eq_id] = srows[i:i + n]
        i += n
    conf = tot = 0
    for eq_id in doc.eq_ids:
        rest = [r for k, v in grouped.items() if k != eq_id for r in v]
        seen = {c for r in rest for c in r}
        res = eliminate_locals(grouped[eq_id], lambda c: c not in seen)
        if not res:
            continue
        tot += 1
        ech = Echelon()
        for r in rest:
            ech.add(r)
        if all(ech.implies(r) for r in res):
            conf += 1
    return conf / max(tot, 1)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def analyse(path: str, opts=None, seed=7, sample=40, shuffle_seeds=20):
    paper_id = os.path.basename(path).replace(".tex", "")
    tex = open(path, encoding="utf-8", errors="replace").read()
    macros = pd.collect_macros(tex)
    eqs = pd.extract_display(tex, macros)
    doc = Doc(paper_id, eqs, opts)
    s = doc.sysm
    ech, cols = s.solve()
    single, pairs, rich, powered = pd.classify(ech)
    cen = doc.census()

    rng = random.Random(seed)
    KEYS = ("hit", "miss", "miss-private", "undetectable", "neutral")

    def tally(results, into):
        for r in results:
            into[r["status"]] = into.get(r["status"], 0) + 1

    # row-level injection on every confirmed equation (where detection should be possible)
    det = dict.fromkeys(KEYS, 0)
    for eq_id in cen["confirmed"]:
        tally(inject_rows(doc, eq_id, rng), det)

    # row-level injection on a uniformly random row-yielding equation — the honest rate
    rnd = dict.fromkeys(KEYS, 0)
    pool = list(doc.eq_ids)
    rng.shuffle(pool)
    for eq_id in pool[:sample]:
        tally(inject_rows(doc, eq_id, rng, tries=2), rnd)

    # LaTeX-level injection on the confirmed set, parser in the loop
    tex_inj = dict.fromkeys(KEYS + ("parse-failed",), 0)
    for eq_id in cen["confirmed"]:
        tally(inject_latex(doc, eq_id, rng, opts), tex_inj)

    # Is `D-flag` the same event as the front end's N1 rule "the grading dimension drops"?
    # Measured in two modes, because they answer differently and the difference is a
    # finding: an injection that drives a coefficient to zero removes a *symbol* from the
    # document, so a column can vanish and the dimension move with no constraint tightened.
    equiv = {"agree": 0, "disagree": 0}
    equiv_del = {"agree": 0, "disagree": 0}
    rng2 = random.Random(seed + 1)
    for eq_id in doc.eq_ids[:60]:
        mine = doc.rows_of[eq_id]
        cand = [(i, c) for i, r in enumerate(mine) for c in r]
        if not cand:
            continue
        i, c = rng2.choice(cand)
        for delta, box in ((Fraction(2), equiv), (-mine[i][c], equiv_del)):
            if delta == 0:
                continue
            new_rows = [perturb_row(r, c, delta) if j == i else dict(r)
                        for j, r in enumerate(mine)]
            e = explain_equivalence(doc, eq_id, new_rows)
            box["agree" if e["d_flag"] == e["dim_dropped"] else "disagree"] += 1

    # N2 shuffle on this paper — on the grading dimension AND on the census itself, because
    # a confirmed fraction that survives a shuffle is a property of row shapes, not of the
    # symbol identities the paper actually asserts.
    dims, shuf_conf, shuf_rows = [], [], len(s.global_rows)
    for k in range(shuffle_seeds):
        r = random.Random(4000 + k)
        srows = pd.shuffle_rows(s.global_rows, r)
        dims.append(pd.grading_dim(srows)[2])
        if k < 3:
            shuf_conf.append(shuffled_confirmed_fraction(doc, srows))
    dims.sort()

    flags = []
    for eq_id in cen["flagged"]:
        _, bad = doc.verdict(eq_id)
        flags.append({"eq": eq_id, "src": doc.src_of[eq_id],
                      "bad": [{doc.sysm.table.keys[c]: str(v) for c, v in r.items()}
                              for r in bad]})

    strength = collections.Counter(confirm_strength(doc, e) for e in cen["confirmed"])

    return doc, {
        "paper": paper_id,
        "found": s.attempted, "parsed": s.parsed, "with_rows": s.with_rows,
        "rows": len(s.global_rows), "cols": len(cols), "rank": ech.rank,
        "dim": len(cols) - ech.rank, "forced_zero": len(single),
        "multi": len(rich), "powered": len(powered), "macros": len(macros),
        "unfalsifiable": len(cen["unfalsifiable"]),
        "confirmed": len(cen["confirmed"]), "flagged": len(cen["flagged"]),
        "strength": dict(strength),
        "inject_rows": det, "inject_random": rnd, "inject_latex": tex_inj,
        "equiv": equiv, "equiv_deletion": equiv_del,
        "shuffle_median": dims[len(dims) // 2] if dims else 0,
        "shuffle_max": dims[-1] if dims else 0,
        "shuffle_confirmed": shuf_conf,
        "real_confirmed_frac": len(cen["confirmed"]) / max(len(doc.eq_ids), 1),
        "failures": dict(s.failures.most_common()),
        "notes": dict(s.notes.most_common(12)),
        "flags": flags,
    }


SELFTEST_DOC = [
    # A closed little system: every symbol occurs at least twice, so equations are
    # checkable and the verdicts have something to say.
    r"F = m a",
    r"a = \frac{dv}{dt}",
    r"v = \frac{dx}{dt}",
    r"p = m v",
    r"W = F x",
    r"E = \frac{1}{2} m v^2",
    r"P = \frac{dW}{dt}",
    r"E = F x",              # confirmed: implied by W = F x and E ~ m v^2 ... see below
    r"J = F t",              # unfalsifiable: J occurs nowhere else
]


def selftest() -> int:
    g = pd.Gate()
    print("=" * 88)
    print("pdx-arxiv selftest — the verdict machinery, on a corpus whose answer is known")
    print("=" * 88)
    doc = Doc("selftest", SELFTEST_DOC)
    cen = doc.census()
    named = {k: sorted(doc.src_of[e] for e in v) for k, v in cen.items()}
    for k in ("unfalsifiable", "confirmed", "flagged"):
        print(f"  {k:<14} {len(cen[k]):>2}  {named[k]}")

    g.check(r"J = F t" in named["unfalsifiable"],
            "an equation whose symbol occurs nowhere else is unfalsifiable",
            named["unfalsifiable"], "contains J = F t")
    g.check(r"E = F x" in named["confirmed"],
            "a derivable restatement is confirmed by the rest of the document",
            named["confirmed"], "contains E = F x")
    # This pair is the whole false-positive story, asserted rather than discovered later.
    #
    # `W = F x` is *correct physics* and is flagged, because the only other equation
    # mentioning `W` is `P = dW/dt` and `P` is itself fresh — so nothing in the rest of the
    # document pins `W` against `F` and `x`, and the equation genuinely carries independent
    # content. A flag means "adds a constraint among symbols already in play", which is what
    # both an error and new physics look like. The first version of this selftest asserted
    # that a consistent document flags nothing; that expectation was false, and it is pinned
    # here in the true direction so nobody reads a flag as a finding.
    g.check(r"W = F x" in named["flagged"],
            "a CORRECT equation is flagged when the rest of the document does not pin its "
            "symbols — this is the false positive, and it is not a bug",
            named["flagged"], "contains W = F x")
    # ... and the paired positive that can fail: pin `W` and the same equation is confirmed.
    pinned = Doc("pinned", SELFTEST_DOC + [r"E = W"])
    cen2 = pinned.census()
    named2 = {k: sorted(pinned.src_of[e] for e in v) for k, v in cen2.items()}
    g.check(r"W = F x" in named2["confirmed"],
            "adding the link that pins W turns that same flag into a confirmation",
            named2["confirmed"], "contains W = F x")

    print()
    print("  injection into every confirmed equation must be detected:")
    rng = random.Random(1)
    c1 = collections.Counter()
    for eq_id in cen["confirmed"]:
        c1.update(r["status"] for r in inject_rows(doc, eq_id, rng))
    print(f"    {dict(c1)}")
    g.check(c1["miss"] == 0 and c1["hit"] > 0,
            "row-level injection detected on the confirmed set",
            f"{c1['hit']} hit / {c1['miss']} miss", "0 miss")

    print()
    print("  the undetectable class must fire — an equation the document cannot see is a")
    print("  FALSE NEGATIVE and must never be scored as a discard:")
    c2 = collections.Counter()
    for eq_id in cen["unfalsifiable"]:
        c2.update(r["status"] for r in inject_rows(doc, eq_id, rng))
    print(f"    {dict(c2)}")
    g.check(c2["undetectable"] > 0 and c2["hit"] == 0,
            "injection into an unfalsifiable equation is scored undetectable, not neutral",
            dict(c2), "undetectable > 0, hit == 0")

    print()
    print("  D-flag and the front end's `dim drops` must be the same event:")
    agree = dis = 0
    rng2 = random.Random(2)
    for eq_id in doc.eq_ids:
        mine = doc.rows_of[eq_id]
        cand = [(i, c) for i, r in enumerate(mine) for c in r]
        for i, c in cand:
            new_rows = [perturb_row(r, c, Fraction(1)) if j == i else dict(r)
                        for j, r in enumerate(mine)]
            e = explain_equivalence(doc, eq_id, new_rows)
            if e["d_flag"] == e["dim_dropped"]:
                agree += 1
            else:
                dis += 1
                print(f"    DISAGREE {doc.src_of[eq_id]}  {e}")
    print(f"    agree {agree}  disagree {dis}")
    g.check(dis == 0, "D-flag == grading dimension drops, over every single-coefficient "
            "perturbation", f"{agree} agree / {dis} disagree", "0 disagree")

    print()
    print("  a LaTeX-level injection must also be detected:")
    rng3 = random.Random(3)
    c3 = collections.Counter()
    for eq_id in cen["confirmed"]:
        c3.update(r["status"] for r in inject_latex(doc, eq_id, rng3))
    print(f"    {dict(c3)}")
    g.check(c3["hit"] > 0 and c3["miss"] == 0, "LaTeX-level injection detected",
            dict(c3), ">0 hit, 0 miss")

    print()
    print("  the neutral filter must actually fire (else it is not filtering):")
    d2 = Doc("z", [r"\beta = \frac{v}{c}", r"v = \frac{x}{t}", r"c = \frac{x}{t}",
                   r"E = \beta m", r"m = \frac{E}{\beta}"])
    fz = {d2.sysm.table.keys[c] for c in d2.forced_zero()}
    print(f"    forced dimensionless: {sorted(fz)}")
    g.check("\\beta" in fz, "beta = v/c is derived dimensionless", sorted(fz), "beta")
    rngh = random.Random(5)
    c4 = collections.Counter(r["status"] for eq in d2.eq_ids
                             for r in inject_rows(d2, eq, rngh, tries=8))
    print(f"    {dict(c4)}")
    g.check(c4["neutral"] > 0,
            "a perturbation on a forced-dimensionless atom is scored neutral", dict(c4),
            "neutral > 0")
    # The validity test must not be the detector wearing a hat: it reads only the atom.
    g.check(c1["hit"] > 0 and c1["neutral"] == 0,
            "on the mechanics corpus no atom is forced dimensionless, so nothing is "
            "discarded there — the two filters are independent",
            dict(c1), "neutral == 0")

    print()
    print(f"{'=' * 88}\n{g.checks - len(g.fails)}/{g.checks} checks passed")
    print("SELFTEST PASS" if not g.fails else "SELFTEST FAIL")
    return 1 if g.fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir")
    ap.add_argument("--out")
    ap.add_argument("--flags", action="store_true")
    ap.add_argument("--paren", choices=["apply", "product"], default="apply")
    ap.add_argument("--sample", type=int, default=40)
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.dir:
        ap.error("--dir or --selftest")

    opts = {"paren": args.paren, "delta": "transparent"}
    results, docs = [], []
    hdr = (f"{'paper':<12}{'eqs':>6}{'pars':>6}{'rate':>7}{'rows':>6}{'cols':>6}"
           f"{'rank':>6}{'dim':>5}{'unfal':>7}{'conf':>6}{'flag':>6}{'shuf':>6}")
    print(hdr)
    print("-" * len(hdr))
    for path in sorted(glob.glob(os.path.join(args.dir, "*.tex"))):
        doc, r = analyse(path, opts, sample=args.sample)
        docs.append(doc)
        results.append(r)
        rate = r["parsed"] / max(r["found"], 1)
        print(f"{r['paper']:<12}{r['found']:>6}{r['parsed']:>6}{rate:>6.0%}"
              f"{r['rows']:>7}{r['cols']:>6}{r['rank']:>6}{r['dim']:>5}"
              f"{r['unfalsifiable']:>7}{r['confirmed']:>6}{r['flagged']:>6}"
              f"{r['shuffle_median']:>6}")
        if args.flags:
            for f in r["flags"]:
                print(f"      FLAG {f['eq']}  {f['src'][:150]}")
                for b in f["bad"]:
                    print(f"           residual not implied: {b}")

    tot = collections.Counter()
    for r in results:
        for k in ("found", "parsed", "with_rows", "rows", "unfalsifiable",
                  "confirmed", "flagged"):
            tot[k] += r[k]
        for grp in ("inject_rows", "inject_random", "inject_latex", "equiv",
                    "equiv_deletion", "strength"):
            for k, v in r[grp].items():
                tot[f"{grp}.{k}"] += v
    print()
    print(f"TOTAL found {tot['found']}  parsed {tot['parsed']} "
          f"({tot['parsed'] / max(tot['found'], 1):.1%})  "
          f"with-rows {tot['with_rows']} ({tot['with_rows'] / max(tot['found'], 1):.1%})")
    ry = tot["unfalsifiable"] + tot["confirmed"] + tot["flagged"]
    print(f"row-yielding equations {ry}   unfalsifiable {tot['unfalsifiable']} "
          f"({tot['unfalsifiable'] / max(ry, 1):.1%})   confirmed {tot['confirmed']} "
          f"({tot['confirmed'] / max(ry, 1):.1%})   flagged {tot['flagged']} "
          f"({tot['flagged'] / max(ry, 1):.1%})")
    print(f"confirmation strength: " + "  ".join(
        f"{k} {tot['strength.' + k]}" for k in ("single-atom", "restatement", "derived")))
    print()
    print(f"{'injection experiment':<40}{'hit':>6}{'miss':>6}{'undet':>7}"
          f"{'neutral':>9}{'det%':>7}{'cover%':>8}")
    for grp, label in (("inject_rows", "row-level, confirmed equations"),
                       ("inject_random", "row-level, random equation"),
                       ("inject_latex", "LaTeX-level, confirmed equations")):
        h, mi = tot[f"{grp}.hit"], tot[f"{grp}.miss"]
        un, ne = tot[f"{grp}.undetectable"], tot[f"{grp}.neutral"]
        real = h + mi + un
        print(f"{label:<40}{h:>6}{mi:>6}{un:>7}{ne:>9}"
              f"{h / max(h + mi, 1):>7.0%}{h / max(real, 1):>8.0%}")
    print(f"  det% = hits among injections the document could see at all;  "
          f"cover% = hits among ALL genuine injections")
    if tot["inject_latex.parse-failed"]:
        print(f"  LaTeX-level injections the parser then refused: "
              f"{tot['inject_latex.parse-failed']}")
    print()
    print(f"D-flag == 'grading dim drops': exponent-changing injections  "
          f"agree {tot['equiv.agree']}  disagree {tot['equiv.disagree']}")
    print(f"                               symbol-DELETING injections     "
          f"agree {tot['equiv_deletion.agree']}  "
          f"disagree {tot['equiv_deletion.disagree']}")
    sc = [x for r in results for x in r["shuffle_confirmed"]]
    rc = [r["real_confirmed_frac"] for r in results]
    if sc:
        print(f"N2 census control: real confirmed fraction "
              f"{sum(rc) / len(rc):.1%} (mean over papers)  vs shuffled "
              f"{sum(sc) / len(sc):.1%} (3 seeds x {len(results)} papers)")
    fell = sum(1 for r in results
               if r["rows"] and r["shuffle_median"] < r["dim"])
    have = sum(1 for r in results if r["rows"])
    print(f"N2 grading control: shuffled median dimension below real in "
          f"{fell}/{have} papers with rows")

    # The control the shuffle cannot be: confirm each paper's equations against a DIFFERENT
    # paper. Two foreign partners per paper, chosen by rotation so every paper is used.
    fc = ft = 0
    per = []
    for i, d in enumerate(docs):
        c = t = 0
        for j in (1, 7):
            other = docs[(i + j) % len(docs)]
            if other is d:
                continue
            a, b = foreign_census(d, other)
            c += a
            t += b
        fc += c
        ft += t
        own = results[i]["confirmed"]
        ownt = (results[i]["confirmed"] + results[i]["flagged"])
        per.append((d.paper_id, own / max(ownt, 1), c / max(t, 1)))
    print(f"FOREIGN control: equations confirmed by a different paper's rows "
          f"{fc}/{ft} = {fc / max(ft, 1):.1%}   "
          f"vs by their own paper {tot['confirmed']}/"
          f"{tot['confirmed'] + tot['flagged']} = "
          f"{tot['confirmed'] / max(tot['confirmed'] + tot['flagged'], 1):.1%}")
    worse = sum(1 for _, o, f in per if f < o)
    print(f"                 own > foreign in {worse}/{len(per)} papers")

    if args.out:
        json.dump(results, open(args.out, "w"), indent=1)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
