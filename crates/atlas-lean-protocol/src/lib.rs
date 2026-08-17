mod ops;
mod types;
pub use ops::*;
pub use types::*;

pub const PROTOCOL_VERSION:&str="2.0.0";
pub const HELLO:&str="Atlas.Server.hello";
pub const LOOKUP_DECL:&str="Atlas.Server.lookupDecl";
pub const GET_TYPE:&str="Atlas.Server.getType";
pub const INFER_TYPE:&str="Atlas.Server.inferType";
pub const WHNF:&str="Atlas.Server.whnf";
pub const IS_DEFEQ:&str="Atlas.Server.isDefEq";
pub const UNIFY:&str="Atlas.Server.unify";
pub const SYNTH_INSTANCE:&str="Atlas.Server.synthInstance";
pub const APPLY:&str="Atlas.Server.apply";
pub const ELABORATE:&str="Atlas.Server.elaborate";
pub const CHECK_PROOF:&str="Atlas.Server.checkProof";
pub const BATCH_DEFEQ:&str="Atlas.Server.batchDefEq";
