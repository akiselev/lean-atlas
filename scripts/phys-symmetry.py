#!/usr/bin/env python3
"""Is there a *structural* signature of symmetry, invariance and conservation?

Physics's organizing principle is Noether's: a symmetry of the action gives a conserved
quantity. If that principle leaves a trace in a formalized physics library, the trace has to
be structural — a shape statements come in — because nothing else survives the trip from
mathematics into `Expr`.

So this script never looks at a declaration's *name*. Names appear in the output, to make a
result readable and spot-checkable, and nowhere in any selection. Every predicate below is a
property of the I3 statement encoding (`statement-hash.md`) and of the citation graph.

## The motifs, defined before anything was run

Peel the statement's `Pi` prefix; call the binders `B` and the remainder the conclusion `C`.
Take `C`'s application spine; if it has >= 2 arguments call the last two `L` and `R` (the
relation's two sides — `Eq a b` is `a(a(a(c(Eq),T),a),b)`, so the last two arguments are the
sides for *any* binary relation, with no name involved).

* **INV — invariance.** Anti-unify `L` and `R`. The pair is invariance-shaped when every
  differing position is a *wrapping*: at each one, one side's subterm is the other's with a
  one-hole context around it, all in the same direction, and at least one properly so. That
  is exactly `f (T x) = f x`, `<Λv, Λw> = <v, w>`, `P (T x) <-> P x`.
  - **INV-strict** additionally requires *one* context — the same `T` at every position,
    which is what "a transformation was applied" means as opposed to "both sides differ".
  - The occurrence must not sit under a binder. De Bruijn indices shift across binders, so
    "the same subterm" one binder deeper is a *different* term; accepting those would be the
    erasure bug of CLAUDE.md §5 rediscovered. Rejections are counted, not swallowed.
* **INV-IMP** — the same test applied to (antecedent, consequent) of a non-dependent `Pi`:
  `P x -> P (T x)`.
* **SWAP — equivariance / commutation.** The anti-unification's variables are a non-identity
  *permutation*: `{l_i} == {r_i}` as multisets with the pairing shuffled. `a * b = b * a` and
  `f (g x) = g (f x)` are one motif under this test, which is the claim that commutativity is
  the degenerate symmetry.
* **CONS — conservation.** One side of the relation mentions an explicitly bound variable the
  other side does not: `forall t, Q (phi t x) = Q x` — "the value does not depend on the
  parameter". **CONS-CLOSED** additionally requires the side that drops it to be closed (no
  loose de Bruijn index at all), i.e. `... = c` for a constant `c`.

## What a good answer looks like — written before the measurements

**Q1 — is there a signature?**
* *works*: INV-strict fires on a minority of theorems (roughly 0.1%-10%), the hit rate on
  scrambled pairs (`L` from one theorem, `R` from another) is far below the genuine rate, and
  a name-level spot check of hits reads as invariance rather than as boilerplate.
* *does not work*: it fires on ~0% (no signature), or on >50% (it is punctuation), or the
  scramble control fires at the same rate (the predicate is a property of terms, not of
  statements), or the hits are dominated by auto-generated declarations.

**Q2 — one motif or three?** Group INV hits by their `carriers` skeleton and score each
family's subfield spread against a **size-matched null** (findings sec. 17: cross-field reach
is the null, not the signal — a 20-member family spans 9.2 subfields by chance).
* *works*: an INV family with spread meaningfully above its size-matched expectation, whose
  members come from different theories.
* *does not work*: INV families are as concentrated as everything else. Findings sec. 17-18
  predict exactly this, so the honest prior is that the null wins.

**Q3 — Noether.** Count citation edges from CONS-matching declarations to INV-matching ones.
* *works*: the observed count exceeds the 99th percentile of **both** nulls — a uniform label
  shuffle and a **degree-matched** shuffle — and the effect is directional (CONS -> INV
  stronger than INV -> CONS).
* *does not work*: inside either null. The degree-matched null is the one that matters: INV
  statements might simply be popular, and a uniform shuffle cannot tell that from Noether.

**Q4 — neighbourhood shape.** In-degree, out-degree and transitive foundation size of INV
declarations against controls matched on subfield, kind and statement size.
* *works*: a difference that survives the matching.
* *does not work*: the difference is explained by statement size, which is the obvious
  confound — a bigger statement mentions more constants.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import random
import statistics
import sys
import threading
import time

sys.setrecursionlimit(400_000)

try:
    import atlas as fa
except ImportError:  # pragma: no cover
    fa = None

# ---------------------------------------------------------------------------
# I3 parser
# ---------------------------------------------------------------------------
# Node kinds. Hash-consed globally, so structural equality *is* integer equality —
# both within a statement and across the corpus.
K_BVAR, K_SORT, K_CONST, K_APP, K_LAM, K_PI, K_LET, K_NAT, K_STR, K_PROJ, K_HOLE, K_VAR = range(12)

TAG = b"atlas-stmt-v1;"


class Arena:
    """Hash-consed I3 terms over bytes.

    Bytes, not str: names are *byte*-length-prefixed and may hold any UTF-8, so `c(3:R,0)`
    is three bytes and one character. A character-indexed parser desynchronises on the first
    non-ASCII carrier, of which a physics corpus is made.
    """

    __slots__ = ("kind", "x", "y", "z", "sym", "lo", "sz", "conc", "_memo", "_syms",
                 "_symname", "nodes_built")

    def __init__(self) -> None:
        self.kind: list[int] = []
        self.x: list[int] = []
        self.y: list[int] = []
        self.z: list[int] = []
        self.sym: list[int] = []
        self.lo: list[int] = []      # 1 + largest loose de Bruijn index, 0 if closed
        self.sz: list[int] = []      # total nodes
        self.conc: list[int] = []    # non-hole, non-var nodes
        self._memo: dict[tuple, int] = {}
        self._syms: dict[bytes, int] = {}
        self._symname: list[bytes] = []
        self.nodes_built = 0

    def reset(self) -> None:
        """Drop the terms, keep the symbol table.

        Hash-consing is what makes structural equality an integer comparison, and it is a
        *global* invariant — the same trap CLAUDE.md sec. 5 records against `Arena::seal`.
        So the arena is reset **between statements**, never during one, and every key that
        has to survive a reset (a context, a family label) is a string built while the terms
        were live.
        """
        self.kind.clear()
        self.x.clear()
        self.y.clear()
        self.z.clear()
        self.sym.clear()
        self.lo.clear()
        self.sz.clear()
        self.conc.clear()
        self._memo.clear()

    def intern_sym(self, b: bytes) -> int:
        s = self._syms.get(b)
        if s is None:
            s = len(self._symname)
            self._syms[b] = s
            self._symname.append(b)
        return s

    def name(self, s: int) -> str:
        return self._symname[s].decode("utf-8", "replace")

    def mk(self, kind: int, sym: int = -1, x: int = -1, y: int = -1, z: int = -1) -> int:
        key = (kind, sym, x, y, z)
        n = self._memo.get(key)
        if n is not None:
            return n
        n = len(self.kind)
        self.kind.append(kind)
        self.sym.append(sym)
        self.x.append(x)
        self.y.append(y)
        self.z.append(z)
        if kind == K_BVAR:
            lo, sz, co = sym + 1, 1, 1
        elif kind in (K_SORT, K_CONST, K_NAT, K_STR):
            lo, sz, co = 0, 1, 1
        elif kind in (K_HOLE, K_VAR):
            lo, sz, co = 0, 1, 0
        elif kind == K_APP:
            lo = max(self.lo[x], self.lo[y])
            sz = 1 + self.sz[x] + self.sz[y]
            co = 1 + self.conc[x] + self.conc[y]
        elif kind in (K_LAM, K_PI):
            lo = max(self.lo[x], self.lo[y] - 1 if self.lo[y] else 0)
            sz = 1 + self.sz[x] + self.sz[y]
            co = 1 + self.conc[x] + self.conc[y]
        elif kind == K_LET:
            lo = max(self.lo[x], self.lo[y], self.lo[z] - 1 if self.lo[z] else 0)
            sz = 1 + self.sz[x] + self.sz[y] + self.sz[z]
            co = 1 + self.conc[x] + self.conc[y] + self.conc[z]
        else:  # K_PROJ
            lo, sz, co = self.lo[x], 1 + self.sz[x], 1 + self.conc[x]
        self.lo.append(lo)
        self.sz.append(sz)
        self.conc.append(co)
        self._memo[key] = n
        self.nodes_built += 1
        return n

    # -- parsing ------------------------------------------------------------
    def parse(self, enc: str | bytes) -> int:
        buf = enc.encode() if isinstance(enc, str) else enc
        i = 0
        if buf.startswith(TAG):
            i = len(TAG)
        root, i = self._parse_at(buf, i)
        if i != len(buf):
            raise ValueError(f"trailing bytes at {i}: {buf[i:i + 20]!r}")
        return root

    def _parse_at(self, buf: bytes, i: int) -> tuple[int, int]:
        stack: list[list[int]] = []   # [node_id, arity, filled, kind, sym]
        pend: list[list[int]] = []    # children collected for the frame on top
        while True:
            c = buf[i]
            nid = -1
            nchild = 0
            kind = -1
            sym = -1
            if c == 0x62:  # 'b'
                v, i = _nat(buf, i + 1)
                nid = self.mk(K_BVAR, v)
            elif c == 0x73 and buf[i + 1] == 0x28:  # 's('
                j = _skip_level(buf, i + 2)
                sym = self.intern_sym(buf[i + 2:j])
                assert buf[j] == 0x29, "sort"
                i = j + 1
                nid = self.mk(K_SORT, sym)
            elif c == 0x63 and buf[i + 1] == 0x28:  # 'c('
                ln, j = _len(buf, i + 2)
                sym = self.intern_sym(buf[j:j + ln])
                j += ln
                assert buf[j] == 0x2C, "const,"
                nlv, j = _nat(buf, j + 1)
                for _ in range(nlv):
                    assert buf[j] == 0x2C
                    j = _skip_level(buf, j + 1)
                assert buf[j] == 0x29, "const)"
                i = j + 1
                nid = self.mk(K_CONST, sym)
            elif c == 0x61 and buf[i + 1] == 0x28:  # 'a('
                i += 2
                kind, nchild = K_APP, 2
            elif (c == 0x6C or c == 0x70) and buf[i + 2] == 0x28:  # 'l'/'p' bi '('
                kind = K_LAM if c == 0x6C else K_PI
                sym = buf[i + 1]
                i += 3
                nchild = 2
            elif c == 0x65 and buf[i + 1] == 0x28:  # 'e('
                i += 2
                kind, nchild = K_LET, 3
            elif c == 0x6E:  # 'n'
                j = i + 1
                while j < len(buf) and 0x30 <= buf[j] <= 0x39:
                    j += 1
                nid = self.mk(K_NAT, self.intern_sym(buf[i + 1:j]))
                i = j
            elif c == 0x74:  # 't' string literal
                ln, j = _len(buf, i + 1)
                nid = self.mk(K_STR, self.intern_sym(buf[j:j + ln]))
                i = j + ln
            elif c == 0x6A and buf[i + 1] == 0x28:  # 'j('
                ln, j = _len(buf, i + 2)
                sym = self.intern_sym(buf[j:j + ln])
                j += ln
                assert buf[j] == 0x2C
                idx, j = _nat(buf, j + 1)
                assert buf[j] == 0x2C
                i = j + 1
                kind, nchild = K_PROJ, 1
            elif c == 0x5F:  # '_' hole (skeleton rendering only)
                i += 1
                nid = self.mk(K_HOLE)
            elif c == 0x3F:  # '?' anti-unification variable
                v, i = _nat(buf, i + 1)
                nid = self.mk(K_VAR, v)
            else:
                raise ValueError(f"bad byte {buf[i:i + 12]!r} at {i}")

            if nchild:
                stack.append([-1, nchild, 0, kind, sym])
                pend.append([])
                continue

            while True:
                if not stack:
                    return nid, i
                fr = stack[-1]
                pend[-1].append(nid)
                fr[2] += 1
                if fr[2] < fr[1]:
                    assert buf[i] == 0x2C, "comma"
                    i += 1
                    break
                assert buf[i] == 0x29, "close"
                i += 1
                kids = pend.pop()
                stack.pop()
                nid = self.mk(fr[3], fr[4], *kids)

    # -- accessors ----------------------------------------------------------
    def spine(self, t: int) -> tuple[int, list[int]]:
        args: list[int] = []
        cur = t
        while self.kind[cur] == K_APP:
            args.append(self.y[cur])
            cur = self.x[cur]
        args.reverse()
        return cur, args

    def peel(self, t: int) -> tuple[list[tuple[int, int, bool]], int]:
        """Strip the `Pi` prefix. Returns `[(binder_info, domain, dependent)]` and the body."""
        bs: list[tuple[int, int, bool]] = []
        cur = t
        while self.kind[cur] == K_PI:
            bs.append((self.sym[cur], self.x[cur], self.lo[self.y[cur]] >= 1))
            cur = self.y[cur]
        return bs, cur

    def lower1(self, t: int, depth: int = 0, memo: dict | None = None) -> int:
        """Decrement every loose de Bruijn index by one. `b_depth` must not occur.

        Needed to compare a non-dependent `Pi`'s antecedent with its consequent: the
        consequent is the *body*, so it lives one binder deeper and every index in it is
        shifted. Comparing the two unshifted is the trap CLAUDE.md sec. 5 records twice —
        indices that look equal denote different binders.
        """
        if memo is None:
            memo = {}
        if self.lo[t] <= depth:
            return t
        key = (t, depth)
        v = memo.get(key)
        if v is not None:
            return v
        k = self.kind[t]
        if k == K_BVAR:
            assert self.sym[t] != depth, "lower1 on a dependent binder"
            r = self.mk(K_BVAR, self.sym[t] - 1)
        elif k == K_APP:
            r = self.mk(K_APP, -1, self.lower1(self.x[t], depth, memo),
                        self.lower1(self.y[t], depth, memo))
        elif k in (K_LAM, K_PI):
            r = self.mk(k, self.sym[t], self.lower1(self.x[t], depth, memo),
                        self.lower1(self.y[t], depth + 1, memo))
        elif k == K_LET:
            r = self.mk(K_LET, -1, self.lower1(self.x[t], depth, memo),
                        self.lower1(self.y[t], depth, memo),
                        self.lower1(self.z[t], depth + 1, memo))
        elif k == K_PROJ:
            r = self.mk(K_PROJ, self.sym[t], self.lower1(self.x[t], depth, memo))
        else:
            r = t
        memo[key] = r
        return r

    def loose(self, t: int, out: set[int], depth: int = 0) -> None:
        """Collect loose de Bruijn indices of `t`, expressed relative to `t`'s own root."""
        k = self.kind[t]
        if k == K_BVAR:
            if self.sym[t] >= depth:
                out.add(self.sym[t] - depth)
            return
        if self.lo[t] == 0:
            return
        if k == K_APP:
            self.loose(self.x[t], out, depth)
            self.loose(self.y[t], out, depth)
        elif k in (K_LAM, K_PI):
            self.loose(self.x[t], out, depth)
            self.loose(self.y[t], out, depth + 1)
        elif k == K_LET:
            self.loose(self.x[t], out, depth)
            self.loose(self.y[t], out, depth)
            self.loose(self.z[t], out, depth + 1)
        elif k == K_PROJ:
            self.loose(self.x[t], out, depth)

    def render(self, t: int, budget: int = 220) -> str:
        out: list[str] = []
        self._render(t, out, [budget])
        return "".join(out)

    def _render(self, t: int, out: list[str], budget: list[int]) -> None:
        if budget[0] <= 0:
            return
        k = self.kind[t]
        budget[0] -= 1
        if k == K_BVAR:
            out.append(f"b{self.sym[t]}")
        elif k == K_SORT:
            out.append(f"s({self.name(self.sym[t])})")
        elif k == K_CONST:
            out.append(f"c({self.name(self.sym[t])})")
        elif k == K_NAT:
            out.append(f"n{self.name(self.sym[t])}")
        elif k == K_STR:
            out.append("t..")
        elif k == K_HOLE:
            out.append("_")
        elif k == K_VAR:
            out.append(f"?{self.sym[t]}")
        elif k == K_APP:
            out.append("a(")
            self._render(self.x[t], out, budget)
            out.append(",")
            self._render(self.y[t], out, budget)
            out.append(")")
        elif k in (K_LAM, K_PI):
            out.append(("l" if k == K_LAM else "p") + chr(self.sym[t]) + "(")
            self._render(self.x[t], out, budget)
            out.append(",")
            self._render(self.y[t], out, budget)
            out.append(")")
        elif k == K_PROJ:
            out.append("j(")
            self._render(self.x[t], out, budget)
            out.append(")")
        else:
            out.append("e(..)")


