//! The dependency graph (atlas.md §1a) — the citation layer, and the substrate for
//! everything else in Track B.
//!
//! > Nodes: declarations. Edges: "proof of X uses Y," extracted by walking proof terms —
//! > not imports, actual term-level usage. Cheap, exact, and the substrate for everything
//! > else. Derived metrics per node: transitive foundation (what it rests on), transitive
//! > impact (what rests on it), and *bridge centrality* — declarations whose removal
//! > disconnects theory clusters are the load-bearing walls, and agents should know a wall
//! > when they lean on one.
//!
//! # Two edge kinds, kept apart
//!
//! B1's extractor emits `uses_statement` and `uses_proof` separately, and this module
//! keeps them separate all the way through. The distinction is the whole point of the
//! queries: what a *claim* rests on is a different question from what an *argument* rests
//! on, and an agent asking "can I weaken this hypothesis" wants the first while one asking
//! "what breaks if this proof is wrong" wants the second.
//!
//! A [`Lens`] selects which edges a query traverses. `Lens::Statement` answers foundations
//! questions about what a theorem *says*; `Lens::Proof` about how it is *argued*;
//! `Lens::Both` is the citation graph as a reader would draw it.

use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};

/// The current JSONL row envelope emitted by `atlas_extract`.
///
/// This version is intentionally separate from `atlas-stmt-v1`: the row can gain metadata
/// without changing the canonical statement language or its digests.
pub const ROW_SCHEMA_V2: &str = "atlas-row-v2";

/// Which row envelope a declaration came from. Rows without a tag remain readable so old
/// slices can be inspected, but metadata absent from them is reported as unknown rather
/// than silently defaulted to `false` or an empty set.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RowSchema {
    Legacy,
    V2,
}

impl RowSchema {
    pub const fn name(self) -> &'static str {
        match self {
            RowSchema::Legacy => "legacy",
            RowSchema::V2 => ROW_SCHEMA_V2,
        }
    }
}

/// One statement-level class requirement observed at a concrete constant use site.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClassRequirement {
    /// The cited constant whose signature contains the instance-implicit parameter.
    pub source: String,
    /// The required typeclass at that parameter.
    pub class_name: String,
    /// Zero-based outer binder of the declaration constrained by the class.
    pub carrier: usize,
}

/// Which dependency edges a query walks.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Lens {
    /// What the claim rests on.
    Statement,
    /// What the argument rests on.
    Proof,
    /// Both, which is the citation graph.
    Both,
}

/// One declaration, as B1's extractor emits it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decl {
    pub schema: RowSchema,
    pub name: String,
    pub kind: String,
    pub module: String,
    /// Whether Lean's imported instance registry contains this declaration. `None` means
    /// a legacy row did not carry the field; it is not equivalent to `Some(false)`.
    pub is_instance: Option<bool>,
    /// The I3 canonical statement encoding, absent when it could not be encoded.
    pub stmt: Option<String>,
    /// Why the statement could not be encoded. Present exactly when `stmt` is absent —
    /// B1 keeps the row rather than dropping it, "an extractor that silently omits rows
    /// is indistinguishable from one that missed them".
    pub stmt_error: Option<String>,
    pub uses_statement: Vec<String>,
    pub uses_proof: Vec<String>,
    /// Source-attributed carrier requirements from the statement. `Some([])` is a known
    /// empty result from the v2 extractor; `None` means a legacy row did not report this
    /// channel.
    pub requirements_statement: Option<Vec<ClassRequirement>>,
}

impl Decl {
    fn edges(&self, lens: Lens) -> impl Iterator<Item = &String> {
        let (a, b) = match lens {
            Lens::Statement => (Some(&self.uses_statement), None),
            Lens::Proof => (Some(&self.uses_proof), None),
            Lens::Both => (Some(&self.uses_statement), Some(&self.uses_proof)),
        };
        a.into_iter().flatten().chain(b.into_iter().flatten())
    }
}

