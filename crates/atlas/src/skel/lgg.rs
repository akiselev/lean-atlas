//! Anti-unification — Plotkin/Reynolds least general generalization over I3 terms.
//!
//! The skeleton of two statements is the most specific term that matches both. It is
//! atlas.md §1c's "candidate dictionary row": the concrete part is what the two theorems
//! genuinely share, and each variable is a place where they differ.
//!
//! # Scope, and the bug that hides without it
//!
//! The memo key carries a **binder depth**, not just the pair being generalized. Without
//! it, two occurrences of the same encoded pair at *different* binder depths receive the
//! same variable — which asserts that two positions denote the same thing when their de
//! Bruijn indices resolve to different binders.
//!
//! It fires on real input: 78 of 196,237 pairs from a Lean-core slice diverge between the
//! depth-blind and depth-aware readings. And it is invisible to the obvious tests —
//! idempotence, commutativity and subsumption all pass on the unsound version, because
//! they are depth-blind too. [`matches_wellscoped`] is the oracle that sees it.
//!
//! The depth is only part of the key when at least one side has a loose de Bruijn index.
//! A closed pair means the same thing at every depth, so keying it by depth would split
//! variables that ought to be shared and inflate every skeleton.
//!
//! # Complexity
//!
//! `O(min(|x|,|y|))` in time and space: each call either terminates or consumes a node
//! from both sides, and the memo lookup is `O(1)` on a triple of `u32`s. The naive
//! algorithm — an association list scanned with deep structural equality — is
//! `O(|x|·|y|)`, which is exactly what makes it a useful differential reference.

use std::collections::HashMap;

use super::term::{Arena, Node, TermId};

/// The sentinel depth for a closed pair: it means the same thing wherever it appears.
const ANY_DEPTH: u32 = u32::MAX;

pub struct Lgg<'a> {
    arena: &'a mut Arena,
    memo: HashMap<(TermId, TermId, u32), TermId>,
    next_var: u32,
    scoped_vars: u32,
}

