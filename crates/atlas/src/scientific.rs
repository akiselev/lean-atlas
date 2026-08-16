//! Read-only index over external scientific refinement records.
//!
//! Lean Atlas remains an engine over checked Lean objects. Scientific/compiler records from
//! Resolvent/Sinbad/Pi Lab are useful context, but they are not silently converted into
//! [`crate::relation::Relation`] edges. In particular, numerical or empirical evidence can
//! never acquire `Warrant::Proved` merely by being imported here.

use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum EvidenceAxis {
    Formal,
    Numerical,
    Empirical,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScientificEvidence {
    pub axis: EvidenceAxis,
    pub grade: String,
    pub artifact: Option<String>,
    pub note: String,
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ScientificArtifactKind {
    FormalSpec,
    ResolventModel,
    VariationalForm,
    DiscreteProgram,
    OperatorProgram,
    ExecutableProgram,
    SimulationResult,
    ObservablePrediction,
    ExperimentalDataset,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScientificArtifact {
    pub digest: String,
    pub kind: ScientificArtifactKind,
    pub locator: Option<String>,
    pub producer: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScopeRecord {
    pub label: String,
    pub parameter_region: Option<String>,
    pub spatial_domain: Option<String>,
    pub temporal_domain: Option<String>,
    pub restrictions: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScientificRefinement {
    pub receipt: String,
    pub source: ScientificArtifact,
    pub target: ScientificArtifact,
    pub relation: String,
    pub source_scope: ScopeRecord,
    pub target_scope: ScopeRecord,
    pub open_obligations: Vec<String>,
    pub evidence: Vec<ScientificEvidence>,
    /// A checked Lean theorem may be named here when it warrants the formal relation.
    pub lean_theorem: Option<String>,
}

impl ScientificRefinement {
    pub fn changes_scope(&self) -> bool {
        self.source_scope != self.target_scope
    }

    pub fn has_formal_warrant(&self) -> bool {
        self.lean_theorem.is_some()
            || self
                .evidence
                .iter()
                .any(|e| e.axis == EvidenceAxis::Formal && e.grade == "kernel-proved")
    }

    pub fn has_open_obligations(&self) -> bool {
        !self.open_obligations.is_empty()
    }
}

#[derive(Clone, Debug, Default)]
pub struct ScientificIndex {
    by_receipt: BTreeMap<String, ScientificRefinement>,
    by_artifact: BTreeMap<String, Vec<String>>,
}

impl ScientificIndex {
    pub fn insert(&mut self, refinement: ScientificRefinement) -> Option<ScientificRefinement> {
        let receipt = refinement.receipt.clone();
        let replaced = self.by_receipt.remove(&receipt);
        if let Some(old) = &replaced {
            for digest in [&old.source.digest, &old.target.digest] {
                let mut delete_bucket = false;
                if let Some(refs) = self.by_artifact.get_mut(digest) {
                    refs.retain(|id| id != &receipt);
                    delete_bucket = refs.is_empty();
                }
                if delete_bucket {
                    self.by_artifact.remove(digest);
                }
            }
        }

        for digest in [&refinement.source.digest, &refinement.target.digest] {
            let refs = self.by_artifact.entry(digest.clone()).or_default();
            if !refs.contains(&receipt) {
                refs.push(receipt.clone());
                refs.sort();
            }
        }
        self.by_receipt.insert(receipt, refinement);
        replaced
    }

    pub fn get(&self, receipt: &str) -> Option<&ScientificRefinement> {
        self.by_receipt.get(receipt)
    }

    pub fn touching_artifact(&self, digest: &str) -> impl Iterator<Item = &ScientificRefinement> {
        self.by_artifact
            .get(digest)
            .into_iter()
            .flat_map(|ids| ids.iter())
            .filter_map(|id| self.by_receipt.get(id))
    }

    pub fn scope_changes(&self) -> impl Iterator<Item = &ScientificRefinement> {
        self.by_receipt.values().filter(|r| r.changes_scope())
    }

    pub fn unresolved(&self) -> impl Iterator<Item = &ScientificRefinement> {
        self.by_receipt
            .values()
            .filter(|r| r.has_open_obligations())
    }

    pub fn without_formal_warrant(&self) -> impl Iterator<Item = &ScientificRefinement> {
        self.by_receipt.values().filter(|r| !r.has_formal_warrant())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scope(label: &str) -> ScopeRecord {
        ScopeRecord {
            label: label.into(),
            parameter_region: None,
            spatial_domain: None,
            temporal_domain: None,
            restrictions: Vec::new(),
        }
    }

    #[test]
    fn empirical_evidence_is_not_formal_warrant() {
        let r = ScientificRefinement {
            receipt: "r1".into(),
            source: ScientificArtifact {
                digest: "a".into(),
                kind: ScientificArtifactKind::FormalSpec,
                locator: Some("Physics.Spec".into()),
                producer: "lean".into(),
            },
            target: ScientificArtifact {
                digest: "b".into(),
                kind: ScientificArtifactKind::SimulationResult,
                locator: None,
                producer: "sinbad".into(),
            },
            relation: "observable-interpretation".into(),
            source_scope: scope("declared"),
            target_scope: scope("declared"),
            open_obligations: Vec::new(),
            evidence: vec![ScientificEvidence {
                axis: EvidenceAxis::Empirical,
                grade: "experimentally-validated".into(),
                artifact: Some("dataset:run-1".into()),
                note: "matched measurements".into(),
            }],
            lean_theorem: None,
        };
        assert!(!r.has_formal_warrant());
    }

    #[test]
    fn scope_changes_remain_queryable() {
        let mut index = ScientificIndex::default();
        let mut target_scope = scope("restricted");
        target_scope.restrictions.push("orbit-family-A".into());
        index.insert(ScientificRefinement {
            receipt: "r2".into(),
            source: ScientificArtifact {
                digest: "a".into(),
                kind: ScientificArtifactKind::FormalSpec,
                locator: None,
                producer: "lean".into(),
            },
            target: ScientificArtifact {
                digest: "b".into(),
                kind: ScientificArtifactKind::ResolventModel,
                locator: None,
                producer: "resolvent".into(),
            },
            relation: "specialization".into(),
            source_scope: scope("global"),
            target_scope,
            open_obligations: vec!["scope transport".into()],
            evidence: Vec::new(),
            lean_theorem: None,
        });
        assert_eq!(index.scope_changes().count(), 1);
        assert_eq!(index.unresolved().count(), 1);
    }

    #[test]
    fn replacing_a_receipt_updates_artifact_indexes() {
        let mut index = ScientificIndex::default();
        let first = ScientificRefinement {
            receipt: "r3".into(),
            source: ScientificArtifact {
                digest: "old-source".into(),
                kind: ScientificArtifactKind::FormalSpec,
                locator: None,
                producer: "lean".into(),
            },
            target: ScientificArtifact {
                digest: "old-target".into(),
                kind: ScientificArtifactKind::ResolventModel,
                locator: None,
                producer: "resolvent".into(),
            },
            relation: "reformulation".into(),
            source_scope: scope("declared"),
            target_scope: scope("declared"),
            open_obligations: Vec::new(),
            evidence: Vec::new(),
            lean_theorem: None,
        };
        index.insert(first.clone());
        let mut replacement = first;
        replacement.source.digest = "new-source".into();
        replacement.target.digest = "new-target".into();
        index.insert(replacement);

        assert_eq!(index.touching_artifact("old-source").count(), 0);
        assert_eq!(index.touching_artifact("old-target").count(), 0);
        assert_eq!(index.touching_artifact("new-source").count(), 1);
        assert_eq!(index.touching_artifact("new-target").count(), 1);
    }
}
