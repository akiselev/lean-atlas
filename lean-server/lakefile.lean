import Lake
open Lake DSL

package atlasServer where

@[default_target]
lean_lib AtlasServer where
  roots := #[`Atlas.Server.Plugin]
