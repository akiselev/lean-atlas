use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use std::{path::PathBuf, process::Stdio, time::Duration};
use thiserror::Error;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
};

const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(1);
const EXIT_WAIT_TIMEOUT: Duration = Duration::from_secs(1);

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
            // `atlasd` is the owner of this process. If a bounded shutdown future is
            // cancelled or the owning session is otherwise dropped, never detach Lean.
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

            // JSON-RPC requests and notifications must be classified before looking at
            // `id`. Lean 4.30 sends client requests such as workspace/inlayHint/refresh
            // with numeric ids while an Atlas request is in flight. Matching only on id
            // can therefore deserialize the server request's absent result as our result
            // (`hello: null`) and also leaves Lean waiting forever for its response.
            if let Some(method) = msg.get("method").and_then(Value::as_str) {
                if let Some(server_id) = msg.get("id").cloned() {
                    self.reply_to_server_request(server_id, method).await?;
                }
                // Notifications have no response. Both kinds are out-of-band relative
                // to the one client request this transport is synchronously awaiting.
                continue;
            }

            if !is_response_for(&msg, id) {
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

    async fn reply_to_server_request(
        &mut self,
        id: Value,
        method: &str,
    ) -> Result<(), TransportError> {
        // Lean currently uses refresh/progress/capability requests here. The LSP methods
        // below either have a null result or, for workspace/configuration, a list result.
        // Unknown requests get a null result rather than being dropped: blocking Lean's
        // server request queue is more damaging than advertising this intentionally small
        // headless-client capability surface.
        let result = match method {
            "workspace/configuration" => json!([]),
            _ => Value::Null,
        };
        self.write(&json!({"jsonrpc":"2.0","id":id,"result":result}))
            .await
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
        // Try the LSP shutdown/exit sequence, but never let a silent or wedged Lean
        // process escape ownership. `kill_on_drop(true)` is the final cancellation guard;
        // the explicit kill below handles a child that ignores `exit` while this future
        // continues to run normally.
        let graceful = tokio::time::timeout(GRACEFUL_SHUTDOWN_TIMEOUT, async {
            let _: Value = self.request("shutdown", Value::Null).await?;
            self.notify("exit", Value::Null).await?;
            Ok::<(), TransportError>(())
        })
        .await;

        let exited = matches!(
            tokio::time::timeout(EXIT_WAIT_TIMEOUT, self.child.wait()).await,
            Ok(Ok(_))
        );
        if !exited {
            let _ = self.child.kill().await;
            let _ = self.child.wait().await;
        }

        match graceful {
            Ok(result) => result,
            // A timeout is a cleanup condition, not a reason to leave a child alive.
            // The child has already been force-reaped above.
            Err(_) => Ok(()),
        }
    }
}

fn is_response_for(message: &Value, id: u64) -> bool {
    message.get("method").is_none() && message.get("id").and_then(Value::as_u64) == Some(id)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_request_cannot_alias_inflight_response_id() {
        let refresh = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "workspace/inlayHint/refresh",
            "params": null
        });
        assert!(!is_response_for(&refresh, 1));

        let response = json!({"jsonrpc": "2.0", "id": 1, "result": null});
        assert!(is_response_for(&response, 1));
    }
}
