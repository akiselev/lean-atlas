#!/usr/bin/env python3
"""Smoke-test the `atlas-mcp` server over stdio, the way a client drives it.

Drives initialize -> tools/list -> a tool call, and asserts the composition boundary: the
generic Lean layer (elaborate/search/goals/hover) is *absent* here — it is delegated to the
community `lean-lsp-mcp` server, and this server implements only the Atlas queries.
"""
from __future__ import annotations

import json
import subprocess
import sys

BINARY = "atlas-mcp"


def send(proc: subprocess.Popen, obj: dict) -> dict | None:
    proc.stdin.write((json.dumps(obj) + "\n").encode())
    proc.stdin.flush()
    if "id" not in obj:
        return None
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server closed before responding")
    return json.loads(line)


def main() -> int:
    proc = subprocess.Popen(
        [BINARY], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    init = send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init and init["result"]["serverInfo"]["name"] == "atlas-mcp", init

    # A notification takes no reply; the client sends initialized without waiting.
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    tools = send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in tools["result"]["tools"]]

    for expected in (
        "atlas_closure", "atlas_similar", "atlas_dictionary", "atlas_why",
        "atlas_foundations", "atlas_impact", "atlas_walls", "statement_verify", "status",
    ):
        assert expected in names, f"missing tool {expected}"

    # The composition boundary, asserted rather than assumed.
    for absent in ("elaborate", "search", "goals", "hover", "try", "minimize"):
        assert absent not in names, f"{absent} should be delegated, not reimplemented"

    status = send(proc, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "status", "arguments": {}},
    })
    text = status["result"]["content"][0]["text"]
    assert "lean" in json.loads(text), text

    proc.stdin.close()
    proc.terminate()
    print(f"mcp smoke: green — {len(names)} tools, composition boundary intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
