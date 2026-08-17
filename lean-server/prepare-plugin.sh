#!/usr/bin/env bash
set -euo pipefail

build_dir="${1:-$PWD/.lake/build}"
out_dir="${2:-$build_dir/plugin}"

shared="$(find "$build_dir/lib" -maxdepth 1 -type f \( -name '*.so' -o -name '*.dylib' -o -name '*.dll' \) -print -quit 2>/dev/null || true)"
if [ -z "$shared" ]; then
  echo "AtlasServer shared library not found under $build_dir/lib" >&2
  find "$build_dir" -maxdepth 5 -type f -print >&2 || true
  exit 1
fi

case "$shared" in
  *.so) ext=.so ;;
  *.dylib) ext=.dylib ;;
  *.dll) ext=.dll ;;
  *) echo "unsupported shared-library extension: $shared" >&2; exit 1 ;;
esac

# Lean derives the initializer it calls from the plugin *basename*. Lake's shared
# facet may name the file after package + target while the exported initializer keeps
# the module path as a separate underscore component. Read the actual root initializer
# and present the same library bytes under the basename that maps back to that symbol.
#
# Example observed with Lake 5 / Lean 4.33:
#   file:   libatlasServer_AtlasServer.so
#   export: initialize_atlasServer_Atlas_Server
# so Lean must be handed libatlasServer_Atlas_Server.so.
initializer=""
if command -v nm >/dev/null 2>&1 && [ "$ext" != ".dll" ]; then
  symbols="$(nm -D "$shared" 2>/dev/null || nm -g "$shared" 2>/dev/null || true)"
  initializer="$(printf '%s\n' "$symbols" | sed -nE 's/^.*[[:space:]](_?initialize_[[:alnum:]_]*Atlas_Server)$/\1/p' | sed 's/^_//' | head -n1)"
fi

if [ -z "$initializer" ]; then
  echo "could not discover the Atlas.Server root initializer in $shared" >&2
  if command -v nm >/dev/null 2>&1; then
    nm -D "$shared" 2>/dev/null | grep 'initialize_' >&2 || true
    nm -g "$shared" 2>/dev/null | grep 'initialize_' >&2 || true
  fi
  exit 1
fi

stem="${initializer#initialize_}"
mkdir -p "$out_dir"
dest="$out_dir/lib${stem}${ext}"
cp "$shared" "$dest"

printf '%s\n' "$dest"
