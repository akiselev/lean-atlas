"""New Atlas queries that exploit exact structure instead of a similarity float.

`research/corpus-atlas-findings.md` §13-16 record eight scoring formulas landing inside
noise of one another (MRR 0.16-0.30) and every surviving result coming from *exact*
structure instead: statement identity, proved `Iff` edges, motif families, kernel
verification. §15 found that partitioning a query's candidates by shared pattern beats
ranking them. This script prototypes the queries that follow from taking that seriously.

Six methods, each with a stated pass condition and a control that can fail. Nothing here
computes a similarity score, and nothing here matches on names.

--------------------------------------------------------------------------------
The shared primitive: the constant-blank key
--------------------------------------------------------------------------------

Every I3 statement is a tree whose leaves include *constant* symbols. Blank every
constant name and what is left is the statement's **rigid skeleton** — the exact shape,
with the vocabulary removed. Two declarations with equal skeletons differ *only* in which
constants sit in which slot, and the difference is then a list of `(slot, a, b)`, which is
an edit rather than a number.

This is what `generalize` throws away. Anti-unification computes the pattern *and* the
substitutions specialising it to each side, and the pipeline keeps the pattern's node count
and discards the substitutions (§15). Recovering them is the cheapest new query there is:
the skeleton is a hash key, so the whole corpus partitions in one pass with no floors, no
`k` and no formula.

--------------------------------------------------------------------------------
M1 `variants(name)` — the exact structural neighbourhood, with the diff
--------------------------------------------------------------------------------

Declarations whose statement is this one with a **uniform substitution of one constant for
another**, or of k constants. Returns the edit, not a score.

*Pass*: on the 131k algebra slice, restricted to claims, at least 200 theorems have a
k=1 partner; the recurring substitutions are coherent operator/relation pairs; and the
`similar` head-to-head shows partners `similar` does not return in its top 10, i.e. the
method adds recall rather than only explanation.

*Fail*: the k=1 partners are dominated by declarations Lean generated (`injEq`,
`sizeOf_spec`, recursors) with substitutions between unrelated constants, or `similar`
already returns every partner at rank <= 10, in which case this is a presentation change.

*Control (degradation)*: permute which constant-list attaches to which skeleton among
skeletons taking the same number of constants. Structure is preserved exactly; only the
association between shape and vocabulary is destroyed. The k=1 pair count must collapse.

--------------------------------------------------------------------------------
M2 `substitutions()` — a dictionary with no scorer in it
--------------------------------------------------------------------------------

The corpus-wide inventory of substitutions M1 witnesses: `(a -> b, how many independent
skeletons witness it)`. This is B6's `dictionary` question answered by exact structure,
where the shipped answer is 96% collisions (§21) and is ranked by a float.

*Pass*: the inventory **transfers**. Learned on half the corpus's modules, it predicts a
strictly higher fraction of the other half's substitutions than a frequency-matched null
does. That is the property a dictionary must have and a coincidence must not.

*Fail*: transfer rate is at or below the null, i.e. the inventory is a restatement of which
constants are common.

--------------------------------------------------------------------------------
M3 `adjacent(name)` — what sits just outside an equivalence class, and why
--------------------------------------------------------------------------------

§46 scored V6 PARTIAL only because this does not exist: the RH reformulation cluster
assembled and "Lambda >= 0" was not surfaced as an adjacent non-member. Adjacency is
defined by exact structure at two levels: `d` is adjacent to the class of `x` when it is
*not* in the class and its rigid skeleton equals a member's, with the substitution reported.

*Pass*: for classes that have one, the adjacent set is small (orders of magnitude below the
corpus) and every member carries a named substitution; and on a planted near-miss the near
miss is returned.

*Fail*: adjacency is empty for nearly every class (no reach) or returns thousands of members
with no discriminating diff (no precision).

*Control*: a size-matched random set of declarations standing in for a real class must have
a far smaller adjacency yield per member than a real class does.

--------------------------------------------------------------------------------
M4 `proof_shape` — the index §46 called UNRUNNABLE
--------------------------------------------------------------------------------

`atlas.md` §1e specifies a proof-shape index; V9 could not run because statements are
indexed and proofs are not. A proof is available only as `uses_proof`, a list of names —
but every name in it has a *statement*, so a proof's shape is the multiset of the
**conclusion shapes of the lemmas it invokes**. That is structure, not names: two proofs
have the same shape when they lean on the same kinds of fact in the same proportions.

*Pass*: genuine citation lists produce far more, and far larger, exact proof-shape families
than a degree-preserving citation shuffle does, and the families are legible.

*Fail*: genuine and shuffled agree, i.e. proof shape is punctuation.

*Control*: shuffle each declaration's `uses_proof` by resampling the same number of citations
from the corpus-wide citation frequency distribution. Family count must collapse.

--------------------------------------------------------------------------------
M5 `match(pattern)` — retrieval by pattern instead of by example
--------------------------------------------------------------------------------

Every query in the shipped surface takes a declaration and asks what resembles it. None
takes a *partial statement* and asks what completes it. `match` takes an I3 term with `_`
holes and returns every declaration one-way matching it, as a partition by the terms the
holes were filled with.

*Pass*: 100% recall against an independent brute-force matcher over a sample; a pattern
built from a known family retrieves that family; a well-formed pattern the corpus cannot
contain returns zero.

*Fail*: any false negative against brute force, or a syntactically absent pattern returning
rows.

--------------------------------------------------------------------------------
M6 `transport_exact(name, a := b)` — the operation §24 says has never done anything
--------------------------------------------------------------------------------

B6's `transport` applies a *skeleton* row and asks where the image lands; §24 records that
it has never produced anything. A witnessed substitution is a rewrite instead: applying
`a := b` to a statement yields a **fully written statement**, and asking whether it exists
is an exact lookup on the encoding rather than a match against a pattern.

*Pass*: the fraction of rewrites whose image is already a declaration is far above a
frequency-matched null, and the misses are stated targets rather than skeletons.

*Fail*: the hit rate matches the null, i.e. the inventory adds nothing to guessing.

*Control*: the same left-hand constants with a frequency-matched random right-hand side.

--------------------------------------------------------------------------------

Usage:  uv run --no-sync python scripts/phys-newqueries.py --slice <f> --method all
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import itertools
import random
import sys
import time

import atlas

TAG = b"atlas-stmt-v1;"
BLANK = b"#"


# ---------------------------------------------------------------------------
# The constant-blank key
# ---------------------------------------------------------------------------

def split_constants(enc: bytes) -> tuple[bytes, list[bytes]]:
    """`(rigid skeleton, constant names in slot order)`.

    A scan, not a parse: names and string literals are byte-length-prefixed, so a `c(`
    occurring *inside* a name can never be mistaken for a constant marker and the whole
    thing is safe over bytes. It is not safe over `str` — `c(3:R,0)` is three bytes and
    one character.

    The length prefix goes with the name, so the skeleton records that a slot exists and
    nothing about what filled it. Keeping the prefix would leak the name's length into the
    key and split families by how long their operator is spelled.
    """
    out = bytearray()
    names: list[bytes] = []
    i, n, last = 0, len(enc), 0
    while i < n:
        ch = enc[i]
        if (ch == 0x63 or ch == 0x6A) and i + 1 < n and enc[i + 1] == 0x28:  # 'c(' / 'j('
            j = i + 2
            k = j
            while k < n and 0x30 <= enc[k] <= 0x39:
                k += 1
            if k == j or k >= n or enc[k] != 0x3A:
                i += 1
                continue
            ln = int(enc[j:k])
            a, b = k + 1, k + 1 + ln
            out += enc[last:j]
            out += BLANK
            names.append(enc[a:b])
            last = b
            i = b
            continue
        if ch == 0x74:  # 't' is a string literal iff digits and ':' follow, else binder info
            j = i + 1
            k = j
            while k < n and 0x30 <= enc[k] <= 0x39:
                k += 1
            if k > j and k < n and enc[k] == 0x3A:
                i = k + 1 + int(enc[j:k])
                continue
        i += 1
    out += enc[last:]
    return bytes(out), names


def assemble(skel: bytes, names: list[bytes]) -> bytes:
    """The inverse of `split_constants`: refill a rigid skeleton's slots.

    Needed by the injection controls. A positive control has to *construct* the near miss
    it then asks the query to find, and a specificity control has to construct a row with
    the right vocabulary in the wrong structure — neither is expressible without this.
    """
    out = bytearray()
    k = 0
    for part in skel.split(BLANK):
        if k:
            nm = names[k - 1]
            out += str(len(nm)).encode() + b":" + nm
        out += part
        k += 1
    if k - 1 != len(names):
        raise ValueError(f"slot/name mismatch: {k-1} slots, {len(names)} names")
    return bytes(out)


def strip_tag(s: str) -> bytes:
    e = s.encode()
    return e[len(TAG):] if e.startswith(TAG) else e


def h16(b: bytes) -> bytes:
    return hashlib.blake2b(b, digest_size=16).digest()


# ---------------------------------------------------------------------------
# A synchronized scanner: one-way matching without building a tree
# ---------------------------------------------------------------------------
#
# Both a pattern and a statement are prefix-free UTF-8 in the same grammar, so matching is
# a walk over two byte strings at once. That matters at corpus scale: building a Python
# tree for every statement in a 131k slice is tens of millions of tuples, and the whole
# query is a comparison that never needs the tree.

def skip_level(b: bytes, i: int) -> int:
    c = b[i]
    if c == 0x30 or c == 0x2A:              # '0' | '*' (an erased level)
        return i + 1
    if c == 0x75:                            # 'u' <digits>
        i += 1
        while i < len(b) and 0x30 <= b[i] <= 0x39:
            i += 1
        return i
    if c in (0x2B, 0x4D, 0x49):              # '+(' | 'M(' | 'I('
        i += 2
        i = skip_level(b, i)
        while b[i] == 0x2C:
            i = skip_level(b, i + 1)
        return i + 1
    raise ValueError(f"level {chr(c)!r} at {i}")


def _digits(b: bytes, i: int) -> int:
    while i < len(b) and 0x30 <= b[i] <= 0x39:
        i += 1
    return i


def skip_expr(b: bytes, i: int) -> int:
    c = b[i]
    if c == 0x5F:                            # '_' a hole
        return i + 1
    if c == 0x3F:                            # '?k' an anti-unification variable
        return _digits(b, i + 1)
    if c == 0x62 or c == 0x6E:               # 'b' <n> | 'n' <n>
        return _digits(b, i + 1)
    if c == 0x74:                            # 't' <len> ':' <bytes>
        j = _digits(b, i + 1)
        return j + 1 + int(b[i + 1:j])
    if c == 0x73:                            # 's(' level ')'
        return skip_level(b, i + 2) + 1
    if c == 0x63:                            # 'c(' name ',' n {',' level} ')'
        j = _digits(b, i + 2)
        i = j + 1 + int(b[i + 2:j])          # past the name
        j = _digits(b, i + 1)                # the level count
        n = int(b[i + 1:j])
        i = j
        for _ in range(n):
            i = skip_level(b, i + 1)
        return i + 1
    if c == 0x61:                            # 'a(' e ',' e ')'
        i = skip_expr(b, i + 2)
        return skip_expr(b, i + 1) + 1
    if c == 0x6C or c == 0x70:               # 'l' bi '(' | 'p' bi '('
        i = skip_expr(b, i + 3)
        return skip_expr(b, i + 1) + 1
    if c == 0x65:                            # 'e(' e ',' e ',' e ')'
        i = skip_expr(b, i + 2)
        i = skip_expr(b, i + 1)
        return skip_expr(b, i + 1) + 1
    if c == 0x6A:                            # 'j(' name ',' n ',' e ')'
        j = _digits(b, i + 2)
        i = j + 1 + int(b[i + 2:j])
        i = _digits(b, i + 1)
        return skip_expr(b, i + 1) + 1
    raise ValueError(f"expr {chr(c)!r} at {i}")


def match_level(p: bytes, pi: int, t: bytes, ti: int):
    if p[pi] == 0x2A:                        # '*' matches any level
        return pi + 1, skip_level(t, ti)
    if p[pi] != t[ti]:
        return None
    c = p[pi]
    if c == 0x30:
        return pi + 1, ti + 1
    if c == 0x75:
        pj, tj = _digits(p, pi + 1), _digits(t, ti + 1)
        return (pj, tj) if p[pi:pj] == t[ti:tj] else None
    if c in (0x2B, 0x4D, 0x49):
        pi, ti = pi + 2, ti + 2
        while True:
            r = match_level(p, pi, t, ti)
            if r is None:
                return None
            pi, ti = r
            if p[pi] == 0x2C and t[ti] == 0x2C:
                pi, ti = pi + 1, ti + 1
                continue
            if p[pi] != t[ti]:
                return None
            return pi + 1, ti + 1
    return None


def match_expr(p: bytes, pi: int, t: bytes, ti: int):
    """Match pattern `p` at `pi` against term `t` at `ti`; `(pi', ti')` or `None`.

    `_` in the pattern matches any one subterm; `?k` likewise, and **without binding** —
    an anti-unification variable that recurred would need a binding table, and every
    pattern this prototype consumes comes from `Corpus.skeleton`, which emits holes only.
    Treating `?k` as unconstrained is the recall-preserving direction: it can over-match
    and never under-match, and a false positive is cheap.
    """
    c = p[pi]
    if c == 0x5F:
        return pi + 1, skip_expr(t, ti)
    if c == 0x3F:
        return _digits(p, pi + 1), skip_expr(t, ti)
    if c != t[ti]:
        return None
    if c == 0x62 or c == 0x6E:
        pj, tj = _digits(p, pi + 1), _digits(t, ti + 1)
        return (pj, tj) if p[pi:pj] == t[ti:tj] else None
    if c == 0x74:
        pj = _digits(p, pi + 1)
        pe = pj + 1 + int(p[pi + 1:pj])
        tj = _digits(t, ti + 1)
        te = tj + 1 + int(t[ti + 1:tj])
        return (pe, te) if p[pi:pe] == t[ti:te] else None
    if c == 0x73:
        r = match_level(p, pi + 2, t, ti + 2)
        return None if r is None else (r[0] + 1, r[1] + 1)
    if c == 0x63:
        pj = _digits(p, pi + 2)
        pe = pj + 1 + int(p[pi + 2:pj])
        tj = _digits(t, ti + 2)
        te = tj + 1 + int(t[ti + 2:tj])
        if p[pj + 1:pe] != t[tj + 1:te]:
            return None
        pj, tj = _digits(p, pe + 1), _digits(t, te + 1)
        if p[pe + 1:pj] != t[te + 1:tj]:     # differing level counts are different constants
            return None
        n = int(p[pe + 1:pj])
        pi, ti = pj, tj
        for _ in range(n):
            r = match_level(p, pi + 1, t, ti + 1)
            if r is None:
                return None
            pi, ti = r
        return pi + 1, ti + 1
    if c == 0x61:
        r = match_expr(p, pi + 2, t, ti + 2)
        if r is None:
            return None
        r = match_expr(p, r[0] + 1, t, r[1] + 1)
        return None if r is None else (r[0] + 1, r[1] + 1)
    if c == 0x6C or c == 0x70:
        if p[pi + 1] != t[ti + 1]:           # binder info is part of the node
            return None
        r = match_expr(p, pi + 3, t, ti + 3)
        if r is None:
            return None
        r = match_expr(p, r[0] + 1, t, r[1] + 1)
        return None if r is None else (r[0] + 1, r[1] + 1)
    if c == 0x65:
        r = match_expr(p, pi + 2, t, ti + 2)
        for _ in range(2):
            if r is None:
                return None
            r = match_expr(p, r[0] + 1, t, r[1] + 1)
        return None if r is None else (r[0] + 1, r[1] + 1)
    if c == 0x6A:
        pj = _digits(p, pi + 2)
        pe = pj + 1 + int(p[pi + 2:pj])
        tj = _digits(t, ti + 2)
        te = tj + 1 + int(t[ti + 2:tj])
        if p[pj + 1:pe] != t[tj + 1:te]:
            return None
        pj, tj = _digits(p, pe + 1), _digits(t, te + 1)
        if p[pe + 1:pj] != t[te + 1:tj]:
            return None
        r = match_expr(p, pj + 1, t, tj + 1)
        return None if r is None else (r[0] + 1, r[1] + 1)
    return None


def matches(pattern: bytes, term: bytes) -> bool:
    r = match_expr(pattern, 0, term, 0)
    return r is not None and r[0] == len(pattern) and r[1] == len(term)


def expr_spans(b: bytes) -> list[tuple[int, int]]:
    """`(start, end)` of every subexpression, so a hole can be punched at any position."""
    out: list[tuple[int, int]] = []
    stack = [0]
    while stack:
        i = stack.pop()
        j = skip_expr(b, i)
        out.append((i, j))
        c = b[i]
        if c == 0x61:                                  # 'a('
            k = skip_expr(b, i + 2)
            stack.append(i + 2)
            stack.append(k + 1)
        elif c == 0x6C or c == 0x70:                   # 'l' bi '(' / 'p' bi '('
            k = skip_expr(b, i + 3)
            stack.append(i + 3)
            stack.append(k + 1)
        elif c == 0x65:                                # 'e('
            k = skip_expr(b, i + 2)
            m = skip_expr(b, k + 1)
            stack.extend([i + 2, k + 1, m + 1])
        elif c == 0x6A:                                # 'j(' name ',' n ',' e ')'
            k = _digits(b, i + 2)
            k = k + 1 + int(b[i + 2:k])
            k = _digits(b, k + 1)
            stack.append(k + 1)
    return out


def punch(enc: bytes, span: tuple[int, int]) -> bytes:
    return enc[:span[0]] + b"_" + enc[span[1]:]


def telescope_heads(enc: bytes) -> tuple[str | None, list[str]]:
    """`(conclusion head, classes heading an instance binder's domain)`.

    `scripts/atlas_home.py` establishes the rule this feeds: **a constant whose conclusion is
    itself a class application is plumbing, not evidence.** B3 learned over three tries
    that without that exclusion every declaration reports "at home" — a tool that says
    everything is fine. The same exclusion is what keeps M6's target list from being a
    list of `Foo.toBar` parent projections.
    """
    i, n = 0, len(enc)
    classes: list[str] = []
    while i < n and enc[i] == 0x70:                     # 'p' bi '('
        bi = enc[i + 1]
        d = i + 3
        e = skip_expr(enc, d)
        if bi == 0x74:                                  # InstImplicit
            h = _spine_head(enc, d)
            if h:
                classes.append(h)
        i = e + 1
    return (_spine_head(enc, i) if i < n else None), classes


def _spine_head(b: bytes, i: int) -> str | None:
    while i < len(b) and b[i] == 0x61:                  # 'a(' — descend the function half
        i += 2
    if i < len(b) and b[i] == 0x63:                     # 'c(' name
        j = _digits(b, i + 2)
        return b[j + 1:j + 1 + int(b[i + 2:j])].decode("utf-8", "replace")
    return None


# ---------------------------------------------------------------------------
# The corpus view every method below shares
# ---------------------------------------------------------------------------

class View:
    """Everything the methods need, built in one pass over the slice.

    Every declaration is kept, not only the claims: M4 keys a proof by the *shapes of the
    lemmas it cites*, and those citations land on definitions and instances as often as on
    theorems. `claims` is the restriction CLAUDE.md requires for anything reported as
    mathematics — without it the largest rigid-skeleton bucket in the algebra slice is
    7,358 structure projections.
    """

    def __init__(self, corpus: atlas.Corpus):
        self.c = corpus
        self.name: list[str] = []
        self.kind: list[str] = []
        self.module: list[str] = []
        self.stmt: list[bytes] = []
        self.skel: list[bytes] = []          # rigid skeleton hash
        self.consts: list[tuple[int, ...]] = []
        self.idx: dict[str, int] = {}
        self.vocab: list[bytes] = []
        self._vid: dict[bytes, int] = {}
        self.no_stmt = 0

        for nm in corpus.names():
            d = corpus.get(nm)
            s = d.stmt
            if not s:
                self.no_stmt += 1
                continue
            enc = strip_tag(s)
            sk, cs = split_constants(enc)
            self.idx[nm] = len(self.name)
            self.name.append(nm)
            self.kind.append(d.kind)
            self.module.append(d.module)
            self.stmt.append(enc)
            self.skel.append(h16(sk))
            self.consts.append(tuple(self.vid(x) for x in cs))

        self.claims = [i for i, k in enumerate(self.kind) if k == "theorem"]
        self._cites: dict[int, list[str]] | None = None
        self._deriv: set[int] | None = None
        self._plumbing: set[int] | None = None

    def plumbing(self) -> set[int]:
        """Declarations whose conclusion is itself a class application — see
        `telescope_heads`. Computed over the whole slice because "is a class" is decided
        by whether *anything* binds it as an instance."""
        if self._plumbing is None:
            heads = []
            classes: set[str] = set()
            for i in range(len(self.name)):
                try:
                    h, cs = telescope_heads(self.stmt[i])
                except Exception:
                    h, cs = None, []
                heads.append(h)
                classes.update(cs)
            self._plumbing = {i for i, h in enumerate(heads) if h in classes}
        return self._plumbing

    def cites(self) -> dict[int, list[str]]:
        if self._cites is None:
            self._cites = {i: self.c.get(self.name[i]).uses_proof for i in self.claims}
        return self._cites

    def derivative(self, top_fraction: float = 0.25) -> set[int]:
        """Claims that look auto-generated, from citation structure alone.

        §3b's three signals, combined the way the shipped `derivativeness` combines them —
        as percentile ranks within the corpus, never through fitted coefficients, because
        the fitted weights differ per corpus:

        * a short proof;
        * a large fraction of the proof citing **constructors and recursors** rather than
          theorems, read off each cited declaration's `kind` and never off its name;
        * nothing citing it back.

        Used to **stratify** and never to filter. CLAUDE.md records that at a hard
        threshold the measure runs precision 0.62-0.67, and that a split ground truth is
        stratified rather than dropped. A first pass here used only the first and third
        signals and flagged 361 of 8,251 pairs, missing every `.inj`/`.injEq` batch —
        which is exactly the case the second signal exists for.
        """
        if self._deriv is None:
            cites = self.cites()
            indeg: collections.Counter = collections.Counter()
            for u in cites.values():
                indeg.update(u)
            generated = {self.name[i] for i in range(len(self.name))
                         if self.kind[i] in ("constructor", "recursor")}
            ids = list(self.claims)
            plen = [len(cites[i]) for i in ids]
            frac = [(sum(1 for x in cites[i] if x in generated) / len(cites[i]))
                    if cites[i] else 1.0 for i in ids]
            deg = [indeg.get(self.name[i], 0) for i in ids]

            def pct(vals, ascending: bool):
                order = sorted(range(len(vals)), key=lambda k: vals[k],
                               reverse=not ascending)
                r = [0.0] * len(vals)
                for rank, k in enumerate(order):
                    r[k] = rank / max(len(vals) - 1, 1)
                return r

            a, b, cc = pct(plen, False), pct(frac, True), pct(deg, False)
            score = [(a[k] + b[k] + cc[k]) / 3 for k in range(len(ids))]
            cut = sorted(score, reverse=True)[int(len(score) * top_fraction)]
            self._deriv = {ids[k] for k in range(len(ids)) if score[k] >= cut}
        return self._deriv

    def vid(self, name: bytes) -> int:
        v = self._vid.get(name)
        if v is None:
            v = len(self.vocab)
            self._vid[name] = v
            self.vocab.append(name)
        return v

    def sym(self, v: int) -> str:
        return self.vocab[v].decode("utf-8", "replace")

    def __len__(self) -> int:
        return len(self.name)

    def theory(self, i: int) -> str:
        parts = self.module[i].split(".")
        return ".".join(parts[:2]) if len(parts) > 1 else parts[0]

    def buckets(self, ids: list[int] | None = None) -> dict[bytes, list[int]]:
        b: dict[bytes, list[int]] = collections.defaultdict(list)
        for i in (self.claims if ids is None else ids):
            b[self.skel[i]].append(i)
        return b


# ---------------------------------------------------------------------------
# M1 / M2 — uniform constant substitution
# ---------------------------------------------------------------------------

_MOD = (1 << 61) - 1
_R = 0x9E3779B97F4A7C15 % _MOD
_BLANKH = 0x5DEECE66D
_SYM_CACHE: dict[int, int] = {}


def _SYMH(sym: int) -> int:
    h = _SYM_CACHE.get(sym)
    if h is None:
        h = int.from_bytes(hashlib.blake2b(str(sym).encode(), digest_size=8).digest(),
                           "little") % _MOD
        _SYM_CACHE[sym] = h
    return h


def subst_pairs(skel: list[bytes], consts, members: dict[bytes, list[int]]):
    """Every pair differing by a **uniform** substitution of one constant for another.

    Indexed, not quadratic. For each declaration and each distinct constant `x` it holds,
    the key `(skeleton, constant-list with every occurrence of x blanked)` is emitted. Two
    declarations sharing that key with different blanked constants differ exactly by
    substituting one for the other, everywhere it occurs.

    Yields `(i, j, a, b)` with `a` the constant in `i` and `b` its image in `j`.
    """
    seen: set[tuple[int, int]] = set()
    for _key, ids in members.items():
        if len(ids) < 2:
            continue
        table: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
        for i in ids:
            cs = consts[i]
            # The masked key is computed **incrementally**. Materialising a fresh tuple
            # per distinct constant costs O(distinct x slots) per declaration, and both
            # factors scale with statement size: the Mathlib slice averages 15.5
            # application heads per declaration and physlib 1,329, so the same code is
            # thousands of times more work there. It stalled the first physlib run for ten
            # minutes without a line of output. A position-weighted polynomial hash lets
            # one slot's contribution be subtracted in O(1), so this is O(slots+distinct).
            base = 0
            weight_of: dict[int, int] = {}
            w = 1
            for c in cs:
                base = (base + w * _SYMH(c)) % _MOD
                weight_of[c] = (weight_of.get(c, 0) + w) % _MOD
                w = (w * _R) % _MOD
            for x, sx in weight_of.items():
                table[(base - sx * (_SYMH(x) - _BLANKH)) % _MOD].append((i, x))
        for _m, entries in table.items():
            if len(entries) < 2:
                continue
            for p in range(len(entries)):
                for q in range(p + 1, len(entries)):
                    (i, a), (j, b) = entries[p], entries[q]
                    if a == b or i == j:
                        continue
                    k = (i, j) if i < j else (j, i)
                    if k in seen:
                        continue
                    # The hash can collide; the claim "these differ by exactly one uniform
                    # substitution" cannot be left to a 61-bit coincidence, so every
                    # candidate is confirmed against the lists themselves.
                    ci, cj = consts[i], consts[j]
                    if any((y != a) != (z != b) or (y != a and y != z)
                           for y, z in zip(ci, cj)):
                        continue
                    seen.add(k)
                    yield (i, j, a, b) if i < j else (j, i, b, a)


def edit_distance_pairs(view: View, members: dict[bytes, list[int]], max_bucket: int = 300):
    """Every within-bucket pair, with the full slot-level diff — the structural diff query.

    Quadratic inside a bucket, so buckets above `max_bucket` are counted and skipped rather
    than silently dropped: a skipped bucket is a false negative, and those are the
    expensive kind.

    Yields `(i, j, distinct substitutions, [(slot, a, b), ...])`.
    """
    skipped = 0
    for _key, ids in members.items():
        if len(ids) < 2:
            continue
        # Both the member count and the slot count enter the cost, and a physlib statement
        # carries ~1,300 constant slots against a Mathlib claim's ~20 — a member cap alone
        # is not a cost cap. Skips are counted and printed: a silent skip is a false
        # negative, and those are the expensive kind.
        if len(ids) > max_bucket or len(ids) ** 2 * (len(view.consts[ids[0]]) + 1) > 5e7:
            skipped += 1
            continue
        for p in range(len(ids)):
            for q in range(p + 1, len(ids)):
                i, j = ids[p], ids[q]
                ci, cj = view.consts[i], view.consts[j]
                diff = [(k, a, b) for k, (a, b) in enumerate(zip(ci, cj)) if a != b]
                subs = {(a, b) for _k, a, b in diff}
                yield i, j, len(subs), diff
    if skipped:
        print(f"    [edit_distance_pairs skipped {skipped} buckets over {max_bucket}]")


def m1_variants(v: View, c: atlas.Corpus, out: dict, sample: int = 200) -> None:
    """M1: the exact structural neighbourhood, and the head-to-head against `similar`."""
    print("\n=== M1  variants: uniform single-constant substitution ===")
    members = v.buckets()
    sizes = collections.Counter(len(x) for x in members.values())
    multi = {k: x for k, x in members.items() if len(x) > 1}
    print(f"  rigid skeletons over {len(v.claims)} claims: {len(members)}  "
          f"({len(multi)} shared by >1 claim, covering "
          f"{sum(len(x) for x in multi.values())} claims)")
    print(f"  largest bucket: {max(sizes)} claims")

    t0 = time.time()
    pairs = list(subst_pairs(v.skel, v.consts, members))
    print(f"  k=1 uniform-substitution pairs: {len(pairs)} in {time.time()-t0:.1f}s")
    involved = {i for i, _j, _a, _b in pairs} | {j for _i, j, _a, _b in pairs}
    print(f"  claims with at least one k=1 partner: {len(involved)}"
          f" ({100*len(involved)/max(len(v.claims),1):.1f}% of claims)")

    # The full diff, at every distance, not only k=1.
    t0 = time.time()
    dist = collections.Counter()
    for _i, _j, k, _d in edit_distance_pairs(v, members):
        dist[k] += 1
    print(f"  within-bucket pairs by distinct substitutions ({time.time()-t0:.0f}s): "
          + ", ".join(f"k={k}:{n}" for k, n in sorted(dist.items())[:8]))

    # A substitution is witnessed by a *skeleton*, not by a pair: one skeleton shared by
    # forty lemmas would otherwise let a single family vote forty times.
    wit: dict[tuple[int, int], set[bytes]] = collections.defaultdict(set)
    for i, _j, a, b in pairs:
        wit[(a, b) if a < b else (b, a)].add(v.skel[i])
    ranked = sorted(wit.items(), key=lambda kv: -len(kv[1]))
    print(f"  distinct substitutions: {len(wit)}")
    print("  top 15 by independent skeletons witnessing them:")
    for (a, b), s in ranked[:15]:
        print(f"    {len(s):5d}  {v.sym(a):42s} <-> {v.sym(b)}")

    # --- control: destroy the association between shape and vocabulary ---
    by_arity: dict[int, list[int]] = collections.defaultdict(list)
    for i in v.claims:
        by_arity[len(v.consts[i])].append(i)
    shuffled = list(v.consts)
    for _arity, ids in by_arity.items():
        perm = ids[:]
        random.shuffle(perm)
        for src, dst in zip(ids, perm):
            shuffled[dst] = v.consts[src]
    ctrl = sum(1 for _ in subst_pairs(v.skel, shuffled, members))
    print(f"  CONTROL (constant-lists permuted within arity): {ctrl} pairs "
          f"vs {len(pairs)} genuine  [{len(pairs)/max(ctrl,1):.1f}x]")

    # --- head-to-head: does `similar` already return the partner? ---
    #
    # Stratified. The first run of this pointed at six misses and every one was a
    # `.inj`/`.injEq`/`instNonempty` pair — which `similar` down-ranks on purpose, by the
    # derivativeness factor. An unstratified recall number would have claimed credit for
    # finding boilerplate.
    h2h = {}
    if pairs:
        deriv = v.derivative()
        strata = {
            "substantive": [p for p in pairs if p[0] not in deriv and p[1] not in deriv],
            "derivative": [p for p in pairs if p[0] in deriv or p[1] in deriv],
        }
        print(f"  strata: substantive {len(strata['substantive'])} pairs, "
              f"derivative {len(strata['derivative'])} pairs")
        for label, pool in strata.items():
            if not pool:
                continue
            take = random.sample(pool, min(sample, len(pool)))
            t0 = time.time()
            hits10 = hits50 = asked = errs = 0
            misses = []
            for i, j, _a, _b in take:
                qn, tn = v.name[i], v.name[j]
                try:
                    ns = c.similar(qn, top=50, theorems_only=True)
                except Exception:
                    errs += 1
                    continue
                asked += 1
                order = [n.name for n in ns]
                if tn in order[:10]:
                    hits10 += 1
                if tn in order:
                    hits50 += 1
                else:
                    misses.append((qn, tn))
            print(f"  HEAD-TO-HEAD [{label}] {asked} pairs ({time.time()-t0:.0f}s): "
                  f"partner in similar top-10 {hits10} ({100*hits10/max(asked,1):.1f}%), "
                  f"top-50 {hits50} ({100*hits50/max(asked,1):.1f}%), errors {errs}")
            # CLAUDE.md §5: recall loss is not one number. Split the misses into "never
            # proposed" and "proposed and ranked out".
            never = ranked_out = 0
            for qn, tn in misses[:20]:
                try:
                    bru = [n for n, _r in c.similar_brute(qn, top=200)]
                except Exception:
                    continue
                if tn in bru:
                    ranked_out += 1
                else:
                    never += 1
            # `similar_brute` has no prefilter, so "outside its top 200" is a statement
            # about the *ranking*, not about candidate generation: the pair is tied with a
            # large field at the same retention. Worded that way because "never proposed"
            # would name the wrong cause.
            print(f"    miss split over {min(len(misses),20)}: outside similar_brute's "
                  f"top-200 {never}, inside it but below similar's 50 {ranked_out}")
            for qn, tn in misses[:4]:
                print(f"    missed: {qn}  ~  {tn}")
            h2h[label] = {"asked": asked, "top10": hits10, "top50": hits50,
                          "miss_never": never, "miss_ranked_out": ranked_out,
                          "examples": misses[:8]}
    out["m1_head_to_head"] = h2h

    out["m1"] = {
        "claims": len(v.claims), "skeletons": len(members), "shared_skeletons": len(multi),
        "pairs": len(pairs), "claims_with_partner": len(involved),
        "distinct_subs": len(wit), "control_pairs": ctrl,
        "distance_hist": dict(sorted(dist.items())[:10]),
        "top": [[v.sym(a), v.sym(b), len(s)] for (a, b), s in ranked[:40]],
    }
    return pairs, members


def m2_substitutions(v: View, pairs, out: dict) -> None:
    """M2: does the substitution inventory *transfer* across theories?

    A dictionary is only a dictionary if it says something about text it was not built
    from. Learned on a random half of the slice's theories, tested on the other half,
    against a null that keeps the left-hand constant and resamples the right-hand one from
    the corpus's own constant-occurrence distribution.
    """
    print("\n=== M2  substitutions: a dictionary with no scorer in it ===")
    theories = sorted({v.theory(i) for i in v.claims})
    random.shuffle(theories)
    side = {t: (k % 2) for k, t in enumerate(theories)}
    print(f"  {len(theories)} theories split {sum(1 for x in side.values() if x==0)}/"
          f"{sum(1 for x in side.values() if x==1)}")

    learn: dict[tuple[int, int], set[bytes]] = collections.defaultdict(set)
    test: collections.Counter = collections.Counter()
    for i, j, a, b in pairs:
        si, sj = side[v.theory(i)], side[v.theory(j)]
        key = (a, b) if a < b else (b, a)
        if si == 0 and sj == 0:
            learn[key].add(v.skel[i])
        elif si == 1 and sj == 1:
            test[key] += 1
    test_pairs = sum(test.values())
    print(f"  learned on half A: {len(learn)} substitutions")
    print(f"  held out on half B: {len(test)} distinct substitutions over "
          f"{test_pairs} pairs")

    # Frequency-matched null: keep `a`, resample `b` from constant *occurrences* over the
    # whole slice, so a substitution onto a very common constant is as likely under the
    # null as it is in the data.
    occ: collections.Counter = collections.Counter()
    for i in range(len(v.name)):
        occ.update(v.consts[i])
    pop = list(occ.keys())
    # `random.choices` rebuilds the cumulative weights on every call, which is O(|vocab|)
    # per draw and dominated a 65k-proof control run. Built once instead.
    cum = list(itertools.accumulate(occ[k] for k in pop))
    trials = 8
    rows = []
    # Swept rather than thresholded: the floor is exactly the knob that trades recall for
    # precision, and CLAUDE.md's rule is to report the sweep rather than pick a point.
    for minw in (1, 2, 3):
        inventory = {k for k, s in learn.items() if len(s) >= minw}
        hit = sum(1 for k in test if k in inventory)
        whit = sum(n for k, n in test.items() if k in inventory)
        null_hits = []
        for _ in range(trials):
            draws = random.choices(pop, cum_weights=cum, k=len(test))
            null_hits.append(sum(1 for (a, _b), b2 in zip(test, draws)
                                 if ((a, b2) if a < b2 else (b2, a)) in inventory))
        mean_null = sum(null_hits) / trials
        print(f"  min_witnesses={minw}: inventory {len(inventory)};  TRANSFER "
              f"{hit}/{len(test)} ({100*hit/max(len(test),1):.1f}%) of distinct, "
              f"{whit}/{test_pairs} ({100*whit/max(test_pairs,1):.1f}%) of pairs;  "
              f"NULL mean {mean_null:.1f} (range {min(null_hits)}-{max(null_hits)})")
        rows.append({"min_witnesses": minw, "inventory": len(inventory),
                     "transfer_distinct": hit, "transfer_pairs": whit,
                     "null_mean": mean_null, "null_max": max(null_hits)})
    out["m2"] = {"theories": len(theories), "learned": len(learn),
                 "held_out": len(test), "held_out_pairs": test_pairs, "sweep": rows}


def m6_transport_exact(v: View, pairs, out: dict, budget: int = 400000,
                       max_bytes: int = 200_000) -> None:
    """M6: `transport`, done by construction and checked by identity.

    §24 records that B6's `transport` — "the active operation" — has never done anything.
    It applies a *skeleton* row and asks whether the image is a declaration, and the
    skeleton is what a scored anti-unification left behind.

    A witnessed substitution is a rewrite instead. Applying `a := b` to a statement
    produces a **fully written statement**, not a pattern, and asking whether it exists is
    an exact lookup on the encoding. Two outcomes, both useful: the image exists, and the
    corpus has realised the analogy; or it does not, and the result is a stated, directed
    target rather than a hole.
    """
    print("\n=== M6  transport_exact: substitution as a rewrite, existence as a lookup ===")
    wit: dict[tuple[int, int], set[bytes]] = collections.defaultdict(set)
    for i, _j, a, b in pairs:
        wit[(a, b) if a < b else (b, a)].add(v.skel[i])
    inventory = [k for k, s in wit.items() if len(s) >= 2]
    print(f"  inventory: {len(inventory)} substitutions witnessed by >=2 skeletons")

    exists: dict[bytes, str] = {}
    for i in range(len(v.name)):
        exists.setdefault(v.stmt[i], v.name[i])

    by_const: dict[int, list[int]] = collections.defaultdict(list)
    for i in v.claims:
        for x in set(v.consts[i]):
            by_const[x].append(i)

    occ = collections.Counter()
    for i in range(len(v.name)):
        occ.update(v.consts[i])
    pop = list(occ.keys())
    cum = list(itertools.accumulate(occ[k] for k in pop))

    # A rewrite copies the whole statement, so a subject's size is the unit cost. The
    # physlib slice holds a single 71 MB statement and averages 1,329 application heads
    # against Mathlib's 15.5; without this cap the control arm did not return after ten
    # minutes of CPU. Skips are counted and printed — a silent skip is a false negative,
    # and this method's whole output is candidates.
    oversize = {i for i in v.claims if len(v.stmt[i]) > max_bytes}
    if oversize:
        print(f"  {len(oversize)} claims over {max_bytes} bytes are skipped as subjects")

    def run(inv):
        hit = tried = 0
        opens = []
        for (a, b) in inv:
            for src, dst in ((a, b), (b, a)):
                for i in by_const.get(src, ())[:40]:
                    if tried >= budget:
                        break
                    if i in oversize:
                        continue
                    tried += 1
                    sk, names = split_constants(v.stmt[i])
                    img = assemble(sk, [v.vocab[dst] if x == v.vocab[src] else x
                                        for x in names])
                    got = exists.get(img)
                    if got is not None and got != v.name[i]:
                        hit += 1
                    elif got is None:
                        opens.append((i, v.sym(src), v.sym(dst)))
        return hit, tried, opens

    t0 = time.time()
    hit, tried, opens = run(inventory)
    excl = v.derivative() | v.plumbing()
    subst_opens = [o for o in opens if o[0] not in excl]
    print(f"  GENUINE: {tried} rewrites, image already a declaration in "
          f"{hit} ({100*hit/max(tried,1):.1f}%), open targets {len(opens)} "
          f"of which {len(subst_opens)} survive the derivative and plumbing exclusions "
          f"({time.time()-t0:.0f}s)")

    # Control: the same left-hand constants, a frequency-matched random right-hand side.
    # A hit rate at the genuine one would mean the inventory is doing no work.
    null_inv = []
    for (a, _b) in inventory:
        b2 = random.choices(pop, cum_weights=cum, k=1)[0]
        if b2 != a:
            null_inv.append((a, b2))
    t0 = time.time()
    nhit, ntried, _ = run(null_inv)
    print(f"  CONTROL (right-hand side resampled frequency-matched): {ntried} rewrites, "
          f"image exists in {nhit} ({100*nhit/max(ntried,1):.1f}%) ({time.time()-t0:.0f}s)")

    seenq = set()
    shown = 0
    for i, a, b in subst_opens:
        if (a, b) in seenq:
            continue
        seenq.add((a, b))
        print(f"    open target: {v.name[i]}   [{a} := {b}]")
        shown += 1
        if shown == 10:
            break

    # The vocabulary graph the inventory induces: connected components of interchangeable
    # constants, discovered with no name matching anywhere.
    parent: dict[int, int] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b) in inventory:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comp: dict[int, list[int]] = collections.defaultdict(list)
    for x in parent:
        comp[find(x)].append(x)
    comps = sorted(comp.values(), key=len, reverse=True)
    print(f"  vocabulary components: {len(comps)}, largest {len(comps[0]) if comps else 0}")
    for cc in comps[:6]:
        if len(cc) < 3:
            continue
        print(f"    [{len(cc)}] " + ", ".join(sorted(v.sym(x) for x in cc)[:8]))
    out["m6"] = {"inventory": len(inventory), "tried": tried, "hit": hit,
                 "open": len(opens), "open_substantive": len(subst_opens),
                 "null_tried": ntried, "null_hit": nhit,
                 "components": len(comps),
                 "largest_components": [sorted(v.sym(x) for x in cc)[:12]
                                        for cc in comps[:8]]}


def m3_adjacent(v: View, c: atlas.Corpus, members, out: dict, n_probe: int = 40) -> None:
    """M3: `adjacent` — what sits just outside an equivalence class, and why.

    Two tiers, both exact:

    * **tier 1, one substitution away** — outside the class, same rigid skeleton as a
      member, reported with the constant swap that separates them.
    * **tier 2, one squint away** — outside the class at this level, inside it at the next
      coarser one. Pure `equivalent` at two levels; no new machinery, and it has never
      been asked.
    """
    print("\n=== M3  adjacent: the query V6 was scored PARTIAL for lacking ===")

    # The whole class inventory in two calls rather than one `equivalent` per candidate:
    # a first cut asked 4,000 times and never finished.
    t0 = time.time()
    fine = c.classes(level="instances", theorems_only=True)
    coarse = c.classes(level="carriers", theorems_only=True)
    coarse_of: dict[str, int] = {}
    for k, (_sz, mem) in enumerate(coarse):
        for m in mem:
            coarse_of[m] = k
    print(f"  {len(fine)} classes at instances, {len(coarse)} at carriers "
          f"({time.time()-t0:.0f}s)")

    def adjacent(cls: set[str]):
        """`(tier 1, tier 2)` for a class given as a set of names."""
        t1 = []
        for m in (v.idx[x] for x in cls if x in v.idx):
            for k in members.get(v.skel[m], ()):
                if v.name[k] in cls:
                    continue
                subs = sorted({(a, b) for a, b in zip(v.consts[m], v.consts[k]) if a != b})
                t1.append((v.name[m], v.name[k], len(subs),
                           [(v.sym(a), v.sym(b)) for a, b in subs[:4]]))
        t2 = set()
        for x in cls:
            k = coarse_of.get(x)
            if k is not None:
                t2.update(y for y in coarse[k][1] if y not in cls)
        return t1, sorted(t2)

    t1sz, t2sz, nonzero = [], [], 0
    shown = 0
    for _sz, mem in random.sample(fine, min(300, len(fine))):
        t1, t2 = adjacent(set(mem))
        t1sz.append(len(t1))
        t2sz.append(len(t2))
        if t1:
            nonzero += 1
            if shown < 3:
                shown += 1
                print(f"  example  adjacent({mem[0]} ...{len(mem)} members):")
                for m, k, ns, sub in t1[:3]:
                    print(f"    {k}   [{ns} sub] " +
                          ", ".join(f"{a} -> {b}" for a, b in sub))
    print(f"  tier 1 (one substitution away): non-empty for {nonzero}/{len(t1sz)} classes, "
          f"median size {sorted(t1sz)[len(t1sz)//2] if t1sz else 0}, max {max(t1sz or [0])}")
    print(f"  tier 2 (one squint coarser):    median "
          f"{sorted(t2sz)[len(t2sz)//2] if t2sz else 0}, max {max(t2sz or [0])}")

    # --- injection controls ---------------------------------------------------------
    #
    # Sensitivity: build a near miss that is not in the corpus and require the query to
    # find it. Specificity: build a row with exactly the right *vocabulary* and the wrong
    # *structure* and require the query to refuse it. A method that passes only the first
    # is matching on nothing in particular.
    seen_subs = set()
    for _i, _j, a, b in out.get("_pairs", []):
        seen_subs.add((a, b) if a < b else (b, a))

    base_n = len(v.name)
    pos_targets, neg_targets = [], []
    cand = [i for i in v.claims if 3 <= len(v.consts[i]) <= 40]
    random.shuffle(cand)
    skel_by_arity: dict[int, list[bytes]] = collections.defaultdict(list)
    raw_skel: dict[bytes, bytes] = {}
    for i in v.claims[:20000]:
        sk, _cs = split_constants(v.stmt[i])
        h = v.skel[i]
        if h not in raw_skel:
            raw_skel[h] = sk
            skel_by_arity[len(v.consts[i])].append(h)

    for i in cand:
        if len(pos_targets) >= n_probe and len(neg_targets) >= n_probe:
            break
        sk, names = split_constants(v.stmt[i])
        # positive: substitute one constant for another that occurs in the corpus, where
        # that substitution is not already witnessed anywhere.
        if len(pos_targets) < n_probe:
            a = random.choice(names)
            for _try in range(12):
                b = random.choice(v.vocab)
                if b == a:
                    continue
                key = (v.vid(a), v.vid(b))
                key = key if key[0] < key[1] else (key[1], key[0])
                if key in seen_subs:
                    continue
                inj = assemble(sk, [b if x == a else x for x in names])
                pos_targets.append((v.name[i], inj, a.decode(), b.decode()))
                break
        # negative: this declaration's exact vocabulary poured into a *different*
        # skeleton of the same arity.
        if len(neg_targets) < n_probe:
            pool = [h for h in skel_by_arity.get(len(names), ()) if h != v.skel[i]]
            if pool:
                other = raw_skel[random.choice(pool)]
                try:
                    inj = assemble(other, names)
                except ValueError:
                    inj = None
                if inj is not None:
                    neg_targets.append((v.name[i], inj))

    def inject(rows):
        for enc in rows:
            sk, cs = split_constants(enc)
            v.name.append(f"__inj_{len(v.name)}")
            v.kind.append("theorem")
            v.module.append("Injected.Control")
            v.stmt.append(enc)
            v.skel.append(h16(sk))
            v.consts.append(tuple(v.vid(x) for x in cs))
            v.idx[v.name[-1]] = len(v.name) - 1
            v.claims.append(len(v.name) - 1)
            members[v.skel[-1]].append(len(v.name) - 1)

    def tier1(name: str) -> list[tuple[str, list[tuple[str, str]]]]:
        i = v.idx[name]
        got = []
        for k in members.get(v.skel[i], ()):
            if k == i:
                continue
            subs = sorted({(a, b) for a, b in zip(v.consts[i], v.consts[k]) if a != b})
            got.append((v.name[k], [(v.sym(a), v.sym(b)) for a, b in subs]))
        return got

    # Before injection the corpus must not already answer the query, or a hit afterwards
    # would mean nothing. §40's control, in the same shape.
    before_pos = sum(1 for nm, _e, _a, _b in pos_targets
                     if any(x.startswith("__inj_") for x, _s in tier1(nm)))
    inject([e for _n, e, _a, _b in pos_targets])
    pos_hit = pos_right = 0
    for nm, _e, a, b in pos_targets:
        got = [(x, s) for x, s in tier1(nm) if x.startswith("__inj_")]
        if got:
            pos_hit += 1
            if any(s == [(a, b)] for _x, s in got):
                pos_right += 1
    n_pos = len(v.name) - base_n
    inject([e for _n, e in neg_targets])
    neg_hit = sum(1 for nm, _e in neg_targets
                  if any(x.startswith("__inj_") and v.idx[x] >= base_n + n_pos
                         for x, _s in tier1(nm)))
    print(f"  CONTROL sensitivity: near miss found for {pos_hit}/{len(pos_targets)} "
          f"injections, with the exact substitution reported in {pos_right} "
          f"(before injection: {before_pos})")
    print(f"  CONTROL specificity: right vocabulary, wrong structure returned for "
          f"{neg_hit}/{len(neg_targets)}")
    out["m3"] = {"classes_probed": len(t1sz), "tier1_nonempty": nonzero,
                 "inj_pos_exact": pos_right,
                 "tier1_median": sorted(t1sz)[len(t1sz)//2] if t1sz else 0,
                 "tier1_max": max(t1sz or [0]),
                 "tier2_median": sorted(t2sz)[len(t2sz)//2] if t2sz else 0,
                 "inj_pos": len(pos_targets), "inj_pos_found": pos_hit,
                 "inj_pos_before": before_pos,
                 "inj_neg": len(neg_targets), "inj_neg_found": neg_hit}


def m4_proof_shape(v: View, c: atlas.Corpus, out: dict) -> None:
    """M4: the proof-shape index. §46 scored V9 UNRUNNABLE because this does not exist.

    A proof reaches the Atlas only as `uses_proof`, a list of names. But every name in it
    has a statement, and the *rigid skeleton* of that statement is constant-blind — so
    `add_comm` and `mul_comm` key the same. A proof's shape is therefore the multiset of
    the shapes of the facts it invokes: not what it cites, but what *kind* of fact it
    cites, in what proportions.
    """
    print("\n=== M4  proof_shape: indexing arguments, not just claims ===")
    unknown: dict[str, bytes] = {}

    def key_of(u: str) -> bytes:
        i = v.idx.get(u)
        if i is not None:
            return v.skel[i]
        k = unknown.get(u)
        if k is None:
            k = h16(b"?" + u.encode())
            unknown[u] = k
        return k

    cites = v.cites()
    deriv = v.derivative()
    freq: collections.Counter = collections.Counter()
    for u in cites.values():
        freq.update(u)
    pop = list(freq.keys())
    cum = list(itertools.accumulate(freq[k] for k in pop))

    def build(ids, shuffle: bool):
        shapes: dict[tuple, list[int]] = collections.defaultdict(list)
        kept = 0
        for i in ids:
            u = cites[i]
            if len(u) < 2:
                continue
            kept += 1
            if shuffle:
                u = random.choices(pop, cum_weights=cum, k=len(u))
            shapes[tuple(sorted(key_of(x) for x in u))].append(i)
        fams = {k: x for k, x in shapes.items() if len(x) > 1}
        return kept, fams

    # Stratified, because the first unstratified run's five largest families were
    # `sizeOf_spec`, `inj` and `injEq` batches — Lean's output, not anyone's proof.
    for label, ids in (("all claims", v.claims),
                       ("substantive", [i for i in v.claims if i not in deriv])):
        t0 = time.time()
        kept, fams = build(ids, False)
        covered = sum(len(x) for x in fams.values())
        _keptn, fams_n = build(ids, True)
        cov_n = sum(len(x) for x in fams_n.values())
        novel = sum(1 for x in fams.values() if len({v.skel[i] for i in x}) > 1)
        print(f"  [{label}] {kept} claims with >=2 proof citations "
              f"({time.time()-t0:.0f}s)")
        print(f"    exact proof-shape families: {len(fams)} covering {covered} "
              f"({100*covered/max(kept,1):.1f}%)")
        print(f"    CONTROL (citations resampled frequency-matched, same count per "
              f"proof): {len(fams_n)} families covering {cov_n} "
              f"({100*cov_n/max(kept,1):.1f}%)")
        print(f"    families whose members do NOT share a statement skeleton: "
              f"{novel}/{len(fams)} ({100*novel/max(len(fams),1):.1f}%) — the part the "
              f"statement index cannot reach")
        for k, x in sorted(fams.items(), key=lambda kv: -len(kv[1]))[:4]:
            print(f"      [{len(x)} proofs, {len(k)} citations] " +
                  ", ".join(v.name[i] for i in x[:4]))
        out.setdefault("m4", {})[label] = {
            "claims_with_proofs": kept, "families": len(fams), "covered": covered,
            "control_families": len(fams_n), "control_covered": cov_n,
            "families_novel": novel}
    out["m4"]["unknown_cited"] = len(unknown)


def m5_hole(v: View, c: atlas.Corpus, out: dict, probes: int = 60) -> None:
    """M5: `match(pattern)` — retrieval by a partial statement instead of by an example.

    Validated as a **differential against `equivalent`**, which computes the same
    containment by a different algorithm: `Corpus.skeleton(d, L)` is a pattern with `_`
    for every position the erasure removed, so every member of `equivalent(d, L)` must
    match it. A single miss is a false negative in a matcher, and those are the expensive
    kind.
    """
    print("\n=== M5  match: query by hole ===")

    # --- gate A: hole punching is monotone, and a hole-free pattern is exact ----------
    #
    # Property tests rather than pinned outputs. Punching a hole anywhere in a statement
    # must leave a pattern that still matches it; a pattern with no hole must match only
    # its own encoding, which is what a same-skeleton different-constant pair tests hardest.
    t0 = time.time()
    mono_ok = mono_bad = exact_ok = exact_bad = 0
    for i in random.sample(v.claims, 400):
        enc = v.stmt[i]
        sp = expr_spans(enc)
        for s in random.sample(sp, min(6, len(sp))):
            if matches(punch(enc, s), enc):
                mono_ok += 1
            else:
                mono_bad += 1
    bucket_pairs = []
    for _k, ids in v.buckets().items():
        if len(ids) > 1:
            bucket_pairs.append((ids[0], ids[1]))
    for i, j in random.sample(bucket_pairs, min(500, len(bucket_pairs))):
        same = v.stmt[i] == v.stmt[j]
        if matches(v.stmt[i], v.stmt[j]) == same:
            exact_ok += 1
        else:
            exact_bad += 1
    print(f"  GATE A ({time.time()-t0:.0f}s): hole-punch monotonicity {mono_ok} ok / "
          f"{mono_bad} violated; hole-free exactness {exact_ok} ok / {exact_bad} violated")

    # --- gate B: differential against `equivalent`, computed a different way ----------
    #
    # From `presentation` upward the erasure only replaces subterms by holes (erase.rs
    # `erase_binder`/`erase_spine`), so `skeleton(d, carriers)` is a hole pattern over
    # `skeleton(x, presentation)` and every member of `equivalent(d, carriers)` must match
    # it. It is **not** a pattern over the raw statement: at `presentation` the erasure
    # also rewrites — `OfNat.ofNat T k inst` collapses to `k` and `StrictImplicit` merges
    # into `Implicit` — so matching a skeleton against `stmt` reports false misses that
    # are the erasure's rewrites and not the matcher's fault. Measured below, because a
    # reader will otherwise try it.
    ok = miss = raw_ok = raw_miss = 0
    used = 0
    t0 = time.time()
    for nm in random.sample([v.name[i] for i in v.claims], probes * 20):
        if used >= probes:
            break
        try:
            eq = c.equivalent(nm, level="carriers")
        except Exception:
            continue
        if not eq:
            continue
        used += 1
        pat = c.skeleton(nm, level="carriers").encode()
        for m in [nm] + eq:
            if m not in v.idx:
                continue
            if matches(pat, c.skeleton(m, level="presentation").encode()):
                ok += 1
            else:
                miss += 1
            if matches(pat, v.stmt[v.idx[m]]):
                raw_ok += 1
            else:
                raw_miss += 1
    print(f"  GATE B ({time.time()-t0:.0f}s) over {used} patterns: against "
          f"skeleton(.,presentation) {ok} matched / {miss} FALSE NEGATIVES; "
          f"against the raw statement {raw_ok} matched / {raw_miss} missed "
          f"(the erasure's own rewrites, not the matcher's)")

    # --- gate C: a pattern the corpus cannot contain must return nothing --------------
    i = random.choice([k for k in v.claims if len(v.consts[k]) >= 3])
    sk, names = split_constants(v.stmt[i])
    bogus = assemble(sk, [b"__no_such_constant__"] + list(names[1:]))
    hits = sum(1 for k in v.claims if matches(bogus, v.stmt[k]))
    print(f"  GATE C (one slot filled with a constant no declaration holds): {hits} hits")

    # --- what it is for: retrieval by a pattern nothing in the corpus equals ----------
    #
    # `equivalent` answers "same erasure"; `match` answers "an instance of this shape",
    # which is strictly wider and is the question an agent with a half-written statement
    # actually has.
    t0 = time.time()
    pres = [c.skeleton(v.name[k], level="presentation").encode() for k in v.claims]
    build = time.time() - t0
    # Swept over queries rather than shown on one: whether extra holes widen the match set
    # is a property of where the concrete structure sits, so a single example is an anecdote.
    HOLES = (0, 2, 4, 6)
    curves: list[list[int]] = []
    eqns: list[int] = []
    t0 = time.time()
    for k in random.sample(v.claims, 3000):
        if len(curves) >= 20:
            break
        if len(v.consts[k]) < 6:
            continue
        e = c.equivalent(v.name[k], level="carriers")
        if len(e) < 1:
            continue
        base = c.skeleton(v.name[k], level="carriers").encode()
        # Punch only at *concrete* positions: a hole where the erasure already put one
        # widens nothing, so a demonstration that used them would understate the query.
        spans = [s for s in expr_spans(base) if base[s[0]:s[0] + 1] != b"_" and s[0] > 0]
        random.shuffle(spans)
        chosen: list[tuple[int, int]] = []
        for s in spans:
            if all(s[1] <= t[0] or s[0] >= t[1] for t in chosen):
                chosen.append(s)
            if len(chosen) == max(HOLES):
                break
        row = []
        for h in HOLES:
            pat = base
            for s in sorted(chosen[:h], reverse=True):
                pat = punch(pat, s)
            row.append(sum(1 for p in pres if matches(pat, p)))
        curves.append(row)
        eqns.append(len(e) + 1)
    med = [sorted(r[i] for r in curves)[len(curves) // 2] for i in range(len(HOLES))]
    grew = sum(1 for r in curves if r[-1] > r[0])
    print(f"  {len(v.claims)} presentation skeletons in {build:.0f}s; sweep over "
          f"{len(curves)} queries in {time.time()-t0:.0f}s")
    print(f"    median class size from equivalent(carriers): "
          f"{sorted(eqns)[len(eqns)//2] if eqns else 0}")
    print("    median matches by extra holes: " +
          ", ".join(f"+{h}:{m}" for h, m in zip(HOLES, med)) +
          f";  widened for {grew}/{len(curves)} queries")
    out["m5"] = {"mono_ok": mono_ok, "mono_bad": mono_bad,
                 "exact_ok": exact_ok, "exact_bad": exact_bad,
                 "patterns": used, "matched": ok, "false_negatives": miss,
                 "raw_matched": raw_ok, "raw_missed": raw_miss,
                 "bogus_hits": hits, "holes": list(HOLES), "median_matches": med,
                 "widened": grew, "queries": len(curves)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", required=True)
    ap.add_argument("--method", default="all")
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--json", default=None)
    ap.add_argument("--skip-selftest", action="store_true",
                    help="skip the split/assemble round-trip over the whole slice. It is "
                         "the gate on the primitive every method rests on, and it costs a "
                         "second full pass; skip it only on a slice where it has passed.")
    args = ap.parse_args()
    random.seed(args.seed)

    t0 = time.time()
    c = atlas.Corpus.load(args.slice)
    print(f"slice {args.slice}: {len(c)} declarations, loaded in {time.time()-t0:.1f}s")
    kh, uh, cov, _worst = c.closure(3)
    print(f"closure: {cov:.4f} over {kh + uh} application heads")
    if cov < 0.95:
        print("WARNING: closure below 0.95 — erasure-dependent results are not trustworthy")

    t0 = time.time()
    v = View(c)
    print(f"view: {len(v)} declarations parsed, {len(v.claims)} of them theorems, "
          f"{v.no_stmt} without a statement, in {time.time()-t0:.1f}s")

    # The primitive every method rests on, checked against the whole slice rather than a
    # fixture: blanking and refilling must be the identity. A skeleton that lost a byte
    # would merge two families and nothing downstream would say so.
    bad = 0
    if args.skip_selftest:
        print("selftest: SKIPPED by --skip-selftest (only sound on a slice it has passed)")
    else:
        for i in range(len(v)):
            sk, names = split_constants(v.stmt[i])
            if assemble(sk, names) != v.stmt[i]:
                bad += 1
        print(f"selftest: split/assemble round-trips on {len(v)-bad}/{len(v)} statements")
        if bad:
            print("ABORT: the rigid-skeleton primitive is lossy on this slice")
            return 1

    out: dict = {"slice": args.slice, "n": len(c), "claims": len(v.claims),
                 "closure": cov, "roundtrip_failures": bad}
    want = set(args.method.split(","))
    if "all" in want:
        want = {"m1", "m2", "m3", "m4", "m5", "m6"}
    # M1, M2, M4 and M6 read the raw statement encoding and never erase, so they are sound
    # on a slice that is not closed. M3 and M5 go through `equivalent`/`skeleton` and are
    # not — see CLAUDE.md §7 and findings §31.
    if cov < 0.95 and (want & {"m3", "m5"}):
        print("REFUSING m3/m5 on a slice below 95% closure; run them on a closed slice")
        want -= {"m3", "m5"}
    pairs = members = None
    if want & {"m1", "m2", "m3", "m6"}:
        if "m1" in want:
            pairs, members = m1_variants(v, c, out)
        else:
            members = v.buckets()
            pairs = list(subst_pairs(v.skel, v.consts, members))
        out["_pairs"] = pairs
    if "m2" in want:
        m2_substitutions(v, pairs, out)
    if "m6" in want:
        m6_transport_exact(v, pairs, out)
    if "m4" in want:
        m4_proof_shape(v, c, out)
    if "m5" in want:
        m5_hole(v, c, out)
    if "m3" in want:
        # last: it injects synthetic rows into the view
        m3_adjacent(v, c, members, out)

    if args.json:
        with open(args.json, "w") as f:
            json.dump({k: x for k, x in out.items() if not k.startswith("_")}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
