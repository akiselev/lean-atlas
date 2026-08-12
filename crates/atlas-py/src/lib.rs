//! Python bindings for the Atlas core — the `fa.Corpus` namespace of
//! `research/python-api.md` §2, and nothing else yet.
//!
//! # What this buys
//!
//! Every `atlas` CLI invocation re-reads and re-parses the whole slice before answering
//! anything: measured at ~6 s for a 131,062-declaration Mathlib slice. A harness that asks
//! eight questions pays that eight times. Here the slice is parsed once into a [`Corpus`]
//! handle and every later query runs against the graph already in memory — §1's "handles,
//! not copies", which is the entire reason this crate exists.
//!
//! # The `&mut Arena` problem, solved behind the handle
//!
//! `skel::erase::erase` and `skel::lgg::generalize` both take `&mut Arena`: erasure interns
//! the holed nodes it produces and anti-unification interns its variables, so a "query"
//! grows the arena. Python has no `&mut`, and a handle that demanded exclusive access would
//! push that problem onto every caller.
//!
//! So the arena, its signature table and its erasure cache live inside the handle behind a
//! `Mutex`, and the pyclass is `frozen` — Python sees only shared references, Rust does the
//! locking. Two consequences worth stating rather than discovering:
//!
//! * Skeleton queries from several Python threads *serialize* on that lock. Graph queries
//!   (`why`, `foundations`, `impact`, `walls`, `honesty`) touch no arena, take no lock and
//!   run genuinely in parallel once the GIL is released.
//! * The arena grows monotonically across queries. Erasure caches, so repeated levels are
//!   free; `generalize` interns fresh variables per call and is the one operation whose
//!   memory grows with use.
//!
//! The arena is built on the *first* skeleton query, not at load: parsing 131k statement
//! encodings is work a graph-only session should not pay for.
//!
//! # Three statement layers, not one
//!
//! B4's `SkeletonIndex` and B5's `EquivIndex` each parse the slice into an arena of their
//! own, so the handle carries three lazily-built layers behind three locks rather than one.
//! Merging them would mean either building the postings on the first `skeleton()` call or
//! building the `Prop` table on the first `similar()` call, and the builds are nowhere near
//! the same size: measured on the 131,062-row algebra slice, the plain statement arena
//! costs 4.3 s, the equivalence index 6.3 s, and the full skeleton index — every subterm of
//! every statement, at two levels, inverted — 13.7 s. (All three roughly halve or double
//! with what else the machine is doing; their ordering does not.) Each layer is built by
//! the first query that needs it and not before, so a session that asks graph questions
//! only builds none of them and one that asks for a skeleton is not charged for postings it
//! will never read. The price is paid in memory, and that part *is* deterministic: 723 MB
//! after a load, 1,095 MB with the skeleton index, 1,442 MB with all three.
//!
//! # `py.detach` is `py.allow_threads`
//!
//! Every operation that walks the graph or the arena runs inside `py.detach(…)`, which is
//! what PyO3 ≥0.26 calls the GIL release `python-api.md` §1 writes as `py.allow_threads`.
//! The old name is gone from the API, not merely deprecated.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};

use ::atlas::dict::{
    self, Coherence as CoreCoherence, LeftState, Policy, Row as CoreRow,
    ShuffleControl as CoreShuffle, TransportError, Transported as CoreTransported,
};
use ::atlas::equiv::{EquivIndex, Unknown};
use ::atlas::graph::{Decl as CoreDecl, Graph, Lens};
use ::atlas::logical::LogicalGraph;
use ::atlas::relation::{Evidence, Relation as CoreRelation, Warrant};
use ::atlas::skel::erase::{EraseCache, Level, Signatures, erase};
use ::atlas::skel::index::{
    Adjacent as CoreAdjacent, Anchor, IndexConfig, Neighbour as CoreNeighbour, SkeletonIndex,
    Sources, Variant as CoreVariant, VocabAdjacent as CoreVocabAdjacent,
};
use ::atlas::skel::lgg::{self, SimilarityScore};
use ::atlas::skel::term::{Arena, SymId, TermId};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyFileNotFoundError, PyOSError, PyValueError};
use pyo3::prelude::*;

create_exception!(
    atlas,
    AtlasError,
    PyException,
    "Base class for every error this module raises."
);
create_exception!(
    atlas,
    SliceError,
    AtlasError,
    "A slice could not be read as B1 JSONL. Carries the offending line number."
);
create_exception!(
    atlas,
    UnknownDeclaration,
    AtlasError,
    "No declaration by that name in this slice."
);
create_exception!(
    atlas,
    NoStatement,
    AtlasError,
    "The declaration is in the slice but carries no usable I3 statement encoding."
);
create_exception!(
    atlas,
    NotAProposition,
    AtlasError,
    "Equivalence was asked of something that is not a claim."
);
create_exception!(
    atlas,
    NoMatch,
    AtlasError,
    "The subject does not match the dictionary row's left-hand pattern."
);
create_exception!(
    atlas,
    ScopedRow,
    AtlasError,
    "The row has a variable standing for something under a binder, so it cannot be \
     instantiated independently of that binder."
);

/// The axioms an argument may rest on when the caller names none — Lean's own three, which
/// everything classical uses. Same default as `atlas honesty`.
const DEFAULT_WHITELIST: [&str; 3] = ["propext", "Classical.choice", "Quot.sound"];

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

/// One declaration, as B1's extractor emitted it.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct Decl {
    pub name: String,
    pub kind: String,
    pub module: String,
    /// The I3 canonical statement encoding, `None` when it could not be encoded.
    pub stmt: Option<String>,
    /// Why `stmt` is absent. Present exactly when `stmt` is — B1 keeps the row rather than
    /// dropping it, and the reason is what makes a `None` readable.
    pub stmt_error: Option<String>,
    /// What the *claim* cites, directly. The graph queries answer the transitive question;
    /// this is the row as extracted, and the difference matters: "does this theorem carry
    /// proof edges at all" is a question about B1's extractor that a transitive closure
    /// answers only expensively and only indirectly.
    pub uses_statement: Vec<String>,
    /// What the *argument* cites, directly.
    pub uses_proof: Vec<String>,
}

impl From<&CoreDecl> for Decl {
    fn from(d: &CoreDecl) -> Decl {
        Decl {
            name: d.name.clone(),
            kind: d.kind.clone(),
            module: d.module.clone(),
            stmt: d.stmt.clone(),
            stmt_error: d.stmt_error.clone(),
            uses_statement: d.uses_statement.clone(),
            uses_proof: d.uses_proof.clone(),
        }
    }
}

#[pymethods]
impl Decl {
    fn __repr__(&self) -> String {
        // The encoding runs to hundreds of bytes and is unreadable at a glance; its size
        // and the reason it is missing are the two things a caller acts on.
        let stmt = match (&self.stmt, &self.stmt_error) {
            (Some(s), _) => format!("stmt={} bytes", s.len()),
            (None, Some(why)) => format!("stmt=None ({why})"),
            (None, None) => "stmt=None".to_string(),
        };
        format!(
            "Decl(name={:?}, kind={:?}, module={:?}, {stmt}, uses_statement={}, uses_proof={})",
            self.name,
            self.kind,
            self.module,
            self.uses_statement.len(),
            self.uses_proof.len()
        )
    }
}

/// The least general generalization of two statements, with the numbers that rank it.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct Generalization {
    /// The skeleton, rendered in the I3 grammar: `_` is a hole, `?k` an anti-unification
    /// variable.
    pub skeleton: String,
    /// Non-hole, non-variable nodes — how much structure the two actually share.
    pub common: u32,
    pub vars: u32,
    /// Variables standing for something with loose de Bruijn indices. Such a row reads fine
    /// and is **not** transportable; reported, never hidden.
    pub scoped_vars: u32,
    /// `common / max(concrete(x), concrete(y))`, in `[0,1]`; exactly 1 when the inputs are equal.
    pub retention: f32,
}

#[pymethods]
impl Generalization {
    fn __repr__(&self) -> String {
        format!(
            "Generalization(common={}, vars={}, scoped_vars={}, retention={:.3}, skeleton={:?})",
            self.common,
            self.vars,
            self.scoped_vars,
            self.retention,
            truncate(&self.skeleton, 60)
        )
    }
}

/// One typed edge of the theory map (Engine 1 §5).
///
/// `warrant` is the field to branch on, and it is derived from `kind` rather than stored
/// beside it: `"proved"` means a Lean theorem says so and its name is in `evidence`,
/// `"structural"` means two canonical encodings compared equal, `"heuristic"` means a
/// ranking produced it. Engine 1's fifth non-goal is that these must not share a result
/// type, so a caller writing `if r.warrant == "proved"` is doing the thing the design
/// asks for, and a caller ignoring the field is making a claim the engine did not.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct Relation {
    pub left: String,
    pub right: String,
    /// One of the fifteen versioned kinds, e.g. `"ProvedIff"`.
    pub kind: String,
    /// `"both"`, `"left_to_right"` or `"right_to_left"`.
    pub direction: String,
    /// `"proved"`, `"structural"` or `"heuristic"`.
    pub warrant: String,
    /// Which sort of evidence, e.g. `"lean_theorem"`.
    pub evidence: String,
    /// The theorem's name when `evidence == "lean_theorem"`, else `None`. `None` exactly
    /// when the edge is not witnessed by a named declaration.
    pub witness: Option<String>,
    /// Which code produced this edge, so a stored map can be re-derived or distrusted.
    pub generator: String,
    pub schema_version: u32,
}

