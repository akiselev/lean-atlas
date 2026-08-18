# M5 `atlasd` manual validation plan

This is an observational validation plan, not a substitute for `cargo test`. The validating agent must record the exact command, exit status, relevant stdout/stderr, observed process IDs/generations, and whether the observation matched the expectation. Do not mark a section complete merely because a command returned zero.

Commands marked **MUTATES** kill a process, change a source file, remove daemon state, or write the semantic store. Run them only in the disposable fixture/worktree described below.

## 0. Validation record

Create `tmp/m5-validation/<date>/` (gitignored or outside the repository) and tee command output into numbered files. Record:

- commit SHA under test;
- OS and architecture;
- Rust/Cargo versions;
- `lean --version`;
- `cat lean-server/lean-toolchain`;
- Atlas server plugin path;
- semantic-store path (`ATLAS_STORE_PATH`);
- every `atlasd` and Lean PID observed during crash/restart tests.

The expected Lean version for this milestone is exactly `4.30.0`.

## 1. Build and deterministic test gate

```bash
set -euo pipefail
cargo fmt --all -- --check
python scripts/check-deps.py
cargo test --workspace --exclude atlas-py
cargo check -p atlas-py

export PATH="$HOME/.elan/bin:$PATH"
export ELAN_TOOLCHAIN="$(cat lean-server/lean-toolchain)"
lean --version
(cd lean-server && lake build AtlasServer:shared)
```

Inspect, rather than infer:

- the dependency-layer check names no forbidden edge;
- `atlas-daemon-protocol`, `atlas-client`, and `atlasd` are actually compiled by the workspace command;
- the `atlas-lean-client` demux regression test is executed;
- the displayed Lean version is `4.30.0`.

## 2. Locate the plugin and prepare the fixture

```bash
PLUGIN="$(find lean-server/.lake/build -type f \( \
  -name 'libatlasServer_Atlas_Server_Plugin.so' -o \
  -name 'libatlasServer_Atlas_Server_Plugin.dylib' -o \
  -name 'atlasServer_Atlas_Server_Plugin.dll' -o \
  -name 'libatlasServer_Atlas_Server_Plugin.dll' \
\) -print -quit)"
PLUGIN="$(realpath "$PLUGIN")"
WORKDIR="$(realpath lean-server)"
FIXTURE="$(realpath lean-server/Fixtures/RpcSmoke.lean)"
ROOT_URI="$(python3 -c 'import pathlib; print(pathlib.Path("lean-server").resolve().as_uri())')"
FIXTURE_URI="$(python3 -c 'import pathlib; print(pathlib.Path("lean-server/Fixtures/RpcSmoke.lean").resolve().as_uri())')"
LEAN="$(command -v lean)"
ATLASD="$(realpath target/debug/atlasd)"
ATLAS_LIVE="$(realpath target/debug/atlas-live)"
export ATLASD
export ATLAS_STORE_PATH="$(mktemp -d)/atlas.sqlite3"
```

Build the two binaries first if necessary:

```bash
cargo build -p atlasd -p atlas-client --bins
```

## 3. Lean 4.30 JSON-RPC demux regression

Run the native and typed live RPC tests, not only the unit test:

```bash
python3 lean-server/tests/rpc_smoke.py "$LEAN" "$PLUGIN"

ATLAS_RUN_LIVE_LEAN_RPC=1 \
ATLAS_LEAN_BIN="$LEAN" \
ATLAS_LEAN_PLUGIN="$PLUGIN" \
ATLAS_LEAN_FIXTURE="$FIXTURE" \
ATLAS_LEAN_WORKDIR="$WORKDIR" \
ATLAS_LEAN_ROOT_URI="$ROOT_URI" \
ATLAS_LEAN_FIXTURE_URI="$FIXTURE_URI" \
  cargo test -p atlas-lean-client --test live_rpc -- --nocapture
```

Required observation: no `hello: null`, no hang after `workspace/inlayHint/refresh`, and the typed hello reports Lean `4.30.0`. This specifically validates that a server request with a numeric `id` is answered and cannot be mistaken for the in-flight Atlas response.

