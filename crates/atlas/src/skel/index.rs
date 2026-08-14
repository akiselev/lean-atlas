//! The skeleton index and `atlas similar` (B4, atlas.md §1c).
//!
//! # Why a prefilter, and what it does *not* guarantee
//!
//! Comparing a query against 131,000 statements is 131,000 anti-unifications — about half
//! a second, which sounds affordable until it is done per query in a loop. The index cuts
//! it to a few hundred candidates.
//!
//! There is a tempting theorem here and it is worth being explicit that it does not do the
//! job people want it to. If `lgg(x,y)` contains a hole-free subterm `s` with `|s| ≥ K`,
//! then `x` and `y` each literally contain `s` — so an inverted index over subterms has no
//! false negatives *with respect to that predicate*. True, and nearly useless: the query
//! is "top-k by retention", not "shares a big subterm". Measured recall against brute
//! force tells the real story, and the gate is a recall floor rather than an equality.
//!
//! # Three sources, all of them needed
//!
//! * **A — whole-statement `Shape` bucket.** Exact structural twins. Cheap and precise;
//!   skipped when the bucket is enormous, since a 7,000-member bucket is a tautology
//!   rather than a lead.
//! * **B — concrete subterms at `Presentation`.** Closed subterms of size ≥ 3, plus
//!   *open* ones (carrying loose de Bruijn indices) of size ≥ 5. Open subterms are sound
//!   keys because de Bruijn indices are preserved along common structure.
//! * **C — `Shape` subterms of size ≥ 8.** Partial structural overlap. This is the source
//!   that carries the design: it is what lets `le_trans` reach `dvd_trans`, where no
//!   concrete subterm is shared at all.
//!
//! Rarity, not frequency, is what the ranking rewards — a shared subterm occurring in two
//! declarations is a discovery, one occurring in four thousand is punctuation. That is the
//! opposite of what a compression-driven library-learner optimises, and it is why this is
//! an inverted index with IDF rather than an e-graph.

use std::collections::{BTreeSet, HashMap};

use super::erase::{EraseCache, Level, Signatures, erase};
use super::lgg::{Generalization, SimilarityScore, generalize};
use super::term::{Arena, BinderInfo, Node, SymId, TermId};
use crate::graph::GraphError;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug)]
pub struct DeclId(pub u32);

/// Which of the three sources produced a candidate. Reported, so a surprising hit can be
/// traced to the reason it was considered.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Sources(pub u8);

impl Sources {
    pub const SHAPE: u8 = 1;
    pub const SUBTERM: u8 = 2;
    pub const SHAPE_SUBTERM: u8 = 4;

    pub fn add(&mut self, s: u8) {
        self.0 |= s;
    }
    pub fn has(self, s: u8) -> bool {
        self.0 & s != 0
    }
    pub fn describe(self) -> String {
        let mut v = Vec::new();
        if self.has(Sources::SHAPE) {
            v.push("shape");
        }
        if self.has(Sources::SUBTERM) {
            v.push("subterm");
        }
        if self.has(Sources::SHAPE_SUBTERM) {
            v.push("shape-subterm");
        }
        v.join("+")
    }
}

/// Compressed-sparse-row posting lists, with each key's inverse document frequency.
pub struct Postings {
    keys: Vec<TermId>,
    starts: Vec<u32>,
    decls: Vec<DeclId>,
    idf: Vec<f32>,
}

impl Postings {
    fn build(mut pairs: Vec<(TermId, DeclId)>, n_docs: usize, max_len: usize) -> Postings {
        pairs.sort_unstable();
        pairs.dedup();
        let (mut keys, mut starts, mut decls, mut idf) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new());
        let mut i = 0;
        while i < pairs.len() {
            let key = pairs[i].0;
            let mut j = i;
            while j < pairs.len() && pairs[j].0 == key {
                j += 1;
            }
            // A key held by a large fraction of the corpus carries no information and
            // would dominate every candidate set it appears in. Dropped, not down-weighted:
            // down-weighting still pays the cost of walking it.
            if j - i <= max_len {
                keys.push(key);
                starts.push(decls.len() as u32);
                idf.push((n_docs as f32 / (j - i) as f32).ln());
                for p in &pairs[i..j] {
                    decls.push(p.1);
                }
            }
            i = j;
        }
        starts.push(decls.len() as u32);
        Postings {
            keys,
            starts,
            decls,
            idf,
        }
    }

    pub fn get(&self, key: TermId) -> Option<(&[DeclId], f32)> {
        let i = self.keys.binary_search(&key).ok()?;
        let (a, b) = (self.starts[i] as usize, self.starts[i + 1] as usize);
        Some((&self.decls[a..b], self.idf[i]))
    }

    pub fn key_count(&self) -> usize {
        self.keys.len()
    }

    /// Every key with its posting list and IDF, for reading the index as an inventory
    /// rather than as a prefilter.
    ///
    /// The postings already *are* a corpus-wide pattern inventory: each key is a subterm
    /// and its list is the family of declarations containing it. §15 found that grouping a
    /// query's candidates by shared pattern beats ranking them, and that whole-statement
    /// grouping corpus-wide is a dead end because real theorems are structurally unique
    /// (mean family size 1.00 at every level but `shape`). The unit that works is the
    /// shared *sub*-pattern, and this is where they are already computed.
    pub fn entries(&self) -> impl Iterator<Item = (TermId, &[DeclId], f32)> {
        (0..self.keys.len()).map(move |i| {
            let (a, b) = (self.starts[i] as usize, self.starts[i + 1] as usize);
            (self.keys[i], &self.decls[a..b], self.idf[i])
        })
    }
}

/// Where a statement is compared *from*.
///
/// Anti-unification aligns two terms from their roots, so a theorem carrying a hypothesis
/// prefix cannot match one without — even when the two conclude exactly the same thing.
/// Measured on B7's validation clusters: `RH.zeros_subset_critical_line` and
/// `Spectral.spectrum_subset_real` are both literally `S ⊆ {x | P x}`, and their lgg is
/// `common 0, retention 0.0000`, because one roots at `LE.le` and the other at a five-deep
/// binder chain. Every cross-theory analogy has that shape mismatch, because the same
/// claim carries different hypotheses in different theories.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Anchor {
    /// Compare whole statements, hypotheses included. Answers "what has the same overall
    /// shape". The shipped default, and the right question when the hypotheses are part of
    /// what is being compared.
    Root,
    /// Compare conclusions, discarding the binder prefix. Answers "what concludes the same
    /// thing", which is the question cross-theory analogy needs.
    ///
    /// Measured: on B7 this moved spectrum-is-real from absent-in-top-8 to **rank 3**,
    /// passing V2. The precision cost on an independent corpus (physlib, 2,287 quantum
    /// declarations) is one percentage point — cross-subfield noise 9% → 10%. It is *not*
    /// the default because the two settings answer different questions and the caller
    /// should say which one they meant.
    Conclusion,
}

#[derive(Clone, Debug, PartialEq)]
pub struct IndexConfig {
    pub min_concrete_closed: u32,
    pub min_concrete_open: u32,
    pub min_shape_sub: u32,
    /// A posting list longer than this fraction of the corpus is dropped as uninformative.
    pub max_posting_fraction: f32,
    /// Absolute floor under `max_posting_fraction`. Whichever is larger wins, so a value
    /// above `max_posting_fraction * n` makes the fraction inert — which it silently was,
    /// for every corpus under 50,000 declarations. See `build`.
    pub min_posting_len: usize,
    pub max_bucket: usize,
    pub candidate_budget: usize,
    /// The level the *reported* skeleton is computed at — the row's fidelity.
    pub lgg_level: Level,
    pub min_common: u32,
    pub min_retention: f32,
    /// The three ranking weights. They live here rather than as literals in `similar`
    /// because the scorer's identity is a digest over this struct: a constant that is not
    /// a field is a constant the digest cannot see, so a stored result would claim to come
    /// from a scorer it did not.
    pub rarity_weight: f32,
    pub cross_weight: f32,
    pub scoped_weight: f32,
    /// Weight of the derivativeness penalty. 0 disables it, restoring the pre-B4.1 score
    /// exactly — which is what the ablation in `tests/golden.rs` needs in order to show the
    /// factor is doing work rather than being decorative.
    pub derivative_weight: f32,
    /// Whether statements are compared from their root or from their conclusion.
    pub anchor: Anchor,
    /// Which formula turns shared structure into a number.
    ///
    /// Pluggable because no single one wins everywhere — see [`SimilarityScore`]. The
    /// shipped default stays `Retention` so existing results remain comparable; the
    /// measurement says `MinNormalised` is the more robust choice.
    pub score: SimilarityScore,
    /// Drop implicit and instance arguments from application spines before indexing.
    ///
    /// **Opt-in, and it is a trade rather than an improvement.** It repairs alignment
    /// across the operator/function seam — `euclid_lemma ~ poly_euclid_lemma` goes from
    /// retention 0.04 to 1.00, and B7's Z~FF dictionary from 0 rows to 9 — and it costs
    /// discrimination, because the arguments that block alignment are the same ones that
    /// tell statements apart. Measured twice: a retrieval regression on corpus probes
    /// (`Grp.assoc` rank 1 → 3) and a false dictionary row eating a deliberately-planted
    /// gap in B7's V4. Default off for that reason.
    pub normalize_arity: bool,
    /// Restrict the ranked pool to theorems. Default `false`, which preserves the query
    /// "what looks like this declaration" for any kind — but a *ground truth* of theorems
    /// scored against a pool that is half definitions and recursors measures the config,
    /// not the scorer, so an experiment sets this.
    pub theorems_only: bool,
    /// Restrict candidates to declarations whose module is, or sits under, this prefix.
    ///
    /// Applied inside retrieval rather than after it. `dictionary` used to take a global
    /// top-N and *then* discard everything outside the target theory, so a left whose
    /// partner sat at global rank 5 had no row at all — the selection could only delete,
    /// never choose. Filtering here means the budget is spent on candidates that can
    /// actually become rows.
    pub restrict_prefix: Option<String>,
    /// Ablation knob: query source B with the raw root instead of the `Presentation`
    /// erasure the postings are keyed at. `true` is the repaired behaviour; `false`
    /// reproduces the defect, which is the only honest way to measure what the repair was
    /// worth without reverting it.
    pub source_b_at_build_level: bool,
    /// Work-budget posting admission (`research/physlib-prefilter.md` §6a/§10 S1,
    /// findings §66). Off by default; `None` is today's behaviour bit for bit.
    ///
    /// The fraction cutoff above is a proxy: it deletes a key by *holder count*, and the
    /// property it is proxying for is informativeness. On the one corpus with a
    /// pre-registered answer the two come apart completely — the keys carrying all four
    /// classical↔quantum information correspondences are `0 ≤ (·:ℝ)`, `(· = · : ℝ)` and
    /// `((·:ℕ):ℝ)`, held by 0.26–1.85% of 95,268 declarations, and the shipped cutoff
    /// returns 0 of 4 where admitting them returns all 4 as the dictionary's top rows.
    /// No constant of the cutoff's shape transfers: on the 495k full closure the shipped
    /// fraction already yields 495 and recall is still 0 of 4.
    ///
    /// `Some(w)` therefore keeps **every** key at build time (measured index cost at full
    /// scale: +0.47% keys, +26.9% postings) and bounds each query at `w` postings walked
    /// — the quantity actually being spent, not a proxy for it. The walk is already
    /// rarest-first, so the budget prunes the uninformative tail the cutoff was deleting
    /// from the front. While it is `Some`, the walk is bounded by work **instead of** by
    /// `candidate_budget`: the measured reference point (W = 2,000, 4/4 at a median
    /// candidate set of 475) has no candidate cap, and keeping one would reproduce the
    /// 3/4 loss it exists to repair — at full scale the 600 slots fill on rarer keys
    /// before the walk reaches the carrying key at document frequency 1,761.
    ///
    /// Both halves read this one field: `build` keeps all keys when it is `Some`,
    /// `candidates` bounds the walk at the *query's* value. An index built with `None`
    /// has already dropped the keys, so a query-time `Some` against it bounds work
    /// without restoring recall — pair them, the way the binding's index cache does.
    /// W = 2,000 reaches 4/4 on both measured corpora but is fitted on two points and is
    /// deliberately not a shipped default; §10's paired sweep is the fitting protocol.
    pub posting_work_budget: Option<usize>,
}

