#!/usr/bin/env python3
"""What physlib asserts but does not prove — a map of where formalized physics stops.

Run: `uv run scripts/phys-frontier.py <mode> [--slice PATH]`, modes below or `all`.

## The question

physlib is young. The premise of this study was that it is "full of `axiom`s and `sorry`s",
so a census of those would draw the frontier of formalized physics. The premise is wrong in
its first half and the measurement says so, which is why the census is run structurally —
off the extractor's `kind` field and the citation graph — and never off names or source
text.

## Pass conditions, fixed before the runs they judge

**Q1 honesty census.** A useful answer names the unproved assertions, their subfields, and
their load — how much of the corpus rests on each. It is a *failure of the instrument*, not
a clean bill of health, if `honesty([])` (the empty whitelist, which allows nothing) returns
the same set as `honesty(None)` (which allows Lean's three): an empty whitelist must be
strictly louder on any corpus that uses classical logic at all. That comparison is run as
the negative control, on physlib and on a Mathlib slice where the control is known to fire.

**Q2 orphans.** A definition no theorem transitively rests on. Reported at two lenses
(`statement` = no theorem *states* anything involving it; `both` = no theorem mentions it
even inside a proof) because they are different claims, and stratified by a *structural*
derivativeness score rather than filtered by a name blocklist — Lean emits `X.recOn` for
every inductive and those are not physics's to-do list. The stratification is validated by
ROC AUC against the name blocklist used as held-out labels, never as an input (§3b's
method); below AUC 0.75 the stratification is not trusted and the unstratified counts are
what gets reported. The per-subfield ranking needs a null: orphan labels are permuted across
definitions 1,000 times and the observed spread must exceed the 95th percentile, or
"subfield X has the most orphans" is just "subfield X has the most definitions".

**Q3 asserted here, proved there.** For each declaration resting on an unproved assertion,
is the same statement proved elsewhere in the corpus? Answered by equality of the erased
statement (`equivalent`) at every level, and by `transport` along dictionary rows. A good
answer is a named pair. §24 measured `transport` as producing zero open targets on physlib
and 98% images equal to the subject; the pass condition here is only that the measurement is
*repeated* and reported as it comes out.

**Genre 4, marker types (`mode=informal`).** Added after the census showed genres 1-3 are
small. A constant declared in the library's own metaprogramming layer that appears in the
*types* of declarations elsewhere is a marker, and what carries it asserts something the
kernel does not check. Reported with the discriminator that makes the reading falsifiable:
how many carriers anything else cites. A marker whose carriers are cited is a data structure
being used, not a wall of assertions — `Physlib.NoteFile` (3 of 4 cited) against
`InformalLemma` (1 of 45).

**Q4 shape of an assertion.** Three arms, because the literal question has no positives:

* *axioms vs theorems* — needs `kind == "axiom"` rows. If there are none the arm is
  UNRUNNABLE and reported as such, with a control on a corpus where the extractor does emit
  that kind, so "no axioms" is a fact about physlib and not about the extractor.
* *`sorry`-carrying vs proved theorems* — few positives; scored by ROC AUC against an exact
  permutation null (1,000 label shuffles). Judged **family-wise**: 21 features tested at
  α = 0.05 produce one hit by chance, and an earlier version of this script reported exactly
  that one hit as a finding. The statistic is `max_f |AUC_f - 0.5|` under a single shared
  shuffle, which also keeps the features' correlation. Reported with its power, so "no
  signal" is a bound rather than a shrug.
* *orphan vs cited definitions* — well powered. A logistic model on **statement-shape
  features only**, fitted on half the definitions and scored on the held-out half. Graph
  features are excluded by construction: the label *is* a graph property, so in-degree would
  be the label wearing a hat. Pass iff held-out AUC exceeds the 95th percentile of 20
  refits on permuted labels.

## Corpora

    /tmp/atlas-physlib.jsonl              14,563 decls, closure 12.39%   graph-only results
    /tmp/atlas-phys-frontier-closed.jsonl 17,067 decls, closure 98.91%   erasure results
    /tmp/atlas-phys-frontier-theories.jsonl  the same, modules re-rooted so that a physics
                                          subfield is a theory to `dictionary`/`frontier`

The second is built by `--reduce-from /tmp/atlas-physlib-closure.jsonl` (the full
`Physlib QuantumInfo` extraction, 495,067 rows, 5.4 GB) and is 3.4% of its size, because the
statement closure of a library is shallow. The third exists because `dict.rs::theory_of` is
depth 1 outside `Mathlib`, so `"Physlib.Relativity"` names no theory and `dictionary`
returns **zero rows with no error** — re-rooting to `Relativity.*` is the only way to ask
those two queries about physics subfields.

## Which results survive an unclosed slice

`Corpus.closure()` on `/tmp/atlas-physlib.jsonl` is **12.39%**: it is `--local`-shaped, so the
constants its statements are headed by are mostly absent (§31, §32).

* **graph-only, valid on either slice** — the kind census, `honesty`, `impact`, orphan
  reachability, the derivativeness stratification, and every feature this script derives
  from the I3 encoding (the encoding is *in* the row; nothing is looked up).
* **erasure-dependent, closure required** — `skeleton`, `equivalent`/`classes` at
  `instances` and `carriers`, `similar`, `dictionary`, `transport`, `frontier`. At `exact`,
  `presentation` and `shape` the erasure consults no signature, so those are graph-only too;
  the script runs `equivalent` at every level and labels each.

Every mode prints `[graph-only]` or `[erasure]` beside its results, and `--slice` is echoed
into the output so a number can never be quoted without the corpus it came from.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import pathlib
import random
import sys
import time

try:
    import atlas as fa
except ImportError:  # pragma: no cover
    sys.exit("atlas is not importable — run under `uv run`")

PHYSLIB = "/tmp/atlas-physlib.jsonl"
MATHLIB = "/tmp/mathlib-algebra.jsonl"

# Lean's own axioms plus the compiler's, as observed in a Mathlib import closure. Used only
# as *seeds for `impact`*, which accepts a name the slice does not contain — that is the
# whole point here, since an unclosed slice contains none of them.
LEAN_AXIOMS = (
    "propext", "Classical.choice", "Quot.sound", "sorryAx",
    "Lean.ofReduceBool", "Lean.ofReduceNat", "Lean.trustCompiler", "Quot.lcInv",
    "isScalarObj", "lcAny", "lcCast", "lcErased", "lcProof", "lcUnreachable", "lcVoid",
)
DEFAULT_WHITELIST = ("propext", "Classical.choice", "Quot.sound")

# Definition-like kinds. `theorem` is excluded (it is a proof, not a concept) and so are
# `recursor`/`constructor`, which are the elaborator's, not the author's.
DEF_KINDS = ("def", "inductive", "opaque", "structure")

# ---------------------------------------------------------------------------
# Name-based derivativeness labels — HELD-OUT VALIDATION ONLY, never an input.
# Copied from scripts/derivativeness.py so the two agree on what is being validated.
# ---------------------------------------------------------------------------
DERIVED_SUFFIX = (
    ".eq_def", ".below", ".ibelow", ".brecOn", ".binductionOn", ".rec", ".recOn",
    ".casesOn", ".noConfusion", ".noConfusionType", ".toCtorIdx", ".ctorIdx",
    ".sizeOf_spec", ".injEq", ".inj", ".induct", ".fun_cases", ".elim", ".ctorElim",
    ".ctorElimType", ".ofNat", ".ext", ".ext_iff", ".congr_simp",
)
DERIVED_SUB = ("._", ".match_", ".proof_", ".eq_", "_example", ".«", ".mk.")


def labelled_derived(n: str) -> bool:
    return n.startswith("_") or n.endswith(DERIVED_SUFFIX) or any(s in n for s in DERIVED_SUB)


def subfield(module: str) -> str:
    """A physics subfield is a depth-2 module prefix (`Physlib.QFT`, `QuantumInfo.Entropy`).

    `dictionary`'s convention — depth 2 under `Mathlib`, depth 1 elsewhere — puts all of
    physlib in one theory, which is the wrong grain for a question about subfields.
    """
    return ".".join(module.split(".")[:2])


def theory(module: str) -> str:
    """`dict.rs::theory_of`, which `dictionary` and `frontier` key on: depth 2 under
    `Mathlib`, depth 1 elsewhere. All of physlib is therefore **one theory** to those two
    queries, which is why this study re-roots the modules before calling them."""
    return ".".join(module.split(".")[:2 if module.startswith("Mathlib.") else 1])


# ---------------------------------------------------------------------------
# The I3 encoding, scanned for shape features.
#
# A scan rather than a parse, for the reason `scripts/atlas_encoding.py` gives: names and
# string literals carry a byte-length prefix, so skipping them by that prefix makes a `c(`
# inside a name unforgeable. Everything here works on `bytes`; `c(3:ℝ,0)` is three bytes and
# one character, and a `str` scan would miscount it.
# ---------------------------------------------------------------------------
TAG = b"atlas-stmt-v1;"
BI = {0x64: "default", 0x69: "implicit", 0x74: "inst", 0x73: "strict"}


def scan(enc: str) -> dict:
    """Structural features of one statement encoding. No corpus lookup, no names used."""
    buf = enc.encode("utf-8")
    if buf.startswith(TAG):
        buf = buf[len(TAG):]
    n = len(buf)
    f = collections.Counter()
    consts: collections.Counter = collections.Counter()
    depth = 0
    maxdepth = 0
    i = 0
    # Binders of the *root* spine, in order: the declared interface a caller must supply.
    root_binders: list[str] = []
    at_root = True
    root_depth = 0
    while i < n:
        ch = buf[i]
        if ch == 0x63 or ch == 0x6A:  # 'c(' const, 'j(' proj
            if i + 1 < n and buf[i + 1] == 0x28:
                ln, after = _read_len(buf, i + 2)
                if ln is None:
                    i += 1
                    continue
                consts[buf[after:after + ln].decode("utf-8", "replace")] += 1
                f["const" if ch == 0x63 else "proj"] += 1
                depth += 1
                maxdepth = max(maxdepth, depth)
                at_root = False
                i = after + ln
                continue
        if ch == 0x74:  # 't' — string literal iff digits+':' follow
            ln, after = _read_len(buf, i + 1)
            if ln is not None:
                f["lit_str"] += 1
                at_root = False
                i = after + ln
                continue
        if (ch == 0x70 or ch == 0x6C) and i + 2 < n and buf[i + 2] == 0x28 and buf[i + 1] in BI:
            kind = "pi" if ch == 0x70 else "lam"
            f[f"{kind}_{BI[buf[i + 1]]}"] += 1
            f[kind] += 1
            if at_root and kind == "pi":
                root_binders.append(BI[buf[i + 1]])
                root_depth += 1
            depth += 1
            maxdepth = max(maxdepth, depth)
            i += 3
            continue
        if ch == 0x61 and i + 1 < n and buf[i + 1] == 0x28:  # 'a('
            f["app"] += 1
            depth += 1
            maxdepth = max(maxdepth, depth)
            at_root = False
            i += 2
            continue
        if ch == 0x73 and i + 1 < n and buf[i + 1] == 0x28:  # 's(' sort
            f["sort"] += 1
            at_root = False
            i += 2
            depth += 1
            maxdepth = max(maxdepth, depth)
            continue
        if ch == 0x65 and i + 1 < n and buf[i + 1] == 0x28:  # 'e(' let
            f["let"] += 1
            at_root = False
            i += 2
            depth += 1
            maxdepth = max(maxdepth, depth)
            continue
        if ch == 0x62 and i + 1 < n and 0x30 <= buf[i + 1] <= 0x39:  # 'b' bvar
            f["bvar"] += 1
            at_root = False
            j = i + 1
            while j < n and 0x30 <= buf[j] <= 0x39:
                j += 1
            i = j
            continue
        if ch == 0x6E and i + 1 < n and 0x30 <= buf[i + 1] <= 0x39:  # 'n' nat lit
            f["lit_nat"] += 1
            at_root = False
            j = i + 1
            while j < n and 0x30 <= buf[j] <= 0x39:
                j += 1
            i = j
            continue
        if ch == 0x29:  # ')'
            depth -= 1
        i += 1
    nodes = sum(f[k] for k in ("const", "proj", "app", "sort", "let", "bvar", "lit_nat",
                               "lit_str", "pi", "lam"))
    return {
        "bytes": len(buf),
        "nodes": nodes,
        "maxdepth": maxdepth,
        "consts_total": f["const"],
        "consts_distinct": len(consts),
        "apps": f["app"],
        "sorts": f["sort"],
        "bvars": f["bvar"],
        "lits": f["lit_nat"] + f["lit_str"],
        "projs": f["proj"],
        "lets": f["let"],
        "pis": f["pi"],
        "lams": f["lam"],
        "pi_default": f["pi_default"],
        "pi_implicit": f["pi_implicit"],
        "pi_inst": f["pi_inst"],
        "pi_strict": f["pi_strict"],
        "root_binders": len(root_binders),
        "root_inst": sum(1 for b in root_binders if b == "inst"),
        "root_implicit": sum(1 for b in root_binders if b == "implicit"),
        "root_default": sum(1 for b in root_binders if b == "default"),
        "const_names": consts,
    }


def _read_len(buf: bytes, i: int):
    j = i
    while j < len(buf) and 0x30 <= buf[j] <= 0x39:
        j += 1
    if j == i or j >= len(buf) or buf[j] != 0x3A:
        return None, i
    return int(buf[i:j]), j + 1


# ---------------------------------------------------------------------------
# Graph helpers. All of these read `uses_statement` / `uses_proof` as extracted, so they are
# valid on an unclosed slice: an edge to a constant with no row is still an edge.
# ---------------------------------------------------------------------------
def targets(d, lens: str) -> list[str]:
    if lens == "statement":
        return d.uses_statement
    if lens == "proof":
        return d.uses_proof
    return d.uses_statement + d.uses_proof


def reachable_from(decls: dict, seeds, lens: str) -> set[str]:
    """Everything transitively cited by `seeds`, excluding the seeds themselves unless cited.

    One multi-source DFS, not one BFS per node: "does *any* theorem rest on `d`" is the
    forward reachability of the theorem set, and asking it per definition would be 4,681
    traversals of the same graph.
    """
    seen: set[str] = set()
    stack: list[str] = []
    for s in seeds:
        for t in targets(decls[s], lens):
            if t not in seen:
                seen.add(t)
                stack.append(t)
    while stack:
        d = decls.get(stack.pop())
        if d is None:
            continue
        for t in targets(d, lens):
            if t not in seen:
                seen.add(t)
                stack.append(t)
    return seen


def derivativeness(decls: dict) -> dict[str, float]:
    """`skel/index.rs::derivativeness`, reimplemented over the same three graph signals.

    Reimplemented rather than called because the engine only exposes it multiplied into a
    `similar` score, and `similar` needs the skeleton index — which needs a closed slice.
    Validated against the engine's published AUC in `mode=orphans`.
    """
    names = list(decls)
    proof_len = {n: len(decls[n].uses_proof) for n in names}
    in_deg = collections.Counter()
    struct_frac = {}
    for n in names:
        cites = decls[n].uses_proof
        structural = 0
        for u in cites:
            d = decls.get(u)
            if d is None:
                continue
            in_deg[u] += 1
            if d.kind in ("recursor", "constructor"):
                structural += 1
        struct_frac[n] = structural / max(len(cites), 1)

    def ranks(vals: dict, ascending: bool) -> dict:
        order = sorted(names, key=lambda n: vals[n], reverse=not ascending)
        out, i, m = {}, 0, len(names)
        while i < m:
            j = i
            while j + 1 < m and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 / max(m - 1, 1)
            for k in order[i:j + 1]:
                out[k] = avg
            i = j + 1
        return out

    r_len = ranks(proof_len, False)
    r_deg = ranks({n: in_deg[n] for n in names}, False)
    r_str = ranks(struct_frac, True)
    return {n: min(max((r_len[n] + r_deg[n] + r_str[n]) / 3.0, 0.0), 1.0) for n in names}


# ---------------------------------------------------------------------------
# Statistics: AUC, permutation nulls, logistic regression. Pure Python — the environment has
# no numpy and `uv sync` is not this script's to run.
# ---------------------------------------------------------------------------
def auc(scores: list[float], labels: list[int]) -> float:
    """Rank-based ROC AUC with tie correction. 0.5 is chance in either direction."""
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    rank = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in order[i:j + 1]:
            rank[k] = r
        i = j + 1
    s = sum(rank[i] for i in range(len(labels)) if labels[i])
    return (s - pos * (pos + 1) / 2.0) / (pos * neg)


def ranks_of(scores: list[float]) -> list[float]:
    """Tie-averaged ranks, so an AUC under any relabelling is a rank sum away."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    rank = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in order[i:j + 1]:
            rank[k] = r
        i = j + 1
    return rank


