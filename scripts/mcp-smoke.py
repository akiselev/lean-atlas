#!/usr/bin/env python3
"""The MCP round-trip smoke (PLAN M2 exit gate, agent-interface §1).

Drives `atlas-mcp` over stdio the way a client does — initialize, the `initialized`
notification, `tools/list`, then real tool calls — and checks the answers.

The gate is not "the server starts". It is:

* a notification draws **no** reply (JSON-RPC says so, and every client sends one);
* `tools/list` advertises the Atlas-specific tools and *not* the ones delegated to
  `lean-lsp-mcp`, per agent-interface §1's amendment;
* `elaborate` comes back with goals at Atlas-source spans, which is the thing a generic
  server cannot produce because it does not know a macro expansion happened.

`try` is absent, and deliberately: it needs proof-state handles, which means the REPL
wrapper (C2). This script asserts its absence rather than skipping it, so the day C2 lands
the gate fails until it is added here too.

Run from the repository root:  python3 scripts/mcp-smoke.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER = ROOT / "target" / "debug" / "atlas-mcp"

REQUESTS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "status", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
     "params": {"name": "elaborate",
                "arguments": {"file": "Tests/corpus/g12_gcd.lean"}}},
]


def fail(msg: str) -> None:
    print(f"mcp smoke: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not SERVER.exists():
        fail(f"{SERVER} not built — run `cargo build -p atlas --bins`")

    stdin = "".join(json.dumps(r) + "\n" for r in REQUESTS)
    proc = subprocess.run(
        [str(SERVER)],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "FH_LEAN_DIR": str(ROOT / "lean")},
        timeout=600,
    )
    if proc.returncode != 0:
        fail(f"server exited {proc.returncode}\n{proc.stderr}")

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    replies = {}
    for ln in lines:
        msg = json.loads(ln)
        replies[msg.get("id")] = msg

    # One reply per *request*, not per line: the notification must draw none.
    if len(lines) != 4:
        fail(f"expected 4 replies for 5 messages (the notification draws none), got {len(lines)}")

    init = replies[1]["result"]
    assert init["serverInfo"]["name"] == "atlas-mcp", init
    assert "tools" in init["capabilities"], init

    names = {t["name"] for t in replies[2]["result"]["tools"]}
    for expected in ("elaborate", "atlas_why", "atlas_foundations", "atlas_impact",
                     "atlas_walls", "statement_verify", "status"):
        if expected not in names:
            fail(f"tools/list is missing `{expected}`: {sorted(names)}")
    # Delegated to `lean-lsp-mcp` (agent-interface §1 as amended) — composition over
    # reimplementation, so a `search` here would be the second-best one.
    for absent in ("search", "goals", "hover"):
        if absent in names:
            fail(f"`{absent}` belongs to lean-lsp-mcp, not fh mcp")
    # Named in §1, honestly missing until C2. Delete this when the REPL lands.
    for pending in ("try", "minimize"):
        if pending in names:
            fail(f"`{pending}` appeared — add it to this gate's positive list")

    status = json.loads(replies[3]["result"]["content"][0]["text"])
    assert "Lean (version" in status["lean"], status

    elaborate = replies[4]["result"]
    if elaborate["isError"]:
        fail(f"elaborate reported an error: {elaborate['content'][0]['text'][:400]}")
    report = json.loads(elaborate["content"][0]["text"])
    if report["status"] != "ok":
        fail(f"g12 should elaborate cleanly: {report['diagnostics'][:2]}")
    # Group 12 keeps the corpus's `todo!()`s, so the goals array is the point.
    if not report["goals"]:
        fail("elaborate returned no goals for a file with holes")
    goal = next((g for g in report["goals"] if g["goal"] == "d ∣ gcd2 a b"), None)
    if goal is None:
        fail(f"expected the gcd2_greatest goal: {[g['goal'] for g in report['goals']]}")
    if [h["name"] for h in goal["context"]] != ["a", "b", "d", "ha", "hb"]:
        fail(f"local context is wrong: {goal['context']}")

    print(f"mcp smoke: green — {len(names)} tools, {len(report['goals'])} goals from elaborate")


if __name__ == "__main__":
    main()
