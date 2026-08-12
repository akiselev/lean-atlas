//! Dictionaries, transport and the frontier (B6, atlas.md §2).
//!
//! atlas.md calls these "query-layer compositions once the indexes exist", and they are:
//! every one is B4's skeletons and B2's citation graph asked a different question.
//!
//! * **`dictionary A B`** — the maximal partial functor between two theory fragments:
//!   every skeleton-matched row, tagged with its epistemic status, plus the report that
//!   matters most, the **missing entries** — concepts on one side with no partner on the
//!   other. atlas.md's canonical example is the number-field/function-field dictionary's
//!   missing Frobenius row.
//! * **`transport row stmt`** — apply a row's substitution and hand the image on. All
//!   three outcomes are signal: it already exists (the dictionary is strengthened), it is
//!   refuted (**the analogy's boundary is located**, which is itself structural knowledge),
//!   or it is open (a directed target).
//! * **`frontier`** — theory pairs with high skeleton similarity and near-zero
//!   cross-citation. Similarity without traffic is an unexplored interface, and the ranked
//!   list is a research agenda.
//!
//! # A theory is a module prefix
//!
//! Crude and honest. `Mathlib.Algebra` and `Mathlib.Analysis` are different theories;
//! `Mathlib.Algebra.Order.Field.Basic` and `Mathlib.Algebra.Group.Defs` are the same one.
//! Depth 2 for Mathlib, depth 1 elsewhere, which is the same rule `similar`'s cross-theory
//! boost uses so the two agree about what "cross-theory" means.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use crate::graph::Graph;
use crate::skel::erase::Level;
use crate::skel::index::{IndexConfig, SkeletonIndex};
use crate::skel::lgg::matches;
use crate::skel::term::{Arena, Node, TermId};

/// Does this declaration belong to the theory the caller named?
///
/// `theory_of` files everything under a fixed depth — 2 inside `Mathlib`, 1 elsewhere — so
/// `theory_of("Physlib.Relativity") == "Physlib"` and an exact-equality test against the
/// string `"Physlib.Relativity"` matches **nothing**. `dictionary` then returned **0 rows
/// with no error**, which is indistinguishable from "these two theories share no structure"
/// and was read as exactly that.
///
/// Membership is therefore a *prefix* test on module-path components, so a caller may name
/// a theory at whatever depth their library organises it: `Physlib`, `Physlib.Relativity`
/// and `Mathlib.Algebra` all work. Component-wise so that `Mathlib.Algebra` does not
/// swallow `Mathlib.AlgebraicGeometry`.
pub fn in_theory(module: &str, theory: &str) -> bool {
    module == theory
        || (module.starts_with(theory) && module.as_bytes().get(theory.len()) == Some(&b'.'))
}

/// Every theory name present in the index, at `theory_of`'s depth. For diagnostics: a
/// caller who names a theory that matches nothing needs to be told what does exist.
pub fn theories_present(idx: &SkeletonIndex) -> Vec<String> {
    let mut out: BTreeSet<String> = BTreeSet::new();
    for i in 0..idx.len() {
        let n = idx.name_of(crate::skel::index::DeclId(i as u32));
        if let Some(m) = idx.module_of(n) {
            out.insert(theory_of(m).to_string());
        }
    }
    out.into_iter().collect()
}

/// A declaration's theory: the module prefix at the depth that distinguishes subjects.
pub fn theory_of(module: &str) -> &str {
    let depth = if module.starts_with("Mathlib.") { 2 } else { 1 };
    let mut end = module.len();
    let mut seen = 0;
    for (i, c) in module.char_indices() {
        if c == '.' {
            seen += 1;
            if seen == depth {
                end = i;
                break;
            }
        }
    }
    &module[..end]
}

/// Whether both halves of a row are established, one, or neither.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Status {
    BothProven,
    OneProven,
    NeitherProven,
}

impl Status {
    pub fn name(self) -> &'static str {
        match self {
            Status::BothProven => "both-proven",
            Status::OneProven => "one-proven",
            Status::NeitherProven => "neither-proven",
        }
    }
}

/// One candidate dictionary row.
#[derive(Clone, Debug)]
pub struct Row {
    pub left: String,
    pub right: String,
    pub skeleton: String,
    pub retention: f32,
    /// The full ranking score, not just retention. They differ: `retention` omits
    /// `scoped_penalty`, so weighting a solver by retention alone would systematically
    /// prefer rows that cannot be transported — 47.5% of the rows on the first slice.
    pub score: f32,
    pub status: Status,
    /// True when no variable abstracts a locally bound thing. `transport` refuses the
    /// rest: a row whose hole stands for something under a binder cannot be instantiated
    /// independently of that binder.
    pub transportable: bool,
}

/// A dictionary between two theory fragments.
pub struct Dictionary {
    pub left_theory: String,
    pub right_theory: String,
    pub rows: Vec<Row>,
    /// Declarations on the left with no partner on the right. **The point of the
    /// exercise**: a missing entry is where the analogy has not been made, which is where
    /// the research is.
    pub missing_left: Vec<String>,
    pub missing_right: Vec<String>,
}