def auc_from_ranks(rank: list[float], pos_idx, k: int) -> float:
    n = len(rank)
    return (sum(rank[i] for i in pos_idx) - k * (k + 1) / 2.0) / (k * (n - k))


def permutation_null(scores: list[float], labels: list[int], trials: int, seed: int):
    """Exact permutation null, via the observation that ranks do not move under relabelling.

    Re-sorting per trial is the obvious implementation and is 600x slower here; with 21
    features x 1,000 trials that difference is what decides whether a family-wise test gets
    run at all, and a per-feature test alone would report the one hit in twenty that chance
    guarantees.
    """
    rng = random.Random(seed)
    rank = ranks_of(scores)
    n, k = len(labels), sum(labels)
    out = [auc_from_ranks(rank, rng.sample(range(n), k), k) for _ in range(trials)]
    out.sort()
    return out


def familywise_null(cols: dict, labels: list[int], trials: int, seed: int):
    """The null of `max_f |AUC_f - 0.5|` over a family of features, under one shared shuffle.

    Sharing the shuffle across features preserves their correlation, which a per-feature
    null discards — and these features are heavily correlated (`nodes`, `bytes`, `apps` all
    measure size).
    """
    rng = random.Random(seed)
    rk = {f: ranks_of(v) for f, v in cols.items()}
    n, k = len(labels), sum(labels)
    out = []
    for _ in range(trials):
        idx = rng.sample(range(n), k)
        out.append(max(abs(auc_from_ranks(rk[f], idx, k) - 0.5) for f in rk))
    out.sort()
    return out


def pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = min(int(p * len(sorted_vals)), len(sorted_vals) - 1)
    return sorted_vals[k]


def logistic(X: list[list[float]], y: list[int], iters: int = 400, lr: float = 0.5,
             l2: float = 1e-3) -> list[float]:
    """Standardised logistic regression by full-batch gradient descent, with an intercept."""
    m, k = len(X), len(X[0])
    w = [0.0] * (k + 1)
    for _ in range(iters):
        g = [0.0] * (k + 1)
        for i in range(m):
            z = w[0] + sum(w[j + 1] * X[i][j] for j in range(k))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            e = p - y[i]
            g[0] += e
            for j in range(k):
                g[j + 1] += e * X[i][j]
        w[0] -= lr * g[0] / m
        for j in range(k):
            w[j + 1] -= lr * (g[j + 1] / m + l2 * w[j + 1])
    return w


def standardise(rows: list[list[float]]):
    k = len(rows[0])
    mu = [sum(r[j] for r in rows) / len(rows) for j in range(k)]
    sd = []
    for j in range(k):
        v = sum((r[j] - mu[j]) ** 2 for r in rows) / max(len(rows) - 1, 1)
        sd.append(math.sqrt(v) or 1.0)
    return mu, sd


def apply_std(rows, mu, sd):
    return [[(r[j] - mu[j]) / sd[j] for j in range(len(mu))] for r in rows]


