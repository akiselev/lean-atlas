import Atlas.Server.Protocol

namespace Atlas.Server
open Lean Server
abbrev ExprRef := WithRpcRef Expr
abbrev DeclRef := WithRpcRef Name
end Atlas.Server