## 4. Startup-race convergence

First stop any prior test daemon:

```bash
"$ATLAS_LIVE" --atlasd "$ATLASD" stop || true
```

If that prior daemon owned a project, record its Lean child PID(s) before stopping it and verify every recorded PID is gone after `stop` returns. `Stopped { ... }` is not sufficient evidence if a `lean --server` process remains alive.

Then launch 32 competing clients:

```bash
seq 1 32 | xargs -P32 -I{} sh -c '"$0" --atlasd "$1" status' "$ATLAS_LIVE" "$ATLASD" \
  > /tmp/atlas-m5-race.out
```

Inspect the daemonkit state/process list and all 32 outputs. Required observations:

- all successful clients attach to one daemon generation;
- there is one long-lived `atlasd` service process, not 32;
- no stale socket/state error is emitted;
- a subsequent `status` returns immediately and reports the same generation.

## 5. One project, one Lean owner, live overlay

Ensure a project:

```bash
"$ATLAS_LIVE" --atlasd "$ATLASD" ensure rpc-smoke "$WORKDIR" "$ROOT_URI" "$LEAN" "$PLUGIN"
```

Record the returned project generation as `GEN`. Open the fixture:

```bash
GEN=1 # replace with the observed value
"$ATLAS_LIVE" --atlasd "$ATLASD" open rpc-smoke "$GEN" "$FIXTURE_URI" 1 "$FIXTURE"
```

Call the hello oracle using a params file to avoid shell quoting ambiguity. The protocol struct uses snake_case field names:

```bash
cat > /tmp/atlas-hello.json <<'JSON'
{"atlas_protocol":"2.0.0","requested_features":[],"position":{"line":2,"character":0}}
JSON
"$ATLAS_LIVE" --atlasd "$ATLASD" call rpc-smoke "$GEN" 2 0 Atlas.Server.hello @/tmp/atlas-hello.json
```

Use the exact method constant emitted by `atlas-lean-protocol` if it changes; do not change production code merely to fit this example command.

Required observations:

- `status` reports one `rpc-smoke` project and an open-document URI;
- only one Lean `--server` child belongs to this project;
- the oracle response is non-null and typed JSON;
- repeated calls keep the same project generation.

### Application-level RPC rejection must not restart Lean

Record the current Lean PID as `LEAN_PID` and current generation as `GEN`. Now deliberately send the previously reported camelCase/malformed hello request:

```bash
cat > /tmp/atlas-hello-bad.json <<'JSON'
{"atlasProtocol":"2.0.0","requestedFeatures":[],"position":{"line":2,"character":0}}
JSON
"$ATLAS_LIVE" --atlasd "$ATLASD" call rpc-smoke "$GEN" 2 0 Atlas.Server.hello @/tmp/atlas-hello-bad.json
"$ATLAS_LIVE" --atlasd "$ATLASD" status
```

Also call a deliberately unknown Atlas RPC method with otherwise valid JSON.

Required observations for both failures:

- the service response is `oracle_failure` (or a more specific non-restart request/oracle error), not `lean_restarted`;
- the error preserves Lean's useful JSON-RPC diagnostic, such as `Cannot decode params` or unknown-method information;
- project generation is still exactly `GEN`;
- `LEAN_PID` is still alive and is still the project's Lean process;
- a subsequent valid `Atlas.Server.hello` call succeeds with the same generation and PID.

A JSON-RPC error response proves Lean is alive enough to reject the request. Do not classify it as transport death.

### Overlay change

**MUTATES disposable copy only.** Copy the fixture, alter a declaration without saving it into the original repository fixture, and send the complete changed text with `change`:

```bash
cp "$FIXTURE" /tmp/RpcSmoke.overlay.lean
# edit /tmp/RpcSmoke.overlay.lean
"$ATLAS_LIVE" --atlasd "$ATLASD" change rpc-smoke "$GEN" 2 /tmp/RpcSmoke.overlay.lean
```

