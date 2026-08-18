use atlas_daemon_protocol::{
    CloseDocumentRequest, Command, DaemonSnapshot, DocumentRequest, ErrorCode, LeanLaunch,
    LeanSnapshot, LeanState, MAX_FRAME_BYTES, OpenProjectRequest, OverlaySnapshot,
    PROTOCOL_VERSION, ProjectMutationRequest, ProjectRequest, ProjectSnapshot, Request, Response,
    ResponsePayload, ServiceError,
};
use atlas_engine::runtime::{LeanClient, LeanCommand, LeanError, Store};
use daemonkit::{AuthenticatedStream, Bootstrap, Incoming, ServiceContext, Shutdown};
use futures_util::StreamExt;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    io,
    path::{Path, PathBuf},
    sync::Arc,
};
use thiserror::Error;
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    sync::Mutex,
};

#[derive(Debug, Error)]
enum ServerError {
    #[error("atlasd IO: {0}")]
    Io(#[from] io::Error),
    #[error("atlasd JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("atlasd frame is too large: {0} bytes")]
    FrameTooLarge(usize),
}

#[derive(Clone)]
struct Overlay {
    text: String,
    version: i64,
}

struct Project {
    id: String,
    root: PathBuf,
    store_path: PathBuf,
    _store: Store,
    launch: LeanLaunch,
    overlays: BTreeMap<String, Overlay>,
    lean: Option<LeanClient>,
    lean_generation: u64,
    lean_state: LeanState,
    last_error: Option<String>,
}

impl Project {
    fn check_generation(&self, expected: Option<u64>) -> Result<(), ServiceError> {
        if let Some(expected) = expected {
            if expected != self.lean_generation {
                return Err(ServiceError::new(
                    ErrorCode::StaleLeanGeneration,
                    format!(
                        "Lean generation {expected} is stale; current generation is {}",
                        self.lean_generation
                    ),
                ));
            }
        }
        Ok(())
    }

    fn snapshot(&self, daemon_generation: &str) -> ProjectSnapshot {
        ProjectSnapshot {
            project_id: self.id.clone(),
            root: self.root.to_string_lossy().into_owned(),
            store_path: self.store_path.to_string_lossy().into_owned(),
            overlay_documents: self
                .overlays
                .iter()
                .map(|(uri, overlay)| OverlaySnapshot {
                    uri: uri.clone(),
                    version: overlay.version,
                    bytes: overlay.text.len(),
                })
                .collect(),
            lean: LeanSnapshot {
                state: self.lean_state,
                generation: self.lean_generation,
                process_id: self.lean.as_ref().and_then(LeanClient::process_id),
                last_error: self.last_error.clone(),
            },
            daemon_generation: daemon_generation.into(),
        }
    }

    async fn start_lean(&mut self) -> Result<(), LeanError> {
        self.lean_state = LeanState::Restarting;
        let mut client = LeanClient::spawn(LeanCommand {
            program: self.launch.program.clone(),
            args: self.launch.args.clone(),
            working_dir: self.root.clone(),
            root_uri: self.launch.root_uri.clone(),
        })
        .await?;
        // Rebuild the live overlay deterministically after every process
        // generation. didOpen notifications recreate unsaved editor state;
        // each open also establishes a fresh Lean RPC session.
        for (uri, overlay) in &self.overlays {
            client
                .open_document(uri.clone(), overlay.text.clone(), overlay.version)
                .await?;
        }
        self.lean = Some(client);
        self.lean_state = LeanState::Ready;
        Ok(())
    }

    async fn restart_lean(&mut self) -> Result<(), LeanError> {
        self.lean.take();
        self.lean_generation = self.lean_generation.saturating_add(1);
        self.start_lean().await
    }

