//! Research-intuition layer: explicit affordances, viewpoint changes, and method transfer.
//!
//! This module deliberately sits one level above theorem similarity. It asks which
//! *representation change* may expose useful structure in a declaration, and why. Every
//! feature is recovered from the elaborated `atlas-stmt-v1` term (plus module provenance),
//! never by reparsing pretty-printed Lean source.
//!
//! Nothing here is a theorem or a novelty claim. A proposal is a ranked research action
//! whose components are printed separately so it can be audited, falsified, or ignored.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet, HashMap};

use crate::graph::Graph;
use crate::skel::term::{Arena, Node, TermId};

/// Structural affordances that make a mathematical method plausible.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Affordance {
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
}

impl Affordance {
    pub fn name(self) -> &'static str {
        match self {
            Self::Algebraic => "algebraic",
            Self::Analytic => "analytic",
            Self::Categorical => "categorical",
            Self::Combinatorial => "combinatorial",
            Self::Conservation => "conservation",
            Self::Continuous => "continuous",
            Self::Convolution => "convolution",
            Self::Differential => "differential",
            Self::Discrete => "discrete",
            Self::Dynamical => "dynamical",
            Self::Entropic => "entropic",
            Self::Equality => "equality",
            Self::Equivalence => "equivalence",
            Self::Finite => "finite",
            Self::Geometric => "geometric",
            Self::InnerProduct => "inner-product",
            Self::Integral => "integral",
            Self::LimitAsymptotic => "limit/asymptotic",
            Self::Linear => "linear",
            Self::Locality => "locality",
            Self::Measure => "measure",
            Self::Metric => "metric",
            Self::Normed => "normed",
            Self::Operator => "operator",
            Self::Optimization => "optimization",
            Self::Order => "order",
            Self::Polynomial => "polynomial",
            Self::Positivity => "positivity",
            Self::Probabilistic => "probabilistic",
            Self::Quotient => "quotient/moduli",
            Self::Scaling => "scaling",
            Self::Spectral => "spectral",
            Self::Symmetry => "symmetry",
            Self::Topological => "topological",
            Self::Variational => "variational",
        }
    }
}

/// An auditable view of one declaration.
#[derive(Clone, Debug, PartialEq)]
pub struct ViewpointProfile {
    pub declaration: String,
    pub module: String,
    /// Constants actually present in the elaborated statement encoding.
    pub symbols: BTreeSet<String>,
    /// Evidence symbols for each affordance. Length is the weight used by the first scorer.
    pub evidence: BTreeMap<Affordance, Vec<String>>,
}

impl ViewpointProfile {
    pub fn has(&self, a: Affordance) -> bool {
        self.evidence.contains_key(&a)
    }

    pub fn weight(&self, a: Affordance) -> usize {
        self.evidence.get(&a).map_or(0, Vec::len)
    }

    pub fn affordances(&self) -> BTreeSet<Affordance> {
        self.evidence.keys().copied().collect()
    }

    pub fn evidence_for(&self, a: Affordance) -> &[String] {
        self.evidence.get(&a).map(Vec::as_slice).unwrap_or(&[])
    }
}

/// A method is represented by the structures it recognizes and those it tends to expose.
#[derive(Clone, Debug, PartialEq)]
pub struct MethodSpec {
    pub id: &'static str,
    pub label: &'static str,
    pub family: &'static str,
    pub recognizes: Vec<Affordance>,
    /// Native affordances are used to reward disciplined cross-domain transfer, not gate it.
    pub native: Vec<Affordance>,
    pub unlocks: Vec<Affordance>,
    /// The auxiliary object that often realizes the viewpoint change.
    pub auxiliary: Option<&'static str>,
    /// Conditions a proposal must discharge before it is trusted.
    pub obligations: Vec<&'static str>,
    /// Information commonly lost by the representation change.
    pub losses: Vec<&'static str>,
}