Query the changed declaration. Required observation: Lean sees the supplied overlay text even though the repository file on disk is unchanged.

## 6. Concurrent CLI and MCP clients share the same daemon

Start the daemon-backed MCP frontend with `ATLASD="$ATLASD" target/debug/atlas-live-mcp` and perform the normal MCP handshake. Call `atlasd_status` while simultaneously running:

```bash
for i in $(seq 1 20); do
  "$ATLAS_LIVE" --atlasd "$ATLASD" status &
done
wait
```

Required observations:

- MCP and CLI report the same project generation;
- no second `atlasd` appears;
- the project remains usable after the concurrency burst;
- MCP `atlasd_request` can issue the same typed protocol requests as the CLI without bypassing session-generation checks.

## 7. Explicit Lean restart invalidates old handles

Acquire at least one real Lean expression/declaration handle through `lookupDecl` and record the current generation `GEN`.

```bash
"$ATLAS_LIVE" --atlasd "$ATLASD" restart rpc-smoke
```

Record the new generation as `NEW_GEN` and assert `NEW_GEN > GEN`. Then deliberately repeat an oracle request with the old token/handle.

Required observation: Atlas returns `stale_session` before forwarding the request to Lean. It must not return a result, reinterpret the old handle, or silently retry the handle against the new Lean process.

Now reopen/reuse the automatically replayed overlay with `NEW_GEN` and acquire fresh handles. Required observation: fresh handles work.

## 8. Unexpected Lean crash: structured degradation + restart

Find the Lean child owned by `rpc-smoke` and kill only that child.

**MUTATES process state.**

```bash
ps -eo pid,ppid,args | grep '[l]ean.*--server'
kill -KILL <LEAN_PID>
```

Issue an oracle call with the pre-crash generation.

Required observations:

- the call fails with `lean_restarted`, including old and new generations and a cause;
- `atlasd` itself stays alive;
- a new Lean child is spawned;
- the in-memory document overlay is replayed into the new child;
- the old generation is rejected on the next request;
- a call using the new generation and newly acquired handles succeeds.

If respawn itself fails (for example, temporarily rename the disposable Lean executable wrapper), `status` must show the project as `degraded` with a diagnostic instead of pretending the oracle is healthy.

## 9. Daemon crash and daemonkit repair

Record daemon and Lean PIDs. Kill `atlasd` abruptly.

**MUTATES process state.**

```bash
kill -KILL <ATLASD_PID>
```

Then run:

```bash
"$ATLAS_LIVE" --atlasd "$ATLASD" repair
"$ATLAS_LIVE" --atlasd "$ATLASD" status
```

Required observations:

- daemonkit repairs only stale state it owns;
- a fresh daemon generation starts successfully;
- the old authenticated endpoint is not reused as authoritative state;
- no orphaned Atlas daemon survives;
- project sessions are process-local and therefore must be re-ensured after an atlasd crash; semantic facts in the SQLite store persist.

The abrupt-kill case relies on stdio/process ownership cleanup and is distinct from the graceful-stop acceptance test below.

## 10. Persistent semantic store survives daemon generations

**MUTATES semantic test DB.** Insert a fixture fact through the existing `atlas-store` test/import path using `ATLAS_STORE_PATH`, stop/restart the daemon, and read the same fact back. Also inspect the SQLite file directly:

```bash
sqlite3 "$ATLAS_STORE_PATH" '.tables'
sqlite3 "$ATLAS_STORE_PATH" 'select count(*) from facts;'
```

Required observation: daemon lifecycle state is ephemeral, while semantic data remains in the configured SQLite database. Do not treat daemonkit's private runtime directory as the semantic database.

## 11. Static-slice compatibility gate

The M5 migration must not make existing exports unusable. Produce or reuse a known JSONL slice and run representative legacy queries exactly as before:

```bash
cargo run -p atlas --bin atlas -- stats <slice.jsonl>
cargo run -p atlas --bin atlas -- why <slice.jsonl> <from> <to>
cargo run -p atlas --bin atlas -- similar <slice.jsonl> <decl>
cargo run -p atlas --bin atlas -- honesty <slice.jsonl>
```

