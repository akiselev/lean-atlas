//! A small typed runtime Datalog core for Atlas.
//!
//! The reference evaluator is deliberately simple and acts as executable semantics.
//! The semi-naive evaluator is the production baseline. Expensive Lean semantic checks
//! are not arbitrary predicates inside recursive rules: higher layers batch those checks,
//! insert authoritative oracle facts, and resume logical evaluation.

use atlas_schema::{FactKey, RelationExecution, RuleId, Value, ValueType, Warrant};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

pub type Tuple = Vec<Value>;
pub type Bindings = BTreeMap<String, Value>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RelationDecl {
    pub name: String,
    pub columns: Vec<ValueType>,
    pub execution: RelationExecution,
    pub warrant: Warrant,
}

impl RelationDecl {
    #[must_use]
    pub fn new(name: impl Into<String>, columns: Vec<ValueType>) -> Self {
        Self {
            name: name.into(),
            columns,
            execution: RelationExecution::Derived,
            warrant: Warrant::Structural,
        }
    }

    #[must_use]
    pub const fn execution(mut self, execution: RelationExecution) -> Self {
        self.execution = execution;
        self
    }

    #[must_use]
    pub const fn warrant(mut self, warrant: Warrant) -> Self {
        self.warrant = warrant;
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Term {
    Var(String),
    Const(Value),
}

impl Term {
    #[must_use]
    pub fn var(name: impl Into<String>) -> Self {
        Self::Var(name.into())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Atom {
    pub relation: String,
    pub terms: Vec<Term>,
}

impl Atom {
    #[must_use]
    pub fn new(relation: impl Into<String>, terms: Vec<Term>) -> Self {
        Self {
            relation: relation.into(),
            terms,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Clause {
    Atom(Atom),
    Not(Atom),
    /// Equality is a filter, not a unification/binding primitive. Every variable in an
    /// equality must already be bound by a positive atom in the same rule.
    Eq(Term, Term),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rule {
    pub id: RuleId,
    pub head: Atom,
    pub body: Vec<Clause>,
}

#[derive(Clone, Debug, Default)]
pub struct Program {
    pub relations: BTreeMap<String, RelationDecl>,
    pub rules: Vec<Rule>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidatedProgram {
    strata: BTreeMap<String, usize>,
}

impl ValidatedProgram {
    #[must_use]
    pub fn strata(&self) -> &BTreeMap<String, usize> {
        &self.strata
    }
}

impl Program {
    pub fn relation(&mut self, relation: RelationDecl) -> Result<(), LogicError> {
        if self
            .relations
            .insert(relation.name.clone(), relation.clone())
            .is_some()
        {
            return Err(LogicError::DuplicateRelation(relation.name));
        }
        Ok(())
    }

    pub fn rule(&mut self, rule: Rule) {
        self.rules.push(rule);
    }

    pub fn validate(&self) -> Result<ValidatedProgram, LogicError> {
        for rule in &self.rules {
            let mut variable_types = BTreeMap::<String, ValueType>::new();

            // Relation existence, arity and constant types; positive atoms also establish
            // the type of every runtime-bound variable.
            self.validate_atom(&rule.head, &mut variable_types)?;
            for clause in &rule.body {
                match clause {
                    Clause::Atom(atom) | Clause::Not(atom) => {
                        self.validate_atom(atom, &mut variable_types)?;
                    }
                    Clause::Eq(_, _) => {}
                }
            }

            let positive_vars = rule
                .body
                .iter()
                .filter_map(|clause| match clause {
                    Clause::Atom(atom) => Some(atom),
                    Clause::Not(_) | Clause::Eq(_, _) => None,
                })
                .flat_map(atom_variables)
                .collect::<BTreeSet<_>>();

            ensure_terms_bound(
                rule.id,
                "head",
                rule.head.terms.iter(),
                &positive_vars,
            )?;

            for clause in &rule.body {
                match clause {
                    Clause::Not(atom) => ensure_terms_bound(
                        rule.id,
                        "negation",
                        atom.terms.iter(),
                        &positive_vars,
                    )?,
                    Clause::Eq(left, right) => {
                        ensure_terms_bound(
                            rule.id,
                            "equality",
                            [left, right].into_iter(),
                            &positive_vars,
                        )?;
                        let left_type = term_type(left, &variable_types);
                        let right_type = term_type(right, &variable_types);
                        if left_type != right_type {
                            return Err(LogicError::EqualityType {
                                left: left_type,
                                right: right_type,
                            });
                        }
                    }
                    Clause::Atom(_) => {}
                }
            }
        }

        Ok(ValidatedProgram {
            strata: self.compute_strata()?,
        })
    }

    fn validate_atom(
        &self,
        atom: &Atom,
        variable_types: &mut BTreeMap<String, ValueType>,
    ) -> Result<(), LogicError> {
        let declaration = self
            .relations
            .get(&atom.relation)
            .ok_or_else(|| LogicError::UnknownRelation(atom.relation.clone()))?;
        if declaration.columns.len() != atom.terms.len() {
            return Err(LogicError::Arity {
                relation: atom.relation.clone(),
                expected: declaration.columns.len(),
                found: atom.terms.len(),
            });
        }

        for (term, expected) in atom.terms.iter().zip(&declaration.columns) {
            match term {
                Term::Const(value) if value.value_type() != *expected => {
                    return Err(LogicError::Type {
                        relation: atom.relation.clone(),
                        expected: *expected,
                        found: value.value_type(),
                    });
                }
                Term::Const(_) => {}
                Term::Var(name) => match variable_types.get(name) {
                    Some(found) if found != expected => {
                        return Err(LogicError::VariableType {
                            variable: name.clone(),
                            first: *found,
                            second: *expected,
                        });
                    }
                    Some(_) => {}
                    None => {
                        variable_types.insert(name.clone(), *expected);
                    }
                },
            }
        }
        Ok(())
    }

    fn compute_strata(&self) -> Result<BTreeMap<String, usize>, LogicError> {
        let mut strata = self
            .relations
            .keys()
            .map(|name| (name.clone(), 0usize))
            .collect::<BTreeMap<_, _>>();

        // Positive dependencies require head >= body. Negative dependencies require
        // head > body. Repeated relaxation reaches the least stratification if one exists;
        // a negative cycle increases without bound and is rejected after a finite limit.
        let limit = self
            .relations
            .len()
            .saturating_mul(self.rules.len().max(1))
            .saturating_add(1);
        for round in 0..=limit {
            let mut changed = false;
            for rule in &self.rules {
                let mut needed = 0usize;
                for clause in &rule.body {
                    let dependency = match clause {
                        Clause::Atom(atom) => Some(strata[&atom.relation]),
                        Clause::Not(atom) => Some(strata[&atom.relation].saturating_add(1)),
                        Clause::Eq(_, _) => None,
                    };
                    if let Some(dependency) = dependency {
                        needed = needed.max(dependency);
                    }
                }
                let head = strata
                    .get_mut(&rule.head.relation)
                    .expect("relation existence was validated");
                if *head < needed {
                    *head = needed;
                    changed = true;
                }
            }
            if !changed {
                return Ok(strata);
            }
            if round == limit {
                return Err(LogicError::UnstratifiedNegation);
            }
        }
        unreachable!()
    }
}

fn atom_variables(atom: &Atom) -> impl Iterator<Item = String> + '_ {
    atom.terms.iter().filter_map(|term| match term {
        Term::Var(name) => Some(name.clone()),
        Term::Const(_) => None,
    })
}

fn ensure_terms_bound<'a>(
    rule: RuleId,
    location: &'static str,
    terms: impl IntoIterator<Item = &'a Term>,
    positive_vars: &BTreeSet<String>,
) -> Result<(), LogicError> {
    for term in terms {
        if let Term::Var(variable) = term {
            if !positive_vars.contains(variable) {
                return Err(LogicError::UnsafeVariable {
                    rule,
                    variable: variable.clone(),
                    location,
                });
            }
        }
    }
    Ok(())
}

fn term_type(term: &Term, variable_types: &BTreeMap<String, ValueType>) -> ValueType {
    match term {
        Term::Const(value) => value.value_type(),
        Term::Var(name) => variable_types[name],
    }
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum LogicError {
    #[error("duplicate relation `{0}`")]
    DuplicateRelation(String),
    #[error("unknown relation `{0}`")]
    UnknownRelation(String),
    #[error("relation `{relation}` expects {expected} columns, found {found}")]
    Arity {
        relation: String,
        expected: usize,
        found: usize,
    },
    #[error("relation `{relation}` expects {expected:?}, found {found:?}")]
    Type {
        relation: String,
        expected: ValueType,
        found: ValueType,
    },
    #[error("variable `{variable}` has incompatible types {first:?} and {second:?}")]
    VariableType {
        variable: String,
        first: ValueType,
        second: ValueType,
    },
    #[error("unsafe variable `{variable}` in {location} of rule {rule:?}")]
    UnsafeVariable {
        rule: RuleId,
        variable: String,
        location: &'static str,
    },
    #[error("equality compares incompatible types {left:?} and {right:?}")]
    EqualityType {
        left: ValueType,
        right: ValueType,
    },
    #[error("program contains recursion through negation")]
    UnstratifiedNegation,
    #[error("fact for `{relation}` has arity {found}, expected {expected}")]
    FactArity {
        relation: String,
        expected: usize,
        found: usize,
    },
    #[error("fact for `{relation}` column {column} expects {expected:?}, found {found:?}")]
    FactType {
        relation: String,
        column: usize,
        expected: ValueType,
        found: ValueType,
    },
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Database {
    relations: BTreeMap<String, BTreeSet<Tuple>>,
}

impl Database {
    pub fn insert(&mut self, relation: impl Into<String>, tuple: Tuple) -> bool {
        self.relations
            .entry(relation.into())
            .or_default()
            .insert(tuple)
    }

    #[must_use]
    pub fn tuples(&self, relation: &str) -> Option<&BTreeSet<Tuple>> {
        self.relations.get(relation)
    }

    #[must_use]
    pub fn contains(&self, relation: &str, tuple: &[Value]) -> bool {
        self.relations
            .get(relation)
            .is_some_and(|tuples| tuples.contains(tuple))
    }

    pub fn validate(&self, program: &Program) -> Result<(), LogicError> {
        for (name, tuples) in &self.relations {
            let declaration = program
                .relations
                .get(name)
                .ok_or_else(|| LogicError::UnknownRelation(name.clone()))?;
            for tuple in tuples {
                if tuple.len() != declaration.columns.len() {
                    return Err(LogicError::FactArity {
                        relation: name.clone(),
                        expected: declaration.columns.len(),
                        found: tuple.len(),
                    });
                }
                for (column, (value, expected)) in
                    tuple.iter().zip(&declaration.columns).enumerate()
                {
                    if value.value_type() != *expected {
                        return Err(LogicError::FactType {
                            relation: name.clone(),
                            column,
                            expected: *expected,
                            found: value.value_type(),
                        });
                    }
                }
            }
        }
        Ok(())
    }

    fn difference(&self, stable: &Database) -> Database {
        let mut result = Database::default();
        for (relation, tuples) in &self.relations {
            for tuple in tuples {
                if !stable.contains(relation, tuple) {
                    result.insert(relation.clone(), tuple.clone());
                }
            }
        }
        result
    }

    fn merge_from(&mut self, other: &Database) -> usize {
        let mut added = 0usize;
        for (relation, tuples) in &other.relations {
            for tuple in tuples {
                added += usize::from(self.insert(relation.clone(), tuple.clone()));
            }
        }
        added
    }

    fn is_empty(&self) -> bool {
        self.relations.values().all(BTreeSet::is_empty)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Derivation {
    pub rule: RuleId,
    pub inputs: Vec<FactKey>,
    pub height: u32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Evaluation {
    pub facts: Database,
    pub derivations: BTreeMap<FactKey, Derivation>,
}

pub trait Evaluator {
    fn evaluate(&self, program: &Program, seed: &Database) -> Result<Evaluation, LogicError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ReferenceEvaluator;

impl Evaluator for ReferenceEvaluator {
    fn evaluate(&self, program: &Program, seed: &Database) -> Result<Evaluation, LogicError> {
        let validated = program.validate()?;
        seed.validate(program)?;
        let mut evaluation = Evaluation {
            facts: seed.clone(),
            derivations: BTreeMap::new(),
        };
        let max_stratum = validated.strata.values().copied().max().unwrap_or(0);

        for stratum in 0..=max_stratum {
            loop {
                let mut pending = Vec::new();
                for rule in rules_in_stratum(program, &validated, stratum) {
                    for proof in eval_body(&rule.body, &evaluation.facts, None) {
                        let tuple = instantiate_atom(&rule.head, &proof.bindings);
                        if !evaluation.facts.contains(&rule.head.relation, &tuple) {
                            pending.push((rule.clone(), tuple, proof.inputs));
                        }
                    }
                }
                let mut changed = false;
                for (rule, tuple, inputs) in pending {
                    changed |= insert_derived(&mut evaluation, &rule, tuple, inputs);
                }
                if !changed {
                    break;
                }
            }
        }
        Ok(evaluation)
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SemiNaiveEvaluator;

impl Evaluator for SemiNaiveEvaluator {
    fn evaluate(&self, program: &Program, seed: &Database) -> Result<Evaluation, LogicError> {
        let validated = program.validate()?;
        seed.validate(program)?;
        let mut evaluation = Evaluation {
            facts: seed.clone(),
            derivations: BTreeMap::new(),
        };
        let max_stratum = validated.strata.values().copied().max().unwrap_or(0);

        for stratum in 0..=max_stratum {
            let rules = rules_in_stratum(program, &validated, stratum).collect::<Vec<_>>();

            // Seed the stratum once against the complete stable database. This handles
            // non-recursive rules and creates the first delta for recursive rules.
            let mut first_round = Database::default();
            let mut first_proofs = Vec::new();
            for rule in &rules {
                for proof in eval_body(&rule.body, &evaluation.facts, None) {
                    let tuple = instantiate_atom(&rule.head, &proof.bindings);
                    if !evaluation.facts.contains(&rule.head.relation, &tuple) {
                        first_round.insert(rule.head.relation.clone(), tuple.clone());
                        first_proofs.push(((*rule).clone(), tuple, proof.inputs));
                    }
                }
            }
            let mut delta = first_round.difference(&evaluation.facts);
            evaluation.facts.merge_from(&delta);
            for (rule, tuple, inputs) in first_proofs {
                if delta.contains(&rule.head.relation, &tuple) {
                    record_derivation(&mut evaluation, &rule, tuple, inputs);
                }
            }

            while !delta.is_empty() {
                let mut generated = Database::default();
                let mut proofs = Vec::new();

                for rule in &rules {
                    let recursive_positions = rule
                        .body
                        .iter()
                        .enumerate()
                        .filter_map(|(index, clause)| match clause {
                            Clause::Atom(atom)
                                if validated.strata[&atom.relation] == stratum =>
                            {
                                Some(index)
                            }
                            Clause::Atom(_) | Clause::Not(_) | Clause::Eq(_, _) => None,
                        })
                        .collect::<Vec<_>>();

                    for position in recursive_positions {
                        for proof in
                            eval_body(&rule.body, &evaluation.facts, Some((position, &delta)))
                        {
                            let tuple = instantiate_atom(&rule.head, &proof.bindings);
                            if !evaluation.facts.contains(&rule.head.relation, &tuple) {
                                generated.insert(rule.head.relation.clone(), tuple.clone());
                                proofs.push(((*rule).clone(), tuple, proof.inputs));
                            }
                        }
                    }
                }

                let next = generated.difference(&evaluation.facts);
                if next.is_empty() {
                    break;
                }
                evaluation.facts.merge_from(&next);
                for (rule, tuple, inputs) in proofs {
                    if next.contains(&rule.head.relation, &tuple) {
                        record_derivation(&mut evaluation, &rule, tuple, inputs);
                    }
                }
                delta = next;
            }
        }
        Ok(evaluation)
    }
}

fn rules_in_stratum<'a>(
    program: &'a Program,
    validated: &'a ValidatedProgram,
    stratum: usize,
) -> impl Iterator<Item = &'a Rule> {
    program
        .rules
        .iter()
        .filter(move |rule| validated.strata[&rule.head.relation] == stratum)
}

#[derive(Clone, Debug)]
struct BodyProof {
    bindings: Bindings,
    inputs: Vec<FactKey>,
}

fn eval_body(
    clauses: &[Clause],
    full: &Database,
    delta_override: Option<(usize, &Database)>,
) -> Vec<BodyProof> {
    let mut states = vec![BodyProof {
        bindings: Bindings::new(),
        inputs: Vec::new(),
    }];

    for (clause_index, clause) in clauses.iter().enumerate() {
        match clause {
            Clause::Atom(atom) => {
                let source = match delta_override {
                    Some((position, delta)) if position == clause_index => delta,
                    _ => full,
                };
                let tuples = source.tuples(&atom.relation);
                let mut next = Vec::new();
                for state in states {
                    if let Some(tuples) = tuples {
                        for tuple in tuples {
                            if let Some(bindings) = unify_atom(atom, tuple, &state.bindings) {
                                let mut inputs = state.inputs.clone();
                                inputs.push(FactKey::new(atom.relation.clone(), tuple.clone()));
                                next.push(BodyProof { bindings, inputs });
                            }
                        }
                    }
                }
                states = next;
            }
            Clause::Not(atom) => {
                states.retain(|state| {
                    let tuple = instantiate_atom(atom, &state.bindings);
                    !full.contains(&atom.relation, &tuple)
                });
            }
            Clause::Eq(left, right) => {
                states.retain(|state| {
                    resolve_term(left, &state.bindings) == resolve_term(right, &state.bindings)
                });
            }
        }
        if states.is_empty() {
            break;
        }
    }
    states
}

fn unify_atom(atom: &Atom, tuple: &[Value], bindings: &Bindings) -> Option<Bindings> {
    let mut result = bindings.clone();
    for (term, value) in atom.terms.iter().zip(tuple) {
        match term {
            Term::Const(expected) if expected != value => return None,
            Term::Const(_) => {}
            Term::Var(name) => match result.get(name) {
                Some(bound) if bound != value => return None,
                Some(_) => {}
                None => {
                    result.insert(name.clone(), value.clone());
                }
            },
        }
    }
    Some(result)
}

fn resolve_term(term: &Term, bindings: &Bindings) -> Value {
    match term {
        Term::Const(value) => value.clone(),
        Term::Var(name) => bindings[name].clone(),
    }
}

fn instantiate_atom(atom: &Atom, bindings: &Bindings) -> Tuple {
    atom.terms
        .iter()
        .map(|term| resolve_term(term, bindings))
        .collect()
}

fn insert_derived(
    evaluation: &mut Evaluation,
    rule: &Rule,
    tuple: Tuple,
    inputs: Vec<FactKey>,
) -> bool {
    let changed = evaluation
        .facts
        .insert(rule.head.relation.clone(), tuple.clone());
    if changed {
        record_derivation(evaluation, rule, tuple, inputs);
    }
    changed
}

fn record_derivation(
    evaluation: &mut Evaluation,
    rule: &Rule,
    tuple: Tuple,
    inputs: Vec<FactKey>,
) {
    let height = inputs
        .iter()
        .filter_map(|input| evaluation.derivations.get(input))
        .map(|derivation| derivation.height)
        .max()
        .unwrap_or(0)
        .saturating_add(1);
    let key = FactKey::new(rule.head.relation.clone(), tuple);
    let candidate = Derivation {
        rule: rule.id,
        inputs,
        height,
    };
    match evaluation.derivations.get(&key) {
        Some(existing) if existing.height <= candidate.height => {}
        Some(_) | None => {
            evaluation.derivations.insert(key, candidate);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn transitive_program() -> Program {
        let mut program = Program::default();
        for name in ["edge", "path"] {
            program
                .relation(RelationDecl::new(
                    name,
                    vec![ValueType::U64, ValueType::U64],
                ))
                .unwrap();
        }
        program.rule(Rule {
            id: RuleId::new(1),
            head: Atom::new("path", vec![Term::var("x"), Term::var("y")]),
            body: vec![Clause::Atom(Atom::new(
                "edge",
                vec![Term::var("x"), Term::var("y")],
            ))],
        });
        program.rule(Rule {
            id: RuleId::new(2),
            head: Atom::new("path", vec![Term::var("x"), Term::var("z")]),
            body: vec![
                Clause::Atom(Atom::new(
                    "path",
                    vec![Term::var("x"), Term::var("y")],
                )),
                Clause::Atom(Atom::new(
                    "edge",
                    vec![Term::var("y"), Term::var("z")],
                )),
            ],
        });
        program
    }

    fn transitive_seed() -> Database {
        let mut database = Database::default();
        database.insert("edge", vec![Value::U64(1), Value::U64(2)]);
        database.insert("edge", vec![Value::U64(2), Value::U64(3)]);
        database.insert("edge", vec![Value::U64(3), Value::U64(4)]);
        database
    }

    #[test]
    fn semi_naive_matches_reference_on_recursive_closure() {
        let program = transitive_program();
        let seed = transitive_seed();
        let reference = ReferenceEvaluator.evaluate(&program, &seed).unwrap();
        let optimized = SemiNaiveEvaluator.evaluate(&program, &seed).unwrap();
        assert_eq!(reference.facts, optimized.facts);
        assert!(optimized
            .facts
            .contains("path", &[Value::U64(1), Value::U64(4)]));
    }

    #[test]
    fn negation_is_stratified_above_its_dependency() {
        let mut program = Program::default();
        for name in ["decl", "bad", "good"] {
            program
                .relation(RelationDecl::new(name, vec![ValueType::U64]))
                .unwrap();
        }
        program.rule(Rule {
            id: RuleId::new(1),
            head: Atom::new("good", vec![Term::var("x")]),
            body: vec![
                Clause::Atom(Atom::new("decl", vec![Term::var("x")])),
                Clause::Not(Atom::new("bad", vec![Term::var("x")])),
            ],
        });
        let validated = program.validate().unwrap();
        assert!(validated.strata()["good"] > validated.strata()["bad"]);
    }

    #[test]
    fn recursion_through_negation_is_rejected() {
        let mut program = Program::default();
        for name in ["domain", "p", "q"] {
            program
                .relation(RelationDecl::new(name, vec![ValueType::U64]))
                .unwrap();
        }
        program.rule(Rule {
            id: RuleId::new(1),
            head: Atom::new("p", vec![Term::var("x")]),
            body: vec![
                Clause::Atom(Atom::new("domain", vec![Term::var("x")])),
                Clause::Not(Atom::new("q", vec![Term::var("x")])),
            ],
        });
        program.rule(Rule {
            id: RuleId::new(2),
            head: Atom::new("q", vec![Term::var("x")]),
            body: vec![
                Clause::Atom(Atom::new("domain", vec![Term::var("x")])),
                Clause::Not(Atom::new("p", vec![Term::var("x")])),
            ],
        });
        assert!(matches!(
            program.validate(),
            Err(LogicError::UnstratifiedNegation)
        ));
    }

    #[test]
    fn unbound_negated_variables_are_rejected() {
        let mut program = Program::default();
        program
            .relation(RelationDecl::new("p", vec![ValueType::U64]))
            .unwrap();
        program.rule(Rule {
            id: RuleId::new(1),
            head: Atom::new("p", vec![Term::var("x")]),
            body: vec![Clause::Not(Atom::new("p", vec![Term::var("x")]))],
        });
        assert!(matches!(
            program.validate(),
            Err(LogicError::UnsafeVariable {
                location: "head",
                ..
            })
        ));
    }

    #[test]
    fn equality_is_a_filter_not_an_implicit_binder() {
        let mut program = Program::default();
        for name in ["domain", "same"] {
            program
                .relation(RelationDecl::new(name, vec![ValueType::U64]))
                .unwrap();
        }
        program.rule(Rule {
            id: RuleId::new(1),
            head: Atom::new("same", vec![Term::var("x")]),
            body: vec![
                Clause::Atom(Atom::new("domain", vec![Term::var("x")])),
                Clause::Eq(Term::var("x"), Term::var("y")),
            ],
        });
        assert!(matches!(
            program.validate(),
            Err(LogicError::UnsafeVariable {
                location: "equality",
                ..
            })
        ));
    }

    #[test]
    fn database_fact_types_are_checked() {
        let mut program = Program::default();
        program
            .relation(RelationDecl::new("p", vec![ValueType::U64]))
            .unwrap();
        let mut database = Database::default();
        database.insert("p", vec![Value::Text("wrong".into())]);
        assert!(matches!(
            database.validate(&program),
            Err(LogicError::FactType { .. })
        ));
    }
}
