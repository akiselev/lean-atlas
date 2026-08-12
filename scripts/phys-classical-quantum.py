#!/usr/bin/env python3
"""Does the Atlas recover the classical ↔ quantum dictionary from structure alone?

The pre-registration — the expected correspondences, the predictions, the controls and the
scoring protocol — is `research/physlib-classical-quantum.md` §1–§2, written before this
script was run. Read it first; this file is the instrument, not the claim.

## Why this corpus and not Mathlib

Mathlib's cross-theory analogies are `to_additive` pairs: two statements of the same shape
differing in one operator. Physics correspondences are not shape-preserving — a Poisson
bracket and a commutator share their *laws* and nothing of their carriers — so this is the
first corpus on which "cross-theory analogy" means what the phrase suggests.

## Three things this script refuses to do

1. **Run on an unclosed slice.** `Corpus.closure()` is checked before any query at
   `instances` or above and the run aborts below the floor. An unclosed slice does not
   fail, it answers with a normalization that quietly did not happen (findings §31/§32),
   and `/tmp/atlas-physlib.jsonl` is 12.4% closed.
2. **Trust an erasure it has not seen fire.** NC2 asserts that `carriers` differs from
   `presentation` somewhere in this corpus. An inert erasure passes every downstream check
   by returning the unerased term — that is how source B stayed dead for 60.6% of a corpus
   behind a green suite.
3. **Score a dictionary against its own null at a different configuration.**
   `dictionary_shuffle_control` takes neither `anchor` nor `score`, so it cannot be run at
   the setting the dictionary is reported at. This script therefore carries its own shuffle
   control, written against `generalize` — a second implementation over the same data, so a
   shared bug cannot make both agree — and prints an **informativeness verdict**, because
   genuine 0.000 against shuffled 0.000 is a dead control and not a pass (findings §46).

## The subfield rewrite

`dict::theory_of` takes the module prefix at depth 1 outside Mathlib, so every physlib
declaration files under `Physlib` and the whole library is one theory. `dictionary("Class"
"icalMechanics", …)` then silently returns zero rows — no error, no warning, an empty
dictionary that reads like a negative result. `scripts/physlib-experiment.py` established
the fix: strip the library root so each subfield is its own theory. Done here to a file of
this script's own, never in place.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import re
import sys
import time

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

ROOTS = re.compile(r"^(?:Physlib|QuantumInfo)\.(.+)$")

# Theory pairs, fixed in the pre-registration. `expect` records what §2 predicted *before*
# the run, so a reader can see which of these were controls and which were the question.
PAIRS: list[tuple[str, str, str]] = [
    ("ClassicalMechanics", "QuantumMechanics", "E1-E15: the question"),
    ("QuantumMechanics", "ClassicalMechanics", "E1-E15, other direction"),
    ("ClassicalInfo", "Entropy", "E16-E19: the easier half"),
    ("ClassicalInfo", "States", "E20"),
    ("ClassicalInfo", "Channels", "E18"),
    ("ClassicalMechanics", "StatisticalMechanics", "bonus: micro/macro"),
    ("ClassicalFieldTheory", "QFT", "bonus: field quantisation"),
    # NC3 — negative theory pairs. No classical/quantum correspondence exists between
    # these, so whatever the pipeline produces here is what "a dictionary between two
    # arbitrary physics modules" looks like.
    ("ClassicalMechanics", "Units", "NC3 negative control"),
    ("ClassicalMechanics", "Meta", "NC3 negative control"),
    ("Thermodynamics", "Meta", "NC3 negative control"),
]


# ---------------------------------------------------------------------------- preparation


def prepare(src: pathlib.Path, dst: pathlib.Path, force: bool = False) -> dict:
    """Rewrite module roots so each physics subfield is its own theory."""
    if dst.exists() and not force and dst.stat().st_size > 0:
        counts: collections.Counter = collections.Counter()
        n = 0
        with dst.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                n += 1
                counts[json.loads(line).get("module", "").split(".")[0]] += 1
        return {"rows": n, "subfields": counts, "reused": True}
    # A closure slice is gigabytes and a JSON round-trip of it costs minutes, so the rewrite
    # is a textual substitution on the one field, with a per-line fallback to real parsing
    # whenever the fast pattern does not match. The fallback count is reported: a rewrite
    # that silently missed rows would leave those declarations in a theory of their own.
    fast = re.compile(r'"module":"(?:Physlib|QuantumInfo)\.')
    field = re.compile(r'"module":"([^"]*)"')
    counts = collections.Counter()
    n = fallbacks = 0
    with src.open() as fh, dst.open("w") as out:
        for line in fh:
            if not line.strip():
                continue
            n += 1
            new = fast.sub('"module":"', line, count=1)
            m = field.search(new)
            if m is None:
                row = json.loads(new)
                mm = ROOTS.match(row.get("module", ""))
                if mm:
                    row["module"] = mm.group(1)
                new = json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
                counts[row.get("module", "").split(".")[0]] += 1
                fallbacks += 1
            else:
                counts[m.group(1).split(".")[0]] += 1
            out.write(new)
    return {"rows": n, "subfields": counts, "reused": False, "fallbacks": fallbacks}


# -------------------------------------------------------------------------------- gates


def gate_closure(c: fa.Corpus, floor: float, allow_unclosed: bool = False) -> dict:
    """NC1. Below the floor the run aborts: a caveat is not a substitute for a corpus.

    `allow_unclosed` exists for one purpose — running the *defective* arm of a paired
    closure ablation, the way `scripts/foundation-control.py` runs the foundation-stripped
    arm. Any run using it is stamped `"defective_arm": True` in the report, and its numbers
    are only ever quoted beside the closed arm's.
    """
    known, unknown, coverage, worst = c.closure(top=12)
    print(f"  application heads {known + unknown:,}   missing {unknown:,}")
    print(f"  COVERAGE {coverage * 100:.2f}%   (floor {floor * 100:.0f}%)")
    if worst:
        print("  worst: " + ", ".join(f"{n} ({k:,})" for n, k in worst[:8]))
    if coverage < floor:
        if not allow_unclosed:
            sys.exit(
                f"ABORT: closure {coverage * 100:.2f}% is below the {floor * 100:.0f}% "
                "floor. Every query at `instances` or above would be computed against a "
                "normalization that did not happen (findings §31)."
            )
        print("  *** DEFECTIVE ARM: below the floor, running anyway by explicit request ***")
    return {"known": known, "unknown": unknown, "coverage": coverage,
            "below_floor": coverage < floor,
            "worst": [(n, k) for n, k in worst]}


def gate_erasure_live(c: fa.Corpus, names: list[str], sample: int = 400) -> dict:
    """NC2. The erasure must be seen to fire on *this* corpus before anything is read off it.

    A missing head constant holes nothing and the spine degrades to `presentation`. If that
    happened everywhere, `carriers` would equal `presentation` everywhere and every level
    sweep below would be measuring one level three times — silently, in the direction that
    still produces output.
    """
    live_cp = live_pi = seen = 0
    example = None
    for n in names[:sample]:
        try:
            inst = c.skeleton(n, level="instances")
            pres = c.skeleton(n, level="presentation")
            car = c.skeleton(n, level="carriers")
        except Exception:
            continue
        seen += 1
        if car != pres:
            live_cp += 1
            if example is None:
                example = (n, pres[:90], car[:90])
        if inst != pres:
            live_pi += 1
    print(f"  {seen} statements erased; carriers≠presentation {live_cp}, "
          f"instances≠presentation {live_pi}")
    if example:
        print(f"  e.g. {example[0]}\n       presentation {example[1]}\n       carriers     {example[2]}")
    if seen and live_cp == 0 and live_pi == 0:
        sys.exit("ABORT: the erasure is inert on this corpus — every level is the identity.")
    return {"sampled": seen, "carriers_differ": live_cp, "instances_differ": live_pi}


# --------------------------------------------------------------------------- dictionaries


def row_dump(c: fa.Corpus, r, level: str = "carriers") -> dict:
    """One row with everything needed to classify it by statement rather than by name."""
    out = {
        "left": r.left, "right": r.right, "retention": round(r.retention, 4),
        "status": r.status, "transportable": r.transportable,
        "skeleton": r.skeleton,
    }
    for side, name in (("left", r.left), ("right", r.right)):
        d = c.get(name)
        out[f"{side}_module"] = d.module if d else None
        out[f"{side}_kind"] = d.kind if d else None
        try:
            out[f"{side}_skel"] = c.skeleton(name, level=level)
        except Exception as e:
            out[f"{side}_skel"] = f"<{type(e).__name__}>"
        try:
            out[f"{side}_requires"] = c.requires(name)
        except Exception:
            out[f"{side}_requires"] = []
    return out


def run_dictionary(c: fa.Corpus, left: str, right: str, *, anchor: str, per_decl: int,
                   score: str, max_per_right, theorems_only: bool, top: int) -> dict:
    t0 = time.time()
    try:
        d = c.dictionary(left, right, per_decl=per_decl, theorems_only=theorems_only,
                         anchor=anchor, score=score, max_per_right=max_per_right)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    dt = time.time() - t0
    rows = [row_dump(c, r) for r in d.rows[:top]]
    return {
        "left": left, "right": right, "anchor": anchor, "per_decl": per_decl,
        "score": score, "max_per_right": max_per_right, "theorems_only": theorems_only,
        "n_rows": len(d.rows), "n_missing_left": len(d.missing_left),
        "n_missing_right": len(d.missing_right),
        "distinct_lefts": len({r.left for r in d.rows}),
        "distinct_rights": len({r.right for r in d.rows}),
        "seconds": round(dt, 1),
        "rows": rows,
        "missing_left": d.missing_left[:200],
        "missing_right": d.missing_right[:200],
    }


def shuffle_control(c: fa.Corpus, dic: dict, *, anchor: str, pool: list[str],
                    seed: int = 20260803) -> dict:
    """This script's own null, at the configuration the dictionary was actually run at.

    `Corpus.dictionary_shuffle_control` takes neither `anchor` nor `score`, so it answers
    about a root-anchored retention dictionary no matter what was reported. Here each
    genuine `(left, right)` is re-paired and both are anti-unified through `generalize` at
    the same anchor.

    Two shuffled arms, because they bound the answer from opposite sides:

    * **matched** — the alternate is drawn from the rights that *did* match something, so
      the null is made of statements already known to be matchable. Hard to beat, and the
      conservative reading.
    * **broad** — the alternate is any theorem of the right theory, which is what the
      engine's own control approximates. Easy to beat, and the one that goes to zero when
      the dictionary is nearly empty.

    Reported with an informativeness verdict: genuine ~0 against shuffled ~0 is a dead
    control and not a pass (findings §46).
    """
    rows = dic.get("rows") or []
    if not rows:
        return {"pairs": 0, "verdict": "no rows to control"}
    rng = random.Random(seed)
    matched = sorted({r["right"] for r in rows})
    arms = {"matched": matched, "broad": pool}
    out: dict = {"pairs": 0}
    gen_vals: list[float] = []
    for arm, cands in arms.items():
        if len(cands) < 2:
            out[arm] = {"verdict": f"pool has {len(cands)} candidate(s)"}
            continue
        gen, shuf, wins, ties = [], [], 0, 0
        for r in rows:
            try:
                g = c.generalize(r["left"], r["right"], anchor=anchor)
            except Exception:
                continue
            alt = r["right"]
            for _try in range(20):
                alt = rng.choice(cands)
                if alt != r["right"] and alt != r["left"]:
                    break
            if alt == r["right"]:
                continue
            try:
                s = c.generalize(r["left"], alt, anchor=anchor)
            except Exception:
                continue
            gen.append(g.retention)
            shuf.append(s.retention)
            if g.retention > s.retention:
                wins += 1
            elif g.retention == s.retention:
                ties += 1
        if not gen:
            out[arm] = {"verdict": "no comparable pairs"}
            continue
        gm, sm = sum(gen) / len(gen), sum(shuf) / len(shuf)
        dead = gm < 0.02 and sm < 0.02
        out[arm] = {
            "pairs": len(gen), "genuine_mean": round(gm, 4),
            "shuffled_mean": round(sm, 4), "separation": round(wins / len(gen), 4),
            "ties": ties,
            "verdict": ("DEAD — both arms ~0" if dead else
                        "informative" if abs(gm - sm) > 0.02 else
                        "UNINFORMATIVE — arms within 0.02"),
        }
        out["pairs"] = max(out["pairs"], len(gen))
        gen_vals = gen
    out["genuine_mean"] = round(sum(gen_vals) / len(gen_vals), 4) if gen_vals else None
    out["verdict"] = "; ".join(f"{k}: {v.get('verdict')}" for k, v in out.items()
                               if isinstance(v, dict))
    return out


def own_coherence(dic: dict) -> dict:
    """Collision structure of the rows as reported, since `dictionary_coherence` is
    anchor-blind and therefore describes a different dictionary than the one printed."""
    rows = dic.get("rows") or []
    claims: collections.Counter = collections.Counter(r["right"] for r in rows)
    contested = sum(1 for _r, k in claims.items() if k > 1)
    in_collision = sum(k for k in claims.values() if k > 1)
    return {"rows_dumped": len(rows), "distinct_rights": len(claims),
            "contested": contested,
            "collision_rate": round(in_collision / len(rows), 4) if rows else 0.0,
            "worst": claims.most_common(6)}


# ------------------------------------------------------------------ the targeted oracle

# Pairs a physicist names as corresponding, written from the ground truth of §2a and then
# resolved to declaration names by reading physlib's source. The names are *disclosed input*
# — they choose which question is asked. Nothing about a name is ever evidence for an
# answer: every number below is an anti-unification of the two statements.
#
# Two pairs are deliberately not correspondences and are marked `control`: they are the
# "same symbol, no content" family that §21 found dominating physlib dictionaries, and they
# exist so a reader can see what a *trivial* high score looks like next to a real one.
TARGETED: list[tuple[str, str, str]] = [
    # E16-E20 — classical vs quantum information
    ("Hₛ_nonneg", "Sᵥₙ_nonneg", "E16 Shannon ≥ 0 ~ von Neumann ≥ 0"),
    ("Hₛ_le_log_d", "Sᵥₙ_le_log_d", "E16 max-entropy bound, both sides"),
    ("Hₛ_constant_eq_zero", "Sᵥₙ_of_pure_zero", "E16/E20 deterministic ~ pure ⇒ zero entropy"),
    ("H₁_nonneg", "Sᵥₙ_nonneg", "E16 binary entropy ≥ 0"),
    ("Prob.coe_le_one", "MState.eigenvalue_le_one", "E20 probability ≤ 1 ~ eigenvalue ≤ 1"),
    ("Prob.zero_le", "MState.eigenvalue_nonneg", "E20 probability ≥ 0 ~ eigenvalue ≥ 0"),
    ("ProbDistribution.normalized", "Ket.normalized",
     "E5/E20 probabilities sum to 1 ~ amplitudes square-sum to 1"),
    ("ProbDistribution.zero_le_expect_val", "MState.exp_val_nonneg",
     "E7 expectation ≥ 0 ~ ⟨A⟩ ≥ 0"),
    ("ProbDistribution.expect_val_constant", "MState.exp_val_one",
     "E7 expectation of a constant ~ Tr(ρ·1)"),
    # E1-E15 — classical vs quantum mechanics
    ("ClassicalMechanics.HarmonicOscillator.energy_eq",
     "QuantumMechanics.HarmonicOscillator.hamiltonain_eq", "E3/E8 H = T + V, both sides"),
    ("ClassicalMechanics.HarmonicOscillator.hamiltonian_eq_energy",
     "QuantumMechanics.HarmonicOscillator.hamiltonain_eq", "E3 Hamiltonian is the energy"),
    ("ClassicalMechanics.HarmonicOscillator.potentialEnergy_eq",
     "QuantumMechanics.HarmonicOscillator.potentialFunction_eq", "E8 the same potential"),
    ("RigidBody.angularMomentum_eq_inertiaTensor_mulVec",
     "QuantumMechanics.angularMomentumOperator_apply", "E12 angular momentum"),
    ("RigidBody.inertiaTensorAbout_symmetric",
     "QuantumMechanics.momentumOperator_isSymmetric",
     "E2 symmetric tensor ~ symmetric operator"),
    ("ClassicalMechanics.hamiltonEqOp_eq_zero_iff_hamiltons_equations",
     "QuantumMechanics.OneDimension.HarmonicOscillator.schrodingerOperator_eigenfunction",
     "E4 Hamilton's equations ~ the Schrödinger operator"),
    ("ClassicalMechanics.HarmonicOscillator.energy_conservation_of_equationOfMotion",
     "QuantumMechanics.QuantumSystem.ℋ_self_adjoint",
     "E10/E17 conservation ~ self-adjointness of the generator"),
    # controls: the same symbol on both sides, no physical content
    ("ClassicalMechanics.HarmonicOscillator.ω_pos",
     "QuantumMechanics.HarmonicOscillator.ω_pos", "control — content-free positivity"),
    ("ClassicalMechanics.HarmonicOscillator.m_ne_zero",
     "QuantumMechanics.HarmonicOscillator.m_ne_zero", "control — content-free ≠ 0"),
]


def targeted(c: fa.Corpus, names_set: set[str], rng: random.Random,
             pool_by_theory: dict[str, list[str]], brute: bool = False) -> list[dict]:
    """For each named correspondence: can the anti-unifier see it, and was it proposed?

    Findings §5 splits recall loss into "never proposed by the prefilter" and "buried by the
    ranking", and the split is the actionable part. Here it is measured directly on pairs a
    physicist supplies: `generalize` answers whether there is shared structure at all,
    `similar` answers whether retrieval would ever have shown it.
    """
    out = []
    for left, right, tag in TARGETED:
        rec: dict = {"left": left, "right": right, "tag": tag}
        if left not in names_set or right not in names_set:
            rec["status"] = ("left missing" if left not in names_set else "") + \
                            ("right missing" if right not in names_set else "")
            out.append(rec)
            continue
        rec["status"] = "ok"
        rec["left_module"] = c.get(left).module
        rec["right_module"] = c.get(right).module
        for anchor in ("root", "conclusion"):
            try:
                g = c.generalize(left, right, anchor=anchor)
                rec[f"lgg_{anchor}"] = {"common": g.common, "vars": g.vars,
                                        "scoped": g.scoped_vars,
                                        "retention": round(g.retention, 4),
                                        "skeleton": g.skeleton[:220]}
            except Exception as e:
                rec[f"lgg_{anchor}"] = {"error": f"{type(e).__name__}: {e}"}
            # The null for this pair: the same left against random rights of the right's
            # own theory. Without it a retention of 0.4 cannot be read as high or low.
            th = theory_of(c.get(right).module)
            pool = pool_by_theory.get(th, [])
            vals = []
            for _ in range(8):
                if not pool:
                    break
                alt = rng.choice(pool)
                if alt in (left, right):
                    continue
                try:
                    vals.append(c.generalize(left, alt, anchor=anchor).retention)
                except Exception:
                    pass
            rec[f"null_{anchor}"] = round(sum(vals) / len(vals), 4) if vals else None
        for level in ("carriers", "shape", "presentation"):
            for anchor in ("root", "conclusion"):
                try:
                    nbs = c.similar(left, top=200, level=level, min_retention=0.02,
                                    min_common=2, theorems_only=False, anchor=anchor)
                except Exception as e:
                    rec[f"rank_{level}_{anchor}"] = f"<{type(e).__name__}>"
                    continue
                rank = next((i + 1 for i, n in enumerate(nbs) if n.name == right), None)
                rec[f"rank_{level}_{anchor}"] = rank
                rec[f"returned_{level}_{anchor}"] = len(nbs)
        if brute:
            # The differential: `similar_brute` switches the prefilter off and anti-unifies
            # against every declaration. If brute ranks the partner and `similar` does not,
            # the loss is in candidate generation and no floor or scorer can recover it —
            # findings §5's split, asked of a pair rather than of an aggregate. Root-anchored
            # only, because `similar_brute` takes no anchor.
            try:
                bs = c.similar_brute(left, top=400, level="carriers")
                rec["brute_rank_root"] = next(
                    (i + 1 for i, (n, _r) in enumerate(bs) if n == right), None)
                rec["brute_returned"] = len(bs)
            except Exception as e:
                rec["brute_rank_root"] = f"<{type(e).__name__}>"
        out.append(rec)
    return out


def exhaustive_dictionary(c: fa.Corpus, lefts: list[str], rights: list[str], *,
                          anchor: str, min_retention: float, min_common: int,
                          max_pairs: int) -> dict:
    """Every left against every right, with no prefilter at all.

    The engine's retrieval drops a posting list longer than `max(0.001 N, 50)` as
    uninformative (`index.rs` `max_len`), and buckets above `max_bucket` contribute nothing.
    That is the right call for "what looks like this declaration" over a whole corpus, and
    it is exactly wrong for a cross-theory dictionary: two theories that state the same idea
    in generic mathematics — `0 ≤ f x`, `∑ = 1` — share only *common* keys, which are the
    ones the index discards.

    This is the ablation that turns that from a story into a number: the same floors, the
    same anti-unifier, no candidate generation. What it finds and the dictionary does not is
    the prefilter's false-negative set, measured rather than estimated. It is affordable
    precisely where it matters — a dictionary between two theories of a few hundred
    declarations is tens of thousands of anti-unifications at ~4 ms each.
    """
    pairs = len(lefts) * len(rights)
    if pairs > max_pairs:
        return {"skipped": f"{pairs:,} pairs exceeds --max-pairs"}
    t0 = time.time()
    rows = []
    for l in lefts:
        for r in rights:
            try:
                g = c.generalize(l, r, anchor=anchor)
            except Exception:
                continue
            if g.retention >= min_retention and g.common >= min_common:
                rows.append((round(g.retention, 4), l, r, g.common, g.vars, g.scoped_vars))
    rows.sort(reverse=True)
    return {"pairs_evaluated": pairs, "rows": rows, "n_rows": len(rows),
            "distinct_lefts": len({r[1] for r in rows}),
            "distinct_rights": len({r[2] for r in rows}),
            "seconds": round(time.time() - t0, 1)}


def dilution(src: pathlib.Path, left: str, right: str, targets: list[tuple[str, str]],
             sizes: list[int], workdir: pathlib.Path, anchor: str = "conclusion") -> list[dict]:
    """The same dictionary between the same two theories, in corpora of growing size.

    Found by accident and then built on purpose: on a 347-row slice holding only these two
    theories, the shipped `dictionary` returns `Hₛ_nonneg ~ Sᵥₙ_nonneg` as its top row; on
    the 14,563-row slice containing the same 347 rows it returns none of the pre-registered
    correspondences at all.

    The mechanism is `Postings::build`'s `max_len = max(0.001·N, 50)`: a key held by more
    declarations than that is **dropped, not down-weighted** (`index.rs:95-98`). The key
    carrying `0 ≤ f x` is under the cap in a small corpus and over it in a large one, so
    *adding unrelated declarations deletes a true row*. Nothing about the two theories
    changed.

    Only the surrounding corpus varies here; the two theories' rows are identical in every
    arm, so anything that moves is caused by the dilution.
    """
    in_theory, others = [], []
    for line in src.open():
        if not line.strip():
            continue
        m = re.search(r'"module":"([^"]*)"', line)
        mod = m.group(1) if m else ""
        th = theory_of(mod)
        (in_theory if th in (left, right) else others).append(line)
    rng = random.Random(4242)
    rng.shuffle(others)
    out = []
    for extra in sizes:
        path = workdir / f"phys-cq-dilute-{extra}.jsonl"
        with path.open("w") as w:
            w.writelines(in_theory)
            w.writelines(others[:extra])
        n = len(in_theory) + min(extra, len(others))
        c = fa.Corpus.load(str(path))
        try:
            d = c.dictionary(left, right, per_decl=3, theorems_only=True, anchor=anchor)
            rows = {(r.left, r.right) for r in d.rows}
            rec = {
                "declarations": n,
                "max_len": max(int(n * 0.001), 50),
                "rows": len(d.rows),
                "found": [t for t in targets if tuple(t) in rows],
                "n_found": sum(1 for t in targets if tuple(t) in rows),
                "top": [(round(r.retention, 3), r.left, r.right) for r in d.rows[:3]],
            }
        except Exception as e:
            rec = {"declarations": n, "error": f"{type(e).__name__}: {e}"}
        out.append(rec)
        path.unlink(missing_ok=True)
    return out


# ------------------------------------------------------------------------ engine surfaces


def theory_of(module: str) -> str:
    """The engine's own rule, mirrored so Python-side filters agree with Rust-side ones."""
    depth = 2 if module.startswith("Mathlib.") else 1
    parts = module.split(".")
    return ".".join(parts[:depth])


