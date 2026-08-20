use atlas_daemon_protocol as wire;
use atlas_engine::{
    query as engine,
    runtime::{LeanClient, LeanError},
};

pub async fn execute(
    lean: &mut LeanClient,
    query: wire::SemanticQuery,
) -> Result<wire::QueryResponse, LeanError> {
    let mut engine = engine::QueryEngine::new(lean);
    match query {
        wire::SemanticQuery::GoalMatch(request) => {
            let result = engine
                .goal_match(
                    &request.goal,
                    &request.candidates,
                    position(request.position),
                    request.max_candidates,
                    request.max_matches,
                )
                .await?;
            Ok(wire::QueryResponse::GoalMatch(wire::GoalMatchResponse {
                goal: result.goal,
                goal_pretty: result.goal_pretty,
                considered: result.considered,
                matches: result
                    .matches
                    .into_iter()
                    .map(|candidate| wire::GoalMatchCandidate {
                        declaration: candidate.declaration,
                        subgoals: candidate.subgoals,
                        closes_goal: candidate.closes_goal,
                    })
                    .collect(),
                rejections: result
                    .rejections
                    .into_iter()
                    .map(|rejection| wire::CandidateRejection {
                        declaration: rejection.declaration,
                        failure: failure(rejection.failure),
                    })
                    .collect(),
                truncated: result.truncated,
                goal_failure: result.goal_failure.map(failure),
            }))
        }
        wire::SemanticQuery::WhyNot(request) => {
            let result = engine
                .why_not(
                    &request.candidate,
                    &request.goal,
                    position(request.position),
                )
                .await?;
            Ok(wire::QueryResponse::WhyNot(wire::WhyNotResponse {
                candidate: result.candidate,
                goal: result.goal,
                applicable: result.applicable,
                closes_goal: result.closes_goal,
                subgoals: result.subgoals,
                failure: result.failure.map(failure),
            }))
        }
        wire::SemanticQuery::InstancePath(request) => {
            let result = engine
                .instance_path(&request.type_text, position(request.position))
                .await?;
            Ok(wire::QueryResponse::InstancePath(
                wire::InstancePathResponse {
                    type_text: result.type_text,
                    instance_pretty: result.instance_pretty,
                    dependencies: result.dependencies,
                    failure: result.failure.map(failure),
                },
            ))
        }
        wire::SemanticQuery::MinimalContext(request) => {
            let hypotheses: Vec<_> = request.hypotheses.into_iter().map(engine_binding).collect();
            let result = engine
                .minimal_context(
                    &request.goal,
                    &request.proof,
                    &hypotheses,
                    position(request.position),
                    request.max_evaluations,
                )
                .await?;
            Ok(wire::QueryResponse::MinimalContext(
                wire::MinimalContextResponse {
                    goal: result.goal,
                    proof: result.proof,
                    frontier: result
                        .frontier
                        .into_iter()
                        .map(|witness| wire::MinimalContextWitness {
                            kept: witness.kept.into_iter().map(wire_binding).collect(),
                            removed: witness.removed.into_iter().map(wire_binding).collect(),
                            goal_pretty: witness.goal_pretty,
                            proof_pretty: witness.proof_pretty,
                        })
                        .collect(),
                    rejections: result
                        .rejections
                        .into_iter()
                        .map(|rejection| wire::RejectedContext {
                            kept: rejection.kept,
                            failure: failure(rejection.failure),
                        })
                        .collect(),
                    evaluations: result.evaluations,
                    truncated: result.truncated,
                },
            ))
        }
        wire::SemanticQuery::Compose(request) => {
            let result = engine
                .compose(
                    &request.left,
                    &request.right,
                    &request.goal,
                    request.proof.as_deref(),
                    position(request.position),
                )
                .await?;
            Ok(wire::QueryResponse::Compose(wire::ComposeResponse {
                left: result.left,
                right: result.right,
                goal: result.goal,
                proof_term: result.proof_term,
                proof_pretty: result.proof_pretty,
                goal_pretty: result.goal_pretty,
                status: match result.status {
                    engine::CompositionStatus::Proved => wire::CompositionStatus::Proved,
                    engine::CompositionStatus::Candidate => wire::CompositionStatus::Candidate,
                },
                failure: result.failure.map(failure),
            }))
        }
    }
}

