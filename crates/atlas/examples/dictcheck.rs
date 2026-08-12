//! Do dictionaries, transport and the frontier say anything a reader can act on?
//!
//! Every claim here names what a good answer looks like before it is produced, because a
//! ranked list of theory pairs is exactly the kind of output that can be admired instead
//! of read.

use atlas::dict::{
    DictOptions, LeftState, Policy, Transported, coherence, dictionary, frontier, select,
    shuffle_control, theory_of, transport,
};
use atlas::graph::Graph;
use atlas::skel::erase::Level;
use atlas::skel::index::{IndexConfig, SkeletonIndex};

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let text = std::fs::read_to_string(&path).unwrap();
    let cfg = IndexConfig::default();
    let t0 = std::time::Instant::now();
    let mut idx = SkeletonIndex::build(&text, &cfg).expect("index");
    let graph = Graph::from_jsonl(&text).expect("graph");
    println!(
        "{} declarations, {:.1}s to build both indexes\n",
        idx.len(),
        t0.elapsed().as_secs_f64()
    );

    println!("theory_of samples:");
    for m in [
        "Mathlib.Algebra.Group.Defs",
        "Mathlib.Order.Basic",
        "Init.Data.Nat.Basic",
        "Std.Time",
    ] {
        println!("  {m:<36} -> {}", theory_of(m));
    }

    // The frontier: high skeleton similarity, low citation traffic.
    println!("\nfrontier — theory pairs that look alike and do not cite each other:");
    let t1 = std::time::Instant::now();
    let infra: Vec<String> = [
        "Init",
        "Std",
        "Lean",
        "Aesop",
        "Batteries",
        "Qq",
        "ProofWidgets",
        "Mathlib.Tactic",
        "Mathlib.Lean",
        "Mathlib.Util",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    let fr = frontier(&mut idx, &graph, 200, 12, true, &infra);
    for f in &fr {
        println!(
            "  {:.3}  {:<22} ~ {:<22} sim {:.2}  cites {:>5}  ({}/{})",
            f.score, f.left, f.right, f.similarity, f.cross_citations, f.left_size, f.right_size
        );
    }
    println!("  ({:.1}s)", t1.elapsed().as_secs_f64());
    assert!(
        !fr.is_empty(),
        "a slice this size must have some theory pairs to rank"
    );
    // A frontier that ranks a pair which already cites heavily is not measuring what it
    // claims to. The top pair should have less traffic than the median pair.
    let median_cites = {
        let mut c: Vec<usize> = fr.iter().map(|f| f.cross_citations).collect();
        c.sort_unstable();
        c[c.len() / 2]
    };
    println!(
        "  top pair's traffic {} vs median {}",
        fr[0].cross_citations, median_cites
    );

    // A dictionary between two theories that genuinely share structure.
    println!("\ndictionary — Mathlib.Order <-> Mathlib.Algebra:");
    let t2 = std::time::Instant::now();
    let d = dictionary(
        &mut idx,
        None,
        "Mathlib.Order",
        "Mathlib.Algebra",
        &cfg,
        &DictOptions::default(),
    );
    println!(
        "  {} rows, {} unmatched on the left, {} on the right  ({:.1}s)",
        d.rows.len(),
        d.missing_left.len(),
        d.missing_right.len(),
        t2.elapsed().as_secs_f64()
    );
    for r in d.rows.iter().take(8) {
        println!(
            "  {:.2} {:<12} {:<34} ~ {}",
            r.retention,
            r.status.name(),
            r.left,
            r.right
        );
    }
    println!(
        "  missing (left), first 5: {:?}",
        &d.missing_left[..d.missing_left.len().min(5)]
    );
    assert!(
        !d.rows.is_empty(),
        "order theory and algebra must share *some* structure"
    );
    // The missing-entry report is the point of the exercise; an empty one means the
    // matcher is claiming a total functor, which it is not.
    assert!(
        !d.missing_left.is_empty(),
        "a total dictionary would mean every order-theory concept has an algebraic partner"
    );

    // ---- M3a: is this a map, and is it about analogy at all? ----
    //
    // Stated before the run. (1) The shuffled control must separate: genuine pairs score
    // above coincidence, and few shuffled pairs clear the same floors. Without that, every
    // other number here is about the floors rather than about mathematics. (2) The
    // coherence report must show the dictionary is *not* a map today — if it already were,
    // M3a has nothing to fix and the plan is wrong.
    println!("\nM3a — coherence of the Order <-> Algebra dictionary:");
    let coh = coherence(&mut idx, &d, 6);
    println!(
        "  {} rows, {} distinct lefts, {} distinct right names ({} distinct right \
         *statements*)",
        coh.rows, coh.distinct_lefts, coh.distinct_rights, coh.distinct_right_statements
    );
    println!(
        "  {} right statements contested by more than one left; {} rows ({:.1}%) are in a \
         collision",
        coh.contested,
        coh.rows_in_collision,
        100.0 * coh.collision_rate()
    );
    for (name, n) in &coh.worst {
        println!("    x{n:<3} {name}");
    }
    assert!(
        coh.collision_rate() > 0.05,
        "the greedy dictionary is already almost a map ({:.1}% of rows in a collision), so \
         M3a's premise is wrong and the solver is not the fix",
        100.0 * coh.collision_rate()
    );

    // How much of the collision is contamination rather than the analogy itself? Two
    // sources were identified by review and confirmed: `theory_of`'s depth-2 rule files
    // `Mathlib.Algebra.Order.*` under "Algebra", so part of this dictionary is order theory
    // against itself; and the worst target is a typeclass instance whose extracted `kind`
    // is "theorem", which `theorems_only` cannot see. Subtracting both says how much of the
    // pathology a *selection* policy would still have to explain.
    println!("\nwith the contaminating families excluded:");
    let clean_opts = DictOptions {
        exclude_subprefix: vec!["Mathlib.Algebra.Order".to_string()],
        exclude_roles: vec!["inst*".to_string()],
        ..DictOptions::default()
    };
    let dc = dictionary(
        &mut idx,
        None,
        "Mathlib.Order",
        "Mathlib.Algebra",
        &cfg,
        &clean_opts,
    );
    let cohc = coherence(&mut idx, &dc, 4);
    println!(
        "  {} rows ({} lefts, {} right statements), {} rows ({:.1}%) in a collision",
        cohc.rows,
        cohc.distinct_lefts,
        cohc.distinct_right_statements,
        cohc.rows_in_collision,
        100.0 * cohc.collision_rate()
    );
    for (name, n) in &cohc.worst {
        println!("    x{n:<3} {name}");
    }
    println!(
        "  contamination accounts for {:.1} points of the collision rate; {:.1}% remains \
         and is the selection problem proper.",
        100.0 * (coh.collision_rate() - cohc.collision_rate()),
        100.0 * cohc.collision_rate()
    );
    // The load-bearing claim, asserted because it is the one that decides whether M3a's
    // remaining work is worth doing. Two alternative explanations for the incoherence were
    // proposed by review and both are real defects — but subtracting them moves the
    // collision rate by under a point, so neither explains it. If this ever drops low
    // enough to fail, the incoherence *was* contamination and a selection policy is the
    // wrong fix.
    assert!(
        cohc.collision_rate() > 0.50,
        "excluding the contaminating families leaves only {:.1}% of rows in a collision, so \
         the incoherence was contamination rather than greedy selection and M3a should be \
         re-planned around the exclusions instead of around a policy",
        100.0 * cohc.collision_rate()
    );

    // The policy sweep. Reported as a frontier rather than resolved into one answer:
    // §6 C5 asks for several Pareto-optimal dictionaries where the ambiguity is real, and
    // the operating points here are exactly that — coverage against coherence.
    println!("\npolicy sweep (the Pareto frontier C5 asks for, not one chosen answer):");
    for policy in [
        Policy::Unconstrained,
        Policy::ManyToOne { cap: 3 },
        Policy::ManyToOne { cap: 2 },
        Policy::Injective,
    ] {
        let (sel, states) = select(&d, policy);
        let c = coherence(&mut idx, &sel, 0);
        let unmatched = states
            .values()
            .filter(|s| matches!(s, LeftState::Unmatched { .. }))
            .count();
        let mean = if sel.rows.is_empty() {
            0.0
        } else {
            sel.rows.iter().map(|r| r.score).sum::<f32>() / sel.rows.len() as f32
        };
        println!(
            "  {:<20} {:>5} rows  {:>5} lefts  collision {:>5.1}%  mean score {:.3}  \
             {:>4} unmatched",
            format!("{policy:?}"),
            sel.rows.len(),
            c.distinct_lefts,
            100.0 * c.collision_rate(),
            mean,
            unmatched
        );
    }

    // Injective must actually be injective on real data, not only on the unit fixture.
    let (inj, _) = select(&d, Policy::Injective);
    let rights: Vec<&str> = inj.rows.iter().map(|r| r.right.as_str()).collect();
    let distinct: std::collections::BTreeSet<&str> = rights.iter().copied().collect();
    assert_eq!(
        rights.len(),
        distinct.len(),
        "Injective reused a right on the real dictionary"
    );

    println!("\nnegative control: shuffled mappings must be rejected (design §9):");
    let sc = shuffle_control(&mut idx, &d, &cfg);
    println!(
        "  genuine mean retention {:.3} vs shuffled {:.3}; genuine wins {:.1}% of pairs",
        sc.genuine_mean,
        sc.shuffled_mean,
        100.0 * sc.separation
    );
    println!(
        "  {} of {} shuffled pairs would still clear the floors ({:.1}%)",
        sc.shuffled_admitted,
        sc.pairs,
        100.0 * sc.shuffled_admitted as f32 / sc.pairs.max(1) as f32
    );
    assert!(
        sc.separation > 0.90,
        "genuine pairs beat shuffled ones only {:.1}% of the time — the dictionary is not \
         separating analogy from coincidence, and no downstream number is about analogy",
        100.0 * sc.separation
    );

    // Transport, on a row we can check by eye.
    println!("\ntransport:");
    for (l, r, subj) in [
        ("le_trans", "dvd_trans", "le_trans"),
        ("le_trans", "dvd_trans", "lt_trans"),
    ] {
        match transport(&mut idx, l, r, subj, Level::Carriers) {
            Ok(Transported::Exists { name, .. }) => {
                println!("  {subj} along ({l} ~ {r}) -> already exists as `{name}`")
            }
            Ok(Transported::Open { image }) => println!(
                "  {subj} along ({l} ~ {r}) -> open target: {}",
                &image[..image.len().min(110)]
            ),
            Err(e) => println!("  {subj} along ({l} ~ {r}) -> refused: {e}"),
        }
    }

    // Transporting a declaration along a row whose right side *is* that declaration's
    // partner must land on a name, not on open ground. This has to hold at every level,
    // and for a long time it did not: the index seals its arena after precomputing Exact,
    // Presentation and Shape, so an image built later compared unequal to those roots by
    // id and `transport` invented an open target. Carriers and Instances are erased
    // lazily, on the far side of the seal, which is why checking only the default level
    // kept this quiet. Sweeping the levels is the gate.
    println!("\ntransport must find an existing target at every level:");
    let mut open_at = Vec::new();
    for level in [
        Level::Exact,
        Level::Presentation,
        Level::Instances,
        Level::Carriers,
        Level::Shape,
    ] {
        match transport(&mut idx, "le_trans", "dvd_trans", "le_trans", level) {
            Ok(Transported::Exists { name, .. }) => println!("  {level:?}: exists as `{name}`"),
            Ok(Transported::Open { .. }) => {
                println!("  {level:?}: OPEN — but the image is `dvd_trans` itself");
                open_at.push(level);
            }
            Err(e) => println!("  {level:?}: refused: {e}"),
        }
    }
    assert!(
        open_at.is_empty(),
        "transporting `le_trans` along (le_trans ~ dvd_trans) is `dvd_trans`, a lemma the \
         slice has; reporting it open at {open_at:?} is the engine inventing research"
    );

    // The negative control: a row with a scoped variable must refuse rather than
    // transport wrongly.
    println!("\nnegative control: transporting a statement that does not match the row");
    match transport(
        &mut idx,
        "le_trans",
        "dvd_trans",
        "add_comm",
        Level::Carriers,
    ) {
        Err(e) => println!("  refused: {e}"),
        Ok(t) => {
            eprintln!("  transported anyway: {t:?} — the applicability check is missing");
            std::process::exit(1);
        }
    }
}
