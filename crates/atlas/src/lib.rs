//! Index and query engine for the Atlas (atlas.md).
//!
//! Build order per atlas.md §5: dependency graph first, consuming JSONL rows
//! from the Lean-side extractor (atlas.md §6, Channel 2).

pub mod dict;
pub mod equiv;
pub mod graph;
pub mod intuition;
pub mod intuition_benchmark;
pub mod intuition_concept;
pub mod intuition_viewpoint;
pub mod json;
pub mod logical;
pub mod relation;
pub mod scientific;
pub mod skel;
pub mod statement;
