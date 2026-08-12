"""A full-tree parser for the I3 encoding (`atlas-stmt-v1`), for the dimensional experiment.

`scripts/atlas_home.py` deliberately does *not* build trees: it needs only a telescope's
binders and the conclusion's head, and a tree per statement over a Mathlib-sized slice is
tens of millions of nodes. Dimensional analysis needs the arithmetic *inside* the
conclusion, so it needs the tree — the cost is paid on the physics rows only, and callers
cap statement size (see `phys-dimensional.py`, which reports what the cap drops).

Grammar, read off `atlas-extract/Atlas/Statement.lean` rather than off any prose:

    b<d>                        bvar
    n<d>                        nat literal
    t<len>:<s>                  string literal
    s(<level>)                  sort
    c(<len>:<name>,<k>,<lvl>*)  const  -- `<k>` is an explicit level *count*
    a(<f>,<x>)                  application
    l<bi>(<dom>,<body>)         lambda
    p<bi>(<dom>,<body>)         pi
    e(<ty>,<val>,<body>)        let
    j(<len>:<name>,<i>,<e>)     projection

Parsed over **bytes**: names are byte-length-prefixed and may contain any UTF-8, so
`c(3:ℝ,0)` is three bytes and one character. A constant's levels are skipped — nothing here
is level-sensitive and keeping them would double the node count — but a *sort's* level is
kept, because `Prop` and `Type` are the difference between a relation and a data type.
"""

from __future__ import annotations

TAG = "atlas-stmt-v1;"
TAG_B = TAG.encode()

# Nodes are plain tuples because millions exist at once:
#   ("b", idx) ("n", v) ("t", s) ("s", level) ("c", name)
#   ("a", f, x) ("l", bi, dom, body) ("p", bi, dom, body) ("e", ty, val, body)
#   ("j", struct, idx, e)

class Parser:
    __slots__ = ("b", "i")

    def __init__(self, encoding: str) -> None:
        self.b = encoding.encode()
        self.i = len(TAG_B) if self.b.startswith(TAG_B) else 0

    def _name(self) -> str:
        b, j = self.b, self.i
        while b[j] != 0x3A:  # ':'
            j += 1
        ln = int(b[self.i:j])
        self.i = j + 1 + ln
        return b[j + 1:j + 1 + ln].decode("utf-8", "replace")

    def _digits(self) -> int:
        b, j = self.b, self.i
        while j < len(b) and 0x30 <= b[j] <= 0x39:
            j += 1
        v = int(b[self.i:j]) if j > self.i else 0
        self.i = j
        return v

    def _skip_level(self) -> None:
        c = self.b[self.i]
        if c == 0x30:      # '0'
            self.i += 1
        elif c == 0x75:    # 'u'
            self.i += 1
            self._digits()
        elif c in (0x2B, 0x4D, 0x49):  # '+', 'M', 'I'
            self.i += 2
            self._skip_level()
            while self.b[self.i] == 0x2C:
                self.i += 1
                self._skip_level()
            self.i += 1
        else:
            raise ValueError(f"level at {self.i}")

    def expr(self):
        b = self.b
        c = b[self.i]
        if c == 0x61:      # a(
            self.i += 2
            f = self.expr()
            self.i += 1
            x = self.expr()
            self.i += 1
            return ("a", f, x)
        if c == 0x63:      # c(
            self.i += 2
            n = self._name()
            self.i += 1
            k = self._digits()
            for _ in range(k):
                self.i += 1
                self._skip_level()
            self.i += 1
            return ("c", n)
        if c == 0x62:      # b
            self.i += 1
            return ("b", self._digits())
        if c in (0x70, 0x6C):  # p<bi>( / l<bi>(
            tag = "p" if c == 0x70 else "l"
            bi = chr(b[self.i + 1])
            self.i += 3
            dom = self.expr()
            self.i += 1
            body = self.expr()
            self.i += 1
            return (tag, bi, dom, body)
        if c == 0x6E:      # n
            self.i += 1
            return ("n", self._digits())
        if c == 0x73:      # s(
            self.i += 2
            j = self.i
            self._skip_level()
            lvl = b[j:self.i].decode()
            self.i += 1
            # The level is kept for sorts alone: a dimension indexes *data* types, and
            # `Prop` (level `0`) is not one. Dropping it made `Eq` and `LE.le` count as
            # type constructors, which is how the Mathlib control out-ranked the physics.
            return ("s", lvl)
        if c == 0x74:      # t<len>:<s>
            self.i += 1
            return ("t", self._name())
        if c == 0x65:      # e(
            self.i += 2
            ty = self.expr()
            self.i += 1
            val = self.expr()
            self.i += 1
            body = self.expr()
            self.i += 1
            return ("e", ty, val, body)
        if c == 0x6A:      # j(
            self.i += 2
            s = self._name()
            self.i += 1
            k = self._digits()
            self.i += 1
            e = self.expr()
            self.i += 1
            return ("j", s, k, e)
        raise ValueError(f"expr {chr(c)!r} at {self.i}")


