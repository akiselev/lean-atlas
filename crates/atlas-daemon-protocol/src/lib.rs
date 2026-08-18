use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PROTOCOL_VERSION: u32 = 1;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProjectConfig {
    pub project_id: String,
    pub lean_program: String,
    pub lean_args: Vec<String>,
    pub working_dir: String,
    pub root_uri: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionToken {
    pub project_id: String,
    pub generation: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocumentOverlay {
    pub uri: String,
    pub text: String,
    pub version: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectHealth {
    Ready,
    Degraded,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProjectStatus {
    pub token: SessionToken,
    pub health: ProjectHealth,
    pub open_document: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Request {
    Ping,
    Status,
    EnsureProject { config: ProjectConfig },
    CloseProject { project_id: String },
    OpenDocument {
        token: SessionToken,
        document: DocumentOverlay,
    },
    ChangeDocument {
        token: SessionToken,
        text: String,
        version: i64,
    },
    RestartLean { project_id: String },
    OracleCall {
        token: SessionToken,
        position: atlas_position::Position,
        method: String,
        params: Value,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum Response {
    Ok { value: Value },
    Projects { projects: Vec<ProjectStatus> },
    Project { status: ProjectStatus },
    Error { error: ServiceError },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ServiceError {
    ProtocolMismatch { expected: u32, observed: u32 },
    ProjectNotFound { project_id: String },
    StaleSession {
        project_id: String,
        expected_generation: u64,
        observed_generation: u64,
    },
    LeanDegraded { project_id: String, message: String },
    LeanRestarted {
        project_id: String,
        old_generation: u64,
        new_generation: u64,
        cause: String,
    },
    InvalidRequest { message: String },
    Internal { message: String },
}

/// Kept local to this wire crate so M5 does not make the daemon protocol depend on
/// Lean's RPC wire types. The daemon converts it at the semantic boundary.
pub mod atlas_position {
    use serde::{Deserialize, Serialize};

    #[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
    pub struct Position {
        pub line: u32,
        pub character: u32,
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Envelope<T> {
    pub protocol: u32,
    pub body: T,
}

impl<T> Envelope<T> {
    pub fn new(body: T) -> Self {
        Self {
            protocol: PROTOCOL_VERSION,
            body,
        }
    }
}