impl Default for IndexConfig {
    fn default() -> IndexConfig {
        IndexConfig {
            min_concrete_closed: 3,
            min_concrete_open: 5,
            min_shape_sub: 8,
            max_posting_fraction: 0.001,
            min_posting_len: 50,
            max_bucket: 600,
            candidate_budget: 600,
            lgg_level: Level::Carriers,
            min_common: 6,
            min_retention: 0.30,
            rarity_weight: 0.5,
            cross_weight: 0.15,
            scoped_weight: 0.30,
            derivative_weight: 0.45,
            anchor: Anchor::Root,
            score: SimilarityScore::Retention,
            normalize_arity: false,
            theorems_only: false,
            restrict_prefix: None,
            source_b_at_build_level: true,
            posting_work_budget: None,
        }
    }
}

/// The score, factor by factor, as it was actually computed.
///
/// Engine 1 §6 C2 requires that "every production result records the scorer code/version
/// and complete feature vector". A single `f32` is neither: it cannot be re-derived, and
/// it cannot be ablated. These are the multiplicands, so `total` is exactly their product
/// and a reader can see which one carried the rank.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ScoreFactors {
    /// Shared concrete structure as a fraction of the larger side.
    ///
    /// Always the classic retention, whatever `IndexConfig::score` is set to, so two runs
    /// under different scorers stay comparable on one axis.
    pub retention: f32,
    /// The configured score's value — what actually multiplies into `total`.
    ///
    /// Separate from `retention` because the two differ once the scorer is changed, and
    /// collapsing them would make a row unable to say which formula ranked it.
    pub base: f32,
    /// `1 + w * min(rarity/ln N, 1)` — how surprising the shared key is.
    pub rarity_boost: f32,
    /// `1 + w` when the candidate is in another module root, else 1.
    pub cross_boost: f32,
    /// `1 - w * scoped/vars` — a row abstracting locally bound things is not transportable.
    pub scoped_penalty: f32,
    /// `1 - w * derivativeness(candidate)` — how much the candidate looks auto-generated.
    ///
    /// Every layer of the Atlas is led by declarations Lean emitted rather than a human
    /// wrote: cross-theory `similar` on Mathlib returns `.mk.inj` pairs, and physlib's
    /// `Relativity ~ QFT` dictionary opens with `CausalCharacter.lightLike ~
    /// annihilate.sizeOf_spec`. The standing workaround was a list of name suffixes, which
    /// is library-specific and is name matching — the thing the index exists to replace.
    ///
    /// `derivativeness` is structural instead: short proof, cites recursors and
    /// constructors rather than theorems, and nothing cites it back. Measured against a
    /// name-based label set it reaches AUC 0.899 on physlib and 0.886 on a 131k Mathlib
    /// slice, with precision 1.000 over the top 100 physlib rows.
    ///
    /// A **penalty and not a filter**, deliberately. At a hard threshold the measure runs
    /// precision 0.62–0.67, so filtering would discard a genuine declaration for roughly
    /// every piece of boilerplate removed. Recall is the thing that cannot be recovered
    /// downstream, so this reorders and never drops.
    pub derivative_penalty: f32,
    pub total: f32,
}

/// Which scorer produced a row, precisely enough to distrust it later.
///
/// `corpus_digest` is here because the score is not a function of (pair, config): the
/// rarity boost divides by `ln(corpus size)` and every IDF is a corpus property, so the
/// same pair scores differently on a different slice. Without it two rows would claim a
/// common provenance they do not have.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScorerId {
    pub name: &'static str,
    pub version: u32,
    pub config_digest: String,
    pub corpus_digest: String,
}

impl std::fmt::Display for ScorerId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}@{} cfg:{} corpus:{}",
            self.name,
            self.version,
            &self.config_digest[..8.min(self.config_digest.len())],
            &self.corpus_digest[..8.min(self.corpus_digest.len())]
        )
    }
}

/// Bumped when the score's *shape* changes — a new factor, or a factor computed
/// differently. A weight change is caught by `config_digest` instead.
pub const SCORER_VERSION: u32 = 2;

/// One neighbour, with everything a reader needs to audit the rank rather than trust it.
#[derive(Clone, Debug)]
pub struct Neighbour {
    pub name: String,
    pub module: String,
    pub kind: String,
    pub retention: f32,
    pub common: u32,
    pub vars: u32,
    pub scoped_vars: u32,
    /// The rarest shared key's IDF — how surprising the overlap is.
    pub rarity: f32,
    pub sources: Sources,
    /// The rendered skeleton. This *is* the candidate dictionary row.
    pub skeleton: String,
    /// True when no variable abstracts a locally bound thing. B6 must refuse the rest.
    pub transportable: bool,
    /// The product. Kept as a plain `f32` because ranking and printing want a number;
    /// `factors` is what an audit or an ablation wants.
    pub score: f32,
    pub factors: ScoreFactors,
}

/// How auto-generated each declaration looks, in `[0,1]`, from citation structure alone.
///
/// Three signals, combined as **percentile ranks within the corpus** rather than through
/// fitted coefficients. A fitted logistic scores better — AUC 0.899 on physlib against
/// 0.886 on a Mathlib slice — but its weights differ per corpus (`proof_size` dominates one,
/// `frac_inst_binders` the other), so shipping them would tune the engine to whichever
/// library they were fitted on. Rank-averaging needs no constants and adapts to the corpus
/// it is given, at some cost in separation.
///
/// * **proof length** — a longer argument means a human wrote it.
/// * **fraction of the proof citing recursors or constructors** — a generated lemma is
///   discharged by its type's own eliminator; a theorem cites other theorems. This is the
///   signal that only works in combination: alone it scores 0.579, but it carries the third
///   largest weight in the fitted model, so testing features one at a time misses it.
/// * **in-degree** — something cites a real theorem.
///
/// Citations leaving the indexed set are counted in the denominator but cannot contribute
/// to anyone's in-degree, so a slice that omits a declaration's users understates how real
/// it looks. That is the honest direction: it can only make something look *more*
/// derivative, and the factor is a penalty rather than a filter.
/// Every constant symbol occurring in a term, with repeats.
/// Every constant that appears in *head* position of an application, with repeats.
///
/// Distinct from `collect_syms`, which gathers all symbols wherever they occur. Only heads
/// are consulted by `erase_spine`'s signature lookup, so only heads say whether the erasure
/// had the information it needed. A bare `Const` that is not applied is a head of a
/// zero-argument spine and counts.
fn collect_app_heads(a: &Arena, t: TermId, out: &mut Vec<SymId>) {
    match a.node(t) {
        Node::Const(s, _) => out.push(s),
        Node::App(..) => {
            let (head, args) = a.spine(t);
            if let Node::Const(s, _) = a.node(head) {
                out.push(s);
            } else {
                collect_app_heads(a, head, out);
            }
            for arg in args {
                collect_app_heads(a, arg, out);
            }
        }
        Node::Lam(_, d, b) | Node::Pi(_, d, b) => {
            collect_app_heads(a, d, out);
            collect_app_heads(a, b, out);
        }
        Node::Let(x, y, z) => {
            collect_app_heads(a, x, out);
            collect_app_heads(a, y, out);
            collect_app_heads(a, z, out);
        }
        Node::Proj(_, _, x) => collect_app_heads(a, x, out),
        _ => {}
    }
}

fn collect_syms(a: &Arena, t: TermId, out: &mut Vec<SymId>) {
    match a.node(t) {
        Node::Const(s, _) => out.push(s),
        Node::App(f, x) => {
            collect_syms(a, f, out);
            collect_syms(a, x, out);
        }
        Node::Lam(_, d, b) | Node::Pi(_, d, b) => {
            collect_syms(a, d, out);
            collect_syms(a, b, out);
        }
        Node::Let(x, y, z) => {
            collect_syms(a, x, out);
            collect_syms(a, y, out);
            collect_syms(a, z, out);
        }
        Node::Proj(s, _, x) => {
            out.push(s);
            collect_syms(a, x, out);
        }
        _ => {}
    }
}

fn derivativeness(
    kinds: &[String],
    proofs: &[Vec<String>],
    by_name: &HashMap<String, DeclId>,
) -> Vec<f32> {
    let n = kinds.len();
    let mut in_degree = vec![0u32; n];
    let mut struct_frac = vec![0f32; n];
    let mut proof_len = vec![0u32; n];

    for (i, cites) in proofs.iter().enumerate() {
        proof_len[i] = cites.len() as u32;
        let mut structural = 0u32;
        for u in cites {
            if let Some(&DeclId(j)) = by_name.get(u.as_str()) {
                in_degree[j as usize] += 1;
                let k = kinds[j as usize].as_str();
                if k == "recursor" || k == "constructor" {
                    structural += 1;
                }
            }
        }
        struct_frac[i] = structural as f32 / (cites.len().max(1)) as f32;
    }

    // Percentile rank of each value, ties averaged, oriented so that 1.0 = most derivative.
    fn ranks<T: PartialOrd + Copy>(v: &[T], ascending: bool) -> Vec<f32> {
        let n = v.len();
        if n == 0 {
            return Vec::new();
        }
        let mut idx: Vec<usize> = (0..n).collect();
        idx.sort_by(|&a, &b| {
            let o = v[a].partial_cmp(&v[b]).unwrap_or(std::cmp::Ordering::Equal);
            if ascending { o } else { o.reverse() }
        });
        let mut out = vec![0f32; n];
        let mut i = 0;
        while i < n {
            let mut j = i;
            while j + 1 < n
                && v[idx[j + 1]]
                    .partial_cmp(&v[idx[i]])
                    .map(|o| o == std::cmp::Ordering::Equal)
                    .unwrap_or(false)
            {
                j += 1;
            }
            let avg = (i + j) as f32 / 2.0 / (n.max(2) - 1) as f32;
            for &k in &idx[i..=j] {
                out[k] = avg;
            }
            i = j + 1;
        }
        out
    }

    // Ascending rank of a *small* proof, a *small* in-degree, and a *large* structural
    // fraction all point the same way: derivative.
    let r_len = ranks(&proof_len, false);
    let r_deg = ranks(&in_degree, false);
    let r_str = ranks(&struct_frac, true);
    (0..n)
        .map(|i| ((r_len[i] + r_deg[i] + r_str[i]) / 3.0).clamp(0.0, 1.0))
        .collect()
}

