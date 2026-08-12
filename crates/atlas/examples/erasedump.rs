use atlas::skel::erase::{EraseCache, Level, Signatures, erase};
use atlas::skel::term::{Arena, TermId};

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let want: Vec<String> = std::env::args().skip(2).collect();
    let text = std::fs::read_to_string(&path).unwrap();
    let mut a = Arena::new();
    let mut sig_rows = Vec::new();
    let mut picked: Vec<(String, TermId)> = Vec::new();
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
            if want.iter().any(|w| w == name) {
                picked.push((name.to_string(), t));
            }
        }
    }
    let sigs = Signatures::from_rows(&a, sig_rows.into_iter());
    let mut cache = EraseCache::new();
    for (name, t) in &picked {
        println!("=== {name}");
        for &l in &Level::ALL {
            let e = erase(&mut a, &sigs, &mut cache, *t, l);
            let r = a.render(e);
            println!("  {:>12}: {}", l.name(), &r[..r.len().min(240)]);
        }
    }
}
