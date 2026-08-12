#!/usr/bin/env python3
"""What does the retrieval prefilter's posting cutoff cost, and what does raising it buy?

The pre-registration — the ladder, the five outcomes, the controls and what would show the
cutoff is *not* the cause — is `research/physlib-prefilter.md` §1–§2, written before this
script was run. Read that first; this file is the instrument, not the claim.

## The measurement problem, and the instrument that solves it

`Postings::build` drops any key held by more than

    max_len = max(floor(N * max_posting_fraction), min_posting_len)

declarations (`skel/index.rs`). On the 95,268-row closed physics corpus that is 95, and
`research/physlib-classical-quantum.md` §7/§11 showed by dilution that this is what deletes
the four pre-registered classical<->quantum information correspondences: they share *common*
keys, which is exactly what a length cutoff removes.

Neither knob is reachable from the Python binding, and Rust edits are out of scope for this
session. But `max_len` reads the corpus only through `N`. Appending rows that **parse and
carry no key** raises `N` — and therefore `max_len` — while leaving every real key's
document frequency byte-identical. The padding row is

    {"kind":"def","module":"ZPad","name":"zpad.pN","stmt":"atlas-stmt-v1;s(0)", ...}

a single `Sort` node: below every posting-key size floor (3 closed / 5 open / 8 shape) so it
contributes no posting, and carrying no application head so `closure()` cannot move. Both
properties are re-measured by `measure` on every corpus this script builds — the coverage and
the four `generalize` retentions are carried at every rung — because an instrument that is
not inert is measuring itself.

**What padding does not emulate, stated rather than hidden.** `N` also enters
`idf = ln(N/df)`, the rarity boost `1 + w*min(idf/ln N, 1)`, and `derivativeness`'s
percentile ranks. None of those gates *admission* — `similar` floors on retention and
`common`, neither of which sees `N` — but all three move the *score*, hence order within a
candidate set, hence which row `per_decl` selects. So every recall number is reported twice:
at the **proposed-and-above-floors** level, which is score-free and therefore unconfounded,
and at the **shipped dictionary** level, which is confounded by ordering and is reported
anyway because it is the surface a caller actually has.

## Why a matched-N control and not a before-and-after

Raising `max_len` and lowering document frequency are the same move on `df/max_len`.
`stage_matched` builds two corpora with the **same** N — hence the same `max_len` — that
differ only in how many of their rows are real, so the cutoff's effect is isolated from
everything else N does. If the targets return in both arms, something other than the cutoff
moved and the sweep does not mean what it says.
"""

from __future__ import annotations

import argparse
import array
import collections
import json
import pathlib
import random
import re
import resource
import shutil
import statistics
import subprocess
import sys
import time

try:
    import atlas as fa
except ImportError:  # pragma: no cover - the script is useless without it
    sys.exit("atlas is not importable — run under `uv run`")

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path("/tmp/pc-physclosed.jsonl")
BASE = pathlib.Path("/tmp/pfx-base.jsonl")
WORK = pathlib.Path("/tmp/pfx-work.jsonl")
OUT = pathlib.Path("/tmp/pfx")

# The four correspondences pre-registered in `physlib-classical-quantum.md` §2a (E16/E20)
# and measured there at conclusion-anchored retention 0.697-0.889 against nulls of
# 0.04-0.10. They are the numerator of every recall figure below. Disclosed input: naming
# them chooses the question, not the answer.
TRUE_ROWS = [
    ("Hₛ_nonneg", "Sᵥₙ_nonneg", "E16"),
    ("Hₛ_constant_eq_zero", "Sᵥₙ_of_pure_zero", "E16/E20"),
    ("H₁_nonneg", "Sᵥₙ_nonneg", "E16"),
    ("Hₛ_le_log_d", "Sᵥₙ_le_log_d", "E16"),
]

# Theory pairs measured at every rung. The negative controls are here so that a recall gain
# cannot be reported without the precision it cost — `ClassicalMechanics ~ Meta` is physics
# against an HTML note utility and already outscored the real dictionary at the shipped
# cutoff (§8 of the prior report).
PAIRS = [
    ("ClassicalInfo", "Entropy", "the question (E16-E19)"),
    ("ClassicalInfo", "States", "E20"),
    ("ClassicalMechanics", "QuantumMechanics", "the pre-registered real negative"),
    ("ClassicalMechanics", "Meta", "NC3 — no correspondence can exist"),
    ("Thermodynamics", "Meta", "NC3 — no correspondence can exist"),
]

PAD_ROW = (
    '{"kind":"def","module":"ZPad","name":"zpad.p%d",'
    '"stmt":"atlas-stmt-v1;s(0)","uses_proof":[],"uses_statement":[]}\n'
)


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6


