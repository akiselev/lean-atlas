//! The ranking golden, as a test target rather than an artifact nobody runs.
//!
//! A golden file with no test that reads it is decoration. This one was written, pinned
//! and then never loaded by `cargo test`, because `crates/atlas/tests/` contained no
//! `.rs` at all — so the regression gate for two changes that moved every score in the
//! corpus was, in effect, absent.
//!
//! It needs a real slice, which is 146 MB and not in the repo, so the test **skips** when
//! `ATLAS_SLICE` is unset rather than failing. A skip is honest; a green tick that silently
//! measured nothing is not, and the skip says so on stdout.
//!
//!     ATLAS_SLICE=/tmp/mathlib-algebra.jsonl cargo test -p atlas --test golden

use std::collections::BTreeMap;

use atlas::skel::index::{IndexConfig, SkeletonIndex};

const GOLDEN: &str = include_str!("golden/similar-algebra.txt");

/// Same list as `examples/goldencheck.rs`, and deliberately duplicated: if the two drift,
/// the diff says so rather than the golden silently covering a different question.
const QUERIES: [&str; 7] = [
    "le_trans",
    "dvd_trans",
    "Nat.mul_comm",
    "le_antisymm",
    "Nat.add_comm",
    "Nat.succ_le_succ",
    "And.comm",
];

fn render(idx: &mut SkeletonIndex, cfg: &IndexConfig) -> String {
    let mut out = String::new();
    for q in QUERIES {
        out.push_str(&format!("# {q}\n"));
        match idx.similar(q, 10, cfg) {
            Err(e) => out.push_str(&format!("  ERROR {e}\n")),
            Ok(ns) if ns.is_empty() => out.push_str("  (no neighbours)\n"),
            Ok(ns) => {
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

#[test]
fn the_ranking_matches_the_pinned_golden() {
    let Ok(path) = std::env::var("ATLAS_SLICE") else {
        println!("SKIPPED: set ATLAS_SLICE to a B1 JSONL slice to run the ranking golden");
        return;
    };
    let src = std::fs::read_to_string(&path).expect("read slice");
    let cfg = IndexConfig::default();
    let mut idx = SkeletonIndex::build(&src, &cfg).expect("build index");
    let now = render(&mut idx, &cfg);
    if now != GOLDEN {
        // Print the drift rather than just asserting, so a reviewer decides whether the
        // change is the intended one instead of re-recording the file to make it quiet.
        let (a, b): (Vec<&str>, Vec<&str>) = (GOLDEN.lines().collect(), now.lines().collect());
        for i in 0..a.len().max(b.len()) {
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
        }
        panic!("ranking drifted from the golden; review the diff above before re-pinning");
    }
}

/// The property the golden cannot express, and the one the tie-break bug actually broke:
/// within a tie class, order must be decided by *content* before it is decided by the
/// alphabet. `dvd_trans` fell out of `le_trans`'s top five because lowercase sorts after
/// every capitalised name.
#[test]
fn ties_are_broken_by_content_before_the_alphabet() {
    let Ok(path) = std::env::var("ATLAS_SLICE") else {
        println!("SKIPPED: set ATLAS_SLICE to a B1 JSONL slice");
        return;
    };
    let src = std::fs::read_to_string(&path).expect("read slice");
    let cfg = IndexConfig::default();
    let mut idx = SkeletonIndex::build(&src, &cfg).expect("build index");

    // Two queries, and a count of what was actually compared.
    //
    // This tested `le_trans` alone, which was right when the score was a product of coarse
    // factors and whole families landed on one value. The derivativeness penalty is
    // near-continuous, so it splits almost every tie: `le_trans`'s top 20 now holds *one*
    // equal-score pair, and one unlucky score change away this test asserts nothing while
    // still reporting green. `Nat.mul_comm` keeps 13 — the machine-integer family, which
    // is genuinely tied because its members are structurally identical — so it is the
    // query that exercises the rule.
    let mut examined = 0usize;
    for q in ["le_trans", "Nat.mul_comm"] {
        let ns = idx.similar(q, 20, &cfg).expect("similar");
        for w in ns.windows(2) {
            let (a, b) = (&w[0], &w[1]);
            if a.score != b.score {
                continue;
            }
            examined += 1;
            assert!(
                a.common > b.common || (a.common == b.common && a.vars <= b.vars),
                "{q}: within a tie class, `{}` (common {}, vars {}) precedes `{}` \
                 (common {}, vars {}) on nothing but its name",
                a.name,
                a.common,
                a.vars,
                b.name,
                b.common,
                b.vars
            );
        }
    }
    assert!(
        examined >= 5,
        "only {examined} tied pairs found across both queries — the tie-break rule is no \
         longer being exercised, so this test passes without testing anything. Pick a query \
         whose neighbours still tie rather than deleting the assertion."
    );
}
