use crate::{EvidenceId, FactId, OracleReceiptId, RelationTypeId};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

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

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FactRow {
    pub id: FactId,
    pub relation: RelationTypeId,
    pub args: Vec<Value>,
    pub warrant: FactWarrant,
    pub provenance: Provenance,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelationType {
    pub id: RelationTypeId,
    pub name: String,
    pub arity: usize,
    pub execution: RelationExecution,
}
