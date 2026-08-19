use crate::{Store, StoreError};
use atlas_schema::{
    Challenge, ChallengeId, ClaimAssessment, ClaimDraft, ClaimRevision, ClaimRevisionId,
    ClaimScope, ClaimScopeId, CompletenessWitness, CompletenessWitnessId, EvidenceExpr, EvidenceId,
    EvidenceRecord, ProposalId, ReceiptId, ReceiptRef, RelationSchema, RelationSchemaId,
    ResearchPlan, ResearchPlanId, ResearchProposal, ResearchRun, ResearchRunId, SupportCircuit,
    SupportCircuitId,
};
use rusqlite::{OptionalExtension, params};
use std::collections::BTreeSet;

impl Store {
    pub fn research_schema_version(&self) -> Result<u32, StoreError> {
        Ok(self.conn.query_row(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations",
            [],
            |row| row.get(0),
        )?)
    }

    pub fn insert_relation_schema(&mut self, schema: &RelationSchema) -> Result<(), StoreError> {
        self.ensure_research_absent("relation_schemas_v3", schema.id.0, "relation schema")?;
        self.conn.execute(
            "INSERT INTO relation_schemas_v3(id,wire_name,version,schema_json) VALUES(?1,?2,?3,?4)",
            params![
                schema.id.0,
                schema.wire_name,
                schema.version,
                serde_json::to_string(schema)?
            ],
        )?;
        Ok(())
    }

    pub fn relation_schema(
        &self,
        id: RelationSchemaId,
    ) -> Result<Option<RelationSchema>, StoreError> {
        self.read_json_by_id("relation_schemas_v3", "schema_json", id.0)
    }

    pub fn insert_completeness_witness(
        &mut self,
        witness: &CompletenessWitness,
    ) -> Result<(), StoreError> {
        self.ensure_research_absent(
            "completeness_witnesses_v3",
            witness.id.0,
            "completeness witness",
        )?;
        self.conn.execute(
            "INSERT INTO completeness_witnesses_v3(id,kind,witness_json,digest_json) VALUES(?1,?2,?3,?4)",
            params![
                witness.id.0,
                serde_json::to_string(&witness.kind)?,
                serde_json::to_string(witness)?,
                serde_json::to_string(&witness.digest)?
            ],
        )?;
        Ok(())
    }

    pub fn completeness_witness(
        &self,
        id: CompletenessWitnessId,
    ) -> Result<Option<CompletenessWitness>, StoreError> {
        self.read_json_by_id("completeness_witnesses_v3", "witness_json", id.0)
    }

    pub fn insert_claim_scope(
        &mut self,
        id: ClaimScopeId,
        scope: &ClaimScope,
        content_digest: &atlas_schema::Digest,
    ) -> Result<(), StoreError> {
        self.ensure_research_absent("claim_scopes_v3", id.0, "claim scope")?;
        self.conn.execute(
            "INSERT INTO claim_scopes_v3(id,scope_json,content_digest_json) VALUES(?1,?2,?3)",
            params![
                id.0,
                serde_json::to_string(scope)?,
                serde_json::to_string(content_digest)?
            ],
        )?;
        Ok(())
    }

    pub fn claim_scope(&self, id: ClaimScopeId) -> Result<Option<ClaimScope>, StoreError> {
        self.read_json_by_id("claim_scopes_v3", "scope_json", id.0)
    }

    pub fn insert_receipt(&mut self, receipt: &ReceiptRef) -> Result<(), StoreError> {
        self.ensure_research_absent("receipts_v3", receipt.id.0, "receipt")?;
        self.conn.execute(
            "INSERT INTO receipts_v3(id,schema_json,producer_json,receipt_json) VALUES(?1,?2,?3,?4)",
            params![
                receipt.id.0,
                serde_json::to_string(&receipt.schema)?,
                serde_json::to_string(&receipt.producer)?,
                serde_json::to_string(receipt)?
            ],
        )?;
        Ok(())
    }

    pub fn receipt(&self, id: ReceiptId) -> Result<Option<ReceiptRef>, StoreError> {
        self.read_json_by_id("receipts_v3", "receipt_json", id.0)
    }

