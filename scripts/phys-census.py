"""Is physics structurally different from mathematics — and does the engine's tuning transfer?

Every floor, weight and constant in the Atlas was fitted on Mathlib. `CLAUDE.md` §4 warns
that constants fitted on the wrong slice do not transfer, and gives the cautionary case
(`Mathlib.Logic.Basic`, 37% Lean metaprogramming). Nobody has asked the same question of
*physics*: physlib is a real corpus written by other people, and if its statements are
systematically bigger, deeper or more instance-laden than Mathlib's, then the posting-key
size floors, the posting-list cutoff and the retrieval floors all select differently there.

## What this measures, and what a good answer looks like — stated before running

**Q1 — census.** Statement size, depth, telescope length, instance-binder count, conclusion
arity, distinct symbols, and hole density after each erasure level, side by side.
*Difference worth calling structural*: a ratio of medians outside [0.5, 2.0], or a hole
density differing by more than 10 percentage points. *Null*: ratios near 1.

**Q2 — prefilter.** The index keys postings on subterms of the `presentation` erasure that
clear `min_concrete_closed=3` / `min_concrete_open=5`, and on subterms of the `shape`
erasure that clear `min_shape_sub=8`; a posting list longer than `max_posting_fraction`
of the corpus is dropped. Those are build-time knobs the Python binding deliberately does
not expose, so this simulates them by parsing the rendered skeletons — and *validates the
simulation against the engine* before using it (see `--check`). *Difference worth calling
a transfer failure*: a materially different fraction of declarations with **zero** surviving
keys, since that is the mechanism by which a floor manufactures a false negative.

**Q3 — ranking.** `similar` against `similar_brute` at matched floors, with each missed true
neighbour attributed to *never proposed* (prefilter) or *buried* (ranking). Mathlib's split
is 33.3% never-proposed / 0 buried (CLAUDE.md §5). *A real finding*: physics never-proposed
materially above 33.3%, which would indict the floors rather than the scorer.

**Q4 — a name-free separator.** A statistic over structure alone that tells a physics module
from a mathematics one, checked on a held-out half of the modules, against a label shuffle.

## The controls, without which none of the above is attributable

1. **Closure.** Erasure holes arguments in `InstImplicit` positions *of the head constant's
   signature*; a head the slice does not contain holes nothing (§31). A less-closed corpus
   therefore holes *less*, which is exactly the statistic Q1 compares. Every corpus reports
   `Corpus.closure()` coverage beside every table, and the unclosed physlib extraction is
   run as a **positive control**: it must show the artifact, or the closure requirement is
   not doing the work claimed for it.

2. **The shared substrate.** Both closures contain `Init`/`Lean`/`Std`/`Batteries` — the
   *same declarations*, modulo a toolchain patch version. Comparing those two strata is a
   null with a known answer: if they differ, the pipeline is measuring the extraction and
   not the mathematics. Likewise `Mathlib.*` appears in both corpora.

3. **Claims only.** CLAUDE.md §5: an unrestricted census measures Lean, not mathematics —
   the largest structures in any slice are recursors and `sizeOf` instances. Every headline
   table is theorems; the all-kinds table is reported beside it, never instead of it.

4. **A label shuffle** for Q4, because a separator that survives shuffling is a separator of
   nothing.

Nothing here name-matches. Strata come from the module path, which is where the extractor
wrote them; every structural statistic is read off the I3 encoding or off a skeleton the
engine rendered.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# `parse_rendered` recurses over the term, and physics statements nest far deeper than
# Lean's default budget allows — the deepest in physlib is 71 MB of encoding. Raised rather
# than rewritten iteratively because the cap below keeps the terms that reach here small,
# and a `RecursionError` is caught and counted where it can still happen.
sys.setrecursionlimit(60_000)

from atlas_home import Reader, TAG_B, TAG_LEN  # noqa: E402

# ---------------------------------------------------------------------------
# Strata.
#
# A stratum is read off the module path the extractor wrote, never off a declaration's
# name. `Physlib` and `QuantumInfo` are the physics workspace's two libraries; the
# substrate is what both workspaces import from the toolchain and is the null control.
# ---------------------------------------------------------------------------

PHYS_ROOTS = {"Physlib", "QuantumInfo"}
MATH_ROOTS = {"Mathlib"}
SUBSTRATE_ROOTS = {"Init", "Lean", "Std", "Batteries"}


def module_root(m: str) -> str:
    return m.split(".", 1)[0] if m else ""


def stratum(m: str) -> str:
    r = module_root(m)
    if r in PHYS_ROOTS:
        return "phys"
    if r in MATH_ROOTS:
        return "math"
    if r in SUBSTRATE_ROOTS:
        return "substrate"
    return "other"


# ---------------------------------------------------------------------------
# A structural walk of one I3 encoding.
#
# One pass, not five: the census wants size, depth, binder counts, application count and
# distinct symbols, and re-reading a 10 kB encoding once per statistic over 470,435 rows is
# minutes of nothing. Node counting follows `atlas_home.node_count` exactly — `c(`, `s(`,
# `j(` are consumed whole by `skip` and score 1 — so the two agree by construction.
# ---------------------------------------------------------------------------


def walk(encoding: str) -> dict | None:
    r = Reader(encoding)
    b = r.b
    n = 0
    depth = 0
    maxd = 0
    apps = 0
    lams = 0
    binders = {"d": 0, "i": 0, "s": 0, "t": 0}
    syms: set[str] = set()
    consts = 0
    try:
        while r.i < len(b):
            before = r.i
            c = b[r.i]
            if c in (0x61, 0x65):  # 'a(' application, 'e(' let
                r.i += 2
                n += 1
                depth += 1
                maxd = max(maxd, depth)
                if c == 0x61:
                    apps += 1
                continue
            if c in (0x6C, 0x70):  # 'l' lambda / 'p' pi, each carrying binder info
                bi = chr(b[r.i + 1])
                r.i += 3
                n += 1
                depth += 1
                maxd = max(maxd, depth)
                if c == 0x70:
                    binders[bi] = binders.get(bi, 0) + 1
                else:
                    lams += 1
                continue
            if c == 0x2C:
                r.i += 1
                continue
            if c == 0x29:
                r.i += 1
                depth -= 1
                continue
            if c == 0x63:  # 'c(' — read the name before skipping past it
                j = r.i + 2
                k = j
                while b[k] != 0x3A:
                    k += 1
                ln = int(b[j:k])
                syms.add(b[k + 1 : k + 1 + ln].decode("utf-8", "replace"))
                consts += 1
            r.skip()
            n += 1
            if r.i == before:
                break
    except Exception:
        return None
    return {
        "nodes": n,
        "depth": maxd,
        "apps": apps,
        "lams": lams,
        "pi_d": binders.get("d", 0),
        "pi_i": binders.get("i", 0),
        "pi_s": binders.get("s", 0),
        "pi_t": binders.get("t", 0),
        "consts": consts,
        "distinct_syms": len(syms),
    }


def telescope2(encoding: str, limit: int = 512):
    """Top-level binders, the conclusion head, and the conclusion's spine arity.

    `atlas_home.telescope` discards the conclusion's arguments; the census wants their count,
    which is the arity a retrieval key is built over.
    """
    r = Reader(encoding)
    infos: list[str] = []
    inst_classes: list[str] = []
    try:
        while len(infos) < limit and r.i < len(r.b) and r.b[r.i] == 0x70:
            bi = chr(r.b[r.i + 1])
            r.i += 3
            sub = Reader.__new__(Reader)
            sub.b, sub.i = r.b, r.i
            head, _args = sub.head_and_args()
            infos.append(bi)
            if bi == "t":
                inst_classes.append(head or "?")
            r.i = sub.i
            r.i += 1  # ','
        concl = Reader.__new__(Reader)
        concl.b, concl.i = r.b, r.i
        chead, cargs = concl.head_and_args()
    except Exception:
        return None
    return {
        "tele": len(infos),
        "tele_d": infos.count("d"),
        "tele_i": infos.count("i"),
        "tele_s": infos.count("s"),
        "tele_t": infos.count("t"),
        "inst_classes": inst_classes,
        "concl_head": chead,
        "concl_arity": len(cargs),
    }


# ---------------------------------------------------------------------------
# Distributions: quantiles without holding every value, where the value is small.
# ---------------------------------------------------------------------------


class Dist:
    """A reservoir plus exact count/mean, so quantiles are honest and memory is bounded."""

    CAP = 50_000

    def __init__(self) -> None:
        self.n = 0
        self.total = 0.0
        self.res: list[float] = []
        self.rng = random.Random(20260804)

    def add(self, v: float) -> None:
        self.n += 1
        self.total += v
        if len(self.res) < self.CAP:
            self.res.append(v)
        else:
            j = self.rng.randrange(self.n)
            if j < self.CAP:
                self.res[j] = v

    def summary(self) -> dict:
        if not self.n:
            return {"n": 0}
        s = sorted(self.res)

        def q(p: float) -> float:
            if not s:
                return 0.0
            return s[min(len(s) - 1, int(p * len(s)))]

        return {
            "n": self.n,
            "mean": self.total / self.n,
            "p10": q(0.10),
            "p25": q(0.25),
            "median": q(0.50),
            "p75": q(0.75),
            "p90": q(0.90),
            "p99": q(0.99),
            "max": s[-1] if s else 0,
        }


FIELDS = [
    "nodes",
    "depth",
    "apps",
    "distinct_syms",
    "tele",
    "tele_t",
    "tele_i",
    "tele_d",
    "concl_arity",
    "inst_distinct",
]


def rows_of(path: str, limit: int | None = None):
    with open(path, "r", encoding="utf-8") as f:
        for k, line in enumerate(f):
            if limit is not None and k >= limit:
                return
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Q1 — the streaming census
# ---------------------------------------------------------------------------


def cmd_census(args) -> None:
    t0 = time.time()
    buckets: dict[tuple[str, str], dict[str, Dist]] = {}
    counts: collections.Counter = collections.Counter()
    kinds: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    modules: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    concl: dict[tuple[str, str], collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    parse_fail = collections.Counter()
    per_module: dict[str, dict] = {}

    for i, row in enumerate(rows_of(args.slice, args.limit)):
        if args.progress and i and i % 100_000 == 0:
            print(f"  … {i:,} rows  {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
        mod = row.get("module") or ""
        st = stratum(mod)
        kind = row.get("kind") or "?"
        counts[st] += 1
        kinds[st][kind] += 1
        modules[st][module_root(mod)] += 1
        stmt = row.get("stmt")
        if not stmt:
            continue
        # Composition is counted on every row; the structural walk can be strided.
        #
        # Walking every encoding in a 4.8 GB closure is about two hours of Python, almost
        # all of it in the upper tail — physlib's largest single statement is 71 MB. Rows
        # are written in module order, so a systematic stride spreads across the whole
        # library rather than sampling one corner, and medians from it estimate the same
        # quantity. `stride=1` is the exact census and is what the headline tables use
        # unless the table says otherwise.
        if args.stride > 1 and (i % args.stride):
            continue
        w = walk(stmt)
        t = telescope2(stmt)
        if w is None or t is None:
            parse_fail[st] += 1
            continue
        rec = dict(w)
        rec.update(t)
        rec["inst_distinct"] = len(set(t["inst_classes"]))
        for kb in ((st, "all"), (st, kind)):
            if kb[1] not in ("all", "theorem"):
                continue
            d = buckets.setdefault(kb, {f: Dist() for f in FIELDS})
            for f in FIELDS:
                d[f].add(rec[f])
        if kind == "theorem" and t["concl_head"]:
            concl[(st, "theorem")][t["concl_head"]] += 1
        # Per-module aggregates feed Q4's separator; kept only for claims.
        if kind == "theorem":
            m = per_module.setdefault(
                mod, {"stratum": st, "n": 0, **{f: 0.0 for f in FIELDS}}
            )
            m["n"] += 1
            for f in FIELDS:
                m[f] += rec[f]

    out = {
        "slice": args.slice,
        "rows": sum(counts.values()),
        "stride": args.stride,
        "seconds": time.time() - t0,
        "strata": dict(counts),
        "kinds": {k: dict(v) for k, v in kinds.items()},
        "module_roots": {k: dict(v.most_common(12)) for k, v in modules.items()},
        "parse_fail": dict(parse_fail),
        "dists": {
            f"{a}|{b}": {f: d[f].summary() for f in FIELDS} for (a, b), d in buckets.items()
        },
        "concl_heads": {
            f"{a}|{b}": dict(c.most_common(25)) for (a, b), c in concl.items()
        },
        "per_module": {
            m: {**v, **{f: v[f] / v["n"] for f in FIELDS}} for m, v in per_module.items()
        },
    }
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(f"wrote {args.out}  ({out['rows']:,} rows, {out['seconds']:.0f}s)")


# ---------------------------------------------------------------------------
# A parser for the *rendered* I3 the engine emits for skeletons.
#
# `Arena::render` is the encoder run backwards, plus `_` for a hole and `?k` for an
# anti-unification variable. Parsing it back gives exactly the terms the index keys its
# postings on, so the floor simulation below is over the engine's own output rather than
# over a reimplementation of the erasure.
# ---------------------------------------------------------------------------


class Term:
    __slots__ = ("size", "loose", "concrete", "key")

    def __init__(self, size: int, loose: int, concrete: int, key: str) -> None:
        self.size = size
        self.loose = loose
        self.concrete = concrete
        self.key = key


def parse_rendered(s: str) -> tuple[Term, list[Term]]:
    """Return the root and every distinct subterm, with `Arena::measure`'s three counters.

    Deduplication is by rendered text, which is what interning is: `render` is injective on
    structure, so two subterms share a key exactly when the arena would share a `TermId`.
    """
    b = s.encode()
    if b.startswith(TAG_B):
        b = b[TAG_LEN:]
    i = 0
    seen: dict[str, Term] = {}

    def emit(size: int, loose: int, concrete: int, start: int, end: int) -> Term:
        key = b[start:end].decode("utf-8", "replace")
        t = seen.get(key)
        if t is None:
            t = Term(size, loose, concrete, key)
            seen[key] = t
        return t

    def digits() -> int:
        nonlocal i
        j = i
        while j < len(b) and 0x30 <= b[j] <= 0x39:
            j += 1
        v = int(b[i:j]) if j > i else 0
        i = j
        return v

    def skip_level() -> None:
        nonlocal i
        c = b[i]
        if c == 0x30:
            i += 1
        elif c == 0x2A:  # '*' — `LevelNode::Star`, what `Presentation` erases a level to
            i += 1
        elif c == 0x75:
            i += 1
            digits()
        elif c in (0x2B, 0x4D, 0x49):
            i += 2
            skip_level()
            while b[i] == 0x2C:
                i += 1
                skip_level()
            i += 1
        else:
            raise ValueError(f"level at {i}")

    def name() -> str:
        nonlocal i
        j = i
        while b[j] != 0x3A:
            j += 1
        ln = int(b[i:j])
        i = j + 1 + ln
        return b[j + 1 : j + 1 + ln].decode("utf-8", "replace")

    def expr() -> Term:
        nonlocal i
        start = i
        c = b[i]
        if c == 0x62:  # bvar
            i += 1
            k = digits()
            return emit(1, k + 1, 1, start, i)
        if c == 0x5F:  # '_' hole
            i += 1
            return emit(1, 0, 0, start, i)
        if c == 0x3F:  # '?k' anti-unification variable
            i += 1
            digits()
            return emit(1, 0, 0, start, i)
        if c == 0x6E:  # nat literal
            i += 1
            digits()
            return emit(1, 0, 1, start, i)
        if c == 0x74:  # string literal
            i += 1
            name()
            return emit(1, 0, 1, start, i)
        if c == 0x73 and b[i + 1] == 0x28:  # sort
            i += 2
            skip_level()
            i += 1
            return emit(1, 0, 1, start, i)
        if c == 0x63:  # const
            i += 2
            name()
            i += 1
            k = digits()
            for _ in range(k):
                i += 1
                skip_level()
            i += 1
            return emit(1, 0, 1, start, i)
        if c == 0x61:  # application
            i += 2
            f = expr()
            i += 1
            a = expr()
            i += 1
            return emit(
                1 + f.size + a.size,
                max(f.loose, a.loose),
                1 + f.concrete + a.concrete,
                start,
                i,
            )
        if c in (0x6C, 0x70):  # lambda / pi
            i += 3
            d = expr()
            i += 1
            body = expr()
            i += 1
            return emit(
                1 + d.size + body.size,
                max(d.loose, max(0, body.loose - 1)),
                1 + d.concrete + body.concrete,
                start,
                i,
            )
        if c == 0x65:  # let
            i += 2
            ty = expr()
            i += 1
            v = expr()
            i += 1
            body = expr()
            i += 1
            return emit(
                1 + ty.size + v.size + body.size,
                max(ty.loose, v.loose, max(0, body.loose - 1)),
                1 + ty.concrete + v.concrete + body.concrete,
                start,
                i,
            )
        if c == 0x6A:  # proj
            i += 2
            name()
            i += 1
            digits()
            i += 1
            e = expr()
            i += 1
            return emit(1 + e.size, e.loose, 1 + e.concrete, start, i)
        raise ValueError(f"expr {chr(c)!r} at {i}")

    root = expr()
    return root, list(seen.values())


# ---------------------------------------------------------------------------
# Q2 — hole density, and the posting-key floors simulated over the engine's own skeletons
# ---------------------------------------------------------------------------

LEVELS = ["exact", "presentation", "instances", "carriers", "shape"]

FLOOR_SWEEP = [(1, 1, 4), (2, 3, 6), (3, 5, 8), (4, 7, 10), (6, 10, 14)]


def sample_names(corpus, args, kinds=("theorem",)):
    """A uniform sample of claims from one stratum.

    Shuffled first and filtered lazily rather than the other way round: a 470,435-row
    corpus is 470,435 `get` calls otherwise, and the sample is uniform either way.
    """
    rng = random.Random(args.seed)
    names = corpus.names()
    rng.shuffle(names)
    picked = []
    for n in names:
        d = corpus.get(n)
        if d is None or d.stmt is None:
            continue
        if kinds and d.kind not in kinds:
            continue
        if args.stratum and stratum(d.module) != args.stratum:
            continue
        picked.append(n)
        if len(picked) >= args.sample:
            break
    return picked


def cmd_erasure(args, corpus=None) -> None:
    t0 = time.time()
    if corpus is None:
        import atlas

        print(f"[load] {args.slice}", file=sys.stderr, flush=True)
        corpus = atlas.Corpus.load(args.slice)
    c = corpus
    known, unknown, coverage, worst = c.closure(top=10)
    print(
        f"[closure] known={known:,} unknown={unknown:,} coverage={coverage:.4f}"
        f"  ({time.time() - t0:.0f}s)",
        file=sys.stderr,
        flush=True,
    )

    result = {
        "slice": args.slice,
        "declarations": len(c),
        "closure": {
            "known_heads": known,
            "unknown_heads": unknown,
            "coverage": coverage,
            "worst": worst,
        },
        "strata": {},
    }

    for st in args.strata.split(","):
        args.stratum = st
        names = sample_names(c, args)
        if not names:
            result["strata"][st] = {"sampled": 0}
            continue
        # The tail has to be excluded and the exclusion has to be reported.
        #
        # A single physlib declaration encodes to 71 MB, and parsing its skeleton in Python
        # does not finish. Excluding it is a filter, so it gets a number rather than a
        # silence: `oversize` is how many of the sample were dropped and at what size, and
        # the medians below are on the remainder. It can only remove mass from the upper
        # tail, so a *larger* physics statement distribution is if anything understated.
        cap = args.max_stmt_bytes
        kept, oversize, oversize_bytes = [], 0, []
        for n in names:
            d = c.get(n)
            s = d.stmt if d else None
            if s is None:
                continue
            if len(s) > cap:
                oversize += 1
                oversize_bytes.append(len(s))
                continue
            kept.append(n)
        print(
            f"[{st}] {len(names)} sampled, {oversize} over {cap:,} bytes excluded",
            file=sys.stderr,
            flush=True,
        )
        names = kept
        per_level = {}
        keydist = {f"{a}_{b}_{s}": Dist() for (a, b, s) in FLOOR_SWEEP}
        zerokeys = {f"{a}_{b}_{s}": 0 for (a, b, s) in FLOOR_SWEEP}
        posting_keys: dict[str, collections.Counter] = {
            f"{a}_{b}_{s}": collections.Counter() for (a, b, s) in FLOOR_SWEEP
        }
        for lvl in LEVELS:
            hole_frac = Dist()
            size = Dist()
            distinct_sub = Dist()
            ok = 0
            for n in names:
                try:
                    sk = c.skeleton(n, level=lvl)
                except Exception:
                    continue
                try:
                    root, subs = parse_rendered(sk)
                except Exception:
                    continue
                ok += 1
                size.add(root.size)
                distinct_sub.add(len(subs))
                hole_frac.add(1.0 - root.concrete / max(1, root.size))
                if lvl == "presentation":
                    for tag, (fc, fo, _fs) in zip(posting_keys, FLOOR_SWEEP):
                        k = sum(
                            1
                            for t in subs
                            if t.size >= (fc if t.loose == 0 else fo)
                        )
                        keydist[tag].add(k)
                        if k == 0:
                            zerokeys[tag] += 1
                        for t in subs:
                            if t.size >= (fc if t.loose == 0 else fo):
                                posting_keys[tag][t.key] += 1
            per_level[lvl] = {
                "parsed": ok,
                "root_size": size.summary(),
                "distinct_subterms": distinct_sub.summary(),
                "hole_fraction": hole_frac.summary(),
            }
        # Shape-erasure keys use their own floor and their own erasure.
        shape_keys = {f"{a}_{b}_{s}": Dist() for (a, b, s) in FLOOR_SWEEP}
        shape_zero = {f"{a}_{b}_{s}": 0 for (a, b, s) in FLOOR_SWEEP}
        for n in names:
            try:
                sk = c.skeleton(n, level="shape")
                _root, subs = parse_rendered(sk)
            except Exception:
                continue
            for tag, (_fc, _fo, fs) in zip(shape_keys, FLOOR_SWEEP):
                k = sum(1 for t in subs if t.size >= fs)
                shape_keys[tag].add(k)
                if k == 0:
                    shape_zero[tag] += 1
        result["strata"][st] = {
            "sampled": len(names),
            "oversize_excluded": oversize,
            "oversize_bytes_median": (
                sorted(oversize_bytes)[len(oversize_bytes) // 2] if oversize_bytes else None
            ),
            "levels": per_level,
            "floor_sweep": {
                tag: {
                    "concrete_keys": keydist[tag].summary(),
                    "decls_with_zero_concrete_keys": zerokeys[tag],
                    "distinct_concrete_keys": len(posting_keys[tag]),
                    "top_key_share": (
                        max(posting_keys[tag].values()) / max(1, len(names))
                        if posting_keys[tag]
                        else 0.0
                    ),
                    "shape_keys": shape_keys[tag].summary(),
                    "decls_with_zero_shape_keys": shape_zero[tag],
                }
                for tag in keydist
            },
        }
        print(
            f"[{st}] done {time.time() - t0:.0f}s",
            file=sys.stderr,
            flush=True,
        )

    with open(args.out, "w") as f:
        json.dump(result, f)
    print(f"wrote {args.out}")


# ---------------------------------------------------------------------------
# The simulation's own control: does it agree with the engine?
#
# A reimplemented prefilter that is wrong in the same direction on both corpora would leave
# every ratio intact and every conclusion unfounded. `motifs` reports the engine's real
# posting lists — key, family, size — so a key the simulation produces must be one the
# engine has, at the same size, and the family sizes must agree.
# ---------------------------------------------------------------------------


def cmd_check(args) -> None:
    import atlas

    c = atlas.Corpus.load(args.slice)
    print(f"[loaded] {len(c):,} declarations", flush=True)
    mot = c.motifs(source="subterm", min_family=args.min_family, min_size=args.min_size,
                   top=args.top)
    print(f"[motifs] {len(mot)} engine posting keys", flush=True)
    agree = 0
    disagree = []
    for pattern, members, size, _idf in mot:
        try:
            root, _subs = parse_rendered(pattern)
        except Exception as e:
            disagree.append((pattern[:60], f"parse: {e}"))
            continue
        if root.size == size:
            agree += 1
        else:
            disagree.append((pattern[:60], f"size {root.size} != engine {size}"))
    print(f"size agreement: {agree}/{len(mot)}")
    for d in disagree[:10]:
        print("  MISMATCH", d)

    # And the other direction: a key the simulation extracts from a declaration's
    # presentation skeleton must contain that declaration in the engine's posting list.
    by_key = {p: set(m) for p, m, _s, _i in mot}
    checked = 0
    contained = 0
    for pattern, members, _size, _idf in mot[: args.decls]:
        for m in members[:3]:
            try:
                sk = c.skeleton(m, level="presentation")
                _r, subs = parse_rendered(sk)
            except Exception:
                continue
            keys = {t.key for t in subs}
            checked += 1
            if pattern in keys:
                contained += 1
    print(f"membership agreement: {contained}/{checked}")

    # The census walker's own control. `walk` counts nodes over the raw encoding; the
    # engine counts them over its arena. They must agree, or every size in the census is a
    # different quantity from every size in the index — and the two are compared. `Proj` is
    # the one shape where they legitimately differ (`Reader.skip` consumes it whole, so the
    # walker scores it 1), so disagreements are reported with a `j(` breakdown rather than
    # waved away.
    rng = random.Random(20260804)
    names = c.names()
    rng.shuffle(names)
    same = diff = diff_with_proj = 0
    for n in names[: args.decls * 10]:
        d = c.get(n)
        if d is None or d.stmt is None or len(d.stmt) > 262_144:
            continue
        try:
            w = walk(d.stmt)
            root, _ = parse_rendered(c.skeleton(n, level="exact"))
        except Exception:
            continue
        if w is None:
            continue
        if w["nodes"] == root.size:
            same += 1
        else:
            diff += 1
            if "j(" in d.stmt:
                diff_with_proj += 1
    print(
        f"walker vs arena node count: {same} agree, {diff} differ "
        f"({diff_with_proj} of those contain a projection)"
    )
    ok = agree == len(mot) and contained == checked and checked > 0
    print("SIMULATION FAITHFUL" if ok else "SIMULATION UNFAITHFUL")
    del c
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# Q3 — the retrieval differential
# ---------------------------------------------------------------------------


def cmd_differential(args, corpus=None) -> None:
    t0 = time.time()
    if corpus is None:
        import atlas

        corpus = atlas.Corpus.load(args.slice)
    c = corpus
    known, unknown, coverage, _worst = c.closure(top=5)
    print(
        f"[closure] coverage={coverage:.4f} known={known:,} unknown={unknown:,}",
        file=sys.stderr,
        flush=True,
    )
    args.stratum = args.stratum or None
    names = sample_names(c, args)
    # Same exclusion as the erasure census, for the same reason and reported the same way:
    # one physlib statement is 71 MB, and anti-unifying it against half a million
    # declarations is not a query anybody would issue. Counted, never silent.
    oversize = 0
    kept = []
    for n in names:
        d = c.get(n)
        if d is not None and d.stmt is not None and len(d.stmt) > args.max_stmt_bytes:
            oversize += 1
            continue
        kept.append(n)
    names = kept
    print(f"[queries] {len(names)} ({oversize} oversize excluded)", file=sys.stderr,
          flush=True)

    # `examples/recallcheck.rs`'s protocol, reproduced through the binding so it can run on
    # a corpus the gate has never seen: truth is the top-`k` of brute force, the prediction
    # is the top-`cut` of `similar`, and an untruncated `similar` separates "the prefilter
    # never proposed it" from "the ranking buried it". The split is only clean because
    # `similar_brute` applies the same `min_common`/`min_retention`, so every truth entry
    # clears those floors by construction.
    truth_total = 0
    found = 0
    never_proposed = 0
    buried = 0
    skipped = 0
    per_query = []
    proposed_sizes = Dist()
    raw_sizes = Dist()
    source_tally: collections.Counter = collections.Counter()
    source_queries: collections.Counter = collections.Counter()
    sweep: dict[str, dict] = collections.defaultdict(
        lambda: {"found": 0, "truth": 0, "returned": 0}
    )
    for k, n in enumerate(names):
        if k and k % 20 == 0:
            print(f"  … {k}/{len(names)}  {time.time() - t0:.0f}s", file=sys.stderr,
                  flush=True)
        try:
            brute = c.similar_brute(n, top=args.k, level=args.level)
        except Exception:
            skipped += 1
            continue
        if not brute:
            skipped += 1
            continue
        try:
            wide = c.similar(n, top=args.wide, level=args.level)
            # The prefilter's own output, floors removed: how many candidates it proposes
            # at all, before `min_common` and `min_retention` have a say.
            raw = c.similar(
                n, top=args.wide, level=args.level, min_common=0, min_retention=0.0
            )
        except Exception:
            skipped += 1
            continue
        proposed = [g.name for g in wide]
        proposed_sizes.add(len(proposed))
        raw_sizes.add(len(raw))
        # Which retrieval source actually fires. A candidate can arrive through the shape
        # bucket (A), a concrete subterm posting (B) or a shape subterm posting (C); the
        # size floors gate B and C only. If B stops firing on one corpus, that is the
        # floors failing to transfer, measured by the engine rather than simulated.
        for g in raw:
            for s in g.sources:
                source_tally[s] += 1
            source_tally["|total"] += 1
        if raw:
            source_queries["queries"] += 1
            for s in {x for g in raw for x in g.sources}:
                source_queries[s] += 1
        cut = set(proposed[: args.cut])
        reachable = set(proposed)
        miss_np = 0
        miss_b = 0
        for tn, _ret in brute:
            truth_total += 1
            if tn in cut:
                found += 1
            elif tn in reachable:
                buried += 1
                miss_b += 1
            else:
                never_proposed += 1
                miss_np += 1
        per_query.append(
            {
                "query": n,
                "truth": len(brute),
                "proposed": len(proposed),
                "raw_candidates": len(raw),
                "never_proposed": miss_np,
                "buried": miss_b,
            }
        )

        # The retrieval floors, swept against a **fixed** truth set.
        #
        # `similar_brute` applies the shipped `min_common`/`min_retention` and the binding
        # exposes no knob for them, so the truth here is always the default-floor one. That
        # is the right reference anyway: the question is not "does a lower floor invent more
        # truth" but "how fast does recall of the *same* neighbours fall as the floor rises",
        # which is sensitivity — and sensitivity is what a constant fitted on another corpus
        # has to survive.
        truth_names = {tn for tn, _r in brute}
        for mc in args.sweep_common:
            for mr in args.sweep_retention:
                try:
                    sw = c.similar(
                        n, top=args.cut, level=args.level, min_common=mc, min_retention=mr
                    )
                except Exception:
                    continue
                got = {g.name for g in sw}
                key = f"c{mc}_r{mr:.2f}"
                sweep[key]["found"] += len(truth_names & got)
                sweep[key]["truth"] += len(truth_names)
                sweep[key]["returned"] += len(sw)

    missed = never_proposed + buried
    out = {
        "slice": args.slice,
        "stratum": args.stratum,
        "level": args.level,
        "k_truth": args.k,
        "cut": args.cut,
        "closure_coverage": coverage,
        "declarations": len(c),
        "queries": len(per_query),
        "skipped": skipped,
        "oversize_excluded": oversize,
        "truth_entries": truth_total,
        "found_in_cut": found,
        "missed": missed,
        "never_proposed": never_proposed,
        "buried": buried,
        "never_proposed_pct_of_truth": (100.0 * never_proposed / truth_total)
        if truth_total
        else None,
        "buried_pct_of_truth": (100.0 * buried / truth_total) if truth_total else None,
        "recall_at_cut": (found / truth_total) if truth_total else None,
        "proposed_set_size": proposed_sizes.summary(),
        "raw_candidate_set_size": raw_sizes.summary(),
        "floor_sweep": {
            k: {
                **v,
                "recall_at_cut": (v["found"] / v["truth"]) if v["truth"] else None,
                "mean_returned": v["returned"] / max(1, len(per_query)),
            }
            for k, v in sorted(sweep.items())
        },
        "candidates_by_source": dict(source_tally),
        "queries_reaching_source": dict(source_queries),
        "per_query": per_query,
    }
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(json.dumps({k: v for k, v in out.items() if k != "per_query"}, indent=2))


# ---------------------------------------------------------------------------
# Why the prefilter misses: is the true neighbour *reachable* by a shared key at all?
#
# The floors turn out not to starve physics of keys (Q2 is a null), so the 40% the prefilter
# loses there has to come from somewhere else. Source B retrieves by **exact subterm
# identity**: two declarations are candidates when some subterm of one erasure is the
# identical term in the other. Anti-unification, which decides the truth set, needs no such
# thing — it will happily match two statements that agree structurally and differ everywhere
# in detail.
#
# So the decisive measurement is: for each true neighbour the prefilter never proposed, do
# the query and the neighbour share **any** key that clears the floors? An empty
# intersection means no budget, no posting cutoff and no ranking change could have retrieved
# it — the index cannot see that pair, by construction.
# ---------------------------------------------------------------------------


def keyset(corpus, name: str, floors=(3, 5), shape_floor: int = 8):
    """The keys the index would file this declaration under, both sources."""
    out = set()
    try:
        _root, subs = parse_rendered(corpus.skeleton(name, level="presentation"))
    except Exception:
        return None
    fc, fo = floors
    for t in subs:
        if t.size >= (fc if t.loose == 0 else fo):
            out.add(("B", t.key))
    try:
        _r2, ssubs = parse_rendered(corpus.skeleton(name, level="shape"))
    except Exception:
        return out
    for t in ssubs:
        if t.size >= shape_floor:
            out.add(("C", t.key))
    return out


def cmd_reachability(args, corpus=None) -> None:
    t0 = time.time()
    if corpus is None:
        import atlas

        corpus = atlas.Corpus.load(args.slice)
    c = corpus
    _k, _u, coverage, _w = c.closure(top=5)
    names = sample_names(c, args)
    names = [
        n
        for n in names
        if (d := c.get(n)) is not None
        and d.stmt is not None
        and len(d.stmt) <= args.max_stmt_bytes
    ]
    print(f"[reach] {len(names)} queries, coverage {coverage:.4f}", file=sys.stderr,
          flush=True)

    tot = shared = 0
    miss_tot = miss_shared = 0
    hit_tot = hit_shared = 0
    overlap = Dist()
    for i, n in enumerate(names):
        if i and i % 20 == 0:
            print(f"  … {i}/{len(names)} {time.time() - t0:.0f}s", file=sys.stderr,
                  flush=True)
        try:
            brute = c.similar_brute(n, top=args.k, level=args.level)
            wide = c.similar(n, top=args.wide, level=args.level)
        except Exception:
            continue
        if not brute:
            continue
        qk = keyset(c, n)
        if qk is None:
            continue
        proposed = {g.name for g in wide}
        for tn, _r in brute:
            tk = keyset(c, tn)
            if tk is None:
                continue
            inter = len(qk & tk)
            tot += 1
            overlap.add(inter)
            if inter:
                shared += 1
            if tn in proposed:
                hit_tot += 1
                hit_shared += 1 if inter else 0
            else:
                miss_tot += 1
                miss_shared += 1 if inter else 0

    out = {
        "slice": args.slice,
        "stratum": args.stratum,
        "closure_coverage": coverage,
        "queries": len(names),
        "truth_pairs": tot,
        "pairs_sharing_a_key": shared,
        "pairs_sharing_a_key_pct": (100.0 * shared / tot) if tot else None,
        "proposed_pairs": hit_tot,
        "proposed_sharing_a_key": hit_shared,
        "missed_pairs": miss_tot,
        "missed_sharing_a_key": miss_shared,
        "missed_sharing_a_key_pct": (100.0 * miss_shared / miss_tot) if miss_tot else None,
        "key_overlap": overlap.summary(),
    }
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(json.dumps(out, indent=2))


# ---------------------------------------------------------------------------
# Q4 — a name-free separator, with a held-out split and a label shuffle
# ---------------------------------------------------------------------------


def auc(pos: list[float], neg: list[float]) -> float:
    """Rank-based AUC. 0.5 is chance; the direction is "pos scores higher"."""
    if not pos or not neg:
        return float("nan")
    s = sorted(neg)
    tot = 0.0
    for p in pos:
        lo = bisect.bisect_left(s, p)
        hi = bisect.bisect_right(s, p)
        tot += lo + 0.5 * (hi - lo)
    return tot / (len(pos) * len(neg))


def cmd_separator(args) -> None:
    mods: dict[str, dict] = {}
    for path in args.census:
        with open(path) as f:
            j = json.load(f)
        tag = os.path.basename(path)
        for m, v in j["per_module"].items():
            if v["n"] < args.min_decls:
                continue
            mods[f"{tag}::{m}"] = v

    labels = {m: v["stratum"] for m, v in mods.items()}
    usable = [m for m, s in labels.items() if s in ("phys", "math")]
    print(f"modules: {len(usable)}  phys={sum(1 for m in usable if labels[m] == 'phys')} "
          f"math={sum(1 for m in usable if labels[m] == 'math')}")

    stats = {
        f: (lambda v, f=f: v[f]) for f in FIELDS
    }
    stats["inst_per_binder"] = lambda v: v["tele_t"] / max(1e-9, v["tele"])
    stats["nodes_per_binder"] = lambda v: v["nodes"] / max(1e-9, v["tele"])
    stats["apps_per_node"] = lambda v: v["apps"] / max(1e-9, v["nodes"])
    stats["syms_per_node"] = lambda v: v["distinct_syms"] / max(1e-9, v["nodes"])
    stats["depth_per_log_nodes"] = lambda v: v["depth"] / max(1e-9, math.log(max(2.0, v["nodes"])))

    rng = random.Random(args.seed)
    train = [m for m in usable if rng.random() < 0.5]
    heldout = [m for m in usable if m not in set(train)]

    rows = []
    for name, fn in stats.items():
        def split(ms):
            p = [fn(mods[m]) for m in ms if labels[m] == "phys"]
            q = [fn(mods[m]) for m in ms if labels[m] == "math"]
            return p, q

        p, q = split(train)
        a = auc(p, q)
        ph, qh = split(heldout)
        ah = auc(ph, qh)
        # Label shuffle on the held-out half: the same statistic, labels permuted.
        sh = []
        for _ in range(args.shuffles):
            lab = [labels[m] for m in heldout]
            rng.shuffle(lab)
            pp = [fn(mods[m]) for m, l in zip(heldout, lab) if l == "phys"]
            qq = [fn(mods[m]) for m, l in zip(heldout, lab) if l == "math"]
            sh.append(auc(pp, qq))
        sh_mean = sum(sh) / len(sh) if sh else float("nan")
        sh_max = max((abs(x - 0.5) for x in sh), default=float("nan"))
        rows.append(
            {
                "statistic": name,
                "auc_train": a,
                "auc_heldout": ah,
                "shuffle_mean": sh_mean,
                "shuffle_max_dev": sh_max,
                "phys_median": sorted(ph)[len(ph) // 2] if ph else None,
                "math_median": sorted(qh)[len(qh) // 2] if qh else None,
            }
        )
    rows.sort(key=lambda r: -abs(r["auc_heldout"] - 0.5))

    # The control that decides whether this is a *physics* detector at all.
    #
    # A statistic that separates physics modules from mathematics modules would separate
    # them just as well if it were really separating "one subject area from another" — and
    # Mathlib has plenty of subject areas. So the same statistic is run on two Mathlib
    # subtrees against each other. Separation there at the same strength means the
    # statistic identifies a *subfield*, not physics, and the Q4 claim collapses.
    subtree = collections.Counter()
    for m in mods:
        mod = m.split("::", 1)[1]
        if mod.startswith("Mathlib."):
            subtree[".".join(mod.split(".")[:2])] += 1
    subtrees = [t for t, k in subtree.most_common() if k >= args.min_subtree][: args.subtrees]
    control_rows = []
    if len(subtrees) >= 2:
        groups = {
            t: [m for m in mods if m.split("::", 1)[1].startswith(t + ".")]
            for t in subtrees
        }
        for name, fn in stats.items():
            aucs = []
            for i in range(len(subtrees)):
                for j in range(i + 1, len(subtrees)):
                    a_, b_ = groups[subtrees[i]], groups[subtrees[j]]
                    v = auc([fn(mods[m]) for m in a_], [fn(mods[m]) for m in b_])
                    if v == v:
                        aucs.append(max(v, 1.0 - v))
            aucs.sort()
            control_rows.append(
                {
                    "statistic": name,
                    "pairs": len(aucs),
                    "median": aucs[len(aucs) // 2] if aucs else None,
                    "max": aucs[-1] if aucs else None,
                }
            )
        print(
            f"\nsubfield control — {len(subtrees)} Mathlib subtrees "
            f"({', '.join(subtrees)}), all pairs, AUC folded to [0.5, 1]:"
        )
        for r in sorted(control_rows, key=lambda r: -(r["max"] or 0))[:8]:
            print(
                f"  {r['statistic']:<22} median {r['median']:.3f}  max {r['max']:.3f}"
                f"  over {r['pairs']} pairs"
            )

    with open(args.out, "w") as f:
        json.dump(
            {
                "train": len(train),
                "heldout": len(heldout),
                "rows": rows,
                "subfield_control": {"subtrees": subtrees, "rows": control_rows},
            },
            f,
        )
    for r in rows:
        print(
            f"{r['statistic']:<22} train {r['auc_train']:.3f}  heldout {r['auc_heldout']:.3f}"
            f"  shuffle {r['shuffle_mean']:.3f} (max dev {r['shuffle_max_dev']:.3f})"
        )


# ---------------------------------------------------------------------------
# Equivalence classes and motif families, per corpus
# ---------------------------------------------------------------------------


def cmd_classes(args, corpus=None) -> None:
    if corpus is None:
        import atlas

        corpus = atlas.Corpus.load(args.slice)
    c = corpus
    known, unknown, coverage, _w = c.closure(top=5)
    out = {"slice": args.slice, "declarations": len(c), "closure_coverage": coverage,
           "levels": {}, "motifs": {}}
    print(f"[closure] {coverage:.4f}", file=sys.stderr, flush=True)
    # `shape` is rejected by `classes` on purpose — there "equivalent" degenerates into
    # "has the same skeleton", which is `similar`'s question — so the sweep stops at
    # `carriers`. `theorems_only` is the default and stays on: CLAUDE.md §5's restriction
    # to claims, without which the largest class is the declarations whose type is `Type`.
    for lvl in [x for x in LEVELS if x != "shape"]:
        t0 = time.time()
        cls = c.classes(level=lvl, theorems_only=True)
        sizes = [s for s, _m in cls]
        # Stratify: a class is "phys" when a majority of its members sit under a physics
        # module. Reported rather than filtered, because a cross-stratum class is the
        # interesting case and dropping it would hide it.
        strat = collections.Counter()
        for _s, members in cls[: args.top_classes]:
            sts = collections.Counter(
                stratum(c.get(m).module) for m in members if c.get(m)
            )
            strat[sts.most_common(1)[0][0]] += 1
        out["levels"][lvl] = {
            "classes": len(cls),
            "members": sum(sizes),
            "largest": sizes[0] if sizes else 0,
            "mean_size": (sum(sizes) / len(sizes)) if sizes else 0.0,
            "size_hist": dict(collections.Counter(min(s, 20) for s in sizes)),
            "dominant_stratum_of_top": dict(strat),
            "seconds": time.time() - t0,
        }
        print(f"[classes {lvl}] {len(cls)} classes {time.time() - t0:.0f}s",
              file=sys.stderr, flush=True)
    for src in ("subterm", "shape"):
        m = c.motifs(source=src, min_family=args.min_family, min_size=args.min_size,
                     top=args.top)
        fam = [len(members) for _p, members, _s, _i in m]
        sz = [s for _p, _m, s, _i in m]
        out["motifs"][src] = {
            "families": len(m),
            "mean_family": (sum(fam) / len(fam)) if fam else 0.0,
            "max_family": max(fam) if fam else 0,
            "mean_size": (sum(sz) / len(sz)) if sz else 0.0,
            "max_size": max(sz) if sz else 0,
        }
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(f"wrote {args.out}")
    del c


# ---------------------------------------------------------------------------
# Rendering. The tables in `research/physlib-census.md` come out of here rather than out
# of a hand transcription, because a number copied by hand is a number nobody can re-derive.
# ---------------------------------------------------------------------------


def _load(spec: str) -> tuple[str, dict]:
    label, _, path = spec.partition("=")
    with open(path) as f:
        return label, json.load(f)


def cmd_tables(args) -> None:
    out: list[str] = []

    if args.census:
        loaded = [_load(s) for s in args.census]
        out.append("### Census — theorems only (median, from the I3 encoding)\n")
        cols = ["nodes", "depth", "apps", "distinct_syms", "tele", "tele_t", "tele_i",
                "concl_arity", "inst_distinct"]
        out.append("| corpus · stratum | decls | " + " | ".join(cols) + " |")
        out.append("|---|---:|" + "---:|" * len(cols))
        for label, j in loaded:
            for st in ("phys", "math", "substrate"):
                key = f"{st}|theorem"
                d = j["dists"].get(key)
                if not d:
                    continue
                row = [f"{d[c]['median']:.0f}" for c in cols]
                out.append(
                    f"| {label} · {st} | {d['nodes']['n']:,} | " + " | ".join(row) + " |"
                )
        out.append("")
        out.append("### Census — all kinds (median), kept beside the claims table\n")
        out.append("| corpus · stratum | decls | " + " | ".join(cols) + " |")
        out.append("|---|---:|" + "---:|" * len(cols))
        for label, j in loaded:
            for st in ("phys", "math", "substrate"):
                d = j["dists"].get(f"{st}|all")
                if not d:
                    continue
                row = [f"{d[c]['median']:.0f}" for c in cols]
                out.append(
                    f"| {label} · {st} | {d['nodes']['n']:,} | " + " | ".join(row) + " |"
                )
        out.append("")

    if args.erasure:
        loaded = [_load(s) for s in args.erasure]
        out.append("### Hole density after each erasure (mean fraction of nodes holed)\n")
        out.append("| corpus (coverage) · stratum | sampled | " + " | ".join(LEVELS) + " |")
        out.append("|---|---:|" + "---:|" * len(LEVELS))
        for label, j in loaded:
            cov = j["closure"]["coverage"]
            for st, v in j["strata"].items():
                if not v.get("sampled"):
                    continue
                cells = [
                    f"{v['levels'][lv]['hole_fraction']['mean']:.3f}" for lv in LEVELS
                ]
                out.append(
                    f"| {label} ({cov:.2%}) · {st} | {v['sampled']:,} | "
                    + " | ".join(cells)
                    + " |"
                )
        out.append("")
        out.append("### Posting-key survival under the size floors (simulated, validated)\n")
        out.append(
            "| corpus · stratum | floors (closed/open/shape) | median concrete keys | "
            "zero-key decls | median shape keys | zero-shape-key decls |"
        )
        out.append("|---|---|---:|---:|---:|---:|")
        for label, j in loaded:
            for st, v in j["strata"].items():
                if not v.get("sampled"):
                    continue
                for tag, f in v["floor_sweep"].items():
                    n = v["sampled"]
                    out.append(
                        f"| {label} · {st} | {tag.replace('_', '/')} | "
                        f"{f['concrete_keys']['median']:.0f} | "
                        f"{f['decls_with_zero_concrete_keys']} ({100.0 * f['decls_with_zero_concrete_keys'] / n:.1f}%) | "
                        f"{f['shape_keys']['median']:.0f} | "
                        f"{f['decls_with_zero_shape_keys']} ({100.0 * f['decls_with_zero_shape_keys'] / n:.1f}%) |"
                    )
        out.append("")

    if args.differential:
        out.append("### `similar` against `similar_brute` — where recall is lost\n")
        out.append(
            "| corpus (coverage, n) · stratum | queries | truth | recall@50 | "
            "never proposed | buried | median candidates (raw / after floors) |"
        )
        out.append("|---|---:|---:|---:|---:|---:|---:|")
        for spec in args.differential:
            label, j = _load(spec)
            out.append(
                f"| {label} ({j['closure_coverage']:.2%}, {j['declarations']:,}) · "
                f"{j['stratum']} | {j['queries']} | {j['truth_entries']} | "
                f"{100.0 * j['recall_at_cut']:.1f}% | "
                f"{j['never_proposed']} ({j['never_proposed_pct_of_truth']:.1f}%) | "
                f"{j['buried']} ({j['buried_pct_of_truth']:.1f}%) | "
                f"{j['raw_candidate_set_size']['median']:.0f} / "
                f"{j['proposed_set_size']['median']:.0f} |"
            )
        out.append("")
        out.append("### Which retrieval source fires\n")
        out.append(
            "| corpus · stratum | candidates | via shape (A) | via subterm (B) | "
            "via shape-subterm (C) | queries reached by B |"
        )
        out.append("|---|---:|---:|---:|---:|---:|")
        for spec in args.differential:
            label, j = _load(spec)
            t = j.get("candidates_by_source", {})
            q = j.get("queries_reaching_source", {})
            tot = max(1, t.get("|total", 0))
            out.append(
                f"| {label} · {j['stratum']} | {t.get('|total', 0):,} | "
                f"{100.0 * t.get('shape', 0) / tot:.1f}% | "
                f"{100.0 * t.get('subterm', 0) / tot:.1f}% | "
                f"{100.0 * t.get('shape-subterm', 0) / tot:.1f}% | "
                f"{q.get('subterm', 0)}/{q.get('queries', 0)} |"
            )
        out.append("")

    if args.classes:
        out.append("### Equivalence classes (claims only) and motif families\n")
        out.append(
            "| corpus (coverage) | level | classes | members | largest | mean size |"
        )
        out.append("|---|---|---:|---:|---:|---:|")
        for spec in args.classes:
            label, j = _load(spec)
            for lvl, v in j["levels"].items():
                out.append(
                    f"| {label} ({j['closure_coverage']:.2%}) | {lvl} | {v['classes']:,} | "
                    f"{v['members']:,} | {v['largest']:,} | {v['mean_size']:.2f} |"
                )
        out.append("")

    text = "\n".join(out)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    print(text)


def cmd_build_closed(args) -> None:
    """Build a physics-anchored *closed* slice by BFS over `uses_statement`.

    A contingency for the full physlib closure extraction, and useful on its own. The erasure
    needs a head constant's signature, and the constants a statement mentions are exactly its
    `uses_statement`, so the transitive closure of that relation from the physics rows is the
    smallest slice on which every physics statement erases correctly. `Corpus.closure()` is
    still the gate — this is a construction, not a proof, and it is only usable if it measures
    above the 95% floor.

    Two passes, and no `json.loads` on the statement. A row averages 11 kB and the merged
    corpus is 485k rows; parsing every one into a dict is 12 GB of Python objects. The
    dependency edges are the last field of each row, so pass one slices them out of the raw
    line and interns the names.
    """
    deps: dict[str, tuple] = {}
    seeds: list[str] = []
    math_thms: list[str] = []
    intern = sys.intern

    def field(line: str, key: str) -> str | None:
        k = f'"{key}":"'
        i = line.find(k)
        if i < 0:
            return None
        i += len(k)
        return line[i : line.find('"', i)]

    n_rows = 0
    with open(args.source, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            n_rows += 1
            name = field(line, "name")
            if name is None:
                continue
            name = intern(name)
            if name in deps:
                continue
            mod = field(line, "module") or ""
            kind = field(line, "kind") or ""
            i = line.rfind('"uses_statement":')
            us: tuple = ()
            if i >= 0:
                tail = line[i + len('"uses_statement":') :].rstrip().rstrip("}")
                try:
                    us = tuple(intern(x) for x in json.loads(tail))
                except Exception:
                    us = ()
            deps[name] = us
            root = module_root(mod)
            if root in PHYS_ROOTS:
                seeds.append(name)
            elif root in MATH_ROOTS and kind == "theorem":
                math_thms.append(name)

    print(f"read {n_rows:,} rows, {len(deps):,} distinct names, {len(seeds):,} seeds",
          flush=True)

    def close(start, keep):
        stack = list(start)
        while stack:
            n = stack.pop()
            if n in keep:
                continue
            keep.add(n)
            for d in deps.get(n, ()):
                if d not in keep:
                    stack.append(d)
        return keep

    keep = close(seeds, set())
    print(f"closure of the seeds: {len(keep):,}", flush=True)
    extra = [n for n in math_thms if n not in keep][: args.extra_math]
    keep = close(extra, keep)
    print(f"after {len(extra):,} comparison theorems and their closure: {len(keep):,}",
          flush=True)

    written = 0
    seen: set[str] = set()
    with open(args.source, "r", encoding="utf-8") as f, open(args.out, "w") as g:
        for line in f:
            name = field(line, "name")
            if name is None or name not in keep or name in seen:
                continue
            seen.add(name)
            g.write(line)
            written += 1
    print(f"wrote {written:,} rows to {args.out}", flush=True)
    print("now check it: Corpus.closure() must be >= 0.95", flush=True)


def cmd_full(args) -> None:
    """Everything that needs a `Corpus`, from one load.

    The whole-Mathlib closure is 4.8 GB on disk and about 11 GB resident, and the physics
    closure is the same order. Loading it once per question is both minutes of wall clock
    and a second copy of it in memory on a machine other agents are using, so the erasure
    census, the class census and the retrieval differential all run off one handle.
    """
    import atlas

    t0 = time.time()
    print(f"[load] {args.slice}", file=sys.stderr, flush=True)
    c = atlas.Corpus.load(args.slice)
    print(f"[loaded] {len(c):,} declarations in {time.time() - t0:.0f}s",
          file=sys.stderr, flush=True)

    class _A:
        pass

    for st in args.strata.split(","):
        a = _A()
        a.slice, a.out, a.sample, a.seed = args.slice, None, args.sample, args.seed
        a.strata, a.stratum = st, st
        a.max_stmt_bytes = args.max_stmt_bytes
        a.level, a.k, a.cut, a.wide = args.level, args.k, args.cut, args.wide
        a.sweep_common = [2, 4, 6, 9, 14]
        a.sweep_retention = [0.10, 0.20, 0.30, 0.45, 0.60]
        for what, fn, out in (
            ("erasure", cmd_erasure, f"{args.prefix}-erasure-{st}.json"),
            ("differential", cmd_differential, f"{args.prefix}-diff-{st}.json"),
        ):
            a.out = out
            if os.path.exists(out) and not args.force:
                print(f"[skip] {out} exists", file=sys.stderr, flush=True)
                continue
            print(f"[{st}] {what}", file=sys.stderr, flush=True)
            a.sample = args.sample if what == "erasure" else args.queries
            try:
                fn(a, corpus=c)
            except Exception as e:
                print(f"[{st}] {what} FAILED: {e}", file=sys.stderr, flush=True)
    a = _A()
    a.slice, a.out = args.slice, f"{args.prefix}-classes.json"
    a.top_classes, a.min_family, a.min_size, a.top = 200, 3, 6, 400
    if args.classes:
        try:
            cmd_classes(a, corpus=c)
        except Exception as e:
            print(f"[classes] FAILED: {e}", file=sys.stderr, flush=True)
    print(f"[done] {time.time() - t0:.0f}s", file=sys.stderr, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("census", help="Q1: streaming structural census (no Corpus load)")
    p.add_argument("slice")
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--progress", action="store_true")
    p.add_argument("--stride", type=int, default=1,
                   help="walk every Nth row; composition is still counted on every row")
    p.set_defaults(fn=cmd_census)

    p = sub.add_parser("erasure", help="Q1/Q2: hole density and simulated posting floors")
    p.add_argument("slice")
    p.add_argument("--out", required=True)
    p.add_argument("--sample", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260804)
    p.add_argument("--strata", default="phys,math,substrate")
    p.add_argument(
        "--max-stmt-bytes", type=int, default=262_144, dest="max_stmt_bytes",
        help="skip and count declarations whose encoding exceeds this",
    )
    p.set_defaults(fn=cmd_erasure)

    p = sub.add_parser("check", help="control: is the floor simulation faithful?")
    p.add_argument("slice")
    p.add_argument("--min-family", type=int, default=3, dest="min_family")
    p.add_argument("--min-size", type=int, default=6, dest="min_size")
    p.add_argument("--top", type=int, default=200)
    p.add_argument("--decls", type=int, default=40)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("differential", help="Q3: similar vs similar_brute")
    p.add_argument("slice")
    p.add_argument("--out", required=True)
    p.add_argument("--sample", type=int, default=60)
    p.add_argument("--seed", type=int, default=20260804)
    p.add_argument("--stratum", default=None)
    p.add_argument("--level", default="carriers")
    p.add_argument("--k", type=int, default=5, help="truth depth, as recallcheck.rs uses")
    p.add_argument("--cut", type=int, default=50, help="the ranked cut recall is at")
    p.add_argument("--wide", type=int, default=1_000_000)
    p.add_argument(
        "--max-stmt-bytes", type=int, default=262_144, dest="max_stmt_bytes",
        help="skip and count queries whose encoding exceeds this",
    )
    p.add_argument("--sweep-common", type=int, nargs="*", dest="sweep_common",
                   default=[2, 4, 6, 9, 14])
    p.add_argument("--sweep-retention", type=float, nargs="*", dest="sweep_retention",
                   default=[0.10, 0.20, 0.30, 0.45, 0.60])
    p.set_defaults(fn=cmd_differential)

    p = sub.add_parser("reachability",
                       help="do a query and its true neighbour share any indexed key?")
    p.add_argument("slice")
    p.add_argument("--out", required=True)
    p.add_argument("--sample", type=int, default=80)
    p.add_argument("--seed", type=int, default=20260804)
    p.add_argument("--stratum", default=None)
    p.add_argument("--level", default="carriers")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--wide", type=int, default=1_000_000)
    p.add_argument("--max-stmt-bytes", type=int, default=262_144, dest="max_stmt_bytes")
    p.set_defaults(fn=cmd_reachability)

    p = sub.add_parser("classes", help="equivalence-class and motif census")
    p.add_argument("slice")
    p.add_argument("--out", required=True)
    p.add_argument("--top-classes", type=int, default=200, dest="top_classes")
    p.add_argument("--min-family", type=int, default=3, dest="min_family")
    p.add_argument("--min-size", type=int, default=6, dest="min_size")
    p.add_argument("--top", type=int, default=400)
    p.set_defaults(fn=cmd_classes)

    p = sub.add_parser("separator", help="Q4: a name-free statistic, held out and shuffled")
    p.add_argument("census", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--min-decls", type=int, default=20, dest="min_decls")
    p.add_argument("--seed", type=int, default=20260804)
    p.add_argument("--shuffles", type=int, default=200)
    p.add_argument("--subtrees", type=int, default=8,
                   help="how many Mathlib subtrees the subfield control compares")
    p.add_argument("--min-subtree", type=int, default=12, dest="min_subtree")
    p.set_defaults(fn=cmd_separator)

    p = sub.add_parser("tables", help="render the markdown tables from the JSON outputs")
    p.add_argument("--census", nargs="*", default=[], metavar="LABEL=PATH")
    p.add_argument("--erasure", nargs="*", default=[], metavar="LABEL=PATH")
    p.add_argument("--differential", nargs="*", default=[], metavar="LABEL=PATH")
    p.add_argument("--classes", nargs="*", default=[], metavar="LABEL=PATH")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_tables)

    p = sub.add_parser("build-closed",
                       help="a physics-anchored closed slice, by BFS over uses_statement")
    p.add_argument("source", help="a concatenation of a Mathlib closure and a physics slice")
    p.add_argument("--out", required=True)
    p.add_argument("--extra-math", type=int, default=60_000, dest="extra_math",
                   help="Mathlib theorems to add as a comparison stratum, with their closure")
    p.set_defaults(fn=cmd_build_closed)

    p = sub.add_parser("full", help="erasure + differential + classes, from one load")
    p.add_argument("slice")
    p.add_argument("--prefix", required=True)
    p.add_argument("--strata", default="phys,math,substrate")
    p.add_argument("--sample", type=int, default=1500)
    p.add_argument("--queries", type=int, default=120)
    p.add_argument("--seed", type=int, default=20260804)
    p.add_argument("--level", default="carriers")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--cut", type=int, default=50)
    p.add_argument("--wide", type=int, default=1_000_000)
    p.add_argument("--max-stmt-bytes", type=int, default=262_144, dest="max_stmt_bytes")
    p.add_argument("--classes", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_full)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
