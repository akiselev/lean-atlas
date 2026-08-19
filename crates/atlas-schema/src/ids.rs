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
    DeclarationRevisionId,
    EntityId,
    EntityRevisionId,
    FactId,
    RelationTypeId,
    RelationSchemaId,
    EvidenceId,
    ArtifactLinkId,
    ArtifactId,
    DatasetId,
    ExperimentId,
    CandidateId,
    AssayId,
    OracleReceiptId,
    ReceiptId,
    ActivityId,
    EnvironmentId,
    FormalEnvironmentId,
    ExecutionEnvironmentId,
    SourceSnapshotId,
    DocumentSnapshotId,
    LocalContextSnapshotId,
    CorpusSnapshotId,
    DatasetSnapshotId,
    PolicyVersionId,
    ClaimRevisionId,
    ClaimScopeId,
    ClaimKeyId,
    SupportCircuitId,
    ChallengeId,
    ProposalId,
    ProposedClaimId,
    FalsifierId,
    ResearchObligationId,
    ResearchPlanId,
    ResearchRunId,
    AssessmentId,
    ActorId,
    IndependenceGroupId,
    CompletenessWitnessId,
    DomainId,
    QuantitySystemId,
    CoordinateFrameId,
    ConventionId,
    RegimeId,
    ApproximationId,
);
