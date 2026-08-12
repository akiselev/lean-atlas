//! `atlas` — queries over an extraction (atlas.md §2, B2).
//!
//! ```text
//! lake exe atlas_extract Mathlib.Logic.Basic > slice.jsonl
//! atlas why  slice.jsonl Nat.Prime.dvd_mul Nat.Prime
//! atlas foundations slice.jsonl Nat.Prime.dvd_mul
//! atlas impact      slice.jsonl Nat.Prime
//! atlas walls       slice.jsonl
//! ```
//!
//! Every query takes a `--lens` of `statement`, `proof` or `both` (default). The lens is
//! not a detail: what a *claim* rests on and what an *argument* rests on are different
//! questions, and B1 emits them as separate edge sets precisely so a query can ask one
//! without the other.

use std::process::ExitCode;

use atlas::dict::{DictOptions, Transported, dictionary, frontier, transport};
use atlas::equiv::EquivIndex;
use atlas::graph::{Graph, Lens};
use atlas::logical::LogicalGraph;
use atlas::skel::erase::Level;
use atlas::skel::index::{IndexConfig, SkeletonIndex};

const USAGE: &str = "\
usage: atlas <query> <slice.jsonl> [args] [--lens statement|proof|both]

queries:
  why <from> <to>     a shortest dependency chain from <from> down to <to>
  foundations <name>  everything <name> transitively rests on
  impact <name>       everything that transitively rests on <name>
  walls               declarations ranked by how many others cite them
  honesty [axiom...]  declarations resting on `sorryAx` or on an axiom outside the
                      whitelist; exits non-zero if any are found
  equivalent <decl>   declarations whose statements normalize to the same thing
  classes             every equivalence class of size > 1, largest first
  relations [d|a b]   proved Iff/implication edges: densest heads, one theorem's
                      edges, or a chain of proved steps between two `Head/arity`
  dictionary <A> <B>  skeleton-matched rows between two theories, plus what is unmatched
  transport <l> <r> <s>  apply the row (l ~ r) to statement s
  frontier            theory pairs that look alike and do not cite each other
  similar <decl>      declarations whose statements anti-unify with this one
  skeleton <decl>     the rendered erasure of one statement
  stats               size of the slice, and how much of it encodes

`similar` and `skeleton` take `--level exact|presentation|instances|carriers|shape`,
which chooses how much to erase before comparing; `--top N`; and `--brute` to skip the
index and compare against every declaration (slow, and the differential reference).

`dictionary` and `frontier` restrict to theorems unless `--all-kinds`; `frontier` takes
`--exclude A,B` to drop infrastructure namespaces.

The lens selects which edges are walked: `statement` is what claims rest on, `proof` is
what arguments rest on, `both` is the citation graph. Default: both.
";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        // `honesty` reports findings on stdout and still exits non-zero — the findings are
        // the answer, not an error, but CI has to be able to fail on them.
        Ok(Report { text, clean }) => {
            print!("{text}");
            if clean {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            }
        }
        Err(msg) => {
            eprintln!("atlas: {msg}");
            ExitCode::FAILURE
        }
    }
}

/// A query's output, and whether it should exit zero.
struct Report {
    text: String,
    clean: bool,
}

impl From<String> for Report {
    fn from(text: String) -> Report {
        Report { text, clean: true }
    }
}

