"""The dimensional machinery `phys-dimensional.py` runs: atoms, constraints, and a solver.

Kept out of the experiment file so the experiment file reads as an experiment. Nothing here
decides anything; every threshold and every verdict lives in `phys-dimensional.py`.

## The one thing that is by name, stated plainly

The solver has to know that `HMul.hMul` multiplies and `HAdd.hAdd` adds. That is a fixed
vocabulary of **Lean's own algebraic hierarchy** — 20-odd names, no physics in any of them,
identical for the physics corpus and for the Mathlib control. Everything downstream is
learned: which constants are quantities, what their exponents are, how many independent
dimensions the corpus supports, and which equations pin which. No quantity is ever
recognised by its name, and the word "velocity" appears nowhere in the decision path.

## The trap this file exists to avoid

An atom keyed on its head constant alone identifies `single .length` with `single .time`,
because both are headed by `single`. One such row forces `L𝓭 = T𝓭` and the entire recovered
lattice collapses to a point — silently, in the direction that still produces output. So the
default keying includes every **closed** argument of the spine and writes `_` for the open
ones. `--keying coarse` reproduces the defect on demand, which is the only way to measure
what the fine keying is worth.
"""

from __future__ import annotations

from fractions import Fraction

from phys_i3 import (annotate, const_name, has_loose_bvar, node_count,
                     render, spine)

# ---------------------------------------------------------------------------
# The ambient algebraic vocabulary. Lean's, not physics'.
# ---------------------------------------------------------------------------

# Heterogeneous forms take (α, β, γ, inst, a, b); homogeneous ones (α, inst, a, b). Both
# are read from the *end* of the spine, so the arity difference costs nothing.
ADD = {"HAdd.hAdd", "Add.add", "HSub.hSub", "Sub.sub"}
MUL = {"HMul.hMul", "Mul.mul", "HSMul.hSMul", "SMul.smul"}
DIV = {"HDiv.hDiv", "Div.div"}
POW = {"HPow.hPow", "Pow.pow", "Monoid.npow", "Monoid.zpow", "DivisionRing.zpow"}
NEG = {"Neg.neg"}
INV = {"Inv.inv"}
# Transparent: a cast changes the carrier and not the dimension.
CAST = {
    "Nat.cast", "Int.cast", "Rat.cast", "NNRat.cast", "IntCast.intCast", "NatCast.natCast",
    "RatCast.ratCast", "NNReal.toReal", "Real.toNNReal", "Complex.ofReal", "algebraMap",
    "ENNReal.toReal", "ENNReal.ofReal", "Subtype.val",
}
LITERAL = {"OfNat.ofNat", "OfScientific.ofScientific", "Zero.zero", "One.one"}

OPERATORS = ADD | MUL | DIV | POW | NEG | INV | CAST | LITERAL

ZERO = Fraction(0)
ONE = Fraction(1)


class AtomTable:
    """Interns atom keys to ints so rows are dicts of small ints."""

    def __init__(self) -> None:
        self.keys: list[str] = []
        self.ids: dict[str, int] = {}
        self.is_local: list[bool] = []

    def intern(self, key: str, local: bool) -> int:
        i = self.ids.get(key)
        if i is None:
            i = len(self.keys)
            self.ids[key] = i
            self.keys.append(key)
            self.is_local.append(local)
        return i

    def __len__(self) -> int:
        return len(self.keys)


def _nat_literal(e) -> int | None:
    """The natural number a term denotes, or `None`. Handles `OfNat.ofNat _ (lit n) _`."""
    if e[0] == "n":
        return e[1]
    h, args = spine(e)
    n = const_name(h)
    if n in ("OfNat.ofNat", "Nat.cast", "Int.cast") and args:
        for a in args:
            v = _nat_literal(a)
            if v is not None:
                return v
    return None


