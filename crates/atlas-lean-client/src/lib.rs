mod transport;

use atlas_lean_protocol::{Position, RpcRef};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use serde_json::{Value, json};
use thiserror::Error;
use transport::Transport;
pub use transport::{LeanCommand, TransportError};

/// Lean's RPC session identifier is an opaque wire value. Lean 4.30 encodes the
/// `UInt64` session id as a JSON string in the v1 RPC wire format so JavaScript
/// clients do not lose integer precision. Keep compatibility with numeric ids as
/// well and, critically, send back the same representation we received.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum SessionId {
    Number(u64),
    String(String),
}

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
    session_id: SessionId,
    position: Position,
    version: i64,
}

impl LeanClient {
    pub async fn spawn(command: LeanCommand) -> Result<Self, ClientError> {
        let transport = Transport::spawn(&command).await?;
        Ok(Self {
            transport,
            uri: String::new(),
            session_id: SessionId::Number(0),
            position: Position::default(),
            version: 0,
        })
    }

    pub fn process_id(&self) -> Option<u32> {
        self.transport.process_id()
    }

    pub async fn open_document(
        &mut self,
        uri: impl Into<String>,
        text: impl Into<String>,
        version: i64,
    ) -> Result<(), ClientError> {
        self.uri = uri.into();
        self.version = version;
        self.transport
            .notify(
                "textDocument/didOpen",
                json!({
                    "textDocument": {"uri": self.uri, "languageId": "lean4", "version": version, "text": text.into()}
                }),
            )
            .await?;
        self.connect().await
    }

    /// Replace an already-open document by URI. This is the daemon-facing
    /// primitive: `atlasd` can retain multiple unsaved buffers in Lean even
    /// though the typed oracle client has one selected RPC document at a time.
    pub async fn change_document_at(
        &mut self,
        uri: impl Into<String>,
        text: impl Into<String>,
        version: i64,
    ) -> Result<(), ClientError> {
        self.uri = uri.into();
        self.version = version;
        self.transport
            .notify(
                "textDocument/didChange",
                json!({
                    "textDocument": {"uri": self.uri, "version": version}, "contentChanges": [{"text": text.into()}]
                }),
            )
            .await?;
        // Editing invalidates Lean's old RPC environment. Establish a fresh
        // session immediately so daemon clients never inherit a pre-edit handle
        // generation by accident.
        self.connect().await
    }

    pub async fn change_document(
        &mut self,
        text: impl Into<String>,
        version: i64,
    ) -> Result<(), ClientError> {
        let uri = self.uri.clone();
        self.change_document_at(uri, text, version).await
    }

    pub async fn close_document(&mut self, uri: impl Into<String>) -> Result<(), ClientError> {
        let uri = uri.into();
        self.transport
            .notify(
                "textDocument/didClose",
                json!({"textDocument": {"uri": uri}}),
            )
            .await?;
        if self.uri == uri {
            self.uri.clear();
            self.session_id = SessionId::Number(0);
            self.version = 0;
        }
        Ok(())
    }

    /// Select an already-open Lean document as the current RPC target without
    /// sending another `didOpen`. This keeps multi-document overlays distinct
    /// from the single document/session selected for typed RPC calls.
    pub async fn select_document(&mut self, uri: impl Into<String>) -> Result<(), ClientError> {
        self.uri = uri.into();
        self.connect().await
    }

    pub fn set_position(&mut self, position: Position) {
        self.position = position;
    }
    pub fn position(&self) -> Position {
        self.position
    }
    pub fn document_version(&self) -> i64 {
        self.version
    }
    pub fn session_id(&self) -> &SessionId {
        &self.session_id
    }
    pub async fn reconnect(&mut self) -> Result<(), ClientError> {
        self.connect().await
    }

    async fn connect(&mut self) -> Result<(), ClientError> {
        #[derive(Deserialize)]
        struct Connected {
            #[serde(rename = "sessionId")]
            session_id: SessionId,
        }
        let connected: Connected = self
            .transport
            .request("$/lean/rpc/connect", json!({"uri": self.uri}))
            .await?;
        self.session_id = connected.session_id;
        Ok(())
    }

    pub async fn keep_alive(&mut self) -> Result<(), ClientError> {
        self.transport
            .notify(
                "$/lean/rpc/keepAlive",
                json!({"uri":self.uri,"sessionId":self.session_id.clone()}),
            )
            .await?;
        Ok(())
    }

    pub async fn call<P: Serialize, R: DeserializeOwned>(
        &mut self,
        method: &str,
        params: &P,
    ) -> Result<R, ClientError> {
        self.keep_alive().await?;
        let encoded = serde_json::to_value(params).map_err(TransportError::Json)?;
        let outer = json!({
            "textDocument": {"uri": self.uri},
            "position": {"line": self.position.line, "character": self.position.character},
            "sessionId": self.session_id.clone(), "method": method, "params": encoded
        });
        match self.transport.request("$/lean/rpc/call", outer).await {
            Ok(value) => Ok(value),
            Err(TransportError::Rpc { message, .. })
                if message.contains("Outdated RPC session") =>
            {
                Err(ClientError::StaleEnvironment)
            }
            Err(TransportError::Rpc { message, .. })
                if message.contains("RPC reference") && message.contains("not valid") =>
            {
                Err(ClientError::StaleHandle)
            }
            Err(error) => Err(ClientError::Transport(error)),
        }
    }

    pub async fn release(
        &mut self,
        refs: impl IntoIterator<Item = RpcRef>,
    ) -> Result<(), ClientError> {
        let refs = refs
            .into_iter()
            .map(serde_json::to_value)
            .collect::<Result<Vec<Value>, _>>()
            .map_err(TransportError::Json)?;
        self.transport
            .notify(
                "$/lean/rpc/release",
                json!({"uri":self.uri,"sessionId":self.session_id.clone(),"refs":refs}),
            )
            .await?;
        Ok(())
    }

    pub async fn shutdown(self) -> Result<(), ClientError> {
        self.transport.shutdown().await?;
        Ok(())
    }
}
