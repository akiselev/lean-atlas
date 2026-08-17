//! Stable, dependency-light data contracts shared across Atlas subsystems.
//!
//! This crate deliberately owns identifiers, tuple values, warrant classes, and
//! relation metadata but no storage, query evaluation, Lean RPC, or graph algorithms.

use serde::{Deserialize, Serialize};

macro_rules! id_type {
    ($name:ident) => {
        #[repr(transparent)]
        #[derive(
            Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize,
        )]
        pub struct $name(pub u64);

        impl $name {
            #[must_use]
            pub const fn new(value: u64) -> Self {
                Self(value)
            }

            #[must_use]
            pub const fn get(self) -> u64 {
                self.0
            }
        }
    };
}

id_type!(DeclarationId);
id_type!(SymbolId);
id_type!(FactId);
id_type!(RuleId);
id_type!(EvidenceId);
id_type!(EnvironmentId);
id_type!(ExperimentId);
id_type!(AssayId);

/// Runtime column types accepted by the logic engine.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueType {
    Declaration,
    Symbol,
    Text,
    Bool,
    I64,
    U64,
    F64,
}

/// A totally ordered runtime value. Floating point values are stored as their IEEE-754
/// bit pattern so relation tuples remain deterministic and orderable.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum Value {
    Declaration(DeclarationId),
    Symbol(SymbolId),
    Text(String),
    Bool(bool),
    I64(i64),
    U64(u64),
    F64(u64),
}

impl Value {
    #[must_use]
    pub fn float(value: f64) -> Self {
        Self::F64(value.to_bits())
    }

    #[must_use]
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Self::F64(bits) => Some(f64::from_bits(*bits)),
            _ => None,
        }
    }

    #[must_use]
    pub const fn value_type(&self) -> ValueType {
        match self {
            Self::Declaration(_) => ValueType::Declaration,
            Self::Symbol(_) => ValueType::Symbol,
            Self::Text(_) => ValueType::Text,
            Self::Bool(_) => ValueType::Bool,
            Self::I64(_) => ValueType::I64,
            Self::U64(_) => ValueType::U64,
            Self::F64(_) => ValueType::F64,
        }
    }
}

/// How a relation is populated. This is intentionally independent from warrant.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationExecution {
    Materialized,
    Derived,
    Oracle,
    Candidate,
}

/// Strength of mathematical warrant. Variant ordering is strongest to weakest so existing
/// Atlas code can keep using `supports > needs` to detect insufficient evidence.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Warrant {
    Proved,
    Structural,
    Asserted,
    Heuristic,
}

/// Static relation metadata. The relation kind is the authority for these properties;
/// callers do not carry a second mutable copy that can drift from the enum.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RelationMetadata {
    pub wire_name: &'static str,
    pub warrant: Warrant,
    pub execution: RelationExecution,
    pub symmetric: bool,
}

macro_rules! relation_kinds {
    (
        count = $count:expr;
        $(
            $variant:ident => {
                wire: $wire:literal,
                warrant: $warrant:ident,
                execution: $execution:ident,
                symmetric: $symmetric:literal
            }
        ),+ $(,)?
    ) => {
        #[derive(
            Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize,
        )]
        pub enum RelationKind {
            $($variant),+
        }

        impl RelationKind {
            pub const ALL: [Self; $count] = [$(Self::$variant),+];

            #[must_use]
            pub const fn metadata(self) -> RelationMetadata {
                match self {
                    $(Self::$variant => RelationMetadata {
                        wire_name: $wire,
                        warrant: Warrant::$warrant,
                        execution: RelationExecution::$execution,
                        symmetric: $symmetric,
                    }),+
                }
            }

            #[must_use]
            pub const fn warrant(self) -> Warrant {
                self.metadata().warrant
            }

            #[must_use]
            pub const fn execution(self) -> RelationExecution {
                self.metadata().execution
            }

            #[must_use]
            pub const fn is_symmetric(self) -> bool {
                self.metadata().symmetric
            }

            #[must_use]
            pub const fn as_str(self) -> &'static str {
                self.metadata().wire_name
            }

            #[must_use]
            pub fn parse(value: &str) -> Option<Self> {
                match value {
                    $($wire => Some(Self::$variant),)+
                    _ => None,
                }
            }
        }
    };
}