class Extractor:
    """Turns one declaration's statement into homogeneous linear rows over atoms.

    A row is `dict[atom_id, Fraction]` and means "this sum of exponents is zero". Rows come
    from two places and both are equations the *statement* asserts:

    * the conclusion, when it is an `Eq`;
    * every additive node anywhere reachable, since `a + b` is only typeable when `a` and
      `b` carry the same dimension. Additive nodes inside hypotheses count too — a
      hypothesis is a statement about the same quantities.
    """

    def __init__(self, table: AtomTable, keying: str = "fine",
                 literals: str = "dimensionless") -> None:
        self.table = table
        self.keying = keying
        self.literals = literals
        self.reset("")

    def reset(self, decl: str, tree=None) -> None:
        self.decl = decl
        self.rows: list[dict[int, Fraction]] = []
        self._fresh = 0
        self.opaque = 0          # subterms treated as atoms rather than decomposed
        self.decomposed = 0      # arithmetic nodes actually understood
        self.needs, self.size = annotate(tree) if tree is not None else ({}, {})

    # -- atoms ------------------------------------------------------------

    def _fresh_local(self) -> int:
        self._fresh += 1
        return self.table.intern(f"?{self.decl}#f{self._fresh}", True)

    def _bvar_atom(self, idx: int, depth: int) -> int:
        # Absolute binder index, so two occurrences of one binder are one atom and two
        # binders that happen to sit at the same relative index are not.
        return self.table.intern(f"?{self.decl}#b{depth - 1 - idx}", True)

    def _spine_atom(self, head, args, depth: int) -> int:
        n = const_name(head)
        if n is None:
            if head[0] == "b":
                return self._bvar_atom(head[1], depth)
            if head[0] == "j":
                inner = self._term_key(head[3], depth)
                return self.table.intern(f"{head[1]}.{head[2]}<{inner}>", not inner)
            return self._fresh_local()
        if self.keying == "coarse":
            return self.table.intern(n, False)
        parts = []
        for a in args:
            if self._open(a, depth):
                parts.append("_")
                continue
            r = render(a, 120)
            # A truncated render can collide, and a collision *merges* two atoms — the
            # direction that manufactures a constraint and collapses the lattice. Losing a
            # constraint is recoverable; inventing one is not. So a truncated key carries
            # the argument's node count, which the annotation already has.
            parts.append(r if not r.endswith("…") else f"{r}#{self._size(a)}")
        return self.table.intern(f"{n}({','.join(parts)})", False)

    def _open(self, e, depth: int) -> bool:
        """Does `e` mention *any* enclosing binder?

        Not `has_loose_bvar(e, depth)`, which asks whether `e` escapes the whole statement
        and is therefore False for every subterm of a well-formed one. Under that reading a
        bound argument rendered as `#0`, so `velocity q t` keyed differently depending on how
        many binders happened to precede it and no two declarations ever shared an atom —
        the constraint system was nearly empty and the failure looked like "physics has no
        structure".
        """
        n = self.needs.get(id(e))
        return n > 0 if n is not None else has_loose_bvar(e, depth)

    def _size(self, e) -> int:
        return self.size.get(id(e)) or node_count(e)

    def _term_key(self, e, depth: int) -> str:
        return "" if self._open(e, depth) else render(e, 120)

    # -- the dimension of a term -----------------------------------------

    def dim(self, e, depth: int) -> dict[int, Fraction]:
        h, args = spine(e)
        name = const_name(h)

        if name in OPERATORS and len(args) >= 2:
            if name in ADD:
                u = self.dim(args[-2], depth)
                v = self.dim(args[-1], depth)
                self._emit(_sub(u, v))
                self.decomposed += 1
                return u
            if name in MUL:
                self.decomposed += 1
                return _add(self.dim(args[-2], depth), self.dim(args[-1], depth))
            if name in DIV:
                self.decomposed += 1
                return _sub(self.dim(args[-2], depth), self.dim(args[-1], depth))
            if name in POW:
                k = _nat_literal(args[-1])
                if k is not None and k <= 64:
                    self.decomposed += 1
                    return _scale(self.dim(args[-2], depth), Fraction(k))
                # A symbolic exponent makes the term non-linear in the exponents; making it
                # an atom loses information but never invents a constraint.
                self.opaque += 1
                return {self._spine_atom(h, args, depth): ONE}
            if name in CAST:
                self.decomposed += 1
                return self.dim(args[-1], depth)
            if name in LITERAL:
                return self._literal(e, depth)
        if name in NEG | INV and len(args) >= 1:
            self.decomposed += 1
            d = self.dim(args[-1], depth)
            return _scale(d, Fraction(-1)) if name in INV else d
        if name in LITERAL:
            return self._literal(e, depth)
        if e[0] == "n":
            return self._literal(e, depth)
        if e[0] == "b":
            return {self._bvar_atom(e[1], depth): ONE}
        if e[0] in ("l", "p", "s", "t", "e"):
            # Not an arithmetic term. Opaque rather than skipped: it still has *a*
            # dimension, and pretending otherwise would drop the equation it sits in.
            self.opaque += 1
            return {self._fresh_local(): ONE}
        self.opaque += 1
        return {self._spine_atom(h, args, depth): ONE}

    def _literal(self, e, depth: int) -> dict[int, Fraction]:
        v = _nat_literal(e)
        if self.literals == "free" or v in (0, 1):
            # `0` and `1` are the units of the two operations and typecheck at every
            # dimension; reading them as dimensionless invents constraints.
            return {self._fresh_local(): ONE}
        return {}

    # -- rows -------------------------------------------------------------

    def _emit(self, row: dict[int, Fraction]) -> None:
        if row:
            self.rows.append(row)

    def equation(self, lhs, rhs, depth: int) -> None:
        self._emit(_sub(self.dim(lhs, depth), self.dim(rhs, depth)))

    def scan(self, e, depth: int) -> None:
        """Walk for `Eq` nodes and additive nodes, at any depth, collecting rows.

        Descends under binders (raising `depth`) so that a hypothesis `(h : x = y * z)`
        contributes exactly as an assertion would.
        """
        stack = [(e, depth)]
        while stack:
            n, d = stack.pop()
            t = n[0]
            if t == "a":
                h, args = spine(n)
                nm = const_name(h)
                if nm == "Eq" and len(args) == 3:
                    self.equation(args[1], args[2], d)
                    # Keep descending: an `Eq` side that `dim` treated as one opaque atom
                    # may still hold a `+` or a nested `Eq` inside it, and a row emitted
                    # twice is a dependent row, which costs a reduction and no rank.
                    stack.append((args[1], d))
                    stack.append((args[2], d))
                    continue
                if nm in ADD and len(args) >= 2:
                    self.dim(n, d)   # emits the same-dimension row as a side effect
                    stack.append((args[-2], d))
                    stack.append((args[-1], d))
                    continue
                # Push the spine's parts rather than its two halves: re-spining every
                # prefix of an application chain is quadratic, and physlib's tensor
                # statements have chains thousands long.
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
# Sparse rational linear algebra
# ---------------------------------------------------------------------------

