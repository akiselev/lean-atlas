//! Explicit search over changes of mathematical viewpoint.
//!
//! A declaration is not treated as one immutable problem representation. Starting from its
//! extracted affordances, methods are typed research actions that expose additional
//! affordances while accumulating obligations and known information loss. The resulting
//! graph is a search space over *representations*, not a proof graph.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet, HashMap};

use crate::intuition::{Affordance, Experience, IntuitionIndex, MethodCandidate, MethodSpec};

#[derive(Clone, Debug, PartialEq)]
pub struct ViewpointNode {
    pub id: usize,
    pub declaration: String,
    pub depth: usize,
    pub path: Vec<String>,
    pub affordances: BTreeSet<Affordance>,
    pub method_breadth: usize,
    /// Search-policy value, never a probability that a theorem is true.
    pub score: f64,
    pub obligations: Vec<String>,
    pub losses: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ViewpointEdge {
    pub from: usize,
    pub to: usize,
    pub method: String,
    pub family: String,
    pub compatibility: f64,
    pub novelty: f64,
    pub breadth_gain: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ViewpointGraph {
    pub root: usize,
    pub nodes: Vec<ViewpointNode>,
    pub edges: Vec<ViewpointEdge>,
}

impl ViewpointGraph {
    pub fn node(&self, id: usize) -> Option<&ViewpointNode> {
        self.nodes.get(id)
    }

    pub fn leaves(&self) -> Vec<&ViewpointNode> {
        let outgoing: BTreeSet<_> = self.edges.iter().map(|e| e.from).collect();
        self.nodes
            .iter()
            .filter(|n| !outgoing.contains(&n.id))
            .collect()
    }

    pub fn best(&self, top: usize) -> Vec<&ViewpointNode> {
        let mut nodes: Vec<_> = self.nodes.iter().filter(|n| n.id != self.root).collect();
        nodes.sort_by(|a, b| {
            cmp_f64(b.score, a.score)
                .then(b.method_breadth.cmp(&a.method_breadth))
                .then(a.path.cmp(&b.path))
        });
        nodes.truncate(top);
        nodes
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ExploreOptions {
    pub max_depth: usize,
    pub beam_width: usize,
    pub max_nodes: usize,
    pub min_compatibility: f64,
    pub family_penalty: f64,
}

impl Default for ExploreOptions {
    fn default() -> Self {
        Self {
            max_depth: 3,
            beam_width: 12,
            max_nodes: 256,
            min_compatibility: 0.25,
            family_penalty: 0.68,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ParetoMethod {
    pub candidate: MethodCandidate,
    pub strengths: Vec<&'static str>,
}

/// Multi-objective alternative to the scalar intuition score. A method survives iff no
/// other method is at least as good on every objective and strictly better on one.
pub fn pareto_methods(
    idx: &IntuitionIndex,
    declaration: &str,
    experience: Option<&Experience>,
) -> Result<Vec<ParetoMethod>, String> {
    let all = idx.candidates(declaration, experience, idx.methods().len())?;
    let mut out = Vec::new();
    for (i, a) in all.iter().enumerate() {
        if all
            .iter()
            .enumerate()
            .any(|(j, b)| i != j && dominates(b, a))
        {
            continue;
        }
        let mut strengths = Vec::new();
        if all.iter().any(|b| a.compatibility > b.compatibility) {
            strengths.push("compatibility");
        }
        if all.iter().any(|b| a.domain_distance > b.domain_distance) {
            strengths.push("domain-distance");
        }
        if all.iter().any(|b| a.bridge_value > b.bridge_value) {
            strengths.push("bridge-value");
        }
        if all.iter().any(|b| a.novelty > b.novelty) {
            strengths.push("novelty-of-view");
        }
        if all.iter().any(|b| a.breadth_gain > b.breadth_gain) {
            strengths.push("representation-breadth");
        }
        out.push(ParetoMethod {
            candidate: a.clone(),
            strengths,
        });
    }
    out.sort_by(|a, b| {
        cmp_f64(b.candidate.score, a.candidate.score)
            .then(a.candidate.method.id.cmp(b.candidate.method.id))
    });
    Ok(out)
}

fn dominates(a: &MethodCandidate, b: &MethodCandidate) -> bool {
    let ge = a.compatibility >= b.compatibility
        && a.domain_distance >= b.domain_distance
        && a.bridge_value >= b.bridge_value
        && a.novelty >= b.novelty
        && a.breadth_gain >= b.breadth_gain
        && a.experience_factor >= b.experience_factor;
    let gt = a.compatibility > b.compatibility
        || a.domain_distance > b.domain_distance
        || a.bridge_value > b.bridge_value
        || a.novelty > b.novelty
        || a.breadth_gain > b.breadth_gain
        || a.experience_factor > b.experience_factor;
    ge && gt
}

/// Explore sequences of representation changes. A method application is simulated only at
/// the affordance level: `unlocks` become visible in the child node, while proof obligations
/// and losses are accumulated. This is weaker than asserting that the transformation exists
/// for the mathematical object.
pub fn explore_viewpoints(
    idx: &IntuitionIndex,
    declaration: &str,
    experience: Option<&Experience>,
    opts: &ExploreOptions,
) -> Result<ViewpointGraph, String> {
    let profile = idx
        .profile(declaration)
        .ok_or_else(|| format!("`{declaration}` has no encoded viewpoint profile"))?;
    let root_affordances = profile.affordances();
    let root = ViewpointNode {
        id: 0,
        declaration: declaration.to_string(),
        depth: 0,
        path: Vec::new(),
        method_breadth: method_breadth(idx.methods(), &root_affordances),
        affordances: root_affordances,
        score: 1.0,
        obligations: Vec::new(),
        losses: Vec::new(),
    };
    let mut graph = ViewpointGraph {
        root: 0,
        nodes: vec![root],
        edges: Vec::new(),
    };
    let mut seen: BTreeMap<Vec<Affordance>, usize> = BTreeMap::new();
    seen.insert(state_key(&graph.nodes[0].affordances), 0);

    let root_candidates = idx.candidates(declaration, experience, idx.methods().len())?;
    let root_scores: HashMap<&str, f64> = root_candidates
        .iter()
        .map(|c| (c.method.id, c.base_score))
        .collect();

    let mut beam = vec![0usize];
    for depth in 0..opts.max_depth {
        if graph.nodes.len() >= opts.max_nodes {
            break;
        }
        let mut proposals = Vec::new();
        for &parent_id in &beam {
            let parent = &graph.nodes[parent_id];
            for method in idx.methods() {
                let fit = compatibility(&parent.affordances, method);
                if fit < opts.min_compatibility {
                    continue;
                }
                let added: Vec<_> = method
                    .unlocks
                    .iter()
                    .copied()
                    .filter(|a| !parent.affordances.contains(a))
                    .collect();
                if added.is_empty() {
                    continue;
                }
                let novelty = added.len() as f64 / method.unlocks.len().max(1) as f64;
                let mut affordances = parent.affordances.clone();
                affordances.extend(added);
                let breadth = method_breadth(idx.methods(), &affordances);
                let breadth_gain = breadth.saturating_sub(parent.method_breadth);
                let step = if depth == 0 {
                    root_scores
                        .get(method.id)
                        .copied()
                        .unwrap_or_else(|| local_step_score(fit, novelty, breadth_gain))
                } else {
                    local_step_score(fit, novelty, breadth_gain)
                };
                proposals.push(Proposal {
                    parent: parent_id,
                    method: method.clone(),
                    affordances,
                    compatibility: fit,
                    novelty,
                    breadth,
                    breadth_gain,
                    score: parent.score * step * 0.94_f64.powi(depth as i32),
                });
            }
        }

        proposals.sort_by(|a, b| {
            cmp_f64(b.score, a.score)
                .then(a.method.family.cmp(b.method.family))
                .then(a.method.id.cmp(b.method.id))
        });
        let chosen = diversify(proposals, opts.beam_width, opts.family_penalty);
        let mut next_beam = Vec::new();

        for proposal in chosen {
            if graph.nodes.len() >= opts.max_nodes {
                break;
            }
            let key = state_key(&proposal.affordances);
            let child_id = if let Some(&existing) = seen.get(&key) {
                if proposal.score > graph.nodes[existing].score {
                    // Clone parent metadata before mutating the vector. Besides satisfying
                    // Rust's aliasing rules, this makes the update atomic at the conceptual
                    // level: the child receives one complete best-known path.
                    let parent_path = graph.nodes[proposal.parent].path.clone();
                    let parent_obligations = graph.nodes[proposal.parent].obligations.clone();
                    let parent_losses = graph.nodes[proposal.parent].losses.clone();
                    let child = &mut graph.nodes[existing];
                    child.score = proposal.score;
                    child.path = append_one(&parent_path, proposal.method.id);
                    child.obligations = append_many(
                        &parent_obligations,
                        proposal.method.obligations.iter().copied(),
                    );
                    child.losses =
                        append_many(&parent_losses, proposal.method.losses.iter().copied());
                }
                existing
            } else {
                let parent = graph.nodes[proposal.parent].clone();
                let id = graph.nodes.len();
                graph.nodes.push(ViewpointNode {
                    id,
                    declaration: declaration.to_string(),
                    depth: parent.depth + 1,
                    path: append_one(&parent.path, proposal.method.id),
                    affordances: proposal.affordances.clone(),
                    method_breadth: proposal.breadth,
                    score: proposal.score,
                    obligations: append_many(
                        &parent.obligations,
                        proposal.method.obligations.iter().copied(),
                    ),
                    losses: append_many(&parent.losses, proposal.method.losses.iter().copied()),
                });
                seen.insert(key, id);
                id
            };

            graph.edges.push(ViewpointEdge {
                from: proposal.parent,
                to: child_id,
                method: proposal.method.id.to_string(),
                family: proposal.method.family.to_string(),
                compatibility: proposal.compatibility,
                novelty: proposal.novelty,
                breadth_gain: proposal.breadth_gain,
            });
            if !next_beam.contains(&child_id) {
                next_beam.push(child_id);
            }
        }

        next_beam.sort_by(|&a, &b| cmp_f64(graph.nodes[b].score, graph.nodes[a].score));
        next_beam.truncate(opts.beam_width);
        beam = next_beam;
        if beam.is_empty() {
            break;
        }
    }
    Ok(graph)
}

#[derive(Clone)]
struct Proposal {
    parent: usize,
    method: MethodSpec,
    affordances: BTreeSet<Affordance>,
    compatibility: f64,
    novelty: f64,
    breadth: usize,
    breadth_gain: usize,
    score: f64,
}

fn diversify(mut proposals: Vec<Proposal>, top: usize, family_penalty: f64) -> Vec<Proposal> {
    let mut selected = Vec::new();
    let mut family_counts: HashMap<&'static str, usize> = HashMap::new();
    while !proposals.is_empty() && selected.len() < top {
        let mut best_idx = 0usize;
        let mut best_score = f64::NEG_INFINITY;
        for (i, proposal) in proposals.iter().enumerate() {
            let repeats = family_counts
                .get(proposal.method.family)
                .copied()
                .unwrap_or(0);
            let score = proposal.score * family_penalty.powi(repeats as i32);
            if score > best_score {
                best_idx = i;
                best_score = score;
            }
        }
        let chosen = proposals.remove(best_idx);
        *family_counts.entry(chosen.method.family).or_default() += 1;
        selected.push(chosen);
    }
    selected
}

fn local_step_score(compatibility: f64, novelty: f64, breadth_gain: usize) -> f64 {
    let breadth = (breadth_gain as f64 / 5.0).min(1.0);
    compatibility * (0.66 + 0.20 * novelty + 0.14 * breadth)
}

fn compatibility(current: &BTreeSet<Affordance>, method: &MethodSpec) -> f64 {
    if method.recognizes.is_empty() {
        return 0.0;
    }
    method
        .recognizes
        .iter()
        .filter(|a| current.contains(a))
        .count() as f64
        / method.recognizes.len() as f64
}

fn method_breadth(methods: &[MethodSpec], current: &BTreeSet<Affordance>) -> usize {
    methods
        .iter()
        .filter(|m| compatibility(current, m) >= 0.34)
        .count()
}

fn state_key(affordances: &BTreeSet<Affordance>) -> Vec<Affordance> {
    affordances.iter().copied().collect()
}

fn append_one(items: &[String], item: &str) -> Vec<String> {
    let mut out = items.to_vec();
    out.push(item.to_string());
    out
}

fn append_many<'a>(items: &[String], more: impl IntoIterator<Item = &'a str>) -> Vec<String> {
    let mut out = items.to_vec();
    out.extend(more.into_iter().map(str::to_string));
    out
}

fn cmp_f64(a: f64, b: f64) -> Ordering {
    a.partial_cmp(&b).unwrap_or(Ordering::Equal)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::Graph;

    fn c(name: &str) -> String {
        format!("c({}:{name},0)", name.len())
    }

    fn stmt(names: &[&str]) -> String {
        let mut names = names.iter();
        let first = c(names.next().unwrap());
        let expr = names.fold(first, |acc, name| format!("a({acc},{})", c(name)));
        format!("atlas-stmt-v1;{expr}")
    }

    fn graph() -> Graph {
        let statement = stmt(&["ContinuousLinearMap", "deriv", "Flow", "InnerProductSpace"]);
        Graph::from_jsonl(&format!(
            "{{\"name\":\"P\",\"kind\":\"theorem\",\"module\":\"Dynamics\",\"stmt\":\"{statement}\",\"uses_statement\":[],\"uses_proof\":[]}}"
        ))
        .unwrap()
    }

    #[test]
    fn exploration_builds_distinct_multistep_viewpoints() {
        let graph = graph();
        let index = IntuitionIndex::build(&graph);
        let viewpoints = explore_viewpoints(
            &index,
            "P",
            None,
            &ExploreOptions {
                max_depth: 2,
                beam_width: 8,
                ..ExploreOptions::default()
            },
        )
        .unwrap();
        assert!(viewpoints.nodes.len() > 1);
        assert!(viewpoints.edges.iter().any(|e| e.method == "spectralize"));
        assert!(viewpoints.nodes.iter().any(|n| n.path.len() == 2));
        assert!(viewpoints.nodes.iter().all(|n| n.depth <= 2));
    }

    #[test]
    fn viewpoint_paths_accumulate_obligations_and_losses() {
        let graph = graph();
        let index = IntuitionIndex::build(&graph);
        let viewpoints = explore_viewpoints(&index, "P", None, &ExploreOptions::default()).unwrap();
        let child = viewpoints
            .nodes
            .iter()
            .find(|n| n.path.first().is_some_and(|m| m == "spectralize"))
            .unwrap();
        assert!(!child.obligations.is_empty());
        assert!(!child.losses.is_empty());
        assert!(child.affordances.contains(&Affordance::Spectral));
    }

    #[test]
    fn pareto_front_does_not_collapse_to_one_scalar_winner() {
        let graph = graph();
        let index = IntuitionIndex::build(&graph);
        let front = pareto_methods(&index, "P", None).unwrap();
        assert!(!front.is_empty());
        assert!(front.iter().all(|p| !p.strengths.is_empty()));
    }
}