/// How a dictionary is assembled. A struct rather than five positional arguments,
/// because the review that produced `pool_width` and `exclude_subprefix` will not be the
/// last to add one.
#[derive(Clone, Debug, PartialEq)]
pub struct DictOptions {
    /// Rows kept per left declaration.
    pub per_decl: usize,
    pub theorems_only: bool,
    /// Candidates retrieved per left. Distinct from `per_decl` on purpose: the selection
    /// needs alternatives to choose between, and taking `per_decl * 4` globally left most
    /// lefts with exactly one right-theory candidate — a "choice" with one option.
    pub pool_width: usize,
    /// Right-hand sub-prefixes to drop. `theory_of` files `Mathlib.Algebra.Order.*` under
    /// `Mathlib.Algebra`, so 27.1% of an Order <-> Algebra dictionary was order theory
    /// matched against itself. Excluded here rather than by changing `theory_of`, which
    /// `frontier` shares and which C1 replaces with versioned cluster manifests anyway.
    pub exclude_subprefix: Vec<String>,
    /// How many lefts may claim one right. `None` keeps the historical behaviour.
    ///
    /// Unbounded, a dictionary is not a map: measured on physlib,
    /// `ClassicalMechanics ~ QuantumMechanics` produces 169 rows over 44 distinct rights
    /// with **95.9% of rows in collision**, and the worst targets are `noConfusion`
    /// (claimed by 14 lefts, three times over) and `ξ_pos` (9 lefts) — auto-generated or
    /// content-free statements that match anything of their shape.
    ///
    /// Capping requires assembling globally rather than greedily per left, so that the
    /// best-scoring claim on a contested right wins rather than the alphabetically first.
    /// `dictionary_policies` already computes this frontier; this connects it to the
    /// assembly, which previously used none of it.
    pub max_per_right: Option<usize>,
    /// Final name components treated as administrative rather than mathematical.
    ///
    /// The worst collision target on the first run was `instReflDvd_mathlib`, claimed by
    /// fourteen lefts — a typeclass instance whose extracted `kind` is `"theorem"`, so
    /// `theorems_only` cannot see it. B1 emits no `is_instance`, so this is a **name
    /// heuristic and is reported as one**: it caught 6.9% of rows on the first slice, and
    /// a principled fix needs a field the extractor does not yet have.
    pub exclude_roles: Vec<String>,
    /// Order candidates and rows by `retention` instead of by the full score.
    ///
    /// Off by default because `Row::score`'s caveat still holds within one theory:
    /// retention omits `scoped_penalty`, so it prefers rows that cannot be transported.
    /// *Across* theories the trade inverts (findings §74): every size-flavoured factor in
    /// the score rewards shared framework mass — rows agreeing on tens of thousands of
    /// apparatus nodes and no claim — which is anti-correlated with cross-domain content.
    /// Measured on the 95,268-row physics corpus, the four validated classical↔quantum
    /// correspondences rank 437–1,150 of 3,029 under retention × support against 17–525
    /// under retention alone. The tie-breaks are `similar`'s own: `common`, then `vars`,
    /// then the name.
    ///
    /// The re-ordering happens inside the retrieved pool: retrieval still returns the
    /// `pool_width` best *by score*, so a partner outside that pool is not recovered by
    /// this knob — widen `pool_width` for that.
    pub rank_by_retention: bool,
    /// Count the `per_decl` cap per (left, skeleton) instead of per left.
    ///
    /// `per_decl = 1` is winner-take-all, and winner-take-all manufactures false
    /// negatives: §74 measured 315 rows displaced, among them the unregistered
    /// von Neumann ~ Gibbs entropy bridge (`Sᵥₙ_nonneg ~ CanonicalEnsemble.entropy_nonneg`,
    /// retention 0.684), evicted by a content-free positivity lookalike (`0 ≤ Z`,
    /// retention 0.9412). No rank key repairs that — the lookalike outscores the bridge on
    /// retention too — so the honest control keeps the displaced row rather than re-losing
    /// it. Two rows with the *same* rendered skeleton are the same structural claim worn by
    /// different partners, and capping those loses nothing; a row with a *different*
    /// skeleton is a different claim, and deleting a claim is exactly the §74 defect. So
    /// the cap moves to (left, skeleton): each structurally distinct claim gets its own
    /// `per_decl` slots, and family clones stay capped.
    pub per_decl_keep_displaced: bool,
    /// Drop rows whose two declarations cite each other — either direction, either lens.
    ///
    /// `frontier` discounts citation traffic for the same reason: similarity plus traffic
    /// is usage, not analogy. §74's graded top-40 was led by 14 rows pairing a framework
    /// with its own instantiations — every anomaly-cancellation lemma against the
    /// `linearSol` structure field its proof projects out of. The notion is frontier's:
    /// a *direct* `uses_statement`/`uses_proof` edge, not transitive reachability, which
    /// on a corpus where everything rests on shared plumbing would be a different and far
    /// more destructive filter. Requires the citation graph to be passed to
    /// [`dictionary`]; asking for the filter without one is refused, not ignored.
    pub exclude_cited: bool,
}

impl Default for DictOptions {
    fn default() -> DictOptions {
        DictOptions {
            per_decl: 1,
            theorems_only: true,
            pool_width: 64,
            max_per_right: None,
            exclude_subprefix: Vec::new(),
            exclude_roles: Vec::new(),
            rank_by_retention: false,
            per_decl_keep_displaced: false,
            exclude_cited: false,
        }
    }
}

/// Is this name administrative under the given heuristics?
fn excluded_role(name: &str, roles: &[String]) -> bool {
    let last = name.rsplit('.').next().unwrap_or(name);
    roles.iter().any(|r| {
        if let Some(pre) = r.strip_suffix('*') {
            last.starts_with(pre)
        } else {
            last == r
        }
    })
}

/// Frontier's citation notion, applied to one ordered pair: does `from`'s statement or
/// proof cite `to` directly? [`frontier`] counts exactly these edges when it discounts a
/// theory pair for traffic; `exclude_cited` reuses the notion so the two queries agree
/// about what "citation-linked" means.
fn cites_directly(g: &Graph, from: &str, to: &str) -> bool {
    g.get(from).is_some_and(|d| {
        d.uses_statement
            .iter()
            .chain(d.uses_proof.iter())
            .any(|u| u == to)
    })
}

