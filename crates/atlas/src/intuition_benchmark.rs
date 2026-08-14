//! Pre-registered benchmarks for viewpoint/method discovery.
//!
//! A historical benchmark is meaningful only when the Lean/literature corpus itself is
//! frozen to a cutoff that predates the hidden method. This module does not manufacture
//! that condition; it makes the target list and scoring explicit so a cutoff experiment can
//! be reproduced instead of graded by anecdote.

use std::collections::BTreeSet;

use crate::intuition::{Experience, IntuitionIndex};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BenchmarkCase {
    pub id: String,
    pub problem: String,
    /// One or more acceptable method IDs. Historical developments often combine moves and
    /// the benchmark should declare alternatives before the ranking is inspected.
    pub expected_methods: Vec<String>,
    pub top_k: usize,
    /// Optional method IDs that are deliberately hidden from the answer key's positive set
    /// but should not be counted as a success if surfaced through a trivial synonym.
    pub excluded_methods: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BenchmarkResult {
    pub id: String,
    pub problem: String,
    pub hit: bool,
    pub rank: Option<usize>,
    pub reciprocal_rank: f64,
    pub expected_methods: Vec<String>,
    pub top_methods: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BenchmarkReport {
    pub cases: Vec<BenchmarkResult>,
    pub hits: usize,
    pub hit_rate: f64,
    pub mean_reciprocal_rank: f64,
}

impl BenchmarkCase {
    /// JSONL schema:
    ///
    /// ```json
    /// {"id":"rh-spectral","problem":"RiemannHypothesis","expected_methods":["spectralize","introduce-operator"],"top_k":5}
    /// ```
    pub fn from_jsonl(input: &str) -> Result<Vec<Self>, String> {
        let mut out = Vec::new();
        for (i, line) in input.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let obj =
                crate::json::parse(line).map_err(|e| format!("benchmark line {}: {e}", i + 1))?;
            let string = |key: &str| obj.get(key).and_then(|v| v.as_str()).map(str::to_string);
            let list = |key: &str| -> Vec<String> {
                obj.get(key)
                    .and_then(|v| v.as_list())
                    .map(|xs| {
                        xs.iter()
                            .filter_map(|x| x.as_str())
                            .map(str::to_string)
                            .collect()
                    })
                    .unwrap_or_default()
            };
            let id = string("id").ok_or_else(|| format!("benchmark line {} has no `id`", i + 1))?;
            let problem = string("problem")
                .ok_or_else(|| format!("benchmark line {} has no `problem`", i + 1))?;
            let expected_methods = list("expected_methods");
            if expected_methods.is_empty() {
                return Err(format!(
                    "benchmark line {} has no non-empty `expected_methods`",
                    i + 1
                ));
            }
            let top_k = match obj.get("top_k") {
                Some(crate::json::Value::Num(n)) if *n > 0.0 && n.fract() == 0.0 => *n as usize,
                Some(_) => return Err(format!("benchmark line {} has invalid `top_k`", i + 1)),
                None => 10,
            };
            out.push(Self {
                id,
                problem,
                expected_methods,
                top_k,
                excluded_methods: list("excluded_methods"),
            });
        }
        Ok(out)
    }
}

pub fn run_benchmark(
    idx: &IntuitionIndex,
    cases: &[BenchmarkCase],
    experience: Option<&Experience>,
) -> Result<BenchmarkReport, String> {
    let mut results = Vec::new();
    for case in cases {
        let max_rank = idx.methods().len();
        let ranked = idx.candidates(&case.problem, experience, max_rank)?;
        let expected: BTreeSet<_> = case.expected_methods.iter().map(String::as_str).collect();
        let excluded: BTreeSet<_> = case.excluded_methods.iter().map(String::as_str).collect();
        let rank = ranked
            .iter()
            .enumerate()
            .filter(|(_, c)| !excluded.contains(c.method.id))
            .find_map(|(i, c)| expected.contains(c.method.id).then_some(i + 1));
        let hit = rank.is_some_and(|r| r <= case.top_k);
        let reciprocal_rank = rank.map_or(0.0, |r| 1.0 / r as f64);
        let top_methods = ranked
            .iter()
            .filter(|c| !excluded.contains(c.method.id))
            .take(case.top_k)
            .map(|c| c.method.id.to_string())
            .collect();
        results.push(BenchmarkResult {
            id: case.id.clone(),
            problem: case.problem.clone(),
            hit,
            rank,
            reciprocal_rank,
            expected_methods: case.expected_methods.clone(),
            top_methods,
        });
    }
    let hits = results.iter().filter(|r| r.hit).count();
    let n = results.len();
    let hit_rate = if n == 0 { 0.0 } else { hits as f64 / n as f64 };
    let mean_reciprocal_rank = if n == 0 {
        0.0
    } else {
        results.iter().map(|r| r.reciprocal_rank).sum::<f64>() / n as f64
    };
    Ok(BenchmarkReport {
        cases: results,
        hits,
        hit_rate,
        mean_reciprocal_rank,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::Graph;

    fn c(name: &str) -> String {
        format!("c({}:{name},0)", name.len())
    }

    fn stmt(names: &[&str]) -> String {
        let mut it = names.iter();
        let first = c(it.next().unwrap());
        let expr = it.fold(first, |acc, n| format!("a({acc},{})", c(n)));
        format!("atlas-stmt-v1;{expr}")
    }

    fn index() -> IntuitionIndex {
        let stmt = stmt(&["ContinuousLinearMap", "InnerProductSpace", "Flow"]);
        let row = format!(
            "{{\"name\":\"Historical.problem\",\"kind\":\"theorem\",\"module\":\"Historical\",\"stmt\":\"{stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
        );
        let g = Graph::from_jsonl(&row).unwrap();
        IntuitionIndex::build(&g)
    }

    #[test]
    fn parses_a_frozen_answer_key_and_scores_rank() {
        let cases = BenchmarkCase::from_jsonl(
            r#"{"id":"spectral-turn","problem":"Historical.problem","expected_methods":["spectralize"],"top_k":10}"#,
        )
        .unwrap();
        let idx = index();
        let report = run_benchmark(&idx, &cases, None).unwrap();
        assert_eq!(report.cases.len(), 1);
        assert!(report.cases[0].rank.is_some());
        assert!(report.cases[0].hit);
        assert_eq!(report.hits, 1);
    }

    #[test]
    fn a_tight_top_k_can_fail_without_erasing_the_rank() {
        let cases = BenchmarkCase::from_jsonl(
            r#"{"id":"tight","problem":"Historical.problem","expected_methods":["finite-analogue"],"top_k":1}"#,
        )
        .unwrap();
        let idx = index();
        let report = run_benchmark(&idx, &cases, None).unwrap();
        assert!(!report.cases[0].hit);
        // If the method was structurally compatible at all, retain its rank for failure
        // analysis. If it was not compatible, None is the meaningful failure mode.
        assert!(report.cases[0].rank.is_none() || report.cases[0].rank.unwrap() > 1);
    }
}
