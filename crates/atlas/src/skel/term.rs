//! The I3 statement encoding, parsed into a hash-consed term arena (B4, atlas.md §1c).
//!
//! # Why an arena
//!
//! The corpus is a DAG, not a forest. Measured over a 74,927-declaration slice: 4,094,711
//! node constructions collapse to 727,038 distinct nodes — 5.6× sharing. Interning turns
//! structural equality into a `u32` compare, makes the anti-unifier's memo key three
//! `u32`s, and means a skeleton's identity *is* its [`TermId`], so the "exact skeleton
//! hashing" atlas.md §1c asks for needs no hashing at all.
//!
//! # The grammar
//!
//! Read off `Atlas/Atlas/Statement.lean` rather than off `statement-hash.md`, which
//! is wrong in one place: a `Const` carries an explicit **level count** before its levels.
//!
//! ```text
//! expr  ::= "b" nat
//!         | "s(" level ")"
//!         | "c(" name "," nat ("," level)* ")"     -- nat is the level count
//!         | "a(" expr "," expr ")"
//!         | "l" bi "(" expr "," expr ")"
//!         | "p" bi "(" expr "," expr ")"
//!         | "e(" expr "," expr "," expr ")"
//!         | "n" nat                                -- Nat literal, unbounded
//!         | "t" len ":" bytes                      -- String literal
//!         | "j(" name "," nat "," expr ")"
//! level ::= "0" | "+(" level ")" | "M(" level "," level ")" | "I(" level "," level ")" | "u" nat
//! bi    ::= "d" | "i" | "t" | "s"
//! name  ::= len ":" bytes                          -- utf8ByteSize prefix
//! ```
//!
//! Parsing is recursive descent over **bytes**, not chars: names are byte-length-prefixed
//! and may contain any UTF-8. Disambiguation is by first byte and is unambiguous — `t` is
//! a string literal at expression position and `instImplicit` only in the one-byte slot
//! after `l`/`p`; `s` is a sort at expression position and `strictImplicit` only in that
//! same slot.

use std::collections::{BTreeSet, HashMap};

#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Debug)]
pub struct TermId(pub u32);
#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Debug)]
pub struct SymId(pub u32);
#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Debug)]
pub struct LevelId(pub u32);
#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Debug)]
pub struct LevelsId(pub u32);

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum BinderInfo {
    Default,
    Implicit,
    InstImplicit,
    StrictImplicit,
}

impl BinderInfo {
    fn from_byte(b: u8) -> Option<BinderInfo> {
        Some(match b {
            b'd' => BinderInfo::Default,
            b'i' => BinderInfo::Implicit,
            b't' => BinderInfo::InstImplicit,
            b's' => BinderInfo::StrictImplicit,
            _ => return None,
        })
    }

    fn to_byte(self) -> u8 {
        match self {
            BinderInfo::Default => b'd',
            BinderInfo::Implicit => b'i',
            BinderInfo::InstImplicit => b't',
            BinderInfo::StrictImplicit => b's',
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum LevelNode {
    Zero,
    Succ(LevelId),
    Max(LevelId, LevelId),
    IMax(LevelId, LevelId),
    Param(u32),
    /// Produced only by erasure at `Presentation` and above. Universe *structure* is
    /// erased; a `Const`'s levels list keeps its length, so arity survives.
    Star,
}

/// One node of the I3 term language.
///
/// `Eq`/`Hash` cover the whole node, so the interner is exact rather than probabilistic.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Node {
    BVar(u32),
    Sort(LevelId),
    Const(SymId, LevelsId),
    App(TermId, TermId),
    Lam(BinderInfo, TermId, TermId),
    Pi(BinderInfo, TermId, TermId),
    Let(TermId, TermId, TermId),
    /// Lean's nat literals are unbounded, so the *digits* are interned rather than a u64.
    NatLit(SymId),
    StrLit(SymId),
    Proj(SymId, u32, TermId),
    /// An erasure hole. **Anonymous** — every hole is the same node, which is what makes
    /// erasure a homomorphism and bucket equality one `u32` compare.
    Hole,
    /// An anti-unification variable. **Identified** — two `Var(k)` occurrences assert that
    /// the same input pair was generalized there. Never produced by erasure.
    Var(u32),
}

#[derive(Debug, PartialEq, Eq)]
pub enum ParseError {
    /// Refused rather than misread: a toolchain bump must not silently reinterpret
    /// encodings, which is the same discipline `statement::verify` follows.
    Version(String),
    At {
        offset: usize,
        expected: &'static str,
    },
    TruncatedName {
        offset: usize,
    },
    Trailing {
        offset: usize,
    },
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ParseError::Version(v) => write!(f, "unknown encoding version `{v}`"),
            ParseError::At { offset, expected } => {
                write!(f, "at byte {offset}: expected {expected}")
            }
            ParseError::TruncatedName { offset } => write!(f, "at byte {offset}: truncated name"),
            ParseError::Trailing { offset } => write!(f, "trailing input at byte {offset}"),
        }
    }
}

