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

# `lean --plugin` derives the module initializer name from the *library basename*.
# Lake's shared facet names the artifact after package + target (`atlasServer_AtlasServer`),
# while the actual root module is `Atlas.Server` and exports `initialize_Atlas_Server`.
# Present the same bytes under the module-derived basename expected by Lean's loader.
mkdir -p "$out_dir"
dest="$out_dir/libAtlas_Server$ext"
cp "$shared" "$dest"

if command -v nm >/dev/null 2>&1 && [ "$ext" != ".dll" ]; then
  if ! nm -D "$dest" 2>/dev/null | grep -qE '[[:space:]]initialize_Atlas_Server$'; then
    # macOS `nm` does not support `-D`; retry its default global-symbol view.
    if ! nm -g "$dest" 2>/dev/null | grep -qE '[[:space:]_]initialize_Atlas_Server$'; then
      echo "shared library does not export initialize_Atlas_Server" >&2
      nm -D "$dest" 2>/dev/null | grep 'initialize_' >&2 || true
      nm -g "$dest" 2>/dev/null | grep 'initialize_' >&2 || true
      exit 1
    fi
  fi
fi

printf '%s\n' "$dest"
