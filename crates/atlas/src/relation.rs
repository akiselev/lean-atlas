//! The typed relation algebra (Engine 1 §5, milestone M2).
//!
//! Every edge the Atlas reports carries *what kind of thing it is* and *what makes it
//! true*, and those are separate fields because they answer separate questions. The
//! engine doc's fifth non-goal is the whole reason this module exists:
//!
//! > Do not hide uncertain or heuristic edges in the same result type as proved edges.
//!
//! An `Iff` theorem and an anti-unification near-miss are both "a relation between two
//! declarations", and a caller that cannot tell them apart will eventually publish the
//! second as if it were the first. So the boundary is enforced at construction:
//! [`Relation::new`] rejects a kind/evidence pair that does not match, and there is no
//! way to build a `ProvedIff` without naming the theorem that proves it.
//!
//! # Versioning
//!
//! `kind` is a closed enum and the set is versioned by [`SCHEMA_VERSION`]. A stored
//! relation whose schema version differs from the running engine's is not silently
//! reinterpreted — the campaign that stored it was answering a question this build may
//! define differently.

use std::collections::BTreeMap;
use std::fmt;

/// Bumped when a variant is added to [`RelationKind`], when an [`Evidence`] variant
/// changes shape, or when a kind's *meaning* changes. Stored relations carry it.
pub const SCHEMA_VERSION: u32 = 1;

/// What sort of relationship this is. Closed and versioned (Engine 1 §5).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RelationKind {
    ExactStatement,
    PresentationEqual,
    DefinitionalRewrite,
    ProvedIff,
    ProvedImplies,
    TypeEquiv,
    SharedInstance,
    SharedHomeCandidate,
    SharedHomeConfirmed,
    StructuralAnalogy,
    ProofShapeAnalogy,
    DictionaryRowCandidate,
    DictionaryRowConfirmed,
    TransportRefuted,
    TransportProved,
    /// An `Iff` **stated as an axiom** rather than proved. The Formal-Conjectures genre:
    /// `atlas-validation.md` §2 mandates statement-level corpora with no proofs, so an
    /// edge from one is asserted by its author and carries exactly that authority.
    AssertedIff,
    /// An implication stated as an axiom. See [`RelationKind::AssertedIff`].
    AssertedImplies,
}

/// The grades of warrant an edge can have. This is the distinction the engine doc forbids
/// collapsing, so it is derived from the kind rather than stored alongside it — a caller
/// cannot construct a relation that lies about its own grade.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Warrant {
    /// A Lean proof exists and is named. The strongest grade the Atlas can report.
    Proved,
    /// A decidable property of the canonical encodings — no proof, but no judgement
    /// either. Reproducible exactly from the corpus and the normalization level.
    Structural,
    /// Stated as an axiom by the corpus author. Exactly as true as they say it is.
    ///
    /// Ranked below `Structural` deliberately: a canonical-encoding equality is machine
    /// checkable, whereas this is a human stipulation. It is *not* [`Warrant::Heuristic`]
    /// either — nothing was guessed, and a statement-level corpus's whole content lives
    /// at this grade, so collapsing it into "a ranking produced this" would make the
    /// Formal-Conjectures genre unreadable.
    Asserted,
    /// A ranking or a search result. Real information, and not a claim about
    /// mathematics.
    Heuristic,
}

impl RelationKind {
    /// The grade of warrant this kind carries. Total and const-evaluable: adding a
    /// variant without classifying it will not compile.
    pub const fn warrant(self) -> Warrant {
        use RelationKind::*;
        match self {
            ProvedIff
            | ProvedImplies
            | TransportProved
            | TransportRefuted
            | SharedHomeConfirmed
            | DictionaryRowConfirmed => Warrant::Proved,
            ExactStatement | PresentationEqual | DefinitionalRewrite | TypeEquiv
            | SharedInstance => Warrant::Structural,
            SharedHomeCandidate
            | StructuralAnalogy
            | ProofShapeAnalogy
            | DictionaryRowCandidate => Warrant::Heuristic,
            AssertedIff | AssertedImplies => Warrant::Asserted,
        }
    }

    /// Whether the relation reads the same in both directions. A `ProvedImplies` does
    /// not, and rendering one as if it did is how an implication becomes an equivalence
    /// in someone's notes.
    pub const fn is_symmetric(self) -> bool {
        use RelationKind::*;
        matches!(
            self,
            ExactStatement
                | PresentationEqual
                | ProvedIff
                | AssertedIff
                | TypeEquiv
                | SharedInstance
                | SharedHomeCandidate
                | SharedHomeConfirmed
                | StructuralAnalogy
                | ProofShapeAnalogy
        )
    }

