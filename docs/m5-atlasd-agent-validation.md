# M5 `atlasd` agent validation plan

This is a manual/observational validation runbook. Passing `cargo test` and the automated `scripts/m5-atlasd-smoke.py` lifecycle smoke is necessary but is not sufficient to close M5. Preserve every command, relevant JSON response, PID/generation observation, and unexpected stderr so another person can reproduce the evidence.

## 1. Build and record the environment

From the repository root:

```bash
set -euo pipefail
cargo fmt --all -- --check
python scripts/check-deps.py
cargo test --locked --workspace --exclude atlas-py
cargo check --locked -p atlas-py
cargo build --locked -p atlasd -p atlas-cli -p atlas-mcp

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

rustc --version
cargo --version
lean --version
git rev-parse HEAD
printf 'atlasd=%s\nlean=%s\nplugin=%s\n' "$ATLASD_BIN" "$ATLAS_LEAN_BIN" "$ATLAS_LEAN_PLUGIN"
```

Expected: the locked Rust workspace is green, the Lean plugin builds, and every recorded executable/plugin path exists.

## 2. Singleton/startup race

Stop any deliberately retained test daemon, then race independent clients:

```bash
cargo run -q -p atlas-cli -- daemon-stop || true
rm -rf /tmp/atlas-m5-race
mkdir -p /tmp/atlas-m5-race
for i in $(seq 1 16); do
  (cargo run -q -p atlas-cli -- ping >"/tmp/atlas-m5-race/$i.json" 2>"/tmp/atlas-m5-race/$i.err") &
done
wait
jq -r '.value.daemon_generation' /tmp/atlas-m5-race/*.json | sort | uniq -c
jq -r '.value.process_id' /tmp/atlas-m5-race/*.json | sort -n | uniq -c
```

Pass only if all clients succeed and all 16 responses report exactly one daemon generation and one daemon PID. The authenticated daemon-reported PID/generation are the primary evidence; `ps`, `pgrep`, or `Get-Process atlasd` may be retained as secondary evidence.

## 3. Prove CLI and MCP share the daemon

Capture CLI state:

```bash
cargo run -q -p atlas-cli -- ping | tee /tmp/atlas-m5-cli-ping.json
```

Exercise the canonical daemon-backed `atlas-mcp` binary:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"atlas.ping","arguments":{}}}' \
  | cargo run -q -p atlas-mcp --bin atlas-mcp \
  | tee /tmp/atlas-m5-mcp.jsonl
```

Pass only if MCP reports the same `daemon_generation` and `process_id` as the CLI. Also run `tools/list` and verify the live MCP exposes project status, open/change/close document, restart Lean, and close project operations. The pre-M5 slice-only MCP binary is `atlas-static-mcp` and is not the primary M5 frontend.

## 4. Project identity and persistent semantic store

```bash
cargo run -q -p atlas-cli -- open-project "$(realpath lean-server)" \
  | tee /tmp/atlas-m5-project.json
export PROJECT_ID="$(jq -r '.value.project_id' /tmp/atlas-m5-project.json)"
export LEAN_GEN="$(jq -r '.value.lean.generation' /tmp/atlas-m5-project.json)"
export LEAN_PID="$(jq -r '.value.lean.process_id' /tmp/atlas-m5-project.json)"
export STORE_PATH="$(jq -r '.value.store_path' /tmp/atlas-m5-project.json)"
test -f "$STORE_PATH"
sha256sum "$STORE_PATH" || shasum -a 256 "$STORE_PATH"
ls -l "$STORE_PATH"
```

Expected: canonical root, deterministic project ID, `ready` Lean state, one Lean PID, and a persistent SQLite store (default `.lean-atlas/atlas.sqlite`). Run `open-project` again and verify the project ID and Lean PID are unchanged; attaching a second client must not start a second Lean server.

## 5. Unsaved live-file overlay

Create an unsaved buffer without modifying the fixture on disk:

```bash
cp "$FIXTURE" /tmp/atlas-m5-overlay.lean
printf '\n-- atlas-m5-unsaved-overlay\n' >> /tmp/atlas-m5-overlay.lean
cargo run -q -p atlas-cli -- open-document \
  "$PROJECT_ID" "$FIXTURE_URI" /tmp/atlas-m5-overlay.lean 100 "$LEAN_GEN" \
  | tee /tmp/atlas-m5-open-overlay.json
cargo run -q -p atlas-cli -- status "$PROJECT_ID" \
  | tee /tmp/atlas-m5-overlay-status.json
git diff --exit-code -- lean-server/Fixtures/RpcSmoke.lean
```

Expected: the overlay contains `$FIXTURE_URI`, version 100, and the exact unsaved byte length while the checked-in fixture remains unchanged.

Change the overlay:

```bash
printf '%s\n' '-- version-101' > /tmp/atlas-m5-overlay-v101.lean
cat /tmp/atlas-m5-overlay.lean >> /tmp/atlas-m5-overlay-v101.lean
cargo run -q -p atlas-cli -- change-document \
  "$PROJECT_ID" "$FIXTURE_URI" /tmp/atlas-m5-overlay-v101.lean 101 "$LEAN_GEN" \
  | tee /tmp/atlas-m5-change-overlay.json
```

Expected: status reports version 101 and the new byte length.

## 6. Explicit Lean restart, replay, stale-generation fencing

```bash
cargo run -q -p atlas-cli -- restart-lean "$PROJECT_ID" "$LEAN_GEN" \
  | tee /tmp/atlas-m5-restart-lean.json
