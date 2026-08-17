//! The normalization-level knob (B4) — precision traded for recall, in stages.
//!
//! Gauthier–Kaliszyk's hierarchy for matching concepts across HOL libraries, adapted. Two
//! differences from theirs, both because the Atlas reads an *elaborated* `Expr` rather than
//! surface text: the levels are a **chain**, so `erase(erase(t, ℓ), ℓ') = erase(t, ℓ')`
//! whenever `ℓ ≤ ℓ'` and the buckets provably refine; and the level is **reported per
//! neighbour**, so "how much did I have to squint" is output rather than configuration.
//!
//! | level | erases (cumulatively) | why |
//! |---|---|---|
//! | `Exact` | nothing | precision 1, recall ≈ 0 |
//! | `Presentation` | universe structure → `Star` (a `Const`'s level-list *length* survives, so arity does); `StrictImplicit` merges into `Implicit`; `OfNat.ofNat T k inst` → the literal `k` | the literal canonicalisation `statement-hash.md` refused for *identity* and which is right for *analogy* |
//! | `Instances` | every argument in an `InstImplicit` position of its head's signature, and every `InstImplicit` binder's domain | `Nat.add_comm` loses `instHAdd`/`instAddNat` and becomes comparable with `Int.add_comm` |
//! | `Carriers` | every argument in an `Implicit` position whose declared domain is a sort **other than `Sort 0`**, and the corresponding binder domains | the type a statement is *about*, as opposed to the propositions it is about |
//! | `Shape` | every `Const`, `NatLit` and `StrLit`; binder info collapses | application structure, binder nesting and de Bruijn indices survive; nothing else |
//!
//! # Three rules that look like details and are not
//!
//! **Binders are replaced, never deleted.** Deleting an instance binder shifts every de
//! Bruijn index above it and silently changes the statement into a different one.
//!
//! **`Prop` is not a carrier.** The naive Carriers rule holes every implicit sort-domain
//! argument, which collapses `and_comm` to a statement about two erased propositions —
//! the things it is *about*, gone. The rule is: implicit, **and** the domain is a sort,
//! **and** that sort is not `Sort 0`.
//!
//! **`outParam` hides a sort.** `HAdd.hAdd`'s output binder has domain
//! `outParam (Sort u)` — an *application*, so a naive "is the domain a sort" test says no,
//! leaves `γ` concrete while erasing `α` and `β`, and produces asymmetric nonsense.
//! Unwrap `outParam`/`semiOutParam` before testing.

use std::collections::{HashMap, HashSet};

use super::term::{Arena, BinderInfo, LevelNode, LevelsId, Node, SymId, TermId};

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug, Hash)]
#[repr(u8)]
pub enum Level {
    Exact = 0,
    Presentation = 1,
    Instances = 2,
    Carriers = 3,
    Shape = 4,
}

impl Level {
    pub const ALL: [Level; 5] = [
        Level::Exact,
        Level::Presentation,
        Level::Instances,
        Level::Carriers,
        Level::Shape,
    ];

    pub fn parse(s: &str) -> Option<Level> {
        Some(match s {
            "exact" => Level::Exact,
            "presentation" => Level::Presentation,
            "instances" => Level::Instances,
            "carriers" => Level::Carriers,
            "shape" => Level::Shape,
            _ => return None,
        })
    }

    pub fn name(self) -> &'static str {
        match self {
            Level::Exact => "exact",
            Level::Presentation => "presentation",
            Level::Instances => "instances",
            Level::Carriers => "carriers",
            Level::Shape => "shape",
        }
    }
}

/// What one argument position of a constant declares about itself.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct ArgKind {
    pub binder: BinderInfo,
    /// Implicit, domain is a sort, and that sort is not `Sort 0`.
    pub is_carrier: bool,
}

