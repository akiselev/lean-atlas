import Atlas.Server.Protocol

namespace Atlas.Server

/-- Marker module for position-local goal/InfoTree APIs. The first M4 gate uses the same
snapshot-position machinery through the semantic RPCs; `goalAt`/`infoAt` are the next API wave. -/
structure InfoCapabilities where
  goal_at : Bool := false
  info_at : Bool := false

end Atlas.Server