#[pymethods]
impl Relation {
    /// An explanation built from the stored evidence, never from free prose — Engine 1
    /// §10's response to "agent explanations exceed evidence".
    fn explain(&self) -> String {
        let arrow = match self.direction.as_str() {
            "left_to_right" => "->",
            "right_to_left" => "<-",
            _ => "~",
        };
        match &self.witness {
            Some(w) => format!(
                "{} {arrow} {} [{}, {}]: proved by `{w}`",
                self.left, self.right, self.kind, self.warrant
            ),
            None => format!(
                "{} {arrow} {} [{}, {}]: {}",
                self.left, self.right, self.kind, self.warrant, self.evidence
            ),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Relation({} {} {}, kind={:?}, warrant={:?}, witness={:?})",
            self.left,
            match self.direction.as_str() {
                "left_to_right" => "->",
                "right_to_left" => "<-",
                _ => "~",
            },
            self.right,
            self.kind,
            self.warrant,
            self.witness
        )
    }
}

/// What the proved-edge extraction actually saw. Reported rather than summarised: a
/// graph built from 4,330 `Iff`s and one built from twelve support different claims.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct LogicalStats {
    pub edges: usize,
    pub heads: usize,
    pub theorems_scanned: usize,
    pub iff_edges: usize,
    pub implication_edges: usize,
    /// Sides whose head is a bound variable, needing higher-order matching. Surfaced
    /// because "we did not look" and "there is nothing there" are different answers.
    pub flex_head_sides: usize,
    /// `Iff`s whose sides key to the same `(head, arity)`, so the edge would be a
    /// self-loop. The **largest** missing category — 184 of physlib's 516 `Iff`-headed
    /// theorems against 71 flex-headed — and until now it was not counted at all.
    pub same_head_sides: usize,
    /// Axioms scanned. An edge from an axiom is *asserted*, not proved.
    pub axioms_scanned: usize,
    /// Non-dependent `Pi`s rejected because a side does not head a proposition.
    pub non_prop_sides: usize,
    pub prop_heads: usize,
}

#[pymethods]
impl LogicalStats {
    fn __repr__(&self) -> String {
        format!(
            "LogicalStats(edges={}, heads={}, iff={}, implication={}, flex_head={}, \
             same_head={}, non_prop={})",
            self.edges,
            self.heads,
            self.iff_edges,
            self.implication_edges,
            self.flex_head_sides,
            self.same_head_sides,
            self.non_prop_sides
        )
    }
}

fn to_py_relation(r: &CoreRelation) -> Relation {
    Relation {
        left: r.left.clone(),
        right: r.right.clone(),
        kind: r.kind.as_str().to_string(),
        direction: r.direction.as_str().to_string(),
        warrant: match r.warrant() {
            Warrant::Proved => "proved",
            Warrant::Structural => "structural",
            Warrant::Asserted => "asserted",
            Warrant::Heuristic => "heuristic",
        }
        .to_string(),
        evidence: r.evidence.tag().to_string(),
        witness: match &r.evidence {
            Evidence::LeanTheorem { name } | Evidence::LeanAxiom { name } => Some(name.clone()),
            _ => None,
        },
        generator: r.generator.clone(),
        schema_version: r.schema_version,
    }
}

fn truncate(s: &str, n: usize) -> String {
    match s.char_indices().nth(n) {
        Some((i, _)) => format!("{}…", &s[..i]),
        None => s.to_string(),
    }
}

/// One neighbour from `similar`, with everything needed to audit the rank rather than
/// trust it.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct Neighbour {
    pub name: String,
    pub module: String,
    pub kind: String,
    /// `common / max(concrete(x), concrete(y))` of the anti-unification against the query.
    pub retention: f32,
    pub common: u32,
    pub vars: u32,
    /// Variables abstracting something locally bound. Positive means the row is a local
    /// coincidence rather than a transportable analogy.
    pub scoped_vars: u32,
    /// The rarest shared index key's IDF — how surprising the overlap is.
    pub rarity: f32,
    /// Which of the index's three sources found this candidate: `shape`, `subterm`,
    /// `shape-subterm`. A list rather than the CLI's `"shape+subterm"` string, because a
    /// caller asking "did the shape-subterm source find this" should not have to grep.
    pub sources: Vec<String>,
    /// The rendered skeleton. This *is* the candidate dictionary row.
    pub skeleton: String,
    /// `scoped_vars == 0`. B6 refuses to transport the rest.
    pub transportable: bool,
    /// Retention, weighted by rarity and a cross-theory bonus, penalised for scoped
    /// variables. The ranking key — not a probability.
    pub score: f32,
    /// The score factor by factor, so a caller can audit or ablate the rank rather than
    /// trust it. Engine 1 §6 C2's "complete feature vector".
    pub factors: ScoreFactors,
}

/// One operating point of the coverage/coherence trade-off.
#[pyclass(module = "atlas", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct PolicyPoint {
    /// `"unconstrained"`, `"many_to_one_2"`, …, `"injective"`.
    pub policy: String,
    pub rows: usize,
    pub lefts: usize,
    /// 0.0 exactly when the selection is a map.
    pub collision_rate: f32,
    pub mean_score: f32,
    /// Lefts whose partner cleared every floor and lost it to a better claim.
    pub unmatched: usize,
}

#[pymethods]
impl PolicyPoint {
    fn __repr__(&self) -> String {
        format!(
            "PolicyPoint({}, rows={}, collision={:.3}, mean={:.3}, unmatched={})",
            self.policy, self.rows, self.collision_rate, self.mean_score, self.unmatched
        )
    }
}

/// How far a dictionary is from the map it claims to be.
///
/// Rights are counted by *statement*, not by name: two names for one theorem would
/// otherwise let a left displaced onto an alias score as a coherence improvement.
#[pyclass(module = "atlas", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct Coherence {
    pub rows: usize,
    pub distinct_lefts: usize,
    pub distinct_rights: usize,
    /// Below `distinct_rights` exactly when the dictionary points at two names for one
    /// theorem.
    pub distinct_right_statements: usize,
    pub contested: usize,
    pub rows_in_collision: usize,
    /// `(right name, lefts claiming its statement)`, worst first.
    pub worst: Vec<(String, usize)>,
    /// `rows_in_collision / rows` — the fraction of the dictionary that is not a map.
    pub collision_rate: f32,
}

#[pymethods]
impl Coherence {
    fn __repr__(&self) -> String {
        format!(
            "Coherence(rows={}, lefts={}, right_statements={}, contested={}, \
             collision_rate={:.3})",
            self.rows,
            self.distinct_lefts,
            self.distinct_right_statements,
            self.contested,
            self.collision_rate
        )
    }
}

/// Design §9's control: are false shuffled mappings rejected earlier than genuine ones?
#[pyclass(module = "atlas", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct ShuffleControl {
    pub pairs: usize,
    pub genuine_mean: f32,
    pub shuffled_mean: f32,
    /// Shuffled pairs that would still clear the floors — the rate a coincidence survives.
    pub shuffled_admitted: usize,
    /// Fraction where the genuine pair outscores its shuffled twin. 1.0 perfect, 0.5 chance.
    pub separation: f32,
}

#[pymethods]
impl ShuffleControl {
    fn __repr__(&self) -> String {
        format!(
            "ShuffleControl(pairs={}, genuine={:.3}, shuffled={:.3}, separation={:.3}, \
             admitted={})",
            self.pairs,
            self.genuine_mean,
            self.shuffled_mean,
            self.separation,
            self.shuffled_admitted
        )
    }
}

/// The multiplicands of a `Neighbour.score`.
///
/// `Clone` is for embedding in `Neighbour`'s `get_all`, not for accepting one from
/// Python — nothing constructs these outside the engine, so the `FromPyObject` derive is
/// declined rather than inherited.
#[pyclass(module = "atlas", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct ScoreFactors {
    /// Shared concrete structure as a fraction of the larger side.
    pub retention: f32,
    /// How surprising the shared key is: `1 + w * min(rarity / ln N, 1)`.
    pub rarity_boost: f32,
    /// `1 + w` when the candidate lives under another module root, else 1.
    pub cross_boost: f32,
    /// `1 - w * scoped/vars`; below 1 exactly when the row is not transportable.
    pub scoped_penalty: f32,
    pub derivative_penalty: f32,
    /// The configured scorer's value — what actually multiplies into `total`.
    pub base: f32,
    pub total: f32,
}

#[pymethods]
impl ScoreFactors {
    fn __repr__(&self) -> String {
        format!(
            "ScoreFactors(retention={:.3}, rarity_boost={:.3}, cross_boost={:.3}, \
             scoped_penalty={:.3}, derivative_penalty={:.3}, total={:.3})",
            self.retention,
            self.rarity_boost,
            self.cross_boost,
            self.scoped_penalty,
            self.derivative_penalty,
            self.total
        )
    }
}

/// Which scorer produced a row — enough to re-derive it, or to refuse to trust it.
#[pyclass(module = "atlas", frozen, get_all, skip_from_py_object)]
#[derive(Clone)]
pub struct ScorerId {
    pub name: String,
    /// Bumped when the score's *shape* changes. A weight change moves `config_digest`.
    pub version: u32,
    /// Over every config field that can move a score.
    pub config_digest: String,
    /// Over the slice. The score is not a function of (pair, config): the rarity boost
    /// divides by `ln(corpus size)` and every IDF is a corpus property.
    pub corpus_digest: String,
}

#[pymethods]
impl ScorerId {
    fn __repr__(&self) -> String {
        format!(
            "ScorerId({}@{}, cfg={}…, corpus={}…)",
            self.name,
            self.version,
            &self.config_digest[..8],
            &self.corpus_digest[..8]
        )
    }
}

impl From<CoreNeighbour> for Neighbour {
    fn from(n: CoreNeighbour) -> Neighbour {
        Neighbour {
            name: n.name,
            module: n.module,
            kind: n.kind,
            retention: n.retention,
            common: n.common,
            vars: n.vars,
            scoped_vars: n.scoped_vars,
            rarity: n.rarity,
            sources: source_names(n.sources),
            skeleton: n.skeleton,
            transportable: n.transportable,
            score: n.score,
            factors: ScoreFactors {
                retention: n.factors.retention,
                rarity_boost: n.factors.rarity_boost,
                cross_boost: n.factors.cross_boost,
                scoped_penalty: n.factors.scoped_penalty,
                derivative_penalty: n.factors.derivative_penalty,
                base: n.factors.base,
                total: n.factors.total,
            },
        }
    }
}