def _nat(buf: bytes, i: int) -> tuple[int, int]:
    j = i
    while j < len(buf) and 0x30 <= buf[j] <= 0x39:
        j += 1
    return int(buf[i:j]), j


def _len(buf: bytes, i: int) -> tuple[int, int]:
    v, j = _nat(buf, i)
    assert buf[j] == 0x3A, "length prefix"
    return v, j + 1


def _skip_level(buf: bytes, i: int) -> int:
    c = buf[i]
    if c == 0x30 or c == 0x2A:          # '0' | '*'
        return i + 1
    if c == 0x75:                        # 'u' nat
        _, j = _nat(buf, i + 1)
        return j
    if c == 0x2B:                        # '+(' level ')'
        j = _skip_level(buf, i + 2)
        assert buf[j] == 0x29
        return j + 1
    if c == 0x4D or c == 0x49:           # 'M(' / 'I('
        j = _skip_level(buf, i + 2)
        assert buf[j] == 0x2C
        j = _skip_level(buf, j + 1)
        assert buf[j] == 0x29
        return j + 1
    raise ValueError(f"bad level {buf[i:i + 10]!r}")


# ---------------------------------------------------------------------------
# Structural predicates
# ---------------------------------------------------------------------------
def antiunify(ar: Arena, l: int, r: int) -> tuple[int, list[tuple[int, int]]]:
    """Least general generalization of two terms of the *same* statement.

    Returns `(concrete nodes shared, [(left subterm, right subterm)] per variable)`.

    The memo is keyed by binder depth as well as by the pair. Without the depth, two
    positions whose de Bruijn indices resolve to different binders collapse onto one
    variable — the defect CLAUDE.md sec. 5 records against the Rust anti-unifier, which is
    invisible to idempotence, commutativity and subsumption because all three are
    depth-blind themselves.
    """
    memo: dict[tuple[int, int, int], int] = {}
    binds: list[tuple[int, int]] = []
    common = 0

    def go(a: int, b: int, d: int) -> None:
        nonlocal common
        key = (a, b, d)
        if key in memo:
            return
        memo[key] = 1
        if a == b:
            common += ar.conc[a]
            return
        ka, kb = ar.kind[a], ar.kind[b]
        if ka != kb:
            binds.append((a, b))
            return
        if ka == K_APP:
            common += 1
            go(ar.x[a], ar.x[b], d)
            go(ar.y[a], ar.y[b], d)
        elif ka in (K_LAM, K_PI) and ar.sym[a] == ar.sym[b]:
            common += 1
            go(ar.x[a], ar.x[b], d)
            go(ar.y[a], ar.y[b], d + 1)
        elif ka == K_PROJ and ar.sym[a] == ar.sym[b]:
            common += 1
            go(ar.x[a], ar.x[b], d)
        else:
            binds.append((a, b))

    go(l, r, 0)
    return common, binds


