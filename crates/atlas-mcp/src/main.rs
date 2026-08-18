use atlas_client::{AtlasClient, ClientError};
use atlas_daemon_protocol::{
    Command, DocumentRequest, LeanLaunch, OpenProjectRequest, ProjectMutationRequest,
    ProjectRequest,
};
use serde_json::{Value, json};
use std::env;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

fn launch(root: &str) -> Result<LeanLaunch, String> {
    let program = env::var("ATLAS_LEAN_BIN")
        .map_err(|_| "ATLAS_LEAN_BIN is required for atlas.open_project".to_string())?;
    let mut args = vec!["--server".to_string()];
    if let Ok(plugin) = env::var("ATLAS_LEAN_PLUGIN") {
        args.push(format!("--plugin={plugin}"));
    }
    let root_uri = env::var("ATLAS_LEAN_ROOT_URI").unwrap_or_else(|_| format!("file://{root}"));
    Ok(LeanLaunch {
        program,
        args,
        root_uri,
    })
}

fn client_error(error: ClientError) -> String {
    match error {
        ClientError::Remote(remote) => {
            serde_json::to_string(&remote).unwrap_or_else(|_| format!("{remote:?}"))
        }
        other => other.to_string(),
    }
}

fn required<'a>(args: &'a Value, key: &str) -> Result<&'a str, String> {
    args.get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing string argument `{key}`"))
}

fn optional_generation(args: &Value) -> Result<Option<u64>, String> {
    match args.get("lean_generation") {
        None | Some(Value::Null) => Ok(None),
        Some(value) => value
            .as_u64()
            .map(Some)
            .ok_or_else(|| "lean_generation must be an unsigned integer".to_string()),
    }
}

async fn tool(client: &AtlasClient, name: &str, args: Value) -> Result<Value, String> {
    let payload = match name {
        "atlas.ping" => client
            .command(1, Command::Ping)
            .await
            .map_err(client_error)?,
        "atlas.open_project" => {
            let root = required(&args, "root")?;
            client
                .command(
                    1,
                    Command::OpenProject(OpenProjectRequest {
                        root: root.into(),
                        lean: launch(root)?,
                        store_path: args
                            .get("store_path")
                            .and_then(Value::as_str)
                            .map(str::to_string),
                    }),
                )
                .await
                .map_err(client_error)?
        }
        "atlas.status" => client
            .command(
                1,
                Command::ProjectStatus(ProjectRequest {
                    project_id: required(&args, "project_id")?.into(),
                }),
            )
            .await
            .map_err(client_error)?,
        "atlas.open_document" | "atlas.change_document" => {
            let request = DocumentRequest {
                project_id: required(&args, "project_id")?.into(),
                uri: required(&args, "uri")?.into(),
                text: required(&args, "text")?.into(),
                version: args.get("version").and_then(Value::as_i64).unwrap_or(1),
                expected_lean_generation: optional_generation(&args)?,
            };
            let command = if name == "atlas.open_document" {
                Command::OpenDocument(request)
            } else {
                Command::ChangeDocument(request)
            };
            client.command(1, command).await.map_err(client_error)?
        }
        "atlas.restart_lean" => client
            .command(
                1,
                Command::RestartLean(ProjectMutationRequest {
                    project_id: required(&args, "project_id")?.into(),
                    expected_lean_generation: optional_generation(&args)?,
                }),
            )
            .await
            .map_err(client_error)?,
        _ => return Err(format!("unknown tool `{name}`")),
    };
    serde_json::to_value(payload).map_err(|error| error.to_string())
}

fn tools() -> Value {
    json!([
        {"name":"atlas.ping","description":"Check the shared atlasd generation","inputSchema":{"type":"object","properties":{}}},
        {"name":"atlas.open_project","description":"Open or attach to a persistent Lean project session","inputSchema":{"type":"object","properties":{"root":{"type":"string"},"store_path":{"type":"string"}},"required":["root"]}},
        {"name":"atlas.status","description":"Inspect project, overlay, store and Lean generation state","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"}},"required":["project_id"]}},
        {"name":"atlas.open_document","description":"Publish an unsaved Lean document into the live overlay","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"uri":{"type":"string"},"text":{"type":"string"},"version":{"type":"integer"},"lean_generation":{"type":"integer"}},"required":["project_id","uri","text"]}},
        {"name":"atlas.change_document","description":"Replace an existing live overlay document","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"uri":{"type":"string"},"text":{"type":"string"},"version":{"type":"integer"},"lean_generation":{"type":"integer"}},"required":["project_id","uri","text"]}},
        {"name":"atlas.restart_lean","description":"Restart the project Lean child and replay all live overlays","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"}},"required":["project_id"]}}
    ])
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = AtlasClient::discover()?;
    let stdin = tokio::io::stdin();
    let mut lines = BufReader::new(stdin).lines();
    let mut stdout = tokio::io::stdout();
    while let Some(line) = lines.next_line().await? {
        let request: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(error) => {
                stdout.write_all(format!("{}\n", json!({"jsonrpc":"2.0","id":Value::Null,"error":{"code":-32700,"message":error.to_string()}})).as_bytes()).await?;
                continue;
            }
        };
        let id = request.get("id").cloned().unwrap_or(Value::Null);
        let method = request.get("method").and_then(Value::as_str).unwrap_or("");
        let response = match method {
            "initialize" => {
                json!({"jsonrpc":"2.0","id":id,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"atlas-live-mcp","version":env!("CARGO_PKG_VERSION")}}})
            }
            "notifications/initialized" => continue,
            "tools/list" => json!({"jsonrpc":"2.0","id":id,"result":{"tools":tools()}}),
            "tools/call" => {
                let params = request.get("params").cloned().unwrap_or_else(|| json!({}));
                let name = params.get("name").and_then(Value::as_str).unwrap_or("");
                let args = params
                    .get("arguments")
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                match tool(&client, name, args).await {
                    Ok(value) => {
                        json!({"jsonrpc":"2.0","id":id,"result":{"content":[{"type":"text","text":serde_json::to_string_pretty(&value)?}],"isError":false}})
                    }
                    Err(error) => {
                        json!({"jsonrpc":"2.0","id":id,"result":{"content":[{"type":"text","text":error}],"isError":true}})
                    }
                }
            }
            _ => {
                json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":"method not found"}})
            }
        };
        stdout
            .write_all(serde_json::to_string(&response)?.as_bytes())
            .await?;
        stdout.write_all(b"\n").await?;
        stdout.flush().await?;
    }
    Ok(())
}
