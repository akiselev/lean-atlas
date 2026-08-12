//! Does the proved-edge layer find real logical structure, and does it keep itself
//! separate from the heuristic layer?
//!
//! What a good answer looks like, stated before the run (CLAUDE.md §3):
//!
//! 1. The graph is built from thousands of `Iff`s, not a handful — otherwise §1d's
//!    "edges are proven `Iff`s" is describing the validation corpus again.
//! 2. The busiest heads are *logical connectives and order relations*, the places where
//!    mathematics actually accumulates reformulations. If they are `Aesop` or `Lean`
//!    internals, this is measuring metaprogramming rather than mathematics, which
//!    CLAUDE.md §5 records as having bitten three times.
//! 3. A path exists between two heads a reader can check by eye, and every step of it
//!    names a theorem.
//! 4. **Negative control:** the flex-head and non-Prop counters must both be non-zero.
//!    A zero there does not mean the extraction was clean, it means the guard is dead —
//!    and a tool that says everything is fine is worse than no tool.
//! 5. **Negative control:** constructing a proved relation from heuristic evidence must
//!    be refused, in the engine rather than by convention.

use std::time::Instant;

use atlas::equiv::EquivIndex;
use atlas::logical::LogicalGraph;
use atlas::relation::{Direction, Evidence, Relation, RelationKind, Warrant};

fn main() {
    let path = std::env::args()
        .nth(1)
        .expect("usage: logicalcheck <jsonl>");
    let src = std::fs::read_to_string(&path).expect("read slice");

    let t0 = Instant::now();
    let idx = EquivIndex::build(&src).expect("build equivalence index");
    println!(
        "slice: {} declarations, {} propositions  ({:.1}s)",
        idx.len(),
        idx.prop_count(),
        t0.elapsed().as_secs_f32()
    );

    let t1 = Instant::now();
    let g = LogicalGraph::build(&idx);
    let s = g.stats();
    println!(
        "\nlogical graph: {} edges over {} heads  ({:.1}s)",
        g.len(),
        g.heads(),
        t1.elapsed().as_secs_f32()
    );
    println!(
        "  {} theorems scanned; {} Iff edges, {} implication edges",
        s.theorems_scanned, s.iff_edges, s.implication_edges
    );
    println!(
        "  {} Prop-heading symbols witnessed by the corpus",
        s.prop_heads
    );
    println!(
        "  unsupported: {} flex-head sides; rejected: {} non-Prop sides",
        s.flex_head_sides, s.non_prop_sides
    );

    assert!(
        s.iff_edges > 500,
        "only {} Iff edges — the proved layer would be too thin to be a graph",
        s.iff_edges
    );

    println!("\nbusiest heads (where reformulations accumulate):");
    for ((h, arity), n) in g.busiest(12) {
        println!("  {n:5}  {h}/{arity}");
    }

    // Claim 3: a chain a reader can check, every step naming its theorem.
    println!("\nproved paths:");
    let mut found_path = false;
    for (a, ar, b, br) in [
        ("Membership.mem", 5, "Eq", 3),
        ("LT.lt", 4, "LE.le", 4),
        ("Dvd.dvd", 4, "Eq", 3),
        ("Membership.mem", 4, "Eq", 3),
    ] {
        match g.path(&(a.to_string(), ar), &(b.to_string(), br)) {
            Some(chain) if !chain.is_empty() => {
                found_path = true;
                println!("  {a}/{ar} --> {b}/{br}  ({} steps)", chain.len());
                for r in chain.iter().take(4) {
                    println!("      {}", r.explain());
                }
                // Heads are carrier-blind, so a chain may compose theorems that no
                // single carrier satisfies. The witnesses' namespaces are the evidence
                // for that, and printing them is how the caveat stays attached to the
                // result rather than living only in a doc comment.
                let roots: Vec<String> = chain
                    .iter()
                    .filter_map(|r| match &r.evidence {
                        Evidence::LeanTheorem { name } => {
                            Some(name.split('.').next().unwrap_or(name).to_string())
                        }
                        _ => None,
                    })
                    .collect();
                let mut distinct = roots.clone();
                distinct.sort();
                distinct.dedup();
                if distinct.len() > 1 {
                    println!(
                        "      ^ spans {} namespaces {distinct:?} — a lead, not a \
                         derivation: no carrier need satisfy every step",
                        distinct.len()
                    );
                } else {
                    println!(
                        "      ^ every step witnessed within `{}`; still unproved as a \
                         composition until elaborated (C6)",
                        distinct.first().map(String::as_str).unwrap_or("?")
                    );
                }
            }
            Some(_) => println!("  {a}/{ar} is {b}/{br}"),
            None => println!("  {a}/{ar} --> {b}/{br}: no proved chain in this slice"),
        }
    }
    assert!(
        found_path,
        "no proved chain between any of the probed heads — the graph is disconnected \
         enough to be useless"
    );

    // Claim 4: the guards are live.
    assert!(
        s.flex_head_sides > 0,
        "zero flex-head sides means the higher-order guard never fired, which on a \
         131k-declaration slice means it is dead rather than satisfied"
    );
    assert!(
        s.non_prop_sides > 0,
        "zero non-Prop rejections means every non-dependent Pi was read as an \
         implication — `∀ (n : ℕ), P n` would be an edge from Nat"
    );
    println!("\nnegative control: both guards fired, so neither is dead.");

    // Claim 5: the warrant boundary is enforced by the type, not by convention.
    let refused = Relation::new(
        "le_trans",
        "dvd_trans",
        RelationKind::ProvedIff,
        Direction::Both,
        Evidence::AntiUnification {
            skeleton: "a(?0,?1)".into(),
            common: 6,
            retention: 0.42,
        },
        "logicalcheck",
    );
    match refused {
        Err(e) => println!("negative control: {e}"),
        Ok(_) => {
            eprintln!("a resemblance was accepted as a proof — the warrant boundary is gone");
            std::process::exit(1);
        }
    }

    // And the edges the graph does emit are all Proved, by construction.
    let sample: Vec<Relation> = g
        .busiest(1)
        .first()
        .map(|((h, a), _)| g.from_head(h, *a))
        .unwrap_or_default();
    assert!(
        sample.iter().all(|r| r.warrant() == Warrant::Proved),
        "the logical graph emitted a non-proved edge"
    );
    println!(
        "every one of the {} edges at the busiest head carries {:?} warrant.",
        sample.len(),
        Warrant::Proved
    );
}
