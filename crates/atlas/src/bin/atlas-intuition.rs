//! `atlas-intuition` — research actions over Atlas viewpoint/affordance profiles.
//!
//! Output is diagnostic rather than declarative: scores expose their components, viewpoint
//! changes name obligations/losses, and corpus regularities are labelled as hypotheses.

use std::process::ExitCode;

use atlas::graph::Graph;
use atlas::intuition::{Affordance, Experience, IntuitionIndex, MethodSpec};
use atlas::intuition_benchmark::{run_benchmark, BenchmarkCase};
use atlas::intuition_concept::ConceptContext;
use atlas::intuition_viewpoint::{explore_viewpoints, pareto_methods, ExploreOptions};

const USAGE: &str = "\
usage: atlas-intuition <query> <slice.jsonl> [args] [options]

queries:
  profile <decl>          affordances recovered from the elaborated statement
  methods                 bootstrap method/viewpoint catalogue
  rank <decl>             diversified ranking of methods worth trying next
  pareto <decl>           non-dominated methods across fit/distance/novelty/breadth
  refract <decl>          proposed changes of representation, obligations, and losses
  explore <decl>          multi-step viewpoint graph (method sequences)
  auxiliary <decl>        missing auxiliary objects suggested by promising methods
  bridge <A> <B>          methods that could translate theory A toward B's language
  toy-worlds <decl>       finite/discrete/limit/linearized surrogate viewpoints
  concepts [prefix]       formal concepts over declaration × affordance incidence
  implications [prefix]   exact observed affordance implications (antecedent size <= 2)
  missing-cells A [B...]  globally common affordances absent from named theories
  benchmark <cases.jsonl> pre-registered top-k viewpoint/method benchmark
  dream                   recurrent adjacent method motifs in an experience ledger

options:
  --top N                 result/concept limit (default 10)
  --experience FILE       research-attempt JSONL overlay
  --depth N               viewpoint exploration depth (default 3)
  --beam N                viewpoint exploration beam width (default 12)
  --min-support N         implication support floor (default 2)
  --min-global F          missing-cell global support fraction (default 0.05)

Experience rows contain problem, method, outcome, optional reason, optional step.
Benchmark rows contain id, problem, expected_methods, optional top_k/excluded_methods.
Nothing printed by this tool is a theorem or a novelty claim.
";

