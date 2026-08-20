#!/usr/bin/env python3
"""Live M6 smoke test for Lean-confirmed semantic queries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable {name}")
    return value


CLI = Path(required_env("ATLAS_M6_CLI"))
MCP = Path(required_env("ATLAS_M6_MCP"))
ROOT = Path(required_env("ATLAS_M6_ROOT")).resolve()
FIXTURE = Path(required_env("ATLAS_M6_FIXTURE")).resolve()
FIXTURE_URI = required_env("ATLAS_M6_FIXTURE_URI")
QUERY_POSITION = {"line": 8, "character": 0}


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


def query_result(result: subprocess.CompletedProcess[str], expected: str) -> dict:
    value = payload(result)
    assert value["type"] == "query", value
    query = value["value"]
    assert query["query"] == expected, query
    return query["result"]


def mcp_query(project_id: str, generation: int) -> dict:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "atlas.goal_match",
                "arguments": {
                    "project_id": project_id,
                    "lean_generation": generation,
                    "goal": "True",
                    "candidates": ["True.intro", "double_two"],
                    "position": QUERY_POSITION,
                },
            },
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
    print(f"$ {MCP.name}  # initialize + atlas.goal_match", flush=True)
    print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    tool_response = next(response for response in responses if response.get("id") == 2)
    assert tool_response["result"]["isError"] is False, tool_response
    encoded = tool_response["result"]["content"][0]["text"]
    value = json.loads(encoded)
    assert value["type"] == "query", value
    assert value["value"]["query"] == "goal_match", value
    return value["value"]["result"]


def main() -> None:
    assert CLI.is_file(), CLI
    assert MCP.is_file(), MCP
    assert FIXTURE.is_file(), FIXTURE

    run_cli("daemon-stop", check=False)
    opened = project(run_cli("open-project", str(ROOT)))
    project_id = opened["project_id"]
    generation = int(opened["lean"]["generation"])
    assert opened["lean"]["state"] == "ready", opened

    project(
        run_cli(
            "open-document",
            project_id,
            FIXTURE_URI,
            str(FIXTURE),
            "1",
            str(generation),
        )
    )

    goal_match = query_result(
        run_cli(
            "goal-match",
            project_id,
            "True",
            "True.intro",
            "double_two",
        ),
        "goal_match",
    )
    assert [match["declaration"] for match in goal_match["matches"]] == ["True.intro"], goal_match
    assert goal_match["matches"][0]["closes_goal"] is True, goal_match
    rejection = next(
        item for item in goal_match["rejections"] if item["declaration"] == "double_two"
    )
    assert rejection["failure"]["class"] != "internal", rejection

    why_not = query_result(
        run_cli("why-not", project_id, "double_two", "True"), "why_not"
    )
    assert why_not["applicable"] is False, why_not
    assert why_not["failure"] is not None, why_not
    assert why_not["failure"]["class"] != "internal", why_not

    instance_path = query_result(
        run_cli("instance-path", project_id, "Inhabited Nat"), "instance_path"
    )
    assert instance_path.get("failure") is None, instance_path
    assert instance_path["instance_pretty"], instance_path
    assert instance_path["dependencies"], instance_path

    with tempfile.TemporaryDirectory(prefix="atlas-m6-") as temp_dir:
        spec = Path(temp_dir) / "minimal-context.json"
        spec.write_text(
            json.dumps(
                {
                    "goal": "True",
                    "proof": "True.intro",
                    "hypotheses": [
                        {"name": "h", "type_text": "True", "kind": "explicit"},
                        {"name": "n", "type_text": "Nat", "kind": "explicit"},
                    ],
                    "position": QUERY_POSITION,
                    "max_evaluations": 8,
                }
            )
        )
        minimal = query_result(
            run_cli("minimal-context", project_id, str(spec), str(generation)),
            "minimal_context",
        )
    assert len(minimal["frontier"]) == 1, minimal
    assert minimal["frontier"][0]["kept"] == [], minimal
    assert {binding["name"] for binding in minimal["frontier"][0]["removed"]} == {
        "h",
        "n",
    }, minimal

    composition = query_result(
        run_cli(
            "compose",
            project_id,
            "atlas_true_left",
            "atlas_true_right",
            "True → True",
        ),
        "compose",
    )
    assert composition["status"] == "proved", composition
    assert composition.get("failure") is None, composition
    assert composition["proof_pretty"], composition

    mcp = mcp_query(project_id, generation)
    assert [match["declaration"] for match in mcp["matches"]] == ["True.intro"], mcp

    restarted = project(run_cli("restart-lean", project_id, str(generation)))
    assert int(restarted["lean"]["generation"]) > generation, restarted
    fresh = run_cli("instance-path", project_id, "Inhabited Nat", check=False)
    # Named query commands intentionally omit a generation guard and remain usable
    # after a restart. The generic query path carries the explicit stale guard.
    assert fresh.returncode == 0, fresh.stderr

    run_cli("daemon-stop")
    print("M6 semantic query smoke: PASS")


if __name__ == "__main__":
    main()
