#!/usr/bin/env python3
"""Live M5 smoke test for atlasd process ownership and RPC error classification.

This intentionally exercises real daemonkit -> atlasd -> Lean 4.30 process behavior.
It is not a replacement for the broader manual validation matrix.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import tempfile
import time
from typing import Any


def run(env: dict[str, str], *args: str) -> str:
    proc = subprocess.run(
        list(args),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    print("$", " ".join(args))
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=os.sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"command exited {proc.returncode}: {' '.join(args)}")
    return proc.stdout


def response(env: dict[str, str], *args: str) -> dict[str, Any]:
    return json.loads(run(env, *args))


def project_generation(status: dict[str, Any], project: str) -> int:
    if status.get("response") == "project":
        item = status["status"]
        if item["token"]["project_id"] == project:
            return int(item["token"]["generation"])
    if status.get("response") == "projects":
        for item in status["projects"]:
            if item["token"]["project_id"] == project:
                return int(item["token"]["generation"])
    raise AssertionError(f"project {project!r} absent from response: {status}")


def proc_cmdline(pid: int) -> list[str]:
    try:
        data = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return []
    return [part.decode(errors="replace") for part in data.split(b"\0") if part]


def lean_pids(plugin: str) -> set[int]:
    wanted_plugin = f"--plugin={plugin}"
    result: set[int] = set()
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        argv = proc_cmdline(pid)
        if "--server" in argv and wanted_plugin in argv:
            result.add(pid)
    return result


def executable_pids(executable: str) -> set[int]:
    target = os.path.realpath(executable)
    result: set[int] = set()
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            actual = os.path.realpath(os.readlink(entry / "exe"))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if actual == target:
            result.add(int(entry.name))
    return result


def wait_until(predicate, timeout_seconds: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def assert_oracle_failure(value: dict[str, Any]) -> None:
    assert value.get("response") == "error", value
    assert value.get("error", {}).get("kind") == "oracle_failure", value


def terminate_leftovers(pids: set[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("atlas_live")
    parser.add_argument("atlasd")
    parser.add_argument("lean")
    parser.add_argument("plugin")
    parser.add_argument("workdir")
    parser.add_argument("fixture")
    parser.add_argument("root_uri")
    parser.add_argument("fixture_uri")
    args = parser.parse_args()

    atlas_live = os.path.realpath(args.atlas_live)
    atlasd = os.path.realpath(args.atlasd)
    # Preserve the lean shim path/argv[0]. Resolving ~/.elan/bin/lean to the elan
    # multiplexer binary can change which tool elan believes it was invoked as.
    lean = os.path.abspath(args.lean)
    plugin = os.path.realpath(args.plugin)
    workdir = os.path.realpath(args.workdir)
    fixture = os.path.realpath(args.fixture)
    project = "atlasd-ci-smoke"

    with tempfile.TemporaryDirectory(prefix="atlasd-smoke-") as temp:
        runtime = pathlib.Path(temp, "runtime")
        state = pathlib.Path(temp, "state")
        runtime.mkdir(mode=0o700)
        state.mkdir()
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = str(runtime)
        env["XDG_STATE_HOME"] = str(state)
        env["ATLAS_STORE_PATH"] = str(state / "atlas.sqlite3")

        valid_params = pathlib.Path(temp, "hello-valid.json")
        valid_params.write_text(
            json.dumps(
                {
                    "atlas_protocol": "2.0.0",
                    "requested_features": [],
                    "position": {"line": 2, "character": 0},
                }
            )
        )
        invalid_params = pathlib.Path(temp, "hello-invalid.json")
        invalid_params.write_text(
            json.dumps(
                {
                    "atlasProtocol": "2.0.0",
                    "requestedFeatures": [],
                    "position": {"line": 2, "character": 0},
                }
            )
        )

        owned_lean: set[int] = set()
        owned_atlasd: set[int] = set()
        try:
            ensured = response(
                env,
                atlas_live,
                "--atlasd",
                atlasd,
                "ensure",
                project,
                workdir,
                args.root_uri,
                lean,
                plugin,
            )
            generation = project_generation(ensured, project)
            assert generation >= 1

            opened = response(
                env,
                atlas_live,
                "--atlasd",
                atlasd,
                "open",
                project,
                str(generation),
                args.fixture_uri,
                "1",
                fixture,
            )
            assert project_generation(opened, project) == generation

            valid = response(
                env,
                atlas_live,
                "--atlasd",
                atlasd,
                "call",
                project,
                str(generation),
                "2",
                "0",
                "Atlas.Server.hello",
                f"@{valid_params}",
            )
            assert valid.get("response") == "ok", valid

            assert wait_until(lambda: len(lean_pids(plugin)) == 1), lean_pids(plugin)
            assert wait_until(lambda: len(executable_pids(atlasd)) == 1), executable_pids(atlasd)
            owned_lean = lean_pids(plugin)
            owned_atlasd = executable_pids(atlasd)
            assert len(owned_lean) == 1, owned_lean
            assert len(owned_atlasd) == 1, owned_atlasd

            # Regression: Lean's JSON-RPC application error is not transport death.
            bad = response(
                env,
                atlas_live,
                "--atlasd",
                atlasd,
                "call",
                project,
                str(generation),
                "2",
                "0",
                "Atlas.Server.hello",
                f"@{invalid_params}",
            )
            assert_oracle_failure(bad)
            assert "decode" in bad["error"]["message"].lower(), bad

            after_bad = response(env, atlas_live, "--atlasd", atlasd, "status")
            assert project_generation(after_bad, project) == generation, after_bad
            assert lean_pids(plugin) == owned_lean, (lean_pids(plugin), owned_lean)
            assert executable_pids(atlasd) == owned_atlasd, (
                executable_pids(atlasd),
                owned_atlasd,
            )

            unknown = response(
                env,
                atlas_live,
                "--atlasd",
                atlasd,
                "call",
                project,
                str(generation),
                "2",
                "0",
                "Atlas.Server.thisMethodDoesNotExist",
                "{}",
            )
            assert_oracle_failure(unknown)
            after_unknown = response(env, atlas_live, "--atlasd", atlasd, "status")
            assert project_generation(after_unknown, project) == generation, after_unknown
            assert lean_pids(plugin) == owned_lean, (lean_pids(plugin), owned_lean)

            # The same process remains usable after both rejected requests.
            again = response(
                env,
                atlas_live,
                "--atlasd",
                atlasd,
                "call",
                project,
                str(generation),
                "2",
                "0",
                "Atlas.Server.hello",
                f"@{valid_params}",
            )
            assert again.get("response") == "ok", again
            assert lean_pids(plugin) == owned_lean, (lean_pids(plugin), owned_lean)

            # Regression: daemonkit may report Stopped only after atlasd has reaped Lean.
            run(env, atlas_live, "--atlasd", atlasd, "stop")
            assert wait_until(lambda: not (owned_lean & lean_pids(plugin))), lean_pids(plugin)
            assert wait_until(lambda: not (owned_atlasd & executable_pids(atlasd))), executable_pids(
                atlasd
            )
            print("atlasd smoke: RPC rejection preserved session; graceful stop reaped Lean")
        finally:
            # Keep the CI runner clean even when an assertion fails. Only target exact
            # processes observed from this atlasd path / plugin path.
            try:
                run(env, atlas_live, "--atlasd", atlasd, "stop")
            except Exception:
                pass
            terminate_leftovers(owned_lean & lean_pids(plugin))
            terminate_leftovers(owned_atlasd & executable_pids(atlasd))


if __name__ == "__main__":
    main()
