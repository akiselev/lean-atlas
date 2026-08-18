use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: &str = "atlas-daemon-v1";
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
    Closed { project_id: String },
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