#[pymethods]
impl Neighbour {
    fn __repr__(&self) -> String {
        format!(
            "Neighbour(name={:?}, score={:.3}, retention={:.2}, common={}, vars={}{}, \
             sources={:?}, module={:?})",
            self.name,
            self.score,
            self.retention,
            self.common,
            self.vars,
            if self.transportable { "" } else { ", scoped" },
            self.sources,
            self.module
        )
    }
}

fn source_names(s: Sources) -> Vec<String> {
    let mut v = Vec::new();
    for (bit, name) in [
        (Sources::SHAPE, "shape"),
        (Sources::SUBTERM, "subterm"),
        (Sources::SHAPE_SUBTERM, "shape-subterm"),
    ] {
        if s.has(bit) {
            v.push(name.to_string());
        }
    }
    v
}

/// One candidate dictionary row: two declarations that anti-unify, and how far.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct Row {
    pub left: String,
    pub right: String,
    pub skeleton: String,
    pub retention: f32,
    /// `both-proven`, `one-proven` or `neither-proven` — whether each half is a theorem.
    pub status: String,
    pub transportable: bool,
}

impl From<CoreRow> for Row {
    fn from(r: CoreRow) -> Row {
        Row {
            left: r.left,
            right: r.right,
            skeleton: r.skeleton,
            retention: r.retention,
            status: r.status.name().to_string(),
            transportable: r.transportable,
        }
    }
}

#[pymethods]
impl Row {
    fn __repr__(&self) -> String {
        format!(
            "Row({:?} ~ {:?}, retention={:.2}, status={:?}{})",
            self.left,
            self.right,
            self.retention,
            self.status,
            if self.transportable { "" } else { ", scoped" }
        )
    }
}

/// A dictionary between two theory fragments: the rows, and what has no partner.
#[pyclass(module = "atlas", frozen)]
pub struct Dictionary {
    #[pyo3(get)]
    pub left_theory: String,
    #[pyo3(get)]
    pub right_theory: String,
    /// Held as `Py<Row>` rather than rebuilt per access, so `d.rows[0] is d.rows[0]` and a
    /// caller can key a dict on a row it pulled out.
    rows: Vec<Py<Row>>,
    #[pyo3(get)]
    pub missing_left: Vec<String>,
    #[pyo3(get)]
    pub missing_right: Vec<String>,
}

#[pymethods]
impl Dictionary {
    /// The matched rows, best retention first.
    #[getter]
    fn rows(&self, py: Python<'_>) -> Vec<Py<Row>> {
        // `clone_ref`, not `clone`: pyo3 0.29 puts `Py: Clone` behind the `py-clone`
        // feature precisely because a refcount bump needs the GIL held, and a getter is the
        // one place it demonstrably is.
        self.rows.iter().map(|r| r.clone_ref(py)).collect()
    }

    fn __repr__(&self) -> String {
        format!(
            "Dictionary({:?} → {:?}, {} rows, unmatched {} left / {} right)",
            self.left_theory,
            self.right_theory,
            self.rows.len(),
            self.missing_left.len(),
            self.missing_right.len()
        )
    }
}

/// What transporting a statement along a dictionary row produced.
///
/// One class with a boolean discriminant rather than two classes: `if t.exists:` is what
/// every caller writes, and a two-state answer does not earn an `isinstance` dispatch or a
/// union type in the stubs. `name` is `None` exactly when `exists` is false — the two are
/// the same fact, and the invariant is asserted in `tests/smoke.py` rather than left to
/// documentation.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct Transported {
    /// True when the image is already a declaration in the slice: the dictionary row is
    /// verified rather than candidate.
    pub exists: bool,
    /// The declaration the image turned out to be, when it exists.
    pub name: Option<String>,
    /// The image statement, rendered in the I3 grammar. When it does not exist this is the
    /// directed target — falsify it before proving it, because refutation is cheap and
    /// locates the analogy's boundary.
    pub image: String,
}

impl From<CoreTransported> for Transported {
    fn from(t: CoreTransported) -> Transported {
        match t {
            CoreTransported::Exists { name, image } => Transported {
                exists: true,
                name: Some(name),
                image,
            },
            CoreTransported::Open { image } => Transported {
                exists: false,
                name: None,
                image,
            },
        }
    }
}

#[pymethods]
impl Transported {
    fn __repr__(&self) -> String {
        match &self.name {
            Some(n) => format!("Transported(exists=True, name={n:?})"),
            None => format!(
                "Transported(exists=False, image={:?})",
                truncate(&self.image, 60)
            ),
        }
    }
}

/// One theory pair's frontier reading: similar, and not talking to each other.
#[pyclass(module = "atlas", frozen, get_all)]
pub struct FrontierPair {
    pub left: String,
    pub right: String,
    /// Shape buckets both theories occupy, as a fraction of the smaller theory's buckets.
    pub similarity: f32,
    /// What two theories of these sizes would share by chance.
    pub expected_similarity: f32,
    /// `similarity - expected_similarity`.
    pub excess: f32,
    /// Declarations in one theory whose statement or proof cites the other.
    pub cross_citations: usize,
    pub left_size: usize,
    pub right_size: usize,
    /// `similarity / (1 + sqrt(cross_citations))`. High similarity, low traffic.
    pub score: f32,
}

#[pymethods]
impl FrontierPair {
    fn __repr__(&self) -> String {
        format!(
            "FrontierPair({:?} ~ {:?}, score={:.3}, similarity={:.2}, cross_citations={}, \
             sizes={}/{})",
            self.left,
            self.right,
            self.score,
            self.similarity,
            self.cross_citations,
            self.left_size,
            self.right_size
        )
    }
}

// ---------------------------------------------------------------------------
// The handle
// ---------------------------------------------------------------------------

/// A parsed slice. One load, many queries.
#[pyclass(module = "atlas", frozen)]
pub struct Corpus {
    path: String,
    /// The bytes the graph was built from, kept because B4's and B5's indexes each parse
    /// the slice themselves. Re-reading the file when one of them is first needed would be
    /// 146 MB cheaper and would make a handle's answers depend on whether the file changed
    /// underneath it — the three layers would then disagree about what the slice *is*,
    /// which is not a failure any caller could diagnose.
    source: String,
    graph: Graph,
    skel: Mutex<Option<Skel>>,
    /// Skeleton indexes, one per `(anchor, normalize_arity, work-budget admission)`
    /// combination.
    ///
    /// All three are *build*-time properties — postings, buckets and erasures all derive
    /// from the transformed term, and the work budget decides which posting keys exist at
    /// all — so none can be a per-query flag over one index. Cached rather than rebuilt
    /// because a caller comparing modes asks repeatedly and a Mathlib-sized build is 14 s.
    ///
    /// The budget dimension is keyed on `is_some()` only: `build` reads nothing but the
    /// presence (admission is keep-all under any `Some`), while the *value* bounds the
    /// walk per query, so two budget values share one index and differ only in the query
    /// config handed to `candidates`.
    indexes: [Mutex<Option<SkeletonIndex>>; 8],
    equiv: Mutex<Option<EquivIndex>>,
    /// The proved-edge layer (Engine 1 §6 C3). Built on top of `equiv`'s arena, so it is
    /// cheap once that exists — 0.2 s against the equivalence index's 6.3 s.
    logical: Mutex<Option<LogicalGraph>>,
}

/// The statement layer: built lazily, mutated by every erasure and every generalization.
struct Skel {
    arena: Arena,
    sigs: Signatures,
    cache: EraseCache,
    terms: HashMap<String, TermId>,
    /// Names whose `stmt` field the arena's parser rejected, with its own message. Kept
    /// rather than counted, so the query that asks about one of them can say why.
    unparsable: HashMap<String, String>,
}

impl Skel {
    fn build(graph: &Graph) -> Skel {
        let mut arena = Arena::new();
        let mut terms = HashMap::new();
        let mut unparsable = HashMap::new();
        let mut sig_rows: Vec<(SymId, TermId)> = Vec::new();
        for name in graph.names() {
            let Some(stmt) = graph.get(name).and_then(|d| d.stmt.as_deref()) else {
                continue;
            };
            match arena.parse(stmt) {
                Ok(t) => {
                    // A declaration's own statement *is* its argument interface, so the
                    // signature table needs no extraction beyond this loop.
                    let sym = arena.intern_sym(name);
                    sig_rows.push((sym, t));
                    terms.insert(name.clone(), t);
                }
                Err(e) => {
                    unparsable.insert(name.clone(), e.to_string());
                }
            }
        }
        let sigs = Signatures::from_rows(&arena, sig_rows.into_iter());
        Skel {
            arena,
            sigs,
            cache: EraseCache::new(),
            terms,
            unparsable,
        }
    }
}

/// Failures from the statement layer, raised after the GIL is reacquired.
enum SkelFail {
    NoStatement { name: String, reason: String },
    Unparsable { name: String, reason: String },
    NotInSlice(String),
    NotAProposition(String),
    NoMatch,
    Scoped,
    Build(String),
    Poisoned,
}

impl From<SkelFail> for PyErr {
    fn from(f: SkelFail) -> PyErr {
        match f {
            SkelFail::NoStatement { name, reason } => NoStatement::new_err(format!(
                "`{name}` has no encoded statement in this slice: {reason}"
            )),
            SkelFail::Unparsable { name, reason } => NoStatement::new_err(format!(
                "`{name}`'s statement encoding could not be parsed: {reason}"
            )),
            SkelFail::NotInSlice(name) => {
                UnknownDeclaration::new_err(format!("`{name}` is not in this slice"))
            }
            SkelFail::NotAProposition(name) => NotAProposition::new_err(format!(
                "`{name}` is not a proposition — equivalence is a relation between claims, \
                 and asking it of a definition would return every declaration whose type is \
                 literally `Type`"
            )),
            SkelFail::NoMatch => NoMatch::new_err(
                "the subject does not match this row's left-hand pattern, so the row says \
                 nothing about it — a failure of applicability, not of transport",
            ),
            SkelFail::Scoped => ScopedRow::new_err(
                "this row has a variable standing for something under a binder, so it cannot \
                 be instantiated independently of that binder",
            ),
            SkelFail::Build(reason) => SliceError::new_err(reason),
            SkelFail::Poisoned => AtlasError::new_err(
                "this corpus's statement arena was left inconsistent by an earlier panic; \
                 reload the slice",
            ),
        }
    }
}