def in_test_half(name: str, salt: str = "phys-frontier") -> bool:
    """A deterministic split. Python's `hash` is randomised per process; md5 is not."""
    return hashlib.md5((salt + name).encode()).digest()[0] & 1 == 1


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
def reduce_closure(src: str, dst: str, roots: tuple[str, ...] = ("Physlib", "QuantumInfo")):
    """Cut a full closure down to the roots plus everything their *statements* cite.

    A full `Physlib QuantumInfo` closure is 495,067 rows and ~7.7 GB; the statement closure
    of the two libraries is a fraction of that and is still closed, which is the property
    that matters (§31). This *grows* a 12.39% slice rather than shrinking a good one, so the
    direction is the safe one — but it is still a restriction, so `mode_census` on the result
    must report >= 95% before anything erasure-dependent is run on it.

    Two string-scanning passes rather than `json.loads`: the `stmt` field is most of the
    bytes and none of the information needed to compute the closure.
    """
    def field(line: str, key: str):
        k = f'"{key}":'
        i = line.find(k)
        return -1 if i < 0 else i + len(k)

    deps: dict[str, list[str]] = {}
    seeds: list[str] = []
    t = time.time()
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            i = field(line, "name")
            if i < 0 or line[i] != '"':
                continue
            j = line.index('"', i + 1)
            name = line[i + 1:j]
            u = field(line, "uses_statement")
            us = json.loads(line[u:line.index("]", u) + 1]) if u > 0 else []
            deps[name] = us
            m = field(line, "module")
            if m > 0 and line[m] == '"':
                mod = line[m + 1:line.index('"', m + 1)]
                if mod.split(".")[0] in roots:
                    seeds.append(name)
    print(f"  pass 1: {len(deps)} rows, {len(seeds)} under {roots}, {time.time() - t:.0f}s")
    keep, stack = set(seeds), list(seeds)
    while stack:
        for d in deps.get(stack.pop(), ()):
            if d not in keep:
                keep.add(d)
                stack.append(d)
    print(f"  statement closure: {len(keep)} declarations")
    n = 0
    with open(src, encoding="utf-8") as fh, open(dst, "w", encoding="utf-8") as out:
        for line in fh:
            i = field(line, "name")
            if i < 0 or line[i] != '"':
                continue
            if line[i + 1:line.index('"', i + 1)] in keep:
                out.write(line)
                n += 1
    print(f"  wrote {n} rows to {dst} in {time.time() - t:.0f}s total")


def load(path: str):
    t = time.time()
    c = fa.Corpus.load(path)
    decls = {n: c.get(n) for n in c.names()}
    print(f"  loaded {path}: {len(c)} declarations in {time.time() - t:.1f}s")
    return c, decls


def mode_census(c, decls, path, out):
    print(f"\n=== CENSUS [graph-only] — {path}")
    kinds = collections.Counter(d.kind for d in decls.values())
    print(f"  kinds: {dict(kinds.most_common())}")
    subs = collections.Counter(subfield(d.module) for d in decls.values())
    per: dict = collections.defaultdict(collections.Counter)
    for d in decls.values():
        per[subfield(d.module)][d.kind] += 1
    print(f"  subfields: {len(subs)}")
    for s, n in subs.most_common(40):
        k = per[s]
        print(f"    {s:34s} {n:6d}  thm {k['theorem']:5d}  def {k['def']:5d}"
              f"  thm/def {k['theorem'] / max(k['def'], 1):5.2f}")
    # `opaque` is the third genre of assertion after `axiom` and `sorry`: a constant whose
    # type is checked and whose value is sealed. Not unsound, but nothing can be proved
    # about it by unfolding, so it belongs in a census of what a library asserts.
    op = sorted(x for x, d in decls.items() if d.kind == "opaque")
    print(f"  opaque (value sealed): {len(op)}")
    for x in op[:25]:
        print(f"    {decls[x].module}  {x}")
    kh, uh, cov, worst = c.closure(top=8)
    print(f"  closure: {cov * 100:.2f}%  known heads {kh}  unknown {uh}")
    print(f"  worst missing: {worst}")
    out["census"] = {"kinds": dict(kinds), "subfields": dict(subs), "closure": cov,
                     "n": len(decls)}
    return out


