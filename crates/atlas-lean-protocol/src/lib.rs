//! Versioned application-level messages carried over Lean's `$/lean/rpc/*` protocol.
//!
//! Lean's own RPC reference wire representation has changed over time. Atlas deliberately
//! treats a remote reference as opaque JSON and returns it to the same RPC session rather
//! than depending on a particular `__rpcref` encoding.

use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: u32 = 1;
pub const SCHEMA: &str = "atlas-lean-rpc-v1";

pub const HELLO_METHOD: &str = "Atlas.Server.hello";
pub const LOOKUP_DECLARATION_METHOD: &str = "Atlas.Server.lookupDeclaration";
pub const USED_CONSTANTS_METHOD: &str = "Atlas.Server.usedConstants";
pub const INFER_TYPE_METHOD: &str = "Atlas.Server.inferType";
pub const WHNF_METHOD: &str = "Atlas.Server.whnf";
pub const DEF_EQ_METHOD: &str = "Atlas.Server.defEq";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Position {
    pub line: u32,
    pub character: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HelloRequest {
    pub protocol: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HelloResponse {
    pub protocol: u32,
    pub schema: String,
    pub lean_version: String,
    pub plugin_version: String,
    pub features: Vec<String>,
}

/// An opaque reference created and owned by one Lean RPC session.
pub type RpcRef = serde_json::Value;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LookupDeclarationRequest {
    pub position: Position,
    pub name: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeclarationRef {
    pub name: String,
    pub kind: String,
    pub type_ref: RpcRef,
    pub uses: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LookupDeclarationResponse {
    pub declaration: Option<DeclarationRef>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExprRequest {
    pub position: Position,
    pub expr: RpcRef,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UsedConstantsResponse {
    pub constants: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExprResponse {
    pub expr: RpcRef,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DefEqRequest {
    pub position: Position,
    pub lhs: RpcRef,
    pub rhs: RpcRef,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DefEqResponse {
    pub equal: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rpc_refs_are_wire_format_agnostic() {
        let old = serde_json::json!({"p": 4});
        let current = serde_json::json!({"__rpcref": "4"});
        let old_request = ExprRequest {
            position: Position::default(),
            expr: old.clone(),
        };
        let current_request = ExprRequest {
            position: Position::default(),
            expr: current.clone(),
        };
        assert_eq!(serde_json::to_value(old_request).unwrap()["expr"], old);
        assert_eq!(serde_json::to_value(current_request).unwrap()["expr"], current);
    }
}
