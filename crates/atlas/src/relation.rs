//! Typed relation algebra and evidence discipline.
//!
//! Relation identity and static metadata live in `atlas-schema` so the enum, parser,
//! exhaustive registry, warrant, and execution class cannot drift independently. This
//! compatibility module retains Atlas's evidence-bearing `Relation` API.

use std::collections::BTreeMap;
use std::fmt;

pub use atlas_schema::{RelationKind, Warrant};

/// Stored relation envelope schema. Bump this when evidence shape or relation meaning changes.
pub const SCHEMA_VERSION: u32 = 2;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Direction {
    Both,
    LeftToRight,
    RightToLeft,
}

impl Direction {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Both => "both",
            Self::LeftToRight => "left_to_right",
            Self::RightToLeft => "right_to_left",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Evidence {
    LeanTheorem { name: String },
    CanonicalEq { level: &'static str },
    AntiUnification {
        skeleton: String,
        common: u32,
        retention: f32,
    },
    DependencyPath { path: Vec<String> },
    RankingFeatures { features: BTreeMap<String, f32> },
    Counterexample { witness: String },
    LeanAxiom { name: String },
    Unsupported { reason: UnsupportedReason },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnsupportedReason {
    FlexHead,
    BudgetExhausted,
    NotAProposition,
}

impl UnsupportedReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::FlexHead => "flex_head",
            Self::BudgetExhausted => "budget_exhausted",
            Self::NotAProposition => "not_a_proposition",
        }
    }
}

impl Evidence {
    pub fn supports(&self) -> Warrant {
        match self {
            Self::LeanTheorem { .. } | Self::Counterexample { .. } => Warrant::Proved,
            Self::CanonicalEq { .. } | Self::DependencyPath { .. } => Warrant::Structural,
            Self::LeanAxiom { .. } => Warrant::Asserted,
            Self::AntiUnification { .. }
            | Self::RankingFeatures { .. }
            | Self::Unsupported { .. } => Warrant::Heuristic,
        }
    }

    pub const fn tag(&self) -> &'static str {
        match self {
            Self::LeanTheorem { .. } => "lean_theorem",
            Self::LeanAxiom { .. } => "lean_axiom",
            Self::CanonicalEq { .. } => "canonical_eq",
            Self::AntiUnification { .. } => "anti_unification",
            Self::DependencyPath { .. } => "dependency_path",
            Self::RankingFeatures { .. } => "ranking_features",
            Self::Counterexample { .. } => "counterexample",
            Self::Unsupported { .. } => "unsupported",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum RelationError {
    InsufficientEvidence {
        kind: RelationKind,
        needs: Warrant,
        evidence: &'static str,
        supports: Warrant,
    },
    DirectionMismatch {
        kind: RelationKind,
        direction: Direction,
    },
}

impl fmt::Display for RelationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InsufficientEvidence {
                kind,
                needs,
                evidence,
                supports,
            } => write!(
                f,
                "`{kind}` is a {needs:?} relation but evidence `{evidence}` only supports {supports:?}"
            ),
            Self::DirectionMismatch { kind, direction } => write!(
                f,
                "`{kind}` is {} but was given direction `{}`",
                if kind.is_symmetric() { "symmetric" } else { "directional" },
                direction.as_str()
            ),
        }
    }
}

impl std::error::Error for RelationError {}

#[derive(Clone, Debug, PartialEq)]
pub struct Relation {
    pub left: String,
    pub right: String,
    pub kind: RelationKind,
    pub direction: Direction,
    pub evidence: Evidence,
    pub level: Option<String>,
    pub generator: String,
    pub schema_version: u32,
}

impl Relation {
    pub fn new(
        left: impl Into<String>,
        right: impl Into<String>,
        kind: RelationKind,
        direction: Direction,
        evidence: Evidence,
        generator: impl Into<String>,
    ) -> Result<Self, RelationError> {
        let (needs, supports) = (kind.warrant(), evidence.supports());
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
        Ok(Self {
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

    #[must_use]
    pub fn at_level(mut self, level: impl Into<String>) -> Self {
        self.level = Some(level.into());
        self
    }

    pub const fn warrant(&self) -> Warrant {
        self.kind.warrant()
    }

    #[must_use]
    pub fn explain(&self) -> String {
        let arrow = match self.direction {
            Direction::Both => "~",
            Direction::LeftToRight => "->",
            Direction::RightToLeft => "<-",
        };
        let because = match &self.evidence {
            Evidence::LeanTheorem { name } => format!("proved by `{name}`"),
            Evidence::LeanAxiom { name } => format!(
                "asserted by axiom `{name}`; this carries the author's authority and no proof"
            ),
            Evidence::CanonicalEq { level } => {
                format!("identical canonical statements at level `{level}`")
            }
            Evidence::AntiUnification {
                common, retention, ..
            } => format!(
                "shared skeleton of {common} nodes retaining {:.0}% of concrete structure; resemblance, not proof",
                retention * 100.0
            ),
            Evidence::DependencyPath { path } => {
                format!("citation path of {} steps", path.len().saturating_sub(1))
            }
            Evidence::RankingFeatures { features } => {
                let mut features = features.iter().collect::<Vec<_>>();
                features.sort_by(|a, b| b.1.total_cmp(a.1));
                let top = features
                    .iter()
                    .take(3)
                    .map(|(name, value)| format!("{name}={value:.3}"))
                    .collect::<Vec<_>>()
                    .join(", ");
                format!("ranked by {top}; search result, not mathematical claim")
            }
            Evidence::Counterexample { witness } => format!("refuted by {witness}"),
            Evidence::Unsupported { reason } => format!(
                "undecided ({}); failure to settle is not evidence of absence",
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
    fn a_proved_kind_cannot_be_built_from_resemblance() {
        let error = Relation::new(
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
            error,
            RelationError::InsufficientEvidence {
                kind: RelationKind::ProvedIff,
                needs: Warrant::Proved,
                supports: Warrant::Heuristic,
                ..
            }
        ));
    }

    #[test]
    fn stronger_evidence_may_back_a_weaker_relation_kind() {
        let relation = Relation::new(
            "a",
            "b",
            RelationKind::StructuralAnalogy,
            Direction::Both,
            Evidence::LeanTheorem {
                name: "some_thm".into(),
            },
            "test",
        )
        .unwrap();
        assert_eq!(relation.warrant(), Warrant::Heuristic);
    }

    #[test]
    fn implication_may_not_be_recorded_as_symmetric() {
        let error = Relation::new(
            "p",
            "q",
            RelationKind::ProvedImplies,
            Direction::Both,
            Evidence::LeanTheorem { name: "t".into() },
            "test",
        )
        .unwrap_err();
        assert!(matches!(error, RelationError::DirectionMismatch { .. }));
    }

    #[test]
    fn every_kind_round_trips_through_authoritative_registry() {
        assert_eq!(RelationKind::ALL.len(), 17);
        for kind in RelationKind::ALL {
            assert_eq!(RelationKind::parse(kind.as_str()), Some(kind), "{kind}");
        }
        assert_eq!(RelationKind::parse("AssertedIff"), Some(RelationKind::AssertedIff));
        assert_eq!(
            RelationKind::parse("AssertedImplies"),
            Some(RelationKind::AssertedImplies)
        );
    }

    #[test]
    fn unsupported_edge_explains_undecided_not_absent() {
        let relation = Relation::new(
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
        let explanation = relation.explain();
        assert!(explanation.contains("undecided"));
        assert!(explanation.contains("flex_head"));
    }
}