def max_len_for(n: int, fraction: float = 0.001, floor: int = 50) -> int:
    """`Postings::build`'s cutoff, reproduced so the ladder can be stated in its units."""
    return max(int(n * fraction), floor)


# --------------------------------------------------------------------------- corpus build


def prepare_base(force: bool = False) -> dict:
    """Strip the library root so each physics subfield is its own theory.

    `dict::theory_of` takes the module prefix at depth 1 outside Mathlib, so without this
    every physlib declaration files under `Physlib` and `dictionary("ClassicalInfo", ...)`
    returns an empty result with no error. Established by `scripts/physlib-experiment.py`;
    done to a copy, never in place.
    """
    if BASE.exists() and not force and BASE.stat().st_size > 0:
        n = sum(1 for _ in BASE.open())
        return {"rows": n, "reused": True, "path": str(BASE)}
    fast = re.compile(r'"module":"(?:Physlib|QuantumInfo)\.')
    n = 0
    with SRC.open() as fh, BASE.open("w") as out:
        for line in fh:
            if not line.strip():
                continue
            n += 1
            out.write(fast.sub('"module":"', line, count=1))
    return {"rows": n, "reused": False, "path": str(BASE)}


def write_padded(src: pathlib.Path, dst: pathlib.Path, pad: int) -> None:
    with dst.open("w") as out:
        with src.open() as fh:
            shutil.copyfileobj(fh, out, length=1 << 22)
        if pad:
            chunk = []
            for i in range(pad):
                chunk.append(PAD_ROW % i)
                if len(chunk) >= 100_000:
                    out.write("".join(chunk))
                    chunk.clear()
            out.write("".join(chunk))


NAME_RE = re.compile(r'"name":"((?:[^"\\]|\\.)*)"')
MODULE_RE = re.compile(r'"module":"((?:[^"\\]|\\.)*)"')
KIND_RE = re.compile(r'"kind":"([a-z]*)"')
USES_RE = re.compile(r'"uses_statement":\[(.*?)\]')


def scan(src: pathlib.Path):
    """`(name, module, kind, uses_statement)` per row, without parsing 25 kB of statement.

    A `json.loads` per row costs minutes on a gigabyte slice and holds it all in Python
    objects; every field this script needs is a short string near the front of the line.
    """
    for line in src.open():
        if not line.strip():
            continue
        n = NAME_RE.search(line)
        m = MODULE_RE.search(line)
        k = KIND_RE.search(line)
        u = USES_RE.search(line)
        if not n:
            continue
        uses = json.loads("[" + u.group(1) + "]") if u and u.group(1) else []
        yield (json.loads('"' + n.group(1) + '"'),
               json.loads('"' + m.group(1) + '"') if m else "",
               k.group(1) if k else "", uses)


def statement_closure(src: pathlib.Path, seeds: set[str], dst: pathlib.Path) -> dict:
    """The smallest subset of `src` containing `seeds` and closed under `uses_statement`.

    A random subsample of a closed corpus is *not* closed — the heads its statements mention
    were dropped with the rows — so the matched-N control cannot use one without confounding
    the cutoff with the erasure degrading (CLAUDE.md §7, findings §31). This builds the
    closed sub-corpus instead, and `measure` reports its coverage like any other.
    """
    uses: dict[str, list[str]] = {}
    for name, _module, _kind, us in scan(src):
        uses[name] = us
    keep: set[str] = set()
    stack = [s for s in seeds if s in uses]
    while stack:
        n = stack.pop()
        if n in keep:
            continue
        keep.add(n)
        for u in uses.get(n, ()):
            if u in uses and u not in keep:
                stack.append(u)
    written = 0
    with src.open() as fh, dst.open("w") as out:
        for line in fh:
            m = NAME_RE.search(line)
            if m and json.loads('"' + m.group(1) + '"') in keep:
                out.write(line)
                written += 1
    return {"seeds": len(seeds), "rows": written, "path": str(dst)}


def theory_members(src: pathlib.Path, theories: set[str]) -> set[str]:
    return {n for n, m, _k, _u in scan(src) if m.split(".")[0] in theories}


def query_pool(src: pathlib.Path, theories: set[str]) -> list[str]:
    return sorted(n for n, m, k, _u in scan(src)
                  if k == "theorem" and m.split(".")[0] in theories)


# ------------------------------------------------------------------------- one measurement


