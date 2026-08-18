#!/usr/bin/env python3
"""Live M5 smoke test for atlasd.

This test deliberately exercises process boundaries and crash recovery. It is
Linux-oriented because the Lean GitHub Actions runner is Linux; the committed
manual validation plan covers platform-specific observation on macOS/Windows.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable {name}")
    return value


CLI = Path(required_env("ATLAS_M5_CLI"))
MCP = Path(required_env("ATLAS_M5_MCP"))
ROOT = Path(required_env("ATLAS_M5_ROOT")).resolve()
FIXTURE = Path(required_env("ATLAS_M5_FIXTURE")).resolve()
FIXTURE_URI = required_env("ATLAS_M5_FIXTURE_URI")


def run_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(CLI), *args],
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    print(f"$ {CLI.name} {' '.join(args)}", flush=True)
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"atlas-cli exited {result.returncode}: {' '.join(args)}")
    return result


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or "type" not in value or "value" not in value:
        raise AssertionError(f"unexpected response payload: {value!r}")
    return value


def project(result: subprocess.CompletedProcess[str]) -> dict:
    value = payload(result)
    assert value["type"] == "project", value
    return value["value"]


def pong(result: subprocess.CompletedProcess[str]) -> dict:
    value = payload(result)
    assert value["type"] == "pong", value
    return value["value"]


def overlay(snapshot: dict, uri: str) -> dict:
    matches = [item for item in snapshot["overlay_documents"] if item["uri"] == uri]
    assert len(matches) == 1, snapshot["overlay_documents"]
    return matches[0]


def mcp_ping() -> dict:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "atlas.ping", "arguments": {}},
        },
    ]
    wire = "\n".join(json.dumps(request) for request in requests) + "\n"
    result = subprocess.run(
        [str(MCP)],
        input=wire,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
        check=True,
    )
    print(f"$ {MCP.name}  # initialize + atlas.ping", flush=True)
    print(result.stdout.rstrip(), flush=True)
    responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    tool_response = next(response for response in responses if response.get("id") == 2)
    text = tool_response["result"]["content"][0]["text"]
    value = json.loads(text)
    assert value["type"] == "pong", value
    return value["value"]


def wait_for_lean_recovery(project_id: str, old_generation: int) -> dict:
    observed_structured_restart = False
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = run_cli("status", project_id, check=False)
        if result.returncode != 0:
            if "lean_restarted" in result.stderr:
                observed_structured_restart = True
            elif "lean_unavailable" in result.stderr:
                raise AssertionError(f"Lean restart became unavailable: {result.stderr}")
        else:
            snapshot = project(result)
            if snapshot["lean"]["generation"] > old_generation:
                assert observed_structured_restart, (
                    "Lean generation advanced without the detecting request exposing "
                    "a structured lean_restarted event"
                )
                return snapshot
        time.sleep(0.1)
    raise AssertionError("atlasd did not detect and recover the killed Lean child")


def repair_after_daemon_crash() -> str:
    deadline = time.monotonic() + 10
    observations: list[str] = []
    while time.monotonic() < deadline:
        result = run_cli("daemon-repair", check=False)
        observations.append(result.stdout + result.stderr)
        if result.returncode == 0 and ("Repaired" in result.stdout or "Clean" in result.stdout):
            return "".join(observations)
        time.sleep(0.1)
    raise AssertionError(f"daemonkit repair did not converge: {observations!r}")


def main() -> None:
    assert CLI.is_file(), CLI
    assert MCP.is_file(), MCP
    assert FIXTURE.is_file(), FIXTURE

    run_cli("daemon-stop", check=False)

    # Startup race: all independently-started clients must converge on one
    # daemon generation and process id.
    racers = [
        subprocess.Popen(
            [str(CLI), "ping"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        for _ in range(12)
    ]
    race_pongs = []
    for process_handle in racers:
        stdout, stderr = process_handle.communicate(timeout=30)
        if process_handle.returncode != 0:
            raise AssertionError(
                f"startup racer failed: rc={process_handle.returncode} stderr={stderr}"
            )
        race_pongs.append(json.loads(stdout)["value"])
    generations = {item["daemon_generation"] for item in race_pongs}
    daemon_pids = {item["process_id"] for item in race_pongs}
    assert len(generations) == 1, race_pongs
    assert len(daemon_pids) == 1, race_pongs
    print(f"startup race converged: generation={generations} pid={daemon_pids}")

    cli_pong = pong(run_cli("ping"))
    mcp_pong_value = mcp_ping()
    assert mcp_pong_value["daemon_generation"] == cli_pong["daemon_generation"]
    assert mcp_pong_value["process_id"] == cli_pong["process_id"]

    opened = project(run_cli("open-project", str(ROOT)))
    project_id = opened["project_id"]
    lean_generation = int(opened["lean"]["generation"])
    lean_pid = int(opened["lean"]["process_id"])
    store_path = Path(opened["store_path"])
    assert opened["lean"]["state"] == "ready", opened
    assert store_path.is_file(), store_path

    reopened_same_process = project(run_cli("open-project", str(ROOT)))
    assert reopened_same_process["project_id"] == project_id
    assert reopened_same_process["lean"]["process_id"] == lean_pid

    with tempfile.TemporaryDirectory(prefix="atlas-m5-") as temp_dir:
        temp = Path(temp_dir)
        first = temp / "overlay-v100.lean"
        first.write_text(FIXTURE.read_text() + "\n-- atlas-m5-unsaved-overlay\n")
        opened_overlay = project(
            run_cli(
                "open-document",
                project_id,
                FIXTURE_URI,
                str(first),
                "100",
                str(lean_generation),
            )
        )
        item = overlay(opened_overlay, FIXTURE_URI)
        assert item["version"] == 100
        assert item["bytes"] == len(first.read_bytes())

        second_version = temp / "overlay-v101.lean"
        second_version.write_text("-- version-101\n" + first.read_text())
        changed = project(
            run_cli(
                "change-document",
                project_id,
                FIXTURE_URI,
                str(second_version),
                "101",
                str(lean_generation),
            )
        )
        assert overlay(changed, FIXTURE_URI)["version"] == 101

        restarted = project(run_cli("restart-lean", project_id, str(lean_generation)))
        lean_generation_2 = int(restarted["lean"]["generation"])
        lean_pid_2 = int(restarted["lean"]["process_id"])
        assert lean_generation_2 > lean_generation
        assert lean_pid_2 != lean_pid
        assert overlay(restarted, FIXTURE_URI)["version"] == 101

        stale = run_cli(
            "change-document",
            project_id,
            FIXTURE_URI,
            str(second_version),
            "102",
            str(lean_generation),
            check=False,
        )
        assert stale.returncode != 0
        assert "stale_lean_generation" in stale.stderr, stale.stderr

        # Exercise multi-document ownership. Close the currently-selected
        # second document and verify atlasd reselects the surviving overlay.
        second_uri = (ROOT / "M5Second.lean").as_uri()
        second_file = temp / "M5Second.lean"
        second_file.write_text("theorem atlasM5Second : True := by trivial\n")
        with_second = project(
            run_cli(
                "open-document",
                project_id,
                second_uri,
                str(second_file),
                "1",
                str(lean_generation_2),
            )
        )
        assert overlay(with_second, second_uri)["version"] == 1
        closed_second = project(
            run_cli(
                "close-document",
                project_id,
                second_uri,
                str(lean_generation_2),
            )
        )
        assert all(item["uri"] != second_uri for item in closed_second["overlay_documents"])
        assert overlay(closed_second, FIXTURE_URI)["version"] == 101
        healthy_after_close = project(run_cli("status", project_id))
        assert healthy_after_close["lean"]["state"] == "ready"

        # Kill Lean out from under atlasd. The detecting request must expose a
        # structured restart event and the successor must replay the overlay.
        os.kill(lean_pid_2, signal.SIGKILL)
        recovered = wait_for_lean_recovery(project_id, lean_generation_2)
        lean_generation_3 = int(recovered["lean"]["generation"])
        assert recovered["lean"]["state"] == "ready"
        assert overlay(recovered, FIXTURE_URI)["version"] == 101
        assert int(recovered["lean"]["process_id"]) != lean_pid_2
        assert lean_generation_3 > lean_generation_2

    before_daemon_crash = pong(run_cli("ping"))
    daemon_generation = before_daemon_crash["daemon_generation"]
    daemon_pid = int(before_daemon_crash["process_id"])
    os.kill(daemon_pid, signal.SIGKILL)
    repair_log = repair_after_daemon_crash()
    print(f"daemon repair observations:\n{repair_log}")

    after_daemon_crash = pong(run_cli("ping"))
    assert after_daemon_crash["daemon_generation"] != daemon_generation
    assert int(after_daemon_crash["process_id"]) != daemon_pid

    reopened_after_crash = project(run_cli("open-project", str(ROOT)))
    assert reopened_after_crash["project_id"] == project_id
    assert Path(reopened_after_crash["store_path"]) == store_path
    assert Path(reopened_after_crash["store_path"]).is_file()
    assert reopened_after_crash["overlay_documents"] == []

    run_cli("daemon-stop")
    print("M5 atlasd live smoke: PASS")


if __name__ == "__main__":
    main()
