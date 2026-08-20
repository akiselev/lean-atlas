use crate::LeanOracle;
use atlas_lean_client::{ClientError, LeanClient};
pub use atlas_lean_protocol::Position;
use atlas_lean_protocol::{
    ApplyResponse, LeanFailure, LeanFailureKind, OracleResult, SynthInstanceResponse,
};
use std::collections::BTreeSet;

const DEFAULT_QUERY_LIMIT: usize = 64;
const HARD_QUERY_LIMIT: usize = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QueryStage {
    GoalElaboration,
    CandidateLookup,
    CandidateApplication,
    TypeElaboration,
    InstanceSynthesis,
    ContextGoalElaboration,
    ContextProofElaboration,
    ContextProofCheck,
    CompositionGoalElaboration,
    CompositionProofElaboration,
    CompositionProofCheck,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObstructionClass {
    UnknownDeclaration,
    Elaboration,
    TypeMismatch,
    Unification,
    DefinitionalEquality,
    InstanceSynthesis,
    UnsolvedMetavariables,
    UniverseConstraint,
    MissingHypothesis,
    InvalidProof,
    StaleContext,
    Internal,
}

#[derive(Clone, Debug, PartialEq)]
pub struct QueryFailure {
    pub stage: QueryStage,
    pub class: ObstructionClass,
    pub lean: LeanFailure,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CandidateRejection {
    pub declaration: String,
    pub failure: QueryFailure,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GoalMatchCandidate {
    pub declaration: String,
    pub subgoals: Vec<String>,
    pub closes_goal: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GoalMatchResult {
    pub goal: String,
    pub goal_pretty: Option<String>,
    pub considered: usize,
    pub matches: Vec<GoalMatchCandidate>,
    pub rejections: Vec<CandidateRejection>,
    pub truncated: bool,
    pub goal_failure: Option<QueryFailure>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct WhyNotResult {
    pub candidate: String,
    pub goal: String,
    pub applicable: bool,
    pub closes_goal: bool,
    pub subgoals: Vec<String>,
    pub failure: Option<QueryFailure>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct InstancePathResult {
    pub type_text: String,
    pub instance_pretty: Option<String>,
    pub dependencies: Vec<String>,
    pub failure: Option<QueryFailure>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ContextBindingKind {
    Explicit,
    Implicit,
    Instance,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContextBinding {
    pub name: String,
    pub type_text: String,
    pub kind: ContextBindingKind,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MinimalContextWitness {
    pub kept: Vec<ContextBinding>,
    pub removed: Vec<ContextBinding>,
    pub goal_pretty: String,
    pub proof_pretty: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RejectedContext {
    pub kept: Vec<String>,
    pub failure: QueryFailure,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MinimalContextResult {
    pub goal: String,
    pub proof: String,
    pub frontier: Vec<MinimalContextWitness>,
    pub rejections: Vec<RejectedContext>,
    pub evaluations: usize,
    pub truncated: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CompositionStatus {
    Proved,
    Candidate,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ComposeResult {
    pub left: String,
    pub right: String,
    pub goal: String,
    pub proof_term: String,
    pub proof_pretty: Option<String>,
    pub goal_pretty: Option<String>,
    pub status: CompositionStatus,
    pub failure: Option<QueryFailure>,
}

pub struct QueryEngine<'a> {
    oracle: LeanOracle<'a>,
}

impl<'a> QueryEngine<'a> {
    pub fn new(client: &'a mut LeanClient) -> Self {
        Self {
            oracle: LeanOracle::new(client),
        }
    }

    pub async fn goal_match(
        &mut self,
        goal_text: &str,
        candidates: &[String],
        position: Position,
        max_candidates: usize,
        max_matches: usize,
    ) -> Result<GoalMatchResult, ClientError> {
        let mut result = GoalMatchResult {
            goal: goal_text.into(),
            goal_pretty: None,
            considered: 0,
            matches: Vec::new(),
            rejections: Vec::new(),
            truncated: false,
            goal_failure: None,
        };

        let goal = match oracle_value(
            self.oracle.elaborate(goal_text, None, position).await?,
            QueryStage::GoalElaboration,
        ) {
            Ok(goal) => goal,
            Err(failure) => {
                result.goal_failure = Some(failure);
                return Ok(result);
            }
        };
        result.goal_pretty = Some(goal.pretty.clone());

        let candidate_limit = bounded_limit(max_candidates);
        let match_limit = bounded_limit(max_matches);
        let mut seen = BTreeSet::new();
        for declaration in candidates
            .iter()
            .filter(|name| seen.insert((*name).clone()))
        {
            if result.considered >= candidate_limit || result.matches.len() >= match_limit {
                result.truncated = true;
                break;
            }
            result.considered += 1;

            let lookup = match oracle_value(
                self.oracle.lookup_decl(declaration, position).await?,
                QueryStage::CandidateLookup,
            ) {
                Ok(lookup) => lookup,
                Err(failure) => {
                    result.rejections.push(CandidateRejection {
                        declaration: declaration.clone(),
                        failure,
                    });
                    continue;
                }
            };

            match oracle_value(
                self.oracle
                    .apply(lookup.expression, goal.expr, position)
                    .await?,
                QueryStage::CandidateApplication,
            ) {
                Ok(ApplyResponse { subgoal_types, .. }) => {
                    result.matches.push(GoalMatchCandidate {
                        declaration: declaration.clone(),
                        closes_goal: subgoal_types.is_empty(),
                        subgoals: subgoal_types,
                    });
                }
                Err(failure) => result.rejections.push(CandidateRejection {
                    declaration: declaration.clone(),
                    failure,
                }),
            }
        }
        if result.considered < seen.len() || result.considered < candidates.len() {
            result.truncated = true;
        }
        Ok(result)
    }

    pub async fn why_not(
        &mut self,
        candidate: &str,
        goal_text: &str,
        position: Position,
    ) -> Result<WhyNotResult, ClientError> {
        let mut result = WhyNotResult {
            candidate: candidate.into(),
            goal: goal_text.into(),
            applicable: false,
            closes_goal: false,
            subgoals: Vec::new(),
            failure: None,
        };

        let goal = match oracle_value(
            self.oracle.elaborate(goal_text, None, position).await?,
            QueryStage::GoalElaboration,
        ) {
            Ok(goal) => goal,
            Err(failure) => {
                result.failure = Some(failure);
                return Ok(result);
            }
        };
        let lookup = match oracle_value(
            self.oracle.lookup_decl(candidate, position).await?,
            QueryStage::CandidateLookup,
        ) {
            Ok(lookup) => lookup,
            Err(failure) => {
                result.failure = Some(failure);
                return Ok(result);
            }
        };
        match oracle_value(
            self.oracle
                .apply(lookup.expression, goal.expr, position)
                .await?,
            QueryStage::CandidateApplication,
        ) {
            Ok(ApplyResponse { subgoal_types, .. }) => {
                result.applicable = true;
                result.closes_goal = subgoal_types.is_empty();
                result.subgoals = subgoal_types;
            }
            Err(failure) => result.failure = Some(failure),
        }
        Ok(result)
    }

    pub async fn instance_path(
        &mut self,
        type_text: &str,
        position: Position,
    ) -> Result<InstancePathResult, ClientError> {
        let mut result = InstancePathResult {
            type_text: type_text.into(),
            instance_pretty: None,
            dependencies: Vec::new(),
            failure: None,
        };
        let type_expr = match oracle_value(
            self.oracle.elaborate(type_text, None, position).await?,
            QueryStage::TypeElaboration,
        ) {
            Ok(value) => value,
            Err(failure) => {
                result.failure = Some(failure);
                return Ok(result);
            }
        };
        match oracle_value(
            self.oracle.synth_instance(type_expr.expr, position).await?,
            QueryStage::InstanceSynthesis,
        ) {
            Ok(SynthInstanceResponse {
                dependencies,
                pretty,
                ..
            }) => {
                result.instance_pretty = Some(pretty);
                result.dependencies = dependencies;
            }
            Err(failure) => result.failure = Some(failure),
        }
        Ok(result)
    }

    pub async fn minimal_context(
        &mut self,
        goal: &str,
        proof: &str,
        hypotheses: &[ContextBinding],
        position: Position,
        max_evaluations: usize,
    ) -> Result<MinimalContextResult, ClientError> {
        let max_evaluations = bounded_limit(max_evaluations);
        let (subsets, enumeration_truncated) =
            bounded_combinations(hypotheses.len(), max_evaluations);
        let mut result = MinimalContextResult {
            goal: goal.into(),
            proof: proof.into(),
            frontier: Vec::new(),
            rejections: Vec::new(),
            evaluations: 0,
            truncated: enumeration_truncated,
        };

        for kept_indices in subsets {
            if result.evaluations >= max_evaluations {
                result.truncated = true;
                break;
            }
            if result
                .frontier
                .iter()
                .any(|witness| binding_names_are_subset(&witness.kept, hypotheses, &kept_indices))
            {
                continue;
            }
            result.evaluations += 1;
            let kept: Vec<_> = kept_indices
                .iter()
                .map(|index| hypotheses[*index].clone())
                .collect();
            let kept_set: BTreeSet<_> = kept_indices.iter().copied().collect();
            let removed: Vec<_> = hypotheses
                .iter()
                .enumerate()
                .filter(|(index, _)| !kept_set.contains(index))
                .map(|(_, binding)| binding.clone())
                .collect();
            let (expected_text, proof_text) = context_terms(&kept, goal, proof);

            let expected = match oracle_value(
                self.oracle.elaborate(expected_text, None, position).await?,
                QueryStage::ContextGoalElaboration,
            ) {
                Ok(value) => value,
                Err(failure) => {
                    push_context_rejection(&mut result, &kept, failure);
                    continue;
                }
            };
            let candidate = match oracle_value(
                self.oracle
                    .elaborate(proof_text, Some(expected.expr), position)
                    .await?,
                QueryStage::ContextProofElaboration,
            ) {
                Ok(value) => value,
                Err(failure) => {
                    push_context_rejection(&mut result, &kept, failure);
                    continue;
                }
            };
            match oracle_value(
                self.oracle
                    .check_proof(candidate.expr, expected.expr, position)
                    .await?,
                QueryStage::ContextProofCheck,
            ) {
                Ok(checked) if checked.value => result.frontier.push(MinimalContextWitness {
                    kept,
                    removed,
                    goal_pretty: expected.pretty,
                    proof_pretty: candidate.pretty,
                }),
                Ok(_) => push_context_rejection(
                    &mut result,
                    &kept,
                    synthetic_failure(
                        QueryStage::ContextProofCheck,
                        LeanFailureKind::InvalidProof,
                        "Lean did not accept the replayed proof for this context",
                    ),
                ),
                Err(failure) => push_context_rejection(&mut result, &kept, failure),
            }
        }
        Ok(result)
    }

    pub async fn compose(
        &mut self,
        left: &str,
        right: &str,
        goal: &str,
        explicit_proof: Option<&str>,
        position: Position,
    ) -> Result<ComposeResult, ClientError> {
        let proof_term = explicit_proof
            .map(str::to_owned)
            .unwrap_or_else(|| default_composition(left, right));
        let mut result = ComposeResult {
            left: left.into(),
            right: right.into(),
            goal: goal.into(),
            proof_term: proof_term.clone(),
            proof_pretty: None,
            goal_pretty: None,
            status: CompositionStatus::Candidate,
            failure: None,
        };

        let proposition = match oracle_value(
            self.oracle.elaborate(goal, None, position).await?,
            QueryStage::CompositionGoalElaboration,
        ) {
            Ok(value) => value,
            Err(failure) => {
                result.failure = Some(failure);
                return Ok(result);
            }
        };
        result.goal_pretty = Some(proposition.pretty.clone());
        let proof = match oracle_value(
            self.oracle
                .elaborate(&proof_term, Some(proposition.expr), position)
                .await?,
            QueryStage::CompositionProofElaboration,
        ) {
            Ok(value) => value,
            Err(failure) => {
                result.failure = Some(failure);
                return Ok(result);
            }
        };
        result.proof_pretty = Some(proof.pretty.clone());
        match oracle_value(
            self.oracle
                .check_proof(proof.expr, proposition.expr, position)
                .await?,
            QueryStage::CompositionProofCheck,
        ) {
            Ok(checked) if checked.value => result.status = CompositionStatus::Proved,
            Ok(_) => {
                result.failure = Some(synthetic_failure(
                    QueryStage::CompositionProofCheck,
                    LeanFailureKind::InvalidProof,
                    "the independently checked composition did not prove the requested goal",
                ));
            }
            Err(failure) => result.failure = Some(failure),
        }
        Ok(result)
    }
}

fn bounded_limit(value: usize) -> usize {
    value.max(1).min(HARD_QUERY_LIMIT)
}

fn oracle_value<T>(result: OracleResult<T>, stage: QueryStage) -> Result<T, QueryFailure> {
    match (result.value, result.failure) {
        (Some(value), _) => Ok(value),
        (_, Some(failure)) => Err(QueryFailure {
            stage,
            class: classify_failure(&failure),
            lean: failure,
        }),
        _ => Err(synthetic_failure(
            stage,
            LeanFailureKind::Internal,
            "Lean oracle returned neither a value nor a structured failure",
        )),
    }
}

fn synthetic_failure(
    stage: QueryStage,
    kind: LeanFailureKind,
    message: impl Into<String>,
) -> QueryFailure {
    let lean = LeanFailure {
        kind,
        message: message.into(),
        goals: vec![],
        missing_instances: vec![],
        metavariables: vec![],
        trace: None,
    };
    QueryFailure {
        stage,
        class: classify_failure(&lean),
        lean,
    }
}

fn classify_failure(failure: &LeanFailure) -> ObstructionClass {
    let message = failure.message.to_ascii_lowercase();
    if !failure.missing_instances.is_empty()
        || message.contains("failed to synthesize")
        || message.contains("synth instance")
    {
        return ObstructionClass::InstanceSynthesis;
    }
    if message.contains("type mismatch") || message.contains("application type mismatch") {
        return ObstructionClass::TypeMismatch;
    }
    if message.contains("unknown identifier") || message.contains("unknown declaration") {
        return ObstructionClass::UnknownDeclaration;
    }
    if message.contains("missing hypothesis") || message.contains("unknown free variable") {
        return ObstructionClass::MissingHypothesis;
    }
    match failure.kind {
        LeanFailureKind::UnknownDeclaration => ObstructionClass::UnknownDeclaration,
        LeanFailureKind::Elaboration => ObstructionClass::Elaboration,
        LeanFailureKind::TypeMismatch => ObstructionClass::TypeMismatch,
        LeanFailureKind::Unification => ObstructionClass::Unification,
        LeanFailureKind::DefinitionalEquality => ObstructionClass::DefinitionalEquality,
        LeanFailureKind::InstanceSynthesis => ObstructionClass::InstanceSynthesis,
        LeanFailureKind::UnsolvedMetavariables => ObstructionClass::UnsolvedMetavariables,
        LeanFailureKind::UniverseConstraint => ObstructionClass::UniverseConstraint,
        LeanFailureKind::MissingHypothesis => ObstructionClass::MissingHypothesis,
        LeanFailureKind::InvalidProof => ObstructionClass::InvalidProof,
        LeanFailureKind::StaleHandle | LeanFailureKind::StaleEnvironment => {
            ObstructionClass::StaleContext
        }
        LeanFailureKind::Internal => ObstructionClass::Internal,
    }
}

fn push_context_rejection(
    result: &mut MinimalContextResult,
    kept: &[ContextBinding],
    failure: QueryFailure,
) {
    if result.rejections.len() < DEFAULT_QUERY_LIMIT {
        result.rejections.push(RejectedContext {
            kept: kept.iter().map(|binding| binding.name.clone()).collect(),
            failure,
        });
    }
}

fn binding_names_are_subset(
    accepted: &[ContextBinding],
    all: &[ContextBinding],
    candidate_indices: &[usize],
) -> bool {
    let candidate: BTreeSet<_> = candidate_indices
        .iter()
        .map(|index| all[*index].name.as_str())
        .collect();
    accepted
        .iter()
        .all(|binding| candidate.contains(binding.name.as_str()))
}

fn context_terms(bindings: &[ContextBinding], goal: &str, proof: &str) -> (String, String) {
    if bindings.is_empty() {
        return (goal.into(), proof.into());
    }
    let rendered = bindings
        .iter()
        .map(render_binding)
        .collect::<Vec<_>>()
        .join(" ");
    (
        format!("(∀ {rendered}, {goal})"),
        format!("(fun {rendered} => {proof})"),
    )
}

fn render_binding(binding: &ContextBinding) -> String {
    match binding.kind {
        ContextBindingKind::Explicit => format!("({} : {})", binding.name, binding.type_text),
        ContextBindingKind::Implicit => format!("{{{} : {}}}", binding.name, binding.type_text),
        ContextBindingKind::Instance => format!("[{} : {}]", binding.name, binding.type_text),
    }
}

fn default_composition(left: &str, right: &str) -> String {
    format!("(fun x => ({right}) (({left}) x))")
}

fn bounded_combinations(n: usize, limit: usize) -> (Vec<Vec<usize>>, bool) {
    let limit = limit.max(1);
    let mut output = Vec::new();
    let mut truncated = false;
    for size in 0..=n {
        let mut current = Vec::with_capacity(size);
        collect_combinations(0, n, size, &mut current, &mut output, limit, &mut truncated);
        if truncated {
            break;
        }
    }
    (output, truncated)
}

fn collect_combinations(
    start: usize,
    n: usize,
    remaining: usize,
    current: &mut Vec<usize>,
    output: &mut Vec<Vec<usize>>,
    limit: usize,
    truncated: &mut bool,
) {
    if output.len() >= limit {
        *truncated = true;
        return;
    }
    if remaining == 0 {
        output.push(current.clone());
        return;
    }
    if n.saturating_sub(start) < remaining {
        return;
    }
    for index in start..=n - remaining {
        current.push(index);
        collect_combinations(
            index + 1,
            n,
            remaining - 1,
            current,
            output,
            limit,
            truncated,
        );
        current.pop();
        if *truncated {
            return;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn combinations_are_cardinality_ordered_and_bounded() {
        let (combinations, truncated) = bounded_combinations(3, 5);
        assert_eq!(
            combinations,
            vec![vec![], vec![0], vec![1], vec![2], vec![0, 1]]
        );
        assert!(truncated);
    }

    #[test]
    fn context_terms_preserve_binder_kinds() {
        let bindings = vec![
            ContextBinding {
                name: "α".into(),
                type_text: "Type".into(),
                kind: ContextBindingKind::Implicit,
            },
            ContextBinding {
                name: "inst".into(),
                type_text: "Inhabited α".into(),
                kind: ContextBindingKind::Instance,
            },
            ContextBinding {
                name: "x".into(),
                type_text: "α".into(),
                kind: ContextBindingKind::Explicit,
            },
        ];
        let (goal, proof) = context_terms(&bindings, "True", "True.intro");
        assert_eq!(goal, "(∀ {α : Type} [inst : Inhabited α] (x : α), True)");
        assert_eq!(
            proof,
            "(fun {α : Type} [inst : Inhabited α] (x : α) => True.intro)"
        );
    }

    #[test]
    fn default_composition_is_an_explicit_proof_candidate() {
        assert_eq!(
            default_composition("left", "right"),
            "(fun x => (right) ((left) x))"
        );
    }

    #[test]
    fn message_specific_classification_refines_generic_unification() {
        let failure = LeanFailure {
            kind: LeanFailureKind::Unification,
            message: "application type mismatch".into(),
            goals: vec![],
            missing_instances: vec![],
            metavariables: vec![],
            trace: None,
        };
        assert_eq!(classify_failure(&failure), ObstructionClass::TypeMismatch);
    }
}