def head_name(ar: Arena, t: int) -> str:
    h, _ = ar.spine(t)
    if ar.kind[h] == K_CONST:
        return ar.name(ar.sym[h])
    if ar.kind[h] == K_BVAR:
        return "?bvar"
    if ar.kind[h] in (K_LAM, K_PI):
        return "?binder"
    return "?"


def context_of(ar: Arena, big: int, small: int, max_nodes: int = 200_000):
    """`big == C[small]` for a one-hole context `C` that crosses no binder.

    Returns `(exact, shape)` **strings**, or `None`. Strings rather than node ids because
    the arena is reset between statements: a family label has to outlive the terms it came
    from. `exact` names the head constant of each sibling — the *operator that was applied*,
    which is precisely the transformation an invariance statement claims to be invariant
    under. `shape` keeps only the argument positions, so `<Λv,Λw> = <v,w>` (Lorentz) and
    `<Uv,Uw> = <v,w>` (unitary) share a shape and differ in exact.

    Crossing a binder is refused rather than allowed: a de Bruijn index means something
    different one binder down, so "the same subterm" under a binder is a different term —
    which is the erasure defect CLAUDE.md sec. 5 records, rediscovered at another level.
    """
    if big == small:
        return None
    stack = [(big, ())]
    seen = set()
    visited = 0
    while stack:
        node, path = stack.pop()
        visited += 1
        if visited > max_nodes:
            return None
        if node == small:
            ex, sh = [], []
            for kind, sym, sibling, side in path:   # outermost first
                if kind == K_APP:
                    ex.append(f"a{side}:{head_name(ar, sibling)}")
                    sh.append(f"a{side}")
                else:
                    ex.append(f"j:{ar.name(sym)}")
                    sh.append("j")
            return "|".join(ex), "|".join(sh)
        if node in seen:
            continue
        seen.add(node)
        k = ar.kind[node]
        if k == K_APP:
            stack.append((ar.x[node], path + ((K_APP, -1, ar.y[node], 0),)))
            stack.append((ar.y[node], path + ((K_APP, -1, ar.x[node], 1),)))
        elif k == K_PROJ:
            stack.append((ar.x[node], path + ((K_PROJ, ar.sym[node], -1, 0),)))
        # K_LAM / K_PI / K_LET bodies deliberately not entered.
    return None


