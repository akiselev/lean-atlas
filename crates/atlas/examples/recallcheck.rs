//! What fraction of the true neighbours does the prefilter actually return?
//!
//! The tempting gate is `assert_eq!(brute, indexed)`. It is unachievable, and pretending
//! otherwise would mean either deleting the prefilter or weakening the assertion until it
//! says nothing. So the gate is a **recall floor**, measured against brute force on a
//! sample, and a floor that has to be re-measured rather than assumed when the sources or
//! their size thresholds change.
//!
//! Brute force is one anti-unification per declaration in the slice, so the sample is
//! small on purpose: 40 queries against 131k declarations is already 5.2 million LGGs.

use std::collections::HashSet;

use atlas::skel::index::{IndexConfig, SkeletonIndex};

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let floor: f64 = std::env::args()
        .nth(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.55);
    let text = std::fs::read_to_string(&path).unwrap();
    let cfg = IndexConfig::default();

    let t0 = std::time::Instant::now();
    let mut idx = SkeletonIndex::build(&text, &cfg).expect("build");
    println!(
        "index: {} declarations, {} signatures, {} + {} posting keys, {} degraded spines, {:.1}s",
        idx.len(),
        idx.signature_count(),
        idx.key_counts().0,
        idx.key_counts().1,
        idx.degraded_spines(),
        t0.elapsed().as_secs_f64()
    );

    // A deterministic spread, so a regression is reproducible — but through the
    // *claims*, not through the slice.
    //
    // Sampling raw declaration order put one Mathlib theorem in thirty queries. The slice
    // is two-thirds `Init`/`Std`/`Lean` and half of it is not a theorem at all, so the
    // number this harness reported was a statement about Lean's metaprogramming API. That
    // is CLAUDE.md §5's "restrict to claims, or you are measuring Lean rather than
    // mathematics", for the fourth recorded time; the unrestricted figure is still printed
    // below, labelled, because the gap between the two is itself the evidence.
    let n = idx.len();
    let claims: Vec<usize> = (0..n)
        .filter(|&i| idx.kind_of_at(i) == "theorem" && idx.module_of_at(i).starts_with("Mathlib."))
        .collect();
    let pick = |pool: &[usize], k: usize| -> Vec<String> {
        (0..k)
            .map(|j| {
                let i = pool[(j * 3187 + 11) % pool.len()];
                idx.name_of(atlas::skel::index::DeclId(i as u32))
                    .to_string()
            })
            .collect()
    };
    let names = pick(&claims, 40);
    let unrestricted = pick(&(0..n).collect::<Vec<_>>(), 40);
    println!(
        "query population: {} Mathlib theorems of {} declarations ({:.1}%)",
        claims.len(),
        n,
        100.0 * claims.len() as f64 / n as f64
    );

    // Measured per population, because a single figure over the whole slice is a figure
    // about Lean. `skipped` is printed rather than swallowed: the loop used to `continue`
    // past queries with no brute-force neighbours while the header still said 40.
    let mut run = |names: &[String], label: &str| -> f64 {
        let (mut found, mut total, mut queries, mut skipped) = (0usize, 0usize, 0usize, 0usize);
        let mut worst: Option<(f64, String)> = None;
        let t1 = std::time::Instant::now();
        for name in names {
            let Ok(brute) = idx.similar_brute(name, 5, &cfg) else {
                skipped += 1;
                continue;
            };
            if brute.is_empty() {
                skipped += 1;
                continue;
            }
            let truth: HashSet<&str> = brute.iter().map(|(n, _)| n.as_str()).collect();
            let Ok(fast) = idx.similar(name, 50, &cfg) else {
                skipped += 1;
                continue;
            };
            let got: HashSet<&str> = fast.iter().map(|n| n.name.as_str()).collect();
            let hit = truth.iter().filter(|t| got.contains(*t)).count();
            found += hit;
            total += truth.len();
            queries += 1;
            let r = hit as f64 / truth.len() as f64;
            if worst.as_ref().is_none_or(|(w, _)| r < *w) {
                worst = Some((r, name.clone()));
            }
        }
        let recall = found as f64 / total.max(1) as f64;
        println!(
            "\n{label}: {found}/{total} = {:.1}% over {queries} queries \
             ({skipped} of {} had no brute-force neighbours and were excluded; {:.1}s)",
            100.0 * recall,
            names.len(),
            t1.elapsed().as_secs_f64()
        );
        if let Some((r, n)) = worst {
            println!("  worst query: {n} at {:.0}%", 100.0 * r);
        }
        recall
    };

    let recall = run(&names, "recall over Mathlib theorems");

    run(
        &unrestricted,
        "recall over the whole slice (measures Lean, kept for contrast)",
    );

    // Where does the missing third actually go? "Recall" here is retrieve-*and-rank*: a
    // true neighbour is missed either because the prefilter never proposed it, or because
    // the scorer buried it below the top-50 cut. Those are different defects with
    // different fixes, and a single number cannot tell them apart.
    //
    // The split is clean rather than approximate, because `similar_brute` applies the same
    // `min_common`/`min_retention` as `similar` does. Every entry in the truth set passes
    // those thresholds by construction, so one missing from an untruncated `similar` was
    // never *proposed* — it cannot have been dropped by a floor.
    {
        let (mut lost_prefilter, mut lost_ranking, mut total) = (0usize, 0usize, 0usize);
        for name in &names {
            let Ok(brute) = idx.similar_brute(name, 5, &cfg) else {
                continue;
            };
            if brute.is_empty() {
                continue;
            }
            let truth: Vec<String> = brute.into_iter().map(|(n, _)| n).collect();
            // An effectively unbounded `top`, so nothing is lost to truncation: what is
            // missing here the prefilter genuinely never proposed.
            let Ok(wide) = idx.similar(name, usize::MAX, &cfg) else {
                continue;
            };
            let reachable: HashSet<&str> = wide.iter().map(|n| n.name.as_str()).collect();
            let Ok(cut) = idx.similar(name, 50, &cfg) else {
                continue;
            };
            let ranked: HashSet<&str> = cut.iter().map(|n| n.name.as_str()).collect();
            for t in &truth {
                total += 1;
                if !reachable.contains(t.as_str()) {
                    lost_prefilter += 1;
                } else if !ranked.contains(t.as_str()) {
                    lost_ranking += 1;
                }
            }
        }
        println!(
            "\ndecomposition over the same {total} true neighbours:\n  \
             lost by the PREFILTER (never proposed): {lost_prefilter} ({:.1}%)\n  \
             lost by the RANKING (proposed, buried below top-50): {lost_ranking} ({:.1}%)",
            100.0 * lost_prefilter as f64 / total.max(1) as f64,
            100.0 * lost_ranking as f64 / total.max(1) as f64
        );
    }

    // The ablation, on the population the gate is about. This is what source B is worth:
    // the same index, the same truth set, the same retention formula on both arms — only
    // the level source B is queried at differs. A before/after taken across the retention
    // fix could not have answered this, because that fix moves `similar_brute`'s ranking
    // and its filter, and so moves the truth set too.
    let mut broken = cfg.clone();
    broken.source_b_at_build_level = false;
    let ablated = {
        let (mut found, mut total) = (0usize, 0usize);
        for name in &names {
            let Ok(brute) = idx.similar_brute(name, 5, &cfg) else {
                continue;
            };
            if brute.is_empty() {
                continue;
            }
            let truth: HashSet<&str> = brute.iter().map(|(n, _)| n.as_str()).collect();
            let Ok(fast) = idx.similar(name, 50, &broken) else {
                continue;
            };
            let got: HashSet<&str> = fast.iter().map(|n| n.name.as_str()).collect();
            found += truth.iter().filter(|t| got.contains(*t)).count();
            total += truth.len();
        }
        found as f64 / total.max(1) as f64
    };
    println!(
        "\nablation — source B queried at the raw root (the defect): {:.1}%\n\
         source B repaired: {:.1}%   =>  the level fix is worth {:+.1}pp on Mathlib theorems",
        100.0 * ablated,
        100.0 * recall,
        100.0 * (recall - ablated)
    );

    // The gate is the restricted number. Both sides of this comparison use the same
    // `generalize`, so `similar_brute` is not an independent oracle: it ranks *by*
    // retention and filters by `min_retention`, which means a change to the retention
    // formula moves the truth set as well as the prediction. A single before/after delta
    // across such a change is therefore not attributable to the retrieval fix, and must be
    // reported as a decomposition or not at all.
    println!("floor: {:.0}%", 100.0 * floor);
    if recall < floor {
        eprintln!(
            "RECALL BELOW FLOOR. The prefilter's tuning does not hold on this slice; refit \
             the thresholds and re-pin the floor in a dedicated change rather than lowering it \
             here."
        );
        std::process::exit(1);
    }
}
