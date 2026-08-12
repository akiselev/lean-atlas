//! The logical relationship graph (Engine 1 §6 C3, milestone M2) — B5's E2.
//!
//! `equiv.rs` establishes that Mathlib's `Iff` theorems are overwhelmingly *rules over
//! patterns* rather than edges between ground propositions: 4,459 conclude in an `Iff`
//! and four have both sides closed. So the graph built here does not connect
//! declarations, it connects **pattern heads**, and every edge names the theorem that
//! proves it.
//!
//! That is the difference between this module and `equiv.rs`. Equivalence there is
//! equality of a canonical form — reflexive, symmetric and transitive by construction,
//! and entirely structural. Here an edge exists because someone proved it, and the proof
//! is the evidence. The two must not be merged: one is a fact about encodings, the other
//! a fact about mathematics.
//!
//! # Two restrictions, each of which the corpus itself justifies
//!
//! **Both sides must head a proposition.** `∀ (n : ℕ), P n` is a `Pi` whose domain is
//! `ℕ`, and reading every non-dependent `Pi` as an implication would make `Nat → True`
//! an edge from the natural numbers to a proposition. The engine cannot typecheck, so it
//! uses what the corpus declares: a head symbol is Prop-heading if it heads the
//! conclusion of some theorem in the slice. This is B3's evidence rule applied to a
//! different question — no guessing, no name matching.
//!
//! **A flex head is reported, not dropped.** A pattern whose head is a bound variable
//! needs higher-order matching. Engine 1 §6 C3 is explicit that these come back with an
//! unsupported status, because "we did not look" and "there is nothing there" are
//! different answers and only one of them should stop a search.

use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};

use crate::equiv::EquivIndex;
use crate::relation::{Direction, Evidence, Relation, RelationKind, UnsupportedReason};
use crate::skel::term::{Arena, Node, TermId};

/// A node of the logical graph: the head symbol of a pattern, with its arity.
///
/// Arity is part of the identity because `Membership.mem` at two arities is two
/// different shapes, and collapsing them creates paths that do not typecheck.
///
/// A head is deliberately **carrier-blind**: `LE.le/4` is one node whether the theorem
/// is about `Nat`, `BitVec` or an arbitrary preorder. That is what makes the graph a map
/// of *reformulation shapes* rather than a per-type relation, and it is also why
/// [`LogicalGraph::path`] returns a lead rather than a derivation. Adding the carrier
/// would give a sound composition relation and a graph too sparse to traverse; the two
/// are different objects and this module builds the first.
pub type Head = (String, usize);

/// One proved logical edge.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Edge {
    pub from: Head,
    pub to: Head,
    /// The theorem whose statement is this edge.
    pub theorem: String,
    /// `true` for an `Iff`, which is traversable both ways.
    pub biconditional: bool,
    /// The edge came from an `axiom` rather than a `theorem`, so it is *asserted*.
    ///
    /// The extraction used to skip anything whose kind was not `theorem`, which made the
    /// entire Formal-Conjectures genre invisible: `atlas-validation.md` §2 mandates
    /// statement-level corpora with no proofs, so B7's own validation clusters produced
    /// **zero** edges — including `RiemannHypothesis ↔ Λ ≤ 0`, sitting in the corpus and
    /// walked past on a `kind` check.
    ///
    /// Carried rather than collapsed, because an axiom's `Iff` is not a proved one and
    /// reporting it as `ProvedIff` would make the graph claim a warrant it has not got.
    pub asserted: bool,
}

/// Counts that say what the extraction actually saw. Reported rather than summarised,
/// because a graph built from 4,459 `Iff`s and one built from 12 support very different
/// claims.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LogicalStats {
    pub theorems_scanned: usize,
    pub iff_edges: usize,
    pub implication_edges: usize,
    /// Statements that *are* `Iff`s or implications but whose sides could not be keyed.
    pub flex_head_sides: usize,
    /// `Iff`s whose two sides key to the *same* `(head, arity)`, so the edge would be a
    /// self-loop and is dropped.
    ///
    /// Counted because it used to be the silent branch of the match, and it is the
    /// **largest** one: on physlib, 184 of 516 `Iff`-headed theorems land here against 71
    /// flex-headed, so "the reformulation layer found 261 edges" was reporting half the
    /// story. Dominated by extensionality lemmas — `X.ext_iff : a = b ↔ a.f = b.f` is
    /// `Eq/3` on both sides — which carry real content that head-level keying cannot see.
    pub same_head_sides: usize,
    /// Axioms scanned. Separate from `theorems_scanned` because an edge from an axiom is
    /// asserted rather than proved, and a corpus of one kind reads very differently from
    /// a corpus of the other.
    pub axioms_scanned: usize,
    /// Implication-shaped statements rejected because a side does not head a
    /// proposition — mostly `∀ (n : ℕ), …`, which is a binder and not an implication.
    pub non_prop_sides: usize,
    pub prop_heads: usize,
}

