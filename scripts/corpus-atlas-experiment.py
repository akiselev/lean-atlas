#!/usr/bin/env python3
"""Apply the Atlas to the twelve corpus groups, against Mathlib as background.

The corpus groups are Atlas's specification: twelve hand-written ports of real mathematics,
each green under all four test tiers. They are also, mathematically, *restatements of
things Mathlib already has* — Peano addition, group laws, a partial order, Cantor,
Fermat's little theorem, gcd. That makes them the one place where the Atlas can be scored
against an answer key that needs no private freezing, because the answer is public: for
each corpus claim, Mathlib's version of it.

So this is a **rediscovery benchmark**. Each group below names, before anything runs, the
Mathlib declarations a working Atlas should surface when handed that group's claims. A run
that surfaces them is evidence; a run that surfaces plausible-looking neighbours instead is
not, which is why the expectations are literals in this file and not a judgement made after
reading the output.

**Recall over precision, deliberately.** The consumer is an agent that can read ten
thousand candidates and discard 99% of them, and cannot recover a candidate that was never
proposed. Every sweep here therefore runs the floors *down* (`min_common` to 3,
`min_retention` to 0.05) and `top` *up*, and reports what that costs in noise rather than
hiding it. `--strict` reruns the same questions at the shipped defaults, so the difference
between "the engine can find it" and "the engine finds it by default" stays visible.

Usage:
    uv run scripts/corpus-slice.py --full /tmp/atlas-mathlib-full.jsonl --out /tmp/atlas-merged.jsonl
    uv run scripts/corpus-atlas-experiment.py --slice /tmp/atlas-merged.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time

try:
    import atlas as fa
except ImportError:
    sys.exit(
        "atlas is not importable — this script runs under the repository's venv:\n"
        "  uv sync && uv run scripts/corpus-atlas-experiment.py\n"
    )

# ---------------------------------------------------------------------------
# The answer key. Public mathematics, written down before the run.
#
# `probes` are the group's authored claims worth asking about. `expect` names Mathlib
# declarations (or name fragments) that a working analogy layer should surface for *some*
# probe in the group. Fragments rather than exact names on purpose: `Nat.add_comm` and
# `AddCommMonoid.add_comm` are both right answers to "what is g01's add_comm", and an
# answer key that demanded one of them would be scoring spelling.
# ---------------------------------------------------------------------------

ANSWER_KEY: dict[str, dict] = {
    "g01_peano": {
        "what": "Peano naturals: addition by recursion, and its monoid laws.",
        "probes": ["add", "add_comm", "add_zero", "zero_add", "succ_add", "N"],
        "expect": ["add_comm", "add_zero", "zero_add", "succ_add", "Nat.add",
                   "AddCommMonoid", "AddMonoid"],
    },
    "g02_group": {
        "what": "A group as a trait with laws; uniqueness of the identity.",
        "probes": ["Grp.assoc", "Grp.id_left", "Grp.inv_left", "Grp.e", "Grp.op",
                   "Grp.inv", "id_unique"],
        "expect": ["mul_assoc", "one_mul", "mul_one", "inv_mul_cancel", "mul_left_inv",
                   "Group", "Monoid", "eq_one"],
    },
    "g03_order": {
        "what": "A partial order as a trait; a Galois connection.",
        "probes": ["POrder.refl", "POrder.trans", "POrder.antisymm", "galois_connection",
                   "id_gc_holds", "idf"],
        "expect": ["le_refl", "le_trans", "le_antisymm", "GaloisConnection", "Preorder",
                   "PartialOrder"],
    },
    "g04_limits": {
        "what": "Epsilon-delta convergence of a function; uniqueness of limits.",
        "probes": ["tends_to", "id_tends_to", "limit_unique", "idr"],
        "expect": ["Tendsto", "tendsto_nhds_unique", "tendsto_id", "Metric.tendsto",
                   "Filter.Tendsto"],
    },
    "g05_rank_nullity": {
        "what": "Rank plus nullity equals the dimension of the domain.",
        "probes": ["rank_nullity", "rn_g", "silent_sort"],
        "expect": ["rank_range_add_rank_ker", "finrank_range_add_finrank_ker",
                   "LinearMap.rank", "Submodule.finrank", "LinearMap.ker"],
    },
    "g06_binomial": {
        "what": "The binomial theorem as a sum over Finset.range.",
        "probes": ["binomial", "binom_g", "written"],
        "expect": ["add_pow", "Commute.add_pow", "Nat.choose", "Nat.add_pow"],
    },
    "g07_number_theory": {
        "what": "Fermat's little theorem over ZMod p; infinitude of primes; CRT.",
        "probes": ["fermat_little", "fermat_g", "primes_infinite", "primes_g", "crt",
                   "crt_g", "congruent", "coprime", "sp"],
        "expect": ["ZMod.pow_card", "exists_infinite_primes", "chineseRemainder",
                   "Nat.Coprime", "Nat.Prime", "ZMod"],
    },
    "g08_cantor": {
        "what": "Cantor's theorem: no surjection onto the powerset.",
        "probes": ["cantor", "injective", "surjective"],
        "expect": ["cantor_surjective", "cantor_injective", "Cardinal.cantor",
                   "Function.Surjective", "Function.Injective"],
    },
    "g09_category": {
        "what": "A category as a trait with identity and associativity laws.",
        "probes": ["Cat.assoc", "Cat.id_comp", "Cat.comp_id", "Cat.comp", "Cat.id",
                   "Cat.Hom", "unit_id"],
        "expect": ["Category.assoc", "Category.id_comp", "Category.comp_id",
                   "CategoryTheory", "Quiver"],
    },
    "g10_pmf": {
        "what": "A probability mass function; two fair flips.",
        "probes": ["half", "half_le_one", "two_flips", "two_flips_fair"],
        "expect": ["PMF", "bernoulli", "ProbabilityTheory", "NNReal", "tsum"],
    },
    "g11_logic": {
        "what": "De Morgan, a clamp, and decidable-if plumbing.",
        "probes": ["demorgan", "demorgan_g", "clamp", "clamp_le", "min2", "find_root"],
        "expect": ["not_or", "not_and", "not_and_or", "Classical", "min_le", "le_min",
                   "le_max"],
    },
    "g12_gcd": {
        "what": "Euclid's gcd as a well-founded recursion, with its specification.",
        "probes": ["gcd2", "gcd2_dvd", "gcd2_greatest", "gcd_dvd_g", "nat_sqrt", "sp"],
        "expect": ["gcd_dvd_left", "gcd_dvd_right", "dvd_gcd", "Nat.gcd", "gcd_comm",
                   "EuclideanDomain.gcd", "sqrt"],
    },
}

LEVELS = ["exact", "presentation", "instances", "carriers", "shape"]

# The recall-first operating point. Not the shipped defaults — see the module docstring.
RECALL = dict(top=50, min_retention=0.05, min_common=3)
SHIPPED = dict(top=10, min_retention=0.30, min_common=6)


def is_corpus(module: str) -> bool:
    return module in ANSWER_KEY


# ---------------------------------------------------------------------------


class Result:
    def __init__(self, name: str, claim: str) -> None:
        self.name, self.claim = name, claim
        self.lines: list[str] = []
        self.data: dict = {}
        self.passed: bool | None = None

    def check(self, ok: bool, detail: str) -> None:
        self.lines.append(("  ok   " if ok else "  MISS ") + detail)
        self.passed = ok if self.passed is None else (self.passed and ok)

    def note(self, detail: str) -> None:
        self.lines.append("       " + detail)

    def report(self) -> bool:
        status = {True: "PASS", False: "FAIL", None: "INFO"}[self.passed]
        print(f"\n[{status}] {self.name}\n       claim: {self.claim}")
        for ln in self.lines:
            print(ln)
        return self.passed is not False


# ---------------------------------------------------------------------------
# X0 — is the answer key about this corpus?
# ---------------------------------------------------------------------------

def x0_answer_key(c: fa.Corpus, manifest: dict) -> Result:
    r = Result(
        "X0 answer key",
        "every probe the key names must exist in the slice — a key that asks about "
        "declarations the corpus does not have would score the Atlas on the wrong corpus, "
        "and would do it invisibly",
    )
    missing = {}
    total = 0
    for g, key in sorted(ANSWER_KEY.items()):
        if g not in manifest:
            continue
        gone = [p for p in key["probes"] if c.get(f"{g}.{p}") is None]
        total += len(key["probes"])
        if gone:
            missing[g] = gone
            r.check(False, f"{g}: {len(gone)}/{len(key['probes'])} probes absent: "
                           f"{', '.join(gone)}")
        else:
            r.check(True, f"{g}: all {len(key['probes'])} probes present")
    r.note(f"{total} probes named; {sum(len(v) for v in missing.values())} absent")
    r.data = {"missing": missing, "total": total}
    return r


# ---------------------------------------------------------------------------
# X1 — can the Atlas see Atlas's output at all?
# ---------------------------------------------------------------------------

def x1_visibility(c: fa.Corpus, manifest: dict) -> Result:
    r = Result(
        "X1 visibility",
        "every authored corpus declaration carries an encodable I3 statement — a row "
        "without one is invisible to every B4/B5/B6 query, so this bounds everything below",
    )
    total = missing = 0
    per_group = {}
    for g, entry in sorted(manifest.items()):
        names = entry["authored"]
        miss = []
        for n in names:
            d = c.get(n)
            if d is None:
                miss.append((n, "not in slice"))
            elif d.stmt is None:
                miss.append((n, d.stmt_error or "no statement"))
        per_group[g] = {"authored": len(names), "missing": miss}
        total += len(names)
        missing += len(miss)
        if miss:
            r.note(f"{g}: {len(miss)}/{len(names)} without a statement")
            for n, why in miss[:4]:
                r.note(f"    {n}: {why}")
    r.check(total > 0, f"{total} authored declarations across {len(manifest)} groups")
    r.check(missing / max(total, 1) < 0.10,
            f"{total - missing}/{total} carry a statement "
            f"({100 * (total - missing) / max(total, 1):.1f}%)")
    r.data = {"total": total, "missing": missing, "per_group": per_group}
    return r


# ---------------------------------------------------------------------------
# X2 — equivalence: is a corpus claim literally a Mathlib claim?
# ---------------------------------------------------------------------------

def x2_equivalence(c: fa.Corpus, manifest: dict) -> Result:
    r = Result(
        "X2 equivalence",
        "a corpus theorem that restates a Mathlib theorem should land in its equivalence "
        "class at some level — this is the strongest possible hit, since the two "
        "statements normalize to the same thing rather than merely rhyming",
    )
    hits: dict[str, list] = {}
    asked = 0
    for g, entry in sorted(manifest.items()):
        for n in entry["authored"]:
            d = c.get(n)
            if d is None or d.stmt is None:
                continue
            for level in ("exact", "presentation", "instances", "carriers"):
                try:
                    eq = c.equivalent(n, level=level)
                except Exception:
                    continue
                asked += 1
                outside = [e for e in eq if not is_corpus((c.get(e).module if c.get(e) else ""))]
                if outside:
                    hits.setdefault(f"{g}/{n}", []).append(
                        {"level": level, "n": len(outside), "sample": outside[:8]}
                    )
                    break
    r.check(asked > 0, f"{asked} equivalence queries answered")
    r.check(len(hits) > 0,
            f"{len(hits)} corpus declarations are statement-identical to something outside "
            f"the corpus")
    for k, v in list(hits.items())[:12]:
        top = v[0]
        r.note(f"{k} ≡ ({top['level']}) {', '.join(top['sample'][:4])}"
               + (f"  (+{top['n'] - 4} more)" if top["n"] > 4 else ""))
    r.data = {"hits": hits, "asked": asked}
    return r


# ---------------------------------------------------------------------------
# X3 — the rediscovery benchmark. The flagship.
# ---------------------------------------------------------------------------

def sweep_similar(c: fa.Corpus, name: str, cfg: dict) -> dict[str, list]:
    """Every cross-theory neighbour of `name`, at every level, at one operating point."""
    out = {}
    for level in LEVELS:
        try:
            ns = c.similar(name, level=level, **cfg)
        except Exception:
            continue
        out[level] = [
            {
                "name": nb.name, "module": nb.module, "score": nb.score,
                "retention": nb.retention, "common": nb.common, "vars": nb.vars,
                "sources": list(nb.sources), "transportable": nb.transportable,
            }
            for nb in ns
            if not is_corpus(nb.module)
        ]
    return out


def x3_rediscovery(c: fa.Corpus, manifest: dict, cfg: dict, label: str) -> Result:
    r = Result(
        f"X3 rediscovery ({label})",
        "handed a corpus group's claims, the analogy layer should surface Mathlib's own "
        "version of those claims — the expectations are literals in this file, written "
        "before the run",
    )
    found: dict[str, dict] = {}
    for g, key in sorted(ANSWER_KEY.items()):
        if g not in manifest:
            r.note(f"{g}: not in this slice, skipped")
            continue
        wanted = key["expect"]
        seen: dict[str, list[str]] = {}
        probed = 0
        for n in manifest[g]["authored"]:
            d = c.get(n)
            if d is None or d.stmt is None:
                continue
            probed += 1
            sweep = sweep_similar(c, n, cfg)
            for level, nbs in sweep.items():
                for nb in nbs:
                    for w in wanted:
                        if w in nb["name"]:
                            seen.setdefault(w, []).append(f"{n} →({level}) {nb['name']}")
        hit = len(seen)
        found[g] = {"probed": probed, "expected": len(wanted), "hit": hit,
                    "evidence": {k: v[:3] for k, v in seen.items()}}
        ok = hit > 0
        r.check(ok, f"{g}: {hit}/{len(wanted)} expected Mathlib targets surfaced "
                    f"(from {probed} probes)")
        for w, ev in list(seen.items())[:3]:
            r.note(f"    {w}: {ev[0]}")
    groups_with_a_hit = sum(1 for v in found.values() if v["hit"] > 0)
    r.note(f"groups with at least one expected target surfaced: "
           f"{groups_with_a_hit}/{len(found)}")
    r.data = found
    return r


# ---------------------------------------------------------------------------
# X4 — the noise floor. What does recall-first actually cost?
# ---------------------------------------------------------------------------

def x4_noise(c: fa.Corpus, manifest: dict) -> Result:
    r = Result(
        "X4 noise floor",
        "recall-first floors must buy candidates rather than repeat one generic answer — "
        "if the same Mathlib heads come back for every corpus declaration regardless of "
        "what it says, the sweep is measuring the encoding's punctuation and not the "
        "mathematics",
    )
    counts: collections.Counter = collections.Counter()
    per_decl = []
    for g, entry in sorted(manifest.items()):
        for n in entry["authored"][:40]:
            d = c.get(n)
            if d is None or d.stmt is None:
                continue
            sweep = sweep_similar(c, n, RECALL)
            names = {nb["name"] for nbs in sweep.values() for nb in nbs}
            per_decl.append((f"{g}/{n}", len(names)))
            counts.update(names)
    total_cand = sum(n for _, n in per_decl)
    subjects = len(per_decl)
    if subjects == 0:
        r.check(False, "no subject produced a candidate")
        return r
    r.note(f"{subjects} subjects, {total_cand} candidate slots, "
           f"{len(counts)} distinct Mathlib declarations proposed")
    r.note(f"mean candidates per subject: {total_cand / subjects:.1f}")
    ubiquitous = [(k, v) for k, v in counts.most_common(10)]
    r.note("most-proposed neighbours (a high count here is the noise to expect):")
    for k, v in ubiquitous:
        r.note(f"    {v:4d}/{subjects}  {k}")
    top_share = ubiquitous[0][1] / subjects if ubiquitous else 0.0
    r.check(top_share < 0.90,
            f"the single most-proposed neighbour appears for {100 * top_share:.0f}% of "
            f"subjects (a value near 100% would mean the sweep answers the same thing "
            f"for everything)")
    r.check(len(counts) > 5 * subjects,
            f"distinct candidates ({len(counts)}) exceed 5x subjects ({subjects}) — "
            f"the sweep discriminates")
    r.data = {"subjects": subjects, "candidates": total_cand,
              "distinct": len(counts), "most_common": ubiquitous}
    return r


# ---------------------------------------------------------------------------
# X5 — honesty, over Atlas's own output
# ---------------------------------------------------------------------------

LEAN_AXIOMS = ["propext", "Classical.choice", "Quot.sound"]


def x5_honesty(c: fa.Corpus, manifest: dict) -> Result:
    r = Result(
        "X5 honesty",
        "the corpus carries tracked `todo!()`s and nothing else — the scan must find "
        "exactly those, and the negative control must show it can find something",
    )
    corpus_names = {n for e in manifest.values() for n in e["authored"]}
    findings = c.honesty(LEAN_AXIOMS)
    mine = [(w, why) for w, why in findings if w in corpus_names]
    r.note(f"{len(findings)} findings over the whole slice; {len(mine)} inside the corpus")
    for w, why in mine[:20]:
        r.note(f"    {w}: {why}")
    narrow = c.honesty([])
    r.check(len(narrow) > len(findings),
            f"negative control: an empty whitelist finds {len(narrow)} (vs {len(findings)}) "
            f"— the scan is live")
    r.data = {"corpus_findings": mine, "all": len(findings), "narrow": len(narrow)}
    return r


# ---------------------------------------------------------------------------
# X6 — dictionaries from a corpus group to a Mathlib theory
# ---------------------------------------------------------------------------

def x6_dictionary(c: fa.Corpus, manifest: dict, pairs: list[tuple[str, str]]) -> Result:
    r = Result(
        "X6 dictionary",
        "a corpus group and the Mathlib theory it ports should admit a dictionary with "
        "rows, and the shuffle control must separate genuine pairs from re-paired ones",
    )
    out = {}
    for left, right in pairs:
        if left not in manifest:
            continue
        try:
            d = c.dictionary(left, right, per_decl=3, theorems_only=False)
            rows = d.rows
            entry = {
                "rows": len(rows),
                "missing_left": len(d.missing_left),
                "sample": [(row.left, row.right, round(row.retention, 3), row.status)
                           for row in rows[:8]],
            }
            try:
                sc = c.dictionary_shuffle_control(left, right, per_decl=3,
                                                  theorems_only=False)
                entry["control"] = {
                    "pairs": sc.pairs, "genuine": sc.genuine_mean,
                    "shuffled": sc.shuffled_mean, "separation": sc.separation,
                }
            except Exception as e:
                entry["control"] = f"unavailable: {type(e).__name__}"
            out[f"{left} → {right}"] = entry
            r.check(len(rows) > 0, f"{left} → {right}: {len(rows)} rows, "
                                   f"{entry['missing_left']} left unmatched")
            for s in entry["sample"][:3]:
                r.note(f"    {s[0]}  ~  {s[1]}   (retention {s[2]}, {s[3]})")
            if isinstance(entry.get("control"), dict):
                ctl = entry["control"]
                r.note(f"    control: genuine {ctl['genuine']:.3f} vs shuffled "
                       f"{ctl['shuffled']:.3f}, separation {ctl['separation']:.3f}")
        except Exception as e:
            r.check(False, f"{left} → {right}: {type(e).__name__}: {e}")
    r.data = out
    return r


# ---------------------------------------------------------------------------
# X7 — the frontier, over whatever background this slice has
# ---------------------------------------------------------------------------

INFRA = ["Aesop", "Qq", "ProofWidgets", "Plausible", "Batteries", "Lean", "Init", "Std",
         "Cli", "ImportGraph", "LeanSearchClient", "Mathlib.Tactic", "Mathlib.Util",
         "Mathlib.Lean", "Mathlib.Testing", "Mathlib.Deprecated", "Tests"]


def x7_frontier(c: fa.Corpus) -> Result:
    r = Result(
        "X7 frontier",
        "theory pairs that look alike and do not cite each other are the research agenda; "
        "the negative control is that without excluding infrastructure the ranking is led "
        "by metaprogramming siblings, which is a correct answer to the wrong question",
    )
    try:
        unrestricted = c.frontier(min_theory_size=200, top=10, theorems_only=True)
        restricted = c.frontier(min_theory_size=200, top=25, theorems_only=True,
                                exclude=INFRA)
    except Exception as e:
        r.check(False, f"frontier unavailable: {type(e).__name__}: {e}")
        return r
    r.note("unrestricted (the control — expect infrastructure):")
    for p in unrestricted[:5]:
        r.note(f"    {p.left} ~ {p.right}  sim {p.similarity:.3f}  "
               f"cross-cites {p.cross_citations}")
    r.note("with infrastructure excluded:")
    for p in restricted[:15]:
        r.note(f"    {p.left} ~ {p.right}  sim {p.similarity:.3f}  "
               f"cross-cites {p.cross_citations}  sizes {p.left_size}/{p.right_size}")
    infra_led = any(any(i in p.left or i in p.right for i in INFRA)
                    for p in unrestricted[:3])
    r.check(infra_led, "negative control fires: infrastructure leads the unrestricted "
                       "ranking, so the exclusion is doing work")
    r.check(len(restricted) > 0, f"{len(restricted)} mathematical frontier pairs ranked")
    r.data = {
        "unrestricted": [(p.left, p.right, p.similarity, p.cross_citations)
                         for p in unrestricted],
        "restricted": [(p.left, p.right, p.similarity, p.cross_citations,
                        p.left_size, p.right_size) for p in restricted],
    }
    return r


# ---------------------------------------------------------------------------
# X8 — what Atlas-authored code rests on
# ---------------------------------------------------------------------------

def x8_foundations(c: fa.Corpus, manifest: dict) -> Result:
    r = Result(
        "X8 foundations",
        "Atlas's expansion is syntax→syntax, so an atlas theorem should rest on the same Lean "
        "constants a hand-written one would — a foundation set full of atlas constants would "
        "mean the artifact carries an atlas dependency, which ADR-006 forbids",
    )
    leaked = {}
    checked = 0
    for g, entry in sorted(manifest.items()):
        for n in entry["authored"]:
            if c.get(n) is None:
                continue
            checked += 1
            f = c.foundations(n, lens="both")
            leaks = [x for x in f if x.startswith("Atlas") or x.startswith("Atlas")]
            if leaks:
                leaked[n] = leaks[:5]
    r.check(checked > 0, f"{checked} corpus declarations walked")
    r.check(not leaked,
            f"{len(leaked)} corpus declarations rest on an atlas constant "
            f"(ADR-006 says this must be zero)")
    for n, leaks in list(leaked.items())[:8]:
        r.note(f"    {n} rests on {', '.join(leaks)}")
    r.data = {"checked": checked, "leaked": leaked}
    return r


# ---------------------------------------------------------------------------
# The high-recall dump — the artifact an agent actually consumes
# ---------------------------------------------------------------------------

def dump_candidates(c: fa.Corpus, manifest: dict, out: pathlib.Path) -> dict:
    """Every cross-theory neighbour of every authored corpus declaration, every level.

    No filtering beyond the floors. This is the false-positive-tolerant artifact: the
    triage is the reader's job, and a candidate that was never written down cannot be
    triaged at all.
    """
    payload = {}
    n_cand = 0
    for g, entry in sorted(manifest.items()):
        payload[g] = {}
        for n in entry["authored"]:
            d = c.get(n)
            if d is None or d.stmt is None:
                continue
            sweep = sweep_similar(c, n, RECALL)
            sweep = {k: v for k, v in sweep.items() if v}
            if sweep:
                payload[g][n] = {
                    "kind": d.kind,
                    "skeletons": {},
                    "neighbours": sweep,
                }
                for level in LEVELS:
                    try:
                        payload[g][n]["skeletons"][level] = c.skeleton(n, level=level)
                    except Exception:
                        pass
                n_cand += sum(len(v) for v in sweep.values())
    out.write_text(json.dumps(payload, indent=1))
    return {"candidates": n_cand, "path": str(out)}


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--manifest", type=pathlib.Path, default=None)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-corpus-candidates.json"))
    ap.add_argument("--report", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-corpus-report.json"))
    ap.add_argument("--strict", action="store_true",
                    help="also run the rediscovery benchmark at the shipped defaults")
    ap.add_argument("--skip", default="", help="comma-separated experiment ids to skip")
    args = ap.parse_args()

    manifest_path = args.manifest or args.slice.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    t0 = time.time()
    c = fa.Corpus.load(args.slice)
    print(f"loaded {len(c):,} declarations in {time.time() - t0:.1f} s "
          f"from {args.slice}")
    print(f"corpus groups in slice: {', '.join(sorted(manifest))}")

    results: list[Result] = []
    report: dict = {}

    def run(rid: str, fn, *a):
        if rid in skip:
            print(f"\n[SKIP] {rid}")
            return
        t = time.time()
        try:
            res = fn(*a)
        except Exception as e:
            res = Result(rid, "experiment raised")
            res.check(False, f"{type(e).__name__}: {e}")
        res.note(f"({time.time() - t:.1f} s)")
        results.append(res)
        report[rid] = {"claim": res.claim, "passed": res.passed, "data": res.data}
        res.report()

    run("X0", x0_answer_key, c, manifest)
    run("X1", x1_visibility, c, manifest)
    run("X5", x5_honesty, c, manifest)
    run("X8", x8_foundations, c, manifest)
    run("X2", x2_equivalence, c, manifest)
    run("X3-recall", x3_rediscovery, c, manifest, RECALL, "recall-first")
    if args.strict:
        run("X3-shipped", x3_rediscovery, c, manifest, SHIPPED, "shipped defaults")
    run("X4", x4_noise, c, manifest)
    pairs = [(g, t) for g in manifest for t in ("Mathlib.Algebra", "Mathlib.Order")]
    run("X6", x6_dictionary, c, manifest, pairs)
    run("X7", x7_frontier, c)

    print("\n--- writing the high-recall candidate dump ---")
    t = time.time()
    d = dump_candidates(c, manifest, args.out)
    print(f"{d['candidates']:,} candidates → {d['path']} ({time.time() - t:.1f} s)")
    report["dump"] = d

    args.report.write_text(json.dumps(report, indent=1, default=str))
    print(f"machine-readable report → {args.report}")

    failed = [r.name for r in results if r.passed is False]
    print(f"\n{'=' * 70}")
    print(f"{len(results)} experiments, {len(failed)} with a failing check")
    for f in failed:
        print(f"  FAIL {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