/// The argument positions of each constant that come from an implicit or instance binder.
///
/// Read off the corpus: every constant has a row, and that row's own telescope says which
/// of its binders are `Implicit` or `InstImplicit`. A constant with no row is absent from
/// the map and is left alone — dropping on a guess would silently rewrite statements the
/// slice cannot justify rewriting.
fn implicit_positions(
    arena: &mut Arena,
    names: &[String],
    roots: &[TermId],
) -> HashMap<SymId, Vec<bool>> {
    let mut out = HashMap::new();
    for (i, root) in roots.iter().enumerate() {
        let mut flags = Vec::new();
        let mut cur = *root;
        while let Node::Pi(bi, _dom, body) = arena.node(cur) {
            flags.push(matches!(
                bi,
                BinderInfo::Implicit | BinderInfo::InstImplicit
            ));
            cur = body;
        }
        if flags.iter().any(|b| *b) {
            let sym = arena.intern_sym(&names[i]);
            out.insert(sym, flags);
        }
    }
    out
}

/// Rewrite a term so that implicit and instance arguments are **dropped** from application
/// spines rather than left in place.
///
/// `add(a,b)` is a two-argument application; `a + b` elaborates to `HAdd.hAdd α β γ inst a b`,
/// six. Anti-unification aligns spines positionally, so the two never align, and erasure
/// cannot help because it *holes* an argument and never removes it — arity survives every
/// level. Measured cost of leaving it alone: retention falls from ~0.87 to ~0.33 across the
/// seam, including between two Mathlib declarations.
///
/// Dropping an argument never shifts a de Bruijn index: arguments are terms, not binders.
fn drop_implicit_args(
    a: &mut Arena,
    t: TermId,
    map: &HashMap<SymId, Vec<bool>>,
    memo: &mut HashMap<TermId, TermId>,
) -> TermId {
    if let Some(&hit) = memo.get(&t) {
        return hit;
    }
    let out = match a.node(t) {
        Node::App(..) => {
            let (head, args) = a.spine(t);
            let head2 = drop_implicit_args(a, head, map, memo);
            let keep: Vec<TermId> = match a.node(head) {
                Node::Const(sym, _) => {
                    let flags = map.get(&sym);
                    args.iter()
                        .enumerate()
                        .filter(|(i, _)| !flags.is_some_and(|f| *f.get(*i).unwrap_or(&false)))
                        .map(|(_, x)| *x)
                        .collect()
                }
                _ => args.clone(),
            };
            let mut acc = head2;
            for x in keep {
                let x2 = drop_implicit_args(a, x, map, memo);
                acc = a.intern(Node::App(acc, x2));
            }
            acc
        }
        Node::Lam(bi, d, b) => {
            let d2 = drop_implicit_args(a, d, map, memo);
            let b2 = drop_implicit_args(a, b, map, memo);
            a.intern(Node::Lam(bi, d2, b2))
        }
        Node::Pi(bi, d, b) => {
            let d2 = drop_implicit_args(a, d, map, memo);
            let b2 = drop_implicit_args(a, b, map, memo);
            a.intern(Node::Pi(bi, d2, b2))
        }
        Node::Let(x, y, z) => {
            let x2 = drop_implicit_args(a, x, map, memo);
            let y2 = drop_implicit_args(a, y, map, memo);
            let z2 = drop_implicit_args(a, z, map, memo);
            a.intern(Node::Let(x2, y2, z2))
        }
        Node::Proj(s, i, x) => {
            let x2 = drop_implicit_args(a, x, map, memo);
            a.intern(Node::Proj(s, i, x2))
        }
        _ => t,
    };
    memo.insert(t, out);
    out
}

/// A declaration that shares a rigid skeleton, and the substitutions that reach it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Variant {
    pub name: String,
    /// `(from, to)` per differing slot, in slot order. Never empty — a variant with no
    /// substitution is the declaration itself.
    pub substitutions: Vec<(String, String)>,
}

/// A declaration sharing a class's distinguished vocabulary without being in it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VocabAdjacent {
    pub name: String,
    /// The distinguished constants it shares, rarest-first order not guaranteed.
    pub shared: Vec<String>,
    /// Document frequency of the rarest shared constant — how specific the link is.
    pub rarest_df: u32,
}

/// A declaration just outside an equivalence class, with the edit that reaches it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Adjacent {
    pub name: String,
    /// The class member it is adjacent to — the shortest route in.
    pub adjacent_to: String,
    pub substitutions: Vec<(String, String)>,
}

pub struct SkeletonIndex {
    arena: Arena,
    sigs: Signatures,
    cache: EraseCache,
    names: Vec<String>,
    modules: Vec<String>,
    kinds: Vec<String>,
    /// How auto-generated each declaration looks, in [0,1]. See `ScoreFactors`.
    derivative: Vec<f32>,
    /// In how many declarations each constant symbol occurs.
    ///
    /// The substrate for `SimilarityScore::InfoWeighted`: a shared `Eq` should not count
    /// the same as a shared `riemannZeta`, and node counting cannot tell them apart.
    sym_df: HashMap<SymId, u32>,
    by_name: HashMap<String, DeclId>,
    roots: Vec<TermId>,
    shape: Vec<TermId>,
    /// The `Presentation` erasure of each root — the level source B's postings are keyed
    /// at. Kept rather than recomputed because `candidates` takes `&self` and erasure
    /// needs `&mut Arena`; discarding it is what let the query drift to the raw root.
    pres: Vec<TermId>,
    shape_bucket: HashMap<TermId, Vec<DeclId>>,
    concrete: Postings,
    shape_sub: Postings,
    /// Application heads whose signature the slice does not contain, counted with repeats.
    /// See `closure` — this is the corpus's most load-bearing health number and it read 0
    /// on every corpus until the root-only spine test was fixed.
    degraded_spines: u64,
    known_heads: u64,
    /// Rigid-skeleton buckets, built on first use. Keyed by `TermId` because the arena is
    /// hash-consed, so structural equality of blanked terms is pointer equality here.
    rigid_index: Option<HashMap<TermId, Vec<DeclId>>>,
    /// In how many *statements* each unknown head occurs, so a diagnostic can name the
    /// constants worth extracting rather than only how many were missed.
    unknown_head_df: HashMap<SymId, u32>,
    /// The config the postings were built with. Kept so a diagnostic can reproduce the
    /// size floors, and so a result can name the scorer that produced it.
    build_cfg: IndexConfig,
    corpus_digest: String,
}

impl IndexConfig {
    /// A digest over every field that can move a score, in a fixed order.
    ///
    /// `f32` fields are hashed as `to_le_bytes` rather than through `Hash`, which `f32`
    /// does not implement — for the good reason that `NaN != NaN`. Byte equality is the
    /// right relation here anyway: two configs are the same config when they are the same
    /// bytes, and a digest is not asked to decide anything subtler.
    pub fn digest(&self) -> String {
        use sha2::{Digest, Sha256};
        let mut h = Sha256::new();
        for v in [
            self.min_concrete_closed,
            self.min_concrete_open,
            self.min_shape_sub,
            self.max_bucket as u32,
            self.candidate_budget as u32,
            self.min_common,
        ] {
            h.update(v.to_le_bytes());
        }
        for v in [
            self.max_posting_fraction,
            self.min_retention,
            self.rarity_weight,
            self.cross_weight,
            self.scoped_weight,
            self.derivative_weight,
        ] {
            h.update(v.to_le_bytes());
        }
        h.update([
            self.lgg_level as u8,
            self.anchor as u8,
            self.normalize_arity as u8,
            self.score as u8,
            self.theorems_only as u8,
            self.source_b_at_build_level as u8,
        ]);
        // Presence byte plus value, so `None` and `Some(0)` differ — both are real
        // settings: `Some(0)` starves sources B and C outright, the walk-bound ablation.
        h.update([self.posting_work_budget.is_some() as u8]);
        h.update((self.posting_work_budget.unwrap_or(0) as u64).to_le_bytes());
        h.update(self.restrict_prefix.as_deref().unwrap_or("").as_bytes());
        crate::statement::to_hex(&h.finalize())
    }
}

impl SkeletonIndex {
    pub fn build(jsonl: &str, cfg: &IndexConfig) -> Result<SkeletonIndex, GraphError> {
        // Over the raw slice, so it identifies the corpus a score was computed against
        // rather than the subset that happened to parse.
        let corpus_digest = {
            use sha2::{Digest, Sha256};
            let mut h = Sha256::new();
            h.update(jsonl.as_bytes());
            crate::statement::to_hex(&h.finalize())
        };
        let mut arena = Arena::new();
        let (mut names, mut modules, mut kinds, mut roots) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new());
        let mut proofs: Vec<Vec<String>> = Vec::new();
        let mut sig_rows = Vec::new();

