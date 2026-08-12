"""Type stubs for the Atlas Python binding.

The `Corpus` namespace of `research/python-api.md` §2 — B2's graph, B4's skeleton index,
B5's equivalence graph and B6's dictionaries. Nothing outside `Corpus` is bound yet; see
`crates/atlas-py/README.md` for what is missing and why.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Literal

Lens = Literal["statement", "proof", "both"]
"""Which dependency edges a query walks.

`statement` is what a claim rests on, `proof` is what an argument rests on, `both` is the
citation graph as a reader would draw it. The distinction is not a detail: "can I weaken
this hypothesis" is the first question, "what breaks if this proof is wrong" the second.
"""

Level = Literal["exact", "presentation", "instances", "carriers", "shape"]
Score = Literal[
    "retention",
    "min_normalised",
    "dice",
    "jaccard",
    "geometric_mean",
    "common",
    "info_weighted",
    "info_dice",
]
"""Which formula turns shared structure into a number.

Pluggable because **no single one wins everywhere**, measured by ROC AUC against labelled
pairs on two corpora with independently-sourced labels:

| score | size-asymmetric pairs | size-symmetric pairs |
|---|---|---|
| `min_normalised` | 0.933 | 1.000 |
| `retention` (default) | 0.756 | 1.000 |
| `common` | 0.943 | 0.762 |

`retention` divides shared structure by the *larger* side, so it is perfect when the two
sides are the same size and collapses when they are not — and cross-theory pairs are wildly
asymmetric, because the same claim carries different type and instance machinery in
different theories (`Z.euclid_lemma` is 65 nodes, `FF.poly_euclid_lemma` 1,059). The default
stays `retention` so results remain comparable; `min_normalised` is the more robust choice.

The floor `min_retention` applies to whichever score is selected, not to retention —
flooring on one and ranking on another would discard exactly the pairs a different scorer
exists to rescue.
"""

Anchor = Literal["root", "conclusion"]
"""Where a statement is compared *from*.

Anti-unification aligns two terms from their roots, so a theorem carrying a hypothesis
prefix cannot match one without — even when both conclude the same thing. Measured on B7's
validation clusters: `RH.zeros_subset_critical_line` and `Spectral.spectrum_subset_real`
are both literally `S subset {x | P x}`, and their lgg is `common 0, retention 0.0`.