/// Per-constant argument interfaces, read off B1's own rows.
///
/// No new extraction is needed: every constant is itself a row, and its statement's
/// leading Π-telescope *is* its interface.
pub struct Signatures {
    table: HashMap<SymId, Box<[ArgKind]>>,
    /// Constants whose fully-applied result is a non-`Prop` sort — i.e. type formers.
    /// `Nat` is one (`Nat : Type`); `Eq a b` is not (`… : Prop`). This is what lets an
    /// *explicit* binder's domain be recognised as a concrete carrier without a
    /// typechecker: the constant's own row says what it produces.
    type_formers: HashSet<SymId>,
    /// Constants with no row in the slice. Reported by the index rather than swallowed —
    /// a spine whose head is unknown degrades to `Presentation` behaviour, and knowing how
    /// often that happens is the difference between a measurement and a guess.
    pub missing: HashSet<SymId>,
}

impl Signatures {
    pub fn from_rows(a: &Arena, rows: impl Iterator<Item = (SymId, TermId)>) -> Signatures {
        let mut table = HashMap::new();
        let mut type_formers = HashSet::new();
        for (sym, ty) in rows {
            table.insert(sym, telescope_kinds(a, ty));
            if produces_nonprop_sort(a, ty) {
                type_formers.insert(sym);
            }
        }
        Signatures {
            table,
            type_formers,
            missing: HashSet::new(),
        }
    }

    pub fn arg_kind(&self, head: SymId, pos: usize) -> Option<ArgKind> {
        self.table.get(&head).and_then(|ks| ks.get(pos)).copied()
    }

    pub fn known(&self, head: SymId) -> bool {
        self.table.contains_key(&head)
    }

    /// Is this constant a type former — does applying it fully give a non-`Prop` sort?
    pub fn is_type_former(&self, head: SymId) -> bool {
        self.type_formers.contains(&head)
    }

    pub fn len(&self) -> usize {
        self.table.len()
    }

    pub fn is_empty(&self) -> bool {
        self.table.is_empty()
    }
}

/// The binder kinds of a leading Π-telescope, in order.
fn telescope_kinds(a: &Arena, ty: TermId) -> Box<[ArgKind]> {
    let mut out = Vec::new();
    let mut cur = ty;
    while let Node::Pi(bi, dom, body) = a.node(cur) {
        let is_carrier = bi == BinderInfo::Implicit && is_nonprop_sort(a, dom);
        out.push(ArgKind {
            binder: bi,
            is_carrier,
        });
        cur = body;
    }
    out.into_boxed_slice()
}

/// Strip the leading Π-telescope and ask whether what remains is a non-`Prop` sort.
///
/// `Nat : Type` yes; `List : Type → Type` yes; `Eq : {α} → α → α → Prop` no. This is the
/// cheap, exact substitute for "what is the type of this domain" — the constant's own row
/// already says.
fn produces_nonprop_sort(a: &Arena, ty: TermId) -> bool {
    let mut cur = ty;
    while let Node::Pi(_, _, body) = a.node(cur) {
        cur = body;
    }
    is_nonprop_sort(a, cur)
}

/// Is this domain a *concrete* carrier — a closed type built from a type former?
///
/// `∀ (n : ℕ)` yes, `∀ (p : Prop)` no (its domain is `Sort 0`, handled by the sort rule),
/// `∀ (h : P)` no (`P` is a bound variable, so the domain is not closed), `∀ (x : Eq a b)`
/// no (`Eq` produces `Prop`, so holing it would erase a hypothesis).
///
/// **This rule is the completion the design was missing.** Without it, `Nat.add_comm` and
/// `Int.add_comm` are identical at `Carriers` *except* for their explicit binder domains
/// — every implicit carrier holed, and the two statements still unequal. Measured: no
/// cross-carrier pair collapsed below `shape`, which is the condition under which the
/// design said to delete levels 2-3. They were not decorative; they were incomplete.
fn is_concrete_carrier(a: &Arena, sigs: &Signatures, dom: TermId) -> bool {
    if !a.is_closed(dom) {
        return false;
    }
    let (head, _) = a.spine(unwrap_out_param(a, dom));
    matches!(a.node(head), Node::Const(s, _) if sigs.is_type_former(s))
}