def mode_honesty(c, decls, path, out):
    print(f"\n=== Q1 HONESTY [graph-only] — {path}")
    n = len(decls)
    axioms = [x for x, d in decls.items() if d.kind == "axiom"]
    print(f"  declarations of kind 'axiom' in this slice: {len(axioms)}")
    if axioms:
        print(f"    {axioms[:20]}")

    default = c.honesty()
    empty = c.honesty([])
    print(f"  honesty(default whitelist): {len(default)} findings "
          f"({100 * len(set(w for w, _ in default)) / n:.2f}% of the corpus)")
    print(f"  honesty([]) NEGATIVE CONTROL: {len(empty)} findings")
    louder = len(empty) > len(default)
    print(f"  control fires (empty whitelist strictly louder): {louder}"
          f"{'' if louder else '   <-- INSTRUMENT FAILURE'}")

    by_axiom = collections.Counter(y for _, y in default)
    print(f"  by axiom: {by_axiom.most_common()}")
    who = sorted(set(w for w, _ in default))
    print(f"  the findings, by subfield:")
    bysub = collections.Counter(subfield(decls[w].module) for w in who if w in decls)
    for s, k in bysub.most_common():
        tot = sum(1 for x in decls if subfield(decls[x].module) == s)
        print(f"    {s:34s} {k:3d} / {tot:5d}  ({100 * k / tot:.2f}%)")

    # Direct vs transitive: how far does an unproved assertion travel?
    direct = [x for x, d in decls.items()
              if "sorryAx" in d.uses_proof or "sorryAx" in d.uses_statement]
    sorry_trans = c.impact("sorryAx", "proof")
    print(f"  sorryAx: {len(direct)} direct citers, {len(sorry_trans)} transitive — "
          f"contagion {len(sorry_trans) / max(len(direct), 1):.2f}x")
    print("  load-bearing (transitive impact of each directly-unproved declaration):")
    load_rank = sorted(((len(c.impact(x, "both")), x) for x in direct), reverse=True)
    for k, x in load_rank:
        print(f"    {k:5d}  {decls[x].kind:9s} {x}")

    # What the whitelist *would* have caught if the slice contained the axioms' rows.
    # `impact` takes an out-of-slice seed, so this is answerable where `honesty` is not.
    print("  what an empty whitelist should have found (impact of each Lean axiom, "
          "proof lens):")
    should = set()
    for a in LEAN_AXIOMS:
        imp = c.impact(a, "proof")
        if imp:
            print(f"    {a:22s} {len(imp):6d}  ({100 * len(imp) / n:5.2f}%)  "
                  f"in slice: {c.get(a) is not None}")
            should |= set(imp)
    print(f"  union: {len(should)} declarations ({100 * len(should) / n:.2f}%) rest on some "
          f"axiom; honesty([]) reported {len(set(w for w, _ in empty))}")
    out["honesty"] = {
        "n": n, "axiom_kind_rows": len(axioms), "default": len(default), "empty": len(empty),
        "control_fires": louder, "direct": len(direct), "transitive": len(who),
        "findings": [[w, y] for w, y in default],
        "load": [[k, x] for k, x in load_rank],
        "should_find_union": len(should),
        "axiom_impacts": {a: len(c.impact(a, "proof")) for a in LEAN_AXIOMS},
    }
    return out


def mode_informal(c, decls, path, out):
    """A fourth genre of assertion: a declaration whose *type* is a marker.

    Found by asking the graph which constants statements instantiate most — `walls` under
    the statement lens — and then reading off which of those are marker types, rather than
    by searching for a command name. A declaration of type `Informal.Lemma` asserts a claim
    in prose and proves nothing; it is neither an axiom nor a `sorry`, so §2 cannot see it.
    """
    print(f"\n=== ASSERTION GENRE 4: MARKER TYPES [graph-only] — {path}")
    # The rule, structural: a constant declared in the library's own metaprogramming layer
    # that appears in the *types* of declarations elsewhere in the library is a marker.
    # Citers inside the marker's own module are excluded — those are the elaborator's
    # accessors and recursors for the type itself, not assertions carrying it. Ranking by
    # `walls` alone misses these entirely: the largest marker here has 58 citers against a
    # 208 cutoff for the corpus's top 60 constants.
    rev: dict = collections.defaultdict(list)
    rev_both: dict = collections.defaultdict(list)
    for x, d in decls.items():
        for u in set(d.uses_statement):
            rev[u].append(x)
        for u in set(d.uses_statement) | set(d.uses_proof):
            rev_both[u].append(x)
    out["informal"] = {"markers": {}}
    total = 0
    for name, d in sorted(decls.items()):
        if ".Meta." not in d.module and not d.module.endswith(".Meta"):
            continue
        users = sorted(x for x in rev.get(name, []) if decls[x].module != d.module)
        if not users:
            continue
        bysub = collections.Counter(subfield(decls[x].module) for x in users)
        bykind = collections.Counter(decls[x].kind for x in users)
        # A marker's carriers are assertions only if nothing rests on them; if theorems
        # cite them they are ordinary data structures being used, and the reading is wrong.
        cited = sum(1 for x in users if rev_both.get(x))
        print(f"  MARKER {name}  ({d.kind}, {d.module})")
        print(f"    {len(users)} declarations carry it in their type; kinds {dict(bykind)}; "
              f"{cited} of them are cited by anything")
        for s, k in bysub.most_common(12):
            print(f"      {s:34s} {k:5d}")
        print(f"      e.g. {users[:5]}")
        total += len(users)
        out["informal"]["markers"][name] = {"module": d.module, "kind": d.kind,
                                            "users": len(users), "cited": cited,
                                            "by_subfield": dict(bysub),
                                            "by_kind": dict(bykind), "sample": users}
    print(f"  total declarations carrying a marker type: {total}")
    out["informal"]["total"] = total
    return out


def mode_orphans(c, decls, path, out):
    print(f"\n=== Q2 ORPHANS [graph-only] — {path}")
    theorems = [x for x, d in decls.items() if d.kind == "theorem"]
    defs = [x for x, d in decls.items() if d.kind in DEF_KINDS]
    print(f"  {len(theorems)} theorems, {len(defs)} definition-like declarations")

    deriv = derivativeness(decls)
    labels = [1 if labelled_derived(x) else 0 for x in defs]
    a = auc([deriv[x] for x in defs], labels)
    null = permutation_null([deriv[x] for x in defs], labels, 200, 11)
    print(f"  derivativeness vs name blocklist (held-out labels): AUC {a:.3f}  "
          f"(permutation 95th pct {pct(null, 0.95):.3f}) — "
          f"{'stratification trusted' if a >= 0.75 else 'NOT TRUSTED, reporting unstratified'}")
    trusted = a >= 0.75
    # The cut is the blocklist's own prevalence, so the strata are comparable in size to the
    # labelled classes without the blocklist choosing which declaration goes where.
    prevalence = sum(labels) / len(labels)
    cut = sorted(deriv[x] for x in defs)[max(int((1 - prevalence) * len(defs)) - 1, 0)]
    print(f"  blocklist prevalence {100 * prevalence:.1f}%  ->  derivativeness cut {cut:.3f}")

    res = {}
    for lens in ("statement", "both"):
        reach = reachable_from(decls, theorems, lens)
        orph = [x for x in defs if x not in reach]
        auth = [x for x in orph if deriv[x] < cut]
        print(f"  lens={lens}: {len(orph)} orphans of {len(defs)} defs "
              f"({100 * len(orph) / len(defs):.1f}%); authored stratum {len(auth)} "
              f"({100 * len(auth) / len(defs):.1f}%)")
        pool = auth if trusted else orph
        bysub = collections.Counter(subfield(decls[x].module) for x in pool)
        denom = collections.Counter(subfield(decls[x].module) for x in defs
                                    if deriv[x] < cut or not trusted)
        rows = sorted(((k / max(denom[s], 1), k, denom[s], s) for s, k in bysub.items()),
                      reverse=True)
        print("    subfield ranking (orphan rate among authored definitions):")
        for r, k, t, s in rows[:12]:
            print(f"      {s:34s} {k:5d} / {t:5d}  {100 * r:5.1f}%")
        # Null: permute the orphan label across definitions and re-measure the spread.
        obs = _spread(pool, defs if not trusted else [x for x in defs if deriv[x] < cut], decls)
        nulls = sorted(_spread_permuted(pool, defs if not trusted else
                                        [x for x in defs if deriv[x] < cut], decls, 1000, 7))
        print(f"    spread (stdev of per-subfield rate) {obs:.4f}  vs permuted 95th pct "
              f"{pct(nulls, 0.95):.4f}  -> "
              f"{'structured' if obs > pct(nulls, 0.95) else 'INDISTINGUISHABLE FROM CHANCE'}")
        res[lens] = {"orphans": len(orph), "authored": len(auth), "defs": len(defs),
                     "spread": obs, "null95": pct(nulls, 0.95),
                     "by_subfield": [[s, k, denom[s]] for _, k, _, s in rows],
                     "sample": sorted(auth)[:400]}
    out["orphans"] = {"deriv_auc": a, "cut": cut, "trusted": trusted, "lenses": res}
    return out