export LEAN_GEN_2="$(jq -r '.value.lean.generation' /tmp/atlas-m5-restart-lean.json)"
export LEAN_PID_2="$(jq -r '.value.lean.process_id' /tmp/atlas-m5-restart-lean.json)"
```

Pass only if `LEAN_GEN_2 > LEAN_GEN`, the Lean PID changes, and the version-101 overlay survives replay.

Then deliberately use the stale generation:

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

Expected: non-zero exit with structured `stale_lean_generation`; the request must not act on the successor process.

Also open a second synthetic URI, then close that currently selected document while leaving the first overlay open. A following `status` must remain `ready`. This catches accidental coupling between the set of open documents and the single URI selected for typed RPC.

## 7. Unexpected Lean crash and recovery

Kill the exact daemon-owned Lean PID:

```bash
kill -KILL "$LEAN_PID_2"
```

On Windows use `Stop-Process -Id $LEAN_PID_2 -Force`.

Issue and preserve status requests until the dead child is detected. The detecting request must expose a structured `lean_restarted` result/error carrying the successor project snapshot; `lean_unavailable` is acceptable only if restart genuinely fails. A raw broken pipe, panic, or silent reuse of the old generation fails M5.

Then verify:

```bash
cargo run -q -p atlas-cli -- status "$PROJECT_ID" \
  | tee /tmp/atlas-m5-after-lean-retry.json
```

Expected: `ready`, newer Lean generation, different PID, and the version-101 overlay replayed.

## 8. Unexpected `atlasd` crash and daemonkit repair

Capture both daemon and currently-owned Lean processes immediately before the crash:

```bash
cargo run -q -p atlas-cli -- ping | tee /tmp/atlas-m5-before-daemon-crash.json
cargo run -q -p atlas-cli -- status "$PROJECT_ID" | tee /tmp/atlas-m5-before-daemon-status.json
export DAEMON_GEN="$(jq -r '.value.daemon_generation' /tmp/atlas-m5-before-daemon-crash.json)"
export DAEMON_PID="$(jq -r '.value.process_id' /tmp/atlas-m5-before-daemon-crash.json)"
export OWNED_LEAN_PID="$(jq -r '.value.lean.process_id' /tmp/atlas-m5-before-daemon-status.json)"
kill -KILL "$DAEMON_PID"
```

On Windows use `Stop-Process -Id $DAEMON_PID -Force`.

Observe that the old Lean child also terminates after its daemon-owned stdio closes. On Linux/macOS, poll rather than assuming immediate scheduler timing:

```bash
for _ in $(seq 1 50); do
  if ! kill -0 "$OWNED_LEAN_PID" 2>/dev/null; then break; fi
  sleep 0.1
done
if kill -0 "$OWNED_LEAN_PID" 2>/dev/null; then
  echo "old daemon-owned Lean process is still alive: $OWNED_LEAN_PID" >&2
  exit 1
fi
```

Then repair:

```bash
cargo run -q -p atlas-cli -- daemon-repair | tee /tmp/atlas-m5-repair.txt
cargo run -q -p atlas-cli -- ping | tee /tmp/atlas-m5-post-repair.json
cargo run -q -p atlas-cli -- open-project "$(realpath lean-server)" \
  | tee /tmp/atlas-m5-reopen-project.json
```

Pass only if daemonkit repairs without manual runtime-file deletion, the new daemon has a different generation/PID, the project ID and SQLite store path are stable, and the persistent store still exists. Live overlays are intentionally daemon-process-local; after a hard `atlasd` loss the editor must republish them, so the reopened project should not pretend old unsaved buffers are current.

## 9. Static/export fallback without `atlasd`

Stop the daemon and run a real exported slice through the compatibility CLI:

```bash
cargo run -q -p atlas-cli -- daemon-stop || true
cargo run -q -p atlas -- stats path/to/real-exported-slice.jsonl
```

Pass only if the static `atlas` query works without starting/contacting `atlasd`. If MCP compatibility is relevant to the consumer, separately exercise `atlas-static-mcp` against the same exported slice.

## 10. MCP mutation path

Repeat at least one project attach and one overlay mutation through canonical `atlas-mcp`, then inspect the result through `atlas-cli status`. At minimum exercise `atlas.open_project`, `atlas.status`, and either `atlas.open_document` or `atlas.change_document`. Also exercise `atlas.close_document` or `atlas.close_project` once so the MCP cleanup path is observed, not just listed.

Pass only if CLI immediately sees the same project ID, Lean generation, and overlay/session state changed through MCP.

## 11. Cleanup and evidence bundle

Gracefully close what remains:

```bash
CURRENT_GEN="$(cargo run -q -p atlas-cli -- status "$PROJECT_ID" | jq -r '.value.lean.generation')"
cargo run -q -p atlas-cli -- close-project "$PROJECT_ID" "$CURRENT_GEN" || true
cargo run -q -p atlas-cli -- daemon-stop || true
git status --short
git diff --stat
```

Do not delete `.lean-atlas/atlas.sqlite` unless this fixture store was intentionally disposable.

Retain `/tmp/atlas-m5-race/*`, CLI/MCP responses, project/open/change/restart/status JSON, crash-detection stdout/stderr and exit codes, all daemon/Lean PIDs and generations, store path/size/digest, repository status, and exact Rust/Lean/plugin versions.

M5 passes only if all of these properties were directly observed:

1. concurrent CLI and MCP clients converge on one authenticated daemon;
2. startup races yield one daemon generation and PID;
3. project sessions own one Lean process and one persistent semantic store;
4. unsaved overlays remain distinct from on-disk files and survive Lean-child restart;
5. stale Lean generations cannot mutate a successor;
6. unexpected Lean death becomes a structured restart/degradation event;
7. hard daemon death is repairable and does not leave the old Lean server live;
8. persistent SQLite state survives daemon loss while stale live overlays do not masquerade as current;
9. the canonical MCP and CLI mutate the same daemon-owned session;
10. static exported JSONL remains explicitly usable without the daemon.