        for (i, line) in jsonl.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let v = crate::json::parse(line).map_err(|reason| GraphError::BadRow {
                line: i + 1,
                reason,
            })?;
            let row = crate::graph::parse_row_value(&v).map_err(|reason| GraphError::BadRow {
                line: i + 1,
                reason,
            })?;
            // A row whose statement could not be encoded is kept by B1 and skipped here:
            // it has no term to index, and dropping it silently would be worse than
            // saying so.
            let Some(stmt) = row.stmt.as_deref() else {
                continue;
            };
            let Ok(t) = arena.parse(stmt) else { continue };
            // Applied once, here, so every downstream structure — postings, buckets,
            // erasures, the query term — sees the same term. Transforming at query time
            // instead would compare a conclusion against whole-statement postings.
            let t = if cfg.anchor == Anchor::Conclusion {
                arena.conclusion(t)
            } else {
                t
            };
            let sym = arena.intern_sym(&row.name);
            sig_rows.push((sym, t));
            names.push(row.name);
            modules.push(row.module);
            kinds.push(row.kind);
            proofs.push(row.uses_proof);
            roots.push(t);
        }

        // Applied after every root is parsed, because the map is read off the corpus and
        // is not complete until then. Before `Signatures`, so the erasures downstream see
        // the normalised terms.
        if cfg.normalize_arity {
            let map = implicit_positions(&mut arena, &names, &roots);
            let mut memo = HashMap::new();
            for r in roots.iter_mut() {
                *r = drop_implicit_args(&mut arena, *r, &map, &mut memo);
            }
        }

        let sigs = Signatures::from_rows(&arena, sig_rows.into_iter());
        let n = roots.len();
        let mut cache = EraseCache::new();

        let mut shape = Vec::with_capacity(n);
        let mut pres_of = Vec::with_capacity(n);
        let mut shape_bucket: HashMap<TermId, Vec<DeclId>> = HashMap::new();
        let mut concrete_pairs = Vec::new();
        let mut shape_pairs = Vec::new();
        let mut degraded_spines = 0u64;
        let mut known_heads = 0u64;
        let mut unknown_head_df: HashMap<SymId, u32> = HashMap::new();

        for (i, &t) in roots.iter().enumerate() {
            let id = DeclId(i as u32);
            let pres = erase(&mut arena, &sigs, &mut cache, t, Level::Presentation);
            let sh = erase(&mut arena, &sigs, &mut cache, t, Level::Shape);
            shape.push(sh);
            pres_of.push(pres);
            shape_bucket.entry(sh).or_default().push(id);

            let mut subs = BTreeSet::new();
            arena.subterms(pres, &mut subs);
            for s in subs {
                let sz = arena.size(s);
                let floor = if arena.is_closed(s) {
                    cfg.min_concrete_closed
                } else {
                    cfg.min_concrete_open
                };
                if sz >= floor {
                    concrete_pairs.push((s, id));
                }
            }
            let mut ssubs = BTreeSet::new();
            arena.subterms(sh, &mut ssubs);
            for s in ssubs {
                if arena.size(s) >= cfg.min_shape_sub {
                    shape_pairs.push((s, id));
                }
            }
            // Closure coverage, over **every** application head in the statement.
            //
            // This tested `arena.spine(t).0` — the *root's* head — which for a quantified
            // theorem is the `Pi` itself, so the `Const` arm never matched and the counter
            // read 0 for essentially every theorem in every corpus. It is the same defect
            // `key_of` had: a spine test that forgets statements begin with binders.
            //
            // It matters because an unknown head is not cosmetic. `erase_spine` asks
            // `sigs.arg_kind` which positions are `InstImplicit`, and a miss holes nothing
            // and silently degrades that spine to `Presentation`. A slice that is not
            // closed under the constants its statements mention therefore answers every
            // query at `Instances` and above with a normalisation that did not happen.
            let mut heads: Vec<SymId> = Vec::new();
            collect_app_heads(&arena, t, &mut heads);
            for &s in heads.iter() {
                if sigs.known(s) {
                    known_heads += 1;
                } else {
                    degraded_spines += 1;
                }
            }
            // The counters above are per *spine*, since that is what degraded. The
            // frequency is per *statement*, matching `sym_df`, so that one verbose proof
            // term cannot make a constant look ubiquitous.
            heads.retain(|&s| !sigs.known(s));
            heads.sort_unstable();
            heads.dedup();
            for s in heads {
                *unknown_head_df.entry(s).or_insert(0u32) += 1;
            }
        }

        // The posting cutoff, and the reason it is now two knobs.
        //
        // This was `.max(50)`, which makes `max_posting_fraction` **inert below n = 50,000**
        // — the floor wins — so the effective fraction *tightens* as a corpus grows: at
        // n = 347 a key may be held by 14% of declarations, at n = 14,563 by 0.34%. A key
        // over the cutoff is dropped outright, and cross-theory analogies are precisely the
        // ones that share *common* keys.
        //
        // Two independent measurements converged on it. A dilution experiment held two
        // theories' rows byte-identical and added unrelated declarations around them:
        // true dictionary rows fell 3/4 -> 0/4 as the corpus grew 347 -> 14,563, with the
        // rows themselves unchanged. Separately, of 36 physics truth pairs the prefilter
        // missed, **30 shared an indexable key and were never proposed** — the loss is here,
        // not in the size floors a recall study would have blamed.
        //
        // Left at 50 so this change moves no number by itself; `min_posting_len` makes the
        // knob reachable, and CLAUDE.md's rule that false negatives are the expensive kind
        // says which direction to sweep it.
        let max_len = if cfg.posting_work_budget.is_some() {
            // Work-budget admission: keep every key and bound the *walk* instead
            // (`candidates`). The keys the cutoff deletes are the common ones
            // cross-theory analogy shares, and no constant of the cutoff's shape
            // survives a change of corpus scale — see `posting_work_budget`'s doc.
            usize::MAX
        } else {
            ((n as f32 * cfg.max_posting_fraction) as usize).max(cfg.min_posting_len)
        };
        let concrete = Postings::build(concrete_pairs, n, max_len);
        let shape_sub = Postings::build(shape_pairs, n, max_len);

        let by_name: HashMap<String, DeclId> = names
            .iter()
            .enumerate()
            .map(|(i, n)| (n.clone(), DeclId(i as u32)))
            .collect();

        let derivative = derivativeness(&kinds, &proofs, &by_name);
        drop(proofs);

        // Document frequency per constant symbol, counted once per declaration so that a
        // symbol repeated inside one statement does not look common.
        let mut sym_df: HashMap<SymId, u32> = HashMap::new();
        {
            let mut here: Vec<SymId> = Vec::new();
            for &t in roots.iter() {
                here.clear();
                collect_syms(&arena, t, &mut here);
                here.sort_unstable();
                here.dedup();
                for s in here.iter() {
                    *sym_df.entry(*s).or_insert(0) += 1;
                }
            }
        }

        arena.seal();
        Ok(SkeletonIndex {
            arena,
            sigs,
            cache,
            names,
            modules,
            kinds,
            derivative,
            sym_df,
            by_name,
            roots,
            shape,
            pres: pres_of,
            shape_bucket,
            concrete,
            shape_sub,
            degraded_spines,
            known_heads,
            rigid_index: None,
            unknown_head_df,
            build_cfg: cfg.clone(),
            corpus_digest,
        })
    }

    /// Which scorer a row from this index came from.
    ///
    /// Two configs are in play — the one the postings were built with and the one a query
    /// passes — and they can differ, so both are digested. A row whose `config_digest`
    /// does not match the running engine's was produced by a different scorer, whatever
    /// its numbers look like.
    pub fn scorer_id(&self, cfg: &IndexConfig) -> ScorerId {
        let digest = if *cfg == self.build_cfg {
            cfg.digest()
        } else {
            use sha2::{Digest, Sha256};
            let mut h = Sha256::new();
            h.update(self.build_cfg.digest().as_bytes());
            h.update(cfg.digest().as_bytes());
            crate::statement::to_hex(&h.finalize())
        };
        ScorerId {
            name: "atlas/skel",
            version: SCORER_VERSION,
            config_digest: digest,
            corpus_digest: self.corpus_digest.clone(),
        }
    }

    pub fn len(&self) -> usize {
        self.roots.len()
    }
    pub fn is_empty(&self) -> bool {
        self.roots.is_empty()
    }
    pub fn degraded_spines(&self) -> u64 {
        self.degraded_spines
    }

    /// Is this slice closed under the constants its statements mention?
    ///
    /// Returns `(known_heads, unknown_heads, worst)` where `worst` names the unknown
    /// constants by how many statements mention them, largest first.
    ///
    /// **Read this before trusting any query at `Instances` or above.** The erasure holes
    /// arguments in `InstImplicit` positions of the head's signature, so an unknown head
    /// holes nothing and that spine is silently normalised at `Presentation` instead. The
    /// failure is invisible: no error, no empty result, just a weaker normalisation than
    /// the level name promises.
    ///
    /// A slice extracted with `--local` is the way this goes wrong in practice — it filters
    /// the output, not the import, so Mathlib's own modules arrive without `Eq`, `Iff`,
    /// `LE.le` or `Monad`, and coverage collapses to near zero.
    pub fn closure(&self, top: usize) -> (u64, u64, Vec<(String, u32)>) {
        let mut worst: Vec<(&str, u32)> = self
            .unknown_head_df
            .iter()
            .map(|(&s, &df)| (self.arena.sym(s), df))
            .collect();
        worst.sort_unstable_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(b.0)));
        worst.truncate(top);
        (
            self.known_heads,
            self.degraded_spines,
            worst
                .into_iter()
                .map(|(n, df)| (n.to_string(), df))
                .collect(),
        )
    }
    pub fn id_of(&self, name: &str) -> Option<DeclId> {
        self.by_name.get(name).copied()
    }
    pub fn name_of(&self, d: DeclId) -> &str {
        &self.names[d.0 as usize]
    }
    /// Positional kind and module, so a caller can restrict a sample to *claims* before
    /// measuring anything over it. A uniform sample of a working slice is two-thirds
    /// `Init`/`Std`/`Lean` and half non-theorems, which is how a recall figure ends up
    /// describing Lean's metaprogramming API rather than mathematics.
    pub fn kind_of_at(&self, i: usize) -> &str {
        &self.kinds[i]
    }
    pub fn module_of_at(&self, i: usize) -> &str {
        &self.modules[i]
    }
    pub fn signature_count(&self) -> usize {
        self.sigs.len()
    }
    pub fn module_of(&self, name: &str) -> Option<&str> {
        self.by_name
            .get(name)
            .map(|d| self.modules[d.0 as usize].as_str())
    }
    pub fn is_theorem(&self, name: &str) -> bool {
        self.by_name
            .get(name)
            .is_some_and(|d| self.kinds[d.0 as usize] == "theorem")
    }
    pub fn shape_of(&self, d: DeclId) -> TermId {
        self.shape[d.0 as usize]
    }
    pub fn arena_mut(&mut self) -> &mut Arena {
        &mut self.arena
    }
    /// A declaration's statement at a level, by name.
    pub fn term_of(&mut self, name: &str, level: Level) -> Option<TermId> {
        let d = self.id_of(name)?;
        Some(self.level_term(d, level))
    }
    /// Which declaration, if any, has exactly this statement at this level. Used by
    /// `transport` to tell "already a theorem" from "a directed target".
    pub fn name_with_term(&mut self, t: TermId, level: Level) -> Option<String> {
        (0..self.len()).find_map(|i| {
            let d = DeclId(i as u32);
            (self.level_term(d, level) == t).then(|| self.names[i].clone())
        })
    }
    /// The corpus's recurring sub-patterns: `(rendered pattern, members, size, idf)`.
    ///
    /// Read off the posting lists, which the ranking builds anyway and then uses only to
    /// shortlist candidates. `source` selects which index: `"subterm"` is the
    /// `Presentation`-level concrete subterms, `"shape"` the `Shape`-level ones — the
    /// latter is where cross-carrier motifs live, because it is the only level that holes
    /// the constants.
    pub fn motifs(
        &self,
        source: &str,
        min_family: usize,
        min_size: u32,
    ) -> Vec<(String, Vec<String>, u32, f32)> {
        let p = if source == "shape" {
            &self.shape_sub
        } else {
            &self.concrete
        };
        let mut out = Vec::new();
        for (key, decls, idf) in p.entries() {
            if decls.len() < min_family {
                continue;
            }
            let size = self.arena.size(key);
            if size < min_size {
                continue;
            }
            out.push((
                self.arena.render(key),
                decls
                    .iter()
                    .map(|d| self.names[d.0 as usize].clone())
                    .collect::<Vec<String>>(),
                size,
                idf,
            ));
        }
        // Informativeness first: a big family sharing a trivial motif is punctuation, and a
        // large motif shared by two declarations is a coincidence. Neither dimension orders
        // usefully alone, so rank on their product.
        out.sort_by(|a, b| {
            let sa = a.2 as f32 * (a.1.len() as f32 + 1.0).ln();
            let sb = b.2 as f32 * (b.1.len() as f32 + 1.0).ln();
            sb.total_cmp(&sa)
        });
        out
    }

    pub fn key_counts(&self) -> (usize, usize) {
        (self.concrete.key_count(), self.shape_sub.key_count())
    }

    /// Candidates for a query, with the sources each arrived through and the rarest key
    /// that produced it.
    pub fn candidates(&self, q: DeclId, cfg: &IndexConfig) -> Vec<(DeclId, Sources, f32)> {
        let mut hits: HashMap<DeclId, (Sources, f32)> = HashMap::new();
        let note = |hits: &mut HashMap<DeclId, (Sources, f32)>, d: DeclId, src: u8, idf: f32| {
            if d == q {
                return;
            }
            let e = hits.entry(d).or_insert((Sources::default(), 0.0));
            e.0.add(src);
            if idf > e.1 {
                e.1 = idf;
            }
        };

        // A — structural twins.
        let sh = self.shape[q.0 as usize];
        if let Some(bucket) = self.shape_bucket.get(&sh)
            && bucket.len() <= cfg.max_bucket
        {
            let idf = (self.len() as f32 / bucket.len() as f32).ln();
            for &d in bucket {
                note(&mut hits, d, Sources::SHAPE, idf);
            }
        }

        // B and C — subterm overlap. Rarest keys first, so the budget is spent on the
        // most informative overlaps rather than on whatever came first.
        // Source B is keyed on subterms of the *presentation erasure* (see `build`), so
        // it must be queried with the same. Querying with the raw root instead made the
        // lookup miss almost always — the arena is hash-consed, so a term that differs at
        // all differs in its `TermId`. Measured on the 131k algebra slice: 6.7% of a
        // query's subterms hit a posting, and 60.6% of declarations got no source-B
        // candidate whatsoever. At the level the postings were actually built at, 88.2%
        // and 6.9%.
        let pres = if cfg.source_b_at_build_level {
            self.pres[q.0 as usize]
        } else {
            self.roots[q.0 as usize]
        };
        let mut keyed: Vec<(f32, &[DeclId], u8)> = Vec::new();
        for (post, src, term) in [
            (&self.concrete, Sources::SUBTERM, pres),
            (&self.shape_sub, Sources::SHAPE_SUBTERM, sh),
        ] {
            let mut subs = BTreeSet::new();
            self.arena.subterms(term, &mut subs);
            for s in subs {
                if let Some((ds, idf)) = post.get(s) {
                    keyed.push((idf, ds, src));
                }
            }
        }
        // Rarest first is also the order the work budget meters, so it has to stay
        // deterministic: `sort_by` is stable, and keys tied on idf keep the order they
        // were pushed in — `BTreeSet` subterm order, concrete before shape.
        keyed.sort_by(|a, b| b.0.total_cmp(&a.0));
        let mut walked = 0usize;
        for (idf, ds, src) in keyed {
            // Either bound is checked at the *top* of a key, so one long list may
            // overshoot; changing that is a separate decision (prefilter §10).
            match cfg.posting_work_budget {
                // The work budget **replaces** `candidate_budget` while it is on: the
                // measured reference point (§6a, W = 2,000, 4/4) has no candidate cap,
                // and keeping one reproduces the 3/4 loss the budget exists to repair —
                // the slots fill on rarer keys before the walk reaches the common key
                // that carries the correspondence.
                Some(w) => {
                    if walked >= w {
                        break;
                    }
                    walked += ds.len();
                }
                None => {
                    if hits.len() >= cfg.candidate_budget {
                        break;
                    }
                }
            }
            for &d in ds {
                note(&mut hits, d, src, idf);
            }
        }

        let mut out: Vec<_> = hits.into_iter().map(|(d, (s, r))| (d, s, r)).collect();
        out.sort_by_key(|&(d, _, _)| d);
        out
    }

    /// The information a term carries: the summed surprisal of the constants it mentions.
    ///
    /// Structural nodes — applications, binders, de Bruijn indices — count **zero**. They
    /// are scaffolding every statement has, and counting them is what makes a verbose
    /// statement look different from a terse one saying the same thing. Erasure holes also
    /// count zero, which is right: a hole is the absence of content.
    fn info_weight(&self, t: TermId) -> f32 {
        let n = self.len().max(1) as f32;
        let mut syms = Vec::new();
        collect_syms(&self.arena, t, &mut syms);
        syms.iter()
            .map(|s| {
                let df = *self.sym_df.get(s).unwrap_or(&1) as f32;
                (n / df.max(1.0)).ln().max(0.0)
            })
            .sum()
    }

    /// The configured score for one candidate.
    ///
    /// Split out because the information-weighted forms need corpus statistics that a
    /// `Generalization` does not carry, and passing them into `SimilarityScore::apply`
    /// would put an `Arena` in a formula's signature for the benefit of two of eight arms.
    fn score_of(&self, g: &Generalization, qt: TermId, ct: TermId, cfg: &IndexConfig) -> f32 {
        if !cfg.score.needs_corpus() {
            return cfg.score.apply(g);
        }
        let (wg, wx, wy) = (
            self.info_weight(g.skeleton),
            self.info_weight(qt),
            self.info_weight(ct),
        );
        match cfg.score {
            SimilarityScore::InfoDice => {
                if wx + wy <= 0.0 {
                    0.0
                } else {
                    2.0 * wg / (wx + wy)
                }
            }
            _ => {
                let d = wx.max(wy);
                if d <= 0.0 { 0.0 } else { wg / d }
            }
        }
    }

    /// The neighbours of a declaration, ranked.
    pub fn similar(
        &mut self,
        name: &str,
        top: usize,
        cfg: &IndexConfig,
    ) -> Result<Vec<Neighbour>, String> {
        let q = self
            .id_of(name)
            .ok_or_else(|| format!("`{name}` is not in this slice"))?;
        let cands = self.candidates(q, cfg);
        let qt = self.level_term(q, cfg.lgg_level);
        let ln_n = (self.len() as f32).ln();
        let q_root = module_root(&self.modules[q.0 as usize]).to_string();

        let mut out = Vec::new();
        for (d, sources, rarity) in cands {
            if cfg.theorems_only && self.kinds[d.0 as usize] != "theorem" {
                continue;
            }
            if let Some(prefix) = &cfg.restrict_prefix {
                let m = &self.modules[d.0 as usize];
                // Equality or a dotted prefix: bare `starts_with` would let
                // `Mathlib.AlgebraicGeometry` in under `Mathlib.Algebra`.
                if m != prefix && !m.starts_with(&format!("{prefix}.")) {
                    continue;
                }
            }
            let ct = self.level_term(d, cfg.lgg_level);
            let g: Generalization = generalize(&mut self.arena, qt, ct);
            // The floor applies to the **configured** score, not to retention. Flooring on
            // retention while ranking on something else would undo the change: the pairs a
            // different scorer exists to rescue are exactly the ones retention discards.
            let base = self.score_of(&g, qt, ct, cfg);
            if g.common < cfg.min_common || base < cfg.min_retention {
                continue;
            }
            let cross = module_root(&self.modules[d.0 as usize]) != q_root;
            let (name, module, kind) = (
                self.names[d.0 as usize].clone(),
                self.modules[d.0 as usize].clone(),
                self.kinds[d.0 as usize].clone(),
            );
            let factors = ScoreFactors {
                retention: g.retention,
                base,
                rarity_boost: 1.0 + cfg.rarity_weight * (rarity / ln_n).min(1.0),
                cross_boost: 1.0 + if cross { cfg.cross_weight } else { 0.0 },
                scoped_penalty: 1.0
                    - cfg.scoped_weight * g.scoped_vars as f32 / g.vars.max(1) as f32,
                derivative_penalty: 1.0 - cfg.derivative_weight * self.derivative[d.0 as usize],
                total: 0.0,
            };
            let factors = ScoreFactors {
                total: factors.base
                    * factors.rarity_boost
                    * factors.cross_boost
                    * factors.scoped_penalty
                    * factors.derivative_penalty,
                ..factors
            };
            let score = factors.total;
            out.push(Neighbour {
                name,
                module,
                kind,
                retention: g.retention,
                common: g.common,
                vars: g.vars,
                scoped_vars: g.scoped_vars,
                rarity,
                sources,
                skeleton: self.arena.render(g.skeleton),
                transportable: g.scoped_vars == 0,
                score,
                factors,
            });
        }
        // Ties are the normal case, not the exception — the score is a product of a few
        // coarse factors, so whole families land on the same value. Breaking straight to
        // the name meant ASCII decided the top of the list: `dvd_trans` sits in a
        // four-way tie for `le_trans` and lowercase sorts after every capitalised name,
        // so the flagship pair fell out of the top five and took a gate with it.
        //
        // So spend the content-bearing signals first. `common` prefers the candidate
        // sharing more actual structure; `vars` prefers the one that needed fewer
        // abstractions to get there. The name remains last, because a total order has to
        // end somewhere and a deterministic one is worth more than a prettier tie-break.
        out.sort_by(|a, b| {
            b.score
                .total_cmp(&a.score)
                .then(b.common.cmp(&a.common))
                .then(a.vars.cmp(&b.vars))
                .then(a.name.cmp(&b.name))
        });
        out.truncate(top);
        Ok(out)
    }

    /// Diagnostic for the normalization-symmetry question: how many of a declaration's
    /// subterms actually hit a posting, computed both the way `candidates` asks today
    /// (subterms of the raw root) and the way the postings were built (subterms of the
    /// presentation erasure). Returns `((keys, hits), (keys, hits))`.
    ///
    /// Exists because "the query and the index disagree about normalization" is a claim
    /// that should be measured before it is repaired.
    pub fn subterm_key_hits(&mut self, i: usize) -> ((usize, usize), (usize, usize)) {
        let root = self.roots[i];
        let pres = erase(
            &mut self.arena,
            &self.sigs,
            &mut self.cache,
            root,
            Level::Presentation,
        );
        let count = |term: TermId| {
            let mut subs = BTreeSet::new();
            self.arena.subterms(term, &mut subs);
            let (mut keys, mut hits) = (0, 0);
            for s in subs {
                let floor = if self.arena.is_closed(s) {
                    self.build_cfg.min_concrete_closed
                } else {
                    self.build_cfg.min_concrete_open
                };
                if self.arena.size(s) < floor {
                    continue;
                }
                keys += 1;
                if self.concrete.get(s).is_some() {
                    hits += 1;
                }
            }
            (keys, hits)
        };
        (count(root), count(pres))
    }

    fn level_term(&mut self, d: DeclId, level: Level) -> TermId {
        let t = self.roots[d.0 as usize];
        erase(&mut self.arena, &self.sigs, &mut self.cache, t, level)
    }

    /// The rendered erasure of one declaration.
    pub fn skeleton_of(&mut self, name: &str, level: Level) -> Option<String> {
        let d = self.id_of(name)?;
        let t = self.level_term(d, level);
        Some(self.arena.render(t))
    }

    /// The **rigid skeleton**: the statement's tree with every constant *name* blanked,
    /// plus the names in slot order.
    ///
    /// The point of the pair is that it is lossless — refilling the slots reconstructs the
    /// statement — so two declarations with the same rigid skeleton differ **only in which
    /// constants fill which slots**, and their difference is an *edit* rather than a float.
    /// That is exactly what `generalize` discards: it keeps the lgg's node counts and drops
    /// the substitutions, which are the actionable part.
    ///
    /// Levels are kept. Only the name is blanked, so `Nat.add` and `Int.mul` collapse
    /// together while a term at a different universe does not.
    ///
    /// Because the arena is hash-consed, rigid-skeleton *equality is `TermId` equality* —
    /// no rendering, no hashing, no string comparison.
    pub fn rigid(&mut self, name: &str) -> Option<(TermId, Vec<SymId>)> {
        let d = self.id_of(name)?;
        let t = self.roots[d.0 as usize];
        let blank = self.arena.intern_sym("");
        let mut slots = Vec::new();
        let skel = Self::blank_consts(&mut self.arena, blank, t, &mut slots);
        Some((skel, slots))
    }

    /// Rebuild `t` with every `Const` name replaced by `blank`, collecting the originals.
    ///
    /// Pre-order, matching the order `render` emits constants, so a slot index means the
    /// same thing here and in the byte encoding. A differential against an independent
    /// byte-level implementation checks that (see `tests`).
    fn blank_consts(a: &mut Arena, blank: SymId, t: TermId, slots: &mut Vec<SymId>) -> TermId {
        match a.node(t) {
            Node::Const(s, lv) => {
                slots.push(s);
                a.intern(Node::Const(blank, lv))
            }
            Node::App(f, x) => {
                let f2 = Self::blank_consts(a, blank, f, slots);
                let x2 = Self::blank_consts(a, blank, x, slots);
                a.intern(Node::App(f2, x2))
            }
            Node::Lam(bi, d, b) => {
                let d2 = Self::blank_consts(a, blank, d, slots);
                let b2 = Self::blank_consts(a, blank, b, slots);
                a.intern(Node::Lam(bi, d2, b2))
            }
            Node::Pi(bi, d, b) => {
                let d2 = Self::blank_consts(a, blank, d, slots);
                let b2 = Self::blank_consts(a, blank, b, slots);
                a.intern(Node::Pi(bi, d2, b2))
            }
            Node::Let(x, y, z) => {
                let x2 = Self::blank_consts(a, blank, x, slots);
                let y2 = Self::blank_consts(a, blank, y, slots);
                let z2 = Self::blank_consts(a, blank, z, slots);
                a.intern(Node::Let(x2, y2, z2))
            }
            Node::Proj(s, i, x) => {
                slots.push(s);
                let x2 = Self::blank_consts(a, blank, x, slots);
                a.intern(Node::Proj(blank, i, x2))
            }
            _ => t,
        }
    }

    /// Declarations whose statement is this one with at most `max_subs` constants swapped,
    /// each reported **with the substitution that produces it**.
    ///
    /// Not a ranking. Two declarations either share a rigid skeleton or they do not, and if
    /// they do the answer is a list of `(from, to)` pairs a caller can act on —
    /// `Ne`↔`Eq`, `Injective`↔`Surjective`, `Monotone`↔`Antitone`, `≤`↔`<`.
    ///
    /// `max_subs = 0` degenerates to "statements identical up to nothing", which is
    /// `equivalent` at `exact`; the interesting settings are 1 and 2.
    pub fn variants(&mut self, name: &str, max_subs: usize, top: usize) -> Option<Vec<Variant>> {
        let (skel, mine) = self.rigid(name)?;
        let peers = self.rigid_bucket(skel);
        let mut out = Vec::new();
        for d in peers {
            let other = self.names[d.0 as usize].clone();
            if other == name {
                continue;
            }
            let Some((_s, theirs)) = self.rigid(&other) else {
                continue;
            };
            // Same skeleton implies the same slot count; a mismatch would be a bug in
            // `blank_consts`, so it is skipped rather than silently zipped short.
            if theirs.len() != mine.len() {
                continue;
            }
            // **Distinct** substitutions, not differing slots.
            //
            // `le_trans` and `lt_trans` differ in six positions and by one idea: `LE.le`
            // becomes `LT.lt`, three times, and `Preorder.toLE` becomes `Preorder.toLT`,
            // three times. Counting slots calls that a six-edit neighbour and buries it
            // below noise; counting substitutions calls it two, which is what a reader
            // means. Measured: slot-counting returned **0** one-substitution partners for
            // `le_trans`, `Nat.add_comm` and `dvd_trans` alike.
            //
            // A slot pair is still required to be *consistent*: if `Eq` maps to `Ne` in one
            // slot and to `Iff` in another, that is two substitutions, and the pair is
            // ranked accordingly rather than merged.
            let mut seen: BTreeSet<(SymId, SymId)> = BTreeSet::new();
            for (a, b) in mine.iter().zip(theirs.iter()) {
                if a != b {
                    seen.insert((*a, *b));
                }
            }
            let subs: Vec<(String, String)> = seen
                .iter()
                .map(|(a, b)| {
                    (
                        self.arena.sym(*a).to_string(),
                        self.arena.sym(*b).to_string(),
                    )
                })
                .collect();
            if !subs.is_empty() && subs.len() <= max_subs {
                out.push(Variant {
                    name: other,
                    substitutions: subs,
                });
            }
        }
        // Fewest edits first, then by name so the order is total and reproducible.
        out.sort_by(|a, b| {
            a.substitutions
                .len()
                .cmp(&b.substitutions.len())
                .then_with(|| a.name.cmp(&b.name))
        });
        out.truncate(top);
        Some(out)
    }

    /// What sits just **outside** an equivalence class, and by which edit.
    ///
    /// §46 scored B7's V6 target PARTIAL for exactly this gap: the cluster assembled, but
    /// nothing could surface `Lambda >= 0` as an *adjacent non-member* of the
    /// `Lambda <= 0` cluster. "Which statements are one substitution away from this family
    /// but not in it" is the sharpening question, and a similarity ranking cannot express
    /// it — a near miss and a distant cousin both come back as floats.
    ///
    /// Takes the class rather than computing it, because class membership is
    /// `EquivIndex`'s job and structure is this index's. The caller passes every member;
    /// anything reachable from a member by at most `max_subs` substitutions and *not*
    /// itself a member is adjacent.
    ///
    /// Each row names the member it is adjacent to and the substitution that reaches it, so
    /// the answer is "`Lambda >= 0` is this class with `LE.le` swapped for `GE.ge`" rather
    /// than a score.
    pub fn adjacent(&mut self, members: &[String], max_subs: usize, top: usize) -> Vec<Adjacent> {
        let inside: BTreeSet<&str> = members.iter().map(|s| s.as_str()).collect();
        let mut best: HashMap<String, Adjacent> = HashMap::new();
        for m in members {
            let Some(vs) = self.variants(m, max_subs, usize::MAX) else {
                continue;
            };
            for v in vs {
                if inside.contains(v.name.as_str()) {
                    continue;
                }
                // Keep the *closest* route in. A statement one edit from one member and
                // four from another is one edit away from the family.
                let cand = Adjacent {
                    name: v.name.clone(),
                    adjacent_to: m.clone(),
                    substitutions: v.substitutions,
                };
                match best.get(&v.name) {
                    Some(old) if old.substitutions.len() <= cand.substitutions.len() => {}
                    _ => {
                        best.insert(v.name, cand);
                    }
                }
            }
        }
        let mut out: Vec<Adjacent> = best.into_values().collect();
        out.sort_by(|a, b| {
            a.substitutions
                .len()
                .cmp(&b.substitutions.len())
                .then_with(|| a.name.cmp(&b.name))
        });
        out.truncate(top);
        out
    }

    /// What shares an equivalence class's **distinguished vocabulary** without being in it.
    ///
    /// The companion to `adjacent`, and the one B7's V6 actually needs. `adjacent` asks
    /// "same tree, which constants differ" — sharp, but it cannot cross a change of
    /// *shape*. `rh_iff_lambda_nonpos` is an `Iff` and `lambda_nonneg` is a bare
    /// inequality, so no number of substitutions relates them; what relates them is that
    /// both are about `Lambda`.
    ///
    /// "Distinguished" is document frequency, not a name list: a constant counts when it
    /// occurs in at most `max_df_fraction` of the corpus. Sharing `Eq` is not evidence;
    /// sharing `Lambda` is. That is the same rarity argument the ranking uses for IDF,
    /// applied as an *admission test* rather than a weight, so the answer stays exact —
    /// each row names the constants it shares rather than scoring them.
    pub fn vocabulary_adjacent(
        &mut self,
        members: &[String],
        max_df_fraction: f32,
        top: usize,
    ) -> Vec<VocabAdjacent> {
        let n = self.roots.len();
        let cutoff = ((n as f32 * max_df_fraction) as u32).max(2);
        let inside: BTreeSet<&str> = members.iter().map(|s| s.as_str()).collect();

        // The class's distinguished constants.
        let mut wanted: BTreeSet<SymId> = BTreeSet::new();
        for m in members {
            let Some(d) = self.id_of(m) else { continue };
            let mut syms = Vec::new();
            collect_syms(&self.arena, self.roots[d.0 as usize], &mut syms);
            syms.sort_unstable();
            syms.dedup();
            for s in syms {
                if self.sym_df.get(&s).copied().unwrap_or(0) <= cutoff {
                    wanted.insert(s);
                }
            }
        }
        if wanted.is_empty() {
            return Vec::new();
        }

        let mut out = Vec::new();
        for i in 0..n {
            let name = &self.names[i];
            if inside.contains(name.as_str()) {
                continue;
            }
            let mut syms = Vec::new();
            collect_syms(&self.arena, self.roots[i], &mut syms);
            syms.sort_unstable();
            syms.dedup();
            let shared: Vec<SymId> = syms.into_iter().filter(|s| wanted.contains(s)).collect();
            if shared.is_empty() {
                continue;
            }
            // Rarest shared constant first — it is the one carrying the claim.
            let rarest = shared
                .iter()
                .map(|s| self.sym_df.get(s).copied().unwrap_or(0))
                .min()
                .unwrap_or(0);
            out.push(VocabAdjacent {
                name: name.clone(),
                shared: shared
                    .iter()
                    .map(|s| self.arena.sym(*s).to_string())
                    .collect(),
                rarest_df: rarest,
            });
        }
        out.sort_by(|a, b| {
            b.shared
                .len()
                .cmp(&a.shared.len())
                .then_with(|| a.rarest_df.cmp(&b.rarest_df))
                .then_with(|| a.name.cmp(&b.name))
        });
        out.truncate(top);
        out
    }

    /// Every declaration sharing a rigid skeleton, built once and cached.
    fn rigid_bucket(&mut self, skel: TermId) -> Vec<DeclId> {
        if self.rigid_index.is_none() {
            let blank = self.arena.intern_sym("");
            let mut idx: HashMap<TermId, Vec<DeclId>> = HashMap::new();
            for i in 0..self.roots.len() {
                let t = self.roots[i];
                let mut slots = Vec::new();
                let s = Self::blank_consts(&mut self.arena, blank, t, &mut slots);
                idx.entry(s).or_default().push(DeclId(i as u32));
            }
            self.rigid_index = Some(idx);
        }
        self.rigid_index
            .as_ref()
            .and_then(|m| m.get(&skel))
            .cloned()
            .unwrap_or_default()
    }

    /// Closure coverage restricted to declarations whose module starts with `prefix`.
    ///
    /// A global coverage figure is dominated by whatever the corpus is mostly made of. A
    /// merged corpus that is 97% Mathlib reports 99.59% while saying **nothing** about
    /// whether the 3% of physics statements are closed — and physics is the part being
    /// studied. That is §31's failure mode one level up: the number is real, it is simply
    /// about the wrong population.
    ///
    /// Recomputed on demand rather than accumulated per prefix at build time, because this
    /// is a diagnostic and the caller chooses the stratum after the fact.
    pub fn closure_by(&self, prefix: &str, top: usize) -> (u64, u64, Vec<(String, u32)>) {
        let (mut known, mut unknown) = (0u64, 0u64);
        let mut df: HashMap<SymId, u32> = HashMap::new();
        for i in 0..self.roots.len() {
            if !self.modules[i].starts_with(prefix) {
                continue;
            }
            let mut heads = Vec::new();
            collect_app_heads(&self.arena, self.roots[i], &mut heads);
            for &s in heads.iter() {
                if self.sigs.known(s) {
                    known += 1;
                } else {
                    unknown += 1;
                }
            }
            heads.retain(|&s| !self.sigs.known(s));
            heads.sort_unstable();
            heads.dedup();
            for s in heads {
                *df.entry(s).or_insert(0) += 1;
            }
        }
        let mut worst: Vec<(&str, u32)> =
            df.iter().map(|(&s, &d)| (self.arena.sym(s), d)).collect();
        worst.sort_unstable_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(b.0)));
        worst.truncate(top);
        (
            known,
            unknown,
            worst.into_iter().map(|(n, d)| (n.to_string(), d)).collect(),
        )
    }

    /// The typeclasses a declaration's `InstImplicit` binders require, in binder order.
    ///
    /// Exists so a caller does not have to re-parse the slice to learn what a declaration
    /// demands. The novelty screen needs this for the handful of declarations `equivalent`
    /// returns, and re-derived it by telescoping all 470,435 statements in Python — 35
    /// minutes to answer a question the arena already holds. That cost is why the
    /// generalization pipeline was run in the wrong order (probe, then screen) and spent
    /// kernel budget on rediscoveries.
    ///
    /// Reads the *unerased* root: at `Instances` and above the binder domains are exactly
    /// what gets holed, so the erased term cannot answer this.
    pub fn requires(&self, name: &str) -> Option<Vec<String>> {
        let d = self.id_of(name)?;
        let mut out = Vec::new();
        let mut cur = self.roots[d.0 as usize];
        while let Node::Pi(bi, dom, body) = self.arena.node(cur) {
            if bi == BinderInfo::InstImplicit
                && let Node::Const(s, _) = self.arena.node(self.arena.spine(dom).0)
            {
                out.push(self.arena.sym(s).to_string());
            }
            cur = body;
        }
        Some(out)
    }

    /// The skeleton of two named declarations — `atlas similar`'s row, on demand.
    pub fn generalize_named(
        &mut self,
        a: &str,
        b: &str,
        level: Level,
    ) -> Result<(Generalization, String), String> {
        let (x, y) = (
            self.id_of(a)
                .ok_or_else(|| format!("`{a}` is not in this slice"))?,
            self.id_of(b)
                .ok_or_else(|| format!("`{b}` is not in this slice"))?,
        );
        let (tx, ty) = (self.level_term(x, level), self.level_term(y, level));
        let g = generalize(&mut self.arena, tx, ty);
        let rendered = self.arena.render(g.skeleton);
        Ok((g, rendered))
    }

    /// Brute force, for the differential gate. Every declaration, no prefilter.
    pub fn similar_brute(
        &mut self,
        name: &str,
        top: usize,
        cfg: &IndexConfig,
    ) -> Result<Vec<(String, f32)>, String> {
        let q = self
            .id_of(name)
            .ok_or_else(|| format!("`{name}` is not in this slice"))?;
        let qt = self.level_term(q, cfg.lgg_level);
        let mut out = Vec::new();
        for i in 0..self.len() {
            let d = DeclId(i as u32);
            if d == q {
                continue;
            }
            let ct = self.level_term(d, cfg.lgg_level);
            let g = generalize(&mut self.arena, qt, ct);
            if g.common >= cfg.min_common && g.retention >= cfg.min_retention {
                out.push((self.names[i].clone(), g.retention));
            }
        }
        out.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
        out.truncate(top);
        Ok(out)
    }
}

