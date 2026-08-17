use serde::{Deserialize, Serialize};

macro_rules! id_type {
    ($($name:ident),+ $(,)?) => {$(
        #[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(pub u64);
    )+};
}

id_type!(
    DeclarationId,
    EntityId,
    FactId,
    RelationTypeId,
    EvidenceId,
    ArtifactLinkId,
    DatasetId,
    ExperimentId,
    CandidateId,
    AssayId,
    OracleReceiptId,
    EnvironmentId,
);