/// Is this domain a sort other than `Sort 0`, after unwrapping `outParam`?
fn is_nonprop_sort(a: &Arena, dom: TermId) -> bool {
    let d = unwrap_out_param(a, dom);
    match a.node(d) {
        // `Sort 0` is `Prop`: the statement is *about* those, not carried by them.
        Node::Sort(l) => !matches!(a.level(l), LevelNode::Zero),
        _ => false,
    }
}

fn unwrap_out_param(a: &Arena, t: TermId) -> TermId {
    let (head, args) = a.spine(t);
    if let (1, Node::Const(s, _)) = (args.len(), a.node(head))
        && matches!(a.sym(s), "outParam" | "semiOutParam")
    {
        return unwrap_out_param(a, args[0]);
    }
    t
}

pub type EraseCache = HashMap<(TermId, Level), TermId>;

/// Erase to a level. Total and deterministic.
pub fn erase(
    a: &mut Arena,
    sigs: &Signatures,
    cache: &mut EraseCache,
    t: TermId,
    level: Level,
) -> TermId {
    if level == Level::Exact {
        return t;
    }
    if let Some(&hit) = cache.get(&(t, level)) {
        return hit;
    }
    let out = erase_uncached(a, sigs, cache, t, level);
    cache.insert((t, level), out);
    out
}

fn erase_uncached(
    a: &mut Arena,
    sigs: &Signatures,
    cache: &mut EraseCache,
    t: TermId,
    level: Level,
) -> TermId {
    // Applications are handled at the spine root, because an argument's fate depends on
    // its *position in the spine*, which an interior node cannot see.
    if matches!(a.node(t), Node::App(..)) {
        return erase_spine(a, sigs, cache, t, level);
    }
    let node = match a.node(t) {
        Node::Sort(l) => {
            let l = erase_level(a, l, level);
            Node::Sort(l)
        }
        Node::Const(s, ls) => {
            if level >= Level::Shape {
                Node::Hole
            } else {
                Node::Const(s, erase_levels(a, ls, level))
            }
        }
        Node::NatLit(_) | Node::StrLit(_) if level >= Level::Shape => Node::Hole,
        Node::Lam(bi, d, b) => {
            let (bi, d) = erase_binder(a, sigs, cache, bi, d, level);
            Node::Lam(bi, d, erase(a, sigs, cache, b, level))
        }
        Node::Pi(bi, d, b) => {
            let (bi, d) = erase_binder(a, sigs, cache, bi, d, level);
            Node::Pi(bi, d, erase(a, sigs, cache, b, level))
        }
        Node::Let(ty, v, b) => Node::Let(
            erase(a, sigs, cache, ty, level),
            erase(a, sigs, cache, v, level),
            erase(a, sigs, cache, b, level),
        ),
        // A projection keeps its structure at every level: which field of which
        // structure is taken is shape, not presentation.
        Node::Proj(s, i, e) => Node::Proj(s, i, erase(a, sigs, cache, e, level)),
        other => other,
    };
    a.intern(node)
}

/// A binder's own erasure. **The binder survives**; only its info and domain change.
fn erase_binder(
    a: &mut Arena,
    sigs: &Signatures,
    cache: &mut EraseCache,
    bi: BinderInfo,
    dom: TermId,
    level: Level,
) -> (BinderInfo, TermId) {
    // Two ways to be a carrier binder. `{α : Type u}` is the generic one the design
    // named; `(n : ℕ)` is the concrete one it missed, and the concrete one is most of
    // Mathlib — a lemma stated at a fixed type binds its variables explicitly at that type.
    let generic_carrier = bi == BinderInfo::Implicit && is_nonprop_sort(a, dom);
    let concrete_carrier = is_concrete_carrier(a, sigs, dom);
    let hole = a.intern(Node::Hole);
    let dom = match () {
        _ if level >= Level::Instances && bi == BinderInfo::InstImplicit => hole,
        _ if level >= Level::Carriers && (generic_carrier || concrete_carrier) => hole,
        _ => erase(a, sigs, cache, dom, level),
    };
    let bi = match level {
        Level::Shape => BinderInfo::Default,
        // `StrictImplicit` is a presentation detail of how an argument is *supplied*,
        // not of what the statement says.
        l if l >= Level::Presentation && bi == BinderInfo::StrictImplicit => BinderInfo::Implicit,
        _ => bi,
    };
    (bi, dom)
}