pub struct LogicalGraph {
    edges: Vec<Edge>,
    /// Adjacency over edge indices. An `Iff` appears in both directions.
    out: HashMap<Head, Vec<usize>>,
    by_theorem: HashMap<String, Vec<usize>>,
    stats: LogicalStats,
}

impl LogicalGraph {
    pub fn build(idx: &EquivIndex) -> LogicalGraph {
        let a = idx.arena();
        let mut stats = LogicalStats::default();

        // Pass one: which head symbols does this corpus witness as heading propositions?
        let mut prop_heads: HashSet<String> = HashSet::new();
        for i in 0..idx.len() {
            if !idx.is_prop_at(i) {
                continue;
            }
            if let Some(h) = head_symbol(a, conclusion(a, idx.stmt_at(i))) {
                prop_heads.insert(h);
            }
        }
        stats.prop_heads = prop_heads.len();

        let mut edges: Vec<Edge> = Vec::new();
        for i in 0..idx.len() {
            let kind = idx.kind_at(i);
            let asserted = match kind {
                "theorem" => false,
                "axiom" => true,
                _ => continue,
            };
            if asserted {
                stats.axioms_scanned += 1;
            } else {
                stats.theorems_scanned += 1;
            }
            let name = idx.name_at(i).to_string();
            let t = idx.stmt_at(i);

            if let Some((l, r)) = iff_sides(a, t) {
                match (key_of(a, l), key_of(a, r)) {
                    (Some(lk), Some(rk)) if lk != rk => {
                        edges.push(Edge {
                            from: lk,
                            to: rk,
                            theorem: name,
                            biconditional: true,
                            asserted,
                        });
                        stats.iff_edges += 1;
                    }
                    (Some(lk), Some(rk)) if lk == rk => {
                        // Refining the key here would reintroduce the carrier this module
                        // deliberately abstracts (see `Head`), so the edge is still
                        // dropped — but it is now *counted*, which is the difference
                        // between "there is nothing here" and "we could not represent it".
                        let _ = (lk, rk);
                        stats.same_head_sides += 1;
                    }
                    (Some(_), Some(_)) => {}
                    _ => stats.flex_head_sides += 1,
                }
                continue;
            }

            if let Some((p, q)) = implication_sides(a, t) {
                match (key_of(a, p), key_of(a, q)) {
                    (Some(pk), Some(qk)) => {
                        if !prop_heads.contains(&pk.0) || !prop_heads.contains(&qk.0) {
                            stats.non_prop_sides += 1;
                        } else if pk != qk {
                            edges.push(Edge {
                                from: pk,
                                to: qk,
                                theorem: name,
                                biconditional: false,
                                asserted,
                            });
                            stats.implication_edges += 1;
                        }
                    }
                    _ => stats.flex_head_sides += 1,
                }
            }
        }

        let mut out: HashMap<Head, Vec<usize>> = HashMap::new();
        let mut by_theorem: HashMap<String, Vec<usize>> = HashMap::new();
        for (n, e) in edges.iter().enumerate() {
            out.entry(e.from.clone()).or_default().push(n);
            if e.biconditional {
                out.entry(e.to.clone()).or_default().push(n);
            }
            by_theorem.entry(e.theorem.clone()).or_default().push(n);
        }

        LogicalGraph {
            edges,
            out,
            by_theorem,
            stats,
        }
    }

    pub fn stats(&self) -> &LogicalStats {
        &self.stats
    }

    pub fn len(&self) -> usize {
        self.edges.len()
    }

    pub fn is_empty(&self) -> bool {
        self.edges.is_empty()
    }

