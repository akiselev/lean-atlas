use crate::LogicError;
use atlas_schema::{Bindings, FactRow, RelationTypeId, Value};
use std::collections::BTreeMap;

pub trait FactSource {
    fn scan(
        &self,
        relation: RelationTypeId,
        bindings: &Bindings,
    ) -> Result<Box<dyn Iterator<Item = FactRow> + '_>, LogicError>;
}

#[derive(Clone, Debug, Default)]
pub struct MemoryFacts {
    by_relation: BTreeMap<RelationTypeId, Vec<FactRow>>,
}
impl MemoryFacts {
    pub fn new(facts: impl IntoIterator<Item = FactRow>) -> Self {
        let mut s = Self::default();
        for f in facts {
            s.by_relation.entry(f.relation).or_default().push(f);
        }
        s
    }
    pub fn push(&mut self, f: FactRow) {
        self.by_relation.entry(f.relation).or_default().push(f)
    }
    pub fn rows(&self, r: RelationTypeId) -> &[FactRow] {
        self.by_relation.get(&r).map(Vec::as_slice).unwrap_or(&[])
    }
}
impl FactSource for MemoryFacts {
    fn scan(
        &self,
        r: RelationTypeId,
        _: &Bindings,
    ) -> Result<Box<dyn Iterator<Item = FactRow> + '_>, LogicError> {
        Ok(Box::new(self.rows(r).iter().cloned()))
    }
}

pub(crate) fn bind_atom(
    terms: &[crate::Term],
    args: &[Value],
    seed: &Bindings,
) -> Option<Bindings> {
    if terms.len() != args.len() {
        return None;
    }
    let mut b = seed.clone();
    for (t, v) in terms.iter().zip(args) {
        match t {
            crate::Term::Const(c) if c != v => return None,
            crate::Term::Const(_) => {}
            crate::Term::Var(n) => match b.get(n) {
                Some(x) if x != v => return None,
                Some(_) => {}
                None => {
                    b.insert(n.clone(), v.clone());
                }
            },
        }
    }
    Some(b)
}

pub(crate) fn eval_term(t: &crate::Term, b: &Bindings) -> Option<Value> {
    match t {
        crate::Term::Const(v) => Some(v.clone()),
        crate::Term::Var(n) => b.get(n).cloned(),
    }
}