/// Failures from reading a slice, raised after the GIL is reacquired.
enum LoadFail {
    Missing(String),
    Io(String),
    Row(String),
}

impl From<LoadFail> for PyErr {
    fn from(f: LoadFail) -> PyErr {
        match f {
            LoadFail::Missing(m) => PyFileNotFoundError::new_err(m),
            LoadFail::Io(m) => PyOSError::new_err(m),
            LoadFail::Row(m) => SliceError::new_err(m),
        }
    }
}

#[pymethods]
impl Corpus {
    /// Read and parse a B1 JSONL slice. The one expensive call in the API.
    #[staticmethod]
    fn load(py: Python<'_>, path: PathBuf) -> PyResult<Corpus> {
        let shown = path.display().to_string();
        let (source, graph) = py.detach(|| -> Result<(String, Graph), LoadFail> {
            let text = std::fs::read_to_string(&path).map_err(|e| match e.kind() {
                std::io::ErrorKind::NotFound => LoadFail::Missing(format!(
                    "no slice at {shown} — produce one with \
                     `cd lean && lake exe atlas_extract <Module> > {shown}`"
                )),
                _ => LoadFail::Io(format!("{shown}: {e}")),
            })?;
            let graph =
                Graph::from_jsonl(&text).map_err(|e| LoadFail::Row(format!("{shown}: {e}")))?;
            Ok((text, graph))
        })?;
        Ok(Corpus {
            path: path.display().to_string(),
            source,
            graph,
            skel: Mutex::new(None),
            indexes: std::array::from_fn(|_| Mutex::new(None)),
            equiv: Mutex::new(None),
            logical: Mutex::new(None),
        })
    }

    fn __len__(&self) -> usize {
        self.graph.len()
    }

    fn __repr__(&self) -> String {
        format!("<Corpus {} — {} declarations>", self.path, self.graph.len())
    }

    /// Every declaration name in the slice, sorted.
    fn names(&self, py: Python<'_>) -> Vec<String> {
        py.detach(|| self.graph.names().cloned().collect())
    }

    /// One declaration, or `None` if the slice does not have it.
    fn get(&self, name: &str) -> Option<Decl> {
        self.graph.get(name).map(Decl::from)
    }

    /// A shortest dependency chain from `source` down to `target`, or `None` if there is
    /// none under this lens.
    #[pyo3(signature = (source, target, lens = "both"))]
    fn why(
        &self,
        py: Python<'_>,
        source: &str,
        target: &str,
        lens: &str,
    ) -> PyResult<Option<Vec<String>>> {
        let lens = parse_lens(lens)?;
        self.known(source)?;
        Ok(py.detach(|| self.graph.why(source, target, lens)))
    }

    /// Everything `name` transitively rests on.
    #[pyo3(signature = (name, lens = "both"))]
    fn foundations(&self, py: Python<'_>, name: &str, lens: &str) -> PyResult<Vec<String>> {
        let lens = parse_lens(lens)?;
        self.known(name)?;
        Ok(py.detach(|| self.graph.foundations(name, lens).into_iter().collect()))
    }

    /// Everything that transitively rests on `name`.
    ///
    /// Unlike the other queries this does not require `name` to be in the slice: asking
    /// what rests on something outside it is a fair question, and the answer is the part of
    /// the slice that cites it.
    #[pyo3(signature = (name, lens = "both"))]
    fn impact(&self, py: Python<'_>, name: &str, lens: &str) -> PyResult<Vec<String>> {
        let lens = parse_lens(lens)?;
        Ok(py.detach(|| self.graph.impact(name, lens).into_iter().collect()))
    }

    /// Declarations ranked by how many others cite them *directly*, most-cited first.
    ///
    /// Direct, not transitive: ranking a whole slice transitively is one BFS per node.
    /// Declarations nothing cites are omitted rather than padding the list with zeros.
    #[pyo3(signature = (lens = "both", top = 20))]
    fn walls(&self, py: Python<'_>, lens: &str, top: usize) -> PyResult<Vec<(String, usize)>> {
        let lens = parse_lens(lens)?;
        Ok(py.detach(|| {
            self.graph
                .ranked_by_citations(lens)
                .into_iter()
                .take_while(|&(_, n)| n > 0)
                .take(top)
                .collect()
        }))
    }

    /// Declarations resting on `sorryAx` or on an axiom outside the whitelist, as
    /// `(who, why)` pairs.
    ///
    /// Transitive on purpose: a complete-looking theorem one step above a hole is not
    /// complete, and that is the case anti-cheat exists to catch. `whitelist=None` means
    /// Lean's own three axioms; an explicit list is used exactly as given, so `[]` allows
    /// nothing.
    #[pyo3(signature = (whitelist = None))]
    fn honesty(
        &self,
        py: Python<'_>,
        whitelist: Option<Vec<String>>,
    ) -> PyResult<Vec<(String, String)>> {
        let allowed: Vec<String> =
            whitelist.unwrap_or_else(|| DEFAULT_WHITELIST.iter().map(|s| s.to_string()).collect());
        Ok(py.detach(|| {
            let mut findings: Vec<(String, String)> = self
                .graph
                .impact("sorryAx", Lens::Proof)
                .into_iter()
                .map(|n| (n, "sorryAx".to_string()))
                .collect();
            for name in self.graph.names() {
                if self.graph.get(name).is_some_and(|d| d.kind == "axiom")
                    && !allowed.contains(name)
                    && name != "sorryAx"
                {
                    // The axiom itself, and *then* what rests on it. Reporting only the
                    // users made a corpus of unproved assertions pass clean: measured on
                    // B7's validation clusters, 113 of 114 declarations are `axiom` and
                    // every one is a graph leaf, so `impact` was empty and honesty
                    // reported **zero findings** on a corpus that is nothing but
                    // assertions. `atlas-validation.md` §2 mandates exactly that genre,
                    // so the scan was blind precisely where it is most needed — the
                    // "tool that says everything is fine" CLAUDE.md warns about.
                    findings.push((name.clone(), name.clone()));
                    for user in self.graph.impact(name, Lens::Proof) {
                        findings.push((user, name.clone()));
                    }
                }
            }
            findings.sort();
            findings.dedup();
            findings
        }))
    }

    /// The declaration's statement erased to `level`, rendered in the I3 grammar.
    ///
    /// Two statements are analogous at a level exactly when this string is the same for
    /// both — erasure interns, so equality of skeletons is equality of these renderings.
    #[pyo3(signature = (name, level = "carriers"))]
    fn skeleton(&self, py: Python<'_>, name: &str, level: &str) -> PyResult<String> {
        let level = parse_level(level)?;
        self.known(name)?;
        Ok(py.detach(|| -> Result<String, SkelFail> {
            let mut guard = self.statements()?;
            let s = guard.as_mut().expect("statements() builds it");
            let t = self.term_of(s, name)?;
            let e = erase(&mut s.arena, &s.sigs, &mut s.cache, t, level);
            Ok(s.arena.render(e))
        })?)
    }

    /// Which scorer this handle's `similar` rows come from, for the config a query would
    /// use. Two rows are comparable only when their `ScorerId`s match — the corpus digest
    /// is part of it because the rarity boost divides by `ln(corpus size)`.
    #[pyo3(signature = (level = "carriers", min_retention = 0.30, min_common = 6, theorems_only = false))]
    fn scorer_id(
        &self,
        py: Python<'_>,
        level: &str,
        min_retention: f32,
        min_common: u32,
        theorems_only: bool,
    ) -> PyResult<ScorerId> {
        let level = parse_level(level)?;
        py.detach(|| -> Result<ScorerId, SkelFail> {
            let cfg = IndexConfig {
                lgg_level: level,
                min_retention,
                min_common,
                theorems_only,
                ..IndexConfig::default()
            };
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            let s = idx.scorer_id(&cfg);
            Ok(ScorerId {
                name: s.name.to_string(),
                version: s.version,
                config_digest: s.config_digest,
                corpus_digest: s.corpus_digest,
            })
        })
        .map_err(Into::into)
    }

    /// Anti-unify two statements: the most specific term that matches both.
    ///
    /// Over the statements as encoded, not as erased — the concrete part is what the two
    /// theorems genuinely share and each variable is a place where they differ.
    #[pyo3(signature = (left, right, anchor = "root"))]
    fn generalize(
        &self,
        py: Python<'_>,
        left: &str,
        right: &str,
        anchor: &str,
    ) -> PyResult<Generalization> {
        // The same `anchor` `similar` takes, and for the same reason. Without it the two
        // APIs answer differently about one pair: the norm-shaped Euclidean-division
        // statements anti-unify to `common 0` through `generalize` while `similar` finds
        // them at rank 4, because one saw the conclusion and the other did not. That is a
        // trap for anyone using `generalize` to explain a `similar` result.
        let anchor = parse_anchor(anchor)?;
        self.known(left)?;
        self.known(right)?;
        Ok(py.detach(|| -> Result<Generalization, SkelFail> {
            let mut guard = self.statements()?;
            let s = guard.as_mut().expect("statements() builds it");
            let (x, y) = (self.term_of(s, left)?, self.term_of(s, right)?);
            let (x, y) = if anchor == Anchor::Conclusion {
                (s.arena.conclusion(x), s.arena.conclusion(y))
            } else {
                (x, y)
            };
            let g = lgg::generalize(&mut s.arena, x, y);
            Ok(Generalization {
                skeleton: s.arena.render(g.skeleton),
                common: g.common,
                vars: g.vars,
                scoped_vars: g.scoped_vars,
                retention: g.retention,
            })
        })?)
    }

