//! A small typed runtime Datalog core for Atlas.
//!
//! The reference evaluator is intentionally simple and serves as executable semantics.
//! The semi-naive evaluator is the production baseline. Expensive Lean semantic checks are
//! not arbitrary predicates in this engine; later layers batch them as authoritative fact
//! producers between logic rounds.

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

impl Program {
    pub fn relation(&mut self, relation: RelationDecl) -> Result<(), LogicError> {
        if self.relations.insert(relation.name.clone(), relation.clone()).is_some() {
            return Err(LogicError::DuplicateRelation(relation.name));
        }
        Ok(())
    }

    pub fn rule(&mut self, rule: Rule) {
        self.rules.push(rule);
    }

    pub fn validate(&self) -> Result<ValidatedProgram<'_>, LogicError> {
        let mut variable_types: BTreeMap<(usize, String), ValueType> = BTreeMap::new();
        for (rule_index, rule) in self.rules.iter().enumerate() {
            self.validate_atom(&rule.head, rule_index, &mut variable_types)?;
            for clause in &rule.body {
                match clause {
                    Clause::Atom(atom) | Clause::Not(atom) => {
                        self.validate_atom(atom, rule_index, &mut variable_types)?;
                    }
                    Clause::Eq(left, right) => {
                        validate_equality(left, right, rule_index, &mut variable_types)?;
                    }
                }
            }
            let positive_vars = rule
                .body
                .iter()
                .filter_map(|clause| match clause {
                    Clause::Atom(atom) => Some(atom),
                    _ => None,
                })
                .flat_map(atom_variables)
                .collect::<BTreeSet<_>>();
            for variable in atom_variables(&rule.head) {
                if !positive_vars.contains(&variable) {
                    return Err(LogicError::UnsafeVariable {
                        rule: rule.id,
                        variable,
                        location: "head",
                    });
                }
            }
            for atom in rule.body.iter().filter_map(|clause| match clause {
                Clause::Not(atom) => Some(atom),
                _ => None,
            }) {
                for variable in atom_variables(atom) {
                    if !positive_vars.contains(&variable) {
                        return Err(LogicError::UnsafeVariable {
                            rule: rule.id,
                            variable,
                            location: "negation",
                        });
                    }
                }
            }
        }
        let strata = self.compute_strata()?;
        Ok(ValidatedProgram { program: self, strata })
    }

    fn validate_atom(
        &self,
        atom: &Atom,
        rule_index: usize,
        variable_types: &mut BTreeMap<(usize, String), ValueType>,
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
                Term::Var(name) => {
                    let key = (rule_index, name.clone());
                    if let Some(found) = variable_types.get(&key) {
                        if found != expected {
                            return Err(LogicError::VariableType {
                                variable: name.clone(),
                                first: *found,
                                second: *expected,
                            });
                        }
                    } else {
                        variable_types.insert(key, *expected);
                    }
                }
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
        let limit = self.relations.len().saturating_mul(self.rules.len().max(1)) + 1;
        for round in 0..=limit {
            let mut changed = false;
            for rule in &self.rules {
                let mut needed = 0usize;
                for clause in &rule.body {
                    let (atom, negative) = match clause {
                        Clause::Atom(atom) => (Some(atom), false),
                        Clause::Not(atom) => (Some(atom), true),
                        Clause::Eq(_, _) => (None, false),
                    };
                    if let Some(atom) = atom {
                        let dependency = strata[&atom.relation] + usize::from(negative);
                        needed = needed.max(dependency);
                    }
                }
                let head = strata.get_mut(&rule.head.relation).expect("validated relation");
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

fn validate_equality(
    left: &Term,
    right: &Term,
    rule_index: usize,
    variable_types: &mut BTreeMap<(usize, String), ValueType>,
) -> Result<(), LogicError> {
    let left_type = term_known_type(left, rule_index, variable_types);
    let right_type = term_known_type(right, rule_index, variable_types);
    if let (Some(left_type), Some(right_type)) = (left_type, right_type) {
        if left_type != right_type {
            return Err(LogicError::EqualityType { left: left_type, right: right_type });
        }
    }
    Ok(())
}

fn term_known_type(
    term: &Term,
    rule_index: usize,
    variable_types: &BTreeMap<(usize, String), ValueType>,
) -> Option<ValueType> {
    match term {
        Term::Const(value) => Some(value.value_type()),
        Term::Var(name) => variable_types.get(&(rule_index, name.clone())).copied(),
    }
}

fn atom_variables(atom: &Atom) -> impl Iterator<Item = String> + '_ {
    atom.terms.iter().filter_map(|term| match term {
        Term::Var(name) => Some(name.clone()),
        Term::Const(_) => None,
    })
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum LogicError {
    #[error("duplicate relation `{0}`")]
    DuplicateRelation(String),
    #[error("unknown relation `{0}`")]
    UnknownRelation(String),
    #[error("relation `{relation}` expects {expected} columns, found {found}")]
    Arity { relation: String, expected: usize, found: usize },
    #[error("relation `{relation}` expects {expected:?}, found {found:?}")]
    Type { relation: String, expected: ValueType, found: ValueType },
    #[error("variable `{variable}` has incompatible types {first:?} and {second:?}")]
    VariableType { variable: String, first: ValueType, second: ValueType },
    #[error("unsafe variable `{variable}` in {location} of rule {rule:?}")]
    UnsafeVariable { rule: RuleId, variable: String, location: &'static str },
    #[error("equality compares incompatible types {left:?} and {right:?}")]
    EqualityType { left: ValueType, right: ValueType },
    #[error("program contains recursion through negation")]
    UnstratifiedNegation,
    #[error("fact for `{relation}` has arity {found}, expected {expected}")]
    FactArity { relation: String, expected: usize, found: usize },
    #[error("fact for `{relation}` column {column} expects {expected:?}, found {found:?}")]
    FactType { relation: String, column: usize, expected: ValueType, found: ValueType },
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Database {
    relations: BTreeMap<String, BTreeSet<Tuple>>,
}

impl Database {
    pub fn insert(&mut self, relation: impl Into<String>, tuple: Tuple) -> bool {
        self.relations.entry(relation.into()).or_default().insert(tuple)
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
                for (column, (value, expected)) in tuple.iter().zip(&declaration.columns).enumerate() {
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

    fn merge_from(&mut self, other: &Database) -> usize {
        let mut added = 0;
        for (relation, tuples) in &other.relations {
            for tuple in tuples {
                added += usize::from(self.insert(relation.clone(), tuple.clone()));
            }
        }
        added
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

pub struct ValidatedProgram<'a> {
    program: &'a Program,
    strata: BTreeMap<String, usize>,
}

impl ValidatedProgram<'_> {
    #[must_use]
    pub fn strata(&self) -> &BTreeMap<String, usize> {
        &self.strata
    }
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
                let mut additions = Vec::new();
                for rule in program
                    .rules
                    .iter()
                    .filter(|rule| validated.strata[&rule.head.relation] == stratum)
                {
                    for proof in eval_body(&rule.body, &evaluation.facts, None) {
                        let tuple = instantiate_head(&rule.head, &proof.bindings);
                        if !evaluation.facts.contains(&rule.head.relation, &tuple) {
                            additions.push((rule, tuple, proof.inputs));
                        }
                    }
                }
                if additions.is_empty() {
                    break;
                }
                let mut changed = false;
                for (rule, tuple, inputs) in additions {
                    changed |= insert_derived(&mut evaluation, rule, tuple, inputs);
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
            // The first round uses the complete stable database as its delta so lower-stratum
            // facts seed this stratum. Subsequent rounds use only newly derived tuples.
            let mut delta = evaluation.facts.clone();
            loop {
                let mut next = Database::default();
                let mut pending_derivations = Vec::new();
                for rule in program
                    .rules
                    .iter()
                    .filter(|rule| validated.strata[&rule.head.relation] == stratum)
                {
                    let positive_positions = rule
                        .body
                        .iter()
                        .enumerate()
                        .filter_map(|(index, clause)| matches!(clause, Clause::Atom(_)).then_some(index))
                        .collect::<Vec<_>>();
                    if positive_positions.is_empty() {
                        for proof in eval_body(&rule.body, &evaluation.facts, None) {
                            let tuple = instantiate_head(&rule.head, &proof.bindings);
                            if !evaluation.facts.contains(&rule.head.relation, &tuple) {
                                next.insert(rule.head.relation.clone(), tuple.clone());
                                pending_derivations.push((rule.clone(), tuple, proof.inputs));
                            }
                        }
                    } else {
                        for delta_position in positive_positions {
                            for proof in eval_body(
                                &rule.body,
                                &evaluation.facts,
                                Some((delta_position, &delta)),
                            ) {
                                let tuple = instantiate_head(&rule.head, &proof.bindings);
                                if !evaluation.facts.contains(&rule.head.relation, &tuple) {
                                    next.insert(rule.head.relation.clone(), tuple.clone());
                                    pending_derivations.push((rule.clone(), tuple, proof.inputs));
                                }
                            }
                        }
                    }
                }
                if next.relations.values().all(BTreeSet::is_empty) {
                    break;
                }
                let before = evaluation.facts.clone();
                let added = evaluation.facts.merge_from(&next);
                for (rule, tuple, inputs) in pending_derivations {
                    if !before.contains(&rule.head.relation, &tuple) {
                        record_derivation(&mut evaluation, &rule, tuple, inputs);
                    }
                }
                if added == 0 {
                    break;
                }
                delta = next;
            }
        }
        Ok(evaluation)
    }
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
                let source = if delta_override.is_some_and(|(index, _)| index == clause_index) {
                    delta_override.expect("checked above").1
                } else {
                    full
                };
                let tuples = source.tuples(&atom.relation).cloned().unwrap_or_default();
                let mut next = Vec::new();
                for state in states {
                    for tuple in &tuples {
                        if let Some(bindings) = unify_atom(atom, tuple, &state.bindings) {
                            let mut inputs = state.inputs.clone();
                            inputs.push(FactKey::new(atom.relation.clone(), tuple.clone()));
                            next.push(BodyProof { bindings, inputs });
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
                states.retain(|state| resolve_term(left, &state.bindings) == resolve_term(right, &state.bindings));
            }
        }
        if states.is_empty() {
            break;
        }
    }
    states
}

fn unify_atom(atom: &Atom, tuple: &[Value], bindings: &Bindings) -> Option<Bindings> {
    let mut out = bindings.clone();
    for (term, value) in atom.terms.iter().zip(tuple) {
        match term {
            Term::Const(expected) if expected != value => return None,
            Term::Const(_) => {}
            Term::Var(name) => match out.get(name) {
                Some(bound) if bound != value => return None,
                Some(_) => {}
                None => {
                    out.insert(name.clone(), value.clone());
                }
            },
        }
    }
    Some(out)
}

fn resolve_term(term: &Term, bindings: &Bindings) -> Option<Value> {
    match term {
        Term::Const(value) => Some(value.clone()),
        Term::Var(name) => bindings.get(name).cloned(),
    }
}

fn instantiate_atom(atom: &Atom, bindings: &Bindings) -> Tuple {
    atom.terms
        .iter()
        .map(|term| resolve_term(term, bindings).expect("validated safe rule"))
        .collect()
}

fn instantiate_head(head: &Atom, bindings: &Bindings) -> Tuple {
    instantiate_atom(head, bindings)
}

fn insert_derived(evaluation: &mut Evaluation, rule: &Rule, tuple: Tuple, inputs: Vec<FactKey>) -> bool {
    let changed = evaluation.facts.insert(rule.head.relation.clone(), tuple.clone());
    if changed {
        record_derivation(evaluation, rule, tuple, inputs);
    }
    changed
}

fn record_derivation(evaluation: &mut Evaluation, rule: &Rule, tuple: Tuple, inputs: Vec<FactKey>) {
    let height = 1 + inputs
        .iter()
        .filter_map(|input| evaluation.derivations.get(input).map(|derivation| derivation.height))
        .max()
        .unwrap_or(0);
    let key = FactKey::new(rule.head.relation.clone(), tuple);
    let candidate = Derivation {
        rule: rule.id,
        inputs,
        height,
    };
    match evaluation.derivations.get(&key) {
        Some(existing) if existing.height <= candidate.height => {}
        _ => {
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
                .relation(RelationDecl::new(name, vec![ValueType::U64, ValueType::U64]))
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
                Clause::Atom(Atom::new("path", vec![Term::var("x"), Term::var("y")])),
                Clause::Atom(Atom::new("edge", vec![Term::var("y"), Term::var("z")])),
            ],
        });
        program
    }

    fn seed() -> Database {
        let mut db = Database::default();
        db.insert("edge", vec![Value::U64(1), Value::U64(2)]);
        db.insert("edge", vec![Value::U64(2), Value::U64(3)]);
        db.insert("edge", vec![Value::U64(3), Value::U64(4)]);
        db
    }

    #[test]
    fn semi_naive_matches_reference_on_recursive_closure() {
        let program = transitive_program();
        let seed = seed();
        let reference = ReferenceEvaluator.evaluate(&program, &seed).unwrap();
        let optimized = SemiNaiveEvaluator.evaluate(&program, &seed).unwrap();
        assert_eq!(reference.facts, optimized.facts);
        assert!(optimized.facts.contains("path", &[Value::U64(1), Value::U64(4)]));
    }

    #[test]
    fn negation_is_stratified() {
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
        assert_eq!(program.validate().unwrap_err(), LogicError::UnstratifiedNegation);
    }

    #[test]
    fn unsafe_negated_variables_are_rejected() {
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
            Err(LogicError::UnsafeVariable { location: "head", .. })
        ));
    }
}