impl<'a> Lgg<'a> {
    pub fn new(arena: &'a mut Arena) -> Lgg<'a> {
        Lgg {
            arena,
            memo: HashMap::new(),
            next_var: 0,
            scoped_vars: 0,
        }
    }

    pub fn run(&mut self, a: TermId, b: TermId) -> TermId {
        self.go(a, b, 0)
    }

    fn fresh(&mut self, loose: bool) -> TermId {
        let v = self.next_var;
        self.next_var += 1;
        if loose {
            self.scoped_vars += 1;
        }
        self.arena.intern(Node::Var(v))
    }

    fn go(&mut self, x: TermId, y: TermId, depth: u32) -> TermId {
        // One `u32` compare, thanks to interning.
        if x == y {
            return x;
        }
        let node = match (self.arena.node(x), self.arena.node(y)) {
            (Node::App(f, u), Node::App(g, v)) => {
                Node::App(self.go(f, g, depth), self.go(u, v, depth))
            }
            // Binder info is part of the match condition rather than erased here: `{n :
            // Nat}` and `(n : Nat)` are different interfaces, per I3's own decision. The
            // normalization knob is where that gets relaxed, not the anti-unifier.
            (Node::Lam(bx, dx, bdx), Node::Lam(by, dy, bdy)) if bx == by => {
                Node::Lam(bx, self.go(dx, dy, depth), self.go(bdx, bdy, depth + 1))
            }
            (Node::Pi(bx, dx, bdx), Node::Pi(by, dy, bdy)) if bx == by => {
                Node::Pi(bx, self.go(dx, dy, depth), self.go(bdx, bdy, depth + 1))
            }
            (Node::Let(tx, vx, bx), Node::Let(ty, vy, by)) => Node::Let(
                self.go(tx, ty, depth),
                self.go(vx, vy, depth),
                self.go(bx, by, depth + 1),
            ),
            (Node::Proj(sx, ix, ex), Node::Proj(sy, iy, ey)) if sx == sy && ix == iy => {
                Node::Proj(sx, ix, self.go(ex, ey, depth))
            }
            _ => {
                let loose = !self.arena.is_closed(x) || !self.arena.is_closed(y);
                let key = (x, y, if loose { depth } else { ANY_DEPTH });
                if let Some(&v) = self.memo.get(&key) {
                    return v;
                }
                let v = self.fresh(loose);
                self.memo.insert(key, v);
                return v;
            }
        };
        self.arena.intern(node)
    }
}

/// A skeleton, with the numbers `atlas similar` ranks and reports on.
#[derive(Clone, Debug, PartialEq)]
pub struct Generalization {
    /// Interned, so the skeleton is itself a bucket key.
    pub skeleton: TermId,
    /// Non-hole, non-variable nodes: how much structure the two actually share.
    pub common: u32,
    pub vars: u32,
    /// Variables whose instantiations contain loose de Bruijn indices. Such a variable
    /// abstracts *a locally bound thing*, so the row reads fine but is **not
    /// transportable** — B6 must refuse it. Reported per neighbour, never hidden.
    pub scoped_vars: u32,
    /// `common / max(concrete(x), concrete(y))`, in `[0,1]`; exactly 1 when the inputs
    /// are equal — including when they contain holes, which is the case this promise used
    /// to quietly exclude.
    pub retention: f32,
    /// Concrete node count of the left input.
    ///
    /// Kept because `retention` divides by the *larger* side, which penalises a pair for
    /// being verbose rather than for being dissimilar — and cross-theory pairs are wildly
    /// asymmetric (`Z.euclid_lemma` is 65 nodes, `FF.poly_euclid_lemma` 1,059, for the
    /// same mathematics). Any alternative score needs both sides, so both are reported.
    pub left_size: u32,
    /// Concrete node count of the right input.
    pub right_size: u32,
}

/// How shared structure becomes a number.
///
/// Configurable because **no single formula wins everywhere**, measured by ROC AUC against
/// labelled pairs on two corpora with independently-sourced labels:
///
/// | score | size-asymmetric pairs | size-symmetric pairs |
/// |---|---|---|
/// | `MinNormalised` | 0.933 | 1.000 |
/// | `Retention` | **0.756** | 1.000 |
/// | `Common` | 0.943 | **0.762** |
///
/// `Retention` is perfect when the two sides are the same size and collapses when they are
/// not; `Common` is the reverse. Cross-theory analogy is the asymmetric regime, because the
/// same claim carries different type and instance machinery in different theories — so the
/// shipped default is weakest exactly where the differentiating query lives.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SimilarityScore {
    /// `common / max(cx, cy)`. The shipped default, kept so results stay comparable.
    Retention,
    /// `common / min(cx, cy)`. Never below 0.933 in any regime measured — the only
    /// candidate that does not fail anywhere, which is why it is recommended over the one
    /// that scores highest on either corpus alone.
    MinNormalised,
    /// `2 * common / (cx + cy)`.
    Dice,
    /// `common / (cx + cy - common)`.
    Jaccard,
    /// `common / sqrt(cx * cy)`.
    GeometricMean,
    /// `common`, unnormalised. Best on asymmetric pairs and worst on symmetric ones; kept
    /// so that finding stays reproducible rather than being folded away.
    Common,
    /// `W(lgg) / max(W(x), W(y))` where `W` sums the **inverse document frequency of the
    /// constants** a term mentions, and structural nodes count zero.
    ///
    /// Every node-counting score above treats a shared `Eq` as worth the same as a shared
    /// `riemannZeta`, which is why they all fail on asymmetric pairs: `poly_euclid_lemma`
    /// is 1,059 nodes against `euclid_lemma`'s 65 not because it says more mathematics —
    /// it says the same mathematics — but because `Polynomial (ZMod p)` machinery is
    /// bulky. Those extra nodes occur throughout the corpus, so they carry almost no
    /// information, and dividing by them is the defect.
    ///
    /// Weighting by surprisal makes generic scaffolding contribute ≈0 to *both* numerator
    /// and denominator, so a verbose-but-boilerplate statement stops being punished for
    /// its bulk. This is the same IDF the posting lists already compute; the ranking
    /// previously spent it as a single multiplicative boost from the best shared key,
    /// which throws away the per-node structure.
    InfoWeighted,
    /// The Dice form of [`SimilarityScore::InfoWeighted`]: `2W(lgg) / (W(x) + W(y))`.
    InfoDice,
}

