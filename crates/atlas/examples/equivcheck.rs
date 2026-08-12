//! Does the equivalence index find real reformulation families, and does the Prop guard
//! matter?
//!
//! The two measurements that decided B5's design are re-taken here rather than cited, so
//! a change to the corpus or the encoder shows up as a changed number.

use atlas::equiv::{EquivIndex, NormLevel, flex_head_count, ladder, rule_index_stats};

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let text = std::fs::read_to_string(&path).unwrap();
    let t0 = std::time::Instant::now();
    let mut idx = EquivIndex::build(&text).expect("build");
    println!(
        "{} declarations, {} propositions, {:.1}s",
        idx.len(),
        idx.prop_count(),
        t0.elapsed().as_secs_f64()
    );

    // Measurement 1: `Iff`-as-edges describes the validation corpus, not Mathlib.
    println!(
        "\n`Iff`-concluding theorems: {}, of which ground on both sides: {}",
        idx.iff_total, idx.iff_ground
    );
    assert!(
        idx.iff_ground * 100 < idx.iff_total,
        "ground `Iff` edges are supposed to be the degenerate case; if they are common \
         here, atlas.md §1d as literally written is viable and this design is wrong"
    );

    // Measurement 2: the Prop guard is the difference between an equivalence index and a
    // type index.
    let unguarded = idx.classes(NormLevel::Exact, false, false);
    let guarded = idx.classes(NormLevel::Exact, true, false);
    let biggest_unguarded = unguarded.first().map(|(n, _)| *n).unwrap_or(0);
    let biggest_guarded = guarded.first().map(|(n, _)| *n).unwrap_or(0);
    println!(
        "\nE0 without the Prop guard: {} classes, largest {}",
        unguarded.len(),
        biggest_unguarded
    );
    println!(
        "E0 with    the Prop guard: {} classes, largest {}",
        guarded.len(),
        biggest_guarded
    );
    if let Some((_, members)) = unguarded.first() {
        println!(
            "  the unguarded giant starts: {:?}",
            &members[..members.len().min(4)]
        );
    }
    assert!(
        biggest_guarded * 4 < biggest_unguarded,
        "the Prop guard is supposed to be what stops a type index masquerading as an \
         equivalence; if it changes nothing, either the guard or this claim is wrong"
    );

    // The rule index's discrimination, which decides whether E2 is feasible at all.
    let ((sk, sm), (dk, dm)) = rule_index_stats(&idx);
    println!("\nrule index  head+arity: {sk} keys, largest bucket {sm}");
    println!("rule index  depth-2   : {dk} keys, largest bucket {dm}");
    assert!(
        dm * 4 < sm,
        "depth-2 discrimination is supposed to be mandatory, and is not helping"
    );

    let (flex, total) = flex_head_count(&idx);
    println!(
        "flex-head rule sides (need higher-order matching): {flex}/{total} = {:.1}%",
        100.0 * flex as f64 / total.max(1) as f64
    );

    // And the thing it is all for: named reformulation families.
    println!("\nreformulation ladders:");
    for probe in ["le_antisymm", "not_lt", "add_comm", "mul_comm", "dvd_trans"] {
        match ladder(&mut idx, probe) {
            Ok(rungs) if rungs.is_empty() => println!("  {probe}: alone at every level"),
            Ok(rungs) => {
                for (lvl, members) in rungs {
                    let show: Vec<&str> = members.iter().take(4).map(|s| s.as_str()).collect();
                    println!(
                        "  {probe} @ {:<12} {:>4} new: {:?}{}",
                        lvl.name(),
                        members.len(),
                        show,
                        if members.len() > 4 { " …" } else { "" }
                    );
                }
            }
            Err(e) => println!("  {probe}: {e}"),
        }
    }

    // And theorems only, which is what a reformulation family is made of.
    let thms = idx.classes(NormLevel::Instances, true, true);
    println!(
        "\nE1 at `instances`, theorems only: {} classes covering {} declarations",
        thms.len(),
        thms.iter().map(|(n, _)| n).sum::<usize>()
    );
    for (n, members) in thms.iter().take(3) {
        println!("  {n}: {:?}", &members[..members.len().min(5)]);
    }

    // The negative control §5.2's T8 asks for: equivalence of a non-proposition must
    // refuse, not answer.
    println!("\nnegative control:");
    match idx.equivalent("Nat.succ", NormLevel::Exact) {
        Err(e) => println!("  Nat.succ -> refused: {e}"),
        Ok(v) => {
            eprintln!(
                "  Nat.succ returned {} results; the Prop guard is missing",
                v.len()
            );
            std::process::exit(1);
        }
    }
}
