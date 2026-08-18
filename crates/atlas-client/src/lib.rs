use atlas_daemon_protocol::{Envelope, Request, Response};
use daemonkit::{Daemon, DaemonSpec, Embedded, Spawn};
use thiserror::Error;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

const MAX_FRAME: usize = 64 * 1024 * 1024;

#[derive(Debug, Error)]
pub enum ClientError {
    #[error("atlasd lifecycle error: {0}")]
    Lifecycle(String),
    #[error("atlasd IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("atlasd protocol JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("atlasd returned an invalid frame length {0}")]
    Frame(usize),
}

pub struct Client {
    daemon: Daemon<Embedded>,
}

impl Client {
    /// Construct a client that can attach to, or atomically start, the process-wide
    /// Atlas daemon. daemonkit serializes competing `ensure` calls and authenticates
    /// every application stream before it is returned here.
    pub fn new(atlasd_program: impl Into<std::ffi::OsString>) -> Result<Self, ClientError> {
        let spec = DaemonSpec::new("org.leanatlas.atlasd")
            .map_err(|error| ClientError::Lifecycle(error.to_string()))?;
        let spawn = Spawn::program(atlasd_program);
        let daemon = Daemon::embedded(spec, spawn)
            .map_err(|error| ClientError::Lifecycle(error.to_string()))?;
        Ok(Self { daemon })
    }

    pub async fn call(&self, request: Request) -> Result<Response, ClientError> {
        let instance = self
            .daemon
            .ensure()
            .await
            .map_err(|error| ClientError::Lifecycle(error.to_string()))?;
        let mut stream = instance
            .connect()
            .await
            .map_err(|error| ClientError::Lifecycle(error.to_string()))?;
        write_frame(&mut stream, &Envelope::new(request)).await?;
        read_frame(&mut stream).await
    }

    pub async fn status(&self) -> Result<daemonkit::InstanceStatus, ClientError> {
        self.daemon
            .status()
            .await
            .map_err(|error| ClientError::Lifecycle(error.to_string()))
    }

    pub async fn stop(&self) -> Result<daemonkit::StopOutcome, ClientError> {
        self.daemon
            .stop()
            .await
            .map_err(|error| ClientError::Lifecycle(error.to_string()))
    }

    pub async fn repair(&self) -> Result<daemonkit::RepairOutcome, ClientError> {
        self.daemon
            .repair()
            .await
            .map_err(|error| ClientError::Lifecycle(error.to_string()))
    }
}

pub async fn write_frame<W, T>(writer: &mut W, value: &T) -> Result<(), ClientError>
where
    W: AsyncWrite + Unpin,
    T: serde::Serialize,
{
    let body = serde_json::to_vec(value)?;
    if body.len() > MAX_FRAME {
        return Err(ClientError::Frame(body.len()));
    }
    writer.write_u32(body.len() as u32).await?;
    writer.write_all(&body).await?;
    writer.flush().await?;
    Ok(())
}

pub async fn read_frame<R, T>(reader: &mut R) -> Result<T, ClientError>
where
    R: AsyncRead + Unpin,
    T: serde::de::DeserializeOwned,
{
    let len = reader.read_u32().await? as usize;
    if len > MAX_FRAME {
        return Err(ClientError::Frame(len));
    }
    let mut body = vec![0; len];
    reader.read_exact(&mut body).await?;
    Ok(serde_json::from_slice(&body)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use atlas_daemon_protocol::Request;

    #[tokio::test]
    async fn frame_roundtrip() {
        let (mut a, mut b) = tokio::io::duplex(1024);
        let writer = tokio::spawn(async move {
            write_frame(&mut a, &Envelope::new(Request::Ping)).await.unwrap();
        });
        let envelope: Envelope<Request> = read_frame(&mut b).await.unwrap();
        writer.await.unwrap();
        assert_eq!(envelope.protocol, atlas_daemon_protocol::PROTOCOL_VERSION);
        assert!(matches!(envelope.body, Request::Ping));
    }
}