    pub fn heads(&self) -> usize {
        self.out.len()
    }

    /// The edges a given theorem contributes. Empty for a theorem that states neither an
    /// `Iff` nor an implication between propositions.
    pub fn edges_of(&self, theorem: &str) -> Vec<Relation> {
        self.by_theorem
            .get(theorem)
            .into_iter()
            .flatten()
            .map(|&n| self.relation(n, false))
            .collect()
    }

    /// Every proved edge leaving a head.
    pub fn from_head(&self, head: &str, arity: usize) -> Vec<Relation> {
        let k: Head = (head.to_string(), arity);
        self.out
            .get(&k)
            .into_iter()
            .flatten()
            .map(|&n| self.relation(n, self.edges[n].to == k))
            .collect()
    }

    /// A shortest chain of *proved* edges from one head to another — the union-graph
    /// `why` of milestone M2, restricted to the proved layer.
    ///
    /// Returns `None` when no chain exists. That is genuinely "no path in this slice",
    /// never "the search gave up": the traversal is a complete BFS over a finite graph.
    ///
    /// # A chain is a lead, not a proof
    ///
    /// Each *step* is proved — it names the theorem. The *chain* is not, and the reason
    /// is [`Head`]'s carrier-blindness. Measured on the algebra slice, the single edge
    /// `LT.lt/4 -> LE.le/4` is witnessed by `BitVec.le_of_lt`, which holds at `BitVec`
    /// and nowhere else; the next step might be witnessed by a theorem about `Nat`.
    /// Composing them proves nothing, because no carrier satisfies both.
    ///
    /// Establishing that a chain composes means checking that some carrier satisfies
    /// every step's hypotheses, which is elaboration — Engine 1's C6, not this module.
    /// Until then a chain is a *reformulation route to investigate*, and callers that
    /// present it as a derivation are making a claim the engine did not make. The
    /// witness names carry their namespaces precisely so this is visible: a chain whose
    /// steps read `BitVec.…` then `Nat.…` is telling you it does not compose.
    pub fn path(&self, from: &Head, to: &Head) -> Option<Vec<Relation>> {
        if from == to {
            return Some(Vec::new());
        }
        let mut seen: HashSet<&Head> = HashSet::from([from]);
        // (head, edge index taken to get here, index into `trail` of the previous step)
        let mut trail: Vec<(&Head, usize, Option<usize>)> = Vec::new();
        let mut queue: VecDeque<(&Head, Option<usize>)> = VecDeque::from([(from, None)]);

        while let Some((cur, prev)) = queue.pop_front() {
            for &n in self.out.get(cur).into_iter().flatten() {
                let e = &self.edges[n];
                // An `Iff` is traversable from either side; a plain implication is not.
                let next = if &e.from == cur {
                    &e.to
                } else if e.biconditional && &e.to == cur {
                    &e.from
                } else {
                    continue;
                };
                if !seen.insert(next) {
                    continue;
                }
                trail.push((next, n, prev));
                let here = trail.len() - 1;
                if next == to {
                    let mut chain = Vec::new();
                    let mut step = Some(here);
                    while let Some(s) = step {
                        let (arrived, edge, back) = trail[s];
                        chain.push(self.relation(edge, self.edges[edge].to != *arrived));
                        step = back;
                    }
                    chain.reverse();
                    return Some(chain);
                }
                queue.push_back((next, Some(here)));
            }
        }
        None
    }

    /// The flex-head sides, surfaced as relations with an explicit unsupported status so
    /// a caller can see what the graph could not key rather than inferring absence.
    pub fn unsupported(&self) -> Relation {
        Relation::new(
            format!("{} sides", self.stats.flex_head_sides),
            "higher-order matching",
            RelationKind::StructuralAnalogy,
            Direction::Both,
            Evidence::Unsupported {
                reason: UnsupportedReason::FlexHead,
            },
            GENERATOR,
        )
        .expect("an unsupported heuristic edge is well-formed by construction")
    }