    pub const fn as_str(self) -> &'static str {
        use RelationKind::*;
        match self {
            ExactStatement => "ExactStatement",
            PresentationEqual => "PresentationEqual",
            DefinitionalRewrite => "DefinitionalRewrite",
            ProvedIff => "ProvedIff",
            ProvedImplies => "ProvedImplies",
            AssertedIff => "AssertedIff",
            AssertedImplies => "AssertedImplies",
            TypeEquiv => "TypeEquiv",
            SharedInstance => "SharedInstance",
            SharedHomeCandidate => "SharedHomeCandidate",
            SharedHomeConfirmed => "SharedHomeConfirmed",
            StructuralAnalogy => "StructuralAnalogy",
            ProofShapeAnalogy => "ProofShapeAnalogy",
            DictionaryRowCandidate => "DictionaryRowCandidate",
            DictionaryRowConfirmed => "DictionaryRowConfirmed",
            TransportRefuted => "TransportRefuted",
            TransportProved => "TransportProved",
        }
    }

    pub fn parse(s: &str) -> Option<RelationKind> {
        use RelationKind::*;
        Some(match s {
            "ExactStatement" => ExactStatement,
            "PresentationEqual" => PresentationEqual,
            "DefinitionalRewrite" => DefinitionalRewrite,
            "ProvedIff" => ProvedIff,
            "ProvedImplies" => ProvedImplies,
            "TypeEquiv" => TypeEquiv,
            "SharedInstance" => SharedInstance,
            "SharedHomeCandidate" => SharedHomeCandidate,
            "SharedHomeConfirmed" => SharedHomeConfirmed,
            "StructuralAnalogy" => StructuralAnalogy,
            "ProofShapeAnalogy" => ProofShapeAnalogy,
            "DictionaryRowCandidate" => DictionaryRowCandidate,
            "DictionaryRowConfirmed" => DictionaryRowConfirmed,
            "TransportRefuted" => TransportRefuted,
            "TransportProved" => TransportProved,
            _ => return None,
        })
    }

    /// Every kind, for exhaustiveness tests and for the CLI's help text.
    pub const ALL: [RelationKind; 15] = {
        use RelationKind::*;
        [
            ExactStatement,
            PresentationEqual,
            DefinitionalRewrite,
            ProvedIff,
            ProvedImplies,
            TypeEquiv,
            SharedInstance,
            SharedHomeCandidate,
            SharedHomeConfirmed,
            StructuralAnalogy,
            ProofShapeAnalogy,
            DictionaryRowCandidate,
            DictionaryRowConfirmed,
            TransportRefuted,
            TransportProved,
        ]
    };
}

impl fmt::Display for RelationKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Which way the relation runs. Symmetric kinds must use [`Direction::Both`]; the
/// constructor enforces it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Direction {
    Both,
    LeftToRight,
    RightToLeft,
}

impl Direction {
    pub const fn as_str(self) -> &'static str {
        match self {
            Direction::Both => "both",
            Direction::LeftToRight => "left_to_right",
            Direction::RightToLeft => "right_to_left",
        }
    }
}

/// What makes the edge true. A sum type rather than prose (Engine 1 §5): an explanation
/// is generated *from* this, so an agent cannot narrate past what was actually found.
#[derive(Clone, Debug, PartialEq)]
pub enum Evidence {
    /// A Lean declaration whose statement *is* the edge. The only evidence that earns
    /// [`Warrant::Proved`].
    LeanTheorem { name: String },
    /// Two canonical encodings compared equal at this normalization level.
    CanonicalEq { level: &'static str },
    /// An anti-unification: the shared skeleton, and how much of each side survived it.
    AntiUnification {
        skeleton: String,
        common: u32,
        retention: f32,
    },
    /// A path through the citation graph.
    DependencyPath { path: Vec<String> },
    /// A ranking produced this edge; the named features are the whole score.
    RankingFeatures { features: BTreeMap<String, f32> },
    /// A falsifying assignment. Carries [`Warrant::Proved`] for `TransportRefuted`
    /// because a counterexample settles the question.
    Counterexample { witness: String },
    /// A Lean **axiom** whose statement is the edge. Earns [`Warrant::Asserted`]: the
    /// declaration exists and says this, and nothing has proved it.
    LeanAxiom { name: String },
    /// The engine could not decide, and says why rather than dropping the edge
    /// (Engine 1 §6 C3).
    Unsupported { reason: UnsupportedReason },
}

/// Why an edge could not be established. Kept explicit so that "we did not look" is
/// never reported as "there is nothing there".
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnsupportedReason {
    /// The pattern's head is a bound variable, so matching it needs higher-order
    /// unification the engine does not do.
    FlexHead,
    /// The search budget ran out before the question was settled.
    BudgetExhausted,
    /// The statement is not a proposition, so the relation is a category error.
    NotAProposition,
}

impl UnsupportedReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            UnsupportedReason::FlexHead => "flex_head",
            UnsupportedReason::BudgetExhausted => "budget_exhausted",
            UnsupportedReason::NotAProposition => "not_a_proposition",
        }
    }
}