def measure(path: str, label: str, queries: int, heavy: bool) -> dict:
    """Every number this study reports, for one corpus. Run in its own process.

    One process per corpus because a `Corpus` holds the whole slice as a string plus one
    index per anchor, and the padded rungs are gigabytes: dropping the handle does not give
    the memory back promptly enough to build the next one beside it.
    """
    rec: dict = {"label": label, "path": path, "t0": time.time()}
    t = time.time()
    c = fa.Corpus.load(path)
    rec["load_s"] = round(time.time() - t, 2)
    rec["n"] = len(c)
    rec["max_len"] = max_len_for(len(c))
    rec["rss_after_load_gb"] = round(rss_gb(), 3)

    # NC-pad, on every corpus: the padding must not change the closure. It cannot if the
    # padding row has no application head, and asserting it is how a change of padding row
    # would be caught rather than absorbed.
    t = time.time()
    known, unknown, cov, worst = c.closure(5)
    rec["closure_s"] = round(time.time() - t, 2)
    rec["closure"] = {"known": known, "unknown": unknown, "coverage": cov,
                      "worst": worst}
    rec["rss_after_root_index_gb"] = round(rss_gb(), 3)

    # NC2 — erasure liveness. An erasure that returns the unerased term passes every
    # downstream check by agreeing with itself (§5's source-B trap).
    live = 0
    names = [n for n, _, _ in TRUE_ROWS] + [r for _, r, _ in TRUE_ROWS]
    sample = sorted(set(names))
    for n in sample:
        try:
            if c.skeleton(n, "carriers") != c.skeleton(n, "presentation"):
                live += 1
        except Exception:
            pass
    rec["nc2_carriers_differ"] = [live, len(sample)]

    # The closure-independent oracle. `generalize` parses two statements and calls `lgg`:
    # no erasure, no signature lookup, no corpus. It must return the same numbers at every
    # rung, and if it does not the padding is not inert.
    rec["generalize"] = {}
    for L, R, e in TRUE_ROWS:
        try:
            g = c.generalize(L, R, anchor="conclusion")
            rec["generalize"][f"{L} ~ {R}"] = {
                "retention": round(g.retention, 4), "common": g.common, "E": e}
        except Exception as exc:
            rec["generalize"][f"{L} ~ {R}"] = {"error": f"{type(exc).__name__}: {exc}"}

    # ---- the recall numerator, at the level that is score-free ----
    # `similar`'s floors are on retention and `common`. Neither reads N, so membership of
    # this list cannot be moved by the padding's effect on idf, rarity or derivativeness.
    t = time.time()
    rec["proposed"] = {}
    for L, R, e in TRUE_ROWS:
        row: dict = {"E": e}
        try:
            floored = c.similar(L, top=10**7, level="carriers", anchor="conclusion",
                                min_retention=0.30, min_common=6)
            row["n_above_floors"] = len(floored)
            hit = next(((i + 1, n) for i, n in enumerate(floored) if n.name == R), None)
            row["above_floors"] = hit is not None
            if hit:
                row["rank"] = hit[0]
                row["retention"] = round(hit[1].retention, 4)
                row["sources"] = hit[1].sources
            allc = c.similar(L, top=10**7, level="carriers", anchor="conclusion",
                             min_retention=0.0, min_common=0)
            row["candidates"] = len(allc)
            row["proposed"] = any(n.name == R for n in allc)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rec["proposed"][f"{L} ~ {R}"] = row
    rec["proposed_s"] = round(time.time() - t, 2)
    rec["rss_after_conclusion_index_gb"] = round(rss_gb(), 3)

    # ---- the shipped surface ----
    rec["dictionaries"] = {}
    for left, right, why in PAIRS:
        entry: dict = {"why": why}
        # `per_decl=10` only on the pair the study is about. It is there to separate the
        # cutoff from `per_decl`'s selection — which the padding *can* move through the
        # score — and running it on 631-declaration `ClassicalMechanics` costs more than
        # the separation is worth.
        for per_decl in ((1, 10) if (left, right) == ("ClassicalInfo", "Entropy") else (1,)):
            t = time.time()
            try:
                d = c.dictionary(left, right, anchor="conclusion", theorems_only=True,
                                 per_decl=per_decl)
                rows = [(r.left, r.right, round(r.retention, 4)) for r in d.rows]
                found = [f"{a} ~ {b}" for a, b, _ in rows
                         if any(a == L and b == R for L, R, _ in TRUE_ROWS)]
                entry[f"per_decl={per_decl}"] = {
                    "seconds": round(time.time() - t, 2),
                    "rows": len(rows),
                    "lefts": len({a for a, _, _ in rows}),
                    "rights": len({b for _, b, _ in rows}),
                    "mean_retention": round(
                        statistics.fmean([s for _, _, s in rows]), 4) if rows else None,
                    "targets_found": found,
                    "top": rows[:12],
                }
            except Exception as exc:
                entry[f"per_decl={per_decl}"] = {"error": f"{type(exc).__name__}: {exc}"}
        rec["dictionaries"][f"{left} ~ {right}"] = entry

    # ---- cost: latency and candidate-set size over a physics query set ----
    pool = query_pool(pathlib.Path(path), {"ClassicalInfo", "Entropy", "States",
                                           "ClassicalMechanics", "QuantumMechanics"})
    rnd = random.Random(20260804)
    sample = rnd.sample(pool, min(queries, len(pool)))
    lat, cands, budgeted = [], [], 0
    for n in sample:
        t = time.time()
        try:
            c.similar(n, top=10, level="carriers", anchor="conclusion")
        except Exception:
            continue
        lat.append(time.time() - t)
        try:
            allc = c.similar(n, top=10**7, level="carriers", anchor="conclusion",
                             min_retention=0.0, min_common=0)
        except Exception:
            continue
        cands.append(len(allc))
        if len(allc) >= 600:
            budgeted += 1
    if lat:
        rec["latency_s"] = {"queries": len(lat), "median": round(statistics.median(lat), 4),
                            "p90": round(sorted(lat)[int(0.9 * (len(lat) - 1))], 4),
                            "mean": round(statistics.fmean(lat), 4)}
    if cands:
        rec["candidate_set"] = {
            "queries": len(cands), "median": statistics.median(cands),
            "p90": sorted(cands)[int(0.9 * (len(cands) - 1))], "max": max(cands),
            "at_or_over_budget_600": budgeted}

    if heavy:
        # The posting inventory the prior report said did not exist: every key that survived
        # this rung's cutoff, with the family that holds it. At a high rung this *is* the
        # measurement of which keys the shipped cutoff deletes.
        rec["inventory"] = inventory(c)

    rec["rss_peak_gb"] = round(rss_gb(), 3)
    rec["wall_s"] = round(time.time() - rec["t0"], 1)
    return rec