    pub fn insert_claim_revision(&mut self, claim: &ClaimRevision) -> Result<(), StoreError> {
        self.ensure_research_absent("claim_revisions_v3", claim.id.0, "claim revision")?;
        let schema = self
            .relation_schema(claim.relation)?
            .ok_or(StoreError::MissingResearchRecord {
                kind: "relation schema",
                id: claim.relation.0,
            })?;
        let scope = self
            .claim_scope(claim.scope)?
            .ok_or(StoreError::MissingResearchRecord {
                kind: "claim scope",
                id: claim.scope.0,
            })?;
        schema.validate_claim(&ClaimDraft {
            kind: claim.kind,
            relation: claim.relation,
            args: claim.args.clone(),
            scope,
            origin: claim.origin.clone(),
        })?;
        if let Some(previous) = claim.supersedes {
            self.require_claim(previous)?;
        }
        self.conn.execute(
            "INSERT INTO claim_revisions_v3(id,stable_key,kind,relation_schema_id,scope_id,content_digest_json,supersedes,claim_json) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
            params![
                claim.id.0,
                claim.stable_key.0,
                serde_json::to_string(&claim.kind)?,
                claim.relation.0,
                claim.scope.0,
                serde_json::to_string(&claim.content_digest)?,
                claim.supersedes.map(|id| id.0),
                serde_json::to_string(claim)?
            ],
        )?;
        Ok(())
    }

    pub fn claim_revision(
        &self,
        id: ClaimRevisionId,
    ) -> Result<Option<ClaimRevision>, StoreError> {
        self.read_json_by_id("claim_revisions_v3", "claim_json", id.0)
    }

