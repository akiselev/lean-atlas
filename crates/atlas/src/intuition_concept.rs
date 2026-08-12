//! Formal-concept analysis over declaration × affordance incidence.
//!
//! This layer is intentionally exact with respect to the *extracted affordance context*:
//! a concept is a closed set of affordances and all declarations carrying it. That does not
//! make an affordance implication a theorem of mathematics; it is a corpus-level regularity
//! that should be tested on held-out theories and, where meaningful, formalized/refuted.

use std::collections::{BTreeMap, BTreeSet};

use crate::graph::Graph;
use crate::intuition::{Affordance, IntuitionIndex};

pub const ALL_AFFORDANCES: [Affordance; 36] = [
    Affordance::Algebraic,
    Affordance::Analytic,
    Affordance::Categorical,
    Affordance::Combinatorial,
    Affordance::Conservation,
    Affordance::Continuous,
    Affordance::Convolution,
    Affordance::Differential,
    Affordance::Discrete,
    Affordance::Dynamical,
    Affordance::Entropic,
    Affordance::Equality,
    Affordance::Equivalence,
    Affordance::Finite,
    Affordance::Geometric,
    Affordance::InnerProduct,
    Affordance::Integral,
    Affordance::LimitAsymptotic,
    Affordance::Linear,
    Affordance::Locality,
    Affordance::Measure,
    Affordance::Metric,
    Affordance::Normed,
    Affordance::Operator,
    Affordance::Optimization,
    Affordance::Order,
    Affordance::Polynomial,
    Affordance::Positivity,
    Affordance::Probabilistic,
    Affordance::Quotient,
    Affordance::Scaling,
    Affordance::Spectral,
    Affordance::Symmetry,
    Affordance::Topological,
    Affordance::Variational,
    // Keep one spare semantic axis explicit rather than changing bit assignments later.
    // Equality of this array length is tested; adding an affordance must update the codec.
    Affordance::Algebraic,
];