def _spread(pool, universe, decls) -> float:
    bysub = collections.Counter(subfield(decls[x].module) for x in pool)
    den = collections.Counter(subfield(decls[x].module) for x in universe)
    rates = [bysub[s] / den[s] for s in den if den[s] >= 20]
    if len(rates) < 2:
        return 0.0
    mu = sum(rates) / len(rates)
    return math.sqrt(sum((r - mu) ** 2 for r in rates) / (len(rates) - 1))


def _spread_permuted(pool, universe, decls, trials, seed):
    rng = random.Random(seed)
    subs = [subfield(decls[x].module) for x in universe]
    den = collections.Counter(subs)
    k = len(pool)
    out = []
    for _ in range(trials):
        picked = rng.sample(subs, k) if k <= len(subs) else subs
        bysub = collections.Counter(picked)
        rates = [bysub[s] / den[s] for s in den if den[s] >= 20]
        if len(rates) < 2:
            out.append(0.0)
            continue
        mu = sum(rates) / len(rates)
        out.append(math.sqrt(sum((r - mu) ** 2 for r in rates) / (len(rates) - 1)))
    return out


def mode_asserted(c, decls, path, out, closed: bool):
    print(f"\n=== Q3 ASSERTED HERE, PROVED THERE — {path}")
    unproved = sorted(set(w for w, _ in c.honesty()))
    inslice = [x for x in unproved if x in decls]
    print(f"  {len(inslice)} declarations rest on an unproved assertion")
    hits = []
    for lens_level in ("exact", "presentation", "instances", "carriers"):
        tag = "[graph-only]" if lens_level in ("exact", "presentation") else "[erasure]"
        if lens_level in ("instances", "carriers") and not closed:
            print(f"  level={lens_level:13s} {tag} SKIPPED — slice is not closed")
            continue
        found = 0
        for x in inslice:
            try:
                eq = c.equivalent(x, lens_level)
            except fa.AtlasError:
                continue
            partners = [p for p in eq if p not in unproved]
            if partners:
                found += 1
                hits.append((lens_level, x, partners[:5]))
        print(f"  level={lens_level:13s} {tag} {found}/{len(inslice)} have a proved "
              f"equivalent elsewhere in the corpus")
    for lv, x, ps in hits:
        print(f"    {lv:13s} {x}  ~  {ps}")
    out["asserted"] = {"unproved": inslice, "hits": [[lv, x, ps] for lv, x, ps in hits]}
    return out


def mode_transport(c, decls, path, out):
    """§24 measured transport as inert. Repeat the measurement rather than cite it."""
    print(f"\n=== Q3b TRANSPORT [erasure] — {path}")
    # `dict.rs::theory_of` is depth 2 under `Mathlib` and depth 1 everywhere else, so a
    # depth-2 physics name such as `Physlib.Relativity` names **no theory** and
    # `dictionary` returns an empty result rather than an error — 0 rows, no exception, and
    # a transport measurement that looks like a null. Ask for theories the engine has.
    theories = collections.Counter(theory(d.module) for d in decls.values())
    top = [s for s, _ in theories.most_common(6)]
    stats = {"rows": 0, "attempted": 0, "ok": 0, "nomatch": 0, "scoped": 0,
             "image_is_right": 0, "image_is_subject": 0, "open": 0, "novel": 0}
    open_targets = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            try:
                d = c.dictionary(top[i], top[j], per_decl=1, theorems_only=True)
            except fa.AtlasError as e:
                print(f"  dictionary({top[i]},{top[j]}): {e}")
                continue
            print(f"  dictionary({top[i]}, {top[j]}): {len(d.rows)} rows, "
                  f"{sum(1 for r in d.rows if r.transportable)} transportable, "
                  f"missing_left {len(d.missing_left)}")
            rows = [r for r in d.rows if r.transportable][:8]
            stats["rows"] += len(rows)
            subjects = [x for x in decls if theory(decls[x].module) == top[i]
                        and decls[x].kind == "theorem"][:60]
            for r in rows:
                for s in subjects:
                    stats["attempted"] += 1
                    try:
                        t = c.transport(r.left, r.right, s)
                    except fa.NoMatch:
                        stats["nomatch"] += 1
                        continue
                    except fa.ScopedRow:
                        stats["scoped"] += 1
                        continue
                    except fa.AtlasError:
                        continue
                    stats["ok"] += 1
                    try:
                        right_img = c.skeleton(r.right, "carriers")
                    except fa.AtlasError:
                        right_img = None
                    try:
                        subj_img = c.skeleton(s, "carriers")
                    except fa.AtlasError:
                        subj_img = None
                    if right_img is not None and t.image == right_img:
                        stats["image_is_right"] += 1
                    elif subj_img is not None and t.image == subj_img:
                        stats["image_is_subject"] += 1
                    else:
                        stats["novel"] += 1
                    if not t.exists:
                        stats["open"] += 1
                        if len(open_targets) < 20:
                            open_targets.append((r.left, r.right, s, t.image[:160]))
    print(f"  {stats}")
    print(f"  open targets: {stats['open']}"
          f"{'  <-- transport still produces nothing' if stats['open'] == 0 else ''}")
    for o in open_targets:
        print(f"    row {o[0]} ~ {o[1]}  subject {o[2]}\n      image {o[3]}")
    out["transport"] = {"stats": stats, "open": open_targets}
    return out


