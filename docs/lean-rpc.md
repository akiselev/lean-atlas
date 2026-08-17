# Live Lean semantic RPC

Atlas v2 keeps Lean as a live semantic coprocessor rather than reconstructing elaboration
semantics from JSONL.

## Packages

- `lean/` is the existing portable extractor. It remains a supported export/fallback path.
- `lean-server/` builds the `AtlasServer:shared` plugin against an explicit Lean toolchain.
- `atlas-lean-protocol` contains versioned Rust wire contracts.
- `atlas-lean-client` owns a long-lived `lean --server` process and Lean RPC session.

## Starting the server

Build the plugin:

```sh
cd lean-server
lake build AtlasServer:shared
```

Run Lean's language server from the target project, passing the resulting shared library with
the current Lean plugin syntax:

```text
lake env lean --server --plugin=/absolute/path/to/libAtlasServer.so
```

The Rust client deliberately accepts a caller-configured `std::process::Command`; it does not
assume where the plugin was materialized or which Lake project should supply the environment.

## RPC lifecycle

1. JSON-RPC `initialize` / `initialized`.
2. `textDocument/didOpen` for the file whose environment/context should be queried.
3. `$/lean/rpc/connect` to obtain a session ID.
4. `$/lean/rpc/call` using methods below.
5. `$/lean/rpc/keepAlive` while a session is idle.
6. `$/lean/rpc/release` for no-longer-needed remote references.

A server restart or RPC reconnect invalidates every outstanding reference. Atlas must never
persist an RPC reference as corpus identity.

## v1 methods

- `Atlas.Server.hello`
- `Atlas.Server.lookupDeclaration`
- `Atlas.Server.usedConstants`
- `Atlas.Server.inferType`
- `Atlas.Server.whnf`
- `Atlas.Server.defEq`

`lookupDeclaration` returns the declaration's type as a Lean `WithRpcRef Expr`; subsequent
operations consume that reference without serializing the full expression into Rust.

`inferType`, `whnf`, and `defEq` execute in the chosen file snapshot using Lean's own `MetaM`.
They therefore respect the actual environment/options at that snapshot instead of an Atlas
approximation.

The v1 operations intentionally work with global/closed expression refs. Source-local terms,
metavariables, tactic states, and `InfoTree` contexts are the next RPC layer and will carry their
own context handles rather than pretending an `Expr` alone is sufficient.
