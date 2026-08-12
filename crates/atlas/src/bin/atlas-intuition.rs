//! `atlas-intuition` — research actions over Atlas viewpoint/affordance profiles.
//!
//! The output is deliberately diagnostic rather than declarative: scores expose their
//! components, viewpoint changes name their obligations and losses, and bridge results are
//! labelled as proposals rather than mathematical correspondences.

use std::process::ExitCode;

use atlas::graph::Graph;
use atlas::intuition::{Affordance, Experience, IntuitionIndex, MethodSpec};

const USAGE: &str = "\
usage: atlas-intuition <query> <slice.jsonl> [args] [--top N] [--experience attempts.jsonl]

queries:
  profile <decl>       affordances recovered from the elaborated statement
  methods              bootstrap method/viewpoint catalogue
  rank <decl>          diversified ranking of methods worth trying next
  refract <decl>       proposed changes of representation, with obligations/losses
  auxiliary <decl>     missing auxiliary objects suggested by promising methods
  bridge <A> <B>       methods that could translate theory A toward B's language (and back)
  toy-worlds <decl>    finite/discrete/limit/linearized surrogate viewpoints
  dream                recurrent adjacent method motifs in an ordered experience ledger

`--experience` takes JSONL rows with problem, method, outcome, optional reason, optional step.
Failures penalize but never silently delete a route; refutations get the strongest penalty.
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
    let Options {
        top,
        experience_path,
        rest,
    } = take_options(args)?;
    let (query, rest) = rest.split_first().ok_or_else(|| USAGE.to_string())?;
    let (path, rest) = rest.split_first().ok_or_else(|| USAGE.to_string())?;
    let input = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    let graph = Graph::from_jsonl(&input).map_err(|e| e.to_string())?;
    let idx = IntuitionIndex::build(&graph);
    let experience = load_experience(experience_path.as_deref())?;

    match query.as_str() {
        "profile" => {
            let [decl] = rest else {
                return Err("profile takes one declaration".into());
            };
            let p = idx
                .profile(decl)
                .ok_or_else(|| format!("`{decl}` has no encoded viewpoint profile"))?;
            let breadth = idx.method_breadth(decl).unwrap_or(0);
            let mut out = format!(
                "{}\nmodule: {}\nmethod breadth: {}\n\n",
                p.declaration, p.module, breadth
            );
            for (a, evidence) in &p.evidence {
                out.push_str(&format!(
                    "{:<18} {:>3}  {}\n",
                    a.name(),
                    evidence.len(),
                    evidence.iter().take(6).cloned().collect::<Vec<_>>().join(", ")
                ));
            }
            Ok(out)
        }
        "methods" => {
            if !rest.is_empty() {
                return Err("methods takes no arguments after the slice".into());
            }
            let mut out = String::new();
            for m in idx.methods() {
                out.push_str(&format!(
                    "{:<22} {:<20} {}\n",
                    m.id, m.family, m.label
                ));
            }
            Ok(out)
        }
        "rank" | "intuition" => {
            let [decl] = rest else {
                return Err("rank takes one declaration".into());
            };
            let mut out = String::new();
            for c in idx.candidates(decl, experience.as_ref(), top)? {
                out.push_str(&format!(
                    "{:.3}  {:<22} fit {:.2} dist {:.2} bridge {:.2} novel {:.2} breadth +{} exp {:.2}\n",
                    c.score,
                    c.method.id,
                    c.compatibility,
                    c.domain_distance,
                    c.bridge_value,
                    c.novelty,
                    c.breadth_gain,
                    c.experience_factor,
                ));
                out.push_str(&format!(
                    "       sees [{}]  opens [{}]\n",
                    names(&c.matched),
                    names(&c.method.unlocks)
                ));
                if !c.prior_attempts.is_empty() {
                    for a in &c.prior_attempts {
                        out.push_str(&format!(
                            "       prior {}{}\n",
                            a.outcome.name(),
                            if a.reason.is_empty() {
                                String::new()
                            } else {
                                format!(": {}", a.reason)
                            }
                        ));
                    }
                }
            }
            Ok(out)
        }
        "refract" | "viewpoints" => {
            let [decl] = rest else {
                return Err("refract takes one declaration".into());
            };
            let mut out = String::new();
            for (i, p) in idx
                .refract(decl, experience.as_ref(), top)?
                .into_iter()
                .enumerate()
            {
                out.push_str(&format!(
                    "{}. {:.3}  {} [{}]\n   {}\n",
                    i + 1,
                    p.score,
                    p.method,
                    p.family,
                    p.label
                ));
                out.push_str(&format!(
                    "   sees: {}\n   opens: {}  (method breadth +{})\n",
                    names(&p.matched),
                    names(&p.unlocks),
                    p.breadth_gain
                ));
                if let Some(aux) = &p.auxiliary {
                    out.push_str(&format!("   auxiliary: {aux}\n"));
                }
                for obligation in &p.obligations {
                    out.push_str(&format!("   obligation: {obligation}\n"));
                }
                for loss in &p.losses {
                    out.push_str(&format!("   loss: {loss}\n"));
                }
                if !p.prior_attempts.is_empty() {
                    for a in &p.prior_attempts {
                        out.push_str(&format!(
                            "   prior: {}{}\n",
                            a.outcome.name(),
                            if a.reason.is_empty() {
                                String::new()
                            } else {
                                format!(" — {}", a.reason)
                            }
                        ));
                    }
                }
                out.push('\n');
            }
            Ok(out)
        }
        "auxiliary" => {
            let [decl] = rest else {
                return Err("auxiliary takes one declaration".into());
            };
            let mut out = String::new();
            for a in idx.missing_auxiliaries(decl, experience.as_ref(), top)? {
                out.push_str(&format!("{:.3}  {}\n       {}\n", a.score, a.method, a.object));
                for obligation in a.obligations {
                    out.push_str(&format!("       obligation: {obligation}\n"));
                }
            }
            Ok(out)
        }
        "bridge" => {
            let [left, right] = rest else {
                return Err("bridge takes two theory/module prefixes".into());
            };
            let l = idx.theory_profile(left);
            let r = idx.theory_profile(right);
            if l.declarations == 0 {
                return Err(format!("no encoded declarations under `{left}`"));
            }
            if r.declarations == 0 {
                return Err(format!("no encoded declarations under `{right}`"));
            }
            let mut out = format!(
                "# {} declarations in {}; {} in {}\n# bridge = method fit on source × output already useful on target × domain distance\n",
                l.declarations, left, r.declarations, right
            );
            for b in idx.bridges(left, right, top) {
                out.push_str(&format!(
                    "{:.3}  {:<20} {} -> {}  fit {:.2} echo {:.2}\n",
                    b.score, b.method.id, b.from, b.to, b.source_fit, b.target_echo
                ));
                out.push_str(&format!(
                    "       shared [{}]; opens [{}]\n",
                    names(&b.shared),
                    names(&b.method.unlocks)
                ));
                if let Some(aux) = b.method.auxiliary {
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
            for p in idx.toy_worlds(decl, experience.as_ref(), top)? {
                out.push_str(&format!(
                    "{:.3}  {:<22} {}\n",
                    p.score, p.method, p.label
                ));
                if let Some(aux) = p.auxiliary {
                    out.push_str(&format!("       model: {aux}\n"));
                }
                out.push_str(&format!("       must preserve: {}\n", p.obligations.join("; ")));
                out.push_str(&format!("       known loss: {}\n", p.losses.join("; ")));
            }
            Ok(out)
        }
        "dream" => {
            if !rest.is_empty() {
                return Err("dream takes no arguments after the slice".into());
            }
            let experience = experience.as_ref().ok_or(
                "dream needs --experience with ordered records carrying `step`",
            )?;
            let mut out = String::from(
                "# recurrent research-action motifs; candidates for later MDL/grammar promotion\n",
            );
            for m in experience.motifs(2).into_iter().take(top) {
                out.push_str(&format!(
                    "{:>4}  {:>4} success  {} -> {}\n",
                    m.count, m.successes, m.first, m.second
                ));
            }
            Ok(out)
        }
        other => Err(format!("unknown query `{other}`\n\n{USAGE}")),
    }
}

fn names(xs: &[Affordance]) -> String {
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
    rest: Vec<String>,
}

fn take_options(args: &[String]) -> Result<Options, String> {
    let mut top = 10usize;
    let mut experience_path = None;
    let mut rest = Vec::new();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--top" => {
                let v = it.next().ok_or("--top takes a number")?;
                top = v.parse().map_err(|_| format!("`{v}` is not a number"))?;
            }
            "--experience" => {
                experience_path = Some(
                    it.next()
                        .ok_or("--experience takes a JSONL path")?
                        .clone(),
                );
            }
            "--help" | "-h" => return Err(USAGE.to_string()),
            _ => rest.push(a.clone()),
        }
    }
    Ok(Options {
        top,
        experience_path,
        rest,
    })
}

#[allow(dead_code)]
fn _method_summary(m: &MethodSpec) -> String {
    format!("{} [{}]: {}", m.id, m.family, m.label)
}