def inventory(c) -> dict:
    """Which posting keys carry the true pairs, and how many declarations hold them."""
    out: dict = {}
    for source, floor in (("subterm", 3), ("shape", 8)):
        t = time.time()
        try:
            fams = c.motifs(source, 2, floor, 20_000_000)
        except Exception as exc:
            out[source] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        hist = collections.Counter()
        shared: dict[str, list] = {}
        want = {(L, R) for L, R, _ in TRUE_ROWS}
        for pattern, members, size, idf in fams:
            hist[len(members)] += 1
            ms = set(members)
            for L, R in want:
                if L in ms and R in ms:
                    shared.setdefault(f"{L} ~ {R}", []).append(
                        {"df": len(members), "size": size, "idf": round(idf, 3),
                         "pattern": pattern[:160]})
        out[source] = {
            "seconds": round(time.time() - t, 1),
            "keys_family_ge_2": len(fams),
            "postings": sum(len(m) for _, m, _, _ in fams),
            "df_histogram": {str(k): v for k, v in sorted(hist.items())[:40]},
            "shared_keys": {k: sorted(v, key=lambda r: r["df"])[:25]
                            for k, v in shared.items()},
            "shared_key_counts": {k: len(v) for k, v in shared.items()},
        }
    return out


# ------------------------------------------------------------------------------ the stages


def stage_sweep(args) -> None:
    OUT.mkdir(exist_ok=True)
    info = prepare_base(force=args.force_prepare)
    print(f"[base] {info}", flush=True)
    n0 = info["rows"]
    rungs = []
    for target in args.rungs:
        pad = max(0, target - n0)
        rungs.append((target, pad))
    for target, pad in rungs:
        label = f"n{n0 + pad}-maxlen{max_len_for(n0 + pad)}"
        dst = OUT / f"rung-{label}.json"
        if dst.exists() and not args.force:
            print(f"[rung {label}] exists, skipping", flush=True)
            continue
        t = time.time()
        write_padded(BASE, WORK, pad)
        print(f"[rung {label}] n={n0 + pad} max_len={max_len_for(n0 + pad)} "
              f"pad={pad} written in {time.time()-t:.0f}s", flush=True)
        run_child(str(WORK), label, dst, args, heavy=(label in args.heavy))
        WORK.unlink(missing_ok=True)