    // -----------------------------------------------------------------------
    // B4 — the skeleton index
    // -----------------------------------------------------------------------

    /// Declarations whose statements anti-unify with this one, ranked.
    ///
    /// `level` is what the *reported* skeleton is computed at, and it is the knob that
    /// chooses the family: at `presentation` the neighbours share a carrier and differ in
    /// operator, at `carriers` they share an operator and differ in carrier. `min_common`
    /// and `min_retention` are the floors a candidate must clear to be reported at all —
    /// the defaults are the engine's, and lowering them buys recall by admitting rows whose
    /// shared structure is punctuation.
    // Six knobs and a name. They are the engine's own, and collapsing them into a config
    // object would make the common call site worse to read for the sake of a lint.
    //
    // `posting_work_budget` switches the prefilter to work-budget admission (findings
    // §66): every posting key is kept at build time and the query walks at most this many
    // postings, rarest key first, instead of dropping the common keys cross-theory
    // analogy rides on. `None` is the shipped cutoff, bit for bit.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (name, top = 10, level = "carriers", min_retention = 0.30, min_common = 6, theorems_only = false, anchor = "root", normalize_arity = false, score = "retention", posting_work_budget = None))]
    fn similar(
        &self,
        py: Python<'_>,
        name: &str,
        top: usize,
        level: &str,
        min_retention: f32,
        min_common: u32,
        theorems_only: bool,
        anchor: &str,
        normalize_arity: bool,
        score: &str,
        posting_work_budget: Option<usize>,
    ) -> PyResult<Vec<Neighbour>> {
        let level = parse_level(level)?;
        let anchor = parse_anchor(anchor)?;
        let score = parse_score(score)?;
        self.known(name)?;
        let found = py.detach(|| -> Result<Vec<CoreNeighbour>, SkelFail> {
            let cfg = IndexConfig {
                lgg_level: level,
                min_retention,
                min_common,
                theorems_only,
                anchor,
                normalize_arity,
                score,
                posting_work_budget,
                ..IndexConfig::default()
            };
            let mut guard = self.skeletons_at(anchor, normalize_arity, posting_work_budget)?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            idx.similar(name, top, &cfg)
                .map_err(|_| self.not_indexed(name))
        })?;
        Ok(found.into_iter().map(Neighbour::from).collect())
    }

    /// The corpus's recurring sub-patterns, read off the posting lists.
    ///
    /// Not a ranking and not a query: the inventory of shared structure the corpus
    /// actually contains. Grouping a *query's* candidates by shared pattern beats ranking
    /// them, and grouping whole statements corpus-wide does not work at all — real theorems
    /// are structurally unique (mean family size 1.00 at every erasure level but `shape`).
    /// The unit that works is the shared **sub**-pattern, which the postings already index.
    ///
    /// `source` is `"subterm"` (concrete subterms at `Presentation`) or `"shape"`
    /// (`Shape`-level subterms — the only level that holes constants, so the only one where
    /// a motif can cross carriers).
    #[pyo3(signature = (source = "shape", min_family = 3, min_size = 6, top = 40))]
    fn motifs(
        &self,
        py: Python<'_>,
        source: &str,
        min_family: usize,
        min_size: u32,
        top: usize,
    ) -> PyResult<Vec<(String, Vec<String>, u32, f32)>> {
        let found = py.detach(
            || -> Result<Vec<(String, Vec<String>, u32, f32)>, SkelFail> {
                let mut guard = self.skeletons()?;
                let idx = guard.as_mut().expect("skeletons() builds it");
                let mut m = idx.motifs(source, min_family, min_size);
                m.truncate(top);
                Ok(m)
            },
        )?;
        Ok(found)
    }

    /// Closure coverage **restricted to one module prefix**.
    ///
    /// Returns `(known_heads, unknown_heads, coverage, worst)` for declarations whose
    /// module starts with `prefix`.
    ///
    /// Call this whenever the corpus is a mixture and you care about one part of it. A
    /// global figure is dominated by whatever the corpus is mostly made of: a merged
    /// corpus that is 97% Mathlib reports 99.59% while saying **nothing** about whether the
    /// 3% of physics statements are closed — and physics is the part being studied. The
    /// number is real; it is about the wrong population.
    #[pyo3(signature = (prefix, top = 20))]
    fn closure_by(
        &self,
        py: Python<'_>,
        prefix: &str,
        top: usize,
    ) -> PyResult<(u64, u64, f64, Vec<(String, u32)>)> {
        let out = py.detach(
            || -> Result<(u64, u64, f64, Vec<(String, u32)>), SkelFail> {
                let mut guard = self.skeletons()?;
                let idx = guard.as_mut().expect("skeletons() builds it");
                let (known, unknown, worst) = idx.closure_by(prefix, top);
                let total = known + unknown;
                let coverage = if total == 0 {
                    1.0
                } else {
                    known as f64 / total as f64
                };
                Ok((known, unknown, coverage, worst))
            },
        )?;
        Ok(out)
    }

    /// Is this slice closed under the constants its statements mention?
    ///
    /// Returns `(known_heads, unknown_heads, coverage, worst)`. `coverage` is
    /// `known / (known + unknown)` over every application head in every statement, and
    /// `worst` names the missing constants by how many statements mention them.
    ///
    /// **Check this before trusting any result at `instances` or above.** The erasure holes
    /// arguments in `InstImplicit` positions *of the head constant's signature*, so a head
    /// the slice does not contain holes nothing and that spine is silently normalised at
    /// `presentation` instead. There is no error and no empty result — just a weaker
    /// normalisation than the level name promises, which is the direction that keeps tests
    /// green.
    ///
    /// In practice this goes wrong via `--local`, which filters the extractor's *output*
    /// rather than its import: a Mathlib-only slice has no `Eq`, `Iff`, `LE.le` or `Monad`
    /// and its coverage collapses. Measured cost on the same corpus restricted that way:
    /// 34.5% of generalization candidates lost and 11.0% fabricated.
    #[pyo3(signature = (top = 20))]
    fn closure(&self, py: Python<'_>, top: usize) -> PyResult<(u64, u64, f64, Vec<(String, u32)>)> {
        let out = py.detach(
            || -> Result<(u64, u64, f64, Vec<(String, u32)>), SkelFail> {
                let mut guard = self.skeletons()?;
                let idx = guard.as_mut().expect("skeletons() builds it");
                let (known, unknown, worst) = idx.closure(top);
                let total = known + unknown;
                let coverage = if total == 0 {
                    1.0
                } else {
                    known as f64 / total as f64
                };
                Ok((known, unknown, coverage, worst))
            },
        )?;
        Ok(out)
    }

    /// Declarations that are this statement with at most `max_subs` constants swapped,
    /// each with the substitution that reaches it.
    ///
    /// Returns `[(name, [(from, to), ...]), ...]`, fewest edits first. Not a ranking and
    /// not a score: two statements either share a rigid skeleton — the tree with every
    /// constant name blanked — or they do not, and when they do the answer is an edit a
    /// caller can act on. `Ne`<->`Eq`, `Injective`<->`Surjective`, `Monotone`<->`Antitone`,
    /// `<=`<->`<`.
    ///
    /// This is the part `generalize` throws away. It reports the lgg's node counts and
    /// discards the substitutions, which are the actionable half.
    ///
    /// The first call builds a rigid-skeleton index over the corpus and caches it.
    #[pyo3(signature = (name, max_subs = 1, top = 50))]
    fn variants(
        &self,
        py: Python<'_>,
        name: &str,
        max_subs: usize,
        top: usize,
    ) -> PyResult<Vec<(String, Vec<(String, String)>)>> {
        let out = py.detach(|| -> Result<Option<Vec<CoreVariant>>, SkelFail> {
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            Ok(idx.variants(name, max_subs, top))
        })?;
        out.map(|v| {
            v.into_iter()
                .map(|x| (x.name, x.substitutions))
                .collect::<Vec<_>>()
        })
        .ok_or_else(|| UnknownDeclaration::new_err(name.to_string()))
    }

    /// What sits just **outside** this declaration's equivalence class, and by which edit.
    ///
    /// Returns `[(name, adjacent_to, [(from, to), ...]), ...]`, closest first.
    ///
    /// The sharpening question a similarity ranking cannot express: a near miss and a
    /// distant cousin both come back as floats, but "this is your class with `<=` swapped
    /// for `>=`" is actionable. B7's V6 target scored PARTIAL for want of exactly this —
    /// the cluster assembled and nothing could surface the adjacent non-member.
    ///
    /// The class is computed at `level` (`equivalent`'s levels) and then excluded, so
    /// members never come back as their own neighbours.
    #[pyo3(signature = (name, level = "instances", max_subs = 1, top = 50))]
    fn adjacent(
        &self,
        py: Python<'_>,
        name: &str,
        level: &str,
        max_subs: usize,
        top: usize,
    ) -> PyResult<Vec<(String, String, Vec<(String, String)>)>> {
        let lvl = parse_level(level)?;
        // The class first — membership is the equivalence index's job — then the structural
        // neighbourhood around it, which is the skeleton index's.
        self.known(name)?;
        let mut members = py.detach(|| -> Result<Vec<String>, SkelFail> {
            let mut guard = self.equivalences()?;
            let idx = guard.as_mut().expect("equivalences() builds it");
            // Propagate rather than defaulting. `unwrap_or_default()` turned "this is not
            // a proposition" into "this class is empty", so the query answered about a
            // one-member class it had silently invented — and returned a declaration as a
            // non-member of its own class.
            idx.equivalent(name, lvl)
                .map_err(|_| SkelFail::NotAProposition(name.to_string()))
        })?;
        members.push(name.to_string());
        let out = py.detach(|| -> Result<Vec<CoreAdjacent>, SkelFail> {
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            Ok(idx.adjacent(&members, max_subs, top))
        })?;
        Ok(out
            .into_iter()
            .map(|a| (a.name, a.adjacent_to, a.substitutions))
            .collect())
    }

