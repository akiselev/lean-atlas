//! `atlas mcp` v0 — the agent-facing surface over an Atlas slice.
//!
//! JSON-RPC 2.0 over stdio, one message per line.
//!
//! # What this server does *not* do, on purpose
//!
//! The generic Lean layer — goals, diagnostics, hover, and the search fan-out including
//! Loogle/LeanSearch — is delegated to the community `lean-lsp-mcp` server, which already
//! ships all of it against any Lake project; `atlas mcp` itself implements only the
//! Atlas queries. Composition over reimplementation.
//!
//! # Tools
//!
//! * `atlas_closure`, `atlas_similar`, `atlas_dictionary` — the skeleton index.
//! * `atlas_why`, `atlas_foundations`, `atlas_impact`, `atlas_walls` — the dependency graph.
//! * `statement_verify` — the anti-cheat check: does an encoding still match a frozen
//!   digest, or has the statement drifted?
//! * `status` — is the toolchain reachable and the build warm?

use std::io::{BufRead, Write};
use std::path::Path;
use std::process::Command;

use atlas::dict::{DictOptions, dictionary};
use atlas::graph::{Graph, Lens};
use atlas::json::{self, Value};
use atlas::skel::index::{Anchor, IndexConfig, SkeletonIndex};
use atlas::statement;

const PROTOCOL_VERSION: &str = "2024-11-05";

fn main() {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if let Some(response) = handle_line(line) {
            let _ = writeln!(stdout, "{response}");
            let _ = stdout.flush();
        }
    }
}

/// One request in, at most one response out.
///
/// A JSON-RPC *notification* has no `id` and takes no reply — `notifications/initialized`
/// is the one every client sends, and answering it is a protocol error rather than a
/// harmless extra.
fn handle_line(line: &str) -> Option<String> {
    let req = match json::parse(line) {
        Ok(v) => v,
        Err(e) => {
            return Some(error_response(
                Value::Null,
                -32700,
                &format!("parse error: {e}"),
            ));
        }
    };
    let id = req.get("id").cloned();
    let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");
    let params = req.get("params").cloned().unwrap_or(Value::Null);

    // No `id` means a notification, and JSON-RPC says a notification takes no reply.
    let id = id?;

    match method {
        "initialize" => Some(ok_response(id, initialize_result())),
        "tools/list" => Some(ok_response(id, Value::obj([("tools", tool_list())]))),
        "tools/call" => match call_tool(&params) {
            Ok(text) => Some(ok_response(
                id,
                Value::obj([
                    (
                        "content",
                        Value::List(vec![Value::obj([
                            ("type", Value::str("text")),
                            ("text", Value::str(text)),
                        ])]),
                    ),
                    ("isError", Value::Bool(false)),
                ]),
            )),
            // A tool that fails reports through `isError` rather than a JSON-RPC error:
            // the failure is the agent's answer, not a transport fault, and it should
            // reach the model as content it can read.
            Err(msg) => Some(ok_response(
                id,
                Value::obj([
                    (
                        "content",
                        Value::List(vec![Value::obj([
                            ("type", Value::str("text")),
                            ("text", Value::str(msg)),
                        ])]),
                    ),
                    ("isError", Value::Bool(true)),
                ]),
            )),
        },
        "ping" => Some(ok_response(id, Value::obj([]))),
        other => Some(error_response(
            id,
            -32601,
            &format!("unknown method `{other}`"),
        )),
    }
}

fn initialize_result() -> Value {
    Value::obj([
        ("protocolVersion", Value::str(PROTOCOL_VERSION)),
        ("capabilities", Value::obj([("tools", Value::obj([]))])),
        (
            "serverInfo",
            Value::obj([
                ("name", Value::str("atlas-mcp")),
                ("version", Value::str(env!("CARGO_PKG_VERSION"))),
            ]),
        ),
    ])
}

fn string_schema(fields: &[(&str, &str)], required: &[&str]) -> Value {
    let props: Vec<(String, Value)> = fields
        .iter()
        .map(|(name, desc)| {
            (
                name.to_string(),
                Value::obj([
                    ("type", Value::str("string")),
                    ("description", Value::str(*desc)),
                ]),
            )
        })
        .collect();
    Value::obj([
        ("type", Value::str("object")),
        ("properties", Value::Obj(props.into_iter().collect())),
        (
            "required",
            Value::List(required.iter().map(|r| Value::str(*r)).collect()),
        ),
    ])
}