/// The first component of a module path — `Mathlib` vs `Init` vs `Std` — and the second
/// within Mathlib, so `Mathlib.Algebra` and `Mathlib.Analysis` count as different theories.
fn module_root(m: &str) -> &str {
    let mut it = m.match_indices('.');
    let first = it.next();
    match (m.starts_with("Mathlib."), first, it.next()) {
        (true, _, Some((i, _))) => &m[..i],
        (_, Some((i, _)), _) => &m[..i],
        _ => m,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `requires` reads the *declared* hypotheses, and reads them at the right level.
    ///
    /// Two things could break it silently. It could read the erased root, where
    /// `Instances` has already holed exactly the binder domains it reports — so the
    /// InstImplicit case is paired with a class-free declaration that must come back
    /// empty, and a mixed telescope whose `Implicit` and `Default` binders must not be
    /// counted. And it could stop at the first non-instance binder, which is why the
    /// fixture puts an `Implicit` binder *before* the instance one, exactly as Lean's
    /// `{α : Type} [Preorder α]` does.
    /// `variants` must find the near miss **and** reject the decoy.
    ///
    /// Two failure modes, and only a paired fixture separates them. A query that returns
    /// every declaration finds the near miss too, so the positive case alone proves
    /// nothing; the decoy has the *same vocabulary in a different tree* and must not match,
    /// which is what makes this a structural query rather than a bag of constants.
    ///
    /// The substitution itself is asserted, not just the hit. Reporting "these are related"
    /// without saying how is the float-valued answer this query exists to replace.
    /// `adjacent` must exclude the class and still find what is just outside it.
    ///
    /// Two ways to fail silently, and the fixture blocks both. Returning class members
    /// would make the query a restatement of `equivalent`; returning nothing would make it
    /// indistinguishable from a class with no neighbours, which is the "tool that says
    /// everything is fine" this repo keeps catching. So the class has two members, the
    /// near miss is one edit from *both*, and a decoy with the same constants in a
    /// different tree must stay out.
    /// Vocabulary adjacency must be selective, or it returns the corpus.
    ///
    /// The whole design rests on document frequency doing the discriminating: sharing a
    /// constant that half the corpus mentions is not evidence, sharing a rare one is. So
    /// the fixture pairs a genuine neighbour — different *shape*, same rare constant, which
    /// is precisely the case `adjacent` cannot reach — against a declaration that shares
    /// only the ubiquitous one. If the common-only declaration comes back, the admission
    /// test is not working and the query degenerates into "everything that mentions `Eq`".
    /// A global coverage figure can hide a stratum that is not closed.
    ///
    /// This is the check the whole session argues for: the corpus below is 90% closed
    /// overall — comfortably over any floor anyone would set — while the stratum actually
    /// under study is 0% closed. If `closure_by` returned the global number, or averaged,
    /// the defect stays invisible and every query over `Phys.*` is silently unsound.
    #[test]
    fn closure_by_finds_an_unclosed_stratum_a_global_figure_hides() {
        let row = |n: &str, m: &str, stmt: &str| {
            format!(
                "{{\"name\":\"{n}\",\"kind\":\"theorem\",\"module\":\"{m}\",\
                 \"stmt\":\"{stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
            )
        };
        let mut rows = vec![
            // `Known`'s own row, so it has a signature.
            row("Known", "Math", "atlas-stmt-v1;pi(s(0),pd(b0,s(0)))"),
            // The physics stratum: heads a constant with NO row in the corpus.
            // Arguments are bound variables, so the *only* application head under test is
            // the one whose closure is in question — an earlier fixture used bare constants
            // as arguments and measured their absence instead, reading 33% globally.
            row(
                "Phys.a",
                "Phys",
                "atlas-stmt-v1;pi(s(0),a(a(c(7:Missing,0),b0),b0))",
            ),
        ];
        // Nine maths rows headed by a constant that *is* present, so the global figure is
        // dominated by them.
        for i in 0..9 {
            rows.push(row(
                &format!("Math.t{i}"),
                "Math",
                "atlas-stmt-v1;pi(s(0),a(a(c(5:Known,0),b0),b0))",
            ));
        }
        let idx = SkeletonIndex::build(&rows.join("\n"), &IndexConfig::default()).expect("build");

        let (gk, gu, _) = idx.closure(5);
        let global = gk as f64 / (gk + gu) as f64;
        let (pk, pu, worst) = idx.closure_by("Phys", 5);
        let phys = pk as f64 / (pk + pu) as f64;

        assert!(global > 0.80, "global coverage should look fine: {global}");
        assert!(
            phys < 0.50,
            "the studied stratum is not closed and must say so: {phys} (known {pk}, unknown {pu})"
        );
        assert!(
            worst.iter().any(|(n, _)| n == "Missing"),
            "must name the missing constant: {worst:?}"
        );
        // And it must not simply report every stratum as broken.
        let (mk, mu, _) = idx.closure_by("Math", 5);
        assert!(
            mk as f64 / (mk + mu) as f64 > 0.80,
            "the closed stratum must pass: known {mk}, unknown {mu}"
        );
    }

    #[test]
    fn vocabulary_adjacent_admits_the_rare_constant_and_not_the_common_one() {
        let row = |n: &str, stmt: &str| {
            format!(
                "{{\"name\":\"{n}\",\"kind\":\"theorem\",\"module\":\"M\",\
                 \"stmt\":\"{stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
            )
        };
        // `Eq` is in every row (common); `Lam` is in only two (rare).
        let mut rows = vec![
            // the class member: an application mentioning Lam
            row("cls", "atlas-stmt-v1;a(a(c(2:Eq,0),c(3:Lam,0)),c(1:z,0))"),
            // different SHAPE (a Pi, not an application) but mentions Lam — `adjacent`
            // cannot reach this and that is the point
            row(
                "neighbour",
                "atlas-stmt-v1;pi(s(0),a(a(c(2:Eq,0),c(3:Lam,0)),b0))",
            ),
        ];
        // Padding that shares only `Eq`, so `Eq`'s document frequency is high.
        for i in 0..20 {
            rows.push(row(
                &format!("common{i}"),
                &format!(
                    "atlas-stmt-v1;a(a(c(2:Eq,0),c(1:{},0)),c(1:z,0))",
                    (b'a' + i) as char
                ),
            ));
        }
        let src = rows.join("\n");
        let mut idx = SkeletonIndex::build(&src, &IndexConfig::default()).expect("build");

        let adj = idx.vocabulary_adjacent(&["cls".to_string()], 0.20, 50);
        let names: Vec<&str> = adj.iter().map(|a| a.name.as_str()).collect();
        assert!(
            names.contains(&"neighbour"),
            "the rare-constant neighbour must be found across a change of shape: {names:?}"
        );
        assert!(
            !names.iter().any(|n| n.starts_with("common")),
            "sharing only the corpus-common constant is not adjacency: {names:?}"
        );
        assert_eq!(
            adj[0].shared,
            vec!["Lam".to_string()],
            "must name what is shared"
        );
        // The class itself is never its own neighbour.
        assert!(!names.contains(&"cls"));
    }

    #[test]
    fn adjacent_excludes_the_class_and_names_the_edit() {
        let row = |n: &str, stmt: &str| {
            format!(
                "{{\"name\":\"{n}\",\"kind\":\"theorem\",\"module\":\"M\",\
                 \"stmt\":\"{stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
            )
        };
        let src = [
            row("cls_a", "atlas-stmt-v1;a(a(c(2:Eq,0),c(1:x,0)),c(1:y,0))"),
            row("cls_b", "atlas-stmt-v1;a(a(c(2:Eq,0),c(1:x,0)),c(1:y,0))"),
            row("near", "atlas-stmt-v1;a(a(c(2:Ne,0),c(1:x,0)),c(1:y,0))"),
            row("decoy", "atlas-stmt-v1;a(c(2:Eq,0),a(c(1:x,0),c(1:y,0)))"),
        ]
        .join("\n");
        let mut idx = SkeletonIndex::build(&src, &IndexConfig::default()).expect("build");
        let cls = vec!["cls_a".to_string(), "cls_b".to_string()];
        let adj = idx.adjacent(&cls, 1, 10);

        let names: Vec<&str> = adj.iter().map(|a| a.name.as_str()).collect();
        assert_eq!(
            names,
            ["near"],
            "the class itself must not come back as adjacent"
        );
        assert_eq!(
            adj[0].substitutions,
            vec![("Eq".to_string(), "Ne".to_string())],
            "the edit into the family must be named"
        );
        assert!(
            cls.contains(&adj[0].adjacent_to),
            "must cite a real class member"
        );

        // A class whose only structural neighbours are its own members has no adjacency —
        // and must say so rather than inventing one.
        let alone = idx.adjacent(&["decoy".to_string()], 1, 10);
        assert!(
            alone.is_empty(),
            "no near miss exists for the decoy: {alone:?}"
        );
    }

    #[test]
    fn variants_finds_the_one_substitution_and_rejects_the_reshuffle() {
        // `f a b` for three different (f, a, b) vocabularies over one tree, plus a decoy
        // that reuses `subject`'s constants in a different shape.
        let row = |n: &str, stmt: &str| {
            format!(
                "{{\"name\":\"{n}\",\"kind\":\"theorem\",\"module\":\"M\",\
                 \"stmt\":\"{stmt}\",\"uses_statement\":[],\"uses_proof\":[]}}"
            )
        };
        let src = [
            row("subject", "atlas-stmt-v1;a(a(c(2:Eq,0),c(1:x,0)),c(1:y,0))"),
            // one slot differs: Eq -> Ne
            row("one_sub", "atlas-stmt-v1;a(a(c(2:Ne,0),c(1:x,0)),c(1:y,0))"),
            // two slots differ
            row("two_sub", "atlas-stmt-v1;a(a(c(2:Ne,0),c(1:z,0)),c(1:y,0))"),
            // same three constants, different tree — must NOT be a variant
            row("decoy", "atlas-stmt-v1;a(c(2:Eq,0),a(c(1:x,0),c(1:y,0)))"),
        ]
        .join("\n");
        let mut idx = SkeletonIndex::build(&src, &IndexConfig::default()).expect("build");

        let v1 = idx.variants("subject", 1, 10).expect("subject exists");
        let names: Vec<&str> = v1.iter().map(|v| v.name.as_str()).collect();
        assert_eq!(
            names,
            ["one_sub"],
            "at max_subs=1, only the one-edit neighbour"
        );
        assert_eq!(
            v1[0].substitutions,
            vec![("Eq".to_string(), "Ne".to_string())],
            "the edit must be named, not merely counted"
        );

        let v2 = idx.variants("subject", 2, 10).expect("subject exists");
        let mut names2: Vec<&str> = v2.iter().map(|v| v.name.as_str()).collect();
        names2.sort_unstable();
        assert_eq!(
            names2,
            ["one_sub", "two_sub"],
            "max_subs=2 admits the two-edit one"
        );

        // The decoy shares every constant and no structure. If it ever appears here, the
        // query has degenerated into vocabulary matching.
        assert!(
            !v2.iter().any(|v| v.name == "decoy"),
            "a reshuffle of the same constants is not a variant"
        );

        assert!(idx.variants("absent", 1, 10).is_none());
    }

    #[test]
    fn requires_reports_instance_binders_and_only_those() {
        // `pi` = Implicit, `pt` = InstImplicit, `pd` = Default.
        let src = "\
{\"name\":\"withclass\",\"kind\":\"theorem\",\"module\":\"M\",\
\"stmt\":\"atlas-stmt-v1;pi(s(0),pt(a(c(8:Preorder,1,0),b0),pd(b1,a(a(a(c(2:Eq,1,0),b2),b0),b0))))\",\
\"uses_statement\":[],\"uses_proof\":[]}
{\"name\":\"noclass\",\"kind\":\"theorem\",\"module\":\"M\",\
\"stmt\":\"atlas-stmt-v1;pi(s(0),pd(b0,a(a(a(c(2:Eq,1,0),b1),b0),b0)))\",\
\"uses_statement\":[],\"uses_proof\":[]}
";
        let idx = SkeletonIndex::build(src, &IndexConfig::default()).expect("build");
        assert_eq!(
            idx.requires("withclass").as_deref(),
            Some(["Preorder".to_string()].as_slice()),
            "the InstImplicit binder's class, and not the Implicit or Default ones"
        );
        assert_eq!(
            idx.requires("noclass").as_deref(),
            Some([].as_slice()),
            "a declaration with no instance binder requires nothing — if this reports \
             something, the walk is reading the wrong binder kind"
        );
        assert_eq!(idx.requires("absent"), None);
    }

    #[test]
    fn changing_a_ranking_weight_changes_the_scorer_digest() {
        // The property the previous design could not have: the weights were literals in
        // `similar` rather than fields, so a digest over `IndexConfig` was blind to
        // exactly the constants that decide the ranking. A stored row would then claim a
        // provenance it did not have.
        let base = IndexConfig::default();
        for mutate in [
            (|c: &mut IndexConfig| c.rarity_weight = 0.6) as fn(&mut IndexConfig),
            |c: &mut IndexConfig| c.cross_weight = 0.20,
            |c: &mut IndexConfig| c.scoped_weight = 0.25,
            |c: &mut IndexConfig| c.min_retention = 0.31,
            |c: &mut IndexConfig| c.min_common = 7,
            |c: &mut IndexConfig| c.lgg_level = Level::Shape,
            |c: &mut IndexConfig| c.theorems_only = true,
            |c: &mut IndexConfig| c.source_b_at_build_level = false,
            // The work budget changes both what the index contains and how far a query
            // walks, so two configs differing only here must not share a scorer.
            |c: &mut IndexConfig| c.posting_work_budget = Some(2_000),
            // `Some(0)` is the walk-bound ablation, not `None` — the digest must keep
            // the three settings apart.
            |c: &mut IndexConfig| c.posting_work_budget = Some(0),
        ] {
            let mut other = base.clone();
            mutate(&mut other);
            assert_ne!(
                base.digest(),
                other.digest(),
                "a config that ranks differently must not share a digest"
            );
        }
    }

    #[test]
    fn the_digest_is_stable_for_the_same_config() {
        // Otherwise "same scorer" is not a decidable question and the field is decoration.
        let (a, b) = (IndexConfig::default(), IndexConfig::default());
        assert_eq!(a.digest(), b.digest());
        assert_eq!(a.digest().len(), 64, "sha256, lowercase hex");
    }

    #[test]
    fn the_recorded_factors_reproduce_the_score() {
        // Cheap invariant rather than the regression gate — `tests/golden.rs` is that,
        // because what a refactor moves is neighbour *order*, and a product recomputed
        // from its own multiplicands is an identity whatever the order did.
        let f = ScoreFactors {
            retention: 0.9,
            base: 0.9,
            rarity_boost: 1.25,
            cross_boost: 1.15,
            scoped_penalty: 0.85,
            derivative_penalty: 0.90,
            total: 0.9 * 1.25 * 1.15 * 0.85 * 0.90,
        };
        assert!(
            (f.total
                - f.base
                    * f.rarity_boost
                    * f.cross_boost
                    * f.scoped_penalty
                    * f.derivative_penalty)
                .abs()
                < 1e-6
        );
    }
}