def cross_theory_similar(c: fa.Corpus, queries: list[str], targets: set[str], *,
                         level: str, anchor: str, top: int, min_retention: float,
                         min_common: int) -> list[dict]:
    """`similar` with the floors dropped, filtered to the target theories afterwards.

    Recall first: `dictionary` restricts retrieval to the right theory but fixes the floors
    at 0.30/6 and exposes no level. Here the floors go to the bottom and the restriction is
    done in Python, so a candidate that the dictionary's floors would have dropped is still
    visible — and a candidate the *prefilter* never proposed is still invisible, which is
    the honest boundary (findings §5: 33.3% of missed neighbours were never proposed).
    """
    out = []
    for q in queries:
        try:
            nbs = c.similar(q, top=top, level=level, min_retention=min_retention,
                            min_common=min_common, theorems_only=False, anchor=anchor)
        except Exception as e:
            out.append({"query": q, "error": f"{type(e).__name__}: {e}"})
            continue
        hits = [n for n in nbs if theory_of(n.module) in targets]
        out.append({
            "query": q,
            "n_returned": len(nbs),
            "n_cross": len(hits),
            "hits": [{"name": n.name, "module": n.module, "retention": round(n.retention, 4),
                      "common": n.common, "vars": n.vars, "score": round(n.score, 4),
                      "sources": n.sources, "transportable": n.transportable,
                      "skeleton": n.skeleton[:400]} for n in hits[:12]],
        })
    return out


