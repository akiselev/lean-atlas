mod ast;
mod eval;
mod optimized;
mod reference;
mod source;

pub use ast::*;
pub use optimized::*;
pub use reference::*;
pub use source::*;

use thiserror::Error;

#[derive(Debug,Error)]
pub enum LogicError{
 #[error("relation arity mismatch")]Arity,
 #[error("unsafe rule: head variable is not bound by a positive body atom: {0}")]UnsafeRule(String),
 #[error("program contains recursion through negation")]UnstratifiedNegation,
 #[error("evaluation exceeded {0} fixed-point rounds")]RecursionLimit(usize),
 #[error("evaluation cancelled")]Cancelled,
 #[error("fact source: {0}")]Source(String),
}
