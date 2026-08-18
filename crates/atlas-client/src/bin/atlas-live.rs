use atlas_client::Client;
use atlas_daemon_protocol::{
    DocumentOverlay, ProjectConfig, Request, Response, SessionToken, atlas_position::Position,
};
use serde_json::Value;
use std::{fs, process::ExitCode};

const USAGE: &str = r#"usage: atlas-live [--atlasd PATH] <command> ...

commands:
  status
  stop
  repair
  ensure <project> <workdir> <root-uri> <lean> <plugin>
  close <project>
  restart <project>
  open <project> <generation> <uri> <version> <file>
  change <project> <generation> <version> <file>
  call <project> <generation> <line> <character> <method> <json-params|@file>

`ensure` launches Lean as: <lean> --server --plugin=<plugin>.
The generation returned by `ensure` must accompany every handle-bearing request.
After a Lean restart, old generations are rejected before their handles reach Lean.
"#;

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("atlas-live: {error}");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<(), String> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let atlasd = if args.first().map(String::as_str) == Some("--atlasd") {
        if args.len() < 2 {
            return Err(USAGE.into());
        }
        let path = args.remove(1);
        args.remove(0);
        path
    } else {
        std::env::var("ATLASD").unwrap_or_else(|_| "atlasd".into())
    };
    let client = Client::new(atlasd).map_err(|error| error.to_string())?;
    let Some(command) = args.first().map(String::as_str) else {
        return Err(USAGE.into());
    };

    match command {
        "status" if args.len() == 1 => send(&client, Request::Status).await,
        "stop" if args.len() == 1 => {
            println!("{:?}", client.stop().await.map_err(|e| e.to_string())?);
            Ok(())
        }
        "repair" if args.len() == 1 => {
            println!("{:?}", client.repair().await.map_err(|e| e.to_string())?);
            Ok(())
        }
        "ensure" if args.len() == 6 => {
            let config = ProjectConfig {
                project_id: args[1].clone(),
                working_dir: args[2].clone(),
                root_uri: args[3].clone(),
                lean_program: args[4].clone(),
                lean_args: vec!["--server".into(), format!("--plugin={}", args[5])],
            };
            send(&client, Request::EnsureProject { config }).await
        }
        "close" if args.len() == 2 => {
            send(
                &client,
                Request::CloseProject {
                    project_id: args[1].clone(),
                },
            )
            .await
        }
        "restart" if args.len() == 2 => {
            send(
                &client,
                Request::RestartLean {
                    project_id: args[1].clone(),
                },
            )
            .await
        }
        "open" if args.len() == 6 => {
            let token = token(&args[1], &args[2])?;
            let version = parse(&args[4], "version")?;
            let text = fs::read_to_string(&args[5]).map_err(|e| e.to_string())?;
            send(
                &client,
                Request::OpenDocument {
                    token,
                    document: DocumentOverlay {
                        uri: args[3].clone(),
                        text,
                        version,
                    },
                },
            )
            .await
        }
        "change" if args.len() == 5 => {
            let token = token(&args[1], &args[2])?;
            let version = parse(&args[3], "version")?;
            let text = fs::read_to_string(&args[4]).map_err(|e| e.to_string())?;
            send(
                &client,
                Request::ChangeDocument {
                    token,
                    text,
                    version,
                },
            )
            .await
        }
        "call" if args.len() == 7 => {
            let token = token(&args[1], &args[2])?;
            let line = parse(&args[3], "line")?;
            let character = parse(&args[4], "character")?;
            let raw = if let Some(path) = args[6].strip_prefix('@') {
                fs::read_to_string(path).map_err(|e| e.to_string())?
            } else {
                args[6].clone()
            };
            let params: Value = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
            send(
                &client,
                Request::OracleCall {
                    token,
                    position: Position { line, character },
                    method: args[5].clone(),
                    params,
                },
            )
            .await
        }
        _ => Err(USAGE.into()),
    }
}

async fn send(client: &Client, request: Request) -> Result<(), String> {
    let response = client.call(request).await.map_err(|error| error.to_string())?;
    print_response(response)
}

fn token(project: &str, generation: &str) -> Result<SessionToken, String> {
    Ok(SessionToken {
        project_id: project.to_owned(),
        generation: parse(generation, "generation")?,
    })
}

fn parse<T: std::str::FromStr>(text: &str, name: &str) -> Result<T, String> {
    text.parse().map_err(|_| format!("invalid {name}: {text}"))
}

fn print_response(response: Response) -> Result<(), String> {
    println!(
        "{}",
        serde_json::to_string_pretty(&response).map_err(|error| error.to_string())?
    );
    Ok(())
}