fn tool(name: &str, description: &str, schema: Value) -> Value {
    Value::obj([
        ("name", Value::str(name)),
        ("description", Value::str(description)),
        ("inputSchema", schema),
    ])
}

const LENS_DOC: &str = "which edges to walk: `statement` (what the claim rests on), \
                        `proof` (what the argument rests on), or `both` (default)";

fn tool_list() -> Value {
    Value::List(vec![
        tool(
            "atlas_closure",
            "Is a slice closed under the constants its statements mention? Returns the \
             coverage fraction and the most-cited missing constants. RUN THIS FIRST on any \
             slice you did not extract yourself: an unclosed slice does not fail, it \
             answers — the erasure holes arguments in InstImplicit positions of the head \
             constant's signature, so a head the slice lacks holes nothing and the \
             normalisation silently does not happen. A slice built with `atlas_extract \
             --local` is the usual cause, since that filters the output rather than the \
             import. Measured cost of ignoring this: 34.5% of results lost and 11.0% \
             fabricated. Below ~95% coverage, treat every other Atlas answer as unsound.",
            string_schema(
                &[("slice", "path to a JSONL extraction from `atlas_extract`")],
                &["slice"],
            ),
        ),
        tool(
            "atlas_similar",
            "Declarations whose statements anti-unify with this one, ranked — the \
             retrieval query behind dictionaries and cross-theory analogy. \
             `posting_work_budget` switches the prefilter to work-budget admission: every \
             posting key is kept and the query walks at most that many postings, rarest \
             key first, instead of dropping keys held by too many declarations. The flat \
             cutoff deletes the common keys cross-domain analogy rides on — measured 0/4 \
             pre-registered classical<->quantum correspondences at the shipped cutoff, \
             4/4 with the keys admitted — so set it (2000 is the measured reference \
             point) together with `anchor=conclusion` when hunting across theories. \
             Loads the slice and builds an index per call; loops belong on the Python \
             binding.",
            string_schema(
                &[
                    ("slice", "path to a JSONL extraction from `atlas_extract`"),
                    ("name", "the declaration to find neighbours of"),
                    ("top", "how many neighbours to return (default 10)"),
                    (
                        "anchor",
                        "`root` (default) compares whole statements; `conclusion` \
                         compares what they conclude, which cross-theory analogy needs",
                    ),
                    (
                        "posting_work_budget",
                        "postings walked per query under keep-all admission; omit for \
                         the shipped frequency cutoff",
                    ),
                ],
                &["slice", "name"],
            ),
        ),
        tool(
            "atlas_dictionary",
            "The maximal partial functor between two theory prefixes: skeleton-matched \
             rows plus the counts of unmatched declarations on each side. The assembly \
             assembly knobs are the §74 repairs, all default-off. `rank_by_retention` \
             orders by retention instead of the full score — cross-domain, size-flavoured \
             score factors reward shared framework mass, and the validated \
             classical<->quantum correspondences rank 437-1,150 of 3,029 under the scored \
             key against 17-525 under retention. `per_decl_keep_displaced` counts the \
             per-left cap per skeleton, so a structurally different claim is not evicted \
             by a higher-ranked lookalike (315 rows were displaced that way, the von \
             Neumann ~ Gibbs entropy bridge among them). `exclude_cited` drops rows whose \
             declarations cite each other — usage, not analogy. `exclude_instances` uses \
             Lean's registry metadata to drop registered instances without guessing from \
             names. Set \
             `posting_work_budget=2000` with `anchor=conclusion` when hunting across \
             theories, as for `atlas_similar`. Loads the slice and builds an index per \
             call; loops belong on the Python binding.",
            string_schema(
                &[
                    ("slice", "path to a JSONL extraction from `atlas_extract`"),
                    ("left", "left theory: a module prefix, e.g. `QuantumInfo`"),
                    ("right", "right theory: a module prefix"),
                    ("top", "how many rows to print (default 20)"),
                    ("per_decl", "rows kept per left declaration (default 1)"),
                    (
                        "anchor",
                        "`root` (default) compares whole statements; `conclusion` \
                         compares what they conclude, which cross-theory analogy needs",
                    ),
                    (
                        "posting_work_budget",
                        "postings walked per query under keep-all admission; omit for \
                         the shipped frequency cutoff",
                    ),
                    (
                        "rank_by_retention",
                        "`true` ranks candidates and rows by retention instead of the \
                         scored key (default `false`)",
                    ),
                    (
                        "per_decl_keep_displaced",
                        "`true` counts the per_decl cap per (left, skeleton) so \
                         structurally distinct claims are kept (default `false`)",
                    ),
                    (
                        "exclude_cited",
                        "`true` drops rows whose two declarations cite each other, \
                         either lens, either direction (default `false`)",
                    ),
                    (
                        "exclude_instances",
                        "`true` drops declarations registered as instances by Lean; \
                         legacy rows with unknown status remain (default `false`)",
                    ),
                ],
                &["slice", "left", "right"],
            ),
        ),
        tool(
            "atlas_why",
            "A shortest citation chain from one declaration down to another. The \
             'decompile the relationship' primitive: the first thing to run when asked \
             whether X is relevant to Y.",
            string_schema(
                &[
                    ("slice", "path to a JSONL extraction from `atlas_extract`"),
                    ("from", "the declaration to start from"),
                    ("to", "the declaration to reach"),
                    ("lens", LENS_DOC),
                ],
                &["slice", "from", "to"],
            ),
        ),
        tool(
            "atlas_foundations",
            "Everything a declaration transitively rests on.",
            string_schema(
                &[
                    ("slice", "path to a JSONL extraction"),
                    ("name", "the declaration"),
                    ("lens", LENS_DOC),
                ],
                &["slice", "name"],
            ),
        ),
        tool(
            "atlas_impact",
            "Everything that transitively rests on a declaration — what breaks if it is \
             wrong.",
            string_schema(
                &[
                    ("slice", "path to a JSONL extraction"),
                    ("name", "the declaration"),
                    ("lens", LENS_DOC),
                ],
                &["slice", "name"],
            ),
        ),
        tool(
            "atlas_walls",
            "The declarations most cited in a slice: the load-bearing walls.",
            string_schema(
                &[("slice", "path to a JSONL extraction"), ("lens", LENS_DOC)],
                &["slice"],
            ),
        ),
        tool(
            "statement_verify",
            "The anti-cheat check: does a statement encoding still match a frozen digest? \
             Answers `match`, `differs`, or `stale-freeze` — a version skew is a distinct \
             verdict from a changed statement, and conflating them would let a toolchain \
             bump read as tampering.",
            string_schema(
                &[
                    (
                        "encoding",
                        "the canonical statement encoding, from `#atlas_statement`",
                    ),
                    ("frozen", "the digest to check against"),
                ],
                &["encoding", "frozen"],
            ),
        ),
        tool(
            "status",
            "Toolchain and build health: which Lean is on PATH, and whether the Lake \
             build is warm.",
            string_schema(&[], &[]),
        ),
    ])
}

