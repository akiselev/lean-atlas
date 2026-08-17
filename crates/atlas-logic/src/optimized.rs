use crate::{eval,EvalOptions,FactSource,Literal,LogicError,Program,Query,QueryRow,Term};
use atlas_schema::{Bindings,FactId,FactRow,FactWarrant,Provenance,RelationTypeId,Value};
use std::collections::{BTreeMap,BTreeSet};
use std::sync::{Arc,atomic::{AtomicBool,Ordering}};

#[derive(Clone,Default)]
pub struct CancellationToken(Arc<AtomicBool>);
impl CancellationToken{
    pub fn cancel(&self){self.0.store(true,Ordering::Release)}
    pub fn is_cancelled(&self)->bool{self.0.load(Ordering::Acquire)}
}

/// Semi-naive fixed point. After the seed round each recursive evaluation consumes at least
/// one fact from the previous delta; results are deterministic and bounded.
pub fn evaluate_optimized<S:FactSource>(source:&S,p:&Program,q:&Query,opts:EvalOptions,cancel:&CancellationToken)->Result<crate::Evaluation,LogicError>{
    let strata=eval::validate(p)?;
    let mut rels=BTreeSet::new();
    for r in &p.rules{rels.insert(r.head.relation);for l in &r.body{if let Literal::Pos(a)|Literal::Neg(a)=l{rels.insert(a.relation);}}}
    for l in &q.body{if let Literal::Pos(a)|Literal::Neg(a)=l{rels.insert(a.relation);}}
    let empty=Bindings::new();
    let mut db:BTreeMap<RelationTypeId,Vec<FactRow>>=BTreeMap::new();
    for r in rels{db.entry(r).or_default().extend(source.scan(r,&empty)?)}
    let mut seen:BTreeSet<(RelationTypeId,Vec<Value>)>=db.iter().flat_map(|(r,fs)|fs.iter().map(move|f|(*r,f.args.clone()))).collect();
    let mut next=db.values().flatten().map(|f|f.id.0).max().unwrap_or(0)+1;

    for s in 0..=strata.values().copied().max().unwrap_or(0){
        let mut delta:BTreeMap<RelationTypeId,Vec<FactRow>>=BTreeMap::new();
        for round in 0..opts.max_rounds{
            if cancel.is_cancelled(){return Err(LogicError::Cancelled)}
            let mut produced:BTreeMap<RelationTypeId,Vec<FactRow>>=BTreeMap::new();
            for rule in p.rules.iter().filter(|r|strata.get(&r.head.relation).copied().unwrap_or(0)==s){
                let positives=rule.body.iter().enumerate().filter_map(|(i,l)|matches!(l,Literal::Pos(_)).then_some(i)).collect::<Vec<_>>();
                let states=if round==0{
                    eval::body(&db,&rule.body)?
                }else{
                    let mut all=Vec::new();
                    for i in positives{all.extend(body_delta(&db,&delta,&rule.body,i)?)}
                    all
                };
                for(b,support)in states{
                    let Some(args)=rule.head.terms.iter().map(|t|crate::source::eval_term(t,&b)).collect::<Option<Vec<_>>>() else{continue};
                    if seen.insert((rule.head.relation,args.clone())){
                        let f=FactRow{id:FactId(next),relation:rule.head.relation,args,warrant:FactWarrant::Structural,provenance:Provenance::Derived{rule:rule.id.clone(),inputs:support}};
                        next+=1;produced.entry(f.relation).or_default().push(f);
                    }
                }
            }
            if produced.values().all(Vec::is_empty){break}
            for(r,fs)in &produced{db.entry(*r).or_default().extend(fs.iter().cloned())}
            delta=produced;
            if round+1==opts.max_rounds{return Err(LogicError::RecursionLimit(opts.max_rounds))}
        }
    }

    let mut rows=eval::body(&db,&q.body)?.into_iter().map(|(b,s)|QueryRow{
        bindings:q.project.iter().filter_map(|n|b.get(n).cloned().map(|v|(n.clone(),v))).collect(),supporting_facts:s
    }).collect::<Vec<_>>();
    rows.sort_by(|a,b|a.bindings.cmp(&b.bindings));rows.dedup();rows.truncate(q.limit.unwrap_or(opts.max_results).min(opts.max_results));
    let mut facts=db.into_values().flatten().collect::<Vec<_>>();facts.sort_by_key(|f|f.id);
    Ok(crate::Evaluation{facts,rows})
}

fn body_delta(db:&BTreeMap<RelationTypeId,Vec<FactRow>>,delta:&BTreeMap<RelationTypeId,Vec<FactRow>>,lits:&[Literal],delta_at:usize)->Result<Vec<(Bindings,Vec<FactId>)>,LogicError>{
    let mut states=vec![(Bindings::new(),Vec::new())];
    for(i,l)in lits.iter().enumerate(){match l{
        Literal::Pos(a)=>{
            let rows=if i==delta_at{delta.get(&a.relation)}else{db.get(&a.relation)};
            let mut n=Vec::new();
            for(b,s)in states{for f in rows.into_iter().flatten(){if let Some(nb)=crate::source::bind_atom(&a.terms,&f.args,&b){let mut ns=s.clone();ns.push(f.id);n.push((nb,ns))}}}
            states=n;
        }
        Literal::Neg(a)=>states.retain(|(b,_)|!db.get(&a.relation).into_iter().flatten().any(|f|crate::source::bind_atom(&a.terms,&f.args,b).is_some())),
        Literal::Eq(a,b)=>{
            let mut out=Vec::new();
            for(mut bs,s)in states{
                match(crate::source::eval_term(a,&bs),crate::source::eval_term(b,&bs)){
                    (Some(x),Some(y)) if x==y=>out.push((bs,s)),
                    (None,Some(v))=>if let Term::Var(n)=a{bs.insert(n.clone(),v);out.push((bs,s))},
                    (Some(v),None)=>if let Term::Var(n)=b{bs.insert(n.clone(),v);out.push((bs,s))},
                    (None,None)=>if matches!((a,b),(Term::Var(x),Term::Var(y)) if x==y){out.push((bs,s))},
                    _=>{}
                }
            }
            states=out;
        }
    }if states.is_empty(){break}}
    Ok(states)
}
