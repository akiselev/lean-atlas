use atlas_logic::*;
use atlas_schema::{FactId, FactRow, FactWarrant, Provenance, RelationTypeId, Value};
use proptest::prelude::*;

fn atom(rel: RelationTypeId, a: Term, b: Term) -> Atom {
    Atom {
        relation: rel,
        terms: vec![a, b],
    }
}
fn v(name: &str) -> Term {
    Term::Var(name.into())
}

proptest! {
    #[test]
    fn optimized_matches_reference(edges in prop::collection::vec((0u8..6,0u8..6), 0..20)) {
        let edge=RelationTypeId(1); let reach=RelationTypeId(2);
        let facts=edges.into_iter().filter(|(a,b)|a!=b).enumerate().map(|(i,(a,b))| FactRow{
            id:FactId(i as u64+1), relation:edge,
            args:vec![Value::Integer(a as i64),Value::Integer(b as i64)],
            warrant:FactWarrant::Structural,
            provenance:Provenance::Source{source:"generated".into()},
        }).collect::<Vec<_>>();
        let source=MemoryFacts::new(facts);
        let program=Program{rules:vec![
            Rule{id:"reach.base".into(),head:atom(reach,v("x"),v("y")),body:vec![Literal::Pos(atom(edge,v("x"),v("y")))]},
            Rule{id:"reach.step".into(),head:atom(reach,v("x"),v("z")),body:vec![Literal::Pos(atom(reach,v("x"),v("y"))),Literal::Pos(atom(edge,v("y"),v("z")))]},
        ]};
        let query=Query{project:vec!["x".into(),"y".into()],body:vec![Literal::Pos(atom(reach,v("x"),v("y")))],limit:None};
        let opts=EvalOptions{max_rounds:64,max_results:10_000};
        let reference=evaluate_reference(&source,&program,&query,opts).unwrap();
        let optimized=evaluate_optimized(&source,&program,&query,opts,&CancellationToken::default()).unwrap();
        prop_assert_eq!(optimized,reference);
    }
}

#[test]
fn optimized_honors_cancellation() {
    let token = CancellationToken::default();
    token.cancel();
    let result = evaluate_optimized(
        &MemoryFacts::default(),
        &Program::default(),
        &Query {
            project: vec![],
            body: vec![],
            limit: None,
        },
        EvalOptions::default(),
        &token,
    );
    assert!(matches!(result, Err(LogicError::Cancelled)));
}
