#!/usr/bin/env -S uv run --no-sync python
"""Calculus rules for the dimensional solver, and what they recover.

Run:  uv run --no-sync scripts/phys-calculus.py --selftest
      uv run --no-sync scripts/phys-calculus.py --census --slice /tmp/atlas-physlib.jsonl
      uv run --no-sync scripts/phys-calculus.py --slice /tmp/atlas-physlib.jsonl \
          --control /tmp/mathlib-algebra.jsonl --calc-control /tmp/akc-mathlib-analysis.jsonl

===========================================================================
WHAT A GOOD ANSWER LOOKS LIKE — written before the first measured run
===========================================================================

`research/physlib-dimensional.md` §8 names the bottleneck: **45% of the subterms the
dimensional walk looks at are opaque**, led by `deriv`, `MeasureTheory.integral` and
`DFunLike.coe`, and each opaque subterm becomes one atom whose dimension the solver has to
leave free. The claim under test here is that the missing vocabulary is *calculus* — the
typing rules of differentiation and integration — and that supplying it converts opacity
into recovered physics.

A calculus rule is a **typing** rule, not a physics fact. `deriv f x` for `f : 𝕜 → F` and
`x : 𝕜` is a limit of `(f y - f x) / (y - x)`, so it scales as `F/𝕜` whatever `F` and `𝕜`
mean; `∫ x, f x ∂μ` is a limit of `Σ f(xᵢ)·μ(Aᵢ)`, so it scales as `f·μ`. Every rule below is
of that form and is attached by head-constant identity, which is a typed lookup and not a
semantic guess. No rule mentions a physical quantity, and the same vocabulary runs on the
physics corpus and on both mathematics controls.

C0 — THE HARNESS REPRODUCES THE PRIOR ART
    With `--rules none` this script must reproduce `phys-dimensional.py`'s E2 numbers on the
    same slice at the same cap, to the row. If it does not, every delta below is measuring my
    harness rather than the rules.
    PASSES: physlib at `--cap 20000` gives 17 multi-atom relations, at `--cap 200000` gives 21.
    FAILS:  anything else — the subclass has changed the baseline and nothing is comparable.

C1 — COVERAGE MUST ACTUALLY IMPROVE
    PASSES: the opaque fraction drops by at least 5 percentage points on physlib, measured
            two ways (dynamically, over the solver's own walk, which is the number §8 quotes;
            and statically, over every maximal application spine in the kept statements,
            which does not move when the rule set changes what the walk reaches).
    FAILS:  the fraction is unmoved — the heads that were opaque are not the ones ruled on,
            and the census picked the wrong targets.

C2 — THE RULES MUST RECOVER MORE PHYSICS
    PASSES: the multi-atom relation count on physlib rises, and the relations name physical
            quantities that the baseline left unconnected.
    FAILS:  the count falls, or rises only by relations of the form `a = b + c` over
            auto-generated or metaprogramming atoms.

C3 — BOTH ORIGINAL CONTROLS MUST STAY AT ZERO   ** the pass condition, not a formality **
    The shuffle control (physlib's own rows, atoms rewired at random) and the
    `mathlib-algebra` control must both still produce **0** multi-atom relations, and the
    shuffle's grading dimension must stay at or below 3.
    FAILS:  either becomes positive — the rules are manufacturing structure out of arithmetic
            density, and the result is withdrawn.

C4 — THE NEW CONTROL THE RULES THEMSELVES REQUIRE
    `mathlib-algebra` contains almost no calculus, so it cannot test a calculus rule. The
    honest control is **pure mathematics that is nothing but calculus**: every
    `Mathlib.Analysis`, `Mathlib.MeasureTheory` and `Mathlib.Probability` row. That corpus
    states the product rule, the chain rule and the FTC, and if these rules manufacture
    "dimensional laws" out of calculus identities it is where it will show.
    Pre-registered discriminator, fixed before the run: **multi-atom relations per thousand
    declarations contributing rows**, and the fraction of them carrying a coefficient outside
    ±1 (a *power* — which algebraic rearrangement cannot produce).
    PASSES: the calculus control's rate is well under half physlib's.
    FAILS:  the rate is at least half physlib's, in which case the rules recover calculus
            bookkeeping rather than physics and the claim is withdrawn loudly.

C5 — RULE ABLATION
    Each rule family is switched off in turn. A family that changes nothing when removed is
    not doing the work its presence claims, and is reported as such.

C6 — THE KEYING CHANGE THE RULES FORCE, AND ITS OWN COLLAPSE CONTROL
    A calculus rule spends the *point* it differentiates at: `D(deriv f x) = D(f) − D(x)`.
    In real statements `x` is a bound variable, and the base solver keys a bound variable
    per-declaration, so that term is eliminated as a local and the row it was in disappears.
    Measured on physlib below; the rules are worth almost nothing without a fix.
    The fix is structural: **a bound variable whose binder domain is a closed type is keyed
    by that type**, so `∀ t : Time` in one theorem and `∀ t : Time` in another are one atom.
    That is exactly the keying the prior art's `--keying coarse` ablation warns about, one
    level up — and it is dangerous in exactly one place, the ambient scalars, because
    `∀ x : ℝ` is a length in one theorem and a time in the next, and identifying them forces
    `L = T` and collapses the lattice. So `--bvar type-nonscalar` excludes Lean's own number
    types (`Real`, `Complex`, `NNReal`, `Nat`, …) — the same ambient vocabulary as
    `HMul.hMul`, containing no physics — and `--bvar type` is the ablation that reproduces
    the collapse on demand.
    PASSES: `type-nonscalar` raises the relation count without collapsing the grading
            dimension, and `type` collapses it — so the exclusion is doing work.
    FAILS:  `type-nonscalar` collapses too, in which case physlib's non-scalar types are
            themselves overloaded and this route is closed.
    Reported as a 2x2 against the rule set, so the keying change and the rules are never
    credited with each other's gain.

    TWO DEVIATIONS FROM THIS REGISTRATION, RECORDED RATHER THAN EDITED IN:
    (a) "closed type" above became "the domain written with `_` for its open arguments",
        the same convention `_spine_atom` uses. Requiring closure keys almost nothing,
        because physlib quantifies over the space dimension; `--bvar type-nonscalar-closed`
        is the stricter variant, kept so the choice is measurable.
    (b) **the prediction failed.** `--bvar type` does *not* collapse the grading: 376 against
        381, where the spine-keying ablation it was modelled on moves 341 -> 95. The
        justification for the scalar guard is withdrawn; the guard is kept on the weaker
        evidence that it yields 66 relations against 60. See `research/physlib-calculus.md`
        §3, and do not turn this into a gate.

W  — THE WILD QUESTION: is an evolution equation structurally distinguished?
    A conservation law is `deriv Q t = 0`. An equation of motion is `deriv Q t = (something
    else)`. Registered prediction, before looking: the solver is **blind to conservation
    laws** — `0` typechecks at every dimension, so the design deliberately gives it a free
    variable and the row carries no information — and **sees equations of motion**, because
    the right-hand side pins the derivative's dimension. If that is right, the grading treats
    the two classes of physical law completely differently, and the difference is structural
    (`Eq(deriv …, 0)` versus `Eq(deriv …, _)`) rather than nominal.

===========================================================================
CLOSURE
===========================================================================

Stated per measurement rather than assumed. **Every number in this script is computed from
statement trees only**: no constant's signature is looked up during solving, no citation is
followed, and no erasure-level query is made. Per `research/physlib-dimensional.md` §0 that
is the E2/E3/E4/E6 case, which does not need a closed slice — the answer over a given set of
declarations is the same whether or not the slice also holds that set's foundation.

The one place a signature *is* read is `--arity-check`, which counts the `Pi` binders of a
rule head's own type row to confirm the arity each rule is pinned at. That is a lookup, so it
runs against the **closed** slice `/tmp/pc-physclosed.jsonl` (95,268 rows, 99.46% closed) and
reports every head it could not find rather than silently defaulting.

===========================================================================
CONSTRAINTS
===========================================================================

* **No name is a semantic oracle.** Rules are attached by head constant — a typed lookup —
  and the arity each is pinned at is checked against the constant's own type. Selection of
  *which* heads to rule on came from the opacity census (`--census`), i.e. from measured
  frequency, not from a guess about what physics needs.
* **A rule may lose information; it may never invent a constraint.** Where a rule cannot be
  applied soundly (symbolic exponent, unknown bundle type, under-applied spine) it returns
  `None` and the subterm stays opaque, exactly as before.
* **No synthesized tree nodes.** `phys_dimlib._open` falls back to `has_loose_bvar` for a
  node absent from the `annotate` table, and that fallback is the defect §3 of the prior art
  documents — it asks whether a subterm escapes the whole statement, which is always false,
  so atom keys pick up raw de Bruijn indices and no two declarations share an atom. Every
  term these rules pass to `dim` is a subterm of the parsed tree, so every node is in the
  table. `--selftest` is the guard and it fails if the keys go local.
* **Measured numbers only.**
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

import phys_i3 as i3                                                    # noqa: E402
import phys_dimlib as dl                                                # noqa: E402
from phys_dimlib import (AtomTable, Echelon, Extractor,                 # noqa: E402
                         eliminate_locals, _add, _sub, _scale, ONE)
from phys_i3 import const_name, spine                                   # noqa: E402

CLOSED_SLICE = "/tmp/pc-physclosed.jsonl"


# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

def rat_literal(e, fuel: int = 40):
    """The rational a closed numeral expression denotes, or `None`.

    `phys_dimlib._nat_literal` reads `OfNat.ofNat` and stops there, so `x ^ (-2)` and
    `x ^ (1/2)` were opaque. Both are exponents a dimensional law actually carries, so the
    evaluator is widened — but only over numerals: anything with a free constant in it
    returns `None` and the subterm stays opaque.
    """
    if fuel <= 0:
        return None
    if e[0] == "n":
        return Fraction(e[1])
    h, args = spine(e)
    n = const_name(h)
    if n is None:
        return None
    if n == "OfNat.ofNat" or n == "OfScientific.ofScientific":
        for a in args:
            v = rat_literal(a, fuel - 1)
            if v is not None:
                return v
        return None
    if n in ("Zero.zero",):
        return Fraction(0)
    if n in ("One.one",):
        return ONE
    if n in dl.CAST and args:
        return rat_literal(args[-1], fuel - 1)
    if n in dl.NEG and args:
        v = rat_literal(args[-1], fuel - 1)
        return None if v is None else -v
    if n in dl.INV and args:
        v = rat_literal(args[-1], fuel - 1)
        return None if not v else 1 / v
    if n in dl.DIV and len(args) >= 2:
        a = rat_literal(args[-2], fuel - 1)
        b = rat_literal(args[-1], fuel - 1)
        return None if a is None or not b else a / b
    if n in dl.MUL and len(args) >= 2:
        a = rat_literal(args[-2], fuel - 1)
        b = rat_literal(args[-1], fuel - 1)
        return None if a is None or b is None else a * b
    return None


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------
#
# Each entry is `head -> (family, arity, fn)`. `arity` is the length of the *fully applied*
# spine, taken from the constant's own signature and checked by `--arity-check` against its
# type row in the closed slice. A shorter spine is a partial application — `deriv f` as a
# function — where the rule does not apply and the subterm stays opaque. A longer one is the
# result being applied further, and the extra arguments are ignored: under this framework a
# function's dimension *is* the dimension of its values, which is the same convention the
# base solver already uses for a spine headed by a bound variable.

VALUE_RULES: dict[str, tuple] = {}
PROP_RULES: dict[str, tuple] = {}


def value_rule(name, family, arity):
    def reg(fn):
        VALUE_RULES[name] = (family, arity, fn)
        return fn
    return reg


def prop_rule(name, family, arity):
    def reg(fn):
        PROP_RULES[name] = (family, arity, fn)
        return fn
    return reg


# -- differentiation ---------------------------------------------------------
# D(deriv f x) = D(f) - D(x): the difference quotient (f y - f x)/(y - x) has the dimension
# of `f`'s values over the dimension of its argument, for any `f : 𝕜 → F`.

def _deriv_at(ex, f, x, depth, order=ONE):
    dx = ex.dim(x, depth)
    body = ex.fun_dim(f, depth, dx)
    return _sub(body, _scale(dx, order))


@value_rule("deriv", "deriv", 8)
def r_deriv(ex, e, h, args, depth):
    return _deriv_at(ex, args[-2], args[-1], depth)


@value_rule("derivWithin", "deriv", 9)
def r_deriv_within(ex, e, h, args, depth):
    return _deriv_at(ex, args[-3], args[-1], depth)


@value_rule("fderiv", "deriv", 12)
def r_fderiv(ex, e, h, args, depth):
    # The Fréchet derivative is a continuous linear map; as an element of `E →L[𝕜] F` it
    # scales as F/E, and `DFunLike.coe` puts the E back when it is applied.
    return _deriv_at(ex, args[-2], args[-1], depth)


@value_rule("fderivWithin", "deriv", 13)
def r_fderiv_within(ex, e, h, args, depth):
    return _deriv_at(ex, args[-3], args[-1], depth)


@value_rule("iteratedDeriv", "deriv", 8)
def r_iterated_deriv(ex, e, h, args, depth):
    k = rat_literal(args[-3])
    if k is None or k < 0 or k > 64:
        return None
    return _deriv_at(ex, args[-2], args[-1], depth, order=k)


@value_rule("iteratedFDeriv", "deriv", 11)
def r_iterated_fderiv(ex, e, h, args, depth):
    k = rat_literal(args[-3])
    if k is None or k < 0 or k > 64:
        return None
    return _deriv_at(ex, args[-2], args[-1], depth, order=k)


@value_rule("gradient", "deriv", 8)
def r_gradient(ex, e, h, args, depth):
    # `∇f x` is the Riesz representative of `fderiv f x`, so it scales the same way. Added
    # after the first measured run put `gradient(…)` inside five recovered relations as an
    # atom the solver had left free — the harmonic oscillator's `k` and `m` among them.
    return _deriv_at(ex, args[-2], args[-1], depth)


@prop_rule("HasDerivAt", "deriv", 10)
def p_has_deriv_at(ex, e, h, args, depth):
    # `HasDerivAt f f' x` asserts `f' = deriv f x`, so it is a row even though the node is a
    # Prop and has no dimension of its own. This is where a hypothesis contributes.
    f, fp, x = args[-3], args[-2], args[-1]
    ex._emit(_sub(ex.dim(fp, depth), _deriv_at(ex, f, x, depth)))
    return True


@prop_rule("HasDerivWithinAt", "deriv", 11)
def p_has_deriv_within_at(ex, e, h, args, depth):
    f, fp, x = args[-4], args[-3], args[-1]
    ex._emit(_sub(ex.dim(fp, depth), _deriv_at(ex, f, x, depth)))
    return True


@prop_rule("HasFDerivAt", "deriv", 13)
def p_has_fderiv_at(ex, e, h, args, depth):
    f, fp, x = args[-3], args[-2], args[-1]
    ex._emit(_sub(ex.dim(fp, depth), _deriv_at(ex, f, x, depth)))
    return True


# -- integration -------------------------------------------------------------
# D(∫ x, f x ∂μ) = D(f) + D(μ): the integral is a limit of `Σ f(xᵢ) · μ(Aᵢ)`. The measure
# carries the dimension of `dx`, and the integration variable is given the measure's
# dimension because that is what `μ` measures.

def _integral(ex, mu, f, depth):
    dmu = ex.dim(mu, depth)
    return _add(ex.fun_dim(f, depth, dmu), dmu)


@value_rule("MeasureTheory.integral", "integral", 7)
def r_integral(ex, e, h, args, depth):
    return _integral(ex, args[-2], args[-1], depth)


@value_rule("MeasureTheory.lintegral", "integral", 4)
def r_lintegral(ex, e, h, args, depth):
    return _integral(ex, args[-2], args[-1], depth)


@value_rule("intervalIntegral", "integral", 7)
def r_interval_integral(ex, e, h, args, depth):
    # `∫ x in a..b, f x ∂μ`. The endpoints live in the domain, so they give the integration
    # variable's dimension directly — better than the measure's atom, which on `volume` is
    # shared across every space in the corpus.
    f, a, b = args[-4], args[-3], args[-2]
    da = ex.dim(a, depth)
    ex._emit(_sub(da, ex.dim(b, depth)))
    return _add(ex.fun_dim(f, depth, da), da)


# -- physlib's own differentiation -------------------------------------------
# Measured, not guessed: the opacity census (`--census`) puts `Space.deriv` (130 occurrences,
# 59 declarations) and `Time.deriv` (123 / 81) *above* Mathlib's `deriv` (50 / 30) on the
# physics slice. Their signatures, read off their own type rows in the closed slice, are a
# derivative's:
#
#   Time.deriv  {M} [AddCommGroup M] [Module ℝ M] [TopologicalSpace M]
#               (f : Time → M) (x : Time) : M
#   Space.deriv {d} {M} [AddCommGroup M] [Module ℝ M] [TopologicalSpace M]
#               (μ : Fin d) (f : Space d → M) (x : Space d) : M
#
# These are a *separate family*, and every cross-corpus comparison is reported with it off as
# well as on. Not because the rule is unsound — it is the same typing rule as `deriv`'s — but
# because a vocabulary tuned to one corpus cannot be the vocabulary a comparison against
# another corpus is run with. The constants do not exist in Mathlib, so the family cannot
# fire there; the separation is so that physlib's gain is never confused with the rules'.

@value_rule("Time.deriv", "physlib", 6)
def r_time_deriv(ex, e, h, args, depth):
    return _deriv_at(ex, args[-2], args[-1], depth)


@value_rule("Space.deriv", "physlib", 8)
def r_space_deriv(ex, e, h, args, depth):
    # `∂f/∂xᵘ`: the direction index is dimensionless, the point is not.
    return _deriv_at(ex, args[-2], args[-1], depth)


# -- summation ---------------------------------------------------------------
# A sum of terms is one of its terms: `Σ f i` has the dimension of `f`. The index carries no
# dimension of the summand's kind, so no row is emitted for it.

@value_rule("Finset.sum", "sum", 5)
def r_finset_sum(ex, e, h, args, depth):
    return ex.fun_dim(args[-1], depth)


@value_rule("tsum", "sum", 6)
def r_tsum(ex, e, h, args, depth):
    # The last argument is an `optParam SummationFilter`, not the summand — measured off the
    # type row, and the reason the arity check is a gate rather than a comment.
    return ex.fun_dim(args[-2], depth)


@value_rule("Matrix.trace", "sum", 5)
def r_trace(ex, e, h, args, depth):
    return ex.dim(args[-1], depth)


@prop_rule("HasSum", "sum", 7)
def p_has_sum(ex, e, h, args, depth):
    f, a = args[-3], args[-2]
    ex._emit(_sub(ex.dim(a, depth), ex.fun_dim(f, depth)))
    return True


# -- magnitude ---------------------------------------------------------------
# A norm, an absolute value and a distance are all homogeneous of degree 1.

@value_rule("Norm.norm", "norm", 3)
def r_norm(ex, e, h, args, depth):
    return ex.dim(args[-1], depth)


@value_rule("NNNorm.nnnorm", "norm", 3)
def r_nnnorm(ex, e, h, args, depth):
    return ex.dim(args[-1], depth)


@value_rule("ENorm.enorm", "norm", 3)
def r_enorm(ex, e, h, args, depth):
    return ex.dim(args[-1], depth)


@value_rule("abs", "norm", 4)
def r_abs(ex, e, h, args, depth):
    return ex.dim(args[-1], depth)


@value_rule("Dist.dist", "norm", 4)
def r_dist(ex, e, h, args, depth):
    a = ex.dim(args[-2], depth)
    ex._emit(_sub(a, ex.dim(args[-1], depth)))
    return a


@value_rule("EDist.edist", "norm", 4)
def r_edist(ex, e, h, args, depth):
    a = ex.dim(args[-2], depth)
    ex._emit(_sub(a, ex.dim(args[-1], depth)))
    return a


# -- powers ------------------------------------------------------------------
# `√x` is `x^(1/2)`; a rational exponent scales the exponent vector by that rational. The
# base solver only read natural-number exponents through `OfNat`, so `x⁻²` and `x^(1/2)`
# were opaque, and those are precisely the exponents a dimensional law carries.

@value_rule("Real.sqrt", "power", 1)
def r_sqrt(ex, e, h, args, depth):
    return _scale(ex.dim(args[-1], depth), Fraction(1, 2))


@value_rule("Real.rpow", "power", 2)
def r_rpow(ex, e, h, args, depth):
    k = rat_literal(args[-1])
    if k is None or abs(k) > 64:
        return None
    return _scale(ex.dim(args[-2], depth), k)


@value_rule("HPow.hPow", "power", 6)
def r_hpow(ex, e, h, args, depth):
    # Only widens the base solver: a *rational* literal exponent, which it left opaque.
    # Anything it already handles falls through to it unchanged.
    if dl._nat_literal(args[-1]) is not None:
        return None
    k = rat_literal(args[-1])
    if k is None or abs(k) > 64:
        return None
    return _scale(ex.dim(args[-2], depth), k)


# -- bilinear application ----------------------------------------------------
# An inner product is bilinear, so it adds. `DFunLike.coe` is the corpus's single largest
# opaque head (1,597 occurrences over 1,052 declarations on physlib), and what is sound to
# say about `f x` depends entirely on the bundle `f` lives in — which is an *argument of the
# spine*, so the split is read off the term rather than assumed:
#
#   linear bundles   `f : E →ₗ F` scales as F/E, so `D(f x) = D(f) + D(x)`.
#   value bundles    a `Basis`, an `Equiv`, a `Finsupp`, a `SchwartzMap` is a plain indexed
#                    family; applying it does not scale, so `D(f x) = D(f)`.
#   everything else  a `MonoidHom` is multiplicative and a general bundle has no algebra at
#                    all; there is nothing sound to say, so the subterm stays opaque.
#
# The sets are the bundles the census actually found, most frequent first.

LINEAR_BUNDLES = {
    "LinearMap", "ContinuousLinearMap", "LinearEquiv", "ContinuousLinearEquiv",
    "LinearIsometry", "LinearIsometryEquiv", "AddMonoidHom", "AddEquiv",
    "LinearPMap", "Matrix",
}

VALUE_BUNDLES = {
    "Module.Basis", "OrthonormalBasis", "Equiv", "Finsupp", "SchwartzMap",
    "ContinuousMap", "Homeomorph", "Function.Embedding", "ProbDistribution",
    "MeasureTheory.SimpleFunc", "Representation.IntertwiningMap",
}


@value_rule("Inner.inner", "bilinear", 5)
def r_inner(ex, e, h, args, depth):
    return _add(ex.dim(args[-2], depth), ex.dim(args[-1], depth))


@value_rule("Matrix.mulVec", "bilinear", 7)
def r_mulvec(ex, e, h, args, depth):
    # Pinned at 7, not at the 8 the type row reports: `Matrix.mulVec M v : m → α` is
    # function-valued, so its telescope continues past the value into the result index. The
    # arity check knows and says so rather than reporting a mismatch it cannot explain.
    return _add(ex.dim(args[-2], depth), ex.dim(args[-1], depth))


@value_rule("DFunLike.coe", "bilinear", 6)
def r_dfunlike(ex, e, h, args, depth):
    bundle = const_name(spine(args[-6])[0])
    if bundle in LINEAR_BUNDLES:
        return _add(ex.dim(args[-2], depth), ex.dim(args[-1], depth))
    if bundle in VALUE_BUNDLES:
        return ex.dim(args[-2], depth)
    return None


# -- unary casts, and a defect in the base solver ----------------------------
# `phys_dimlib.CAST` already lists `Complex.ofReal`, `NNReal.toReal`, `ENNReal.toReal` and
# `Real.toNNReal` — and its dispatch can never reach them. The `CAST` branch sits inside
# `if name in OPERATORS and len(args) >= 2`, and every one of those casts is **unary**
# (measured off its own type row: arity 1). So they fell through to the opaque fallback, and
# the census counts what that cost on physlib: `Complex.ofReal` 145 occurrences over 75
# declarations, `NNReal.toReal` 48 over 27. The rule below is the repair, as a rule rather
# than an edit to the file the prior art measured.

@value_rule("Complex.ofReal", "cast", 1)
@value_rule("NNReal.toReal", "cast", 1)
@value_rule("ENNReal.toReal", "cast", 1)
@value_rule("Real.toNNReal", "cast", 1)
@value_rule("ENNReal.ofReal", "cast", 1)
def r_unary_cast(ex, e, h, args, depth):
    return ex.dim(args[-1], depth)


@value_rule("WithLp.ofLp", "cast", 3)
@value_rule("WithLp.toLp", "cast", 3)
def r_withlp(ex, e, h, args, depth):
    # `WithLp p α` is a type synonym for `α`; the coercion changes the norm, not the value.
    return ex.dim(args[-1], depth)


@value_rule("Subtype.mk", "cast", 4)
def r_subtype_mk(ex, e, h, args, depth):
    # The last argument is the membership proof, not the value.
    return ex.dim(args[-2], depth)


# -- branches ----------------------------------------------------------------
# Both arms of an `if` and both arguments of `max` have one dimension, for the same reason a
# sum does: the term only typechecks at one.

@value_rule("ite", "branch", 5)
def r_ite(ex, e, h, args, depth):
    a = ex.dim(args[-2], depth)
    ex._emit(_sub(a, ex.dim(args[-1], depth)))
    return a


@value_rule("Max.max", "branch", 4)
def r_max(ex, e, h, args, depth):
    a = ex.dim(args[-2], depth)
    ex._emit(_sub(a, ex.dim(args[-1], depth)))
    return a


@value_rule("Min.min", "branch", 4)
def r_min(ex, e, h, args, depth):
    a = ex.dim(args[-2], depth)
    ex._emit(_sub(a, ex.dim(args[-1], depth)))
    return a


FAMILIES = sorted({f for f, _a, _fn in VALUE_RULES.values()} |
                  {f for f, _a, _fn in PROP_RULES.values()})

DERIV_HEADS = {n for n, (f, _a, _fn) in VALUE_RULES.items() if f in ("deriv", "physlib")}
INTEGRAL_HEADS = {n for n, (f, _a, _fn) in VALUE_RULES.items() if f == "integral"}


# ---------------------------------------------------------------------------
# The extractor
# ---------------------------------------------------------------------------

"""Lean's own number types. A bound variable of one of these has no recoverable dimension:
`∀ x : ℝ` is a length in one theorem and a time in the next, so identifying them across
declarations forces `L = T`. The list is the ambient numeric vocabulary — the same kind of
input as `HMul.hMul` — and contains no physics.
"""
SCALARS = {
    "Real", "Complex", "NNReal", "ENNReal", "EReal", "Rat", "NNRat", "Int", "Nat",
    "PNat", "Fin", "ZMod", "Bool", "Float", "UInt8", "UInt16", "UInt32", "UInt64",
    "USize", "Quaternion", "RCLike", "Polynomial", "Prop",
}


class CalcExtractor(Extractor):
    """`phys_dimlib.Extractor` plus the calculus vocabulary.

    Subclassed rather than edited: `phys_dimlib.py` is the prior art's measured artifact and
    `--rules none --bvar local` has to reproduce its numbers exactly. Every hook here either
    adds a rule or counts something; none removes a case.
    """

    def __init__(self, table, keying="fine", literals="dimensionless", rules=None,
                 bvar="local"):
        self.rules = set(FAMILIES) if rules is None else set(rules)
        self.bvar = bvar
        self.opaque_heads = collections.Counter()
        self.opaque_head_ndecls = collections.Counter()
        self.rule_hits = collections.Counter()
        self.typed_bvars = 0
        self.local_bvars = 0
        self._decl_heads: set[str] = set()
        self._dom: dict[int, str | None] = {}
        super().__init__(table, keying=keying, literals=literals)

    def reset(self, decl: str, tree=None) -> None:
        heads = getattr(self, "_decl_heads", None)
        if heads:
            for hd in heads:
                self.opaque_head_ndecls[hd] += 1
            heads.clear()
        super().reset(decl, tree)
        self._dom = {}
        if tree is not None and self.bvar != "local":
            self._build_domains(tree)

    # -- binder domains --------------------------------------------------

    def _build_domains(self, tree) -> None:
        """`absolute binder index -> the key of its domain`, or `None` where unusable.

        Two binders can sit at the same absolute index in disjoint branches of one
        statement — the base solver's local key has the same ambiguity and contains it by
        being local. Here the key escapes the declaration, so an index whose two binders
        disagree is marked unusable and falls back to the local key. Losing an atom is
        recoverable; merging two is not.
        """
        MISS = object()
        dom = self._dom
        stack = [(tree, 0)]
        while stack:
            n, d = stack.pop()
            t = n[0]
            if t == "a":
                stack.append((n[1], d))
                stack.append((n[2], d))
            elif t in ("p", "l", "e"):
                ty = n[1] if t == "e" else n[2]
                key = self._type_key(ty, d)
                prev = dom.get(d, MISS)
                if prev is MISS:
                    dom[d] = key
                elif prev != key:
                    dom[d] = None
                if t == "e":
                    stack.append((n[1], d))
                    stack.append((n[2], d))
                    stack.append((n[3], d + 1))
                else:
                    stack.append((n[2], d))
                    stack.append((n[3], d + 1))
            elif t == "j":
                stack.append((n[3], d))

    def _type_key(self, ty, d: int) -> str | None:
        """The atom key for a binder domain, or `None` where the domain must not be used.

        Written with `_` for an open argument, which is the convention `_spine_atom` already
        uses: `∀ x : Space d` in a theorem that quantified over `d` keys as `Space(_)`, and
        every position variable in the corpus is one atom. Requiring the domain to be closed
        instead would key almost nothing, because physlib quantifies over the dimension.

        `None` — fall back to the base solver's declaration-local key — in three cases:
          * a **sort** domain (`{α : Type}`). A type variable has no dimension, and merging
            every declaration's type arguments into one atom wires the corpus together
            through nothing.
          * a domain headed by something that is not a constant: a bound variable, a `Pi`
            (a function-typed binder), a projection. Nothing to key on.
          * a **scalar** domain, under `type-nonscalar`. This is the collapse guard; `--bvar
            type` drops it and the grading dimension is the number that falls.
        """
        if ty[0] == "s":
            return None
        head, args = spine(ty)
        n = const_name(head)
        if n is None:
            return None
        if self.bvar in ("type-nonscalar", "type-nonscalar-closed") and n in SCALARS:
            return None
        if self.bvar.endswith("closed") and self._open(ty, d):
            return None
        parts = []
        for a in args:
            if self._open(a, d):
                parts.append("_")
                continue
            r = i3.render(a, 120)
            parts.append(r if not r.endswith("…") else f"{r}#{self._size(a)}")
        return f"{n}({','.join(parts)})"

    def _bvar_atom(self, idx: int, depth: int) -> int:
        key = self._dom.get(depth - 1 - idx) if self.bvar != "local" else None
        if key is None:
            self.local_bvars += 1
            return super()._bvar_atom(idx, depth)
        self.typed_bvars += 1
        return self.table.intern(f"⟨{key}⟩", False)

    # -- census ----------------------------------------------------------
    # `_spine_atom` is called from exactly the two places the base solver gives up on an
    # application — the symbolic-exponent branch and the fallback — so instrumenting it is
    # the opacity census with no duplicated dispatch to drift out of sync.

    def _spine_atom(self, head, args, depth: int) -> int:
        n = const_name(head)
        if n is None:
            n = {"b": "«bvar»", "l": "«lambda»", "p": "«pi»", "j": "«proj»",
                 "s": "«sort»", "t": "«str»", "n": "«nat»"}.get(head[0], "«?»")
        self.opaque_heads[n] += 1
        self._decl_heads.add(n)
        return super()._spine_atom(head, args, depth)

    # -- functions -------------------------------------------------------

    def fun_dim(self, f, depth: int, arg_dim=None):
        """The dimension of the *values* of a function term.

        A `fun t => body` is descended into at `depth + 1`, so the body's arithmetic is
        visible rather than collapsing to one fresh atom, and — when the caller knows what
        the function is applied to — the binder is identified with the argument. That row is
        what substitution would have done, and it is sound because the two terms have the
        same type; doing it as a row rather than as a substitution means no tree node is
        ever synthesized, which matters because `_open` misreads a node that
        `phys_i3.annotate` has never seen.
        """
        if f[0] == "l":
            v = self._bvar_atom(0, depth + 1)
            if arg_dim is not None:
                self._emit(_sub({v: ONE}, arg_dim))
            return self.dim(f[3], depth + 1)
        return self.dim(f, depth)

    # -- dispatch --------------------------------------------------------

    def dim(self, e, depth: int):
        if self.rules:
            h, args = spine(e)
            name = const_name(h)
            r = VALUE_RULES.get(name) if name is not None else None
            if r is not None:
                family, arity, fn = r
                if family in self.rules and len(args) >= arity:
                    out = fn(self, e, h, args[:arity], depth)
                    if out is not None:
                        self.rule_hits[name] += 1
                        self.decomposed += 1
                        return out
        return super().dim(e, depth)

    def scan(self, e, depth: int) -> None:
        if self.rules & {f for f, _a, _fn in PROP_RULES.values()}:
            self._prop_scan(e, depth)
        super().scan(e, depth)

    def _prop_scan(self, e, depth: int) -> None:
        """A second walk, for the Prop-valued rules.

        `HasDerivAt f f' x` is an equation about dimensions and is not an `Eq`, so the base
        scan never reaches it — it looks for `Eq` and `+` only. Separate walk rather than a
        reimplemented one: duplicating the base traversal is how the two drift apart.
        """
        stack = [(e, depth)]
        while stack:
            n, d = stack.pop()
            t = n[0]
            if t == "a":
                h, args = spine(n)
                nm = const_name(h)
                r = PROP_RULES.get(nm) if nm is not None else None
                if r is not None:
                    family, arity, fn = r
                    if family in self.rules and len(args) >= arity:
                        if fn(self, n, h, args[:arity], d):
                            self.rule_hits[nm] += 1
                stack.append((h, d))
                for a in args:
                    stack.append((a, d))
            elif t in ("p", "l"):
                stack.append((n[2], d))
                stack.append((n[3], d + 1))
            elif t == "e":
                stack.append((n[1], d))
                stack.append((n[2], d))
                stack.append((n[3], d + 1))
            elif t == "j":
                stack.append((n[3], d))


# ---------------------------------------------------------------------------
# Loading (same filters and the same reporting as `phys-dimensional.py`)
# ---------------------------------------------------------------------------

def load_rows(path, cap, only_module=None, drop_module=None):
    rows = []
    stats = collections.Counter()
    dropped_modules = collections.Counter()
    t0 = time.time()
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            stats["rows"] += 1
            mod = r.get("module", "")
            if only_module and not any(mod.startswith(m) for m in only_module):
                stats["out_of_scope"] += 1
                continue
            if drop_module and any(mod.startswith(m) for m in drop_module):
                stats["out_of_scope"] += 1
                continue
            s = r.get("stmt")
            if not s:
                stats["no_stmt"] += 1
                continue
            if len(s) > cap:
                stats["over_cap"] += 1
                dropped_modules[mod] += 1
                continue
            try:
                i3.parse(s)
            except (ValueError, IndexError, RecursionError):
                stats["parse_failed"] += 1
                continue
            rows.append((r.get("name", ""), mod, r.get("kind", ""), s))
            stats["kept"] += 1
    stats["seconds"] = round(time.time() - t0, 1)
    return rows, stats, dropped_modules


def trees(rows):
    for name, module, kind, s in rows:
        yield name, module, kind, i3.parse(s)


# ---------------------------------------------------------------------------
# The system
# ---------------------------------------------------------------------------

def build_system(rows, keying="fine", literals="dimensionless", rules=None,
                 bvar="local"):
    table = AtomTable()
    ex = CalcExtractor(table, keying=keying, literals=literals, rules=rules, bvar=bvar)
    global_rows, provenance = [], []
    stats = collections.Counter()
    for name, _mod, _kind, tree in trees(rows):
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
    ex.reset("")                                     # flush the last declaration's heads
    return table, global_rows, provenance, stats, ex


def solve(table, global_rows):
    ech = Echelon(order=lambda c: table.keys[c])
    for r in global_rows:
        ech.add(r)
    return ech, ech.columns()


def classify(ech):
    single = [c for c, r in ech.pivots.items() if len(r) == 1]
    pairs = [(c, r) for c, r in ech.pivots.items() if len(r) == 2]
    rich = [(c, r) for c, r in ech.pivots.items() if len(r) >= 3]
    powered = [(c, r) for c, r in rich if any(abs(v) != 1 for v in r.values())]
    return single, pairs, rich, powered


def shuffle_rows(global_rows, rng):
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


# ---------------------------------------------------------------------------
# Static coverage — a number that does not move when the walk does
# ---------------------------------------------------------------------------

def static_coverage(rows, rules=None):
    """Head-constant census over every maximal application spine in the kept statements.

    The dynamic `opaque / (opaque + decomposed)` counts what the solver's own walk looked at,
    and that walk *changes* when a rule lets it descend into a lambda body. So it is reported
    beside this, which does not: the tree is the same tree whatever the rule set, and the
    only question asked of each spine is whether its head is in the vocabulary.
    """
    fams = set(FAMILIES) if rules is None else set(rules)
    known = {n for n, (f, _a, _fn) in VALUE_RULES.items() if f in fams}
    known |= {n for n, (f, _a, _fn) in PROP_RULES.items() if f in fams}
    seen = collections.Counter()
    for _n, _m, _k, tree in trees(rows):
        for h, _args in i3.iter_spines(tree):
            cn = const_name(h)
            if cn is None:
                seen["bound"] += 1
            elif cn in dl.OPERATORS:
                seen["arith"] += 1
            elif cn in known:
                seen["calculus"] += 1
            else:
                seen["opaque"] += 1
    return seen


# ---------------------------------------------------------------------------
# Arity check — the one lookup, against the closed slice
# ---------------------------------------------------------------------------

def arity_check(path):
    want = {}
    for n, (f, a, _fn) in list(VALUE_RULES.items()) + list(PROP_RULES.items()):
        want[n] = (f, a)
    found = {}
    with open(path) as fh:
        for line in fh:
            i = line.find('"name":"')
            if i < 0:
                continue
            j = line.index('"', i + 8)
            nm = line[i + 8:j]
            if nm in want and nm not in found:
                r = json.loads(line)
                s = r.get("stmt")
                if not s:
                    continue
                try:
                    binders, _body = i3.pi_telescope(i3.parse(s))
                except (ValueError, IndexError, RecursionError):
                    continue
                found[nm] = len(binders)
    return want, found


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def short(key, width=58):
    return key if len(key) <= width else key[:width] + "…"


def _coef(v):
    if v == 1:
        return "+ "
    if v == -1:
        return "- "
    return ("+ " if v > 0 else "- ") + str(abs(v)) + "*"


def render_relation(table, col, row, width=4):
    terms = [f"{_coef(-v)}{short(table.keys[c], 46)}"
             for c, v in sorted(row.items(), key=lambda kv: table.keys[kv[0]]) if c != col]
    if not terms:
        return f"{short(table.keys[col])} = 0"
    body = " ".join(terms[:width]) + ("" if len(terms) <= width
                                      else f" … (+{len(terms) - width})")
    return f"{short(table.keys[col])} = " + body.lstrip("+ ")


def attribute(table, ech, grows, prov, top=8, limit=4):
    """Which declarations a multi-atom relation could have come from.

    **Attribution, not derivation.** A pivot row is a combination of arbitrarily many source
    rows, and recovering that combination exactly means carrying a coefficient vector over
    the sources through the whole elimination. What this does instead is name every
    declaration whose own global row shares **two or more** atoms with the relation — a
    superset of the true witnesses, and cheap. The prior art's spec (§9) requires real
    witnesses on `Relation`; this is the placeholder that says what real witnesses would
    have to beat, and it is labelled as such wherever it is printed.
    """
    rich = [(c, r) for c, r in ech.pivots.items() if len(r) >= 3]
    rich.sort(key=lambda cr: table.keys[cr[0]])
    out = []
    for c, r in rich[:top]:
        atoms = set(r)
        hits = collections.Counter()
        for row, name in zip(grows, prov):
            n = len(atoms & set(row))
            if n >= 2:
                hits[name] = max(hits[name], n)
        out.append((c, r, hits.most_common(limit)))
    return out


def banner(s):
    print()
    print("=" * 78)
    print(s)
    print("=" * 78)
    sys.stdout.flush()


def report_system(label, rows, keying, literals, rules, show=0, rng=None,
                  shuffle=False, bvar="local"):
    t0 = time.time()
    table, grows, prov, st, ex = build_system(rows, keying=keying, literals=literals,
                                              rules=rules, bvar=bvar)
    ech, connected = solve(table, grows)
    single, pairs, rich, powered = classify(ech)
    op, dec = st["opaque"], st["decomposed"]
    frac = op / max(op + dec, 1)
    per_k = 1000 * len(rich) / max(st["decls_with_rows"], 1)
    print(f"\n[{label}]  rules={','.join(sorted(rules)) if rules else 'none'}  bvar={bvar}")
    print(f"  declarations contributing rows {st['decls_with_rows']:,}")
    print(f"  raw rows                       {st['raw_rows']:,}")
    print(f"  rows after local elimination   {st['global_rows']:,}")
    print(f"  arithmetic nodes decomposed    {dec:,}")
    print(f"  subterms left opaque           {op:,}   ({frac:.1%} of the walk)")
    print(f"  connected global atoms |C|     {len(connected):,}")
    print(f"  rank                           {ech.rank:,}")
    print(f"  grading space dim              {len(connected) - ech.rank:,}")
    print(f"  forced dimensionless           {len(single):,}")
    print(f"  forced equal to one other atom {len(pairs):,}")
    print(f"  MULTI-ATOM RELATIONS           {len(rich):,}"
          f"   ({per_k:.2f} per 1,000 decls)")
    print(f"  …with a coefficient outside ±1 {len(powered):,}"
          + (f" ({len(powered) / len(rich):.1%})" if rich else ""))
    print(f"  bound variables keyed by type  {ex.typed_bvars:,} "
          f"(left local {ex.local_bvars:,})")
    print(f"  [{time.time() - t0:.1f}s]")
    if show:
        rich_sorted = sorted(rich, key=lambda cr: table.keys[cr[0]])
        print(f"  --- {min(show, len(rich_sorted))} of {len(rich)} relations ---")
        for c, r in rich_sorted[:show]:
            print("   " + render_relation(table, c, r))
    out = {"decls": st["decls_with_rows"], "rows": st["global_rows"],
           "opaque": op, "decomposed": dec, "opaque_frac": frac,
           "C": len(connected), "rank": ech.rank, "dim": len(connected) - ech.rank,
           "single": len(single), "pairs": len(pairs), "rich": len(rich),
           "powered": len(powered), "per_k": per_k}
    if shuffle:
        grs = shuffle_rows(grows, rng)
        es, cs = solve(table, grs)
        s1, s2, s3, s4 = classify(es)
        print(f"  control, atoms shuffled: |C| {len(cs):,}  rank {es.rank:,}  "
              f"grading dim {len(cs) - es.rank:,}  multi-atom relations {len(s3):,}")
        out["shuffled"] = {"C": len(cs), "rank": es.rank, "dim": len(cs) - es.rank,
                           "rich": len(s3)}
    return out, table, ech, grows, prov, ex


# ---------------------------------------------------------------------------
# W — evolution equations and conservation laws
# ---------------------------------------------------------------------------

def evolution_census(rows):
    """Every `Eq` with a derivative on one side, split by what is on the other.

    Structural throughout: the classification reads the spine heads of the two sides of an
    `Eq` node and nothing else. Names are attached afterwards, in the report.
    """
    out = collections.Counter()
    conservation, evolution = [], []
    for name, mod, _k, tree in trees(rows):
        seen_c = seen_e = False
        stack = [tree]
        while stack:
            n = stack.pop()
            t = n[0]
            if t == "a":
                h, args = spine(n)
                if const_name(h) == "Eq" and len(args) == 3:
                    for i, j in ((1, 2), (2, 1)):
                        hh, aa = spine(args[i])
                        if const_name(hh) in DERIV_HEADS:
                            other = args[j]
                            oh, _oa = spine(other)
                            zero = (rat_literal(other) == 0)
                            if zero:
                                out["conservation"] += 1
                                seen_c = True
                            else:
                                out["evolution"] += 1
                                seen_e = True
                                out["evol_head_" + str(const_name(oh))] += 1
                            break
                stack.append(h)
                stack.extend(args)
            elif t in ("p", "l"):
                stack.append(n[2])
                stack.append(n[3])
            elif t == "e":
                stack.extend((n[1], n[2], n[3]))
            elif t == "j":
                stack.append(n[3])
        if seen_c:
            conservation.append((name, mod))
        if seen_e:
            evolution.append((name, mod))
    return out, conservation, evolution


def rows_from(rows, names, rules, bvar="local"):
    """How many *global* rows a named subset of declarations contributes."""
    sub = [r for r in rows if r[0] in names]
    if not sub:
        return 0, 0
    table, grows, _p, st, _ex = build_system(sub, rules=rules, bvar=bvar)
    return st["decls_with_rows"], st["global_rows"]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _synthetic():
    """A synthetic mechanics corpus, written as I3 trees, whose grading is known in advance.

    Nine independent statements over twelve quantities, plus three deliberately redundant
    ones. `Time` is a non-scalar carrier so its binders are keyed by type; every value lives
    in `Real`, which is a scalar and is therefore never keyed by type — the same asymmetry
    the physics corpus has.
    """
    C = lambda n: ("c", n)                                              # noqa: E731

    def A(f, *xs):
        for x in xs:
            f = ("a", f, x)
        return f

    R, TIME, I = C("Real"), C("Time"), C("i")
    eq = lambda l, r: A(C("Eq"), R, l, r)                               # noqa: E731
    mul = lambda a, b: A(C("HMul.hMul"), R, R, R, I, a, b)              # noqa: E731
    lam = lambda body: ("l", "d", TIME, body)                           # noqa: E731
    fa = lambda body: ("p", "d", TIME, body)                            # noqa: E731
    drv = lambda f, x: A(C("deriv"), TIME, I, R, I, I, I, f, x)         # noqa: E731
    idrv = lambda k, f, x: A(C("iteratedDeriv"), TIME, I, R, I, I,      # noqa: E731
                             ("n", k), f, x)
    ii = lambda f, a, b: A(C("intervalIntegral"), R, I, I, f, a, b,     # noqa: E731
                           C("volume"))
    mi = lambda f: A(C("MeasureTheory.integral"), TIME, R, I, I, I,     # noqa: E731
                     C("volume"), f)
    nrm = lambda x: A(C("Norm.norm"), R, I, x)                          # noqa: E731
    sqrt = lambda x: A(C("Real.sqrt"), x)                               # noqa: E731
    fsum = lambda f: A(C("Finset.sum"), R, C("Idx"), I, C("s"), f)      # noqa: E731
    hda = lambda f, fp, x: A(C("HasDerivAt"), TIME, I, R, I, I, I, I, f, fp, x)  # noqa: E731
    pos, vel, acc, mom, frc = (C(x) for x in ("pos", "vel", "acc", "mom", "force"))
    mass, energy, spd, spd2, epart = (C(x) for x in
                                      ("mass", "energy", "spd", "spd2", "epart"))
    B = ("b", 0)
    return {
        # 1  ∀ t : Time, vel t = deriv (fun s => pos s) t
        "vel_def": fa(eq(A(vel, B), drv(lam(A(pos, B)), B))),
        # 2  ∀ t, acc t = deriv (fun s => vel s) t
        "acc_def": fa(eq(A(acc, B), drv(lam(A(vel, B)), B))),
        # 3  ∀ t, mom t = mass * vel t
        "mom_def": fa(eq(A(mom, B), mul(mass, A(vel, B)))),
        # 4  ∀ t, force t = deriv (fun s => mom s) t          (Newton II)
        "newton2": fa(eq(A(frc, B), drv(lam(A(mom, B)), B))),
        # 5  ∀ t, energy t = force t * pos t                  (work)
        "work": fa(eq(A(energy, B), mul(A(frc, B), A(pos, B)))),
        # 6  ∀ t, mom t = ∫ s, force s ∂volume                (impulse)
        "impulse": fa(eq(A(mom, B), mi(lam(A(frc, B))))),
        # 7  ∀ t, spd t = ‖vel t‖
        "speed": fa(eq(A(spd, B), nrm(A(vel, B)))),
        # 8  ∀ t, spd t = √(spd2 t)
        "speed_sq": fa(eq(A(spd, B), sqrt(A(spd2, B)))),
        # 9  ∀ t, energy t = ∑ i, epart i t
        "energy_parts": fa(eq(A(energy, B), fsum(("l", "d", C("Idx"), A(epart, B))))),
        # redundant: the FTC restates 1
        "ftc": fa(fa(eq(A(pos, B), ii(lam(A(vel, B)), ("b", 1), B)))),
        # redundant: the second derivative restates 1 and 2
        "acc_alt": fa(eq(A(acc, B), idrv(2, lam(A(pos, B)), B))),
        # redundant: a `HasDerivAt` hypothesis restates 1
        "hyp": fa(("p", "i", hda(lam(A(pos, B)), A(vel, B), B), C("True"))),
    }


def selftest():
    """The synthetic corpus, with the answer fixed before the solver runs.

    Assertions are properties, not pinned output:

      * the grading space has dimension exactly **3** — one per base dimension. A `deriv`
        rule with the wrong sign, or an integral rule that divided instead of multiplying,
        would tie two together and give 2; one that lost the point's dimension entirely
        would leave `Time` unconnected and give 4.
      * the intended exponent assignment satisfies **every** row, and no atom in any row is
        outside the intended vocabulary.
      * the three redundant statements are **implied** by the nine that precede them —
        which is what says the rules compose rather than merely fire.
      * no global atom key carries a declaration name. That is the guard against the prior
        art's §3 defect: `has_loose_bvar(a, depth)` asks whether a subterm escapes the whole
        statement, is therefore always false, and makes every key local — at which point
        the grading looks healthy and is empty.
    """
    stmts = _synthetic()
    core = [k for k in stmts if k not in ("ftc", "acc_alt", "hyp")]
    truth = {"pos(_)": {"L": 1}, "vel(_)": {"L": 1, "T": -1},
             "acc(_)": {"L": 1, "T": -2}, "mass()": {"M": 1},
             "mom(_)": {"M": 1, "L": 1, "T": -1},
             "force(_)": {"M": 1, "L": 1, "T": -2},
             "energy(_)": {"M": 1, "L": 2, "T": -2},
             "epart(_)": {"M": 1, "L": 2, "T": -2},
             "spd(_)": {"L": 1, "T": -1}, "spd2(_)": {"L": 2, "T": -2},
             "volume()": {"T": 1}, "⟨Time()⟩": {"T": 1}}
    rc = 0
    for bvar in ("type-nonscalar", "local"):
        tab = AtomTable()
        ex = CalcExtractor(tab, bvar=bvar)
        per, grows = {}, []
        for n, t in stmts.items():
            ex.reset(n, t)
            ex.scan(t, 0)
            per[n] = eliminate_locals(ex.rows, lambda c: tab.is_local[c])
            grows += per[n]
        ech = Echelon(order=lambda c: tab.keys[c])
        for r in grows:
            ech.add(r)
        cols = ech.columns()
        dim = len(cols) - ech.rank
        bad, unknown = 0, set()
        for r in grows:
            tot = {}
            for c, co in r.items():
                k = tab.keys[c]
                if k not in truth:
                    unknown.add(k)
                for g, e in truth.get(k, {}).items():
                    tot[g] = tot.get(g, 0) + co * e
            bad += any(tot.values())
        fit = Echelon()
        for n in core:
            for r in per[n]:
                fit.add(r)
        implied = {n: all(fit.implies(r) for r in per[n]) and bool(per[n])
                   for n in ("ftc", "acc_alt", "hyp")}
        leaked = sorted({tab.keys[c] for c in cols if tab.keys[c].startswith("?")})
        want_dim = 3 if bvar == "type-nonscalar" else None
        ok = bad == 0 and not leaked and not unknown
        if want_dim is not None:
            ok = ok and dim == want_dim and all(implied.values())
        rc |= 0 if ok else 1
        print(f"selftest[bvar={bvar}]: columns {len(cols)}  rank {ech.rank}  "
              f"grading dim {dim}" + (f" (want {want_dim})" if want_dim else "") +
              f"  rows violating truth {bad} (want 0)  redundant implied {implied}"
              f"  local atoms leaked {len(leaked)} (want 0)  "
              f"unkeyed {sorted(unknown)} (want [])  ->  {'PASS' if ok else 'FAIL'}")
        for c, r in sorted(ech.pivots.items(), key=lambda kv: tab.keys[kv[0]]):
            print("   ", render_relation(tab, c, r))
    return rc


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice")
    ap.add_argument("--control", default=None, help="the mathlib-algebra control (C3)")
    ap.add_argument("--calc-control", default=None,
                    help="the calculus control (C4): Mathlib.Analysis/MeasureTheory")
    ap.add_argument("--cap", type=int, default=20000)
    ap.add_argument("--module", default=None)
    ap.add_argument("--drop-module", default=None)
    ap.add_argument("--keying", default="fine", choices=("fine", "coarse"))
    ap.add_argument("--bvar", default="type-nonscalar",
                    choices=("local", "type", "type-nonscalar", "type-nonscalar-closed"),
                    help="how a bound variable is keyed; see C6")
    ap.add_argument("--literals", default="dimensionless",
                    choices=("dimensionless", "free"))
    ap.add_argument("--rules", default="all",
                    help="comma-separated families, `all`, or `none`")
    ap.add_argument("--ablate", action="store_true", help="C5: drop each family in turn")
    ap.add_argument("--census", action="store_true", help="opacity census only")
    ap.add_argument("--arity-check", action="store_true")
    ap.add_argument("--wild", action="store_true", help="W: evolution vs conservation")
    ap.add_argument("--witness", type=int, default=0,
                    help="attribute the first N relations to declarations")
    ap.add_argument("--show", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    rng = random.Random(args.seed)
    results = {"argv": sys.argv[1:]}

    if args.arity_check:
        banner("arity check — rule heads against their own type rows in the closed slice")
        print(f"lookup slice: {CLOSED_SLICE}  (the one query in this script that reads a "
              f"signature)")
        want, found = arity_check(CLOSED_SLICE)
        agree = dis = miss = 0
        # A function-valued constant's type telescope continues past the value into the
        # result's own arguments, so its `Pi` count exceeds the arity at which the rule must
        # fire. Listed rather than silently tolerated.
        FUNC_VALUED = {"Matrix.mulVec"}
        for n in sorted(want):
            fam, a = want[n]
            got = found.get(n)
            mark = ("ok" if got == a else
                    "ok(fn)" if n in FUNC_VALUED and got is not None and got > a else
                    "MISSING" if got is None else "MISMATCH")
            if mark.startswith("ok"):
                agree += 1
                got = a
            elif got is None:
                miss += 1
            else:
                dis += 1
            if got != a:
                print(f"  {mark:<9} {n:<34} rule={a:<3} slice={got}")
        print(f"  agree {agree}   mismatch {dis}   not in slice {miss}   "
              f"of {len(want)} rule heads")
        results["arity"] = {"agree": agree, "mismatch": dis, "missing": miss,
                            "detail": {n: (want[n][1], found.get(n)) for n in want}}
        if not args.slice:
            _dump(args, results)
            return

    if not args.slice:
        ap.error("--slice is required unless --selftest or --arity-check alone")

    only_mod = args.module.split(",") if args.module else None
    drop_mod = args.drop_module.split(",") if args.drop_module else None

    banner(f"loading {args.slice}  cap={args.cap:,}")
    rows, st, dropped = load_rows(args.slice, args.cap, only_mod, drop_mod)
    print(f"rows {st['rows']:,}  kept {st['kept']:,}  over cap {st['over_cap']:,}  "
          f"out of scope {st['out_of_scope']:,}  no stmt {st['no_stmt']:,}  "
          f"parse failed {st['parse_failed']:,}  [{st['seconds']}s]")
    if dropped:
        print("  over-cap by module: " +
              ", ".join(f"{m.split('.')[-1]} {c}" for m, c in dropped.most_common(5)))
    print("closure: not required — every measurement below reads statement trees only "
          "(no erasure, no citation followed). See the module docstring.")
    results["load"] = dict(st)

    if args.census:
        banner("opacity census — which heads the solver cannot see through")
        for label, rules in (("baseline (--rules none)", set()),
                             ("with calculus rules", set(FAMILIES))):
            table, grows, _p, s, ex = build_system(rows, rules=rules)
            op, dec = s["opaque"], s["decomposed"]
            print(f"\n{label}: opaque {op:,}  decomposed {dec:,}  "
                  f"opaque fraction {op / max(op + dec, 1):.1%}")
            print(f"  {'occurrences':>11}  {'decls':>6}  head")
            for h, c in ex.opaque_heads.most_common(40):
                print(f"  {c:>11,}  {ex.opaque_head_ndecls[h]:>6,}  {h}")
            if rules:
                print("  rule hits: " + ", ".join(
                    f"{h}={c:,}" for h, c in ex.rule_hits.most_common(25)))
            results.setdefault("census", {})[label] = {
                "opaque": op, "decomposed": dec,
                "top": ex.opaque_heads.most_common(60),
                "hits": ex.rule_hits.most_common(40)}
        _dump(args, results)
        return

    rules = (set() if args.rules == "none"
             else set(FAMILIES) if args.rules == "all"
             else set(args.rules.split(",")))
    bad = rules - set(FAMILIES)
    if bad:
        ap.error(f"unknown rule families {sorted(bad)}; known: {FAMILIES}")

    banner("static coverage — every maximal application spine, rule-set independent")
    base_cov = static_coverage(rows, rules=set())
    calc_cov = static_coverage(rows, rules=set(FAMILIES))
    tot = sum(base_cov.values())
    print(f"  spines {tot:,}   bound-headed {base_cov['bound']:,}")
    print(f"  baseline:  arithmetic {base_cov['arith']:,}   opaque {base_cov['opaque']:,}"
          f"   opaque fraction {base_cov['opaque'] / max(tot, 1):.1%}")
    print(f"  +calculus: arithmetic {calc_cov['arith']:,}   calculus {calc_cov['calculus']:,}"
          f"   opaque {calc_cov['opaque']:,}"
          f"   opaque fraction {calc_cov['opaque'] / max(tot, 1):.1%}")
    results["static_coverage"] = {"baseline": dict(base_cov), "calculus": dict(calc_cov)}

    banner("C0/C2/C6 — the 2x2: rule set against bound-variable keying")
    print("The two changes are separable and are separated: `rules none / bvar local` is the")
    print("prior art, and each other cell adds exactly one thing.")
    grid = {}
    for rs, rlabel in ((set(), "none"), (rules, "calculus")):
        for bv in ("local", args.bvar):
            r, *_ = report_system(f"physlib rules={rlabel} bvar={bv}", rows, args.keying,
                                  args.literals, rs, show=0, bvar=bv)
            grid[(rlabel, bv)] = r
            if rlabel == "none" and bv == "local":
                results["baseline"] = r
    results["grid"] = {f"{a}|{b}": v for (a, b), v in grid.items()}
    print("\n  rules      bvar               opaque%   |C|    rank   dim   relations  powered")
    for (rlabel, bv), r in grid.items():
        print(f"  {rlabel:<10} {bv:<18} {r['opaque_frac']:6.1%}  {r['C']:6,} {r['rank']:6,} "
              f"{r['dim']:5,}  {r['rich']:8,}  {r['powered']:7,}")

    banner("the headline configuration, with its relations and its shuffle control")
    calc, table, ech, grows, prov, ex = report_system(
        "physlib, calculus", rows, args.keying, args.literals, rules,
        show=args.show, rng=rng, shuffle=True, bvar=args.bvar)
    results["calculus"] = calc
    print("\n  rule hits: " + ", ".join(f"{h}={c:,}" for h, c in ex.rule_hits.most_common(30)))
    results["rule_hits"] = ex.rule_hits.most_common(60)

    if args.witness:
        print("\n  candidate witnesses (declarations sharing >=2 atoms with the relation;")
        print("  an over-approximation of the true derivation, see `attribute`):")
        att = attribute(table, ech, grows, prov, top=args.witness)
        for c, r, hits in att:
            print("   " + render_relation(table, c, r, width=3))
            for nm, k in hits:
                print(f"        {k} atoms  {nm}")
        results["witnesses"] = [(table.keys[c], hits) for c, _r, hits in att]

    banner("C6 — the collapse control: `--bvar type` drops the scalar guard")
    coll, *_ = report_system("physlib, calculus, bvar=type", rows, args.keying,
                             args.literals, rules, show=6, bvar="type")
    results["bvar_type"] = coll

    if args.ablate:
        banner("C5 — rule ablation: each family removed in turn")
        results["ablation"] = {}
        for fam in sorted(rules):
            sub = rules - {fam}
            r, *_ = report_system(f"physlib, without {fam}", rows, args.keying,
                                  args.literals, sub, show=0, bvar=args.bvar)
            results["ablation"][fam] = r

    if args.control:
        banner("C3 — the mathlib-algebra control (must stay at 0 multi-atom relations)")
        crows, cst, _d = load_rows(args.control, args.cap)
        print(f"  kept {cst['kept']:,} of {cst['rows']:,}  [{cst['seconds']}s]")
        cb, *_ = report_system("mathlib-algebra, rules none, bvar local", crows, args.keying,
                               args.literals, set(), show=0, bvar="local")
        cc, *_ = report_system("mathlib-algebra, calculus", crows, args.keying,
                               args.literals, rules, show=8, bvar=args.bvar)
        results["control_algebra"] = {"baseline": cb, "calculus": cc}
        del crows

    if args.calc_control:
        banner("C4 — the calculus control: pure mathematics that is nothing but calculus")
        krows, kst, _d = load_rows(args.calc_control, args.cap)
        print(f"  kept {kst['kept']:,} of {kst['rows']:,}  [{kst['seconds']}s]")
        kb, *_ = report_system("mathlib-analysis, rules none, bvar local", krows,
                               args.keying, args.literals, set(), show=0, bvar="local")
        # The portable vocabulary only: physlib's own `Time.deriv`/`Space.deriv` cannot fire
        # here, and running the comparison without them makes that explicit rather than
        # relying on the reader to notice.
        kc, *_ = report_system("mathlib-analysis, calculus", krows, args.keying,
                               args.literals, rules - {"physlib"}, show=20, bvar=args.bvar)
        results["control_calculus"] = {"baseline": kb, "calculus": kc}
        portable, *_ = report_system("physlib, calculus minus physlib family", rows,
                                     args.keying, args.literals, rules - {"physlib"},
                                     show=0, bvar=args.bvar)
        results["physlib_portable"] = portable
        pk_phys, pk_ctrl = portable["per_k"], kc["per_k"]
        verdict = ("PASS — the calculus control's relation rate is under half physlib's"
                   if pk_ctrl < 0.5 * pk_phys else
                   "FAIL — the rules produce comparable structure on pure mathematics; "
                   "the physics claim is withdrawn for them")
        print(f"\n  pre-registered discriminator, portable rules both sides: physlib "
              f"{pk_phys:.2f} vs analysis {pk_ctrl:.2f} multi-atom relations per 1,000 "
              f"declarations")
        print(f"  {verdict}")
        results["c4_verdict"] = verdict
        del krows

    if args.wild:
        banner("W — is an evolution equation structurally distinguished?")
        cens, conservation, evolution = evolution_census(rows)
        print(f"  `Eq` nodes with a derivative on one side and a literal zero on the other "
              f"(conservation laws): {cens['conservation']:,}")
        print(f"  `Eq` nodes with a derivative on one side and anything else "
              f"(equations of motion):   {cens['evolution']:,}")
        print(f"  declarations stating a conservation law {len(conservation):,}   "
              f"an equation of motion {len(evolution):,}")
        print("\n  conservation laws:")
        for n, m in conservation[:20]:
            print(f"    {n}   [{m}]")
        print("\n  equations of motion:")
        for n, m in evolution[:25]:
            print(f"    {n}   [{m}]")
        heads = [(k[10:], v) for k, v in cens.items() if k.startswith("evol_head_")]
        heads.sort(key=lambda kv: -kv[1])
        print("\n  what an equation of motion has on its other side: " +
              ", ".join(f"{h}={c}" for h, c in heads[:12]))
        cd, cr = rows_from(rows, {n for n, _m in conservation}, rules, args.bvar)
        ed, er = rows_from(rows, {n for n, _m in evolution}, rules, args.bvar)
        print(f"\n  global rows contributed: conservation-law declarations {cr} from {cd} "
              f"decls;  equation-of-motion declarations {er} from {ed} decls")
        results["wild"] = {"conservation": len(conservation), "evolution": len(evolution),
                           "conservation_names": conservation[:60],
                           "evolution_names": evolution[:60],
                           "cons_rows": cr, "evol_rows": er,
                           "eq_conservation": cens["conservation"],
                           "eq_evolution": cens["evolution"]}

    _dump(args, results)


def _dump(args, results):
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=1, default=str)
        print(f"\n[json -> {args.json}]")


if __name__ == "__main__":
    main()
