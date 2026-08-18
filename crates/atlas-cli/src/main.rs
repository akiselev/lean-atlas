use atlas_client::{AtlasClient, ClientError};
use atlas_daemon_protocol::{
    CloseDocumentRequest, Command, DocumentRequest, LeanLaunch, OpenProjectRequest,
    ProjectMutationRequest, ProjectRequest, ResponsePayload,
};
use std::{env, path::Path};

const USAGE: &str = r#"usage: atlas-cli <command> [args]

live daemon commands:
  ping
  open-project <root>
  status <project-id>
  open-document <project-id> <uri> <file> <version> [lean-generation]
  change-document <project-id> <uri> <file> <version> [lean-generation]
  close-document <project-id> <uri> [lean-generation]
  restart-lean <project-id> [lean-generation]
  close-project <project-id> [lean-generation]
  daemon-restart
  daemon-stop
  daemon-repair

Lean launch defaults for open-project:
  ATLAS_LEAN_BIN       required (for example /path/to/lean)
  ATLAS_LEAN_PLUGIN    optional; adds --plugin=<path>
  ATLAS_LEAN_ROOT_URI  optional; defaults to file://<canonical-root>
  ATLAS_STORE_PATH     optional persistent SQLite path
  ATLASD_BIN           optional atlasd executable override

The legacy `atlas <query> <slice.jsonl> ...` binary remains the explicit static-export path.
"#;

fn arg<'a>(args: &'a [String], index: usize, name: &str) -> Result<&'a str, String> {
    args.get(index)
        .map(String::as_str)
        .ok_or_else(|| format!("missing {name}\n\n{USAGE}"))
}

fn generation(value: Option<&String>) -> Result<Option<u64>, String> {
    value
        .map(|value| {
            value
                .parse::<u64>()
                .map_err(|_| format!("invalid Lean generation `{value}`"))
        })
        .transpose()
}

fn default_launch(root: &str) -> Result<LeanLaunch, String> {
    let program = env::var("ATLAS_LEAN_BIN")
        .map_err(|_| "ATLAS_LEAN_BIN is required for open-project".to_string())?;
    let mut args = vec!["--server".into()];
    if let Ok(plugin) = env::var("ATLAS_LEAN_PLUGIN") {
        args.push(format!("--plugin={plugin}"));
    }
    let root_uri = match env::var("ATLAS_LEAN_ROOT_URI") {
        Ok(uri) => uri,
        Err(_) => {
            let canonical = std::fs::canonicalize(root)
                .map_err(|error| format!("cannot canonicalize {root}: {error}"))?;
            format!("file://{}", canonical.to_string_lossy())
        }
    };
    Ok(LeanLaunch {
        program,
        args,
        root_uri,
    })
}

fn print_payload(payload: ResponsePayload) -> Result<(), String> {
    println!(
        "{}",
        serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn remote_error(error: ClientError) -> String {
    match error {
        ClientError::Remote(remote) => serde_json::to_string_pretty(&remote)
            .unwrap_or_else(|_| format!("{remote:?}")),
        other => other.to_string(),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().skip(1).collect();
    let result = run(&args).await;
    if let Err(error) = result {
        eprintln!("atlas-cli: {error}");
        std::process::exit(1);
    }
    Ok(())
}

async fn run(args: &[String]) -> Result<(), String> {
    let command = args.first().map(String::as_str).ok_or_else(|| USAGE.to_string())?;
    let client = AtlasClient::discover().map_err(remote_error)?;
    match command {
        "ping" => print_payload(
            client
                .command(1, Command::Ping)
                .await
                .map_err(remote_error)?,
        ),
        "open-project" => {
            let root = arg(args, 1, "root")?;
            let launch = default_launch(root)?;
            print_payload(
                client
                    .command(
                        1,
                        Command::OpenProject(OpenProjectRequest {
                            root: root.into(),
                            lean: launch,
                            store_path: env::var("ATLAS_STORE_PATH").ok(),
                        }),
                    )
                    .await
                    .map_err(remote_error)?,
            )
        }
        "status" => print_payload(
            client
                .command(
                    1,
                    Command::ProjectStatus(ProjectRequest {
                        project_id: arg(args, 1, "project-id")?.into(),
                    }),
                )
                .await
                .map_err(remote_error)?,
        ),
        "open-document" | "change-document" => {
            let project_id = arg(args, 1, "project-id")?.to_string();
            let uri = arg(args, 2, "uri")?.to_string();
            let file = arg(args, 3, "file")?;
            let version = arg(args, 4, "version")?
                .parse::<i64>()
                .map_err(|_| "version must be an integer".to_string())?;
            let text = tokio::fs::read_to_string(Path::new(file))
                .await
                .map_err(|error| format!("{file}: {error}"))?;
            let request = DocumentRequest {
                project_id,
                uri,
                text,
                version,
                expected_lean_generation: generation(args.get(5))?,
            };
            let command = if command == "open-document" {
                Command::OpenDocument(request)
            } else {
                Command::ChangeDocument(request)
            };
            print_payload(client.command(1, command).await.map_err(remote_error)?)
        }
        "close-document" => print_payload(
            client
                .command(
                    1,
                    Command::CloseDocument(CloseDocumentRequest {
                        project_id: arg(args, 1, "project-id")?.into(),
                        uri: arg(args, 2, "uri")?.into(),
                        expected_lean_generation: generation(args.get(3))?,
                    }),
                )
                .await
                .map_err(remote_error)?,
        ),
        "restart-lean" | "close-project" => {
            let request = ProjectMutationRequest {
                project_id: arg(args, 1, "project-id")?.into(),
                expected_lean_generation: generation(args.get(2))?,
            };
            let command = if command == "restart-lean" {
                Command::RestartLean(request)
            } else {
                Command::CloseProject(request)
            };
            print_payload(client.command(1, command).await.map_err(remote_error)?)
        }
        "daemon-restart" => {
            println!("{}", client.restart_daemon().await.map_err(remote_error)?);
            Ok(())
        }
        "daemon-stop" => {
            println!("{:?}", client.stop().await.map_err(remote_error)?);
            Ok(())
        }
        "daemon-repair" => {
            println!("{:?}", client.repair().await.map_err(remote_error)?);
            Ok(())
        }
        _ => Err(USAGE.into()),
    }
}