/// Assemble the maximal partial functor between two theories.
/// `theorems_only` for the same reason [`frontier`] wants it: a dictionary row between two
/// *recursors* (`Compl.rec ~ Star.rec`) is a fact about how Lean compiles inductive types,
/// not a structure-preserving map between theories.
///
/// `graph` is only consulted when `opts.exclude_cited` asks for it; every other option
/// works with `None`. Asking for the citation filter without a graph panics rather than
/// silently keeping the citation-linked rows — a filter that quietly does nothing is
/// indistinguishable from a clean result, which is the failure mode §5's traps keep
/// documenting.
pub fn dictionary(
    idx: &mut SkeletonIndex,
    graph: Option<&Graph>,
    left: &str,
    right: &str,
    cfg: &IndexConfig,
    opts: &DictOptions,
) -> Dictionary {
    assert!(
        graph.is_some() || !opts.exclude_cited,
        "exclude_cited needs the citation graph: pass `Some(&graph)` to `dictionary`"
    );
    let (per_decl, theorems_only) = (opts.per_decl, opts.theorems_only);
    // Retrieval itself is restricted to the target theory, so the pool is candidates that
    // can become rows rather than a global top-N mostly discarded a line later.
    let cfg = &IndexConfig {
        restrict_prefix: Some(right.to_string()),
        theorems_only,
        ..cfg.clone()
    };
    let (mut rows, mut matched_left, mut matched_right) =
        (Vec::new(), BTreeSet::new(), BTreeSet::new());
    let names: Vec<String> = (0..idx.len())
        .map(|i| {
            idx.name_of(crate::skel::index::DeclId(i as u32))
                .to_string()
        })
        .collect();
    let lefts: Vec<String> = names
        .iter()
        .filter(|n| idx.module_of(n).is_some_and(|m| in_theory(m, left)))
        .filter(|n| !theorems_only || idx.is_theorem(n))
        .cloned()
        .collect();

    // When a right may be claimed only so many times, the contest has to be settled
    // globally: greedy per-left assembly hands a contested right to whichever left the
    // iteration reached first, which is alphabetical order and not a judgement. Candidates
    // are therefore collected, sorted by the rank key (the score, or retention when
    // `rank_by_retention` is set), and allocated best-first.
    let mut pending: Vec<(f32, Row)> = Vec::new();

    for name in &lefts {
        let Ok(mut neighbours) = idx.similar(name, opts.pool_width, cfg) else {
            continue;
        };
        // The retrieved pool is still `similar`'s top `pool_width` by score; the knob
        // re-orders the choice *within* it, with `similar`'s own tie-breaks so the two
        // orderings differ in exactly one thing — the key.
        if opts.rank_by_retention {
            neighbours.sort_by(|a, b| {
                b.retention
                    .total_cmp(&a.retention)
                    .then(b.common.cmp(&a.common))
                    .then(a.vars.cmp(&b.vars))
                    .then(a.name.cmp(&b.name))
            });
        }
        let mut kept = 0;
        // Rows already kept for this left, by rendered skeleton — the unit
        // `per_decl_keep_displaced` caps on.
        let mut kept_per_skeleton: HashMap<String, usize> = HashMap::new();
        for n in neighbours {
            if !in_theory(&n.module, right) || (theorems_only && !idx.is_theorem(&n.name)) {
                continue;
            }
            if opts
                .exclude_subprefix
                .iter()
                .any(|p| n.module == *p || n.module.starts_with(&format!("{p}.")))
            {
                continue;
            }
            if excluded_role(&n.name, &opts.exclude_roles) {
                continue;
            }
            // Filtered here, before slot accounting, so a citation-linked candidate frees
            // its slot for the next-ranked genuine one instead of consuming it.
            if opts.exclude_cited {
                let g = graph.expect("asserted at entry");
                if cites_directly(g, name, &n.name) || cites_directly(g, &n.name, name) {
                    continue;
                }
            }
            if opts.per_decl_keep_displaced {
                let c = kept_per_skeleton.entry(n.skeleton.clone()).or_insert(0);
                if *c >= per_decl {
                    continue;
                }
                *c += 1;
            }
            let status = match (idx.is_theorem(name), idx.is_theorem(&n.name)) {
                (true, true) => Status::BothProven,
                (true, false) | (false, true) => Status::OneProven,
                (false, false) => Status::NeitherProven,
            };
            let score = n.score;
            // The key the global contest is settled by, when there is one. It has to be
            // the same key the per-left choice used, or `max_per_right` would evict on a
            // different judgement than the one that admitted.
            let rank_key = if opts.rank_by_retention {
                n.retention
            } else {
                score
            };
            let row = Row {
                left: name.clone(),
                right: n.name.clone(),
                skeleton: n.skeleton,
                retention: n.retention,
                score,
                status,
                transportable: n.transportable,
            };
            if opts.max_per_right.is_none() {
                matched_left.insert(name.clone());
                matched_right.insert(row.right.clone());
                rows.push(row);
            } else {
                pending.push((rank_key, row));
            }
            kept += 1;
            if !opts.per_decl_keep_displaced && kept >= per_decl {
                break;
            }
        }
    }

    if let Some(cap) = opts.max_per_right {
        pending.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.left.cmp(&b.1.left)));
        let mut claims: HashMap<String, usize> = HashMap::new();
        let mut per_left: HashMap<String, usize> = HashMap::new();
        let mut per_left_skeleton: HashMap<(String, String), usize> = HashMap::new();
        for (_s, row) in pending {
            let c = claims.entry(row.right.clone()).or_insert(0);
            if *c >= cap {
                continue;
            }
            // The same unit the retrieval loop counted in: per left, or per
            // (left, skeleton) when displaced claims are kept.
            let l = if opts.per_decl_keep_displaced {
                per_left_skeleton
                    .entry((row.left.clone(), row.skeleton.clone()))
                    .or_insert(0)
            } else {
                per_left.entry(row.left.clone()).or_insert(0)
            };
            if *l >= per_decl {
                continue;
            }
            *c += 1;
            *l += 1;
            matched_left.insert(row.left.clone());
            matched_right.insert(row.right.clone());
            rows.push(row);
        }
    }

    let rights: Vec<String> = names
        .iter()
        .filter(|n| idx.module_of(n).is_some_and(|m| in_theory(m, right)))
        .filter(|n| !theorems_only || idx.is_theorem(n))
        .cloned()
        .collect();
    // By `score`, not by `retention`. `Row::score`'s own doc comment already says why —
    // retention omits every ranking factor, so ordering by it "would systematically prefer
    // rows that cannot be transported" — and the sort did it anyway, which meant the
    // scorer had no effect on what a reader saw first. Measured consequence: the
    // `Relativity ~ QFT` dictionary opened with `CausalCharacter.lightLike ~
    // annihilate.sizeOf_spec`, and adding a derivativeness penalty to the score changed
    // the presented rows not at all, because the presentation never consulted the score.
    //
    // `rank_by_retention` is the measured exception (§74): for *cross-domain* content
    // every size-flavoured score factor rewards shared apparatus mass, so the caller who
    // set the knob gets retention here too — the presented order and the per-left choice
    // must agree on the key, or the knob would choose one row and show another first.
    if opts.rank_by_retention {
        rows.sort_by(|a, b| {
            b.retention
                .total_cmp(&a.retention)
                .then(a.left.cmp(&b.left))
        });
    } else {
        rows.sort_by(|a, b| b.score.total_cmp(&a.score).then(a.left.cmp(&b.left)));
    }
    Dictionary {
        left_theory: left.to_string(),
        right_theory: right.to_string(),
        missing_left: lefts
            .into_iter()
            .filter(|n| !matched_left.contains(n))
            .collect(),
        missing_right: rights
            .into_iter()
            .filter(|n| !matched_right.contains(n))
            .collect(),
        rows,
    }
}

/// What transporting a statement produced.
#[derive(Clone, Debug)]
pub enum Transported {
    /// The image is already a declaration in the slice: the dictionary is strengthened
    /// and this row is now verified rather than candidate.
    Exists { name: String, image: String },
    /// The image is well-formed and not present. This is the directed target — hand it to
    /// the falsification battery first (`#atlas_falsify`) and to a prover second, because
    /// refutation is cheap and locates the analogy's boundary.
    Open { image: String },
}

/// Refusals, kept distinct from "nothing found".
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TransportError {
    NotInSlice(String),
    /// The statement does not match the row's left pattern, so the row says nothing about
    /// it. Not a failure of transport — a failure of applicability.
    NoMatch,
    /// A variable stands for something under a binder, so it cannot be instantiated
    /// independently. Reported rather than transported wrongly.
    Scoped,
}

impl std::fmt::Display for TransportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TransportError::NotInSlice(n) => write!(f, "`{n}` is not in this slice"),
            TransportError::NoMatch => {
                write!(
                    f,
                    "the statement does not match this row's left-hand pattern"
                )
            }
            TransportError::Scoped => write!(
                f,
                "this row has a variable standing for something under a binder, so it \
                 cannot be instantiated independently of that binder"
            ),
        }
    }
}

/// Apply a row to a statement: match the left, re-instantiate with the right.
///
/// The row is `lgg(left, right)`. Matching the subject against the skeleton gives the
/// subject's own instantiation; matching `right` against the same skeleton gives the
/// target's. Transport is composing the first with the second — which is exactly the
/// "partial structure-preserving map" a dictionary row *is*.
pub fn transport(
    idx: &mut SkeletonIndex,
    row_left: &str,
    row_right: &str,
    subject: &str,
    level: Level,
) -> Result<Transported, TransportError> {
    let (row, _) = idx
        .generalize_named(row_left, row_right, level)
        .map_err(TransportError::NotInSlice)?;
    if row.scoped_vars > 0 {
        return Err(TransportError::Scoped);
    }
    let skeleton = row.skeleton;
    let subj = idx
        .term_of(subject, level)
        .ok_or(TransportError::NotInSlice(subject.into()))?;
    let right = idx
        .term_of(row_right, level)
        .ok_or(TransportError::NotInSlice(row_right.into()))?;

    let left = idx
        .term_of(row_left, level)
        .ok_or(TransportError::NotInSlice(row_left.into()))?;

    let arena = idx.arena_mut();
    let sub_subject = matches(arena, skeleton, subj).ok_or(TransportError::NoMatch)?;
    let sub_right = matches(arena, skeleton, right).ok_or(TransportError::NoMatch)?;
    let sub_left = matches(arena, skeleton, left).ok_or(TransportError::NoMatch)?;

    // The image: the subject, with the row's correspondence applied.
    //
    // A row `left ~ right` over skeleton `S` asserts, at each hole `k`, that the left's
    // filling corresponds to the right's. Transporting a *subject* means rewriting the
    // subject's own fillings through that correspondence: where the subject fills a hole
    // the way the left does, the row says it should be filled the way the right does;
    // where it fills it with something else, the row says nothing and it stays.
    //
    // The previous construction took `sub_right` for every hole and fell back to the
    // subject only when `sub_right` lacked a binding — which it never can, since it was
    // obtained by matching the same skeleton against the right. So the fallback was dead
    // code, `image_subst` equalled `sub_right` identically, and the image was **always
    // `row_right` regardless of the subject**. Measured before the fix: 1,074 of 1,074
    // successful transports returned `.name == row.right`, 32 of 32 rows produced exactly
    // one image across hundreds of distinct subjects, and `.exists` was `true` every
    // time — so the operation atlas.md calls "the active operation" could not, even in
    // principle, emit the open target that is its entire purpose.
    let mut image_subst = HashMap::new();
    for (k, v) in &sub_subject {
        let moved = match (sub_left.get(k), sub_right.get(k)) {
            (Some(l), Some(r)) if l == v => *r,
            _ => *v,
        };
        image_subst.insert(*k, moved);
    }
    let image = substitute(arena, skeleton, &image_subst);
    let rendered = arena.render(image);
    match idx.name_with_term(image, level) {
        Some(name) => Ok(Transported::Exists {
            name,
            image: rendered,
        }),
        None => Ok(Transported::Open { image: rendered }),
    }
}