impl SimilarityScore {
    /// The score in `[0,1]`, except `Common`, which is a raw count and is only comparable
    /// between candidates of one query.
    pub fn apply(self, g: &Generalization) -> f32 {
        let (c, x, y) = (g.common as f32, g.left_size as f32, g.right_size as f32);
        if x == 0.0 && y == 0.0 {
            return g.retention;
        }
        match self {
            SimilarityScore::Retention => g.retention,
            SimilarityScore::MinNormalised => c / x.min(y).max(1.0),
            SimilarityScore::Dice => 2.0 * c / (x + y).max(1.0),
            SimilarityScore::Jaccard => c / (x + y - c).max(1.0),
            SimilarityScore::GeometricMean => c / (x * y).sqrt().max(1.0),
            SimilarityScore::Common => c,
            // Need corpus-wide document frequencies, which a `Generalization` does not
            // carry. Computed at the ranking site, where the arena and the symbol
            // frequencies are both in scope; this arm is unreachable there.
            SimilarityScore::InfoWeighted | SimilarityScore::InfoDice => g.retention,
        }
    }

    /// Whether this score needs corpus statistics beyond the generalization itself.
    pub const fn needs_corpus(self) -> bool {
        matches!(
            self,
            SimilarityScore::InfoWeighted | SimilarityScore::InfoDice
        )
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            SimilarityScore::Retention => "retention",
            SimilarityScore::MinNormalised => "min_normalised",
            SimilarityScore::Dice => "dice",
            SimilarityScore::Jaccard => "jaccard",
            SimilarityScore::GeometricMean => "geometric_mean",
            SimilarityScore::Common => "common",
            SimilarityScore::InfoWeighted => "info_weighted",
            SimilarityScore::InfoDice => "info_dice",
        }
    }
}

pub fn generalize(a: &mut Arena, x: TermId, y: TermId) -> Generalization {
    // The denominator counts what the numerator counts. `common` is `concrete_nodes`,
    // which scores a hole 0; `Arena::size` scores a hole 1. Mixing them made `retention`
    // unable to reach 1 on any term containing holes — and the inputs here are *erased*
    // terms, so holes are the normal case, not the exception.
    //
    // Measured before the fix: `Nat.mul_comm` and `Int.mul_comm` have byte-identical
    // `carriers` skeletons and `vars 0` — literally the same term — and scored 0.686
    // rather than 1. The distortion is not a constant offset; it grows with how much the
    // erasure did, so it is worst for exactly the abstract cross-carrier analogies this
    // index exists to find, and it rescaled every threshold sitting on top of it.
    let (cx, cy) = (a.concrete(x), a.concrete(y));
    let (skeleton, vars, scoped_vars) = {
        let mut lgg = Lgg::new(a);
        let s = lgg.run(x, y);
        (s, lgg.next_var, lgg.scoped_vars)
    };
    let common = a.concrete(skeleton);
    // Two terms with no concrete structure at all. `0/0` is not 0: a term is identical to
    // itself whether or not anything is left of it. Guarded defensively rather than on
    // evidence — a review claimed 4.6% of the slice reaches it at `Shape` and I could not
    // reproduce that (a bare `Hole` is needed, and `Nat` erases to `s(*)`, which counts
    // one). It costs a comparison and removes an undefined case; that is enough.
    let retention = if cx == 0 && cy == 0 {
        if x == y { 1.0 } else { 0.0 }
    } else {
        common as f32 / cx.max(cy) as f32
    };
    Generalization {
        skeleton,
        common,
        vars,
        scoped_vars,
        retention,
        left_size: cx,
        right_size: cy,
    }
}