fn run(args: &[String]) -> Result<Report, String> {
    let Options {
        lens,
        level: level_opt,
        top,
        brute,
        all_kinds,
        exclude,
        rest,
    } = take_options(args)?;
    let (query, rest) = rest.split_first().ok_or_else(|| USAGE.to_string())?;
    let (path, rest) = rest.split_first().ok_or_else(|| USAGE.to_string())?;
    let input = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    let g = Graph::from_jsonl(&input).map_err(|e| e.to_string())?;

    match query.as_str() {
        "why" => {
            let [from, to] = rest else {
                return Err("why takes two declaration names".into());
            };
            known(&g, from)?;
            match g.why(from, to, lens) {
                // The chain is printed one name per line rather than joined, because the
                // thing an agent does next is read it top to bottom.
                Some(path) => Ok((path.join("\n") + "\n").into()),
                None => Err(format!(
                    "no dependency chain from `{from}` to `{to}` in this slice"
                )),
            }
        }
        "foundations" => {
            let [name] = rest else {
                return Err("foundations takes one declaration name".into());
            };
            known(&g, name)?;
            Ok(lines(g.foundations(name, lens)).into())
        }
        "impact" => {
            let [name] = rest else {
                return Err("impact takes one declaration name".into());
            };
            // Not `known`: asking what rests on something outside the slice is a fair
            // question, and the answer is the part of the slice that cites it.
            Ok(lines(g.impact(name, lens)).into())
        }
        "walls" => {
            let mut out = String::new();
            // Direct citations, not transitive impact: ranking a whole slice
            // transitively is one BFS per node, and a Mathlib slice is 75,000 of them.
            // Ask `impact <name>` for the transitive answer about one declaration.
            for (name, n) in g.ranked_by_citations(lens).into_iter().take(20) {
                if n == 0 {
                    break;
                }
                out.push_str(&format!("{n:>6}  {name}\n"));
            }
            Ok(out.into())
        }
        "honesty" => {
            // C5's transitive-sorry scan, which the dependency graph answers directly:
            // everything resting on `sorryAx` is its impact under the proof lens. The
            // scan is *transitive* on purpose — a complete-looking theorem one step above
            // a hole is not complete, and that is the case anti-cheat exists to catch.
            let mut findings: Vec<(String, String)> = g
                .impact("sorryAx", Lens::Proof)
                .into_iter()
                .map(|n| (n, "sorryAx".to_string()))
                .collect();
            // The whitelist is the axioms an argument may rest on. Default: Lean's own
            // three, which everything classical uses. Anything else is named.
            let allowed: Vec<String> = if rest.is_empty() {
                ["propext", "Classical.choice", "Quot.sound"]
                    .iter()
                    .map(|s| s.to_string())
                    .collect()
            } else {
                rest.to_vec()
            };
            for name in g.names() {
                if g.get(name).is_some_and(|d| d.kind == "axiom")
                    && !allowed.contains(name)
                    && name != "sorryAx"
                {
                    // The axiom itself, then its users — matching the binding, which
                    // gained the self-finding first: on an axiom-only corpus (B7's
                    // genre) every axiom is a graph leaf, `impact` is empty, and
                    // users-only reported zero findings on a corpus that is nothing
                    // but assertions. The 13-row disagreement between the two routes
                    // was caught by the smoke differential, which is its job.
                    findings.push((name.clone(), name.clone()));
                    for user in g.impact(name, Lens::Proof) {
                        findings.push((user, name.clone()));
                    }
                }
            }
            findings.sort();
            findings.dedup();
            if findings.is_empty() {
                return Ok(format!("honesty: clean — {} declarations\n", g.len()).into());
            }
            let mut out = String::new();
            for (who, why) in &findings {
                out.push_str(&format!("{who}  rests on  {why}\n"));
            }
            out.push_str(&format!("honesty: {} finding(s)\n", findings.len()));
            Ok(Report {
                text: out,
                clean: false,
            })
        }
        "equivalent" => {
            let [decl] = rest else {
                return Err("equivalent takes one declaration name".into());
            };
            let mut idx = EquivIndex::build(&input).map_err(|e| e.to_string())?;
            // Coarser than `carriers` is `similar`'s job, not this one: at `shape`
            // "equivalent" would mean "same skeleton", which is a different question.
            let level = level_opt.unwrap_or(Level::Instances);
            if level > Level::Carriers {
                return Err("equivalent stops at `carriers`; use `similar` for `shape`".into());
            }
            let members = idx.equivalent(decl, level).map_err(|e| e.to_string())?;
            if members.is_empty() {
                return Ok(format!("`{decl}` is alone at `{}`\n", level.name()).into());
            }
            let mut out = String::new();
            for m in members {
                out.push_str(&format!("{:<52} {}\n", m, idx.module_of(&m).unwrap_or("")));
            }
            Ok(out.into())
        }
        // The proved layer, kept separate from `equivalent`'s structural one on purpose:
        // one reports equality of a canonical form, the other reports that somebody
        // proved something. Merging the two output shapes would merge the claims.
        "relations" => {
            let idx = EquivIndex::build(&input).map_err(|e| e.to_string())?;
            let g = LogicalGraph::build(&idx);
            let s = g.stats();
            let mut out = format!(
                "{} proved edges over {} heads — {} Iff, {} implication\n\
                 {} sides unsupported (flex head), {} rejected as non-Prop\n\n",
                g.len(),
                g.heads(),
                s.iff_edges,
                s.implication_edges,
                s.flex_head_sides,
                s.non_prop_sides
            );
            match rest {
                // No argument: where the corpus's logical structure is densest.
                [] => {
                    for ((h, arity), n) in g.busiest(top) {
                        out.push_str(&format!("{n:>6}  {h}/{arity}\n"));
                    }
                }
                // A declaration name: the edges that theorem itself proves.
                [decl] => {
                    let edges = g.edges_of(decl);
                    if edges.is_empty() {
                        out.push_str(&format!(
                            "`{decl}` states neither an `Iff` nor an implication between \
                             propositions, so it contributes no proved edge\n"
                        ));
                    }
                    for r in edges {
                        out.push_str(&format!("{}\n", r.explain()));
                    }
                }
                // Two heads: a chain of proved steps, with its caveat attached.
                [from, to] => {
                    let parse = |s: &str| -> Result<(String, usize), String> {
                        let (h, a) = s.rsplit_once('/').ok_or_else(|| {
                            format!("`{s}` must be a head and arity, e.g. `LE.le/4`")
                        })?;
                        Ok((
                            h.to_string(),
                            a.parse().map_err(|_| "arity must be a number")?,
                        ))
                    };
                    let (a, b) = (parse(from)?, parse(to)?);
                    match g.path(&a, &b) {
                        None => out.push_str("no chain of proved edges in this slice\n"),
                        Some(c) if c.is_empty() => out.push_str("the same head\n"),
                        Some(chain) => {
                            for r in &chain {
                                out.push_str(&format!("{}\n", r.explain()));
                            }
                            out.push_str(
                                "\nEach step is proved. The chain is not: heads are \
                                 carrier-blind, so the steps need not share a carrier. \
                                 Read the witnesses' namespaces.\n",
                            );
                        }
                    }
                }
                _ => return Err("relations takes zero, one, or two arguments".into()),
            }
            Ok(out.into())
        }
        "classes" => {
            let mut idx = EquivIndex::build(&input).map_err(|e| e.to_string())?;
            let level = level_opt.unwrap_or(Level::Instances);
            let mut out = String::new();
            for (n, members) in idx.classes(level, true, true).into_iter().take(top) {
                out.push_str(&format!("{n:>4}  {}\n", members.join(", ")));
            }
            Ok(out.into())
        }
        "dictionary" => {
            let [left, right] = rest else {
                return Err("dictionary takes two theory prefixes".into());
            };
            let cfg = IndexConfig::default();
            let mut idx = SkeletonIndex::build(&input, &cfg).map_err(|e| e.to_string())?;
            let opts = DictOptions {
                theorems_only: !all_kinds,
                // The exclusions are opt-in on the CLI so the default output stays
                // comparable with what was measured before them.
                exclude_subprefix: exclude.clone(),
                ..DictOptions::default()
            };
            let d = dictionary(&mut idx, None, left, right, &cfg, &opts);
            let mut out = String::new();
            for r in d.rows.iter().take(top) {
                out.push_str(&format!(
                    "{:.2} {:<14} {:<40} ~ {}{}\n",
                    r.retention,
                    r.status.name(),
                    r.left,
                    r.right,
                    if r.transportable { "" } else { "  (scoped)" }
                ));
            }
            // The missing-entry report is the point of the exercise, so it is not
            // optional output.
            out.push_str(&format!(
                "\n{} rows; unmatched: {} in {}, {} in {}\n",
                d.rows.len(),
                d.missing_left.len(),
                d.left_theory,
                d.missing_right.len(),
                d.right_theory
            ));
            Ok(out.into())
        }
        "transport" => {
            let [l, r, subject] = rest else {
                return Err("transport takes a row (two names) and a subject".into());
            };
            let cfg = IndexConfig::default();
            let mut idx = SkeletonIndex::build(&input, &cfg).map_err(|e| e.to_string())?;
            let level = level_opt.unwrap_or(Level::Carriers);
            match transport(&mut idx, l, r, subject, level).map_err(|e| e.to_string())? {
                // Existing strengthens the dictionary; open is the directed target, and
                // the next step on it is falsification rather than proof — refutation is
                // cheap and locates the analogy's boundary.
                Transported::Exists { name, .. } => Ok(format!("exists: `{name}`\n").into()),
                Transported::Open { image } => {
                    Ok(format!("open target (falsify before proving):\n{image}\n").into())
                }
            }
        }
        "frontier" => {
            let cfg = IndexConfig::default();
            let mut idx = SkeletonIndex::build(&input, &cfg).map_err(|e| e.to_string())?;
            let graph = Graph::from_jsonl(&input).map_err(|e| e.to_string())?;
            let mut out = String::new();
            for f in frontier(&mut idx, &graph, 200, top, !all_kinds, &exclude) {
                out.push_str(&format!(
                    "{:.3}  {:<24} ~ {:<24} sim {:.2}  cites {:>6}  ({}/{})\n",
                    f.score,
                    f.left,
                    f.right,
                    f.similarity,
                    f.cross_citations,
                    f.left_size,
                    f.right_size
                ));
            }
            Ok(out.into())
        }
        "similar" => {
            let [decl] = rest else {
                return Err("similar takes one declaration name".into());
            };
            let mut cfg = IndexConfig::default();
            if let Some(l) = level_opt {
                cfg.lgg_level = l;
            }
            let mut idx = SkeletonIndex::build(&input, &cfg).map_err(|e| e.to_string())?;
            let mut out = String::new();
            if brute {
                for (name, ret) in idx.similar_brute(decl, top, &cfg)? {
                    out.push_str(&format!("{ret:.3}  {name}\n"));
                }
            } else {
                // Provenance first, as a `#` comment: a ranking without the scorer that
                // produced it cannot be re-derived or distrusted, which Engine 1 §6 C2
                // asks for. Consumers skip `#` lines.
                out.push_str(&format!("# scorer: {}\n", idx.scorer_id(&cfg)));
                for n in idx.similar(decl, top, &cfg)? {
                    out.push_str(&format!(
                        "{:.3}  {:<44} {:<7} ret {:.2} common {:>3} vars {:>2}{}  [{}]\n",
                        n.score,
                        n.name,
                        n.kind,
                        n.retention,
                        n.common,
                        n.vars,
                        if n.transportable { "" } else { " scoped" },
                        n.sources.describe()
                    ));
                }
            }
            Ok(out.into())
        }
        "skeleton" => {
            let [decl] = rest else {
                return Err("skeleton takes one declaration name".into());
            };
            let mut cfg = IndexConfig::default();
            if let Some(l) = level_opt {
                cfg.lgg_level = l;
            }
            let mut idx = SkeletonIndex::build(&input, &cfg).map_err(|e| e.to_string())?;
            let level = level_opt.unwrap_or(Level::Shape);
            idx.skeleton_of(decl, level)
                .map(|s| (s + "\n").into())
                .ok_or_else(|| format!("`{decl}` is not in this slice"))
        }
        "stats" => {
            let total = g.len();
            let encoded = g
                .names()
                .filter(|n| g.get(n).is_some_and(|d| d.stmt.is_some()))
                .count();
            Ok(format!(
                "declarations: {total}\nencoded statements: {encoded}\nunencodable: {}\n",
                total - encoded
            )
            .into())
        }
        other => Err(format!("unknown query `{other}`\n\n{USAGE}")),
    }
}

