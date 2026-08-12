//! Run the anti-unifier's properties over real Mathlib pairs.
//!
//! Unit tests pin behaviour on hand-written terms; this pins it on the corpus. The
//! depth-blindness bug the design study found is invisible to a fixture and shows up at a
//! rate of about 4 in 10,000 real pairs, so corpus scale is not optional here.

use std::collections::HashMap;

use atlas::skel::lgg::{Lgg, generalize, matches, matches_wellscoped};
use atlas::skel::term::{Arena, Node, TermId};

/// The **unsound** depth-blind anti-unifier, reproduced here as a negative control.
///
/// It keys its memo on the pair alone, so two occurrences of the same pair at different
/// binder depths share a variable. It passes idempotence, commutativity and subsumption —
/// which is exactly why it needed finding by something else.
fn depth_blind(a: &mut Arena, x: TermId, y: TermId) -> TermId {
    fn go(
        a: &mut Arena,
        x: TermId,
        y: TermId,
        memo: &mut HashMap<(TermId, TermId), TermId>,
    ) -> TermId {
        if x == y {
            return x;
        }
        let node = match (a.node(x), a.node(y)) {
            (Node::App(f, u), Node::App(g, v)) => Node::App(go(a, f, g, memo), go(a, u, v, memo)),
            (Node::Lam(bx, dx, bdx), Node::Lam(by, dy, bdy)) if bx == by => {
                Node::Lam(bx, go(a, dx, dy, memo), go(a, bdx, bdy, memo))
            }
            (Node::Pi(bx, dx, bdx), Node::Pi(by, dy, bdy)) if bx == by => {
                Node::Pi(bx, go(a, dx, dy, memo), go(a, bdx, bdy, memo))
            }
            (Node::Let(tx, vx, bx), Node::Let(ty, vy, by)) => Node::Let(
                go(a, tx, ty, memo),
                go(a, vx, vy, memo),
                go(a, bx, by, memo),
            ),
            (Node::Proj(sx, ix, ex), Node::Proj(sy, iy, ey)) if sx == sy && ix == iy => {
                Node::Proj(sx, ix, go(a, ex, ey, memo))
            }
            _ => {
                let next = memo.len() as u32;
                if let Some(&v) = memo.get(&(x, y)) {
                    return v;
                }
                let v = a.intern(Node::Var(next));
                memo.insert((x, y), v);
                return v;
            }
        };
        a.intern(node)
    }
    go(a, x, y, &mut HashMap::new())
}

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let text = std::fs::read_to_string(&path).unwrap();
    let mut a = Arena::new();
    let mut terms: Vec<TermId> = Vec::new();
    for line in text.lines() {
        let Ok(v) = atlas::json::parse(line) else {
            continue;
        };
        let Some(stmt) = v.get("stmt").and_then(|s| s.as_str()) else {
            continue;
        };
        if let Ok(t) = a.parse(stmt) {
            terms.push(t);
        }
    }
    // Deterministic pairing: a fixed stride, so a failure is reproducible.
    let n = terms.len();
    let mut pairs = Vec::new();
    for stride in [1usize, 7, 53, 401, 2003] {
        for i in 0..n {
            let j = (i + stride) % n;
            if terms[i] != terms[j] {
                pairs.push((terms[i], terms[j]));
            }
        }
    }
    println!("{n} statements, {} pairs", pairs.len());

    let t0 = std::time::Instant::now();
    let (mut idem, mut comm, mut subs, mut scope, mut sizeb, mut counted) = (0, 0, 0, 0, 0, 0u64);
    for &t in &terms {
        if Lgg::new(&mut a).run(t, t) != t {
            idem += 1;
        }
    }
    for &(x, y) in &pairs {
        let g = generalize(&mut a, x, y);
        let h = generalize(&mut a, y, x);
        if g.skeleton != h.skeleton {
            comm += 1;
        }
        if matches(&a, g.skeleton, x).is_none() || matches(&a, g.skeleton, y).is_none() {
            subs += 1;
        }
        if !matches_wellscoped(&a, g.skeleton, x) || !matches_wellscoped(&a, g.skeleton, y) {
            scope += 1;
        }
        if a.size(g.skeleton) > a.size(x).min(a.size(y)) {
            sizeb += 1;
        }
        if g.scoped_vars > g.vars {
            counted += 1;
        }
    }
    // The negative control: the depth-blind reading must *diverge* from the correct one
    // on real input, or the fix is decorative and the extra memo term should go.
    let (mut diverged, mut blind_unscoped) = (0u64, 0u64);
    for &(x, y) in &pairs {
        let good = generalize(&mut a, x, y).skeleton;
        let blind = depth_blind(&mut a, x, y);
        if good != blind {
            diverged += 1;
            if !matches_wellscoped(&a, blind, x) || !matches_wellscoped(&a, blind, y) {
                blind_unscoped += 1;
            }
        }
    }
    let el = t0.elapsed().as_secs_f64();
    println!("P1 idempotence        violations: {idem}");
    println!("P2 commutativity      violations: {comm}");
    println!("P3 subsumption        violations: {subs}");
    println!("P9 well-scopedness    violations: {scope}");
    println!("P5 size bound         violations: {sizeb}");
    println!("P10 scoped accounting violations: {counted}");
    println!(
        "negative control: depth-blind diverges on {diverged} pairs ({:.3}%), of which \
         {blind_unscoped} are ill-scoped",
        100.0 * diverged as f64 / pairs.len() as f64
    );
    println!("{el:.2}s  ({:.1} µs / pair)", el * 1e6 / pairs.len() as f64);
    if diverged == 0 {
        eprintln!("negative control FAILED: the depth term never mattered on this corpus");
        std::process::exit(1);
    }
    let bad = idem + comm + subs + scope + sizeb + counted;
    if bad > 0 {
        std::process::exit(1);
    }
}
