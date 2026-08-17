use serde::{Deserialize,Serialize};

#[derive(Clone,Copy,Debug,Default,PartialEq,Eq,Serialize,Deserialize)]
pub struct Position{pub line:u32,pub character:u32}

#[derive(Clone,Copy,Debug,PartialEq,Eq,Hash,Serialize,Deserialize)]
pub struct RpcRef{#[serde(rename="__rpcref")]pub id:u64}
macro_rules! handle{($($n:ident),+)=>{$(#[derive(Clone,Copy,Debug,PartialEq,Eq,Hash,Serialize,Deserialize)]#[serde(transparent)]pub struct $n(pub RpcRef);)+}}
handle!(ExprHandle,DeclHandle);

#[derive(Clone,Debug,PartialEq,Eq,Serialize,Deserialize)]
#[serde(rename_all="snake_case")]
pub enum LeanFailureKind{UnknownDeclaration,Elaboration,TypeMismatch,Unification,DefinitionalEquality,InstanceSynthesis,UnsolvedMetavariables,UniverseConstraint,MissingHypothesis,InvalidProof,StaleHandle,StaleEnvironment,Internal}

#[derive(Clone,Debug,Default,PartialEq,Eq,Serialize,Deserialize)]
pub struct GoalSummary{pub type_text:String}
#[derive(Clone,Debug,Default,PartialEq,Eq,Serialize,Deserialize)]
pub struct MVarSummary{pub name:String,pub type_text:String}

#[derive(Clone,Debug,PartialEq,Eq,Serialize,Deserialize)]
pub struct LeanFailure{pub kind:LeanFailureKind,pub message:String,#[serde(default)]pub goals:Vec<GoalSummary>,#[serde(default)]pub missing_instances:Vec<String>,#[serde(default)]pub metavariables:Vec<MVarSummary>,pub trace:Option<serde_json::Value>}

#[derive(Clone,Debug,PartialEq,Serialize,Deserialize)]
pub struct OracleResult<T>{pub value:Option<T>,pub failure:Option<LeanFailure>}
impl<T> OracleResult<T>{pub fn ok(value:T)->Self{Self{value:Some(value),failure:None}}}

#[derive(Clone,Debug,PartialEq,Eq,Serialize,Deserialize)]
pub struct EnvironmentFingerprint{pub lean_version:String,pub plugin_version:String,pub project_root:String,pub modules_digest:String,pub options_digest:String,pub document_version:Option<i64>}