relation_kinds! {
    count = 17;
    ExactStatement => { wire: "ExactStatement", warrant: Structural, execution: Derived, symmetric: true },
    PresentationEqual => { wire: "PresentationEqual", warrant: Structural, execution: Derived, symmetric: true },
    DefinitionalRewrite => { wire: "DefinitionalRewrite", warrant: Structural, execution: Derived, symmetric: false },
    ProvedIff => { wire: "ProvedIff", warrant: Proved, execution: Materialized, symmetric: true },
    ProvedImplies => { wire: "ProvedImplies", warrant: Proved, execution: Materialized, symmetric: false },
    TypeEquiv => { wire: "TypeEquiv", warrant: Structural, execution: Derived, symmetric: true },
    SharedInstance => { wire: "SharedInstance", warrant: Structural, execution: Derived, symmetric: true },
    SharedHomeCandidate => { wire: "SharedHomeCandidate", warrant: Heuristic, execution: Candidate, symmetric: true },
    SharedHomeConfirmed => { wire: "SharedHomeConfirmed", warrant: Proved, execution: Oracle, symmetric: true },
    StructuralAnalogy => { wire: "StructuralAnalogy", warrant: Heuristic, execution: Candidate, symmetric: true },
    ProofShapeAnalogy => { wire: "ProofShapeAnalogy", warrant: Heuristic, execution: Candidate, symmetric: true },
    DictionaryRowCandidate => { wire: "DictionaryRowCandidate", warrant: Heuristic, execution: Candidate, symmetric: false },
    DictionaryRowConfirmed => { wire: "DictionaryRowConfirmed", warrant: Proved, execution: Oracle, symmetric: false },
    TransportRefuted => { wire: "TransportRefuted", warrant: Proved, execution: Oracle, symmetric: false },
    TransportProved => { wire: "TransportProved", warrant: Proved, execution: Oracle, symmetric: false },
    AssertedIff => { wire: "AssertedIff", warrant: Asserted, execution: Materialized, symmetric: true },
    AssertedImplies => { wire: "AssertedImplies", warrant: Asserted, execution: Materialized, symmetric: false },
}

impl core::fmt::Display for RelationKind {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// A fully identified relation tuple, suitable as a key in provenance and persistent stores.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct FactKey {
    pub relation: String,
    pub tuple: Vec<Value>,
}

impl FactKey {
    #[must_use]
    pub fn new(relation: impl Into<String>, tuple: Vec<Value>) -> Self {
        Self {
            relation: relation.into(),
            tuple,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_relation_kind_round_trips() {
        assert_eq!(RelationKind::ALL.len(), 17);
        for kind in RelationKind::ALL {
            assert_eq!(RelationKind::parse(kind.as_str()), Some(kind), "{kind}");
        }
    }

    #[test]
    fn asserted_relations_cannot_fall_out_of_the_registry_again() {
        assert_eq!(
            RelationKind::parse("AssertedIff"),
            Some(RelationKind::AssertedIff)
        );
        assert_eq!(
            RelationKind::parse("AssertedImplies"),
            Some(RelationKind::AssertedImplies)
        );
    }

    #[test]
    fn execution_class_is_not_warrant() {
        assert_eq!(RelationKind::SharedHomeCandidate.execution(), RelationExecution::Candidate);
        assert_eq!(RelationKind::SharedHomeCandidate.warrant(), Warrant::Heuristic);
        assert_eq!(RelationKind::SharedHomeConfirmed.execution(), RelationExecution::Oracle);
        assert_eq!(RelationKind::SharedHomeConfirmed.warrant(), Warrant::Proved);
    }
}
