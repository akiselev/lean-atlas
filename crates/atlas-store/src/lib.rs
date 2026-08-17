//! Durable semantic fact storage.
//!
//! Bulk corpora and scientific datasets do not belong here; this database stores small
//! semantic tuples, evidence origins, and derivation edges. Artifact bytes remain the
//! responsibility of the external artifact layer.

use atlas_schema::{FactId, FactKey, RuleId, Value, Warrant};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;

const SCHEMA_VERSION: i64 = 1;

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("serialization error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("unknown warrant value {0}")]
    UnknownWarrant(i64),
    #[error("database schema version {found} is newer than supported version {supported}")]
    NewerSchema { found: i64, supported: i64 },
}

pub type Result<T, E = StoreError> = std::result::Result<T, E>;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Origin {
    pub kind: String,
    pub payload: serde_json::Value,
}

impl Origin {
    #[must_use]
    pub fn new(kind: impl Into<String>, payload: serde_json::Value) -> Self {
        Self {
            kind: kind.into(),
            payload,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct StoredFact {
    pub id: FactId,
    pub key: FactKey,
    pub warrant: Warrant,
    pub origins: Vec<Origin>,
}

pub struct Store {
    connection: Connection,
}

impl Store {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let connection = Connection::open(path)?;
        Self::from_connection(connection)
    }

    pub fn in_memory() -> Result<Self> {
        let connection = Connection::open_in_memory()?;
        Self::from_connection(connection)
    }

    fn from_connection(connection: Connection) -> Result<Self> {
        connection.pragma_update(None, "foreign_keys", "ON")?;
        connection.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS atlas_meta (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY,
                relation TEXT NOT NULL,
                tuple_json TEXT NOT NULL,
                warrant INTEGER NOT NULL,
                UNIQUE(relation, tuple_json)
            );
            CREATE INDEX IF NOT EXISTS facts_by_relation ON facts(relation);
            CREATE TABLE IF NOT EXISTS origins (
                id INTEGER PRIMARY KEY,
                fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(fact_id, kind, payload_json)
            );
            CREATE TABLE IF NOT EXISTS derivations (
                fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
                rule_id INTEGER NOT NULL,
                input_fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY(fact_id, rule_id, ordinal)
            );
            ",
        )?;
        let found: Option<i64> = connection
            .query_row(
                "SELECT value FROM atlas_meta WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(found) = found {
            if found > SCHEMA_VERSION {
                return Err(StoreError::NewerSchema {
                    found,
                    supported: SCHEMA_VERSION,
                });
            }
        } else {
            connection.execute(
                "INSERT INTO atlas_meta(key, value) VALUES('schema_version', ?1)",
                [SCHEMA_VERSION],
            )?;
        }
        Ok(Self { connection })
    }

    pub fn insert_fact(
        &mut self,
        key: &FactKey,
        warrant: Warrant,
        origin: Option<&Origin>,
    ) -> Result<FactId> {
        let tuple_json = serde_json::to_string(&key.tuple)?;
        let transaction = self.connection.transaction()?;
        transaction.execute(
            "INSERT INTO facts(relation, tuple_json, warrant)
             VALUES(?1, ?2, ?3)
             ON CONFLICT(relation, tuple_json)
             DO UPDATE SET warrant = MIN(facts.warrant, excluded.warrant)",
            params![key.relation, tuple_json, warrant_rank(warrant)],
        )?;
        let id: i64 = transaction.query_row(
            "SELECT id FROM facts WHERE relation = ?1 AND tuple_json = ?2",
            params![key.relation, tuple_json],
            |row| row.get(0),
        )?;
        if let Some(origin) = origin {
            transaction.execute(
                "INSERT OR IGNORE INTO origins(fact_id, kind, payload_json)
                 VALUES(?1, ?2, ?3)",
                params![id, origin.kind, serde_json::to_string(&origin.payload)?],
            )?;
        }
        transaction.commit()?;
        Ok(FactId::new(id as u64))
    }

    pub fn fact(&self, id: FactId) -> Result<Option<StoredFact>> {
        let row: Option<(String, String, i64)> = self
            .connection
            .query_row(
                "SELECT relation, tuple_json, warrant FROM facts WHERE id = ?1",
                [id.get() as i64],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()?;
        let Some((relation, tuple_json, warrant)) = row else {
            return Ok(None);
        };
        let tuple: Vec<Value> = serde_json::from_str(&tuple_json)?;
        let origins = self.origins(id)?;
        Ok(Some(StoredFact {
            id,
            key: FactKey::new(relation, tuple),
            warrant: warrant_from_rank(warrant)?,
            origins,
        }))
    }

    pub fn facts_by_relation(&self, relation: &str) -> Result<Vec<StoredFact>> {
        let mut statement = self
            .connection
            .prepare("SELECT id, tuple_json, warrant FROM facts WHERE relation = ?1 ORDER BY id")?;
        let rows = statement.query_map([relation], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
            ))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (id, tuple_json, warrant) = row?;
            let id = FactId::new(id as u64);
            out.push(StoredFact {
                id,
                key: FactKey::new(relation, serde_json::from_str(&tuple_json)?),
                warrant: warrant_from_rank(warrant)?,
                origins: self.origins(id)?,
            });
        }
        Ok(out)
    }

