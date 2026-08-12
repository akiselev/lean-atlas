//! Just enough JSON for the Atlas rows and the MCP wire format.
//!
//! Hand-written rather than pulled in with serde, for the same reason `statement.rs`
//! digests an encoding Lean produced rather than re-deriving it: the schemas are small,
//! fixed, and ours, and the fewer moving parts between the extractor and the consumer the
//! easier a mismatch is to see. If a schema grows past this, swap in serde — no public
//! signature here changes.

use std::collections::BTreeMap;
use std::fmt::Write as _;

#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    List(Vec<Value>),
    Obj(BTreeMap<String, Value>),
}

impl Value {
    pub fn str(s: impl Into<String>) -> Value {
        Value::Str(s.into())
    }

    pub fn obj(pairs: impl IntoIterator<Item = (&'static str, Value)>) -> Value {
        Value::Obj(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Obj(m) => m.get(key),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_list(&self) -> Option<&[Value]> {
        match self {
            Value::List(v) => Some(v),
            _ => None,
        }
    }

    /// Serialize. Objects come out key-sorted because `BTreeMap` is the representation,
    /// which makes a diff between two outputs readable.
    pub fn to_json(&self) -> String {
        let mut out = String::new();
        self.write(&mut out);
        out
    }

    fn write(&self, out: &mut String) {
        match self {
            Value::Null => out.push_str("null"),
            Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Value::Num(n) => {
                if n.fract() == 0.0 && n.is_finite() {
                    let _ = write!(out, "{}", *n as i64);
                } else {
                    let _ = write!(out, "{n}");
                }
            }
            Value::Str(s) => write_string(s, out),
            Value::List(items) => {
                out.push('[');
                for (i, v) in items.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    v.write(out);
                }
                out.push(']');
            }
            Value::Obj(m) => {
                out.push('{');
                for (i, (k, v)) in m.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write_string(k, out);
                    out.push(':');
                    v.write(out);
                }
                out.push('}');
            }
        }
    }
}

fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// Parse a complete JSON value.
pub fn parse(s: &str) -> Result<Value, String> {
    let b: Vec<char> = s.chars().collect();
    let mut i = 0;
    skip_ws(&b, &mut i);
    let v = parse_value(&b, &mut i)?;
    skip_ws(&b, &mut i);
    if i != b.len() {
        return Err(format!("trailing input at {i}"));
    }
    Ok(v)
}

fn parse_value(b: &[char], i: &mut usize) -> Result<Value, String> {
    match peek(b, *i) {
        Some('"') => Ok(Value::Str(parse_string(b, i)?)),
        Some('{') => {
            *i += 1;
            let mut m = BTreeMap::new();
            skip_ws(b, i);
            if peek(b, *i) == Some('}') {
                *i += 1;
                return Ok(Value::Obj(m));
            }
            loop {
                skip_ws(b, i);
                let k = parse_string(b, i)?;
                skip_ws(b, i);
                expect(b, i, ':')?;
                skip_ws(b, i);
                m.insert(k, parse_value(b, i)?);
                skip_ws(b, i);
                match peek(b, *i) {
                    Some(',') => *i += 1,
                    Some('}') => {
                        *i += 1;
                        break;
                    }
                    other => return Err(format!("expected `,` or `}}`, got {other:?}")),
                }
            }
            Ok(Value::Obj(m))
        }
        Some('[') => {
            *i += 1;
            let mut items = Vec::new();
            skip_ws(b, i);
            if peek(b, *i) == Some(']') {
                *i += 1;
                return Ok(Value::List(items));
            }
            loop {
                skip_ws(b, i);
                items.push(parse_value(b, i)?);
                skip_ws(b, i);
                match peek(b, *i) {
                    Some(',') => *i += 1,
                    Some(']') => {
                        *i += 1;
                        break;
                    }
                    other => return Err(format!("expected `,` or `]`, got {other:?}")),
                }
            }
            Ok(Value::List(items))
        }
        Some('t') => lit(b, i, "true", Value::Bool(true)),
        Some('f') => lit(b, i, "false", Value::Bool(false)),
        Some('n') => lit(b, i, "null", Value::Null),
        Some(_) => {
            let start = *i;
            while let Some(c) = peek(b, *i) {
                if c == ',' || c == '}' || c == ']' || c.is_whitespace() {
                    break;
                }
                *i += 1;
            }
            let text: String = b[start..*i].iter().collect();
            text.parse::<f64>()
                .map(Value::Num)
                .map_err(|e| format!("{text:?}: {e}"))
        }
        None => Err("unexpected end of input".into()),
    }
}

fn lit(b: &[char], i: &mut usize, word: &str, v: Value) -> Result<Value, String> {
    for c in word.chars() {
        if peek(b, *i) != Some(c) {
            return Err(format!("expected `{word}`"));
        }
        *i += 1;
    }
    Ok(v)
}

fn parse_string(b: &[char], i: &mut usize) -> Result<String, String> {
    expect(b, i, '"')?;
    let mut out = String::new();
    loop {
        match peek(b, *i) {
            None => return Err("unterminated string".into()),
            Some('"') => {
                *i += 1;
                return Ok(out);
            }
            Some('\\') => {
                *i += 1;
                let c = peek(b, *i).ok_or("unterminated escape")?;
                *i += 1;
                out.push(match c {
                    'n' => '\n',
                    't' => '\t',
                    'r' => '\r',
                    'b' => '\u{8}',
                    'f' => '\u{c}',
                    'u' => {
                        let hex: String = b.get(*i..*i + 4).ok_or("short \\u")?.iter().collect();
                        *i += 4;
                        let n = u32::from_str_radix(&hex, 16).map_err(|e| e.to_string())?;
                        char::from_u32(n).ok_or("bad code point")?
                    }
                    other => other,
                });
            }
            Some(c) => {
                *i += 1;
                out.push(c);
            }
        }
    }
}

fn peek(b: &[char], i: usize) -> Option<char> {
    b.get(i).copied()
}

fn skip_ws(b: &[char], i: &mut usize) {
    while matches!(peek(b, *i), Some(c) if c.is_whitespace()) {
        *i += 1;
    }
}

fn expect(b: &[char], i: &mut usize, c: char) -> Result<(), String> {
    if peek(b, *i) == Some(c) {
        *i += 1;
        Ok(())
    } else {
        Err(format!("expected `{c}`, got {:?}", peek(b, *i)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips() {
        let src = r#"{"a":[1,"two",true,null],"b":{"c":-3.5}}"#;
        let v = parse(src).unwrap();
        assert_eq!(v.to_json(), src);
    }

    #[test]
    fn escapes_survive_a_round_trip() {
        let v = Value::str("line\nquote\"back\\slash\ttab");
        assert_eq!(parse(&v.to_json()).unwrap(), v);
    }

    #[test]
    fn unicode_escapes_decode() {
        assert_eq!(parse(r#""∣""#).unwrap(), Value::str("∣"));
    }

    #[test]
    fn integers_do_not_grow_a_decimal_point() {
        // MCP peers read `id` back as an integer; `1.0` is a different value to some.
        assert_eq!(Value::Num(1.0).to_json(), "1");
    }

    #[test]
    fn trailing_input_is_an_error() {
        assert!(parse("{} {}").is_err());
    }
}