    /// What shares this declaration's equivalence class's **distinguished vocabulary**
    /// without being in the class.
    ///
    /// Returns `[(name, [shared constants], rarest_df), ...]`, most-shared first.
    ///
    /// The companion to `adjacent`. That one asks "same tree, which constants differ" and
    /// cannot cross a change of *shape*: an `Iff` and a bare inequality about the same
    /// object are not one substitution apart. This one asks "what else is about the same
    /// distinguished things", which is the relation B7's V6 target is after.
    ///
    /// "Distinguished" is document frequency: a constant counts when it occurs in at most
    /// `max_df_fraction` of the corpus, so sharing `Eq` is not evidence and sharing
    /// `Lambda` is. Applied as an admission test rather than a weight, so each row *names*
    /// what it shares instead of scoring it.
    #[pyo3(signature = (name, level = "instances", max_df_fraction = 0.05, top = 50))]
    fn vocabulary_adjacent(
        &self,
        py: Python<'_>,
        name: &str,
        level: &str,
        max_df_fraction: f32,
        top: usize,
    ) -> PyResult<Vec<(String, Vec<String>, u32)>> {
        let lvl = parse_level(level)?;
        self.known(name)?;
        let mut members = py.detach(|| -> Result<Vec<String>, SkelFail> {
            let mut guard = self.equivalences()?;
            let idx = guard.as_mut().expect("equivalences() builds it");
            // Propagate rather than defaulting. `unwrap_or_default()` turned "this is not
            // a proposition" into "this class is empty", so the query answered about a
            // one-member class it had silently invented — and returned a declaration as a
            // non-member of its own class.
            idx.equivalent(name, lvl)
                .map_err(|_| SkelFail::NotAProposition(name.to_string()))
        })?;
        members.push(name.to_string());
        let out = py.detach(|| -> Result<Vec<CoreVocabAdjacent>, SkelFail> {
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            Ok(idx.vocabulary_adjacent(&members, max_df_fraction, top))
        })?;
        Ok(out
            .into_iter()
            .map(|a| (a.name, a.shared, a.rarest_df))
            .collect())
    }

    /// The typeclasses a declaration's instance binders require, in binder order.
    ///
    /// `Additive.ofMul_le` returns `["Preorder"]`. Repeats are kept — two binders over
    /// different carriers can name the same class, and collapsing them would lose that.
    ///
    /// Answers from the loaded arena, so a caller checking "does this other declaration
    /// need a weaker hypothesis than mine" does not re-parse the slice. The novelty screen
    /// used to telescope all 470,435 statements in Python to build the same table — 35
    /// minutes for something needed on a handful of declarations per query, which is why
    /// the generalization pipeline ended up probing before screening.
    ///
    /// Read off the *unerased* statement: `instances` and above hole binder domains, which
    /// is precisely the information this returns.
    fn requires(&self, py: Python<'_>, name: &str) -> PyResult<Vec<String>> {
        let out = py.detach(|| -> Result<Option<Vec<String>>, SkelFail> {
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            Ok(idx.requires(name))
        })?;
        out.ok_or_else(|| UnknownDeclaration::new_err(name.to_string()))
    }

    /// The same ranking with the index switched off: every declaration, compared.
    ///
    /// The differential reference for `similar`, and the reason it is exposed rather than
    /// kept in a Rust test — a recall floor measured against a prefilter that shares the
    /// prefilter's blind spots is not a measurement. Costs one anti-unification per
    /// declaration in the slice, so seconds rather than milliseconds.
    #[pyo3(signature = (name, top = 10, level = "carriers"))]
    fn similar_brute(
        &self,
        py: Python<'_>,
        name: &str,
        top: usize,
        level: &str,
    ) -> PyResult<Vec<(String, f32)>> {
        let level = parse_level(level)?;
        self.known(name)?;
        Ok(py.detach(|| -> Result<Vec<(String, f32)>, SkelFail> {
            let cfg = IndexConfig {
                lgg_level: level,
                ..IndexConfig::default()
            };
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            idx.similar_brute(name, top, &cfg)
                .map_err(|_| self.not_indexed(name))
        })?)
    }

    // -----------------------------------------------------------------------
    // The proved layer — Engine 1 §6 C3 / B5's E2
    // -----------------------------------------------------------------------

    /// What the proved-edge extraction saw over this slice.
    fn logical_stats(&self, py: Python<'_>) -> PyResult<LogicalStats> {
        py.detach(|| -> Result<LogicalStats, SkelFail> {
            let guard = self.logical()?;
            let g = guard.as_ref().expect("logical() builds it");
            let s = g.stats();
            Ok(LogicalStats {
                edges: g.len(),
                heads: g.heads(),
                theorems_scanned: s.theorems_scanned,
                iff_edges: s.iff_edges,
                implication_edges: s.implication_edges,
                flex_head_sides: s.flex_head_sides,
                same_head_sides: s.same_head_sides,
                axioms_scanned: s.axioms_scanned,
                non_prop_sides: s.non_prop_sides,
                prop_heads: s.prop_heads,
            })
        })
        .map_err(Into::into)
    }

    /// The proved `Iff` and implication edges a theorem contributes.
    ///
    /// Empty for a theorem stating neither — which is most of them, and is an answer
    /// rather than a failure.
    fn relations(&self, py: Python<'_>, theorem: &str) -> PyResult<Vec<Relation>> {
        self.known(theorem)?;
        py.detach(|| -> Result<Vec<Relation>, SkelFail> {
            let guard = self.logical()?;
            let g = guard.as_ref().expect("logical() builds it");
            Ok(g.edges_of(theorem).iter().map(to_py_relation).collect())
        })
        .map_err(Into::into)
    }

    /// The heads carrying the most proved edges — where reformulations accumulate.
    #[pyo3(signature = (top = 20))]
    fn busiest_heads(&self, py: Python<'_>, top: usize) -> PyResult<Vec<(String, usize, usize)>> {
        py.detach(|| -> Result<Vec<(String, usize, usize)>, SkelFail> {
            let guard = self.logical()?;
            let g = guard.as_ref().expect("logical() builds it");
            Ok(g.busiest(top)
                .into_iter()
                .map(|((h, arity), n)| (h, arity, n))
                .collect())
        })
        .map_err(Into::into)
    }

    /// A shortest chain of proved edges between two `(head, arity)` nodes.
    ///
    /// **Each step is proved; the chain is not.** Heads are carrier-blind, so a chain may
    /// compose a theorem about `BitVec` with one about `Nat` — measured, not
    /// hypothetical. Read `witness` on each step: differing namespaces mean the chain
    /// does not compose, and establishing that it does is elaboration (Engine 1 C6).
    /// Returns `None` when no chain exists, which is a complete answer rather than a
    /// budget running out.
    fn relation_path(
        &self,
        py: Python<'_>,
        from_head: &str,
        from_arity: usize,
        to_head: &str,
        to_arity: usize,
    ) -> PyResult<Option<Vec<Relation>>> {
        py.detach(|| -> Result<Option<Vec<Relation>>, SkelFail> {
            let guard = self.logical()?;
            let g = guard.as_ref().expect("logical() builds it");
            Ok(g.path(
                &(from_head.to_string(), from_arity),
                &(to_head.to_string(), to_arity),
            )
            .map(|c| c.iter().map(to_py_relation).collect()))
        })
        .map_err(Into::into)
    }

    // -----------------------------------------------------------------------
    // B5 — the equivalence graph
    // -----------------------------------------------------------------------

    /// The declarations whose statements normalize to the same thing as this one.
    ///
    /// Reflexive, symmetric and transitive by construction — the relation *is* equality of
    /// `erase(stmt, level)` — and the class excludes `name` itself.
    ///
    /// Raises rather than answers for a non-proposition: without that guard the query
    /// returns every declaration whose type is literally `Type`, which is a type index
    /// wearing an equivalence relation's name.
    #[pyo3(signature = (name, level = "instances"))]
    fn equivalent(&self, py: Python<'_>, name: &str, level: &str) -> PyResult<Vec<String>> {
        let level = parse_level(level)?;
        // Coarser than `carriers` is `similar`'s question: at `shape` "equivalent" would
        // mean "same skeleton", which is an analogy rather than a reformulation.
        if level > Level::Carriers {
            return Err(PyValueError::new_err(
                "`equivalent` stops at `carriers` — at `shape` it would mean `has the same \
                 skeleton`, which is what `similar` answers",
            ));
        }
        self.known(name)?;
        Ok(py.detach(|| -> Result<Vec<String>, SkelFail> {
            let mut guard = self.equivalences()?;
            let idx = guard.as_mut().expect("equivalences() builds it");
            idx.equivalent(name, level).map_err(|e| match e {
                Unknown::NotProp(n) => SkelFail::NotAProposition(n),
                Unknown::NotInSlice(n) => self.not_indexed(&n),
            })
        })?)
    }

    /// Every equivalence class of size > 1 at a level, largest first, as `(size, members)`.
    ///
    /// `theorems_only` is the useful default and not a convenience: a *class definition*
    /// like `AddLeftMono` is a proposition by the conclusion test, the corpus has dozens
    /// with literally identical statements, and they bury the reformulation families under
    /// an alphabetised list of typeclass names. Non-propositions are excluded outright —
    /// there is no knob for that, because the largest class it produces is the 1,859
    /// declarations whose type is `Type`.
    #[pyo3(signature = (level = "instances", theorems_only = true, top = None))]
    fn classes(
        &self,
        py: Python<'_>,
        level: &str,
        theorems_only: bool,
        top: Option<usize>,
    ) -> PyResult<Vec<(usize, Vec<String>)>> {
        let level = parse_level(level)?;
        Ok(
            py.detach(|| -> Result<Vec<(usize, Vec<String>)>, SkelFail> {
                let mut guard = self.equivalences()?;
                let idx = guard.as_mut().expect("equivalences() builds it");
                let mut out = idx.classes(level, true, theorems_only);
                if let Some(n) = top {
                    out.truncate(n);
                }
                Ok(out)
            })?,
        )
    }

