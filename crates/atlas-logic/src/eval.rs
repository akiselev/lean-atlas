use crate::{Literal, LogicError, Program, Term, bind_atom, eval_term};
use atlas_schema::{Bindings, FactId, FactRow, FactWarrant, RelationTypeId};
use std::collections::{BTreeMap, BTreeSet};

pub(crate) fn body(
    db: &BTreeMap<RelationTypeId, Vec<FactRow>>,
    lits: &[Literal],
) -> Result<Vec<(Bindings, Vec<FactId>)>, LogicError> {
    let mut states = vec![(Bindings::new(), Vec::new())];
    for lit in lits {
        match lit {
            Literal::Pos(a) => {
                let mut n = Vec::new();
                for (b, s) in states {
                    for f in db.get(&a.relation).into_iter().flatten() {
                        if let Some(nb) = bind_atom(&a.terms, &f.args, &b) {
                            let mut ns = s.clone();
                            ns.push(f.id);
                            n.push((nb, ns));
                        }
                    }
                }
                states = n;
            }
            Literal::Neg(a) => states.retain(|(b, _)| {
                !db.get(&a.relation)
                    .into_iter()
                    .flatten()
                    .any(|f| bind_atom(&a.terms, &f.args, b).is_some())
            }),
            Literal::Eq(a, b) => {
                states = states
                    .into_iter()
                    .filter_map(|(mut bs, s)| eq(a, b, &mut bs).then_some((bs, s)))
                    .collect()
            }
        }
        if states.is_empty() {
            break;
        }
    }
    Ok(states)
}

/// Datalog inference is structural at best, and can never strengthen the weakest
/// supporting fact. This makes heuristic/numerical inputs remain heuristic downstream.
pub(crate) fn derived_warrant(
    db: &BTreeMap<RelationTypeId, Vec<FactRow>>,
    support: &[FactId],
) -> FactWarrant {
    let mut warrant = FactWarrant::Structural;
    for id in support {
        if let Some(fact) = db.values().flatten().find(|fact| fact.id == *id) {
            warrant = warrant.weaker(fact.warrant);
        }
    }
    warrant
}

fn eq(a: &Term, b: &Term, bs: &mut Bindings) -> bool {
    match (eval_term(a, bs), eval_term(b, bs)) {
        (Some(x), Some(y)) => x == y,
        (None, Some(v)) => {
            if let Term::Var(n) = a {
                bs.insert(n.clone(), v);
                true
            } else {
                false
            }
        }
        (Some(v), None) => {
            if let Term::Var(n) = b {
                bs.insert(n.clone(), v);
                true
            } else {
                false
            }
        }
        (None, None) => matches!((a,b),(Term::Var(x),Term::Var(y))if x==y),
    }
}

pub(crate) fn validate(p: &Program) -> Result<BTreeMap<RelationTypeId, usize>, LogicError> {
    for r in &p.rules {
        let bound: BTreeSet<_> = r
            .body
            .iter()
            .filter_map(|l| {
                if let Literal::Pos(a) = l {
                    Some(a)
                } else {
                    None
                }
            })
            .flat_map(|a| a.terms.iter())
            .filter_map(|t| {
                if let Term::Var(v) = t {
                    Some(v.clone())
                } else {
                    None
                }
            })
            .collect();
        for t in &r.head.terms {
            if let Term::Var(v) = t {
                if !bound.contains(v) {
                    return Err(LogicError::UnsafeRule(v.clone()));
                }
            }
        }
    }
    let mut s = BTreeMap::new();
    for r in &p.rules {
        s.entry(r.head.relation).or_insert(0);
        for l in &r.body {
            if let Literal::Pos(a) | Literal::Neg(a) = l {
                s.entry(a.relation).or_insert(0);
            }
        }
    }
    let limit = s.len().max(1) * p.rules.len().max(1) + 1;
    for pass in 0..=limit {
        let mut changed = false;
        for r in &p.rules {
            for l in &r.body {
                let (a, d) = match l {
                    Literal::Pos(a) => (a, 0),
                    Literal::Neg(a) => (a, 1),
                    Literal::Eq(..) => continue,
                };
                let need = s[&a.relation] + d;
                if s[&r.head.relation] < need {
                    s.insert(r.head.relation, need);
                    changed = true
                }
            }
        }
        if !changed {
            return Ok(s);
        }
        if pass == limit {
            return Err(LogicError::UnstratifiedNegation);
        }
    }
    unreachable!()
}