def parse(encoding: str):
    return Parser(encoding).expr()


def spine(e):
    """`(head, args)` of an application spine; args in written (outermost-last) order."""
    args = []
    while e[0] == "a":
        args.append(e[2])
        e = e[1]
    args.reverse()
    return e, args


def iter_spines(e):
    """Yield `(head, args)` for every *maximal* application spine in `e`, once each.

    Walking every node and calling `spine` there is quadratic in the spine's length, and
    physlib's tensor statements have spines thousands long — the difference between a pass
    that finishes and one that does not.
    """
    stack = [e]
    while stack:
        n = stack.pop()
        t = n[0]
        if t == "a":
            head, args = spine(n)
            yield head, args
            stack.append(head)
            stack.extend(args)
        elif t in ("p", "l"):
            stack.append(n[2])
            stack.append(n[3])
        elif t == "e":
            stack.extend((n[1], n[2], n[3]))
        elif t == "j":
            stack.append(n[3])


def pi_telescope(e):
    """Strip top-level `forall`s: `(binders, body)` with binders as `(binder_info, dom)`."""
    binders = []
    while e[0] == "p":
        binders.append((e[1], e[2]))
        e = e[3]
    return binders, e


def const_name(e):
    return e[1] if e[0] == "c" else None


def has_loose_bvar(e, depth: int = 0) -> bool:
    """Does `e` mention a de Bruijn index escaping it?

    Needed because atom identity keys on the *closed* arguments of a spine: `single .length`
    and `single .time` must not become one atom, or the solver identifies length with time
    and the whole lattice collapses.
    """
    stack = [(e, depth)]
    while stack:
        n, d = stack.pop()
        t = n[0]
        if t == "b":
            if n[1] >= d:
                return True
        elif t == "a":
            stack.append((n[1], d))
            stack.append((n[2], d))
        elif t in ("p", "l"):
            stack.append((n[2], d))
            stack.append((n[3], d + 1))
        elif t == "e":
            stack.append((n[1], d))
            stack.append((n[2], d))
            stack.append((n[3], d + 1))
        elif t == "j":
            stack.append((n[3], d))
    return False