def stage_matched(args) -> None:
    """The control that can refute: same N, same cutoff, different document frequency."""
    OUT.mkdir(exist_ok=True)
    info = prepare_base(force=False)
    n0 = info["rows"]
    small = pathlib.Path("/tmp/pfx-small.jsonl")
    if not small.exists() or args.force:
        seeds = theory_members(BASE, {"ClassicalInfo", "Entropy"})
        meta = statement_closure(BASE, seeds, small)
        print(f"[matched] closed sub-corpus: {meta}", flush=True)
    n_small = sum(1 for _ in small.open())
    target = args.matched_n
    for arm, src, n_real in (("low-df", small, n_small), ("high-df", BASE, n0)):
        label = f"matched-{arm}"
        dst = OUT / f"{label}.json"
        if dst.exists() and not args.force:
            print(f"[{label}] exists, skipping", flush=True)
            continue
        pad = max(0, target - n_real)
        write_padded(src, WORK, pad)
        print(f"[{label}] real={n_real} pad={pad} n={n_real+pad} "
              f"max_len={max_len_for(n_real+pad)}", flush=True)
        run_child(str(WORK), label, dst, args, heavy=False)
        WORK.unlink(missing_ok=True)


def stage_exhaustive(args) -> None:
    """What the prefilter-free path costs at physics scale, measured not estimated."""
    OUT.mkdir(exist_ok=True)
    prepare_base(force=False)
    t = time.time()
    c = fa.Corpus.load(str(BASE))
    rec: dict = {"load_s": round(time.time() - t, 1), "n": len(c)}
    rec["closure"] = c.closure(3)[2]

    by_theory: dict[str, list[str]] = collections.defaultdict(list)
    for name, module, kind, _u in scan(BASE):
        if kind == "theorem":
            by_theory[module.split(".")[0]].append(name)
    physics = {k: v for k, v in by_theory.items()
               if k in {"ClassicalInfo", "Entropy", "States", "Channels", "Capacity",
                        "ClassicalMechanics", "QuantumMechanics", "Relativity", "QFT",
                        "Electromagnetism", "Thermodynamics", "StatisticalMechanics",
                        "Particles", "SpaceAndTime", "Units", "Meta", "Mathematics",
                        "StringTheory", "CondensedMatter", "Cosmology", "FluidDynamics",
                        "ClassicalFieldTheory", "ResourceTheory", "Measurements",
                        "Operators", "ForMathlib"}}
    rec["theory_theorem_counts"] = {k: len(v) for k, v in sorted(physics.items())}

    # `generalize` throughput, measured on the pair the study is about.
    lefts, rights = physics.get("ClassicalInfo", []), physics.get("Entropy", [])
    t = time.time()
    rows, done = [], 0
    for L in lefts:
        for R in rights:
            try:
                g = c.generalize(L, R, anchor="conclusion")
            except Exception:
                continue
            done += 1
            if g.common >= 6 and g.retention >= 0.30:
                rows.append((round(g.retention, 4), L, R))
    dt = time.time() - t
    rows.sort(reverse=True)
    rec["exhaustive_ClassicalInfo_Entropy"] = {
        "pairs": done, "seconds": round(dt, 1),
        "pairs_per_s": round(done / dt, 1) if dt else None,
        "rows_above_floors": len(rows),
        "targets_found": [f"{L} ~ {R}" for _, L, R in rows
                          if any(L == a and R == b for a, b, _ in TRUE_ROWS)],
        "top": rows[:15],
    }

    # `similar_brute` — the same ranking with the index switched off, per query.
    rnd = random.Random(20260804)
    pool = rnd.sample(lefts, min(10, len(lefts)))
    times = []
    for n in pool:
        t = time.time()
        try:
            c.similar_brute(n, top=10, level="carriers")
        except Exception:
            continue
        times.append(time.time() - t)
    if times:
        rec["similar_brute_s"] = {"queries": len(times),
                                  "median": round(statistics.median(times), 2),
                                  "mean": round(statistics.fmean(times), 2)}

    # The two-tier question: what would exhausting every cross-theory pair inside physics
    # cost at the measured rate?
    rate = rec["exhaustive_ClassicalInfo_Entropy"]["pairs_per_s"]
    sizes = sorted(len(v) for v in physics.values())
    total = sum(sizes) ** 2 - sum(s * s for s in sizes)
    rec["all_cross_theory_pairs"] = {
        "theorems": sum(sizes), "ordered_cross_pairs": total,
        "seconds_at_measured_rate": round(total / rate, 1) if rate else None}
    (OUT / "exhaustive.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in rec.items()
                      if k != "theory_theorem_counts"}, indent=1, ensure_ascii=False))