class Hit:
    __slots__ = ("motif", "strict", "nvars", "ctx_exact", "ctx_shape", "direction",
                 "rel_head", "rel_arity", "whole_side")

    def __init__(self, motif, strict, nvars, ctx_exact, ctx_shape, direction,
                 rel_head, rel_arity):
        self.motif = motif
        self.whole_side = False
        self.strict = strict
        self.nvars = nvars
        self.ctx_exact = ctx_exact
        self.ctx_shape = ctx_shape
        self.direction = direction
        self.rel_head = rel_head
        self.rel_arity = rel_arity


def inv_test(ar: Arena, l: int, r: int, stats: collections.Counter) -> Hit | None:
    """Is `(l, r)` invariance-shaped: one side is the other with a context wrapped in?"""
    common, binds = antiunify(ar, l, r)
    if not binds:
        stats["identical_sides"] += 1
        return None
    if len(binds) > 16:
        stats["too_many_diffs"] += 1
        return None
    # `common == 0` is not a rejection. It is the case where the *whole* of one side is the
    # other wrapped — `- -a = a`, `n + 0 = n`, `|-a|` against `|a|` when nothing outside the
    # wrapping is shared. Excluding it was a false negative on the most elementary
    # invariance statements there are, so it is admitted and tagged instead.
    whole_side = common == 0
    dirs = set()
    exacts, shapes = set(), set()
    proper = 0
    for a, b in binds:
        ca = context_of(ar, b, a)      # b == C[a]  ->  right side is bigger
        cb = context_of(ar, a, b)      # a == C[b]
        if ca is not None and cb is None:
            dirs.add("L<R")
            exacts.add(ca[0])
            shapes.add(ca[1])
            proper += 1
        elif cb is not None and ca is None:
            dirs.add("R<L")
            exacts.add(cb[0])
            shapes.add(cb[1])
            proper += 1
        else:
            stats["diff_not_a_wrapping"] += 1
            return None
    if len(dirs) != 1 or proper == 0:
        stats["mixed_direction"] += 1
        return None
    h = Hit("INV", len(exacts) == 1, len(binds),
            sorted(exacts)[0] if len(exacts) == 1 else "+".join(sorted(exacts)),
            sorted(shapes)[0] if len(shapes) == 1 else "+".join(sorted(shapes)),
            dirs.pop(), -1, -1)
    h.whole_side = whole_side
    return h


def swap_test(ar: Arena, l: int, r: int) -> Hit | None:
    """Are the two sides a non-identity permutation of the same parts?"""
    common, binds = antiunify(ar, l, r)
    if not binds or common == 0 or len(binds) < 2 or len(binds) > 8:
        return None
    left = sorted(a for a, _ in binds)
    right = sorted(b for _, b in binds)
    if left != right:
        return None
    if all(a == b for a, b in binds):
        return None
    return Hit("SWAP", True, len(binds), None, None, "swap", -1, -1)


def classify(ar: Arena, root: int, stats: collections.Counter) -> dict:
    """Every motif verdict for one statement. Name-free throughout."""
    out: dict = {"parsed": True}
    binders, concl = ar.peel(root)
    out["nbinders"] = len(binders)
    head, args = ar.spine(concl)
    out["rel_head"] = ar.name(ar.sym[head]) if ar.kind[head] == K_CONST else None
    out["rel_arity"] = len(args)
    if len(args) >= 2 and ar.kind[head] == K_CONST:
        out["relational"] = True
        l, r = args[-2], args[-1]
        h = inv_test(ar, l, r, stats)
        if h is not None:
            h.rel_head = out["rel_head"]
            h.rel_arity = len(args)
            out["INV"] = h
        s = swap_test(ar, l, r)
        if s is not None:
            s.rel_head = out["rel_head"]
            s.rel_arity = len(args)
            out["SWAP"] = s
        # CONS: does one side depend on an explicitly bound variable the other drops?
        fl: set[int] = set()
        fr: set[int] = set()
        ar.loose(l, fl)
        ar.loose(r, fr)
        # index k inside the conclusion refers to binder len(binders)-1-k
        expl = {len(binders) - 1 - i for i, (bi, _d, _dep) in enumerate(binders) if bi == 0x64}
        droppedL = {k for k in fl - fr if k in expl}
        droppedR = {k for k in fr - fl if k in expl}
        if (droppedL or droppedR) and ar.conc[l] > 1 and ar.conc[r] >= 1:
            closed = (not fr) if droppedL else (not fl)
            out["CONS"] = Hit("CONS", closed, len(droppedL or droppedR), None, None,
                              "L>R" if droppedL else "R>L", out["rel_head"], len(args))
    # INV-IMP: a non-dependent `Pi`'s antecedent against its consequent — `P x -> P (T x)`.
    # The consequent is the Pi's *body*, one binder deeper, so it is lowered before the
    # comparison. Without that every index disagrees and the test can never fire.
    cur = root
    while ar.kind[cur] == K_PI:
        body = ar.y[cur]
        if ar.lo[body] == 0 or not _mentions_zero(ar, body):
            ante = ar.x[cur]
            if ar.conc[ante] > 2:
                try:
                    cons = ar.lower1(body)
                except AssertionError:
                    cons = None
                if cons is not None:
                    h = inv_test(ar, ante, cons, stats)
                    if h is not None:
                        h.motif = "INV_IMP"
                        h.rel_head = out["rel_head"]
                        out.setdefault("INV_IMP", h)
                    s2 = swap_test(ar, ante, cons)
                    if s2 is not None:
                        s2.motif = "SWAP_IMP"
                        s2.rel_head = out["rel_head"]
                        out.setdefault("SWAP_IMP", s2)
        cur = body
    return out


def _mentions_zero(ar: Arena, t: int, depth: int = 0) -> bool:
    if ar.lo[t] <= depth:
        return False
    k = ar.kind[t]
    if k == K_BVAR:
        return ar.sym[t] == depth
    if k == K_APP:
        return _mentions_zero(ar, ar.x[t], depth) or _mentions_zero(ar, ar.y[t], depth)
    if k in (K_LAM, K_PI):
        return _mentions_zero(ar, ar.x[t], depth) or _mentions_zero(ar, ar.y[t], depth + 1)
    if k == K_LET:
        return (_mentions_zero(ar, ar.x[t], depth) or _mentions_zero(ar, ar.y[t], depth)
                or _mentions_zero(ar, ar.z[t], depth + 1))
    if k == K_PROJ:
        return _mentions_zero(ar, ar.x[t], depth)
    return False


# ---------------------------------------------------------------------------
# Corpus loading (streaming; the Rust binding is used for erasure and the graph)
# ---------------------------------------------------------------------------
class Rows:
    __slots__ = ("name", "kind", "module", "stmt", "us", "up")

    def __init__(self) -> None:
        self.name: list[str] = []
        self.kind: list[str] = []
        self.module: list[str] = []
        self.stmt: list[bytes | None] = []
        self.us: list[list[str]] = []
        self.up: list[list[str]] = []


def subfield(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "?")


