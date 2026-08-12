#!/usr/bin/env python3
"""Validation experiments for the Atlas indexes against real Mathlib (B4/B5/B6).

The point is not "the code runs". It is "the answers are the ones a mathematician would
give", so every experiment below names *what a good answer looks like* before it runs, and
fails if the answer is merely plausible.

The slice is produced by:

    cd lean && lake exe atlas_extract Mathlib.Algebra.Order.Field.Basic > /tmp/mathlib-algebra.jsonl

which takes ~80 s and is worth caching. Pass `--slice PATH` to point elsewhere, and read
CLAUDE.md §4 first: `Mathlib.Logic.Basic` sounds like Mathlib and is 37% Lean metaprogramming.

The experiments run against one `atlas.Corpus` handle. They used to shell out to the
`atlas` CLI, which re-parses the whole 131k-row slice per question — eight questions, eight
re-parses, ~48 s of pure re-reading. From a clean clone:

    uv sync
    uv run scripts/atlas-mathlib-experiment.py

Most of the wall clock is three index builds, each charged to the first query that needs it:
the statement arena, B5's equivalence index and B4/B6's skeleton index cost 4.3 s, 6.3 s and
13.7 s on the algebra slice. The CLI pays those, plus the slice re-parse, *per invocation*.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

try:
    import atlas as fa
except ImportError:
    sys.exit(
        "atlas is not importable — this script runs under the repository's venv:\n"
        "  uv sync && uv run scripts/atlas-mathlib-experiment.py\n"
        "(see crates/atlas-py/README.md)"
    )


class Experiment:
    """One named claim about the Atlas, with the evidence that would settle it."""

    def __init__(self, name: str, claim: str) -> None:
        self.name = name
        self.claim = claim
        self.notes: list[str] = []
        self.passed: bool | None = None

    def check(self, condition: bool, detail: str) -> None:
        self.notes.append(("  ok   " if condition else "  FAIL ") + detail)
        self.passed = condition if self.passed is None else (self.passed and condition)

    def report(self) -> bool:
        status = "PASS" if self.passed else "FAIL"
        print(f"[{status}] {self.name}\n       claim: {self.claim}")
        for n in self.notes:
            print(n)
        return bool(self.passed)


# ---------------------------------------------------------------------------
# B2 — the dependency graph. Already built; these are its regression experiments.
# ---------------------------------------------------------------------------

def experiment_walls(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B2 walls",
        "the most-cited declarations in Mathlib are its foundations, not an artefact",
    )
    top = [name for name, _ in corpus.walls(lens="proof", top=10)]
    # `Eq` is under essentially every proof in mathematics; if it is not at the top,
    # the proof lens is not reading proof terms.
    e.check("Eq" in top[:3], f"`Eq` in the top 3 (got {top[:3]})")
    # A wall list dominated by one namespace would mean the slice is not Mathlib-wide.
    e.check(len(set(n.split(".")[0] for n in top)) >= 3, f"top 10 spans ≥3 roots: {top}")
    return e


def experiment_proof_edges(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B1 proof edges",
        "theorems carry proof dependencies — the bug B2 found stays fixed",
    )
    # `uses_proof` off the row, not `foundations`: the bug was that the extractor emitted
    # *no* proof edges for theorems, which is a question about direct edges. The transitive
    # closure would answer it too, at 2.4 ms per theorem against 66,700 theorems.
    theorems = [d for d in map(corpus.get, corpus.names()) if d.kind == "theorem"]
    with_edges = [d for d in theorems if d.uses_proof]
    e.check(len(theorems) > 1000, f"{len(theorems)} theorems in the slice")
    ratio = len(with_edges) / max(len(theorems), 1)
    e.check(ratio > 0.9, f"{ratio:.1%} of theorems have proof edges")
    return e


# Lean's compiler axioms. They stand behind `unsafe` implementations, are erased at
# runtime, and never participate in a proof of a theorem — so they are a legitimate
# whitelist entry rather than a finding. Naming them here rather than widening the tool's
# default keeps the default strict.
COMPILER_AXIOMS = [
    "lcProof", "lcAny", "lcCast", "lcErased", "lcUnreachable", "lcVoid",
    "Quot.lcInv", "isScalarObj", "Lean.trustCompiler",
    "Lean.ofReduceBool", "Lean.ofReduceNat",
]

# Lean's own three, which everything classical uses. The binding's default, spelled out
# here because the honesty experiment passes an explicit whitelist and an explicit list is
# used exactly as given.
CLASSICAL_AXIOMS = ["propext", "Classical.choice", "Quot.sound"]


def experiment_honesty(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "C5 honesty",
        "nothing in the slice rests on `sorryAx`, and the axioms that *are* used are the "
        "ones a reader would expect",
    )
    # The sharp claim, and the one that matters: not a single declaration's proof reaches
    # `sorryAx`. This is the transitive scan doing the job anti-cheat needs.
    resting = corpus.impact("sorryAx", lens="proof")
    e.check(not resting, f"{len(resting)} declarations rest on `sorryAx`")

    # And with the compiler axioms whitelisted, the scan is clean. Without them it is not,
    # which is the tool working: it found the four `ByteArray` unsafe internals whose
    # implementations stand on `lcProof`, out of 131k declarations.
    findings = corpus.honesty(whitelist=CLASSICAL_AXIOMS + COMPILER_AXIOMS)
    e.check(not findings, f"clean under the compiler-axiom whitelist: {findings[:4]}")

    # The negative control: with a *narrow* whitelist the scan must find something, or it
    # is not looking.
    narrow = corpus.honesty(whitelist=["propext"])
    e.check(bool(narrow), f"a narrow whitelist produces findings ({len(narrow)}) — the scan is live")
    return e


# ---------------------------------------------------------------------------
# B4 — the skeleton index. Does squinting find analogies a keyword search cannot?
# ---------------------------------------------------------------------------

def experiment_similar_crosses_theories(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B4 similar",
        "transitivity of `≤` reaches transitivity of `∣` — the cross-theory analogy the "
        "index exists for, and the one no name- or keyword-search finds",
    )
    top5 = [n.name for n in corpus.similar("le_trans", top=5)]
    top8 = [n.name for n in corpus.similar("le_trans", top=8)]
    # Divisibility is a different theory with a different carrier and no shared concrete
    # subterm: `le_trans` reaches it only through source C, the `Shape`-subterm postings.
    #
    # The claim is about reaching *divisibility transitivity*, which Mathlib spells twice —
    # `dvd_trans` and `Dvd.dvd.trans` are one theorem under two names, as this file's own
    # transport experiment already says. So the top-5 assertion is on the theorem, and the
    # two spellings are asserted inside a wider window.
    #
    # The window widened from 5 to 8 deliberately, and the reason is a fix rather than a
    # regression: repairing `retention`'s denominator promoted `LE.le.trans` and
    # `ge_trans'` — restatements of `le_trans` itself, retention exactly 1.00 — to ranks 1
    # and 2, where they belong and where they now consume two slots. Ranks 3-6 are then an
    # exact four-way tie on score, `common` and `vars` alike, so which of them lands at 5
    # and which at 6 is alphabetical and carries no information.
    dvd = {"dvd_trans", "Dvd.dvd.trans"}
    e.check(
        bool(dvd & set(top5)),
        f"divisibility transitivity in the top 5 (got {top5})",
    )
    e.check(dvd <= set(top8), f"both spellings within the top 8 (got {top8})")

    # The failure mode, asserted rather than assumed. If the answer were `Nat.le_trans`,
    # `Int.le_trans`, `UInt8.le_trans` … the index would be ranking along the *carrier*
    # axis — the same theorem re-instantiated — which means the erasure levels are not
    # firing and the whole normalization knob is decoration.
    carrier_axis = [n for n in top5 if n.rsplit(".", 1)[-1] in ("le_trans", "trans")]
    e.check(
        len(carrier_axis) < len(top5),
        f"the top 5 is not the carrier axis alone: {carrier_axis} of {top5}",
    )

    # The differential: brute force is a different algorithm — every declaration, no
    # prefilter — so a prefilter that quietly dropped the head of the ranking shows up here
    # and nowhere else. The index may *reorder* (it ranks by score, brute by retention);
    # it must not lose.
    brute = [n for n, _ in corpus.similar_brute("le_trans", top=10)]
    wide = {n.name for n in corpus.similar("le_trans", top=50)}
    kept = [n for n in brute if n in wide]
    e.check(
        len(kept) == len(brute),
        f"the index's top 50 keeps all {len(brute)} of brute force's top 10 "
        f"(kept {len(kept)}; lost {[n for n in brute if n not in wide]})",
    )
    return e


def experiment_similar_level_selects_the_family(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B4 level knob",
        "the erasure level *selects* which analogy is returned: at `presentation` the "
        "neighbours of `Nat.add_comm` keep the carrier and vary the operator, at `carriers` "
        "they keep the operator and vary the carrier — and the two families do not mix",
    )
    pres = [n.name for n in corpus.similar("Nat.add_comm", top=8, level="presentation")]
    carr = [n.name for n in corpus.similar("Nat.add_comm", top=8, level="carriers")]
    e.check("Nat.mul_comm" in pres and "Nat.or_comm" in pres, f"presentation: {pres}")
    # The original witness pin — `Int.add_comm` in the top 8 — went stale when the score
    # vectors landed: the cross-carrier family now out-crowds its own canonical member.
    # Measured 2026-08-06: the top 8 are all `*.add_comm` at common=24, retention=1.0,
    # and `Int.add_comm` sits at rank 12 on the same factors, separated only by the
    # newer within-family signal. The claim under test is that the level selects the
    # cross-carrier same-operator family, so assert the family; the old witness stays as
    # a wider regression guard rather than being deleted.
    fam8 = sum(1 for n in carr
               if n.rsplit(".", 1)[-1] == "add_comm" and not n.startswith("Nat."))
    e.check(fam8 >= 6, f"carriers top-8 is the cross-carrier add_comm family "
                       f"({fam8}/8): {carr}")
    carr15 = [n.name for n in corpus.similar("Nat.add_comm", top=15, level="carriers")]
    e.check("Int.add_comm" in carr15,
            f"Int.add_comm within the top 15 (rank "
            f"{carr15.index('Int.add_comm') if 'Int.add_comm' in carr15 else '>14'})")

    # "Selected by the level, not interleaved" is the sharp claim, and it is the one that
    # distinguishes a working knob from a ranking that happens to contain both families:
    # every member of the level's own family must rank above every member of the other.
    def separated(names: list[str], in_family) -> tuple[bool, str]:
        mine = [i for i, n in enumerate(names) if in_family(n)]
        theirs = [i for i, n in enumerate(names) if not in_family(n)]
        if not mine:
            return False, "the level's own family is absent"
        if not theirs:
            return True, "the whole list is the level's own family"
        return max(mine) < min(theirs), f"last own at {max(mine)}, first other at {min(theirs)}"

    ok, why = separated(pres, lambda n: n.startswith("Nat."))
    e.check(ok, f"presentation ranks same-carrier above cross-carrier ({why}): {pres}")
    ok, why = separated(carr, lambda n: n.rsplit(".", 1)[-1] == "add_comm")
    e.check(ok, f"carriers ranks same-operator above different-operator ({why}): {carr}")
    return e


# ---------------------------------------------------------------------------
# B5 — the equivalence graph. When are two theorems one theorem?
# ---------------------------------------------------------------------------

def experiment_equivalence(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B5 equivalent",
        "two spellings of antisymmetry are recognised as one claim, and asking the question "
        "of a non-proposition is refused rather than answered",
    )
    # `le_antisymm : a ≤ b → b ≤ a → a = b` and `eq_of_le_of_ge` are the same theorem under
    # two names. At `exact` — no erasure at all — so this is statement identity, not
    # squinting.
    members = corpus.equivalent("le_antisymm", level="exact")
    e.check("eq_of_le_of_ge" in members, f"`eq_of_le_of_ge` in the class (got {members[:5]})")

    # The Prop guard. Without it the query answers "everything whose type is `Type`" and
    # calls that an equivalence class, which is a type index wearing a relation's name.
    try:
        answer = corpus.equivalent("Nat.succ")
    except fa.NotAProposition as err:
        e.check("Nat.succ" in str(err), f"`Nat.succ` refused, naming itself: {err!s:.60}")
    else:
        e.check(False, f"`Nat.succ` was answered with {len(answer)} 'equivalents'")

    # And the class list must be reformulation families, not the corpus's type structure.
    # Measured without the restriction, the largest class is 1,859 declarations whose type
    # is literally `Type`; a class of that order here means the restriction is off.
    classes = corpus.classes(top=5)
    e.check(bool(classes) and classes[0][0] > 1, f"largest class: {classes[0] if classes else None}")
    e.check(
        classes[0][0] < 100,
        f"the largest class is a reformulation family ({classes[0][0]} members: "
        f"{classes[0][1][:3]}), not the `Type` bucket",
    )
    return e


# ---------------------------------------------------------------------------
# B6 — dictionaries, transport, the frontier
# ---------------------------------------------------------------------------

def experiment_dictionary(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B6 dictionary",
        "order theory and algebra have a *partial* dictionary: matched rows where the "
        "analogy has been made, and a larger unmatched list where it has not",
    )
    d = corpus.dictionary("Mathlib.Order", "Mathlib.Algebra")
    e.check(len(d.rows) > 50, f"{len(d.rows)} rows between {d.left_theory} and {d.right_theory}")
    # The missing entries are the point of the exercise (atlas.md §2's Frobenius row). A
    # *total* dictionary would mean every order concept already has an algebraic partner,
    # which would say the analogy is exhausted — and would be evidence the matcher is
    # matching on nothing.
    e.check(
        bool(d.missing_left) and bool(d.missing_right),
        f"unmatched: {len(d.missing_left)} in {d.left_theory}, "
        f"{len(d.missing_right)} in {d.right_theory}",
    )
    e.check(
        len(d.missing_left) > len(d.rows),
        f"the unmatched side dominates ({len(d.missing_left)} vs {len(d.rows)}) — the "
        "dictionary is partial, which is what makes it a research object",
    )
    # Not "no row is below the floor" — `similar` discards those before a row is ever
    # built, so that check cannot fail and CLAUDE.md §3 asks a negative control to be able
    # to find something. What is worth asserting is that the floor *binds*: the weakest
    # surviving row sits near it. A minimum far above the floor would mean the threshold is
    # inert and the row set is being decided by something else entirely.
    lowest = min(r.retention for r in d.rows)
    e.check(
        lowest < 0.50,
        f"the retention floor binds — weakest row at {lowest:.3f}, near the 0.30 floor "
        "rather than far above it",
    )
    return e


def experiment_transport(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B6 transport",
        "transporting `le_trans` along the row `le_trans ~ dvd_trans` lands on a theorem "
        "that already exists — the outcome that *verifies* a dictionary row",
    )
    t = corpus.transport("le_trans", "dvd_trans", "le_trans")
    e.check(t.exists, f"the image exists: {t!r}")
    # `dvd_trans` and `Dvd.dvd.trans` have the same statement, so which name comes back is
    # a tie-break; either is the right answer and neither is `None`.
    e.check(
        t.name in ("dvd_trans", "Dvd.dvd.trans"),
        f"the image is named as divisibility transitivity: {t.name}",
    )
    # `.exists` and `.name` are one fact, and a caller branching on the first must be able
    # to read the second without a None check that never fires.
    e.check((t.name is not None) == t.exists, f"name={t.name!r} agrees with exists={t.exists}")
    # Cross-layer: the image is rendered from the skeleton index's arena, the comparison
    # from the plain statement arena. Equal strings mean the two agree about what the
    # transported statement *is*, which no single-arena check can establish.
    e.check(
        t.image == corpus.skeleton(t.name, level="carriers"),
        "the image renders as the existing declaration's own carriers-level statement",
    )
    # And the answer must not depend on which level was asked for. `exists` is TermId
    # equality inside the engine, and the index seals its arena after precomputing exact /
    # presentation / shape — so for a while those three reported an *open target* for a
    # lemma the slice already had, while instances and carriers were right by accident.
    # Checking the default level alone is what let that stand; the sweep is the gate.
    open_at = [
        lv
        for lv in ("exact", "presentation", "instances", "carriers", "shape")
        if not corpus.transport("le_trans", "dvd_trans", "le_trans", level=lv).exists
    ]
    e.check(
        not open_at,
        f"every level finds it: open at {open_at} would be the engine inventing research",
    )
    return e


# Infrastructure namespaces. Excluded not to flatter the result but to ask the question
# meant: CLAUDE.md §5's third repetition of "restrict to claims, or you are measuring Lean
# rather than mathematics". The negative control below asserts they *would* have dominated.
INFRASTRUCTURE = [
    "Init", "Std", "Lean", "Aesop", "Batteries", "Qq", "ProofWidgets", "Plausible",
    "Cli", "ImportGraph", "LeanSearchClient", "Mathlib.Tactic", "Mathlib.Lean",
    "Mathlib.Util", "Mathlib.Control", "Mathlib.Testing", "Mathlib.Deprecated",
]


def experiment_frontier(corpus: fa.Corpus) -> Experiment:
    e = Experiment(
        "B6 frontier",
        "the frontier ranking is dominated by metaprogramming siblings until infrastructure "
        "is excluded, and the exclusion is what turns it from a refactoring list into a "
        "mathematical one",
    )
    # The documented failure mode, asserted as a *positive* control: it must still happen,
    # or the exclusion knob below is being credited with a problem that no longer exists.
    unfiltered = corpus.frontier(top=5)
    infra_hits = [f for f in unfiltered if f.left in INFRASTRUCTURE or f.right in INFRASTRUCTURE]
    e.check(
        len(infra_hits) >= 3,
        f"unfiltered, the top 5 is mostly infrastructure: "
        f"{[(f.left, f.right) for f in unfiltered]}",
    )
    e.check(
        any(f.cross_citations == 0 for f in unfiltered),
        "and the pairs it ranks first do not cite each other at all — similarity without "
        "traffic, which is exactly what the score rewards",
    )

    filtered = corpus.frontier(top=8, exclude=INFRASTRUCTURE)
    e.check(
        all(f.left not in INFRASTRUCTURE and f.right not in INFRASTRUCTURE for f in filtered),
        f"excluded, nothing infrastructural survives: {[(f.left, f.right) for f in filtered]}",
    )
    # What is left is the honest reading of *this* slice, and it is a negative result worth
    # recording rather than hiding: every mathematical theory pair big enough to rank
    # already cites the other, so this slice has no unexplored interface. A pair here with
    # zero traffic would be the interesting case; there is none.
    quiet = [f for f in filtered if f.cross_citations == 0]
    e.check(
        bool(filtered),
        f"{len(filtered)} mathematical pairs clear the size floor; "
        f"{len(quiet)} of them have no cross-citations at all",
    )
    e.check(
        all(f.similarity <= 1.0 for f in filtered),
        "similarity is a fraction of the smaller theory's shape buckets",
    )
    return e


EXPERIMENTS = [
    experiment_proof_edges,
    experiment_walls,
    experiment_honesty,
    experiment_similar_crosses_theories,
    experiment_similar_level_selects_the_family,
    experiment_equivalence,
    experiment_dictionary,
    experiment_transport,
    experiment_frontier,
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", default="/tmp/mathlib-algebra.jsonl")
    args = ap.parse_args()

    if not pathlib.Path(args.slice).exists():
        sys.exit(
            f"no slice at {args.slice}\n"
            "produce one with:  cd lean && lake exe atlas_extract "
            "Mathlib.Algebra.Order.Field.Basic > /tmp/mathlib-algebra.jsonl"
        )
    started = time.perf_counter()
    corpus = fa.Corpus.load(args.slice)
    print(f"slice: {args.slice} — {len(corpus)} declarations, parsed once in "
          f"{time.perf_counter() - started:.1f}s\n")

    ok = True
    for make in EXPERIMENTS:
        started = time.perf_counter()
        experiment = make(corpus)
        ok = experiment.report() and ok
        print(f"       ({time.perf_counter() - started:.1f}s)\n")
    print("atlas experiments:", "green" if ok else "RED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
