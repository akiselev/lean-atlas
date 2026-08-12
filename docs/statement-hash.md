# Statement hashing — mini-design (I3)

**Status:** Decided 2026-08-01 · implementation scheduled week 2 · consumers: C5 (freeze/verify),
B1 (extractor rows), B8 (overlay keying) · records the §9.6 amendment, which implements
`agent-interface.md` §4(d) as versioned-hash equality

## What is hashed

The **statement**: a declaration's elaborated type, as stored in the environment
(`ConstantInfo.type`). Not the proof term, not the value, not the declaration's name.

The name's exclusion is load-bearing rather than incidental: renaming a theorem does not change
what it claims, and B8's rebind-by-hash overlay depends on that being true.

## Normalization decisions

Every decision below is deliberate; changing any of them bumps the version tag.

| aspect | decision | why |
|---|---|---|
| binder names (alpha) | erased | `Expr` is already de Bruijn; names are pretty-printing |
| binder info (`explicit` / `implicit` / `instImplicit` / `strictImplicit`) | **kept** | it is the declared interface — what a caller must supply. Keeping it is also the stricter direction, and strictness is the safe direction here |
| universe parameter names | canonically renamed in order of **first occurrence in the type** | names are arbitrary, and so is `levelParams` order |
| universe level structure | `Level.normalize` first, then rename | `max u (max u v)` and `max u v` are the same level; core already provides the normal form |
| `mdata` | stripped | elaboration annotations, not content |
| numeric literals | kept exactly as elaborated (`OfNat.ofNat …` or `Expr.lit`) — no canonicalisation | two spellings are two statements; both sides of a comparison come from the same frozen source text, so this costs nothing in practice |
| definitional unfolding | **none** — no whnf, no delta, no beta, no eta, no zeta | see "What equality means" |
| instance arguments | kept | they are part of the type |
| `Expr.proj` | kept structurally | |
| metavariables | error | instantiate first; a statement with holes is not freezable |
| free variables | error | statements are closed |
| `sorryAx` occurring in the type | error | a statement that mentions `sorry` is not a statement |

## The encoding

The normative artifact is a **canonical encoding**, not a digest: a prefix-free, deterministic,
UTF-8 string. It is inspectable and diffable, which matters the first time a freeze check fails and
someone has to find out why.

```
encoding  ::= "atlas-stmt-v1;" expr
expr      ::= "b" nat                          -- bvar (de Bruijn index)
            | "s(" level ")"                   -- sort
            | "c(" name levels ")"             -- const
            | "a(" expr "," expr ")"           -- app
            | "l" bi "(" expr "," expr ")"     -- lam: domain, body
            | "p" bi "(" expr "," expr ")"     -- forall: domain, body
            | "e(" expr "," expr "," expr ")"  -- let: type, value, body
            | "n" nat                          -- Nat literal
            | "t" len ":" bytes                -- String literal
            | "j(" name "," nat "," expr ")"   -- proj
level     ::= "0" | "+(" level ")" | "M(" level "," level ")"
            | "I(" level "," level ")" | "u" nat
bi        ::= "d" | "i" | "t" | "s"            -- default, implicit, instImplicit, strictImplicit
name      ::= len ":" bytes                    -- byte length prefix; `Name.toString`
```

`mdata` never appears: the encoder recurses through it. Length-prefixed names keep the grammar
prefix-free, so no separator can be forged by a name containing punctuation.

## Version tag

The tag is **inside** the encoding, as its first field, so the payload and the version it was
produced under cannot be separated by any consumer. Frozen values are written
`atlas-stmt-v1:sha256:<hex>`.

Comparing across tags is a **loud failure**, never a mismatch: a `v1` freeze checked by a `v2`
implementation must report "this freeze predates the current statement-hash algorithm and must be
re-frozen by its owner", not "statement changed". Silent version skew would turn the anti-cheat
gate into noise, and noise is how gates get disabled.

## Where the digest is computed

There is no cryptographic hash in the pinned toolchain — no SHA-256, no BLAKE, in either Lean core
or Lake (checked). Anti-cheat needs collision resistance, because the adversary is an optimiser
holding the target, so a 64-bit non-cryptographic hash is not an option.

Therefore:

* **Lean produces the encoding.** That is the whole Lean-side obligation.
* **Rust digests it** — SHA-256 over the encoding's UTF-8 bytes, in `atlas` / `atlas check`, where a
  vetted implementation exists as a dependency rather than as our code.
* **B8 keys in Lean on the encoding itself** (bucketed by `String.hash`, compared exactly on
  collision), so the Lean side never needs a digest and no SHA-256 has to be written in Lean.

## What equality means

Encoding equality means: the same statement up to binder names, universe-parameter names, and
elaboration metadata. It is **strictly stronger than definitional equality** — two defeq statements
written differently encode differently.

The asymmetry that buys is the one worth having: a false *rejection* is possible (an honest
restatement fails the check and must be re-frozen, a reviewed event), a false *acceptance* is not
(a weakened statement cannot collide with the target). `agent-interface.md` §4(d)'s "definitionally
identical" is implemented as this, and the substitution is recorded rather than assumed: defeq is
undecidable in general and depends on the ambient environment, which is exactly what an anti-cheat
check must not depend on.

## Consumers

| consumer | contract |
|---|---|
| C5 freeze/verify | re-elaborate from source in a fresh environment, encode, digest, compare against the frozen `atlas-stmt-v1:sha256:…`. The rehearsal fixture (a weakened statement must fail) lands before first real use. |
| B1 extractor | every JSONL row carries the encoding version and the digest alongside name/kind/module/used-constants. |
| B8 overlay | rebind-by-hash; `@[deprecated]` chains follow the hash, Channel 3 hard-fails on mismatch, Channel 2 recomputes. |

## Test plan

*Invariance* — encoding is unchanged by: renaming binders; renaming universe parameters;
reordering `levelParams`; `mdata` annotations; renaming the declaration itself.

*Sensitivity* — encoding changes when: a hypothesis is added or dropped; a binder changes class
(`(n : Nat)` → `{n : Nat}`); a universe is specialised; an argument order changes. The C5 rehearsal
fixture (`∀ n, P n` weakened to `∀ n, n = 0 → P n`) is the headline case.

*Determinism* — the same input encoded in two processes agrees byte for byte. This is the test that
catches an iteration-order or name-hashing leak, which is the classic way a "canonical" encoding
turns out not to be.

*Differential* — a fixture of `(statement, encoding, digest)` triples checked on both sides; SHA-256
itself checked against published vectors Rust-side.

*Versioning* — a `v1` freeze verified by a `v2` implementation fails loudly with the re-freeze
message, and is not reported as a statement change.

## Open, deliberately

* **Literal canonicalisation.** If M2 shows honest restatements failing on literal representation,
  revisit — as a `v2`, not as a patch to `v1`.
* **A defeq-tolerant advisory.** Reporting "these differ but are defeq in this environment"
  alongside a failure would cut false rejections without weakening the gate. Worth doing only once
  there is evidence of false rejections.
* **Ambient context (A2.4).** A statement's meaning lives in its type, and `var`/`include` decide
  which binders end up there — so freezing the resulting type is the right object. Re-examine when
  F17 lands, because "which binders got included" becomes a thing a careless edit can change
  silently.
