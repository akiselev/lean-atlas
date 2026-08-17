use atlas_schema::{FactId, RelationTypeId, Value};
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Term {
    Var(String),
    Const(Value),
}
impl Term {
    pub fn var(v: impl Into<String>) -> Self {
        Self::Var(v.into())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Atom {
    pub relation: RelationTypeId,
    pub terms: Vec<Term>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Literal {
    Pos(Atom),
    Neg(Atom),
    Eq(Term, Term),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rule {
    pub id: String,
    pub head: Atom,
    pub body: Vec<Literal>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Program {
    pub rules: Vec<Rule>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Query {
    pub project: Vec<String>,
    pub body: Vec<Literal>,
    pub limit: Option<usize>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueryRow {
    pub bindings: BTreeMap<String, Value>,
    pub supporting_facts: Vec<FactId>,
}

#[derive(Clone, Copy, Debug)]
pub struct EvalOptions {
    pub max_rounds: usize,
    pub max_results: usize,
}
impl Default for EvalOptions {
    fn default() -> Self {
        Self {
            max_rounds: 128,
            max_results: 10_000,
        }
    }
}