/// Replace each `Var(k)` with its binding.
pub fn substitute(a: &mut Arena, t: TermId, subst: &HashMap<u32, TermId>) -> TermId {
    let node = match a.node(t) {
        Node::Var(k) => return subst.get(&k).copied().unwrap_or(t),
        Node::App(x, y) => Node::App(substitute(a, x, subst), substitute(a, y, subst)),
        Node::Lam(b, d, y) => Node::Lam(b, substitute(a, d, subst), substitute(a, y, subst)),
        Node::Pi(b, d, y) => Node::Pi(b, substitute(a, d, subst), substitute(a, y, subst)),
        Node::Let(x, y, z) => Node::Let(
            substitute(a, x, subst),
            substitute(a, y, subst),
            substitute(a, z, subst),
        ),
        Node::Proj(s, i, e) => Node::Proj(s, i, substitute(a, e, subst)),
        _ => return t,
    };
    a.intern(node)
}

/// One theory pair's frontier reading.
#[derive(Clone, Debug)]
pub struct Frontier {
    pub left: String,
    pub right: String,
    /// Shape buckets both theories occupy, as a fraction of the smaller theory's buckets.
    pub similarity: f32,
    /// What two theories of these sizes would share by chance. See `frontier`.
    pub expected_similarity: f32,
    /// `similarity - expected_similarity`. The quantity the query is actually about:
    /// shared shape *beyond* what size alone explains. Can be negative, and often is —
    /// most theory pairs are less alike than chance, which is the finding that motivated
    /// adding this (`research/corpus-atlas-findings.md` §17–§18).
    pub excess: f32,
    /// Declarations in one theory whose statement or proof cites the other.
    pub cross_citations: usize,
    pub left_size: usize,
    pub right_size: usize,
    /// High similarity, low traffic. The ranked list is the research agenda.
    pub score: f32,
}

/// Theory pairs that look alike and do not talk to each other.
/// `theorems_only` is the useful default, and the reason is worth stating: without it the
/// top of the ranking is `Aesop ~ ProofWidgets`, `Aesop ~ Qq`, `Batteries ~ Mathlib.Lean`
/// — metaprogramming libraries that share shapes because they are all Lean code doing
/// monadic work over syntax trees, and that do not cite each other because they are
/// siblings. Structurally that is a correct answer to the question as posed. It is also
/// not mathematics, and a research agenda made of it would be a list of places to go
/// refactor.
///
/// This is the third place the same lesson has applied — B5's classes and dictionaries
/// need it too. In a corpus that is half infrastructure, "restrict to claims" is not a
/// filter, it is the difference between measuring mathematics and measuring Lean.
pub fn frontier(
    idx: &mut SkeletonIndex,
    graph: &Graph,
    min_theory_size: usize,
    top: usize,
    theorems_only: bool,
    exclude: &[String],
) -> Vec<Frontier> {
    // Which shape buckets each theory occupies, and which theory each declaration is in.
    let mut theory_shapes: BTreeMap<String, BTreeSet<TermId>> = BTreeMap::new();
    let mut theory_of_decl: HashMap<String, String> = HashMap::new();
    let mut sizes: BTreeMap<String, usize> = BTreeMap::new();
    for i in 0..idx.len() {
        let d = crate::skel::index::DeclId(i as u32);
        let name = idx.name_of(d).to_string();
        if theorems_only && !idx.is_theorem(&name) {
            continue;
        }
        let Some(m) = idx.module_of(&name) else {
            continue;
        };
        let th = theory_of(m).to_string();
        theory_of_decl.insert(name, th.clone());
        *sizes.entry(th.clone()).or_insert(0) += 1;
        let sh = idx.shape_of(d);
        theory_shapes.entry(th).or_default().insert(sh);
    }

    let theories: Vec<String> = sizes
        .iter()
        .filter(|&(_, &n)| n >= min_theory_size)
        .map(|(t, _)| t.clone())
        // Excluding infrastructure is not cheating, it is asking the question you meant.
        // On a corpus that is two-thirds `Init`/`Std`/`Lean`, the highest-scoring pairs
        // are metaprogramming siblings — correct, and not a mathematical agenda.
        .filter(|t| !exclude.iter().any(|e| t == e))
        .collect();

    // Cross-citation counts, from B2's graph rather than from imports: what a proof
    // actually uses, not what a file happens to import.
    let mut cites: HashMap<(String, String), usize> = HashMap::new();
    for name in graph.names() {
        let Some(from) = theory_of_decl.get(name.as_str()) else {
            continue;
        };
        let Some(decl) = graph.get(name) else {
            continue;
        };
        for used in decl.uses_statement.iter().chain(decl.uses_proof.iter()) {
            if let Some(to) = theory_of_decl.get(used.as_str())
                && to != from
            {
                let key = if from < to {
                    (from.clone(), to.clone())
                } else {
                    (to.clone(), from.clone())
                };
                *cites.entry(key).or_insert(0) += 1;
            }
        }
    }

    // How many distinct shapes the included theories occupy between them. The denominator
    // of the null below, so it is computed over exactly the theories being compared.
    let universe: BTreeSet<TermId> = theories
        .iter()
        .flat_map(|t| theory_shapes[t].iter().copied())
        .collect();
    let m = universe.len().max(1) as f32;

    let mut out = Vec::new();
    for (i, a) in theories.iter().enumerate() {
        for b in &theories[i + 1..] {
            let (sa, sb) = (&theory_shapes[a], &theory_shapes[b]);
            let shared = sa.intersection(sb).count();
            let denom = sa.len().min(sb.len()).max(1);
            let similarity = shared as f32 / denom as f32;
            // What two theories of these sizes would share **by chance**, if shapes were
            // assigned to theories at random: `E|A ∩ B| = |A||B|/M`, so dividing by
            // `min(|A|,|B|)` leaves `max(|A|,|B|)/M`.
            //
            // Without this the ranking is a size ranking. Measured on physlib, a
            // twenty-member family already spans 9.23 of 22 subfields by chance, and both
            // recorded frontier failures are this: `Mathlib.Algebra ~ Mathlib.Order` at
            // similarity 0.040 with 1,508 cross-citations (the largest pair, not the most
            // similar one), and physlib's units-API duplication. Raw similarity cannot
            // tell a real interface from a big theory.
            let expected = sa.len().max(sb.len()) as f32 / m;
            let excess = similarity - expected;
            let cross = cites.get(&(a.clone(), b.clone())).copied().unwrap_or(0);
            // Excess buys, traffic discounts. A theory pair that already cites each other
            // heavily is explored, whatever it looks like.
            let score = excess / (1.0 + (cross as f32).sqrt());
            out.push(Frontier {
                left: a.clone(),
                right: b.clone(),
                similarity,
                expected_similarity: expected,
                excess,
                cross_citations: cross,
                left_size: sizes[a],
                right_size: sizes[b],
                score,
            });
        }
    }
    out.sort_by(|x, y| y.score.total_cmp(&x.score).then(x.left.cmp(&y.left)));
    out.truncate(top);
    out
}

