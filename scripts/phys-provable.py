"""Which of physlib's unproved assertions are provable from what is already formalized?

`research/physlib-frontier.md` §1 refutes the premise this study was handed: **physlib
declares no axioms at all** — 0 of 14,563 by the extractor's `kind` field, against 15 in a
Mathlib slice extracted by the same tool. That is re-measured here on a different and
closed corpus rather than inherited (§ stage 1).

So "which asserted physics facts are corollaries of already-proved theorems" has to be
asked of the genres physlib *does* use to assert without proving:

| genre | how it is found | can a proof route even be expressed? |
|---|---|---|
| `axiom` | `kind == "axiom"` | yes — and there are none that are physics |
| `sorry` | `honesty()`, transitively | **yes**: the claim is a formal proposition |
| prose | statement is a single constant whose row is an `inductive` in the library's own `*.Meta.*` subtree | **no**: the row carries no proposition at all |
| orphan def | reachability | not applicable: a definition asserts nothing |

Only the `sorry` genre carries a statement a rewrite can act on, and there are sixteen of
them. That is the sample size, it is small, and every number below says so.

--------------------------------------------------------------------------------
What a proof route is, and the four kinds this looks for
--------------------------------------------------------------------------------

A **route** is a named, checkable claim of the form "this unproved statement follows from
these proved declarations". Four kinds, strongest first:

* **R1 identity** — the target's statement encoding *equals* a proved declaration's.
  Route: `theorem T := D`. This is decided by the corpus alone, so it is a result and not
  a candidate.
* **R2 equivalence** — the target and a proved declaration have the same statement after
  erasure at `exact` / `presentation` / `instances` / `carriers`. Route: "T is D with the
  carrier (or the instance plumbing) swapped." A candidate: erasure equality is not
  provable equality.
* **R3 rewrite** — applying a substitution **the corpus witnesses elsewhere** to the
  target's statement produces exactly a proved declaration's statement. Route: "T is the
  σ-image of proved D; port D's proof along σ." This is `transport_exact`
  (`research/physlib-newqueries.md` §7), which lands 25.1% of physlib rewrites on real
  declarations against a frequency-matched null of 0.0%.
* **R4 adjacency** — the target shares a **rigid skeleton** with a proved declaration and
  differs by k constant substitutions (`Corpus.variants` / `Corpus.adjacent`), or shares
  its class's distinguished vocabulary (`Corpus.vocabulary_adjacent`). The weakest: a
  place to look rather than a route.

Plus **subsumption**, which is the relation the question actually wants and which §8 of
`physlib-newqueries.md` records as *not attempted*: `D` subsumes `T` when `skeleton(D, L)`
one-way matches `skeleton(T, "presentation")`, i.e. T is an instance of D. Attempted here
in the only affordable direction — 16 subjects rather than 4.4 billion pairs — behind a
recall-safe prefilter.

--------------------------------------------------------------------------------
Stated before running: what a good answer looks like, and what a bad one looks like
--------------------------------------------------------------------------------

*Pass.* (a) The planted-provable control is recovered: a synthetic target built by applying
a witnessed substitution to a proved theorem, whose image is a real declaration, gets an R3
route **with the substitution named**, at >= 90%. (b) The planted-decoy control — the same
vocabulary poured into a different tree — gets a route in **0** cases. (c) The
frequency-matched substitution null lands far below the witnessed inventory. (d) The
calibration arm (proved theorems run as pseudo-targets) gives a base rate, so a route found
on a real target can be read against something.

*Fail.* Decoys route at the genuine rate; or the null matches the inventory; or the
calibration arm routes ~100% of proved theorems, in which case a route means only "the
corpus is redundant" and says nothing about the target.

*Refuse.* Below 95% closure the script stops: `skeleton`, `equivalent` at `instances` and
above, `variants` and `adjacent` all degrade **toward output** on an unclosed slice
(CLAUDE.md §7, findings §31), which is the direction that manufactures a route that is not
there.

Nothing here uses a declaration's *name* to decide anything. Targets come from `kind` and
from `honesty`; routes come from statement trees.

Usage:
    uv run --no-sync python scripts/phys-provable.py --slice /tmp/pc-physclosed.jsonl \
        --json /tmp/phys-provable.json
"""

from __future__ import annotations

import argparse
import array
import collections
import gc
import importlib.util
import itertools
import json
import os
import pathlib
import random
import sys
import time

import atlas

# The rigid-skeleton primitive, the one-way matcher and the telescope reader are
# `scripts/phys-newqueries.py`'s and are reused rather than rewritten: two independent
# implementations of `split_constants` would be two places for the blank-then-refill
# identity to break, and that identity is what every route below rests on.
_NQ = pathlib.Path(__file__).with_name("phys-newqueries.py")
_spec = importlib.util.spec_from_file_location("phys_newqueries", _NQ)
nq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nq)

split_constants = nq.split_constants
assemble = nq.assemble
strip_tag = nq.strip_tag
h16 = nq.h16
matches = nq.matches
telescope_heads = nq.telescope_heads
subst_pairs = nq.subst_pairs

KERNEL_AXIOMS = ("propext", "Classical.choice", "Quot.sound", "sorryAx")


def conclusion(enc: bytes) -> tuple[bytes, int]:
    """`(the statement's conclusion as a standalone term, how many binders were dropped)`.

    Anti-unification aligns two terms from their roots, so a claim carrying a hypothesis
    prefix cannot match one without — `atlas.pyi`'s `Anchor` records the measured cost:
    two statements that are literally `S subset {x | P x}` anti-unify to `common 0`. The
    same is true of every exact-structure route here, and the fix is the same: compare what
    the statement *concludes*.

    Not a slice of the encoding: `enc[i:]` after the `Pi` prefix carries one trailing `)`
    per binder and is not a term. The end has to be found by walking it.
    """
    i, n, binders = 0, len(enc), 0
    while i < n and enc[i] == 0x70:                    # 'p' <binder-info> '('
        d = i + 3
        e = nq.skip_expr(enc, d)
        i = e + 1
        binders += 1
    if i >= n:
        return enc, 0
    return enc[i:nq.skip_expr(enc, i)], binders


def now() -> float:
    return time.time()


def rss_mb() -> float:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    except Exception:
        return -1.0


def subfield(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) > 1 else module


# ---------------------------------------------------------------------------
# Stage 2: a memory-lean view
# ---------------------------------------------------------------------------
#
# The slice is 2.4 GB of statement encodings. `phys-newqueries.py`'s `View` keeps every
# statement and every constant list in Python, which is affordable at 146 MB and is not
# here — 95k statements averaging 25 kB is the whole corpus a second time, and the machine
# has 14 GB free with other work on it. What the route search actually needs per
# declaration is four hashes and a 64-bit set signature, so that is what is kept; the
# statements are re-fetched from the corpus for the few thousand declarations that turn out
# to matter.