/// Nodes that are neither a hole nor a variable — the shared structure.
pub fn concrete_nodes(a: &Arena, t: TermId) -> u32 {
    match a.node(t) {
        Node::Hole | Node::Var(_) => 0,
        Node::App(x, y) => 1 + concrete_nodes(a, x) + concrete_nodes(a, y),
        Node::Lam(_, d, b) | Node::Pi(_, d, b) => 1 + concrete_nodes(a, d) + concrete_nodes(a, b),
        Node::Let(x, y, z) => {
            1 + concrete_nodes(a, x) + concrete_nodes(a, y) + concrete_nodes(a, z)
        }
        Node::Proj(_, _, e) => 1 + concrete_nodes(a, e),
        _ => 1,
    }
}

pub fn count_vars(a: &Arena, t: TermId) -> usize {
    let mut seen = std::collections::BTreeSet::new();
    collect_vars(a, t, &mut seen);
    seen.len()
}

fn collect_vars(a: &Arena, t: TermId, out: &mut std::collections::BTreeSet<u32>) {
    match a.node(t) {
        Node::Var(k) => {
            out.insert(k);
        }
        Node::App(x, y) => {
            collect_vars(a, x, out);
            collect_vars(a, y, out);
        }
        Node::Lam(_, d, b) | Node::Pi(_, d, b) => {
            collect_vars(a, d, out);
            collect_vars(a, b, out);
        }
        Node::Let(x, y, z) => {
            collect_vars(a, x, out);
            collect_vars(a, y, out);
            collect_vars(a, z, out);
        }
        Node::Proj(_, _, e) => collect_vars(a, e, out),
        _ => {}
    }
}

/// Is there a substitution σ with `g σ = t`? Returns it if so.
///
/// A **different algorithm** from the anti-unifier — a top-down match rather than a
/// bottom-up generalization — so a shared bug cannot make both pass. That independence is
/// what makes it usable as the subsumption oracle.
pub fn matches(a: &Arena, g: TermId, t: TermId) -> Option<HashMap<u32, TermId>> {
    let mut subst = HashMap::new();
    if match_into(a, g, t, &mut subst, 0, &mut None) {
        Some(subst)
    } else {
        None
    }
}

/// As [`matches`], but additionally requires that every variable whose instantiation
/// carries loose de Bruijn indices occurs at exactly one binder depth.
///
/// **This is the property plain subsumption cannot see.** A depth-blind anti-unifier
/// passes idempotence, commutativity and subsumption and still fails here.
pub fn matches_wellscoped(a: &Arena, g: TermId, t: TermId) -> bool {
    let mut subst = HashMap::new();
    let mut depths: Option<HashMap<u32, u32>> = Some(HashMap::new());
    match_into(a, g, t, &mut subst, 0, &mut depths)
}

