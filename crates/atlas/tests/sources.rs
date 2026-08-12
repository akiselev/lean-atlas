//! M1 D3 — one test per retrieval source, on corpora built to isolate it.
//!
//! The index has three ways of proposing a candidate (`index.rs` header):
//!
//! * **A** — the whole-statement `Shape` bucket.
//! * **B** — concrete subterms of the `Presentation` erasure.
//! * **C** — `Shape` subterms of size ≥ 8.
//!
//! Aggregate recall cannot tell them apart, which is how source B ran dead for 60.6% of
//! the corpus while the recall gate read 64.6% and nobody could say why. These fixtures
//! are small enough that the source firing is the only thing that could have produced the
//! candidate.
//!
//! # The one thing that makes the B fixture worth writing
//!
//! B's postings are keyed on subterms of `erase(root, Presentation)` and were queried with
//! subterms of the raw root. On a corpus where those two coincide, the bug is invisible
//! and a fixture passes while the source is 95% dead on real data.
//!
//! `Presentation` erases exactly three things: universe levels become `*` (the level
//! *count* survives), `StrictImplicit` merges into `Implicit`, and `OfNat.ofNat T k inst`
//! collapses to the literal `k`. So a discriminating fixture must share a subterm
//! containing one of those. Both B cases below do — `level_carrying` shares a `Const` with
//! a universe level, `ofnat_collapse` shares an `OfNat.ofNat` application — and each is
//! checked against the ablation knob to confirm it genuinely fails the other way.

use atlas::skel::erase::Level;
use atlas::skel::index::{IndexConfig, SkeletonIndex, Sources};