/// Human-seeded bootstrap catalogue. A later compression/dreaming layer can promote
/// recurrent successful traces into new methods; keeping the bootstrap explicit makes the
/// first experiments reproducible.
pub fn method_catalog() -> Vec<MethodSpec> {
    use Affordance::*;
    vec![
        MethodSpec {
            id: "spectralize",
            label: "turn the problem into spectral/operator data",
            family: "spectral",
            recognizes: vec![Operator, Linear, Dynamical, InnerProduct],
            native: vec![Spectral, Analytic, Operator],
            unlocks: vec![Spectral, Operator],
            auxiliary: Some("an operator whose spectrum encodes the target structure"),
            obligations: vec![
                "construct the operator",
                "prove the relevant spectral correspondence",
            ],
            losses: vec!["local/pointwise information may be hidden in global spectrum"],
        },
        MethodSpec {
            id: "fourier-transform",
            label: "move from physical/local variables to frequency variables",
            family: "spectral",
            recognizes: vec![Convolution, Differential, Linear, Dynamical, Integral],
            native: vec![Analytic, Spectral, Linear],
            unlocks: vec![Spectral, Linear],
            auxiliary: Some("a Fourier/character transform or frequency decomposition"),
            obligations: vec![
                "identify a transform domain",
                "prove the inversion/Plancherel control needed by the claim",
            ],
            losses: vec!["spatial locality can become frequency delocalization"],
        },
        MethodSpec {
            id: "generating-function",
            label: "encode a discrete family as one algebraic/analytic object",
            family: "algebraic-analytic",
            recognizes: vec![Combinatorial, Discrete, Polynomial, Algebraic, Finite],
            native: vec![Combinatorial, Algebraic],
            unlocks: vec![Analytic, Algebraic],
            auxiliary: Some("a generating function carrying the family as coefficients"),
            obligations: vec![
                "prove coefficient correspondence",
                "control the domain of formal/analytic manipulation",
            ],
            losses: vec!["individual combinatorial witnesses are compressed into coefficients"],
        },
        MethodSpec {
            id: "geometrize",
            label: "replace algebraic constraints by spaces, loci, or moduli",
            family: "geometry",
            recognizes: vec![Algebraic, Polynomial, Symmetry, Equivalence, Quotient],
            native: vec![Algebraic],
            unlocks: vec![Geometric, Topological, Quotient],
            auxiliary: Some("a geometric locus/moduli space representing solutions"),
            obligations: vec![
                "construct the representing space",
                "prove the translation preserves the target property",
            ],
            losses: vec!["coordinate-free geometry can obscure explicit algebraic formulas"],
        },
        MethodSpec {
            id: "algebraize",
            label: "replace geometric structure by algebraic invariants or coordinates",
            family: "algebra",
            recognizes: vec![Geometric, Topological, Symmetry, Equivalence, Quotient],
            native: vec![Geometric, Topological],
            unlocks: vec![Algebraic, Polynomial],
            auxiliary: Some("an algebra of functions/invariants/cohomological coordinates"),
            obligations: vec!["show the algebraic invariant is faithful enough for the question"],
            losses: vec!["geometric locality or smooth structure may be forgotten"],
        },
        MethodSpec {
            id: "probabilize",
            label: "introduce a measure and attack deterministic structure statistically",
            family: "probability",
            recognizes: vec![Combinatorial, Finite, Order, Dynamical, Scaling],
            native: vec![Combinatorial, Discrete],
            unlocks: vec![Probabilistic, Measure, Entropic],
            auxiliary: Some("a probability measure or random variable encoding the target"),
            obligations: vec![
                "specify the ensemble",
                "connect probabilistic statements back to the deterministic target",
            ],
            losses: vec!["typical-case control need not imply worst-case control"],
        },
        MethodSpec {
            id: "variationalize",
            label: "turn the claim into minimization, stationarity, or monotonicity",
            family: "variational",
            recognizes: vec![Dynamical, Differential, Operator, Order, Positivity],
            native: vec![Analytic, Dynamical],
            unlocks: vec![Variational, Optimization, Positivity],
            auxiliary: Some("an energy/action/Lyapunov functional"),
            obligations: vec![
                "construct the functional",
                "prove extrema or monotonicity control the original quantity",
            ],
            losses: vec!["a scalar functional may forget phase/directional information"],
        },
        MethodSpec {
            id: "linearize",
            label: "study a nonlinear object through its tangent/first-order problem",
            family: "local-approximation",
            recognizes: vec![Dynamical, Differential, Geometric, Algebraic, Optimization],
            native: vec![Dynamical, Differential],
            unlocks: vec![Linear, Operator, Spectral],
            auxiliary: Some("a derivative/Jacobian/Hessian or tangent operator"),
            obligations: vec![
                "choose an expansion point/regime",
                "bound the nonlinear remainder",
            ],
            losses: vec!["global nonlinear behavior is discarded outside the certified regime"],
        },
        MethodSpec {
            id: "dualize",
            label: "move to a dual space or dual optimization problem",
            family: "duality",
            recognizes: vec![Linear, Optimization, Geometric, Algebraic, InnerProduct],
            native: vec![Linear, Optimization],
            unlocks: vec![Operator, Equivalence, Positivity],
            auxiliary: Some("a dual object/pairing exposing constraints as functionals"),
            obligations: vec![
                "construct the pairing",
                "prove the required duality/no-gap statement",
            ],
            losses: vec!["primal witnesses can become indirect existence statements"],
        },
        MethodSpec {
            id: "symmetry-reduce",
            label: "quotient by symmetry or decompose into representations",
            family: "symmetry",
            recognizes: vec![Symmetry, Dynamical, Geometric, Algebraic, Operator],
            native: vec![Symmetry, Algebraic],
            unlocks: vec![Quotient, Geometric, Spectral],
            auxiliary: Some("a group action, orbit space, or representation decomposition"),
            obligations: vec![
                "identify the action",
                "prove target quantities descend or decompose equivariantly",
            ],
            losses: vec!["quotienting removes gauge/orbit information by design"],
        },
        MethodSpec {
            id: "moduli-space",
            label: "organize equivalence classes as one parameter space",
            family: "geometry",
            recognizes: vec![Equivalence, Symmetry, Geometric, Algebraic, Quotient],
            native: vec![Geometric, Algebraic],
            unlocks: vec![Quotient, Geometric, Topological],
            auxiliary: Some("a moduli/parameter space with the equivalence built in"),
            obligations: vec![
                "define the equivalence relation",
                "control singular/non-Hausdorff behavior if relevant",
            ],
            losses: vec!["representatives are intentionally identified"],
        },
        MethodSpec {
            id: "tropicalize",
            label: "pass from algebraic/asymptotic data to piecewise-linear combinatorics",
            family: "asymptotic-geometry",
            recognizes: vec![Algebraic, Polynomial, Scaling, LimitAsymptotic, Optimization],
            native: vec![Algebraic, Geometric],
            unlocks: vec![Combinatorial, Geometric, Discrete],
            auxiliary: Some("a valuation/scaling map producing a tropical object"),
            obligations: vec![
                "choose a valuation/scaling regime",
                "prove which information survives tropicalization",
            ],
            losses: vec!["coefficients/phase data can collapse under valuation"],
        },
        MethodSpec {
            id: "compactify",
            label: "add a boundary at infinity so limiting behavior becomes geometric",
            family: "geometry",
            recognizes: vec![Geometric, Topological, Analytic, LimitAsymptotic],
            native: vec![Geometric, Topological],
            unlocks: vec![Topological, Geometric, LimitAsymptotic],
            auxiliary: Some("a compactification with a controlled boundary at infinity"),
            obligations: vec![
                "construct the compactification",
                "extend the structures used by the target theorem",
            ],
            losses: vec!["new boundary points may introduce singular behavior"],
        },
        MethodSpec {
            id: "categorify",
            label: "replace elements/equalities by objects, morphisms, and universal properties",
            family: "categorical",
            recognizes: vec![Algebraic, Geometric, Equivalence, Symmetry, Quotient],
            native: vec![Algebraic, Geometric],
            unlocks: vec![Categorical, Equivalence],
            auxiliary: Some("a category/functor/universal object encoding the constructions"),
            obligations: vec![
                "identify the morphisms",
                "show the target is invariant under the categorical translation",
            ],
            losses: vec!["element-level computational information can be abstracted away"],
        },
        MethodSpec {
            id: "cohomologize",
            label: "replace local compatibility by global obstruction/invariant classes",
            family: "topological-algebraic",
            recognizes: vec![Topological, Geometric, Algebraic, Locality, Equivalence],
            native: vec![Topological, Geometric],
            unlocks: vec![Algebraic, Categorical, Topological],
            auxiliary: Some("a chain complex/cohomology class measuring the obstruction"),
            obligations: vec![
                "construct the complex",
                "prove the class detects the original obstruction",
            ],
            losses: vec!["cohomology identifies data differing by exact terms"],
        },
        MethodSpec {
            id: "introduce-operator",
            label: "encode the target relation as an operator equation",
            family: "spectral",
            recognizes: vec![Equality, Dynamical, Algebraic, Analytic, Linear],
            native: vec![Analytic, Linear],
            unlocks: vec![Operator, Spectral],
            auxiliary: Some("an operator whose kernel/fixed points/eigenvalues encode the claim"),
            obligations: vec![
                "construct the operator",
                "prove equivalence between the operator property and original claim",
            ],
            losses: vec!["the encoding can add noncanonical operator choices"],
        },
        MethodSpec {
            id: "introduce-energy",
            label: "search for a conserved or monotone scalar quantity",
            family: "variational",
            recognizes: vec![Dynamical, Differential, Order, Positivity, Symmetry],
            native: vec![Dynamical],
            unlocks: vec![Conservation, Variational, Positivity],
            auxiliary: Some("an energy/entropy/Lyapunov quantity"),
            obligations: vec![
                "derive its evolution law",
                "prove coercivity or relevance to the target",
            ],
            losses: vec!["one scalar may not distinguish all states"],
        },
        MethodSpec {
            id: "renormalize-scale",
            label: "make scale dependence explicit and search for fixed points/invariants",
            family: "scaling",
            recognizes: vec![
                Scaling,
                LimitAsymptotic,
                Dynamical,
                Operator,
                Probabilistic,
                Locality,
            ],
            native: vec![Scaling, Analytic],
            unlocks: vec![Scaling, Dynamical, LimitAsymptotic],
            auxiliary: Some("a scale transformation/flow with fixed points or monotones"),
            obligations: vec![
                "define the coarse-graining/scale map",
                "control information lost between scales",
            ],
            losses: vec!["irrelevant microscopic detail is deliberately discarded"],
        },
        MethodSpec {
            id: "finite-analogue",
            label: "solve a finite/toy universe and inspect what survives",
            family: "toy-world",
            recognizes: vec![
                Algebraic,
                Geometric,
                Combinatorial,
                Probabilistic,
                Equality,
                Equivalence,
            ],
            native: vec![Finite, Discrete],
            unlocks: vec![Finite, Discrete, Combinatorial],
            auxiliary: Some("a finite analogue with an explicit correspondence to the target"),
            obligations: vec![
                "state which structures survive the finite model",
                "separate finite artifacts from robust invariants",
            ],
            losses: vec!["continuity/infinite-size phenomena may disappear"],
        },
        MethodSpec {
            id: "discretize",
            label: "replace continuous structure by a controlled discrete model",
            family: "toy-world",
            recognizes: vec![Continuous, Differential, Integral, Dynamical, Geometric],
            native: vec![Continuous, Analytic],
            unlocks: vec![Discrete, Finite, Combinatorial],
            auxiliary: Some("a lattice/mesh/finite approximation plus convergence map"),
            obligations: vec!["prove consistency", "bound discretization error"],
            losses: vec!["continuous symmetries may be broken by discretization"],
        },
        MethodSpec {
            id: "continuum-limit",
            label: "embed a discrete family into a limiting continuous theory",
            family: "toy-world",
            recognizes: vec![Discrete, Finite, Combinatorial, Probabilistic, Scaling],
            native: vec![Discrete, Probabilistic],
            unlocks: vec![Continuous, Analytic, LimitAsymptotic],
            auxiliary: Some("a scaled family and limiting continuous object"),
            obligations: vec![
                "choose scaling",
                "prove convergence strong enough for the target observable",
            ],
            losses: vec!["microscopic/discrete information can vanish in the limit"],
        },
        MethodSpec {
            id: "large-parameter-limit",
            label: "study an extreme parameter regime where structure simplifies",
            family: "toy-world",
            recognizes: vec![Finite, Discrete, Dynamical, Probabilistic, Scaling, Algebraic],
            native: vec![LimitAsymptotic, Scaling],
            unlocks: vec![LimitAsymptotic, Scaling, Continuous],
            auxiliary: Some("a one-parameter family plus an asymptotic comparison map"),
            obligations: vec![
                "identify the control parameter",
                "bound the remainder away from the limit",
            ],
            losses: vec!["the limit can erase finite-parameter effects"],
        },
    ]
}

