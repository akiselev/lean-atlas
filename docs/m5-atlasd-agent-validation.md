# M5 `atlasd` agent validation plan

This is a manual/observational validation runbook. Passing `cargo test` or the automated `scripts/m5-atlasd-smoke.py` CI smoke is necessary but is not sufficient to close M5. An agent executing this plan must preserve the commands it ran, the JSON returned by Atlas, PIDs/generations observed, and any unexpected stderr.

## 1. Build and environment

From the repository root:

```bash
set -euo pipefail
cargo fmt --all -- --check
python scripts/check-deps.py
cargo test --workspace --exclude atlas-py
cargo check -p atlas-py
cargo build -p atlasd -p atlas-cli -p atlas-mcp

export ATLASD_BIN="$(realpath target/debug/atlasd)"
export PATH="$HOME/.elan/bin:$PATH"
cd lean-server
lake build AtlasServer:shared
cd ..

export ATLAS_LEAN_BIN="$(command -v lean)"
export ATLAS_LEAN_PLUGIN="$(find lean-server/.lake/build -type f \
  \( -name 'libatlasServer_Atlas_Server_Plugin.so' \
  -o -name 'libatlasServer_Atlas_Server_Plugin.dylib' \
  -o -name 'atlasServer_Atlas_Server_Plugin.dll' \
  -o -name 'libatlasServer_Atlas_Server_Plugin.dll' \) -print -quit)"
export ATLAS_LEAN_PLUGIN="$(realpath "$ATLAS_LEAN_PLUGIN")"
export ATLAS_LEAN_ROOT_URI="$(python3 -c 'import pathlib; print(pathlib.Path("lean-server").resolve().as_uri())')"
export FIXTURE="$(realpath lean-server/Fixtures/RpcSmoke.lean)"
export FIXTURE_URI="$(python3 -c 'import pathlib; print(pathlib.Path("lean-server/Fixtures/RpcSmoke.lean").resolve().as_uri())')"
```

Record:

```bash
rustc --version
cargo --version
lean --version
git rev-parse HEAD
printf 'atlasd=%s\nlean=%s\nplugin=%s\n' "$ATLASD_BIN" "$ATLAS_LEAN_BIN" "$ATLAS_LEAN_PLUGIN"
```

Expected: all paths exist and the Rust workspace is green before lifecycle testing starts.

## 2. Singleton/startup race

Ensure no old Atlas daemon is deliberately retained from another run:

```bash
ATLASD_BIN="$ATLASD_BIN" cargo run -q -p atlas-cli -- daemon-stop || true
```

Race 16 independent clients:

```bash
rm -rf /tmp/atlas-m5-race
mkdir -p /tmp/atlas-m5-race
for i in $(seq 1 16); do
  (cargo run -q -p atlas-cli -- ping >"/tmp/atlas-m5-race/$i.json" 2>"/tmp/atlas-m5-race/$i.err") &
done
wait
jq -r '.value.daemon_generation' /tmp/atlas-m5-race/*.json | sort | uniq -c
jq -r '.value.process_id' /tmp/atlas-m5-race/*.json | sort -n | uniq -c
```

Expected:

- all 16 commands succeed;
- exactly one daemon generation appears;
- exactly one daemon PID appears;
- no client reports bootstrap/authentication/state corruption.

The PID is reported by the authenticated daemon itself; process-name matching is not the acceptance oracle. You may still record `ps`, `pgrep`, or `Get-Process atlasd` output as secondary evidence.

## 3. CLI and MCP share the same daemon

Capture the CLI generation and daemon PID:

```bash
cargo run -q -p atlas-cli -- ping | tee /tmp/atlas-m5-cli-ping.json
```

Start `atlas-live-mcp` and send these JSON-RPC lines on stdin:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"atlas.ping","arguments":{}}}
```

One non-interactive way to capture it is:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"atlas.ping","arguments":{}}}' \
  | cargo run -q -p atlas-mcp --bin atlas-live-mcp \
  | tee /tmp/atlas-m5-mcp.jsonl
```

Expected: both `daemon_generation` and `process_id` embedded in the MCP tool result are byte-for-byte/numerically identical to the CLI ping. This is the primary M5 evidence that the two frontends attach to one daemon rather than each owning a private server.

## 4. Project session and persistent semantic store

Open the Lean fixture project:

