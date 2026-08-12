"""Bound minimization over a slice too large to hold in memory.

`atlas_home.HomeIndex` keeps every row, which is fine for a 145 MB slice and impossible for the
whole-Mathlib one: 348,810 declarations at ~21 KB of statement encoding each is 4.7 GB on
disk and roughly three times that once parsed into Python objects.

Nothing in the evidence rule needs the statement string after its telescope has been read.
So this variant streams the file twice and keeps only:

* per declaration — its instance binders' classes and carriers, its conclusion head, its
  kind, its module, and the *names* it cites in its proof;
* corpus-wide — the class lattice, read off parent projections as before.

Two passes rather than one because the lattice and the `produces_class` set must be complete
before any declaration can be judged, and holding the rows to avoid a second pass is exactly
what does not fit.

The verdict rule is `atlas_home`'s, unchanged: same forgetful-instance traversal, same
single-carrier restriction, same projection stratification. Only the storage differs, and
`--check-against` re-runs the in-memory implementation on a small slice to prove they agree.
"""

from __future__ import annotations

import collections
import json

from atlas_home import telescope


class StreamHomeIndex:
    """The same evidence rule, over a file rather than a dict of rows."""

    def __init__(self, path: str, progress=None) -> None:
        self.path = path
        self.binders: dict[str, list] = {}
        self.concl: dict[str, str | None] = {}
        self.kind: dict[str, str] = {}
        self.module: dict[str, str] = {}
        self.parse_errors = 0

        # ---- pass one: telescopes only, statements discarded immediately -------------
        for i, row in enumerate(self._rows()):
            if progress and i % 50000 == 0:
                progress(i)
            stmt = row.get("stmt")
            if not stmt:
                continue
            try:
                b, c = telescope(stmt)
            except Exception:
                self.parse_errors += 1
                continue
            n = row["name"]
            # Only the instance binders survive; the rest of the telescope is not consulted
            # by the verdict rule and is the bulk of the memory.
            self.binders[n] = [(bi, h, a, d) for bi, h, a, d in b if bi == "t" and h]
            self.concl[n] = c
            self.kind[n] = row.get("kind", "")
            self.module[n] = row.get("module", "")

        self.classes = {h for b in self.binders.values() for _bi, h, _a, _d in b}
        self.produces_class = {n for n, c in self.concl.items() if c in self.classes}

        self.parents: dict[str, set[str]] = collections.defaultdict(set)
        for name in self.binders:
            if ".to" not in name:
                continue
            owner = name.rsplit(".to", 1)[0]
            c = self.concl.get(name)
            if owner in self.classes and c in self.classes and c != owner:
                self.parents[owner].add(c)
        self._anc: dict[str, set[str]] = {}

        self.forgetful = set()
        for name in self.produces_class:
            c = self.concl.get(name)
            for cls, _carrier in self.instance_binders(name):
                if c in self.ancestors(cls) or c == cls:
                    self.forgetful.add(name)
                    break

    def _rows(self):
        with open(self.path) as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    def ancestors(self, cls: str) -> set[str]:
        hit = self._anc.get(cls)
        if hit is not None:
            return hit
        out: set[str] = set()
        stack = list(self.parents.get(cls, ()))
        while stack:
            p = stack.pop()
            if p in out or p == cls:
                continue
            out.add(p)
            stack.extend(self.parents.get(p, ()))
        self._anc[cls] = out
        return out

    def instance_binders(self, name: str) -> list[tuple[str, int | None]]:
        out = []
        for _bi, head, args, depth in self.binders.get(name, []):
            carrier = None
            for kind, idx in reversed(args):
                if kind == "b":
                    carrier = depth - 1 - idx
                    break
            out.append((head, carrier))
        return out

    def verdicts(self, progress=None):
        """Second pass: judge each theorem against its cited constants."""
        for i, row in enumerate(self._rows()):
            if progress and i % 50000 == 0:
                progress(i)
            n = row["name"]
            if row.get("kind") != "theorem" or n not in self.binders:
                continue
            ibs = self.instance_binders(n)
            if not ibs:
                continue
            if len({c for _cls, c in ibs}) > 1:
                yield n, "multi-carrier", None, None
                continue
            if n in self.produces_class:
                yield n, "produces-a-class", None, None
                continue
            proof = row.get("uses_proof") or []
            ns = n.rsplit(".", 1)[0] if "." in n else None
            if ns and ns in self.classes and ns in proof:
                yield n, "projection-like", None, None
                continue
            reached: set[str] = set()
            for u in list(row.get("uses_statement") or []) + list(proof):
                if u in self.forgetful:
                    continue
                for cls, _c in self.instance_binders(u):
                    reached.add(cls)
            for cls, _carrier in ibs:
                if cls in reached:
                    yield n, "at-home", cls, None
                    continue
                hit = sorted(self.ancestors(cls) & reached)
                if not hit:
                    yield n, "unused", cls, None
                    continue
                weakest = next(
                    (c for c in hit
                     if all(o == c or o in self.ancestors(c) for o in hit)), None)
                if weakest is not None:
                    yield n, "over-hypothesis", cls, weakest
                else:
                    yield n, "no-single-home", cls, None