def mode_frontier(c, decls, path, out, min_theory_size=100, top=15):
    print(f"\n=== Q3c FRONTIER [erasure] min_theory_size={min_theory_size} — {path}")
    try:
        fr = c.frontier(min_theory_size=min_theory_size, top=top, theorems_only=True)
    except fa.AtlasError as e:
        print(f"  frontier failed: {e}")
        return out
    rows = []
    for p in fr:
        print(f"  {p.left:30s} ~ {p.right:30s} sim {p.similarity:.3f} "
              f"exp {p.expected_similarity:.3f} excess {p.excess:+.3f} "
              f"xcite {p.cross_citations:5d} sizes {p.left_size}/{p.right_size}")
        rows.append([p.left, p.right, p.similarity, p.expected_similarity, p.excess,
                     p.cross_citations, p.left_size, p.right_size])
    out["frontier"] = rows
    return out


FEATURES = ("bytes", "nodes", "maxdepth", "consts_total", "consts_distinct", "apps",
            "sorts", "bvars", "lits", "projs", "lets", "pis", "lams", "pi_default",
            "pi_implicit", "pi_inst", "pi_strict", "root_binders", "root_inst",
            "root_implicit", "root_default")


def _vec(s: dict) -> list[float]:
    v = [float(s[k]) for k in FEATURES]
    # Two ratios: absolute size dominates otherwise, and "how much of this statement is
    # binder" is the shape question, not "how big is it".
    v.append(s["consts_distinct"] / max(s["consts_total"], 1))
    v.append(s["pis"] / max(s["nodes"], 1))
    v.append(math.log(max(s["nodes"], 1)))
    return v


def _fit_eval(feats: dict, labels: dict, pool: list[str], tag: str, verbose=True):
    tr = [x for x in pool if not in_test_half(x)]
    te = [x for x in pool if in_test_half(x)]
    if min(sum(labels[x] for x in tr), sum(labels[x] for x in te)) < 3:
        return float("nan"), 0, 0
    Xtr = [_vec(feats[x]) for x in tr]
    mu, sd = standardise(Xtr)
    w = logistic(apply_std(Xtr, mu, sd), [labels[x] for x in tr])
    Xte = apply_std([_vec(feats[x]) for x in te], mu, sd)
    sc = [w[0] + sum(w[j + 1] * r[j] for j in range(len(r))) for r in Xte]
    a = auc(sc, [labels[x] for x in te])
    if verbose:
        print(f"    {tag}: train {len(tr)} ({sum(labels[x] for x in tr)} pos), "
              f"test {len(te)} ({sum(labels[x] for x in te)} pos), held-out AUC {a:.3f}")
    return a, len(te), sum(labels[x] for x in te)


