//! Does the normalization knob do anything on real algebra?
//!
//! This is the test that decides whether levels 2 and 3 ship. They "barely move the
//! needle" on a Lean-core slice, because Lean core has almost no instances and no
//! carriers — so measuring there proves nothing either way. If the buckets do not
//! collapse on an *algebra* slice, the knob is decorative and should be deleted rather
//! than shipped.

use std::collections::{HashMap, HashSet};

use atlas::skel::erase::{EraseCache, Level, Signatures, erase};
use atlas::skel::term::{Arena, TermId};

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let text = std::fs::read_to_string(&path).unwrap();
    let mut a = Arena::new();
    let mut rows: Vec<(String, TermId)> = Vec::new();
    let mut sig_rows: Vec<(atlas::skel::term::SymId, TermId)> = Vec::new();
    for line in text.lines() {
        let Ok(v) = atlas::json::parse(line) else {
            continue;
        };
        let (Some(name), Some(stmt)) = (
            v.get("name").and_then(|s| s.as_str()),
            v.get("stmt").and_then(|s| s.as_str()),
        ) else {
            continue;
        };
        if let Ok(t) = a.parse(stmt) {
            let sym = a.intern_sym(name);
            sig_rows.push((sym, t));
            rows.push((name.to_string(), t));
        }
    }
    let sigs = Signatures::from_rows(&a, sig_rows.into_iter());
    println!("{} statements, {} signatures", rows.len(), sigs.len());

    let mut cache = EraseCache::new();
    let mut prev_buckets = usize::MAX;
    for &level in &Level::ALL {
        let t0 = std::time::Instant::now();
        let mut buckets: HashMap<TermId, u32> = HashMap::new();
        for (_, t) in &rows {
            let e = erase(&mut a, &sigs, &mut cache, *t, level);
            *buckets.entry(e).or_insert(0) += 1;
        }
        let n = buckets.len();
        let singletons = buckets.values().filter(|&&c| c == 1).count();
        let biggest = buckets.values().copied().max().unwrap_or(0);
        println!(
            "{:>12}  buckets {:>7}  singletons {:>6.1}%  largest {:>6}   {:.2}s",
            level.name(),
            n,
            100.0 * singletons as f64 / n as f64,
            biggest,
            t0.elapsed().as_secs_f64()
        );
        // P7 in the large: buckets must never grow as the level coarsens, because the
        // levels are a chain and coarser buckets are unions of finer ones.
        assert!(
            n <= prev_buckets,
            "buckets grew from {prev_buckets} to {n} at {level:?}"
        );
        prev_buckets = n;
    }

    // The claim the knob exists for: statements that are *different* at `Exact` become
    // *equal* at `Instances`, and the ones that do are the cross-carrier analogies.
    let mut by_name: HashMap<&str, TermId> = HashMap::new();
    for (n, t) in &rows {
        by_name.insert(n.as_str(), *t);
    }
    let probes = [
        ("Nat.add_comm", "Int.add_comm"),
        ("Nat.mul_comm", "Int.mul_comm"),
        ("Nat.add_assoc", "Int.add_assoc"),
        ("Nat.le_trans", "Int.le_trans"),
    ];
    println!("\ncross-carrier collapse (the reason levels 2-3 exist):");
    let mut collapsed_any = false;
    for (x, y) in probes {
        let (Some(&tx), Some(&ty)) = (by_name.get(x), by_name.get(y)) else {
            println!("  {x} ~ {y}: one of them is not in this slice");
            continue;
        };
        let mut first_equal = None;
        for &level in &Level::ALL {
            let ex = erase(&mut a, &sigs, &mut cache, tx, level);
            let ey = erase(&mut a, &sigs, &mut cache, ty, level);
            if ex == ey {
                first_equal = Some(level);
                break;
            }
        }
        match first_equal {
            Some(l) => {
                println!("  {x} ~ {y}: equal from `{}`", l.name());
                if l < Level::Shape {
                    collapsed_any = true;
                }
            }
            None => println!("  {x} ~ {y}: never equal, even at `shape`"),
        }
    }
    if !collapsed_any {
        eprintln!(
            "\nVERDICT: no cross-carrier pair collapsed before `shape`. Levels 2-3 are \
             decorative on this slice and should be deleted rather than shipped."
        );
        std::process::exit(1);
    }
    println!(
        "\nVERDICT: the knob collapses cross-carrier pairs below `shape` — levels 2-3 earn their place."
    );
    let _ = HashSet::<u8>::new();
}