def load_rows(path: pathlib.Path, keep_stmt_prefixes: tuple[str, ...] | None,
              max_stmt: int, want_edges: bool) -> tuple[Rows, dict]:
    r = Rows()
    diag = collections.Counter()
    # A byte-level prefilter on the `module` field, purely to avoid `json.loads` on rows
    # that are only in the file to close it. It selects a *scope* (which library is being
    # analysed), never a result: nothing downstream looks at a declaration's name.
    needles = tuple(b'"module":"' + p.encode() for p in (keep_stmt_prefixes or ()))
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            diag["lines"] += 1
            if needles and not any(nd in line for nd in needles):
                diag["out_of_scope"] += 1
                continue
            d = json.loads(line)
            nm = d["name"]
            mod = d.get("module") or "?"
            st = d.get("stmt")
            keep = keep_stmt_prefixes is None or mod.startswith(keep_stmt_prefixes)
            diag["rows"] += 1
            if st is None:
                diag["no_stmt"] += 1
                stb = None
            elif not keep:
                stb = None
            elif len(st) > max_stmt:
                diag["oversize"] += 1
                stb = None
            else:
                stb = st.encode()
            r.name.append(nm)
            r.kind.append(d.get("kind") or "?")
            r.module.append(mod)
            r.stmt.append(stb)
            if want_edges:
                r.us.append(d.get("uses_statement") or [])
                r.up.append(d.get("uses_proof") or [])
            else:
                r.us.append([])
                r.up.append([])
    return r, diag


# ---------------------------------------------------------------------------
# Phase 1: prevalence + controls
# ---------------------------------------------------------------------------
def phase_motifs(rows: Rows, args) -> dict:
    ar = Arena()
    stats = collections.Counter()
    # INV_POS is INV with `common > 0`: some structure is shared *outside* the wrapping.
    # It is tracked separately because the scramble control separates the two branches and
    # only this one survives it — see the findings section of research/physlib-symmetry.md.
    hits: dict[str, dict[int, Hit]] = {
        k: {} for k in ("INV", "INV_POS", "SWAP", "CONS", "CONS_CLOSED", "INV_IMP",
                        "SWAP_IMP")}
    parsed_idx: list[int] = []
    rel_head_of: dict[int, str | None] = {}
    relational: list[int] = []       # rows whose conclusion is a >= 2-ary application
    t0 = time.time()
    parse_fail = collections.Counter()
    for i, st in enumerate(rows.stmt):
        if st is None or rows.kind[i] != "theorem":
            continue
        ar.reset()
        try:
            root = ar.parse(st)
        except Exception as e:  # noqa: BLE001
            parse_fail[type(e).__name__ + ":" + str(e)[:40]] += 1
            continue
        parsed_idx.append(i)
        try:
            v = classify(ar, root, stats)
        except RecursionError:
            parse_fail["RecursionError"] += 1
            continue
        rel_head_of[i] = v["rel_head"]
        for m in hits:
            if m in v:
                hits[m][i] = v[m]
        if "INV" in v and not v["INV"].whole_side:
            hits["INV_POS"][i] = v["INV"]
        if "CONS" in v and v["CONS"].strict:
            hits["CONS_CLOSED"][i] = v["CONS"]
        if v.get("relational"):
            relational.append(i)
    dt = time.time() - t0
    concl_sides = relational

    n = len(parsed_idx)
    out = {
        "theorems_parsed": n,
        "parse_failures": dict(parse_fail),
        "seconds": round(dt, 1),
        "arena_nodes": ar.nodes_built,
        "relational": len(concl_sides),
        "reject_reasons": dict(stats),
        "counts": {m: len(h) for m, h in hits.items()},
        "rates": {m: (len(h) / n if n else 0.0) for m, h in hits.items()},
        "inv_strict": sum(1 for h in hits["INV"].values() if h.strict),
        "inv_whole_side": sum(1 for h in hits["INV"].values() if h.whole_side),
        "inv_positional": sum(1 for h in hits["INV"].values() if not h.whole_side),
        "inv_imp_strict": sum(1 for h in hits["INV_IMP"].values() if h.strict),
        "cons_closed": sum(1 for h in hits["CONS"].values() if h.strict),
        "inv_ctx_shapes": [[str(k), v] for k, v in collections.Counter(
            str(h.ctx_shape) for h in hits["INV"].values()).most_common(10)],
        "inv_rel_heads": [[k, v] for k, v in collections.Counter(
            h.rel_head for h in hits["INV"].values()).most_common(12)],
        "cons_rel_heads": [[k, v] for k, v in collections.Counter(
            h.rel_head for h in hits["CONS"].values()).most_common(12)],
        "all_rel_heads": [[k, v] for k, v in collections.Counter(
            rel_head_of[i] for i in parsed_idx).most_common(12)],
    }

    # ---- negative control: scramble the pairing -------------------------
    # Same predicate, same terms, but `L` from one theorem and `R` from another. If the hit
    # rate survives that, the predicate is a property of *terms* and says nothing about
    # statements — which is the failure mode sec. 16 of the findings doc records.
    rng = random.Random(args.seed)
    m = len(concl_sides)
    scr = collections.Counter()
    trials = min(args.scramble_trials, m * 4)

    def sides(idx: int, ar2: Arena):
        ar2.reset()
        root = ar2.parse(rows.stmt[idx])
        _b, cc = ar2.peel(root)
        h, a = ar2.spine(cc)
        return a[-2], a[-1]

    if m >= 2:
        ar2 = Arena()
        for _ in range(trials):
            i1, i2 = rng.randrange(m), rng.randrange(m)
            while i2 == i1:
                i2 = rng.randrange(m)
            try:
                # Both sides must live in ONE arena for structural equality to mean
                # anything, so the two statements are parsed together and the pairing is
                # crossed afterwards: L from the first, R from the second.
                ar2.reset()
                r1 = ar2.parse(rows.stmt[concl_sides[i1]])
                r2 = ar2.parse(rows.stmt[concl_sides[i2]])
                _b, c1 = ar2.peel(r1)
                _b, c2 = ar2.peel(r2)
                _h1, a1 = ar2.spine(c1)
                _h2, a2 = ar2.spine(c2)
                h = inv_test(ar2, a1[-2], a2[-1], collections.Counter())
                s = swap_test(ar2, a1[-2], a2[-1])
            except Exception:  # noqa: BLE001
                scr["error"] += 1
                continue
            scr["trials"] += 1
            if h is not None:
                scr["inv"] += 1
                scr["inv_strict"] += h.strict
                scr["inv_whole_side" if h.whole_side else "inv_positional"] += 1
            if s is not None:
                scr["swap"] += 1
    tr = scr["trials"] or 1
    npos = len(hits["INV_POS"])
    nwhole = len(hits["INV"]) - npos
    out["scramble_control"] = {
        "trials": scr["trials"], "errors": scr["error"],
        "inv_hits": scr["inv"], "inv_rate": round(scr["inv"] / tr, 5),
        "inv_strict": scr["inv_strict"],
        "inv_positional": scr["inv_positional"],
        "inv_positional_rate": round(scr["inv_positional"] / tr, 5),
        "inv_whole_side": scr["inv_whole_side"],
        "inv_whole_side_rate": round(scr["inv_whole_side"] / tr, 5),
        "swap_hits": scr["swap"], "swap_rate": round(scr["swap"] / tr, 5),
    }
    # genuine rates over the same denominator (relational conclusions only)
    out["inv_rate_relational"] = round(len(hits["INV"]) / m, 5) if m else 0.0
    out["inv_positional_rate_relational"] = round(npos / m, 5) if m else 0.0
    out["inv_whole_side_rate_relational"] = round(nwhole / m, 5) if m else 0.0
    out["swap_rate_relational"] = round(len(hits["SWAP"]) / m, 5) if m else 0.0
    return {"summary": out, "hits": hits, "parsed": parsed_idx, "relational": relational,
            "rel_head": rel_head_of}


