use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: &str = "atlas-daemon-v2";
pub const MAX_FRAME_BYTES: usize = 8 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Request {
    pub id: u64,
    pub protocol: String,
    pub command: Command,
}

impl Request {
    pub fn new(id: u64, command: Command) -> Self {
        Self {
            id,
            protocol: PROTOCOL_VERSION.into(),
            command,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "method", content = "params", rename_all = "snake_case")]
pub enum Command {
    Ping,
    OpenProject(OpenProjectRequest),
    ProjectStatus(ProjectRequest),
    OpenDocument(DocumentRequest),
    ChangeDocument(DocumentRequest),
    CloseDocument(CloseDocumentRequest),
    Query(SemanticQueryRequest),
    RestartLean(ProjectMutationRequest),
    CloseProject(ProjectMutationRequest),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeanLaunch {
    pub program: String,
    #[serde(default)]
    pub args: Vec<String>,
    pub root_uri: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OpenProjectRequest {
    pub root: String,
    pub lean: LeanLaunch,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub store_path: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProjectRequest {
    pub project_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProjectMutationRequest {
    pub project_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_lean_generation: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocumentRequest {
    pub project_id: String,
    pub uri: String,
    pub text: String,
    pub version: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_lean_generation: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CloseDocumentRequest {
    pub project_id: String,
    pub uri: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_lean_generation: Option<u64>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct QueryPosition {
    #[serde(default)]
    pub line: u32,
    #[serde(default)]
    pub character: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticQueryRequest {
    pub project_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_lean_generation: Option<u64>,
    pub query: SemanticQuery,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "query", content = "params", rename_all = "snake_case")]
pub enum SemanticQuery {
    GoalMatch(GoalMatchQuery),
    WhyNot(WhyNotQuery),
    InstancePath(InstancePathQuery),
    MinimalContext(MinimalContextQuery),
    Compose(ComposeQuery),
}

fn default_max_candidates() -> usize {
    256
}
fn default_max_matches() -> usize {
    64
}
fn default_max_evaluations() -> usize {
    256
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GoalMatchQuery {
    pub goal: String,
    pub candidates: Vec<String>,
    #[serde(default)]
    pub position: QueryPosition,
    #[serde(default = "default_max_candidates")]
    pub max_candidates: usize,
    #[serde(default = "default_max_matches")]
    pub max_matches: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WhyNotQuery {
    pub candidate: String,
    pub goal: String,
    #[serde(default)]
    pub position: QueryPosition,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct InstancePathQuery {
    pub type_text: String,
    #[serde(default)]
    pub position: QueryPosition,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextBindingKind {
    Explicit,
    Implicit,
    Instance,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContextBinding {
    pub name: String,
    pub type_text: String,
    #[serde(default = "default_context_binding_kind")]
    pub kind: ContextBindingKind,
}

fn default_context_binding_kind() -> ContextBindingKind {
    ContextBindingKind::Explicit
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MinimalContextQuery {
    pub goal: String,
    pub proof: String,
    #[serde(default)]
    pub hypotheses: Vec<ContextBinding>,
    #[serde(default)]
    pub position: QueryPosition,
    #[serde(default = "default_max_evaluations")]
    pub max_evaluations: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComposeQuery {
    pub left: String,
    pub right: String,
    pub goal: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub proof: Option<String>,
    #[serde(default)]
    pub position: QueryPosition,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Response {
    pub id: u64,
    pub protocol: String,
    pub outcome: Outcome,
}

impl Response {
    pub fn ok(id: u64, result: ResponsePayload) -> Self {
        Self {
            id,
            protocol: PROTOCOL_VERSION.into(),
            outcome: Outcome::Ok { result },
        }
    }

    pub fn err(id: u64, error: ServiceError) -> Self {
        Self {
            id,
            protocol: PROTOCOL_VERSION.into(),
            outcome: Outcome::Err { error },
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum Outcome {
    Ok { result: ResponsePayload },
    Err { error: ServiceError },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum ResponsePayload {
    Pong(DaemonSnapshot),
    Project(ProjectSnapshot),
    Query(QueryResponse),
    Closed { project_id: String },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "query", content = "result", rename_all = "snake_case")]
pub enum QueryResponse {
    GoalMatch(GoalMatchResponse),
    WhyNot(WhyNotResponse),
    InstancePath(InstancePathResponse),
    MinimalContext(MinimalContextResponse),
    Compose(ComposeResponse),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryStage {
    GoalElaboration,
    CandidateLookup,
    CandidateApplication,
    TypeElaboration,
    InstanceSynthesis,
    ContextGoalElaboration,
    ContextProofElaboration,
    ContextProofCheck,
    CompositionGoalElaboration,
    CompositionProofElaboration,
    CompositionProofCheck,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObstructionClass {
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
    StaleContext,
    Internal,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct QueryMetavariable {
    pub name: String,
    pub type_text: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct QueryFailure {
    pub stage: QueryStage,
    pub class: ObstructionClass,
    pub message: String,
    #[serde(default)]
    pub goals: Vec<String>,
    #[serde(default)]
    pub missing_instances: Vec<String>,
    #[serde(default)]
    pub metavariables: Vec<QueryMetavariable>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trace: Option<serde_json::Value>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CandidateRejection {
    pub declaration: String,
    pub failure: QueryFailure,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GoalMatchCandidate {
    pub declaration: String,
    pub subgoals: Vec<String>,
    pub closes_goal: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GoalMatchResponse {
    pub goal: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub goal_pretty: Option<String>,
    pub considered: usize,
    pub matches: Vec<GoalMatchCandidate>,
    pub rejections: Vec<CandidateRejection>,
    pub truncated: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub goal_failure: Option<QueryFailure>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WhyNotResponse {
    pub candidate: String,
    pub goal: String,
    pub applicable: bool,
    pub closes_goal: bool,
    pub subgoals: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure: Option<QueryFailure>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct InstancePathResponse {
    pub type_text: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instance_pretty: Option<String>,
    pub dependencies: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure: Option<QueryFailure>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MinimalContextWitness {
    pub kept: Vec<ContextBinding>,
    pub removed: Vec<ContextBinding>,
    pub goal_pretty: String,
    pub proof_pretty: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RejectedContext {
    pub kept: Vec<String>,
    pub failure: QueryFailure,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MinimalContextResponse {
    pub goal: String,
    pub proof: String,
    pub frontier: Vec<MinimalContextWitness>,
    pub rejections: Vec<RejectedContext>,
    pub evaluations: usize,
    pub truncated: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CompositionStatus {
    Proved,
    Candidate,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComposeResponse {
    pub left: String,
    pub right: String,
    pub goal: String,
    pub proof_term: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub proof_pretty: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub goal_pretty: Option<String>,
    pub status: CompositionStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure: Option<QueryFailure>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DaemonSnapshot {
    pub daemon_generation: String,
    pub process_id: u32,
    pub projects: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProjectSnapshot {
    pub project_id: String,
    pub root: String,
    pub store_path: String,
    pub overlay_documents: Vec<OverlaySnapshot>,
    pub lean: LeanSnapshot,
    pub daemon_generation: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OverlaySnapshot {
    pub uri: String,
    pub version: i64,
    pub bytes: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeanSnapshot {
    pub state: LeanState,
    pub generation: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub process_id: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_error: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LeanState {
    Ready,
    Degraded,
    Restarting,
    Stopped,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ServiceError {
    pub code: ErrorCode,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project: Option<ProjectSnapshot>,
}

impl ServiceError {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            project: None,
        }
    }

    pub fn with_project(mut self, project: ProjectSnapshot) -> Self {
        self.project = Some(project);
        self
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    ProtocolMismatch,
    InvalidRequest,
    ProjectNotFound,
    StaleLeanGeneration,
    LeanUnavailable,
    LeanRestarted,
    OracleFailure,
    StoreUnavailable,
    Internal,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_roundtrips_without_erasing_method() {
        let request = Request::new(
            7,
            Command::OpenProject(OpenProjectRequest {
                root: "/tmp/project".into(),
                lean: LeanLaunch {
                    program: "lean".into(),
                    args: vec!["--server".into()],
                    root_uri: "file:///tmp/project".into(),
                },
                store_path: None,
            }),
        );
        let encoded = serde_json::to_vec(&request).unwrap();
        assert_eq!(
            serde_json::from_slice::<Request>(&encoded).unwrap(),
            request
        );
    }

    #[test]
    fn semantic_query_roundtrips_with_typed_operation() {
        let request = Request::new(
            11,
            Command::Query(SemanticQueryRequest {
                project_id: "project".into(),
                expected_lean_generation: Some(3),
                query: SemanticQuery::Compose(ComposeQuery {
                    left: "left".into(),
                    right: "right".into(),
                    goal: "A → C".into(),
                    proof: None,
                    position: QueryPosition::default(),
                }),
            }),
        );
        let encoded = serde_json::to_vec(&request).unwrap();
        assert_eq!(
            serde_json::from_slice::<Request>(&encoded).unwrap(),
            request
        );
    }

    #[test]
    fn stale_generation_is_machine_readable() {
        let response = Response::err(
            3,
            ServiceError::new(ErrorCode::StaleLeanGeneration, "old generation"),
        );
        let value = serde_json::to_value(response).unwrap();
        assert_eq!(
            value["outcome"]["error"]["code"],
            serde_json::Value::String("stale_lean_generation".into())
        );
    }
}