fn main() -> ExitCode {
    match run(&std::env::args().skip(1).collect::<Vec<_>>()) {
        Ok(text) => {
            print!("{text}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("atlas-intuition: {e}");
            ExitCode::FAILURE
        }
    }
}

fn run(args: &[String]) -> Result<String, String> {
    let options = take_options(args)?;
    let (query, rest) = options.rest.split_first().ok_or_else(|| USAGE.to_string())?;
    let (path, rest) = rest.split_first().ok_or_else(|| USAGE.to_string())?;
    let input = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    let graph = Graph::from_jsonl(&input).map_err(|e| e.to_string())?;
    let index = IntuitionIndex::build(&graph);
    let experience = load_experience(options.experience_path.as_deref())?;

    match query.as_str() {
        "profile" => {
            let [decl] = rest else {
                return Err("profile takes one declaration".into());
            };
            let profile = index
                .profile(decl)
                .ok_or_else(|| format!("`{decl}` has no encoded viewpoint profile"))?;
            let breadth = index.method_breadth(decl).unwrap_or(0);
            let mut out = format!(
                "{}\nmodule: {}\nmethod breadth: {}\n\n",
                profile.declaration, profile.module, breadth
            );
            for (affordance, evidence) in &profile.evidence {
                out.push_str(&format!(
                    "{:<18} {:>3}  {}\n",
                    affordance.name(),
                    evidence.len(),
                    evidence
                        .iter()
                        .take(6)
                        .cloned()
                        .collect::<Vec<_>>()
                        .join(", ")
                ));
            }
            Ok(out)
        }
        "methods" => {
            if !rest.is_empty() {
                return Err("methods takes no arguments after the slice".into());
            }
            let mut out = String::new();
            for method in index.methods() {
                out.push_str(&format!(
                    "{:<22} {:<20} {}\n",
                    method.id, method.family, method.label
                ));
            }
            Ok(out)
        }
        "rank" | "intuition" => {
            let [decl] = rest else {
                return Err("rank takes one declaration".into());
            };
            render_rank(
                &index,
                decl,
                experience.as_ref(),
                options.top,
            )
        }
        "pareto" => {
            let [decl] = rest else {
                return Err("pareto takes one declaration".into());
            };
            let mut out = String::from(
                "# non-dominated research moves; no scalar utility assumed\n",
            );
            for p in pareto_methods(&index, decl, experience.as_ref())? {
                let c = p.candidate;
                out.push_str(&format!(
                    "{:.3}  {:<22} strengths [{}]\n",
                    c.score,
                    c.method.id,
                    p.strengths.join(", ")
                ));
                out.push_str(&format!(
                    "       fit {:.2} dist {:.2} bridge {:.2} novel {:.2} breadth +{} exp {:.2}\n",
                    c.compatibility,
                    c.domain_distance,
                    c.bridge_value,
                    c.novelty,
                    c.breadth_gain,
                    c.experience_factor
                ));
            }
            Ok(out)
        }
        "refract" | "viewpoints" => {
            let [decl] = rest else {
                return Err("refract takes one declaration".into());
            };
            let mut out = String::new();
            for (i, proposal) in index
                .refract(decl, experience.as_ref(), options.top)?
                .into_iter()
                .enumerate()
            {
                out.push_str(&format!(
                    "{}. {:.3}  {} [{}]\n   {}\n",
                    i + 1,
                    proposal.score,
                    proposal.method,
                    proposal.family,
                    proposal.label
                ));
                out.push_str(&format!(
                    "   sees: {}\n   opens: {}  (method breadth +{})\n",
                    names(&proposal.matched),
                    names(&proposal.unlocks),
                    proposal.breadth_gain
                ));
                if let Some(aux) = &proposal.auxiliary {
                    out.push_str(&format!("   auxiliary: {aux}\n"));
                }
                for obligation in &proposal.obligations {
                    out.push_str(&format!("   obligation: {obligation}\n"));
                }
                for loss in &proposal.losses {
                    out.push_str(&format!("   loss: {loss}\n"));
                }
                for attempt in &proposal.prior_attempts {
                    out.push_str(&format!(
                        "   prior: {}{}\n",
                        attempt.outcome.name(),
                        if attempt.reason.is_empty() {
                            String::new()
                        } else {
                            format!(" — {}", attempt.reason)
                        }
                    ));
                }
                out.push('\n');
            }
            Ok(out)
        }
        "explore" => {
            let [decl] = rest else {
                return Err("explore takes one declaration".into());
            };
            let viewpoints = explore_viewpoints(
                &index,
                decl,
                experience.as_ref(),
                &ExploreOptions {
                    max_depth: options.depth,
                    beam_width: options.beam,
                    ..ExploreOptions::default()
                },
            )?;
            let mut out = format!(
                "# viewpoint graph: {} nodes, {} edges; depth <= {}, beam {}\n",
                viewpoints.nodes.len(),
                viewpoints.edges.len(),
                options.depth,
                options.beam
            );
            for node in viewpoints.best(options.top) {
                out.push_str(&format!(
                    "{:.4}  depth {} breadth {}  {}\n",
                    node.score,
                    node.depth,
                    node.method_breadth,
                    node.path.join(" -> ")
                ));
                out.push_str(&format!(
                    "        affordances [{}]\n",
                    names_set(&node.affordances)
                ));
                if !node.obligations.is_empty() {
                    out.push_str(&format!(
                        "        obligations: {}\n",
                        node.obligations.join("; ")
                    ));
                }
                if !node.losses.is_empty() {
                    out.push_str(&format!("        losses: {}\n", node.losses.join("; ")));
                }
            }
            Ok(out)
        }
        "auxiliary" => {
            let [decl] = rest else {
                return Err("auxiliary takes one declaration".into());
            };
            let mut out = String::new();
            for candidate in
                index.missing_auxiliaries(decl, experience.as_ref(), options.top)?
            {
                out.push_str(&format!(
                    "{:.3}  {}\n       {}\n",
                    candidate.score, candidate.method, candidate.object
                ));
                for obligation in candidate.obligations {
                    out.push_str(&format!("       obligation: {obligation}\n"));
                }
            }
            Ok(out)
        }
        "bridge" => {
            let [left, right] = rest else {
                return Err("bridge takes two theory/module prefixes".into());
            };
            let l = index.theory_profile(left);
            let r = index.theory_profile(right);
            if l.declarations == 0 {
                return Err(format!("no encoded declarations under `{left}`"));
            }
            if r.declarations == 0 {
                return Err(format!("no encoded declarations under `{right}`"));
            }
            let mut out = format!(
                "# {} declarations in {}; {} in {}\n# bridge = source method fit × target output-language echo × domain distance\n",
                l.declarations, left, r.declarations, right
            );
            for bridge in index.bridges(left, right, options.top) {
                out.push_str(&format!(
                    "{:.3}  {:<20} {} -> {}  fit {:.2} echo {:.2}\n",
                    bridge.score,
                    bridge.method.id,
                    bridge.from,
                    bridge.to,
                    bridge.source_fit,
                    bridge.target_echo
                ));
                out.push_str(&format!(
                    "       shared [{}]; opens [{}]\n",
                    names(&bridge.shared),
                    names(&bridge.method.unlocks)
                ));
                if let Some(aux) = bridge.method.auxiliary {
                    out.push_str(&format!("       try constructing: {aux}\n"));
                }
            }
            Ok(out)
        }
        "toy-worlds" => {
            let [decl] = rest else {
                return Err("toy-worlds takes one declaration".into());
            };
            let mut out = String::new();
            for proposal in index.toy_worlds(decl, experience.as_ref(), options.top)? {
                out.push_str(&format!(
                    "{:.3}  {:<22} {}\n",
                    proposal.score, proposal.method, proposal.label
                ));
                if let Some(aux) = proposal.auxiliary {
                    out.push_str(&format!("       model: {aux}\n"));
                }
                out.push_str(&format!(
                    "       must preserve: {}\n",
                    proposal.obligations.join("; ")
                ));
                out.push_str(&format!(
                    "       known loss: {}\n",
                    proposal.losses.join("; ")
                ));
            }
            Ok(out)
        }
        "concepts" => {
            if rest.len() > 1 {
                return Err("concepts takes at most one theory/module prefix".into());
            }
            let prefix = rest.first().map(String::as_str);
            let context = ConceptContext::build(&graph, &index, prefix);
            let lattice = context.concepts(options.top);
            let mut out = format!(
                "# FCA context: {} declarations; {} concepts{}; {} cover edges\n",
                context.len(),
                lattice.concepts.len(),
                if lattice.truncated { " (truncated)" } else { "" },
                lattice.covers.len()
            );
            for (i, concept) in lattice.concepts.iter().enumerate() {
                out.push_str(&format!(
                    "{:>4} support {:>6}  [{}]\n",
                    i,
                    concept.extent.len(),
                    names(&concept.intent)
                ));
                if concept.extent.len() <= 6 {
                    out.push_str(&format!("     {}\n", concept.extent.join(", ")));
                }
            }
            Ok(out)
        }
        "implications" => {
            if rest.len() > 1 {
                return Err("implications takes at most one theory/module prefix".into());
            }
            let prefix = rest.first().map(String::as_str);
            let context = ConceptContext::build(&graph, &index, prefix);
            let mut out = format!(
                "# exact implications in extracted affordance context; n={} (not mathematical theorems)\n",
                context.len()
            );
            for rule in context
                .implications(2, options.min_support)
                .into_iter()
                .take(options.top)
            {
                out.push_str(&format!(
                    "support {:>6} ({:>6.2}%)  [{}] => [{}]\n",
                    rule.support,
                    100.0 * rule.support_fraction,
                    names(&rule.antecedent),
                    names(&rule.consequent)
                ));
            }
            Ok(out)
        }
        "missing-cells" => {
            if rest.is_empty() {
                return Err("missing-cells takes one or more theory/module prefixes".into());
            }
            let cells = ConceptContext::missing_cells(
                &graph,
                &index,
                rest,
                options.min_global,
            );
            let mut out = String::from(
                "# structural absences only; a missing cell becomes a research question only with independent neighborhood/alignment evidence\n",
            );
            for cell in cells.into_iter().take(options.top) {
                out.push_str(&format!(
                    "{:<28} {:<18} global {:>6} ({:>6.2}%) local 0\n",
                    cell.theory,
                    cell.affordance.name(),
                    cell.global_support,
                    100.0 * cell.global_fraction
                ));
            }
            Ok(out)
        }
        "benchmark" => {
            let [cases_path] = rest else {
                return Err("benchmark takes one answer-key JSONL path".into());
            };
            let cases_text = std::fs::read_to_string(cases_path)
                .map_err(|e| format!("{cases_path}: {e}"))?;
            let cases = BenchmarkCase::from_jsonl(&cases_text)?;
            let report = run_benchmark(&index, &cases, experience.as_ref())?;
            let mut out = format!(
                "# cases {} hits {} hit-rate {:.3} MRR {:.3}\n",
                report.cases.len(),
                report.hits,
                report.hit_rate,
                report.mean_reciprocal_rank
            );
            for result in report.cases {
                out.push_str(&format!(
                    "{}  {}  rank {}  expected [{}]\n",
                    if result.hit { "HIT " } else { "MISS" },
                    result.id,
                    result
                        .rank
                        .map(|r| r.to_string())
                        .unwrap_or_else(|| "none".to_string()),
                    result.expected_methods.join(", ")
                ));
                out.push_str(&format!(
                    "      top [{}]\n",
                    result.top_methods.join(", ")
                ));
            }
            Ok(out)
        }
        "dream" => {
            if !rest.is_empty() {
                return Err("dream takes no arguments after the slice".into());
            }
            let experience = experience
                .as_ref()
                .ok_or("dream needs --experience with ordered records carrying `step`")?;
            let mut out = String::from(
                "# recurrent research-action motifs; candidates for later MDL/grammar promotion\n",
            );
            for motif in experience.motifs(2).into_iter().take(options.top) {
                out.push_str(&format!(
                    "{:>4}  {:>4} success  {} -> {}\n",
                    motif.count, motif.successes, motif.first, motif.second
                ));
            }
            Ok(out)
        }
        other => Err(format!("unknown query `{other}`\n\n{USAGE}")),
    }
}

fn render_rank(
    index: &IntuitionIndex,
    decl: &str,
    experience: Option<&Experience>,
    top: usize,
) -> Result<String, String> {
    let mut out = String::new();
    for candidate in index.candidates(decl, experience, top)? {
        out.push_str(&format!(
            "{:.3}  {:<22} fit {:.2} dist {:.2} bridge {:.2} novel {:.2} breadth +{} exp {:.2}\n",
            candidate.score,
            candidate.method.id,
            candidate.compatibility,
            candidate.domain_distance,
            candidate.bridge_value,
            candidate.novelty,
            candidate.breadth_gain,
            candidate.experience_factor,
        ));
        out.push_str(&format!(
            "       sees [{}]  opens [{}]\n",
            names(&candidate.matched),
            names(&candidate.method.unlocks)
        ));
        for attempt in &candidate.prior_attempts {
            out.push_str(&format!(
                "       prior {}{}\n",
                attempt.outcome.name(),
                if attempt.reason.is_empty() {
                    String::new()
                } else {
                    format!(": {}", attempt.reason)
                }
            ));
        }
    }
    Ok(out)
}

fn names(xs: &[Affordance]) -> String {
    xs.iter().map(|a| a.name()).collect::<Vec<_>>().join(", ")
}

fn names_set(xs: &std::collections::BTreeSet<Affordance>) -> String {
    xs.iter().map(|a| a.name()).collect::<Vec<_>>().join(", ")
}

fn load_experience(path: Option<&str>) -> Result<Option<Experience>, String> {
    let Some(path) = path else {
        return Ok(None);
    };
    let input = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    Experience::from_jsonl(&input).map(Some)
}

struct Options {
    top: usize,
    experience_path: Option<String>,
    depth: usize,
    beam: usize,
    min_support: usize,
    min_global: f64,
    rest: Vec<String>,
}

fn take_options(args: &[String]) -> Result<Options, String> {
    let mut top = 10usize;
    let mut experience_path = None;
    let mut depth = 3usize;
    let mut beam = 12usize;
    let mut min_support = 2usize;
    let mut min_global = 0.05_f64;
    let mut rest = Vec::new();
    let mut it = args.iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--top" => {
                let value = it.next().ok_or("--top takes a number")?;
                top = value
                    .parse()
                    .map_err(|_| format!("`{value}` is not a number"))?;
            }
            "--experience" => {
                experience_path = Some(
                    it.next()
                        .ok_or("--experience takes a JSONL path")?
                        .clone(),
                );
            }
            "--depth" => {
                let value = it.next().ok_or("--depth takes a number")?;
                depth = value
                    .parse()
                    .map_err(|_| format!("`{value}` is not a number"))?;
            }
            "--beam" => {
                let value = it.next().ok_or("--beam takes a number")?;
                beam = value
                    .parse()
                    .map_err(|_| format!("`{value}` is not a number"))?;
            }
            "--min-support" => {
                let value = it.next().ok_or("--min-support takes a number")?;
                min_support = value
                    .parse()
                    .map_err(|_| format!("`{value}` is not a number"))?;
            }
            "--min-global" => {
                let value = it.next().ok_or("--min-global takes a fraction")?;
                min_global = value
                    .parse()
                    .map_err(|_| format!("`{value}` is not a fraction"))?;
                if !(0.0..=1.0).contains(&min_global) {
                    return Err("--min-global must be between 0 and 1".into());
                }
            }
            "--help" | "-h" => return Err(USAGE.to_string()),
            _ => rest.push(arg.clone()),
        }
    }
    Ok(Options {
        top,
        experience_path,
        depth,
        beam,
        min_support,
        min_global,
        rest,
    })
}

#[allow(dead_code)]
fn _method_summary(method: &MethodSpec) -> String {
    format!("{} [{}]: {}", method.id, method.family, method.label)
}
