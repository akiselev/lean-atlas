//! Provenance-bearing links from exact Lean declarations to artifacts owned by external
//! systems such as Resolvent, Sinbad and Pi Lab.
//!
//! Atlas remains read-only and does not parse the foreign artifact into mathematical truth.
//! The link records what is being claimed and what warrants the link. In particular, a
//! simulation agreeing with a theorem is not itself a proof of that theorem.

use std::fmt;

/// A versioned object owned by another authority.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ExternalArtifact {
    /// Owning system, e.g. `resolvent`, `sinbad`, `pi-lab`.
    pub authority: String,
    /// Authority-native schema/version tag.
    pub schema: String,
    /// Authority-native content digest, including algorithm prefix where applicable.
    pub digest: String,
    /// Optional durable locator (repository path, object-store URI, run id, ...).
    pub locator: Option<String>,
}

/// Semantic meaning of a declaration/artifact edge.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ArtifactRelationKind {
    /// The artifact is a deep-IR reification of the declaration's semantics.
    ReifiedAs,
    /// The artifact refines/lowers the declaration through an explicit refinement chain.
    RefinedInto,
    /// The executable/simulation artifact implements the declaration-derived model.
    ImplementedBy,
    /// The artifact checks an invariant/property derived from the declaration.
    ValidatedBy,
    /// The artifact is an empirical observation/measurement related to the declaration.
    ObservedBy,
    /// A generic provenance edge that does not assert semantic equivalence.
    DerivedArtifact,
}

impl ArtifactRelationKind {
    /// A short stable wire/display name.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ReifiedAs => "reified_as",
            Self::RefinedInto => "refined_into",
            Self::ImplementedBy => "implemented_by",
            Self::ValidatedBy => "validated_by",
            Self::ObservedBy => "observed_by",
            Self::DerivedArtifact => "derived_artifact",
        }
    }
}

/// What warrants the external link. This is intentionally not Atlas's mathematical
/// `Warrant`: external execution/measurement evidence answers different questions.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ArtifactEvidence {
    /// Lean theorem proving the reification/refinement statement.
    LeanTheorem { name: String },
    /// A small checker accepted a certificate produced by the external system.
    CheckedCertificate { checker: String, digest: String },
    /// Structural identity/provenance (hash equality, declared producer edge).
    Structural { description: String },
    /// Source/campaign author asserted the relationship; not independently proved.
    Asserted { source: String },
    /// Search/ranking proposed the relationship. This is a lead only.
    Heuristic { method: String },
    /// Experimental comparison with an explicit dataset/observable contract.
    Empirical { dataset: String, protocol: String },
}

/// Typed relation between one Lean declaration and one external artifact.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArtifactLink {
    pub declaration: String,
    pub artifact: ExternalArtifact,
    pub kind: ArtifactRelationKind,
    pub evidence: ArtifactEvidence,
}

impl ArtifactLink {
    /// Construct a link while enforcing the strongest category rule: a semantic
    /// `ReifiedAs` edge may only be advertised as such when a Lean theorem or checked
    /// certificate warrants it. Merely asserted/heuristic/empirical evidence cannot turn a
    /// foreign IR into the declaration's formal semantics.
    pub fn new(
        declaration: impl Into<String>,
        artifact: ExternalArtifact,
        kind: ArtifactRelationKind,
        evidence: ArtifactEvidence,
    ) -> Result<Self, ArtifactLinkError> {
        if kind == ArtifactRelationKind::ReifiedAs
            && !matches!(
                evidence,
                ArtifactEvidence::LeanTheorem { .. } | ArtifactEvidence::CheckedCertificate { .. }
            )
        {
            return Err(ArtifactLinkError::InsufficientEvidence { kind });
        }
        Ok(Self {
            declaration: declaration.into(),
            artifact,
            kind,
            evidence,
        })
    }

    /// Whether this link itself constitutes a formal/checker-backed semantic bridge.
    /// `ValidatedBy`/`ObservedBy` remain execution/empirical links regardless of evidence.
    pub fn is_formal_bridge(&self) -> bool {
        matches!(
            (&self.kind, &self.evidence),
            (
                ArtifactRelationKind::ReifiedAs | ArtifactRelationKind::RefinedInto,
                ArtifactEvidence::LeanTheorem { .. } | ArtifactEvidence::CheckedCertificate { .. }
            )
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ArtifactLinkError {
    InsufficientEvidence { kind: ArtifactRelationKind },
}

impl fmt::Display for ArtifactLinkError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InsufficientEvidence { kind } => write!(
                f,
                "external relation {} requires a Lean theorem or checked certificate",
                kind.as_str()
            ),
        }
    }
}

impl std::error::Error for ArtifactLinkError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn artifact() -> ExternalArtifact {
        ExternalArtifact {
            authority: "resolvent".into(),
            schema: "resolvent-science/0.1".into(),
            digest: "blake3:abc".into(),
            locator: None,
        }
    }

    #[test]
    fn heuristic_cannot_masquerade_as_formal_reification() {
        let result = ArtifactLink::new(
            "Physics.Heat.spec",
            artifact(),
            ArtifactRelationKind::ReifiedAs,
            ArtifactEvidence::Heuristic {
                method: "shape similarity".into(),
            },
        );
        assert!(matches!(
            result,
            Err(ArtifactLinkError::InsufficientEvidence {
                kind: ArtifactRelationKind::ReifiedAs
            })
        ));
    }

    #[test]
    fn theorem_backed_reification_is_formal_bridge() {
        let link = ArtifactLink::new(
            "Physics.Heat.spec",
            artifact(),
            ArtifactRelationKind::ReifiedAs,
            ArtifactEvidence::LeanTheorem {
                name: "Physics.Heat.spec_reify_sound".into(),
            },
        )
        .unwrap();
        assert!(link.is_formal_bridge());
    }

    #[test]
    fn measurement_link_is_not_formal_truth() {
        let link = ArtifactLink::new(
            "Physics.Heat.spec",
            artifact(),
            ArtifactRelationKind::ObservedBy,
            ArtifactEvidence::Empirical {
                dataset: "experiment-17".into(),
                protocol: "frozen-v2".into(),
            },
        )
        .unwrap();
        assert!(!link.is_formal_bridge());
    }
}
