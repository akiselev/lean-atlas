//! What was retrieval source B's normalization mismatch worth? (repaired; kept as the record)
//!
//! The postings are built from the subterms of `erase(root, Presentation)`, and source B
//! *used to be* queried with the subterms of the raw `root`. Those are different term sets whenever presentation erasure
//! changes anything, and the arena is hash-consed, so a term that differs at all differs
//! in its `TermId` and the posting lookup simply misses.
//!
//! This probe measures the gap directly rather than inferring it: for a sample of
//! declarations, how many of the query's raw subterms hit a posting, versus how many of
//! its *presentation-erased* subterms would have?
//!
//! A good answer, stated before the run: if the two are equal, the mismatch is harmless
//! and the plan's claim is wrong. If the erased side hits substantially more keys, source
//! B is degraded and the recall gate's 64.6% has an explanation.

use atlas::skel::erase::Level;
use atlas::skel::index::{IndexConfig, SkeletonIndex};

fn main() {
    let path = std::env::args().nth(1).expect("usage: sourcecheck <jsonl>");
    let src = std::fs::read_to_string(&path).expect("read slice");
    let cfg = IndexConfig::default();
    let mut idx = SkeletonIndex::build(&src, &cfg).expect("build index");
    println!("index: {} declarations", idx.len());

    let (mut raw_hits, mut pres_hits, mut raw_keys, mut pres_keys) =
        (0usize, 0usize, 0usize, 0usize);
    let (mut raw_dead, mut pres_dead) = (0usize, 0usize);
    let sample = idx.len().min(4000);
    // A fixed stride rather than a random sample: reproducible, and it walks the whole
    // slice rather than clustering in whatever module happens to sort first.
    let stride = (idx.len() / sample).max(1);

    for i in (0..idx.len()).step_by(stride).take(sample) {
        let (r, p) = idx.subterm_key_hits(i);
        raw_keys += r.0;
        raw_hits += r.1;
        pres_keys += p.0;
        pres_hits += p.1;
        if r.1 == 0 {
            raw_dead += 1;
        }
        if p.1 == 0 {
            pres_dead += 1;
        }
    }

    let n = (0..idx.len()).step_by(stride).take(sample).count();
    println!("\nsampled {n} declarations (stride {stride})\n");
    println!("as source B was queried BEFORE the fix — subterms of the RAW root:");
    println!("  {raw_keys} subterms above the size floor, {raw_hits} of them hit a posting");
    println!(
        "  {raw_dead} declarations ({:.1}%) get NO source-B candidate at all",
        100.0 * raw_dead as f32 / n as f32
    );
    println!("\nas the postings were BUILT — subterms of erase(root, Presentation):");
    println!("  {pres_keys} subterms above the size floor, {pres_hits} of them hit a posting");
    println!(
        "  {pres_dead} declarations ({:.1}%) get NO source-B candidate at all",
        100.0 * pres_dead as f32 / n as f32
    );

    // The gap is a property of the two term sets, not of what `candidates` does, so this
    // number does not move when the query level is repaired. It is the record of what the
    // defect cost, not a check that it is gone — `recallcheck`'s ablation is that.
    //
    // "12.7x more" is a ratio of *postings hit*, over slightly FEWER keys. The pres arm's
    // hit rate is also close to a ceiling by construction: the postings were built from
    // exactly these subterms, so anything below 100% is `max_posting_fraction` dropping a
    // key rather than a miss.
    println!(
        "\nthe mismatch cost {:.1}x in postings hit ({pres_hits} vs {raw_hits}), over \
         slightly fewer keys ({pres_keys} vs {raw_keys}).",
        pres_hits as f32 / raw_hits.max(1) as f32
    );
    println!(
        "the pres arm is near a ceiling by construction: those subterms built the postings, \
         so its shortfall is `max_posting_fraction` dropping keys, not misses."
    );
    let _ = Level::Presentation;
}
