use atlas_logic::*;
use atlas_schema::{
    Derivation, FactId, FactRow, FactWarrant, Provenance, RelationTypeId, SourceEvidence, Value,
};
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

fn reachability_program(edge: RelationTypeId, reach: RelationTypeId) -> Program {
    Program {
        rules: vec![
            Rule {
                id: "reach.base".into(),
                head: atom(reach, v("x"), v("y")),
                body: vec![Literal::Pos(atom(edge, v("x"), v("y")))],
            },
            Rule {
                id: "reach.step".into(),
                head: atom(reach, v("x"), v("z")),
                body: vec![
                    Literal::Pos(atom(reach, v("x"), v("y"))),
                    Literal::Pos(atom(edge, v("y"), v("z"))),
                ],
            },
        ],
    }
}

fn reachability_query(reach: RelationTypeId) -> Query {
    Query {
        project: vec!["x".into(), "y".into()],
        body: vec![Literal::Pos(atom(reach, v("x"), v("y")))],
        limit: None,
    }
}

proptest! {
    #[test]
    fn optimized_matches_reference(edges in prop::collection::vec((0u8..6,0u8..6), 0..20)) {
        let edge=RelationTypeId(1); let reach=RelationTypeId(2);
        let facts=edges.into_iter().filter(|(a,b)|a!=b).enumerate().map(|(i,(a,b))| FactRow{
            id:FactId(i as u64+1), relation:edge,
            args:vec![Value::Integer(a as i64),Value::Integer(b as i64)],
            warrant:FactWarrant::Structural,
            provenance:Provenance::Source{
                source:"generated".into(),
                evidence:SourceEvidence::Structural,
            },
        }).collect::<Vec<_>>();
        let source=MemoryFacts::new(facts);
        let program=reachability_program(edge, reach);
        let query=reachability_query(reach);
        let opts=EvalOptions{max_rounds:64,max_results:10_000};
        let reference=evaluate_reference(&source,&program,&query,opts).unwrap();
        let optimized=evaluate_optimized(&source,&program,&query,opts,&CancellationToken::default()).unwrap();
        prop_assert_eq!(optimized,reference);
    }
}

#[test]
fn heuristic_support_cannot_be_upgraded_by_derivation() {
    let edge = RelationTypeId(1);
    let reach = RelationTypeId(2);
    let source = MemoryFacts::new(vec![FactRow {
        id: FactId(1),
        relation: edge,
        args: vec![Value::Integer(1), Value::Integer(2)],
        warrant: FactWarrant::Heuristic,
        provenance: Provenance::Source {
            source: "numerical-fit".into(),
            evidence: SourceEvidence::Numerical,
        },
    }]);
    let program = Program {
        rules: vec![Rule {
            id: "reach.base".into(),
            head: atom(reach, v("x"), v("y")),
            body: vec![Literal::Pos(atom(edge, v("x"), v("y")))],
        }],
    };
    let query = reachability_query(reach);
    let opts = EvalOptions::default();
    let reference = evaluate_reference(&source, &program, &query, opts).unwrap();
    let optimized = evaluate_optimized(
        &source,
        &program,
        &query,
        opts,
        &CancellationToken::default(),
    )
    .unwrap();
    assert_eq!(optimized, reference);
    let derived = reference
        .facts
        .iter()
        .find(|fact| fact.relation == reach)
        .expect("reach fact");
    assert_eq!(derived.warrant, FactWarrant::Heuristic);
}