/// Errors from reading an extraction.
#[derive(Debug, PartialEq, Eq)]
pub enum GraphError {
    /// A row was not valid JSON, or lacked a field the schema requires.
    BadRow { line: usize, reason: String },
}

impl std::fmt::Display for GraphError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            GraphError::BadRow { line, reason } => write!(f, "line {line}: {reason}"),
        }
    }
}

impl std::error::Error for GraphError {}

/// The dependency graph over an extraction.
///
/// Names are the identity — the extractor emits them in Lean's own namespaced form and
/// design §6's no-mangling policy means they are the names a reader already knows.
#[derive(Debug, Default)]
pub struct Graph {
    decls: BTreeMap<String, Decl>,
    /// Reverse edges, built once: `rev[y]` is everything whose statement mentions `y`.
    rev_statement: HashMap<String, Vec<String>>,
    /// `rev[y]` is everything whose proof mentions `y`.
    rev_proof: HashMap<String, Vec<String>>,
}

impl Graph {
    /// Build a graph from B1's JSONL, one row per line.
    ///
    /// Rows naming constants that were not themselves extracted are kept: an edge to
    /// something outside the slice is a real fact about the slice, and dropping it would
    /// make a boundary declaration look self-supporting.
    pub fn from_jsonl(input: &str) -> Result<Self, GraphError> {
        let mut g = Graph::default();
        for (i, line) in input.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let decl = parse_row(line).map_err(|reason| GraphError::BadRow {
                line: i + 1,
                reason,
            })?;
            g.decls.insert(decl.name.clone(), decl);
        }
        for decl in g.decls.values() {
            for used in &decl.uses_statement {
                g.rev_statement
                    .entry(used.clone())
                    .or_default()
                    .push(decl.name.clone());
            }
            for used in &decl.uses_proof {
                g.rev_proof
                    .entry(used.clone())
                    .or_default()
                    .push(decl.name.clone());
            }
        }
        for v in g.rev_statement.values_mut() {
            v.sort();
            v.dedup();
        }
        for v in g.rev_proof.values_mut() {
            v.sort();
            v.dedup();
        }
        Ok(g)
    }

    pub fn len(&self) -> usize {
        self.decls.len()
    }

    pub fn is_empty(&self) -> bool {
        self.decls.is_empty()
    }

    pub fn get(&self, name: &str) -> Option<&Decl> {
        self.decls.get(name)
    }

    pub fn names(&self) -> impl Iterator<Item = &String> {
        self.decls.keys()
    }

    fn successors(&self, name: &str, lens: Lens) -> Vec<String> {
        match self.decls.get(name) {
            Some(d) => {
                let mut v: Vec<String> = d.edges(lens).cloned().collect();
                v.sort();
                v.dedup();
                v
            }
            None => Vec::new(),
        }
    }

    fn predecessors(&self, name: &str, lens: Lens) -> Vec<String> {
        let mut v = Vec::new();
        if matches!(lens, Lens::Statement | Lens::Both) {
            v.extend(self.rev_statement.get(name).into_iter().flatten().cloned());
        }
        if matches!(lens, Lens::Proof | Lens::Both) {
            v.extend(self.rev_proof.get(name).into_iter().flatten().cloned());
        }
        v.sort();
        v.dedup();
        v
    }

    /// Everything `name` transitively rests on — atlas.md's *transitive foundation*.
    ///
    /// Excludes `name` itself. Mutual recursion makes a declaration reachable from itself,
    /// and reporting it as its own foundation would be noise.
    pub fn foundations(&self, name: &str, lens: Lens) -> BTreeSet<String> {
        self.reach(name, lens, |g, n, l| g.successors(n, l))
    }

    /// Everything that transitively rests on `name` — atlas.md's *transitive impact*.
    pub fn impact(&self, name: &str, lens: Lens) -> BTreeSet<String> {
        self.reach(name, lens, |g, n, l| g.predecessors(n, l))
    }

    fn reach(
        &self,
        name: &str,
        lens: Lens,
        step: fn(&Graph, &str, Lens) -> Vec<String>,
    ) -> BTreeSet<String> {
        let mut seen = BTreeSet::new();
        let mut queue = VecDeque::from(step(self, name, lens));
        while let Some(n) = queue.pop_front() {
            if n == name || !seen.insert(n.clone()) {
                continue;
            }
            queue.extend(step(self, &n, lens));
        }
        seen
    }

    /// A shortest dependency chain from `from` down to `to`, if one exists.
    ///
    /// This is `atlas why`'s core: "how is A connected to B", answered as the actual
    /// citation path rather than a yes/no. Shortest because the point is to be *read* —
    /// a twenty-step chain that happens to exist tells an agent nothing it can act on.
    pub fn why(&self, from: &str, to: &str, lens: Lens) -> Option<Vec<String>> {
        if from == to {
            return Some(vec![from.to_string()]);
        }
        let mut prev: HashMap<String, String> = HashMap::new();
        let mut queue = VecDeque::from(vec![from.to_string()]);
        let mut seen: BTreeSet<String> = BTreeSet::from([from.to_string()]);
        while let Some(n) = queue.pop_front() {
            for next in self.successors(&n, lens) {
                if !seen.insert(next.clone()) {
                    continue;
                }
                prev.insert(next.clone(), n.clone());
                if next == to {
                    let mut path = vec![to.to_string()];
                    let mut cur = to.to_string();
                    while let Some(p) = prev.get(&cur) {
                        path.push(p.clone());
                        cur = p.clone();
                    }
                    path.reverse();
                    return Some(path);
                }
                queue.push_back(next);
            }
        }
        None
    }

    /// **Bridge centrality**: how much of the slice a declaration is load-bearing for.
    ///
    /// atlas.md: "declarations whose removal disconnects theory clusters are the
    /// load-bearing walls, and agents should know a wall when they lean on one." The
    /// measure is the size of the declaration's transitive impact — exactly how many
    /// things stop having a proof if it turns out to be wrong.
    ///
    /// It is *not* articulation-point centrality, which is what "disconnects clusters"
    /// literally asks for; that needs the cluster structure B4/B5 supply. Named rather
    /// than implied, and the two agree at the extremes.
    ///
    /// One BFS, so this is cheap for a named declaration and expensive for all of them —
    /// see [`Graph::ranked_by_citations`].
    pub fn bridge_centrality(&self, name: &str, lens: Lens) -> usize {
        self.impact(name, lens).len()
    }

    /// How many declarations cite `name` *directly*.
    pub fn citations(&self, name: &str, lens: Lens) -> usize {
        self.predecessors(name, lens).len()
    }

    /// Every declaration ranked by how many others cite it directly.
    ///
    /// **Direct, not transitive, and the distinction is deliberate.** Ranking a whole
    /// slice by transitive impact is one BFS per node — quadratic, and a Mathlib slice is
    /// 75,000 nodes, so it does not finish. Direct citation count is a single pass, is a
    /// real measure rather than an approximation of one, and agrees with the transitive
    /// ranking on the extremes that matter (`Eq` and `Nat` are walls either way).
    ///
    /// Transitive ranking over a full slice wants SCC condensation with a reverse
    /// topological count, which is B2 work this does not do yet. Ask
    /// [`Graph::bridge_centrality`] about a *named* declaration and you get the transitive
    /// answer immediately.
    pub fn ranked_by_citations(&self, lens: Lens) -> Vec<(String, usize)> {
        let mut v: Vec<(String, usize)> = self
            .decls
            .keys()
            .map(|n| (n.clone(), self.citations(n, lens)))
            .collect();
        v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        v
    }
}

