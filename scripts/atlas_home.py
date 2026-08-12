"""Bound minimization (`atlas.md` §1b) computed from a slice, not from an environment.

`#atlas_home` already answers this per declaration, inside Lean, with the real instance
lattice. It is an `elab` command: there is no batch surface and no binding, so the claim
atlas.md leads with — "every gap found is a free generalization … to my knowledge nobody
runs it systematically" — has never actually been run systematically. This module is the
systematic run: same verdict rule, computed from B1's JSONL, so it covers a whole slice.

## What it needs, and where each piece comes from

A declaration's **declared** instance binders come from its own statement encoding: the
`pt(` binders of its telescope, whose domain heads a class.

The classes it **reaches** come from the constants it cites. Every constant carries its own
instance binders — that constant's written statement of what it requires — so the union
over cited constants is what the declaration actually demands. This is B3's evidence rule,
unchanged; the only difference is that the union is taken over rows rather than over an
`Expr` walk.

The **lattice** comes from parent projections. `CommRing.toRing` is a declaration in the
slice whose type goes from something headed by `CommRing` to something headed by `Ring`,
which is the edge `CommRing → Ring`. Ancestry is that relation's transitive closure.

## The exclusion that decides whether this tool is worth anything

B3 learned, over three tries, that counting the wrong constants makes *every* declaration
report "at home" — a tool that says everything is fine, which is worse than no tool. The
two exclusions it landed on were parent projections (`CommRing.toRing`) and instances
(`instCommSemiringOfCommRing`), and here they turn out to be one rule:

**A constant whose conclusion is itself a class application is plumbing, not evidence.**

Both excluded families produce an instance rather than consuming one. What counts as
evidence is a constant that *takes* a class binder and concludes something else — a lemma
or an operation. Stated this way the rule needs no name matching, which matters because
`instAddCommMonoidNat` and `Nat.add_comm` are told apart by their types and not by their
spelling.

## The restriction that keeps it sound

`#atlas_home`'s D3 revision attaches each piece of evidence to the carrier it was found at,
because with a flat set "a class reached at `S`" is indistinguishable from "a class reached
at `R`", and a binder can be told it is over-strong on its neighbour's evidence. Recovering
that from rows would mean matching each use site's arguments, which the row does not carry.

So the default `home` method does not try: it **judges only declarations all of whose
instance binders constrain the same carrier**, where the flat set and the carrier-aware set
are equal by construction. Multi-carrier declarations are counted and reported as skipped
rather than judged wrongly. That is a real coverage limit, and naming it is cheaper than a
verdict nobody can trust.

Every verdict is a *candidate*. `#atlas_home_confirm` puts the weakened binder in front of the
kernel, and only the kernel settles it.

`statement_candidates` is a deliberately separate search surface. Historical replay found
one theorem whose own class (`ContinuousDiv G`) carries synthesized class arguments after
its structural parameter; the conservative carrier rule mistakes one of those instances for
the theorem's carrier and refuses the declaration. The search surface reads parameter roles
from the cited class declaration, uses statement evidence only, and returns *all* weaker
classes that cover those requirements. It does not choose a winner: class-head evidence
erases indices such as the `0` in `OfNat G 0`, so only statement re-elaboration may discard
the resulting false candidates. The default `home` rule remains unchanged.

`carrier_statement_candidates` is the next, explicitly opt-in lane. New extractor rows may
carry `requirements_statement` entries naming the cited source, required class, and outer
carrier-binder index. This method keeps source provenance long enough to apply the same
forgetful-instance exclusion, then enumerates candidates independently per carrier. Missing
or composite carrier identities are not treated as negative evidence; a row without the new
field is refused, and every proposal still requires statement re-elaboration and proof.
"""

from __future__ import annotations

import collections

TAG = "atlas-stmt-v1;"


# ---------------------------------------------------------------------------
# A shallow reader for the I3 encoding.
#
# Deliberately not a parse into trees: a full tree for every statement in a Mathlib-sized
# slice is tens of millions of nodes. Everything below needs only the telescope's binders
# and the conclusion's head, so domains are *skipped* by advancing an index and only the
# few that matter are looked at.
# ---------------------------------------------------------------------------

