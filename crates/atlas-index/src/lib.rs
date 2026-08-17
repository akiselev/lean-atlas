use atlas_schema::{FactRow, RelationTypeId, Value};
use std::collections::{BTreeMap, BTreeSet};

/// Small deterministic inverted index used by the v2 query planner. Existing specialized
/// skeleton/dependency indexes remain behind the `atlas` compatibility facade and can migrate
/// independently without becoming dependencies of the semantic store.
#[derive(Clone, Debug, Default)]
pub struct FactIndex {
    by_relation: BTreeMap<RelationTypeId, Vec<FactRow>>,
    by_arg: BTreeMap<(RelationTypeId, usize, Value), BTreeSet<usize>>,
}

impl FactIndex {
    pub fn build(facts: impl IntoIterator<Item = FactRow>) -> Self {
        let mut out = Self::default();
        for fact in facts {
            out.insert(fact);
        }
        out
    }

    pub fn insert(&mut self, fact: FactRow) {
        let rows = self.by_relation.entry(fact.relation).or_default();
        let row = rows.len();
        for (position, value) in fact.args.iter().cloned().enumerate() {
            self.by_arg
                .entry((fact.relation, position, value))
                .or_default()
                .insert(row);
        }
        rows.push(fact);
    }

    pub fn relation(&self, relation: RelationTypeId) -> &[FactRow] {
        self.by_relation
            .get(&relation)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    pub fn select(
        &self,
        relation: RelationTypeId,
        position: usize,
        value: &Value,
    ) -> Vec<&FactRow> {
        let Some(rows) = self.by_relation.get(&relation) else {
            return vec![];
        };
        self.by_arg
            .get(&(relation, position, value.clone()))
            .into_iter()
            .flat_map(|ids| ids.iter())
            .filter_map(|i| rows.get(*i))
            .collect()
    }

    pub fn cardinality(&self, relation: RelationTypeId) -> usize {
        self.relation(relation).len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use atlas_schema::{FactId, FactWarrant, Provenance, SourceEvidence};

    #[test]
    fn exact_argument_index_preserves_rows() {
        let f = FactRow {
            id: FactId(1),
            relation: RelationTypeId(9),
            args: vec![Value::Integer(7)],
            warrant: FactWarrant::Structural,
            provenance: Provenance::Source {
                source: "fixture".into(),
                evidence: SourceEvidence::Structural,
            },
        };
        let index = FactIndex::build([f.clone()]);
        assert_eq!(
            index.select(RelationTypeId(9), 0, &Value::Integer(7)),
            vec![&f]
        );
    }
}