def stage_admission(args) -> None:
    """Is a length cutoff the right shape of rule? Simulated against the same numerator.

    `candidates` is short enough to reproduce exactly, and the posting lists it reads are
    already exposed: `motifs(source, min_family=2, …)` *is* the index, key by key, with the
    family that holds each. Inverting those member lists recovers every declaration's key
    set, which is the whole input to candidate generation, so an admission rule can be
    scored offline on the same ground truth and the same cost axes without touching Rust.

    **Censored, and it says by how much.** The inventory can only see keys this corpus's own
    cutoff kept, so run it on a padded slice: at `max_len = M` the simulation is exact for
    every rule that admits nothing above `M`, and undercounts the cost of one that admits
    more. The reported `censored_at` is that bound.
    """
    OUT.mkdir(exist_ok=True)
    c = fa.Corpus.load(args.slice)
    n = len(c)
    rec: dict = {"slice": args.slice, "n": n, "censored_at": max_len_for(n),
                 "budget": args.budget}

    # key i -> (df, size, idf, source); decl -> [key ids]. Declaration names are folded to
    # integers before anything is stored: `motifs` hands back a fresh `str` per posting, and
    # a corpus-scale inventory is tens of millions of them.
    df: list[int] = []
    size: list[int] = []
    idf: list[float] = []
    src: list[int] = []
    members: list[array.array] = []
    ids: dict[str, int] = {}
    names: list[str] = []
    holds_l: list[array.array] = []
    # The rendered key, kept only for the handful a true pair shares. Keeping every one is
    # hundreds of megabytes of strings that nothing reads; keeping none leaves the report
    # asserting which fragment carries the analogy instead of quoting it.
    want_names = {n for L, R, _ in TRUE_ROWS for n in (L, R)}
    pat: dict[int, str] = {}
    for s_i, (source, floor) in enumerate((("subterm", 3), ("shape", 8))):
        t = time.time()
        fams = c.motifs(source, 2, floor, 20_000_000)
        print(f"[{source}] {len(fams)} keys in {time.time()-t:.0f}s", flush=True)
        while fams:
            pattern, mem, sz, f = fams.pop()
            k = len(df)
            df.append(len(mem))
            size.append(sz)
            idf.append(f)
            src.append(s_i)
            if want_names.intersection(mem):
                pat[k] = pattern
            row = array.array("i")
            for m in mem:
                i = ids.get(m)
                if i is None:
                    i = ids[m] = len(names)
                    names.append(m)
                    holds_l.append(array.array("i"))
                row.append(i)
                holds_l[i].append(k)
            members.append(row)
        del fams
    holds = {names[i]: holds_l[i] for i in range(len(names))}
    rec["keys"] = {"total": len(df), "subterm": src.count(0), "shape": src.count(1),
                   "postings": sum(df), "declarations_with_a_key": len(names)}
    rec["df_quantiles"] = {q: sorted(df)[int(q / 100 * (len(df) - 1))]
                           for q in (50, 75, 90, 99)} if df else {}

    # Which keys does each true pair actually share, and how common are they? This is the
    # measurement the dilution experiment said did not exist.
    rec["shared_keys"] = {}
    for L, R, e in TRUE_ROWS:
        rid = ids.get(R)
        shared = [k for k in holds.get(L, ()) if rid is not None and rid in members[k]]
        shared.sort(key=lambda k: df[k])
        rec["shared_keys"][f"{L} ~ {R}"] = {
            "E": e, "count": len(shared),
            "min_df": df[shared[0]] if shared else None,
            "by_source": {"subterm": sum(1 for k in shared if src[k] == 0),
                          "shape": sum(1 for k in shared if src[k] == 1)},
            "rarest": [{"df": df[k], "size": size[k],
                        "source": ("subterm", "shape")[src[k]],
                        "key": pat.get(k, "")[:200]} for k in shared[:12]],
        }

    def walk(q: str, admit, budget: int) -> tuple[set[int], int]:
        """`SkeletonIndex::candidates`, reproduced: rarest key first, stop at the budget."""
        qid = ids.get(q, -1)
        keyed = sorted((k for k in holds.get(q, ()) if admit(k)), key=lambda k: -idf[k])
        hits: set[int] = set()
        visited = 0
        for k in keyed:
            if len(hits) >= budget:
                break
            visited += df[k]
            hits.update(members[k])
        hits.discard(qid)
        return hits, visited

    pool = query_pool(pathlib.Path(args.slice),
                      {"ClassicalInfo", "Entropy", "States", "ClassicalMechanics",
                       "QuantumMechanics"})
    sample = random.Random(20260804).sample(pool, min(args.queries, len(pool)))

    rules: list[tuple[str, object]] = []
    for M in (50, 95, 200, 400, 800, 1600, 3200, 10**9):
        rules.append((f"length<={M}", lambda k, M=M: df[k] <= M))
    for S in (16, 32, 64):
        rules.append((f"length<=95 or size>={S}",
                      lambda k, S=S: df[k] <= 95 or size[k] >= S))
    for MB, MC in ((95, 3200), (3200, 95)):
        rules.append((f"subterm<={MB}, shape<={MC}",
                      lambda k, MB=MB, MC=MC: df[k] <= (MB if src[k] == 0 else MC)))

    rec["rules"] = []
    for name, admit in rules:
        found = []
        for L, R, _e in TRUE_ROWS:
            hits, _ = walk(L, admit, args.budget)
            if ids.get(R, -1) in hits:
                found.append(f"{L} ~ {R}")
        cands, visits = [], []
        for q in sample:
            h, v = walk(q, admit, args.budget)
            cands.append(len(h))
            visits.append(v)
        rec["rules"].append({
            "rule": name,
            "keys_admitted": sum(1 for k in range(len(df)) if admit(k)),
            "postings_retained": sum(df[k] for k in range(len(df)) if admit(k)),
            "targets": found,
            "n_targets": len(found),
            "cand_median": statistics.median(cands) if cands else None,
            "cand_p90": sorted(cands)[int(0.9 * (len(cands) - 1))] if cands else None,
            "visited_median": statistics.median(visits) if visits else None,
        })
        print(f"  {name:28s} targets={len(found)}/4 "
              f"cand_med={rec['rules'][-1]['cand_median']} "
              f"visited_med={rec['rules'][-1]['visited_median']}", flush=True)

    # (c) keep everything, and let a *work* budget do the pruning instead of a key cutoff.
    # Is the *budget* corpus-global while the query is theory-restricted? `similar` calls
    # `candidates` first and applies `restrict_prefix` to the result, so the 600 slots are
    # spent corpus-wide and then filtered — on this corpus that means 95,268 declarations
    # competing for a dictionary that can only use 181 of them. Scoping the walk is a
    # separate change from raising the cutoff, and this measures them apart.
    theory = {}
    for name, module, _kind, _u in scan(pathlib.Path(args.slice)):
        theory[name] = module.split(".")[0]
    tid = [theory.get(nm, "") for nm in names]

    def walk_scoped(q: str, admit, budget: int, right: str) -> set[int]:
        keyed = sorted((k for k in holds.get(q, ()) if admit(k)), key=lambda k: -idf[k])
        hits: set[int] = set()
        for k in keyed:
            if len(hits) >= budget:
                break
            hits.update(m for m in members[k] if tid[m] == right)
        hits.discard(ids.get(q, -1))
        return hits

    rec["scoped_budget"] = []
    for M in (95, 400, 1600, 10**9):
        def admit(k, M=M):
            return df[k] <= M
        glob = [f"{L} ~ {R}" for L, R, _e in TRUE_ROWS
                if ids.get(R, -1) in walk(L, admit, args.budget)[0]]
        scoped = [f"{L} ~ {R}" for L, R, _e in TRUE_ROWS
                  if ids.get(R, -1) in walk_scoped(L, admit, args.budget, "Entropy")]
        rec["scoped_budget"].append({
            "cutoff": M, "global_budget_600": len(glob),
            "scoped_to_right_theory_600": len(scoped),
            "targets_scoped": scoped})
        print(f"  cutoff {M:>10}  global={len(glob)}/4  scoped={len(scoped)}/4", flush=True)

    def walk_work(q: str, W: int) -> set[int]:
        keyed = sorted(holds.get(q, ()), key=lambda k: -idf[k])
        hits, visited = set(), 0
        for k in keyed:
            if visited >= W:
                break
            visited += df[k]
            hits.update(members[k])
        hits.discard(ids.get(q, -1))
        return hits

    rec["work_budget"] = []
    for W in (2_000, 10_000, 50_000, 250_000):
        found = [f"{L} ~ {R}" for L, R, _e in TRUE_ROWS
                 if ids.get(R, -1) in walk_work(L, W)]
        cands = [len(walk_work(q, W)) for q in sample]
        rec["work_budget"].append({
            "postings_visited_budget": W, "n_targets": len(found), "targets": found,
            "cand_median": statistics.median(cands) if cands else None,
            "cand_p90": sorted(cands)[int(0.9 * (len(cands) - 1))] if cands else None})
        print(f"  work<= {W:>8}            targets={len(found)}/4 "
              f"cand_med={rec['work_budget'][-1]['cand_median']}", flush=True)

    (OUT / f"admission-{pathlib.Path(args.slice).stem}.json").write_text(
        json.dumps(rec, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in rec.items() if k != "rules"},
                     indent=1, ensure_ascii=False))


