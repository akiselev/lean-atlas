#!/usr/bin/env python3
"""Attribute the reformulation layer's recall gap, cause by cause.

An independent parse of the encodings finds 516 `Iff`-headed theorems in physlib; the
engine reports 261 edges. This script says *why* each missing one is missing, using the
same I3 encoding and a different implementation, so a shared bug cannot hide the answer.

`logical.rs` keys each side of an `Iff` by `(head constant, arity)` and then branches:

```rust
(Some(lk), Some(rk)) if lk != rk => { push edge }
(Some(_), Some(_)) => {}            // same head+arity: dropped, and counted NOWHERE
_ => stats.flex_head_sides += 1,
```

So there are three outcomes and only two are reported. The silent one is the interesting
one: `X.ext_iff : a = b ↔ a.f = b.f` has `Eq` on both sides, so every structure's
extensionality lemma lands there.

Whether a same-head `Iff` *should* produce an edge is a design question — at head level it
is a self-loop and carries nothing. But it must be counted, or "we did not look" and
"there is nothing there" stay indistinguishable, which is the failure `flex_head_sides`
exists to prevent.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from atlas_home import Reader, telescope  # noqa: E402


def conclusion_span(enc: str) -> tuple[bytes, int]:
    """Bytes of the encoding and the offset where the conclusion begins."""
    r = Reader(enc)
    while r.i < len(r.b) and r.b[r.i] == 0x70:  # 'p' — a forall binder
        r.i += 3
        r.skip()  # domain
        r.i += 1  # ','
    return r.b, r.i


def spine(buf: bytes, at: int):
    """`(head_name_or_None, [arg_offsets])` for the application spine at `at`."""
    args: list[int] = []
    cur = at
    while cur < len(buf) and buf[cur] == 0x61:  # 'a('
        f = cur + 2
        sub = Reader.__new__(Reader)
        sub.b, sub.i = buf, f
        sub.skip()
        arg = sub.i + 1
        args.append(arg)
        cur = f
    # `cur` is now the innermost function position.
    sub = Reader.__new__(Reader)
    sub.b, sub.i = buf, cur
    if buf[cur] == 0x63:  # 'c('
        sub.i += 2
        name = sub._name()
        return name, list(reversed(args))
    return None, list(reversed(args))


def head_at(buf: bytes, at: int) -> tuple[str | None, int]:
    h, args = spine(buf, at)
    return h, len(args)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-iff-gap.json"))
    args = ap.parse_args()

    rows = []
    with args.slice.open() as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))

    buckets: collections.Counter = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)
    same_head_pairs: collections.Counter = collections.Counter()

    for r in rows:
        if r.get("kind") != "theorem" or not r.get("stmt"):
            continue
        try:
            buf, at = conclusion_span(r["stmt"])
            head, argoffs = spine(buf, at)
        except Exception:
            buckets["parse error"] += 1
            continue
        if head != "Iff" or len(argoffs) != 2:
            continue
        buckets["iff-headed total"] += 1
        try:
            lh, la = head_at(buf, argoffs[0])
            rh, ra = head_at(buf, argoffs[1])
        except Exception:
            buckets["side parse error"] += 1
            continue
        if lh is None or rh is None:
            buckets["flex head (side is not a constant)"] += 1
            if len(examples["flex"]) < 8:
                examples["flex"].append(r["name"])
        elif (lh, la) == (rh, ra):
            buckets["same head+arity (dropped silently)"] += 1
            same_head_pairs[f"{lh}/{la}"] += 1
            if len(examples["same"]) < 8:
                examples["same"].append(r["name"])
        else:
            buckets["edge (should be extracted)"] += 1
            if len(examples["edge"]) < 5:
                examples["edge"].append(f"{r['name']}: {lh}/{la} ~ {rh}/{ra}")

    total = buckets["iff-headed total"]
    print(f"{total:,} Iff-headed theorems\n")
    for k, v in buckets.most_common():
        if k == "iff-headed total":
            continue
        print(f"  {k:42s} {v:6,}  ({100*v/max(total,1):5.1f}%)")

    print("\n  most common same-head pairs (the silent bucket):")
    for k, v in same_head_pairs.most_common(8):
        print(f"    {k:28s} {v:5,}")

    for tag, label in (("edge", "extracted"), ("same", "same-head"), ("flex", "flex-head")):
        if examples[tag]:
            print(f"\n  {label} examples:")
            for e in examples[tag][:6]:
                print(f"    {e[:74]}")

    args.out.write_text(json.dumps(
        {"buckets": dict(buckets), "same_head_pairs": dict(same_head_pairs.most_common(40)),
         "examples": {k: v for k, v in examples.items()}}, indent=1))
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
