use atlas_client::Client;
use atlas_daemon_protocol::{Request, Response};
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

const MCP_VERSION: &str = "2024-11-05";

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let atlasd = std::env::var("ATLASD").unwrap_or_else(|_| "atlasd".into());
    let client = match Client::new(atlasd) {
        Ok(client) => client,
        Err(error) => {
            eprintln!("atlas-live-mcp: {error}");
            return;
        }
    };
    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    let mut stdout = tokio::io::stdout();
    while let Ok(Some(line)) = lines.next_line().await {
        if line.trim().is_empty() {
            continue;
        }
        if let Some(response) = handle_line(&client, &line).await {
            if stdout.write_all(response.as_bytes()).await.is_err()
                || stdout.write_all(b"\n").await.is_err()
                || stdout.flush().await.is_err()
            {
                break;
            }
        }
    }
}

async fn handle_line(client: &Client, line: &str) -> Option<String> {
    let request: Value = match serde_json::from_str(line) {
        Ok(value) => value,
        Err(error) => {
            return Some(rpc_error(
                Value::Null,
                -32700,
                &format!("parse error: {error}"),
            ));
        }
    };
    let id = request.get("id").cloned()?;
    let method = request.get("method").and_then(Value::as_str).unwrap_or("");
    match method {
        "initialize" => Some(rpc_ok(
            id,
            json!({
                "protocolVersion": MCP_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "atlas-live-mcp", "version": env!("CARGO_PKG_VERSION")}
            }),
        )),
        "tools/list" => Some(rpc_ok(id, json!({"tools": tools()}))),
        "tools/call" => {
            let params = request.get("params").cloned().unwrap_or(Value::Null);
            Some(rpc_ok(id, tool_result(call_tool(client, &params).await)))
        }
        "ping" => Some(rpc_ok(id, json!({}))),
        other => Some(rpc_error(id, -32601, &format!("unknown method `{other}`"))),
    }
}

fn tools() -> Vec<Value> {
    vec![
        json!({
            "name": "atlasd_status",
            "description": "Inspect the shared atlasd daemon and every Lean project session/generation.",
            "inputSchema": {"type":"object","properties":{},"additionalProperties":false}
        }),
        json!({
            "name": "atlasd_request",
            "description": "Send one typed atlasd protocol request. Use session generations returned by ensure/status for every handle-bearing Lean oracle call.",
            "inputSchema": {
                "type":"object",
                "properties": {
                    "request": {"type":"object","description":"An atlas-daemon-protocol Request object including its op tag."}
                },
                "required":["request"],
                "additionalProperties":false
            }
        }),
    ]
}

async fn call_tool(client: &Client, params: &Value) -> Result<String, String> {
    let name = params
        .get("name")
        .and_then(Value::as_str)
        .ok_or_else(|| "tools/call requires a tool name".to_string())?;
    let arguments = params
        .get("arguments")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let request = match name {
        "atlasd_status" => Request::Status,
        "atlasd_request" => serde_json::from_value(
            arguments
                .get("request")
                .cloned()
                .ok_or_else(|| "atlasd_request requires arguments.request".to_string())?,
        )
        .map_err(|error| format!("invalid atlasd request: {error}"))?,
        other => return Err(format!("unknown tool `{other}`")),
    };
    let response = client
        .call(request)
        .await
        .map_err(|error| error.to_string())?;
    serde_json::to_string_pretty(&response).map_err(|error| error.to_string())
}

fn tool_result(result: Result<String, String>) -> Value {
    match result {
        Ok(text) => json!({
            "content": [{"type":"text","text":text}],
            "isError": false
        }),
        Err(text) => json!({
            "content": [{"type":"text","text":text}],
            "isError": true
        }),
    }
}

fn rpc_ok(id: Value, result: Value) -> String {
    json!({"jsonrpc":"2.0","id":id,"result":result}).to_string()
}

fn rpc_error(id: Value, code: i64, message: &str) -> String {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}}).to_string()
}

#[allow(dead_code)]
fn _assert_response_is_serializable(response: &Response) -> Value {
    serde_json::to_value(response).expect("Response is serializable")
}