/// What a dictionary's row set actually is, as opposed to what it is called.
///
/// A dictionary is meant to be a *partial structure-preserving map*. Greedy
/// per-declaration selection cannot produce one — it returns each left's nearest
/// right-theory neighbour and nothing looks across rows — so the first thing M3a needs is
/// a way to say how far the output is from a map, before anything tries to fix it.
///
/// # Rights are counted by statement, not by name
///
/// `dvd_trans` and `Dvd.dvd.trans` are one theorem under two names, and a left displaced
/// onto the alias of its old partner would otherwise score as a coherence *improvement*.
/// So the collision count keys on the `Exact` skeleton — statement identity — and the
/// name-keyed count is reported beside it, because the gap between them is itself worth
/// seeing.
#[derive(Clone, Debug, PartialEq)]
pub struct Coherence {
    pub rows: usize,
    pub distinct_lefts: usize,
    /// Distinct right-hand *names*.
    pub distinct_rights: usize,
    /// Distinct right-hand *statements*. Lower than `distinct_rights` exactly when the
    /// dictionary points at two names for one theorem.
    pub distinct_right_statements: usize,
    /// Right statements claimed by more than one left.
    pub contested: usize,
    /// Rows whose right statement is contested — the fraction of the dictionary that is
    /// not a map.
    pub rows_in_collision: usize,
    /// The worst offenders: `(right name, number of lefts claiming its statement)`.
    pub worst: Vec<(String, usize)>,
}

impl Coherence {
    pub fn collision_rate(&self) -> f32 {
        self.rows_in_collision as f32 / self.rows.max(1) as f32
    }
}

/// Measure a dictionary against the map it claims to be.
pub fn coherence(idx: &mut SkeletonIndex, d: &Dictionary, worst: usize) -> Coherence {
    // Statement identity, so two names for one theorem count once. A name with no
    // encodable statement falls back to its own name, which cannot collide with anything.
    let mut key_of: HashMap<&str, String> = HashMap::new();
    for r in &d.rows {
        if !key_of.contains_key(r.right.as_str()) {
            let k = idx
                .skeleton_of(&r.right, Level::Exact)
                .unwrap_or_else(|| format!("\u{0}name:{}", r.right));
            key_of.insert(r.right.as_str(), k);
        }
    }

    let mut lefts_per_statement: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    for r in &d.rows {
        lefts_per_statement
            .entry(key_of[r.right.as_str()].as_str())
            .or_default()
            .insert(&r.left);
    }

    let contested: BTreeSet<&str> = lefts_per_statement
        .iter()
        .filter(|(_, ls)| ls.len() > 1)
        .map(|(k, _)| *k)
        .collect();

    let rows_in_collision = d
        .rows
        .iter()
        .filter(|r| contested.contains(key_of[r.right.as_str()].as_str()))
        .count();

    // Reported by a representative name rather than by the encoding, which is unreadable.
    let mut by_name: BTreeMap<&str, usize> = BTreeMap::new();
    for r in &d.rows {
        let n = lefts_per_statement[key_of[r.right.as_str()].as_str()].len();
        by_name.insert(&r.right, n);
    }
    let mut worst_v: Vec<(String, usize)> = by_name
        .into_iter()
        .filter(|(_, n)| *n > 1)
        .map(|(n, c)| (n.to_string(), c))
        .collect();
    worst_v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    worst_v.truncate(worst);

    Coherence {
        rows: d.rows.len(),
        distinct_lefts: d
            .rows
            .iter()
            .map(|r| &r.left)
            .collect::<BTreeSet<_>>()
            .len(),
        distinct_rights: d
            .rows
            .iter()
            .map(|r| &r.right)
            .collect::<BTreeSet<_>>()
            .len(),
        distinct_right_statements: lefts_per_statement.len(),
        contested: contested.len(),
        rows_in_collision,
        worst: worst_v,
    }
}

/// §9's acceptance criterion, as a runnable control: *"false shuffled mappings are
/// rejected at a substantially earlier rate than genuine mappings."*
///
/// Every gate M3a's first draft proposed measured the dictionary against itself —
/// injectivity, total score, row counts — and a perfectly injective, high-scoring,
/// entirely fabricated dictionary passes all of them. This is the one that a fabricated
/// dictionary fails: re-pair each left with a *different* right drawn from the same
/// theory, and compare the retention the anti-unifier assigns.
///
/// If genuine pairs do not separate from shuffled ones, the floors are admitting
/// coincidence and no number computed downstream is about analogy.
#[derive(Clone, Debug, PartialEq)]
pub struct ShuffleControl {
    pub pairs: usize,
    pub genuine_mean: f32,
    pub shuffled_mean: f32,
    /// Shuffled pairs that would clear the same floors the real rows cleared. The rate a
    /// coincidence survives the admission test.
    pub shuffled_admitted: usize,
    /// Fraction of (genuine, shuffled) comparisons where the genuine pair scores higher.
    /// 1.0 is perfect separation, 0.5 is chance.
    pub separation: f32,
}

/// Deterministic: the shuffle is a fixed stride through the right-hand pool, not a random
/// permutation, so a failure is reproducible and a reviewer can re-derive the pairing.
/// `stride` must be coprime with the pool size to be a permutation; 7919 is prime and
/// larger than any right-hand pool here.
pub fn shuffle_control(
    idx: &mut SkeletonIndex,
    d: &Dictionary,
    cfg: &IndexConfig,
) -> ShuffleControl {
    let rights: Vec<String> = d
        .rows
        .iter()
        .map(|r| r.right.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    if rights.len() < 2 || d.rows.is_empty() {
        return ShuffleControl {
            pairs: 0,
            genuine_mean: 0.0,
            shuffled_mean: 0.0,
            shuffled_admitted: 0,
            separation: 0.0,
        };
    }

    let (mut gsum, mut ssum, mut admitted, mut wins, mut n) =
        (0.0f32, 0.0f32, 0usize, 0usize, 0usize);
    for (i, r) in d.rows.iter().enumerate() {
        // A different right, chosen deterministically and never the true partner.
        let mut j = (i * 7919 + 13) % rights.len();
        if rights[j] == r.right {
            j = (j + 1) % rights.len();
        }
        let Ok((g, _)) = idx.generalize_named(&r.left, &rights[j], cfg.lgg_level) else {
            continue;
        };
        let shuffled = g.retention;
        if g.common >= cfg.min_common && shuffled >= cfg.min_retention {
            admitted += 1;
        }
        if r.retention > shuffled {
            wins += 1;
        }
        gsum += r.retention;
        ssum += shuffled;
        n += 1;
    }

    ShuffleControl {
        pairs: n,
        genuine_mean: gsum / n.max(1) as f32,
        shuffled_mean: ssum / n.max(1) as f32,
        shuffled_admitted: admitted,
        separation: wins as f32 / n.max(1) as f32,
    }
}

/// How many lefts a single right may serve.
///
/// A choice, not an assumption. Genuine many-to-one correspondences exist in mathematics —
/// several order-theoretic facts really do collapse onto one divisibility fact — so
/// forcing 1:1 manufactures a distinction the evidence does not support. Measured on the
/// first slice, `Injective` deleted 232 of 680 rows including correspondences scoring
/// 0.919, and moved 172 lefts onto partners the anti-unifier ranked *lower*. Hence the
/// default below, and hence the naming: a constrained result is a **selection**, not a
/// correspondence.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum Policy {
    /// Every candidate row survives. What greedy assembly produces, and the default.
    #[default]
    Unconstrained,
    /// At most one left per right.
    Injective,
    /// At most `cap` lefts per right.
    ManyToOne { cap: usize },
}

