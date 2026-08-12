#!/usr/bin/env -S uv run --no-sync python
"""Dimensional analysis as a latent structure recoverable from statement shape.

Run:  uv run --no-sync scripts/phys-dimensional.py --slice /tmp/atlas-physlib-closure.jsonl \
          --control /tmp/mathlib-algebra.jsonl

===========================================================================
WHAT A GOOD ANSWER LOOKS LIKE — written before the first run, not after
===========================================================================

The question is whether the Atlas can recover a *dimensional signature* for a declaration
from the shape of its statement, without being told which constant means "metre". Four
experiments, each with the outcome that would show the method does not work.

E1 — DISCOVER THE DIMENSION TYPE, STRUCTURALLY
    A dimension type has a signature nothing else in a library has: it is a `CommGroup`
    whose *elements appear as arguments to type constructors*. That is what a grading is.
    Ranking every type constant in the corpus by that signature should put physlib's
    `Dimension` first.
    WORKS:      the top-ranked grading carrier is a type whose elements index other types,
                and it is `Dimension` (checked by name only after the ranking is fixed).
    FAILS:      the ranking is led by something with no group structure, or `Dimension` is
                not in the top five — the signature is not discriminative.

E2 — RECOVER A GRADING FROM EQUATIONS ALONE
    Every `Eq` and every `+` in the corpus is a linear constraint on the unknown exponent
    vectors of the constants it mentions: `*` adds, `/` subtracts, `^n` scales, `+` forces
    equality. Solve the whole system over ℚ. Local (bound) variables are eliminated per
    declaration, leaving a system over the *global* constants.
    WORKS:      the connected global constants number in the hundreds, the derived relations
                number in the dozens, and the relations read as dimensional facts —
                `speed = length - time` and not `x = x`.
    FAILS:      (a) the global system has rank 0 — every equation is dimensionally
                self-contained and nothing is tied to anything, which is what a corpus of
                pure algebra should give; or (b) the same pipeline on the Mathlib control
                produces a comparable rank, in which case we are measuring the algebraic
                hierarchy and not physics; or (c) the grading space collapses to dimension
                0 or 1, meaning the corpus's own equations say every quantity is the same
                dimension, which is a bug not a finding.

E3 — IS THE RECOVERED STRUCTURE REDUNDANT, OR JUST TRANSCRIBED?
    A grading learned from equations is only interesting if it *predicts*. Hold out a random
    tenth of the global rows, fit on the rest, and ask how many held-out rows are already
    implied. An implied row is an equation whose dimensional content the rest of the corpus
    already determined.
    WORKS:      the implication rate is well above the shuffled control, where every atom is
                replaced by a uniformly random atom from the same pool.
    FAILS:      the rate matches the shuffle, or is ~0 — in which case each equation is its
                own island and "recovering dimensions" means transcribing definitions.

    AS RUN, THIS DESIGN IS CONFOUNDED and the confound is left in place with its diagnosis
    rather than edited out. A fitted system whose rank equals its atom count has only the
    zero grading left, so *every* row is implied vacuously — and random rewiring is exactly
    what saturates a system. The shuffled control therefore scores ~99% for the opposite of
    the reason the test assumed. The fit's surviving grading dimension is printed beside the
    rate; read the two together or not at all.

E4 — HOMOGENEITY: CAN A DIMENSIONAL ERROR BE DETECTED AT ALL?
    A tool that says everything is fine is worse than no tool. So: inject equations that are
    dimensionally false by construction (identify two atoms the solver had kept independent)
    and check the diagnostic fires. Then run the same diagnostic on the untouched corpus.
    WORKS:      every injected row is detected, and the count on the real corpus is reported
                whatever it is.
    FAILS:      injections are not detected — the check is decorative and no statement about
                physlib's homogeneity can be made from it.

E5 — DOES DIMENSIONAL AGREEMENT PREDICT ANALOGY?
    Prediction, registered in advance: **no, and it should be anti-predictive.** The units
    API replicated across `LengthUnit`/`TimeUnit`/`MassUnit`/`ChargeUnit`/`TemperatureUnit`
    (findings §3c) is the corpus's clearest family of genuine analogues, and its members
    have *different* dimensions by construction. If dimensional agreement scored analogy
    well it would be measuring something other than what it claims to.
    WORKS (as a negative): retention separates analogue pairs from random pairs and
                dimensional agreement does not, so the two signals are orthogonal and
                dimension belongs in a filter, not in a ranking.
    FAILS:      dimensional agreement beats retention — which would be a real finding and
                would mean the prediction above is wrong.

E6 — DO DECLARATIONS CLUSTER BY THE QUANTITY CONSTANTS THEY MENTION?
    And is that clustering different from module structure?
    WORKS:      pairs sharing informative atoms are same-subfield far above the random-pair
                base rate, and the label shuffle does not reproduce it.
    FAILS:      the enrichment survives a label shuffle, in which case it is subfield sizes.

===========================================================================
WHICH EXPERIMENTS NEED A CLOSED SLICE, AND WHICH DO NOT
===========================================================================

This decides what is reportable from an unclosed corpus, so it is stated rather than assumed.

* **E1 and (naively) E5 need one.** E1 reads each constant's own type row to decide what is
  `Dimension`-valued and what is a type former; a missing row is invisible to it, which can
  only make its ranking under-inclusive. E5 is written to *avoid* the dependency: it scores
  with `Corpus.generalize`, which anti-unifies the encodings without erasing, and validates
  its ground truth with `phys_i3.shape_key` rather than `Corpus.skeleton`.
* **E2, E3, E4 and E6 do not.** They read statement trees and nothing else — no constant
  signature is looked up, no citation is followed — so their answer over a given set of
  declarations does not depend on whether the slice also holds that set's foundation.

===========================================================================
CONSTRAINTS THIS SCRIPT HOLDS ITSELF TO
===========================================================================

* **Closure gate.** Two implementations: `Corpus.closure()` over the whole slice, and a
  Python walk over the parsed trees. Either below 95% exits non-zero. An unclosed slice
  degrades every erasure query silently (CLAUDE.md §7, findings §31-32), and a check with one
  implementation shares its blind spots — §32's Rust counter read 0 on every corpus ever
  built because it tested the root's head, and a statement's root is a `Pi`.
* **No name is a semantic oracle.** The solver's only by-name input is Lean's algebraic
  vocabulary (`HMul.hMul`, `HAdd.hAdd`, …) — the same 20-odd names for the physics corpus
  and for the Mathlib control. Names appear afterwards, in the report and in checking a
  ground truth that was built structurally.
* **Every filter has a control.** The statement-size cap, the atom keying and the "connected
  atoms" restriction each report what they drop, and the keying has an ablation
  (`--keying coarse`) that reproduces the collapse the fine keying exists to prevent.
* **Measured numbers only.** Everything printed is computed by this run.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
import time
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.setrecursionlimit(20000)

import phys_i3 as i3                                             # noqa: E402
from phys_dimlib import (AtomTable, Echelon, Extractor,          # noqa: E402
                         eliminate_locals)

CLOSURE_FLOOR = 0.95

# Structures whose presence marks a type as a candidate grading carrier. Lean/Mathlib
# vocabulary; nothing physical.
GROUP_CLASSES = {"Mul", "CommGroup", "Group", "CommMonoid", "Monoid", "Inv", "Div",
                 "DivisionRing", "One"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_rows(path, cap, only_prefix=None, only_module=None):
    """Read a slice, keeping *encodings* rather than trees. Returns `(rows, stats, dropped)`.

    Trees are built per pass by `trees()` and thrown away. Holding them costs 20-50x the
    encoding's bytes, which is affordable for the 553 MB of physics statements exactly once
    and not four times, and not at all for a Mathlib-sized closure.

    `cap` bounds the encoding's byte length. Physlib's size distribution is extreme — median
    1.5 kB, but 674 of 14,576 rows hold 81% of the bytes, all of them Lorentz-tensor and
    distributional-EM computations — so an uncapped Python tree walk is dominated by a
    handful of declarations. What the cap drops is reported, never assumed harmless.
    """
    rows = []
    stats = collections.Counter()
    dropped_modules = collections.Counter()
    t0 = time.time()
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            stats["rows"] += 1
            name = r.get("name", "")
            if only_prefix and not any(name.startswith(p) for p in only_prefix):
                stats["out_of_scope"] += 1
                continue
            # Module rather than name: physlib's unit API is declared at the top level
            # (`LengthUnit.days_div_hours`), so a name filter would drop exactly the family
            # E5 needs while a module filter keeps it.
            if only_module and not any(r.get("module", "").startswith(m)
                                       for m in only_module):
                stats["out_of_scope"] += 1
                continue
            s = r.get("stmt")
            if not s:
                stats["no_stmt"] += 1
                continue
            if len(s) > cap:
                stats["over_cap"] += 1
                dropped_modules[r.get("module", "?")] += 1
                continue
            # Parsed once here and thrown away, so that a row every later pass would skip is
            # counted at the door rather than silently vanishing from four measurements.
            try:
                i3.parse(s)
            except (ValueError, IndexError, RecursionError):
                stats["parse_failed"] += 1
                continue
            rows.append((name, r.get("module", ""), r.get("kind", ""), s))
            stats["kept"] += 1
    stats["seconds"] = round(time.time() - t0, 1)
    stats["bytes"] = sum(len(r[3]) for r in rows)
    return rows, stats, dropped_modules


def trees(rows):
    """Parse each kept row on demand. Every row here parsed once already, at load."""
    for name, module, kind, s in rows:
        yield name, module, kind, i3.parse(s)


def all_names(path):
    """Every declaration name in the slice, without parsing a single statement."""
    names = set()
    with open(path) as f:
        for line in f:
            i = line.find('"name":"')
            if i < 0:
                names.add(json.loads(line).get("name", ""))
            else:
                j = line.index('"', i + 8)
                names.add(line[i + 8:j])
    return names


def python_closure(rows, names, top=8):
    """The closure check, computed by a second implementation over the parsed trees.

    `Corpus.closure` is the authority; this exists because a check with one implementation
    is a check that shares its blind spots (findings §32 — the Rust counter read 0 on every
    corpus ever built, because it tested the *root's* head and a statement's root is a `Pi`).
    Two algorithms that disagree is a finding; one that runs alone is a hope.
    """
    known = unknown = 0
    misses = collections.Counter()
    for _n, _m, _k, tree in trees(rows):
        for h, _args in i3.iter_spines(tree):
            cn = i3.const_name(h)
            if cn is None:
                continue
            if cn in names:
                known += 1
            else:
                unknown += 1
                misses[cn] += 1
    cov = known / (known + unknown) if (known + unknown) else 1.0
    return known, unknown, cov, misses.most_common(top)


# ---------------------------------------------------------------------------
# E1 — discover the grading carrier
# ---------------------------------------------------------------------------

def e1_discover(rows):
    """Rank type constants by the structural signature of a dimension.

    Two properties, both read off statements:
      1. the type carries a multiplicative-group structure — some declaration's conclusion
         is `Mul (T …)` or `CommGroup (T …)`;
      2. its elements *index other types* — some type-former constant is applied to an
         argument headed by a `T`-valued constant.
    Property 2 is what separates a dimension from every other `CommGroup` in the library.
    """
    concl = {}
    group_on = collections.defaultdict(set)
    for name, _mod, _kind, tree in trees(rows):
        _, body = i3.pi_telescope(tree)
        h, args = i3.spine(body)
        cn = i3.const_name(h)
        concl[name] = ("*Prop*" if h[1] == "0" else "*Type*") if h[0] == "s" else cn
        if cn in GROUP_CLASSES and args:                       # 1. group structure
            th, _ = i3.spine(args[0])
            tn = i3.const_name(th)
            if tn:
                group_on[tn].add(cn)

    # Type formers: constants whose own type concludes in a *data* sort. `Prop` is excluded
    # on purpose. Without the split `Eq`, `LE.le` and `LT.lt` count as type constructors,
    # every carrier in the library then looks like a grading, and the Mathlib control
    # produced eight candidates instead of the one it should.
    sort_valued = {n for n, h in concl.items() if h == "*Type*"}

    # 2. elements used as type indices
    valued_in = collections.defaultdict(set)
    for n, h in concl.items():
        if h and not h.startswith("*"):
            valued_in[h].add(n)
    owner = {}
    for T, members in valued_in.items():
        for m in members:
            owner[m] = T

    indexes = collections.defaultdict(lambda: collections.Counter())
    for _name, _mod, _kind, tree in trees(rows):
        for h, args in i3.iter_spines(tree):
            cn = i3.const_name(h)
            if cn not in sort_valued:
                continue
            for a in args:
                ah, _ = i3.spine(a)
                T = owner.get(i3.const_name(ah))
                if T and T != cn:
                    indexes[T][cn] += 1

    # A dimension algebra needs *inverses*: `T⁻¹` is a dimension, so the exponents form a
    # group and not a monoid. Reported as its own column because it is what separates the
    # two corpora — Mathlib's only candidate is `Nat`, whose structure stops at `Monoid`.
    ranked = []
    for T, formers in indexes.items():
        if T not in group_on:
            continue
        inv = bool(group_on[T] & {"CommGroup", "Group", "Inv"})
        ranked.append((inv, len(formers), sum(formers.values()), T,
                       sorted(group_on[T]), formers.most_common(4)))
    ranked.sort(reverse=True)
    return ranked, concl, valued_in, sort_valued


def e1_decode(rows, T, valued_in, sort_valued):
    """Evaluate every `T`-valued subterm as a vector in the free abelian group on generators.

    The generators are discovered, not named: they are the `T`-valued constants that survive
    as leaves once `*`, `/`, `⁻¹` and `^n` have been interpreted. So `WithDim (L𝓭 * T𝓭⁻¹) ℝ`
    decodes to `{L𝓭: 1, T𝓭: -1}` without the decoder knowing that `L𝓭` is a length.
    """
    from phys_dimlib import DIV, INV, MUL, POW, _nat_literal

    members = valued_in.get(T, set())

    def value(e, depth=0):
        h, args = i3.spine(e)
        n = i3.const_name(h)
        if n in MUL and len(args) >= 2:
            return _vadd(value(args[-2]), value(args[-1]))
        if n in DIV and len(args) >= 2:
            return _vsub(value(args[-2]), value(args[-1]))
        if n in INV and args:
            return _vscale(value(args[-1]), -1)
        if n in POW and len(args) >= 2:
            k = _nat_literal(args[-1])
            return _vscale(value(args[-2]), k) if k is not None else None
        if n in ("One.one", "OfNat.ofNat"):
            return {}
        if n in members:
            return {n: Fraction(1)}
        return None

    ops = MUL | DIV | INV | POW
    annotated = {}         # decl -> list of (former, vector)
    for name, _mod, _kind, tree in trees(rows):
        found = []
        for h, args in i3.iter_spines(tree):
            if i3.const_name(h) not in sort_valued:
                continue
            cn = i3.const_name(h)
            for a in args:
                ah, _ = i3.spine(a)
                an = i3.const_name(ah)
                if an in members or an in ops:
                    v = value(a)
                    if v is not None:
                        found.append((cn, tuple(sorted(v.items()))))
        if found:
            annotated[name] = found
    return annotated


def _vadd(a, b):
    if a is None or b is None:
        return None
    r = dict(a)
    for k, v in b.items():
        nv = r.get(k, 0) + v
        if nv:
            r[k] = nv
        else:
            r.pop(k, None)
    return r


def _vsub(a, b):
    return _vadd(a, _vscale(b, -1)) if b is not None else None


def _vscale(a, f):
    if a is None:
        return None
    return {k: v * f for k, v in a.items()} if f else {}


# ---------------------------------------------------------------------------
# E2 — the grading solver
# ---------------------------------------------------------------------------

def shuffle_rows(global_rows, rng):
    """The negative control: rewire the atoms, keep every row's shape.

    Applied to the rows the real run already produced rather than by re-extracting, so the
    control is *exactly* the same system with different labels and costs no second pass over
    553 MB of statements. It answers "would a corpus with this arithmetic and random wiring
    look like this?".
    """
    pool = sorted({c for r in global_rows for c in r})
    out = []
    for r in global_rows:
        m, acc = {}, {}
        for c, v in r.items():
            if c not in m:
                m[c] = rng.choice(pool)
            acc[m[c]] = acc.get(m[c], Fraction(0)) + v
        out.append({k: v for k, v in acc.items() if v})
    return out


def build_system(rows, keying="fine", literals="dimensionless", limit=None):
    """Every declaration's rows, projected onto global atoms."""
    table = AtomTable()
    ex = Extractor(table, keying=keying, literals=literals)
    global_rows = []
    provenance = []
    stats = collections.Counter()
    for name, _mod, _kind, tree in trees(rows):
        if limit and len(global_rows) >= limit:
            break
        ex.reset(name, tree)
        try:
            ex.scan(tree, 0)
        except RecursionError:
            stats["recursion"] += 1
            continue
        if not ex.rows:
            continue
        stats["decls_with_rows"] += 1
        stats["raw_rows"] += len(ex.rows)
        stats["opaque"] += ex.opaque
        stats["decomposed"] += ex.decomposed
        gr = eliminate_locals(ex.rows, lambda c: table.is_local[c])
        for r in gr:
            global_rows.append(r)
            provenance.append(name)
        stats["global_rows"] += len(gr)
    return table, global_rows, provenance, stats


