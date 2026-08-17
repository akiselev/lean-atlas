//! Blocking client for Lean's language-server JSON-RPC transport and Atlas RPC methods.
//!
//! The process is intentionally long lived: callers import/elaborate a project once and then
//! issue small semantic requests. Large Lean expressions remain server-side as RPC refs.

use atlas_lean_protocol::{
    DefEqRequest, DefEqResponse, ExprRequest, ExprResponse, HelloRequest, HelloResponse,
    LookupDeclarationRequest, LookupDeclarationResponse, Position, UsedConstantsResponse,
    DEF_EQ_METHOD, HELLO_METHOD, INFER_TYPE_METHOD, LOOKUP_DECLARATION_METHOD, PROTOCOL_VERSION,
    USED_CONSTANTS_METHOD, WHNF_METHOD,
};
use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ClientError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Lean JSON-RPC error {code}: {message}")]
    Server { code: i64, message: String },
    #[error("protocol error: {0}")]
    Protocol(String),
}

pub type Result<T, E = ClientError> = std::result::Result<T, E>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RpcSession {
    pub uri: String,
    pub session_id: u64,
}

pub struct LeanServer {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

impl LeanServer {
    /// Spawn a caller-configured Lean server command. The command should normally be
    /// `lake env lean --server --plugin=/path/to/libAtlasServer.so` from the target project.
    pub fn spawn(command: &mut Command) -> Result<Self> {
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| ClientError::Protocol("Lean server stdin is unavailable".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| ClientError::Protocol("Lean server stdout is unavailable".into()))?;
        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            next_id: 1,
        })
    }

    pub fn initialize(&mut self, root_uri: Option<&str>) -> Result<Value> {
        let result = self.request(
            "initialize",
            json!({
                "processId": null,
                "rootUri": root_uri,
                "capabilities": {},
                "workspaceFolders": null
            }),
        )?;
        self.notify("initialized", json!({}))?;
        Ok(result)
    }

    pub fn did_open(&mut self, uri: &str, text: &str, version: i64) -> Result<()> {
        self.notify(
            "textDocument/didOpen",
            json!({
                "textDocument": {
                    "uri": uri,
                    "languageId": "lean4",
                    "version": version,
                    "text": text
                }
            }),
        )
    }

    pub fn did_change(&mut self, uri: &str, text: &str, version: i64) -> Result<()> {
        self.notify(
            "textDocument/didChange",
            json!({
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}]
            }),
        )
    }

    pub fn connect(&mut self, uri: &str) -> Result<RpcSession> {
        let response = self.request("$/lean/rpc/connect", json!({"uri": uri}))?;
        let session_id = response
            .get("sessionId")
            .and_then(Value::as_u64)
            .ok_or_else(|| ClientError::Protocol("RPC connect response omitted sessionId".into()))?;
        Ok(RpcSession {
            uri: uri.to_owned(),
            session_id,
        })
    }

    pub fn keep_alive(&mut self, session: &RpcSession) -> Result<()> {
        self.notify(
            "$/lean/rpc/keepAlive",
            json!({"uri": session.uri, "sessionId": session.session_id}),
        )
    }

    pub fn release(&mut self, session: &RpcSession, refs: Vec<Value>) -> Result<()> {
        self.notify(
            "$/lean/rpc/release",
            json!({"uri": session.uri, "sessionId": session.session_id, "refs": refs}),
        )
    }

    pub fn hello(&mut self, session: &RpcSession, position: Position) -> Result<HelloResponse> {
        self.rpc_call(
            session,
            position,
            HELLO_METHOD,
            &HelloRequest {
                protocol: PROTOCOL_VERSION,
            },
        )
    }

    pub fn lookup_declaration(
        &mut self,
        session: &RpcSession,
        position: Position,
        name: impl Into<String>,
    ) -> Result<LookupDeclarationResponse> {
        self.rpc_call(
            session,
            position,
            LOOKUP_DECLARATION_METHOD,
            &LookupDeclarationRequest {
                position,
                name: name.into(),
            },
        )
    }

    pub fn used_constants(
        &mut self,
        session: &RpcSession,
        position: Position,
        expr: Value,
    ) -> Result<UsedConstantsResponse> {
        self.rpc_call(
            session,
            position,
            USED_CONSTANTS_METHOD,
            &ExprRequest { position, expr },
        )
    }

    pub fn infer_type(
        &mut self,
        session: &RpcSession,
        position: Position,
        expr: Value,
    ) -> Result<ExprResponse> {
        self.rpc_call(
            session,
            position,
            INFER_TYPE_METHOD,
            &ExprRequest { position, expr },
        )
    }

    pub fn whnf(
        &mut self,
        session: &RpcSession,
        position: Position,
        expr: Value,
    ) -> Result<ExprResponse> {
        self.rpc_call(
            session,
            position,
            WHNF_METHOD,
            &ExprRequest { position, expr },
        )
    }

    pub fn def_eq(
        &mut self,
        session: &RpcSession,
        position: Position,
        lhs: Value,
        rhs: Value,
    ) -> Result<DefEqResponse> {
        self.rpc_call(
            session,
            position,
            DEF_EQ_METHOD,
            &DefEqRequest {
                position,
                lhs,
                rhs,
            },
        )
    }

    pub fn rpc_call<Req: Serialize, Resp: DeserializeOwned>(
        &mut self,
        session: &RpcSession,
        position: Position,
        method: &str,
        params: &Req,
    ) -> Result<Resp> {
        let response = self.request(
            "$/lean/rpc/call",
            json!({
                "textDocument": {"uri": session.uri},
                "position": position,
                "sessionId": session.session_id,
                "method": method,
                "params": serde_json::to_value(params)?
            }),
        )?;
        Ok(serde_json::from_value(response)?)
    }

    pub fn shutdown(mut self) -> Result<()> {
        let _ = self.request("shutdown", Value::Null)?;
        self.notify("exit", Value::Null)?;
        let _ = self.child.wait()?;
        Ok(())
    }

    fn notify(&mut self, method: &str, params: Value) -> Result<()> {
        write_message(
            &mut self.stdin,
            &json!({"jsonrpc": "2.0", "method": method, "params": params}),
        )
    }

    fn request(&mut self, method: &str, params: Value) -> Result<Value> {
        let id = self.next_id;
        self.next_id += 1;
        write_message(
            &mut self.stdin,
            &json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}),
        )?;
        loop {
            let message = read_message(&mut self.stdout)?;
            if message.get("id").and_then(Value::as_u64) != Some(id) {
                // Lean can publish diagnostics/progress while a request is outstanding. Those
                // messages are intentionally ignored by this low-level semantic client; a
                // frontend can add a notification sink without changing request ordering.
                continue;
            }
            if let Some(error) = message.get("error") {
                return Err(ClientError::Server {
                    code: error.get("code").and_then(Value::as_i64).unwrap_or(-1),
                    message: error
                        .get("message")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown Lean RPC error")
                        .to_owned(),
                });
            }
            return message
                .get("result")
                .cloned()
                .ok_or_else(|| ClientError::Protocol("JSON-RPC response omitted result".into()));
        }
    }
}

