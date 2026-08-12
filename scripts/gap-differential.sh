#!/usr/bin/env bash
# gap-differential.sh — gate for KIT 3, the sextant -> GAP/QDistRnd bundle.
#
# Mandatory (always run, must pass):
#   * mtxe-check.py — the stdlib, stack-independent checker: recompute every
#     count, re-verify MTXE isotropy, replay the Frobenius orbit partition, and
#     REJECT the planted-invalid corrupted matrix.
# Best-effort (run when the tool is present; a firing failure fails the gate,
# absence does not):
#   * reproducibility — regenerate the bundle via the sextant example and diff
#     against the committed files (cargo, in ~/sinbad only).
#   * GAP replay — run verify.g if GAP is installed; otherwise the bundle IS the
#     deliverable (stated, not failed).
#
# Exit 0 iff every mandatory check passed. Each exit status is read immediately.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE="$REPO/research/data/referee-kits/gap"
SINBAD="${SINBAD_DIR:-$HOME/sinbad}"

fail=0

echo "=== gap-differential: KIT 3 bundle at $BUNDLE ==="

# ---- 1. mandatory: stdlib checker -----------------------------------------
echo
echo "--- [mandatory] mtxe-check.py (stack-independent) ---"
python3 "$SCRIPT_DIR/mtxe-check.py" "$BUNDLE"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "mtxe-check.py FAILED (exit $rc)"
  fail=1
fi

# ---- 2. best-effort: reproducibility via the sextant example --------------
echo
echo "--- [best-effort] reproducibility (regenerate + diff) ---"
if command -v cargo >/dev/null 2>&1 && [ -d "$SINBAD/crates/sextant" ]; then
  tmp="$(mktemp -d)"
  ( cd "$SINBAD" && cargo run -q -p sinbad-sextant --example gap_export -- "$tmp" )
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "regeneration FAILED (cargo exit $rc)"
    fail=1
  else
    diffrc=0
    diff -u "$BUNDLE/manifest.json" "$tmp/manifest.json" || diffrc=1
    diff -r "$BUNDLE/lagrangians" "$tmp/lagrangians" || diffrc=1
    diff -r "$BUNDLE/corrupted"   "$tmp/corrupted"   || diffrc=1
    diff -r "$BUNDLE/orbits"      "$tmp/orbits"      || diffrc=1
    if [ "$diffrc" -ne 0 ]; then
      echo "reproducibility FAILED: regenerated bundle differs from committed"
      fail=1
    else
      echo "reproducible: regenerated bundle is byte-identical to committed"
    fi
  fi
  rm -rf "$tmp"
else
  echo "SKIP: cargo or $SINBAD/crates/sextant not available (committed bundle is the deliverable)"
fi

# ---- 3. best-effort: GAP replay -------------------------------------------
echo
echo "--- [best-effort] GAP replay (verify.g) ---"
# Resolve a real gap executable, not a shell alias (aliases do not apply in
# non-interactive shells anyway, but be explicit).
GAP_BIN=""
for cand in gap; do
  if command -v "$cand" >/dev/null 2>&1; then
    resolved="$(command -v "$cand")"
    # reject if it is not actually GAP (e.g. an alias masking git)
    if "$resolved" --version >/dev/null 2>&1; then GAP_BIN="$resolved"; fi
  fi
done
if [ -n "$GAP_BIN" ]; then
  ( cd "$BUNDLE" && "$GAP_BIN" -q verify.g )
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "GAP verify.g FAILED (exit $rc)"
    fail=1
  else
    echo "GAP verify.g PASSED"
  fi
else
  echo "GAP NOT INSTALLED: the bundle IS the deliverable."
  echo "  A referee replays it with:  cd $BUNDLE && gap verify.g"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "=== gap-differential: PASS ==="
  exit 0
else
  echo "=== gap-differential: FAIL ==="
  exit 1
fi