impl Evidence {
    /// The strongest warrant this evidence can support. Compared against the kind's own
    /// warrant at construction.
    pub fn supports(&self) -> Warrant {
        match self {
            Evidence::LeanTheorem { .. } | Evidence::Counterexample { .. } => Warrant::Proved,
            Evidence::CanonicalEq { .. } | Evidence::DependencyPath { .. } => Warrant::Structural,
            Evidence::LeanAxiom { .. } => Warrant::Asserted,
            Evidence::AntiUnification { .. }
            | Evidence::RankingFeatures { .. }
            | Evidence::Unsupported { .. } => Warrant::Heuristic,
        }
    }

    pub fn tag(&self) -> &'static str {
        match self {
            Evidence::LeanTheorem { .. } => "lean_theorem",
            Evidence::LeanAxiom { .. } => "lean_axiom",
            Evidence::CanonicalEq { .. } => "canonical_eq",
            Evidence::AntiUnification { .. } => "anti_unification",
            Evidence::DependencyPath { .. } => "dependency_path",
            Evidence::RankingFeatures { .. } => "ranking_features",
            Evidence::Counterexample { .. } => "counterexample",
            Evidence::Unsupported { .. } => "unsupported",
        }
    }
}

/// A kind and its evidence disagreed. Returned rather than panicking, because the
/// mismatch is a bug in whatever *generated* the edge and its identity is the useful
/// part of the report.
#[derive(Clone, Debug, PartialEq)]
pub enum RelationError {
    /// e.g. a `ProvedIff` offered an anti-unification as its evidence.
    InsufficientEvidence {
        kind: RelationKind,
        needs: Warrant,
        evidence: &'static str,
        supports: Warrant,
    },
    /// A symmetric kind was given a direction, or an asymmetric one was not.
    DirectionMismatch {
        kind: RelationKind,
        direction: Direction,
    },
}

impl fmt::Display for RelationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RelationError::InsufficientEvidence {
                kind,
                needs,
                evidence,
                supports,
            } => write!(
                f,
                "`{kind}` is a {needs:?} relation but its evidence is `{evidence}`, which \
                 only supports {supports:?} — reporting it would put a heuristic edge in \
                 the same result type as a proved one"
            ),
            RelationError::DirectionMismatch { kind, direction } => write!(
                f,
                "`{kind}` is {} but was given direction `{}`",
                if kind.is_symmetric() {
                    "symmetric"
                } else {
                    "directional"
                },
                direction.as_str()
            ),
        }
    }
}

impl std::error::Error for RelationError {}

/// One edge of the theory map.
#[derive(Clone, Debug, PartialEq)]
pub struct Relation {
    pub left: String,
    pub right: String,
    pub kind: RelationKind,
    pub direction: Direction,
    pub evidence: Evidence,
    /// The normalization level the edge was found at, where that is meaningful.
    pub level: Option<String>,
    /// Which code produced this, so a stored map can be re-derived or distrusted.
    pub generator: String,
    pub schema_version: u32,
}

impl Relation {
    /// Build an edge, checking that its evidence can carry its kind.
    ///
    /// This is the enforcement point for the engine doc's fifth non-goal. There is no
    /// other constructor, and the fields that would let a caller lie — `kind` against
    /// `evidence`, `direction` against symmetry — are validated here rather than
    /// documented as a convention.
    pub fn new(
        left: impl Into<String>,
        right: impl Into<String>,
        kind: RelationKind,
        direction: Direction,
        evidence: Evidence,
        generator: impl Into<String>,
    ) -> Result<Relation, RelationError> {
        let (needs, supports) = (kind.warrant(), evidence.supports());
        // `Warrant` orders strongest-first, so "the evidence is weaker than the kind
        // claims" is a `>` on the enum's own ordering.
        if supports > needs {
            return Err(RelationError::InsufficientEvidence {
                kind,
                needs,
                evidence: evidence.tag(),
                supports,
            });
        }
        if kind.is_symmetric() != (direction == Direction::Both) {
            return Err(RelationError::DirectionMismatch { kind, direction });
        }
        Ok(Relation {
            left: left.into(),
            right: right.into(),
            kind,
            direction,
            evidence,
            level: None,
            generator: generator.into(),
            schema_version: SCHEMA_VERSION,
        })
    }