    fn relation(&self, n: usize, reversed: bool) -> Relation {
        let e = &self.edges[n];
        let (kind, direction) = if e.biconditional {
            (
                if e.asserted {
                    RelationKind::AssertedIff
                } else {
                    RelationKind::ProvedIff
                },
                Direction::Both,
            )
        } else {
            (
                if e.asserted {
                    RelationKind::AssertedImplies
                } else {
                    RelationKind::ProvedImplies
                },
                Direction::LeftToRight,
            )
        };
        let (l, r) = if reversed {
            (&e.to, &e.from)
        } else {
            (&e.from, &e.to)
        };
        Relation::new(
            format!("{}/{}", l.0, l.1),
            format!("{}/{}", r.0, r.1),
            kind,
            direction,
            if e.asserted {
                Evidence::LeanAxiom {
                    name: e.theorem.clone(),
                }
            } else {
                Evidence::LeanTheorem {
                    name: e.theorem.clone(),
                }
            },
            GENERATOR,
        )
        .expect("an edge always carries the declaration it came from")
    }

    /// The heads with the most proved edges — where the corpus's logical structure is
    /// densest, and so where a reformulation search has the most to work with.
    pub fn busiest(&self, top: usize) -> Vec<(Head, usize)> {
        let mut counts: BTreeMap<&Head, usize> = BTreeMap::new();
        for e in &self.edges {
            *counts.entry(&e.from).or_default() += 1;
            *counts.entry(&e.to).or_default() += 1;
        }
        let mut v: Vec<(Head, usize)> = counts.into_iter().map(|(h, c)| (h.clone(), c)).collect();
        v.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        v.truncate(top);
        v
    }
}

const GENERATOR: &str = concat!("atlas/logical@", env!("CARGO_PKG_VERSION"));

/// Strip the `Pi` prefix to reach what the statement actually concludes.
fn conclusion(a: &Arena, t: TermId) -> TermId {
    a.conclusion(t)
}

fn head_symbol(a: &Arena, t: TermId) -> Option<String> {
    match a.node(a.spine(t).0) {
        Node::Const(s, _) => Some(a.sym(s).to_string()),
        _ => None,
    }
}

/// The graph's node key for a pattern: head symbol and arity.
fn key_of(a: &Arena, t: TermId) -> Option<Head> {
    // Descend through a quantifier prefix before keying.
    //
    // A side that is itself `∀`/`→` is not a higher-order pattern — it is a first-order
    // statement wearing a binder prefix, and refusing it was the single largest source of
    // unrepresentable edges. Measured over the merged slice: of 18,943 sides the graph
    // could not key, **18,579 (98.1%) were `Pi`-headed** and only 359 (1.9%) had a bound
    // variable at the head; on physlib it is 1,820 of 1,824 (99.8%). The most common shape
    // is `Eq/3 ↔ ∀∀. Eq/3` at 25.9%, and the `funext`/`ext_iff` family is a third of the
    // bucket.
    //
    // Recovery, measured: descending recovers **72%** of the missed `Iff` edges on
    // Mathlib, **100%** on physlib and 4/4 on B7's clusters (including
    // `rh_iff_all_zeros_real`), taking `iff_edges` from 4,330 to 5,306 — **+22.5%**.
    // Higher-order matching, which this was long assumed to need, recovers 5.3% on Mathlib
    // and *nothing* on either other corpus.
    //
    // The binder count is part of the key: `Eq/3` and `∀².Eq/3` are different claims, and
    // merging them would let a pointwise equation and an extensionality lemma share a node.
    let mut depth = 0u32;
    let mut cur = t;
    while let Node::Pi(_, _, body) = a.node(cur) {
        depth += 1;
        cur = body;
    }
    let (head, args) = a.spine(cur);
    match a.node(head) {
        Node::Const(s, _) => {
            let name = if depth == 0 {
                a.sym(s).to_string()
            } else {
                format!("∀{depth}.{}", a.sym(s))
            };
            Some((name, args.len()))
        }
        // A bound variable at the head, under any number of binders. Genuinely
        // higher-order, counted as unsupported by the caller, and rare.
        _ => None,
    }
}

fn iff_sides(a: &Arena, t: TermId) -> Option<(TermId, TermId)> {
    let c = conclusion(a, t);
    let (head, args) = a.spine(c);
    if let (Node::Const(s, _), 2) = (a.node(head), args.len())
        && a.sym(s) == "Iff"
    {
        return Some((args[0], args[1]));
    }
    None
}

