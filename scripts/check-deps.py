#!/usr/bin/env python3
import json
import subprocess
import sys

metadata = json.loads(
    subprocess.check_output(
        ["cargo", "metadata", "--format-version=1", "--no-deps"], text=True
    )
)
dependencies = {
    package["name"]: {dependency["name"] for dependency in package["dependencies"]}
    for package in metadata["packages"]
}
workspace = set(dependencies)

# Existing core layering: lower layers cannot grow back-edges into higher ones.
forbidden = {
    "atlas-schema": {
        "atlas-index",
        "atlas-store",
        "atlas-logic",
        "atlas-lean-client",
        "atlas-engine",
    },
    "atlas-index": {"atlas-store", "atlas-logic", "atlas-lean-client", "atlas-engine"},
    "atlas-store": {"atlas-index", "atlas-logic", "atlas-lean-client", "atlas-engine"},
    "atlas-logic": {"atlas-store", "atlas-lean-client", "atlas-engine"},
    "atlas-lean-protocol": {
        "atlas-store",
        "atlas-logic",
        "atlas-lean-client",
        "atlas-engine",
    },
    "atlas-lean-client": {"atlas-store", "atlas-logic", "atlas-engine"},
    "atlas-engine": {
        "atlas-daemon-protocol",
        "atlas-client",
        "atlasd",
        "atlas-cli",
        "atlas-mcp",
    },
}

errors = [
    f"forbidden dependency: {package} -> {dependency}"
    for package, blocked in forbidden.items()
    for dependency in sorted(dependencies.get(package, set()) & blocked)
]

# M5 process-boundary ownership is intentionally stricter than the legacy core
# checks. These are the only direct workspace edges permitted for each daemon
# layer. External crates (daemonkit, serde, tokio, etc.) are outside this check.
allowed_workspace_edges = {
    "atlas-daemon-protocol": set(),
    "atlas-client": {"atlas-daemon-protocol"},
    "atlasd": {"atlas-engine", "atlas-daemon-protocol"},
    "atlas-cli": {"atlas-client"},
    "atlas-mcp": {"atlas-client"},
}

for package, allowed in allowed_workspace_edges.items():
    actual = dependencies.get(package, set()) & workspace
    for dependency in sorted(actual - allowed):
        errors.append(
            f"forbidden M5 dependency: {package} -> {dependency}; "
            f"allowed workspace deps: {sorted(allowed)}"
        )

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)

print("Atlas dependency layering: OK")
