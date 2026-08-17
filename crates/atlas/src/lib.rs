//! Compatibility facade for the Atlas v1 indexes plus v2 contracts.

pub mod artifact;
pub mod dict;
pub mod equiv;
pub mod graph;
pub mod intuition;
pub mod intuition_benchmark;
pub mod intuition_concept;
pub mod intuition_viewpoint;
pub mod json;
pub mod logical;
pub mod skel;
pub mod statement;

/// v2 owns the relation registry in `atlas-schema`; the old facade reexports it so existing
/// callers keep the `atlas::relation::*` path while parallel enum/parser registries disappear.
pub use atlas_schema::relation;
