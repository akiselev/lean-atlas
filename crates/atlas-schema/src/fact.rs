use crate::{EvidenceId, FactId, OracleReceiptId, RelationTypeId};
use serde::{Deserialize, Serialize};
use std::fmt::Write as _;
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
    /// within one derivation, where every input is conjunctively required.
    pub const fn weaker(self, other: Self) -> Self {
        if self.strength() <= other.strength() {
            self
        } else {
            other
        }
    }

    /// Return the stronger of two warrants. This is the trust aggregation operation used
    /// across alternative derivations, where any one derivation is sufficient.
    pub const fn stronger(self, other: Self) -> Self {
        if self.strength() >= other.strength() {
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

/// Stable, collision-free identifier for one immediate derivation alternative.
///
/// The ID is a canonical encoding of the rule name and ordered supporting fact IDs rather
/// than a process-local counter or randomized hash. It therefore survives insertion-order
/// changes and can safely be used by explanation UIs as an alternative identity.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct DerivationId(pub String);

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct Derivation {
    pub id: DerivationId,
    pub rule: String,
    pub inputs: Vec<FactId>,
}

impl Derivation {
    pub fn new(rule: impl Into<String>, inputs: Vec<FactId>) -> Self {
        let rule = rule.into();
        let id = DerivationId(stable_derivation_id(&rule, &inputs));
        Self { id, rule, inputs }
    }
}

fn stable_derivation_id(rule: &str, inputs: &[FactId]) -> String {
    // Length-prefixing is unnecessary after hex encoding: ':' and '.' cannot occur in a
    // hex-encoded rule. Fixed-width fact IDs keep the representation unambiguous as well.
    let mut out = String::from("d1:");
    for byte in rule.as_bytes() {
        write!(&mut out, "{byte:02x}").expect("writing to String cannot fail");
    }
    out.push(':');
    for (index, input) in inputs.iter().enumerate() {
        if index != 0 {
            out.push('.');
        }
        write!(&mut out, "{:016x}", input.0).expect("writing to String cannot fail");
    }
    out
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Provenance {
    Source {
        source: String,
        #[serde(default)]
        evidence: SourceEvidence,
    },
    Derived {
        /// Canonical first derivation retained in the original fields for backward-compatible
        /// serialized data. It is not semantically privileged over `alternatives`.
        rule: String,
        inputs: Vec<FactId>,
        /// Additional derivations are OR alternatives. Inputs *within* each derivation remain
        /// conjunctive. Old persisted rows deserialize with an empty alternatives vector.
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        alternatives: Vec<Derivation>,
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
    pub fn derived(rule: impl Into<String>, inputs: Vec<FactId>) -> Self {
        Self::Derived {
            rule: rule.into(),
            inputs,
            alternatives: Vec::new(),
        }
    }

    /// Return every immediate derivation in canonical order. The primary compatibility
    /// fields and the alternative vector are treated as one OR-set here.
    pub fn derivations(&self) -> Vec<Derivation> {
        let Self::Derived {
            rule,
            inputs,
            alternatives,
        } = self
        else {
            return Vec::new();
        };
        let mut derivations = Vec::with_capacity(alternatives.len() + 1);
        derivations.push(Derivation::new(rule.clone(), inputs.clone()));
        derivations.extend(alternatives.iter().cloned());
        derivations.sort();
        derivations.dedup();
        derivations
    }

    /// Add one OR alternative and rewrite the serialized representation canonically.
    /// Returns true exactly when the support set changed.
    pub fn add_derivation(&mut self, derivation: Derivation) -> bool {
        let Self::Derived {
            rule,
            inputs,
            alternatives,
        } = self
        else {
            return false;
        };

        let mut derivations = Vec::with_capacity(alternatives.len() + 2);
        derivations.push(Derivation::new(rule.clone(), inputs.clone()));
        derivations.extend(alternatives.iter().cloned());
        if derivations.contains(&derivation) {
            return false;
        }
        derivations.push(derivation);
        derivations.sort();
        derivations.dedup();

        let primary = derivations.remove(0);
        *rule = primary.rule;
        *inputs = primary.inputs;
        *alternatives = derivations;
        true
    }

    /// The strongest warrant justified by the provenance kind alone. Derived facts
    /// additionally have to be bounded by their retained derivations at persistence time.
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
    fn weaker_is_the_trust_meet_and_stronger_is_the_alternative_join() {
        assert_eq!(
            FactWarrant::Proved.weaker(FactWarrant::Heuristic),
            FactWarrant::Heuristic
        );
        assert_eq!(
            FactWarrant::Structural.weaker(FactWarrant::Asserted),
            FactWarrant::Asserted
        );
        assert_eq!(
            FactWarrant::Heuristic.stronger(FactWarrant::Structural),
            FactWarrant::Structural
        );
    }

    #[test]
    fn alternative_derivations_have_stable_ids_and_canonical_order() {
        let a = Derivation::new("reach.base", vec![FactId(20)]);
        let b = Derivation::new("reach.base", vec![FactId(10)]);
        assert_eq!(
            a.id,
            Derivation::new("reach.base", vec![FactId(20)]).id
        );
        assert_ne!(a.id, b.id);

        let mut left = Provenance::derived(a.rule.clone(), a.inputs.clone());
        assert!(left.add_derivation(b.clone()));
        let mut right = Provenance::derived(b.rule.clone(), b.inputs.clone());
        assert!(right.add_derivation(a.clone()));
        assert_eq!(left, right);
        assert_eq!(left.derivations(), right.derivations());
    }

    #[test]
    fn legacy_single_derivation_json_still_deserializes() {
        let legacy = r#"{"kind":"derived","rule":"r","inputs":[1]}"#;
        let provenance: Provenance = serde_json::from_str(legacy).unwrap();
        assert_eq!(provenance.derivations().len(), 1);
        assert_eq!(provenance.derivations()[0].inputs, vec![FactId(1)]);
    }
}