    async fn recover_from_lean_failure(
        &mut self,
        error: LeanError,
        daemon_generation: &str,
    ) -> ServiceError {
        let original = error.to_string();
        self.last_error = Some(original.clone());
        self.lean_state = LeanState::Degraded;
        match self.restart_lean().await {
            Ok(()) => ServiceError::new(
                ErrorCode::LeanRestarted,
                format!("Lean failed ({original}); atlasd started a fresh Lean generation"),
            )
            .with_project(self.snapshot(daemon_generation)),
            Err(restart) => {
                self.lean.take();
                self.lean_state = LeanState::Degraded;
                self.last_error = Some(format!("{original}; restart failed: {restart}"));
                ServiceError::new(
                    ErrorCode::LeanUnavailable,
                    format!("Lean failed ({original}) and restart failed: {restart}"),
                )
                .with_project(self.snapshot(daemon_generation))
            }
        }
    }
}

struct ServiceState {
    daemon_generation: String,
    process_id: u32,
    projects: BTreeMap<String, Project>,
}

impl ServiceState {
    fn new(context: &ServiceContext) -> Self {
        Self {
            daemon_generation: format!("{:?}", context.generation()),
            process_id: std::process::id(),
            projects: BTreeMap::new(),
        }
    }

    fn daemon_snapshot(&self) -> DaemonSnapshot {
        DaemonSnapshot {
            daemon_generation: self.daemon_generation.clone(),
            process_id: self.process_id,
            projects: self.projects.len(),
        }
    }

    async fn execute(&mut self, command: Command) -> Result<ResponsePayload, ServiceError> {
        match command {
            Command::Ping => Ok(ResponsePayload::Pong(self.daemon_snapshot())),
            Command::OpenProject(request) => self.open_project(request).await,
            Command::ProjectStatus(request) => self.project_status(request).await,
            Command::OpenDocument(request) => self.open_document(request, true).await,
            Command::ChangeDocument(request) => self.open_document(request, false).await,
            Command::CloseDocument(request) => self.close_document(request).await,
            Command::RestartLean(request) => self.restart_lean(request).await,
            Command::CloseProject(request) => self.close_project(request).await,
        }
    }

