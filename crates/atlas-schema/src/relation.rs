use std::{collections::BTreeMap, fmt};

pub const SCHEMA_VERSION: u32 = 2;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Warrant {
    Proved,
    Structural,
    Asserted,
    Heuristic,
}

macro_rules! relations {
    ($( $v:ident => ($wire:literal,$w:ident,$sym:expr) ),+ $(,)?) => {
        #[derive(Clone,Copy,Debug,PartialEq,Eq,PartialOrd,Ord,Hash)]
        pub enum RelationKind { $($v),+ }
        impl RelationKind {
            pub const ALL: [RelationKind; 17] = [$(RelationKind::$v),+];
            pub const fn as_str(self)->&'static str { match self {$(Self::$v=>$wire),+} }
            pub fn parse(s:&str)->Option<Self>{match s {$($wire=>Some(Self::$v),)+_=>None}}
            pub const fn warrant(self)->Warrant{match self {$(Self::$v=>Warrant::$w),+}}
            pub const fn is_symmetric(self)->bool{match self {$(Self::$v=>$sym),+}}
        }
    };
}

relations! {
    ExactStatement => ("ExactStatement",Structural,true),
    PresentationEqual => ("PresentationEqual",Structural,true),
    DefinitionalRewrite => ("DefinitionalRewrite",Structural,true),
    ProvedIff => ("ProvedIff",Proved,true),
    ProvedImplies => ("ProvedImplies",Proved,false),
    TypeEquiv => ("TypeEquiv",Structural,true),
    SharedInstance => ("SharedInstance",Structural,true),
    SharedHomeCandidate => ("SharedHomeCandidate",Heuristic,true),
    SharedHomeConfirmed => ("SharedHomeConfirmed",Proved,true),
    StructuralAnalogy => ("StructuralAnalogy",Heuristic,true),
    ProofShapeAnalogy => ("ProofShapeAnalogy",Heuristic,true),
    DictionaryRowCandidate => ("DictionaryRowCandidate",Heuristic,true),
    DictionaryRowConfirmed => ("DictionaryRowConfirmed",Proved,true),
    TransportRefuted => ("TransportRefuted",Proved,false),
    TransportProved => ("TransportProved",Proved,false),
    AssertedIff => ("AssertedIff",Asserted,true),
    AssertedImplies => ("AssertedImplies",Asserted,false),
}

impl fmt::Display for RelationKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Direction {
    Both,
    LeftToRight,
    RightToLeft,
}
impl Direction {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Both => "both",
            Self::LeftToRight => "left_to_right",
            Self::RightToLeft => "right_to_left",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Evidence {
    LeanTheorem {
        name: String,
    },
    CanonicalEq {
        level: &'static str,
    },
    AntiUnification {
        skeleton: String,
        common: u32,
        retention: f32,
    },
    DependencyPath {
        path: Vec<String>,
    },
    RankingFeatures {
        features: BTreeMap<String, f32>,
    },
    Counterexample {
        witness: String,
    },
    LeanAxiom {
        name: String,
    },
    Unsupported {
        reason: UnsupportedReason,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnsupportedReason {
    FlexHead,
    BudgetExhausted,
    NotAProposition,
}
impl UnsupportedReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::FlexHead => "flex_head",
            Self::BudgetExhausted => "budget_exhausted",
            Self::NotAProposition => "not_a_proposition",
        }
    }
}

impl Evidence {
    pub fn supports(&self) -> Warrant {
        match self {
            Self::LeanTheorem { .. } | Self::Counterexample { .. } => Warrant::Proved,
            Self::CanonicalEq { .. } | Self::DependencyPath { .. } => Warrant::Structural,
            Self::LeanAxiom { .. } => Warrant::Asserted,
            _ => Warrant::Heuristic,
        }
    }
    pub fn tag(&self) -> &'static str {
        match self {
            Self::LeanTheorem { .. } => "lean_theorem",
            Self::CanonicalEq { .. } => "canonical_eq",
            Self::AntiUnification { .. } => "anti_unification",
            Self::DependencyPath { .. } => "dependency_path",
            Self::RankingFeatures { .. } => "ranking_features",
            Self::Counterexample { .. } => "counterexample",
            Self::LeanAxiom { .. } => "lean_axiom",
            Self::Unsupported { .. } => "unsupported",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum RelationError {
    InsufficientEvidence {
        kind: RelationKind,
        needs: Warrant,
        evidence: &'static str,
        supports: Warrant,
    },
    DirectionMismatch {
        kind: RelationKind,
        direction: Direction,
    },
}
impl fmt::Display for RelationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InsufficientEvidence {
                kind,
                needs,
                evidence,
                supports,
            } => write!(
                f,
                "`{kind}` is {needs:?} but evidence `{evidence}` only supports {supports:?}"
            ),
            Self::DirectionMismatch { kind, direction } => {
                write!(f, "`{kind}` direction mismatch: {}", direction.as_str())
            }
        }
    }
}
impl std::error::Error for RelationError {}

#[derive(Clone, Debug, PartialEq)]
pub struct Relation {
    pub left: String,
    pub right: String,
    pub kind: RelationKind,
    pub direction: Direction,
    pub evidence: Evidence,
    pub level: Option<String>,
    pub generator: String,
    pub schema_version: u32,
}
impl Relation {
    pub fn new(
        left: impl Into<String>,
        right: impl Into<String>,
        kind: RelationKind,
        direction: Direction,
        evidence: Evidence,
        generator: impl Into<String>,
    ) -> Result<Self, RelationError> {
        let (needs, supports) = (kind.warrant(), evidence.supports());
        if supports > needs {
            return Err(RelationError::InsufficientEvidence {
                kind,
                needs,
                evidence: evidence.tag(),
                supports,
            });
        }
        if kind.is_symmetric() != (direction == Direction::Both) {
            return Err(RelationError::DirectionMismatch { kind, direction });
        }
        Ok(Self {
            left: left.into(),
            right: right.into(),
            kind,
            direction,
            evidence,
            level: None,
            generator: generator.into(),
            schema_version: SCHEMA_VERSION,
        })
    }
    pub fn at_level(mut self, level: impl Into<String>) -> Self {
        self.level = Some(level.into());
        self
    }
    pub fn warrant(&self) -> Warrant {
        self.kind.warrant()
    }
    pub fn explain(&self) -> String {
        format!(
            "{} {} {} [{}, {:?}] via {}",
            self.left,
            match self.direction {
                Direction::Both => "~",
                Direction::LeftToRight => "->",
                Direction::RightToLeft => "<-",
            },
            self.right,
            self.kind,
            self.warrant(),
            self.evidence.tag()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_kind_round_trips() {
        for k in RelationKind::ALL {
            assert_eq!(RelationKind::parse(k.as_str()), Some(k));
        }
        assert_eq!(RelationKind::ALL.len(), 17);
    }
    #[test]
    fn asserted_variants_are_in_registry() {
        assert_eq!(
            RelationKind::parse("AssertedIff"),
            Some(RelationKind::AssertedIff)
        );
        assert_eq!(
            RelationKind::parse("AssertedImplies"),
            Some(RelationKind::AssertedImplies)
        );
    }
}
