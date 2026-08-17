use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Position {
    pub line: u32,
    pub character: u32,
}

fn serialize_bignum<S>(value: &u64, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    serializer.serialize_str(&value.to_string())
}

fn deserialize_bignum<'de, D>(deserializer: D) -> Result<u64, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum Wire {
        String(String),
        Number(u64),
    }
    match Wire::deserialize(deserializer)? {
        Wire::String(value) => value.parse().map_err(D::Error::custom),
        // Accept numeric refs defensively for non-Lean test doubles, but always emit
        // Lean's canonical string bignum representation on the wire.
        Wire::Number(value) => Ok(value),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct RpcRef {
    #[serde(
        rename = "__rpcref",
        serialize_with = "serialize_bignum",
        deserialize_with = "deserialize_bignum"
    )]
    pub id: u64,
}
macro_rules! handle{($($n:ident),+)=>{$(#[derive(Clone,Copy,Debug,PartialEq,Eq,Hash,Serialize,Deserialize)]#[serde(transparent)]pub struct $n(pub RpcRef);)+}}
handle!(ExprHandle, DeclHandle);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LeanFailureKind {
    UnknownDeclaration,
    Elaboration,
    TypeMismatch,
    Unification,
    DefinitionalEquality,
    InstanceSynthesis,
    UnsolvedMetavariables,
    UniverseConstraint,
    MissingHypothesis,
    InvalidProof,
    StaleHandle,
    StaleEnvironment,
    Internal,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct GoalSummary {
    pub type_text: String,
}
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct MVarSummary {
    pub name: String,
    pub type_text: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeanFailure {
    pub kind: LeanFailureKind,
    pub message: String,
    #[serde(default)]
    pub goals: Vec<GoalSummary>,
    #[serde(default)]
    pub missing_instances: Vec<String>,
    #[serde(default)]
    pub metavariables: Vec<MVarSummary>,
    pub trace: Option<serde_json::Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct OracleResult<T> {
    pub value: Option<T>,
    pub failure: Option<LeanFailure>,
}
impl<T> OracleResult<T> {
    pub fn ok(value: T) -> Self {
        Self {
            value: Some(value),
            failure: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EnvironmentFingerprint {
    pub lean_version: String,
    pub plugin_version: String,
    pub project_root: String,
    pub modules_digest: String,
    pub options_digest: String,
    pub document_version: Option<i64>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn rpc_ref_uses_lean_string_bignum_wire_format() {
        let rpc_ref = RpcRef { id: 42 };
        assert_eq!(serde_json::to_value(rpc_ref).unwrap(), json!({"__rpcref":"42"}));
        assert_eq!(
            serde_json::from_value::<RpcRef>(json!({"__rpcref":"42"})).unwrap(),
            rpc_ref
        );
    }
}