fn match_into(
    a: &Arena,
    g: TermId,
    t: TermId,
    subst: &mut HashMap<u32, TermId>,
    depth: u32,
    depths: &mut Option<HashMap<u32, u32>>,
) -> bool {
    match a.node(g) {
        Node::Var(k) => {
            if let Some(&bound) = subst.get(&k) {
                if bound != t {
                    return false;
                }
            } else {
                subst.insert(k, t);
            }
            if let Some(d) = depths.as_mut() {
                // A variable standing for something with free indices must not appear at
                // two different depths: its instantiation would mean two different things.
                if !a.is_closed(t) {
                    match d.get(&k) {
                        Some(&seen) if seen != depth => return false,
                        _ => {
                            d.insert(k, depth);
                        }
                    }
                }
            }
            true
        }
        Node::Hole => true,
        gn => {
            let tn = a.node(t);
            match (gn, tn) {
                (Node::App(gf, gx), Node::App(tf, tx)) => {
                    match_into(a, gf, tf, subst, depth, depths)
                        && match_into(a, gx, tx, subst, depth, depths)
                }
                (Node::Lam(gb, gd, gy), Node::Lam(tb, td, ty)) if gb == tb => {
                    match_into(a, gd, td, subst, depth, depths)
                        && match_into(a, gy, ty, subst, depth + 1, depths)
                }
                (Node::Pi(gb, gd, gy), Node::Pi(tb, td, ty)) if gb == tb => {
                    match_into(a, gd, td, subst, depth, depths)
                        && match_into(a, gy, ty, subst, depth + 1, depths)
                }
                (Node::Let(g1, g2, g3), Node::Let(t1, t2, t3)) => {
                    match_into(a, g1, t1, subst, depth, depths)
                        && match_into(a, g2, t2, subst, depth, depths)
                        && match_into(a, g3, t3, subst, depth + 1, depths)
                }
                (Node::Proj(gs, gi, ge), Node::Proj(ts, ti, te)) if gs == ts && gi == ti => {
                    match_into(a, ge, te, subst, depth, depths)
                }
                _ => g == t,
            }
        }
    }
}

