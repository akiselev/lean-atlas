use atlas_daemon_protocol::{
    DocumentOverlay, Envelope, ProjectConfig, ProjectHealth, ProjectStatus, Request, Response,
    ServiceError, SessionToken, PROTOCOL_VERSION,
};
use atlas_lean_client::{ClientError as LeanError, LeanClient, LeanCommand};
use atlas_lean_protocol::Position;
use atlas_store::Store;
use daemonkit::{Bootstrap, Daemon, DaemonSpec, Spawn};
use futures_util::StreamExt;
use serde::{Serialize, de::DeserializeOwned};
use serde_json::{Value, json};
use std::{collections::HashMap, path::PathBuf, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    sync::Mutex,
};

const MAX_FRAME: usize = 64 * 1024 * 1024;
const APP_ID: &str = "org.leanatlas.atlasd";

type SharedSession = Arc<Mutex<ProjectSession>>;

struct ServiceState {
    projects: Mutex<HashMap<String, SharedSession>>,
    // M5 establishes the durable semantic-store owner. Query/import operations are
    // intentionally added at the semantic-query layer rather than inventing a second DB.
    _store: Mutex<Store>,
}

struct ProjectSession {
    config: ProjectConfig,
    generation: u64,
    client: Option<LeanClient>,
    overlay: Option<DocumentOverlay>,
    last_error: Option<String>,
}

impl ProjectSession {
    async fn start(config: ProjectConfig, generation: u64) -> Self {
        let mut session = Self {
            config,
            generation,
            client: None,
            overlay: None,
            last_error: None,
        };
        if let Err(error) = session.spawn_lean().await {
            session.last_error = Some(error);
        }
        session
    }

    fn token(&self) -> SessionToken {
        SessionToken {
            project_id: self.config.project_id.clone(),
            generation: self.generation,
        }
    }

    fn status(&self) -> ProjectStatus {
        ProjectStatus {
            token: self.token(),
            health: if self.client.is_some() {
                ProjectHealth::Ready
            } else {
                ProjectHealth::Degraded
            },
            open_document: self.overlay.as_ref().map(|doc| doc.uri.clone()),
            last_error: self.last_error.clone(),
        }
    }

    fn validate_token(&self, token: &SessionToken) -> Result<(), ServiceError> {
        if token.project_id != self.config.project_id || token.generation != self.generation {
            return Err(ServiceError::StaleSession {
                project_id: token.project_id.clone(),
                expected_generation: self.generation,
                observed_generation: token.generation,
            });
        }
        Ok(())
    }

    async fn spawn_lean(&mut self) -> Result<(), String> {
        let command = LeanCommand {
            program: self.config.lean_program.clone(),
            args: self.config.lean_args.clone(),
            working_dir: PathBuf::from(&self.config.working_dir),
            root_uri: self.config.root_uri.clone(),
        };
        let mut client = LeanClient::spawn(command)
            .await
            .map_err(|error| error.to_string())?;
        if let Some(document) = &self.overlay {
            client
                .open_document(
                    document.uri.clone(),
                    document.text.clone(),
                    document.version,
                )
                .await
                .map_err(|error| error.to_string())?;
        }
        self.client = Some(client);
        self.last_error = None;
        Ok(())
    }