def scanner_differential(decls, sample=2000, seed=5) -> tuple[int, int]:
    """Check `scan` against an independently-written reader of the same encoding.

    `scripts/atlas_encoding.constants` walks the encoding with different code to a different
    end (it exists to *rewrite* names), and yields one entry per `c(` and per `j(`. Every
    shape feature below rides on this scanner, so a shared bug in it would be invisible to
    any downstream control; a second implementation is the only thing that catches it.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import atlas_encoding

    rng = random.Random(seed)
    names = [x for x, d in decls.items() if d.stmt]
    picked = rng.sample(names, min(sample, len(names)))
    bad = 0
    for x in picked:
        s = scan(decls[x].stmt)
        if s["consts_total"] + s["projs"] != len(atlas_encoding.constants(decls[x].stmt)):
            bad += 1
    return len(picked), bad


def mode_shape(c, decls, path, out):
    print(f"\n=== Q4 THE SHAPE OF AN ASSERTION [graph-only: features come from the I3 "
          f"encoding in the row] — {path}")
    n, bad = scanner_differential(decls)
    print(f"  scanner differential vs scripts/atlas_encoding: {n - bad}/{n} agree"
          f"{'' if bad == 0 else '   <-- SCANNER DISAGREES, features are not trustworthy'}")
    if bad:
        raise SystemExit("scanner differential failed; refusing to report shape results")
    feats = {}
    for x, d in decls.items():
        if d.stmt:
            feats[x] = scan(d.stmt)

    # --- arm A: axioms vs theorems, as literally posed
    axioms = [x for x, d in decls.items() if d.kind == "axiom"]
    print(f"  arm A (axiom vs theorem): {len(axioms)} axioms — "
          f"{'UNRUNNABLE, no positives' if not axioms else 'runnable'}")

    # --- arm B: sorry-carrying vs proved theorems
    unproved = set(w for w, _ in c.honesty())
    thm = [x for x, d in decls.items() if d.kind == "theorem" and x in feats]
    lab = {x: 1 if x in unproved else 0 for x in thm}
    npos = sum(lab.values())
    print(f"  arm B (unproved vs proved theorem): {npos} positives of {len(thm)}")
    armB = {"positives": npos, "n": len(thm)}
    if npos >= 5:
        cols = {f: [float(feats[x][f]) for x in thm] for f in FEATURES}
        y = [lab[x] for x in thm]
        per_feature = {}
        marginal = []
        for i, f in enumerate(FEATURES):
            a = auc(cols[f], y)
            null = permutation_null(cols[f], y, 1000, 3 + i)
            lo, hi = pct(null, 0.025), pct(null, 0.975)
            per_feature[f] = {"auc": a, "lo": lo, "hi": hi, "sig": a > hi or a < lo}
            if a > hi or a < lo:
                marginal.append((f, a, lo, hi))
        print(f"    per-feature tests significant at 95%: {len(marginal)} of "
              f"{len(FEATURES)} — chance alone gives {0.05 * len(FEATURES):.1f}")
        for f, a, lo, hi in marginal:
            print(f"      {f:18s} AUC {a:.3f}  per-feature null 95% [{lo:.3f},{hi:.3f}]")
        # The test that means something: max deviation over the family, one shared shuffle.
        obs = max(abs(per_feature[f]["auc"] - 0.5) for f in FEATURES)
        arg = max(FEATURES, key=lambda f: abs(per_feature[f]["auc"] - 0.5))
        fw = familywise_null(cols, y, 1000, 91)
        print(f"    FAMILY-WISE: max|AUC-0.5| = {obs:.3f} ({arg}), null 95th pct "
              f"{pct(fw, 0.95):.3f}, null max {fw[-1]:.3f}  ->  "
              f"{'signal' if obs > pct(fw, 0.95) else 'NO SIGNAL — the per-feature hits are '
                 'what 21 tests produce by chance'}")
        # Power, so "no signal" is bounded rather than merely reported: the smallest true
        # AUC this test would detect 80% of the time at this positive count.
        detect = pct(fw, 0.95)
        print(f"    power: with {npos} positives this test cannot see a true |AUC-0.5| "
              f"below {detect:.3f} (AUC {0.5 + detect:.3f}); a real but smaller effect is "
              f"not excluded")
        armB.update({"per_feature": per_feature, "n_marginal": len(marginal),
                     "familywise_obs": obs, "familywise_arg": arg,
                     "familywise_95": pct(fw, 0.95),
                     "signal": obs > pct(fw, 0.95)})
        # No multivariate arm: 16 positives against 24 features is not identifiable, and a
        # held-out AUC from such a fit reports the split, not the corpus.
    out_shape = {"armA_axioms": len(axioms), "armB": armB}

    # --- arm C: orphan vs cited definitions, statement shape only
    theorems = [x for x, d in decls.items() if d.kind == "theorem"]
    reach = reachable_from(decls, theorems, "both")
    deriv = derivativeness(decls)
    defs = [x for x, d in decls.items() if d.kind in DEF_KINDS and x in feats]
    dl = [1 if labelled_derived(x) else 0 for x in defs]
    prevalence = sum(dl) / max(len(dl), 1)
    cut = sorted(deriv[x] for x in defs)[max(int((1 - prevalence) * len(defs)) - 1, 0)]
    pool = [x for x in defs if deriv[x] < cut]
    lab2 = {x: 0 if x in reach else 1 for x in pool}
    print(f"  arm C (orphan vs cited definition, authored stratum): "
          f"{sum(lab2.values())} orphans of {len(pool)}")
    a_real, nte, npte = _fit_eval(feats, lab2, pool, "real labels")
    shuffles = []
    for t in range(20):
        rng = random.Random(100 + t)
        vals = [lab2[x] for x in pool]
        rng.shuffle(vals)
        perm = dict(zip(pool, vals))
        a_s, _, _ = _fit_eval(feats, perm, pool, f"shuffle {t}", verbose=False)
        if not math.isnan(a_s):
            shuffles.append(a_s)
    shuffles.sort()
    print(f"    label-shuffle control: mean {sum(shuffles) / max(len(shuffles), 1):.3f}, "
          f"95th pct {pct(shuffles, 0.95):.3f}, n={len(shuffles)}")
    verdict = a_real > pct(shuffles, 0.95)
    print(f"    held-out AUC {a_real:.3f} vs shuffled 95th {pct(shuffles, 0.95):.3f}  ->  "
          f"{'SEPARABLE' if verdict else 'not separable'}")
    # Which single feature carries it — a multivariate AUC with no univariate story is a
    # fit, not a finding.
    uni = sorted(((abs(auc([float(feats[x][f]) for x in pool],
                           [lab2[x] for x in pool]) - 0.5), f,
                   auc([float(feats[x][f]) for x in pool], [lab2[x] for x in pool]))
                  for f in FEATURES), reverse=True)
    print("    strongest single shape features (|AUC-0.5|):")
    for _, f, a in uni[:6]:
        print(f"      {f:18s} AUC {a:.3f}")
    out_shape["armC"] = {"n": len(pool), "pos": sum(lab2.values()), "auc": a_real,
                         "shuffle_mean": sum(shuffles) / max(len(shuffles), 1),
                         "shuffle_95": pct(shuffles, 0.95), "separable": verdict,
                         "univariate": [[f, a] for _, f, a in uni[:10]]}
    out["shape"] = out_shape
    return out


MODES = {"census": mode_census, "honesty": mode_honesty, "informal": mode_informal,
         "orphans": mode_orphans, "shape": mode_shape}
ERASURE_MODES = {"asserted": mode_asserted, "transport": mode_transport,
                 "frontier": mode_frontier}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("modes", nargs="+",
                    choices=list(MODES) + list(ERASURE_MODES) + ["all", "graph"])
    ap.add_argument("--slice", default=PHYSLIB)
    ap.add_argument("--json", default=None)
    ap.add_argument("--force-erasure", action="store_true",
                    help="run erasure-dependent modes even below the 95%% closure floor")
    ap.add_argument("--min-theory-size", type=int, default=100)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--reduce-from", default=None,
                    help="build --slice as the statement closure of a full extraction")
    args = ap.parse_args()

    if args.reduce_from:
        reduce_closure(args.reduce_from, args.slice)

    c, decls = load(args.slice)
    _, _, cov, _ = c.closure(top=1)
    closed = cov >= 0.95
    print(f"  closure {cov * 100:.2f}%  -> erasure-dependent results are "
          f"{'VALID' if closed else 'INVALID (§31); graph-only results stand'}")

    modes = list(args.modes)
    if "all" in modes:
        modes = list(MODES) + list(ERASURE_MODES)
    elif "graph" in modes:
        # `asserted` self-guards: two of its four levels consult no signature.
        modes = list(MODES) + ["asserted"]
    out = {"slice": args.slice, "closure": cov, "closed": closed}
    for m in modes:
        if m in MODES:
            MODES[m](c, decls, args.slice, out)
        elif m == "asserted":
            # Self-guarding: its `exact` and `presentation` arms consult no signature, so
            # they are valid on an unclosed slice and the other two say they were skipped.
            mode_asserted(c, decls, args.slice, out, closed or args.force_erasure)
        else:
            if not closed and not args.force_erasure:
                print(f"\n=== {m.upper()} [erasure] SKIPPED — closure {cov * 100:.2f}% "
                      f"< 95% (§31). Re-run on a closure, or pass --force-erasure.")
                continue
            if m == "frontier":
                mode_frontier(c, decls, args.slice, out, args.min_theory_size, args.top)
            else:
                ERASURE_MODES[m](c, decls, args.slice, out)
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(out, indent=1, default=str))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