    pub fn at_level(mut self, level: impl Into<String>) -> Relation {
        self.level = Some(level.into());
        self
    }

    pub fn warrant(&self) -> Warrant {
        self.kind.warrant()
    }

    /// An explanation built from the stored evidence, never from free prose — Engine 1
    /// §10's response to "agent explanations exceed evidence".
    pub fn explain(&self) -> String {
        let arrow = match self.direction {
            Direction::Both => "~",
            Direction::LeftToRight => "->",
            Direction::RightToLeft => "<-",
        };
        let because = match &self.evidence {
            Evidence::LeanTheorem { name } => format!("proved by `{name}`"),
            Evidence::LeanAxiom { name } => format!(
                "asserted by the axiom `{name}` — stated without proof, so this edge \
                 carries its author's authority and no more"
            ),
            Evidence::CanonicalEq { level } => {
                format!("identical canonical statements at level `{level}`")
            }
            Evidence::AntiUnification {
                common, retention, ..
            } => format!(
                "a shared skeleton of {common} nodes, retaining {:.0}% of the larger \
                 statement's concrete structure — a resemblance, not a proof",
                retention * 100.0
            ),
            Evidence::DependencyPath { path } => {
                format!("a citation path of {} steps", path.len().saturating_sub(1))
            }
            Evidence::RankingFeatures { features } => {
                let mut fs: Vec<_> = features.iter().collect();
                fs.sort_by(|a, b| b.1.total_cmp(a.1));
                let top: Vec<String> = fs
                    .iter()
                    .take(3)
                    .map(|(k, v)| format!("{k}={v:.3}"))
                    .collect();
                format!(
                    "ranked by {} — a search result, not a claim",
                    top.join(", ")
                )
            }
            Evidence::Counterexample { witness } => format!("refuted by {witness}"),
            Evidence::Unsupported { reason } => format!(
                "undecided ({}) — the engine did not settle this, which is not the same \
                 as there being nothing here",
                reason.as_str()
            ),
        };
        format!(
            "{} {arrow} {} [{}, {:?}]: {because}",
            self.left,
            self.right,
            self.kind,
            self.warrant()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_proved_kind_cannot_be_built_from_a_resemblance() {
        // The engine doc's fifth non-goal, as a compile-and-run guarantee rather than a
        // convention: this is the exact mistake that turns a ranking into a claim.
        let e = Relation::new(
            "le_trans",
            "dvd_trans",
            RelationKind::ProvedIff,
            Direction::Both,
            Evidence::AntiUnification {
                skeleton: "a(?0,?1)".into(),
                common: 6,
                retention: 0.42,
            },
            "test",
        )
        .unwrap_err();
        assert!(matches!(
            e,
            RelationError::InsufficientEvidence {
                kind: RelationKind::ProvedIff,
                needs: Warrant::Proved,
                supports: Warrant::Heuristic,
                ..
            }
        ));
    }

    #[test]
    fn a_heuristic_kind_accepts_stronger_evidence_than_it_needs() {
        // The check is one-directional on purpose. A structural analogy that happens to
        // be backed by a theorem is still a structural analogy, and refusing it would
        // force callers to guess a kind from the evidence they have.
        let r = Relation::new(
            "a",
            "b",
            RelationKind::StructuralAnalogy,
            Direction::Both,
            Evidence::LeanTheorem {
                name: "some_thm".into(),
            },
            "test",
        )
        .expect("stronger evidence is not an error");
        assert_eq!(r.warrant(), Warrant::Heuristic);
    }

    #[test]
    fn an_implication_may_not_be_recorded_as_symmetric() {
        let e = Relation::new(
            "p",
            "q",
            RelationKind::ProvedImplies,
            Direction::Both,
            Evidence::LeanTheorem { name: "t".into() },
            "test",
        )
        .unwrap_err();
        assert!(matches!(e, RelationError::DirectionMismatch { .. }));
    }

    #[test]
    fn every_kind_round_trips_through_its_name() {
        for k in RelationKind::ALL {
            assert_eq!(RelationKind::parse(k.as_str()), Some(k), "{k}");
        }
        assert_eq!(RelationKind::ALL.len(), 15, "SCHEMA_VERSION must be bumped");
    }

    #[test]
    fn an_unsupported_edge_explains_itself_as_undecided_not_absent() {
        let r = Relation::new(
            "p",
            "q",
            RelationKind::StructuralAnalogy,
            Direction::Both,
            Evidence::Unsupported {
                reason: UnsupportedReason::FlexHead,
            },
            "test",
        )
        .unwrap();
        let s = r.explain();
        assert!(s.contains("undecided"), "{s}");
        assert!(s.contains("flex_head"), "{s}");
    }
}
