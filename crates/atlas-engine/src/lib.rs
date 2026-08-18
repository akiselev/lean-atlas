pub mod runtime;

use atlas_lean_client::{ClientError, LeanClient};
use atlas_lean_protocol as protocol;
use atlas_logic::{FactSource, LogicError};
use atlas_schema::{Bindings, FactRow, RelationTypeId};
use atlas_store::Store;

pub struct StoreFacts<'a>(pub &'a Store);
impl FactSource for StoreFacts<'_> {
    fn scan(
        &self,
        relation: RelationTypeId,
        _bindings: &Bindings,
    ) -> Result<Box<dyn Iterator<Item = FactRow> + '_>, LogicError> {
        let rows = self
            .0
            .scan(relation)
            .map_err(|e| LogicError::Source(e.to_string()))?;
        Ok(Box::new(rows.into_iter()))
    }
}

pub struct LeanOracle<'a> {
    client: &'a mut LeanClient,
}
impl<'a> LeanOracle<'a> {
    pub fn new(client: &'a mut LeanClient) -> Self {
        Self { client }
    }

    pub async fn hello(
        &mut self,
        position: protocol::Position,
    ) -> Result<protocol::HelloResponse, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::HELLO,
                &protocol::HelloRequest {
                    atlas_protocol: protocol::PROTOCOL_VERSION.into(),
                    requested_features: vec![],
                    position,
                },
            )
            .await
    }

    pub async fn lookup_decl(
        &mut self,
        name: impl Into<String>,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::LookupDeclResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::LOOKUP_DECL,
                &protocol::LookupDeclRequest {
                    name: name.into(),
                    position,
                },
            )
            .await
    }

    pub async fn infer_type(
        &mut self,
        expr: protocol::ExprHandle,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::ExprResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::INFER_TYPE,
                &protocol::ExprRequest { expr, position },
            )
            .await
    }

    pub async fn whnf(
        &mut self,
        expr: protocol::ExprHandle,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::ExprResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(protocol::WHNF, &protocol::ExprRequest { expr, position })
            .await
    }

    pub async fn is_def_eq(
        &mut self,
        lhs: protocol::ExprHandle,
        rhs: protocol::ExprHandle,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::BoolResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::IS_DEFEQ,
                &protocol::PairRequest { lhs, rhs, position },
            )
            .await
    }

    pub async fn synth_instance(
        &mut self,
        type_expr: protocol::ExprHandle,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::SynthInstanceResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::SYNTH_INSTANCE,
                &protocol::SynthInstanceRequest {
                    type_expr,
                    position,
                },
            )
            .await
    }

    pub async fn apply(
        &mut self,
        candidate: protocol::ExprHandle,
        goal_type: protocol::ExprHandle,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::ApplyResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::APPLY,
                &protocol::ApplyRequest {
                    candidate,
                    goal_type,
                    position,
                },
            )
            .await
    }

    pub async fn elaborate(
        &mut self,
        text: impl Into<String>,
        expected: Option<protocol::ExprHandle>,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::ElaborateResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::ELABORATE,
                &protocol::ElaborateRequest {
                    text: text.into(),
                    expected,
                    position,
                },
            )
            .await
    }

    pub async fn check_proof(
        &mut self,
        proof: protocol::ExprHandle,
        proposition: protocol::ExprHandle,
        position: protocol::Position,
    ) -> Result<protocol::OracleResult<protocol::BoolResponse>, ClientError> {
        self.client.set_position(position);
        self.client
            .call(
                protocol::CHECK_PROOF,
                &protocol::CheckProofRequest {
                    proof,
                    proposition,
                    position,
                },
            )
            .await
    }
}
