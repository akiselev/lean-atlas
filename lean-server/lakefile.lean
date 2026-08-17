import Lake
open Lake DSL

package atlasServer where

@[default_target]
lean_lib AtlasServer where
  -- A Lean shared library is loadable via `--plugin` only when it has exactly
  -- one root and its native library name matches that root's package-qualified
  -- initialization stem. Keep the sibling server modules local via the glob;
  -- Plugin imports the transitive implementation graph.
  roots := #[`Atlas.Server.Plugin]
  globs := #[`Atlas.Server.+]
  libName := "atlasServer_Atlas_Server_Plugin"