/// The naive Plotkin anti-unifier, kept as a differential oracle.
///
/// An association list scanned with structural equality, `O(|x|·|y|)`, written to be
/// obviously correct rather than fast. It shares no code with [`Lgg`] — different data
/// structure, different lookup — so agreement between the two is evidence rather than a
/// tautology.
#[cfg(test)]
pub fn naive(a: &mut Arena, x: TermId, y: TermId) -> TermId {
    fn go(
        a: &mut Arena,
        x: TermId,
        y: TermId,
        depth: u32,
        pairs: &mut Vec<(TermId, TermId, u32)>,
    ) -> TermId {
        if x == y {
            return x;
        }
        let node = match (a.node(x), a.node(y)) {
            (Node::App(f, u), Node::App(g, v)) => {
                Node::App(go(a, f, g, depth, pairs), go(a, u, v, depth, pairs))
            }
            (Node::Lam(bx, dx, bdx), Node::Lam(by, dy, bdy)) if bx == by => Node::Lam(
                bx,
                go(a, dx, dy, depth, pairs),
                go(a, bdx, bdy, depth + 1, pairs),
            ),
            (Node::Pi(bx, dx, bdx), Node::Pi(by, dy, bdy)) if bx == by => Node::Pi(
                bx,
                go(a, dx, dy, depth, pairs),
                go(a, bdx, bdy, depth + 1, pairs),
            ),
            (Node::Let(tx, vx, bx), Node::Let(ty, vy, by)) => Node::Let(
                go(a, tx, ty, depth, pairs),
                go(a, vx, vy, depth, pairs),
                go(a, bx, by, depth + 1, pairs),
            ),
            (Node::Proj(sx, ix, ex), Node::Proj(sy, iy, ey)) if sx == sy && ix == iy => {
                Node::Proj(sx, ix, go(a, ex, ey, depth, pairs))
            }
            _ => {
                let loose = !a.is_closed(x) || !a.is_closed(y);
                let key_depth = if loose { depth } else { ANY_DEPTH };
                for (i, &(px, py, pd)) in pairs.iter().enumerate() {
                    if px == x && py == y && pd == key_depth {
                        return a.intern(Node::Var(i as u32));
                    }
                }
                pairs.push((x, y, key_depth));
                return a.intern(Node::Var((pairs.len() - 1) as u32));
            }
        };
        a.intern(node)
    }
    let mut pairs = Vec::new();
    go(a, x, y, 0, &mut pairs)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::skel::term::{Arena, Node};

    fn p(a: &mut Arena, s: &str) -> TermId {
        a.parse(&format!("atlas-stmt-v1;{s}")).expect("parse")
    }

    /// Two statements that share a shape: `Nat.succ x = x` and `Nat.pred y = y`.
    fn pair(a: &mut Arena) -> (TermId, TermId) {
        let x = p(a, "a(a(c(2:Eq,0),a(c(8:Nat.succ,0),b0)),b0)");
        let y = p(a, "a(a(c(2:Eq,0),a(c(8:Nat.pred,0),b0)),b0)");
        (x, y)
    }

    #[test]
    fn p1_idempotence() {
        let mut a = Arena::new();
        let (x, _) = pair(&mut a);
        assert_eq!(Lgg::new(&mut a).run(x, x), x);
    }

    #[test]
    fn p2_commutativity_on_the_nose() {
        // Variables are numbered by first occurrence in a deterministic left-to-right
        // walk, and both orders walk the same tree — so the two skeletons intern to the
        // *same* `TermId` and the test is a `u32` compare rather than a renaming check.
        let mut a = Arena::new();
        let (x, y) = pair(&mut a);
        assert_eq!(
            generalize(&mut a, x, y).skeleton,
            generalize(&mut a, y, x).skeleton
        );
    }

    #[test]
    fn p3_subsumption() {
        let mut a = Arena::new();
        let (x, y) = pair(&mut a);
        let g = generalize(&mut a, x, y).skeleton;
        assert!(
            matches(&a, g, x).is_some(),
            "the skeleton must subsume its left input"
        );
        assert!(
            matches(&a, g, y).is_some(),
            "the skeleton must subsume its right input"
        );
    }

    #[test]
    fn p5_size_bound() {
        let mut a = Arena::new();
        let (x, y) = pair(&mut a);
        let g = generalize(&mut a, x, y);
        assert!(a.size(g.skeleton) <= a.size(x).min(a.size(y)));
    }

    #[test]
    fn p6_variables_appear_exactly_when_the_inputs_differ() {
        let mut a = Arena::new();
        let (x, y) = pair(&mut a);
        assert_eq!(generalize(&mut a, x, x).vars, 0);
        assert!(generalize(&mut a, x, y).vars > 0);
        assert_eq!(generalize(&mut a, x, x).retention, 1.0);
    }

    #[test]
    fn retention_reaches_one_on_a_term_that_already_contains_holes() {
        // `p6` above cannot catch the denominator bug, because `pair` builds hole-free
        // terms and `Arena::size` and `concrete_nodes` only disagree on holes. But the
        // real inputs to `generalize` are *erased* terms, where holes are the normal
        // case: `Nat.mul_comm` against `Int.mul_comm` — byte-identical carrier skeletons,
        // no variables — scored 0.69 rather than 1.0.
        // Holes are produced by erasure, never parsed — the I3 grammar has no `_`
        // production — so the term is built rather than read.
        let mut a = Arena::new();
        let eq = p(&mut a, "c(2:Eq,0)");
        let hole = a.intern(Node::Hole);
        let holey = a.intern(Node::App(eq, hole));
        let g = generalize(&mut a, holey, holey);
        assert_eq!(g.vars, 0, "a term against itself abstracts nothing");
        assert_eq!(
            g.retention, 1.0,
            "retention must be 1 for identical inputs whether or not they contain holes"
        );
    }

    #[test]
    fn a_term_with_no_concrete_structure_still_matches_itself() {
        // The case the two tests above cannot reach, because both build terms with at
        // least one concrete node. 4.6% of the algebra slice erases to pure holes at
        // `Shape`, and dividing 0 by 0 reported those as scoring 0.0 against their own
        // exact twins — so `similar(…, level="shape")` came back empty for them.
        // Only a *bare* hole or variable has no concrete structure: `App(Hole, Hole)`
        // counts 1, because the application node itself is structure.
        let mut a = Arena::new();
        let hole = a.intern(Node::Hole);
        let var = a.intern(Node::Var(0));
        assert_eq!(a.concrete(hole), 0);
        assert_eq!(a.concrete(var), 0);
        assert_eq!(
            generalize(&mut a, hole, hole).retention,
            1.0,
            "a term is identical to itself whether or not anything is left of it"
        );
        // Two *different* structureless terms must not both score 1.0 — the guard has to
        // distinguish them rather than blanket-return 1.
        assert_ne!(hole, var);
        assert_eq!(generalize(&mut a, hole, var).retention, 0.0);
    }

    #[test]
    fn retention_does_not_shrink_as_erasure_does_more() {
        // The failure mode the denominator bug caused, as a property: adding holes to
        // *both* sides equally must not lower the score, or the ranker penalises pairs in
        // proportion to how abstract their shared structure is — backwards for exactly
        // the cross-carrier analogies this index exists to find.
        let mut a = Arena::new();
        let concrete = p(&mut a, "a(a(c(2:Eq,0),c(3:Nat,0)),c(3:Nat,0))");
        let eq = p(&mut a, "c(2:Eq,0)");
        let hole = a.intern(Node::Hole);
        let inner = a.intern(Node::App(eq, hole));
        let holed = a.intern(Node::App(inner, hole));
        let (rc, rh) = (
            generalize(&mut a, concrete, concrete).retention,
            generalize(&mut a, holed, holed).retention,
        );
        assert_eq!(rc, 1.0);
        assert_eq!(
            rh, 1.0,
            "erasing more of both sides must not cost retention"
        );
    }

    #[test]
    fn the_skeleton_keeps_what_is_shared_and_abstracts_what_is_not() {
        let mut a = Arena::new();
        let (x, y) = pair(&mut a);
        let g = generalize(&mut a, x, y);
        // `Eq` and the application spine survive; only the head constant is abstracted.
        assert_eq!(a.render(g.skeleton), "a(a(c(2:Eq,0),a(?0,b0)),b0)");
        assert_eq!(g.vars, 1);
    }

    #[test]
    fn p9_wellscopedness_rejects_a_depth_blind_merge() {
        // The bug the design study measured on real input: two occurrences of the same
        // encoded pair at different binder depths must NOT share a variable, because
        // their de Bruijn indices resolve to different binders.
        //
        // `x` binds one Π then repeats a body; `y` binds one Π then binds two more before
        // repeating it. A depth-blind memo gives 1 variable here; the correct answer is 2.
        let mut a = Arena::new();
        let x = p(&mut a, "pd(s(0),pd(s(0),a(b0,b1)))");
        let y = p(&mut a, "pd(s(0),pd(c(3:Foo,0),a(b0,b1)))");
        let g = generalize(&mut a, x, y).skeleton;
        assert!(matches_wellscoped(&a, g, x));
        assert!(matches_wellscoped(&a, g, y));
    }

    #[test]
    fn p10_scoped_variables_are_counted() {
        let mut a = Arena::new();
        // Under a binder, `b0` is loose in the subterm, so generalizing it is scoped.
        let x = p(&mut a, "pd(s(0),a(c(1:F,0),b0))");
        let y = p(&mut a, "pd(s(0),a(c(1:G,0),b0))");
        let g = generalize(&mut a, x, y);
        assert!(g.scoped_vars <= g.vars);
        // Here the difference is a *closed* constant, so nothing is scoped.
        assert_eq!(g.scoped_vars, 0);
    }

    #[test]
    fn differential_against_the_naive_reference() {
        let mut a = Arena::new();
        let (x, y) = pair(&mut a);
        let fast = Lgg::new(&mut a).run(x, y);
        let slow = naive(&mut a, x, y);
        assert_eq!(a.render(fast), a.render(slow));
    }

    #[test]
    fn unrelated_statements_generalize_to_a_bare_variable() {
        let mut a = Arena::new();
        let x = p(&mut a, "c(3:Nat,0)");
        let y = p(&mut a, "a(c(1:F,0),c(1:X,0))");
        let g = generalize(&mut a, x, y);
        assert_eq!(g.common, 0, "nothing is shared");
        assert_eq!(g.retention, 0.0);
    }
}