fn position(position: wire::QueryPosition) -> engine::Position {
    engine::Position {
        line: position.line,
        character: position.character,
    }
}

fn engine_binding(binding: wire::ContextBinding) -> engine::ContextBinding {
    engine::ContextBinding {
        name: binding.name,
        type_text: binding.type_text,
        kind: match binding.kind {
            wire::ContextBindingKind::Explicit => engine::ContextBindingKind::Explicit,
            wire::ContextBindingKind::Implicit => engine::ContextBindingKind::Implicit,
            wire::ContextBindingKind::Instance => engine::ContextBindingKind::Instance,
        },
    }
}

fn wire_binding(binding: engine::ContextBinding) -> wire::ContextBinding {
    wire::ContextBinding {
        name: binding.name,
        type_text: binding.type_text,
        kind: match binding.kind {
            engine::ContextBindingKind::Explicit => wire::ContextBindingKind::Explicit,
            engine::ContextBindingKind::Implicit => wire::ContextBindingKind::Implicit,
            engine::ContextBindingKind::Instance => wire::ContextBindingKind::Instance,
        },
    }
}

fn failure(failure: engine::QueryFailure) -> wire::QueryFailure {
    let lean = failure.lean;
    wire::QueryFailure {
        stage: match failure.stage {
            engine::QueryStage::GoalElaboration => wire::QueryStage::GoalElaboration,
            engine::QueryStage::CandidateLookup => wire::QueryStage::CandidateLookup,
            engine::QueryStage::CandidateApplication => wire::QueryStage::CandidateApplication,
            engine::QueryStage::TypeElaboration => wire::QueryStage::TypeElaboration,
            engine::QueryStage::InstanceSynthesis => wire::QueryStage::InstanceSynthesis,
            engine::QueryStage::ContextGoalElaboration => wire::QueryStage::ContextGoalElaboration,
            engine::QueryStage::ContextProofElaboration => {
                wire::QueryStage::ContextProofElaboration
            }
            engine::QueryStage::ContextProofCheck => wire::QueryStage::ContextProofCheck,
            engine::QueryStage::CompositionGoalElaboration => {
                wire::QueryStage::CompositionGoalElaboration
            }
            engine::QueryStage::CompositionProofElaboration => {
                wire::QueryStage::CompositionProofElaboration
            }
            engine::QueryStage::CompositionProofCheck => wire::QueryStage::CompositionProofCheck,
        },
        class: match failure.class {
            engine::ObstructionClass::UnknownDeclaration => {
                wire::ObstructionClass::UnknownDeclaration
            }
            engine::ObstructionClass::Elaboration => wire::ObstructionClass::Elaboration,
            engine::ObstructionClass::TypeMismatch => wire::ObstructionClass::TypeMismatch,
            engine::ObstructionClass::Unification => wire::ObstructionClass::Unification,
            engine::ObstructionClass::DefinitionalEquality => {
                wire::ObstructionClass::DefinitionalEquality
            }
            engine::ObstructionClass::InstanceSynthesis => {
                wire::ObstructionClass::InstanceSynthesis
            }
            engine::ObstructionClass::UnsolvedMetavariables => {
                wire::ObstructionClass::UnsolvedMetavariables
            }
            engine::ObstructionClass::UniverseConstraint => {
                wire::ObstructionClass::UniverseConstraint
            }
            engine::ObstructionClass::MissingHypothesis => {
                wire::ObstructionClass::MissingHypothesis
            }
            engine::ObstructionClass::InvalidProof => wire::ObstructionClass::InvalidProof,
            engine::ObstructionClass::StaleContext => wire::ObstructionClass::StaleContext,
            engine::ObstructionClass::Internal => wire::ObstructionClass::Internal,
        },
        message: lean.message,
        goals: lean.goals.into_iter().map(|goal| goal.type_text).collect(),
        missing_instances: lean.missing_instances,
        metavariables: lean
            .metavariables
            .into_iter()
            .map(|metavariable| wire::QueryMetavariable {
                name: metavariable.name,
                type_text: metavariable.type_text,
            })
            .collect(),
        trace: lean.trace,
    }
}