fn erase_spine(
    a: &mut Arena,
    sigs: &Signatures,
    cache: &mut EraseCache,
    t: TermId,
    level: Level,
) -> TermId {
    let (head, args) = a.spine(t);

    // `OfNat.ofNat T k inst` is how a numeral reaches an arbitrary type. At
    // `Presentation` and above it collapses to the literal, which is the canonicalisation
    // `statement-hash.md` deliberately refused for *identity* and which is exactly right
    // for *analogy*.
    if let (true, 3, Node::Const(s, _)) = (level >= Level::Presentation, args.len(), a.node(head))
        && a.sym(s) == "OfNat.ofNat"
        && matches!(a.node(args[1]), Node::NatLit(_))
    {
        return erase(a, sigs, cache, args[1], level);
    }

    let head_sym = match a.node(head) {
        Node::Const(s, _) => Some(s),
        _ => None,
    };
    let hole = a.intern(Node::Hole);
    let mut out = erase(a, sigs, cache, head, level);
    for (i, &arg) in args.iter().enumerate() {
        let kind = head_sym.and_then(|s| sigs.arg_kind(s, i));
        let erased = match kind {
            Some(k) if level >= Level::Instances && k.binder == BinderInfo::InstImplicit => hole,
            Some(k) if level >= Level::Carriers && k.is_carrier => hole,
            // An unknown head degrades to `Presentation` behaviour for its arguments —
            // deterministically, and the index counts how often it happens.
            _ => erase(a, sigs, cache, arg, level),
        };
        out = a.intern(Node::App(out, erased));
    }
    out
}

fn erase_level(a: &mut Arena, l: super::term::LevelId, level: Level) -> super::term::LevelId {
    if level >= Level::Presentation {
        a.intern_level(LevelNode::Star)
    } else {
        l
    }
}