/// One scored "try this method/viewpoint" action.
#[derive(Clone, Debug, PartialEq)]
pub struct MethodCandidate {
    pub method: MethodSpec,
    pub matched: Vec<Affordance>,
    pub missing: Vec<Affordance>,
    pub compatibility: f64,
    pub domain_distance: f64,
    pub bridge_value: f64,
    pub novelty: f64,
    pub breadth_gain: usize,
    pub experience_factor: f64,
    pub prior_attempts: Vec<AttemptRecord>,
    pub base_score: f64,
    /// Score after quality-diversity reranking.
    pub score: f64,
}

/// A concrete proposed change of viewpoint.
#[derive(Clone, Debug, PartialEq)]
pub struct ViewpointProposal {
    pub method: String,
    pub label: String,
    pub family: String,
    pub score: f64,
    pub matched: Vec<Affordance>,
    pub unlocks: Vec<Affordance>,
    pub breadth_gain: usize,
    pub auxiliary: Option<String>,
    pub obligations: Vec<String>,
    pub losses: Vec<String>,
    pub prior_attempts: Vec<AttemptRecord>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AuxiliaryCandidate {
    pub method: String,
    pub object: String,
    pub score: f64,
    pub obligations: Vec<String>,
}

/// Aggregate affordances of a namespace/module prefix.
#[derive(Clone, Debug, PartialEq)]
pub struct TheoryProfile {
    pub prefix: String,
    pub declarations: usize,
    pub evidence: BTreeMap<Affordance, usize>,
}

impl TheoryProfile {
    pub fn has(&self, a: Affordance) -> bool {
        self.evidence.contains_key(&a)
    }

