use crate::{EvalOptions, FactSource, Literal, LogicError, Program, Query, QueryRow, eval};
use atlas_schema::{Bindings, FactId, FactRow, FactWarrant, Provenance, RelationTypeId, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Evaluation {
    pub facts: Vec<FactRow>,
    pub rows: Vec<QueryRow>,
}

pub fn evaluate_reference<S: FactSource>(
    source: &S,
    program: &Program,
    query: &Query,
    opts: EvalOptions,
) -> Result<Evaluation, LogicError> {
    let strata = eval::validate(program)?;
    let mut rels = BTreeSet::new();
    for r in &program.rules {
        rels.insert(r.head.relation);
        for l in &r.body {
            if let Literal::Pos(a) | Literal::Neg(a) = l {
                rels.insert(a.relation);
            }
        }
    }
    for l in &query.body {
        if let Literal::Pos(a) | Literal::Neg(a) = l {
            rels.insert(a.relation);
        }
    }
    let mut db: BTreeMap<RelationTypeId, Vec<FactRow>> = BTreeMap::new();
    let empty = Bindings::new();
    for r in rels {
        db.entry(r).or_default().extend(source.scan(r, &empty)?)
    }
    let mut seen: BTreeSet<(RelationTypeId, Vec<Value>)> = db
        .iter()
        .flat_map(|(r, fs)| fs.iter().map(move |f| (*r, f.args.clone())))
        .collect();
    let mut next = db.values().flatten().map(|f| f.id.0).max().unwrap_or(0) + 1;
    for stratum in 0..=strata.values().copied().max().unwrap_or(0) {
        for round in 0..opts.max_rounds {
            let mut added = 0;
            for rule in program
                .rules
                .iter()
                .filter(|r| strata.get(&r.head.relation).copied().unwrap_or(0) == stratum)
            {
                for (b, support) in eval::body(&db, &rule.body)? {
                    let Some(args) = rule
                        .head
                        .terms
                        .iter()
                        .map(|t| crate::source::eval_term(t, &b))
                        .collect::<Option<Vec<_>>>()
                    else {
                        continue;
                    };
                    if seen.insert((rule.head.relation, args.clone())) {
                        let f = FactRow {
                            id: FactId(next),
                            relation: rule.head.relation,
                            args,
                            warrant: FactWarrant::Structural,
                            provenance: Provenance::Derived {
                                rule: rule.id.clone(),
                                inputs: support,
                            },
                        };
                        next += 1;
                        db.entry(f.relation).or_default().push(f);
                        added += 1;
                    }
                }
            }
            if added == 0 {
                break;
            }
            if round + 1 == opts.max_rounds {
                return Err(LogicError::RecursionLimit(opts.max_rounds));
            }
        }
    }
    let mut rows = eval::body(&db, &query.body)?
        .into_iter()
        .map(|(b, support)| QueryRow {
            bindings: query
                .project
                .iter()
                .filter_map(|n| b.get(n).cloned().map(|v| (n.clone(), v)))
                .collect(),
            supporting_facts: support,
        })
        .collect::<Vec<_>>();
    rows.sort_by(|a, b| a.bindings.cmp(&b.bindings));
    rows.dedup();
    rows.truncate(
        query
            .limit
            .unwrap_or(opts.max_results)
            .min(opts.max_results),
    );
    let mut facts = db.into_values().flatten().collect::<Vec<_>>();
    facts.sort_by_key(|f| f.id);
    Ok(Evaluation { facts, rows })
}
