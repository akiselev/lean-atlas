//! Versioned claim, scope, receipt, evidence, proposal and assessment contracts.
//!
//! This module is additive while the v2 `FactRow` compatibility surface is
//! migrated. The durable scientific model deliberately has no universal
//! `Proved > Structural > Asserted > Heuristic` ordering: formal, numerical,
//! empirical, documentary and reproducibility evidence are different axes.

use crate::{
    ActivityId, ActorId, ApproximationId, ArtifactId, AssessmentId, ChallengeId, ClaimKeyId,
    ClaimRevisionId, ClaimScopeId, CompletenessWitnessId, ConventionId, CoordinateFrameId,
    CorpusSnapshotId, DatasetSnapshotId, DeclarationRevisionId, DocumentSnapshotId, DomainId,
    EvidenceId, ExecutionEnvironmentId, FalsifierId, FormalEnvironmentId, IndependenceGroupId,
    LocalContextSnapshotId, PolicyVersionId, ProposalId, ProposedClaimId, QuantitySystemId,
    ReceiptId, RegimeId, RelationExecution, RelationSchemaId, ResearchObligationId, ResearchPlanId,
    ResearchRunId, SourceSnapshotId, SupportCircuitId,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
};

pub const RESEARCH_SCHEMA_VERSION: &str = "atlas-research-v3";

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct Digest {
    pub algorithm: String,
    pub value: String,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct SchemaId {
    pub name: String,
    pub version: u32,
    pub digest: Digest,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct ArtifactRef {
    pub id: ArtifactId,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub digest: Option<Digest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub locator: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SourceAnchor {
    Repository {
        repository: String,
        commit: String,
        path: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        start_line: Option<u32>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        end_line: Option<u32>,
    },
    Paper {
        citation: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        doi: Option<String>,
        locator: String,
    },
    Dataset {
        snapshot: DatasetSnapshotId,
        locator: String,
    },
    Lean {
        declaration: DeclarationRevisionId,
        environment: FormalEnvironmentId,
    },
    Artifact {
        artifact: ArtifactRef,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        member: Option<String>,
    },
    Generated {
        artifact: ArtifactRef,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        span: Option<String>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProducerIdentity {
    pub repository: String,
    pub commit: String,
    pub package: String,
    pub package_version: String,
    pub executable_digest: Digest,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActivityIdentity {
    pub id: ActivityId,
    pub kind: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionEnvironment {
    pub id: ExecutionEnvironmentId,
    pub operating_system: String,
    pub architecture: String,
    #[serde(default)]
    pub runtime_versions: BTreeMap<String, String>,
    #[serde(default)]
    pub environment_digest: Option<Digest>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RecordedCommand {
    pub argv: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub working_directory: Option<String>,
    #[serde(default)]
    pub declared_environment: BTreeMap<String, String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PortableDiagnostic {
    pub code: String,
    pub severity: DiagnosticSeverity,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<SourceAnchor>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiagnosticSeverity {
    Info,
    Warning,
    Error,
}

/// Common outer activity envelope. Producer-specific scientific meaning stays
/// in `payload`; Atlas interprets the receipt through a separate evidence record.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReceiptEnvelope<P> {
    pub schema: SchemaId,
    pub receipt_id: ReceiptId,
    pub producer: ProducerIdentity,
    pub activity: ActivityIdentity,
    pub environment: ExecutionEnvironment,
    #[serde(default)]
    pub inputs: Vec<ArtifactRef>,
    #[serde(default)]
    pub outputs: Vec<ArtifactRef>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub command: Option<RecordedCommand>,
    #[serde(default)]
    pub diagnostics: Vec<PortableDiagnostic>,
    pub started_at: String,
    pub finished_at: String,
    pub payload: P,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReceiptRef {
    pub id: ReceiptId,
    pub schema: SchemaId,
    pub producer: ProducerIdentity,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub artifact: Option<ArtifactRef>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FormalReceiptPayload {
    pub operation: FormalOperation,
    pub request_digest: Digest,
    pub formal_environment: FormalEnvironmentId,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_snapshot: Option<DocumentSnapshotId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_position: Option<SourcePosition>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub local_context: Option<LocalContextSnapshot>,
    #[serde(default)]
    pub goals_before: Vec<GoalSnapshot>,
    #[serde(default)]
    pub goals_after: Vec<GoalSnapshot>,
    pub result: FormalResult,
    #[serde(default)]
    pub used_declarations: Vec<DeclarationRevisionId>,
    #[serde(default)]
    pub axiom_footprint: Vec<DeclarationRevisionId>,
    pub replay: FormalReplayRecipe,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FormalOperation {
    ExtractDeclaration,
    ElaborateInContext,
    CheckDefinitionalEquality,
    Unify,
    SynthesizeInstance,
    ApplyCandidate,
    CheckProof,
    ProbeTactic,
    TraceInstanceSearch,
    MinimizeContext,
    Compose,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourcePosition {
    pub line: u32,
    pub character: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalContextSnapshot {
    pub id: LocalContextSnapshotId,
    #[serde(default)]
    pub bindings: Vec<LocalBinding>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalBinding {
    pub name: String,
    pub type_repr: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value_repr: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GoalSnapshot {
    pub goal_id: String,
    pub target: String,
    #[serde(default)]
    pub local_context: Vec<LocalBinding>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum FormalResult {
    Accepted {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        result_digest: Option<Digest>,
    },
    Rejected {
        failure: FormalFailure,
    },
    Inconclusive {
        reason: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FormalFailure {
    pub class: FormalFailureClass,
    pub message: String,
    #[serde(default)]
    pub missing_instances: Vec<String>,
    #[serde(default)]
    pub unresolved_goals: Vec<GoalSnapshot>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub nearest_successful_prefix: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FormalFailureClass {
    UnknownDeclaration,
    StaleSnapshot,
    StaleHandle,
    ElaborationFailure,
    TypeMismatch,
    UnificationFailure,
    DefinitionalEqualityFailure,
    InstanceSynthesisFailure,
    UniverseConstraint,
    MissingHypothesis,
    UnsolvedGoals,
    InvalidProof,
    Timeout,
    Cancelled,
    BackendUnavailable,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FormalReplayRecipe {
    pub project_root_digest: Digest,
    pub toolchain: String,
    pub command: RecordedCommand,
    #[serde(default)]
    pub required_artifacts: Vec<ArtifactRef>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueType {
    Entity,
    Claim,
    Declaration,
    Text,
    Integer,
    Rational,
    Boolean,
    Quantity,
    Expression,
    Domain,
    Artifact,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum TypedValue {
    Entity(crate::EntityRevisionId),
    Claim(ClaimRevisionId),
    Declaration(DeclarationRevisionId),
    Text(String),
    Integer(i64),
    Rational(RationalValue),
    Boolean(bool),
    Quantity(ArtifactRef),
    Expression(ArtifactRef),
    Domain(DomainId),
    Artifact(ArtifactRef),
}

impl TypedValue {
    pub const fn value_type(&self) -> ValueType {
        match self {
            Self::Entity(_) => ValueType::Entity,
            Self::Claim(_) => ValueType::Claim,
            Self::Declaration(_) => ValueType::Declaration,
            Self::Text(_) => ValueType::Text,
            Self::Integer(_) => ValueType::Integer,
            Self::Rational(_) => ValueType::Rational,
            Self::Boolean(_) => ValueType::Boolean,
            Self::Quantity(_) => ValueType::Quantity,
            Self::Expression(_) => ValueType::Expression,
            Self::Domain(_) => ValueType::Domain,
            Self::Artifact(_) => ValueType::Artifact,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RationalValue {
    pub numerator: i64,
    pub denominator: u64,
}

impl RationalValue {
    pub fn new(numerator: i64, denominator: u64) -> Result<Self, MetricValueError> {
        if denominator == 0 {
            return Err(MetricValueError::ZeroDenominator);
        }
        Ok(Self {
            numerator,
            denominator,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArgumentSpec {
    pub role: String,
    pub value_type: ValueType,
    pub equality: EqualitySemantics,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EqualitySemantics {
    ExactIdentity,
    CanonicalSyntax { normalizer: String },
    LeanDefinitionalEquality,
    PropositionalEquality,
    Isomorphism,
    PhysicalEquivalenceUnderScope,
    NumericalAgreement { policy: String },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationSymmetry {
    Directed,
    Symmetric,
    Antisymmetric,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum WorldSemantics {
    OpenWorld,
    ClosedWorld {
        required_witness: CompletenessWitnessKind,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CompletenessWitnessKind {
    CorpusSnapshot,
    DatasetSnapshot,
    FormalEnvironment,
    EnumeratedExperiment,
    External(String),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScopePolicy {
    Required,
    Optional,
    NotApplicable,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClass {
    Formal,
    ExactCertificate,
    Structural,
    Numerical,
    Empirical,
    Documentary,
    Reproducibility,
    HumanAssessment,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelationSchema {
    pub id: RelationSchemaId,
    pub wire_name: String,
    pub version: u32,
    pub arguments: Vec<ArgumentSpec>,
    pub symmetry: RelationSymmetry,
    pub execution: RelationExecution,
    pub world_semantics: WorldSemantics,
    pub scope_policy: ScopePolicy,
    pub admissible_evidence: BTreeSet<EvidenceClass>,
}

impl RelationSchema {
    pub fn validate_claim(&self, claim: &ClaimDraft) -> Result<(), SchemaValidationError> {
        if claim.relation != self.id {
            return Err(SchemaValidationError::WrongRelation {
                expected: self.id,
                observed: claim.relation,
            });
        }
        if claim.args.len() != self.arguments.len() {
            return Err(SchemaValidationError::WrongArity {
                expected: self.arguments.len(),
                observed: claim.args.len(),
            });
        }
        for (index, (argument, value)) in self.arguments.iter().zip(&claim.args).enumerate() {
            let observed = value.value_type();
            if argument.value_type != observed {
                return Err(SchemaValidationError::WrongArgumentType {
                    index,
                    expected: argument.value_type,
                    observed,
                });
            }
        }
        if self.scope_policy == ScopePolicy::Required
            && matches!(claim.scope.completeness, ScopeCompleteness::NotApplicable)
        {
            return Err(SchemaValidationError::ScopeRequired);
        }
        Ok(())
    }

    pub fn validate_evidence_class(
        &self,
        class: EvidenceClass,
    ) -> Result<(), SchemaValidationError> {
        if self.admissible_evidence.contains(&class) {
            Ok(())
        } else {
            Err(SchemaValidationError::EvidenceClassNotAllowed { class })
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SchemaValidationError {
    WrongRelation {
        expected: RelationSchemaId,
        observed: RelationSchemaId,
    },
    WrongArity {
        expected: usize,
        observed: usize,
    },
    WrongArgumentType {
        index: usize,
        expected: ValueType,
        observed: ValueType,
    },
    ScopeRequired,
    EvidenceClassNotAllowed {
        class: EvidenceClass,
    },
    EmptyEvidenceTargets,
}

impl fmt::Display for SchemaValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::WrongRelation { expected, observed } => write!(
                f,
                "claim uses relation {:?}; schema describes {:?}",
                observed, expected
            ),
            Self::WrongArity { expected, observed } => {
                write!(f, "relation expects {expected} arguments, got {observed}")
            }
            Self::WrongArgumentType {
                index,
                expected,
                observed,
            } => write!(f, "argument {index} expects {expected:?}, got {observed:?}"),
            Self::ScopeRequired => write!(f, "relation requires an explicit claim scope"),
            Self::EvidenceClassNotAllowed { class } => {
                write!(
                    f,
                    "evidence class {class:?} is not allowed by this relation"
                )
            }
            Self::EmptyEvidenceTargets => write!(f, "evidence must target at least one claim"),
        }
    }
}

impl std::error::Error for SchemaValidationError {}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClaimDraft {
    pub kind: ClaimKind,
    pub relation: RelationSchemaId,
    pub args: Vec<TypedValue>,
    pub scope: ClaimScope,
    pub origin: ClaimOrigin,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClaimRevision {
    pub id: ClaimRevisionId,
    pub stable_key: ClaimKeyId,
    pub kind: ClaimKind,
    pub relation: RelationSchemaId,
    pub args: Vec<TypedValue>,
    pub scope: ClaimScopeId,
    pub origin: ClaimOrigin,
    pub content_digest: Digest,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supersedes: Option<ClaimRevisionId>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimKind {
    Definition,
    FormalTheorem,
    FormalCorrespondence,
    MathematicalConjecture,
    ModelAssumption,
    ModelPrediction,
    NumericalResult,
    EmpiricalObservation,
    LiteratureAssertion,
    MechanisticHypothesis,
    Exclusion,
    Counterexample,
    Transformation,
    Approximation,
    RegimeBoundary,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ClaimOrigin {
    Imported {
        source: SourceAnchor,
    },
    Extracted {
        source: SourceAnchor,
        extractor: ReceiptRef,
    },
    Derived {
        rule: String,
        inputs: Vec<ClaimRevisionId>,
    },
    Proposed {
        actor: ActorId,
        generator: ReceiptRef,
    },
    Authored {
        actor: ActorId,
    },
    Legacy {
        classification: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClaimScope {
    pub semantic: SemanticScope,
    pub context: ClaimContext,
    pub completeness: ScopeCompleteness,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticScope {
    #[serde(default)]
    pub assumptions: Vec<ScopedAssumption>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parameter_domain: Option<DomainId>,
    #[serde(default)]
    pub regimes: Vec<RegimeConstraint>,
    #[serde(default)]
    pub approximations: Vec<ApproximationUse>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error_semantics: Option<ClaimRevisionId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quantity_system: Option<QuantitySystemId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub coordinate_frame: Option<CoordinateFrameId>,
    #[serde(default)]
    pub conventions: Vec<ConventionId>,
    #[serde(default)]
    pub boundary_conditions: Vec<ClaimRevisionId>,
    #[serde(default)]
    pub initial_conditions: Vec<ClaimRevisionId>,
    #[serde(default)]
    pub validity_constraints: Vec<ClaimRevisionId>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClaimContext {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub formal_environment: Option<FormalEnvironmentId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_snapshot: Option<SourceSnapshotId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub corpus_snapshot: Option<CorpusSnapshotId>,
    #[serde(default)]
    pub dataset_snapshots: Vec<DatasetSnapshotId>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ScopedAssumption {
    pub claim: ClaimRevisionId,
    pub origin: AssumptionOrigin,
    pub necessity: AssumptionNecessity,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AssumptionOrigin {
    SourceQuoted { source: SourceAnchor },
    SourceImplied { evidence: Vec<SourceAnchor> },
    EncodingAdapter { rationale: String },
    InvestigatorAdded { actor: ActorId, rationale: String },
    Generated { proposal: ProposalId },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssumptionNecessity {
    Required,
    SufficientOnly,
    Convenience,
    Unknown,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegimeConstraint {
    pub regime: RegimeId,
    pub description: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApproximationUse {
    pub approximation: ApproximationId,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub order: Option<RationalValue>,
    pub omitted_term_semantics: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum ScopeCompleteness {
    Complete,
    Incomplete {
        missing: BTreeSet<ScopeDimension>,
        rationale: String,
    },
    NotApplicable,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScopeDimension {
    Assumptions,
    ParameterDomain,
    Regime,
    Approximation,
    ErrorBound,
    QuantitySystem,
    CoordinateFrame,
    Conventions,
    BoundaryConditions,
    InitialConditions,
    FormalEnvironment,
    SourceSnapshot,
    DatasetSnapshot,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompletenessWitness {
    pub id: CompletenessWitnessId,
    pub kind: CompletenessWitnessKind,
    pub snapshot: SnapshotRef,
    pub digest: Digest,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum SnapshotRef {
    FormalEnvironment(FormalEnvironmentId),
    Corpus(CorpusSnapshotId),
    Dataset(DatasetSnapshotId),
    Document(DocumentSnapshotId),
    Source(SourceSnapshotId),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceRecord {
    pub id: EvidenceId,
    pub class: EvidenceClass,
    pub receipt: ReceiptRef,
    pub targets: Vec<EvidenceTarget>,
    pub payload: EvidencePayload,
    #[serde(default)]
    pub limitations: Vec<Limitation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub independence_group: Option<IndependenceGroupId>,
    pub recorded_by: ActorId,
    pub recorded_at: String,
}

impl EvidenceRecord {
    pub fn validate(&self) -> Result<(), SchemaValidationError> {
        if self.targets.is_empty() {
            Err(SchemaValidationError::EmptyEvidenceTargets)
        } else {
            Ok(())
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceTarget {
    pub claim: ClaimRevisionId,
    pub bearing: EvidenceBearing,
    pub applicability_scope: ClaimScopeId,
    pub scope_relation: ScopeRelation,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EvidenceBearing {
    Supports,
    Challenges { challenge: ChallengeKind },
    ContextOnly,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScopeRelation {
    Exact,
    Narrower,
    Broader,
    Overlapping,
    Disjoint,
    Unknown,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EvidencePayload {
    FormalReceipt {
        receipt: ReceiptRef,
    },
    CertificateCheck {
        receipt: ReceiptRef,
    },
    StructuralDerivation {
        rule: String,
        inputs: Vec<ClaimRevisionId>,
    },
    NumericalResult {
        artifact: ArtifactRef,
        metrics: BTreeMap<String, MetricValue>,
    },
    ExperimentalObservation {
        artifact: ArtifactRef,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        instrument: Option<String>,
    },
    LiteratureSource {
        source: SourceAnchor,
        statement: String,
    },
    Counterexample {
        witness: ArtifactRef,
        explanation: String,
    },
    Replication {
        original: ReceiptRef,
        replay: ReceiptRef,
        agrees: bool,
    },
    ReproducibilityCheck {
        replay: ReceiptRef,
        matched_outputs: bool,
    },
    External {
        schema: SchemaId,
        artifact: ArtifactRef,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Limitation {
    pub code: String,
    pub description: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum EvidenceExpr {
    Evidence(EvidenceId),
    Claim(ClaimRevisionId),
    All(Vec<EvidenceExpr>),
    Any(Vec<EvidenceExpr>),
    AtLeast {
        k: usize,
        of: Vec<EvidenceExpr>,
    },
    RuleApplication {
        rule: String,
        inputs: Vec<EvidenceExpr>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SupportCircuit {
    pub id: SupportCircuitId,
    pub claim: ClaimRevisionId,
    pub expression: EvidenceExpr,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Challenge {
    pub id: ChallengeId,
    pub target: ClaimRevisionId,
    pub kind: ChallengeKind,
    pub evidence: EvidenceExpr,
    pub scope: ClaimScopeId,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChallengeKind {
    Counterexample,
    ProvedNegation,
    EmpiricalMismatch,
    NumericalInstability,
    Nonconvergence,
    ScopeViolation,
    UnitMismatch,
    SymmetryIncompatibility,
    MissingAssumption,
    FormalizationMismatch,
    PriorArt,
    ReproducibilityFailure,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResearchWorldRef {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub formal: Option<FormalEnvironmentId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<SourceSnapshotId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub corpus: Option<CorpusSnapshotId>,
    #[serde(default)]
    pub datasets: Vec<DatasetSnapshotId>,
    #[serde(default)]
    pub execution: Vec<ExecutionEnvironmentId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub policy: Option<PolicyVersionId>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResearchQuestion {
    pub text: String,
    #[serde(default)]
    pub anchors: Vec<SourceAnchor>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProposedClaim {
    pub local_id: ProposedClaimId,
    pub draft: ClaimDraft,
    pub role: ProposedClaimRole,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProposedClaimRole {
    Primary,
    Mechanism,
    Prediction,
    IntermediateLemma,
    ScopeCondition,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProposalEdge {
    pub from: ProposedClaimId,
    pub to: ProposedClaimId,
    pub relation: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResearchObligation {
    pub id: ResearchObligationId,
    pub kind: String,
    pub description: String,
    pub evaluator: EvaluatorRequirement,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum EvaluatorRequirement {
    Formal,
    Symbolic,
    Numerical,
    Empirical,
    Documentary,
    Reproducibility,
    Human,
    External(String),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MetricValue {
    pub numerator: i64,
    pub denominator: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
}

impl MetricValue {
    pub fn new(
        numerator: i64,
        denominator: u64,
        unit: Option<String>,
    ) -> Result<Self, MetricValueError> {
        if denominator == 0 {
            return Err(MetricValueError::ZeroDenominator);
        }
        Ok(Self {
            numerator,
            denominator,
            unit,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MetricValueError {
    ZeroDenominator,
}

impl fmt::Display for MetricValueError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ZeroDenominator => write!(f, "metric denominator cannot be zero"),
        }
    }
}

impl std::error::Error for MetricValueError {}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SearchScoreVector {
    #[serde(default)]
    pub dimensions: BTreeMap<String, MetricValue>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResourceBudget {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_candidates: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_evaluations: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_iterations: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_wall_seconds: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_memory_bytes: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResourceEstimate {
    pub budget: ResourceBudget,
    #[serde(default)]
    pub notes: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum NoveltyProtocol {
    NotAssessed,
    PostCommitReviewRequired,
    Reviewed {
        reviewer: ActorId,
        conclusion: String,
        #[serde(default)]
        sources: Vec<SourceAnchor>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum ProposalCompleteness {
    Complete,
    Incomplete { missing: BTreeSet<String> },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResearchProposal {
    pub id: ProposalId,
    pub world: ResearchWorldRef,
    pub question: ResearchQuestion,
    pub proposed_claims: Vec<ProposedClaim>,
    #[serde(default)]
    pub mechanism: Vec<ProposalEdge>,
    #[serde(default)]
    pub assumptions: Vec<ClaimDraft>,
    #[serde(default)]
    pub predicted_observations: Vec<ClaimDraft>,
    pub falsifiers: Vec<FalsifierSpec>,
    #[serde(default)]
    pub alternatives: Vec<ProposalId>,
    #[serde(default)]
    pub obligations: Vec<ResearchObligation>,
    pub search_score: SearchScoreVector,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_information_gain: Option<MetricValue>,
    pub estimated_cost: ResourceEstimate,
    pub generator: ReceiptRef,
    pub novelty_protocol: NoveltyProtocol,
    pub completeness: ProposalCompleteness,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FalsifierSpec {
    pub id: FalsifierId,
    pub target: ProposedClaimId,
    pub scope: ClaimScope,
    pub evaluator: EvaluatorRequirement,
    pub procedure: PlanFragment,
    pub decisive_condition: DecisionRule,
    pub effect: FalsifierEffect,
    pub independence: IndependenceRequirement,
    pub budget: ResourceBudget,
    pub stop_policy: StopPolicy,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanFragment {
    pub steps: Vec<PlanStepSpec>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanStepSpec {
    pub id: String,
    pub evaluator: EvaluatorRequirement,
    pub action: String,
    #[serde(default)]
    pub inputs: Vec<ArtifactRef>,
    #[serde(default)]
    pub depends_on: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DecisionRule {
    FormalCounterexample {
        witness_schema: SchemaId,
    },
    FormalRejection {
        failure: FormalFailureClass,
    },
    MetricComparison {
        left: String,
        comparison: ComparisonOp,
        right: MetricValue,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        margin: Option<MetricValue>,
    },
    NonReproduction {
        required_replays: u32,
    },
    External {
        schema: SchemaId,
        rule_artifact: ArtifactRef,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ComparisonOp {
    Less,
    LessOrEqual,
    Equal,
    GreaterOrEqual,
    Greater,
    NotEqual,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FalsifierEffect {
    RefutesClaim,
    NarrowsScope,
    ChallengesMechanism,
    InvalidatesImplementation,
    StopsResearchLane,
    TriggersIndependentReview,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "requirements", rename_all = "snake_case")]
pub enum IndependenceRequirement {
    None,
    DifferentImplementation,
    DifferentAlgorithm,
    DifferentBackend,
    DifferentInstitutionOrReviewer,
    Multiple(Vec<IndependenceRequirement>),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum StopPolicy {
    Exhaustive,
    BudgetBounded,
    FirstDecisiveResult,
    Custom(String),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResearchPlan {
    pub id: ResearchPlanId,
    pub proposal: ProposalId,
    pub world: ResearchWorldRef,
    pub steps: Vec<PlanStepSpec>,
    pub budget: ResourceBudget,
    #[serde(default)]
    pub stopping_rules: Vec<StopPolicy>,
    pub frozen_at: String,
    pub content_digest: Digest,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResearchRun {
    pub id: ResearchRunId,
    pub plan: ResearchPlanId,
    pub world: ResearchWorldRef,
    #[serde(default)]
    pub events: Vec<RunEvent>,
    #[serde(default)]
    pub receipts: Vec<ReceiptRef>,
    #[serde(default)]
    pub produced_claims: Vec<ClaimRevisionId>,
    #[serde(default)]
    pub produced_evidence: Vec<EvidenceId>,
    #[serde(default)]
    pub interventions: Vec<HumanIntervention>,
    #[serde(default)]
    pub deviations: Vec<PlanDeviation>,
    pub outcome: RunOutcome,
    pub content_digest: Digest,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RunEvent {
    pub sequence: u64,
    pub kind: RunEventKind,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub receipt: Option<ReceiptRef>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunEventKind {
    Started,
    StepSucceeded,
    StepFailed,
    StepSkipped,
    Retried,
    HumanIntervention,
    BudgetReached,
    Finished,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct HumanIntervention {
    pub actor: ActorId,
    pub at_sequence: u64,
    pub action: String,
    pub rationale: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanDeviation {
    pub at_sequence: u64,
    pub planned_step: String,
    pub actual_action: String,
    pub rationale: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunOutcome {
    Completed,
    Refuted,
    ScopeNarrowed,
    Blocked,
    BudgetExhausted,
    Inconclusive,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClaimAssessment {
    pub id: AssessmentId,
    pub claim: ClaimRevisionId,
    pub evidence_snapshot: Digest,
    pub policy: PolicyVersionId,
    pub state: ClaimState,
    pub profile: EvidenceProfile,
    pub assessor: ActorId,
    pub rationale: String,
    pub assessed_at: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimState {
    Proposed,
    UnderTest,
    Supported,
    Contested,
    Refuted,
    Retired,
    Superseded,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceProfile {
    pub formal: EvidenceAxisState,
    pub computational: EvidenceAxisState,
    pub empirical: EvidenceAxisState,
    pub documentary: EvidenceAxisState,
    pub reproducibility: EvidenceAxisState,
    pub scope_completeness: ScopeCompleteness,
    #[serde(default)]
    pub challenges: Vec<ChallengeId>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceAxisState {
    NoEvidence,
    Present,
    IndependentlyChecked,
    Challenged,
    Refuted,
    Inconclusive,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest {
        Digest {
            algorithm: "sha256".into(),
            value: value.into(),
        }
    }

    fn producer() -> ProducerIdentity {
        ProducerIdentity {
            repository: "akiselev/lean-atlas".into(),
            commit: "abc".into(),
            package: "atlas-intuition".into(),
            package_version: "0.3.0".into(),
            executable_digest: digest("generator"),
        }
    }

    fn receipt() -> ReceiptRef {
        ReceiptRef {
            id: ReceiptId(1),
            schema: SchemaId {
                name: "generator-receipt".into(),
                version: 1,
                digest: digest("schema"),
            },
            producer: producer(),
            artifact: None,
        }
    }

    fn scope() -> ClaimScope {
        ClaimScope {
            semantic: SemanticScope::default(),
            context: ClaimContext::default(),
            completeness: ScopeCompleteness::Incomplete {
                missing: BTreeSet::from([ScopeDimension::ParameterDomain]),
                rationale: "proposal has not fixed its parameter domain".into(),
            },
        }
    }

    #[test]
    fn relation_schema_rejects_wrong_arity_and_type() {
        let relation = RelationSchema {
            id: RelationSchemaId(7),
            wire_name: "iff".into(),
            version: 1,
            arguments: vec![
                ArgumentSpec {
                    role: "left".into(),
                    value_type: ValueType::Claim,
                    equality: EqualitySemantics::ExactIdentity,
                },
                ArgumentSpec {
                    role: "right".into(),
                    value_type: ValueType::Claim,
                    equality: EqualitySemantics::ExactIdentity,
                },
            ],
            symmetry: RelationSymmetry::Symmetric,
            execution: RelationExecution::Oracle,
            world_semantics: WorldSemantics::OpenWorld,
            scope_policy: ScopePolicy::Required,
            admissible_evidence: BTreeSet::from([EvidenceClass::Formal]),
        };
        let wrong_arity = ClaimDraft {
            kind: ClaimKind::FormalCorrespondence,
            relation: relation.id,
            args: vec![TypedValue::Claim(ClaimRevisionId(1))],
            scope: scope(),
            origin: ClaimOrigin::Authored { actor: ActorId(1) },
        };
        assert!(matches!(
            relation.validate_claim(&wrong_arity),
            Err(SchemaValidationError::WrongArity { .. })
        ));

        let wrong_type = ClaimDraft {
            args: vec![
                TypedValue::Claim(ClaimRevisionId(1)),
                TypedValue::Text("not a claim".into()),
            ],
            ..wrong_arity
        };
        assert!(matches!(
            relation.validate_claim(&wrong_type),
            Err(SchemaValidationError::WrongArgumentType { index: 1, .. })
        ));
        assert!(
            relation
                .validate_evidence_class(EvidenceClass::Formal)
                .is_ok()
        );
        assert!(matches!(
            relation.validate_evidence_class(EvidenceClass::Empirical),
            Err(SchemaValidationError::EvidenceClassNotAllowed { .. })
        ));
    }

    #[test]
    fn support_circuit_preserves_or_of_and_alternatives() {
        let circuit = SupportCircuit {
            id: SupportCircuitId(1),
            claim: ClaimRevisionId(9),
            expression: EvidenceExpr::Any(vec![
                EvidenceExpr::All(vec![
                    EvidenceExpr::Evidence(EvidenceId(1)),
                    EvidenceExpr::Evidence(EvidenceId(2)),
                ]),
                EvidenceExpr::All(vec![EvidenceExpr::Evidence(EvidenceId(3))]),
            ]),
        };
        let encoded = serde_json::to_vec(&circuit).unwrap();
        assert_eq!(
            serde_json::from_slice::<SupportCircuit>(&encoded).unwrap(),
            circuit
        );
    }

    #[test]
    fn proposal_roundtrip_keeps_scope_falsifier_and_search_metadata_separate() {
        let claim = ClaimDraft {
            kind: ClaimKind::MathematicalConjecture,
            relation: RelationSchemaId(10),
            args: vec![TypedValue::Text("candidate phase-fiber theorem".into())],
            scope: scope(),
            origin: ClaimOrigin::Proposed {
                actor: ActorId(1),
                generator: receipt(),
            },
        };
        let proposal = ResearchProposal {
            id: ProposalId(1),
            world: ResearchWorldRef {
                formal: Some(FormalEnvironmentId(1)),
                source: Some(SourceSnapshotId(1)),
                corpus: Some(CorpusSnapshotId(1)),
                datasets: vec![],
                execution: vec![],
                policy: Some(PolicyVersionId(1)),
            },
            question: ResearchQuestion {
                text: "Is the finite critical set complete?".into(),
                anchors: vec![],
            },
            proposed_claims: vec![ProposedClaim {
                local_id: ProposedClaimId(1),
                draft: claim,
                role: ProposedClaimRole::Primary,
            }],
            mechanism: vec![],
            assumptions: vec![],
            predicted_observations: vec![],
            falsifiers: vec![FalsifierSpec {
                id: FalsifierId(1),
                target: ProposedClaimId(1),
                scope: scope(),
                evaluator: EvaluatorRequirement::Numerical,
                procedure: PlanFragment {
                    steps: vec![PlanStepSpec {
                        id: "interval-minimize".into(),
                        evaluator: EvaluatorRequirement::Numerical,
                        action: "independent certified interval minimization".into(),
                        inputs: vec![],
                        depends_on: vec![],
                    }],
                },
                decisive_condition: DecisionRule::MetricComparison {
                    left: "interval_minimum".into(),
                    comparison: ComparisonOp::Less,
                    right: MetricValue::new(0, 1, None).unwrap(),
                    margin: None,
                },
                effect: FalsifierEffect::RefutesClaim,
                independence: IndependenceRequirement::DifferentImplementation,
                budget: ResourceBudget::default(),
                stop_policy: StopPolicy::FirstDecisiveResult,
            }],
            alternatives: vec![],
            obligations: vec![],
            search_score: SearchScoreVector {
                dimensions: BTreeMap::from([(
                    "semantic_applicability".into(),
                    MetricValue::new(4, 5, None).unwrap(),
                )]),
            },
            expected_information_gain: None,
            estimated_cost: ResourceEstimate {
                budget: ResourceBudget::default(),
                notes: vec![],
            },
            generator: receipt(),
            novelty_protocol: NoveltyProtocol::PostCommitReviewRequired,
            completeness: ProposalCompleteness::Complete,
        };
        let encoded = serde_json::to_vec(&proposal).unwrap();
        let decoded: ResearchProposal = serde_json::from_slice(&encoded).unwrap();
        assert_eq!(decoded, proposal);
        assert_eq!(decoded.falsifiers.len(), 1);
        assert_eq!(decoded.search_score.dimensions.len(), 1);
    }

    #[test]
    fn evidence_without_a_target_is_invalid() {
        let evidence = EvidenceRecord {
            id: EvidenceId(1),
            class: EvidenceClass::Numerical,
            receipt: receipt(),
            targets: vec![],
            payload: EvidencePayload::NumericalResult {
                artifact: ArtifactRef {
                    id: ArtifactId(1),
                    digest: Some(digest("result")),
                    locator: None,
                },
                metrics: BTreeMap::new(),
            },
            limitations: vec![],
            independence_group: None,
            recorded_by: ActorId(1),
            recorded_at: "2026-08-19T00:00:00Z".into(),
        };
        assert_eq!(
            evidence.validate().unwrap_err(),
            SchemaValidationError::EmptyEvidenceTargets
        );
    }
}
