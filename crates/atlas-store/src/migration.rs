pub const V1: &str = r#"
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS entities(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,canonical_name TEXT);
CREATE TABLE IF NOT EXISTS declarations(id INTEGER PRIMARY KEY,entity_id INTEGER,lean_name TEXT NOT NULL,module TEXT);
CREATE TABLE IF NOT EXISTS entity_aliases(entity_id INTEGER NOT NULL,alias TEXT NOT NULL,UNIQUE(entity_id,alias));
CREATE TABLE IF NOT EXISTS relation_types(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,arity INTEGER NOT NULL,execution TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY,relation_id INTEGER NOT NULL,warrant TEXT NOT NULL,provenance_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fact_args(fact_id INTEGER NOT NULL,position INTEGER NOT NULL,value_json TEXT NOT NULL,PRIMARY KEY(fact_id,position));
CREATE INDEX IF NOT EXISTS facts_by_relation ON facts(relation_id,id);
CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fact_evidence(fact_id INTEGER NOT NULL,evidence_id INTEGER NOT NULL,PRIMARY KEY(fact_id,evidence_id));
CREATE TABLE IF NOT EXISTS origins(id INTEGER PRIMARY KEY,authority TEXT NOT NULL,locator TEXT,digest TEXT);
CREATE TABLE IF NOT EXISTS oracle_receipts(id INTEGER PRIMARY KEY,environment_id INTEGER NOT NULL,operation TEXT NOT NULL,request_json TEXT NOT NULL,response_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifact_links(id INTEGER PRIMARY KEY,fact_id INTEGER,authority TEXT NOT NULL,artifact_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS statement_fingerprints(declaration_id INTEGER PRIMARY KEY,fingerprint TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proof_fingerprints(declaration_id INTEGER PRIMARY KEY,fingerprint TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS module_versions(module TEXT PRIMARY KEY,environment_id INTEGER NOT NULL,digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS experiments(id INTEGER PRIMARY KEY,external_id TEXT,payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assays(id INTEGER PRIMARY KEY,external_id TEXT,payload_json TEXT NOT NULL);
INSERT OR IGNORE INTO schema_migrations(version) VALUES(1);
"#;

/// Additive research-v3 storage. Semantic identities, provenance, claims and
/// evidence are append-only. Proposals, falsifiers, plans, observed runs and
/// assessments remain mutable provisional workspace state while Atlas itself is
/// being validated; persistence alone never promotes an experimental result.
pub const V2: &str = r#"
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS relation_schemas_v3(
  id INTEGER PRIMARY KEY,
  wire_name TEXT NOT NULL,
  version INTEGER NOT NULL,
  schema_json TEXT NOT NULL,
  UNIQUE(wire_name, version)
);

CREATE TABLE IF NOT EXISTS completeness_witnesses_v3(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  witness_json TEXT NOT NULL,
  digest_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_scopes_v3(
  id INTEGER PRIMARY KEY,
  scope_json TEXT NOT NULL,
  content_digest_json TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS receipts_v3(
  id INTEGER PRIMARY KEY,
  schema_json TEXT NOT NULL,
  producer_json TEXT NOT NULL,
  receipt_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_revisions_v3(
  id INTEGER PRIMARY KEY,
  stable_key INTEGER NOT NULL,
  kind TEXT NOT NULL,
  relation_schema_id INTEGER NOT NULL REFERENCES relation_schemas_v3(id),
  scope_id INTEGER NOT NULL REFERENCES claim_scopes_v3(id),
  content_digest_json TEXT NOT NULL,
  supersedes INTEGER REFERENCES claim_revisions_v3(id),
  claim_json TEXT NOT NULL,
  UNIQUE(stable_key, content_digest_json)
);
CREATE INDEX IF NOT EXISTS claims_v3_by_relation
  ON claim_revisions_v3(relation_schema_id, id);
CREATE INDEX IF NOT EXISTS claims_v3_by_stable_key
  ON claim_revisions_v3(stable_key, id);

CREATE TABLE IF NOT EXISTS evidence_records_v3(
  id INTEGER PRIMARY KEY,
  class TEXT NOT NULL,
  receipt_id INTEGER NOT NULL REFERENCES receipts_v3(id),
  evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_targets_v3(
  evidence_id INTEGER NOT NULL REFERENCES evidence_records_v3(id),
  position INTEGER NOT NULL,
  claim_id INTEGER NOT NULL REFERENCES claim_revisions_v3(id),
  scope_id INTEGER NOT NULL REFERENCES claim_scopes_v3(id),
  target_json TEXT NOT NULL,
  PRIMARY KEY(evidence_id, position)
);
CREATE INDEX IF NOT EXISTS evidence_targets_v3_by_claim
  ON evidence_targets_v3(claim_id, evidence_id);

CREATE TABLE IF NOT EXISTS support_circuits_v3(
  id INTEGER PRIMARY KEY,
  claim_id INTEGER NOT NULL REFERENCES claim_revisions_v3(id),
  expression_json TEXT NOT NULL,
  circuit_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS support_circuits_v3_by_claim
  ON support_circuits_v3(claim_id, id);

CREATE TABLE IF NOT EXISTS challenges_v3(
  id INTEGER PRIMARY KEY,
  target_claim_id INTEGER NOT NULL REFERENCES claim_revisions_v3(id),
  scope_id INTEGER NOT NULL REFERENCES claim_scopes_v3(id),
  kind TEXT NOT NULL,
  challenge_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS challenges_v3_by_claim
  ON challenges_v3(target_claim_id, id);

-- The following tables describe an evolving research workflow. Their rows may
-- be revised or discarded until a result is represented by immutable receipts,
-- claim revisions and evidence records above.
CREATE TABLE IF NOT EXISTS research_proposals_v3(
  id INTEGER PRIMARY KEY,
  generator_receipt_id INTEGER NOT NULL REFERENCES receipts_v3(id),
  world_json TEXT NOT NULL,
  proposal_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS falsifiers_v3(
  id INTEGER PRIMARY KEY,
  proposal_id INTEGER NOT NULL REFERENCES research_proposals_v3(id),
  target_local_id INTEGER NOT NULL,
  falsifier_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS falsifiers_v3_by_proposal
  ON falsifiers_v3(proposal_id, id);

CREATE TABLE IF NOT EXISTS research_plans_v3(
  id INTEGER PRIMARY KEY,
  proposal_id INTEGER NOT NULL REFERENCES research_proposals_v3(id),
  content_digest_json TEXT NOT NULL,
  plan_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_runs_v3(
  id INTEGER PRIMARY KEY,
  plan_id INTEGER NOT NULL REFERENCES research_plans_v3(id),
  content_digest_json TEXT NOT NULL,
  run_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_assessments_v3(
  id INTEGER PRIMARY KEY,
  claim_id INTEGER NOT NULL REFERENCES claim_revisions_v3(id),
  policy_id INTEGER NOT NULL,
  evidence_snapshot_json TEXT NOT NULL,
  assessment_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS claim_assessments_v3_by_claim
  ON claim_assessments_v3(claim_id, id);

CREATE TRIGGER IF NOT EXISTS relation_schemas_v3_no_update BEFORE UPDATE ON relation_schemas_v3 BEGIN SELECT RAISE(ABORT, 'relation_schemas_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS relation_schemas_v3_no_delete BEFORE DELETE ON relation_schemas_v3 BEGIN SELECT RAISE(ABORT, 'relation_schemas_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS completeness_witnesses_v3_no_update BEFORE UPDATE ON completeness_witnesses_v3 BEGIN SELECT RAISE(ABORT, 'completeness_witnesses_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS completeness_witnesses_v3_no_delete BEFORE DELETE ON completeness_witnesses_v3 BEGIN SELECT RAISE(ABORT, 'completeness_witnesses_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS claim_scopes_v3_no_update BEFORE UPDATE ON claim_scopes_v3 BEGIN SELECT RAISE(ABORT, 'claim_scopes_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS claim_scopes_v3_no_delete BEFORE DELETE ON claim_scopes_v3 BEGIN SELECT RAISE(ABORT, 'claim_scopes_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_v3_no_update BEFORE UPDATE ON receipts_v3 BEGIN SELECT RAISE(ABORT, 'receipts_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_v3_no_delete BEFORE DELETE ON receipts_v3 BEGIN SELECT RAISE(ABORT, 'receipts_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS claim_revisions_v3_no_update BEFORE UPDATE ON claim_revisions_v3 BEGIN SELECT RAISE(ABORT, 'claim_revisions_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS claim_revisions_v3_no_delete BEFORE DELETE ON claim_revisions_v3 BEGIN SELECT RAISE(ABORT, 'claim_revisions_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_records_v3_no_update BEFORE UPDATE ON evidence_records_v3 BEGIN SELECT RAISE(ABORT, 'evidence_records_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_records_v3_no_delete BEFORE DELETE ON evidence_records_v3 BEGIN SELECT RAISE(ABORT, 'evidence_records_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_targets_v3_no_update BEFORE UPDATE ON evidence_targets_v3 BEGIN SELECT RAISE(ABORT, 'evidence_targets_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_targets_v3_no_delete BEFORE DELETE ON evidence_targets_v3 BEGIN SELECT RAISE(ABORT, 'evidence_targets_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS support_circuits_v3_no_update BEFORE UPDATE ON support_circuits_v3 BEGIN SELECT RAISE(ABORT, 'support_circuits_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS support_circuits_v3_no_delete BEFORE DELETE ON support_circuits_v3 BEGIN SELECT RAISE(ABORT, 'support_circuits_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS challenges_v3_no_update BEFORE UPDATE ON challenges_v3 BEGIN SELECT RAISE(ABORT, 'challenges_v3 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS challenges_v3_no_delete BEFORE DELETE ON challenges_v3 BEGIN SELECT RAISE(ABORT, 'challenges_v3 is append-only'); END;

INSERT OR IGNORE INTO schema_migrations(version) VALUES(2);
"#;

#[cfg(test)]
mod tests {
    use crate::Store;
    use rusqlite::params;

    #[test]
    fn workflow_records_remain_revisable_during_validation() {
        let store = Store::memory().unwrap();

        store
            .conn
            .execute(
                "INSERT INTO relation_schemas_v3(id,wire_name,version,schema_json) VALUES(1,'test',1,'{}')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO claim_scopes_v3(id,scope_json,content_digest_json) VALUES(1,'{}','scope')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO receipts_v3(id,schema_json,producer_json,receipt_json) VALUES(1,'{}','{}','{}')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO claim_revisions_v3(id,stable_key,kind,relation_schema_id,scope_id,content_digest_json,claim_json) VALUES(1,1,'candidate',1,1,'claim','{}')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO research_proposals_v3(id,generator_receipt_id,world_json,proposal_json) VALUES(1,1,'{}','{}')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO falsifiers_v3(id,proposal_id,target_local_id,falsifier_json) VALUES(1,1,1,'{}')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO research_plans_v3(id,proposal_id,content_digest_json,plan_json) VALUES(1,1,'plan','{}')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO research_runs_v3(id,plan_id,content_digest_json,run_json) VALUES(1,1,'run','{}')",
                [],
            )
            .unwrap();
        store
            .conn
            .execute(
                "INSERT INTO claim_assessments_v3(id,claim_id,policy_id,evidence_snapshot_json,assessment_json) VALUES(1,1,1,'{}','{}')",
                [],
            )
            .unwrap();

        for table in [
            "research_proposals_v3",
            "falsifiers_v3",
            "research_plans_v3",
            "research_runs_v3",
            "claim_assessments_v3",
        ] {
            let sql = format!("UPDATE {table} SET id=id WHERE id=1");
            store.conn.execute(&sql, []).unwrap();
        }

        store
            .conn
            .execute(
                "UPDATE research_runs_v3 SET run_json=?1 WHERE id=1",
                params![r#"{"revision":2}"#],
            )
            .unwrap();
        let stored: String = store
            .conn
            .query_row(
                "SELECT run_json FROM research_runs_v3 WHERE id=1",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(stored, r#"{"revision":2}"#);

        store
            .conn
            .execute("DELETE FROM research_runs_v3 WHERE id=1", [])
            .unwrap();
    }

    #[test]
    fn semantic_and_provenance_records_remain_append_only() {
        let store = Store::memory().unwrap();
        store
            .conn
            .execute(
                "INSERT INTO relation_schemas_v3(id,wire_name,version,schema_json) VALUES(1,'test',1,'{}')",
                [],
            )
            .unwrap();
        let error = store
            .conn
            .execute(
                "UPDATE relation_schemas_v3 SET wire_name='changed' WHERE id=1",
                [],
            )
            .unwrap_err();
        assert!(error.to_string().contains("append-only"));
    }
}