`"conclusion"` discards the binder prefix and compares what the statement concludes, which
is the question cross-theory analogy needs. On B7 it moved spectrum-is-real from absent-in-
top-8 to rank 3; on physlib's 2,287 quantum declarations it costs one percentage point of
cross-subfield noise (9% -> 10%). Not the default: the two settings answer different
questions and a call site should say which one it meant.
"""
"""How much to squint. The levels are a chain: coarser buckets are unions of finer ones."""

class AtlasError(Exception):
    """Base class for every error this module raises."""

class SliceError(AtlasError):
    """A slice could not be read as B1 JSONL. The message names the offending line."""

class UnknownDeclaration(AtlasError):
    """No declaration by that name in this slice."""

class NoStatement(AtlasError):
    """The declaration is in the slice but carries no usable I3 statement encoding."""

class NotAProposition(AtlasError):
    """Equivalence was asked of something that is not a claim.

    Raised rather than answered: without the guard the query returns every declaration
    whose type is literally `Type`, which is a type index wearing a relation's name.
    """

class NoMatch(AtlasError):
    """The subject does not match the dictionary row's left-hand pattern.

    A failure of applicability, not of transport — the row simply says nothing about this
    statement.
    """

class ScopedRow(AtlasError):
    """The row has a variable standing for something under a binder.

    It cannot be instantiated independently of that binder, so the image would be a
    different statement than the one the row promises.
    """

class Decl:
    """One declaration, as B1's extractor emitted it."""

    @property
    def name(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def module(self) -> str: ...
    @property
    def stmt(self) -> str | None:
        """The I3 canonical statement encoding, `None` when it could not be encoded."""

    @property
    def stmt_error(self) -> str | None:
        """Why `stmt` is absent. Present exactly when `stmt` is absent."""

    @property
    def uses_statement(self) -> list[str]:
        """What the claim cites, **directly** — the row as extracted.

        `Corpus.foundations` answers the transitive question; this answers the extractor's
        one, which is what a claim about B1's output has to ask.
        """

    @property
    def uses_proof(self) -> list[str]:
        """What the argument cites, directly."""

    def __repr__(self) -> str: ...

class Relation:
    """One typed edge of the theory map (Engine 1 §5).

    Branch on `warrant`. `"proved"` means a Lean theorem says so and `witness` names it;
    `"structural"` means two canonical encodings compared equal; `"heuristic"` means a
    ranking produced it. Engine 1's fifth non-goal is that these must not share a result
    type, so ignoring this field is making a claim the engine did not.
    """

    @property
    def left(self) -> str: ...
    @property
    def right(self) -> str: ...
    @property
    def kind(self) -> str:
        """One of the fifteen versioned kinds, e.g. `"ProvedIff"`."""

    @property
    def direction(self) -> str:
        """`"both"`, `"left_to_right"` or `"right_to_left"`."""

    @property
    def warrant(self) -> str:
        """`"proved"`, `"structural"` or `"heuristic"`."""

    @property
    def evidence(self) -> str:
        """Which sort of evidence, e.g. `"lean_theorem"`."""

    @property
    def witness(self) -> str | None:
        """The theorem's name when `evidence == "lean_theorem"`, else `None`."""

    @property
    def generator(self) -> str: ...
    @property
    def schema_version(self) -> int: ...
    def explain(self) -> str:
        """An explanation built from the stored evidence, never from free prose."""


class LogicalStats:
    """What the proved-edge extraction actually saw over a slice."""

    @property
    def edges(self) -> int: ...
    @property
    def heads(self) -> int: ...
    @property
    def theorems_scanned(self) -> int: ...
    @property
    def iff_edges(self) -> int: ...
    @property
    def implication_edges(self) -> int: ...
    @property
    def flex_head_sides(self) -> int:
        """Sides whose head is a bound variable, needing higher-order matching. Surfaced
        because "we did not look" and "there is nothing there" are different answers."""

    @property
    def axioms_scanned(self) -> int:
        """Axioms scanned for logical edges.

        Extraction used to skip anything whose kind was not `theorem`, which made a
        statement-level corpus invisible: B7's validation clusters produced zero edges,
        including `RiemannHypothesis <-> Lambda <= 0` sitting in the corpus. Edges from an
        axiom carry `warrant == "asserted"`, never `"proved"`.
        """

    @property
    def same_head_sides(self) -> int:
        """`Iff`s whose two sides key to the same `(head, arity)`, so the edge would be a
        self-loop and is dropped.

        The largest missing category, and until recently uncounted: on physlib 184 of 516
        `Iff`-headed theorems land here against 71 flex-headed. Dominated by extensionality
        lemmas (`X.ext_iff : a = b ↔ a.f = b.f` is `Eq/3` on both sides), which carry real
        content that carrier-blind head keying cannot represent.
        """

    @property
    def non_prop_sides(self) -> int:
        """Non-dependent `Pi`s rejected because a side does not head a proposition."""

    @property
    def prop_heads(self) -> int: ...


class PolicyPoint:
    """One operating point of the coverage/coherence trade-off."""

    @property
    def policy(self) -> str:
        """`"unconstrained"`, `"many_to_one_3"`, `"many_to_one_2"` or `"injective"`."""

    @property
    def rows(self) -> int: ...
    @property
    def lefts(self) -> int: ...
    @property
    def collision_rate(self) -> float:
        """0.0 exactly when the selection is a map."""

    @property
    def mean_score(self) -> float: ...
    @property
    def unmatched(self) -> int:
        """Lefts whose partner cleared every floor and lost it to a better claim."""


class Coherence:
    """How far a dictionary is from the map it claims to be.

    Rights are counted by *statement*, not by name — two names for one theorem would
    otherwise let a left displaced onto an alias score as a coherence improvement.
    """

    @property
    def rows(self) -> int: ...
    @property
    def distinct_lefts(self) -> int: ...
    @property
    def distinct_rights(self) -> int: ...
    @property
    def distinct_right_statements(self) -> int:
        """Below `distinct_rights` exactly when two names for one theorem are pointed at."""

    @property
    def contested(self) -> int:
        """Right statements claimed by more than one left."""

    @property
    def rows_in_collision(self) -> int: ...
    @property
    def worst(self) -> list[tuple[str, int]]:
        """`(right name, lefts claiming its statement)`, worst first."""

    @property
    def collision_rate(self) -> float:
        """The fraction of the dictionary that is not a map."""


class ShuffleControl:
    """Design §9's control: are false shuffled mappings rejected earlier than genuine ones?"""

    @property
    def pairs(self) -> int: ...
    @property
    def genuine_mean(self) -> float: ...
    @property
    def shuffled_mean(self) -> float: ...
    @property
    def shuffled_admitted(self) -> int:
        """Shuffled pairs still clearing the floors — the rate a coincidence survives."""

    @property
    def separation(self) -> float:
        """Fraction where the genuine pair outscores its shuffled twin. 1.0 perfect, 0.5 chance."""


class ScoreFactors:
    """The multiplicands of a `Neighbour.score` — Engine 1 §6 C2's feature vector."""

    @property
    def retention(self) -> float:
        """Shared concrete structure as a fraction of the larger side."""

    @property
    def rarity_boost(self) -> float:
        """`1 + w * min(rarity / ln N, 1)` — how surprising the shared key is."""

    @property
    def cross_boost(self) -> float:
        """`1 + w` when the candidate is under another module root, else 1."""

    @property
    def derivative_penalty(self) -> float:
        """`1 - w * derivativeness(candidate)` — how auto-generated the candidate looks.

        Structural, never nominal: short proof, cites recursors and constructors rather
        than theorems, nothing cites it back. Measured against a name-based label set it
        reaches AUC 0.899 on physlib and 0.886 on a 131k Mathlib slice.

        A penalty rather than a filter. At a hard threshold the measure runs precision
        0.62-0.67, so filtering would discard a genuine declaration for roughly every piece
        of boilerplate removed; recall is what cannot be recovered downstream.
        """

    @property
    def base(self) -> float:
        """The configured scorer's value — what actually multiplies into `total`.

        Separate from `retention`, which is always the classic formula so two runs under
        different scorers stay comparable on one axis.
        """

    @property
    def scoped_penalty(self) -> float:
        """`1 - w * scoped/vars`; below 1 exactly when the row is not transportable."""

    @property
    def total(self) -> float: ...


class ScorerId:
    """Which scorer produced a row. Rows are comparable only when these match."""

    @property
    def name(self) -> str: ...
    @property
    def version(self) -> int:
        """Bumped when the score's *shape* changes; a weight change moves config_digest."""

    @property
    def config_digest(self) -> str:
        """Over every config field that can move a score."""

    @property
    def corpus_digest(self) -> str:
        """Over the slice — the score is not a function of (pair, config) alone."""


class Generalization:
    """The least general generalization of two statements, with the numbers that rank it."""

    @property
    def skeleton(self) -> str:
        """Rendered in the I3 grammar: `_` is a hole, `?k` an anti-unification variable."""

    @property
    def common(self) -> int:
        """Non-hole, non-variable nodes — how much structure the two actually share."""

    @property
    def vars(self) -> int: ...
    @property
    def scoped_vars(self) -> int:
        """Variables standing for something with loose de Bruijn indices.

        Such a row reads fine and is **not** transportable. Never zero-by-omission: if this
        is positive, the generalization is a local coincidence rather than a dictionary row.
        """

    @property
    def retention(self) -> float:
        """`common / max(concrete(x), concrete(y))`, in `[0,1]`; exactly 1 when the inputs are equal."""

    def __repr__(self) -> str: ...

class Neighbour:
    """One neighbour from `Corpus.similar`, with the numbers that rank it."""

    @property
    def name(self) -> str: ...
    @property
    def module(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def retention(self) -> float:
        """`common / max(concrete(x), concrete(y))` of the anti-unification against the query."""

    @property
    def common(self) -> int: ...
    @property
    def vars(self) -> int: ...
    @property
    def scoped_vars(self) -> int:
        """Variables abstracting something locally bound. Positive means not transportable."""

    @property
    def rarity(self) -> float:
        """The rarest shared index key's IDF — how surprising the overlap is."""

    @property
    def sources(self) -> list[str]:
        """Which of the index's three sources found this: `shape`, `subterm`,
        `shape-subterm`. `shape-subterm` is the one that carries cross-theory analogies.
        """

    @property
    def skeleton(self) -> str:
        """The rendered anti-unification. This *is* the candidate dictionary row."""

    @property
    def transportable(self) -> bool:
        """`scoped_vars == 0`. `Corpus.transport` refuses the rest."""

    @property
    def score(self) -> float:
        """Retention weighted by rarity and a cross-theory bonus. A ranking key, not a
        probability — comparable within one query's results and nowhere else.
        """

    @property
    def factors(self) -> ScoreFactors:
        """The score factor by factor, so a rank can be audited or ablated rather than
        trusted. `factors.total == score`.
        """

    def __repr__(self) -> str: ...

class Row:
    """One candidate dictionary row: two declarations that anti-unify, and how far."""

    @property
    def left(self) -> str: ...
    @property
    def right(self) -> str: ...
    @property
    def skeleton(self) -> str: ...
    @property
    def retention(self) -> float: ...
    @property
    def status(self) -> Literal["both-proven", "one-proven", "neither-proven"]:
        """Whether each half of the row is a theorem or merely a definition."""

    @property
    def transportable(self) -> bool: ...
    def __repr__(self) -> str: ...

class Dictionary:
    """A dictionary between two theory fragments: the rows, and what has no partner."""

    @property
    def left_theory(self) -> str: ...
    @property
    def right_theory(self) -> str: ...
    @property
    def rows(self) -> list[Row]:
        """The matched rows, best retention first."""

    @property
    def missing_left(self) -> list[str]:
        """Declarations on the left with no partner on the right.

        **The point of the exercise.** A missing entry is where the analogy has not been
        made, which is where the research is; a total dictionary would mean there is none.
        """

    @property
    def missing_right(self) -> list[str]: ...
    def __repr__(self) -> str: ...

class Transported:
    """What transporting a statement along a dictionary row produced.

    One class with a boolean discriminant rather than two: `if t.exists:` is what every
    caller writes, and `name` is `None` exactly when `exists` is `False`.
    """

    @property
    def exists(self) -> bool:
        """True when the image is already a declaration in the slice — the outcome that
        turns a candidate row into a verified one.
        """

    @property
    def name(self) -> str | None:
        """The declaration the image turned out to be; `None` exactly when it is open."""

    @property
    def image(self) -> str:
        """The image statement in the I3 grammar. When it does not exist this is the
        directed target — falsify it before proving it, because refutation is cheap and
        locates the analogy's boundary.
        """

    def __repr__(self) -> str: ...

class FrontierPair:
    """One theory pair's frontier reading: similar, and not talking to each other."""

    @property
    def left(self) -> str: ...
    @property
    def right(self) -> str: ...
    @property
    def similarity(self) -> float:
        """Shape buckets both theories occupy, over the smaller theory's bucket count."""

    @property
    def expected_similarity(self) -> float:
        """What two theories of these sizes would share **by chance**.

        Under random assignment of shapes to theories, `E|A cap B| = |A||B|/M`, so dividing
        by `min(|A|,|B|)` leaves `max(|A|,|B|)/M`. A large theory therefore has high
        expected similarity with everything, which is why the uncorrected ranking returned
        the biggest theory pairs rather than the most similar ones.
        """

    @property
    def excess(self) -> float:
        """`similarity - expected_similarity` — shared shape beyond what size explains.

        Often negative: most theory pairs are *less* alike than chance. Measured on two
        corpora, aggregate cross-theory similarity is indistinguishable from chance while
        within-theory concentration is a very strong signal (findings section 17-18).
        """

    @property
    def cross_citations(self) -> int:
        """Declarations in one theory whose statement or proof cites the other."""

    @property
    def left_size(self) -> int: ...
    @property
    def right_size(self) -> int: ...
    @property
    def score(self) -> float:
        """`similarity / (1 + sqrt(cross_citations))`. Similarity buys, traffic discounts."""

    def __repr__(self) -> str: ...

class Corpus:
    """A parsed slice: one load, many queries.

    Loading parses the whole JSONL once (~5 s for 131k declarations); every query below
    then runs against the graph already in memory.

    Three further layers are built lazily, each by the first query that needs it and each
    once: the statement arena (`skeleton`, `generalize`), B5's equivalence index
    (`equivalent`, `classes`) and B4's skeleton index (`similar`, `dictionary`,
    `transport`, `frontier`). Measured on the 131,062-row algebra slice they cost 4.3 s,
    6.3 s and 13.7 s. A session that asks graph questions only pays none of it.
    """

    @staticmethod
    def load(path: str | os.PathLike[str]) -> Corpus:
        """Read and parse a B1 JSONL slice.

        Raises:
            FileNotFoundError: no file at `path`.
            SliceError: a row is not valid JSON or lacks a `name`.
        """

    def __len__(self) -> int:
        """How many declarations the slice holds."""

    def __repr__(self) -> str: ...
    def names(self) -> list[str]:
        """Every declaration name in the slice, sorted."""

    def get(self, name: str) -> Decl | None:
        """One declaration, or `None` if the slice does not have it."""

    def why(self, source: str, target: str, lens: Lens = "both") -> list[str] | None:
        """A shortest dependency chain from `source` down to `target`.

        `None` when no chain exists under this lens — which is an answer, not an error.
        `target` need not be in the slice: an edge out of the slice is a real fact about it.

        Raises:
            UnknownDeclaration: `source` is not in the slice.
            ValueError: `lens` is not one of the three names.
        """

    def foundations(self, name: str, lens: Lens = "both") -> list[str]:
        """Everything `name` transitively rests on, sorted. Excludes `name` itself.

        Raises:
            UnknownDeclaration: `name` is not in the slice.
            ValueError: `lens` is not one of the three names.
        """

    def impact(self, name: str, lens: Lens = "both") -> list[str]:
        """Everything that transitively rests on `name`, sorted.

        Unlike the other queries this does not require `name` to be in the slice: asking
        what rests on something outside it is a fair question, and the answer is the part
        of the slice that cites it.

        Raises:
            ValueError: `lens` is not one of the three names.
        """

    def walls(self, lens: Lens = "both", top: int = 20) -> list[tuple[str, int]]:
        """Declarations ranked by how many others cite them *directly*, most-cited first.

        Direct, not transitive: ranking a whole slice transitively is one BFS per node.
        Declarations nothing cites are omitted rather than padding the list with zeros, so
        the result may be shorter than `top`.
        """

    def honesty(self, whitelist: list[str] | None = None) -> list[tuple[str, str]]:
        """Declarations resting on `sorryAx` or on an axiom outside `whitelist`.

        Returns `(who, why)` pairs, sorted and deduplicated; an empty list means clean. The
        scan is transitive: a complete-looking theorem one step above a hole is not
        complete.

        `whitelist=None` means Lean's own three axioms (`propext`, `Classical.choice`,
        `Quot.sound`). An explicit list is used exactly as given, so `[]` allows nothing.
        """

    def skeleton(self, name: str, level: Level = "carriers") -> str:
        """The declaration's statement erased to `level`, rendered in the I3 grammar.

        Two statements are analogous at a level exactly when this string is equal for both.

        Raises:
            UnknownDeclaration: `name` is not in the slice.
            NoStatement: the row carries no statement, or one the parser rejected.
            ValueError: `level` is not one of the five names.
        """

    def generalize(
        self, left: str, right: str, anchor: Anchor = "root"
    ) -> Generalization:
        """Anti-unify two statements: the most specific term that matches both.

        Over the statements as encoded, not as erased — the concrete part is what the two
        theorems genuinely share and each variable is a place where they differ.

        Raises:
            UnknownDeclaration: either name is not in the slice.
            NoStatement: either row carries no usable statement.
        """

    def scorer_id(
        self,
        level: Level = "carriers",
        min_retention: float = 0.30,
        min_common: int = 6,
        theorems_only: bool = False,
    ) -> ScorerId:
        """Which scorer `similar` rows come from, for the config a query would use."""

    def similar(
        self,
        name: str,
        top: int = 10,
        level: Level = "carriers",
        min_retention: float = 0.30,
        min_common: int = 6,
        theorems_only: bool = False,
        anchor: Anchor = "root",
        normalize_arity: bool = False,
        score: Score = "retention",
        posting_work_budget: int | None = None,
    ) -> list[Neighbour]:
        """Declarations whose statements anti-unify with this one, best score first.

        `level` chooses the family, not just the fidelity: at `presentation` the neighbours
        keep the carrier and vary the operator, at `carriers` they keep the operator and
        vary the carrier. `min_common` and `min_retention` are the floors a candidate must
        clear to be reported at all; lowering them buys recall by admitting rows whose
        shared structure is punctuation.

        `posting_work_budget` switches the prefilter to work-budget admission: every
        posting key is kept at build time and the query walks at most this many postings,
        rarest key first, instead of dropping keys held by too many declarations. The
        flat cutoff deletes the *common* keys cross-domain analogy rides on — measured
        0/4 pre-registered classical<->quantum correspondences at the shipped cutoff,
        4/4 with the keys admitted (findings §66). `None` is the shipped cutoff, bit for
        bit. The first call at each (anchor, normalize_arity, budget-on) combination
        builds and caches its own index.

        Raises:
            UnknownDeclaration: `name` is not in the slice.
            NoStatement: it is, and carries no comparable statement.
            ValueError: `level` is not one of the five names.
        """

    def adjacent(
        self,
        name: str,
        level: Level = "instances",
        max_subs: int = 1,
        top: int = 50,
    ) -> list[tuple[str, str, list[tuple[str, str]]]]:
        """What sits just **outside** this declaration's equivalence class, and by which edit.

        Returns `[(name, adjacent_to, [(from, to), ...]), ...]`, closest first.

        The sharpening question a similarity ranking cannot express: a near miss and a
        distant cousin both come back as floats, but "this is your class with `<=` swapped
        for `>=`" is actionable. B7's V6 target scored PARTIAL for want of exactly this —
        the cluster assembled and nothing could surface the adjacent non-member.

        The class is computed at `level` and then excluded, so members never come back as
        their own neighbours.

        Raises:
            UnknownDeclaration: `name` is not in the slice.
        """

    def variants(
        self, name: str, max_subs: int = 1, top: int = 50
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        """Declarations that are this statement with at most `max_subs` constants swapped.

        Returns `[(name, [(from, to), ...]), ...]`, fewest edits first.

        Not a ranking and not a score. Two statements either share a **rigid skeleton** —
        the tree with every constant name blanked — or they do not, and when they do the
        answer is an edit you can act on: `Ne`<->`Eq`, `Injective`<->`Surjective`,
        `Monotone`<->`Antitone`, `<=`<->`<`.

        This is the half `generalize` discards: it reports the lgg's node counts and drops
        the substitutions. Measured on Mathlib, 11.2% of claims have a one-substitution
        partner, against 18.5x fewer under a permuted-constant control.

        The first call builds and caches a rigid-skeleton index over the corpus.

        Raises:
            UnknownDeclaration: `name` is not in the slice.
        """

    def requires(self, name: str) -> list[str]:
        """The typeclasses this declaration's instance binders require, in binder order.

        `Additive.ofMul_le` gives `["Preorder"]`. Repeats are kept: two binders over
        different carriers can name the same class, and collapsing them loses that.

        Answered from the loaded arena, so checking "does this other declaration need a
        weaker hypothesis than mine" costs nothing beyond the corpus already in memory.
        Read off the *unerased* statement — `instances` and above hole binder domains,
        which is exactly what this reports.

        Raises:
            UnknownDeclaration: `name` is not in the slice.
        """

    def closure_by(
        self, prefix: str, top: int = 20
    ) -> tuple[int, int, float, list[tuple[str, int]]]:
        """Closure coverage **restricted to one module prefix**.

        Returns `(known_heads, unknown_heads, coverage, worst)` over declarations whose
        module starts with `prefix`.

        Use this whenever the corpus is a mixture and you care about one part of it. A
        global figure is dominated by whatever the corpus is mostly made of: a merged
        corpus that is 97% Mathlib reports 99.59% while saying nothing about whether the 3%
        of physics statements are closed — and physics is the part being studied. The
        number is real; it is about the wrong population.
        """

    def closure(self, top: int = 20) -> tuple[int, int, float, list[tuple[str, int]]]:
        """Is this slice closed under the constants its statements mention?

        Returns `(known_heads, unknown_heads, coverage, worst)`. `coverage` is
        `known / (known + unknown)` over every application head in every statement; `worst`
        names the missing constants by how many statements mention them.

        **Check this before trusting any result at `instances` or above.** The erasure holes
        arguments in `InstImplicit` positions *of the head constant's signature*, so a head
        the slice does not contain holes nothing and that spine is normalized at
        `presentation` instead. No error, no empty result — a weaker normalization than the
        level name promises, which is the direction that keeps tests green.

        The usual cause is `atlas_extract --local`, which filters the extractor's *output*
        and not its import: the resulting Mathlib-only slice has no `Eq`, `Iff`, `LE.le` or
        `Monad` at all. Measured cost of that on the same corpus restricted the same way:
        34.5% of generalization candidates lost, 11.0% fabricated.
        """

    def motifs(
        self,
        source: Literal["shape", "subterm"] = "shape",
        min_family: int = 3,
        min_size: int = 6,
        top: int = 40,
    ) -> list[tuple[str, list[str], int, float]]:
        """The corpus's recurring sub-patterns: `(pattern, members, size, idf)`.

        Not a ranking and not a query — the inventory of shared structure the corpus
        contains. Ordered by `size * log(family)`, because a large family sharing a trivial
        motif is punctuation and a large motif shared by two declarations is a coincidence.

        Whole-statement grouping does not work corpus-wide: real theorems are structurally
        unique (mean family size 1.00 at every erasure level but `shape`). The shared
        *sub*-pattern is the unit that does, and the posting lists already index it.
        """

    def similar_brute(
        self, name: str, top: int = 10, level: Level = "carriers"
    ) -> list[tuple[str, float]]:
        """The same ranking with the index switched off: `(name, retention)`, best first.

        The differential reference for `similar` — a recall floor measured against a
        prefilter that shares the prefilter's blind spots is not a measurement. Ranked by
        retention alone, where `similar` ranks by score, so the two orders differ on
        purpose. Costs one anti-unification per declaration in the slice.
        """

    def logical_stats(self) -> LogicalStats:
        """What the proved-edge extraction saw over this slice."""

    def relations(self, theorem: str) -> list[Relation]:
        """The proved `Iff` and implication edges a theorem contributes.

        Empty for a theorem stating neither — which is most of them, and is an answer
        rather than a failure.
        """

    def busiest_heads(self, top: int = 20) -> list[tuple[str, int, int]]:
        """`(head, arity, edge count)`, densest first — where reformulations accumulate."""

    def relation_path(
        self, from_head: str, from_arity: int, to_head: str, to_arity: int
    ) -> list[Relation] | None:
        """A shortest chain of proved edges between two `(head, arity)` nodes.

        **Each step is proved; the chain is not.** Heads are carrier-blind, so a chain may
        compose a theorem about `BitVec` with one about `Nat` — measured, not
        hypothetical. Read `witness` on each step: differing namespaces mean it does not
        compose. `None` means no chain exists, which is complete rather than a budget
        running out.
        """

    def equivalent(self, name: str, level: Level = "instances") -> list[str]:
        """Declarations whose statements normalize to the same thing as this one, sorted.

        Reflexive, symmetric and transitive by construction — the relation *is* equality of
        `erase(stmt, level)` — and the class excludes `name` itself.

        Raises:
            UnknownDeclaration: `name` is not in the slice.
            NotAProposition: it is, and is not a claim.
            ValueError: `level` is not one of the five names, or is `shape` — at `shape`
                "equivalent" would mean "has the same skeleton", which `similar` answers.
        """

    def classes(
        self, level: Level = "instances", theorems_only: bool = True, top: int | None = None
    ) -> list[tuple[int, list[str]]]:
        """Every equivalence class of size > 1 at a level, largest first: `(size, members)`.

        Non-propositions are excluded outright and there is no knob for it: unrestricted,
        the largest class is the 1,859 declarations whose type is literally `Type`.
        `theorems_only` additionally drops Prop-valued *definitions* — dozens of typeclass
        definitions have identical statements and bury the reformulation families.
        """

    def dictionary_policies(
        self,
        left: str,
        right: str,
        per_decl: int = 1,
        theorems_only: bool = True,
    ) -> list[PolicyPoint]:
        """The coverage/coherence trade-off as a frontier, not one chosen answer.

        §6 C5 asks for several Pareto-optimal dictionaries where ambiguity is real and
        never for manufactured uniqueness.
        """

    def dictionary_coherence(
        self,
        left: str,
        right: str,
        per_decl: int = 1,
        theorems_only: bool = True,
        worst: int = 6,
    ) -> Coherence:
        """How far the dictionary between two theories is from being a map."""

    def dictionary_shuffle_control(
        self,
        left: str,
        right: str,
        per_decl: int = 1,
        theorems_only: bool = True,
    ) -> ShuffleControl:
        """Re-pair each left with a different right; genuine pairs must separate."""

    def dictionary(
        self,
        left: str,
        right: str,
        per_decl: int = 1,
        theorems_only: bool = True,
        anchor: Anchor = "root",
        normalize_arity: bool = False,
        score: Score = "retention",
        max_per_right: int | None = None,
        posting_work_budget: int | None = None,
        rank_by_retention: bool = False,
        per_decl_keep_displaced: bool = False,
        exclude_cited: bool = False,
    ) -> Dictionary:
        """The maximal partial functor between two theories.

        A theory is a module prefix — depth 2 under `Mathlib`, depth 1 elsewhere — so
        `"Mathlib.Order"` and `"Mathlib.Algebra"` are two theories and
        `Mathlib.Algebra.Group.Defs` is inside one. `per_decl` caps how many partners one
        declaration may contribute.

        `posting_work_budget` as on `similar`, and this is the surface the defect was
        measured on: at the shipped cutoff the ClassicalInfo ~ Entropy dictionary returns
        none of the four pre-registered correspondences — none is even a candidate — and
        with the keys admitted they are its top rows (findings §66).

        The three assembly knobs are §74's, all default-off:

        `rank_by_retention` orders candidates and rows by retention (with `similar`'s
        tie-breaks) instead of the full score. Cross-domain, every size-flavoured score
        factor rewards shared framework mass: the four validated classical<->quantum
        correspondences rank 437-1,150 of 3,029 under the scored key against 17-525 under
        retention alone. The re-ordering acts within the retrieved pool (the engine's
        `pool_width`, 64 by score), so a partner outside that pool is not recovered by
        this knob.

        `per_decl_keep_displaced` counts the `per_decl` cap per (left, skeleton) instead
        of per left: a structurally different claim is no longer evicted by a
        higher-ranked lookalike (315 rows were displaced that way, the von Neumann ~
        Gibbs entropy bridge among them), while same-skeleton family clones stay capped.

        `exclude_cited` drops rows whose two declarations cite each other — either
        direction, either lens, frontier's notion of a citation link. 14 of §74's graded
        top-40 were a framework paired with its own instantiations.
        """

    def transport(
        self, row_left: str, row_right: str, subject: str, level: Level = "carriers"
    ) -> Transported:
        """Apply the row `(row_left ~ row_right)` to `subject` and say where it lands.

        Raises:
            UnknownDeclaration: one of the three is not in the slice.
            NoMatch: `subject` does not match the row's left-hand pattern.
            ScopedRow: the row abstracts something under a binder.
        """

    def frontier(
        self,
        min_theory_size: int = 200,
        top: int = 20,
        theorems_only: bool = True,
        exclude: Sequence[str] = (),
    ) -> list[FrontierPair]:
        """Theory pairs that look alike and do not cite each other, best first.

        `exclude` drops namespaces by name. Without excluding infrastructure the ranking is
        led by metaprogramming siblings — `Aesop ~ ProofWidgets`, `Aesop ~ Qq` — which is a
        correct answer to the question as posed and not a mathematical agenda.
        """
