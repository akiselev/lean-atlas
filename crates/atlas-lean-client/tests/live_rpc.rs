use atlas_lean_client::{ClientError, LeanClient, LeanCommand};
use atlas_lean_protocol::{
    BoolResponse, DefEqRequest, ElaborateRequest, ElaborateResponse, ExprRequest, ExprResponse,
    HelloRequest, HelloResponse, LookupDeclRequest, LookupDeclResponse, OracleResult, Position,
    ELABORATE, HELLO, INFER_TYPE, IS_DEFEQ, LOOKUP_DECL, PROTOCOL_VERSION,
};
use std::{env, fs, path::PathBuf};

fn required(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("{name} must be set for the live RPC test"))
}

fn value<T>(result: OracleResult<T>) -> T {
    match (result.value, result.failure) {
        (Some(value), None) => value,
        (_, failure) => panic!("Atlas RPC failure: {failure:?}"),
    }
}

#[tokio::test]
async fn typed_client_roundtrips_live_handles_and_stale_errors() {
    // This test is deliberately explicit/opt-in so normal `cargo test` does not require Lean.
    if env::var_os("ATLAS_RUN_LIVE_LEAN_RPC").is_none() {
        return;
    }

    let lean = required("ATLAS_LEAN_BIN");
    let plugin = required("ATLAS_LEAN_PLUGIN");
    let fixture = PathBuf::from(required("ATLAS_LEAN_FIXTURE"));
    let working_dir = PathBuf::from(required("ATLAS_LEAN_WORKDIR"));
    let root_uri = required("ATLAS_LEAN_ROOT_URI");
    let fixture_uri = required("ATLAS_LEAN_FIXTURE_URI");
    let text = fs::read_to_string(&fixture).expect("read Lean fixture");
    let position = Position {
        line: 2,
        character: 0,
    };

    let mut client = LeanClient::spawn(LeanCommand {
        program: lean,
        args: vec!["--server".into(), format!("--plugin={plugin}")],
        working_dir,
        root_uri,
    })
    .await
    .expect("spawn Lean server");
    client.set_position(position);
    client
        .open_document(fixture_uri, text, 1)
        .await
        .expect("open fixture and connect RPC session");

    let hello: HelloResponse = client
        .call(
            HELLO,
            &HelloRequest {
                atlas_protocol: PROTOCOL_VERSION.into(),
                requested_features: vec!["lookupDecl".into(), "isDefEq".into()],
                position,
            },
        )
        .await
        .expect("hello");
    assert_eq!(hello.atlas_protocol, PROTOCOL_VERSION);
    assert!(hello.lean_version.starts_with("4.30.0"));
    assert!(hello.features.iter().any(|feature| feature == "lookupDecl"));
    assert!(hello.features.iter().any(|feature| feature == "isDefEq"));

    let lookup: OracleResult<LookupDeclResponse> = client
        .call(
            LOOKUP_DECL,
            &LookupDeclRequest {
                name: "double".into(),
                position,
            },
        )
        .await
        .expect("lookupDecl transport");
    let lookup = value(lookup);
    assert_eq!(lookup.name, "double");

    let inferred: OracleResult<ExprResponse> = client
        .call(
            INFER_TYPE,
            &ExprRequest {
                expr: lookup.expression,
                position,
            },
        )
        .await
        .expect("inferType transport");
    let inferred = value(inferred);
    assert!(inferred.pretty.contains("Nat"), "{}", inferred.pretty);

    let lhs: OracleResult<ElaborateResponse> = client
        .call(
            ELABORATE,
            &ElaborateRequest {
                text: "double 2".into(),
                expected: None,
                position,
            },
        )
        .await
        .expect("elaborate lhs transport");
    let lhs = value(lhs);
    let rhs: OracleResult<ElaborateResponse> = client
        .call(
            ELABORATE,
            &ElaborateRequest {
                text: "(4 : Nat)".into(),
                expected: None,
                position,
            },
        )
        .await
        .expect("elaborate rhs transport");
    let rhs = value(rhs);

    for (left, right) in [(lhs.expr, rhs.expr), (rhs.expr, lhs.expr)] {
        let equal: OracleResult<BoolResponse> = client
            .call(
                IS_DEFEQ,
                &DefEqRequest {
                    lhs: left,
                    rhs: right,
                    position,
                },
            )
            .await
            .expect("isDefEq transport");
        assert!(value(equal).value);
    }

    // Release a handle that has been served exactly once, then prove that the Rust client
    // maps Lean's native decode error into the typed stale-handle error promised by M4.
    client
        .release([lhs.expr.0])
        .await
        .expect("release lhs expression");
    let stale: Result<OracleResult<ExprResponse>, ClientError> = client
        .call(
            INFER_TYPE,
            &ExprRequest {
                expr: lhs.expr,
                position,
            },
        )
        .await;
    assert!(matches!(stale, Err(ClientError::StaleHandle)));

    client
        .release([
            lookup.declaration.0,
            lookup.expression.0,
            lookup.type_expr.0,
            inferred.expr.0,
            lhs.type_expr.0,
            rhs.expr.0,
            rhs.type_expr.0,
        ])
        .await
        .expect("release remaining handles");
    client.shutdown().await.expect("shutdown Lean server");
}