/// A row in B1's JSONL shape. `module` and `kind` matter only where a test says so.
fn row(name: &str, stmt: &str) -> String {
    format!(r#"{{"name":"{name}","module":"T","kind":"theorem","stmt":"atlas-stmt-v1;{stmt}"}}"#)
}

fn corpus(rows: &[String]) -> String {
    rows.join("\n")
}

/// Thresholds low enough that a two-declaration corpus can trip them at all: the defaults
/// are fitted to 131k rows, where a size-3 subterm is common and a size-8 shape subterm is
/// a real signal. Every test says which knob it relies on.
fn cfg() -> IndexConfig {
    IndexConfig {
        min_concrete_closed: 3,
        min_concrete_open: 3,
        min_shape_sub: 3,
        min_common: 1,
        min_retention: 0.0,
        ..IndexConfig::default()
    }
}

fn sources_for(idx: &mut SkeletonIndex, query: &str, target: &str, cfg: &IndexConfig) -> Sources {
    let ns = idx.similar(query, 50, cfg).expect("query is in the slice");
    ns.iter()
        .find(|n| n.name == target)
        .unwrap_or_else(|| panic!("`{target}` was not a candidate for `{query}`: {ns:?}"))
        .sources
}

// ---------------------------------------------------------------------------
// A — the whole-statement shape bucket
// ---------------------------------------------------------------------------

#[test]
fn source_a_fires_for_two_statements_with_the_same_shape() {
    // `Foo x = x` and `Bar y = y`: different constants, identical shape.
    let c = corpus(&[
        row("a", "a(a(c(2:Eq,0),a(c(3:Foo,0),b0)),b0)"),
        row("b", "a(a(c(2:Eq,0),a(c(3:Bar,0),b0)),b0)"),
    ]);
    let cfg = cfg();
    let mut idx = SkeletonIndex::build(&c, &cfg).expect("build");
    assert!(
        sources_for(&mut idx, "a", "b", &cfg).has(Sources::SHAPE),
        "identical shapes must land in one bucket"
    );
}

#[test]
fn source_a_is_skipped_when_the_bucket_is_larger_than_max_bucket() {
    // The bucket is a tautology rather than a lead once it holds most of the corpus, and
    // the guard is a *config* decision — so it has to be observable from outside.
    let rows: Vec<String> = (0..6)
        .map(|i| row(&format!("d{i}"), "a(a(c(2:Eq,0),a(c(3:Foo,0),b0)),b0)"))
        .collect();
    let c = corpus(&rows);
    let narrow = IndexConfig {
        max_bucket: 2,
        ..cfg()
    };
    let mut idx = SkeletonIndex::build(&c, &narrow).expect("build");
    let ns = idx.similar("d0", 50, &narrow).expect("query");
    assert!(
        ns.iter().all(|n| !n.sources.has(Sources::SHAPE)),
        "a 6-member bucket over max_bucket=2 must not fire source A"
    );
}

// ---------------------------------------------------------------------------
// B — concrete subterms of the Presentation erasure
// ---------------------------------------------------------------------------

#[test]
fn source_b_fires_on_a_shared_subterm_whose_universe_levels_are_erased() {
    // The shared subterm is `a(c(3:Set,1,+(0)), c(3:Nat,0))` — headed by a `Const`
    // carrying one universe level. Under `Presentation` that level becomes `*`, so the
    // erased subterm is a *different term* from the raw one. Querying at the wrong level
    // therefore misses, which is what the ablation below asserts.
    let shared = "a(c(3:Set,1,+(0)),c(3:Nat,0))";
    let c = corpus(&[
        row("p", &format!("a(a(c(2:Eq,0),{shared}),c(1:x,0))")),
        row("q", &format!("a(a(c(2:Ne,0),{shared}),c(1:y,0))")),
    ]);
    let cfg = cfg();
    let mut idx = SkeletonIndex::build(&c, &cfg).expect("build");
    assert!(
        sources_for(&mut idx, "p", "q", &cfg).has(Sources::SUBTERM),
        "a shared concrete subterm above the size floor must fire source B"
    );
}

#[test]
fn the_b_fixture_actually_discriminates_the_normalization_bug() {
    // The negative control for the test above, and the reason it is written with a
    // level-carrying constant at all. With the query taken at the raw root instead of at
    // the level the postings were built at, source B must go silent — otherwise the
    // fixture would have passed while the source was dead on real data, which is exactly
    // what happened for as long as this bug lived.
    let shared = "a(c(3:Set,1,+(0)),c(3:Nat,0))";
    let c = corpus(&[
        row("p", &format!("a(a(c(2:Eq,0),{shared}),c(1:x,0))")),
        row("q", &format!("a(a(c(2:Ne,0),{shared}),c(1:y,0))")),
    ]);
    let broken = IndexConfig {
        source_b_at_build_level: false,
        ..cfg()
    };
    let mut idx = SkeletonIndex::build(&c, &broken).expect("build");
    let ns = idx.similar("p", 50, &broken).expect("query");
    let b_fired = ns
        .iter()
        .find(|n| n.name == "q")
        .is_some_and(|n| n.sources.has(Sources::SUBTERM));
    assert!(
        !b_fired,
        "querying at the raw root must miss a subterm whose universe levels the postings \
         erased — if this passes, the fixture cannot detect the bug it exists for"
    );
}

#[test]
fn source_b_sees_through_the_ofnat_collapse() {
    // `Presentation`'s other rewrite: `OfNat.ofNat T k inst` collapses to the literal `k`.
    // So `2` written through `OfNat` and `2` written bare share a posting key *after*
    // erasure and share nothing before it — a second, independent way for the query level
    // to matter.
    let ofnat = "a(a(a(c(11:OfNat.ofNat,1,0),c(3:Nat,0)),n2),c(12:instOfNatNat,0))";
    let c = corpus(&[
        row("viaofnat", &format!("a(a(c(2:Eq,0),{ofnat}),{ofnat})")),
        row("bare", "a(a(c(2:Eq,0),n2),n2)"),
    ]);
    let cfg = cfg();
    let mut idx = SkeletonIndex::build(&c, &cfg).expect("build");
    let g = idx
        .generalize_named("viaofnat", "bare", Level::Presentation)
        .expect("both are in the slice");
    assert_eq!(
        g.1,
        idx.skeleton_of("bare", Level::Presentation).unwrap(),
        "at `presentation` the two statements are the same term, so their skeleton is that \
         term rather than a variable"
    );
}

// ---------------------------------------------------------------------------
// C — Shape subterms
// ---------------------------------------------------------------------------

#[test]
fn source_c_fires_where_no_concrete_subterm_is_shared_at_all() {
    // The source that carries the design (`index.rs` header): `le_trans` reaches
    // `dvd_trans` with no shared concrete subterm. Here the two statements share *no*
    // constant — every name differs — so A and B have nothing to work with and only the
    // shape-subterm postings can propose the pair.
    let c = corpus(&[
        row(
            "left",
            "a(a(c(2:Le,0),a(a(c(3:Add,0),b0),b1)),a(a(c(3:Add,0),b1),b0))",
        ),
        row(
            "right",
            "a(a(c(3:Dvd,0),a(a(c(3:Mul,0),b0),b1)),a(a(c(3:Mul,0),b1),b0))",
        ),
    ]);
    let cfg = cfg();
    let mut idx = SkeletonIndex::build(&c, &cfg).expect("build");
    let s = sources_for(&mut idx, "left", "right", &cfg);
    assert!(
        s.has(Sources::SHAPE_SUBTERM),
        "shape subterms are the only source that can see this pair, got {s:?}"
    );
    assert!(
        !s.has(Sources::SUBTERM),
        "the two share no constant, so no concrete subterm can be shared: {s:?}"
    );
}

#[test]
fn source_c_respects_its_size_floor() {
    // The floor is what keeps punctuation out of the postings. Below it, the same pair
    // must not be proposed by C at all.
    let c = corpus(&[
        row(
            "left",
            "a(a(c(2:Le,0),a(a(c(3:Add,0),b0),b1)),a(a(c(3:Add,0),b1),b0))",
        ),
        row(
            "right",
            "a(a(c(3:Dvd,0),a(a(c(3:Mul,0),b0),b1)),a(a(c(3:Mul,0),b1),b0))",
        ),
    ]);
    let high = IndexConfig {
        min_shape_sub: 100,
        ..cfg()
    };
    let mut idx = SkeletonIndex::build(&c, &high).expect("build");
    let ns = idx.similar("left", 50, &high).expect("query");
    assert!(
        ns.iter().all(|n| !n.sources.has(Sources::SHAPE_SUBTERM)),
        "no shape subterm reaches size 100, so source C must contribute nothing"
    );
}

// ---------------------------------------------------------------------------
// Work-budget posting admission (prefilter §10 S1, findings §66)
// ---------------------------------------------------------------------------
//
// The defect these fixtures pin: `max_posting_fraction` drops a key by holder count, and
// the keys cross-theory analogy rides on are precisely the *common* ones — measured 0/4
// pre-registered classical<->quantum correspondences at the shipped cutoff, 4/4 with the
// keys admitted. The fixture is built so it can fail in both directions (§5's per-source
// trap): the only route from `p` to `q` is one concrete subterm key crowded over the
// cutoff, so the positive case proves admission and each ablation proves one half of the
// knob — `None` that the cutoff still drops the key, `Some(0)` that the walk bound is
// real and not a synonym for admission.

/// `p` and `q` share exactly one concrete subterm, and three crowd rows push that key's
/// document frequency over the cutoff. `q` carries a binder prefix so the two only align
/// at the conclusion anchor — the setting cross-theory retrieval actually runs at — and
/// so their shapes differ, keeping source A out of the way.
fn crowded_key_corpus() -> String {
    let shared = "a(c(5:LE.le,0),c(4:Real,0))";
    corpus(&[
        row("p", &format!("a({shared},c(1:x,0))")),
        row("q", &format!("pi(s(0),a({shared},b0))")),
        row("c0", &format!("a(a(c(2:Eq,0),{shared}),c(1:u,0))")),
        row("c1", &format!("a(a(c(2:Eq,0),{shared}),c(1:v,0))")),
        row("c2", &format!("a(a(c(2:Eq,0),{shared}),c(1:w,0))")),
    ])
}

/// `min_posting_len: 2` puts the five-holder shared key over the cutoff on a five-row
/// corpus — the regime the shipped constants only reach at Mathlib scale (§5c: the
/// fraction *tightens* as a corpus grows).
fn budget_cfg(posting_work_budget: Option<usize>) -> IndexConfig {
    IndexConfig {
        min_posting_len: 2,
        min_common: 1,
        min_retention: 0.0,
        anchor: atlas::skel::index::Anchor::Conclusion,
        posting_work_budget,
        ..IndexConfig::default()
    }
}

#[test]
fn the_work_budget_admits_the_crowded_key_the_cutoff_drops() {
    let c = crowded_key_corpus();
    let on = budget_cfg(Some(1_000));
    let off = budget_cfg(None);
    let mut idx_on = SkeletonIndex::build(&c, &on).expect("build");
    let idx_off = SkeletonIndex::build(&c, &off).expect("build");
    // Admission is observable on the index itself, not only through a query: the
    // budget build must hold keys the cutoff build does not.
    assert!(
        idx_on.key_counts().0 > idx_off.key_counts().0,
        "keep-all admission must retain concrete keys the cutoff drops: {:?} vs {:?}",
        idx_on.key_counts(),
        idx_off.key_counts()
    );
    assert!(
        sources_for(&mut idx_on, "p", "q", &on).has(Sources::SUBTERM),
        "the crowded key is the only route to `q`, so admitting it must fire source B"
    );
}

#[test]
fn without_the_budget_the_fraction_cutoff_silences_the_same_pair() {
    // The ablation that makes the positive case a measurement (CLAUDE.md §5): if `q`
    // arrives with the knob off, the fixture's key was never over the cutoff and the
    // test above passes whatever the admission rule does.
    let c = crowded_key_corpus();
    let off = budget_cfg(None);
    let mut idx = SkeletonIndex::build(&c, &off).expect("build");
    let ns = idx.similar("p", 50, &off).expect("query");
    assert!(
        !ns.iter().any(|n| n.name == "q"),
        "the five-holder key must be over the two-holder cutoff, so `q` has no route: {ns:?}"
    );
}

#[test]
fn a_zero_budget_walks_no_postings_even_though_the_keys_are_admitted() {
    // Separates the knob's two halves: `Some(0)` builds the same keep-all index as any
    // other `Some`, so if `q` still arrives, the walk bound is decorative and the recall
    // gain above is admission alone wearing a budget's name.
    let c = crowded_key_corpus();
    let starved = budget_cfg(Some(0));
    let mut idx = SkeletonIndex::build(&c, &starved).expect("build");
    let ns = idx.similar("p", 50, &starved).expect("query");
    assert!(
        ns.iter()
            .all(|n| !n.sources.has(Sources::SUBTERM) && !n.sources.has(Sources::SHAPE_SUBTERM)),
        "zero postings walked must starve sources B and C: {ns:?}"
    );
    assert!(
        !ns.iter().any(|n| n.name == "q"),
        "`q`'s only route is a posting, and none may be walked at budget 0: {ns:?}"
    );
}

/// The knob against the real slice, in both directions.
///
/// With every key admitted and the walk unbounded, the candidate set can only grow — the
/// budget walk's prefix is byte-identical to the shipped walk, so anything the cutoff
/// found is still found. With the walk bound at zero, sources B and C must go silent on a
/// corpus where they otherwise dominate. Between them the two assertions pin that the
/// admission half and the walk half each do their own work at scale, not just on a
/// five-row fixture.
#[test]
fn on_the_real_slice_the_budget_grows_candidates_monotonically() {
    let Ok(path) = std::env::var("ATLAS_SLICE") else {
        println!("SKIPPED: set ATLAS_SLICE to a B1 JSONL slice for the work-budget gate");
        return;
    };
    let src = std::fs::read_to_string(&path).expect("read slice");
    let off = IndexConfig::default();
    let idx_off = SkeletonIndex::build(&src, &off).expect("build");
    let unbounded = IndexConfig {
        posting_work_budget: Some(usize::MAX),
        ..IndexConfig::default()
    };
    let idx_on = SkeletonIndex::build(&src, &unbounded).expect("build");

    let (con_off, shp_off) = idx_off.key_counts();
    let (con_on, shp_on) = idx_on.key_counts();
    assert!(
        con_on > con_off,
        "the cutoff drops real concrete keys on this corpus, so keep-all must hold more: \
         {con_on} vs {con_off}"
    );
    assert!(
        shp_on >= shp_off,
        "keep-all admission must never hold fewer shape keys: {shp_on} vs {shp_off}"
    );

    let starved = IndexConfig {
        posting_work_budget: Some(0),
        ..IndexConfig::default()
    };
    for q in ["le_trans", "Nat.mul_comm", "And.comm"] {
        let d = idx_off.id_of(q).expect("query is in the slice");
        let base: std::collections::BTreeSet<_> = idx_off
            .candidates(d, &off)
            .into_iter()
            .map(|(d, _, _)| d)
            .collect();
        let wide: std::collections::BTreeSet<_> = idx_on
            .candidates(d, &unbounded)
            .into_iter()
            .map(|(d, _, _)| d)
            .collect();
        let lost: Vec<_> = base.difference(&wide).collect();
        assert!(
            lost.is_empty(),
            "an unbounded work budget must be a superset of the shipped walk for `{q}`, \
             lost {lost:?}"
        );
        // The paired direction on the same index: a zero budget must starve B and C, so
        // every surviving candidate arrived through the shape bucket alone.
        for (_, sources, _) in idx_on.candidates(d, &starved) {
            assert!(
                sources.has(Sources::SHAPE)
                    && !sources.has(Sources::SUBTERM)
                    && !sources.has(Sources::SHAPE_SUBTERM),
                "budget 0 walked a posting for `{q}`: {sources:?}"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// The differential, in the direction that has content
// ---------------------------------------------------------------------------

#[test]
fn the_prefilter_over_generates_rather_than_under_generates() {
    // Stated the other way round — `candidates ⊆ brute` — this is false by construction
    // and would fail on the first query: `candidates` applies no score and no thresholds
    // and returns hundreds of rows, while `similar_brute` filters by `min_common` and
    // `min_retention` and truncates to `top`. Over-generation is a prefilter's job.
    //
    // The property with content is the converse: what brute force ranks highest must be
    // *reachable* through the prefilter. That is the claim a lost candidate violates, and
    // it is the one worth asserting.
    let Ok(path) = std::env::var("ATLAS_SLICE") else {
        println!("SKIPPED: set ATLAS_SLICE to a B1 JSONL slice for the differential");
        return;
    };
    let src = std::fs::read_to_string(&path).expect("read slice");
    let cfg = IndexConfig::default();
    let mut idx = SkeletonIndex::build(&src, &cfg).expect("build index");

    for q in ["le_trans", "Nat.mul_comm", "And.comm"] {
        let truth: Vec<String> = idx
            .similar_brute(q, 5, &cfg)
            .expect("brute")
            .into_iter()
            .map(|(n, _)| n)
            .collect();
        if truth.is_empty() {
            continue;
        }
        let reachable: std::collections::HashSet<String> = idx
            .similar(q, 500, &cfg)
            .expect("indexed")
            .into_iter()
            .map(|n| n.name)
            .collect();
        let lost: Vec<&String> = truth.iter().filter(|t| !reachable.contains(*t)).collect();
        assert!(
            lost.is_empty(),
            "the prefilter lost brute force's top-5 for `{q}`: {lost:?}"
        );
    }
}