impl std::error::Error for ParseError {}

#[derive(Default)]
pub struct Arena {
    nodes: Vec<Node>,
    intern: HashMap<Node, TermId>,
    size: Vec<u32>,
    /// 1 + the largest free de Bruijn index in the subtree; 0 means closed. Lean calls
    /// this `looseBVarRange`. Computed at intern time and load-bearing for both the
    /// anti-unifier's scope handling and the index's choice of posting keys.
    loose: Vec<u32>,
    /// Nodes that are neither a hole nor a variable, per subtree. The denominator of
    /// `retention`, kept here so it costs an array read rather than a DAG traversal.
    concrete: Vec<u32>,
    levels: Vec<LevelNode>,
    level_intern: HashMap<LevelNode, LevelId>,
    level_lists: Vec<Box<[LevelId]>>,
    level_list_intern: HashMap<Box<[LevelId]>, LevelsId>,
    syms: Vec<Box<str>>,
    sym_intern: HashMap<Box<str>, SymId>,
    /// Set by `seal`, cleared by the first `intern` after it. See `seal` for why the
    /// maps cannot simply stay dropped.
    sealed: bool,
}

impl Arena {
    pub fn new() -> Arena {
        Arena::default()
    }

    pub fn intern(&mut self, n: Node) -> TermId {
        if self.sealed {
            self.unseal();
        }
        if let Some(&id) = self.intern.get(&n) {
            return id;
        }
        let (size, loose, concrete) = self.measure(&n);
        let id = TermId(self.nodes.len() as u32);
        self.nodes.push(n);
        self.size.push(size);
        self.loose.push(loose);
        self.concrete.push(concrete);
        self.intern.insert(n, id);
        id
    }

    /// `(size, loose, concrete)`.
    ///
    /// `concrete` counts nodes that are neither a hole nor a variable. It is computed
    /// here, at intern time and in O(1) from the children, rather than by a recursion at
    /// query time: the arena is a hash-consed DAG, so walking it counts the *tree*
    /// unfolding and re-walks shared subterms once per parent. `similar_brute` needs this
    /// value once per candidate over 131,062 candidates, which is where the difference
    /// between an array read and a traversal stops being academic.
    fn measure(&self, n: &Node) -> (u32, u32, u32) {
        let sz = |t: TermId| self.size[t.0 as usize];
        let lo = |t: TermId| self.loose[t.0 as usize];
        let co = |t: TermId| self.concrete[t.0 as usize];
        match *n {
            Node::BVar(k) => (1, k + 1, 1),
            Node::Sort(_) | Node::Const(..) | Node::NatLit(_) | Node::StrLit(_) => (1, 0, 1),
            Node::Hole | Node::Var(_) => (1, 0, 0),
            Node::App(a, b) => (1 + sz(a) + sz(b), lo(a).max(lo(b)), 1 + co(a) + co(b)),
            Node::Lam(_, d, b) | Node::Pi(_, d, b) => (
                1 + sz(d) + sz(b),
                lo(d).max(lo(b).saturating_sub(1)),
                1 + co(d) + co(b),
            ),
            Node::Let(t, v, b) => (
                1 + sz(t) + sz(v) + sz(b),
                lo(t).max(lo(v)).max(lo(b).saturating_sub(1)),
                1 + co(t) + co(v) + co(b),
            ),
            Node::Proj(_, _, e) => (1 + sz(e), lo(e), 1 + co(e)),
        }
    }

    pub fn node(&self, t: TermId) -> Node {
        self.nodes[t.0 as usize]
    }
    pub fn size(&self, t: TermId) -> u32 {
        self.size[t.0 as usize]
    }
    pub fn loose(&self, t: TermId) -> u32 {
        self.loose[t.0 as usize]
    }
    /// Nodes that are neither a hole nor a variable — the shared structure `retention`
    /// is a fraction of.
    pub fn concrete(&self, t: TermId) -> u32 {
        self.concrete[t.0 as usize]
    }

