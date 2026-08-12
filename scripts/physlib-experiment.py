#!/usr/bin/env python3
"""Point the Atlas at physlib — a small, curated, ~100% mathematics corpus.

## Why this is the right target and Mathlib was not

Mathlib is the null hypothesis. Everything in it is known, refereed and used daily, so
mining it for missed mathematics searches the one place where the prior is lowest — and
every ranking there is swamped by `Init`/`Std`/`Lean` infrastructure, because two-thirds of
a Mathlib slice is compiler metaprogramming. Measured on the algebra slice: `walls` returned
`congrArg` and `Eq.refl`, cross-theory analogy returned auto-generated `.mk.inj` lemmas, and
the frontier returned the largest theory pairs rather than the most similar ones.

physlib inverts every one of those properties. It is ~600 modules of physics, the subfields
are of comparable size (Relativity 98, QFT 72, Particles 71, QuantumMechanics 50,
Electromagnetism 35, ClassicalMechanics 27, FluidDynamics 17), and nothing in it is
metaprogramming. If the Atlas's rankings are still dominated by infrastructure here, the
problem is the engine rather than the slice — which is a result either way.

## The subfield rewrite, and why it is required rather than cosmetic

`dict::theory_of` takes the module prefix at depth 1 outside Mathlib, so every physlib
module files under `Physlib` and the whole library is one theory. A frontier between
theories would then be a frontier from a theory to itself, and `similar`'s cross-theory
boost would score an Electromagnetism/FluidDynamics match as same-theory and penalise it.
Rewriting `Physlib.Relativity.Foo` to `Relativity.Foo` makes each subfield its own theory.

## What a good answer looks like, stated before the run

1. **The known Iff edges must be found.** physlib's fluid dynamics states four `_iff_`
   theorems, including `navier_stokes_iff_convective_navier_stokes`. The relationship layer
   reads proved `Iff` edges; if it does not recover these, it does not work on this corpus
   and nothing downstream of it means anything. This is the load-bearing check.
2. **The frontier becomes well-posed.** With ~14 subfields of comparable size, "theory" is a
   meaningful granularity for the first time. A good answer names pairs with genuine shared
   structure and low citation — Electromagnetism/FluidDynamics (both are conservation laws
   over vector fields) would be the physicist's expected hit.
3. **Infrastructure must not dominate.** If `walls` still returns `congrArg`, the claims
   restriction is an engine problem, not a corpus problem.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import atlas_home  # noqa: E402

PHYS = re.compile(r"^(?:Physlib|QuantumInfo)\.(.+)$")


def prepare(src: pathlib.Path, dst: pathlib.Path) -> dict:
    """Rewrite module names so each physics subfield is its own theory."""
    counts: collections.Counter = collections.Counter()
    n = 0
    with src.open() as fh, dst.open("w") as out:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            m = PHYS.match(row.get("module", ""))
            if m:
                row["module"] = m.group(1)
            counts[row["module"].split(".")[0]] += 1
            n += 1
            out.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    return {"rows": n, "subfields": counts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, default=pathlib.Path("/tmp/atlas-physlib.jsonl"))
    ap.add_argument("--prepared", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-physlib-theories.jsonl"))
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("/tmp/atlas-physlib-report.json"))
    args = ap.parse_args()

    meta = prepare(args.slice, args.prepared)
    print(f"{meta['rows']:,} rows; {len(meta['subfields'])} subfields")
    for k, v in meta["subfields"].most_common(20):
        print(f"  {k:26s} {v:6,}")

    c = fa.Corpus.load(str(args.prepared))
    print(f"\nloaded {len(c):,} declarations")
    report: dict = {"census": dict(meta["subfields"])}

    # -- 0. coverage -------------------------------------------------------------------
    names = c.names()
    kinds = collections.Counter()
    no_stmt = 0
    for n in names:
        d = c.get(n)
        kinds[d.kind] += 1
        if d.stmt is None:
            no_stmt += 1
    print(f"\nkinds: {dict(kinds.most_common(8))}")
    print(f"without a statement: {no_stmt:,} ({100*no_stmt/max(len(names),1):.1f}%)")
    report["kinds"] = dict(kinds)

    # -- 1. THE load-bearing check: are the known Iff edges found? ----------------------
    print("\n" + "=" * 70)
    print("1. Known Iff theorems — the check everything downstream depends on")
    print("=" * 70)
    st = c.logical_stats()
    print(f"  theorems scanned {st.theorems_scanned:,}   edges {st.edges:,} "
          f"(Iff {st.iff_edges:,}, impl {st.implication_edges:,})")
    print(f"  skipped: flex head {st.flex_head_sides:,}, non-prop {st.non_prop_sides:,}")
    # The answer key is computed from the **statement**, never from the name.
    #
    # An earlier version searched for declarations whose name contained `_iff_`. That is a
    # naming convention, not a semantic fact: a theorem can state an `↔` and not be named
    # for it, or be named for it and state something else. Scoring the engine against that
    # measures Lean's naming habits.
    #
    # A theorem states an equivalence exactly when its statement's conclusion head is
    # `Iff` — a property of the encoded tree. `atlas_home.telescope` walks the I3 encoding in
    # Python; `logical.rs` does it in Rust with a different algorithm. Two independent
    # implementations over the same data is a differential oracle, so a shared bug cannot
    # make both agree.
    truth_iff, truth_impl = [], []
    for n in names:
        d = c.get(n)
        if d.kind != "theorem" or not d.stmt:
            continue
        try:
            binders, concl = atlas_home.telescope(d.stmt)
        except Exception:
            continue
        if concl == "Iff":
            truth_iff.append(n)
        elif any(bi == "d" for bi, _h, _a, _dep in binders) and concl not in (None, "Eq"):
            # A non-dependent `Pi` into a proposition is an implication; kept separately
            # because `logical.rs` treats the two cases differently.
            truth_impl.append(n)

    print(f"\n  ground truth from the encodings (not from names):")
    print(f"    conclusion head is `Iff` : {len(truth_iff):,}")
    print(f"    implication-shaped        : {len(truth_impl):,}")

    found = 0
    for n in sorted(truth_iff)[:40]:
        try:
            rels = c.relations(n)
        except Exception:
            rels = []
        if rels:
            found += 1
        print(f"    [{'ok  ' if rels else 'MISS'}] {n[:56]:56s} {len(rels)} edge(s)"
              + (f"  {rels[0].kind}/{rels[0].warrant}" if rels else ""))
    shown = min(len(truth_iff), 40)
    print(f"\n  recovered {found}/{shown} of the Iff-headed theorems sampled")
    # Cross-check the totals: the engine's own `iff_edges` count against the independent one.
    print(f"  engine reports {st.iff_edges:,} Iff edges; the independent parse finds "
          f"{len(truth_iff):,} Iff-headed theorems")
    report["iff"] = {"truth_iff": len(truth_iff), "truth_impl": len(truth_impl),
                     "sampled": shown, "recovered": found,
                     "engine_iff_edges": st.iff_edges,
                     "stats": {"edges": st.edges, "flex": st.flex_head_sides}}

    # -- 2. frontier, now that `theory` means something --------------------------------
    print("\n" + "=" * 70)
    print("2. Frontier between physics subfields")
    print("=" * 70)
    # `Mathematics` and `ForMathlib` are physlib's own infrastructure — 1,576 theorems of
    # general-purpose lemmas upstreamed toward Mathlib. Left in, they play the role
    # `Init`/`Std` played on the Mathlib slice and lead the ranking for the same reason.
    # The unrestricted pass is kept as the control that shows they would have.
    INFRA = ["Mathematics", "ForMathlib", "Meta", "Units"]
    for size, exclude in ((20, ()), (20, INFRA), (60, INFRA)):
        try:
            fr = c.frontier(min_theory_size=size, top=15, theorems_only=False,
                            exclude=list(exclude))
        except Exception as e:
            print(f"  min_theory_size={size}: {type(e).__name__}: {e}")
            continue
        tag = "with infrastructure (control)" if not exclude else "physics only"
        print(f"\n  min_theory_size={size}, {tag}: {len(fr)} pairs")
        for p in fr:
            print(f"    {p.left[:24]:24s} ~ {p.right[:24]:24s} sim {p.similarity:.3f} "
                  f"cites {p.cross_citations:4d}  sizes {p.left_size}/{p.right_size}")
        report.setdefault("frontier", {})[f"{size}/{bool(exclude)}"] = [
            (p.left, p.right, p.similarity, p.cross_citations) for p in fr]

    # -- 3. is infrastructure still dominating? ----------------------------------------
    print("\n" + "=" * 70)
    print("3. Walls — infrastructure check")
    print("=" * 70)
    for lens in ("statement", "proof"):
        w = c.walls(lens=lens, top=10)
        print(f"  --lens {lens}: " + ", ".join(f"{n}({k})" for n, k in w[:8]))
        report.setdefault("walls", {})[lens] = w

    # -- 4. cross-subfield analogy ------------------------------------------------------
    print("\n" + "=" * 70)
    print("4. Cross-subfield analogy")
    print("=" * 70)
    thms = [n for n in names if c.get(n).kind == "theorem" and c.get(n).stmt]
    print(f"  {len(thms):,} theorems with statements")
    pairs: collections.Counter = collections.Counter()
    examples: list = []
    for n in thms[:1500]:
        try:
            nbs = c.similar(n, top=8, level="carriers", min_retention=0.25, min_common=4)
        except Exception:
            continue
        mine = (c.get(n).module or "").split(".")[0]
        for b in nbs:
            theirs = (b.module or "").split(".")[0]
            if theirs != mine:
                pairs[tuple(sorted((mine, theirs)))] += 1
                if len(examples) < 20:
                    examples.append((n, b.name, round(b.score, 3)))
    print(f"\n  cross-subfield neighbour counts:")
    for (a, b), k in pairs.most_common(15):
        print(f"    {a:22s} ~ {b:22s} {k:5,}")
    print(f"\n  examples:")
    for a, b, s in examples[:15]:
        print(f"    {a[:44]:44s} ~ {b[:44]:44s} {s}")
    report["cross_pairs"] = {f"{a}~{b}": k for (a, b), k in pairs.most_common(40)}
    report["cross_examples"] = examples

    # -- 4b. dictionaries, transport, and the missing-entry report ---------------------
    #
    # This is the part that chases novelty rather than surveying. atlas.md: "the
    # missing-entry report: concepts on one side with no matched partner … the whole point
    # is finding the *next* such gap in territory no human has mapped."
    #
    # The pairs are chosen for physics reasons, written down before the run, so a hit is
    # a prediction confirmed rather than a pattern noticed afterwards:
    #
    #   Relativity ~ FluidDynamics    stress-energy tensor against Cauchy stress tensor —
    #                                 the same object in two subfields, and the deepest
    #                                 structural correspondence available in this corpus
    #   Electromagnetism ~ FluidDynamics  both are conservation laws over vector fields
    #                                 with potentials and flux/divergence structure
    #   QuantumMechanics ~ Optics     wave equations, same operator content
    #   StatisticalMechanics ~ QFT    partition function against path integral
    #   ClassicalMechanics ~ QuantumMechanics  the correspondence principle
    print("\n" + "=" * 70)
    print("4b. Dictionaries between subfields, and what has no partner")
    print("=" * 70)
    # Ordered by how much corpus is on both sides, measured from the source before the
    # run: Relativity 1263 theorems, QFT 1180, Particles 899, SpaceAndTime 740,
    # QuantumMechanics 598, Electromagnetism 390, ClassicalMechanics 246, StringTheory 180,
    # StatisticalMechanics 137 — and FluidDynamics only 12, so the fluids pairs are
    # lopsided and kept for the physics reason rather than the statistics.
    PAIRS = [
        ("Relativity", "QFT"),                      # both field-theoretic, 1263/1180
        ("Electromagnetism", "Relativity"),          # the historical unification
        ("ClassicalMechanics", "QuantumMechanics"),  # the correspondence principle
        ("StatisticalMechanics", "QFT"),             # partition function ~ path integral
        ("Electromagnetism", "QuantumMechanics"),
        ("Relativity", "FluidDynamics"),             # stress-energy ~ Cauchy stress
        ("Electromagnetism", "FluidDynamics"),       # conservation laws over vector fields
    ]
    present = set(meta["subfields"])
    for left, right in PAIRS:
        if left not in present or right not in present:
            print(f"\n  {left} ~ {right}: one side absent from this slice, skipped")
            continue
        print(f"\n  --- {left} ~ {right} ---")
        for theorems_only in (True, False):
            try:
                d = c.dictionary(left, right, per_decl=3, theorems_only=theorems_only)
            except Exception as e:
                print(f"    theorems_only={theorems_only}: {type(e).__name__}: {e}")
                continue
            rows = d.rows
            ml, mr = d.missing_left, d.missing_right
            print(f"    theorems_only={theorems_only}: {len(rows)} rows, "
                  f"{len(ml)} unmatched on the left, {len(mr)} on the right")
            for r in rows[:6]:
                print(f"      {r.left[:38]:38s} ~ {r.right[:38]:38s} "
                      f"ret {r.retention:.2f} {r.status}"
                      + ("  TRANSPORTABLE" if r.transportable else ""))
            if ml:
                print(f"      missing-entry sample (left with no partner): "
                      f"{', '.join(x.split('.')[-1][:22] for x in ml[:6])}")
            report.setdefault("dictionaries", {})[f"{left}~{right}/{theorems_only}"] = {
                "rows": [(r.left, r.right, r.retention, r.status, r.transportable)
                         for r in rows[:40]],
                "missing_left": ml[:60], "missing_right": mr[:60],
            }
            try:
                sc = c.dictionary_shuffle_control(left, right, per_decl=3,
                                                  theorems_only=theorems_only)
                print(f"      control: genuine {sc.genuine_mean:.3f} vs shuffled "
                      f"{sc.shuffled_mean:.3f}, separation {sc.separation:.3f}")
            except Exception as e:
                print(f"      control unavailable: {type(e).__name__}")

    # -- 4c. transport: turn a row into a conjecture -----------------------------------
    print("\n" + "=" * 70)
    print("4c. Transport — apply a row to a subject and see where it lands")
    print("=" * 70)
    transported = []
    for key, entry in list(report.get("dictionaries", {}).items())[:6]:
        for (rl, rr, _ret, _status, ok) in entry["rows"][:4]:
            if not ok:
                continue
            for subj in entry["missing_left"][:6]:
                try:
                    t = c.transport(rl, rr, subj)
                except Exception:
                    continue
                transported.append({
                    "row": f"{rl} ~ {rr}", "subject": subj,
                    "exists": t.exists, "name": t.name, "image": t.image[:160],
                })
                break
    print(f"  {len(transported)} transports attempted")
    for t in transported[:12]:
        tag = f"EXISTS as {t['name']}" if t["exists"] else "OPEN — no such declaration"
        print(f"    {t['subject'].split('.')[-1][:34]:34s} via {t['row'][:44]:44s} {tag}")
    report["transport"] = transported

    # -- 5. honesty ---------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("5. Honesty — what rests on a sorry")
    print("=" * 70)
    h = c.honesty(["propext", "Classical.choice", "Quot.sound"])
    print(f"  {len(h)} declarations rest on something outside Lean's three axioms")
    for who, why in h[:15]:
        print(f"    {who[:56]:56s} {why}")
    report["honesty"] = h[:200]

    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
