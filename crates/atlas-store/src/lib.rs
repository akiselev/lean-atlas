mod migration;

use atlas_schema::{FactId,FactRow,FactWarrant,Provenance,RelationTypeId,Value};
use rusqlite::{params,Connection,OptionalExtension};
use std::path::Path;
use thiserror::Error;

#[derive(Debug,Error)]
pub enum StoreError{
    #[error(transparent)]Sql(#[from]rusqlite::Error),
    #[error(transparent)]Json(#[from]serde_json::Error),
    #[error("unknown warrant {0}")]InvalidWarrant(String),
}

pub struct Store{conn:Connection}
impl Store{
    pub fn open(path:impl AsRef<Path>)->Result<Self,StoreError>{let s=Self{conn:Connection::open(path)?};s.migrate()?;Ok(s)}
    pub fn memory()->Result<Self,StoreError>{let s=Self{conn:Connection::open_in_memory()?};s.migrate()?;Ok(s)}
    pub fn migrate(&self)->Result<(),StoreError>{self.conn.execute_batch(migration::V1)?;Ok(())}

    pub fn insert_fact(&mut self,f:&FactRow)->Result<(),StoreError>{
        let tx=self.conn.transaction()?;
        tx.execute("INSERT OR REPLACE INTO facts(id,relation_id,warrant,provenance_json)VALUES(?1,?2,?3,?4)",params![f.id.0,f.relation.0,warrant_name(f.warrant),serde_json::to_string(&f.provenance)?])?;
        tx.execute("DELETE FROM fact_args WHERE fact_id=?1",[f.id.0])?;
        for(i,v)in f.args.iter().enumerate(){tx.execute("INSERT INTO fact_args(fact_id,position,value_json)VALUES(?1,?2,?3)",params![f.id.0,i as i64,serde_json::to_string(v)?])?;}
        tx.commit()?;Ok(())
    }

    pub fn fact(&self,id:FactId)->Result<Option<FactRow>,StoreError>{
        let h:Option<(u64,String,String)>=self.conn.query_row("SELECT relation_id,warrant,provenance_json FROM facts WHERE id=?1",[id.0],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        let Some((rel,w,p))=h else{return Ok(None)};
        Ok(Some(FactRow{id,relation:RelationTypeId(rel),args:self.args(id)?,warrant:parse_warrant(&w)?,provenance:serde_json::from_str::<Provenance>(&p)?}))
    }

    pub fn scan(&self,rel:RelationTypeId)->Result<Vec<FactRow>,StoreError>{
        let mut q=self.conn.prepare("SELECT id,warrant,provenance_json FROM facts WHERE relation_id=?1 ORDER BY id")?;
        let h=q.query_map([rel.0],|r|Ok((r.get::<_,u64>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?)))?.collect::<Result<Vec<_>,_>>()?;
        h.into_iter().map(|(id,w,p)|Ok(FactRow{id:FactId(id),relation:rel,args:self.args(FactId(id))?,warrant:parse_warrant(&w)?,provenance:serde_json::from_str(&p)?})).collect()
    }

    fn args(&self,id:FactId)->Result<Vec<Value>,StoreError>{
        let mut q=self.conn.prepare("SELECT value_json FROM fact_args WHERE fact_id=?1 ORDER BY position")?;
        let raw=q.query_map([id.0],|r|r.get::<_,String>(0))?.collect::<Result<Vec<_>,_>>()?;
        raw.into_iter().map(|x|Ok(serde_json::from_str(&x)?)).collect()
    }
}

fn warrant_name(w:FactWarrant)->&'static str{match w{FactWarrant::Proved=>"proved",FactWarrant::Structural=>"structural",FactWarrant::Asserted=>"asserted",FactWarrant::Heuristic=>"heuristic"}}
fn parse_warrant(w:&str)->Result<FactWarrant,StoreError>{Ok(match w{"proved"=>FactWarrant::Proved,"structural"=>FactWarrant::Structural,"asserted"=>FactWarrant::Asserted,"heuristic"=>FactWarrant::Heuristic,_=>return Err(StoreError::InvalidWarrant(w.into()))})}

#[cfg(test)]mod tests{use super::*;#[test]fn roundtrip(){let mut s=Store::memory().unwrap();let f=FactRow{id:FactId(1),relation:RelationTypeId(2),args:vec![Value::Text("x".into())],warrant:FactWarrant::Structural,provenance:Provenance::Source{source:"fixture".into()}};s.insert_fact(&f).unwrap();assert_eq!(s.fact(f.id).unwrap(),Some(f));}}
