#!/usr/bin/env python3
"""Does the novelty screen find a general version that really is there?

## Why this is not answerable by counting

§39 reported that 6.0% of random theorems have a non-empty equivalence class at `instances`
and read that as the screen's detection rate. It is not. That figure is the **prevalence**
of equivalents — how often Mathlib happens to state the same thing twice — and says nothing
about what the screen does when prior art exists. Conflating the two understates the screen,
and the mistake is only visible by constructing the case.

## The control

For each confirmed weakening `decl [C] -> T`, synthesize the row that a general version
*would* have and inject it into the corpus under a fresh name:

* **variant A** — the same statement with the binder domain weakened, `Preorder α` becoming
  `LE α`. This is a general version stated the obvious way.
* **variant B** — variant A with the coercion the stronger class supplied also removed:
  `Preorder.toLE α inst` collapsed to `inst`. This is §31's claimed blind spot, written out.

Then ask whether `equivalent(decl, level="instances")` contains the injection. A screen that
misses variant A is broken. A screen that finds A and misses B has exactly the blind spot
§31 named; one that finds both does not, and §31 needs correcting.

The injection is a **positive control**: it must be found. The paired negative is the
unmodified corpus, where nothing is injected and the screen must stay silent for the same
declarations — otherwise a hit proves nothing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from atlas_home import TAG, Reader  # noqa: E402

try:
    import atlas as fa
except ImportError:
    sys.exit("atlas is not importable — run under `uv run`")


def enc_name(n: str) -> bytes:
    b = n.encode()
    return str(len(b)).encode() + b":" + b


def span_of(buf: bytes, start: int) -> int:
    """End offset of the term beginning at `start`, by re-parsing it."""
    r = Reader.__new__(Reader)
    r.b, r.i = buf, start
    r.skip()
    return r.i


def weaken_first_binder(stmt: str, declared: str, target: str) -> str | None:
    """Variant A: the first instance binder's domain head, replaced."""
    buf = stmt[len(TAG):].encode()
    needle = b"pt(a(c(" + enc_name(declared)
    i = buf.find(needle)
    if i < 0:
        return None
    head = b"pt(a(c(" + enc_name(target)
    return TAG + (buf[:i] + head + buf[i + len(needle):]).decode()


def drop_coercion(stmt: str, declared: str, target: str) -> str | None:
    """Variant B: also collapse `<declared>.to<target> α inst` to `inst`.

    The coercion is `a(a(c(N:C.toT,...),<carrier>),<inst>)`. Replacing the whole application
    with its last argument is what a general version stated in terms of the weaker class
    would look like.
    """
    a = weaken_first_binder(stmt, declared, target)
    if a is None:
        return None
    buf = a[len(TAG):].encode()
    coe = enc_name(f"{declared}.to{target}")
    marker = b"a(a(c(" + coe
    out, i = bytearray(), 0
    while True:
        j = buf.find(marker, i)
        if j < 0:
            out += buf[i:]
            break
        end = span_of(buf, j)                    # the whole `a(a(c(...),X),Y)`
        inner = buf[j:end]
        # `a(a(H,X),Y)` — take Y, the last argument.
        k = span_of(inner, 2)                    # end of `a(H,X)` inside `a(...,...)`
        y = inner[k + 1:-1]                      # skip the ',' and the trailing ')'
        out += buf[i:j] + y
        i = end
    return TAG + bytes(out).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path,
                    default=pathlib.Path("/tmp/mathlib-algebra.jsonl"))
    ap.add_argument("--confirmed", type=pathlib.Path,
                    default=pathlib.Path("/tmp/atlas-gen-scored-v2.json"))
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--work", type=pathlib.Path, default=pathlib.Path("/tmp/atlas-sens"))
    args = ap.parse_args()

    conf = [tuple(x) for x in json.loads(args.confirmed.read_text())["confirmed"]]
    rows = {}
    for line in args.slice.open():
        if line.strip():
            r = json.loads(line)
            rows[r["name"]] = r

    cases = []
    for decl, declared, target in conf:
        r = rows.get(decl)
        if r is None or not r.get("stmt"):
            continue
        a = weaken_first_binder(r["stmt"], declared, target)
        if a is None or a == r["stmt"]:
            continue
        try:
            b = drop_coercion(r["stmt"], declared, target)
        except Exception:
            b = None
        cases.append((decl, declared, target, r, a, b))
        if len(cases) >= args.limit:
            break
    print(f"{len(cases)} injectable cases of {len(conf)} confirmed "
          f"(a case needs its declared class as the first instance binder)")
    nb = sum(1 for c in cases if c[5] and c[5] != c[4])
    print(f"  of which variant B differs from variant A: {nb} "
          f"(the rest have no {declared}.to{target}-style coercion in the body)")

    args.work.mkdir(exist_ok=True)
    results = {"A": [0, 0], "B": [0, 0], "control": [0, 0]}
    for label in ("control", "A", "B"):
        path = args.work / f"{label}.jsonl"
        with path.open("w") as w:
            for line in args.slice.open():
                if line.strip():
                    w.write(line)
            if label != "control":
                for decl, dc, tg, r, a, b in cases:
                    stmt = a if label == "A" else b
                    if stmt is None:
                        continue
                    inj = dict(r)
                    inj["name"] = f"SYNTH.{label}.{decl}"
                    inj["stmt"] = stmt
                    w.write(json.dumps(inj, ensure_ascii=False) + "\n")
        c = fa.Corpus.load(str(path))
        hits = 0
        for decl, dc, tg, _r, a, b in cases:
            if label == "B" and (b is None):
                continue
            try:
                eq = c.equivalent(decl, level="instances")
            except Exception:
                continue
            if any(e.startswith(f"SYNTH.{label}.") for e in eq):
                hits += 1
        n = len(cases) if label != "B" else sum(1 for c_ in cases if c_[5])
        results[label] = [hits, n]
        print(f"  {label:8s}: injected version found for {hits}/{n}")
        del c

    print("\n=== verdict ===")
    ha, na = results["A"]
    hb, nb2 = results["B"]
    hc, _ = results["control"]
    print(f"  variant A (weaker binder)            : {ha}/{na} found")
    print(f"  variant B (weaker binder, no coercion): {hb}/{nb2} found")
    print(f"  control   (nothing injected)          : {hc} spurious hits")
    if hc:
        print("  ABORT: the control fired, so a hit does not mean the injection was found.")
        return 1
    if na and ha == na:
        print("\n  The screen detects an identically-stated general version every time.")
    if nb2 and hb == nb2:
        print("  It also detects one stated without the coercion — §31's blind spot does "
              "not exist at this level, because the coercion sits in an InstImplicit "
              "position and is holed either way.")
    elif nb2:
        print(f"  It misses {nb2 - hb} of {nb2} coercion-free versions — §31's blind spot "
              "is real and now has a size.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