fn call_tool(params: &Value) -> Result<String, String> {
    let name = params
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or("tools/call needs a `name`")?;
    let args = params
        .get("arguments")
        .cloned()
        .unwrap_or(Value::Obj(Default::default()));
    let arg = |k: &str| -> Result<String, String> {
        args.get(k)
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .ok_or_else(|| format!("`{name}` needs a `{k}`"))
    };
    let lens = match args.get("lens").and_then(|v| v.as_str()).unwrap_or("both") {
        "statement" => Lens::Statement,
        "proof" => Lens::Proof,
        "both" => Lens::Both,
        other => return Err(format!("unknown lens `{other}`")),
    };
    let load = |path: &str| -> Result<Graph, String> {
        let text = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
        Graph::from_jsonl(&text).map_err(|e| e.to_string())
    };

    match name {
        "atlas_closure" => {
            // Builds the skeleton index rather than the graph: the coverage figure is a
            // by-product of erasing every statement, which is what the index does anyway.
            let path = arg("slice")?;
            let text = std::fs::read_to_string(&path).map_err(|e| format!("{path}: {e}"))?;
            let idx =
                SkeletonIndex::build(&text, &IndexConfig::default()).map_err(|e| e.to_string())?;
            let (known, unknown, worst) = idx.closure(10);
            let total = known + unknown;
            let cov = if total == 0 {
                1.0
            } else {
                known as f64 / total as f64
            };
            let mut out = format!(
                "declarations: {}\napplication heads: {total}\nwith a signature: {known}\n\
                 missing: {unknown}\nCOVERAGE: {:.2}%\n",
                idx.len(),
                cov * 100.0
            );
            if cov < 0.95 {
                out.push_str(
                    "\nVERDICT: NOT CLOSED. Every result at erasure level `instances` or \
                     above is unsound on this slice — the normalisation silently did not \
                     happen. Re-extract without `--local`.\n",
                );
            } else {
                out.push_str("\nVERDICT: closed enough to query.\n");
            }
            if !worst.is_empty() {
                out.push_str("\nmost-cited missing constants (statements mentioning them):\n");
                for (n, df) in worst {
                    out.push_str(&format!("  {n}  {df}\n"));
                }
            }
            Ok(out)
        }
        "atlas_similar" => {
            let path = arg("slice")?;
            let text = std::fs::read_to_string(&path).map_err(|e| format!("{path}: {e}"))?;
            let query = arg("name")?;
            // Optional numbers arrive as strings under `string_schema`; a malformed one
            // is the caller's error to hear about, not a default to fall back on.
            let opt_num = |k: &str| -> Result<Option<usize>, String> {
                args.get(k)
                    .and_then(|v| v.as_str())
                    .map(|s| {
                        s.parse::<usize>()
                            .map_err(|_| format!("`{k}` must be a number, got `{s}`"))
                    })
                    .transpose()
            };
            let top = opt_num("top")?.unwrap_or(10);
            let posting_work_budget = opt_num("posting_work_budget")?;
            let anchor = match args
                .get("anchor")
                .and_then(|v| v.as_str())
                .unwrap_or("root")
            {
                "root" => Anchor::Root,
                "conclusion" => Anchor::Conclusion,
                other => return Err(format!("unknown anchor `{other}`")),
            };
            let cfg = IndexConfig {
                anchor,
                posting_work_budget,
                ..IndexConfig::default()
            };
            let mut idx = SkeletonIndex::build(&text, &cfg).map_err(|e| e.to_string())?;
            let ns = idx.similar(&query, top, &cfg)?;
            if ns.is_empty() {
                return Ok("(no neighbours above the floors)".to_string());
            }
            Ok(ns
                .iter()
                .map(|n| {
                    format!(
                        "{:.4}  ret {:.3}  common {:>3}  [{}]  {}  ({})",
                        n.score,
                        n.retention,
                        n.common,
                        n.sources.describe(),
                        n.name,
                        n.module
                    )
                })
                .collect::<Vec<_>>()
                .join("\n"))
        }
        "atlas_dictionary" => {
            let path = arg("slice")?;
            let text = std::fs::read_to_string(&path).map_err(|e| format!("{path}: {e}"))?;
            let (left, right) = (arg("left")?, arg("right")?);
            let opt_num = |k: &str| -> Result<Option<usize>, String> {
                args.get(k)
                    .and_then(|v| v.as_str())
                    .map(|s| {
                        s.parse::<usize>()
                            .map_err(|_| format!("`{k}` must be a number, got `{s}`"))
                    })
                    .transpose()
            };
            // Booleans arrive as strings under `string_schema`, like the numbers; a
            // malformed one is the caller's error to hear about, not a default.
            let opt_bool = |k: &str| -> Result<bool, String> {
                match args.get(k).and_then(|v| v.as_str()) {
                    None | Some("false") => Ok(false),
                    Some("true") => Ok(true),
                    Some(other) => Err(format!("`{k}` must be `true` or `false`, got `{other}`")),
                }
            };
            let top = opt_num("top")?.unwrap_or(20);
            let anchor = match args
                .get("anchor")
                .and_then(|v| v.as_str())
                .unwrap_or("root")
            {
                "root" => Anchor::Root,
                "conclusion" => Anchor::Conclusion,
                other => return Err(format!("unknown anchor `{other}`")),
            };
            let cfg = IndexConfig {
                anchor,
                posting_work_budget: opt_num("posting_work_budget")?,
                ..IndexConfig::default()
            };
            let opts = DictOptions {
                per_decl: opt_num("per_decl")?.unwrap_or(1),
                rank_by_retention: opt_bool("rank_by_retention")?,
                per_decl_keep_displaced: opt_bool("per_decl_keep_displaced")?,
                exclude_cited: opt_bool("exclude_cited")?,
                exclude_instances: opt_bool("exclude_instances")?,
                ..DictOptions::default()
            };
            // The graph is only paid for when a filter reads complete row metadata; the
            // engine refuses either filter without one, so neither can silently no-op.
            let graph = if opts.exclude_cited || opts.exclude_instances {
                Some(Graph::from_jsonl(&text).map_err(|e| e.to_string())?)
            } else {
                None
            };
            let mut idx = SkeletonIndex::build(&text, &cfg).map_err(|e| e.to_string())?;
            let d = dictionary(&mut idx, graph.as_ref(), &left, &right, &cfg, &opts);
            let mut out = String::new();
            for r in d.rows.iter().take(top) {
                out.push_str(&format!(
                    "ret {:.3}  score {:.4}  {:<14}  {} ~ {}{}\n",
                    r.retention,
                    r.score,
                    r.status.name(),
                    r.left,
                    r.right,
                    if r.transportable { "" } else { "  (scoped)" }
                ));
            }
            out.push_str(&format!(
                "\n{} rows; unmatched: {} in {}, {} in {}\n",
                d.rows.len(),
                d.missing_left.len(),
                d.left_theory,
                d.missing_right.len(),
                d.right_theory
            ));
            Ok(out)
        }
        "atlas_why" => {
            let g = load(&arg("slice")?)?;
            let (from, to) = (arg("from")?, arg("to")?);
            g.why(&from, &to, lens)
                .map(|p| p.join("\n"))
                .ok_or_else(|| format!("no dependency chain from `{from}` to `{to}` in this slice"))
        }
        "atlas_foundations" => {
            let g = load(&arg("slice")?)?;
            Ok(g.foundations(&arg("name")?, lens)
                .into_iter()
                .collect::<Vec<_>>()
                .join("\n"))
        }
        "atlas_impact" => {
            let g = load(&arg("slice")?)?;
            Ok(g.impact(&arg("name")?, lens)
                .into_iter()
                .collect::<Vec<_>>()
                .join("\n"))
        }
        "atlas_walls" => {
            let g = load(&arg("slice")?)?;
            Ok(g.ranked_by_citations(lens)
                .into_iter()
                .take(20)
                .filter(|(_, n)| *n > 0)
                .map(|(name, n)| format!("{n:>6}  {name}"))
                .collect::<Vec<_>>()
                .join("\n"))
        }
        "statement_verify" => {
            let verdict = statement::verify(&arg("encoding")?, &arg("frozen")?)
                .map_err(|e| format!("{e:?}"))?;
            Ok(format!("{verdict:?}"))
        }
        "status" => Ok(status()),
        other => Err(format!("unknown tool `{other}`")),
    }
}