def solve(table, global_rows):
    ech = Echelon(order=lambda c: table.keys[c])
    for r in global_rows:
        ech.add(r)
    connected = ech.columns()
    return ech, connected


# ---------------------------------------------------------------------------
# reporting helpers
# ---------------------------------------------------------------------------

def short(key, width=58):
    return key if len(key) <= width else key[:width] + "…"


def _coef(v):
    if v == 1:
        return "+ "
    if v == -1:
        return "- "
    return ("+ " if v > 0 else "- ") + str(abs(v)) + "*"


def render_relation(table, col, row, width=3):
    """A pivot row read as `atom = combination of the others` — a derived dimensional fact."""
    terms = [f"{_coef(-v)}{short(table.keys[c], 44)}"
             for c, v in sorted(row.items(), key=lambda kv: table.keys[kv[0]]) if c != col]
    if not terms:
        return f"{short(table.keys[col])} = 0"
    body = " ".join(terms[:width]) + ("" if len(terms) <= width else f" … (+{len(terms) - width})")
    return f"{short(table.keys[col])} = " + body.lstrip("+ ")


def banner(s):
    print()
    print("=" * 78)
    print(s)
    print("=" * 78)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice")
    ap.add_argument("--selftest", action="store_true",
                    help="run the synthetic corpus whose answer is known; exit non-zero on "
                         "failure. Needs no slice.")
    ap.add_argument("--control", default=None,
                    help="a corpus with no dimensional content; the Mathlib algebra slice")
    ap.add_argument("--cap", type=int, default=200000)
    ap.add_argument("--module", default=None,
                    help="comma-separated module prefixes to keep, e.g. "
                         "`Physlib,QuantumInfo`. Use this rather than --prefix on a "
                         "closure: it selects what the library authored.")
    ap.add_argument("--prefix", default=None,
                    help="comma-separated name prefixes to keep. A filter, so what it "
                         "drops is counted and printed; the closure gate still runs over "
                         "the whole slice.")
    ap.add_argument("--keying", default="fine", choices=("fine", "coarse"))
    ap.add_argument("--literals", default="dimensionless", choices=("dimensionless", "free"))
    ap.add_argument("--skip-closure", action="store_true",
                    help="for prototyping only; the run reports that it was skipped")
    ap.add_argument("--experiments", default="1,2,3,4,5,6")
    ap.add_argument("--seed", type=int, default=20260803)
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.slice:
        ap.error("--slice is required unless --selftest")
    want = set(args.experiments.split(","))
    rng = random.Random(args.seed)

    # ---- parse ----------------------------------------------------------
    banner("parsing statements into trees")
    prefixes = tuple(p for p in (args.prefix or "").split(",") if p) or None
    modules = tuple(m for m in (args.module or "").split(",") if m) or None
    rows, stats, dropped = load_rows(args.slice, args.cap, prefixes, modules)
    print(f"rows {stats['rows']:,}  kept {stats['kept']:,} ({stats['bytes'] / 1e6:.0f} MB "
          f"of encoding)  no-stmt {stats['no_stmt']:,}  over-cap {stats['over_cap']:,}  "
          f"out-of-scope {stats['out_of_scope']:,}  parse-failed "
          f"{stats['parse_failed']:,}  [{stats['seconds']}s]")
    if dropped:
        print("  cap dropped, by module (top 6):", dropped.most_common(6))

    results = {}

    # ---- E0: the closure gate -------------------------------------------
    banner("E0 — closure gate")
    print(f"slice  {args.slice}")
    t0 = time.time()
    names = all_names(args.slice)
    pk, pu, pcov, pworst = python_closure(rows, names)
    print(f"[python, over the {stats['kept']:,} rows measured below, against all "
          f"{len(names):,} names in the slice]")
    print(f"  heads     known {pk:,}  unknown {pu:,}")
    print(f"  coverage  {pcov:.4%}   floor {CLOSURE_FLOOR:.0%}   [{time.time() - t0:.0f}s]")
    print(f"  worst     {pworst}")
    results["closure_python"] = pcov
    if args.skip_closure:
        print("\n`Corpus.closure` SKIPPED by flag — prototyping only.")
    else:
        import atlas as fa
        t0 = time.time()
        c = fa.Corpus.load(args.slice)
        known, unknown, cov, worst = c.closure(top=8)
        print(f"[Corpus.closure, over the whole slice]")
        print(f"  declarations {len(c):,}   (loaded in {time.time() - t0:.1f}s)")
        print(f"  heads     known {known:,}  unknown {unknown:,}")
        print(f"  coverage  {cov:.4%}")
        print(f"  worst     {worst}")
        results["closure_rust"] = cov
        del c
        if cov < CLOSURE_FLOOR:
            print("\nREFUSING: an unclosed slice degrades every erasure query silently.")
            sys.exit(1)
    if pcov < CLOSURE_FLOOR and not args.skip_closure:
        print("\nREFUSING: the independent check puts the measured subcorpus below the "
              "floor, whatever the whole slice scores.")
        sys.exit(1)

    ctrl_rows = None
    if args.control:
        ctrl_rows, cstats, _ = load_rows(args.control, args.cap, None)
        print(f"\ncontrol: rows {cstats['rows']:,}  kept {cstats['kept']:,}  "
              f"over-cap {cstats['over_cap']:,}  [{cstats['seconds']}s]")

    # ---- E1 --------------------------------------------------------------
    annotated, T = {}, None
    if "1" in want:
        banner("E1 — discovering the grading carrier, structurally")
        ranked, concl, valued_in, sort_valued = e1_discover(rows)
        print(f"{'inv':>4} {'formers':>8} {'uses':>8}  type                  group structure")
        for k, (inv, nf, uses, Tname, gs, ex) in enumerate(ranked[:8]):
            print(f"{'yes' if inv else 'no':>4} {nf:>8} {uses:>8}  {Tname:<21} "
                  f"{','.join(gs[:4])}")
            if k < 3:
                print(f"{'':>23}  indexed by: {[e[0] for e in ex]}")
        if ranked:
            T = ranked[0][3]
            print(f"\ntop-ranked grading carrier: {T}")
            annotated = e1_decode(rows, T, valued_in, sort_valued)
            sigs = collections.Counter()
            for _n, fs in annotated.items():
                for _former, v in fs:
                    sigs[v] += 1
            print(f"declarations carrying a decodable {T} annotation: {len(annotated):,}")
            print(f"distinct signatures: {len(sigs)}")
            for v, k in sigs.most_common(12):
                pretty = " * ".join(f"{n}^{e}" for n, e in v) if v else "(dimensionless)"
                print(f"  {k:>5}  {pretty}")
        results["e1"] = {"top": T, "annotated": len(annotated)}

    # ---- E2 --------------------------------------------------------------
    if want & {"2", "3", "4", "5", "6"}:
        banner("E2 — recovering a grading from equations alone")
        t0 = time.time()
        table, grows, prov, sstats = build_system(rows, keying=args.keying,
                                                  literals=args.literals)
        ech, connected = solve(table, grows)
        elapsed = time.time() - t0
        n_global = sum(1 for i in range(len(table)) if not table.is_local[i])
        print(f"declarations contributing rows   {sstats['decls_with_rows']:,}")
        print(f"raw rows                         {sstats['raw_rows']:,}")
        print(f"rows after local elimination     {sstats['global_rows']:,}")
        print(f"arithmetic nodes decomposed      {sstats['decomposed']:,}")
        print(f"subterms left opaque             {sstats['opaque']:,}")
        print(f"global atoms seen                {n_global:,}")
        print(f"connected global atoms |C|       {len(connected):,}")
        print(f"rank r                           {ech.rank:,}")
        print(f"grading space dim on C           {len(connected) - ech.rank:,}")
        print(f"[{elapsed:.1f}s]")

        singleton = [c for c, r in ech.pivots.items() if len(r) == 1]
        pairs = [(c, r) for c, r in ech.pivots.items() if len(r) == 2]
        print(f"\nforced dimensionless             {len(singleton):,}")
        print(f"forced equal to one other atom   {len(pairs):,}")
        print(f"genuine multi-atom relations     {ech.rank - len(singleton) - len(pairs):,}")

        print("\nsample derived relations (multi-atom, sorted by atom name):")
        rich = [(c, r) for c, r in ech.pivots.items() if len(r) >= 3]
        rich.sort(key=lambda cr: table.keys[cr[0]])
        for c, r in rich[:18]:
            print("  " + render_relation(table, c, r))

        # Relations that share a coefficient pattern are the same *dimensional* law written
        # over different quantities — `speed = length - time` and `current = charge - time`
        # differ only in which atoms fill the slots. This is the analogy E5 asks about,
        # visible here without any ranking.
        shapes = collections.Counter()
        witness = {}
        for c, r in rich:
            pat = tuple(sorted((str(-v) for k, v in r.items() if k != c)))
            shapes[pat] += 1
            witness.setdefault(pat, (c, r))
        print("\nrelation shapes (a shape shared by many relations is one dimensional law "
              "instantiated many times):")
        for pat, k in shapes.most_common(8):
            c, r = witness[pat]
            print(f"  {k:>5} x  coefficients {list(pat)}   e.g. {render_relation(table, c, r)}")

        # A *dimensional* law carries powers: `v²`, `r³`, `1/T²`. An algebraic rearrangement
        # does not — moving terms across an `=` only ever produces ±1. So the fraction of
        # relations with a coefficient outside {+1, -1} separates recovered physics from
        # recovered bookkeeping, and it is the number to compare across corpora rather than
        # the raw relation count.
        powered = sum(1 for _c, r in rich if any(abs(v) != 1 for v in r.values()))
        print(f"\nmulti-atom relations with a coefficient outside +/-1: {powered} of "
              f"{len(rich)}" + (f" ({powered / len(rich):.1%})" if rich else ""))
        results["e2_shapes"] = {"distinct": len(shapes), "rich": len(rich),
                                "powered": powered,
                                "largest": shapes.most_common(3)}

        # The equivalence classes the corpus forces: `a - b = 0` rows, closed under
        # transitivity. This *is* the dimension signature as a partition — two constants in
        # one class must carry the same dimension whatever that dimension turns out to be.
        parent = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        joined = 0
        for c, r in pairs:
            (a, va), (b, vb) = sorted(r.items())
            if va + vb == 0:                 # a - b = 0, not a + b = 0
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
                    joined += 1
        classes = collections.defaultdict(list)
        for a in list(parent):
            classes[find(a)].append(a)
        sizes = sorted((len(v) for v in classes.values()), reverse=True)
        print(f"\nforced-equal classes: {len(classes):,} classes over "
              f"{sum(sizes):,} atoms  (largest {sizes[:8]})")
        big = sorted(classes.values(), key=len, reverse=True)[:3]
        for cl in big:
            print("  class of "
                  f"{len(cl)}: " + ", ".join(short(table.keys[a], 34) for a in sorted(cl)[:4]))
        results["e2_classes"] = {"classes": len(classes), "atoms": sum(sizes),
                                 "largest": sizes[:8]}

        results["e2"] = {"C": len(connected), "rank": ech.rank,
                         "dim": len(connected) - ech.rank}

        # -- the keying ablation: the collapse the fine keying prevents ----
        if args.keying == "fine":
            tb2, gr2, _p2, _s2 = build_system(rows, keying="coarse",
                                              literals=args.literals)
            e2, c2 = solve(tb2, gr2)
            print(f"\nablation --keying coarse: |C| {len(c2):,}  rank {e2.rank:,}  "
                  f"grading dim {len(c2) - e2.rank:,}")
            print("  (head-only atoms identify `single .length` with `single .time`; the "
                  "grading dimension is the number the collapse destroys)")
            results["e2_coarse"] = {"C": len(c2), "rank": e2.rank,
                                    "dim": len(c2) - e2.rank}

        # -- the shuffle control ------------------------------------------
        # Same rows, same shapes, atoms rewired at random. A corpus whose equations carry
        # dimensional content keeps a large grading space; one whose wiring is noise forces
        # everything to zero, because random rows saturate the rank.
        grs = shuffle_rows(grows, rng)
        es, cs = solve(table, grs)
        rich_s = sum(1 for r in es.pivots.values() if len(r) >= 3)
        print(f"\ncontrol, atoms shuffled: |C| {len(cs):,}  rank {es.rank:,}  "
              f"grading dim {len(cs) - es.rank:,}  multi-atom relations {rich_s:,}")
        results["e2_shuffled"] = {"C": len(cs), "rank": es.rank,
                                  "dim": len(cs) - es.rank, "rich": rich_s}

        # -- the Mathlib control ------------------------------------------
        if ctrl_rows is not None:
            tb3, gr3, _p3, s3 = build_system(ctrl_rows, keying=args.keying,
                                             literals=args.literals)
            e3, c3 = solve(tb3, gr3)
            print(f"\ncontrol ({os.path.basename(args.control)}): decls {s3['decls_with_rows']:,}"
                  f"  rows {s3['global_rows']:,}  |C| {len(c3):,}  rank {e3.rank:,}"
                  f"  grading dim {len(c3) - e3.rank:,}")
            sing3 = sum(1 for r in e3.pivots.values() if len(r) == 1)
            print(f"  forced dimensionless: {sing3:,} of {e3.rank:,} pivots "
                  f"({sing3 / max(e3.rank, 1):.1%})")
            results["e2_control"] = {"C": len(c3), "rank": e3.rank,
                                     "dim": len(c3) - e3.rank,
                                     "forced_zero_frac": sing3 / max(e3.rank, 1)}

    # ---- E3 --------------------------------------------------------------
    if "3" in want:
        banner("E3 — is the grading redundant, or just transcribed?")

        print("The raw implication rate turned out to be uninformative and the reason is "
              "reported rather than hidden: when the fitted system saturates — rank equal "
              "to its atom count — the only grading is the zero one and *every* row is\n"
              "implied. That is exactly what the shuffled control does, so a high rate "
              "there is a collapse and not a prediction. The columns that matter are the "
              "fit's surviving grading dimension and the rate on multi-atom rows.")

        def holdout(rows_in, tag):
            idx = list(range(len(rows_in)))
            rng.shuffle(idx)
            k = max(1, len(idx) // 10)
            test = set(idx[:k])
            fit = Echelon()
            for i, r in enumerate(rows_in):
                if i not in test:
                    fit.add(r)
            seen = fit.columns()
            fit_dim = len(seen) - fit.rank
            implied = covered = uncovered = 0
            rich_cov = rich_imp = 0
            for i in sorted(test):
                r = rows_in[i]
                if not r:
                    continue
                if not all(c in seen for c in r):
                    uncovered += 1
                    continue
                covered += 1
                ok = fit.implies(r)
                implied += ok
                if len(r) >= 3:
                    rich_cov += 1
                    rich_imp += ok
            rate = implied / covered if covered else float("nan")
            rrate = rich_imp / rich_cov if rich_cov else float("nan")
            print(f"{tag:<26} fit rank {fit.rank:>6,}/{len(seen):>6,}  fit grading dim "
                  f"{fit_dim:>6,}  held out {len(test):,}  covered {covered:,}  "
                  f"implied {rate:.1%}  multi-atom implied {rich_imp}/{rich_cov}"
                  f"  (uncovered {uncovered:,})")
            return {"rate": rate, "rich_rate": rrate, "fit_dim": fit_dim,
                    "covered": covered, "rich_covered": rich_cov}

        e3 = {"real": holdout(grows, "physlib"),
              "shuffled": holdout(grs, "shuffled atoms (control)")}
        if ctrl_rows is not None:
            e3["mathlib"] = holdout(gr3, "mathlib (control)")
        results["e3"] = e3

    # ---- E4 --------------------------------------------------------------
    if "4" in want:
        banner("E4 — can a dimensional error be detected at all?")
        # Positive control: pick pairs of atoms the solver kept independent and assert they
        # are equal. Each injection must be caught, or the check is decorative.
        cols = sorted(connected, key=lambda c: table.keys[c])
        base = Echelon()
        for r in grows:
            base.add(r)
        indep = []
        tries = 0
        while len(indep) < 20 and tries < 4000:
            tries += 1
            a, b = rng.sample(cols, 2)
            row = {a: Fraction(1), b: Fraction(-1)}
            if not base.implies(row):
                indep.append((a, b))
        caught = 0
        for a, b in indep:
            probe = Echelon()
            for r in grows:
                probe.add(r)
            probe.add({a: Fraction(1), b: Fraction(-1)})
            if probe.rank == base.rank + 1:
                caught += 1
        print(f"injected false identities   {len(indep)}")
        print(f"detected as new constraints {caught}")
        print("  (an injection that does not raise the rank is a claim the corpus already "
              "made; the detector must see every one that does)")

        if annotated:
            # The annotation cross-check: rows all of whose atoms carry a decoded exponent
            # vector must evaluate to zero under it. A nonzero row is either a dimensional
            # inhomogeneity or a modelling limit of the solver, and both get reported.
            byname = {}
            for i, k in enumerate(table.keys):
                if table.is_local[i]:
                    continue
                n = k.split("(")[0]
                v = annotated.get(n)
                if v:
                    byname[i] = dict(v[0][1])
            checked = violated = 0
            examples = []
            for r in grows:
                if r and all(c in byname for c in r):
                    checked += 1
                    tot = {}
                    for c, coef in r.items():
                        for g, e in byname[c].items():
                            tot[g] = tot.get(g, 0) + coef * e
                    if any(tot.values()):
                        violated += 1
                        if len(examples) < 5:
                            examples.append((r, tot))
            print(f"\nrows fully covered by decoded annotations {checked:,}")
            print(f"rows violating the decoded assignment      {violated:,}")
            for r, tot in examples:
                print("   ", {short(table.keys[c], 30): str(v) for c, v in r.items()},
                      "->", {k: str(v) for k, v in tot.items() if v})
            results["e4"] = {"injected": len(indep), "caught": caught,
                             "annotation_rows": checked, "violations": violated}
        else:
            results["e4"] = {"injected": len(indep), "caught": caught}

    # ---- E6 --------------------------------------------------------------
    per_decl = collections.defaultdict(set)
    if want & {"5", "6"}:
        for r, d in zip(grows, prov):
            per_decl[d].update(r)
    if "6" in want:
        banner("E6 — do declarations cluster by the quantity constants they mention?")
        run_e6(table, dict(per_decl), results, rng)

    # ---- E5 --------------------------------------------------------------
    if "5" in want:
        banner("E5 — does dimensional agreement predict analogy?")
        run_e5(args, rows, annotated, dict(per_decl), results)

    banner("summary (machine-readable)")
    print(json.dumps(results, indent=2, default=str))


UNIT_TYPES = ("LengthUnit", "TimeUnit", "MassUnit", "ChargeUnit", "TemperatureUnit")


def run_e5(args, rows, annotated, atom_sig, results):
    """The units-API family: genuine analogues whose dimensions differ by construction.

    Ground truth is *proposed* by name — the same lemma suffix under `LengthUnit`,
    `TimeUnit`, `MassUnit`, `ChargeUnit`, `TemperatureUnit` — and then **validated
    structurally** by `phys_i3.shape_key`: the two statements must be identical once every
    constant name is replaced by one token. Pairs that fail are counted, not quietly dropped.

    Not `Corpus.skeleton`: at `carriers` the five unit types are *concrete constants* rather
    than bound carriers, so the erasure leaves them in place and would reject the family it
    is being asked to confirm — and any erasure level needs a closed slice, which `generalize`
    does not (it anti-unifies the statements as encoded). Not retention either, since
    retention is the quantity under test.
    """
    import atlas as fa
    t0 = time.time()
    c = fa.Corpus.load(args.slice)
    print(f"corpus loaded for `generalize` (which anti-unifies the encodings and does not "
          f"erase): {len(c):,} rows, {time.time() - t0:.0f}s")

    kinds = {n: k for n, _m, k, _s in rows}
    shapes = {}
    for name, _mod, _kind, tree in trees(rows):
        if any(name.startswith(p + ".") for p in UNIT_TYPES):
            shapes[name] = i3.shape_key(tree)
    fams = collections.defaultdict(dict)
    for name, _mod, kind, _stmt in rows:
        for p in UNIT_TYPES:
            if name.startswith(p + "."):
                fams[name[len(p) + 1:]][p] = name
    proposed = []
    for suffix, byp in fams.items():
        ks = sorted(byp)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                proposed.append((byp[ks[i]], byp[ks[j]], suffix))
    thm = [(a, b, s) for a, b, s in proposed
           if kinds.get(a) == "theorem" and kinds.get(b) == "theorem"]
    kept = [(a, b, s) for a, b, s in thm
            if shapes.get(a) is not None and shapes.get(a) == shapes.get(b)]
    print(f"proposed by suffix {len(proposed):,}   both sides theorems {len(thm):,}")
    print(f"confirmed by identical name-erased shape {len(kept):,}   "
          f"rejected {len(thm) - len(kept):,}")
    if not kept:
        results["e5"] = {"proposed": len(proposed), "theorem_pairs": len(thm),
                         "confirmed": 0}
        return

    rng = random.Random(args.seed + 1)
    unit_thms = sorted({n for n, _m, k, _s in rows
                        if k == "theorem" and any(n.startswith(p + ".") for p in UNIT_TYPES)})
    kept_set = {(a, b) for a, b, _ in kept} | {(b, a) for a, b, _ in kept}
    negatives = []
    seen = set()
    while len(negatives) < len(kept) and len(seen) < 20 * len(kept):
        a, b = rng.sample(unit_thms, 2)
        seen.add((a, b))
        if (a, b) not in kept_set and a.split(".")[0] != b.split(".")[0]:
            negatives.append((a, b))

    def retention(a, b):
        try:
            return c.generalize(a, b).retention
        except Exception:
            return None

    pos = [r for a, b, _ in kept if (r := retention(a, b)) is not None]
    neg = [r for a, b in negatives if (r := retention(a, b)) is not None]
    r_auc = auc(pos, neg)
    print(f"\nretention          analogues n={len(pos)} mean "
          f"{sum(pos) / max(len(pos), 1):.3f}   non-analogues n={len(neg)} mean "
          f"{sum(neg) / max(len(neg), 1):.3f}   AUC {r_auc:.3f}")

    # Two dimensional readings of a declaration, both structural:
    #   `annotated` — the decoded `Dimension` term in its type, when it has one;
    #   `atom_sig`  — the set of global solver atoms its statement contributes.
    def ann(n):
        v = annotated.get(n)
        return v[0][1] if v else None

    def agree(a, b):
        x, y = ann(a), ann(b)
        if x is None or y is None:
            return None
        return 1.0 if x == y else 0.0

    ap = [v for a, b, _ in kept if (v := agree(a, b)) is not None]
    an = [v for a, b in negatives if (v := agree(a, b)) is not None]
    d_auc = auc(ap, an)
    print(f"dimension agreement analogues n={len(ap)}   non-analogues n={len(an)}   "
          f"AUC {d_auc:.3f}")
    print("  (0.5 is chance; below 0.5 means dimensional agreement is *anti*-predictive of "
          "analogy, which is the registered prediction)")

    def jac(a, b):
        x, y = atom_sig.get(a, set()), atom_sig.get(b, set())
        return len(x & y) / len(x | y) if (x or y) else None

    jp = [v for a, b, _ in kept if (v := jac(a, b)) is not None]
    jn = [v for a, b in negatives if (v := jac(a, b)) is not None]
    print(f"atom-set Jaccard   analogues n={len(jp)} mean "
          f"{sum(jp) / max(len(jp), 1):.3f}   non-analogues n={len(jn)} mean "
          f"{sum(jn) / max(len(jn), 1):.3f}   AUC {auc(jp, jn):.3f}")

    results["e5"] = {"proposed": len(proposed), "theorem_pairs": len(thm),
                     "confirmed": len(kept),
                     "retention_auc": r_auc, "dim_agreement_auc": d_auc,
                     "dim_agreement_n": len(ap),
                     "atom_jaccard_auc": auc(jp, jn)}


def run_e6(table, per_decl, results, rng, top=12):
    """Do declarations cluster by the quantity constants they mention, and is that module
    structure wearing a different hat?

    The unit is the *global atom* the solver already built: a constant applied to its closed
    arguments. Atoms that appear in almost every declaration carry no information and atoms
    that appear in one carry none either, so the band is reported rather than assumed — and
    the whole measurement is repeated with subfield labels shuffled, because "declarations
    that share a constant are usually in the same subfield" is true of any corpus with more
    than one subfield in it.
    """
    freq = collections.Counter()
    for d, atoms in per_decl.items():
        for a in atoms:
            freq[a] += 1
    n_decls = len(per_decl)
    lo, hi = 2, max(3, n_decls // 20)
    informative = {a for a, k in freq.items() if lo <= k <= hi}
    print(f"declarations with atoms   {n_decls:,}")
    print(f"global atoms              {len(freq):,}")
    print(f"informative band [{lo}, {hi}]  {len(informative):,}")

    subfield = {}
    for d in per_decl:
        parts = d.split(".")
        subfield[d] = ".".join(parts[:2]) if len(parts) > 1 else parts[0]

    postings = collections.defaultdict(list)
    for d, atoms in per_decl.items():
        for a in atoms & informative:
            postings[a].append(d)

    shared = collections.Counter()
    for a, ds in postings.items():
        if len(ds) > 60:            # a posting list this long is punctuation, not a quantity
            continue
        ds = sorted(set(ds))
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                shared[(ds[i], ds[j])] += 1

    def rate(pairs, labels):
        if not pairs:
            return float("nan")
        return sum(labels[a] == labels[b] for a, b in pairs) / len(pairs)

    allpairs = list(shared)
    print(f"pairs sharing >=1 informative atom  {len(allpairs):,}")
    names = sorted(per_decl)
    base_pairs = [tuple(rng.sample(names, 2)) for _ in range(min(200000, len(allpairs) or 1))]
    shuffled = dict(zip(names, rng.sample([subfield[n] for n in names], len(names))))
    out = {}
    for k in (1, 2, 3):
        sel = [p for p, c in shared.items() if c >= k]
        r = rate(sel, subfield)
        rs = rate(sel, shuffled)
        out[k] = {"pairs": len(sel), "same_subfield": r, "shuffled": rs}
        print(f"  share >= {k} atoms: {len(sel):>9,} pairs   "
              f"same-subfield {r:.1%}   label-shuffled {rs:.1%}")
    b = rate(base_pairs, subfield)
    print(f"  random pairs:      {len(base_pairs):>9,} pairs   same-subfield {b:.1%}")
    out["random_baseline"] = b

    cross = [(c, a, b) for (a, b), c in shared.items() if subfield[a] != subfield[b]]
    cross.sort(reverse=True)
    print("\nhighest-overlap CROSS-subfield pairs — where the same quantities are used in "
          "two places:")
    for c, a, b in cross[:top]:
        print(f"  {c:>3}  {short(a, 46)}   ~   {short(b, 46)}")
    results["e6"] = out


def selftest():
    """A synthetic corpus whose dimensional answer is known before the solver runs.

    Three base dimensions, three defined quantities, one redundant restatement and one
    statement that is pure algebra. The assertions are *properties*, not pinned output:
    the grading space must have dimension 3 (the number of base dimensions), the redundant
    restatement must be implied by the definitions that precede it, and the intended
    exponent assignment must satisfy every row. A solver that identifies two base
    dimensions fails the first; one that does not propagate through `^` fails the second.
    """
    C = lambda n: ("c", n)                                              # noqa: E731

    def A(f, *xs):
        for x in xs:
            f = ("a", f, x)
        return f

    R = C("Real")
    eq = lambda l, r: A(C("Eq"), R, l, r)                               # noqa: E731
    mul = lambda a, b: A(C("HMul.hMul"), R, R, R, C("i"), a, b)         # noqa: E731
    div = lambda a, b: A(C("HDiv.hDiv"), R, R, R, C("i"), a, b)         # noqa: E731
    add = lambda a, b: A(C("HAdd.hAdd"), R, R, R, C("i"), a, b)         # noqa: E731
    pw = lambda a, k: A(C("HPow.hPow"), R, C("Nat"), R, C("i"), a, ("n", k))  # noqa: E731
    L, T, M, S, P, E = (C(x) for x in ("len", "time", "mass", "speed", "mom", "energy"))
    stmts = {
        "s_def": eq(S, div(L, T)),
        "p_def": eq(P, mul(M, S)),
        "e_def": eq(E, mul(P, S)),
        "e_alt": eq(E, mul(M, pw(S, 2))),
        "algebra": ("p", "d", R, eq(add(("b", 0), ("b", 0)), mul(C("two"), ("b", 0)))),
    }
    tab = AtomTable()
    ex = Extractor(tab)
    per, grows = {}, []
    for n, t in stmts.items():
        ex.reset(n)
        ex.scan(t, 0)
        per[n] = eliminate_locals(ex.rows, lambda c: tab.is_local[c])
        grows += per[n]
    ech = Echelon(order=lambda c: tab.keys[c])
    for r in grows:
        ech.add(r)
    cols = ech.columns()
    grading_dim = len(cols) - ech.rank
    fit = Echelon()
    for n in ("s_def", "p_def", "e_def"):
        for r in per[n]:
            fit.add(r)
    implied = all(fit.implies(r) for r in per["e_alt"])
    truth = {"len()": {"L": 1}, "time()": {"T": 1}, "mass()": {"M": 1},
             "speed()": {"L": 1, "T": -1}, "mom()": {"M": 1, "L": 1, "T": -1},
             "energy()": {"M": 1, "L": 2, "T": -2}, "two()": {}}
    bad = 0
    for r in grows:
        tot = {}
        for c, co in r.items():
            for g, e in truth.get(tab.keys[c], {}).items():
                tot[g] = tot.get(g, 0) + co * e
        bad += any(tot.values())
    ok = grading_dim == 3 and implied and bad == 0
    print(f"selftest: columns {len(cols)}  rank {ech.rank}  grading dim {grading_dim} "
          f"(want 3)  redundant-implied {implied} (want True)  "
          f"rows violating truth {bad} (want 0)  ->  {'PASS' if ok else 'FAIL'}")
    for c, r in sorted(ech.pivots.items(), key=lambda kv: tab.keys[kv[0]]):
        print("   ", render_relation(tab, c, r))
    return 0 if ok else 1


def auc(pos, neg):
    """Probability a random positive outranks a random negative; ties count a half."""
    if not pos or not neg:
        return float("nan")
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


if __name__ == "__main__":
    main()