class Reader:
    __slots__ = ("b", "i")

    def __init__(self, encoding: str) -> None:
        # Byte-oriented: names are byte-length-prefixed and may hold any UTF-8, so
        # `c(3:ℝ,0)` is three bytes and one character.
        self.b = encoding.encode()
        self.i = TAG_LEN if self.b.startswith(TAG_B) else 0

    def _name(self) -> str:
        j = self.i
        while self.b[j] != 0x3A:  # ':'
            j += 1
        ln = int(self.b[self.i:j])
        self.i = j + 1 + ln
        return self.b[j + 1:j + 1 + ln].decode("utf-8", "replace")

    def _digits(self) -> int:
        j = self.i
        while j < len(self.b) and 0x30 <= self.b[j] <= 0x39:
            j += 1
        v = int(self.b[self.i:j]) if j > self.i else 0
        self.i = j
        return v

    def _skip_level(self) -> None:
        c = self.b[self.i]
        if c == 0x30:  # '0'
            self.i += 1
        elif c == 0x75:  # 'u'
            self.i += 1
            self._digits()
        elif c in (0x2B, 0x4D, 0x49):  # '+', 'M', 'I'
            self.i += 2  # the letter and '('
            self._skip_level()
            while self.b[self.i] == 0x2C:  # ','
                self.i += 1
                self._skip_level()
            self.i += 1  # ')'
        else:
            raise ValueError(f"level at {self.i}")

    def skip(self) -> None:
        """Advance past one expression."""
        c = self.b[self.i]
        if c == 0x62:  # 'b'
            self.i += 1
            self._digits()
        elif c == 0x6E:  # 'n'
            self.i += 1
            self._digits()
        elif c == 0x74:  # 't' string literal
            self.i += 1
            self._name()
        elif c == 0x73 and self.b[self.i + 1] == 0x28:  # 's('
            self.i += 2
            self._skip_level()
            self.i += 1
        elif c == 0x63:  # 'c('
            self.i += 2
            self._name()
            self.i += 1  # ','
            n = self._digits()
            for _ in range(n):
                self.i += 1  # ','
                self._skip_level()
            self.i += 1  # ')'
        elif c == 0x61:  # 'a('
            self.i += 2
            self.skip()
            self.i += 1
            self.skip()
            self.i += 1
        elif c in (0x6C, 0x70):  # 'l' / 'p' + binder info
            self.i += 3  # letter, bi, '('
            self.skip()
            self.i += 1
            self.skip()
            self.i += 1
        elif c == 0x65:  # 'e('
            self.i += 2
            self.skip()
            self.i += 1
            self.skip()
            self.i += 1
            self.skip()
            self.i += 1
        elif c == 0x6A:  # 'j('
            self.i += 2
            self._name()
            self.i += 1
            self._digits()
            self.i += 1
            self.skip()
            self.i += 1
        else:
            raise ValueError(f"expr {chr(c)!r} at {self.i}")

    def head_and_args(self) -> tuple[str | None, list[tuple[str, int]]]:
        """The head constant of an application spine, and its arguments' shapes.

        An argument is reported as `("b", index)` for a de Bruijn variable and
        `("o", 0)` for anything else — enough to identify a carrier, which is all the
        caller wants.
        """
        args: list[tuple[str, int]] = []
        while self.b[self.i] == 0x61:  # 'a('
            self.i += 2
            start = self.i
            self.skip()  # the function half; re-read below
            mid = self.i
            self.i += 1
            if self.b[self.i] == 0x62:  # bvar argument
                self.i += 1
                args.append(("b", self._digits()))
            else:
                self.skip()
                args.append(("o", 0))
            self.i += 1  # ')'
            end = self.i
            # Recurse into the function half by re-reading it in place.
            sub = Reader.__new__(Reader)
            sub.b, sub.i = self.b, start
            h, inner = sub.head_and_args()
            args = inner + args
            self.i = end
            return h, args
        if self.b[self.i] == 0x63:  # 'c('
            self.i += 2
            n = self._name()
            self.i += 1
            k = self._digits()
            for _ in range(k):
                self.i += 1
                self._skip_level()
            self.i += 1
            return n, args
        self.skip()
        return None, args


TAG_B = TAG.encode()
TAG_LEN = len(TAG_B)


def telescope(encoding: str, limit: int = 64):
    """The declaration's top-level `forall` binders and its conclusion head.

    Returns `(binders, conclusion_head)` where each binder is
    `(binder_info, domain_head, domain_args)`.
    """
    r = Reader(encoding)
    binders = []
    depth = 0
    while depth < limit and r.i < len(r.b) and r.b[r.i] == 0x70:  # 'p'
        bi = chr(r.b[r.i + 1])
        r.i += 3
        sub = Reader.__new__(Reader)
        sub.b, sub.i = r.b, r.i
        head, args = sub.head_and_args()
        binders.append((bi, head, args, depth))
        r.i = sub.i
        r.i += 1  # ','
        depth += 1
    concl = Reader.__new__(Reader)
    concl.b, concl.i = r.b, r.i
    try:
        chead, _ = concl.head_and_args()
    except Exception:
        chead = None
    return binders, chead


