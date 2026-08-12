#!/usr/bin/env python3
"""Does the binding answer the same questions as the CLI, and is it worth having?

Two kinds of claim here, and both are needed. The **differential** ones check the binding
against `target/release/atlas` — a separately written caller of the same engine, so a
mis-wired lens, a swapped argument or a dropped sort shows up as a diff rather than as a
plausible-looking answer. The **property** ones check the things no oracle can: that the
lens separates claim from argument, that erasure levels form a chain, that a bad argument
raises instead of guessing.

The last claim is the reason the crate exists, and it is a measurement: one load plus
twenty queries against the handle, versus twenty CLI invocations answering the same twenty
questions.

    cargo build -p atlas --bins --release          # the oracle
    uv run crates/atlas-py/tests/smoke.py [--slice /tmp/mathlib-algebra.jsonl]

Most of the wall clock is the CLI side, and the B4/B5/B6 differentials are the expensive
part of it: each of those CLI invocations rebuilds an index the handle built once.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import subprocess
import sys
import time

import atlas as fa

ROOT = pathlib.Path(__file__).resolve().parents[3]
ATLAS = ROOT / "target" / "release" / "atlas"

# Fixed, so a failure is reproducible and a slow run is comparable with the last one.
PROBE_NAMES = [
    "Nat.add_comm", "Nat.mul_comm", "Nat.add_assoc", "Nat.le_trans", "Nat.succ_le_succ",
    "Int.add_comm", "Int.mul_comm", "Int.add_assoc", "Int.neg_neg", "Int.sub_self",
    "List.length_cons", "List.append_assoc", "Option.some_get", "Bool.and_comm",
    "Eq.symm", "Eq.trans", "congrArg", "congrFun", "id_eq", "trans",
]


def cli(*args: str, slice_path: str) -> tuple[str, int]:
    """Run the CLI the way the old harness did: one process, one question, one re-parse."""
    if not ATLAS.exists():
        sys.exit(f"no {ATLAS} — run `cargo build -p atlas --bins --release` first")
    p = subprocess.run(
        [str(ATLAS), args[0], slice_path, *args[1:]],
        capture_output=True, text=True, cwd=ROOT, timeout=1800,
    )
    return p.stdout, p.returncode


def present(corpus: fa.Corpus, names: list[str]) -> list[str]:
    return [n for n in names if corpus.get(n) is not None]


# ---------------------------------------------------------------------------
# Differential: the handle and the CLI must not disagree
# ---------------------------------------------------------------------------

def the_handle_and_the_cli_agree_on_foundations(corpus: fa.Corpus, slice_path: str) -> None:
    for name in present(corpus, PROBE_NAMES)[:5]:
        for lens in ("statement", "proof", "both"):
            out, _ = cli("foundations", name, "--lens", lens, slice_path=slice_path)
            assert corpus.foundations(name, lens=lens) == out.split(), (name, lens)


def the_handle_and_the_cli_agree_on_why(corpus: fa.Corpus, slice_path: str) -> None:
    chain = corpus.why("Nat.add_comm", "Nat.rec", lens="proof")
    out, code = cli("why", "Nat.add_comm", "Nat.rec", "--lens", "proof", slice_path=slice_path)
    assert code == 0 and chain == out.split(), (chain, out)
    # And where there is no chain, both must say so — the CLI by failing, the API with
    # `None`. A binding that invented a path here would be worse than one that crashed.
    assert corpus.why("Nat.add_comm", "Nat.rec", lens="statement") is None
    _, code = cli("why", "Nat.add_comm", "Nat.rec", "--lens", "statement", slice_path=slice_path)
    assert code != 0


def the_handle_and_the_cli_agree_on_walls(corpus: fa.Corpus, slice_path: str) -> None:
    out, _ = cli("walls", "--lens", "proof", slice_path=slice_path)
    expected = [(ln.split()[1], int(ln.split()[0])) for ln in out.splitlines() if ln.strip()]
    assert corpus.walls(lens="proof", top=20) == expected, corpus.walls(lens="proof", top=20)[:3]


def the_handle_and_the_cli_agree_on_honesty(corpus: fa.Corpus, slice_path: str) -> None:
    out, code = cli("honesty", "propext", slice_path=slice_path)
    expected = sorted(
        (ln.split("  rests on  ")[0], ln.split("  rests on  ")[1])
        for ln in out.splitlines() if "  rests on  " in ln
    )
    findings = corpus.honesty(whitelist=["propext"])
    assert findings == expected, (len(findings), len(expected))
    # The negative control the CLI carries in its exit code: a narrow whitelist must find
    # something, or the scan is not looking.
    assert code != 0 and findings


def the_handle_and_the_cli_agree_on_skeletons(corpus: fa.Corpus, slice_path: str) -> None:
    out, code = cli("skeleton", "Nat.add_comm", "--level", "carriers", slice_path=slice_path)
    # Failing rather than skipping when the CLI has no `skeleton`: a differential that can
    # go quiet on a stale binary is not a differential.
    assert code == 0, f"the CLI answered no skeleton — rebuild it: {out!r}"
    assert corpus.skeleton("Nat.add_comm", level="carriers") == out.strip()


def the_handle_and_the_cli_agree_on_similar(corpus: fa.Corpus, slice_path: str) -> None:
    # The whole ranking, in order: `similar` reads five knobs off `IndexConfig`, and a
    # binding that defaulted one of them differently from the CLI would still return
    # plausible neighbours. Order included, because the score is the part that would drift.
    out, code = cli("similar", "le_trans", "--top", "5", slice_path=slice_path)
    assert code == 0, f"the CLI answered no `similar`: {out!r}"
    # Skip `#` provenance lines and take the name explicitly, rather than trusting a
    # column index: the row carries a score, and the day the score gains a field a
    # positional parse compares the wrong column instead of failing.
    expected = [
        ln.split()[1]
        for ln in out.splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert [n.name for n in corpus.similar("le_trans", top=5)] == expected, out


def the_handle_and_the_cli_agree_on_equivalence(corpus: fa.Corpus, slice_path: str) -> None:
    # `equivalent` has a default level (`instances`) that is *not* the module-wide default
    # (`carriers`), which is exactly the kind of thing a second implementation gets wrong.
    out, code = cli("equivalent", "le_antisymm", slice_path=slice_path)
    assert code == 0, f"the CLI answered no `equivalent`: {out!r}"
    expected = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
    assert corpus.equivalent("le_antisymm") == expected, (corpus.equivalent("le_antisymm"), expected)


def the_handle_and_the_cli_agree_on_dictionaries(corpus: fa.Corpus, slice_path: str) -> None:
    out, code = cli("dictionary", "Mathlib.Order", "Mathlib.Algebra", slice_path=slice_path)
    assert code == 0, f"the CLI answered no `dictionary`: {out!r}"
    # The summary line carries the three numbers the whole query is about: how many rows,
    # and how much of each side went unmatched.
    summary = [ln for ln in out.splitlines() if " rows; unmatched: " in ln][0].split()
    d = corpus.dictionary("Mathlib.Order", "Mathlib.Algebra")
    assert [len(d.rows), len(d.missing_left), len(d.missing_right)] == [
        int(summary[0]), int(summary[3]), int(summary[6])
    ], (len(d.rows), len(d.missing_left), len(d.missing_right), summary)


def the_handle_and_the_cli_agree_on_transport(corpus: fa.Corpus, slice_path: str) -> None:
    out, code = cli("transport", "le_trans", "dvd_trans", "le_trans", slice_path=slice_path)
    assert code == 0, f"the CLI answered no `transport`: {out!r}"
    t = corpus.transport("le_trans", "dvd_trans", "le_trans")
    assert t.exists == out.startswith("exists:"), (out, repr(t))
    assert t.name is not None and f"`{t.name}`" in out, (out, t.name)




# ---------------------------------------------------------------------------
# Properties: the things no oracle can check
# ---------------------------------------------------------------------------

def foundations_and_impact_are_converse(corpus: fa.Corpus, slice_path: str) -> None:
    # y is a foundation of x exactly when x is in y's impact. A one-sided bug in the
    # binding — a lens dropped on one path only — shows up here and nowhere else.
    for name in present(corpus, PROBE_NAMES)[:3]:
        for lens in ("statement", "proof"):
            for base in corpus.foundations(name, lens=lens)[:20]:
                assert name in corpus.impact(base, lens=lens), (name, base, lens)


def the_lens_separates_claim_from_argument(corpus: fa.Corpus, slice_path: str) -> None:
    both = set(corpus.foundations("Nat.add_comm", lens="both"))
    stmt = set(corpus.foundations("Nat.add_comm", lens="statement"))
    proof = set(corpus.foundations("Nat.add_comm", lens="proof"))
    assert stmt <= both and proof <= both
    # Not equal, or the two edge sets are not being kept apart at all.
    assert stmt != proof
    assert "Nat.rec" in proof and "Nat.rec" not in stmt


def erasure_levels_form_a_chain(corpus: fa.Corpus, slice_path: str) -> None:
    # P7 in the large, through the API: coarser buckets are unions of finer ones, so the
    # number of distinct skeletons over a fixed sample can only fall as the level coarsens.
    names = present(corpus, PROBE_NAMES)
    counts = []
    for level in ("exact", "presentation", "instances", "carriers", "shape"):
        skels = set()
        for n in names:
            try:
                skels.add(corpus.skeleton(n, level=level))
            except fa.NoStatement:
                pass
        counts.append(len(skels))
    assert counts == sorted(counts, reverse=True), counts


def cross_carrier_statements_collapse_at_carriers(corpus: fa.Corpus, slice_path: str) -> None:
    # The claim the normalization knob exists for, asked through the binding: `Nat.add_comm`
    # and `Int.add_comm` are different statements that become the same skeleton once the
    # carrier is erased.
    assert corpus.skeleton("Nat.add_comm", level="exact") != corpus.skeleton("Int.add_comm", level="exact")
    assert corpus.skeleton("Nat.add_comm", level="carriers") == corpus.skeleton("Int.add_comm", level="carriers")


def a_statement_generalizes_with_itself_perfectly(corpus: fa.Corpus, slice_path: str) -> None:
    g = corpus.generalize("Nat.add_comm", "Nat.add_comm")
    assert g.vars == 0 and g.scoped_vars == 0 and g.retention == 1.0, repr(g)


def generalization_is_commutative_and_partial(corpus: fa.Corpus, slice_path: str) -> None:
    left = corpus.generalize("Nat.add_comm", "Int.add_comm")
    right = corpus.generalize("Int.add_comm", "Nat.add_comm")
    assert left.skeleton == right.skeleton
    # Two statements that are not the same one must retain less than everything, or the
    # anti-unifier is reporting a match it did not find.
    assert 0.0 < left.retention < 1.0 and left.vars > 0, repr(left)


def a_class_member_reports_the_rest_of_its_class(corpus: fa.Corpus, slice_path: str) -> None:
    # `classes` buckets the whole slice; `equivalent` answers about one declaration. Two
    # code paths over one relation, so a member of a reported class must see its siblings —
    # and this is what catches the two disagreeing about which rows count as propositions.
    # A superset rather than equality: `classes(theorems_only=True)` drops the Prop-valued
    # *definitions* that `equivalent` still reports.
    size, members = corpus.classes(top=1)[0]
    assert size == len(members) > 1, (size, members)
    assert set(corpus.equivalent(members[0])) >= set(members[1:]), members


def a_transported_image_names_a_declaration_exactly_when_it_exists(
    corpus: fa.Corpus, slice_path: str
) -> None:
    # `.exists` and `.name` are one fact in two fields, which is only safe if they cannot
    # disagree. `le_trans ~ dvd_trans` applied to itself lands on an existing theorem;
    # applied to `Nat.add_comm` the row does not match at all, which is a refusal rather
    # than an open target — the distinction B6 exists to keep.
    hit = corpus.transport("le_trans", "dvd_trans", "le_trans")
    assert hit.exists and hit.name is not None and hit.image
    # Rendered from the skeleton index's arena, compared against the plain statement
    # arena's rendering: the two layers must agree about what the image *is*.
    assert hit.image == corpus.skeleton(hit.name, level="carriers")
    try:
        corpus.transport("le_trans", "dvd_trans", "Nat.add_comm")
    except fa.NoMatch:
        pass
    else:
        raise AssertionError("a row was applied to a statement it does not match")


def similar_keeps_the_head_of_the_brute_force_ranking(corpus: fa.Corpus, slice_path: str) -> None:
    # The index exists to avoid 131,062 anti-unifications per query, and its own docs say
    # the honest gate is a recall floor rather than an equality. Brute force is a different
    # algorithm over the same corpus — ranked by retention where the index ranks by score,
    # so it may reorder, and must not lose.
    brute = [n for n, _ in corpus.similar_brute("le_trans", top=10)]
    wide = {n.name for n in corpus.similar("le_trans", top=50)}
    assert set(brute) <= wide, [n for n in brute if n not in wide]


# ---------------------------------------------------------------------------
# Errors: a wrong argument must be readable, not silent
# ---------------------------------------------------------------------------

def a_bad_lens_names_the_lenses_that_exist(corpus: fa.Corpus, slice_path: str) -> None:
    for call in (
        lambda: corpus.foundations("Nat.add_comm", lens="statements"),
        lambda: corpus.why("Nat.add_comm", "Eq", lens="Proof"),
        lambda: corpus.walls(lens=""),
    ):
        try:
            call()
        except ValueError as e:
            assert "statement" in str(e) and "proof" in str(e), str(e)
        else:
            raise AssertionError("a bad lens was accepted")


def a_bad_level_names_the_levels_that_exist(corpus: fa.Corpus, slice_path: str) -> None:
    try:
        corpus.skeleton("Nat.add_comm", level="carrier")
    except ValueError as e:
        assert "carriers" in str(e) and "shape" in str(e), str(e)
    else:
        raise AssertionError("a bad level was accepted")


def an_unknown_declaration_says_so_rather_than_returning_nothing(corpus: fa.Corpus, slice_path: str) -> None:
    for call in (
        lambda: corpus.foundations("Nat.add_comm_typo"),
        lambda: corpus.why("Nat.add_comm_typo", "Eq"),
        lambda: corpus.skeleton("Nat.add_comm_typo"),
        lambda: corpus.generalize("Nat.add_comm", "Nat.add_comm_typo"),
    ):
        try:
            call()
        except fa.UnknownDeclaration as e:
            assert "Nat.add_comm_typo" in str(e), str(e)
        else:
            raise AssertionError("an unknown declaration was answered")
    # `get` is the one query that answers `None`, because "is it here" is its question.
    assert corpus.get("Nat.add_comm_typo") is None
    # And `impact` deliberately accepts names outside the slice.
    assert corpus.impact("Nat.add_comm_typo") == []


def an_unusable_statement_says_which_declaration_and_why(corpus: fa.Corpus, slice_path: str) -> None:
    # On a fixture, not on the Mathlib slice: measured, every one of that slice's 131,062
    # rows encodes, so the two ways a statement can be unusable have no witness there.
    fixture = pathlib.Path("/tmp/atlas-unusable.jsonl")
    fixture.write_text(
        '{"name":"Encoded","kind":"theorem","module":"M","stmt":"atlas-stmt-v1;b0"}\n'
        '{"name":"Unencodable","kind":"recursor","module":"M","stmt_error":"recursor"}\n'
        '{"name":"Garbled","kind":"theorem","module":"M","stmt":"atlas-stmt-v1;zzz"}\n'
    )
    try:
        c = fa.Corpus.load(fixture)
        for name, expected in (("Unencodable", "recursor"), ("Garbled", "byte")):
            try:
                c.skeleton(name)
            except fa.NoStatement as e:
                # The name and the reason, both: "it failed" is not an actionable answer.
                assert name in str(e) and expected in str(e), str(e)
            else:
                raise AssertionError(f"{name} produced a skeleton")
        # The row that *does* encode still works, so the failures above are about those
        # rows rather than about the fixture being rejected wholesale.
        assert c.skeleton("Encoded", level="shape") == "b0"
    finally:
        fixture.unlink()


def the_stubs_describe_the_module_that_shipped(corpus: fa.Corpus, slice_path: str) -> None:
    # Agents lean on stubs harder than humans do (python-api.md §2), so a stub that has
    # drifted from the extension is worse than no stub: it is a confident wrong answer.
    stub = ast.parse((ROOT / "crates" / "atlas-py" / "atlas.pyi").read_text())
    for node in stub.body:
        if not isinstance(node, ast.ClassDef):
            continue
        live = getattr(fa, node.name, None)
        assert live is not None, f"{node.name} is stubbed but not exported"
        if issubclass(live, BaseException):
            continue
        for member in node.body:
            if isinstance(member, ast.FunctionDef):
                assert hasattr(live, member.name), f"{node.name}.{member.name} is stubbed only"
    stubbed = {n.name for n in stub.body if isinstance(n, ast.ClassDef)}
    exported = {n for n in dir(fa) if not n.startswith("_") and isinstance(getattr(fa, n), type)}
    assert exported <= stubbed, f"exported but unstubbed: {exported - stubbed}"


def a_missing_or_broken_slice_raises_before_any_query(corpus: fa.Corpus, slice_path: str) -> None:
    try:
        fa.Corpus.load("/tmp/definitely-not-a-slice-4f2a.jsonl")
    except FileNotFoundError as e:
        assert "definitely-not-a-slice-4f2a" in str(e), str(e)
    else:
        raise AssertionError("a missing slice loaded")

    broken = pathlib.Path("/tmp/atlas-broken-slice.jsonl")
    broken.write_text('{"name":"A","uses_proof":[]}\nnot json\n')
    try:
        fa.Corpus.load(broken)
    except fa.SliceError as e:
        assert "line 2" in str(e), str(e)
    else:
        raise AssertionError("a malformed slice loaded")
    finally:
        broken.unlink()


# ---------------------------------------------------------------------------
# The measurement the crate exists for
# ---------------------------------------------------------------------------

def one_load_answers_twenty_questions_for_less_than_one_cli_call(
    corpus: fa.Corpus, slice_path: str
) -> None:
    questions = [(n, "proof") for n in present(corpus, PROBE_NAMES)]
    assert len(questions) >= 20, f"only {len(questions)} probe names are in this slice"
    questions = questions[:20]

    t0 = time.perf_counter()
    reload_s = time.perf_counter()
    handle = fa.Corpus.load(slice_path)
    reload_s = time.perf_counter() - reload_s
    api_answers = [handle.foundations(n, lens=lens) for n, lens in questions]
    api_s = time.perf_counter() - t0
    query_s = api_s - reload_s

    t0 = time.perf_counter()
    cli_answers = [
        cli("foundations", n, "--lens", lens, slice_path=slice_path)[0].split()
        for n, lens in questions
    ]
    cli_s = time.perf_counter() - t0

    assert api_answers == cli_answers, "the two paths answered different questions"
    print(
        f"       load {reload_s:.2f}s + {len(questions)} queries {query_s * 1e3:.1f}ms "
        f"= {api_s:.2f}s   vs CLI {cli_s:.2f}s   ({cli_s / api_s:.1f}× faster end to end, "
        f"{cli_s / max(query_s, 1e-9):.0f}× per query)"
    )
    assert api_s < cli_s / 2, f"{api_s:.2f}s is not decisively under {cli_s:.2f}s"


CLAIMS = [
    the_handle_and_the_cli_agree_on_foundations,
    the_handle_and_the_cli_agree_on_why,
    the_handle_and_the_cli_agree_on_walls,
    the_handle_and_the_cli_agree_on_honesty,
    the_handle_and_the_cli_agree_on_skeletons,
    the_handle_and_the_cli_agree_on_similar,
    the_handle_and_the_cli_agree_on_equivalence,
    the_handle_and_the_cli_agree_on_dictionaries,
    the_handle_and_the_cli_agree_on_transport,
    foundations_and_impact_are_converse,
    the_lens_separates_claim_from_argument,
    erasure_levels_form_a_chain,
    cross_carrier_statements_collapse_at_carriers,
    a_statement_generalizes_with_itself_perfectly,
    generalization_is_commutative_and_partial,
    a_class_member_reports_the_rest_of_its_class,
    a_transported_image_names_a_declaration_exactly_when_it_exists,
    similar_keeps_the_head_of_the_brute_force_ranking,
    a_bad_lens_names_the_lenses_that_exist,
    a_bad_level_names_the_levels_that_exist,
    an_unknown_declaration_says_so_rather_than_returning_nothing,
    an_unusable_statement_says_which_declaration_and_why,
    the_stubs_describe_the_module_that_shipped,
    a_missing_or_broken_slice_raises_before_any_query,
    one_load_answers_twenty_questions_for_less_than_one_cli_call,
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", default="/tmp/mathlib-algebra.jsonl")
    args = ap.parse_args()

    started = time.perf_counter()
    corpus = fa.Corpus.load(args.slice)
    print(f"{corpus!r}  loaded in {time.perf_counter() - started:.2f}s\n")

    ok = True
    for claim in CLAIMS:
        started = time.perf_counter()
        try:
            claim(corpus, args.slice)
            print(f"[ ok ] {claim.__name__}  ({time.perf_counter() - started:.2f}s)")
        except Exception as e:
            ok = False
            print(f"[FAIL] {claim.__name__}: {type(e).__name__}: {e}")
    print("\natlas smoke:", "green" if ok else "RED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
