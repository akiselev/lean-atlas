"""Rewrite I3 encodings so implicit and instance arguments are **dropped**, not holed.

## Why

`add(a,b)` is a two-argument application; `a + b` elaborates to `HAdd.hAdd α β γ inst a b`,
six. Anti-unification aligns spines positionally, so the two never align — and no erasure
level repairs it, because erasure holes an argument (`*`) and never removes it, so arity is
preserved by construction. Measured cost: retention falls from ~0.87 to ~0.33 across the
seam, including between two Mathlib declarations (`Nat.add_comm` ~ `Nat.gcd_comm`).

This is the proposed fix, simulated as a slice transform so it can be measured before
`erase.rs` is touched. That module carries several of CLAUDE.md's recorded traps and a
level that changes *arity* deserves its ablation first.

## How

Every constant has a row, so its own telescope says which of its binders are implicit
(`i`) or instance-implicit (`t`). For an application spine headed by that constant, drop
the arguments sitting at those positions. `HAdd.hAdd α β γ inst a b` becomes
`HAdd.hAdd a b`, which aligns with `gcd a b`.

Explicit arguments are kept, so nothing that a caller actually writes is discarded. A
constant with no row in the slice is left alone — dropping on a guess would silently change
statements the slice cannot justify changing.
"""

from __future__ import annotations

import collections

from atlas_home import Reader, telescope

TAG = "atlas-stmt-v1;"


def implicit_positions(rows: dict) -> dict[str, set[int]]:
    """For each constant, the argument positions whose binder is implicit or instance."""
    out: dict[str, set[int]] = {}
    for name, r in rows.items():
        stmt = r.get("stmt")
        if not stmt:
            continue
        try:
            binders, _ = telescope(stmt, limit=64)
        except Exception:
            continue
        drop = {i for i, (bi, _h, _a, _d) in enumerate(binders) if bi in ("i", "t")}
        if drop:
            out[name] = drop
    return out


class _Rw:
    """Recursive rewriter over the encoding grammar."""

    def __init__(self, buf: bytes, drop: dict[str, set[int]]) -> None:
        self.b = buf
        self.drop = drop
        self.i = 0

    # -- primitives ---------------------------------------------------------------
    def _digits(self) -> bytes:
        j = self.i
        while j < len(self.b) and 0x30 <= self.b[j] <= 0x39:
            j += 1
        out = self.b[self.i:j]
        self.i = j
        return out

    def _raw(self, n: int) -> bytes:
        out = self.b[self.i:self.i + n]
        self.i += n
        return out

    def _skip_to(self, end: int) -> bytes:
        out = self.b[self.i:end]
        self.i = end
        return out

    def _span(self) -> tuple[int, int]:
        """Byte span of the next expression, without rewriting."""
        r = Reader.__new__(Reader)
        r.b, r.i = self.b, self.i
        start = r.i
        r.skip()
        return start, r.i

    # -- the grammar --------------------------------------------------------------
    def expr(self) -> bytes:
        c = self.b[self.i]
        if c == 0x61:  # 'a(' — an application spine
            return self.spine()
        if c == 0x63:  # 'c(' — const, copied verbatim
            s, e = self._span()
            return self._skip_to(e)
        if c in (0x6C, 0x70):  # 'l'/'p' binder
            head = self._raw(3)  # letter, bi, '('
            dom = self.expr()
            comma = self._raw(1)
            body = self.expr()
            close = self._raw(1)
            return head + dom + comma + body + close
        if c == 0x65:  # 'e(' — let
            head = self._raw(2)
            a = self.expr()
            c1 = self._raw(1)
            b = self.expr()
            c2 = self._raw(1)
            d = self.expr()
            close = self._raw(1)
            return head + a + c1 + b + c2 + d + close
        if c == 0x6A:  # 'j(' — proj
            s, e = self._span()
            return self._skip_to(e)
        # bvar, nat, string literal, sort: copy
        s, e = self._span()
        return self._skip_to(e)

    def spine(self) -> bytes:
        """Parse `a(a(...(head, a1), a2)...)`, rewrite parts, drop implicit args."""
        start = self.i
        # Collect argument spans outermost-last by walking down the left chain.
        args: list[tuple[int, int]] = []
        cur = start
        while self.b[cur] == 0x61:  # 'a('
            f = cur + 2
            r = Reader.__new__(Reader)
            r.b, r.i = self.b, f
            r.skip()          # function half
            argstart = r.i + 1
            r2 = Reader.__new__(Reader)
            r2.b, r2.i = self.b, argstart
            r2.skip()
            args.append((argstart, r2.i))
            cur = f
        args.reverse()
        # `cur` is the head position.
        headstart = cur
        r = Reader.__new__(Reader)
        r.b, r.i = self.b, headstart
        r.skip()
        headend = r.i
        headbytes = self.b[headstart:headend]

        name = None
        if self.b[headstart] == 0x63:  # 'c('
            hr = Reader.__new__(Reader)
            hr.b, hr.i = self.b, headstart + 2
            name = hr._name()

        keep = []
        dropset = self.drop.get(name or "", set())
        for pos, (a0, a1) in enumerate(args):
            sub = _Rw(self.b, self.drop)
            sub.i = a0
            rewritten = sub.expr()
            if pos in dropset:
                continue
            keep.append(rewritten)

        # advance past the whole original spine
        r = Reader.__new__(Reader)
        r.b, r.i = self.b, start
        r.skip()
        self.i = r.i

        out = headbytes
        for k in keep:
            out = b"a(" + out + b"," + k + b")"
        return out


def rewrite(encoding: str, drop: dict[str, set[int]]) -> str | None:
    body = encoding[len(TAG):] if encoding.startswith(TAG) else encoding
    rw = _Rw(body.encode(), drop)
    try:
        out = rw.expr()
    except Exception:
        return None
    if rw.i != len(rw.b):
        return None
    return TAG + out.decode("utf-8", "replace")