def run_child(path: str, label: str, dst: pathlib.Path, args, heavy: bool) -> None:
    cmd = [sys.executable, str(HERE / "phys-prefilter.py"), "one",
           "--slice", path, "--label", label, "--out", str(dst),
           "--queries", str(args.queries)]
    if heavy:
        cmd.append("--heavy")
    t = time.time()
    p = subprocess.run(cmd)
    print(f"[{label}] child exit={p.returncode} in {time.time()-t:.0f}s", flush=True)


def stage_one(args) -> None:
    rec = measure(args.slice, args.label, args.queries, args.heavy)
    pathlib.Path(args.out).write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    keep = {k: rec.get(k) for k in
            ("label", "n", "max_len", "closure_s", "load_s", "wall_s", "rss_peak_gb",
             "latency_s", "candidate_set")}
    keep["coverage"] = rec.get("closure", {}).get("coverage")
    keep["proposed"] = {k: {kk: v.get(kk) for kk in ("above_floors", "rank", "candidates")}
                        for k, v in rec.get("proposed", {}).items()}
    keep["dict_rows"] = {k: v.get("per_decl=1", {}).get("rows")
                         for k, v in rec.get("dictionaries", {}).items()}
    keep["dict_targets"] = {k: v.get("per_decl=1", {}).get("targets_found")
                            for k, v in rec.get("dictionaries", {}).items()}
    print(json.dumps(keep, indent=1, ensure_ascii=False), flush=True)