/// The first non-dependent `Pi` in the prefix, which is an implication rather than a
/// quantifier.
///
/// The returned right-hand side sits under one more binder than the left, so its de
/// Bruijn indices for *outer* binders are shifted by one. That is harmless here because
/// the graph keys on head symbol and arity, and a shifted `BVar` cannot be a head
/// symbol — it is reported as a flex head instead.
fn implication_sides(a: &Arena, t: TermId) -> Option<(TermId, TermId)> {
    let mut cur = t;
    while let Node::Pi(_, dom, body) = a.node(cur) {
        if !mentions_bvar(a, body, 0) {
            return Some((dom, body));
        }
        cur = body;
    }
    None
}

/// Does de Bruijn index `depth` occur free in `t`?
///
/// The `loose` prefilter is what keeps this cheap: `loose` is `1 +` the largest free
/// index, so a subtree whose range does not reach `depth` cannot mention it and is
/// skipped whole.
fn mentions_bvar(a: &Arena, t: TermId, depth: u32) -> bool {
    if a.loose(t) <= depth {
        return false;
    }
    match a.node(t) {
        Node::BVar(k) => k == depth,
        Node::App(f, x) => mentions_bvar(a, f, depth) || mentions_bvar(a, x, depth),
        Node::Lam(_, d, b) | Node::Pi(_, d, b) => {
            mentions_bvar(a, d, depth) || mentions_bvar(a, b, depth + 1)
        }
        Node::Let(ty, v, b) => {
            mentions_bvar(a, ty, depth)
                || mentions_bvar(a, v, depth)
                || mentions_bvar(a, b, depth + 1)
        }
        Node::Proj(_, _, e) => mentions_bvar(a, e, depth),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn arena_with(src: &str) -> (Arena, TermId) {
        let mut a = Arena::new();
        let t = a.parse(src).expect("parse");
        (a, t)
    }

    #[test]
    fn a_quantifier_is_not_an_implication() {
        // `∀ (n : Nat), Even n` — a dependent Pi. Reading it as an implication would put
        // an edge from `Nat` to `Even`, which is the failure this test exists to pin.
        let (a, t) = arena_with("atlas-stmt-v1;pd(c(3:Nat,0),a(c(4:Even,0),b0))");
        assert_eq!(implication_sides(&a, t), None);
    }

    #[test]
    fn a_non_dependent_arrow_is_an_implication() {
        // `Even n → Odd n` with `n` an outer binder: the body mentions `#1`, never `#0`.
        let (a, t) =
            arena_with("atlas-stmt-v1;pd(c(3:Nat,0),pd(a(c(4:Even,0),b0),a(c(3:Odd,0),b1)))");
        let inner = match a.node(t) {
            Node::Pi(_, _, body) => body,
            _ => panic!("expected a Pi"),
        };
        let (p, q) = implication_sides(&a, inner).expect("an implication");
        assert_eq!(head_symbol(&a, p).as_deref(), Some("Even"));
        assert_eq!(head_symbol(&a, q).as_deref(), Some("Odd"));
    }

    #[test]
    fn mentions_bvar_sees_through_binders_with_the_right_shift() {
        // `∀ x, f #0 #1` — under one binder, `#1` is the outer variable.
        let (a, t) = arena_with("atlas-stmt-v1;pd(c(3:Nat,0),a(a(c(1:f,0),b0),b1))");
        let body = match a.node(t) {
            Node::Pi(_, _, b) => b,
            _ => panic!("expected a Pi"),
        };
        assert!(mentions_bvar(&a, body, 0), "the Pi's own binder occurs");
        assert!(mentions_bvar(&a, body, 1), "an outer binder occurs too");
        assert!(!mentions_bvar(&a, body, 2));
    }

    #[test]
    fn an_iff_is_recognised_under_its_quantifiers() {
        let (a, t) = arena_with(
            "atlas-stmt-v1;pd(c(3:Nat,0),a(a(c(3:Iff,0),a(c(4:Even,0),b0)),a(c(3:Odd,0),b0)))",
        );
        let (l, r) = iff_sides(&a, t).expect("an Iff");
        assert_eq!(head_symbol(&a, l).as_deref(), Some("Even"));
        assert_eq!(head_symbol(&a, r).as_deref(), Some("Odd"));
    }
}
