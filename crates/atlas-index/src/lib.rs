//! Lean-independent structural indexing primitives for Atlas.
//!
//! The I3 term arena, erasure hierarchy, and least-general-generalization engine are
//! deliberately separated from corpus loading, the semantic store, and Lean RPC. The
//! existing `atlas::skel` modules re-export this crate during the migration so downstream
//! callers do not need a flag-day API change.

pub mod erase;
pub mod lgg;
pub mod term;