    async fn restart(&mut self, cause: impl Into<String>) -> String {
        let cause = cause.into();
        if let Some(client) = self.client.take() {
            let _ = tokio::time::timeout(Duration::from_secs(2), client.shutdown()).await;
        }
        self.generation = self.generation.saturating_add(1);
        match self.spawn_lean().await {
            Ok(()) => cause,
            Err(restart_error) => {
                let message = format!("{cause}; restart failed: {restart_error}");
                self.last_error = Some(message.clone());
                message
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    if let Some(bootstrap) = Bootstrap::detect()? {
        bootstrap
            .run_embedded_fn(|_context, incoming, mut shutdown| async move {
                let state = Arc::new(ServiceState {
                    projects: Mutex::new(HashMap::new()),
                    _store: Mutex::new(open_store()?),
                });
                tokio::pin!(incoming);
                loop {
                    tokio::select! {
                        _ = shutdown.requested() => break,
                        next = incoming.next() => {
                            let Some(next) = next else { break };
                            if let Ok(stream) = next {
                                let state = state.clone();
                                tokio::spawn(async move {
                                    let _ = serve_connection(stream, state).await;
                                });
                            }
                        }
                    }
                }
                Ok::<_, std::io::Error>(())
            })
            .await?;
        return Ok(());
    }

    // Running atlasd directly is useful in terminals and service managers too. It uses
    // the same daemonkit lifecycle path as atlas-client, so competing starters converge
    // on exactly one authenticated generation.
    let daemon = Daemon::embedded(DaemonSpec::new(APP_ID)?, Spawn::current_exe()?)?;
    let instance = daemon.ensure().await?;
    println!("atlasd ready generation {:?}", instance.generation());
    Ok(())
}

fn open_store() -> Result<Store, std::io::Error> {
    let path = std::env::var_os("ATLAS_STORE_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(default_store_path);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    Store::open(&path).map_err(std::io::Error::other)
}

fn default_store_path() -> PathBuf {
    if let Some(path) = std::env::var_os("XDG_STATE_HOME") {
        return PathBuf::from(path).join("lean-atlas/atlas.sqlite3");
    }
    if let Some(path) = std::env::var_os("LOCALAPPDATA") {
        return PathBuf::from(path).join("lean-atlas/atlas.sqlite3");
    }
    if let Some(home) = std::env::var_os("HOME") {
        return PathBuf::from(home).join(".local/state/lean-atlas/atlas.sqlite3");
    }
    PathBuf::from(".lean-atlas/atlas.sqlite3")
}

async fn serve_connection<S>(mut stream: S, state: Arc<ServiceState>) -> Result<(), std::io::Error>
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    loop {
        let envelope: Envelope<Request> = match read_frame(&mut stream).await {
            Ok(value) => value,
            Err(FrameError::Io(error)) if error.kind() == std::io::ErrorKind::UnexpectedEof => {
                return Ok(())
            }
            Err(error) => {
                let response = Response::Error {
                    error: ServiceError::InvalidRequest {
                        message: error.to_string(),
                    },
                };
                let _ = write_frame(&mut stream, &response).await;
                return Ok(());
            }
        };
        let response = if envelope.protocol != PROTOCOL_VERSION {
            Response::Error {
                error: ServiceError::ProtocolMismatch {
                    expected: PROTOCOL_VERSION,
                    observed: envelope.protocol,
                },
            }
        } else {
            handle_request(state.clone(), envelope.body).await
        };
        write_frame(&mut stream, &response)
            .await
            .map_err(std::io::Error::other)?;
    }
}

async fn handle_request(state: Arc<ServiceState>, request: Request) -> Response {
    match handle_request_inner(state, request).await {
        Ok(response) => response,
        Err(error) => Response::Error { error },
    }
}

async fn handle_request_inner(
    state: Arc<ServiceState>,
    request: Request,
) -> Result<Response, ServiceError> {
    match request {
        Request::Ping => Ok(Response::Ok {
            value: json!({"protocol": PROTOCOL_VERSION}),
        }),
        Request::Status => {
            let sessions: Vec<SharedSession> = state.projects.lock().await.values().cloned().collect();
            let mut projects = Vec::with_capacity(sessions.len());
            for session in sessions {
                projects.push(session.lock().await.status());
            }
            projects.sort_by(|a, b| a.token.project_id.cmp(&b.token.project_id));
            Ok(Response::Projects { projects })
        }
        Request::EnsureProject { config } => {
            let existing = state.projects.lock().await.get(&config.project_id).cloned();
            let session = if let Some(existing) = existing {
                let changed = existing.lock().await.config != config;
                if changed {
                    let generation = existing.lock().await.generation.saturating_add(1);
                    let replacement = Arc::new(Mutex::new(ProjectSession::start(config.clone(), generation).await));
                    state.projects.lock().await.insert(config.project_id.clone(), replacement.clone());
                    replacement
                } else {
                    existing
                }
            } else {
                let session = Arc::new(Mutex::new(ProjectSession::start(config.clone(), 1).await));
                state.projects.lock().await.insert(config.project_id.clone(), session.clone());
                session
            };
            Ok(Response::Project {
                status: session.lock().await.status(),
            })
        }
        Request::CloseProject { project_id } => {
            let session = state.projects.lock().await.remove(&project_id);
            if let Some(session) = session {
                if let Some(client) = session.lock().await.client.take() {
                    let _ = tokio::time::timeout(Duration::from_secs(2), client.shutdown()).await;
                }
            }
            Ok(Response::Ok { value: Value::Null })
        }
        Request::RestartLean { project_id } => {
            let session = get_session(&state, &project_id).await?;
            let mut session = session.lock().await;
            session.restart("explicit client restart").await;
            Ok(Response::Project {
                status: session.status(),
            })
        }
        Request::OpenDocument { token, document } => {
            let session = get_session(&state, &token.project_id).await?;
            let mut session = session.lock().await;
            session.validate_token(&token)?;
            session.overlay = Some(document.clone());
            let Some(client) = session.client.as_mut() else {
                return Err(degraded(&session));
            };
            if let Err(error) = client
                .open_document(document.uri, document.text, document.version)
                .await
            {
                return Err(restart_error(&mut session, error).await);
            }
            Ok(Response::Project { status: session.status() })
        }
        Request::ChangeDocument { token, text, version } => {
            let session = get_session(&state, &token.project_id).await?;
            let mut session = session.lock().await;
            session.validate_token(&token)?;
            let Some(overlay) = session.overlay.as_mut() else {
                return Err(ServiceError::InvalidRequest {
                    message: "change_document requires an open document".into(),
                });
            };
            overlay.text = text.clone();
            overlay.version = version;
            let Some(client) = session.client.as_mut() else {
                return Err(degraded(&session));
            };
            if let Err(error) = client.change_document(text, version).await {
                return Err(restart_error(&mut session, error).await);
            }
            Ok(Response::Project { status: session.status() })
        }
        Request::OracleCall {
            token,
            position,
            method,
            params,
        } => {
            let session = get_session(&state, &token.project_id).await?;
            let mut session = session.lock().await;
            session.validate_token(&token)?;
            let Some(client) = session.client.as_mut() else {
                return Err(degraded(&session));
            };
            client.set_position(Position {
                line: position.line,
                character: position.character,
            });
            let result: Result<Value, LeanError> = client.call(&method, &params).await;
            match result {
                Ok(value) => Ok(Response::Ok { value }),
                Err(LeanError::Transport(error)) => {
                    Err(restart_error(&mut session, LeanError::Transport(error)).await)
                }
                Err(LeanError::StaleEnvironment) => {
                    Err(restart_error(&mut session, LeanError::StaleEnvironment).await)
                }
                Err(error @ LeanError::StaleHandle) => Err(ServiceError::OracleFailure {
                    project_id: session.config.project_id.clone(),
                    message: error.to_string(),
                }),
            }
        }
    }
}

async fn get_session(state: &ServiceState, project_id: &str) -> Result<SharedSession, ServiceError> {
    state
        .projects
        .lock()
        .await
        .get(project_id)
        .cloned()
        .ok_or_else(|| ServiceError::ProjectNotFound {
            project_id: project_id.to_owned(),
        })
}

fn degraded(session: &ProjectSession) -> ServiceError {
    ServiceError::LeanDegraded {
        project_id: session.config.project_id.clone(),
        message: session
            .last_error
            .clone()
            .unwrap_or_else(|| "Lean session is unavailable".into()),
    }
}

async fn restart_error(session: &mut ProjectSession, error: LeanError) -> ServiceError {
    let project_id = session.config.project_id.clone();
    let old_generation = session.generation;
    let cause = session.restart(error.to_string()).await;
    ServiceError::LeanRestarted {
        project_id,
        old_generation,
        new_generation: session.generation,
        cause,
    }
}

#[derive(Debug, thiserror::Error)]
enum FrameError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("frame length {0} exceeds limit")]
    TooLarge(usize),
}

async fn read_frame<R, T>(reader: &mut R) -> Result<T, FrameError>
where
    R: AsyncRead + Unpin,
    T: DeserializeOwned,
{
    let len = reader.read_u32().await? as usize;
    if len > MAX_FRAME {
        return Err(FrameError::TooLarge(len));
    }
    let mut body = vec![0; len];
    reader.read_exact(&mut body).await?;
    Ok(serde_json::from_slice(&body)?)
}

async fn write_frame<W, T>(writer: &mut W, value: &T) -> Result<(), FrameError>
where
    W: AsyncWrite + Unpin,
    T: Serialize,
{
    let body = serde_json::to_vec(value)?;
    if body.len() > MAX_FRAME {
        return Err(FrameError::TooLarge(body.len()));
    }
    writer.write_u32(body.len() as u32).await?;
    writer.write_all(&body).await?;
    writer.flush().await?;
    Ok(())
}