class LeanView:
    """Per-declaration: statement hash, rigid-skeleton hash, conclusion head, size, and a
    64-bit signature of its constant set.

    The signature exists for a prefilter that can only produce false positives:
    `sig(d) & ~sig(t) == 0` is implied by "every constant of `d` also occurs in `t`", so
    dropping the rest of the corpus cannot lose a subsumer. CLAUDE.md's rule is that false
    negatives are the expensive kind, and a prefilter that is only sound in one direction is
    the only kind admissible here.
    """

    def __init__(self, c: atlas.Corpus, unproved: set[str],
                 progress_every: int = 20000, selftest: bool = True):
        self.c = c
        self.name: list[str] = []
        self.kind: list[str] = []
        self.module: list[str] = []
        self.hstmt: list[bytes] = []
        self.hskel: list[bytes] = []
        self.hconcl: list[bytes] = []       # hash of the conclusion, binders discarded
        self.hcskel: list[bytes] = []       # hash of the conclusion's rigid skeleton
        self.binders = array.array("i")
        self.concl: list[int] = []          # vid of the conclusion's spine head, -1 if none
        self.nslots = array.array("i")
        self.nbytes = array.array("q")
        self.sig = array.array("Q")
        self.idx: dict[str, int] = {}
        self.vocab: list[bytes] = []
        self._vid: dict[bytes, int] = {}
        self.df: collections.Counter = collections.Counter()   # constant -> #declarations
        self.no_stmt: list[str] = []
        self.bad_scan: list[str] = []
        self.concl_bad = 0
        # Accumulated in the same pass rather than in a second one: "does a proved theorem
        # already talk about this constant" costs a full re-scan of 2.4 GB otherwise, and
        # the census that decides `unproved` has already run.
        self.proved_vocab: set[int] = set()

        t0 = now()
        for k, nm in enumerate(c.names()):
            d = c.get(nm)
            s = d.stmt
            if not s:
                self.no_stmt.append(nm)
                continue
            enc = strip_tag(s)
            try:
                sk, cs = split_constants(enc)
                # The gate on the primitive every route rests on, run over the whole slice
                # rather than a fixture: a lossy skeleton merges two families and nothing
                # downstream says so.
                #
                # `selftest=False` exists and buys less than it looks like it should, which
                # is the useful thing to record: measured over the whole 2.4 GB corpus, the
                # view costs 1,363 s with the check and 1,126 s without — 17%. The bulk is
                # `split_constants` and the per-slot `bytes` allocations, not the refill.
                # Keep the gate on.
                if selftest and assemble(sk, cs) != enc:
                    self.bad_scan.append(nm)
                    continue
            except Exception:
                self.bad_scan.append(nm)
                continue
            vids = {self.vid(x) for x in cs}
            sig = 0
            for v in vids:
                sig |= 1 << (v & 63)
            self.df.update(vids)
            if d.kind == "theorem" and nm not in unproved:
                self.proved_vocab |= vids
            try:
                head, _classes = telescope_heads(enc)
            except Exception:
                head = None
            try:
                concl, nb = conclusion(enc)
                # The gate on the extractor: dropping k binders must leave a term that is
                # a suffix of the encoding and shorter than it, and a statement with no
                # binder must be its own conclusion. Counted rather than asserted, so a
                # violation is visible in the report instead of aborting a 2.4 GB pass.
                if (nb == 0 and concl != enc) or len(concl) > len(enc):
                    self.concl_bad += 1
                cskel, _cs2 = split_constants(concl)
                hc, hcs = h16(concl), h16(cskel)
            except Exception:
                self.concl_bad += 1
                concl, nb, hc, hcs = b"", 0, b"", b""
            self.idx[nm] = len(self.name)
            self.name.append(nm)
            self.kind.append(d.kind)
            self.module.append(d.module)
            self.hstmt.append(h16(enc))
            self.hskel.append(h16(sk))
            self.hconcl.append(hc)
            self.hcskel.append(hcs)
            self.binders.append(nb)
            self.concl.append(self.vid(head.encode()) if head else -1)
            self.nslots.append(len(cs))
            self.nbytes.append(len(enc))
            self.sig.append(sig)
            del enc, sk, cs, vids
            if progress_every and (k + 1) % progress_every == 0:
                print(f"    view: {k+1} rows, {now()-t0:.0f}s, rss {rss_mb():.0f} MB",
                      flush=True)
        gc.collect()
        self.claims = [i for i, x in enumerate(self.kind) if x == "theorem"]
        self.by_stmt: dict[bytes, list[int]] = collections.defaultdict(list)
        for i, h in enumerate(self.hstmt):
            self.by_stmt[h].append(i)
        self.by_concl: dict[bytes, list[int]] = collections.defaultdict(list)
        self.by_cskel: dict[bytes, list[int]] = collections.defaultdict(list)
        for i in self.claims:
            if self.hconcl[i]:
                self.by_concl[self.hconcl[i]].append(i)
                self.by_cskel[self.hcskel[i]].append(i)

    def vid(self, name: bytes) -> int:
        v = self._vid.get(name)
        if v is None:
            v = len(self.vocab)
            self._vid[name] = v
            self.vocab.append(name)
        return v

    def sym(self, v: int) -> str:
        return self.vocab[v].decode("utf-8", "replace")

    def stmt(self, i: int) -> bytes:
        """Re-read one statement from the corpus. Deliberately not cached."""
        return strip_tag(self.c.get(self.name[i]).stmt)

    def __len__(self) -> int:
        return len(self.name)


# ---------------------------------------------------------------------------
# Stage 1: the target census, structurally
# ---------------------------------------------------------------------------