    pub fn insert_evidence_record(
        &mut self,
        evidence: &EvidenceRecord,
    ) -> Result<(), StoreError> {
        evidence.validate()?;
        self.ensure_research_absent("evidence_records_v3", evidence.id.0, "evidence")?;
        self.require_receipt(evidence.receipt.id)?;

        for target in &evidence.targets {
            let claim = self.require_claim(target.claim)?;
            self.require_scope(target.applicability_scope)?;
            let schema = self
                .relation_schema(claim.relation)?
                .ok_or(StoreError::MissingResearchRecord {
                    kind: "relation schema",
                    id: claim.relation.0,
                })?;
            schema.validate_evidence_class(evidence.class)?;
        }

        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO evidence_records_v3(id,class,receipt_id,evidence_json) VALUES(?1,?2,?3,?4)",
            params![
                evidence.id.0,
                serde_json::to_string(&evidence.class)?,
                evidence.receipt.id.0,
                serde_json::to_string(evidence)?
            ],
        )?;
        for (position, target) in evidence.targets.iter().enumerate() {
            tx.execute(
                "INSERT INTO evidence_targets_v3(evidence_id,position,claim_id,scope_id,target_json) VALUES(?1,?2,?3,?4,?5)",
                params![
                    evidence.id.0,
                    position as u64,
                    target.claim.0,
                    target.applicability_scope.0,
                    serde_json::to_string(target)?
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn evidence_record(
        &self,
        id: EvidenceId,
    ) -> Result<Option<EvidenceRecord>, StoreError> {
        self.read_json_by_id("evidence_records_v3", "evidence_json", id.0)
    }

    pub fn insert_support_circuit(
        &mut self,
        circuit: &SupportCircuit,
    ) -> Result<(), StoreError> {
        self.ensure_research_absent("support_circuits_v3", circuit.id.0, "support circuit")?;
        self.require_claim(circuit.claim)?;
        self.validate_evidence_expr(&circuit.expression)?;
        self.conn.execute(
            "INSERT INTO support_circuits_v3(id,claim_id,expression_json,circuit_json) VALUES(?1,?2,?3,?4)",
            params![
                circuit.id.0,
                circuit.claim.0,
                serde_json::to_string(&circuit.expression)?,
                serde_json::to_string(circuit)?
            ],
        )?;
        Ok(())
    }

    pub fn support_circuit(
        &self,
        id: SupportCircuitId,
    ) -> Result<Option<SupportCircuit>, StoreError> {
        self.read_json_by_id("support_circuits_v3", "circuit_json", id.0)
    }

    pub fn insert_challenge(&mut self, challenge: &Challenge) -> Result<(), StoreError> {
        self.ensure_research_absent("challenges_v3", challenge.id.0, "challenge")?;
        self.require_claim(challenge.target)?;
        self.require_scope(challenge.scope)?;
        self.validate_evidence_expr(&challenge.evidence)?;
        self.conn.execute(
            "INSERT INTO challenges_v3(id,target_claim_id,scope_id,kind,challenge_json) VALUES(?1,?2,?3,?4,?5)",
            params![
                challenge.id.0,
                challenge.target.0,
                challenge.scope.0,
                serde_json::to_string(&challenge.kind)?,
                serde_json::to_string(challenge)?
            ],
        )?;
        Ok(())
    }

    pub fn challenge(&self, id: ChallengeId) -> Result<Option<Challenge>, StoreError> {
        self.read_json_by_id("challenges_v3", "challenge_json", id.0)
    }

    pub fn insert_research_proposal(
        &mut self,
        proposal: &ResearchProposal,
    ) -> Result<(), StoreError> {
        self.ensure_research_absent("research_proposals_v3", proposal.id.0, "research proposal")?;
        self.require_receipt(proposal.generator.id)?;

        let local_claims: BTreeSet<_> = proposal
            .proposed_claims
            .iter()
            .map(|claim| claim.local_id)
            .collect();
        if local_claims.len() != proposal.proposed_claims.len() {
            return Err(StoreError::InvalidResearchGraph(
                "proposal contains duplicate local claim IDs".into(),
            ));
        }
        for proposed in &proposal.proposed_claims {
            let schema = self
                .relation_schema(proposed.draft.relation)?
                .ok_or(StoreError::MissingResearchRecord {
                    kind: "relation schema",
                    id: proposed.draft.relation.0,
                })?;
            schema.validate_claim(&proposed.draft)?;
        }
        for falsifier in &proposal.falsifiers {
            if !local_claims.contains(&falsifier.target) {
                return Err(StoreError::InvalidResearchGraph(format!(
                    "falsifier {:?} targets unknown proposal-local claim {:?}",
                    falsifier.id, falsifier.target
                )));
            }
            self.ensure_research_absent("falsifiers_v3", falsifier.id.0, "falsifier")?;
        }

        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO research_proposals_v3(id,generator_receipt_id,world_json,proposal_json) VALUES(?1,?2,?3,?4)",
            params![
                proposal.id.0,
                proposal.generator.id.0,
                serde_json::to_string(&proposal.world)?,
                serde_json::to_string(proposal)?
            ],
        )?;
        for falsifier in &proposal.falsifiers {
            tx.execute(
                "INSERT INTO falsifiers_v3(id,proposal_id,target_local_id,falsifier_json) VALUES(?1,?2,?3,?4)",
                params![
                    falsifier.id.0,
                    proposal.id.0,
                    falsifier.target.0,
                    serde_json::to_string(falsifier)?
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn research_proposal(
        &self,
        id: ProposalId,
    ) -> Result<Option<ResearchProposal>, StoreError> {
        self.read_json_by_id("research_proposals_v3", "proposal_json", id.0)
    }

    pub fn insert_research_plan(&mut self, plan: &ResearchPlan) -> Result<(), StoreError> {
        self.ensure_research_absent("research_plans_v3", plan.id.0, "research plan")?;
        self.require_research_record("research_proposals_v3", plan.proposal.0, "research proposal")?;
        self.conn.execute(
            "INSERT INTO research_plans_v3(id,proposal_id,content_digest_json,plan_json) VALUES(?1,?2,?3,?4)",
            params![
                plan.id.0,
                plan.proposal.0,
                serde_json::to_string(&plan.content_digest)?,
                serde_json::to_string(plan)?
            ],
        )?;
        Ok(())
    }

    pub fn research_plan(
        &self,
        id: ResearchPlanId,
    ) -> Result<Option<ResearchPlan>, StoreError> {
        self.read_json_by_id("research_plans_v3", "plan_json", id.0)
    }

    pub fn insert_research_run(&mut self, run: &ResearchRun) -> Result<(), StoreError> {
        self.ensure_research_absent("research_runs_v3", run.id.0, "research run")?;
        self.require_research_record("research_plans_v3", run.plan.0, "research plan")?;
        for receipt in &run.receipts {
            self.require_receipt(receipt.id)?;
        }
        for claim in &run.produced_claims {
            self.require_claim(*claim)?;
        }
        for evidence in &run.produced_evidence {
            self.require_evidence(*evidence)?;
        }
        self.conn.execute(
            "INSERT INTO research_runs_v3(id,plan_id,content_digest_json,run_json) VALUES(?1,?2,?3,?4)",
            params![
                run.id.0,
                run.plan.0,
                serde_json::to_string(&run.content_digest)?,
                serde_json::to_string(run)?
            ],
        )?;
        Ok(())
    }

    pub fn research_run(
        &self,
        id: ResearchRunId,
    ) -> Result<Option<ResearchRun>, StoreError> {
        self.read_json_by_id("research_runs_v3", "run_json", id.0)
    }

    pub fn insert_claim_assessment(
        &mut self,
        assessment: &ClaimAssessment,
    ) -> Result<(), StoreError> {
        self.ensure_research_absent(
            "claim_assessments_v3",
            assessment.id.0,
            "claim assessment",
        )?;
        self.require_claim(assessment.claim)?;
        self.conn.execute(
            "INSERT INTO claim_assessments_v3(id,claim_id,policy_id,evidence_snapshot_json,assessment_json) VALUES(?1,?2,?3,?4,?5)",
            params![
                assessment.id.0,
                assessment.claim.0,
                assessment.policy.0,
                serde_json::to_string(&assessment.evidence_snapshot)?,
                serde_json::to_string(assessment)?
            ],
        )?;
        Ok(())
    }

    pub fn claim_assessment(
        &self,
        id: atlas_schema::AssessmentId,
    ) -> Result<Option<ClaimAssessment>, StoreError> {
        self.read_json_by_id("claim_assessments_v3", "assessment_json", id.0)
    }

    fn validate_evidence_expr(&self, expression: &EvidenceExpr) -> Result<(), StoreError> {
        match expression {
            EvidenceExpr::Evidence(id) => {
                self.require_evidence(*id)?;
            }
            EvidenceExpr::Claim(id) => {
                self.require_claim(*id)?;
            }
            EvidenceExpr::All(items) | EvidenceExpr::Any(items) => {
                if items.is_empty() {
                    return Err(StoreError::InvalidResearchGraph(
                        "support alternatives and conjunctions cannot be empty".into(),
                    ));
                }
                for item in items {
                    self.validate_evidence_expr(item)?;
                }
            }
            EvidenceExpr::AtLeast { k, of } => {
                if *k == 0 || *k > of.len() {
                    return Err(StoreError::InvalidResearchGraph(format!(
                        "invalid AtLeast threshold {k} for {} inputs",
                        of.len()
                    )));
                }
                for item in of {
                    self.validate_evidence_expr(item)?;
                }
            }
            EvidenceExpr::RuleApplication { inputs, .. } => {
                if inputs.is_empty() {
                    return Err(StoreError::InvalidResearchGraph(
                        "rule application requires at least one input".into(),
                    ));
                }
                for input in inputs {
                    self.validate_evidence_expr(input)?;
                }
            }
        }
        Ok(())
    }

    fn require_claim(&self, id: ClaimRevisionId) -> Result<ClaimRevision, StoreError> {
        self.claim_revision(id)?
            .ok_or(StoreError::MissingResearchRecord {
                kind: "claim revision",
                id: id.0,
            })
    }

    fn require_scope(&self, id: ClaimScopeId) -> Result<ClaimScope, StoreError> {
        self.claim_scope(id)?
            .ok_or(StoreError::MissingResearchRecord {
                kind: "claim scope",
                id: id.0,
            })
    }

    fn require_receipt(&self, id: ReceiptId) -> Result<ReceiptRef, StoreError> {
        self.receipt(id)?
            .ok_or(StoreError::MissingResearchRecord {
                kind: "receipt",
                id: id.0,
            })
    }

    fn require_evidence(&self, id: EvidenceId) -> Result<EvidenceRecord, StoreError> {
        self.evidence_record(id)?
            .ok_or(StoreError::MissingResearchRecord {
                kind: "evidence",
                id: id.0,
            })
    }

    fn require_research_record(
        &self,
        table: &'static str,
        id: u64,
        kind: &'static str,
    ) -> Result<(), StoreError> {
        if self.research_exists(table, id)? {
            Ok(())
        } else {
            Err(StoreError::MissingResearchRecord { kind, id })
        }
    }

    fn ensure_research_absent(
        &self,
        table: &'static str,
        id: u64,
        kind: &'static str,
    ) -> Result<(), StoreError> {
        if self.research_exists(table, id)? {
            Err(StoreError::DuplicateResearchRecord { kind, id })
        } else {
            Ok(())
        }
    }

    fn research_exists(&self, table: &'static str, id: u64) -> Result<bool, StoreError> {
        let sql = format!("SELECT 1 FROM {table} WHERE id=?1");
        Ok(self
            .conn
            .query_row(&sql, [id], |_| Ok(()))
            .optional()?
            .is_some())
    }

    fn read_json_by_id<T: serde::de::DeserializeOwned>(
        &self,
        table: &'static str,
        column: &'static str,
        id: u64,
    ) -> Result<Option<T>, StoreError> {
        let sql = format!("SELECT {column} FROM {table} WHERE id=?1");
        let raw: Option<String> = self
            .conn
            .query_row(&sql, [id], |row| row.get(0))
            .optional()?;
        raw.map(|json| Ok(serde_json::from_str(&json)?)).transpose()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use atlas_schema::{
        ActorId, ArgumentSpec, ArtifactId, ArtifactRef, ClaimContext, ClaimKeyId, ClaimKind,
        ClaimOrigin, Digest, EqualitySemantics, EvidenceBearing, EvidenceClass, EvidencePayload,
        EvidenceTarget, MetricValue, ProducerIdentity, RelationExecution, RelationSymmetry,
        ScopeCompleteness, ScopePolicy, SchemaId, SemanticScope, SourceAnchor, TypedValue,
        ValueType, WorldSemantics,
    };
    use std::collections::{BTreeMap, BTreeSet};

    fn digest(value: &str) -> Digest {
        Digest {
            algorithm: "sha256".into(),
            value: value.into(),
        }
    }

    fn scope() -> ClaimScope {
        ClaimScope {
            semantic: SemanticScope::default(),
            context: ClaimContext::default(),
            completeness: ScopeCompleteness::Complete,
        }
    }

    fn schema() -> RelationSchema {
        RelationSchema {
            id: RelationSchemaId(1),
            wire_name: "describes".into(),
            version: 1,
            arguments: vec![ArgumentSpec {
                role: "description".into(),
                value_type: ValueType::Text,
                equality: EqualitySemantics::ExactIdentity,
            }],
            symmetry: RelationSymmetry::Directed,
            execution: RelationExecution::Materialized,
            world_semantics: WorldSemantics::OpenWorld,
            scope_policy: ScopePolicy::Required,
            admissible_evidence: BTreeSet::from([
                EvidenceClass::Formal,
                EvidenceClass::Documentary,
                EvidenceClass::Numerical,
            ]),
        }
    }

    fn receipt() -> ReceiptRef {
        ReceiptRef {
            id: ReceiptId(1),
            schema: SchemaId {
                name: "test-receipt".into(),
                version: 1,
                digest: digest("receipt-schema"),
            },
            producer: ProducerIdentity {
                repository: "akiselev/lean-atlas".into(),
                commit: "abc".into(),
                package: "atlas-test".into(),
                package_version: "0.1.0".into(),
                executable_digest: digest("executable"),
            },
            artifact: Some(ArtifactRef {
                id: ArtifactId(1),
                digest: Some(digest("receipt")),
                locator: None,
            }),
        }
    }

    fn claim() -> ClaimRevision {
        ClaimRevision {
            id: ClaimRevisionId(1),
            stable_key: ClaimKeyId(1),
            kind: ClaimKind::LiteratureAssertion,
            relation: RelationSchemaId(1),
            args: vec![TypedValue::Text("scoped statement".into())],
            scope: ClaimScopeId(1),
            origin: ClaimOrigin::Imported {
                source: SourceAnchor::Paper {
                    citation: "fixture".into(),
                    doi: None,
                    locator: "p. 1".into(),
                },
            },
            content_digest: digest("claim"),
            supersedes: None,
        }
    }

    fn initialized_store() -> Store {
        let mut store = Store::memory().unwrap();
        store.insert_relation_schema(&schema()).unwrap();
        store
            .insert_claim_scope(ClaimScopeId(1), &scope(), &digest("scope"))
            .unwrap();
        store.insert_receipt(&receipt()).unwrap();
        store.insert_claim_revision(&claim()).unwrap();
        store
    }

    #[test]
    fn v3_claim_and_evidence_roundtrip() {
        let mut store = initialized_store();
        let evidence = EvidenceRecord {
            id: EvidenceId(1),
            class: EvidenceClass::Documentary,
            receipt: receipt(),
            targets: vec![EvidenceTarget {
                claim: ClaimRevisionId(1),
                bearing: EvidenceBearing::Supports,
                applicability_scope: ClaimScopeId(1),
                scope_relation: atlas_schema::ScopeRelation::Exact,
            }],
            payload: EvidencePayload::LiteratureSource {
                source: SourceAnchor::Paper {
                    citation: "fixture".into(),
                    doi: None,
                    locator: "p. 1".into(),
                },
                statement: "scoped statement".into(),
            },
            limitations: vec![],
            independence_group: None,
            recorded_by: ActorId(1),
            recorded_at: "2026-08-19T00:00:00Z".into(),
        };
        store.insert_evidence_record(&evidence).unwrap();
        assert_eq!(store.claim_revision(ClaimRevisionId(1)).unwrap(), Some(claim()));
        assert_eq!(store.evidence_record(EvidenceId(1)).unwrap(), Some(evidence));
        assert_eq!(store.research_schema_version().unwrap(), 2);
    }

    #[test]
    fn evidence_requires_a_persisted_receipt() {
        let mut store = initialized_store();
        let mut missing = receipt();
        missing.id = ReceiptId(99);
        let evidence = EvidenceRecord {
            id: EvidenceId(2),
            class: EvidenceClass::Numerical,
            receipt: missing,
            targets: vec![EvidenceTarget {
                claim: ClaimRevisionId(1),
                bearing: EvidenceBearing::Supports,
                applicability_scope: ClaimScopeId(1),
                scope_relation: atlas_schema::ScopeRelation::Exact,
            }],
            payload: EvidencePayload::NumericalResult {
                artifact: ArtifactRef {
                    id: ArtifactId(2),
                    digest: Some(digest("result")),
                    locator: None,
                },
                metrics: BTreeMap::from([(
                    "score".into(),
                    MetricValue::new(1, 1, None).unwrap(),
                )]),
            },
            limitations: vec![],
            independence_group: None,
            recorded_by: ActorId(1),
            recorded_at: "2026-08-19T00:00:00Z".into(),
        };
        assert!(matches!(
            store.insert_evidence_record(&evidence),
            Err(StoreError::MissingResearchRecord {
                kind: "receipt",
                id: 99
            })
        ));
    }

    #[test]
    fn support_circuit_rejects_missing_evidence() {
        let mut store = initialized_store();
        let circuit = SupportCircuit {
            id: SupportCircuitId(1),
            claim: ClaimRevisionId(1),
            expression: EvidenceExpr::Evidence(EvidenceId(404)),
        };
        assert!(matches!(
            store.insert_support_circuit(&circuit),
            Err(StoreError::MissingResearchRecord {
                kind: "evidence",
                id: 404
            })
        ));
    }

    #[test]
    fn append_only_trigger_rejects_claim_mutation() {
        let store = initialized_store();
        let error = store
            .conn
            .execute(
                "UPDATE claim_revisions_v3 SET kind='changed' WHERE id=1",
                [],
            )
            .unwrap_err();
        assert!(error.to_string().contains("append-only"));
    }

    #[test]
    fn relation_signature_is_checked_before_claim_insert() {
        let mut store = Store::memory().unwrap();
        store.insert_relation_schema(&schema()).unwrap();
        store
            .insert_claim_scope(ClaimScopeId(1), &scope(), &digest("scope"))
            .unwrap();
        let mut malformed = claim();
        malformed.args = vec![TypedValue::Integer(1)];
        assert!(matches!(
            store.insert_claim_revision(&malformed),
            Err(StoreError::InvalidResearchSchema(_))
        ));
    }
}
