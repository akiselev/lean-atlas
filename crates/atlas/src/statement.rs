//! Statement identity (I3): digests over the canonical encoding.
//!
//! The Lean side (`Atlas/Atlas/Statement.lean`) produces the canonical *encoding*
//! of a statement; this module turns it into the frozen identity
//! `atlas-stmt-v1:sha256:<hex>`. The split is deliberate — see `statement-hash.md`: the
//! toolchain ships no cryptographic hash, and anti-cheat needs collision resistance
//! against an adversary holding the target, so the digest happens where a vetted
//! implementation is a dependency rather than our own code.
//!
//! The version tag lives inside the encoding, so payload and version cannot be separated.
//! Verifying a freeze written under an older version is a **loud** outcome
//! ([`Verdict::StaleFreeze`]), never a plain mismatch: silent version skew would turn the
//! anti-cheat gate into noise, and noise is how gates get disabled.

use sha2::{Digest, Sha256};
use std::fmt;

/// The encoding version this build understands. Must match `encodingVersion` in
/// `Atlas/Atlas/Statement.lean`.
pub const ENCODING_VERSION: &str = "atlas-stmt-v1";

/// Why an encoding or a frozen identity could not be used.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StatementError {
    /// The encoding does not start with `<version>;`.
    Malformed,
    /// The encoding carries a version this build does not implement.
    UnknownVersion(String),
    /// The frozen identity is not `<version>:sha256:<hex>`.
    MalformedFreeze,
}

impl fmt::Display for StatementError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StatementError::Malformed => {
                write!(
                    f,
                    "not a statement encoding: expected a `<version>;` prefix"
                )
            }
            StatementError::UnknownVersion(v) => write!(
                f,
                "statement encoding version `{v}` is not implemented by this build \
                 (this build writes `{ENCODING_VERSION}`)"
            ),
            StatementError::MalformedFreeze => write!(
                f,
                "not a frozen statement identity: expected `<version>:sha256:<hex>`"
            ),
        }
    }
}

impl std::error::Error for StatementError {}

/// The outcome of checking a statement against a frozen identity.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Verdict {
    /// The statement is the one that was frozen.
    Match,
    /// The statement is not the one that was frozen. This is the anti-cheat failure.
    Differs,
    /// The freeze predates the current algorithm; it says nothing about the statement and
    /// must be re-frozen by its owner.
    StaleFreeze { frozen_version: String },
}

/// Lowercase hex, written out because `sha2` 0.11 returns a `hybrid-array` `Array`, which
/// does not implement `LowerHex`.
pub(crate) fn to_hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        let _ = write!(out, "{b:02x}");
    }
    out
}

/// Split `<version>;<payload>` out of an encoding.
fn split_encoding(encoding: &str) -> Result<(&str, &str), StatementError> {
    let (version, payload) = encoding.split_once(';').ok_or(StatementError::Malformed)?;
    if version.is_empty() || payload.is_empty() {
        return Err(StatementError::Malformed);
    }
    Ok((version, payload))
}

/// The frozen identity of a canonical encoding: `atlas-stmt-v1:sha256:<hex>`.
///
/// The version in the output is the one carried by the encoding, not a constant, so a
/// digest can never claim a version its payload was not produced under.
pub fn digest(encoding: &str) -> Result<String, StatementError> {
    let (version, _) = split_encoding(encoding)?;
    if version != ENCODING_VERSION {
        return Err(StatementError::UnknownVersion(version.to_string()));
    }
    let mut hasher = Sha256::new();
    hasher.update(encoding.as_bytes());
    Ok(format!("{version}:sha256:{}", to_hex(&hasher.finalize())))
}