/// Why a left-hand declaration has no row.
///
/// Design §9 asks that a dictionary "distinguish absent, unsupported, low-ranked, and
/// contradicted". Those four are here. `Unmatched` is a fifth the document does not name
/// because it cannot arise without an assignment — it is the state the solver creates.
#[derive(Clone, Debug, PartialEq)]
pub enum LeftState {
    /// No candidate in the right theory was proposed at all. The index never reached it.
    Absent,
    /// Candidates existed and every one fell below the floors. Carries the best seen, so a
    /// reader can tell "nearly" from "nothing".
    LowRanked { best_retention: f32 },
    /// The engine declined rather than answered.
    Unsupported { reason: &'static str },
    /// A candidate cleared the floors and lost the assignment: this concept has a partner,
    /// but another concept had a better claim on it. Only reachable under a constrained
    /// policy — under `Unconstrained` it is unreachable by construction.
    Unmatched { best: String },
    /// A candidate exists and is refuted.
    ///
    /// **Not emittable yet.** Refutation is C6's falsification route, which M4 builds; the
    /// variant is present so the vocabulary is the document's rather than a subset of it,
    /// and so that adding the producer later is not also a schema change.
    Contradicted,
}

impl LeftState {
    pub fn name(&self) -> &'static str {
        match self {
            LeftState::Absent => "absent",
            LeftState::LowRanked { .. } => "low-ranked",
            LeftState::Unsupported { .. } => "unsupported",
            LeftState::Unmatched { .. } => "unmatched",
            LeftState::Contradicted => "contradicted",
        }
    }
}

/// Exact max-flow-then-min-cost over the candidate rows.
///
/// Coverage first, score second, and that order is deliberate: a dictionary that partners
/// more concepts at slightly lower mean quality is more useful than a smaller one with a
/// better sum, and "maximize the total score" is a proxy that would happily drop a left
/// entirely to raise an average. Costs are negated scores; the network is a DAG, so
/// Bellman-Ford shortest-path augmentation terminates without a negative-cycle check.
fn assign(rows: &[Row], policy: Policy) -> Vec<usize> {
    let cap_right = match policy {
        Policy::Unconstrained => return (0..rows.len()).collect(),
        Policy::Injective => 1,
        Policy::ManyToOne { cap } => cap.max(1),
    };

    let lefts: Vec<&str> = rows
        .iter()
        .map(|r| r.left.as_str())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let rights: Vec<&str> = rows
        .iter()
        .map(|r| r.right.as_str())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let li: HashMap<&str, usize> = lefts.iter().enumerate().map(|(i, n)| (*n, i)).collect();
    let ri: HashMap<&str, usize> = rights.iter().enumerate().map(|(i, n)| (*n, i)).collect();

    let (nl, nr) = (lefts.len(), rights.len());
    let (src, snk) = (nl + nr, nl + nr + 1);
    let n = nl + nr + 2;

    // (to, capacity, cost, index of the reverse arc)
    let mut g: Vec<Vec<(usize, i64, i64, usize)>> = vec![Vec::new(); n];
    let add = |g: &mut Vec<Vec<(usize, i64, i64, usize)>>, u: usize, v: usize, c: i64, w: i64| {
        let (iu, iv) = (g[u].len(), g[v].len());
        g[u].push((v, c, w, iv));
        g[v].push((u, 0, -w, iu));
    };
    for i in 0..nl {
        add(&mut g, src, i, 1, 0);
    }
    for j in 0..nr {
        add(&mut g, nl + j, snk, cap_right as i64, 0);
    }
    // Costs are scaled to integers; f32 scores in [0, ~2] keep four decimals at 1e4.
    for (k, r) in rows.iter().enumerate() {
        let _ = k;
        add(
            &mut g,
            li[r.left.as_str()],
            nl + ri[r.right.as_str()],
            1,
            -((r.score * 10_000.0) as i64),
        );
    }

    // Successive shortest augmenting path, one unit at a time (each left supplies one).
    loop {
        let mut dist = vec![i64::MAX; n];
        let mut prev: Vec<Option<(usize, usize)>> = vec![None; n];
        dist[src] = 0;
        for _ in 0..n {
            let mut changed = false;
            for u in 0..n {
                if dist[u] == i64::MAX {
                    continue;
                }
                for (ei, &(v, c, w, _)) in g[u].iter().enumerate() {
                    if c > 0 && dist[u] + w < dist[v] {
                        dist[v] = dist[u] + w;
                        prev[v] = Some((u, ei));
                        changed = true;
                    }
                }
            }
            if !changed {
                break;
            }
        }
        if dist[snk] == i64::MAX {
            break;
        }
        let mut v = snk;
        while let Some((u, ei)) = prev[v] {
            g[u][ei].1 -= 1;
            let rev = g[u][ei].3;
            g[v][rev].1 += 1;
            v = u;
        }
    }

    // A row is kept when its arc carries flow: capacity 1 spent to 0.
    let mut kept = Vec::new();
    for (k, r) in rows.iter().enumerate() {
        let (u, v) = (li[r.left.as_str()], nl + ri[r.right.as_str()]);
        if let Some(pos) = g[u].iter().position(|&(t, c, _, _)| t == v && c == 0) {
            g[u][pos].1 = -1; // consume, so two rows for one (left,right) are not both kept
            kept.push(k);
        }
    }
    kept.sort_unstable();
    kept
}

/// Apply a selection policy to an assembled dictionary, and say what happened to the
/// lefts that lost.
pub fn select(d: &Dictionary, policy: Policy) -> (Dictionary, BTreeMap<String, LeftState>) {
    let keep = assign(&d.rows, policy);
    let keep_set: BTreeSet<usize> = keep.iter().copied().collect();
    let mut best_lost: BTreeMap<String, (f32, String)> = BTreeMap::new();
    for (i, r) in d.rows.iter().enumerate() {
        if !keep_set.contains(&i) {
            let e = best_lost
                .entry(r.left.clone())
                .or_insert((f32::MIN, String::new()));
            if r.score > e.0 {
                *e = (r.score, r.right.clone());
            }
        }
    }
    let rows: Vec<Row> = keep.into_iter().map(|i| d.rows[i].clone()).collect();
    let survivors: BTreeSet<&str> = rows.iter().map(|r| r.left.as_str()).collect();

    let mut states: BTreeMap<String, LeftState> = BTreeMap::new();
    for (left, (_, best)) in best_lost {
        if !survivors.contains(left.as_str()) {
            states.insert(left, LeftState::Unmatched { best });
        }
    }
    for l in &d.missing_left {
        // Without per-candidate history the honest reading of "no row at all" is `Absent`.
        // `LowRanked` needs the best sub-threshold score, which assembly does not retain;
        // producing it is a change to `dictionary`, not to this function, and claiming it
        // here would be inventing a distinction the data does not carry.
        states.insert(l.clone(), LeftState::Absent);
    }

    (
        Dictionary {
            left_theory: d.left_theory.clone(),
            right_theory: d.right_theory.clone(),
            rows,
            missing_left: d.missing_left.clone(),
            missing_right: d.missing_right.clone(),
        },
        states,
    )
}

#[cfg(test)]
mod select_tests {
    use super::*;

