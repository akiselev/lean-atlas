pub use atlas_daemon_protocol as protocol;

use daemonkit::{Daemon, DaemonSpec, Embedded, RepairOutcome, Spawn, StopOutcome};
use protocol::{
    Command, MAX_FRAME_BYTES, Outcome, PROTOCOL_VERSION, Request, Response, ResponsePayload,
    ServiceError,
};
use std::path::{Path, PathBuf};
use thiserror::Error;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

const APP_ID: &str = "com.akiselev.lean-atlas";

#[derive(Debug, Error)]
pub enum ClientError {
    #[error("cannot configure atlasd lifecycle: {0}")]
    Config(#[from] daemonkit::ConfigError),
    #[error("atlasd lifecycle: {0}")]
    Daemon(#[from] daemonkit::Error),
    #[error("atlasd stream IO: {0}")]
    Io(#[from] std::io::Error),
    #[error("atlasd JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("atlasd protocol mismatch: expected {expected}, got {observed}")]
    ProtocolMismatch { expected: String, observed: String },
    #[error("atlasd response id mismatch: expected {expected}, got {observed}")]
    ResponseId { expected: u64, observed: u64 },
    #[error("atlasd rejected request: {0:?}")]
    Remote(ServiceError),
    #[error("atlasd frame is too large: {0} bytes")]
    FrameTooLarge(usize),
    #[error("cannot discover atlasd next to current executable; set ATLASD_BIN")]
    AtlasdNotFound,
}

pub struct AtlasClient {
    daemon: Daemon<Embedded>,
}

impl AtlasClient {
    pub fn new(atlasd: impl AsRef<Path>) -> Result<Self, ClientError> {
        let spawn = Spawn::program(atlasd.as_ref().as_os_str().to_owned());
        let daemon = Daemon::embedded(DaemonSpec::new(APP_ID)?, spawn)?;
        Ok(Self { daemon })
    }

    pub fn discover() -> Result<Self, ClientError> {
        if let Some(path) = std::env::var_os("ATLASD_BIN") {
            return Self::new(PathBuf::from(path));
        }
        let current = std::env::current_exe().map_err(|_| ClientError::AtlasdNotFound)?;
        let directory = current.parent().ok_or(ClientError::AtlasdNotFound)?;
        #[cfg(windows)]
        let candidate = directory.join("atlasd.exe");
        #[cfg(not(windows))]
        let candidate = directory.join("atlasd");
        if !candidate.exists() {
            return Err(ClientError::AtlasdNotFound);
        }
        Self::new(candidate)
    }

    pub async fn request(&self, request: Request) -> Result<ResponsePayload, ClientError> {
        let expected_id = request.id;
        let instance = self.daemon.ensure().await?;
        let mut stream = instance.connect().await?;
        write_frame(&mut stream, &request).await?;
        let response: Response = read_frame(&mut stream).await?;
        if response.protocol != PROTOCOL_VERSION {
            return Err(ClientError::ProtocolMismatch {
                expected: PROTOCOL_VERSION.into(),
                observed: response.protocol,
            });
        }
        if response.id != expected_id {
            return Err(ClientError::ResponseId {
                expected: expected_id,
                observed: response.id,
            });
        }
        match response.outcome {
            Outcome::Ok { result } => Ok(result),
            Outcome::Err { error } => Err(ClientError::Remote(error)),
        }
    }

    pub async fn command(&self, id: u64, command: Command) -> Result<ResponsePayload, ClientError> {
        self.request(Request::new(id, command)).await
    }

    pub async fn daemon_generation(&self) -> Result<String, ClientError> {
        let instance = self.daemon.ensure().await?;
        Ok(format!("{:?}", instance.generation()))
    }

    pub async fn repair(&self) -> Result<RepairOutcome, ClientError> {
        Ok(self.daemon.repair().await?)
    }

    pub async fn stop(&self) -> Result<StopOutcome, ClientError> {
        Ok(self.daemon.stop().await?)
    }

    pub async fn restart_daemon(&self) -> Result<String, ClientError> {
        let instance = self.daemon.restart().await?;
        Ok(format!("{:?}", instance.generation()))
    }
}

pub async fn write_frame<W, T>(stream: &mut W, value: &T) -> Result<(), ClientError>
where
    W: AsyncWrite + Unpin,
    T: serde::Serialize,
{
    let body = serde_json::to_vec(value)?;
    if body.len() > MAX_FRAME_BYTES || body.len() > u32::MAX as usize {
        return Err(ClientError::FrameTooLarge(body.len()));
    }
    stream.write_all(&(body.len() as u32).to_be_bytes()).await?;
    stream.write_all(&body).await?;
    stream.flush().await?;
    Ok(())
}

pub async fn read_frame<R, T>(stream: &mut R) -> Result<T, ClientError>
where
    R: AsyncRead + Unpin,
    T: serde::de::DeserializeOwned,
{
    let mut header = [0u8; 4];
    stream.read_exact(&mut header).await?;
    let length = u32::from_be_bytes(header) as usize;
    if length > MAX_FRAME_BYTES {
        return Err(ClientError::FrameTooLarge(length));
    }
    let mut body = vec![0; length];
    stream.read_exact(&mut body).await?;
    Ok(serde_json::from_slice(&body)?)
}