fn known(g: &Graph, name: &str) -> Result<(), String> {
    if g.get(name).is_some() {
        Ok(())
    } else {
        Err(format!("`{name}` is not in this slice"))
    }
}

fn lines(names: impl IntoIterator<Item = String>) -> String {
    let mut out = String::new();
    for n in names {
        out.push_str(&n);
        out.push('\n');
    }
    out
}

struct Options {
    lens: Lens,
    level: Option<Level>,
    top: usize,
    brute: bool,
    all_kinds: bool,
    exclude: Vec<String>,
    rest: Vec<String>,
}

fn take_options(args: &[String]) -> Result<Options, String> {
    let mut lens = Lens::Both;
    let mut level = None;
    let mut top = 10usize;
    let mut brute = false;
    let mut all_kinds = false;
    let mut exclude = Vec::new();
    let mut rest = Vec::new();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--lens" => {
                let v = it.next().ok_or("--lens takes a value")?;
                lens = match v.as_str() {
                    "statement" => Lens::Statement,
                    "proof" => Lens::Proof,
                    "both" => Lens::Both,
                    other => return Err(format!("unknown lens `{other}`")),
                };
            }
            "--level" => {
                let v = it.next().ok_or("--level takes a value")?;
                level = Some(Level::parse(v).ok_or_else(|| format!("unknown level `{v}`"))?);
            }
            "--top" => {
                let v = it.next().ok_or("--top takes a number")?;
                top = v.parse().map_err(|_| format!("`{v}` is not a number"))?;
            }
            "--brute" => brute = true,
            // Dictionaries and frontiers restrict to theorems by default: a row between
            // two *recursors* is a fact about how Lean compiles inductives, not a
            // structure-preserving map between theories.
            "--all-kinds" => all_kinds = true,
            "--exclude" => {
                let v = it.next().ok_or("--exclude takes a comma-separated list")?;
                exclude.extend(v.split(',').map(|s| s.trim().to_string()));
            }
            _ => rest.push(a.clone()),
        }
    }
    Ok(Options {
        lens,
        level,
        top,
        brute,
        all_kinds,
        exclude,
        rest,
    })
}
