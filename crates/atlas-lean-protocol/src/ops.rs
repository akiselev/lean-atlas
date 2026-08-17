use crate::*;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HelloRequest {
    pub atlas_protocol: String,
    #[serde(default)]
    pub requested_features: Vec<String>,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HelloResponse {
    pub atlas_protocol: String,
    pub lean_version: String,
    pub plugin_version: String,
    pub features: Vec<String>,
    pub environment_fingerprint: EnvironmentFingerprint,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LookupDeclRequest {
    pub name: String,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LookupDeclResponse {
    pub declaration: DeclHandle,
    pub expression: ExprHandle,
    pub type_expr: ExprHandle,
    pub name: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExprRequest {
    pub expr: ExprHandle,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExprResponse {
    pub expr: ExprHandle,
    pub pretty: String,
}
pub type GetTypeRequest = ExprRequest;
pub type InferTypeRequest = ExprRequest;
pub type WhnfRequest = ExprRequest;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PairRequest {
    pub lhs: ExprHandle,
    pub rhs: ExprHandle,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BoolResponse {
    pub value: bool,
}
pub type DefEqRequest = PairRequest;
pub type UnifyRequest = PairRequest;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SynthInstanceRequest {
    pub type_expr: ExprHandle,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SynthInstanceResponse {
    pub instance: ExprHandle,
    pub dependencies: Vec<String>,
    pub pretty: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ApplyRequest {
    pub candidate: ExprHandle,
    pub goal_type: ExprHandle,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ApplyResponse {
    pub subgoals: Vec<ExprHandle>,
    pub subgoal_types: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ElaborateRequest {
    pub text: String,
    pub expected: Option<ExprHandle>,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ElaborateResponse {
    pub expr: ExprHandle,
    pub type_expr: ExprHandle,
    pub pretty: String,
    pub type_pretty: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CheckProofRequest {
    pub proof: ExprHandle,
    pub proposition: ExprHandle,
    pub position: Position,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BatchDefEqRequest {
    pub pairs: Vec<(ExprHandle, ExprHandle)>,
    pub position: Position,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BatchDefEqResponse {
    pub results: Vec<OracleResult<BoolResponse>>,
}
