//! The ranking golden: top-k for a fixed query list, on a named slice.
//!
//! Its whole purpose is to make a ranking change *visible and reviewed* rather than
//! assumed benign. Two of M1's fixes — querying source B at the level the postings were
//! built at, and repairing `retention`'s denominator — move scores for every pair in the
//! corpus. Recomputing a product from the factors it was just built from proves nothing
//! about neighbour order, so the regression gate has to be the order itself.
//!
//! Usage:
//!   goldencheck <slice.jsonl>              print the golden
//!   goldencheck <slice.jsonl> <golden.txt> compare against a stored one, exit 1 on drift
//!
//! Ties are reported with their group size, because they are the normal case rather than
//! an edge case: the score is a product of a few coarse factors, so whole families land on
//! one value. That matters concretely — an alphabetical tie-break once pushed `dvd_trans`
//! out of `le_trans`'s top five and took a named gate with it. A top-k that slices a tie
//! class records the alphabet, not the scorer, so read the group sizes before reading the
//! order.

use std::collections::BTreeMap;

use atlas::skel::index::{IndexConfig, SkeletonIndex};

/// Fixed by hand, and chosen to span the cases the index is supposed to handle rather
/// than the ones it does well on:
/// * `le_trans` / `dvd_trans` — the cross-carrier analogy the design exists for.
/// * `Nat.mul_comm` — a large same-name family across word widths; tie-saturated.
/// * `le_antisymm` — a claim with two spellings in the corpus.
/// * `Nat.add_comm` — carrier is an *explicit* binder, CLAUDE.md §5's trap.
/// * `Nat.succ_le_succ` — a monotonicity shape with many partial matches.
/// * `And.comm` — a pure logical rewrite, no carrier at all.
const QUERIES: [&str; 7] = [
    "le_trans",
    "dvd_trans",
    "Nat.mul_comm",
    "le_antisymm",
    "Nat.add_comm",
    "Nat.succ_le_succ",
    "And.comm",
];

const TOP: usize = 10;

fn render(idx: &mut SkeletonIndex, cfg: &IndexConfig) -> String {
    let mut out = String::new();
    for q in QUERIES {
        out.push_str(&format!("# {q}\n"));
        match idx.similar(q, TOP, cfg) {
            Err(e) => out.push_str(&format!("  ERROR {e}\n")),
            Ok(ns) if ns.is_empty() => out.push_str("  (no neighbours)\n"),
            Ok(ns) => {
                // Group by score so the diff distinguishes "the scorer moved" from "the
                // alphabet moved", which are different failures.
                let mut groups: BTreeMap<String, usize> = BTreeMap::new();
                for n in &ns {
                    *groups.entry(format!("{:.4}", n.score)).or_default() += 1;
                }
                for n in &ns {
                    let key = format!("{:.4}", n.score);
                    out.push_str(&format!(
                        "  {key}  tie{:<2}  ret {:.3}  common {:>3}  vars {:>2}  [{}]  {}\n",
                        groups[&key],
                        n.retention,
                        n.common,
                        n.vars,
                        n.sources.describe(),
                        n.name,
                    ));
                }
            }
        }
    }
    out
}

fn main() {
    let mut args = std::env::args().skip(1);
    let path = args
        .next()
        .expect("usage: goldencheck <jsonl> [golden.txt]");
    let golden = args.next();

    let src = std::fs::read_to_string(&path).expect("read slice");
    let cfg = IndexConfig::default();
    let mut idx = SkeletonIndex::build(&src, &cfg).expect("build index");
    let now = render(&mut idx, &cfg);

    match golden {
        None => print!("{now}"),
        Some(g) => {
            let was = std::fs::read_to_string(&g).expect("read golden");
            if was == now {
                println!("golden: unchanged ({} queries)", QUERIES.len());
                return;
            }
            println!("golden: RANKING CHANGED\n");
            // A line-level diff, so a reviewer sees which rows moved rather than being
            // told that something did.
            let (a, b): (Vec<&str>, Vec<&str>) = (was.lines().collect(), now.lines().collect());
            let mut i = 0;
            while i < a.len().max(b.len()) {
                match (a.get(i), b.get(i)) {
                    (Some(x), Some(y)) if x == y => {}
                    (x, y) => {
                        if let Some(x) = x {
                            println!("- {x}");
                        }
                        if let Some(y) = y {
                            println!("+ {y}");
                        }
                    }
                }
                i += 1;
            }
            std::process::exit(1);
        }
    }
}