def census(c: atlas.Corpus, out: dict) -> dict:
    print("\n=== stage 1  what this corpus asserts without proving ===", flush=True)
    kinds: collections.Counter = collections.Counter()
    axioms: list[tuple[str, str]] = []
    inductive_meta: set[str] = set()
    rows: dict[str, tuple[str, str]] = {}
    for nm in c.names():
        d = c.get(nm)
        kinds[d.kind] += 1
        rows[nm] = (d.kind, d.module)
        if d.kind == "axiom":
            axioms.append((nm, d.module))
        if d.kind == "inductive" and ".Meta." in d.module:
            inductive_meta.add(nm)
    print(f"  kinds: {dict(kinds.most_common())}")
    print(f"  axiom rows: {len(axioms)} -> {axioms}")
    non_kernel = [a for a in axioms if a[0] not in KERNEL_AXIOMS]
    print(f"  axioms that are not one of Lean's four kernel axioms: {len(non_kernel)}")

    # `honesty` with its negative control. The empty whitelist allows nothing and must
    # therefore be strictly louder; findings §3 of physlib-frontier.md records it going
    # silent on an *unclosed* slice, which is exactly the failure a closed one should not
    # reproduce.
    t0 = now()
    findings = c.honesty()
    strict = c.honesty([])
    print(f"  honesty(default): {len(findings)} findings; honesty([]): {len(strict)} "
          f"({now()-t0:.0f}s)")
    if len(strict) <= len(findings):
        print("  WARNING: the honesty negative control did not fire on this slice")
    unproved = sorted({w for w, _why in findings})
    why = dict(findings)
    print(f"  declarations resting on an unproved leaf: {len(unproved)}")
    for w in unproved:
        k, m = rows.get(w, ("?", "?"))
        print(f"    {k:8s} {w}   [{m}]  <- {why[w]}")

    # The prose genre, found the way physlib-frontier.md §5 found it: a declaration whose
    # *type* is a marker inductive living in the library's own metaprogramming subtree.
    # Structural — the marker set comes from `kind` and `module`, never from a name pattern.
    prose: list[tuple[str, str, str]] = []
    for nm in c.names():
        d = c.get(nm)
        us = d.uses_statement
        if len(us) == 1 and us[0] in inductive_meta and ".Meta." not in d.module:
            prose.append((nm, d.module, us[0]))
    by_marker = collections.Counter(m for _n, _mod, m in prose)
    by_sub = collections.Counter(subfield(mod) for _n, mod, _m in prose)
    print(f"  prose claims (type is a marker inductive from the library's Meta subtree): "
          f"{len(prose)}")
    print(f"    markers: {dict(by_marker)}")
    print(f"    by subfield: {by_sub.most_common()}")

    out["census"] = {
        "kinds": dict(kinds), "axioms": axioms, "non_kernel_axioms": non_kernel,
        "honesty": len(findings), "honesty_empty_whitelist": len(strict),
        "unproved": [[w, rows.get(w, ("?", "?"))[0], rows.get(w, ("?", "?"))[1], why[w]]
                     for w in unproved],
        "prose": len(prose), "prose_by_marker": dict(by_marker),
        "prose_by_subfield": dict(by_sub),
        "prose_examples": prose[:12],
    }
    return {"unproved": unproved, "rows": rows, "prose": prose}


# ---------------------------------------------------------------------------
# Stage 3: the witnessed substitution inventory, bucket by bucket
# ---------------------------------------------------------------------------

def inventory(v: LeanView, out: dict, max_bucket: int = 400) -> dict:
    """Every substitution the corpus witnesses, learned one rigid-skeleton bucket at a time.

    Memory-bounded on purpose: the constant lists of a whole 2.4 GB corpus do not fit, and
    a bucket does. Buckets above `max_bucket` are counted and skipped rather than dropped
    silently — a skipped bucket is a false negative and those are the expensive kind.
    """
    print("\n=== stage 3  the witnessed substitution inventory ===", flush=True)
    buckets: dict[bytes, list[int]] = collections.defaultdict(list)
    for i in v.claims:
        buckets[v.hskel[i]].append(i)
    multi = {k: x for k, x in buckets.items() if len(x) > 1}
    print(f"  {len(buckets)} rigid skeletons over {len(v.claims)} claims; "
          f"{len(multi)} shared, covering {sum(len(x) for x in multi.values())} claims")
    if buckets:
        print(f"  largest bucket: {max(len(x) for x in buckets.values())}")

    wit: dict[tuple[int, int], set[bytes]] = collections.defaultdict(set)
    examples: dict[tuple[int, int], list[tuple[str, str]]] = collections.defaultdict(list)
    # The cross-library reach, computed here because the constant lists are already in
    # hand: for a physics claim, the fewest substitutions separating it from a *mathematics*
    # claim with the same rigid skeleton. "Asserted here, proved there" with the two
    # libraries named.
    cross: dict[int, tuple[int, str]] = {}
    pairs_n = skipped = 0
    t0 = now()
    for key, ids in multi.items():
        if len(ids) > max_bucket:
            skipped += 1
            continue
        consts: dict[int, tuple[int, ...]] = {}
        ok = []
        for i in ids:
            try:
                _sk, cs = split_constants(v.stmt(i))
            except Exception:
                continue
            consts[i] = tuple(v.vid(x) for x in cs)
            ok.append(i)
        if len(ok) < 2:
            continue
        phys = [i for i in ok if v.module[i].split(".")[0] in ("Physlib", "QuantumInfo")]
        math = [i for i in ok if v.module[i].split(".")[0] not in
                ("Physlib", "QuantumInfo")]
        for i in phys:
            best = None
            for j in math:
                if len(consts[j]) != len(consts[i]):
                    continue
                d = len({(a, b) for a, b in zip(consts[i], consts[j]) if a != b})
                if best is None or d < best[0]:
                    best = (d, v.name[j])
            if best is not None:
                cross[i] = best
        # `subst_pairs` indexes by (skeleton, constant-list with one constant masked); the
        # whole bucket shares a skeleton, so a per-bucket call is the same computation.
        local_skel = {i: key for i in ok}
        for i, j, a, b in subst_pairs(local_skel, consts, {key: ok}):
            pairs_n += 1
            k = (a, b) if a < b else (b, a)
            wit[k].add(key)
            if len(examples[k]) < 3:
                examples[k].append((v.name[i], v.name[j]))
        del consts
    print(f"  k=1 uniform-substitution pairs: {pairs_n} ({now()-t0:.0f}s, "
          f"{skipped} buckets over {max_bucket} skipped)")
    print(f"  distinct substitutions witnessed: {len(wit)}")
    ranked = sorted(wit.items(), key=lambda kv: -len(kv[1]))
    for (a, b), s in ranked[:15]:
        print(f"    {len(s):4d}  {v.sym(a):46s} <-> {v.sym(b)}")

    out["inventory"] = {
        "skeletons": len(buckets), "shared": len(multi), "pairs": pairs_n,
        "skipped_buckets": skipped, "distinct": len(wit),
        "top": [[v.sym(a), v.sym(b), len(s)] for (a, b), s in ranked[:40]],
    }
    return {"wit": wit, "examples": examples, "buckets": buckets, "cross": cross}