impl Drop for LeanServer {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = self.child.kill();
        }
    }
}

fn write_message(writer: &mut impl Write, value: &Value) -> Result<()> {
    let body = serde_json::to_vec(value)?;
    write!(writer, "Content-Length: {}\r\n\r\n", body.len())?;
    writer.write_all(&body)?;
    writer.flush()?;
    Ok(())
}

fn read_message(reader: &mut impl BufRead) -> Result<Value> {
    let mut content_length = None;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            return Err(ClientError::Protocol("Lean server closed stdout".into()));
        }
        if line == "\r\n" || line == "\n" {
            break;
        }
        if let Some(value) = line.strip_prefix("Content-Length:") {
            content_length = Some(
                value
                    .trim()
                    .parse::<usize>()
                    .map_err(|_| ClientError::Protocol("invalid Content-Length header".into()))?,
            );
        }
    }
    let length = content_length
        .ok_or_else(|| ClientError::Protocol("message omitted Content-Length".into()))?;
    let mut body = vec![0u8; length];
    reader.read_exact(&mut body)?;
    Ok(serde_json::from_slice(&body)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn lsp_framing_round_trips() {
        let message = json!({"jsonrpc": "2.0", "id": 7, "result": {"ok": true}});
        let mut bytes = Vec::new();
        write_message(&mut bytes, &message).unwrap();
        let mut reader = BufReader::new(Cursor::new(bytes));
        assert_eq!(read_message(&mut reader).unwrap(), message);
    }
}