    // -----------------------------------------------------------------------
    // B6 — dictionaries, transport, the frontier
    // -----------------------------------------------------------------------

    /// The maximal partial functor between two theories: every skeleton-matched row, plus
    /// the declarations on each side with no partner.
    ///
    /// A theory is a module prefix — depth 2 under `Mathlib`, depth 1 elsewhere, so
    /// `Mathlib.Order` and `Mathlib.Algebra` are different theories and
    /// `Mathlib.Algebra.Group.Defs` is inside one of them. The missing-entry lists are the
    /// point of the exercise: a total dictionary would mean the analogy has nothing left to
    /// say.
    /// How far a dictionary is from the map it claims to be.
    ///
    /// Greedy per-declaration selection cannot produce a map — nothing looks across rows —
    /// so this is the measurement any repair has to be judged against, and it exists
    /// before the repair does.
    #[pyo3(signature = (left, right, per_decl = 1, theorems_only = true, worst = 6))]
    fn dictionary_coherence(
        &self,
        py: Python<'_>,
        left: &str,
        right: &str,
        per_decl: usize,
        theorems_only: bool,
        worst: usize,
    ) -> PyResult<Coherence> {
        py.detach(|| -> Result<Coherence, SkelFail> {
            let cfg = IndexConfig::default();
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            let d = dict::dictionary(
                idx,
                None,
                left,
                right,
                &cfg,
                &dict::DictOptions {
                    per_decl,
                    theorems_only,
                    ..dict::DictOptions::default()
                },
            );
            let c: CoreCoherence = dict::coherence(idx, &d, worst);
            Ok(Coherence {
                rows: c.rows,
                distinct_lefts: c.distinct_lefts,
                distinct_rights: c.distinct_rights,
                distinct_right_statements: c.distinct_right_statements,
                contested: c.contested,
                rows_in_collision: c.rows_in_collision,
                collision_rate: c.collision_rate(),
                worst: c.worst,
            })
        })
        .map_err(Into::into)
    }

    /// The coverage/coherence trade-off, as a frontier rather than one chosen answer.
    ///
    /// §6 C5 asks for several Pareto-optimal dictionaries where the ambiguity is real, and
    /// never for manufactured uniqueness. These are the operating points: tightening the
    /// cap raises per-row quality and costs coverage, and on the algebra slice a 1:1
    /// dictionary is capped by how many distinct partners the index finds at all.
    #[pyo3(signature = (left, right, per_decl = 1, theorems_only = true))]
    fn dictionary_policies(
        &self,
        py: Python<'_>,
        left: &str,
        right: &str,
        per_decl: usize,
        theorems_only: bool,
    ) -> PyResult<Vec<PolicyPoint>> {
        py.detach(|| -> Result<Vec<PolicyPoint>, SkelFail> {
            let cfg = IndexConfig::default();
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            let d = dict::dictionary(
                idx,
                None,
                left,
                right,
                &cfg,
                &dict::DictOptions {
                    per_decl,
                    theorems_only,
                    ..dict::DictOptions::default()
                },
            );
            let mut out = Vec::new();
            for (label, policy) in [
                ("unconstrained", Policy::Unconstrained),
                ("many_to_one_3", Policy::ManyToOne { cap: 3 }),
                ("many_to_one_2", Policy::ManyToOne { cap: 2 }),
                ("injective", Policy::Injective),
            ] {
                let (sel, states) = dict::select(&d, policy);
                let c = dict::coherence(idx, &sel, 0);
                let mean = if sel.rows.is_empty() {
                    0.0
                } else {
                    sel.rows.iter().map(|r| r.score).sum::<f32>() / sel.rows.len() as f32
                };
                out.push(PolicyPoint {
                    policy: label.to_string(),
                    rows: sel.rows.len(),
                    lefts: c.distinct_lefts,
                    collision_rate: c.collision_rate(),
                    mean_score: mean,
                    unmatched: states
                        .values()
                        .filter(|s| matches!(s, LeftState::Unmatched { .. }))
                        .count(),
                });
            }
            Ok(out)
        })
        .map_err(Into::into)
    }

    /// Design §9's control: re-pair each left with a different right and compare. If
    /// genuine pairs do not separate from shuffled ones, the floors are admitting
    /// coincidence and nothing computed from this dictionary is about analogy.
    ///
    /// The shuffle is a fixed stride, not a random permutation, so a failure is
    /// reproducible and the pairing can be re-derived by hand.
    #[pyo3(signature = (left, right, per_decl = 1, theorems_only = true))]
    fn dictionary_shuffle_control(
        &self,
        py: Python<'_>,
        left: &str,
        right: &str,
        per_decl: usize,
        theorems_only: bool,
    ) -> PyResult<ShuffleControl> {
        py.detach(|| -> Result<ShuffleControl, SkelFail> {
            let cfg = IndexConfig::default();
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            let d = dict::dictionary(
                idx,
                None,
                left,
                right,
                &cfg,
                &dict::DictOptions {
                    per_decl,
                    theorems_only,
                    ..dict::DictOptions::default()
                },
            );
            let s: CoreShuffle = dict::shuffle_control(idx, &d, &cfg);
            Ok(ShuffleControl {
                pairs: s.pairs,
                genuine_mean: s.genuine_mean,
                shuffled_mean: s.shuffled_mean,
                shuffled_admitted: s.shuffled_admitted,
                separation: s.separation,
            })
        })
        .map_err(Into::into)
    }

    // `posting_work_budget` for the same reason it is on `similar`, and this is the
    // surface where the defect was measured: at the shipped cutoff the ClassicalInfo ~
    // Entropy dictionary returns none of the four pre-registered correspondences — none
    // is even a candidate — and with the keys admitted they are its top rows (§66).
    // The three §74 knobs land here in the same change that adds them to the engine, per
    // CLAUDE.md §6: a query that exists only below the binding is one validation scripts
    // cannot afford to call. `rank_by_retention` orders candidates and rows by retention
    // (the four validated cross-domain correspondences rank 437–1,150 of 3,029 under the
    // scored key against 17–525 under retention); `per_decl_keep_displaced` moves the
    // per-left cap to (left, skeleton) so a structurally different claim is not evicted by
    // a higher-ranked lookalike (315 rows displaced, the entropy bridge among them); and
    // `exclude_cited` drops rows whose declarations cite each other, frontier's notion —
    // 14 of §74's graded top-40 were a framework paired with its own instantiations.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (left, right, per_decl = 1, theorems_only = true, anchor = "root", normalize_arity = false, score = "retention", max_per_right = None, posting_work_budget = None, rank_by_retention = false, per_decl_keep_displaced = false, exclude_cited = false))]
    fn dictionary(
        &self,
        py: Python<'_>,
        left: &str,
        right: &str,
        per_decl: usize,
        theorems_only: bool,
        anchor: &str,
        normalize_arity: bool,
        score: &str,
        max_per_right: Option<usize>,
        posting_work_budget: Option<usize>,
        rank_by_retention: bool,
        per_decl_keep_displaced: bool,
        exclude_cited: bool,
    ) -> PyResult<Dictionary> {
        // The anchor reaches `dictionary` for the same reason it reaches `similar` and
        // `generalize`. Without it the Z~FF dictionary returned **0 rows** while the pairs
        // it should have contained anti-unified at retention up to 1.00 conclusion-anchored
        // — the rows existed and the query could not see them.
        let anchor = parse_anchor(anchor)?;
        let score = parse_score(score)?;
        let core = py.detach(|| -> Result<dict::Dictionary, SkelFail> {
            let cfg = IndexConfig {
                anchor,
                normalize_arity,
                score,
                posting_work_budget,
                ..IndexConfig::default()
            };
            let mut guard = self.skeletons_at(anchor, normalize_arity, posting_work_budget)?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            Ok(dict::dictionary(
                idx,
                // Always passed: the graph is already resident, and the engine refuses
                // `exclude_cited` without one.
                Some(&self.graph),
                left,
                right,
                &cfg,
                &dict::DictOptions {
                    per_decl,
                    theorems_only,
                    max_per_right,
                    rank_by_retention,
                    per_decl_keep_displaced,
                    exclude_cited,
                    ..dict::DictOptions::default()
                },
            ))
        })?;
        let rows = core
            .rows
            .into_iter()
            .map(|r| Py::new(py, Row::from(r)))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(Dictionary {
            left_theory: core.left_theory,
            right_theory: core.right_theory,
            rows,
            missing_left: core.missing_left,
            missing_right: core.missing_right,
        })
    }

    /// Apply the row `(row_left ~ row_right)` to `subject` and report where the image lands.
    ///
    /// Both outcomes are signal: an image that already exists verifies the row, and one
    /// that does not is a directed target. Refusals are raised rather than folded into the
    /// result — `NoMatch` when the subject does not match the row's left pattern (the row
    /// says nothing about it), `ScopedRow` when a variable stands for something under a
    /// binder (it cannot be instantiated independently of that binder).
    #[pyo3(signature = (row_left, row_right, subject, level = "carriers"))]
    fn transport(
        &self,
        py: Python<'_>,
        row_left: &str,
        row_right: &str,
        subject: &str,
        level: &str,
    ) -> PyResult<Transported> {
        let level = parse_level(level)?;
        for n in [row_left, row_right, subject] {
            self.known(n)?;
        }
        // `exists` is `TermId` equality inside the engine, so it is only meaningful while
        // the arena's interner is intact. `Arena::seal` used to break that silently and
        // this call returned open targets that already existed; see `Arena::unseal` and
        // the level sweep in `atlas/examples/dictcheck.rs`.
        let core = py.detach(|| -> Result<CoreTransported, SkelFail> {
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            dict::transport(idx, row_left, row_right, subject, level).map_err(|e| match e {
                TransportError::NotInSlice(n) => self.not_indexed(&n),
                TransportError::NoMatch => SkelFail::NoMatch,
                TransportError::Scoped => SkelFail::Scoped,
            })
        })?;
        Ok(Transported::from(core))
    }