fn parse_row(line: &str) -> Result<Decl, String> {
    let obj = crate::json::parse(line)?;
    parse_row_value(&obj)
}

/// Parse one already-decoded row. Shared with the skeleton index so every engine applies
/// the same envelope-version and metadata checks without parsing the JSON twice.
pub(crate) fn parse_row_value(obj: &crate::json::Value) -> Result<Decl, String> {
    let get_str =
        |k: &str| -> Option<String> { obj.get(k).and_then(|v| v.as_str()).map(str::to_string) };
    let get_list = |k: &str| -> Vec<String> {
        obj.get(k)
            .and_then(|v| v.as_list())
            .map(|items| {
                items
                    .iter()
                    .filter_map(|v| v.as_str())
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default()
    };
    let schema = match obj.get("schema") {
        None => RowSchema::Legacy,
        Some(v) => match v.as_str() {
            Some(ROW_SCHEMA_V2) => RowSchema::V2,
            Some(other) => return Err(format!("unsupported row schema `{other}`")),
            None => return Err("`schema` must be a string".into()),
        },
    };
    let is_instance = match obj.get("is_instance") {
        Some(v) => Some(v.as_bool().ok_or("`is_instance` must be a boolean")?),
        None if schema == RowSchema::V2 => {
            return Err("atlas-row-v2 row has no `is_instance`".into());
        }
        None => None,
    };
    let requirements_statement = match obj.get("requirements_statement") {
        Some(v) => {
            let items = v
                .as_list()
                .ok_or("`requirements_statement` must be a list")?;
            let mut out = Vec::with_capacity(items.len());
            for (j, item) in items.iter().enumerate() {
                let source = item
                    .get("source")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| format!("requirements_statement[{j}] has no string `source`"))?;
                let class_name = item
                    .get("class")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| format!("requirements_statement[{j}] has no string `class`"))?;
                let carrier = item
                    .get("carrier")
                    .and_then(|v| v.as_num())
                    .ok_or_else(|| {
                        format!("requirements_statement[{j}] has no numeric `carrier`")
                    })?;
                if !carrier.is_finite()
                    || carrier < 0.0
                    || carrier.fract() != 0.0
                    || carrier > usize::MAX as f64
                {
                    return Err(format!(
                        "requirements_statement[{j}].carrier is not a non-negative integer"
                    ));
                }
                out.push(ClassRequirement {
                    source: source.to_string(),
                    class_name: class_name.to_string(),
                    carrier: carrier as usize,
                });
            }
            Some(out)
        }
        None if schema == RowSchema::V2 => {
            return Err("atlas-row-v2 row has no `requirements_statement`".into());
        }
        None => None,
    };
    let name = get_str("name").ok_or("row has no `name`")?;
    let kind = match (schema, get_str("kind")) {
        (RowSchema::V2, None) => return Err("atlas-row-v2 row has no string `kind`".into()),
        (_, value) => value.unwrap_or_default(),
    };
    let module = match (schema, get_str("module")) {
        (RowSchema::V2, None) => return Err("atlas-row-v2 row has no string `module`".into()),
        (_, value) => value.unwrap_or_default(),
    };
    let strict_list = |key: &str| -> Result<Vec<String>, String> {
        let values = obj
            .get(key)
            .and_then(|v| v.as_list())
            .ok_or_else(|| format!("atlas-row-v2 row has no list `{key}`"))?;
        values
            .iter()
            .enumerate()
            .map(|(j, value)| {
                value
                    .as_str()
                    .map(str::to_string)
                    .ok_or_else(|| format!("{key}[{j}] must be a string"))
            })
            .collect()
    };
    let uses_statement = if schema == RowSchema::V2 {
        strict_list("uses_statement")?
    } else {
        get_list("uses_statement")
    };
    let uses_proof = if schema == RowSchema::V2 {
        strict_list("uses_proof")?
    } else {
        get_list("uses_proof")
    };
    let stmt = get_str("stmt");
    let stmt_error = get_str("stmt_error");
    if schema == RowSchema::V2 && stmt.is_some() == stmt_error.is_some() {
        return Err("atlas-row-v2 row must carry exactly one of `stmt` and `stmt_error`".into());
    }
    Ok(Decl {
        schema,
        name,
        kind,
        module,
        is_instance,
        stmt,
        stmt_error,
        uses_statement,
        uses_proof,
        requirements_statement,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A slice with the shape the queries are about: a theorem whose *statement* mentions
    /// one thing and whose *proof* rests on another. Keeping the two apart is the point of
    /// the lens, so every fixture here has to be able to tell them apart.
    fn slice() -> Graph {
        Graph::from_jsonl(
            r#"
{"name":"Nat","kind":"inductive","module":"Init.Prelude","stmt":"s","uses_statement":[],"uses_proof":[]}
{"name":"Nat.add","kind":"def","module":"Init.Prelude","stmt":"s","uses_statement":["Nat"],"uses_proof":["Nat"]}
{"name":"Nat.add_comm","kind":"theorem","module":"Init.Nat","stmt":"s","uses_statement":["Nat","Nat.add"],"uses_proof":["Nat.add_assoc"]}
{"name":"Nat.add_assoc","kind":"theorem","module":"Init.Nat","stmt":"s","uses_statement":["Nat","Nat.add"],"uses_proof":["Nat.rec"]}
{"name":"Nat.rec","kind":"recursor","module":"Init.Prelude","stmt_error":"recursor","uses_statement":["Nat"],"uses_proof":[]}
"#,
        )
        .unwrap()
    }

    #[test]
    fn reads_b1_rows_including_unencodable_ones() {
        let g = slice();
        assert_eq!(g.len(), 5);
        let add_comm = g.get("Nat.add_comm").unwrap();
        assert_eq!(add_comm.kind, "theorem");
        assert_eq!(add_comm.schema, RowSchema::Legacy);
        assert_eq!(add_comm.is_instance, None);
        assert_eq!(add_comm.requirements_statement, None);
        // B1 keeps a row whose statement could not be encoded rather than dropping it.
        let rec = g.get("Nat.rec").unwrap();
        assert_eq!(rec.stmt, None);
        assert_eq!(rec.stmt_error.as_deref(), Some("recursor"));
    }

    #[test]
    fn reads_v2_role_and_source_attributed_requirement_fields() {
        let g = Graph::from_jsonl(
            r#"{"schema":"atlas-row-v2","name":"M.foo","kind":"theorem","module":"M","is_instance":false,"stmt":"s","requirements_statement":[{"source":"HMul.hMul","class":"HMul","carrier":1},{"source":"LT.lt","class":"LT","carrier":0}],"uses_statement":[],"uses_proof":[]}"#,
        )
        .unwrap();
        let d = g.get("M.foo").unwrap();
        assert_eq!(d.schema, RowSchema::V2);
        assert_eq!(d.is_instance, Some(false));
        assert_eq!(
            d.requirements_statement.as_deref(),
            Some(
                [
                    ClassRequirement {
                        source: "HMul.hMul".into(),
                        class_name: "HMul".into(),
                        carrier: 1,
                    },
                    ClassRequirement {
                        source: "LT.lt".into(),
                        class_name: "LT".into(),
                        carrier: 0,
                    },
                ]
                .as_slice()
            )
        );
    }

    #[test]
    fn v2_known_empty_requirements_are_not_legacy_unknown() {
        let g = Graph::from_jsonl(
            r#"{"schema":"atlas-row-v2","name":"M.inst","kind":"theorem","module":"M","is_instance":true,"stmt":"s","requirements_statement":[],"uses_statement":[],"uses_proof":[]}"#,
        )
        .unwrap();
        let d = g.get("M.inst").unwrap();
        assert_eq!(d.is_instance, Some(true));
        assert_eq!(d.requirements_statement, Some(Vec::new()));
    }

    #[test]
    fn v2_refuses_missing_or_malformed_required_metadata() {
        let missing = Graph::from_jsonl(
            r#"{"schema":"atlas-row-v2","name":"M.foo","kind":"theorem","module":"M","requirements_statement":[],"uses_statement":[],"uses_proof":[]}"#,
        )
        .unwrap_err();
        assert!(missing.to_string().contains("no `is_instance`"));

        let malformed = Graph::from_jsonl(
            r#"{"schema":"atlas-row-v2","name":"M.foo","kind":"theorem","module":"M","is_instance":false,"requirements_statement":[{"source":"f","class":"C","carrier":-1}],"uses_statement":[],"uses_proof":[]}"#,
        )
        .unwrap_err();
        assert!(malformed.to_string().contains("non-negative integer"));

        let ambiguous_statement = Graph::from_jsonl(
            r#"{"schema":"atlas-row-v2","name":"M.foo","kind":"theorem","module":"M","is_instance":false,"stmt":"s","stmt_error":"also bad","requirements_statement":[],"uses_statement":[],"uses_proof":[]}"#,
        )
        .unwrap_err();
        assert!(ambiguous_statement.to_string().contains("exactly one"));

        let malformed_dependencies = Graph::from_jsonl(
            r#"{"schema":"atlas-row-v2","name":"M.foo","kind":"theorem","module":"M","is_instance":false,"stmt":"s","requirements_statement":[],"uses_statement":[3],"uses_proof":[]}"#,
        )
        .unwrap_err();
        assert!(
            malformed_dependencies
                .to_string()
                .contains("uses_statement[0] must be a string")
        );
    }

    #[test]
    fn unknown_row_schema_is_distinct_from_bad_statement_data() {
        let err = Graph::from_jsonl(
            r#"{"schema":"atlas-row-v99","name":"M.foo","kind":"theorem","module":"M","uses_statement":[],"uses_proof":[]}"#,
        )
        .unwrap_err();
        assert!(
            err.to_string()
                .contains("unsupported row schema `atlas-row-v99`")
        );
    }

    #[test]
    fn the_lens_separates_claim_from_argument() {
        let g = slice();
        // `add_comm` *says* something about `Nat.add`; it is *argued* from `add_assoc`.
        // A query that conflated the two would report both under either lens, which is
        // exactly the blur B1's two lists exist to prevent.
        assert!(
            g.foundations("Nat.add_comm", Lens::Statement)
                .contains("Nat.add")
        );
        assert!(
            !g.foundations("Nat.add_comm", Lens::Statement)
                .contains("Nat.add_assoc")
        );
        assert!(
            g.foundations("Nat.add_comm", Lens::Proof)
                .contains("Nat.add_assoc")
        );
        assert!(
            !g.foundations("Nat.add_comm", Lens::Proof)
                .contains("Nat.add")
        );
    }

    #[test]
    fn foundations_are_transitive() {
        let g = slice();
        // add_comm -proof-> add_assoc -proof-> Nat.rec, so `Nat.rec` is a foundation of
        // `add_comm` even though nothing in it mentions the recursor directly.
        let f = g.foundations("Nat.add_comm", Lens::Proof);
        assert!(f.contains("Nat.add_assoc"));
        assert!(f.contains("Nat.rec"));
    }

    #[test]
    fn impact_is_the_converse_of_foundations() {
        let g = slice();
        // The property that makes the pair trustworthy: y is a foundation of x exactly
        // when x is in y's impact. Checked over every pair in the slice rather than on
        // one example, since a one-sided bug is the easy one to write.
        for a in g.names() {
            for b in g.names() {
                assert_eq!(
                    g.foundations(a, Lens::Both).contains(b),
                    g.impact(b, Lens::Both).contains(a),
                    "asymmetry between foundations({a}) and impact({b})"
                );
            }
        }
    }

    #[test]
    fn why_returns_a_real_chain() {
        let g = slice();
        let path = g.why("Nat.add_comm", "Nat.rec", Lens::Proof).unwrap();
        assert_eq!(path, vec!["Nat.add_comm", "Nat.add_assoc", "Nat.rec"]);
        // And every consecutive pair is an actual edge — a path query that returned
        // plausible-looking names would be worse than one that returned nothing.
        for w in path.windows(2) {
            assert!(
                g.get(&w[0]).unwrap().uses_proof.contains(&w[1]),
                "{} does not cite {}",
                w[0],
                w[1]
            );
        }
    }

    #[test]
    fn why_is_lens_sensitive_and_can_fail() {
        let g = slice();
        // Reachable through proofs, not through statements: `add_comm`'s *claim* says
        // nothing that leads to the recursor.
        assert!(g.why("Nat.add_comm", "Nat.rec", Lens::Proof).is_some());
        assert!(g.why("Nat.add_comm", "Nat.rec", Lens::Statement).is_none());
        // Dependency runs one way. Nothing `Nat` rests on reaches `add_comm`.
        assert!(g.why("Nat", "Nat.add_comm", Lens::Both).is_none());
    }

    #[test]
    fn a_declaration_is_not_its_own_foundation() {
        let g = Graph::from_jsonl(
            r#"{"name":"A","kind":"def","module":"M","stmt":"s","uses_statement":["B"],"uses_proof":[]}
{"name":"B","kind":"def","module":"M","stmt":"s","uses_statement":["A"],"uses_proof":[]}"#,
        )
        .unwrap();
        // Mutual recursion makes `A` reachable from itself; reporting it as its own
        // foundation would be noise, and the traversal has to terminate regardless.
        assert_eq!(
            g.foundations("A", Lens::Both),
            BTreeSet::from(["B".to_string()])
        );
        assert_eq!(
            g.foundations("B", Lens::Both),
            BTreeSet::from(["A".to_string()])
        );
    }

    #[test]
    fn walls_rank_by_how_much_rests_on_them() {
        let g = slice();
        let ranked = g.ranked_by_citations(Lens::Both);
        // `Nat` is under everything here, so it is the wall — and it is the wall under
        // both the cheap direct measure and the transitive one, which is the agreement
        // the ranking's docstring claims.
        assert_eq!(ranked[0].0, "Nat");
        assert_eq!(g.bridge_centrality("Nat", Lens::Both), g.len() - 1);
        // And the ranking agrees with the metric it claims to report.
        for (name, n) in &ranked {
            assert_eq!(*n, g.citations(name, Lens::Both));
        }
    }

    #[test]
    fn direct_citations_bound_transitive_impact() {
        // The relationship that makes the cheap ranking defensible: everything that cites
        // a declaration directly also rests on it, so direct count never exceeds
        // transitive, and a wall by the cheap measure is a wall by the real one.
        let g = slice();
        for n in g.names() {
            assert!(g.citations(n, Lens::Both) <= g.bridge_centrality(n, Lens::Both));
        }
    }

    #[test]
    fn edges_out_of_the_slice_are_kept() {
        // A boundary declaration cites something not extracted. Dropping the edge would
        // make it look self-supporting, which is the opposite of the truth.
        let g = Graph::from_jsonl(
            r#"{"name":"A","kind":"theorem","module":"M","stmt":"s","uses_statement":[],"uses_proof":["Outside"]}"#,
        )
        .unwrap();
        assert_eq!(g.len(), 1);
        assert!(g.foundations("A", Lens::Proof).contains("Outside"));
        assert!(g.impact("Outside", Lens::Proof).contains("A"));
    }

    #[test]
    fn a_malformed_row_names_its_line() {
        let err = Graph::from_jsonl("{\"name\":\"A\",\"uses_proof\":[]}\nnot json\n").unwrap_err();
        assert_eq!(
            err,
            GraphError::BadRow {
                line: 2,
                reason: "expected `null`".into()
            }
        );
    }

    #[test]
    fn a_row_without_a_name_is_an_error_not_a_silent_skip() {
        let err = Graph::from_jsonl(r#"{"kind":"def"}"#).unwrap_err();
        assert!(matches!(err, GraphError::BadRow { line: 1, .. }));
    }

    #[test]
    fn blank_lines_are_ignored() {
        let g = Graph::from_jsonl("\n\n{\"name\":\"A\"}\n\n").unwrap();
        assert_eq!(g.len(), 1);
    }
}
