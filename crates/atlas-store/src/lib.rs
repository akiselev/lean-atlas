mod migration;

use atlas_schema::{
    FactId, FactRow, FactValidationError, FactWarrant, Provenance, RelationTypeId, SourceEvidence,
    Value,
};
use rusqlite::{Connection, OptionalExtension, params};
use std::path::Path;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum StoreError {
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    InvalidFact(#[from] FactValidationError),
    #[error("unknown warrant {0}")]
    InvalidWarrant(String),
    #[error("fact {0:?} already exists; facts are immutable")]
    DuplicateFact(FactId),
    #[error("derived fact {fact:?} references missing support {support:?}")]
    MissingSupport { fact: FactId, support: FactId },
}

pub struct Store {
    conn: Connection,
}
impl Store {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StoreError> {
        let s = Self {
            conn: Connection::open(path)?,
        };
        s.migrate()?;
        Ok(s)
    }
    pub fn memory() -> Result<Self, StoreError> {
        let s = Self {
            conn: Connection::open_in_memory()?,
        };
        s.migrate()?;
        Ok(s)
    }
    pub fn migrate(&self) -> Result<(), StoreError> {
        self.conn.execute_batch(migration::V1)?;
        Ok(())
    }

    /// Persist one immutable fact. Validation lives at this boundary rather than only
    /// in higher-level relation constructors: every write must prove that its warrant
    /// is no stronger than its provenance and (for derived facts) its weakest input.
    pub fn insert_fact(&mut self, f: &FactRow) -> Result<(), StoreError> {
        self.validate_for_insert(f)?;
        if self.fact(f.id)?.is_some() {
            return Err(StoreError::DuplicateFact(f.id));
        }

        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO facts(id,relation_id,warrant,provenance_json)VALUES(?1,?2,?3,?4)",
            params![
                f.id.0,
                f.relation.0,
                warrant_name(f.warrant),
                serde_json::to_string(&f.provenance)?
            ],
        )?;
        for (i, v) in f.args.iter().enumerate() {
            tx.execute(
                "INSERT INTO fact_args(fact_id,position,value_json)VALUES(?1,?2,?3)",
                params![f.id.0, i as i64, serde_json::to_string(v)?],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    fn validate_for_insert(&self, f: &FactRow) -> Result<(), StoreError> {
        f.validate_intrinsic_warrant()?;
        if let Provenance::Derived { inputs, .. } = &f.provenance {
            let mut supported = FactWarrant::Structural;
            for input in inputs {
                let Some(input_fact) = self.fact(*input)? else {
                    return Err(StoreError::MissingSupport {
                        fact: f.id,
                        support: *input,
                    });
                };
                supported = supported.weaker(input_fact.warrant);
            }
            if f.warrant.is_stronger_than(supported) {
                return Err(StoreError::InvalidFact(FactValidationError {
                    claimed: f.warrant,
                    supported,
                    provenance_kind: "derived support",
                }));
            }
        }
        Ok(())
    }

    pub fn fact(&self, id: FactId) -> Result<Option<FactRow>, StoreError> {
        let h: Option<(u64, String, String)> = self
            .conn
            .query_row(
                "SELECT relation_id,warrant,provenance_json FROM facts WHERE id=?1",
                [id.0],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?;
        let Some((rel, w, p)) = h else {
            return Ok(None);
        };
        Ok(Some(FactRow {
            id,
            relation: RelationTypeId(rel),
            args: self.args(id)?,
            warrant: parse_warrant(&w)?,
            provenance: serde_json::from_str::<Provenance>(&p)?,
        }))
    }

    pub fn scan(&self, rel: RelationTypeId) -> Result<Vec<FactRow>, StoreError> {
        let mut q = self.conn.prepare(
            "SELECT id,warrant,provenance_json FROM facts WHERE relation_id=?1 ORDER BY id",
        )?;
        let h = q
            .query_map([rel.0], |r| {
                Ok((
                    r.get::<_, u64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        h.into_iter()
            .map(|(id, w, p)| {
                Ok(FactRow {
                    id: FactId(id),
                    relation: rel,
                    args: self.args(FactId(id))?,
                    warrant: parse_warrant(&w)?,
                    provenance: serde_json::from_str(&p)?,
                })
            })
            .collect()
    }

    fn args(&self, id: FactId) -> Result<Vec<Value>, StoreError> {
        let mut q = self
            .conn
            .prepare("SELECT value_json FROM fact_args WHERE fact_id=?1 ORDER BY position")?;
        let raw = q
            .query_map([id.0], |r| r.get::<_, String>(0))?
            .collect::<Result<Vec<_>, _>>()?;
        raw.into_iter()
            .map(|x| Ok(serde_json::from_str(&x)?))
            .collect()
    }
}

fn warrant_name(w: FactWarrant) -> &'static str {
    match w {
        FactWarrant::Proved => "proved",
        FactWarrant::Structural => "structural",
        FactWarrant::Asserted => "asserted",
        FactWarrant::Heuristic => "heuristic",
    }
}
fn parse_warrant(w: &str) -> Result<FactWarrant, StoreError> {
    Ok(match w {
        "proved" => FactWarrant::Proved,
        "structural" => FactWarrant::Structural,
        "asserted" => FactWarrant::Asserted,
        "heuristic" => FactWarrant::Heuristic,
        _ => return Err(StoreError::InvalidWarrant(w.into())),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn source_fact(id: u64, warrant: FactWarrant, evidence: SourceEvidence) -> FactRow {
        FactRow {
            id: FactId(id),
            relation: RelationTypeId(2),
            args: vec![Value::Text("x".into())],
            warrant,
            provenance: Provenance::Source {
                source: "fixture".into(),
                evidence,
            },
        }
    }

    #[test]
    fn roundtrip() {
        let mut s = Store::memory().unwrap();
        let f = source_fact(1, FactWarrant::Structural, SourceEvidence::Structural);
        s.insert_fact(&f).unwrap();
        assert_eq!(s.fact(f.id).unwrap(), Some(f));
    }

    #[test]
    fn rejects_candidate_promoted_to_proved() {
        let mut s = Store::memory().unwrap();
        let f = FactRow {
            id: FactId(100),
            relation: RelationTypeId(4),
            args: vec![],
            warrant: FactWarrant::Proved,
            provenance: Provenance::Candidate {
                method: "numerical_fit".into(),
                evidence: vec![],
            },
        };
        assert!(matches!(s.insert_fact(&f), Err(StoreError::InvalidFact(_))));
    }

    #[test]
    fn rejects_numerical_source_promoted_to_proved() {
        let mut s = Store::memory().unwrap();
        let f = source_fact(101, FactWarrant::Proved, SourceEvidence::Numerical);
        assert!(matches!(s.insert_fact(&f), Err(StoreError::InvalidFact(_))));
    }

    #[test]
    fn fact_ids_are_immutable() {
        let mut s = Store::memory().unwrap();
        let original = source_fact(101, FactWarrant::Heuristic, SourceEvidence::Numerical);
        s.insert_fact(&original).unwrap();
        let replacement = source_fact(101, FactWarrant::Proved, SourceEvidence::Formal);
        assert!(matches!(
            s.insert_fact(&replacement),
            Err(StoreError::DuplicateFact(FactId(101)))
        ));
        assert_eq!(s.fact(FactId(101)).unwrap(), Some(original));
    }

    #[test]
    fn derived_warrant_cannot_exceed_weakest_input() {
        let mut s = Store::memory().unwrap();
        let input = source_fact(1, FactWarrant::Heuristic, SourceEvidence::Numerical);
        s.insert_fact(&input).unwrap();
        let derived = FactRow {
            id: FactId(2),
            relation: RelationTypeId(3),
            args: vec![],
            warrant: FactWarrant::Structural,
            provenance: Provenance::Derived {
                rule: "r".into(),
                inputs: vec![input.id],
            },
        };
        assert!(matches!(
            s.insert_fact(&derived),
            Err(StoreError::InvalidFact(_))
        ));
    }
}