# ---------------------------------------------------------------------------
# Phase 2: families and the size-matched null
# ---------------------------------------------------------------------------
def expected_spread(sizes: list[int], n: int) -> float:
    """Expected distinct subfields in a uniformly random family of `n` declarations."""
    N = sum(sizes)
    if n >= N:
        return float(len([s for s in sizes if s]))
    tot = 0.0
    for s in sizes:
        if s == 0:
            continue
        # P(subfield s absent) = C(N-s, n) / C(N, n)
        if N - s < n:
            tot += 1.0
            continue
        lp = (math.lgamma(N - s + 1) - math.lgamma(N - s - n + 1)
              - math.lgamma(N + 1) + math.lgamma(N - n + 1))
        tot += 1.0 - math.exp(lp)
    return tot


# ---------------------------------------------------------------------------
# Phase 3: Noether — citation edges between motif classes, against two nulls
# ---------------------------------------------------------------------------
def build_adj(rows: Rows, universe: list[int], lens: str) -> dict[int, set[int]]:
    idx = {rows.name[i]: i for i in universe}
    adj: dict[int, set[int]] = {}
    for i in universe:
        names = []
        if lens in ("statement", "both"):
            names += rows.us[i]
        if lens in ("proof", "both"):
            names += rows.up[i]
        s = {idx[nm] for nm in names if nm in idx}
        s.discard(i)
        adj[i] = s
    return adj


def reach2(adj: dict[int, set[int]]) -> dict[int, set[int]]:
    """Everything within two citation steps. Precomputed once: reachability does not depend
    on the motif labels, so every shuffle re-uses it and the null costs set intersections."""
    out: dict[int, set[int]] = {}
    for i, one in adj.items():
        s = set(one)
        for j in one:
            s |= adj.get(j, ())
        s.discard(i)
        out[i] = s
    return out


def noether(rows: Rows, universe: list[int], setA: set[int], setB: set[int],
            lens: str, shuffles: int, seed: int, do_two_hop: bool = True) -> dict:
    """Do declarations matching motif A cite declarations matching motif B, beyond chance?

    Two nulls, because one is not enough. A **uniform** label shuffle preserves only the
    class sizes, so it cannot distinguish Noether from "invariance lemmas are popular". A
    **degree-matched** shuffle redraws A from the same out-degree distribution and B from
    the same in-degree distribution, which is the null that kills that explanation.
    """
    uni = list(universe)
    adj = build_adj(rows, uni, lens)
    two = reach2(adj) if do_two_hop else None

    def count(g, A, B):
        return sum(len(g[i] & B) for i in A if i in g)

    outdeg = {i: len(adj[i]) for i in uni}
    indeg = collections.Counter()
    for i in uni:
        for j in adj[i]:
            indeg[j] += 1

    def bucket(v: int) -> int:
        return 0 if v == 0 else min(12, int(math.log2(v)) + 1)

    rng = random.Random(seed)

    def matched_draw(target: set[int], key) -> set[int]:
        by: dict[int, list[int]] = collections.defaultdict(list)
        for i in uni:
            by[bucket(key[i])].append(i)
        want = collections.Counter(bucket(key[i]) for i in target)
        out: set[int] = set()
        for b, k in want.items():
            pool = by[b]
            # The target is a subset of the universe, so its own members are in the pool and
            # `k <= len(pool)` always; a short draw would bias the null downward and is
            # reported rather than silently taken.
            out |= set(rng.sample(pool, min(k, len(pool))))
        return out

    graphs = {"1hop": adj} | ({"2hop": two} if two else {})
    result: dict = {"lens": lens, "universe": len(uni), "|A|": len(setA), "|B|": len(setB),
                    "overlap": len(setA & setB)}
    for gname, g in graphs.items():
        obs_ab = count(g, setA, setB)
        obs_ba = count(g, setB, setA)
        null_u, null_m = [], []
        for _ in range(shuffles):
            null_u.append(count(g, set(rng.sample(uni, len(setA))),
                                set(rng.sample(uni, len(setB)))))
            null_m.append(count(g, matched_draw(setA, outdeg),
                                matched_draw(setB, indeg)))

        def summarise(obs, null):
            mu = statistics.fmean(null) if null else 0.0
            sd = statistics.pstdev(null) if len(null) > 1 else 0.0
            ge = sum(1 for v in null if v >= obs)
            return {"observed": obs, "null_mean": round(mu, 2), "null_sd": round(sd, 2),
                    "z": round((obs - mu) / sd, 2) if sd else None,
                    "null_max": max(null) if null else None,
                    "ratio": round(obs / mu, 2) if mu else None,
                    "p_ge": round((ge + 1) / (len(null) + 1), 4) if null else None}

        result[gname] = {
            "A_to_B_vs_uniform_null": summarise(obs_ab, null_u),
            "A_to_B_vs_degree_matched_null": summarise(obs_ab, null_m),
            "B_to_A_observed": obs_ba,
        }
    return result


# ---------------------------------------------------------------------------
# The positive control. Fourteen lemmas whose content is known by hand, three of which the
# predicate must *reject*. Names appear here to state the control; they select nothing —
# the population every measurement runs over is "every theorem in the slice".
#
# It is not decoration. INV-IMP shipped unable to fire at all, because the consequent of a
# non-dependent `Pi` is one binder deeper than its antecedent; no property test caught it
# and this did.
SELF_TEST = {
    "abs_neg": "INV", "abs_abs": "INV", "neg_neg": "INV", "inv_inv": "INV",
    "Int.neg_neg": "INV", "Nat.add_zero": "INV",
    "Nat.succ_le_succ": "INV_IMP",
    "add_comm": "SWAP", "Nat.add_comm": "SWAP", "Nat.mul_comm": "SWAP",
    "Nat.gcd_comm": "SWAP", "abs_sub_comm": "SWAP",
    "Nat.sub_self": "CONS",
    "le_refl": None, "mul_le_mul_left": None, "Nat.gcd_rec": None,
}