    async fn open_project(
        &mut self,
        request: OpenProjectRequest,
    ) -> Result<ResponsePayload, ServiceError> {
        let root = std::fs::canonicalize(&request.root).map_err(|error| {
            ServiceError::new(
                ErrorCode::InvalidRequest,
                format!("cannot canonicalize project root {}: {error}", request.root),
            )
        })?;
        let id = project_id(&root);
        if let Some(existing) = self.projects.get(&id) {
            if existing.launch != request.lean {
                return Err(ServiceError::new(
                    ErrorCode::InvalidRequest,
                    "project is already open with a different Lean launch configuration",
                )
                .with_project(existing.snapshot(&self.daemon_generation)));
            }
            return Ok(ResponsePayload::Project(
                existing.snapshot(&self.daemon_generation),
            ));
        }

        let store_path = request
            .store_path
            .map(PathBuf::from)
            .unwrap_or_else(|| root.join(".lean-atlas").join("atlas.sqlite"));
        if let Some(parent) = store_path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| {
                ServiceError::new(
                    ErrorCode::StoreUnavailable,
                    format!("cannot create semantic-store directory: {error}"),
                )
            })?;
        }
        let store = Store::open(&store_path).map_err(|error| {
            ServiceError::new(
                ErrorCode::StoreUnavailable,
                format!(
                    "cannot open semantic store {}: {error}",
                    store_path.display()
                ),
            )
        })?;
        let mut project = Project {
            id: id.clone(),
            root,
            store_path,
            _store: store,
            launch: request.lean,
            overlays: BTreeMap::new(),
            lean: None,
            lean_generation: 1,
            lean_state: LeanState::Restarting,
            last_error: None,
        };
        if let Err(error) = project.start_lean().await {
            project.lean_state = LeanState::Degraded;
            project.last_error = Some(error.to_string());
        }
        let snapshot = project.snapshot(&self.daemon_generation);
        self.projects.insert(id, project);
        Ok(ResponsePayload::Project(snapshot))
    }

    async fn project_status(
        &mut self,
        request: ProjectRequest,
    ) -> Result<ResponsePayload, ServiceError> {
        let daemon_generation = self.daemon_generation.clone();
        let project = self.projects.get_mut(&request.project_id).ok_or_else(|| {
            ServiceError::new(
                ErrorCode::ProjectNotFound,
                format!("unknown project {}", request.project_id),
            )
        })?;
        // keepAlive is meaningful only after a document established an RPC
        // session. It doubles as a cheap crash probe for live projects.
        if !project.overlays.is_empty() {
            if let Some(lean) = project.lean.as_mut() {
                if let Err(error) = lean.keep_alive().await {
                    return Err(project
                        .recover_from_lean_failure(error, &daemon_generation)
                        .await);
                }
            }
        }
        Ok(ResponsePayload::Project(
            project.snapshot(&daemon_generation),
        ))
    }

    async fn open_document(
        &mut self,
        request: DocumentRequest,
        is_open: bool,
    ) -> Result<ResponsePayload, ServiceError> {
        let daemon_generation = self.daemon_generation.clone();
        let project = self.projects.get_mut(&request.project_id).ok_or_else(|| {
            ServiceError::new(
                ErrorCode::ProjectNotFound,
                format!("unknown project {}", request.project_id),
            )
        })?;
        project.check_generation(request.expected_lean_generation)?;
        if !is_open && !project.overlays.contains_key(&request.uri) {
            return Err(ServiceError::new(
                ErrorCode::InvalidRequest,
                format!("document {} is not open", request.uri),
            ));
        }
        project.overlays.insert(
            request.uri.clone(),
            Overlay {
                text: request.text.clone(),
                version: request.version,
            },
        );
        if project.lean.is_none() {
            if let Err(error) = project.restart_lean().await {
                project.lean_state = LeanState::Degraded;
                project.last_error = Some(error.to_string());
                return Err(ServiceError::new(
                    ErrorCode::LeanUnavailable,
                    format!("cannot start Lean: {error}"),
                )
                .with_project(project.snapshot(&daemon_generation)));
            }
            // restart replayed the newly-recorded overlay.
            return Ok(ResponsePayload::Project(
                project.snapshot(&daemon_generation),
            ));
        }
        let result = if is_open {
            project
                .lean
                .as_mut()
                .expect("checked above")
                .open_document(request.uri, request.text, request.version)
                .await
        } else {
            project
                .lean
                .as_mut()
                .expect("checked above")
                .change_document_at(request.uri, request.text, request.version)
                .await
        };
        if let Err(error) = result {
            return Err(project
                .recover_from_lean_failure(error, &daemon_generation)
                .await);
        }
        project.lean_state = LeanState::Ready;
        project.last_error = None;
        Ok(ResponsePayload::Project(
            project.snapshot(&daemon_generation),
        ))
    }

    async fn close_document(
        &mut self,
        request: CloseDocumentRequest,
    ) -> Result<ResponsePayload, ServiceError> {
        let daemon_generation = self.daemon_generation.clone();
        let project = self.projects.get_mut(&request.project_id).ok_or_else(|| {
            ServiceError::new(
                ErrorCode::ProjectNotFound,
                format!("unknown project {}", request.project_id),
            )
        })?;
        project.check_generation(request.expected_lean_generation)?;
        if project.overlays.remove(&request.uri).is_none() {
            return Err(ServiceError::new(
                ErrorCode::InvalidRequest,
                format!("document {} is not open", request.uri),
            ));
        }
        let next_uri = project.overlays.keys().next().cloned();
        if let Some(lean) = project.lean.as_mut() {
            if let Err(error) = lean.close_document(request.uri).await {
                return Err(project
                    .recover_from_lean_failure(error, &daemon_generation)
                    .await);
            }
            if let Some(next_uri) = next_uri {
                if let Err(error) = lean.select_document(next_uri).await {
                    return Err(project
                        .recover_from_lean_failure(error, &daemon_generation)
                        .await);
                }
            }
        }
        Ok(ResponsePayload::Project(
            project.snapshot(&daemon_generation),
        ))
    }

    async fn restart_lean(
        &mut self,
        request: ProjectMutationRequest,
    ) -> Result<ResponsePayload, ServiceError> {
        let daemon_generation = self.daemon_generation.clone();
        let project = self.projects.get_mut(&request.project_id).ok_or_else(|| {
            ServiceError::new(
                ErrorCode::ProjectNotFound,
                format!("unknown project {}", request.project_id),
            )
        })?;
        project.check_generation(request.expected_lean_generation)?;
        if let Err(error) = project.restart_lean().await {
            project.lean_state = LeanState::Degraded;
            project.last_error = Some(error.to_string());
            return Err(ServiceError::new(
                ErrorCode::LeanUnavailable,
                format!("Lean restart failed: {error}"),
            )
            .with_project(project.snapshot(&daemon_generation)));
        }
        project.last_error = None;
        Ok(ResponsePayload::Project(
            project.snapshot(&daemon_generation),
        ))
    }

    async fn close_project(
        &mut self,
        request: ProjectMutationRequest,
    ) -> Result<ResponsePayload, ServiceError> {
        let project = self.projects.get(&request.project_id).ok_or_else(|| {
            ServiceError::new(
                ErrorCode::ProjectNotFound,
                format!("unknown project {}", request.project_id),
            )
        })?;
        project.check_generation(request.expected_lean_generation)?;
        self.projects.remove(&request.project_id);
        Ok(ResponsePayload::Closed {
            project_id: request.project_id,
        })
    }
}