Compare output against the same slice on `master` or a stored golden. Required observation: M5 adds the live daemon path; it does not reinterpret static slices.

## 12. Failure/adversarial matrix

Run each case and retain the response:

| Fault | Required result |
|---|---|
| nonexistent Lean executable in `ensure` | project is `degraded`; daemon remains healthy |
| wrong plugin path | structured project degradation, not daemon crash |
| old session generation after restart | `stale_session` |
| malformed daemon JSON frame | `invalid_request`; connection can close without killing daemon |
| protocol version mismatch | `protocol_mismatch` |
| 64 MiB+ frame | rejected by framing limit |
| bad params / Lean JSON-RPC decode rejection | `oracle_failure`; generation and Lean PID unchanged |
| unknown Lean RPC method / ordinary RPC error | `oracle_failure`; generation and Lean PID unchanged |
| kill Lean during oracle call | `lean_restarted`; generation increments |
| graceful `atlas-live stop` | daemon exits and all Lean children owned by its project sessions are gone |
| kill atlasd | daemonkit `repair` + `ensure` can recover |
| 32 simultaneous starters | one daemon generation |
| simultaneous CLI and MCP status | same daemon/project generation |

## 13. Bug-regression disposition from the M4 audit

For this PR, explicitly validate the fixes that compose with M5:

1. Lean JSON-RPC messages are classified by `method` before `id`; server requests are answered rather than consumed as Atlas responses.
2. CI and manual live tests use `lean-server/lean-toolchain` / Lean `4.30.0`, not an ambient elan default.
3. Lean process restart changes the Atlas project generation, and all handle-bearing requests require that generation.
4. Dead stdio, broken transport/protocol synchronization, and stale Lean sessions become structured `lean_restarted`/`lean_degraded` service errors; ordinary JSON-RPC error responses remain `oracle_failure` and do not bump generation.
5. Graceful daemon shutdown explicitly drains project sessions and reaps every owned Lean child before daemonkit reports the service stopped.
6. Existing store warrant/immutability tests and static-slice compatibility remain green.

Do not opportunistically alter deeper M4 oracle semantics (`apply`, `unify`, proof meaning, declaration snapshot policy) merely to make this milestone green. Those require independent semantic fixtures and should be handled as focused follow-ups from the audit rather than hidden inside daemon plumbing.

The pre-existing store warrant holes are also not closed by M5 merely because store tests are green: empty derived provenance, missing Oracle/Formal evidence linkage, missing `relation_types` enforcement, and inconsistent warrant ordering remain separate P1 work.

## 14. Completion evidence

Before declaring M5 complete, run a final graceful-stop observation with at least one live project:

```bash
# Record the atlasd PID and only the Lean --server children owned by it.
ATLASD_PID="$(pgrep -f "$ATLASD" | head -n1)"
LEAN_PIDS="$(ps -eo pid=,ppid=,args= | awk -v p="$ATLASD_PID" '$2 == p && /lean.*--server/ {print $1}')"
printf 'atlasd=%s lean_children=%s\n' "$ATLASD_PID" "$LEAN_PIDS"

"$ATLAS_LIVE" --atlasd "$ATLASD" stop

for pid in $LEAN_PIDS; do
  if kill -0 "$pid" 2>/dev/null; then
    echo "FAIL: leaked Lean child $pid" >&2
    exit 1
  fi
done
if kill -0 "$ATLASD_PID" 2>/dev/null; then
  echo "FAIL: atlasd still alive $ATLASD_PID" >&2
  exit 1
fi
```

The validating agent should finish with a compact table containing:

- test section;
- exact command/log path;
- observed generations/PIDs where relevant;
- pass/fail;
- any discrepancy;
- whether the discrepancy is an M5 regression or a pre-existing/deferred M4/store semantic issue.

M5 is complete only when the observational acceptance criteria are satisfied, not merely when CI is green. In particular, `stop` must leave neither `atlasd` nor any Lean child owned by its project sessions alive.
