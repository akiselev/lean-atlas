#!/usr/bin/env python3
"""End-to-end smoke test for the Atlas Lean language-server RPC plugin.

This deliberately speaks Lean's JSON-RPC/LSP framing directly so the test validates the
server/plugin boundary independently of the Rust client implementation. Rust separately tests
its framing and typed protocol serialization.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, BinaryIO


class Rpc:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stdin is not None
        assert process.stdout is not None
        self.process = process
        self.stdin: BinaryIO = process.stdin
        self.stdout: BinaryIO = process.stdout
        self.next_id = 1

    def send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, separators=(",", ":")).encode()
        self.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode())
        self.stdin.write(body)
        self.stdin.flush()

    def notify(self, method: str, params: Any) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Any) -> Any:
        request_id = self.next_id
        self.next_id += 1
        self.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            response = self.read()
            if response.get("id") != request_id:
                # Diagnostics/progress notifications are expected while files elaborate.
                continue
            if "error" in response:
                raise RuntimeError(f"{method} failed: {response['error']}")
            return response["result"]

    def read(self) -> dict[str, Any]:
        content_length: int | None = None
        while True:
            line = self.stdout.readline()
            if not line:
                stderr = b""
                if self.process.stderr is not None:
                    stderr = self.process.stderr.read()
                raise RuntimeError(
                    "Lean server closed stdout; stderr:\n" + stderr.decode(errors="replace")
                )
            if line in (b"\r\n", b"\n"):
                break
            name, _, value = line.decode("ascii").partition(":")
            if name.lower() == "content-length":
                content_length = int(value.strip())
        if content_length is None:
            raise RuntimeError("Lean response omitted Content-Length")
        body = self.stdout.read(content_length)
        if len(body) != content_length:
            raise RuntimeError("truncated Lean JSON-RPC response")
        return json.loads(body)


def position(line: int, character: int = 0) -> dict[str, int]:
    return {"line": line, "character": character}


def rpc_call(
    rpc: Rpc,
    uri: str,
    session_id: int,
    pos: dict[str, int],
    method: str,
    params: dict[str, Any],
) -> Any:
    return rpc.request(
        "$/lean/rpc/call",
        {
            "textDocument": {"uri": uri},
            "position": pos,
            "sessionId": session_id,
            "method": method,
            "params": params,
        },
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: lean-rpc-smoke.py /absolute/path/to/libAtlasServer.so")
    plugin = pathlib.Path(sys.argv[1]).resolve()
    if not plugin.is_file():
        raise SystemExit(f"plugin not found: {plugin}")

    repo = pathlib.Path(__file__).resolve().parents[1]
    package = repo / "lean-server"
    source = "import Lean\n\ndef atlasRpcSmoke : Nat := 1\n"

    with tempfile.TemporaryDirectory(prefix="atlas-lean-rpc-") as tmp:
        fixture = pathlib.Path(tmp) / "RpcSmoke.lean"
        fixture.write_text(source, encoding="utf-8")
        uri = fixture.resolve().as_uri()

        process = subprocess.Popen(
            ["lake", "env", "lean", "--server", f"--plugin={plugin}"],
            cwd=package,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        rpc = Rpc(process)
        try:
            rpc.request(
                "initialize",
                {
                    "processId": None,
                    "rootUri": package.resolve().as_uri(),
                    "capabilities": {},
                    "workspaceFolders": None,
                },
            )
            rpc.notify("initialized", {})
            rpc.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "lean4",
                        "version": 1,
                        "text": source,
                    }
                },
            )

            session = rpc.request("$/lean/rpc/connect", {"uri": uri})
            session_id = session["sessionId"]
            pos = position(2, 28)

            hello = rpc_call(
                rpc,
                uri,
                session_id,
                pos,
                "Atlas.Server.hello",
                {"protocol": 1},
            )
            assert hello["protocol"] == 1, hello
            assert hello["schema"] == "atlas-lean-rpc-v1", hello
            assert "defeq" in hello["features"], hello

            lookup = rpc_call(
                rpc,
                uri,
                session_id,
                pos,
                "Atlas.Server.lookupDeclaration",
                {"position": pos, "name": "atlasRpcSmoke"},
            )
            declaration = lookup["declaration"]
            assert declaration is not None, lookup
            assert declaration["name"] == "atlasRpcSmoke", declaration
            assert declaration["kind"] == "def", declaration
            type_ref = declaration["typeRef"]

            used = rpc_call(
                rpc,
                uri,
                session_id,
                pos,
                "Atlas.Server.usedConstants",
                {"position": pos, "expr": type_ref},
            )
            assert "Nat" in used["constants"], used

            inferred = rpc_call(
                rpc,
                uri,
                session_id,
                pos,
                "Atlas.Server.inferType",
                {"position": pos, "expr": type_ref},
            )
            assert "expr" in inferred, inferred

            reduced = rpc_call(
                rpc,
                uri,
                session_id,
                pos,
                "Atlas.Server.whnf",
                {"position": pos, "expr": type_ref},
            )
            assert "expr" in reduced, reduced

            equal = rpc_call(
                rpc,
                uri,
                session_id,
                pos,
                "Atlas.Server.defEq",
                {"position": pos, "lhs": type_ref, "rhs": type_ref},
            )
            assert equal == {"equal": True}, equal

            # Release every reference we received; refs are deliberately treated as opaque.
            refs = [type_ref, inferred["expr"], reduced["expr"]]
            rpc.notify(
                "$/lean/rpc/release",
                {"uri": uri, "sessionId": session_id, "refs": refs},
            )

            rpc.request("shutdown", None)
            rpc.notify("exit", None)
            return_code = process.wait(timeout=10)
            if return_code != 0:
                stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
                raise RuntimeError(f"Lean server exited {return_code}:\n{stderr}")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    print("Atlas live Lean RPC smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
