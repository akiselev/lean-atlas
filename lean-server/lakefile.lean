import Lake
open Lake DSL

package atlasServer where

@[default_target]
lean_lib AtlasServer where
  roots := #[
    `Atlas.Server.Protocol,
    `Atlas.Server.Handles,
    `Atlas.Server.Oracle,
    `Atlas.Server.Queries,
    `Atlas.Server.Rpc,
    `Atlas.Server.Info,
    `Atlas.Server.Plugin
  ]