    /// A theory named at a depth `theory_of` does not use must still match.
    ///
    /// `theory_of` files everything outside Mathlib at depth 1, so
    /// `theory_of("Physlib.Relativity")` is `"Physlib"` and an equality test against
    /// `"Physlib.Relativity"` matched nothing — `dictionary` returned zero rows and no
    /// error, which reads as "these theories share no structure" and was read as exactly
    /// that. Prefix membership fixes it; the component boundary is what keeps
    /// `Mathlib.Algebra` from swallowing `Mathlib.AlgebraicGeometry`, and that is the half
    /// a naive `starts_with` gets wrong.
    #[test]
    fn theory_membership_is_by_component_at_any_depth() {
        assert!(in_theory("Physlib.Relativity.Lorentz", "Physlib"));
        assert!(in_theory(
            "Physlib.Relativity.Lorentz",
            "Physlib.Relativity"
        ));
        assert!(in_theory("Physlib", "Physlib"));
        assert!(!in_theory("PhyslibExtra.Thing", "Physlib"));
        assert!(in_theory("Mathlib.Algebra.Order.Field", "Mathlib.Algebra"));
        assert!(
            !in_theory("Mathlib.AlgebraicGeometry.Scheme", "Mathlib.Algebra"),
            "a prefix test without a component boundary merges two unrelated subjects"
        );
    }

    fn row(left: &str, right: &str, score: f32) -> Row {
        Row {
            left: left.into(),
            right: right.into(),
            skeleton: String::new(),
            retention: score,
            score,
            status: Status::BothProven,
            transportable: true,
        }
    }

    fn dict(rows: Vec<Row>) -> Dictionary {
        Dictionary {
            left_theory: "L".into(),
            right_theory: "R".into(),
            rows,
            missing_left: Vec::new(),
            missing_right: Vec::new(),
        }
    }

    /// Three lefts all preferring one right, each with a weaker second choice.
    fn contested() -> Dictionary {
        dict(vec![
            row("a", "x", 0.90),
            row("a", "p", 0.50),
            row("b", "x", 0.80),
            row("b", "q", 0.40),
            row("c", "x", 0.70),
            row("c", "r", 0.30),
        ])
    }

    #[test]
    fn unconstrained_keeps_every_row() {
        let (d, states) = select(&contested(), Policy::Unconstrained);
        assert_eq!(d.rows.len(), 6);
        assert!(
            states.is_empty(),
            "no left loses an assignment that was never made"
        );
    }

    #[test]
    fn injective_gives_each_right_to_at_most_one_left() {
        let (d, _) = select(&contested(), Policy::Injective);
        let rights: Vec<&str> = d.rows.iter().map(|r| r.right.as_str()).collect();
        let distinct: BTreeSet<&str> = rights.iter().copied().collect();
        assert_eq!(
            rights.len(),
            distinct.len(),
            "a right was reused: {rights:?}"
        );
    }

    #[test]
    fn many_to_one_respects_its_cap() {
        let (d, _) = select(&contested(), Policy::ManyToOne { cap: 2 });
        let mut per_right: BTreeMap<&str, usize> = BTreeMap::new();
        for r in &d.rows {
            *per_right.entry(r.right.as_str()).or_default() += 1;
        }
        assert!(
            per_right.values().all(|&n| n <= 2),
            "cap exceeded: {per_right:?}"
        );
    }

    #[test]
    fn the_solver_prefers_coverage_over_the_score_sum() {
        // `a` is the only left that can reach `x`, and its alternative is poor. A
        // sum-maximising solver would happily drop `b` to keep a fractionally better
        // arrangement; a dictionary that partners more concepts is the more useful object,
        // so coverage is maximised first and the score decides among equal-coverage
        // solutions.
        let d = dict(vec![
            row("a", "x", 0.95),
            row("b", "x", 0.94),
            row("b", "y", 0.10),
        ]);
        let (out, _) = select(&d, Policy::Injective);
        assert_eq!(out.rows.len(), 2, "both lefts should be partnered");
        let lefts: BTreeSet<&str> = out.rows.iter().map(|r| r.left.as_str()).collect();
        assert!(lefts.contains("a") && lefts.contains("b"));
    }

    #[test]
    fn a_displaced_left_is_unmatched_and_names_what_it_lost() {
        // The state the solver creates: `c` had a partner that cleared every floor and
        // lost it to a better claim. Reporting that as `Absent` — which is all the
        // pre-solver vocabulary could say — would tell a researcher to go looking for a
        // correspondence that was found and then given away.
        let d = dict(vec![row("a", "x", 0.90), row("c", "x", 0.70)]);
        let (out, states) = select(&d, Policy::Injective);
        assert_eq!(out.rows.len(), 1);
        match states.get("c") {
            Some(LeftState::Unmatched { best }) => assert_eq!(best, "x"),
            other => panic!("expected `c` to be Unmatched, got {other:?}"),
        }
    }
}

/// The §74 assembly knobs, each paired with the ablation that must restore the shipped
/// behaviour. Every fixture also asserts the premise it depends on (which candidate the
/// two keys prefer, which rows are citation-linked), so a scoring change that erodes the
/// fixture fails loudly instead of letting the knob test pass without testing anything.
#[cfg(test)]
mod assembly_tests {
    use super::*;
    use crate::skel::index::{IndexConfig, SkeletonIndex};

    /// A 7-node concrete spine, shared so every genuine pair clears `min_common = 6`.
    const SH: &str = "a(a(a(c(5:LE.le,0),c(4:Real,0)),c(3:iii,0)),c(2:zz,0))";

    fn row_json(
        name: &str,
        module: &str,
        stmt: &str,
        uses_stmt: &[&str],
        uses_proof: &[&str],
    ) -> String {
        let quote = |xs: &[&str]| {
            xs.iter()
                .map(|u| format!("\"{u}\""))
                .collect::<Vec<_>>()
                .join(",")
        };
        format!(
            "{{\"name\":\"{name}\",\"kind\":\"theorem\",\"module\":\"{module}\",\
             \"stmt\":\"atlas-stmt-v1;{stmt}\",\"uses_statement\":[{}],\"uses_proof\":[{}]}}",
            quote(uses_stmt),
            quote(uses_proof),
        )
    }

    fn rights_of(d: &Dictionary, left: &str) -> Vec<String> {
        d.rows
            .iter()
            .filter(|r| r.left == left)
            .map(|r| r.right.clone())
            .collect()
    }