#[test]
fn duplicate_supports_are_order_invariant_and_explain_every_alternative() {
    let edge = RelationTypeId(1);
    let reach = RelationTypeId(2);
    let structural = FactRow {
        id: FactId(10),
        relation: edge,
        args: vec![Value::Text("A".into()), Value::Text("B".into())],
        warrant: FactWarrant::Structural,
        provenance: Provenance::Source {
            source: "lean-structure".into(),
            evidence: SourceEvidence::Structural,
        },
    };
    let heuristic = FactRow {
        id: FactId(20),
        relation: edge,
        args: structural.args.clone(),
        warrant: FactWarrant::Heuristic,
        provenance: Provenance::Source {
            source: "numerical-candidate".into(),
            evidence: SourceEvidence::Numerical,
        },
    };
    let program = Program {
        rules: vec![Rule {
            id: "reach.base".into(),
            head: atom(reach, v("x"), v("y")),
            body: vec![Literal::Pos(atom(edge, v("x"), v("y")))],
        }],
    };
    let query = reachability_query(reach);
    let opts = EvalOptions::default();

    let forward = MemoryFacts::new(vec![heuristic.clone(), structural.clone()]);
    let reverse = MemoryFacts::new(vec![structural.clone(), heuristic.clone()]);
    let reference_forward = evaluate_reference(&forward, &program, &query, opts).unwrap();
    let reference_reverse = evaluate_reference(&reverse, &program, &query, opts).unwrap();
    let optimized_forward = evaluate_optimized(
        &forward,
        &program,
        &query,
        opts,
        &CancellationToken::default(),
    )
    .unwrap();
    let optimized_reverse = evaluate_optimized(
        &reverse,
        &program,
        &query,
        opts,
        &CancellationToken::default(),
    )
    .unwrap();

    assert_eq!(reference_forward, reference_reverse);
    assert_eq!(optimized_forward, optimized_reverse);
    assert_eq!(optimized_forward, reference_forward);

    let derived = reference_forward
        .facts
        .iter()
        .find(|fact| fact.relation == reach)
        .expect("reach fact");
    assert_eq!(derived.warrant, FactWarrant::Structural);
    let derivations = derived.provenance.derivations();
    assert_eq!(derivations.len(), 2);
    assert!(derivations.contains(&Derivation::new("reach.base", vec![FactId(10)])));
    assert!(derivations.contains(&Derivation::new("reach.base", vec![FactId(20)])));

    let explanation = reference_forward.explain(derived.id).expect("explanation");
    assert_eq!(explanation.derivations.len(), 2);
    assert_eq!(
        explanation
            .derivations
            .iter()
            .map(|alternative| alternative.warrant)
            .collect::<std::collections::BTreeSet<_>>(),
        [FactWarrant::Heuristic, FactWarrant::Structural]
            .into_iter()
            .collect()
    );
    let strongest = explanation
        .strongest_derivation
        .expect("strongest derivation id");
    let strongest_alternative = explanation
        .derivations
        .iter()
        .find(|alternative| alternative.derivation.id == strongest)
        .unwrap();
    assert_eq!(strongest_alternative.warrant, FactWarrant::Structural);
    assert_eq!(strongest_alternative.derivation.inputs, vec![FactId(10)]);
}

#[test]
fn stronger_alternative_propagates_through_recursive_derivations() {
    let edge = RelationTypeId(1);
    let reach = RelationTypeId(2);
    let facts = vec![
        FactRow {
            id: FactId(1),
            relation: edge,
            args: vec![Value::Text("A".into()), Value::Text("B".into())],
            warrant: FactWarrant::Heuristic,
            provenance: Provenance::Source {
                source: "candidate".into(),
                evidence: SourceEvidence::Numerical,
            },
        },
        FactRow {
            id: FactId(2),
            relation: edge,
            args: vec![Value::Text("A".into()), Value::Text("B".into())],
            warrant: FactWarrant::Structural,
            provenance: Provenance::Source {
                source: "structure".into(),
                evidence: SourceEvidence::Structural,
            },
        },
        FactRow {
            id: FactId(3),
            relation: edge,
            args: vec![Value::Text("B".into()), Value::Text("C".into())],
            warrant: FactWarrant::Structural,
            provenance: Provenance::Source {
                source: "structure".into(),
                evidence: SourceEvidence::Structural,
            },
        },
    ];
    let source = MemoryFacts::new(facts);
    let program = reachability_program(edge, reach);
    let query = reachability_query(reach);
    let reference = evaluate_reference(&source, &program, &query, EvalOptions::default()).unwrap();
    let optimized = evaluate_optimized(
        &source,
        &program,
        &query,
        EvalOptions::default(),
        &CancellationToken::default(),
    )
    .unwrap();
    assert_eq!(optimized, reference);

    let ac = reference
        .facts
        .iter()
        .find(|fact| {
            fact.relation == reach
                && fact.args == vec![Value::Text("A".into()), Value::Text("C".into())]
        })
        .expect("reach A C");
    assert_eq!(ac.warrant, FactWarrant::Structural);
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