# ---------------------------------------------------------------------------
# The lattice, the evidence rule, and the verdict
# ---------------------------------------------------------------------------

class HomeIndex:
    """Everything `home` needs about a slice, built once."""

    def __init__(self, rows: dict[str, dict], progress=None) -> None:
        self.rows = rows
        self.binders: dict[str, list] = {}
        self.concl: dict[str, str | None] = {}
        self.parse_errors = 0

        for k, (name, row) in enumerate(rows.items()):
            if progress and k % 50000 == 0:
                progress(k)
            stmt = row.get("stmt")
            if not stmt:
                continue
            try:
                b, c = telescope(stmt)
            except Exception:
                self.parse_errors += 1
                continue
            self.binders[name] = b
            self.concl[name] = c

        # A class is anything that appears as the head of an instance-binder domain.
        self.classes: set[str] = set()
        for b in self.binders.values():
            for bi, head, _args, _d in b:
                if bi == "t" and head:
                    self.classes.add(head)

        # Constants that produce an instance rather than consuming one.
        self.produces_class: set[str] = {
            n for n, c in self.concl.items() if c in self.classes
        }

        # The lattice, read off parent projections: `X.toY` from a class X to a class Y.
        self.parents: dict[str, set[str]] = collections.defaultdict(set)
        for name in self.binders:
            if ".to" not in name:
                continue
            owner = name.rsplit(".to", 1)[0]
            concl = self.concl.get(name)
            if owner in self.classes and concl in self.classes and concl != owner:
                self.parents[owner].add(concl)

        # Subjects whose "proof" is a field access rather than an argument.
        #
        # `AddCommMagma.add_comm` cites exactly one constant — `AddCommMagma` — because it
        # *is* the class's field, read off the structure. The evidence rule then finds
        # nothing that needs the binder and reports it unused, which is true of the cited
        # constants and false about the declaration: the binder is the thing being
        # projected. Left unstratified these dominate the `unused` verdict and the survey
        # reads as thousands of free generalizations that are all one artifact.
        #
        # Tagged rather than dropped, per CLAUDE.md's rule that a split ground truth is
        # stratified: a projection is still a real declaration and the count of them is
        # part of understanding what the evidence rule can and cannot see from a row.
        self.projection_like: set[str] = set()
        for name in self.binders:
            ns = name.rsplit(".", 1)[0] if "." in name else None
            if ns and ns in self.classes:
                if ns in (rows[name].get("uses_proof") or ()):
                    self.projection_like.add(name)

        self._anc_cache: dict[str, set[str]] = {}

        # **Forgetful** instances, the ones that actually have to be excluded.
        #
        # B3 excluded instances wholesale, because without that every declaration reported
        # "at home": a proof citing `instCommSemiringOfCommRing` (which takes `[CommRing R]`
        # and yields `CommSemiring R`) hands back the declared class as evidence for
        # itself, and the walk can never find anything weaker.
        #
        # But the wholesale rule severs a path it should not. `AddOpposite.op_add` writes
        # `+`, elaborated as `HAdd.hAdd` needing `[HAdd α α α]`, supplied by
        # `instHAdd : [Add α] → HAdd α α α` — so the declared `Add` binder is reached
        # *only* through an instance. Excluding it reports `Add` unused for a statement
        # whose whole content is an addition. Measured, not hypothesised: see the
        # `AddOpposite.op_*` family, 14 of them in the algebra slice alone.
        #
        # The two cases differ by direction. A forgetful instance walks *down* the lattice
        # it is being asked about — its conclusion class is an ancestor of one of its own
        # binder classes — so it re-states the hypothesis. `instHAdd` does not: `HAdd` is
        # not an ancestor of `Add`, it is a different requirement. So exclude the
        # direction, not the kind, and parent projections fall out as the special case
        # they always were.
        self.forgetful: set[str] = set()
        for name in self.produces_class:
            concl = self.concl.get(name)
            for cls, _carrier in self.instance_binders(name):
                if concl in self.ancestors(cls) or concl == cls:
                    self.forgetful.add(name)
                    break

    def ancestors(self, cls: str) -> set[str]:
        """Strict ancestors of a class, transitively."""
        hit = self._anc_cache.get(cls)
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
        self._anc_cache[cls] = out
        return out

    def instance_binders(self, name: str) -> list[tuple[str, int | None]]:
        """`(class, carrier binder index)` for each instance binder, outermost first."""
        out = []
        for bi, head, args, depth in self.binders.get(name, []):
            if bi != "t" or not head:
                continue
            carrier = None
            for kind, idx in reversed(args):
                if kind == "b":
                    # Inside binder `depth`'s domain, bvar `idx` is binder `depth-1-idx`.
                    carrier = depth - 1 - idx
                    break
            out.append((head, carrier))
        return out

    def parameter_aware_instance_binders(self, name: str) -> list[tuple[str, int | None]]:
        """Instance binders keyed by their class's last structural parameter.

        Fully elaborated applications include a class declaration's own instance
        parameters. For `ContinuousDiv G`, for example, the application spine contains
        `G`, a `TopologicalSpace G` instance, and a `Div G` instance. The ordinary rule's
        last-bvar heuristic therefore keys it to an instance binder rather than to `G`.

        This variant aligns application arguments with the class declaration's telescope,
        drops arguments whose corresponding parameters are themselves instance implicit,
        and then applies the existing last-bvar convention. Multi-parameter structural
        classes such as `SMul R M` consequently remain keyed to `M`.
        """
        out = []
        for bi, head, args, depth in self.binders.get(name, []):
            if bi != "t" or not head:
                continue
            class_params = self.binders.get(head, ())
            structural_args = [
                arg for arg, param in zip(args, class_params) if param[0] != "t"
            ]
            carrier = None
            for kind, idx in reversed(structural_args or args):
                if kind == "b":
                    carrier = depth - 1 - idx
                    break
            out.append((head, carrier))
        return out

    def evidence(self, row: dict) -> set[str]:
        """Classes the declaration's cited constants require.

        Forgetful instances are skipped — they would return the declared hypothesis as
        evidence for itself. Every other instance is *traversed*: the classes it requires
        are requirements the citing declaration inherits, which is how a notation reaches
        the class that implements it.
        """
        got: set[str] = set()
        for u in row.get("uses_statement", ()) + row.get("uses_proof", ()):
            if u in self.forgetful:
                continue
            for cls, _carrier in self.instance_binders(u):
                got.add(cls)
        return got

    def home(self, name: str) -> dict | None:
        """The verdict for one declaration, or `None` when it is not judgeable.

        `None` covers three cases, each counted by `survey`: no statement, no instance
        binder to weaken, or binders spanning more than one carrier — see the module
        docstring for why the last is refused rather than approximated.
        """
        row = self.rows.get(name)
        if row is None or name not in self.binders:
            return None
        ibs = self.instance_binders(name)
        if not ibs:
            return None
        carriers = {c for _cls, c in ibs}
        if len(carriers) > 1:
            return {"skipped": "multi-carrier", "carriers": len(carriers)}
        if name in self.produces_class:
            return {"skipped": "produces-a-class"}

        reached = self.evidence(row)
        verdicts = []
        for cls, _carrier in ibs:
            if cls in reached:
                verdicts.append({"class": cls, "verdict": "at-home"})
                continue
            anc = self.ancestors(cls)
            hit = sorted(anc & reached)
            if not hit:
                verdicts.append({"class": cls, "verdict": "unused", "reached": []})
                continue
            weakest = None
            for cand in hit:
                if all(other == cand or other in self.ancestors(cand) for other in hit):
                    weakest = cand
                    break
            if weakest is not None:
                verdicts.append({"class": cls, "verdict": "over-hypothesis",
                                 "home": weakest, "reached": hit})
            else:
                verdicts.append({"class": cls, "verdict": "no-single-home",
                                 "reached": hit})
        return {"name": name, "module": row.get("module"), "kind": row.get("kind"),
                "projection_like": name in self.projection_like,
                "binders": verdicts}

    def statement_candidates(self, name: str) -> dict | None:
        """Enumerate weaker classes compatible with statement-level class heads.

        This is search, not the `home` verdict. It uses parameter-aware carriers so a
        declaration conservatively refused by `home` can enter the lane, ignores the old
        proof because a generalization may need a new proof, and returns every strict
        ancestor strong enough to provide all reached statement classes. Candidates are not
        guaranteed to form a well-typed rewritten statement: applied class arguments are
        absent from row evidence, so the caller must re-elaborate each statement and then
        prove it in Lean.
        """
        row = self.rows.get(name)
        if row is None or name not in self.binders:
            return None
        ibs = self.parameter_aware_instance_binders(name)
        if not ibs:
            return None
        carriers = {carrier for _cls, carrier in ibs}
        if len(carriers) > 1:
            return {"skipped": "multi-carrier", "carriers": len(carriers)}
        if name in self.produces_class:
            return {"skipped": "produces-a-class"}

        reached: set[str] = set()
        for used in row.get("uses_statement", ()):
            if used in self.forgetful:
                continue
            for cls, _carrier in self.instance_binders(used):
                reached.add(cls)

        verdicts = []
        for cls, _carrier in ibs:
            if cls in reached:
                verdicts.append({"class": cls, "verdict": "at-home", "candidates": []})
                continue
            ancestors = self.ancestors(cls)
            requirements = sorted(ancestors & reached)
            if not requirements:
                verdicts.append({"class": cls, "verdict": "unused", "reached": [],
                                 "candidates": []})
                continue
            candidates = sorted(
                candidate for candidate in ancestors
                if all(req == candidate or req in self.ancestors(candidate)
                       for req in requirements)
            )
            verdicts.append({
                "class": cls,
                "verdict": "candidates" if candidates else "no-single-home",
                "reached": requirements,
                "candidates": candidates,
            })
        return {"name": name, "module": row.get("module"), "kind": row.get("kind"),
                "projection_like": name in self.projection_like,
                "binders": verdicts}

    def carrier_statement_candidates(self, name: str) -> dict | None:
        """Enumerate statement-compatible ancestors from carrier-attached row evidence.

        This is a search surface, not a minimal-home verdict. It is allowed to propose a
        candidate that statement re-elaboration later rejects, but it must not move evidence
        between carriers. Rows produced before `requirements_statement` existed are refused
        rather than interpreted as saying that nothing was required.
        """
        row = self.rows.get(name)
        if row is None or name not in self.binders:
            return None
        # This option-gated lane may distinguish an ordinary theorem whose conclusion is
        # class-valued from a declaration registered for typeclass synthesis. The
        # extractor records that environment fact explicitly. Constructors, definitions,
        # registered theorems, and legacy rows remain on the conservative refusal path.
        # The two older methods deliberately keep their frozen blanket guards.
        class_claim = row.get("kind") == "theorem" and row.get("is_instance") is False
        if name in self.produces_class and not class_claim:
            return {"skipped": "produces-a-class"}
        if "requirements_statement" not in row:
            return {"skipped": "no-carrier-evidence"}
        ibs = self.parameter_aware_instance_binders(name)
        if not ibs:
            return None

        reached_by_carrier: dict[int, set[str]] = collections.defaultdict(set)
        retained = 0
        for requirement in row.get("requirements_statement") or ():
            source = requirement.get("source")
            cls = requirement.get("class")
            carrier = requirement.get("carrier")
            if source in self.forgetful or not cls or not isinstance(carrier, int):
                continue
            reached_by_carrier[carrier].add(cls)
            retained += 1

        verdicts = []
        for cls, carrier in ibs:
            if carrier is None:
                verdicts.append({"class": cls, "carrier": None,
                                 "verdict": "unknown-carrier", "candidates": []})
                continue
            reached = reached_by_carrier.get(carrier, set())
            if cls in reached:
                verdicts.append({"class": cls, "carrier": carrier,
                                 "verdict": "at-home", "candidates": []})
                continue
            ancestors = self.ancestors(cls)
            requirements = sorted(ancestors & reached)
            candidates = sorted(
                candidate for candidate in ancestors
                if all(req == candidate or req in self.ancestors(candidate)
                       for req in requirements)
            ) if requirements else []
            verdicts.append({
                "class": cls,
                "carrier": carrier,
                "verdict": "candidates" if candidates else "no-attached-requirement",
                "reached": requirements,
                "candidates": candidates,
            })
        return {"name": name, "module": row.get("module"), "kind": row.get("kind"),
                "projection_like": name in self.projection_like,
                "retained_statement_requirements": retained,
                "binders": verdicts}


def node_count(encoding: str) -> int:
    """How many expression nodes the encoding holds.

    Needed to score alternatives to `retention`, which divides shared structure by the
    *larger* side and so penalises a pair for being verbose rather than for being
    dissimilar. Comparing that against Dice, Jaccard and a min-normalised variant needs
    both sides' sizes, and the encoding is the only place they live.
    """
    r = Reader(encoding)
    n = 0
    while r.i < len(r.b):
        before = r.i
        c = r.b[r.i]
        if c in (0x61, 0x65):            # 'a(' / 'e(' — descend
            r.i += 2
            n += 1
            continue
        if c in (0x6C, 0x70):            # 'l' / 'p' + binder info
            r.i += 3
            n += 1
            continue
        if c in (0x2C, 0x29):            # ',' ')'
            r.i += 1
            continue
        try:
            r.skip()
            n += 1
        except Exception:
            break
        if r.i == before:
            break
    return n
