use atlas_client::{
    AtlasClient, ClientError,
    protocol::{
        CloseDocumentRequest, Command, ComposeQuery, DocumentRequest, GoalMatchQuery,
        InstancePathQuery, LeanLaunch, MinimalContextQuery, OpenProjectRequest,
        ProjectMutationRequest, ProjectRequest, SemanticQuery, SemanticQueryRequest, WhyNotQuery,
    },
};
use serde::de::DeserializeOwned;
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

fn decode_query<T: DeserializeOwned>(args: &Value) -> Result<T, String> {
    serde_json::from_value(args.clone()).map_err(|error| error.to_string())
}

async fn semantic_query(
    client: &AtlasClient,
    args: &Value,
    query: SemanticQuery,
) -> Result<atlas_client::protocol::ResponsePayload, String> {
    client
        .command(
            1,
            Command::Query(SemanticQueryRequest {
                project_id: required(args, "project_id")?.into(),
                expected_lean_generation: optional_generation(args)?,
                query,
            }),
        )
        .await
        .map_err(client_error)
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
        "atlas.close_document" => client
            .command(
                1,
                Command::CloseDocument(CloseDocumentRequest {
                    project_id: required(&args, "project_id")?.into(),
                    uri: required(&args, "uri")?.into(),
                    expected_lean_generation: optional_generation(&args)?,
                }),
            )
            .await
            .map_err(client_error)?,
        "atlas.goal_match" => {
            let query: GoalMatchQuery = decode_query(&args)?;
            semantic_query(&client, &args, SemanticQuery::GoalMatch(query)).await?
        }
        "atlas.why_not" => {
            let query: WhyNotQuery = decode_query(&args)?;
            semantic_query(&client, &args, SemanticQuery::WhyNot(query)).await?
        }
        "atlas.instance_path" => {
            let query: InstancePathQuery = decode_query(&args)?;
            semantic_query(&client, &args, SemanticQuery::InstancePath(query)).await?
        }
        "atlas.minimal_context" => {
            let query: MinimalContextQuery = decode_query(&args)?;
            semantic_query(&client, &args, SemanticQuery::MinimalContext(query)).await?
        }
        "atlas.compose" => {
            let query: ComposeQuery = decode_query(&args)?;
            semantic_query(&client, &args, SemanticQuery::Compose(query)).await?
        }
        "atlas.restart_lean" | "atlas.close_project" => {
            let request = ProjectMutationRequest {
                project_id: required(&args, "project_id")?.into(),
                expected_lean_generation: optional_generation(&args)?,
            };
            let command = if name == "atlas.restart_lean" {
                Command::RestartLean(request)
            } else {
                Command::CloseProject(request)
            };
            client.command(1, command).await.map_err(client_error)?
        }
        _ => return Err(format!("unknown tool `{name}`")),
    };
    serde_json::to_value(payload).map_err(|error| error.to_string())
}

fn query_position_schema() -> Value {
    json!({
        "type":"object",
        "properties":{
            "line":{"type":"integer","minimum":0},
            "character":{"type":"integer","minimum":0}
        }
    })
}

fn tools() -> Value {
    let position = query_position_schema();
    json!([
        {"name":"atlas.ping","description":"Check the shared atlasd generation","inputSchema":{"type":"object","properties":{}}},
        {"name":"atlas.open_project","description":"Open or attach to a persistent Lean project session","inputSchema":{"type":"object","properties":{"root":{"type":"string"},"store_path":{"type":"string"}},"required":["root"]}},
        {"name":"atlas.status","description":"Inspect project, overlay, store and Lean generation state","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"}},"required":["project_id"]}},
        {"name":"atlas.open_document","description":"Publish an unsaved Lean document into the live overlay","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"uri":{"type":"string"},"text":{"type":"string"},"version":{"type":"integer"},"lean_generation":{"type":"integer"}},"required":["project_id","uri","text"]}},
        {"name":"atlas.change_document","description":"Replace an existing live overlay document","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"uri":{"type":"string"},"text":{"type":"string"},"version":{"type":"integer"},"lean_generation":{"type":"integer"}},"required":["project_id","uri","text"]}},
        {"name":"atlas.close_document","description":"Remove a document from the live overlay","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"uri":{"type":"string"},"lean_generation":{"type":"integer"}},"required":["project_id","uri"]}},
        {"name":"atlas.goal_match","description":"Lean-confirm which named declarations apply to a goal; rejected candidates retain structured obstructions","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"},"goal":{"type":"string"},"candidates":{"type":"array","items":{"type":"string"},"minItems":1},"position":position,"max_candidates":{"type":"integer","minimum":1},"max_matches":{"type":"integer","minimum":1}},"required":["project_id","goal","candidates"]}},
        {"name":"atlas.why_not","description":"Explain the first structured Lean obstruction preventing a candidate from applying to a goal","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"},"candidate":{"type":"string"},"goal":{"type":"string"},"position":position},"required":["project_id","candidate","goal"]}},
        {"name":"atlas.instance_path","description":"Run actual Lean typeclass synthesis and return the constructed instance term and dependencies","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"},"type_text":{"type":"string"},"position":position},"required":["project_id","type_text"]}},
        {"name":"atlas.minimal_context","description":"Search a bounded Pareto frontier of explicit, implicit and instance binders while replaying and checking each surviving proof in Lean","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"},"goal":{"type":"string"},"proof":{"type":"string"},"hypotheses":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"type_text":{"type":"string"},"kind":{"enum":["explicit","implicit","instance"]}},"required":["name","type_text"]}},"position":position,"max_evaluations":{"type":"integer","minimum":1}},"required":["project_id","goal","proof"]}},
        {"name":"atlas.compose","description":"Attempt a logical composition and mark it proved only after an independent Lean proof check","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"},"left":{"type":"string"},"right":{"type":"string"},"goal":{"type":"string"},"proof":{"type":"string"},"position":position},"required":["project_id","left","right","goal"]}},
        {"name":"atlas.restart_lean","description":"Restart the project Lean child and replay all live overlays","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"}},"required":["project_id"]}},
        {"name":"atlas.close_project","description":"Close a daemon-owned project session","inputSchema":{"type":"object","properties":{"project_id":{"type":"string"},"lean_generation":{"type":"integer"}},"required":["project_id"]}}
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
                stdout
                    .write_all(
                        format!(
                            "{}\n",
                            json!({"jsonrpc":"2.0","id":Value::Null,"error":{"code":-32700,"message":error.to_string()}})
                        )
                        .as_bytes(),
                    )
                    .await?;
                continue;
            }
        };
        let method = request.get("method").and_then(Value::as_str).unwrap_or("");
        let Some(id) = request.get("id").cloned() else {
            // MCP notifications have no response. Unknown notifications are
            // deliberately ignored rather than emitting a JSON-RPC error with
            // a null id.
            continue;
        };
        let response = match method {
            "initialize" => {
                json!({"jsonrpc":"2.0","id":id,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"atlas-mcp","version":env!("CARGO_PKG_VERSION")}}})
            }
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