fn project_id(root: &Path) -> String {
    let mut hash = Sha256::new();
    hash.update(b"lean-atlas:project:v1\0");
    hash.update(root.as_os_str().to_string_lossy().as_bytes());
    let digest = hash.finalize();
    digest[..16]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

async fn handle_connection(
    mut stream: AuthenticatedStream,
    state: Arc<Mutex<ServiceState>>,
) -> Result<(), ServerError> {
    let request: Request = read_frame(&mut stream).await?;
    let id = request.id;
    let response = if request.protocol != PROTOCOL_VERSION {
        Response::err(
            id,
            ServiceError::new(
                ErrorCode::ProtocolMismatch,
                format!(
                    "expected protocol {PROTOCOL_VERSION}, got {}",
                    request.protocol
                ),
            ),
        )
    } else {
        let mut state = state.lock().await;
        match state.execute(request.command).await {
            Ok(result) => Response::ok(id, result),
            Err(error) => Response::err(id, error),
        }
    };
    write_frame(&mut stream, &response).await
}

async fn read_frame<R, T>(stream: &mut R) -> Result<T, ServerError>
where
    R: AsyncRead + Unpin,
    T: serde::de::DeserializeOwned,
{
    let mut header = [0u8; 4];
    stream.read_exact(&mut header).await?;
    let length = u32::from_be_bytes(header) as usize;
    if length > MAX_FRAME_BYTES {
        return Err(ServerError::FrameTooLarge(length));
    }
    let mut body = vec![0; length];
    stream.read_exact(&mut body).await?;
    Ok(serde_json::from_slice(&body)?)
}

async fn write_frame<W, T>(stream: &mut W, value: &T) -> Result<(), ServerError>
where
    W: AsyncWrite + Unpin,
    T: serde::Serialize,
{
    let body = serde_json::to_vec(value)?;
    if body.len() > MAX_FRAME_BYTES || body.len() > u32::MAX as usize {
        return Err(ServerError::FrameTooLarge(body.len()));
    }
    stream.write_all(&(body.len() as u32).to_be_bytes()).await?;
    stream.write_all(&body).await?;
    stream.flush().await?;
    Ok(())
}

async fn serve(
    context: ServiceContext,
    mut incoming: Incoming,
    mut shutdown: Shutdown,
) -> Result<(), ServerError> {
    let state = Arc::new(Mutex::new(ServiceState::new(&context)));
    loop {
        tokio::select! {
            _ = shutdown.requested() => break,
            connection = incoming.next() => {
                let Some(connection) = connection else { break; };
                match connection {
                    Ok(stream) => {
                        let state = state.clone();
                        tokio::spawn(async move {
                            if let Err(error) = handle_connection(stream, state).await {
                                eprintln!("atlasd: connection failed: {error}");
                            }
                        });
                    }
                    Err(error) => eprintln!("atlasd: authenticated accept failed: {error}"),
                }
            }
        }
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let Some(bootstrap) = Bootstrap::detect()? else {
        eprintln!("atlasd is launched and authenticated by atlas-client/daemonkit");
        return Ok(());
    };
    bootstrap
        .run_embedded_fn(|context, incoming, shutdown| async move {
            serve(context, incoming, shutdown).await
        })
        .await?;
    Ok(())
}