/// One exact formal concept in the current extracted context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FormalConcept {
    pub intent: Vec<Affordance>,
    pub extent: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConceptLattice {
    pub concepts: Vec<FormalConcept>,
    /// `(general, specific)`: immediate cover edges in intent-inclusion order.
    pub covers: Vec<(usize, usize)>,
    pub truncated: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ObservedImplication {
    pub antecedent: Vec<Affordance>,
    pub consequent: Vec<Affordance>,
    pub support: usize,
    pub support_fraction: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MissingCell {
    pub theory: String,
    pub affordance: Affordance,
    pub local_support: usize,
    pub global_support: usize,
    pub global_fraction: f64,
}

#[derive(Clone, Debug)]
struct Object {
    name: String,
    mask: u64,
}

/// A compact FCA context. Affordances fit in a u64 so closure and NextClosure are cheap.
#[derive(Clone, Debug)]
pub struct ConceptContext {
    objects: Vec<Object>,
    attribute_count: usize,
    all_mask: u64,
}

impl ConceptContext {
    pub fn build(graph: &Graph, idx: &IntuitionIndex, prefix: Option<&str>) -> Self {
        let attrs = unique_affordances();
        let attribute_count = attrs.len();
        assert!(attribute_count <= 63, "affordance context must fit in u64");
        let all_mask = if attribute_count == 64 {
            u64::MAX
        } else {
            (1u64 << attribute_count) - 1
        };
        let mut objects = Vec::new();
        for name in graph.names() {
            let Some(p) = idx.profile(name) else {
                continue;
            };
            if let Some(prefix) = prefix {
                if !p.declaration.starts_with(prefix) && !p.module.starts_with(prefix) {
                    continue;
                }
            }
            let mut mask = 0u64;
            for a in p.affordances() {
                if let Some(i) = attribute_index(a) {
                    mask |= 1u64 << i;
                }
            }
            objects.push(Object {
                name: name.clone(),
                mask,
            });
        }
        Self {
            objects,
            attribute_count,
            all_mask,
        }
    }

    pub fn len(&self) -> usize {
        self.objects.len()
    }

    pub fn is_empty(&self) -> bool {
        self.objects.is_empty()
    }

    /// FCA closure B'' = attributes common to every declaration carrying B.
    pub fn closure_mask(&self, seed: u64) -> u64 {
        let seed = seed & self.all_mask;
        let mut closure = self.all_mask;
        let mut any = false;
        for o in &self.objects {
            if o.mask & seed == seed {
                closure &= o.mask;
                any = true;
            }
        }
        // Standard FCA convention: intersection over the empty extent is all attributes.
        if any { closure } else { self.all_mask }
    }

    pub fn extent_mask(&self, intent: u64) -> Vec<String> {
        self.objects
            .iter()
            .filter(|o| o.mask & intent == intent)
            .map(|o| o.name.clone())
            .collect()
    }

    pub fn concepts(&self, max_concepts: usize) -> ConceptLattice {
        if self.objects.is_empty() || max_concepts == 0 {
            return ConceptLattice {
                concepts: Vec::new(),
                covers: Vec::new(),
                truncated: false,
            };
        }
        let mut masks = Vec::new();
        let mut current = self.closure_mask(0);
        loop {
            masks.push(current);
            if masks.len() >= max_concepts {
                let truncated = next_closure(self, current).is_some();
                let concepts = self.materialize(&masks);
                let covers = cover_edges(&masks);
                return ConceptLattice {
                    concepts,
                    covers,
                    truncated,
                };
            }
            let Some(next) = next_closure(self, current) else {
                break;
            };
            if next == current {
                break;
            }
            current = next;
        }
        let concepts = self.materialize(&masks);
        let covers = cover_edges(&masks);
        ConceptLattice {
            concepts,
            covers,
            truncated: false,
        }
    }

    fn materialize(&self, masks: &[u64]) -> Vec<FormalConcept> {
        masks
            .iter()
            .map(|&m| FormalConcept {
                intent: decode_mask(m),
                extent: self.extent_mask(m),
            })
            .collect()
    }

    /// Exact corpus implications with singleton and optionally pair antecedents. This is
    /// not advertised as the Duquenne–Guigues canonical basis; the restricted antecedent
    /// size is deliberate so the output remains legible and scalable.
    pub fn implications(&self, max_antecedent: usize, min_support: usize) -> Vec<ObservedImplication> {
        let attrs = unique_affordances();
        let mut seeds = Vec::new();
        for i in 0..attrs.len() {
            seeds.push(1u64 << i);
        }
        if max_antecedent >= 2 {
            for i in 0..attrs.len() {
                for j in i + 1..attrs.len() {
                    seeds.push((1u64 << i) | (1u64 << j));
                }
            }
        }
        let mut seen = BTreeSet::new();
        let mut out = Vec::new();
        for seed in seeds {
            let extent = self.extent_mask(seed);
            if extent.len() < min_support {
                continue;
            }
            let closure = self.closure_mask(seed);
            let consequent = closure & !seed;
            if consequent == 0 || closure == self.all_mask && extent.is_empty() {
                continue;
            }
            let key = (seed, consequent);
            if !seen.insert(key) {
                continue;
            }
            out.push(ObservedImplication {
                antecedent: decode_mask(seed),
                consequent: decode_mask(consequent),
                support: extent.len(),
                support_fraction: extent.len() as f64 / self.objects.len().max(1) as f64,
            });
        }
        out.sort_by(|a, b| {
            b.support
                .cmp(&a.support)
                .then(b.consequent.len().cmp(&a.consequent.len()))
                .then(a.antecedent.cmp(&b.antecedent))
        });
        out
    }

    /// A simple “periodic table” detector: affordances common in the global corpus but
    /// absent from a named theory prefix. These are missing structural cells, not theorem
    /// conjectures; they become interesting only when a neighboring family/dictionary says
    /// the role should be occupied.
    pub fn missing_cells(
        graph: &Graph,
        idx: &IntuitionIndex,
        theories: &[String],
        min_global_fraction: f64,
    ) -> Vec<MissingCell> {
        let global = Self::build(graph, idx, None);
        if global.is_empty() {
            return Vec::new();
        }
        let attrs = unique_affordances();
        let mut global_support = vec![0usize; attrs.len()];
        for o in &global.objects {
            for (i, support) in global_support.iter_mut().enumerate() {
                if o.mask & (1u64 << i) != 0 {
                    *support += 1;
                }
            }
        }
        let mut out = Vec::new();
        for theory in theories {
            let local = Self::build(graph, idx, Some(theory));
            if local.is_empty() {
                continue;
            }
            for (i, a) in attrs.iter().copied().enumerate() {
                let gs = global_support[i];
                let gf = gs as f64 / global.len() as f64;
                if gf < min_global_fraction {
                    continue;
                }
                let ls = local
                    .objects
                    .iter()
                    .filter(|o| o.mask & (1u64 << i) != 0)
                    .count();
                if ls == 0 {
                    out.push(MissingCell {
                        theory: theory.clone(),
                        affordance: a,
                        local_support: 0,
                        global_support: gs,
                        global_fraction: gf,
                    });
                }
            }
        }
        out.sort_by(|a, b| {
            b.global_fraction
                .partial_cmp(&a.global_fraction)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.theory.cmp(&b.theory))
                .then(a.affordance.cmp(&b.affordance))
        });
        out
    }
}

fn unique_affordances() -> Vec<Affordance> {
    use Affordance::*;
    vec![
        Algebraic,
        Analytic,
        Categorical,
        Combinatorial,
        Conservation,
        Continuous,
        Convolution,
        Differential,
        Discrete,
        Dynamical,
        Entropic,
        Equality,
        Equivalence,
        Finite,
        Geometric,
        InnerProduct,
        Integral,
        LimitAsymptotic,
        Linear,
        Locality,
        Measure,
        Metric,
        Normed,
        Operator,
        Optimization,
        Order,
        Polynomial,
        Positivity,
        Probabilistic,
        Quotient,
        Scaling,
        Spectral,
        Symmetry,
        Topological,
        Variational,
    ]
}

fn attribute_index(a: Affordance) -> Option<usize> {
    unique_affordances().iter().position(|x| *x == a)
}

fn decode_mask(mask: u64) -> Vec<Affordance> {
    unique_affordances()
        .into_iter()
        .enumerate()
        .filter_map(|(i, a)| (mask & (1u64 << i) != 0).then_some(a))
        .collect()
}

/// Ganter's NextClosure in lectic order.
fn next_closure(ctx: &ConceptContext, current: u64) -> Option<u64> {
    for i in (0..ctx.attribute_count).rev() {
        let bit = 1u64 << i;
        if current & bit != 0 {
            continue;
        }
        let lower_mask = bit - 1;
        let seed = (current & lower_mask) | bit;
        let candidate = ctx.closure_mask(seed);
        if candidate & lower_mask == current & lower_mask {
            return Some(candidate);
        }
    }
    None
}

fn cover_edges(masks: &[u64]) -> Vec<(usize, usize)> {
    let mut edges = Vec::new();
    for (i, &a) in masks.iter().enumerate() {
        for (j, &b) in masks.iter().enumerate() {
            if i == j || a == b || a & b != a {
                continue;
            }
            // a ⊂ b. It is a cover if there is no c strictly between them.
            let between = masks.iter().enumerate().any(|(k, &c)| {
                k != i && k != j && c != a && c != b && a & c == a && c & b == c
            });
            if !between {
                edges.push((i, j));
            }
        }
    }
    edges.sort();
    edges
}

#[cfg(test)]
mod tests {
    use super::*;

    fn c(name: &str) -> String {
        format!("c({}:{name},0)", name.len())
    }

    fn stmt(names: &[&str]) -> String {
        let mut it = names.iter();
        let first = c(it.next().unwrap());
        let expr = it.fold(first, |acc, n| format!("a({acc},{})", c(n)));
        format!("atlas-stmt-v1;{expr}")
    }

    fn row(name: &str, module: &str, symbols: &[&str]) -> String {
        format!(
            "{{\"name\":\"{name}\",\"kind\":\"theorem\",\"module\":\"{module}\",\"stmt\":\"{}\",\"uses_statement\":[],\"uses_proof\":[]}}",
            stmt(symbols)
        )
    }

    #[test]
    fn closure_recovers_an_exact_corpus_implication() {
        let input = [
            row("A.one", "A", &["Polynomial", "CommRing"]),
            row("A.two", "A", &["Polynomial", "Field"]),
            row("B.three", "B", &["Manifold"]),
        ]
        .join("\n");
        let g = Graph::from_jsonl(&input).unwrap();
        let idx = IntuitionIndex::build(&g);
        let ctx = ConceptContext::build(&g, &idx, None);
        let rules = ctx.implications(1, 2);
        let rule = rules
            .iter()
            .find(|r| r.antecedent == vec![Affordance::Polynomial])
            .unwrap();
        assert!(rule.consequent.contains(&Affordance::Algebraic));
        assert_eq!(rule.support, 2);
    }

    #[test]
    fn nextclosure_enumerates_closed_concepts_without_duplicates() {
        let input = [
            row("A.one", "A", &["Polynomial", "CommRing"]),
            row("A.two", "A", &["Polynomial", "Field"]),
            row("B.three", "B", &["Manifold", "TopologicalSpace"]),
        ]
        .join("\n");
        let g = Graph::from_jsonl(&input).unwrap();
        let idx = IntuitionIndex::build(&g);
        let ctx = ConceptContext::build(&g, &idx, None);
        let lattice = ctx.concepts(100);
        assert!(!lattice.concepts.is_empty());
        let intents: BTreeSet<_> = lattice
            .concepts
            .iter()
            .map(|c| c.intent.clone())
            .collect();
        assert_eq!(intents.len(), lattice.concepts.len());
    }

    #[test]
    fn missing_cells_are_structural_absences_not_similarity_scores() {
        let input = [
            row("A.one", "A", &["Polynomial", "CommRing"]),
            row("A.two", "A", &["Field"]),
            row("B.one", "B", &["Manifold", "TopologicalSpace"]),
            row("B.two", "B", &["Manifold", "Continuous"]),
        ]
        .join("\n");
        let g = Graph::from_jsonl(&input).unwrap();
        let idx = IntuitionIndex::build(&g);
        let cells = ConceptContext::missing_cells(
            &g,
            &idx,
            &["A".to_string(), "B".to_string()],
            0.25,
        );
        assert!(cells.iter().any(|c| {
            c.theory == "A" && c.affordance == Affordance::Geometric && c.local_support == 0
        }));
    }
}