def self_test(path: pathlib.Path) -> int:
    want = dict(SELF_TEST)
    got: dict[str, list[str]] = {}
    ar = Arena()
    stats: collections.Counter = collections.Counter()
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            d = json.loads(line)
            if d["name"] not in want or not d.get("stmt"):
                continue
            ar.reset()
            v = classify(ar, ar.parse(d["stmt"].encode()), stats)
            got[d["name"]] = [k for k in ("INV", "INV_IMP", "SWAP", "CONS") if k in v]
    bad = 0
    for name, expect in sorted(want.items()):
        if name not in got:
            print(f"  SKIP  {name:22s} not in slice")
            continue
        ms = got[name]
        ok = (expect in ms) if expect else (not ms)
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:22s} expect={expect or 'no motif':9s} got={ms}")
    print(f"\n{len(got)} checked, {bad} failures")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="run the hand-known positive control against --slice and exit")
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--authored", default="",
                    help="comma-separated module prefixes to analyse; empty = all")
    ap.add_argument("--max-stmt", type=int, default=120_000)
    ap.add_argument("--scramble-trials", type=int, default=4000)
    ap.add_argument("--shuffles", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--skeletons", type=int, default=0,
                    help="if >0, load the Rust corpus and take carriers skeletons for "
                         "up to this many INV hits (needs a closed slice)")
    ap.add_argument("--motifs-top", type=int, default=400)
    ap.add_argument("--similar-probes", type=int, default=120)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-phys-symmetry.json"))
    args = ap.parse_args()

    if args.self_test:
        return self_test(args.slice)

    prefixes = tuple(p for p in args.authored.split(",") if p) or None
    print(f"loading {args.slice} …", flush=True)
    t0 = time.time()
    rows, diag = load_rows(args.slice, prefixes, args.max_stmt, want_edges=True)
    print(f"  {diag['rows']:,} rows in {time.time() - t0:.1f}s; "
          f"{diag['no_stmt']:,} without a statement, {diag['oversize']:,} over "
          f"{args.max_stmt:,} bytes (not parsed — counted, not hidden)", flush=True)

    res = phase_motifs(rows, args)
    s = res["summary"]
    hits = res["hits"]
    print(json.dumps(s, indent=1, default=str), flush=True)

    report: dict = {"slice": str(args.slice), "authored": args.authored,
                    "max_stmt": args.max_stmt, "seed": args.seed,
                    "load": dict(diag), "motifs": s}

    # ---- families and spread -------------------------------------------
    inv = hits["INV"]
    pop_sub = collections.Counter(subfield(rows.module[i]) for i in res["parsed"])
    sizes = list(pop_sub.values())
    report["population_subfields"] = dict(pop_sub.most_common(20))

    def families(assign, min_family=3, top=40):
        fam = collections.defaultdict(list)
        for i, key in assign:
            fam[key].append(i)
        out = []
        for key, members in sorted(fam.items(), key=lambda kv: -len(kv[1])):
            if len(members) < min_family:
                continue
            subs = collections.Counter(subfield(rows.module[i]) for i in members)
            exp = expected_spread(sizes, len(members))
            out.append({"key": str(key)[:160], "members": len(members),
                        "subfields": len(subs), "expected_subfields": round(exp, 2),
                        "excess": round(len(subs) - exp, 2),
                        "spread": dict(subs.most_common(8)),
                        "sample": [rows.name[i] for i in members[:8]]})
        return out

    # The transformation itself: the head constant of every sibling on the path from the
    # relation's side down to the hole. `<Λv,Λw> = <v,w>` keys on `Λ`.
    by_transform = families([(i, (h.ctx_exact,)) for i, h in inv.items()])
    by_shape = families([(i, (h.rel_head, h.ctx_shape, h.nvars, h.direction))
                         for i, h in inv.items()])
    report["inv_families_by_transformation"] = by_transform[:40]
    report["inv_families_by_shape"] = by_shape[:25]
    for label, fams in (("transformation", by_transform), ("shape", by_shape)):
        report[f"inv_family_excess_{label}"] = {
            "families": len(fams),
            "mean_excess": round(statistics.fmean([f["excess"] for f in fams]), 3) if fams else None,
            "max_excess": max((f["excess"] for f in fams), default=None),
            "min_excess": min((f["excess"] for f in fams), default=None),
            "positive_excess": sum(1 for f in fams if f["excess"] > 0),
        }
    # The corpus's own baseline for the same statistic: families of theorems that are NOT
    # invariance-shaped, grouped by the same relation head. Without this the excess numbers
    # have a null but no peer group, and sec. 17 of the findings doc is about exactly that
    # gap — a filter that looks selective until something equally arbitrary is measured.
    noninv = [i for i in res["relational"] if i not in inv]
    report["baseline_families_by_relhead"] = families(
        [(i, ("relhead", res["rel_head"].get(i))) for i in noninv], min_family=3)[:12]

    # ---- Noether --------------------------------------------------------
    universe = res["parsed"]
    invset = set(inv)
    consset = set(hits["CONS"])
    swapset = set(hits["SWAP"])
    impset = set(hits["INV_IMP"])
    posset = set(hits["INV_POS"])
    report["noether"] = {}
    for lens in ("statement", "proof", "both"):
        report["noether"][lens] = noether(rows, universe, consset, invset, lens,
                                          args.shuffles, args.seed)
        print(f"noether[{lens}]: {json.dumps(report['noether'][lens], default=str)}", flush=True)
    # CONS and INV overlap — a statement can drop a parameter *and* be a wrapping. Same-motif
    # citation is strongly elevated on its own (see the placebos), so an overlapping pair can
    # inherit that elevation without any cross-motif effect. These variants make the two sets
    # disjoint, which is the only version of the test that can mean what it says.
    report["noether_disjoint"] = {}
    ccset = set(hits["CONS_CLOSED"])
    for label, A, B in (("CONS\\INV -> INV\\CONS", consset - invset, invset - consset),
                        ("CONS\\INV_POS -> INV_POS\\CONS", consset - posset, posset - consset),
                        # CONS_CLOSED is the tight conservation reading — `... = c` for a
                        # closed `c`, i.e. the value is literally constant in the parameter.
                        ("CONS_CLOSED\\INV -> INV\\CONS_CLOSED", ccset - invset, invset - ccset),
                        ("CONS_CLOSED\\INV_POS -> INV_POS\\CONS_CLOSED",
                         ccset - posset, posset - ccset)):
        if not A or not B:
            continue
        report["noether_disjoint"][label] = noether(rows, universe, A, B, "both",
                                                    args.shuffles, args.seed)
        print(f"disjoint[{label}]: "
              f"{json.dumps(report['noether_disjoint'][label]['1hop'], default=str)}",
              flush=True)
    # Placebo pairs. If every motif pair is elevated, the elevation is a property of the
    # citation graph and not of Noether — which no single pair's null can reveal.
    report["noether_placebos"] = {}
    for label, A, B in (("CONS->SWAP", consset, swapset),
                        ("SWAP->INV", swapset, invset),
                        ("INV->INV", invset, invset),
                        ("CONS->CONS", consset, consset),
                        ("CONS->INV_IMP", consset, impset)):
        if not A or not B:
            continue
        report["noether_placebos"][label] = noether(
            rows, universe, A, B, "both", max(50, args.shuffles // 4), args.seed)
        print(f"placebo[{label}]: "
              f"{json.dumps(report['noether_placebos'][label]['1hop'], default=str)}",
              flush=True)

    # ---- neighbourhood shape -------------------------------------------
    name_to_row = {rows.name[i]: i for i in range(len(rows.name))}
    idx = name_to_row
    uni_set = set(universe)
    indeg = collections.Counter()
    for i in universe:
        for nm in rows.us[i] + rows.up[i]:
            j = idx.get(nm)
            if j is not None and j in uni_set:
                indeg[j] += 1
    size_of = {}
    for i in universe:
        st = rows.stmt[i]
        size_of[i] = len(st) if st else 0

    def size_bucket(i):
        v = size_of[i]
        return 0 if v <= 0 else min(14, int(math.log2(v)))

    pool = collections.defaultdict(list)
    for i in universe:
        pool[(subfield(rows.module[i]), size_bucket(i))].append(i)
    rng = random.Random(args.seed + 1)
    pairs: list[tuple[int, int]] = []
    for i in sorted(invset):
        cand = [j for j in pool[(subfield(rows.module[i]), size_bucket(i))]
                if j not in invset]
        if cand:
            pairs.append((i, rng.choice(cand)))
    matched = [j for _i, j in pairs]

    def paired_test(metric, trials=2000):
        """Swap labels within each matched pair. The design is paired by construction, so a
        paired permutation is the test that respects it; an unpaired one would credit the
        matching itself."""
        d = [metric(i) - metric(j) for i, j in pairs]
        obs = statistics.fmean(d) if d else 0.0
        r = random.Random(args.seed + 2)
        ge = 0
        for _ in range(trials):
            s = statistics.fmean([v if r.random() < 0.5 else -v for v in d])
            if abs(s) >= abs(obs):
                ge += 1
        return {"paired_mean_difference": round(obs, 4),
                "p_two_sided": round((ge + 1) / (trials + 1), 4), "pairs": len(d)}

    def shape_stats(group):
        od = [len(rows.us[i]) + len(rows.up[i]) for i in group]
        ind = [indeg[i] for i in group]
        sz = [size_of[i] for i in group]
        return {"n": len(group),
                "out_degree_mean": round(statistics.fmean(od), 2) if od else None,
                "out_degree_median": statistics.median(od) if od else None,
                "in_degree_mean": round(statistics.fmean(ind), 3) if ind else None,
                "in_degree_zero_frac": round(sum(1 for v in ind if v == 0) / len(ind), 3) if ind else None,
                "stmt_bytes_median": statistics.median(sz) if sz else None}

    report["neighbourhood"] = {
        "INV": shape_stats(sorted(invset)),
        "matched_control": shape_stats(matched),
        "all_theorems": shape_stats(universe),
        "INV_POS": shape_stats(sorted(posset)),
        "paired_in_degree": paired_test(lambda i: indeg[i]),
        "paired_out_degree": paired_test(lambda i: len(rows.us[i]) + len(rows.up[i])),
        "paired_stmt_bytes": paired_test(lambda i: size_of[i]),
    }
    print("neighbourhood:", json.dumps(report["neighbourhood"], indent=1, default=str),
          flush=True)

    # ---- optional: carriers skeletons for the INV hits -------------------
    if args.skeletons and fa is not None:
        print("loading the Rust corpus for erasure …", flush=True)
        c = fa.Corpus.load(str(args.slice))
        kn, unk, cov, worst = c.closure(top=6)
        report["closure"] = {"known": kn, "unknown": unk, "coverage": cov,
                             "worst": [list(w) for w in worst]}
        print(f"closure coverage {cov:.4f} ({kn:,} known / {unk:,} unknown)", flush=True)

        # ---- the corpus-wide sub-pattern inventory, asked the invariance question -----
        # `motifs` returns the shapes the corpus *contains*, with no query and no ranking.
        # Each pattern is an I3 term with holes, so the same predicate that classifies a
        # statement classifies a motif. This is the route the topic asks for: find the
        # recurring shapes first, then ask which of them are invariance-shaped — rather
        # than deciding what invariance looks like and going to find it.
        mot_report = []
        for src in ("shape", "subterm"):
            try:
                mots = c.motifs(source=src, min_family=3, min_size=6, top=args.motifs_top)
            except Exception as e:  # noqa: BLE001
                mot_report.append({"source": src, "error": f"{type(e).__name__}: {e}"})
                continue
            ar3 = Arena()
            tally = collections.Counter()
            examples = []
            for pat, members, size, idf in mots:
                tally["motifs"] += 1
                try:
                    ar3.reset()
                    t = ar3.parse(pat)
                except Exception:  # noqa: BLE001
                    tally["unparsed"] += 1
                    continue
                _b, cc = ar3.peel(t)
                h, a = ar3.spine(cc)
                if len(a) < 2:
                    tally["not_relational"] += 1
                    continue
                tally["relational"] += 1
                st2 = collections.Counter()
                hit = inv_test(ar3, a[-2], a[-1], st2)
                sw = swap_test(ar3, a[-2], a[-1])
                if hit is not None:
                    tally["INV"] += 1
                if sw is not None:
                    tally["SWAP"] += 1
                if hit is not None or sw is not None:
                    subs = collections.Counter(
                        subfield(rows.module[j]) for j in
                        (idx0 for idx0 in (name_to_row.get(n) for n in members)
                         if idx0 is not None))
                    examples.append({
                        "motif": "INV" if hit is not None else "SWAP",
                        "ctx": hit.ctx_exact if hit is not None else None,
                        "family": len(members), "pattern_size": size,
                        "subfields": len(subs), "spread": dict(subs.most_common(6)),
                        "members": [m.split(".")[-1][:28] for m in members[:8]],
                        "pattern": pat[:180]})
            mot_report.append({"source": src, "tally": dict(tally),
                               "invariance_shaped": examples[:20]})
            print(f"motifs[{src}]: {dict(tally)}", flush=True)
        report["motif_inventory"] = mot_report

        # ---- does `similar` retrieve the motif? ------------------------------
        # Ask the engine's own neighbour query from an INV declaration and count how many
        # of its neighbours are INV. The null is the base rate of INV among theorems: a
        # retrieval that returns the motif at its base rate is not retrieving the motif.
        rng2 = random.Random(args.seed + 7)
        inv_names = {rows.name[i] for i in invset}
        base = len(invset) / len(universe) if universe else 0.0
        probes = rng2.sample(sorted(invset), min(args.similar_probes, len(invset)))
        ctrl = rng2.sample([i for i in universe if i not in invset],
                           min(args.similar_probes, len(universe) - len(invset)))
        def retrieval(group):
            tot = hitn = qs = 0
            cross = 0
            for i in group:
                try:
                    nbs = c.similar(rows.name[i], top=25, level="carriers",
                                    min_retention=0.05, min_common=3,
                                    theorems_only=True, anchor="conclusion")
                except Exception:  # noqa: BLE001
                    continue
                qs += 1
                for nb in nbs:
                    if nb.name not in name_to_row:
                        continue
                    tot += 1
                    if nb.name in inv_names:
                        hitn += 1
                        if subfield(nb.module) != subfield(rows.module[i]):
                            cross += 1
            return {"queries": qs, "neighbours": tot, "inv_neighbours": hitn,
                    "rate": round(hitn / tot, 4) if tot else None,
                    "cross_subfield_inv_neighbours": cross}
        report["similar_retrieval"] = {
            "base_rate_INV_among_theorems": round(base, 4),
            "from_INV_queries": retrieval(probes),
            "from_non_INV_queries": retrieval(ctrl),
        }
        print("similar_retrieval:",
              json.dumps(report["similar_retrieval"], default=str), flush=True)

        skel = collections.defaultdict(list)
        for i in list(invset)[:args.skeletons]:
            try:
                skel[c.skeleton(rows.name[i], level="carriers")].append(i)
            except Exception:  # noqa: BLE001
                pass
        groups = sorted(skel.items(), key=lambda kv: -len(kv[1]))
        out = []
        for pat, members in groups[:30]:
            if len(members) < 2:
                continue
            subs = collections.Counter(subfield(rows.module[i]) for i in members)
            exp = expected_spread(sizes, len(members))
            out.append({"members": len(members), "subfields": len(subs),
                        "expected": round(exp, 2), "excess": round(len(subs) - exp, 2),
                        "spread": dict(subs), "pattern": pat[:200],
                        "sample": [rows.name[i] for i in members[:8]]})
        report["inv_carriers_families"] = out

    # ---- readable spot check (names used for reporting only) ------------
    report["spot_check"] = {
        m: [rows.name[i] for i in list(h)[:25]] for m, h in hits.items()
    }
    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(f"-> {args.out}")
    return 0


def _run():
    global _RC
    _RC = main()


if __name__ == "__main__":
    threading.stack_size(512 * 1024 * 1024)
    _RC = 1
    th = threading.Thread(target=_run)
    th.start()
    th.join()
    raise SystemExit(_RC)