fn lean_dir() -> std::path::PathBuf {
    if let Ok(d) = std::env::var("ATLAS_LEAN_DIR") {
        return d.into();
    }
    let cwd = std::env::current_dir().unwrap_or_else(|_| ".".into());
    if cwd.join("lakefile.toml").exists() {
        cwd
    } else {
        cwd.join("lean")
    }
}

fn status() -> String {
    let lean_dir = lean_dir();
    let version = Command::new("lean")
        .arg("--version")
        .output()
        .ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_else(|| "lean not on PATH".into());
    let warm = Path::new(&lean_dir).join(".lake/build/lib/lean").exists();
    Value::obj([
        ("lean", Value::str(version)),
        ("leanDir", Value::str(lean_dir.display().to_string())),
        ("buildWarm", Value::Bool(warm)),
    ])
    .to_json()
}

fn ok_response(id: Value, result: Value) -> String {
    Value::obj([
        ("jsonrpc", Value::str("2.0")),
        ("id", id),
        ("result", result),
    ])
    .to_json()
}

fn error_response(id: Value, code: i64, message: &str) -> String {
    Value::obj([
        ("jsonrpc", Value::str("2.0")),
        ("id", id),
        (
            "error",
            Value::obj([
                ("code", Value::Num(code as f64)),
                ("message", Value::str(message)),
            ]),
        ),
    ])
    .to_json()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn call(line: &str) -> Value {
        json::parse(&handle_line(line).expect("expected a response")).unwrap()
    }

    #[test]
    fn initialize_announces_tools() {
        let r = call(r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}"#);
        assert_eq!(r.get("id"), Some(&Value::Num(1.0)));
        let caps = r.get("result").unwrap().get("capabilities").unwrap();
        assert!(caps.get("tools").is_some());
    }

    #[test]
    fn a_notification_gets_no_reply() {
        // JSON-RPC: no `id` means no response. Every client sends
        // `notifications/initialized`, and answering it is a protocol error.
        assert!(handle_line(r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#).is_none());
    }

    #[test]
    fn tools_list_names_the_atlas_tools() {
        let r = call(r#"{"jsonrpc":"2.0","id":2,"method":"tools/list"}"#);
        let tools = r
            .get("result")
            .unwrap()
            .get("tools")
            .unwrap()
            .as_list()
            .unwrap();
        let names: Vec<&str> = tools
            .iter()
            .filter_map(|t| t.get("name"))
            .filter_map(|n| n.as_str())
            .collect();
        assert!(names.contains(&"atlas_why"));
        assert!(names.contains(&"atlas_closure"));
        assert!(names.contains(&"atlas_similar"));
        assert!(names.contains(&"atlas_dictionary"));
        assert!(names.contains(&"statement_verify"));
        // Delegated to `lean-lsp-mcp` per agent-interface §1's amendment: composition
        // over reimplementation. A `search` here would be the second-best one.
        assert!(!names.contains(&"search"));
        // Named in §1 but honestly absent until the REPL wrapper (C2) exists.
        assert!(!names.contains(&"try"));
        assert!(!names.contains(&"minimize"));
        // Every tool has to declare a schema, or a client cannot call it.
        for t in tools {
            assert!(t.get("inputSchema").is_some(), "{t:?} has no inputSchema");
            assert!(t.get("description").is_some(), "{t:?} has no description");
        }
    }

    #[test]
    fn a_tool_failure_is_content_not_a_transport_error() {
        // The failure is the agent's answer. Reporting it as a JSON-RPC error would hide
        // it from the model, which is the one reader who needs it.
        let r = call(
            r#"{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"atlas_why","arguments":{"slice":"/nonexistent.jsonl","from":"A","to":"B"}}}"#,
        );
        assert!(r.get("error").is_none());
        let res = r.get("result").unwrap();
        assert_eq!(res.get("isError"), Some(&Value::Bool(true)));
        let text = res.get("content").unwrap().as_list().unwrap()[0]
            .get("text")
            .unwrap();
        assert!(text.as_str().unwrap().contains("nonexistent"), "{text:?}");
    }

    /// The closure check must **discriminate**, not merely run.
    ///
    /// A coverage number that reads high on every input is the failure mode it exists to
    /// catch, so this pairs a slice whose statements name only constants it contains
    /// against one missing its head constant, and asserts opposite verdicts. Without the
    /// negative half a hard-coded `100%` would pass.
    #[test]
    fn atlas_closure_separates_a_closed_slice_from_an_unclosed_one() {
        let dir = std::env::temp_dir().join("atlas-mcp-closure-test");
        std::fs::create_dir_all(&dir).unwrap();
        // Real encodings lifted from the corpus, not hand-written ones: the first
        // attempt at this fixture used `s(*)`, which is *erased-output* syntax and not
        // input, so both slices parsed to zero declarations and the closed half passed
        // only because 0/0 defaults to 100%. A fixture that tests nothing is the exact
        // failure this test exists to catch, so it is worth the two literals.
        //
        // `proof_irrel`'s statement is headed by `Eq`. The closed slice carries `Eq`'s own
        // row; the unclosed one does not, which is the whole difference.
        let stmt = "atlas-stmt-v1;pi(s(0),pd(b0,pd(b1,a(a(a(c(2:Eq,1,0),b2),b1),b0))))";
        let eq_stmt = "atlas-stmt-v1;pi(s(u0),pd(b0,pd(b1,s(0))))";
        let thm = format!(
            "{{\"name\":\"proof_irrel\",\"kind\":\"theorem\",\"module\":\"M\",\
             \"stmt\":\"{stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
        );
        let eq = format!(
            "{{\"name\":\"Eq\",\"kind\":\"def\",\"module\":\"M\",\
             \"stmt\":\"{eq_stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
        );
        let closed = dir.join("closed.jsonl");
        std::fs::write(&closed, format!("{thm}\n{eq}\n")).unwrap();
        let unclosed = dir.join("unclosed.jsonl");
        std::fs::write(&unclosed, format!("{thm}\n")).unwrap();

        let text_of = |path: &std::path::Path| -> String {
            let p = path.display().to_string();
            let r = call(&format!(
                r#"{{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{{"name":"atlas_closure","arguments":{{"slice":"{p}"}}}}}}"#
            ));
            let res = r.get("result").unwrap();
            assert_eq!(res.get("isError"), Some(&Value::Bool(false)), "{res:?}");
            res.get("content").unwrap().as_list().unwrap()[0]
                .get("text")
                .unwrap()
                .as_str()
                .unwrap()
                .to_string()
        };

        let a = text_of(&closed);
        let b = text_of(&unclosed);
        assert!(
            a.contains("closed enough to query"),
            "closed slice reported: {a}"
        );
        assert!(b.contains("NOT CLOSED"), "unclosed slice reported: {b}");
        // …and it must name what is missing, or a caller cannot act on the verdict.
        assert!(
            b.contains("Eq"),
            "unclosed slice did not name the missing constant: {b}"
        );
    }

    /// `atlas_similar`'s budget knob, paired so it can fail in both directions.
    ///
    /// The fixture reproduces the §66 defect at MCP scale: the only key linking `p` to
    /// `q` is a concrete subterm held by 62 of 62 declarations, over the shipped
    /// `min_posting_len` of 50, so with the knob off `q` must be absent — if it appears,
    /// the fixture's key was never crowded and the positive half proves nothing. With
    /// the budget on, the key is admitted and `q` must arrive. The crowd rows share
    /// `p`'s whole shape, so the ranking still returns *them* either way — which pins
    /// that the knob widened source B rather than turning retrieval on at all.
    #[test]
    fn atlas_similar_pairs_the_work_budget_with_its_ablation() {
        let dir = std::env::temp_dir().join("atlas-mcp-similar-test");
        std::fs::create_dir_all(&dir).unwrap();
        // Size-7 shared subterm, so the pair clears the shipped `min_common` of 6 at the
        // conclusion anchor. `q` carries a binder prefix: different shape from `p`, so
        // the shape bucket cannot propose it and the crowded key is the only route.
        let shared = "a(a(a(c(5:LE.le,0),c(4:Real,0)),c(3:iii,0)),c(2:zz,0))";
        let row = |name: &str, stmt: &str| {
            format!(
                "{{\"name\":\"{name}\",\"kind\":\"theorem\",\"module\":\"M\",\
                 \"stmt\":\"atlas-stmt-v1;{stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
            )
        };
        let mut rows = vec![
            row("p", &format!("a(a(c(2:Eq,0),{shared}),c(1:u,0))")),
            row("q", &format!("pi(s(0),a(a(c(3:Nee,0),{shared}),b0))")),
        ];
        for i in 0..60 {
            let k = format!("k{i}");
            rows.push(row(
                &format!("crowd{i}"),
                &format!("a(a(c(2:Eq,0),{shared}),c({}:{k},0))", k.len()),
            ));
        }
        let slice = dir.join("slice.jsonl");
        std::fs::write(&slice, rows.join("\n")).unwrap();
        let s = slice.display().to_string();

        let similar = |budget: Option<&str>| -> String {
            let budget_arg = match budget {
                Some(b) => format!(",\"posting_work_budget\":\"{b}\""),
                None => String::new(),
            };
            let req = format!(
                r#"{{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{{"name":"atlas_similar","arguments":{{"slice":"{s}","name":"p","top":"100","anchor":"conclusion"{budget_arg}}}}}}}"#
            );
            let r = call(&req);
            let res = r.get("result").unwrap();
            assert_eq!(res.get("isError"), Some(&Value::Bool(false)), "{res:?}");
            res.get("content").unwrap().as_list().unwrap()[0]
                .get("text")
                .unwrap()
                .as_str()
                .unwrap()
                .to_string()
        };

        let off = similar(None);
        assert!(
            !off.contains(" q "),
            "with the shipped cutoff the crowded key is dropped and `q` has no route: {off}"
        );
        assert!(
            off.contains("crowd0"),
            "the shape bucket must still work with the knob off, or the ablation is \
             measuring a dead server rather than the cutoff: {off}"
        );
        let on = similar(Some("100000"));
        assert!(
            on.contains(" q "),
            "the work budget must admit the crowded key and surface `q`: {on}"
        );
    }

    /// `atlas_dictionary`'s §74 knobs through the MCP surface, paired.
    ///
    /// The fixture is the `linearSol` pattern: the left's best-ranked partner is the
    /// framework lemma its proof cites, so with the knobs off the row must pair them —
    /// the shipped behaviour — and with `exclude_cited=true` the slot must pass to the
    /// unlinked candidate rather than to nobody. Off asserting the linked pair is the
    /// half that keeps this from passing on a server that returns nothing.
    #[test]
    fn atlas_dictionary_pairs_exclude_cited_with_its_ablation() {
        let dir = std::env::temp_dir().join("atlas-mcp-dictionary-test");
        std::fs::create_dir_all(&dir).unwrap();
        let shared = "a(a(a(c(5:LE.le,0),c(4:Real,0)),c(3:iii,0)),c(2:zz,0))";
        let row = |name: &str, module: &str, stmt: &str, proof: &str| {
            format!(
                "{{\"name\":\"{name}\",\"kind\":\"theorem\",\"module\":\"{module}\",\
                 \"stmt\":\"atlas-stmt-v1;{stmt}\",\"uses_statement\":[],\"uses_proof\":[{proof}]}}"
            )
        };
        let rows = [
            row(
                "l1",
                "L",
                &format!("a(a(c(2:Eq,0),{shared}),c(1:u,0))"),
                "\"rf\"",
            ),
            row("rf", "R", &format!("a(a(c(2:Eq,0),{shared}),c(1:v,0))"), ""),
            row(
                "rg",
                "R",
                "a(a(c(2:Eq,0),a(a(a(c(5:LE.le,0),c(4:Real,0)),c(3:jjj,0)),c(2:qq,0))),c(1:u,0))",
                "",
            ),
        ];
        let slice = dir.join("slice.jsonl");
        std::fs::write(&slice, rows.join("\n")).unwrap();
        let s = slice.display().to_string();

        let dict_rows = |knob: Option<&str>| -> String {
            let knob_arg = match knob {
                Some(v) => format!(",\"exclude_cited\":\"{v}\""),
                None => String::new(),
            };
            let req = format!(
                r#"{{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{{"name":"atlas_dictionary","arguments":{{"slice":"{s}","left":"L","right":"R"{knob_arg}}}}}}}"#
            );
            let r = call(&req);
            let res = r.get("result").unwrap();
            assert_eq!(res.get("isError"), Some(&Value::Bool(false)), "{res:?}");
            res.get("content").unwrap().as_list().unwrap()[0]
                .get("text")
                .unwrap()
                .as_str()
                .unwrap()
                .to_string()
        };

        let off = dict_rows(None);
        assert!(
            off.contains("l1 ~ rf"),
            "off, the citation-linked framework partner wins the slot: {off}"
        );
        let on = dict_rows(Some("true"));
        assert!(
            !on.contains("l1 ~ rf"),
            "on, the citation-linked pair must be dropped: {on}"
        );
        assert!(
            on.contains("l1 ~ rg"),
            "on, the slot must pass to the unlinked candidate, not to nobody: {on}"
        );
    }

    #[test]
    fn atlas_queries_answer_over_a_slice() {
        let dir = std::env::temp_dir().join("atlas-mcp-test");
        std::fs::create_dir_all(&dir).unwrap();
        let slice = dir.join("slice.jsonl");
        std::fs::write(
            &slice,
            "{\"name\":\"A\",\"kind\":\"theorem\",\"module\":\"M\",\"uses_statement\":[],\"uses_proof\":[\"B\"]}\n\
             {\"name\":\"B\",\"kind\":\"theorem\",\"module\":\"M\",\"uses_statement\":[],\"uses_proof\":[\"C\"]}\n\
             {\"name\":\"C\",\"kind\":\"def\",\"module\":\"M\",\"uses_statement\":[],\"uses_proof\":[]}\n",
        )
        .unwrap();
        let s = slice.display().to_string();
        let req = format!(
            r#"{{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{{"name":"atlas_why","arguments":{{"slice":"{s}","from":"A","to":"C","lens":"proof"}}}}}}"#
        );
        let r = call(&req);
        let res = r.get("result").unwrap();
        assert_eq!(res.get("isError"), Some(&Value::Bool(false)));
        let text = res.get("content").unwrap().as_list().unwrap()[0]
            .get("text")
            .unwrap();
        assert_eq!(text.as_str().unwrap(), "A\nB\nC");
    }

    #[test]
    fn statement_verify_distinguishes_drift_from_version_skew() {
        let enc = "atlas-stmt-v1;s(u0)";
        let digest = statement::digest(enc).unwrap();
        let call_with = |encoding: &str| {
            let req = format!(
                r#"{{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{{"name":"statement_verify","arguments":{{"encoding":"{encoding}","frozen":"{digest}"}}}}}}"#
            );
            let r = call(&req);
            r.get("result")
                .unwrap()
                .get("content")
                .unwrap()
                .as_list()
                .unwrap()[0]
                .get("text")
                .unwrap()
                .as_str()
                .unwrap()
                .to_string()
        };
        assert_eq!(call_with(enc), "Match");
        assert_eq!(call_with("atlas-stmt-v1;s(u1)"), "Differs");
    }

    #[test]
    fn an_unknown_method_is_a_jsonrpc_error() {
        let r = call(r#"{"jsonrpc":"2.0","id":6,"method":"nope"}"#);
        assert_eq!(
            r.get("error").unwrap().get("code"),
            Some(&Value::Num(-32601.0))
        );
    }

    #[test]
    fn malformed_input_does_not_kill_the_server() {
        let r = call("not json");
        assert_eq!(
            r.get("error").unwrap().get("code"),
            Some(&Value::Num(-32700.0))
        );
    }
}