```bash
cargo run -q -p atlas-cli -- open-project "$(realpath lean-server)" \
  | tee /tmp/atlas-m5-project.json
export PROJECT_ID="$(jq -r '.value.project_id' /tmp/atlas-m5-project.json)"
export LEAN_GEN="$(jq -r '.value.lean.generation' /tmp/atlas-m5-project.json)"
export LEAN_PID="$(jq -r '.value.lean.process_id' /tmp/atlas-m5-project.json)"
export STORE_PATH="$(jq -r '.value.store_path' /tmp/atlas-m5-project.json)"
printf 'project=%s lean_generation=%s lean_pid=%s store=%s\n' "$PROJECT_ID" "$LEAN_GEN" "$LEAN_PID" "$STORE_PATH"
test -f "$STORE_PATH"
```

Expected:

- the root is canonicalized;
- the store is created under `.lean-atlas/atlas.sqlite` unless `ATLAS_STORE_PATH` was set;
- Lean state is `ready` and a PID is reported;
- repeated `open-project` calls return the same project id and do not start another Lean child.

Record the store digest and size:

```bash
sha256sum "$STORE_PATH" || shasum -a 256 "$STORE_PATH"
ls -l "$STORE_PATH"
```

## 5. Unsaved live-file overlay

Create an unsaved variant without changing the fixture on disk:

```bash
cp "$FIXTURE" /tmp/atlas-m5-overlay.lean
printf '\n-- atlas-m5-unsaved-overlay\n' >> /tmp/atlas-m5-overlay.lean
cargo run -q -p atlas-cli -- open-document \
  "$PROJECT_ID" "$FIXTURE_URI" /tmp/atlas-m5-overlay.lean 100 "$LEAN_GEN" \
  | tee /tmp/atlas-m5-open-overlay.json
```

Then inspect status:

```bash
cargo run -q -p atlas-cli -- status "$PROJECT_ID" \
  | tee /tmp/atlas-m5-overlay-status.json
```

Expected:

- `overlay_documents` contains `$FIXTURE_URI` at version 100;
- `bytes` equals the unsaved file byte length;
- the original `lean-server/Fixtures/RpcSmoke.lean` remains unchanged (`git diff --exit-code -- lean-server/Fixtures/RpcSmoke.lean`);
- Lean remains ready.

Change the same overlay to version 101:

```bash
printf '%s' '-- version-101' > /tmp/atlas-m5-overlay-v101.lean
printf '\n' >> /tmp/atlas-m5-overlay-v101.lean
cat /tmp/atlas-m5-overlay.lean >> /tmp/atlas-m5-overlay-v101.lean
cargo run -q -p atlas-cli -- change-document \
  "$PROJECT_ID" "$FIXTURE_URI" /tmp/atlas-m5-overlay-v101.lean 101 "$LEAN_GEN" \
  | tee /tmp/atlas-m5-change-overlay.json
```

Expected: status reports version 101 and the changed byte length.

## 6. Explicit Lean restart, overlay replay, and stale generation rejection

Restart Lean using the current generation as a compare-and-swap guard:

```bash
cargo run -q -p atlas-cli -- restart-lean "$PROJECT_ID" "$LEAN_GEN" \
  | tee /tmp/atlas-m5-restart-lean.json
export LEAN_GEN_2="$(jq -r '.value.lean.generation' /tmp/atlas-m5-restart-lean.json)"
export LEAN_PID_2="$(jq -r '.value.lean.process_id' /tmp/atlas-m5-restart-lean.json)"
```

Expected:

- `LEAN_GEN_2 > LEAN_GEN`;
- `LEAN_PID_2 != LEAN_PID`;
- the overlay is still present at version 101 after restart/replay.

Prove stale tokens cannot act on the successor:

```bash
set +e
cargo run -q -p atlas-cli -- change-document \
  "$PROJECT_ID" "$FIXTURE_URI" /tmp/atlas-m5-overlay-v101.lean 102 "$LEAN_GEN" \
  >/tmp/atlas-m5-stale.out 2>/tmp/atlas-m5-stale.err
rc=$?
set -e
printf 'exit=%s\n' "$rc"
cat /tmp/atlas-m5-stale.err
```

Expected: non-zero exit and a structured `stale_lean_generation` error. The old generation must never be silently accepted.

Also validate the multi-document selection edge: open a second synthetic URI, then close that currently selected overlay while leaving the first open. A following `status` must remain `ready`; closing one overlay must not orphan the RPC session for the surviving documents. The automated CI smoke exercises this exact sequence, but record it manually as well.

## 7. Unexpected Lean crash and service recovery

Kill the observed Lean child directly:

```bash
kill -KILL "$LEAN_PID_2"
```

On Windows use `Stop-Process -Id $LEAN_PID_2 -Force`.

Issue status requests until the dead pipe/process is observed. Preserve every response; do not hide the detecting request behind a retry loop.

