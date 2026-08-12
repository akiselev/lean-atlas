"""Read and rewrite constant names inside an I3 statement encoding.

The encoding (`statement-hash.md`) is prefix-free UTF-8 text:

    expr ::= "b" nat | "s(" level ")" | "c(" name levels ")" | "a(" expr "," expr ")"
           | "l" bi "(" expr "," expr ")" | "p" bi "(" expr "," expr ")"
           | "e(" expr "," expr "," expr ")" | "n" nat | "t" len ":" bytes
           | "j(" name "," nat "," expr ")"
    name ::= len ":" bytes        -- byte length prefix

Two rules make a scan rather than a parse sufficient, and both matter:

**Names are counted in bytes, not characters.** `c(3:ℝ,0)` is three bytes and one
character, so everything here works on `bytes` and never on `str`.

**Names and string literals are skipped by their length prefix**, so a `c(` occurring
*inside* a name can never be mistaken for a constant marker. That is the whole reason a
scan is safe; a naive `str.replace` on the same data is not, and would corrupt the length
prefix it did not update.
"""

from __future__ import annotations

TAG = b"atlas-stmt-v1;"


def _read_len(buf: bytes, i: int) -> tuple[int, int] | None:
    """Parse `<digits>:` at `i`. Returns `(value, index after the colon)`."""
    j = i
    while j < len(buf) and 0x30 <= buf[j] <= 0x39:
        j += 1
    if j == i or j >= len(buf) or buf[j] != 0x3A:  # ':'
        return None
    return int(buf[i:j]), j + 1


def _spans(buf: bytes):
    """Yield `(start, end)` byte spans of every constant name in the encoding.

    `start`/`end` bound the name's bytes, not its length prefix. Also skips string
    literals, whose payload could otherwise contain a forged `c(` marker.
    """
    i, n = 0, len(buf)
    while i < n:
        ch = buf[i]
        if (ch == 0x63 or ch == 0x6A) and i + 1 < n and buf[i + 1] == 0x28:  # 'c(' / 'j('
            got = _read_len(buf, i + 2)
            if got is None:
                i += 1
                continue
            ln, after = got
            yield after, after + ln
            i = after + ln
            continue
        if ch == 0x74:  # 't' — a string literal iff digits+':' follow (else binder info)
            got = _read_len(buf, i + 1)
            if got is not None:
                ln, after = got
                i = after + ln
                continue
        i += 1


def constants(encoding: str) -> list[str]:
    """Every constant name the statement mentions, in order, with repeats."""
    buf = encoding.encode()
    return [buf[a:b].decode("utf-8", "replace") for a, b in _spans(buf)]


def rename(encoding: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Rewrite constant names through `mapping`, fixing each length prefix.

    Returns the new encoding and how many occurrences were rewritten.
    """
    buf = encoding.encode()
    out = bytearray()
    last = 0
    hits = 0
    for a, b in _spans(buf):
        name = buf[a:b].decode("utf-8", "replace")
        new = mapping.get(name)
        if new is None:
            continue
        # Back up over the `<digits>:` prefix so it can be rewritten with the new length.
        p = a - 1  # the ':'
        q = p - 1
        while q >= 0 and 0x30 <= buf[q] <= 0x39:
            q -= 1
        out += buf[last:q + 1]
        nb = new.encode()
        out += str(len(nb)).encode() + b":" + nb
        last = b
        hits += 1
    out += buf[last:]
    return out.decode("utf-8", "replace"), hits