def spanning_classes(c: fa.Corpus, level: str, theories: set[str], top: int = 40) -> list[dict]:
    """Equivalence classes whose members straddle two of the named theories.

    A class is `erase(stmt, level)` equality, so a spanning class is the strongest possible
    structural claim: not "similar", *identical* after erasure.
    """
    out = []
    try:
        cls = c.classes(level=level, theorems_only=True, top=None)
    except Exception as e:
        return [{"error": f"{type(e).__name__}: {e}"}]
    for size, members in cls:
        ths = {theory_of(c.get(m).module) for m in members if c.get(m)}
        if len(ths & theories) >= 2:
            out.append({"size": size, "theories": sorted(ths & theories),
                        "all_theories": sorted(ths)[:8], "members": members[:12]})
        if len(out) >= top:
            break
    return out


def spanning_motifs(c: fa.Corpus, theories: set[str], *, source: str, min_family: int,
                    min_size: int, top: int) -> list[dict]:
    try:
        ms = c.motifs(source=source, min_family=min_family, min_size=min_size, top=top)
    except Exception as e:
        return [{"error": f"{type(e).__name__}: {e}"}]
    out = []
    for pattern, members, size, idf in ms:
        ths = collections.Counter()
        for m in members:
            d = c.get(m)
            if d:
                ths[theory_of(d.module)] += 1
        spanned = {t for t in ths if t in theories}
        if len(spanned) >= 2:
            out.append({"pattern": pattern[:300], "size": size, "idf": round(idf, 3),
                        "family": len(members), "spanned": sorted(spanned),
                        "theory_counts": dict(ths.most_common(8)),
                        "members": members[:10]})
    return out