/// A `Const`'s level list keeps its **length** — arity is part of what the constant is,
/// even when the levels themselves are erased.
fn erase_levels(a: &mut Arena, ls: LevelsId, level: Level) -> LevelsId {
    if level < Level::Presentation {
        return ls;
    }
    let n = a.level_list(ls).len();
    let star = a.intern_level(LevelNode::Star);
    let stars: Vec<_> = std::iter::repeat_n(star, n).collect();
    a.intern_levels(&stars)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::skel::term::Arena;

    fn p(a: &mut Arena, s: &str) -> TermId {
        a.parse(&format!("atlas-stmt-v1;{s}")).expect("parse")
    }

    /// Erase and render. A helper because `a.render(erase(&mut a, …))` borrows twice.
    fn er(a: &mut Arena, s: &Signatures, c: &mut EraseCache, t: TermId, l: Level) -> String {
        let e = erase(a, s, c, t, l);
        a.render(e)
    }

    fn no_sigs() -> Signatures {
        Signatures {
            table: HashMap::new(),
            type_formers: HashSet::new(),
            missing: HashSet::new(),
        }
    }

    /// A one-argument constant declared `{α : Type u} → …`: an implicit carrier.
    fn sigs_with_carrier(a: &mut Arena) -> Signatures {
        let f = a.intern_sym("F");
        let ty = p(a, "pi(s(+(u0)),pd(b0,b1))");
        Signatures::from_rows(a, std::iter::once((f, ty)))
    }

    #[test]
    fn exact_is_the_identity() {
        let mut a = Arena::new();
        let t = p(&mut a, "a(c(1:F,1,+(u0)),c(3:Nat,0))");
        let s = no_sigs();
        let mut c = EraseCache::new();
        assert_eq!(erase(&mut a, &s, &mut c, t, Level::Exact), t);
    }

    #[test]
    fn presentation_stars_universes_but_keeps_arity() {
        let mut a = Arena::new();
        let t = p(&mut a, "c(1:F,2,+(u0),u1)");
        let s = no_sigs();
        let mut c = EraseCache::new();
        let e = erase(&mut a, &s, &mut c, t, Level::Presentation);
        // Two levels in, two out — the levels are erased, the *arity* is not.
        assert_eq!(a.render(e), "c(1:F,2,*,*)");
    }

    #[test]
    fn presentation_collapses_ofnat_to_the_literal() {
        let mut a = Arena::new();
        let t = p(
            &mut a,
            "a(a(a(c(11:OfNat.ofNat,1,0),c(3:Nat,0)),n2),c(4:inst,0))",
        );
        let s = no_sigs();
        let mut c = EraseCache::new();
        assert_eq!(er(&mut a, &s, &mut c, t, Level::Presentation), "n2");
    }

    #[test]
    fn instances_hole_instance_binders_without_deleting_them() {
        let mut a = Arena::new();
        // `∀ {α} [Inst α] (x : α), …` — the instance binder must be *replaced*, because
        // deleting it would shift `b0`/`b1` and change the statement.
        let t = p(&mut a, "pi(s(+(u0)),pt(a(c(4:Inst,0),b0),pd(b1,b2)))");
        let s = no_sigs();
        let mut c = EraseCache::new();
        let e = erase(&mut a, &s, &mut c, t, Level::Instances);
        assert_eq!(a.render(e), "pi(s(*),pt(_,pd(b1,b2)))");
        // The de Bruijn indices are untouched, which is the whole point.
        assert!(a.render(e).contains("b1"));
        assert!(a.render(e).contains("b2"));
    }

    #[test]
    fn carriers_holes_a_type_binder_but_not_a_prop_binder() {
        let mut a = Arena::new();
        // `{α : Type u}` is a carrier; `{p : Prop}` is what the statement is *about*.
        let ty = p(&mut a, "pi(s(+(u0)),b0)");
        let prop = p(&mut a, "pi(s(0),b0)");
        let s = no_sigs();
        let mut c = EraseCache::new();
        assert_eq!(er(&mut a, &s, &mut c, ty, Level::Carriers), "pi(_,b0)");
        // `Sort 0` is `Prop` and survives — this is the rule that keeps `and_comm`
        // from collapsing into a statement about two erased propositions.
        assert_eq!(er(&mut a, &s, &mut c, prop, Level::Carriers), "pi(s(*),b0)");
    }

    #[test]
    fn out_param_hides_a_sort_and_is_unwrapped() {
        let mut a = Arena::new();
        // `{γ : outParam (Sort u)}` is a carrier, even though its domain is an
        // *application*. Without unwrapping, `α` erases and `γ` does not — asymmetric
        // nonsense.
        let t = p(&mut a, "pi(a(c(8:outParam,1,+(u0)),s(+(u0))),b0)");
        let s = no_sigs();
        let mut c = EraseCache::new();
        assert_eq!(er(&mut a, &s, &mut c, t, Level::Carriers), "pi(_,b0)");
    }

    #[test]
    fn shape_keeps_structure_and_nothing_else() {
        let mut a = Arena::new();
        let t = p(&mut a, "a(a(c(2:Eq,0),c(3:Foo,0)),n7)");
        let s = no_sigs();
        let mut c = EraseCache::new();
        // Application structure survives; every constant and literal is gone.
        assert_eq!(er(&mut a, &s, &mut c, t, Level::Shape), "a(a(_,_),_)");
    }

    #[test]
    fn p7_levels_form_a_chain() {
        // `erase(erase(t, ℓ), ℓ') = erase(t, ℓ')` for ℓ ≤ ℓ'. This is what makes the
        // buckets provably refine, and therefore what makes recall monotone in the level.
        let mut a = Arena::new();
        let t = p(
            &mut a,
            "pi(s(+(u0)),pt(a(c(4:Inst,0),b0),a(a(c(2:Eq,1,u0),b1),n3)))",
        );
        let s = no_sigs();
        let mut c = EraseCache::new();
        for (i, &lo) in Level::ALL.iter().enumerate() {
            for &hi in &Level::ALL[i..] {
                let once = erase(&mut a, &s, &mut c, t, hi);
                let staged = erase(&mut a, &s, &mut c, t, lo);
                let twice = erase(&mut a, &s, &mut c, staged, hi);
                assert_eq!(once, twice, "chain broken at {lo:?} -> {hi:?}");
            }
        }
    }

    #[test]
    fn argument_positions_come_from_the_signature() {
        let mut a = Arena::new();
        let s = sigs_with_carrier(&mut a);
        let t = p(&mut a, "a(c(1:F,1,u0),c(3:Nat,0))");
        let mut c = EraseCache::new();
        // `F`'s first argument is an implicit carrier, so `Carriers` holes it — read off
        // `F`'s own row rather than guessed from the call site.
        assert_eq!(
            er(&mut a, &s, &mut c, t, Level::Carriers),
            "a(c(1:F,1,*),_)"
        );
        // …and `Instances` leaves it alone, because it is not an instance.
        assert_eq!(
            er(&mut a, &s, &mut c, t, Level::Instances),
            "a(c(1:F,1,*),c(3:Nat,0))"
        );
    }

    #[test]
    fn carriers_holes_a_concrete_explicit_binder_domain() {
        // The completion the design was missing, and the reason levels 2-3 ship.
        // `∀ (n : ℕ), …` and `∀ (n : ℤ), …` differ only in an *explicit* binder domain;
        // without this rule they stay distinct at `carriers` and the knob does nothing.
        let mut a = Arena::new();
        let nat = a.intern_sym("Nat");
        let int = a.intern_sym("Int");
        let prop_fam = a.intern_sym("P");
        // `Nat : Type`, `Int : Type` — type formers. `P : Prop` is not.
        let ty = p(&mut a, "s(+(0))");
        let pr = p(&mut a, "s(0)");
        let s = Signatures::from_rows(&a, [(nat, ty), (int, ty), (prop_fam, pr)].into_iter());
        let mut c = EraseCache::new();

        let over_nat = p(&mut a, "pd(c(3:Nat,0),b0)");
        let over_int = p(&mut a, "pd(c(3:Int,0),b0)");
        let en = erase(&mut a, &s, &mut c, over_nat, Level::Carriers);
        let ei = erase(&mut a, &s, &mut c, over_int, Level::Carriers);
        assert_eq!(
            en, ei,
            "quantifying over ℕ and over ℤ must agree at `carriers`"
        );
        assert_eq!(a.render(en), "pd(_,b0)");

        // And a *proposition* binder is untouched: holing it would erase a hypothesis.
        let over_prop = p(&mut a, "pd(c(1:P,0),b0)");
        assert_eq!(
            er(&mut a, &s, &mut c, over_prop, Level::Carriers),
            "pd(c(1:P,0),b0)"
        );
    }

    #[test]
    fn an_unknown_head_degrades_deterministically() {
        let mut a = Arena::new();
        let s = no_sigs();
        let t = p(&mut a, "a(c(7:Unknown,0),c(3:Nat,0))");
        let mut c = EraseCache::new();
        // No row for `Unknown`, so its arguments keep `Presentation` behaviour rather
        // than being holed on a guess.
        assert_eq!(
            er(&mut a, &s, &mut c, t, Level::Carriers),
            "a(c(7:Unknown,0),c(3:Nat,0))"
        );
    }
}
