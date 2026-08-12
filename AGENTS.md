# lean-atlas — operating contract

This repository is a research instrument: a read-only semantic index over Lean, plus the
extractor and query engine that feed it. Treat evidence as replayable and every consequential
claim as a computed answer.

## Non-negotiable rules

- **Never re-parse strings.** The statement encoding is produced by the Lean extractor from
  elaborated `Expr` trees (`atlas-stmt-v1;…`). Do not format a string and parse it back.
- **A slice must be closed under the constants its statements mention.** The erasure holes
  arguments in `InstImplicit` positions of the head constant's signature, so a missing head
  holes nothing and silently falls back to a weaker normalization. Run `atlas closure
  <slice>` (or the MCP `atlas_closure` tool) first on any slice you did not extract yourself,
  and assert that a known-holed skeleton is *still holed* afterwards — otherwise restriction
  is indistinguishable from a changed answer.
- **Restrict to claims, or you are measuring Lean rather than mathematics.** Unrestricted,
  the top skeleton/equivalence/dictionary answers are metaprogramming siblings and recursors,
  not mathematics. Use the `--lens`, `--level`, and `--all-kinds` gates deliberately.
- **The kernel is a soundness oracle, never a novelty oracle.** `#atlas_home` / `atlas why`
  certify truth and location; "novel", "first", "no prior art" need a literature search no
  internal control supplies.
- **An exclusion at the wrong level is no exclusion.** When a control removes a component,
  exclude coincidence at the *level that component operates on*, or the control passes on
  identity.
- **Read the exit status of the gate itself**, not of whatever it was piped into.

## The encoding (`atlas-stmt-v1`)

- Version tag lives *inside* the encoding, so payload and version cannot be separated.
- Normalization: alpha erased, binder info kept, universes normalized then renamed by first
  occurrence, `mdata` stripped, literals uncanonicalized, no unfolding.
- The digest is SHA-256 of the encoding's UTF-8 bytes, computed Rust-side. `statement_verify`
  reports `Match` / `Differs` / `StaleFreeze` — a version skew is a *distinct* verdict from a
  changed statement.

## Layout

```
lean/            the extractor (AtlasExtract package) — imports only Lean
crates/atlas     the Rust engine: graph, statement digest, skel/ (erasure + anti-unifier),
                 equiv, dict, relation, logical + the `atlas` CLI and `atlas-mcp` server
crates/atlas-py  the Python binding (import atlas)
scripts/         the research harness (historical; re-extract corpora before running)
docs/            the original design documents
```