def cross_library(v: LeanView, cross: dict[int, tuple[int, str]], out: dict, rng,
                  trials: int = 1000) -> None:
    """How much of the physics library is a mathematics claim with the vocabulary swapped?

    Every physics claim sharing a rigid skeleton with a mathematics claim is a place where
    the same tree is stated in both libraries; the substitution count says how far apart
    they are. This is the "asserted here, proved there" question with the two sides named,
    and it is the one arm of this study with a sample size worth stratifying.

    The control is a **label permutation**: "subfield X reaches mathematics most often" is
    worth nothing if it only means "X is the biggest subfield", so the reach label is
    permuted across physics claims and the spread of per-subfield rates re-measured. This
    is the control physlib-frontier.md §4 used for the orphan concentration, in the same
    shape, because the same confound is available here.
    """
    print("\n=== stage 7  cross-library reach, stratified ===", flush=True)
    phys = [i for i in v.claims
            if v.module[i].split(".")[0] in ("Physlib", "QuantumInfo")]
    if not phys:
        print("  no physics claims in this slice")
        return
    reach = {i for i in phys if i in cross}
    print(f"  physics claims: {len(phys)}; sharing a rigid skeleton with a mathematics "
          f"claim: {len(reach)} ({100*len(reach)/len(phys):.2f}%)")
    hist = collections.Counter(cross[i][0] for i in reach)
    print("  by substitution distance: " +
          ", ".join(f"k={k}:{n}" for k, n in sorted(hist.items())[:10]))
    k01 = [i for i in reach if cross[i][0] <= 1]
    print(f"  at distance <= 1 (a proved mathematics statement with at most one constant "
          f"swapped): {len(k01)}")
    for i in sorted(k01, key=lambda i: cross[i][0])[:12]:
        print(f"    {v.name[i]:60s} k={cross[i][0]}  <- {cross[i][1]}")

    sub_tot: collections.Counter = collections.Counter()
    sub_hit: collections.Counter = collections.Counter()
    for i in phys:
        s = subfield(v.module[i])
        sub_tot[s] += 1
        if i in reach:
            sub_hit[s] += 1
    rows = [(s, sub_hit[s], n, sub_hit[s] / n) for s, n in sub_tot.items() if n >= 20]
    rows.sort(key=lambda r: -r[3])
    print("  by subfield (>=20 claims):")
    for s, h, n, rate in rows[:16]:
        print(f"    {s:34s} {h:5d} / {n:6d}  {100*rate:6.2f}%")

    def spread(labels: list[bool]) -> float:
        t: collections.Counter = collections.Counter()
        h: collections.Counter = collections.Counter()
        for i, lab in zip(phys, labels):
            s = subfield(v.module[i])
            t[s] += 1
            h[s] += int(lab)
        vals = [h[s] / t[s] for s in t if t[s] >= 20]
        if len(vals) < 2:
            return 0.0
        m = sum(vals) / len(vals)
        return (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5

    labels = [i in reach for i in phys]
    obs = spread(labels)
    nulls = []
    for _ in range(trials):
        perm = labels[:]
        rng.shuffle(perm)
        nulls.append(spread(perm))
    nulls.sort()
    p95 = nulls[int(0.95 * len(nulls))]
    print(f"  CONTROL (reach label permuted across physics claims, {trials} shuffles): "
          f"observed spread {obs:.4f}, permuted 95th pct {p95:.4f} -> "
          f"{'structured' if obs > p95 else 'NOT distinguishable from chance'}")
    out["cross_library"] = {
        "physics_claims": len(phys), "reaching": len(reach),
        "distance_hist": dict(sorted(hist.items())),
        "at_k_le_1": [[v.name[i], cross[i][0], cross[i][1]] for i in k01],
        "by_subfield": [[s, h, n, rate] for s, h, n, rate in rows],
        "spread_observed": obs, "spread_null_p95": p95,
    }


# ---------------------------------------------------------------------------
# Stage 4: the route search
# ---------------------------------------------------------------------------

class Router:
    def __init__(self, v: LeanView, c: atlas.Corpus, wit, unproved: set[str],
                 min_witnesses: int = 1):
        self.v = v
        self.c = c
        self.unproved = unproved
        # `min_witnesses` defaults to 1 because the measured sweep in
        # research/physlib-newqueries.md §3 loses recall monotonically as it rises while the
        # frequency-matched null stays at exactly zero: the floor costs candidates and buys
        # nothing.
        self.subs: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
        for (a, b), s in wit.items():
            if len(s) >= min_witnesses:
                self.subs[a].append((a, b))
                self.subs[b].append((b, a))
        self.wit = wit

    def proved(self, i: int) -> bool:
        return self.v.kind[i] == "theorem" and self.v.name[i] not in self.unproved

    def r1_identity(self, i: int) -> list[str]:
        return [self.v.name[j] for j in self.v.by_stmt.get(self.v.hstmt[i], ())
                if j != i and self.proved(j)]

    def r3_rewrite(self, i: int, enc: bytes,
                   max_bytes: int = 2_000_000) -> tuple[list[dict], int]:
        """Rewrite the target by every witnessed substitution it can take; report the
        images that are already declarations.

        Both directions of every substitution are tried: the inventory is symmetric and
        which side the target sits on is not known in advance.
        """
        if len(enc) > max_bytes:
            return [], 0
        sk, names = split_constants(enc)
        held = {self.v.vid(x) for x in names}
        got: list[dict] = []
        # Counted, not inferred. findings §20's trap is a control arm that reported zero
        # because it never ran; "0 images exist" and "0 rewrites attempted" are different
        # answers and only one of them is a result.
        tried = 0
        for src in held:
            for (a, b) in self.subs.get(src, ()):
                if a != src:
                    continue
                tried += 1
                bn = self.v.vocab[b]
                an = self.v.vocab[a]
                img = assemble(sk, [bn if x == an else x for x in names])
                for j in self.v.by_stmt.get(h16(img), ()):
                    if j == i:
                        continue
                    got.append({"image": self.v.name[j], "kind": self.v.kind[j],
                                "module": self.v.module[j],
                                "proved": self.proved(j),
                                "sub": [self.v.sym(a), self.v.sym(b)],
                                "witnesses": len(self.wit.get((a, b) if a < b else (b, a),
                                                              ()))})
        return got, tried

    def r5_conclusion(self, i: int, enc: bytes, top: int = 12) -> dict:
        """Proved theorems concluding the *same thing*, hypotheses discarded.

        Two tiers. `identical` is exact equality of the conclusion encoding: a proved
        theorem states this very conclusion, so the only question left is whether its
        hypotheses are available — which is a route with one thing to check. `same_tree` is
        equality of the conclusion's rigid skeleton with the differing constants named:
        the same conclusion about different objects.

        This is the arm that can fire when every root-anchored one is silent, and the
        reason it is separate is that the two are different claims: "concludes the same"
        does not imply "is the same theorem".
        """
        v = self.v
        if not v.hconcl[i]:
            return {}
        ident = [v.name[j] for j in v.by_concl.get(v.hconcl[i], ())
                 if j != i and self.proved(j)]
        same: list[dict] = []
        mates = [j for j in v.by_cskel.get(v.hcskel[i], ())
                 if j != i and self.proved(j)]
        if mates and len(enc) < 2_000_000:
            concl, _nb = conclusion(enc)
            _sk, mine = split_constants(concl)
            for j in mates[:200]:
                try:
                    cj, _nb2 = conclusion(v.stmt(j))
                    _sk2, theirs = split_constants(cj)
                except Exception:
                    continue
                if len(theirs) != len(mine):
                    continue
                subs = sorted({(a.decode("utf-8", "replace"), b.decode("utf-8", "replace"))
                               for a, b in zip(mine, theirs) if a != b})
                same.append({"name": v.name[j], "module": v.module[j],
                             "subs": subs[:6], "n_subs": len(subs)})
            same.sort(key=lambda x: x["n_subs"])
        return {"identical": ident[:top], "identical_n": len(ident),
                "same_tree": same[:top], "same_tree_n": len(mates)}

    def r3_null(self, i: int, enc: bytes, pop, cum, rng, max_bytes: int = 2_000_000):
        """The same rewrite count with a frequency-matched random right-hand side."""
        if len(enc) > max_bytes:
            return 0, 0
        sk, names = split_constants(enc)
        held = {self.v.vid(x) for x in names}
        hit = tried = 0
        for src in held:
            for (a, _b) in self.subs.get(src, ()):
                if a != src:
                    continue
                b2 = rng.choices(pop, cum_weights=cum, k=1)[0]
                if b2 == a:
                    continue
                tried += 1
                an, bn = self.v.vocab[a], self.v.vocab[b2]
                img = assemble(sk, [bn if x == an else x for x in names])
                for j in self.v.by_stmt.get(h16(img), ()):
                    if j != i:
                        hit += 1
                        break
        return hit, tried

    def r2_equivalence(self, name: str) -> dict:
        got: dict[str, list[str]] = {}
        for lvl in ("exact", "presentation", "instances", "carriers"):
            try:
                members = self.c.equivalent(name, level=lvl)
            except Exception as e:
                got[lvl] = [f"<{type(e).__name__}>"]
                continue
            got[lvl] = [m for m in members
                        if m in self.v.idx and self.proved(self.v.idx[m])]
        return got

    def subsumers(self, i: int, budget: int = 2000, level: str = "carriers",
                  max_bytes: int = 1_000_000) -> list[str]:
        """Proved declarations that **subsume** the target: `skeleton(D, level)` one-way
        matches `skeleton(T, "presentation")`, i.e. the target is an instance of D.

        The prefilter is `sig(D) & ~sig(T) == 0`, which is implied by "every constant of D
        occurs in T" and therefore admits every real subsumer plus some coincidences. The
        conclusion head must agree exactly, which is the same argument one level up.

        A pattern must be matched against `skeleton(x, "presentation")` and never against
        the raw statement: from `presentation` upward the erasure *rewrites*
        (`OfNat.ofNat T k inst -> k`, `StrictImplicit -> Implicit`), so a raw match reports
        false misses that are the erasure's and look exactly like a matcher bug
        (findings §51).
        """
        v = self.v
        if v.nbytes[i] > max_bytes:
            return [f"<skipped: subject is {int(v.nbytes[i])} bytes>"]
        try:
            subject = self.c.skeleton(v.name[i], level="presentation").encode()
        except Exception:
            return []
        want, sig, head = v.nslots[i], v.sig[i], v.concl[i]
        cands = [j for j in v.claims
                 if j != i and v.concl[j] == head and v.nslots[j] <= want
                 and (v.sig[j] & ~sig) == 0 and self.proved(j)
                 and v.nbytes[j] <= max_bytes]
        cands.sort(key=lambda j: -v.nslots[j])
        capped = len(cands) > budget
        out = []
        for j in cands[:budget]:
            try:
                pat = self.c.skeleton(v.name[j], level=level).encode()
            except Exception:
                continue
            if matches(pat, subject):
                out.append(v.name[j])
        return out if not capped else out + [f"<budget {budget} of {len(cands)}>"]


def route_report(r: Router, v: LeanView, name: str, deep: bool, rng,
                 pop, cum) -> dict:
    i = v.idx.get(name)
    if i is None:
        return {"name": name, "in_slice": False}
    enc = v.stmt(i)
    rep: dict = {
        "name": name, "kind": v.kind[i], "module": v.module[i],
        "subfield": subfield(v.module[i]), "bytes": int(v.nbytes[i]),
        "slots": int(v.nslots[i]),
        "conclusion_head": v.sym(v.concl[i]) if v.concl[i] >= 0 else None,
    }
    rep["binders"] = int(v.binders[i])
    rep["R1_identity"] = r.r1_identity(i)
    rep["R5_conclusion"] = r.r5_conclusion(i, enc)
    rep["R3_rewrite"], rep["R3_tried"] = r.r3_rewrite(i, enc)
    nh, nt = r.r3_null(i, enc, pop, cum, rng)
    rep["R3_null"] = {"hits": nh, "tried": nt}
    if deep:
        rep["R2_equivalence"] = r.r2_equivalence(name)
        for q, kw in (("variants", {"max_subs": 3, "top": 40}),
                      ("adjacent", {"level": "instances", "max_subs": 3, "top": 40}),
                      ("vocabulary_adjacent", {"level": "instances", "top": 25})):
            try:
                rep[q] = getattr(r.c, q)(name, **kw)
            except Exception as e:
                rep[q] = f"<{type(e).__name__}: {e}>"
        try:
            rep["requires"] = r.c.requires(name)
        except Exception as e:
            rep["requires"] = f"<{type(e).__name__}>"
        try:
            rep["subsumers"] = r.subsumers(i)
        except Exception as e:
            rep["subsumers"] = [f"<{type(e).__name__}: {e}>"]
        # The shipped retrieval surface, reported beside the exact-structure routes so the
        # reader can see whether it reaches these declarations at all. Both anchors: a
        # target carrying a hypothesis prefix cannot root-match one without, and
        # `conclusion` is the setting cross-theory analogy needs (`atlas.pyi`, Anchor).
        for tag, anchor in (("similar_root", "root"), ("similar_concl", "conclusion")):
            try:
                ns = r.c.similar(name, top=8, level="carriers", theorems_only=True,
                                 min_retention=0.0, min_common=3, anchor=anchor)
                rep[tag] = [[n.name, round(n.retention, 3), n.common,
                             r.proved(v.idx[n.name]) if n.name in v.idx else None]
                            for n in ns]
            except Exception as e:
                rep[tag] = f"<{type(e).__name__}>"
        try:
            rep["impact"] = len(r.c.impact(name))
        except Exception:
            rep["impact"] = None
    # Direction 2 of the brief: vocabulary already in use by proved theorems is a
    # structurally better prospect than vocabulary the corpus has never proved anything
    # about.
    _sk, names = split_constants(enc)
    held = {v.vid(x) for x in names}
    rep["distinct_constants"] = len(held)
    rep["vocab_in_proved"] = sum(1 for x in held if x in r.proved_vocab)
    rep["vocab_coverage"] = (rep["vocab_in_proved"] / len(held)) if held else 0.0
    rare = sorted(held, key=lambda x: v.df[x])[:6]
    rep["rarest_constants"] = [[v.sym(x), int(v.df[x])] for x in rare]
    del enc
    return rep


# ---------------------------------------------------------------------------
# Stage 5: the distance to the proved frontier
# ---------------------------------------------------------------------------

def frontier_distance(v: LeanView, buckets, unproved: set[str], targets: list[str],
                      out: dict, rng, max_bucket: int = 400) -> None:
    """`d(x)` = the fewest distinct constant substitutions separating `x` from a **proved**
    declaration sharing its rigid skeleton; undefined when no proved declaration does.

    Reported as a distribution against a size-matched proved control rather than as a
    number per target, because "how far is this from what is proved" is only interpretable
    against how far a proved thing is.
    """
    print("\n=== stage 5  distance to the proved frontier ===", flush=True)
    want = {v.idx[t] for t in targets if t in v.idx}
    # A size-matched control: for each target, proved claims within +-20% of its statement
    # size. Matched because statement size is the one feature that separates physics from
    # mathematics (findings §50, §53) and would otherwise be the whole result.
    proved = [i for i in v.claims if v.name[i] not in unproved]
    by_size = sorted(proved, key=lambda i: v.nbytes[i])
    sizes = [v.nbytes[i] for i in by_size]
    import bisect
    control: list[int] = []
    for t in want:
        lo = bisect.bisect_left(sizes, int(v.nbytes[t] * 0.8))
        hi = bisect.bisect_right(sizes, int(v.nbytes[t] * 1.2))
        pool = by_size[lo:hi]
        if pool:
            control.extend(rng.sample(pool, min(25, len(pool))))
    control = list(dict.fromkeys(control))
    print(f"  {len(want)} targets, {len(control)} size-matched proved controls")

    def dist(ids: set[int]) -> dict[int, tuple[int, str] | None]:
        res: dict[int, tuple[int, str] | None] = {i: None for i in ids}
        by_bucket: dict[bytes, list[int]] = collections.defaultdict(list)
        for i in ids:
            by_bucket[v.hskel[i]].append(i)
        for key, mine in by_bucket.items():
            mates = [j for j in buckets.get(key, ()) if j not in ids
                     and v.name[j] not in unproved and v.kind[j] == "theorem"]
            if not mates or len(mates) > max_bucket:
                continue
            cons: dict[int, tuple[int, ...]] = {}
            for j in mine + mates:
                try:
                    _sk, cs = split_constants(v.stmt(j))
                except Exception:
                    continue
                cons[j] = tuple(v.vid(x) for x in cs)
            for i in mine:
                if i not in cons:
                    continue
                best = None
                for j in mates:
                    if j not in cons or len(cons[j]) != len(cons[i]):
                        continue
                    subs = {(a, b) for a, b in zip(cons[i], cons[j]) if a != b}
                    if best is None or len(subs) < best[0]:
                        best = (len(subs), v.name[j])
                res[i] = best
        return res

    dt = dist(want)
    dc = dist(set(control))
    reach_t = [x for x in dt.values() if x is not None]
    reach_c = [x for x in dc.values() if x is not None]
    print(f"  targets reaching a proved bucket-mate: {len(reach_t)}/{len(dt)}")
    print(f"  controls reaching one:                 {len(reach_c)}/{len(dc)}")
    if reach_t:
        print("  target distances: " +
              ", ".join(f"{v.name[i]}={x[0]}" for i, x in dt.items() if x))
    out["frontier_distance"] = {
        "targets": len(dt), "targets_reaching": len(reach_t),
        "controls": len(dc), "controls_reaching": len(reach_c),
        "target_rows": [[v.name[i], (x[0] if x else None), (x[1] if x else None)]
                        for i, x in dt.items()],
        "control_distances": sorted(x[0] for x in reach_c),
    }


# ---------------------------------------------------------------------------
# Stage 6: the controls that can fail
# ---------------------------------------------------------------------------

def vocabulary_novelty(v: LeanView, unproved: set[str], out: dict, rng) -> None:
    """Is an unproved claim the **first thing said** about its own vocabulary?

    Every route in §1 needs a structural neighbour, and the reason the targets have none may
    be simpler than "the analogy is not there": if a claim's rarest constant occurs in two
    declarations in a 95,268-row corpus, there is nothing for it to be a corollary *of*.

    The measure is `min over the claim's constants of document frequency` — one number,
    always defined, computed from the same `df` table the null draws from. Reported as a
    percentile against **every** proved claim rather than against a hand-picked control,
    because the whole point is where the targets sit in the corpus-wide distribution, and
    with 16 positives a rank statistic is the only thing 16 can support.
    """
    print("\n=== stage 8  is an unproved claim the first thing said about its own "
          "vocabulary? ===", flush=True)
    mins: dict[int, int] = {}
    for i in v.claims:
        if v.nbytes[i] > 2_000_000:
            continue
        try:
            _sk, cs = split_constants(v.stmt(i))
        except Exception:
            continue
        if not cs:
            continue
        mins[i] = min(v.df[v.vid(x)] for x in set(cs))
    proved = sorted(m for i, m in mins.items() if v.name[i] not in unproved)
    if not proved:
        print("  no proved claims measurable")
        return
    import bisect
    rows = []
    for i, m in sorted(mins.items(), key=lambda kv: kv[0]):
        if v.name[i] not in unproved:
            continue
        pct = 100.0 * bisect.bisect_left(proved, m) / len(proved)
        rows.append((v.name[i], m, pct))
    med = proved[len(proved) // 2]
    q1 = proved[len(proved) // 4]
    print(f"  proved claims measured: {len(proved)}; rarest-constant document frequency "
          f"quartile 1 = {q1}, median = {med}")
    print("  targets:")
    for nm, m, pct in sorted(rows, key=lambda r: r[1]):
        print(f"    {nm:66s} rarest df {m:6d}   percentile {pct:5.1f}")
    if rows:
        below = sum(1 for _n, _m, p in rows if p <= 25.0)
        print(f"  targets in the bottom quartile of the proved distribution: "
              f"{below}/{len(rows)}")
        # Under the null "a target is an ordinary claim", each percentile is uniform on
        # [0,100], so the count at or below 25 is Binomial(n, 0.25). Reported rather than
        # thresholded.
        out["vocabulary_novelty"] = {
            "proved_measured": len(proved), "q1": q1, "median": med,
            "targets": [[n, m, p] for n, m, p in rows], "in_bottom_quartile": below,
        }


def controls(r: Router, v: LeanView, out: dict, rng, pop, cum, n: int = 60) -> None:
    """Three arms, each able to fail.

    *Planted provable.* Take a proved theorem whose statement admits a witnessed
    substitution landing on another real declaration; hand the **image** to the router as
    if it were an unproved target. The route must come back with the substitution named.
    A router that cannot recover a route it built itself cannot be trusted on a real one.

    *Planted decoy.* The same declaration's exact vocabulary poured into a *different*
    rigid skeleton of the same arity. Same constants, wrong tree. A method keyed on a bag
    of constants passes the first arm and fails this one.

    *Calibration.* Proved theorems run unmodified as pseudo-targets. This is the base rate
    a route on a real target has to be read against: if every proved theorem has a route,
    a route means the corpus is redundant and nothing about the target.
    """
    print("\n=== stage 6  controls ===", flush=True)

    # --- planted provable ----------------------------------------------------------
    pool = [i for i in v.claims if r.proved(i) and 3 <= v.nslots[i] <= 400
            and v.nbytes[i] < 200_000]
    rng.shuffle(pool)
    planted = 0
    recovered = 0
    named = 0
    for i in pool:
        if planted >= n:
            break
        enc = v.stmt(i)
        sk, names = split_constants(enc)
        held = [v.vid(x) for x in set(names)]
        rng.shuffle(held)
        made = False
        for src in held:
            for (a, b) in r.subs.get(src, ())[:8]:
                if a != src:
                    continue
                img = assemble(sk, [v.vocab[b] if x == v.vocab[a] else x for x in names])
                if h16(img) == v.hstmt[i]:
                    continue
                js = [j for j in v.by_stmt.get(h16(img), ()) if j != i]
                if not js:
                    continue
                # The plant: the image is a real declaration, so the *pre*-image is a
                # provable statement whose route is "apply (b -> a) and cite `js[0]`".
                planted += 1
                got, _tr = r.r3_rewrite(js[0], v.stmt(js[0]))
                if any(g["image"] == v.name[i] for g in got):
                    recovered += 1
                    if any(g["image"] == v.name[i]
                           and set(g["sub"]) == {v.sym(a), v.sym(b)} for g in got):
                        named += 1
                made = True
                break
            if made:
                break
        del enc
    print(f"  PLANTED PROVABLE: {planted} plants, route recovered {recovered} "
          f"({100*recovered/max(planted,1):.1f}%), with the substitution named {named}")

    # --- planted decoy -------------------------------------------------------------
    #
    # Built and matched entirely in this process: the decoy must not be added to the
    # corpus (the engine's indexes are Rust-side and immutable here), so it is routed by
    # the same R1/R3 code paths against the same statement-hash table.
    skel_by_arity: dict[int, list[bytes]] = collections.defaultdict(list)
    seen: set[bytes] = set()
    for i in rng.sample(v.claims, min(6000, len(v.claims))):
        if v.nbytes[i] > 100_000 or v.hskel[i] in seen:
            continue
        seen.add(v.hskel[i])
        try:
            sk, _cs = split_constants(v.stmt(i))
        except Exception:
            continue
        skel_by_arity[int(v.nslots[i])].append(sk)
    decoys = decoy_routed = 0
    for i in pool[:4000]:
        if decoys >= n:
            break
        if v.nbytes[i] > 100_000:
            continue
        try:
            _sk, names = split_constants(v.stmt(i))
        except Exception:
            continue
        alts = skel_by_arity.get(len(names), ())
        if not alts:
            continue
        other = rng.choice(alts)
        try:
            enc = assemble(other, names)
        except ValueError:
            continue
        if h16(enc) in v.by_stmt:
            continue                       # not a decoy: the corpus already states it
        decoys += 1
        hit = bool(v.by_stmt.get(h16(enc)))
        if not hit:
            sk2, nm2 = split_constants(enc)
            for src in {v.vid(x) for x in nm2}:
                for (a, b) in r.subs.get(src, ()):
                    if a != src:
                        continue
                    img = assemble(sk2, [v.vocab[b] if x == v.vocab[a] else x
                                         for x in nm2])
                    if v.by_stmt.get(h16(img)):
                        hit = True
                        break
                if hit:
                    break
        decoy_routed += int(hit)
    print(f"  PLANTED DECOY (right vocabulary, wrong tree): {decoys} decoys, "
          f"routed {decoy_routed}")

    # --- calibration ---------------------------------------------------------------
    cal = rng.sample(pool, min(120, len(pool)))
    r1 = r3 = r5 = 0
    nullhit = nulltried = 0
    for i in cal:
        enc = v.stmt(i)
        if v.by_stmt.get(v.hstmt[i], []) != [i]:
            r1 += 1
        if len([j for j in v.by_concl.get(v.hconcl[i], ()) if j != i]) > 0:
            r5 += 1
        got, _tr = r.r3_rewrite(i, enc)
        r3 += int(bool(got))
        nh, nt = r.r3_null(i, enc, pop, cum, rng)
        nullhit += nh
        nulltried += nt
        del enc
    print(f"  CALIBRATION over {len(cal)} proved theorems: R1 identity {r1} "
          f"({100*r1/max(len(cal),1):.1f}%), R3 rewrite lands {r3} "
          f"({100*r3/max(len(cal),1):.1f}%), R5 same conclusion {r5} "
          f"({100*r5/max(len(cal),1):.1f}%)")
    print(f"  CONTROL frequency-matched right-hand side over the same subjects: "
          f"{nullhit}/{nulltried} rewrites land "
          f"({100*nullhit/max(nulltried,1):.2f}%)")
    out["controls"] = {
        "planted": planted, "planted_recovered": recovered, "planted_named": named,
        "decoys": decoys, "decoys_routed": decoy_routed,
        "calibration_n": len(cal), "calibration_r1": r1, "calibration_r3": r3,
        "calibration_r5": r5,
        "null_hits": nullhit, "null_tried": nulltried,
    }


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--min-closure", type=float, default=0.95)
    ap.add_argument("--no-deep", action="store_true",
                    help="skip the engine index queries (equivalent/variants/adjacent). "
                         "They build Rust-side indexes over the whole slice and are the "
                         "part most likely to exhaust memory on a 2.4 GB corpus.")
    ap.add_argument("--deep-only", action="store_true",
                    help="run only the census and the engine-index half of the route "
                         "search. Paired with a `--no-deep` run so that an out-of-memory "
                         "death in the Rust index cannot take the rest of the study with "
                         "it: on a 2.4 GB slice the arena is the largest allocation in "
                         "the process and it is built lazily by the first query that "
                         "needs it.")
    ap.add_argument("--skip-selftest", action="store_true",
                    help="skip the blank-then-refill identity check over the whole slice. "
                         "Only sound on a slice where it has already passed.")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out: dict = {"slice": args.slice, "seed": args.seed}

    def dump():
        if args.json:
            with open(args.json, "w") as f:
                json.dump(out, f, indent=1, default=str)

    t0 = now()
    c = atlas.Corpus.load(args.slice)
    print(f"slice {args.slice}: {len(c)} declarations, loaded in {now()-t0:.1f}s, "
          f"rss {rss_mb():.0f} MB", flush=True)
    t0 = now()
    kh, uh, cov, worst = c.closure(5)
    print(f"closure: {cov:.4f} over {kh+uh} application heads ({now()-t0:.0f}s); "
          f"worst missing {worst}", flush=True)
    out["n"] = len(c)
    out["closure"] = cov
    if cov < args.min_closure:
        print(f"REFUSING: closure {cov:.4f} below {args.min_closure}. Every route kind "
              f"below either erases or looks a constant up, and both degrade toward "
              f"output on an unclosed slice.")
        dump()
        return 1

    cen = census(c, out)
    dump()
    unproved = set(cen["unproved"])

    print("\n=== stage 2  building the lean view ===", flush=True)
    t0 = now()
    v = LeanView(c, unproved, selftest=not args.skip_selftest)
    print(f"  {len(v)} declarations, {len(v.claims)} claims, "
          f"{len(v.no_stmt)} without a statement, "
          f"{'SELFTEST SKIPPED' if args.skip_selftest else len(v.bad_scan)} the rigid-skeleton "
          f"scan could not round-trip, in {now()-t0:.0f}s, rss {rss_mb():.0f} MB",
          flush=True)
    print(f"  GATE conclusion extractor: {v.concl_bad} statements violated "
          f"'no binder => the conclusion is the statement, and never longer'", flush=True)
    if v.bad_scan:
        print(f"  ABORT-WORTHY: blank-then-refill is lossy on {len(v.bad_scan)} rows, "
              f"e.g. {v.bad_scan[:5]}")
    out["view"] = {"n": len(v), "claims": len(v.claims), "no_stmt": len(v.no_stmt),
                   "roundtrip_failures": len(v.bad_scan),
                   "conclusion_gate_violations": v.concl_bad,
                   "total_statement_bytes": int(sum(v.nbytes)),
                   "vocabulary": len(v.vocab)}
    dump()

    if args.deep_only:
        inv = {"wit": {}, "examples": {}, "buckets": {}, "cross": {}}
    else:
        inv = inventory(v, out)
    dump()

    # The frequency-matched null population, over constant *document frequency* so a
    # substitution onto a very common constant is as likely under the null as in the data.
    pop = list(v.df.keys())
    cum = list(itertools.accumulate(v.df[k] for k in pop))

    r = Router(v, c, inv["wit"], unproved)
    r.proved_vocab = v.proved_vocab
    print(f"\n  vocabulary occurring in a proved theorem: {len(r.proved_vocab)} of "
          f"{len(v.vocab)} constants", flush=True)

    print("\n=== stage 4  the route search, per unproved declaration ===", flush=True)
    reports = []
    for nm in sorted(unproved):
        t0 = now()
        rep = route_report(r, v, nm, deep=args.deep_only or not args.no_deep,
                           rng=rng, pop=pop, cum=cum)
        reports.append(rep)
        print(f"\n  {nm}  [{rep.get('kind')}, {rep.get('subfield')}, "
              f"{rep.get('bytes')} bytes, {rep.get('slots')} slots, "
              f"head {rep.get('conclusion_head')}]  ({now()-t0:.0f}s)")
        print(f"    R1 identity      : {rep['R1_identity'] or 'none'}")
        r3 = rep["R3_rewrite"]
        print(f"    R3 rewrite       : {rep['R3_tried']} rewrites attempted, "
              f"{len(r3)} image(s) exist"
              + ("" if not r3 else "  " + "; ".join(
                  f"{g['image']} [{g['sub'][0]} := {g['sub'][1]}, "
                  f"{g['witnesses']}w, proved={g['proved']}]" for g in r3[:4])))
        print(f"    R3 null          : {rep['R3_null']}")
        r5 = rep.get("R5_conclusion") or {}
        print(f"    R5 conclusion    : identical {r5.get('identical_n', 0)} "
              f"{r5.get('identical', [])[:5]}; same tree {r5.get('same_tree_n', 0)}")
        for s in (r5.get("same_tree") or [])[:4]:
            print(f"       ~ {s['name']}  [{s['n_subs']} sub] {s['subs'][:3]}")
        if "R2_equivalence" in rep:
            print(f"    R2 equivalence   : {rep['R2_equivalence']}")
            print(f"    variants         : {str(rep.get('variants'))[:220]}")
            print(f"    adjacent         : {str(rep.get('adjacent'))[:220]}")
            print(f"    vocab-adjacent   : {str(rep.get('vocabulary_adjacent'))[:220]}")
            print(f"    subsumers        : {str(rep.get('subsumers'))[:220]}")
            print(f"    requires         : {rep.get('requires')}")
        print(f"    vocab coverage   : {rep['vocab_in_proved']}/"
              f"{rep['distinct_constants']} = {rep['vocab_coverage']:.3f}")
        print(f"    rarest constants : {rep['rarest_constants']}")
        out["routes"] = reports
        dump()

    # A named check rather than a remark, because it decides whether the shipped surface
    # can answer this study's question at all. `EquivIndex::build` sets
    # `is_prop = kind == "theorem" || concludes_in_prop(stmt)`, and `concludes_in_prop`
    # tests whether the statement's own conclusion is `Sort 0` — true of a *definition of*
    # a proposition and false of a theorem's statement, which **is** the proposition. So
    # for anything whose kind is not `theorem` the flag is decided by kind alone, and
    # `equivalent` refuses every `axiom` however plainly propositional it is. That is
    # findings §23's defect (`logical.rs` skipping non-theorems, which made a
    # statement-level corpus invisible) surviving one query over. Demonstrated rather than
    # asserted: a target with a non-empty R1 identity class has an equivalence class by
    # construction, and the query refuses to compute it.
    refused = [rep["name"] for rep in reports
               if rep.get("R1_identity")
               and isinstance(rep.get("R2_equivalence"), dict)
               and any("NotAProposition" in str(x)
                       for x in rep["R2_equivalence"].values())]
    print(f"\n  CHECK `equivalent` refuses a declaration whose identity class is "
          f"non-empty: {len(refused)} -> {refused}")
    out["equivalent_refused_nonempty_class"] = refused

    prose_h: collections.Counter = collections.Counter()
    for nm, _mod, _mk in cen["prose"]:
        i = v.idx.get(nm)
        if i is not None:
            prose_h[v.hstmt[i].hex()] += 1
    print(f"  CHECK prose claims carry a statement: {len(cen['prose'])} claims over "
          f"{len(prose_h)} distinct statement encodings {prose_h.most_common(4)}")
    out["prose_distinct_statements"] = len(prose_h)

    if not args.deep_only:
        cross_library(v, inv["cross"], out, rng)
        dump()
        frontier_distance(v, inv["buckets"], unproved, sorted(unproved), out, rng)
        dump()
        vocabulary_novelty(v, unproved, out, rng)
        dump()
        controls(r, v, out, rng, pop, cum)
        dump()
    print(f"\ndone, rss {rss_mb():.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
