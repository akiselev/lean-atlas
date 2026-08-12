fn main() {
    let path = std::env::args().nth(1).unwrap();
    let text = std::fs::read_to_string(&path).unwrap();
    let mut a = atlas::skel::term::Arena::new();
    let (mut ok, mut fail, mut roundtrip_fail, mut nodes_built) = (0u64, 0u64, 0u64, 0u64);
    let mut first: Option<String> = None;
    let t0 = std::time::Instant::now();
    for line in text.lines() {
        let Ok(v) = atlas::json::parse(line) else {
            continue;
        };
        let Some(stmt) = v.get("stmt").and_then(|s| s.as_str()) else {
            continue;
        };
        match a.parse(stmt) {
            Ok(t) => {
                ok += 1;
                nodes_built += a.size(t) as u64;
                // Rendering is the parser's inverse: a mismatch is a parse bug.
                if format!("atlas-stmt-v1;{}", a.render(t)) != stmt {
                    roundtrip_fail += 1;
                    if first.is_none() {
                        first = Some(stmt.to_string());
                    }
                }
            }
            Err(e) => {
                fail += 1;
                if first.is_none() {
                    first = Some(format!("{e}: {stmt}"));
                }
            }
        }
    }
    println!("parsed  {ok}\nfailed  {fail}\nround-trip mismatches {roundtrip_fail}");
    println!(
        "tree nodes {nodes_built} -> {} distinct ({:.1}x sharing)",
        a.node_count(),
        nodes_built as f64 / a.node_count() as f64
    );
    println!(
        "symbols {}   elapsed {:.2}s",
        a.sym_count(),
        t0.elapsed().as_secs_f64()
    );
    if let Some(f) = first {
        println!("first problem: {}", &f[..f.len().min(300)]);
    }
}