    /// Theory pairs that look alike and do not cite each other, best first.
    ///
    /// `exclude` drops namespaces by name, and `theorems_only` is on for the same reason it
    /// is on for `classes`: without it the top of this ranking is `Aesop ~ ProofWidgets` and
    /// `Aesop ~ Qq` — metaprogramming siblings that share shapes because they are all Lean
    /// code over syntax trees. A correct answer to the question as posed, and not a research
    /// agenda.
    #[pyo3(signature = (min_theory_size = 200, top = 20, theorems_only = true, exclude = Vec::new()))]
    fn frontier(
        &self,
        py: Python<'_>,
        min_theory_size: usize,
        top: usize,
        theorems_only: bool,
        exclude: Vec<String>,
    ) -> PyResult<Vec<FrontierPair>> {
        Ok(py.detach(|| -> Result<Vec<FrontierPair>, SkelFail> {
            let mut guard = self.skeletons()?;
            let idx = guard.as_mut().expect("skeletons() builds it");
            Ok(dict::frontier(
                idx,
                &self.graph,
                min_theory_size,
                top,
                theorems_only,
                &exclude,
            )
            .into_iter()
            .map(|f| FrontierPair {
                left: f.left,
                right: f.right,
                similarity: f.similarity,
                expected_similarity: f.expected_similarity,
                excess: f.excess,
                cross_citations: f.cross_citations,
                left_size: f.left_size,
                right_size: f.right_size,
                score: f.score,
            })
            .collect())
        })?)
    }
}

impl Corpus {
    fn known(&self, name: &str) -> PyResult<()> {
        if self.graph.get(name).is_some() {
            Ok(())
        } else {
            Err(UnknownDeclaration::new_err(format!(
                "`{name}` is not in this slice ({} declarations from {})",
                self.graph.len(),
                self.path
            )))
        }
    }

    fn statements(&self) -> Result<MutexGuard<'_, Option<Skel>>, SkelFail> {
        let mut guard = self.skel.lock().map_err(|_| SkelFail::Poisoned)?;
        if guard.is_none() {
            *guard = Some(Skel::build(&self.graph));
        }
        Ok(guard)
    }

    /// B4's index, built once for every level and every threshold.
    ///
    /// Caching one index across calls is only sound because `SkeletonIndex::build` reads
    /// none of `lgg_level`, `min_common` or `min_retention` — those are `similar`'s, applied
    /// per query. The build-time knobs (the posting-key size floors and the
    /// posting-list cutoff) are the engine's defaults and are not exposed: they change what
    /// the index *contains*, so a per-call value would silently mean a rebuild.
    fn skeletons(&self) -> Result<MutexGuard<'_, Option<SkeletonIndex>>, SkelFail> {
        self.skeletons_at(Anchor::Root, false, None)
    }

    fn skeletons_at(
        &self,
        anchor: Anchor,
        normalize_arity: bool,
        posting_work_budget: Option<usize>,
    ) -> Result<MutexGuard<'_, Option<SkeletonIndex>>, SkelFail> {
        // The budget slot is presence-keyed: admission is keep-all under any `Some`, so
        // every budget value shares the keep-all index and the caller's exact value
        // travels in the query config instead. See the field doc on `indexes`.
        let slot = (anchor as usize) * 4
            + usize::from(normalize_arity) * 2
            + usize::from(posting_work_budget.is_some());
        let mut guard = self.indexes[slot].lock().map_err(|_| SkelFail::Poisoned)?;
        if guard.is_none() {
            let cfg = IndexConfig {
                anchor,
                normalize_arity,
                posting_work_budget,
                ..IndexConfig::default()
            };
            let built = SkeletonIndex::build(&self.source, &cfg)
                .map_err(|e| SkelFail::Build(format!("{}: {e}", self.path)))?;
            *guard = Some(built);
        }
        Ok(guard)
    }

    /// B5's index. Separate from [`Corpus::skeletons`] because it carries what that one
    /// does not: which rows are propositions.
    fn equivalences(&self) -> Result<MutexGuard<'_, Option<EquivIndex>>, SkelFail> {
        let mut guard = self.equiv.lock().map_err(|_| SkelFail::Poisoned)?;
        if guard.is_none() {
            let built = EquivIndex::build(&self.source)
                .map_err(|e| SkelFail::Build(format!("{}: {e}", self.path)))?;
            *guard = Some(built);
        }
        Ok(guard)
    }

    /// The proved-edge layer. Built from [`Corpus::equivalences`] rather than from the
    /// source, so it inherits that arena instead of parsing the slice a fourth time —
    /// and so a session that asks for a relation pays the equivalence index's 6.3 s
    /// first, whether or not it asked for one.
    fn logical(&self) -> Result<MutexGuard<'_, Option<LogicalGraph>>, SkelFail> {
        let mut guard = self.logical.lock().map_err(|_| SkelFail::Poisoned)?;
        if guard.is_none() {
            let equiv = self.equivalences()?;
            let idx = equiv.as_ref().expect("equivalences() builds it");
            *guard = Some(LogicalGraph::build(idx));
        }
        Ok(guard)
    }

    /// Why a name the graph knows is absent from an index.
    ///
    /// The indexes skip rows whose statement is missing or unparseable; the graph keeps
    /// them. So an index miss on a name the graph has is never "not in this slice" — it is
    /// "in it, and carrying nothing to compare", and a caller does something different with
    /// each.
    fn not_indexed(&self, name: &str) -> SkelFail {
        let Some(decl) = self.graph.get(name) else {
            return SkelFail::NotInSlice(name.to_string());
        };
        match &decl.stmt_error {
            Some(reason) => SkelFail::NoStatement {
                name: name.to_string(),
                reason: reason.clone(),
            },
            None => SkelFail::Unparsable {
                name: name.to_string(),
                reason: "the arena's parser rejected the encoding".to_string(),
            },
        }
    }

    fn term_of(&self, s: &Skel, name: &str) -> Result<TermId, SkelFail> {
        if let Some(&t) = s.terms.get(name) {
            return Ok(t);
        }
        if let Some(reason) = s.unparsable.get(name) {
            return Err(SkelFail::Unparsable {
                name: name.to_string(),
                reason: reason.clone(),
            });
        }
        let reason = self
            .graph
            .get(name)
            .and_then(|d| d.stmt_error.clone())
            .unwrap_or_else(|| "the row carries no `stmt` field".to_string());
        Err(SkelFail::NoStatement {
            name: name.to_string(),
            reason,
        })
    }
}

fn parse_lens(s: &str) -> PyResult<Lens> {
    Ok(match s {
        "statement" => Lens::Statement,
        "proof" => Lens::Proof,
        "both" => Lens::Both,
        other => {
            return Err(PyValueError::new_err(format!(
                "unknown lens `{other}` — expected `statement` (what the claim rests on), \
                 `proof` (what the argument rests on) or `both`"
            )));
        }
    })
}

/// `"root"` or `"conclusion"`. Spelled out rather than a bool so a reader of a call site
/// can tell which question was asked.
/// The scorer's name. Spelled out rather than an index so a call site says which formula
/// it meant, and so adding one cannot silently renumber the others.
fn parse_score(s: &str) -> PyResult<SimilarityScore> {
    match s {
        "retention" => Ok(SimilarityScore::Retention),
        "min_normalised" | "min_normalized" => Ok(SimilarityScore::MinNormalised),
        "dice" => Ok(SimilarityScore::Dice),
        "jaccard" => Ok(SimilarityScore::Jaccard),
        "geometric_mean" => Ok(SimilarityScore::GeometricMean),
        "common" => Ok(SimilarityScore::Common),
        "info_weighted" => Ok(SimilarityScore::InfoWeighted),
        "info_dice" => Ok(SimilarityScore::InfoDice),
        other => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "score must be one of retention, min_normalised, dice, jaccard, \
             geometric_mean, common, info_weighted, info_dice; got `{other}`"
        ))),
    }
}

fn parse_anchor(s: &str) -> PyResult<Anchor> {
    match s {
        "root" => Ok(Anchor::Root),
        "conclusion" => Ok(Anchor::Conclusion),
        other => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "anchor must be `root` or `conclusion`, got `{other}`"
        ))),
    }
}

fn parse_level(s: &str) -> PyResult<Level> {
    Level::parse(s).ok_or_else(|| {
        PyValueError::new_err(format!(
            "unknown erasure level `{s}` — expected one of: {}",
            Level::ALL.map(Level::name).join(", ")
        ))
    })
}

#[pymodule]
fn atlas(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Corpus>()?;
    m.add_class::<Decl>()?;
    m.add_class::<Generalization>()?;
    m.add_class::<Relation>()?;
    m.add_class::<ScoreFactors>()?;
    m.add_class::<Coherence>()?;
    m.add_class::<PolicyPoint>()?;
    m.add_class::<ShuffleControl>()?;
    m.add_class::<ScorerId>()?;
    m.add_class::<LogicalStats>()?;
    m.add_class::<Neighbour>()?;
    m.add_class::<Row>()?;
    m.add_class::<Dictionary>()?;
    m.add_class::<Transported>()?;
    m.add_class::<FrontierPair>()?;
    m.add("AtlasError", m.py().get_type::<AtlasError>())?;
    m.add("SliceError", m.py().get_type::<SliceError>())?;
    m.add(
        "UnknownDeclaration",
        m.py().get_type::<UnknownDeclaration>(),
    )?;
    m.add("NoStatement", m.py().get_type::<NoStatement>())?;
    m.add("NotAProposition", m.py().get_type::<NotAProposition>())?;
    m.add("NoMatch", m.py().get_type::<NoMatch>())?;
    m.add("ScopedRow", m.py().get_type::<ScopedRow>())?;
    Ok(())
}
