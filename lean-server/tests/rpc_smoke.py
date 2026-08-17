#!/usr/bin/env python3
"""End-to-end smoke test for Atlas's Lean native RPC plugin.

This intentionally speaks LSP/Lean RPC directly rather than going through the Rust
client. It proves that the shared plugin can be loaded into a real `lean --server`
process, methods are registered, opaque `WithRpcRef` handles round-trip, and a
released handle is rejected by the server.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any


class Lsp:
    def __init__(self, command: list[str], cwd: pathlib.Path) -> None:
        self.proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.stdin = self.proc.stdin
        self.stdout = self.proc.stdout
        self.next_id = 1

    def _write(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, separators=(",", ":")).encode()
        self.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode())
        self.stdin.write(body)
        self.stdin.flush()

    def notify(self, method: str, params: Any) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request_raw(self, method: str, params: Any) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            message = self._read()
            if message.get("id") == request_id:
                return message

    def request(self, method: str, params: Any) -> Any:
        message = self.request_raw(method, params)
        if "error" in message:
            raise AssertionError(f"{method} failed: {message['error']}")
        return message.get("result")

    def _read(self) -> dict[str, Any]:
        length: int | None = None
        while True:
            line = self.stdout.readline()
            if not line:
                raise RuntimeError(
                    f"Lean server closed stdout (exit={self.proc.poll()})"
                )
            stripped = line.rstrip(b"\r\n")
            if not stripped:
                break
            key, _, value = stripped.partition(b":")
            if key.lower() == b"content-length":
                length = int(value.strip())
        if length is None:
            raise RuntimeError("LSP frame has no Content-Length")
        return json.loads(self.stdout.read(length))

    def close(self) -> None:
        if self.proc.poll() is not None:
            return
        try:
            self.request("shutdown", None)
            self.notify("exit", None)
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


def rpc_call(
    lsp: Lsp,
    *,
    uri: str,
    session_id: int | str,
    method: str,
    params: dict[str, Any],
    position: dict[str, int],
) -> Any:
    return lsp.request(
        "$/lean/rpc/call",
        {
            "textDocument": {"uri": uri},
            "position": position,
            "sessionId": session_id,
            "method": method,
            "params": params,
        },
    )


def ref_id(handle: dict[str, Any]) -> str:
    value = handle.get("__rpcref")
    assert isinstance(value, str), f"not a v1 RPC ref: {handle!r}"
    int(value)  # validate canonical bignum payload
    return value


def oracle_value(result: dict[str, Any], method: str) -> dict[str, Any]:
    failure = result.get("failure")
    assert failure is None, f"{method} returned Atlas failure: {failure!r}"
    value = result.get("value")
    assert isinstance(value, dict), f"{method} returned no value: {result!r}"
    return value


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: rpc_smoke.py LEAN PLUGIN", file=sys.stderr)
        return 2

    lean = pathlib.Path(sys.argv[1]).resolve()
    plugin = pathlib.Path(sys.argv[2]).resolve()
    root = pathlib.Path(__file__).resolve().parents[1]
    fixture = root / "Fixtures" / "RpcSmoke.lean"
    uri = fixture.resolve().as_uri()
    text = fixture.read_text()
    pos = {"line": 2, "character": 0}

    assert lean.exists(), lean
    assert plugin.exists(), plugin

    lsp = Lsp([str(lean), "--server", f"--plugin={plugin}"], root)
    refs_to_release: set[str] = set()
    try:
        lsp.request(
            "initialize",
            {
                "processId": None,
                "clientInfo": {"name": "atlas-rpc-smoke", "version": "1"},
                "rootUri": root.resolve().as_uri(),
                "capabilities": {
                    "lean": {"rpcWireFormat": "v1"}
                },
            },
        )
        lsp.notify("initialized", {})
        lsp.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "lean4",
                    "version": 1,
                    "text": text,
                }
            },
        )

        connected = lsp.request("$/lean/rpc/connect", {"uri": uri})
        session_id = connected["sessionId"]
        assert isinstance(session_id, str), connected
        int(session_id)

        hello = rpc_call(
            lsp,
            uri=uri,
            session_id=session_id,
            method="Atlas.Server.hello",
            params={
                "atlas_protocol": "2.0.0",
                "requested_features": ["lookupDecl", "isDefEq"],
                "position": pos,
            },
            position=pos,
        )
        assert hello["atlas_protocol"] == "2.0.0", hello
        assert hello["lean_version"].startswith("4.30.0"), hello
        assert "lookupDecl" in hello["features"], hello
        assert "isDefEq" in hello["features"], hello

        lookup = oracle_value(
            rpc_call(
                lsp,
                uri=uri,
                session_id=session_id,
                method="Atlas.Server.lookupDecl",
                params={"name": "double", "position": pos},
                position=pos,
            ),
            "lookupDecl",
        )
        assert lookup["name"] == "double", lookup
        for key in ("declaration", "expression", "type_expr"):
            refs_to_release.add(ref_id(lookup[key]))

        inferred = oracle_value(
            rpc_call(
                lsp,
                uri=uri,
                session_id=session_id,
                method="Atlas.Server.inferType",
                params={"expr": lookup["expression"], "position": pos},
                position=pos,
            ),
            "inferType",
        )
        refs_to_release.add(ref_id(inferred["expr"]))
        assert "Nat" in inferred["pretty"], inferred

        lhs = oracle_value(
            rpc_call(
                lsp,
                uri=uri,
                session_id=session_id,
                method="Atlas.Server.elaborate",
                params={"text": "double 2", "expected": None, "position": pos},
                position=pos,
            ),
            "elaborate lhs",
        )
        rhs = oracle_value(
            rpc_call(
                lsp,
                uri=uri,
                session_id=session_id,
                method="Atlas.Server.elaborate",
                params={"text": "(4 : Nat)", "expected": None, "position": pos},
                position=pos,
            ),
            "elaborate rhs",
        )
        for response in (lhs, rhs):
            refs_to_release.add(ref_id(response["expr"]))
            refs_to_release.add(ref_id(response["type_expr"]))

        for left, right in ((lhs["expr"], rhs["expr"]), (rhs["expr"], lhs["expr"])):
            eq = oracle_value(
                rpc_call(
                    lsp,
                    uri=uri,
                    session_id=session_id,
                    method="Atlas.Server.isDefEq",
                    params={"lhs": left, "rhs": right, "position": pos},
                    position=pos,
                ),
                "isDefEq",
            )
            assert eq["value"] is True, eq

        # A released native Lean handle must not remain usable. This validates the
        # server side of the stale-handle contract rather than only Rust error mapping.
        stale_ref = ref_id(lhs["expr"])
        lsp.notify(
            "$/lean/rpc/release",
            {
                "uri": uri,
                "sessionId": session_id,
                "refs": [{"__rpcref": stale_ref}],
            },
        )
        refs_to_release.discard(stale_ref)
        stale = lsp.request_raw(
            "$/lean/rpc/call",
            {
                "textDocument": {"uri": uri},
                "position": pos,
                "sessionId": session_id,
                "method": "Atlas.Server.inferType",
                "params": {"expr": {"__rpcref": stale_ref}, "position": pos},
            },
        )
        assert "error" in stale, stale
        assert "RPC reference" in stale["error"].get("message", ""), stale
        assert "not valid" in stale["error"].get("message", ""), stale

        if refs_to_release:
            lsp.notify(
                "$/lean/rpc/release",
                {
                    "uri": uri,
                    "sessionId": session_id,
                    "refs": [
                        {"__rpcref": value} for value in sorted(refs_to_release)
                    ],
                },
            )

        print(
            "live RPC smoke passed: hello, lookupDecl, inferType, elaborate, "
            "bidirectional isDefEq, release/stale-handle"
        )
        return 0
    finally:
        lsp.close()


if __name__ == "__main__":
    raise SystemExit(main())
