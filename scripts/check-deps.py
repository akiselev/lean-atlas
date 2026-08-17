#!/usr/bin/env python3
import json, subprocess, sys
m=json.loads(subprocess.check_output(["cargo","metadata","--format-version=1","--no-deps"],text=True))
p={x["name"]:{d["name"] for d in x["dependencies"]} for x in m["packages"]}
f={"atlas-schema":{"atlas-index","atlas-store","atlas-logic","atlas-lean-client","atlas-engine"},"atlas-index":{"atlas-store","atlas-logic","atlas-lean-client","atlas-engine"},"atlas-store":{"atlas-index","atlas-logic","atlas-lean-client","atlas-engine"},"atlas-logic":{"atlas-store","atlas-lean-client","atlas-engine"},"atlas-lean-protocol":{"atlas-store","atlas-logic","atlas-lean-client","atlas-engine"},"atlas-lean-client":{"atlas-store","atlas-logic","atlas-engine"}}
e=[f"forbidden dependency: {pkg} -> {dep}" for pkg,b in f.items() for dep in sorted(p.get(pkg,set())&b)]
if e: print("\n".join(e),file=sys.stderr);sys.exit(1)
print("Atlas dependency layering: OK")