    /// One left, two right-theory candidates whose two keys disagree: `ra` shares more
    /// structure (higher retention) but its one variable is scoped, so the score's
    /// `scoped_penalty` demotes it below `rb`. Off must keep the score's choice — that is
    /// the shipped behaviour the golden pins — and on must keep retention's.
    #[test]
    fn rank_by_retention_changes_which_candidate_wins_and_off_keeps_the_score_order() {
        let corpus = [
            row_json(
                "l1",
                "L",
                &format!("a(a(c(2:Eq,0),{SH}),pi(s(0),a(c(1:f,0),b0)))"),
                &[],
                &[],
            ),
            // Same spine, and the difference sits under `l1`'s binder: the lgg variable
            // abstracts `a(f, b0)` against `k`, mentions the bound thing, and is scoped.
            row_json("ra", "R", &format!("a(a(c(2:Eq,0),{SH}),pi(s(0),c(1:k,0)))"), &[], &[]),
            // Four clean constant-for-constant differences: less shared structure, no
            // scoped variable, so the score prefers it while retention does not.
            row_json(
                "rb",
                "R",
                "a(a(c(2:Eq,0),a(a(a(c(5:LE.le,0),c(3:Rho,0)),c(3:jjj,0)),c(2:qq,0))),pi(s(0),a(c(1:g,0),b0)))",
                &[],
                &[],
            ),
        ]
        .join("\n");
        let cfg = IndexConfig::default();
        let mut idx = SkeletonIndex::build(&corpus, &cfg).expect("build");

        // The premise, asserted before the claim: the two keys must actually disagree.
        let pool_cfg = IndexConfig {
            restrict_prefix: Some("R".into()),
            theorems_only: true,
            ..cfg.clone()
        };
        let ns = idx.similar("l1", 16, &pool_cfg).expect("similar");
        let get = |name: &str| {
            ns.iter()
                .find(|n| n.name == name)
                .unwrap_or_else(|| panic!("`{name}` not proposed: {ns:?}"))
        };
        let (ra, rb) = (get("ra").clone(), get("rb").clone());
        assert!(
            ra.retention > rb.retention && rb.score > ra.score,
            "fixture premise broken — the keys no longer disagree \
             (ra: ret {:.3} score {:.3}, rb: ret {:.3} score {:.3})",
            ra.retention,
            ra.score,
            rb.retention,
            rb.score
        );

        let d_off = dictionary(&mut idx, None, "L", "R", &cfg, &DictOptions::default());
        assert_eq!(
            rights_of(&d_off, "l1"),
            vec!["rb".to_string()],
            "with the knob off, the score's choice is the shipped one"
        );
        let d_on = dictionary(
            &mut idx,
            None,
            "L",
            "R",
            &cfg,
            &DictOptions {
                rank_by_retention: true,
                ..DictOptions::default()
            },
        );
        assert_eq!(
            rights_of(&d_on, "l1"),
            vec!["ra".to_string()],
            "with the knob on, retention's choice wins the per_decl slot"
        );
    }

    /// §74's eviction, in miniature: the winner-take-all slot goes to `ra`, and the
    /// structurally different claim `rx` is silently deleted. The knob must recover `rx`
    /// **without** uncapping `ra`'s family — `rz` carries the same skeleton as `ra`, is
    /// the same claim worn by another partner, and must stay capped, or the knob is just
    /// `per_decl = ∞` renamed.
    #[test]
    fn keep_displaced_recovers_a_structurally_different_claim_without_uncapping_its_family() {
        let corpus = [
            row_json(
                "l2",
                "L",
                &format!("a(a(c(2:Eq,0),{SH}),c(1:u,0))"),
                &[],
                &[],
            ),
            row_json(
                "ra",
                "R",
                &format!("a(a(c(2:Eq,0),{SH}),c(1:v,0))"),
                &[],
                &[],
            ),
            row_json(
                "rz",
                "R",
                &format!("a(a(c(2:Eq,0),{SH}),c(1:w,0))"),
                &[],
                &[],
            ),
            row_json(
                "rx",
                "R",
                "a(a(c(2:Eq,0),a(a(a(c(5:LE.le,0),c(4:Real,0)),c(3:jjj,0)),c(2:qq,0))),c(1:u,0))",
                &[],
                &[],
            ),
        ]
        .join("\n");
        let cfg = IndexConfig::default();
        let mut idx = SkeletonIndex::build(&corpus, &cfg).expect("build");

        let d_off = dictionary(&mut idx, None, "L", "R", &cfg, &DictOptions::default());
        assert_eq!(
            rights_of(&d_off, "l2"),
            vec!["ra".to_string()],
            "the ablation: winner-take-all keeps only the top candidate, which is the \
             shipped defect this knob exists to control"
        );

        let d_on = dictionary(
            &mut idx,
            None,
            "L",
            "R",
            &cfg,
            &DictOptions {
                per_decl_keep_displaced: true,
                ..DictOptions::default()
            },
        );
        let rights = rights_of(&d_on, "l2");
        assert!(
            rights.contains(&"ra".to_string()) && rights.contains(&"rx".to_string()),
            "the displaced structurally-different claim must be kept: {rights:?}"
        );
        assert!(
            !rights.contains(&"rz".to_string()),
            "a same-skeleton clone is the same claim and must stay capped: {rights:?}"
        );
        // The two kept rows genuinely differ structurally; if a change ever makes their
        // skeletons render identically, the fixture stops testing the cap's unit.
        let (a, x) = (
            d_on.rows.iter().find(|r| r.right == "ra").unwrap(),
            d_on.rows.iter().find(|r| r.right == "rx").unwrap(),
        );
        assert_ne!(a.skeleton, x.skeleton, "fixture premise broken");
    }

    /// The `linearSol` pattern from §74's graded top-40: the best-ranked partner is the
    /// framework lemma the left is proved *by* (proof lens, left→right), the second cites
    /// the left in its own statement (statement lens, right→left), and only the third is
    /// an actual analogy candidate. On, both linked rows are dropped **and the slot moves
    /// on** — the left keeps a row rather than vanishing from the dictionary.
    #[test]
    fn exclude_cited_drops_linked_pairs_under_both_lenses_and_frees_the_slot() {
        let corpus = [
            row_json(
                "l3",
                "L",
                &format!("a(a(c(2:Eq,0),{SH}),c(1:u,0))"),
                &[],
                &["rf"],
            ),
            row_json(
                "rf",
                "R",
                &format!("a(a(c(2:Eq,0),{SH}),c(1:v,0))"),
                &[],
                &[],
            ),
            row_json(
                "rh",
                "R",
                &format!("a(a(c(2:Eq,0),{SH}),c(1:w,0))"),
                &["l3"],
                &[],
            ),
            row_json(
                "rg",
                "R",
                "a(a(c(2:Eq,0),a(a(a(c(5:LE.le,0),c(4:Real,0)),c(3:jjj,0)),c(2:qq,0))),c(1:u,0))",
                &[],
                &[],
            ),
        ]
        .join("\n");
        let cfg = IndexConfig::default();
        let mut idx = SkeletonIndex::build(&corpus, &cfg).expect("build");
        let graph = Graph::from_jsonl(&corpus).expect("graph");

        let d_off = dictionary(
            &mut idx,
            Some(&graph),
            "L",
            "R",
            &cfg,
            &DictOptions::default(),
        );
        assert_eq!(
            rights_of(&d_off, "l3"),
            vec!["rf".to_string()],
            "the ablation: off, the framework partner the left is proved by wins the slot"
        );

        let d_on = dictionary(
            &mut idx,
            Some(&graph),
            "L",
            "R",
            &cfg,
            &DictOptions {
                exclude_cited: true,
                ..DictOptions::default()
            },
        );
        assert_eq!(
            rights_of(&d_on, "l3"),
            vec!["rg".to_string()],
            "on, both citation-linked candidates are dropped and the slot passes to the \
             unlinked one — not to nobody"
        );
        assert!(
            !d_on.missing_left.contains(&"l3".to_string()),
            "the left must stay matched; deleting it would trade one false negative for \
             another"
        );
    }

    /// A filter that silently does nothing is indistinguishable from a clean result, so
    /// asking for the citation filter without a citation graph is refused outright.
    #[test]
    #[should_panic(expected = "exclude_cited needs the citation graph")]
    fn exclude_cited_without_a_graph_refuses_rather_than_silently_keeping_rows() {
        let corpus = row_json(
            "l4",
            "L",
            &format!("a(a(c(2:Eq,0),{SH}),c(1:u,0))"),
            &[],
            &[],
        );
        let cfg = IndexConfig::default();
        let mut idx = SkeletonIndex::build(&corpus, &cfg).expect("build");
        let _ = dictionary(
            &mut idx,
            None,
            "L",
            "R",
            &cfg,
            &DictOptions {
                exclude_cited: true,
                ..DictOptions::default()
            },
        );
    }
}