    pub fn is_closed(&self, t: TermId) -> bool {
        self.loose(t) == 0
    }
    /// Strip the `Pi` prefix to reach what a statement actually concludes.
    ///
    /// The result is an **open** term: its loose de Bruijn indices refer to binders that
    /// are no longer there. That is the same situation source B's open subterm keys are
    /// already in, and it carries the same caveat — index `0` in two different conclusions
    /// need not mean the same thing, so a match found this way is weaker evidence than one
    /// found on closed terms. Measured cost on physlib: cross-subfield noise rises from 9%
    /// to 10%.
    pub fn conclusion(&self, t: TermId) -> TermId {
        let mut cur = t;
        while let Node::Pi(_, _, body) = self.node(cur) {
            cur = body;
        }
        cur
    }

    pub fn sym(&self, s: SymId) -> &str {
        &self.syms[s.0 as usize]
    }
    pub fn level(&self, l: LevelId) -> LevelNode {
        self.levels[l.0 as usize]
    }
    pub fn level_list(&self, l: LevelsId) -> &[LevelId] {
        &self.level_lists[l.0 as usize]
    }
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }
    pub fn sym_count(&self) -> usize {
        self.syms.len()
    }

    pub fn intern_sym(&mut self, s: &str) -> SymId {
        if self.sealed {
            self.unseal();
        }
        if let Some(&id) = self.sym_intern.get(s) {
            return id;
        }
        let id = SymId(self.syms.len() as u32);
        let boxed: Box<str> = s.into();
        self.syms.push(boxed.clone());
        self.sym_intern.insert(boxed, id);
        id
    }

    pub fn intern_level(&mut self, l: LevelNode) -> LevelId {
        if self.sealed {
            self.unseal();
        }
        if let Some(&id) = self.level_intern.get(&l) {
            return id;
        }
        let id = LevelId(self.levels.len() as u32);
        self.levels.push(l);
        self.level_intern.insert(l, id);
        id
    }

    pub fn intern_levels(&mut self, ls: &[LevelId]) -> LevelsId {
        if self.sealed {
            self.unseal();
        }
        if let Some(&id) = self.level_list_intern.get(ls) {
            return id;
        }
        let id = LevelsId(self.level_lists.len() as u32);
        let boxed: Box<[LevelId]> = ls.into();
        self.level_lists.push(boxed.clone());
        self.level_list_intern.insert(boxed, id);
        id
    }

    /// Parse one `stmt` field.
    pub fn parse(&mut self, encoding: &str) -> Result<TermId, ParseError> {
        let bytes = encoding.as_bytes();
        let Some(semi) = bytes.iter().position(|&b| b == b';') else {
            return Err(ParseError::At {
                offset: 0,
                expected: "`version;`",
            });
        };
        let version = &encoding[..semi];
        if version != crate::statement::ENCODING_VERSION {
            return Err(ParseError::Version(version.to_string()));
        }
        let mut p = Parser {
            b: bytes,
            i: semi + 1,
        };
        let t = p.expr(self)?;
        if p.i != bytes.len() {
            return Err(ParseError::Trailing { offset: p.i });
        }
        Ok(t)
    }

    /// Re-serialize in the I3 grammar, with `_` for a hole and `?k` for a variable.
    ///
    /// Round-trips on hole-free, variable-free terms, which is what makes the parser
    /// testable against itself.
    pub fn render(&self, t: TermId) -> String {
        let mut out = String::new();
        self.render_into(t, &mut out);
        out
    }

    fn render_into(&self, t: TermId, out: &mut String) {
        use std::fmt::Write as _;
        match self.node(t) {
            Node::BVar(k) => {
                let _ = write!(out, "b{k}");
            }
            Node::Sort(l) => {
                out.push_str("s(");
                self.render_level(l, out);
                out.push(')');
            }
            Node::Const(s, ls) => {
                let name = self.sym(s);
                let _ = write!(
                    out,
                    "c({}:{},{}",
                    name.len(),
                    name,
                    self.level_list(ls).len()
                );
                for &l in self.level_list(ls) {
                    out.push(',');
                    self.render_level(l, out);
                }
                out.push(')');
            }
            Node::App(f, a) => {
                out.push_str("a(");
                self.render_into(f, out);
                out.push(',');
                self.render_into(a, out);
                out.push(')');
            }
            Node::Lam(bi, d, b) | Node::Pi(bi, d, b) => {
                out.push(if matches!(self.node(t), Node::Lam(..)) {
                    'l'
                } else {
                    'p'
                });
                out.push(bi.to_byte() as char);
                out.push('(');
                self.render_into(d, out);
                out.push(',');
                self.render_into(b, out);
                out.push(')');
            }
            Node::Let(ty, v, b) => {
                out.push_str("e(");
                self.render_into(ty, out);
                out.push(',');
                self.render_into(v, out);
                out.push(',');
                self.render_into(b, out);
                out.push(')');
            }
            Node::NatLit(s) => {
                let _ = write!(out, "n{}", self.sym(s));
            }
            Node::StrLit(s) => {
                let v = self.sym(s);
                let _ = write!(out, "t{}:{}", v.len(), v);
            }
            Node::Proj(s, i, e) => {
                let name = self.sym(s);
                let _ = write!(out, "j({}:{},{},", name.len(), name, i);
                self.render_into(e, out);
                out.push(')');
            }
            Node::Hole => out.push('_'),
            Node::Var(k) => {
                let _ = write!(out, "?{k}");
            }
        }
    }

    fn render_level(&self, l: LevelId, out: &mut String) {
        use std::fmt::Write as _;
        match self.level(l) {
            LevelNode::Zero => out.push('0'),
            LevelNode::Succ(a) => {
                out.push_str("+(");
                self.render_level(a, out);
                out.push(')');
            }
            LevelNode::Max(a, b) => {
                out.push_str("M(");
                self.render_level(a, out);
                out.push(',');
                self.render_level(b, out);
                out.push(')');
            }
            LevelNode::IMax(a, b) => {
                out.push_str("I(");
                self.render_level(a, out);
                out.push(',');
                self.render_level(b, out);
                out.push(')');
            }
            LevelNode::Param(k) => {
                let _ = write!(out, "u{k}");
            }
            LevelNode::Star => out.push('*'),
        }
    }

    /// An application spine, head first: `a(a(f,x),y)` is `(f, [x, y])`.
    pub fn spine(&self, t: TermId) -> (TermId, Vec<TermId>) {
        let mut args = Vec::new();
        let mut cur = t;
        while let Node::App(f, a) = self.node(cur) {
            args.push(a);
            cur = f;
        }
        args.reverse();
        (cur, args)
    }

    /// Every distinct subterm, deduplicated by identity — which interning makes exact.
    pub fn subterms(&self, t: TermId, out: &mut BTreeSet<TermId>) {
        if !out.insert(t) {
            return;
        }
        match self.node(t) {
            Node::App(a, b) => {
                self.subterms(a, out);
                self.subterms(b, out);
            }
            Node::Lam(_, d, b) | Node::Pi(_, d, b) => {
                self.subterms(d, out);
                self.subterms(b, out);
            }
            Node::Let(a, b, c) => {
                self.subterms(a, out);
                self.subterms(b, out);
                self.subterms(c, out);
            }
            Node::Proj(_, _, e) => self.subterms(e, out),
            _ => {}
        }
    }

    /// Drop the construction-time interner maps. They are roughly a third of the
    /// footprint and a pure-query workload never touches them.
    ///
    /// This is only sound because `intern` restores them before building anything new.
    /// Dropping them outright is *not* sound, and the failure is silent: `intern` would
    /// miss on a term that is already in `nodes`, push a structurally identical duplicate
    /// under a fresh `TermId`, and every downstream `TermId` comparison would then answer
    /// "different" for two terms that are equal. `name_with_term` is exactly such a
    /// comparison, so `transport` reported an *open* target — a lemma Mathlib does not
    /// have — for subjects whose image was sitting in the corpus all along. Sealing after
    /// the precomputed levels (Exact, Presentation, Shape) and querying at a lazy one
    /// (Instances, Carriers) hid it, because both sides of the comparison were then built
    /// in the same post-seal generation and shared with each other.
    pub fn seal(&mut self) {
        self.intern = HashMap::new();
        self.level_intern = HashMap::new();
        self.level_list_intern = HashMap::new();
        self.sym_intern = HashMap::new();
        self.sealed = true;
    }

    /// Rebuild the interner maps from the arena's own vectors, restoring the invariant
    /// that structurally equal terms share a `TermId`.
    ///
    /// `or_insert` rather than `insert`: the earliest id for a node is the one already
    /// stored in the index's roots and erasure cache, so it must stay canonical.
    #[cold]
    fn unseal(&mut self) {
        for (i, n) in self.nodes.iter().enumerate() {
            self.intern.entry(*n).or_insert(TermId(i as u32));
        }
        for (i, l) in self.levels.iter().enumerate() {
            self.level_intern.entry(*l).or_insert(LevelId(i as u32));
        }
        for (i, ls) in self.level_lists.iter().enumerate() {
            self.level_list_intern
                .entry(ls.clone())
                .or_insert(LevelsId(i as u32));
        }
        for (i, s) in self.syms.iter().enumerate() {
            self.sym_intern.entry(s.clone()).or_insert(SymId(i as u32));
        }
        self.sealed = false;
    }
}

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<u8> {
        self.b.get(self.i).copied()
    }

    fn eat(&mut self, c: u8, expected: &'static str) -> Result<(), ParseError> {
        if self.peek() == Some(c) {
            self.i += 1;
            Ok(())
        } else {
            Err(ParseError::At {
                offset: self.i,
                expected,
            })
        }
    }

    fn nat(&mut self) -> Result<u32, ParseError> {
        let start = self.i;
        while matches!(self.peek(), Some(c) if c.is_ascii_digit()) {
            self.i += 1;
        }
        if self.i == start {
            return Err(ParseError::At {
                offset: start,
                expected: "a number",
            });
        }
        std::str::from_utf8(&self.b[start..self.i])
            .ok()
            .and_then(|s| s.parse().ok())
            .ok_or(ParseError::At {
                offset: start,
                expected: "a number that fits",
            })
    }

    /// Digits, kept as a string: Lean's nat literals are unbounded.
    fn digits(&mut self) -> Result<&'a str, ParseError> {
        let start = self.i;
        while matches!(self.peek(), Some(c) if c.is_ascii_digit()) {
            self.i += 1;
        }
        if self.i == start {
            return Err(ParseError::At {
                offset: start,
                expected: "digits",
            });
        }
        std::str::from_utf8(&self.b[start..self.i]).map_err(|_| ParseError::At {
            offset: start,
            expected: "utf-8 digits",
        })
    }

    /// A byte-length-prefixed name.
    fn name(&mut self) -> Result<&'a str, ParseError> {
        let len = self.nat()? as usize;
        self.eat(b':', "`:` after a name length")?;
        let end = self.i + len;
        if end > self.b.len() {
            return Err(ParseError::TruncatedName { offset: self.i });
        }
        let s = std::str::from_utf8(&self.b[self.i..end])
            .map_err(|_| ParseError::TruncatedName { offset: self.i })?;
        self.i = end;
        Ok(s)
    }

    fn level(&mut self, a: &mut Arena) -> Result<LevelId, ParseError> {
        let node = match self.peek() {
            Some(b'0') => {
                self.i += 1;
                LevelNode::Zero
            }
            Some(b'+') => {
                self.i += 1;
                self.eat(b'(', "`(` after `+`")?;
                let l = self.level(a)?;
                self.eat(b')', "`)` closing `+(`")?;
                LevelNode::Succ(l)
            }
            Some(c @ (b'M' | b'I')) => {
                self.i += 1;
                self.eat(b'(', "`(` after a level operator")?;
                let x = self.level(a)?;
                self.eat(b',', "`,` between level operands")?;
                let y = self.level(a)?;
                self.eat(b')', "`)` closing a level operator")?;
                if c == b'M' {
                    LevelNode::Max(x, y)
                } else {
                    LevelNode::IMax(x, y)
                }
            }
            Some(b'u') => {
                self.i += 1;
                LevelNode::Param(self.nat()?)
            }
            _ => {
                return Err(ParseError::At {
                    offset: self.i,
                    expected: "a universe level",
                });
            }
        };
        Ok(a.intern_level(node))
    }

    fn expr(&mut self, a: &mut Arena) -> Result<TermId, ParseError> {
        let node = match self.peek() {
            Some(b'b') => {
                self.i += 1;
                Node::BVar(self.nat()?)
            }
            Some(b's') => {
                self.i += 1;
                self.eat(b'(', "`(` after `s`")?;
                let l = self.level(a)?;
                self.eat(b')', "`)` closing `s(`")?;
                Node::Sort(l)
            }
            Some(b'c') => {
                self.i += 1;
                self.eat(b'(', "`(` after `c`")?;
                let name = self.name()?;
                let sym = a.intern_sym(name);
                self.eat(b',', "`,` after a constant's name")?;
                let n = self.nat()? as usize;
                let mut ls = Vec::with_capacity(n);
                for _ in 0..n {
                    self.eat(b',', "`,` before a universe level")?;
                    ls.push(self.level(a)?);
                }
                self.eat(b')', "`)` closing `c(`")?;
                Node::Const(sym, a.intern_levels(&ls))
            }
            Some(b'a') => {
                self.i += 1;
                self.eat(b'(', "`(` after `a`")?;
                let f = self.expr(a)?;
                self.eat(b',', "`,` between application parts")?;
                let x = self.expr(a)?;
                self.eat(b')', "`)` closing `a(`")?;
                Node::App(f, x)
            }
            Some(c @ (b'l' | b'p')) => {
                self.i += 1;
                let bi = self
                    .peek()
                    .and_then(BinderInfo::from_byte)
                    .ok_or(ParseError::At {
                        offset: self.i,
                        expected: "binder info",
                    })?;
                self.i += 1;
                self.eat(b'(', "`(` after binder info")?;
                let d = self.expr(a)?;
                self.eat(b',', "`,` between a binder's domain and body")?;
                let b = self.expr(a)?;
                self.eat(b')', "`)` closing a binder")?;
                if c == b'l' {
                    Node::Lam(bi, d, b)
                } else {
                    Node::Pi(bi, d, b)
                }
            }
            Some(b'e') => {
                self.i += 1;
                self.eat(b'(', "`(` after `e`")?;
                let ty = self.expr(a)?;
                self.eat(b',', "`,` in a `let`")?;
                let v = self.expr(a)?;
                self.eat(b',', "`,` in a `let`")?;
                let b = self.expr(a)?;
                self.eat(b')', "`)` closing `e(`")?;
                Node::Let(ty, v, b)
            }
            Some(b'n') => {
                self.i += 1;
                let d = self.digits()?;
                Node::NatLit(a.intern_sym(d))
            }
            Some(b't') => {
                self.i += 1;
                let s = self.name()?;
                Node::StrLit(a.intern_sym(s))
            }
            Some(b'j') => {
                self.i += 1;
                self.eat(b'(', "`(` after `j`")?;
                let name = self.name()?;
                let sym = a.intern_sym(name);
                self.eat(b',', "`,` after a projection's structure")?;
                let idx = self.nat()?;
                self.eat(b',', "`,` before a projection's target")?;
                let e = self.expr(a)?;
                self.eat(b')', "`)` closing `j(`")?;
                Node::Proj(sym, idx, e)
            }
            _ => {
                return Err(ParseError::At {
                    offset: self.i,
                    expected: "an expression",
                });
            }
        };
        Ok(a.intern(node))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse1(s: &str) -> (Arena, TermId) {
        let mut a = Arena::new();
        let t = a.parse(s).expect("parse");
        (a, t)
    }

    #[test]
    fn round_trips_a_real_statement() {
        // `two_eq_two : 2 = 2`, taken verbatim from `Tests/Atlas/Extract.lean`'s golden.
        let src = "atlas-stmt-v1;a(a(a(c(2:Eq,1,+(0)),c(3:Nat,0)),a(a(a(c(11:OfNat.ofNat,1,0),\
                   c(3:Nat,0)),n2),a(c(12:instOfNatNat,0),n2))),a(a(a(c(11:OfNat.ofNat,1,0),\
                   c(3:Nat,0)),n2),a(c(12:instOfNatNat,0),n2)))";
        let (a, t) = parse1(src);
        // Rendering is the parser's own inverse, so a mismatch is a parse bug rather than
        // a formatting preference.
        assert_eq!(format!("atlas-stmt-v1;{}", a.render(t)), src);
    }

    #[test]
    fn a_sealed_arena_still_shares_ids_with_terms_built_before_the_seal() {
        // The bug this pins made `transport` report an *open* target — a lemma that does
        // not exist — for a subject whose image was in the corpus, because the image was
        // built after `seal` and compared by `TermId` against a root built before it.
        let src = "atlas-stmt-v1;a(a(a(c(2:Eq,1,+(0)),c(3:Nat,0)),a(a(a(c(11:OfNat.ofNat,1,0),\
                   c(3:Nat,0)),n2),a(c(12:instOfNatNat,0),n2))),a(a(a(c(11:OfNat.ofNat,1,0),\
                   c(3:Nat,0)),n2),a(c(12:instOfNatNat,0),n2)))";
        let (mut a, before) = parse1(src);
        let nodes_before = a.nodes.len();
        a.seal();
        let after = a.parse(src).expect("parse");
        assert_eq!(
            before, after,
            "a term rebuilt after `seal` must share the id of its pre-seal twin"
        );
        assert_eq!(
            a.nodes.len(),
            nodes_before,
            "rebuilding after `seal` must not push duplicate nodes"
        );
    }

    #[test]
    fn interning_shares_the_repeated_half() {
        // `2 = 2` mentions the same `2` twice; the arena must store it once.
        let src = "atlas-stmt-v1;a(a(a(c(2:Eq,1,+(0)),c(3:Nat,0)),a(a(a(c(11:OfNat.ofNat,1,0),\
                   c(3:Nat,0)),n2),a(c(12:instOfNatNat,0),n2))),a(a(a(c(11:OfNat.ofNat,1,0),\
                   c(3:Nat,0)),n2),a(c(12:instOfNatNat,0),n2)))";
        let (a, t) = parse1(src);
        let Node::App(f, x) = a.node(t) else {
            panic!("expected an application")
        };
        let Node::App(_, y) = a.node(f) else {
            panic!("expected an application")
        };
        assert_eq!(
            x, y,
            "the two sides of `2 = 2` are the same term and must intern equal"
        );
        // And `size` counts the tree, not the DAG — it is what ranking divides by.
        assert!(a.size(t) > a.node_count() as u32 / 2);
    }

    #[test]
    fn loose_bvar_range_is_computed() {
        // `∀ (x : Sort 0), x` — the body's `b0` is bound, so the whole thing is closed.
        let (a, t) = parse1("atlas-stmt-v1;pd(s(0),b0)");
        assert!(a.is_closed(t));
        let Node::Pi(_, _, body) = a.node(t) else {
            panic!()
        };
        assert_eq!(a.loose(body), 1, "the body alone has one free index");
    }

    #[test]
    fn a_wrong_version_is_refused_not_misread() {
        let mut a = Arena::new();
        assert_eq!(
            a.parse("atlas-stmt-v9;b0"),
            Err(ParseError::Version("atlas-stmt-v9".into()))
        );
    }

    #[test]
    fn trailing_input_is_an_error() {
        let mut a = Arena::new();
        assert!(matches!(
            a.parse("atlas-stmt-v1;b0b0"),
            Err(ParseError::Trailing { .. })
        ));
    }

    #[test]
    fn a_name_may_contain_non_ascii() {
        // Names are *byte*-length-prefixed, which is why the parser works over bytes.
        let (a, t) = parse1("atlas-stmt-v1;c(3:ℝ,0)");
        let Node::Const(s, _) = a.node(t) else {
            panic!()
        };
        assert_eq!(a.sym(s), "ℝ");
    }

    #[test]
    fn const_levels_carry_an_explicit_count() {
        // `statement-hash.md` omits the count; the encoder emits it. Pinned here because
        // the doc and the code disagreed and the code is what produces the corpus.
        let (a, t) = parse1("atlas-stmt-v1;c(3:Foo,2,0,u1)");
        let Node::Const(_, ls) = a.node(t) else {
            panic!()
        };
        assert_eq!(a.level_list(ls).len(), 2);
    }

    #[test]
    fn unbounded_nat_literals_survive() {
        let big = "123456789012345678901234567890";
        let (a, t) = parse1(&format!("atlas-stmt-v1;n{big}"));
        let Node::NatLit(s) = a.node(t) else { panic!() };
        assert_eq!(a.sym(s), big);
    }

    #[test]
    fn subterms_are_deduplicated_by_identity() {
        let (a, t) = parse1("atlas-stmt-v1;a(b0,b0)");
        let mut out = std::collections::BTreeSet::new();
        a.subterms(t, &mut out);
        assert_eq!(out.len(), 2, "the application and the one shared `b0`");
    }
}
