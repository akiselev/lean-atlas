//! Runtime primitives owned by the semantic engine boundary.
//!
//! `atlasd` depends on `atlas-engine`, not directly on lower storage or Lean
//! transport crates. This module intentionally exposes only the primitives the
//! daemon needs to own a project session.

pub use atlas_lean_client::{
    ClientError as LeanError, LeanClient, LeanCommand, TransportError as LeanTransportError,
};
pub use atlas_store::Store;
