use crate::{EvidenceId, FactId, OracleReceiptId, RelationTypeId};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, fmt};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationExecution {
    Materialized,
    Derived,
    Oracle,
    Candidate,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FactWarrant {
    Proved,
    Structural,
    Asserted,
    Heuristic,
}

impl FactWarrant {
    /// Strength is intentionally independent of enum declaration/serialization order.
    pub const fn strength(self) -> u8 {
        match self {
            Self::Proved => 3,
            Self::Structural => 2,
            Self::Asserted => 1,
            Self::Heuristic => 0,
        }
    }

    pub const fn is_stronger_than(self, supported: Self) -> bool {
        self.strength() > supported.strength()
    }

    /// Return the weaker of two warrants. This is the trust propagation operation used
    /// when a derived fact depends on multiple supports.
    pub const fn weaker(self, other: Self) -> Self {
        if self.strength() <= other.strength() {
            self
        } else {
            other
        }
    }
}

/// What kind of evidence an externally sourced fact actually carries. This is kept
/// separate from `FactWarrant`: callers may deliberately downgrade a fact, but cannot
/// claim a warrant stronger than its evidence class supports.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceEvidence {
    Formal,
    Structural,
    Assertion,
    Empirical,
    Numerical,
    Heuristic,
    #[default]
    Unclassified,
}

impl SourceEvidence {
    pub const fn strongest_warrant(self) -> FactWarrant {
        match self {
            Self::Formal => FactWarrant::Proved,
            Self::Structural => FactWarrant::Structural,
            Self::Assertion | Self::Empirical => FactWarrant::Asserted,
            Self::Numerical | Self::Heuristic | Self::Unclassified => FactWarrant::Heuristic,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum Value {
    Entity(u64),
    Text(String),
    Integer(i64),
    Boolean(bool),
}

pub type Bindings = BTreeMap<String, Value>;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Provenance {
    Source {
        source: String,
        #[serde(default)]
        evidence: SourceEvidence,
    },
    Derived {
        rule: String,
        inputs: Vec<FactId>,
    },
    Oracle {
        receipt: OracleReceiptId,
    },
    Candidate {
        method: String,
        evidence: Vec<EvidenceId>,
    },
}

impl Provenance {
    /// The strongest warrant justified by the provenance kind alone. Derived facts
    /// additionally have to be bounded by the warrants of every input at persistence time.
    pub const fn strongest_intrinsic_warrant(&self) -> FactWarrant {
        match self {
            Self::Source { evidence, .. } => evidence.strongest_warrant(),
            Self::Derived { .. } => FactWarrant::Structural,
            Self::Oracle { .. } => FactWarrant::Proved,
            Self::Candidate { .. } => FactWarrant::Heuristic,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FactValidationError {
    pub claimed: FactWarrant,
    pub supported: FactWarrant,
    pub provenance_kind: &'static str,
}

impl fmt::Display for FactValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "fact claims {:?} warrant but {} provenance supports at most {:?}",
            self.claimed, self.provenance_kind, self.supported
        )
    }
}

impl std::error::Error for FactValidationError {}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FactRow {
    pub id: FactId,
    pub relation: RelationTypeId,
    pub args: Vec<Value>,
    pub warrant: FactWarrant,
    pub provenance: Provenance,
}

impl FactRow {
    pub fn validate_intrinsic_warrant(&self) -> Result<(), FactValidationError> {
        let supported = self.provenance.strongest_intrinsic_warrant();
        if self.warrant.is_stronger_than(supported) {
            return Err(FactValidationError {
                claimed: self.warrant,
                supported,
                provenance_kind: match self.provenance {
                    Provenance::Source { .. } => "source",
                    Provenance::Derived { .. } => "derived",
                    Provenance::Oracle { .. } => "oracle",
                    Provenance::Candidate { .. } => "candidate",
                },
            });
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelationType {
    pub id: RelationTypeId,
    pub name: String,
    pub arity: usize,
    pub execution: RelationExecution,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numerical_source_cannot_claim_formal_warrant() {
        let fact = FactRow {
            id: FactId(1),
            relation: RelationTypeId(1),
            args: vec![],
            warrant: FactWarrant::Proved,
            provenance: Provenance::Source {
                source: "ranking".into(),
                evidence: SourceEvidence::Numerical,
            },
        };
        let err = fact.validate_intrinsic_warrant().unwrap_err();
        assert_eq!(err.claimed, FactWarrant::Proved);
        assert_eq!(err.supported, FactWarrant::Heuristic);
    }

    #[test]
    fn candidate_is_always_heuristic_at_most() {
        let fact = FactRow {
            id: FactId(1),
            relation: RelationTypeId(1),
            args: vec![],
            warrant: FactWarrant::Structural,
            provenance: Provenance::Candidate {
                method: "numerical_fit".into(),
                evidence: vec![],
            },
        };
        assert!(fact.validate_intrinsic_warrant().is_err());
    }

    #[test]
    fn weaker_is_the_trust_meet() {
        assert_eq!(
            FactWarrant::Proved.weaker(FactWarrant::Heuristic),
            FactWarrant::Heuristic
        );
        assert_eq!(
            FactWarrant::Structural.weaker(FactWarrant::Asserted),
            FactWarrant::Asserted
        );
    }
}