```bash
set +e
cargo run -q -p atlas-cli -- status "$PROJECT_ID" \
  >/tmp/atlas-m5-after-lean-crash.out 2>/tmp/atlas-m5-after-lean-crash.err
rc=$?
set -e
printf 'exit=%s\n' "$rc"
cat /tmp/atlas-m5-after-lean-crash.out /tmp/atlas-m5-after-lean-crash.err
```

Expected on the detecting request: a structured `lean_restarted` error carrying the new project snapshot. `lean_unavailable` is acceptable only when restart genuinely failed and must then be investigated; a generic broken pipe or panic is not acceptable.

Then retry:

```bash
cargo run -q -p atlas-cli -- status "$PROJECT_ID" \
  | tee /tmp/atlas-m5-after-lean-retry.json
```

Expected:

- Lean is `ready` after successful recovery;
- generation advanced again;
- PID changed;
- the version-101 overlay survived and was replayed.

## 8. Unexpected daemon crash and daemonkit repair

Record the authenticated daemon generation and PID, then kill exactly that process. Do not use `daemon-stop` for this test.

```bash
cargo run -q -p atlas-cli -- ping | tee /tmp/atlas-m5-before-daemon-crash.json
export DAEMON_GEN="$(jq -r '.value.daemon_generation' /tmp/atlas-m5-before-daemon-crash.json)"
export DAEMON_PID="$(jq -r '.value.process_id' /tmp/atlas-m5-before-daemon-crash.json)"
kill -KILL "$DAEMON_PID"
```

On Windows use `Stop-Process -Id $DAEMON_PID -Force`.

Immediately run:

```bash
cargo run -q -p atlas-cli -- daemon-repair | tee /tmp/atlas-m5-repair.txt
cargo run -q -p atlas-cli -- ping | tee /tmp/atlas-m5-post-repair.json
```

Expected:

- repair does not delete state belonging to a live successor;
- the next `ping` starts/attaches to one healthy daemon;
- both its daemon generation and PID differ from the killed daemon;
- no manual deletion of daemonkit runtime files is required.

Re-open the same project:

```bash
cargo run -q -p atlas-cli -- open-project "$(realpath lean-server)" \
  | tee /tmp/atlas-m5-reopen-project.json
```

Expected: the project id and persistent store path are stable. Live overlays are intentionally process-local and therefore must be republished by the editor after an `atlasd` process crash; the persistent semantic SQLite store remains on disk.

## 9. Static JSONL compatibility

M5 must not make the daemon mandatory for exported slices. Stop the daemon and run a legacy query against a known extraction:

```bash
cargo run -q -p atlas-cli -- daemon-stop || true
# Substitute a real exported slice produced by the portable extractor.
cargo run -q -p atlas -- stats path/to/slice.jsonl
```

Expected: the static `atlas` command reads the JSONL file without starting or contacting `atlasd`. This is the explicit offline/export fallback required by M5.

## 10. MCP overlay path

Repeat project attach/status and one overlay update through `atlas-live-mcp`, not only through the CLI. At minimum invoke:

- `atlas.open_project`;
- `atlas.status`;
- `atlas.open_document` or `atlas.change_document`.

Expected: the project id, Lean generation, and overlay state are immediately visible from a subsequent CLI `status`, proving both frontends mutate one daemon-owned session.

## 11. Cleanup

Gracefully close the project and daemon when possible:

```bash
CURRENT_GEN="$(cargo run -q -p atlas-cli -- status "$PROJECT_ID" | jq -r '.value.lean.generation')"
cargo run -q -p atlas-cli -- close-project "$PROJECT_ID" "$CURRENT_GEN" || true
cargo run -q -p atlas-cli -- daemon-stop || true
```

The `.lean-atlas/atlas.sqlite` file is persistent state. Delete it only if this fixture run was intentionally disposable.

## 12. Evidence bundle and pass/fail decision

Attach or retain:

- `/tmp/atlas-m5-race/*`;
- CLI and MCP ping outputs;
- project/open/change/restart/status JSON;
- crash-detection stdout/stderr and exit codes;
- daemon and Lean PIDs/generations before/after race, restart, and forced crashes;
- store path, size, and digest;
- `git diff --stat` and `git status --short` after the run;
- exact Rust/Lean/plugin versions.

M5 passes only if every acceptance property was observed, not merely inferred from unit tests:

1. concurrent CLI and MCP clients share one authenticated daemon;
2. startup races produce one daemon generation and one daemon PID;
3. daemon crash is repairable through daemonkit;
4. Lean crash becomes a structured degradation/restart event;
5. stale Lean generations cannot mutate a successor;
6. persistent semantic store survives daemon process loss;
7. unsaved overlays survive Lean-child restart via replay;
8. explicit static JSONL operation still works with no daemon.