    pub fn add_derivation(&mut self, fact: FactId, rule: RuleId, inputs: &[FactId]) -> Result<()> {
        let transaction = self.connection.transaction()?;
        for (ordinal, input) in inputs.iter().enumerate() {
            transaction.execute(
                "INSERT OR REPLACE INTO derivations(fact_id, rule_id, input_fact_id, ordinal)
                 VALUES(?1, ?2, ?3, ?4)",
                params![
                    fact.get() as i64,
                    rule.get() as i64,
                    input.get() as i64,
                    ordinal as i64
                ],
            )?;
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn derivation_inputs(&self, fact: FactId, rule: RuleId) -> Result<Vec<FactId>> {
        let mut statement = self.connection.prepare(
            "SELECT input_fact_id FROM derivations
             WHERE fact_id = ?1 AND rule_id = ?2 ORDER BY ordinal",
        )?;
        let rows = statement.query_map(params![fact.get() as i64, rule.get() as i64], |row| {
            row.get::<_, i64>(0)
        })?;
        let mut out = Vec::new();
        for row in rows {
            out.push(FactId::new(row? as u64));
        }
        Ok(out)
    }

    fn origins(&self, fact: FactId) -> Result<Vec<Origin>> {
        let mut statement = self
            .connection
            .prepare("SELECT kind, payload_json FROM origins WHERE fact_id = ?1 ORDER BY id")?;
        let rows = statement.query_map([fact.get() as i64], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (kind, payload) = row?;
            out.push(Origin::new(kind, serde_json::from_str(&payload)?));
        }
        Ok(out)
    }
}

const fn warrant_rank(warrant: Warrant) -> i64 {
    match warrant {
        Warrant::Proved => 0,
        Warrant::Structural => 1,
        Warrant::Asserted => 2,
        Warrant::Heuristic => 3,
    }
}

fn warrant_from_rank(value: i64) -> Result<Warrant> {
    match value {
        0 => Ok(Warrant::Proved),
        1 => Ok(Warrant::Structural),
        2 => Ok(Warrant::Asserted),
        3 => Ok(Warrant::Heuristic),
        value => Err(StoreError::UnknownWarrant(value)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use atlas_schema::Value;

    #[test]
    fn facts_merge_origins_and_keep_the_strongest_warrant() {
        let mut store = Store::in_memory().unwrap();
        let key = FactKey::new(
            "similar",
            vec![Value::Text("a".into()), Value::Text("b".into())],
        );
        let first = store
            .insert_fact(
                &key,
                Warrant::Heuristic,
                Some(&Origin::new("ranking", serde_json::json!({"score": 0.8}))),
            )
            .unwrap();
        let second = store
            .insert_fact(
                &key,
                Warrant::Structural,
                Some(&Origin::new(
                    "canonical",
                    serde_json::json!({"level": "l2"}),
                )),
            )
            .unwrap();
        assert_eq!(first, second);
        let fact = store.fact(first).unwrap().unwrap();
        assert_eq!(fact.warrant, Warrant::Structural);
        assert_eq!(fact.origins.len(), 2);
    }

    #[test]
    fn derivation_inputs_preserve_order() {
        let mut store = Store::in_memory().unwrap();
        let a = store
            .insert_fact(
                &FactKey::new("p", vec![Value::U64(1)]),
                Warrant::Structural,
                None,
            )
            .unwrap();
        let b = store
            .insert_fact(
                &FactKey::new("p", vec![Value::U64(2)]),
                Warrant::Structural,
                None,
            )
            .unwrap();
        let c = store
            .insert_fact(
                &FactKey::new("q", vec![Value::U64(3)]),
                Warrant::Structural,
                None,
            )
            .unwrap();
        store.add_derivation(c, RuleId::new(7), &[b, a]).unwrap();
        assert_eq!(
            store.derivation_inputs(c, RuleId::new(7)).unwrap(),
            vec![b, a]
        );
    }
}
