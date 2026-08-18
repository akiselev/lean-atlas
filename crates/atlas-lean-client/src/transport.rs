use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use std::{path::PathBuf, process::Stdio};
use thiserror::Error;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
};

#[derive(Clone, Debug)]
pub struct LeanCommand {
    pub program: String,
    pub args: Vec<String>,
    pub working_dir: PathBuf,
    pub root_uri: String,
}

#[derive(Debug, Error)]
pub enum TransportError {
    #[error("cannot start Lean server: {0}")]
    Spawn(#[source] std::io::Error),
    #[error("Lean server closed stdio")]
    Closed,
    #[error("Lean server IO: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid Lean JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Lean JSON-RPC error {code}: {message}")]
    Rpc { code: i64, message: String },
    #[error("malformed LSP frame: {0}")]
    Frame(String),
}

pub struct Transport {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

impl Transport {
    pub async fn spawn(spec: &LeanCommand) -> Result<Self, TransportError> {
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(&spec.working_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);
        let mut child = command.spawn().map_err(TransportError::Spawn)?;
        let stdin = child.stdin.take().ok_or(TransportError::Closed)?;
        let stdout = BufReader::new(child.stdout.take().ok_or(TransportError::Closed)?);
        let mut transport = Self {
            child,
            stdin,
            stdout,
            next_id: 1,
        };
        let _: Value = transport
            .request(
                "initialize",
                json!({
                    "processId": null,
                    "clientInfo": {"name": "lean-atlas", "version": env!("CARGO_PKG_VERSION")},
                    "rootUri": spec.root_uri,
                    "capabilities": {
                        "lean": {"rpcWireFormat": "v1"}
                    }
                }),
            )
            .await?;
        transport.notify("initialized", json!({})).await?;
        Ok(transport)
    }

    pub fn process_id(&self) -> Option<u32> {
        self.child.id()
    }

    pub async fn request<T: DeserializeOwned>(
        &mut self,
        method: &str,
        params: Value,
    ) -> Result<T, TransportError> {
        let id = self.next_id;
        self.next_id += 1;
        self.write(&json!({"jsonrpc":"2.0","id":id,"method":method,"params":params}))
            .await?;
        loop {
            let msg = self.read().await?;
            // Lean 4.30 may interleave server requests (notably
            // workspace/inlayHint/refresh) with a client response. A server
            // request has a method even when its id happens to equal ours; it
            // must be acknowledged rather than deserialized as our result.
            if let Some(method) = msg.get("method").and_then(Value::as_str) {
                if let Some(server_id) = msg.get("id").cloned() {
                    self.write(&json!({"jsonrpc":"2.0","id":server_id,"result":null}))
                        .await?;
                }
                let _ = method;
                continue;
            }
            if msg.get("id").and_then(Value::as_u64) != Some(id) {
                continue;
            }
            if let Some(err) = msg.get("error") {
                return Err(TransportError::Rpc {
                    code: err.get("code").and_then(Value::as_i64).unwrap_or(-1),
                    message: err
                        .get("message")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown Lean error")
                        .to_owned(),
                });
            }
            return Ok(serde_json::from_value(
                msg.get("result").cloned().unwrap_or(Value::Null),
            )?);
        }
    }

    pub async fn notify(&mut self, method: &str, params: Value) -> Result<(), TransportError> {
        self.write(&json!({"jsonrpc":"2.0","method":method,"params":params}))
            .await
    }

    async fn write(&mut self, value: &Value) -> Result<(), TransportError> {
        let body = serde_json::to_vec(value)?;
        self.stdin
            .write_all(format!("Content-Length: {}\r\n\r\n", body.len()).as_bytes())
            .await?;
        self.stdin.write_all(&body).await?;
        self.stdin.flush().await?;
        Ok(())
    }

    async fn read(&mut self) -> Result<Value, TransportError> {
        let mut length = None;
        loop {
            let mut line = String::new();
            if self.stdout.read_line(&mut line).await? == 0 {
                return Err(TransportError::Closed);
            }
            let line = line.trim_end_matches(['\r', '\n']);
            if line.is_empty() {
                break;
            }
            if let Some(value) = line.strip_prefix("Content-Length:") {
                length = Some(
                    value
                        .trim()
                        .parse::<usize>()
                        .map_err(|_| TransportError::Frame(line.into()))?,
                );
            }
        }
        let n = length.ok_or_else(|| TransportError::Frame("missing Content-Length".into()))?;
        let mut buf = vec![0; n];
        self.stdout.read_exact(&mut buf).await?;
        Ok(serde_json::from_slice(&buf)?)
    }

    pub async fn shutdown(mut self) -> Result<(), TransportError> {
        let _: Value = self.request("shutdown", Value::Null).await?;
        self.notify("exit", Value::Null).await?;
        let _ = self.child.wait().await;
        Ok(())
    }
}