    pub fn affordances(&self) -> BTreeSet<Affordance> {
        self.evidence.keys().copied().collect()
    }
}

/// A directed proposal for translating one theory into a language already productive in
/// another. This is a bridge hypothesis, not a dictionary row.
#[derive(Clone, Debug, PartialEq)]
pub struct BridgeCandidate {
    pub method: MethodSpec,
    pub from: String,
    pub to: String,
    pub score: f64,
    pub source_fit: f64,
    pub target_echo: f64,
    pub shared: Vec<Affordance>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AttemptOutcome {
    Succeeded,
    Failed,
    Refuted,
    Blocked,
    Inconclusive,
}

impl AttemptOutcome {
    fn parse(s: &str) -> Option<Self> {
        match s {
            "succeeded" | "success" | "proved" => Some(Self::Succeeded),
            "failed" | "failure" => Some(Self::Failed),
            "refuted" => Some(Self::Refuted),
            "blocked" | "unstatable" => Some(Self::Blocked),
            "inconclusive" | "unknown" => Some(Self::Inconclusive),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Refuted => "refuted",
            Self::Blocked => "blocked",
            Self::Inconclusive => "inconclusive",
        }
    }
}

/// Research experience is deliberately separate from the formal graph: a failed research
/// move is evidence about search policy, not a Lean fact.
#[derive(Clone, Debug, PartialEq)]
pub struct AttemptRecord {
    pub problem: String,
    pub method: String,
    pub outcome: AttemptOutcome,
    pub reason: String,
    pub step: Option<u64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Experience {
    records: Vec<AttemptRecord>,
}

impl Experience {
    /// JSONL schema: `{ "problem": ..., "method": ..., "outcome": ..., "reason": ...,
    /// "step": 3 }`. `step` and `reason` are optional.
    pub fn from_jsonl(input: &str) -> Result<Self, String> {
        let mut records = Vec::new();
        for (i, line) in input.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let obj = crate::json::parse(line)
                .map_err(|e| format!("experience line {}: {e}", i + 1))?;
            let get = |k: &str| obj.get(k).and_then(|v| v.as_str());
            let problem = get("problem")
                .ok_or_else(|| format!("experience line {} has no `problem`", i + 1))?;
            let method = get("method")
                .ok_or_else(|| format!("experience line {} has no `method`", i + 1))?;
            let outcome_text = get("outcome")
                .ok_or_else(|| format!("experience line {} has no `outcome`", i + 1))?;
            let outcome = AttemptOutcome::parse(outcome_text).ok_or_else(|| {
                format!(
                    "experience line {} has unknown outcome `{outcome_text}`",
                    i + 1
                )
            })?;
            let step = match obj.get("step") {
                Some(crate::json::Value::Num(n)) if *n >= 0.0 && n.fract() == 0.0 => {
                    Some(*n as u64)
                }
                _ => None,
            };
            records.push(AttemptRecord {
                problem: problem.to_string(),
                method: method.to_string(),
                outcome,
                reason: get("reason").unwrap_or("").to_string(),
                step,
            });
        }
        Ok(Self { records })
    }

    pub fn records(&self) -> &[AttemptRecord] {
        &self.records
    }

    pub fn attempts_for(&self, problem: &str, method: &str) -> Vec<AttemptRecord> {
        self.records
            .iter()
            .filter(|r| r.problem == problem && r.method == method)
            .cloned()
            .collect()
    }

    fn factor(&self, problem: &str, method: &str) -> f64 {
        let attempts = self.attempts_for(problem, method);
        if attempts.is_empty() {
            return 1.0;
        }
        // Do not hard-prune failures. A stronger theorem or later method improvement may
        // make a previously bad route useful. Refutation gets the strongest penalty.
        attempts.iter().fold(1.0_f64, |acc, a| {
            acc * match a.outcome {
                AttemptOutcome::Succeeded => 1.10,
                AttemptOutcome::Failed => 0.55,
                AttemptOutcome::Refuted => 0.20,
                AttemptOutcome::Blocked => 0.70,
                AttemptOutcome::Inconclusive => 0.90,
            }
        })
    }

