use crate::{EvalOptions, FactSource, Literal, LogicError, Program, Query, QueryRow, eval};
use atlas_schema::{
    Bindings, Derivation, DerivationId, FactId, FactRow, FactWarrant, Provenance, RelationTypeId,
};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Evaluation {
    pub facts: Vec<FactRow>,
    pub rows: Vec<QueryRow>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DerivationExplanation {
    pub derivation: Derivation,
    pub warrant: FactWarrant,
    pub supporting_facts: Vec<FactRow>,
    pub missing_inputs: Vec<FactId>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FactExplanation {
    pub fact: FactRow,
    pub derivations: Vec<DerivationExplanation>,
    pub strongest_derivation: Option<DerivationId>,
}

impl Evaluation {
    /// Explain one fact without collapsing alternative derivations into a false conjunction.
    /// Each returned derivation is one OR branch; its `supporting_facts` are the AND inputs for
    /// that branch. Callers can recursively explain those fact IDs as needed.
    pub fn explain(&self, id: FactId) -> Option<FactExplanation> {
        let fact = self.facts.iter().find(|fact| fact.id == id)?.clone();
        let by_id = self
            .facts
            .iter()
            .map(|fact| (fact.id, fact))
            .collect::<BTreeMap<_, _>>();
        let warrants = self
            .facts
            .iter()
            .map(|fact| (fact.id, fact.warrant))
            .collect::<BTreeMap<_, _>>();

        let mut derivations = Vec::new();
        for derivation in fact.provenance.derivations() {
            let mut supporting_facts = Vec::new();
            let mut missing_inputs = Vec::new();
            for input in &derivation.inputs {
                match by_id.get(input) {
                    Some(input_fact) => supporting_facts.push((*input_fact).clone()),
                    None => missing_inputs.push(*input),
                }
            }
            derivations.push(DerivationExplanation {
                warrant: eval::derivation_warrant(&warrants, &derivation),
                derivation,
                supporting_facts,
                missing_inputs,
            });
        }

        // `Provenance::derivations` is canonically ordered. Keep the first derivation on ties so
        // the selected strongest alternative is deterministic without erasing weaker branches.
        let mut strongest_derivation = None;
        let mut strongest_warrant = FactWarrant::Heuristic;
        for explanation in &derivations {
            if strongest_derivation.is_none()
                || explanation.warrant.is_stronger_than(strongest_warrant)
            {
                strongest_warrant = explanation.warrant;
                strongest_derivation = Some(explanation.derivation.id.clone());
            }
        }

        Some(FactExplanation {
            fact,
            derivations,
            strongest_derivation,
        })
    }
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
    eval::sort_db(&mut db);

    let mut seen: BTreeSet<eval::FactKey> = db
        .iter()
        .flat_map(|(r, fs)| fs.iter().map(move |f| (*r, f.args.clone())))
        .collect();
    let mut derived = eval::derived_index(&db);
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
                    let key = (rule.head.relation, args.clone());
                    let derivation = Derivation::new(rule.id.clone(), support);
                    if let Some(id) = derived.get(&key).copied() {
                        eval::attach_derivation(&mut db, id, derivation);
                        continue;
                    }
                    if seen.insert(key.clone()) {
                        let f = FactRow {
                            id: FactId(next),
                            relation: rule.head.relation,
                            args,
                            warrant: FactWarrant::Heuristic,
                            provenance: Provenance::derived(
                                derivation.rule.clone(),
                                derivation.inputs.clone(),
                            ),
                        };
                        next += 1;
                        derived.insert(key, f.id);
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

    eval::recompute_derived_warrants(&mut db);
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