# ---------------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    # Default to a *closed* physics slice, because the gate below refuses anything else and
    # the point of a default is to be the thing you should have used. `/tmp/atlas-physlib.jsonl`
    # is the 12.39%-closed extraction and needs --allow-unclosed to load at all.
    ap.add_argument("--slice", type=pathlib.Path,
                    default=pathlib.Path("/tmp/pc-physclosed.jsonl"))
    ap.add_argument("--prepared", type=pathlib.Path,
                    default=pathlib.Path("/tmp/phys-cq-theories.jsonl"))
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/phys-cq-report.json"))
    ap.add_argument("--no-prepare", action="store_true",
                    help="load --slice directly; for prototyping on a Mathlib slice")
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--allow-unclosed", action="store_true",
                    help="run below the closure floor as the defective arm of a paired "
                         "ablation; the report is stamped and the numbers are only quoted "
                         "beside the closed arm's")
    ap.add_argument("--pair", action="append", default=[],
                    help="LEFT:RIGHT, overriding the pre-registered list")
    ap.add_argument("--stages", default="census,gates,dict,similar,classes,motifs,frontier")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--quick", action="store_true", help="one anchor sweep only")
    ap.add_argument("--dilute-sizes", type=lambda s: [int(x) for x in s.split(",")],
                    default=[0, 250, 1000, 3000, 7000, 14000, 60000, 250000],
                    help="declarations added around the two theories in the dilution stage")
    ap.add_argument("--exh-anchors", default="root,conclusion",
                    help="anchors for the exhaustive stage; the sweep is quadratic, so a "
                         "large theory pair is usually run at one anchor at a time")
    ap.add_argument("--max-pairs", type=int, default=250_000,
                    help="cap on left×right for the exhaustive stage")
    ap.add_argument("--brute", action="store_true",
                    help="add the prefilter-off differential to the targeted stage; one "
                         "anti-unification per declaration per query, so only on small slices")
    ap.add_argument("--probe-n", type=int, default=60,
                    help="queries sampled per theory for the `similar` probe")
    args = ap.parse_args()

    stages = set(args.stages.split(","))
    report: dict = {"slice": str(args.slice), "stages": sorted(stages)}
    pairs = ([(l, r, "cli") for l, r in (p.split(":", 1) for p in args.pair)]
             if args.pair else PAIRS)

    src = args.slice
    if not args.no_prepare:
        t0 = time.time()
        meta = prepare(args.slice, args.prepared)
        print(f"prepared {meta['rows']:,} rows in {time.time() - t0:.0f}s "
              f"({'reused' if meta['reused'] else 'written'}); "
              f"{len(meta['subfields'])} top-level theories")
        report["census"] = dict(meta["subfields"].most_common(40))
        src = args.prepared

    t0 = time.time()
    c = fa.Corpus.load(str(src))
    print(f"loaded {len(c):,} declarations in {time.time() - t0:.0f}s")
    names = c.names()
    report["declarations"] = len(c)

    if "census" in stages:
        print("\n=== theory census (theorems with statements) ===")
        th = collections.Counter()
        thm = collections.Counter()
        for n in names:
            d = c.get(n)
            if not d:
                continue
            t = theory_of(d.module)
            th[t] += 1
            if d.kind == "theorem" and d.stmt:
                thm[t] += 1
        for t, k in th.most_common(30):
            print(f"  {t:28s} {k:7,}  theorems {thm[t]:6,}")
        report["theories"] = {t: [k, thm[t]] for t, k in th.most_common(60)}

    if "gates" in stages:
        print("\n=== NC1 closure ===")
        report["closure"] = gate_closure(c, args.min_coverage, args.allow_unclosed)
        report["defective_arm"] = bool(report["closure"].get("below_floor"))
        print("\n=== NC2 erasure liveness ===")
        phys = [n for n in names if theory_of(c.get(n).module) in
                {l for l, _r, _e in pairs} | {r for _l, r, _e in pairs}] or names
        report["erasure_live"] = gate_erasure_live(c, phys)

    if "targeted" in stages:
        print("\n=== targeted: named correspondences, one pair at a time ===")
        names_set = set(names)
        pools: dict[str, list[str]] = {}
        for n in names:
            d = c.get(n)
            if d and d.kind == "theorem" and d.stmt:
                pools.setdefault(theory_of(d.module), []).append(n)
        res = targeted(c, names_set, random.Random(11), pools, brute=args.brute)
        hdr = f"  {'pair':<62} {'root':>6} {'concl':>6} {'null_r':>6} {'null_c':>6} {'rank(c/r)':>10}"
        print(hdr)
        for r in res:
            if r["status"] != "ok":
                print(f"  {r['left'][:30]} ~ {r['right'][:28]:<28} NOT IN SLICE: {r['status']}")
                continue
            lr = r.get("lgg_root", {}).get("retention")
            lc = r.get("lgg_conclusion", {}).get("retention")
            print(f"  {(r['left'][:30] + ' ~ ' + r['right'][:28]):<62} "
                  f"{lr if lr is not None else '-':>6} {lc if lc is not None else '-':>6} "
                  f"{r.get('null_root') or '-':>6} {r.get('null_conclusion') or '-':>6} "
                  f"{str(r.get('rank_carriers_conclusion')) + '/' + str(r.get('rank_carriers_root')):>10}")
        report["targeted"] = res

    if "dict" in stages:
        print("\n=== dictionaries ===")
        anchors = ("conclusion",) if args.quick else ("root", "conclusion")
        settings = [dict(per_decl=3, score="retention", max_per_right=None),
                    dict(per_decl=3, score="min_normalised", max_per_right=None),
                    dict(per_decl=3, score="retention", max_per_right=1)]
        if args.quick:
            settings = settings[:1]
        dicts = []
        right_pool: dict[str, list[str]] = {}
        for left, right, why in pairs:
            for anchor in anchors:
                for s in settings:
                    tag = (f"{left} ~ {right} [{anchor}, {s['score']}, "
                           f"cap={s['max_per_right']}]")
                    d = run_dictionary(c, left, right, anchor=anchor, theorems_only=True,
                                       top=args.top, **s)
                    d["why"] = why
                    if "error" in d:
                        print(f"  {tag}: {d['error']}")
                        dicts.append(d)
                        continue
                    print(f"  {tag}: {d['n_rows']} rows "
                          f"({d['distinct_lefts']}L/{d['distinct_rights']}R), "
                          f"missing {d['n_missing_left']}L/{d['n_missing_right']}R, "
                          f"{d['seconds']}s")
                    for r in d["rows"][:6]:
                        print(f"      {r['retention']:.3f} {r['left'][:44]:44s} ~ "
                              f"{r['right'][:44]}")
                    pool = right_pool.setdefault(
                        right,
                        [n for n in names
                         if (dd := c.get(n)) and theory_of(dd.module) == right
                         and dd.kind == "theorem" and dd.stmt])
                    d["null"] = shuffle_control(c, d, anchor=anchor, pool=pool)
                    d["own_coherence"] = own_coherence(d)
                    for arm in ("matched", "broad"):
                        a = d["null"].get(arm, {})
                        print(f"      null[{arm}]: genuine {a.get('genuine_mean')} vs "
                              f"shuffled {a.get('shuffled_mean')} sep {a.get('separation')}"
                              f" — {a.get('verdict')}")
                    print(f"      collision {d['own_coherence']['collision_rate']:.3f} over "
                          f"{d['own_coherence']['rows_dumped']} dumped rows")
                    dicts.append(d)
            # NC5 — the engine's own coherence report, so a 96%-collision dictionary is
            # not read as N findings.
            try:
                co = c.dictionary_coherence(left, right, per_decl=3, theorems_only=True)
                pol = c.dictionary_policies(left, right, per_decl=3, theorems_only=True)
                sc = c.dictionary_shuffle_control(left, right, per_decl=3, theorems_only=True)
                info = {
                    "rows": co.rows, "lefts": co.distinct_lefts, "rights": co.distinct_rights,
                    "contested": co.contested, "collision_rate": round(co.collision_rate, 4),
                    "worst": co.worst[:6],
                    "policies": [(p.policy, p.rows, p.lefts, round(p.collision_rate, 4),
                                  round(p.mean_score, 4), p.unmatched) for p in pol],
                    "engine_null": {"pairs": sc.pairs,
                                    "genuine": round(sc.genuine_mean, 4),
                                    "shuffled": round(sc.shuffled_mean, 4),
                                    "separation": round(sc.separation, 4),
                                    "shuffled_admitted": sc.shuffled_admitted},
                }
                print(f"    coherence {left}~{right}: {co.rows} rows, collision "
                      f"{co.collision_rate:.3f}, engine null genuine {sc.genuine_mean:.3f} "
                      f"vs shuffled {sc.shuffled_mean:.3f}")
                report.setdefault("coherence", {})[f"{left}~{right}"] = info
            except Exception as e:
                print(f"    coherence {left}~{right}: {type(e).__name__}: {e}")
        report["dictionaries"] = dicts

    if "dilution" in stages:
        print("\n=== dilution: the same two theories inside corpora of growing size ===")
        left, right = (pairs[0][0], pairs[0][1]) if args.pair else ("ClassicalInfo", "Entropy")
        # The targets are §2a's pairs that actually connect these two theories, so the same
        # stage measures the mechanics pair against mechanics expectations rather than
        # against zero by construction.
        TARGETS = [(l, r) for l, r, _t in TARGETED
                   if (dl := c.get(l)) and (dr := c.get(r))
                   and theory_of(dl.module) == left and theory_of(dr.module) == right]
        print(f"  {len(TARGETS)} pre-registered target rows connect {left} and {right}")
        res = dilution(pathlib.Path(src), left, right, TARGETS, args.dilute_sizes,
                       args.out.parent)
        print(f"  {left} ~ {right}, conclusion anchor; 4 pre-registered target rows")
        print(f"  {'N':>9} {'max_len':>8} {'rows':>6} {'targets':>8}   top row")
        for r in res:
            if "error" in r:
                print(f"  {r['declarations']:>9,} {r['error']}")
                continue
            t = r["top"][0] if r["top"] else ("-", "-", "-")
            print(f"  {r['declarations']:>9,} {r['max_len']:>8} {r['rows']:>6} "
                  f"{r['n_found']}/{len(TARGETS)}      {t[0]} {str(t[1])[:26]} ~ {str(t[2])[:26]}")
        report["dilution"] = {"left": left, "right": right, "targets": TARGETS, "arms": res}

    if "exhaustive" in stages:
        print("\n=== exhaustive: the same floors with the prefilter removed ===")
        by_theory: dict[str, list[str]] = {}
        for n in names:
            d = c.get(n)
            if d and d.kind == "theorem" and d.stmt:
                by_theory.setdefault(theory_of(d.module), []).append(n)
        ex = {}
        for left, right, why in pairs:
            L, R = by_theory.get(left, []), by_theory.get(right, [])
            if not L or not R:
                print(f"  {left} ~ {right}: {len(L)}L/{len(R)}R — skipped")
                continue
            for anchor in args.exh_anchors.split(","):
                res = exhaustive_dictionary(c, L, R, anchor=anchor, min_retention=0.30,
                                            min_common=6, max_pairs=args.max_pairs)
                if "skipped" in res:
                    print(f"  {left} ~ {right} [{anchor}]: {res['skipped']}")
                    ex[f"{left}~{right}/{anchor}"] = res
                    continue
                # What the shipped dictionary found at the same anchor, for the recall
                # comparison. Engine rows are per_decl-capped, so the honest comparison is
                # on left declarations covered and on (left,right) membership.
                eng = next((d for d in report.get("dictionaries", [])
                            if d.get("left") == left and d.get("right") == right
                            and d.get("anchor") == anchor and d.get("score") == "retention"
                            and d.get("max_per_right") is None), None)
                # A comparison against a dictionary this process never ran would be zero by
                # construction and would read as a finding. Say so instead.
                if eng is None:
                    res["engine_comparison"] = "not run in this process"
                    cmp_msg = "no engine dictionary in this run"
                else:
                    eng_pairs = {(r["left"], r["right"]) for r in eng.get("rows", [])}
                    ex_pairs = {(r[1], r[2]) for r in res["rows"]}
                    res["engine_rows_dumped"] = len(eng_pairs)
                    res["engine_rows_total"] = eng.get("n_rows")
                    res["engine_found_of_exhaustive"] = len(eng_pairs & ex_pairs)
                    res["exhaustive_only_lefts"] = len(
                        {r[1] for r in res["rows"]} - {p[0] for p in eng_pairs})
                    cmp_msg = (f"the shipped dictionary's {len(eng_pairs)} dumped rows "
                               f"cover {res['engine_found_of_exhaustive']} of them")
                print(f"  {left} ~ {right} [{anchor}]: {res['n_rows']} rows over "
                      f"{res['pairs_evaluated']:,} pairs ({res['distinct_lefts']}L/"
                      f"{res['distinct_rights']}R) in {res['seconds']}s; {cmp_msg}")
                for r in res["rows"][:8]:
                    print(f"      {r[0]:.3f} c{r[3]:3d} {r[1][:44]:44s} ~ {r[2][:44]}")
                res["rows"] = res["rows"][:2000]
                ex[f"{left}~{right}/{anchor}"] = res
        report["exhaustive"] = ex

    if "similar" in stages:
        print("\n=== cross-theory `similar`, floors at the bottom ===")
        # Queries are chosen by *module*, not by name-semantics: every theorem of the two
        # mechanics theories that carries a statement, capped for cost. Which questions get
        # asked is a module-level choice; what counts as an answer is never a name.
        probes = {}
        for left, right, why in pairs:
            qs = [n for n in names
                  if (d := c.get(n)) and theory_of(d.module) == left and d.stmt
                  and d.kind == "theorem"]
            random.Random(7).shuffle(qs)
            qs = qs[:args.probe_n]
            if not qs:
                continue
            for level in ("carriers", "shape"):
                for anchor in ("root", "conclusion"):
                    res = cross_theory_similar(c, qs, {right}, level=level, anchor=anchor,
                                               top=200, min_retention=0.02, min_common=2)
                    tot = sum(r.get("n_cross", 0) for r in res)
                    withhit = sum(1 for r in res if r.get("n_cross"))
                    print(f"  {left}->{right} [{level},{anchor}]: {withhit}/{len(qs)} "
                          f"queries have a cross-theory neighbour, {tot} hits")
                    probes[f"{left}->{right}/{level}/{anchor}"] = {
                        "queries": len(qs), "with_hit": withhit, "hits": tot,
                        "detail": [r for r in res if r.get("n_cross")][:20]}
        report["similar_probes"] = probes

    if "classes" in stages:
        print("\n=== equivalence classes spanning theories ===")
        ths = {l for l, _r, _e in pairs} | {r for _l, r, _e in pairs}
        for level in ("presentation", "instances", "carriers"):
            sp = spanning_classes(c, level, ths)
            print(f"  {level}: {len(sp)} spanning classes")
            for s in sp[:6]:
                print(f"    size {s['size']:3d} {s['theories']}: {s['members'][:3]}")
            report.setdefault("spanning_classes", {})[level] = sp

    if "motifs" in stages:
        print("\n=== motifs spanning theories ===")
        ths = {l for l, _r, _e in pairs} | {r for _l, r, _e in pairs}
        for source in ("shape", "subterm"):
            sp = spanning_motifs(c, ths, source=source, min_family=2, min_size=4, top=400)
            print(f"  {source}: {len(sp)} motifs span two named theories")
            for s in sp[:8]:
                print(f"    size {s['size']:3d} idf {s['idf']:.2f} {s['spanned']}: "
                      f"{s['pattern'][:70]}")
            report.setdefault("motifs", {})[source] = sp

    if "transport" in stages:
        print("\n=== transport along the top rows ===")
        # A row is a claim that two theories correspond; transport is the only operation
        # that *uses* it. Both outcomes are signal — an image already in the slice verifies
        # the row, an open one is a directed physics target — and §24 records that this
        # operation had never produced anything, so it is worth asking on a corpus where
        # the rows mean something.
        out = []
        for d in report.get("dictionaries", []):
            if d.get("error") or not d.get("rows"):
                continue
            for r in d["rows"][:5]:
                if not r["transportable"]:
                    continue
                subjects = [x["left"] for x in d["rows"] if x["left"] != r["left"]][:6]
                for s in subjects:
                    try:
                        t = c.transport(r["left"], r["right"], s)
                    except Exception as e:
                        out.append({"row": [r["left"], r["right"]], "subject": s,
                                    "outcome": f"{type(e).__name__}"})
                        continue
                    out.append({"row": [r["left"], r["right"]], "subject": s,
                                "exists": t.exists, "name": t.name,
                                "image": t.image[:300]})
        ok = sum(1 for o in out if o.get("exists"))
        openq = sum(1 for o in out if o.get("exists") is False)
        refused = len(out) - ok - openq
        print(f"  {len(out)} attempts: {ok} existing images, {openq} open targets, "
              f"{refused} refused")
        for o in out[:10]:
            print(f"    {o.get('outcome') or ('exists ' + str(o.get('name')) if o.get('exists') else 'OPEN')}"
                  f"  [{o['row'][0][:34]} ~ {o['row'][1][:34]}] <- {o['subject'][:40]}")
        report["transport"] = out

    if "frontier" in stages:
        print("\n=== frontier ===")
        for exclude in ((), ("Mathematics", "ForMathlib", "Meta", "Units")):
            try:
                fr = c.frontier(min_theory_size=60, top=20, theorems_only=True,
                                exclude=list(exclude))
            except Exception as e:
                print(f"  exclude={exclude}: {type(e).__name__}: {e}")
                continue
            print(f"  exclude={list(exclude)}: {len(fr)} pairs")
            for p in fr[:12]:
                print(f"    {p.left[:22]:22s} ~ {p.right[:22]:22s} sim {p.similarity:.3f} "
                      f"excess {p.excess:+.3f} cites {p.cross_citations:4d} "
                      f"sizes {p.left_size}/{p.right_size}")
            report.setdefault("frontier", {})[str(bool(exclude))] = [
                (p.left, p.right, round(p.similarity, 4), round(p.excess, 4),
                 p.cross_citations, p.left_size, p.right_size) for p in fr]

    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