def stage_report(args) -> None:
    """Collect the rungs into the table the report quotes."""
    rows = []
    for f in sorted(OUT.glob("*.json")):
        try:
            rec = json.loads(f.read_text())
        except Exception:
            continue
        if "max_len" not in rec:
            continue
        rows.append(rec)
    rows.sort(key=lambda r: r["max_len"])
    hdr = ("label", "n", "max_len", "targets/4", "cand median", "cand max",
           ">=600", "latency ms", "build s", "RSS GB",
           "CI~Ent", "CM~Meta", "CM~QM")
    print("\t".join(hdr))
    for r in rows:
        prop = r.get("proposed", {})
        found = sum(1 for v in prop.values() if v.get("above_floors"))
        cs = r.get("candidate_set", {})
        lat = r.get("latency_s", {})
        dd = r.get("dictionaries", {})

        def dr(k):
            return dd.get(k, {}).get("per_decl=1", {}).get("rows")

        print("\t".join(str(x) for x in (
            r["label"], r["n"], r["max_len"], f"{found}/4",
            cs.get("median"), cs.get("max"), cs.get("at_or_over_budget_600"),
            round(1000 * lat.get("median", 0), 1), r.get("closure_s"),
            r.get("rss_peak_gb"),
            dr("ClassicalInfo ~ Entropy"), dr("ClassicalMechanics ~ Meta"),
            dr("ClassicalMechanics ~ QuantumMechanics"))))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="stage", required=True)

    s = sub.add_parser("sweep", help="the posting-cutoff ladder")
    s.add_argument("--rungs", type=int, nargs="+",
                   default=[0, 200_000, 400_000, 800_000, 1_600_000, 3_200_000])
    s.add_argument("--queries", type=int, default=40)
    s.add_argument("--heavy", nargs="*", default=[])
    s.add_argument("--force", action="store_true")
    s.add_argument("--force-prepare", action="store_true")
    s.set_defaults(fn=stage_sweep)

    m = sub.add_parser("matched", help="same N, same cutoff, different document frequency")
    m.add_argument("--matched-n", type=int, default=200_000)
    m.add_argument("--queries", type=int, default=40)
    m.add_argument("--force", action="store_true")
    m.set_defaults(fn=stage_matched)

    e = sub.add_parser("exhaustive", help="what the prefilter-free path costs")
    e.set_defaults(fn=stage_exhaustive)

    o = sub.add_parser("one", help="measure a single corpus (spawned by `sweep`)")
    o.add_argument("--slice", required=True)
    o.add_argument("--label", required=True)
    o.add_argument("--out", required=True)
    o.add_argument("--queries", type=int, default=40)
    o.add_argument("--heavy", action="store_true")
    o.set_defaults(fn=stage_one)

    a = sub.add_parser("admission", help="alternative admission rules, simulated")
    a.add_argument("--slice", required=True)
    a.add_argument("--queries", type=int, default=40)
    a.add_argument("--budget", type=int, default=600)
    a.set_defaults(fn=stage_admission)

    r = sub.add_parser("report", help="collect the rungs into one table")
    r.set_defaults(fn=stage_report)

    args = p.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
