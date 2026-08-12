#!/usr/bin/env python3
"""Turn NO STATEMENT refusals into statable-level candidates — the §69 recovery ladder.

Round 1 refused 626 attempts: 490 because the rewritten statement was ill-typed at the
evidence-proposed target (the statement uses operations the target class does not carry),
134 because the target could not apply to the source's arguments, 2 resynthesis failures.
A refusal is evidence about the lane, and this is the repair: for each refusal, propose
every lattice level **strictly between** the failed target and the declared class. The
weakest statable level is exactly what the kuna replay-3 ladder found by hand —
`refusal -> five structural covers -> one well-formed statement -> one kernel proof`
(`kuna-math-loop.md` §13) — mechanized over the whole refusal ledger.

Stated before the run, per house rules: the expectation from replay 3's precedent is that
a meaningful fraction of refusals becomes statable at some intermediate, and that the
kernel then splits those between PROVED and not-proved like any other population. Zero
recovered statements would itself be a result — it would say the citation evidence
systematically proposes targets *below* the statable frontier, which is a representation
loss (statement-level operations are invisible to citation evidence), not a search loss.

Emits a plain triples JSON for `attempt-plan.py --triples`, ordered weakest-first within
a declaration so an interrupted run measures the most general levels first. Triples
already asked in a prior round are excluded there, not here.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from atlas_home import telescope  # noqa: E402

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")


def strict_lattice(c, t0: float) -> tuple[dict[str, set], dict[tuple[str, str], str]]:
    """Forgetful edges only, or the whole round points the wrong way.

    The first run of this script reused `novelty-rescreen.py`'s name-keyed lattice —
    any `X.toY` whose conclusion is a class — and 54 of 54 'recoveries' came back
    PROVED at classes like `PseudoMetricSpace` from `PseudoEMetricSpace`: conditional
    *constructions* (a `.to`-named def that takes extra hypotheses and builds the
    stronger structure) entered as parent edges, one fake edge contaminates every
    transitive chain through it, and a 'weakening' quietly became a strengthening —
    which the original theorem proves trivially and the novelty screen cannot flag,
    because the prior art is the declaration itself.

    A true parent projection forgets and asks nothing: its telescope is implicit
    carriers plus exactly one instance binder headed by the owner, no explicit binder
    at all. `CommRing.toRing` passes; anything taking a hypothesis fails. The cost is
    losing multi-parameter projections (`Algebra.toModule` carries its parameters'
    instances), which only shrinks the bracket — a lost edge cannot invert direction.

    Returns the edge map and, for the audit trail, which declaration owns each edge.
    """
    parents: dict[str, set[str]] = collections.defaultdict(set)
    edge_owner: dict[tuple[str, str], str] = {}
    kept = dropped = 0
    for name in c.names():
        if ".to" not in name:
            continue
        d = c.get(name)
        if d is None or not d.stmt:
            continue
        owner = name.rsplit(".to", 1)[0]
        try:
            binders, concl = telescope(d.stmt)
        except Exception:
            continue
        if not concl or concl == owner:
            continue
        inst = [h for bi, h, _a, _d in binders if bi == "t"]
        explicit = [1 for bi, _h, _a, _d in binders if bi == "d"]
        if explicit or inst != [owner]:
            dropped += 1
            continue
        parents[owner].add(concl)
        edge_owner[(owner, concl)] = name
        kept += 1
    print(f"  strict lattice: {kept:,} projection edges kept, {dropped:,} .to-named "
          f"declarations rejected (hypothesis-taking or multi-parameter)", flush=True)
    return parents, edge_owner


def ancestors(parents, cls, _cache={}):
    if cls in _cache:
        return _cache[cls]
    out, stack = set(), list(parents.get(cls, ()))
    while stack:
        p = stack.pop()
        if p in out or p == cls:
            continue
        out.add(p)
        stack.extend(parents.get(p, ()))
    _cache[cls] = out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", type=pathlib.Path,
                    default=pathlib.Path(
                        "/home/dev/research/lean-atlas/research/data/"
                        "refuter-round1-scored.json"))
    ap.add_argument("--slice", type=pathlib.Path,
                    default=pathlib.Path("/tmp/mathlib-closure.jsonl"))
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-recovery-triples.json"))
    ap.add_argument("--audit-proved", type=pathlib.Path, default=None,
                    help="a scored attempt file whose `proved` rows to classify by "
                         "direction under the strict lattice (the round-3 damage report)")
    args = ap.parse_args()
    t0 = time.time()

    refusals = json.loads(args.scored.read_text())["no_statement"]
    print(f"{len(refusals):,} refusals from {args.scored.name}", flush=True)

    c = fa.Corpus.load(str(args.slice))
    print(f"{len(c):,} declarations loaded ({time.time() - t0:.0f}s)", flush=True)
    parents, _edge_owner = strict_lattice(c, t0)

    # The control that would have caught the first run: the exemplar inversion must be
    # impossible under this lattice, or nothing below may be emitted.
    assert "PseudoMetricSpace" not in ancestors(parents, "PseudoEMetricSpace"), \
        "strict lattice still contains a strengthening edge — refusing to emit triples"

    if args.audit_proved:
        proved = json.loads(args.audit_proved.read_text())["proved"]
        verdicts = collections.Counter()
        for r in proved:
            up = ancestors(parents, r["source"])
            down = ancestors(parents, r["target"])
            if r["target"] in up:
                verdicts["genuinely weaker"] += 1
            elif r["source"] in down:
                verdicts["STRONGER (inverted)"] += 1
            else:
                verdicts["incomparable under strict lattice"] += 1
        print(f"\naudit of {len(proved)} proved rows: {dict(verdicts)}")

    triples, per_reason = [], collections.Counter()
    no_intermediate = 0
    for r in refusals:
        declared, target = r["source"], r["target"]
        # Strictly between: weaker than declared, strictly stronger than the failed
        # target. `ancestors` runs toward the weaker end of the lattice.
        between = [cls for cls in ancestors(parents, declared)
                   if cls != target and target in ancestors(parents, cls)]
        if not between:
            no_intermediate += 1
            continue
        # Weakest first: a PROVED at the most general statable level is the result the
        # round exists for; the stronger levels are the fallback, not the headline.
        between.sort(key=lambda cls: (-len(ancestors(parents, cls)), cls))
        # Bracket, do not enumerate. The first version emitted every intermediate and
        # produced 81,499 attempts over 1,019 shards — deep hierarchies contribute ~130
        # levels per refusal, and a census over them is weeks of kernel time spent mostly
        # in the middle of chains whose endpoints already answer the question. The two
        # weakest levels ask "how general could this possibly be"; the two strongest ask
        # "is any weakening statable at all". A hit at either end bounds the frontier,
        # and the interior can be binary-searched later for the few that deserve it.
        bracket = []
        for cls in between[:2] + between[-2:]:
            if cls not in bracket:
                bracket.append(cls)
        reason = "ill-typed" if "not type-correct" in r.get("reason", "") else "other"
        for cls in bracket:
            triples.append([r["decl"], declared, cls])
            per_reason[reason] += 1

    fams = collections.Counter((s, t) for _d, s, t in triples)
    print(f"\nrefusals with no lattice intermediate : {no_intermediate:,}")
    print(f"recovery triples emitted              : {len(triples):,} "
          f"({len(fams):,} families) — by original reason: {dict(per_reason)}")
    args.out.write_text(json.dumps({"triples": triples}, indent=1))
    print(f"-> {args.out}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