/// Check a freshly computed encoding against a frozen identity.
///
/// A freeze from another version yields [`Verdict::StaleFreeze`] rather than
/// [`Verdict::Differs`]: the two mean entirely different things to whoever reads the
/// report.
pub fn verify(encoding: &str, frozen: &str) -> Result<Verdict, StatementError> {
    let mut parts = frozen.splitn(3, ':');
    let frozen_version = parts.next().ok_or(StatementError::MalformedFreeze)?;
    let algorithm = parts.next().ok_or(StatementError::MalformedFreeze)?;
    let hex = parts.next().ok_or(StatementError::MalformedFreeze)?;
    if algorithm != "sha256" || hex.is_empty() || !hex.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(StatementError::MalformedFreeze);
    }
    if frozen_version != ENCODING_VERSION {
        return Ok(Verdict::StaleFreeze {
            frozen_version: frozen_version.to_string(),
        });
    }
    let computed = digest(encoding)?;
    Ok(if computed == frozen {
        Verdict::Match
    } else {
        Verdict::Differs
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The canonical encoding of `theorem t1 (a : Nat) : a = a`, produced by
    /// `#atlas_statement` on the pinned toolchain and pinned identically in
    /// `lean/Tests/Atlas/Statement.lean`. If one side changes, the other fails — that is
    /// the whole point of pinning it in both.
    const T1: &str = "atlas-stmt-v1;pd(c(3:Nat,0),a(a(a(c(2:Eq,1,+(0)),c(3:Nat,0)),b0),b0))";

    /// `theorem w2 : ∀ n : Nat, n = 0 → n = n` — the weakened statement from the C5
    /// rehearsal. It must not collide with anything.
    const WEAKENED: &str = "atlas-stmt-v1;pd(c(3:Nat,0),pd(a(a(a(c(2:Eq,1,+(0)),c(3:Nat,0)),b0),a(a(a(c(11:OfNat.ofNat,1,0),c(3:Nat,0)),n0),a(c(12:instOfNatNat,0),n0))),a(a(a(c(2:Eq,1,+(0)),c(3:Nat,0)),b1),b1)))";

    #[test]
    fn sha256_matches_published_vectors() {
        // Guards the digest itself, independently of anything Atlas-shaped.
        let mut hasher = Sha256::new();
        hasher.update(b"abc");
        assert_eq!(
            to_hex(&hasher.finalize()),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn digest_is_prefixed_and_stable() {
        let d = digest(T1).unwrap();
        assert!(d.starts_with("atlas-stmt-v1:sha256:"));
        assert_eq!(d, digest(T1).unwrap());
        assert_eq!(d.len(), "atlas-stmt-v1:sha256:".len() + 64);
    }

    #[test]
    fn weakening_changes_the_digest() {
        assert_ne!(digest(T1).unwrap(), digest(WEAKENED).unwrap());
    }

    #[test]
    fn verify_matches_and_differs() {
        let frozen = digest(T1).unwrap();
        assert_eq!(verify(T1, &frozen).unwrap(), Verdict::Match);
        assert_eq!(verify(WEAKENED, &frozen).unwrap(), Verdict::Differs);
    }

    #[test]
    fn a_freeze_from_another_version_is_stale_not_different() {
        let frozen = "atlas-stmt-v0:sha256:00";
        assert_eq!(
            verify(T1, frozen).unwrap(),
            Verdict::StaleFreeze {
                frozen_version: "atlas-stmt-v0".to_string()
            }
        );
    }

    #[test]
    fn malformed_inputs_are_refused() {
        assert_eq!(digest("no-version-here"), Err(StatementError::Malformed));
        assert_eq!(digest("atlas-stmt-v1;"), Err(StatementError::Malformed));
        assert_eq!(
            digest("atlas-stmt-v99;b0"),
            Err(StatementError::UnknownVersion("atlas-stmt-v99".to_string()))
        );
        assert_eq!(
            verify(T1, "atlas-stmt-v1:md5:abcd"),
            Err(StatementError::MalformedFreeze)
        );
        assert_eq!(
            verify(T1, "atlas-stmt-v1:sha256:nothex"),
            Err(StatementError::MalformedFreeze)
        );
    }
}