    /// Frequent adjacent method moves in ordered research traces: the first "dream" layer.
    /// It identifies recurrent action motifs that an MDL/grammar-induction layer can later
    /// consider promoting into new methods.
    pub fn motifs(&self, min_count: usize) -> Vec<MethodMotif> {
        let mut by_problem: BTreeMap<&str, Vec<&AttemptRecord>> = BTreeMap::new();
        for r in &self.records {
            if r.step.is_some() {
                by_problem.entry(&r.problem).or_default().push(r);
            }
        }
        let mut counts: BTreeMap<(String, String), (usize, usize)> = BTreeMap::new();
        for mut trace in by_problem.into_values() {
            trace.sort_by_key(|r| r.step);
            for pair in trace.windows(2) {
                let key = (pair[0].method.clone(), pair[1].method.clone());
                let entry = counts.entry(key).or_default();
                entry.0 += 1;
                if pair[1].outcome == AttemptOutcome::Succeeded {
                    entry.1 += 1;
                }
            }
        }
        let mut out: Vec<MethodMotif> = counts
            .into_iter()
            .filter(|(_, (count, _))| *count >= min_count)
            .map(|((first, second), (count, successes))| MethodMotif {
                first,
                second,
                count,
                successes,
            })
            .collect();
        out.sort_by(|a, b| {
            b.count
                .cmp(&a.count)
                .then(b.successes.cmp(&a.successes))
                .then(a.first.cmp(&b.first))
                .then(a.second.cmp(&b.second))
        });
        out
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MethodMotif {
    pub first: String,
    pub second: String,
    pub count: usize,
    pub successes: usize,
}

/// Index of auditable viewpoint profiles and the bootstrap method ontology.
#[derive(Debug)]
pub struct IntuitionIndex {
    profiles: BTreeMap<String, ViewpointProfile>,
    parse_failures: BTreeMap<String, String>,
    methods: Vec<MethodSpec>,
}

impl IntuitionIndex {
    pub fn build(graph: &Graph) -> Self {
        let mut arena = Arena::new();
        let mut profiles = BTreeMap::new();
        let mut parse_failures = BTreeMap::new();

        for name in graph.names() {
            let Some(decl) = graph.get(name) else {
                continue;
            };
            let Some(stmt) = decl.stmt.as_deref() else {
                continue;
            };
            match arena.parse(stmt) {
                Ok(root) => {
                    let symbols = collect_symbols(&arena, root);
                    let evidence = classify_affordances(&symbols);
                    profiles.insert(
                        name.clone(),
                        ViewpointProfile {
                            declaration: name.clone(),
                            module: decl.module.clone(),
                            symbols,
                            evidence,
                        },
                    );
                }
                Err(e) => {
                    parse_failures.insert(name.clone(), e.to_string());
                }
            }
        }

        Self {
            profiles,
            parse_failures,
            methods: method_catalog(),
        }
    }

    pub fn profile(&self, declaration: &str) -> Option<&ViewpointProfile> {
        self.profiles.get(declaration)
    }

    pub fn parse_failures(&self) -> &BTreeMap<String, String> {
        &self.parse_failures
    }

    pub fn methods(&self) -> &[MethodSpec] {
        &self.methods
    }

    /// Representation-quality proxy: how many catalogue methods currently see enough
    /// recognized structure to be plausible.
    pub fn method_breadth(&self, declaration: &str) -> Option<usize> {
        let p = self.profile(declaration)?;
        Some(self.method_breadth_for(&p.affordances()))
    }

    fn method_breadth_for(&self, affs: &BTreeSet<Affordance>) -> usize {
        self.methods
            .iter()
            .filter(|m| compatibility_set(affs, m) >= 0.34)
            .count()
    }

    pub fn candidates(
        &self,
        declaration: &str,
        experience: Option<&Experience>,
        top: usize,
    ) -> Result<Vec<MethodCandidate>, String> {
        let profile = self
            .profile(declaration)
            .ok_or_else(|| format!("`{declaration}` has no encoded viewpoint profile"))?;
        let current = profile.affordances();
        let breadth_before = self.method_breadth_for(&current);
        let empty = Experience::default();
        let experience = experience.unwrap_or(&empty);

        let mut candidates = Vec::new();
        for method in &self.methods {
            let (matched, missing) = match_method(&current, method);
            let compatibility = compatibility_set(&current, method);
            if compatibility == 0.0 {
                continue;
            }
            let native_seen = fraction_present(&current, &method.native);
            let domain_distance = 1.0 - native_seen;
            let unlock_new = method
                .unlocks
                .iter()
                .filter(|a| !current.contains(a))
                .count();
            let bridge_value = if method.unlocks.is_empty() {
                0.0
            } else {
                unlock_new as f64 / method.unlocks.len() as f64
            };
            let novelty = if method.unlocks.is_empty() {
                0.5
            } else {
                1.0 - fraction_present(&current, &method.unlocks)
            };
            let mut simulated = current.clone();
            simulated.extend(method.unlocks.iter().copied());
            let breadth_after = self.method_breadth_for(&simulated);
            let breadth_gain = breadth_after.saturating_sub(breadth_before);
            let breadth_term = (breadth_gain as f64 / 5.0).min(1.0);
            let experience_factor = experience.factor(declaration, method.id);
            let prior_attempts = experience.attempts_for(declaration, method.id);

            // Compatibility gates the score: domain distance without structural fit is
            // noise. Once fit exists, reward distance, new affordances, and representations
            // that enlarge the future method repertoire.
            let base_score = compatibility
                * (0.44
                    + 0.18 * domain_distance
                    + 0.16 * bridge_value
                    + 0.10 * novelty
                    + 0.12 * breadth_term)
                * experience_factor;
            candidates.push(MethodCandidate {
                method: method.clone(),
                matched,
                missing,
                compatibility,
                domain_distance,
                bridge_value,
                novelty,
                breadth_gain,
                experience_factor,
                prior_attempts,
                base_score,
                score: base_score,
            });
        }

        Ok(diversify(candidates, top))
    }

    pub fn refract(
        &self,
        declaration: &str,
        experience: Option<&Experience>,
        top: usize,
    ) -> Result<Vec<ViewpointProposal>, String> {
        Ok(self
            .candidates(declaration, experience, top)?
            .into_iter()
            .map(|c| ViewpointProposal {
                method: c.method.id.to_string(),
                label: c.method.label.to_string(),
                family: c.method.family.to_string(),
                score: c.score,
                matched: c.matched,
                unlocks: c.method.unlocks.clone(),
                breadth_gain: c.breadth_gain,
                auxiliary: c.method.auxiliary.map(str::to_string),
                obligations: c
                    .method
                    .obligations
                    .iter()
                    .map(|s| s.to_string())
                    .collect(),
                losses: c.method.losses.iter().map(|s| s.to_string()).collect(),
                prior_attempts: c.prior_attempts,
            })
            .collect())
    }

    pub fn missing_auxiliaries(
        &self,
        declaration: &str,
        experience: Option<&Experience>,
        top: usize,
    ) -> Result<Vec<AuxiliaryCandidate>, String> {
        Ok(self
            .candidates(declaration, experience, self.methods.len())?
            .into_iter()
            .filter_map(|c| {
                c.method.auxiliary.map(|object| AuxiliaryCandidate {
                    method: c.method.id.to_string(),
                    object: object.to_string(),
                    score: c.score,
                    obligations: c
                        .method
                        .obligations
                        .iter()
                        .map(|s| s.to_string())
                        .collect(),
                })
            })
            .take(top)
            .collect())
    }

    pub fn toy_worlds(
        &self,
        declaration: &str,
        experience: Option<&Experience>,
        top: usize,
    ) -> Result<Vec<ViewpointProposal>, String> {
        Ok(self
            .refract(declaration, experience, self.methods.len())?
            .into_iter()
            .filter(|p| p.family == "toy-world" || p.family == "local-approximation")
            .take(top)
            .collect())
    }

    pub fn theory_profile(&self, prefix: &str) -> TheoryProfile {
        let mut declarations = 0usize;
        let mut evidence: BTreeMap<Affordance, usize> = BTreeMap::new();
        for profile in self.profiles.values() {
            if profile.declaration.starts_with(prefix) || profile.module.starts_with(prefix) {
                declarations += 1;
                for (a, symbols) in &profile.evidence {
                    *evidence.entry(*a).or_default() += symbols.len();
                }
            }
        }
        TheoryProfile {
            prefix: prefix.to_string(),
            declarations,
            evidence,
        }
    }

    /// Search for a language transfer: a method structurally supported on one side whose
    /// outputs are already prominent on the other. This says "try viewing A through
    /// machinery productive in B", not "A and B are analogous".
    pub fn bridges(&self, left: &str, right: &str, top: usize) -> Vec<BridgeCandidate> {
        let l = self.theory_profile(left);
        let r = self.theory_profile(right);
        let mut out = Vec::new();
        out.extend(self.directed_bridges(&l, &r));
        out.extend(self.directed_bridges(&r, &l));
        out.sort_by(|a, b| {
            cmp_f64(b.score, a.score)
                .then(a.method.id.cmp(b.method.id))
                .then(a.from.cmp(&b.from))
        });
        out.truncate(top);
        out
    }

    fn directed_bridges(
        &self,
        from: &TheoryProfile,
        to: &TheoryProfile,
    ) -> Vec<BridgeCandidate> {
        let source = from.affordances();
        let target = to.affordances();
        let shared: Vec<Affordance> = source.intersection(&target).copied().collect();
        let distance = jaccard_distance(&source, &target);
        let mut out = Vec::new();
        for method in &self.methods {
            let source_fit = compatibility_set(&source, method);
            let target_echo = fraction_present(&target, &method.unlocks);
            if source_fit == 0.0 || target_echo == 0.0 {
                continue;
            }
            // An edge that changes no representation is usage, not a bridge.
            if method.unlocks.iter().all(|a| source.contains(a)) {
                continue;
            }
            let score = source_fit * target_echo * (0.65 + 0.35 * distance);
            out.push(BridgeCandidate {
                method: method.clone(),
                from: from.prefix.clone(),
                to: to.prefix.clone(),
                score,
                source_fit,
                target_echo,
                shared: shared.clone(),
            });
        }
        out
    }
}

fn collect_symbols(arena: &Arena, root: TermId) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    let mut seen = BTreeSet::new();
    let mut stack = vec![root];
    while let Some(t) = stack.pop() {
        if !seen.insert(t) {
            continue;
        }
        match arena.node(t) {
            Node::Const(sym, _) => {
                out.insert(arena.sym(sym).to_string());
            }
            Node::App(a, b) | Node::Lam(_, a, b) | Node::Pi(_, a, b) => {
                stack.push(a);
                stack.push(b);
            }
            Node::Let(t, v, b) => {
                stack.push(t);
                stack.push(v);
                stack.push(b);
            }
            Node::Proj(sym, _, e) => {
                out.insert(arena.sym(sym).to_string());
                stack.push(e);
            }
            Node::BVar(_)
            | Node::Sort(_)
            | Node::NatLit(_)
            | Node::StrLit(_)
            | Node::Hole
            | Node::Var(_) => {}
        }
    }
    out
}

fn classify_affordances(symbols: &BTreeSet<String>) -> BTreeMap<Affordance, Vec<String>> {
    let mut evidence: BTreeMap<Affordance, BTreeSet<String>> = BTreeMap::new();
    for symbol in symbols {
        let lower = symbol.to_ascii_lowercase();
        let mut mark = |a: Affordance| {
            evidence.entry(a).or_default().insert(symbol.clone());
        };
        if has(
            &lower,
            &["ring", "field", "semiring", "monoid", "group", "algebra", "ideal", "module"],
        ) {
            mark(Affordance::Algebraic);
        }
        if has(
            &lower,
            &["analytic", "complex", "realanalytic", "holomorph", "series", "tendsto"],
        ) {
            mark(Affordance::Analytic);
        }
        if has(
            &lower,
            &["category", "functor", "naturaltransformation", "yoneda", "adjunction"],
        ) {
            mark(Affordance::Categorical);
        }
        if has(
            &lower,
            &["finset", "fintype", "card", "choose", "simplegraph", "multiset", "permutation"],
        ) {
            mark(Affordance::Combinatorial);
        }
        if has(
            &lower,
            &["conserved", "conservation", "invariantquantity", "firstintegral"],
        ) {
            mark(Affordance::Conservation);
        }
        if has(&lower, &["continuous", "continuity", "smooth", "manifold"]) {
            mark(Affordance::Continuous);
        }
        if has(&lower, &["convolution", "conv"]) {
            mark(Affordance::Convolution);
        }
        if has(
            &lower,
            &["deriv", "differential", "gradient", "laplace", "curl", "divergence", "jacobian", "hessian"],
        ) {
            mark(Affordance::Differential);
        }
        if has(
            &lower,
            &["nat", "int", "finset", "fintype", "discrete", "lattice"],
        ) {
            mark(Affordance::Discrete);
        }
        if has(
            &lower,
            &["flow", "trajectory", "dynamics", "evolution", "semigroup", "time", "ode", "iterate"],
        ) {
            mark(Affordance::Dynamical);
        }
        if has(
            &lower,
            &["entropy", "relativeentropy", "mutualinformation", "shannon"],
        ) {
            mark(Affordance::Entropic);
        }
        if symbol == "Eq" || symbol.ends_with(".Eq") {
            mark(Affordance::Equality);
        }
        if has(
            &lower,
            &["iff", "equiv", "isomorph", "homeomorph", "linearequiv", "ringequiv"],
        ) {
            mark(Affordance::Equivalence);
        }
        if has(&lower, &["finite", "fintype", "finset", "matrix"]) || lower.ends_with(".fin") {
            mark(Affordance::Finite);
        }
        if has(
            &lower,
            &["geometry", "geometric", "manifold", "affine", "euclidean", "lorentz", "scheme", "variety", "vectorbundle"],
        ) {
            mark(Affordance::Geometric);
        }
        if has(
            &lower,
            &["innerproduct", "inner", "orthogon", "hilbert", "sesquilinear"],
        ) {
            mark(Affordance::InnerProduct);
        }
        if has(
            &lower,
            &["integral", "integrable", "measureintegral", "intervalintegral"],
        ) {
            mark(Affordance::Integral);
        }
        if has(
            &lower,
            &["tendsto", "limit", "asympt", "littleo", "bigo", "filter.at", "eventually"],
        ) {
            mark(Affordance::LimitAsymptotic);
        }
        if has(&lower, &["linear", "matrix", "module", "vector", "addhom"]) {
            mark(Affordance::Linear);
        }
        if has(
            &lower,
            &["local", "compact_support", "finite_range", "neighborhood", "nhds"],
        ) {
            mark(Affordance::Locality);
        }
        if has(
            &lower,
            &["measure", "volume", "haar", "probabilitymeasure", "integral"],
        ) {
            mark(Affordance::Measure);
        }
        if has(&lower, &["metric", "dist", "edist", "pseudoemetric"]) {
            mark(Affordance::Metric);
        }
        if has(&lower, &["norm", "seminorm", "banach", "isometry"]) {
            mark(Affordance::Normed);
        }
        if has(
            &lower,
            &["operator", "continuouslinearmap", "linearoperator", "module.end", "endomorph", "matrix"],
        ) {
            mark(Affordance::Operator);
        }
        if has(
            &lower,
            &["argmin", "argmax", "minim", "maxim", "optimal", "convex", "concave"],
        ) {
            mark(Affordance::Optimization);
        }
        if has(
            &lower,
            &["le.le", "lt.lt", "partialorder", "linearorder", "sup", "inf", "monotone"],
        ) {
            mark(Affordance::Order);
        }
        if has(
            &lower,
            &["polynomial", "mvpolynomial", "power_series", "laurent"],
        ) {
            mark(Affordance::Polynomial);
        }
        if has(
            &lower,
            &["nonneg", "positive", "positiv", "psd", "semidefinite", "sq_nonneg"],
        ) {
            mark(Affordance::Positivity);
        }
        if has(
            &lower,
            &["probability", "random", "distribution", "expectation", "independent", "markov", "stochastic"],
        ) {
            mark(Affordance::Probabilistic);
        }
        if has(&lower, &["quotient", "quot", "orbit", "moduli", "setoid"]) {
            mark(Affordance::Quotient);
        }
        if has(
            &lower,
            &["scale", "scaling", "homogeneous", "degree", "dilation", "renormal"],
        ) {
            mark(Affordance::Scaling);
        }
        if has(
            &lower,
            &["spectrum", "eigen", "eigenspace", "resolvent", "selfadjoint", "spectral", "trace"],
        ) {
            mark(Affordance::Spectral);
        }
        if has(
            &lower,
            &["mulaction", "addaction", "groupaction", "equivariant", "invariant", "symmetry", "representation"],
        ) {
            mark(Affordance::Symmetry);
        }
        if has(
            &lower,
            &["topolog", "continuous", "compact", "connected", "homotopy", "homology", "cohomology", "homeomorph"],
        ) {
            mark(Affordance::Topological);
        }
        if has(
            &lower,
            &["energy", "action", "lagrang", "hamilton", "variational", "euler_lagrange", "lyapunov", "functional"],
        ) {
            mark(Affordance::Variational);
        }
    }
    evidence
        .into_iter()
        .map(|(a, xs)| (a, xs.into_iter().collect()))
        .collect()
}

fn has(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|n| haystack.contains(n))
}

fn method_recognizers(method: &MethodSpec) -> Vec<Affordance> {
    let mut r = method.recognizes.clone();
    r.sort();
    r.dedup();
    r
}

fn compatibility_set(current: &BTreeSet<Affordance>, method: &MethodSpec) -> f64 {
    let recognizers = method_recognizers(method);
    fraction_present(current, &recognizers)
}

fn fraction_present(current: &BTreeSet<Affordance>, xs: &[Affordance]) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    xs.iter().filter(|a| current.contains(a)).count() as f64 / xs.len() as f64
}

fn match_method(
    current: &BTreeSet<Affordance>,
    method: &MethodSpec,
) -> (Vec<Affordance>, Vec<Affordance>) {
    let recognizers = method_recognizers(method);
    let mut matched = Vec::new();
    let mut missing = Vec::new();
    for a in recognizers {
        if current.contains(&a) {
            matched.push(a);
        } else {
            missing.push(a);
        }
    }
    (matched, missing)
}

fn jaccard_distance(a: &BTreeSet<Affordance>, b: &BTreeSet<Affordance>) -> f64 {
    let union = a.union(b).count();
    if union == 0 {
        return 0.0;
    }
    1.0 - a.intersection(b).count() as f64 / union as f64
}

fn diversify(mut candidates: Vec<MethodCandidate>, top: usize) -> Vec<MethodCandidate> {
    let mut selected = Vec::new();
    let mut family_counts: HashMap<&'static str, usize> = HashMap::new();
    while !candidates.is_empty() && selected.len() < top {
        let mut best_idx = 0usize;
        let mut best_score = f64::NEG_INFINITY;
        for (i, c) in candidates.iter().enumerate() {
            let repeats = family_counts.get(c.method.family).copied().unwrap_or(0);
            let penalty = 0.68_f64.powi(repeats as i32);
            let diversified = c.base_score * penalty;
            if diversified > best_score {
                best_score = diversified;
                best_idx = i;
            }
        }
        let mut c = candidates.remove(best_idx);
        c.score = best_score;
        *family_counts.entry(c.method.family).or_default() += 1;
        selected.push(c);
    }
    selected
}

fn cmp_f64(a: f64, b: f64) -> Ordering {
    a.partial_cmp(&b).unwrap_or(Ordering::Equal)
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
    fn profiles_are_recovered_from_elaborated_term_symbols() {
        let input = row(
            "Dynamics.foo",
            "Dynamics",
            &["ContinuousLinearMap", "deriv", "InnerProductSpace"],
        );
        let g = Graph::from_jsonl(&input).unwrap();
        let idx = IntuitionIndex::build(&g);
        let p = idx.profile("Dynamics.foo").unwrap();
        assert!(p.has(Affordance::Linear));
        assert!(p.has(Affordance::Operator));
        assert!(p.has(Affordance::Differential));
        assert!(p.has(Affordance::InnerProduct));
        assert!(p.symbols.contains("deriv"));
    }

    #[test]
    fn refracting_prefers_supported_methods_and_exposes_obligations() {
        let input = row(
            "Dynamics.foo",
            "Dynamics",
            &["ContinuousLinearMap", "deriv", "InnerProductSpace", "Flow"],
        );
        let g = Graph::from_jsonl(&input).unwrap();
        let idx = IntuitionIndex::build(&g);
        let proposals = idx.refract("Dynamics.foo", None, 8).unwrap();
        let spectral = proposals
            .iter()
            .find(|p| p.method == "spectralize")
            .unwrap();
        assert!(spectral.score > 0.0);
        assert!(spectral.unlocks.contains(&Affordance::Spectral));
        assert!(!spectral.obligations.is_empty());
        assert!(proposals.iter().any(|p| p.family != spectral.family));
    }

    #[test]
    fn failed_experience_penalizes_but_does_not_delete_a_method() {
        let input = row(
            "Dynamics.foo",
            "Dynamics",
            &["ContinuousLinearMap", "deriv", "InnerProductSpace", "Flow"],
        );
        let g = Graph::from_jsonl(&input).unwrap();
        let idx = IntuitionIndex::build(&g);
        let before = idx
            .candidates("Dynamics.foo", None, idx.methods().len())
            .unwrap()
            .into_iter()
            .find(|c| c.method.id == "spectralize")
            .unwrap();
        let exp = Experience::from_jsonl(
            r#"{"problem":"Dynamics.foo","method":"spectralize","outcome":"failed","reason":"no self-adjoint realization","step":1}"#,
        )
        .unwrap();
        let after = idx
            .candidates("Dynamics.foo", Some(&exp), idx.methods().len())
            .unwrap()
            .into_iter()
            .find(|c| c.method.id == "spectralize")
            .unwrap();
        assert!(after.base_score < before.base_score);
        assert_eq!(after.prior_attempts.len(), 1);
    }

    #[test]
    fn bridge_search_asks_for_language_transfer_not_statement_similarity() {
        let input = [
            row("Alg.foo", "Alg", &["CommRing", "Polynomial", "MulAction"]),
            row("Geo.bar", "Geo", &["Manifold", "TopologicalSpace", "Quotient"]),
        ]
        .join("\n");
        let g = Graph::from_jsonl(&input).unwrap();
        let idx = IntuitionIndex::build(&g);
        let bridges = idx.bridges("Alg", "Geo", 20);
        let b = bridges
            .iter()
            .find(|b| b.from == "Alg" && b.to == "Geo" && b.method.id == "geometrize")
            .unwrap();
        assert!(b.source_fit > 0.0);
        assert!(b.target_echo > 0.0);
    }

    #[test]
    fn dream_mines_ordered_method_motifs() {
        let exp = Experience::from_jsonl(
            r#"{"problem":"p1","method":"linearize","outcome":"succeeded","step":1}
{"problem":"p1","method":"spectralize","outcome":"succeeded","step":2}
{"problem":"p2","method":"linearize","outcome":"succeeded","step":1}
{"problem":"p2","method":"spectralize","outcome":"failed","step":2}"#,
        )
        .unwrap();
        let motifs = exp.motifs(2);
        assert_eq!(motifs.len(), 1);
        assert_eq!(motifs[0].first, "linearize");
        assert_eq!(motifs[0].second, "spectralize");
        assert_eq!(motifs[0].count, 2);
        assert_eq!(motifs[0].successes, 1);
    }
}