def _add(a, b):
    r = dict(a)
    for k, v in b.items():
        nv = r.get(k, ZERO) + v
        if nv:
            r[k] = nv
        else:
            r.pop(k, None)
    return r


def _sub(a, b):
    r = dict(a)
    for k, v in b.items():
        nv = r.get(k, ZERO) - v
        if nv:
            r[k] = nv
        else:
            r.pop(k, None)
    return r


def _scale(a, f):
    return {k: v * f for k, v in a.items()} if f else {}


class Echelon:
    """Incremental reduced row echelon form over ℚ, sparse.

    RREF rather than plain echelon because the *pivot rows are the result*: each one reads
    `atom = combination of later atoms`, which is a derived dimensional relation. An
    unreduced echelon form says the same thing in a basis nobody can read.
    """

    def __init__(self, order=None) -> None:
        self.pivots: dict[int, dict[int, Fraction]] = {}
        self.occ: dict[int, set[int]] = {}
        self.order = order or (lambda c: c)

    def reduce(self, row: dict[int, Fraction]) -> dict[int, Fraction]:
        row = dict(row)
        while True:
            hit = None
            for c in row:
                if c in self.pivots:
                    hit = c
                    break
            if hit is None:
                return row
            f = row[hit]
            for c, v in self.pivots[hit].items():
                nv = row.get(c, ZERO) - f * v
                if nv:
                    row[c] = nv
                else:
                    row.pop(c, None)

    def add(self, row: dict[int, Fraction], restrict=None) -> int | None:
        """Insert a row; returns the pivot column chosen, or `None` if it was dependent.

        `restrict` limits which columns may be chosen as pivots — that is how local atoms
        are eliminated first, leaving the Schur complement on the global ones.
        """
        row = self.reduce(row)
        if not row:
            return None
        cand = [c for c in row if restrict(c)] if restrict else list(row)
        if not cand:
            return None
        col = min(cand, key=self.order)
        f = row[col]
        row = {c: v / f for c, v in row.items()}
        for other in list(self.occ.get(col, ())):
            if other == col:
                continue
            pr = self.pivots.get(other)
            if pr is None:
                continue
            g = pr.get(col)
            if not g:
                continue
            for c, v in row.items():
                nv = pr.get(c, ZERO) - g * v
                if nv:
                    if c not in pr:
                        self.occ.setdefault(c, set()).add(other)
                    pr[c] = nv
                else:
                    if c in pr:
                        del pr[c]
                        self.occ.get(c, set()).discard(other)
        self.pivots[col] = row
        for c in row:
            self.occ.setdefault(c, set()).add(col)
        return col

    def implies(self, row: dict[int, Fraction]) -> bool:
        """Is this row already a consequence of the rows inserted so far?"""
        return not self.reduce(row)

    @property
    def rank(self) -> int:
        return len(self.pivots)

    def columns(self) -> set[int]:
        cols: set[int] = set()
        for r in self.pivots.values():
            cols.update(r)
        return cols


def eliminate_locals(rows, is_local) -> list[dict[int, Fraction]]:
    """Project one declaration's rows onto its global atoms.

    Valid blockwise because a local atom occurs in exactly one declaration's rows, so the
    Schur complement of the whole system is the concatenation of the per-declaration ones.
    """
    ech = Echelon()
    out = []
    for row in rows:
        red = ech.reduce(row)
        if not red:
            continue
        if any(is_local(c) for c in red):
            ech.add(red, restrict=is_local)
        else:
            out.append(red)
    return out