def annotate(root):
    """One bottom-up pass giving every node its `(needs, size)`.

    `needs` is how many enclosing binders the subterm requires — 0 exactly when it is
    closed. `size` is its node count.

    Both were previously recomputed per query, and both are asked at every argument of every
    application spine. On physlib's tensor statements, where one statement is 200 kB of
    nested spines, that is quadratic and the pass never finishes; here it is linear. Keyed by
    `id`, which is sound because the caller holds the tree for the duration.
    """
    needs: dict[int, int] = {}
    size: dict[int, int] = {}
    order = []
    stack = [root]
    while stack:                       # collect in reverse topological order
        n = stack.pop()
        order.append(n)
        t = n[0]
        if t == "a":
            stack.append(n[1])
            stack.append(n[2])
        elif t in ("p", "l"):
            stack.append(n[2])
            stack.append(n[3])
        elif t == "e":
            stack.extend((n[1], n[2], n[3]))
        elif t == "j":
            stack.append(n[3])
    for n in reversed(order):
        k = id(n)
        t = n[0]
        if t == "b":
            needs[k] = n[1] + 1
            size[k] = 1
        elif t == "a":
            a, b = id(n[1]), id(n[2])
            needs[k] = needs[a] if needs[a] > needs[b] else needs[b]
            size[k] = 1 + size[a] + size[b]
        elif t in ("p", "l"):
            a, b = id(n[2]), id(n[3])
            under = needs[b] - 1
            needs[k] = max(needs[a], under if under > 0 else 0)
            size[k] = 1 + size[a] + size[b]
        elif t == "e":
            a, b, c = id(n[1]), id(n[2]), id(n[3])
            under = needs[c] - 1
            needs[k] = max(needs[a], needs[b], under if under > 0 else 0)
            size[k] = 1 + size[a] + size[b] + size[c]
        elif t == "j":
            a = id(n[3])
            needs[k] = needs[a]
            size[k] = 1 + size[a]
        else:
            needs[k] = 0
            size[k] = 1
    return needs, size


def render(e, budget: int = 400) -> str:
    """A compact canonical string for a closed subterm, used as part of an atom key."""
    out = []

    def go(n):
        if len(out) > budget:
            return
        t = n[0]
        if t == "c":
            out.append(n[1])
        elif t == "b":
            out.append(f"#{n[1]}")
        elif t == "n":
            out.append(str(n[1]))
        elif t == "t":
            out.append(repr(n[1]))
        elif t == "s":
            out.append("Prop" if n[1] == "0" else "Sort" + n[1])
        elif t == "a":
            out.append("(")
            go(n[1])
            out.append(" ")
            go(n[2])
            out.append(")")
        elif t in ("p", "l"):
            out.append(t + n[1] + "[")
            go(n[2])
            out.append("|")
            go(n[3])
            out.append("]")
        elif t == "e":
            out.append("let[")
            go(n[3])
            out.append("]")
        elif t == "j":
            out.append(f"{n[1]}.{n[2]}(")
            go(n[3])
            out.append(")")

    go(e)
    s = "".join(out)
    return s if len(s) <= budget else s[:budget] + "…"


def shape_key(e, budget: int = 100000) -> str:
    """The statement with every constant name replaced by one token.

    Structure, binder info, de Bruijn indices and literals survive; *which* constants were
    used does not. Two statements with the same key are the same statement modulo the
    constants filling it.

    Exists so a ground truth can be validated without `Corpus.skeleton`, which erases and
    therefore needs a closed slice, and without retention, which is the quantity under test.
    A label set validated by the score being measured measures nothing.
    """
    out = []
    stack = [e]
    while stack and len(out) < budget:
        n = stack.pop()
        t = n[0]
        if t == "c":
            out.append("C")
        elif t == "b":
            out.append(f"#{n[1]}")
        elif t == "n":
            out.append(f"N{n[1]}")
        elif t == "t":
            out.append("S")
        elif t == "s":
            out.append("*" + n[1])
        elif t == "a":
            out.append("(")
            stack.append(n[2])
            stack.append(n[1])
        elif t in ("p", "l"):
            out.append(t + n[1])
            stack.append(n[3])
            stack.append(n[2])
        elif t == "e":
            out.append("L")
            stack.extend((n[3], n[2], n[1]))
        elif t == "j":
            out.append(f"J{n[2]}")
            stack.append(n[3])
    return "".join(out)


def node_count(e) -> int:
    n = 0
    stack = [e]
    while stack:
        x = stack.pop()
        n += 1
        t = x[0]
        if t == "a":
            stack.append(x[1])
            stack.append(x[2])
        elif t in ("p", "l"):
            stack.append(x[2])
            stack.append(x[3])
        elif t == "e":
            stack.extend((x[1], x[2], x[3]))
        elif t == "j":
            stack.append(x[3])
    return n
