mod transport;

use atlas_lean_protocol::{Position, RpcRef};
use serde::{de::DeserializeOwned, Serialize};
use serde_json::{json, Value};
use thiserror::Error;
pub use transport::{LeanCommand, TransportError};
use transport::Transport;

#[derive(Debug, Error)]
pub enum ClientError {
    #[error(transparent)]
    Transport(#[from] TransportError),
    #[error("Lean RPC session is stale; reconnect and discard all handles")]
    StaleEnvironment,
    #[error("Lean RPC handle is stale")]
    StaleHandle,
}

pub struct LeanClient {
    transport: Transport,
    uri: String,
    session_id: u64,
    position: Position,
    version: i64,
}

impl LeanClient {
    pub async fn spawn(command: LeanCommand) -> Result<Self, ClientError> {
        let transport = Transport::spawn(&command).await?;
        Ok(Self { transport, uri: String::new(), session_id: 0, position: Position::default(), version: 0 })
    }

    pub async fn open_document(&mut self, uri: impl Into<String>, text: impl Into<String>, version: i64) -> Result<(), ClientError> {
        self.uri = uri.into();
        self.version = version;
        self.transport.notify("textDocument/didOpen", json!({
            "textDocument": {"uri": self.uri, "languageId": "lean4", "version": version, "text": text.into()}
        })).await?;
        self.connect().await
    }

    pub async fn change_document(&mut self, text: impl Into<String>, version: i64) -> Result<(), ClientError> {
        self.version = version;
        self.transport.notify("textDocument/didChange", json!({
            "textDocument": {"uri": self.uri, "version": version}, "contentChanges": [{"text": text.into()}]
        })).await?;
        Ok(())
    }

    pub fn set_position(&mut self, position: Position) { self.position = position; }
    pub fn position(&self) -> Position { self.position }
    pub fn document_version(&self) -> i64 { self.version }
    pub fn session_id(&self) -> u64 { self.session_id }
    pub async fn reconnect(&mut self) -> Result<(), ClientError> { self.connect().await }

    async fn connect(&mut self) -> Result<(), ClientError> {
        #[derive(serde::Deserialize)]
        struct Connected { #[serde(rename = "sessionId")] session_id: u64 }
        let connected: Connected = self.transport.request("$/lean/rpc/connect", json!({"uri": self.uri})).await?;
        self.session_id = connected.session_id;
        Ok(())
    }

    pub async fn keep_alive(&mut self) -> Result<(), ClientError> {
        self.transport.notify("$/lean/rpc/keepAlive", json!({"uri":self.uri,"sessionId":self.session_id})).await?;
        Ok(())
    }

    pub async fn call<P: Serialize, R: DeserializeOwned>(&mut self, method: &str, params: &P) -> Result<R, ClientError> {
        self.keep_alive().await?;
        let encoded = serde_json::to_value(params).map_err(TransportError::Json)?;
        let outer = json!({
            "textDocument": {"uri": self.uri},
            "position": {"line": self.position.line, "character": self.position.character},
            "sessionId": self.session_id, "method": method, "params": encoded
        });
        match self.transport.request("$/lean/rpc/call", outer).await {
            Ok(value) => Ok(value),
            Err(TransportError::Rpc { message, .. }) if message.contains("Outdated RPC session") => Err(ClientError::StaleEnvironment),
            Err(TransportError::Rpc { message, .. }) if message.contains("RPC reference") && message.contains("not valid") => Err(ClientError::StaleHandle),
            Err(error) => Err(ClientError::Transport(error)),
        }
    }

    pub async fn release(&mut self, refs: impl IntoIterator<Item = RpcRef>) -> Result<(), ClientError> {
        let refs = refs.into_iter().map(|r| json!({"__rpcref":r.id})).collect::<Vec<Value>>();
        self.transport.notify("$/lean/rpc/release", json!({"uri":self.uri,"sessionId":self.session_id,"refs":refs})).await?;
        Ok(())
    }

    pub async fn shutdown(self) -> Result<(), ClientError> { self.transport.shutdown().await?; Ok(()) }
}
