#!/usr/bin/env python3
"""LaTeX display equations -> dimensional constraint rows, for the validated solver.

`scripts/phys_dimlib.py` holds a dimensional-analysis solver that has already recovered 154
multi-atom laws from a *Lean* physics library (`research/physlib-calculus.md`). The solver
knows nothing about Lean: it consumes rows of `dict[atom_id, Fraction]` meaning "this sum of
exponents is zero", eliminates per-item variables blockwise, and takes the RREF over ℚ. Only
the front end is Lean-specific. This file is a **second front end** — LaTeX display
equations instead of I3 trees — so that the same solver can be pointed at physics *papers*.

Nothing in `phys_dimlib.py` or `phys_i3.py` is edited or reimplemented here. `AtomTable`,
`Echelon` and `eliminate_locals` are imported.

The grading is never given. Not one line below says "velocity is L/T". The exponent lattice
is inferred from the equation system alone, which is the whole point: it works on quantities
that have no standard units.

===========================================================================================
PRE-REGISTRATION — written before any corpus was run, and not edited afterwards
===========================================================================================

WHAT A GOOD ANSWER LOOKS LIKE

  P1  On a hand-built Newtonian corpus whose grading is known by hand (M, L, T), the
      recovered null space is *exactly* the truth: grading dimension **3**, and all three
      truth exponent vectors satisfy **every** row. Not "at least 3" — exactly 3, because a
      larger null space means a symbol was never connected and a smaller one means a false
      constraint was invented.

  P2  Laws that are **not stated** are recovered as consequences: from {F=ma, a=dv/dt,
      v=dx/dt, p=mv, E=½mv², W=Fx, P=dW/dt} the system must *imply* D(E)=D(F)+D(x) and
      D(P)=D(F)+D(v), and must **not** imply D(E)=D(p) or D(F)=D(m).

  P3  On a larger hand-built corpus (58 equations, mechanics + gravitation + rotation +
      fluids + one QM relation, exercising derivatives, integrals, \\nabla, \\dot, \\Delta,
      exp, cos, sqrt and fractional powers) the grading dimension is again exactly **3** and
      truth violations are **0**.

  N1  Injecting a dimensionally WRONG equation must be *detected*: the grading dimension
      must strictly drop. Pre-registered target 100% of injections detected, on both
      corpora. A detector that never says "inconsistent" is worthless.

  N1b The same detector must NOT fire on dimensionally CORRECT equations that were not in
      the corpus — otherwise it is flagging novelty, not error. Pre-registered target 0%
      false-alarm rate. (This is the control the injection control needs: N1 narrows, and
      §3 of CLAUDE.md says narrowing is where false negatives are manufactured.)

  N2  Shuffling symbol identities across equations (per-row bijection on the atom pool,
      coefficients and row shapes preserved) must **collapse** the grading: median grading
      dimension across 20 seeds strictly below the real one, and the truth grading contained
      in 0/20 shuffled null spaces.

WHAT WOULD SHOW IT DOES NOT WORK

  * P1/P3 recovering a grading dimension **above** 3 — symbols are not being identified
    across equations, so the parser is minting a fresh atom per occurrence and the system is
    nearly empty. (This is exactly the `_open` defect `phys_dimlib.py` documents: the
    failure presents as "physics has no structure".)
  * P1/P3 recovering a grading dimension **below** 3, or any truth violation — a parse rule
    invented a constraint. That is the unrecoverable direction and it collapses the lattice.
  * N1 detection rate materially below 100%: the solver cannot see dimensional error, so
    every positive result is unfalsifiable.
  * N1b false-alarm rate above 0%: "detected" means "new", not "wrong".
  * N2 not collapsing: the recovered structure is an artifact of row *shapes* rather than of
    which symbols the paper actually related, and every headline number is uninterpretable.
  * A parse rate reported without a failure taxonomy. A silently skipped equation is a false
    negative and nothing downstream can tell.

===========================================================================================
THE READING RULES, AND WHICH DIRECTION EACH ONE ERRS IN
===========================================================================================

`phys_dimlib.py` states the asymmetry that governs every choice here: *"a collision merges
two atoms — the direction that manufactures a constraint and collapses the lattice. Losing a
constraint is recoverable; inventing one is not."* So wherever LaTeX is ambiguous, the rule
below is the one that **splits** rather than merges, or that emits **nothing** rather than
a guess. Each is counted and reported so the choice can be audited on a real paper.

  * `f(x)` is **application**, not product: D(f(x)) = D(f), argument unconstrained. If the
    truth were a product we lose one constraint; if we had guessed product and the truth
    were `V(r)`, we would have invented `D(V) + D(r)`. `--paren product` is the ablation.
  * A symbolic superscript is an **index**, not a power: `A^\\mu` is its own atom. A
    superscript that evaluates to a rational is a power. A *compound* superscript (contains
    an operator) is forced **dimensionless**, which is sound for a real exponent.
  * `e^{X}` is `exp(X)` **only when X is not a rational literal**. `e^2` is read as a
    squared quantity, because `e` is the elementary charge at least as often as it is
    Euler's number, and reading `e^2/(4\\pi\\epsilon_0 r)` as an exponential would assert
    that charge is dimensionless — a catastrophic false constraint.
  * `\\dot x`, `\\nabla`, `\\partial_\\mu` each spend a **shared global atom** (`«dot»`,
    `«nabla»`, `«partial»`) rather than being tied by name to `t` or `x`. The solver then
    *derives* `«dot» = t` from the equations if the paper says so. Nothing is assumed;
    `«nabla» = «partial»` is likewise left to the equations.
  * `\\Delta X` is transparent (`D(\\Delta X) = D(X)`) — that is not a physics fact, it
    follows from the sum rule applied to `X_2 - X_1`. `--delta opaque` is the ablation.
  * `\\propto` and `\\sim` emit **nothing**: proportionality hides a dimensionful constant.
    `<`, `>`, `\\le`, `\\ge`, `\\ll`, `\\gg` emit an equality — comparison requires it.
  * A numeric literal is dimensionless, **except** `0` and except a bare literal alone on
    one side of a relation (`E = 0`, `c = 1`), which get a free per-equation atom. `0` is
    the additive unit at every dimension and `c = 1` is a choice of units, not a claim that
    speed is dimensionless.
  * Anything not understood becomes a fresh **local** atom, eliminated blockwise, so the row
    it sits in degrades to no-information rather than to a wrong constraint.

Usage:

    uv run scripts/paper-dim.py --selftest            # the gate, ~1.5 s; non-zero on failure
    uv run scripts/paper-dim.py --tex paper.tex --show 20 --shuffle
    uv run scripts/paper-dim.py --tex paper.tex --dump-failures 20
    uv run scripts/paper-dim.py --eqs equations.txt   # one LaTeX equation per line

`--tex` wants a flattened source: `find . -name '*.tex' -exec cat {} + > paper.tex`.
"""

from __future__ import annotations

import argparse
import collections
import os
import random
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from phys_dimlib import (AtomTable, Echelon, eliminate_locals,  # noqa: E402
                         _add, _scale, _sub)

ZERO = Fraction(0)
ONE = Fraction(1)

# The three operators that spend a coordinate nobody named. Global atoms: two occurrences of
# `\dot` anywhere in the paper are the same denominator, which is what makes `«dot» = t`
# derivable rather than assumed.
DOT_ATOM = "«dot»"
NABLA_ATOM = "«nabla»"
PARTIAL_ATOM = "«partial»"

# Genuinely dimensionless by construction, in every unit system. `\pi` is a numeral; `i` is
# NOT in this set, because `i` is an index far more often than it is √-1.
DIMENSIONLESS = {"\\pi", "\\Pi"}

EULER = {"e", "\\mathrm{e}"}


class ParseError(Exception):
    """Carries a short *category* so the driver can report a failure taxonomy."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Dropped outright: they change spacing or size, never meaning.
SKIP_CMDS = {
    "\\left", "\\right", "\\big", "\\Big", "\\bigg", "\\Bigg", "\\bigl", "\\bigr",
    "\\Bigl", "\\Bigr", "\\biggl", "\\biggr", "\\Biggl", "\\Biggr",
    "\\displaystyle", "\\textstyle", "\\scriptstyle", "\\limits", "\\nolimits",
    "\\nonumber", "\\notag", "\\label", "\\qquad", "\\quad", "\\hfill", "\\hspace",
    "\\phantom", "\\hphantom", "\\vphantom", "\\rule", "\\ ", "\\!", "\\smallskip",
}
# `\label{...}` also has to lose its argument; handled by ARG_EATING.
ARG_EATING = {"\\label", "\\tag", "\\hspace", "\\phantom", "\\hphantom", "\\vphantom",
              "\\ref", "\\eqref", "\\cite", "\\color", "\\textcolor", "\\substack",
              "\\intertext", "\\raisebox", "\\qq", "\\qqtext"}
# `\notag` deliberately absent: it takes no argument, and listing it here made it swallow
# the next token — which on an `align` continuation is the `&` *and then* the operator, so
# the equation lost its second half and failed as `unexpected-op`.

# Transparent decoration: the decorated symbol is the same quantity. `\bar x` is a mean,
# `\vec v` is the vector whose magnitude is `v`; both share a dimension with `x` and `v`.
DECOR_CMDS = {
    "\\vec", "\\hat", "\\bar", "\\tilde", "\\overline", "\\widetilde", "\\widehat",
    "\\overrightarrow", "\\overleftarrow", "\\underline", "\\check", "\\breve",
    "\\mathbf", "\\boldsymbol", "\\bm", "\\mathbfit", "\\pmb",
}
# Name-changing font: `\mathcal{L}` is conventionally a *different* object from `L`, so
# merging them would be the unsafe direction.
NAME_CMDS = {"\\mathcal", "\\mathbb", "\\mathfrak", "\\mathscr", "\\mathsf"}
# Roman text: the content becomes the symbol's name, so `\mathrm{d}` is the differential and
# `\mathrm{kg}` is a unit atom.
TEXT_CMDS = {"\\mathrm", "\\text", "\\textrm", "\\mbox", "\\operatorname", "\\mathit",
             "\\textnormal", "\\rm", "\\mathop"}

THIN_SPACE = {"\\,", "\\;", "\\:", "\\!", "\\ "}

# Spelled-out delimiters, normalised to the punctuation the parser already knows.
DELIM_ALIAS = {
    "\\lvert": ("op", "|"), "\\rvert": ("op", "|"), "\\vert": ("op", "|"),
    "\\lVert": ("cmd", "\\|"), "\\rVert": ("cmd", "\\|"), "\\Vert": ("cmd", "\\|"),
    "\\lbrace": ("op", "("), "\\rbrace": ("op", ")"),
    "\\lbrack": ("op", "["), "\\rbrack": ("op", "]"),
    "\\lparen": ("op", "("), "\\rparen": ("op", ")"),
}

_LETTER = re.compile(r"[A-Za-z]")
_NUM = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def _read_balanced(s: str, i: int) -> tuple[str, int]:
    """`s[i]` is `{`; return the inner text and the index just past the matching `}`."""
    depth = 0
    j = i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise ParseError("unbalanced-brace")


def _next_arg_text(s: str, i: int) -> tuple[str, int]:
    """The next macro argument as raw text: a braced group, or a single token."""
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s):
        raise ParseError("truncated-macro")
    if s[i] == "{":
        return _read_balanced(s, i)
    if s[i] == "\\":
        j = i + 1
        while j < len(s) and _LETTER.match(s[j]):
            j += 1
        return s[i:max(j, i + 2)], max(j, i + 2)
    return s[i], i + 1


def tokenize(src: str) -> list[tuple[str, str]]:
    """`(kind, value)` tokens: `sym`, `num`, `cmd`, `op`.

    `~` is emitted for an explicit thin space. It is *not* noise: it is the only signal
    separating `\\sin\\omega t` (argument `\\omega t`) from `\\sin\\theta\\,mv` (argument
    `\\theta`), and reading the second as `sin(\\theta m v)` would invent D(m)+D(v)=0.
    """
    toks: list[tuple[str, str]] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == "%":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "&":
            i += 1
            continue
        if c == "\\":
            j = i + 1
            if j < n and _LETTER.match(src[j]):
                k = j
                while k < n and _LETTER.match(src[k]):
                    k += 1
                name, i = src[i:k], k
                if name in ARG_EATING:
                    try:
                        _, i = _next_arg_text(src, i)
                    except ParseError:
                        pass
                    continue
                if name in SKIP_CMDS:
                    continue
                if name in DECOR_CMDS:
                    continue                       # transparent; the group follows
                if name in TEXT_CMDS or name in NAME_CMDS:
                    body, i = _next_arg_text(src, i)
                    body = body.strip()
                    if name in NAME_CMDS:
                        toks.append(("sym", f"{name}{{{body}}}"))
                    elif re.fullmatch(r"[A-Za-z0-9]+", body):
                        toks.append(("sym", body))
                    else:
                        toks.extend(tokenize(body))
                    continue
                if name == "\\begin" or name == "\\end":
                    body, i = _next_arg_text(src, i)
                    raise ParseError("environment", body)
                if name in DELIM_ALIAS:
                    toks.append(DELIM_ALIAS[name])
                    continue
                if name in PHYSICS_PKG_ALIAS:
                    toks.append(PHYSICS_PKG_ALIAS[name])
                    continue
                toks.append(("cmd", name))
                continue
            two = src[i:i + 2]
            i += 2
            if two in THIN_SPACE:
                toks.append(("op", "~"))
                continue
            if two == "\\\\":
                toks.append(("op", "\\\\"))
                continue
            if two in ("\\{", "\\}"):
                toks.append(("op", "(" if two == "\\{" else ")"))
                continue
            if two == "\\|":
                toks.append(("cmd", "\\|"))
                continue
            toks.append(("cmd", two))
            continue
        m = _NUM.match(src, i)
        if m:
            toks.append(("num", m.group(0)))
            i = m.end()
            continue
        if _LETTER.match(c):
            toks.append(("sym", c))
            i += 1
            continue
        if c in "{}()[]_^|+-*/=<>,!'":
            toks.append(("op", c))
            i += 1
            continue
        if c in "⟨⟩":
            toks.append(("cmd", "\\langle" if c == "⟨" else "\\rangle"))
            i += 1
            continue
        if c in ".;:":
            i += 1
            continue
        # Unicode operators a paper may use directly.
        if c in "×·":
            toks.append(("cmd", "\\cdot" if c == "·" else "\\times"))
            i += 1
            continue
        if c == "−":
            toks.append(("op", "-"))
            i += 1
            continue
        toks.append(("sym", c))
        i += 1
    return toks


def cleanup_tokens(toks):
    """Two rewrites that recover equations the grammar would otherwise reject.

    `\\bm{\\cdot}` leaves `{ \\cdot }` once the font command is dropped, and a braced group
    holding one bare operator is not an expression. And a display equation almost always ends
    in the sentence's punctuation — `E = mc^2,` — which is trailing garbage to the grammar
    and was the single largest parse-failure category measured on real papers.
    """
    out = []
    i = 0
    while i < len(toks):
        if (toks[i] == ("op", "{") and i + 2 < len(toks) and toks[i + 2] == ("op", "}")
                and toks[i + 1][0] == "cmd"
                and (toks[i + 1][1] in MUL_CMDS or toks[i + 1][1] in ADD_CMDS
                     or relop_of(toks[i + 1]) is not None)):
            out.append(toks[i + 1])
            i += 3
            continue
        out.append(toks[i])
        i += 1
    while out and (out[-1] in (("op", ","), ("op", "~"), ("op", "\\\\"))
                   or out[-1][0] == "cmd" and out[-1][1] in ("\\qedhere", "\\nonumber")):
        out.pop()
    while out and out[0] in (("op", ","), ("op", "~")):
        out.pop(0)
    return out


def render_tokens(toks: list[tuple[str, str]]) -> str:
    out = []
    for k, v in toks:
        out.append(v if k != "op" or v not in ("~",) else "")
    return "".join(out)


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

EQ_RELS = {"=", "\\equiv", "\\approx", "\\simeq", "\\cong", "\\doteq", "\\coloneqq",
           "\\define", "\\triangleq"}
ORD_RELS = {"<", ">", "\\le", "\\leq", "\\ge", "\\geq", "\\ll", "\\gg", "\\lesssim",
            "\\gtrsim"}
# Emits nothing on purpose: `F \propto 1/r^2` hides a dimensionful constant, so an equality
# here would be a fabricated constraint.
SILENT_RELS = {"\\propto", "\\sim", "\\in", "\\to", "\\rightarrow", "\\mapsto", "\\ne",
               "\\neq", "\\Rightarrow", "\\Leftrightarrow", "\\iff", "\\subset",
               "\\subseteq", "\\supset", "\\approxeq", "\\leftrightarrow", "\\longrightarrow"}

ADD_OPS = {"+", "-"}
ADD_CMDS = {"\\pm", "\\mp"}
MUL_CMDS = {"\\cdot", "\\times", "\\ast", "\\otimes", "\\wedge", "\\star", "\\bullet",
            "\\circ"}

TRANS_FUNCS = {"\\exp", "\\log", "\\ln", "\\lg", "\\sin", "\\cos", "\\tan", "\\cot",
               "\\sec", "\\csc", "\\sinh", "\\cosh", "\\tanh", "\\coth", "\\arcsin",
               "\\arccos", "\\arctan", "\\erf", "\\erfc", "\\sgn", "\\sign"}

DIFF_TOKS = {("sym", "d"), ("cmd", "\\partial"), ("sym", "D")}

# Commands that name a *symbol*. Listing them buys nothing at parse time — an unrecognised
# command already becomes an atom — but it keeps the audit census honest: `\omega` topping a
# list headed "unrecognised" hides the entries that actually need a human, and the first
# measured census was 213 `\omega` above 139 `\abs`.
GREEK = {"alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
         "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron",
         "pi", "varpi", "rho", "varrho", "sigma", "varsigma", "tau", "upsilon", "phi",
         "varphi", "chi", "psi", "omega"}
KNOWN_SYMBOL_CMDS = ({f"\\{g}" for g in GREEK}
                     | {f"\\{g[0].upper()}{g[1:]}" for g in GREEK}
                     | {"\\hbar", "\\ell", "\\imath", "\\jmath", "\\aleph", "\\wp",
                        "\\prime", "\\dagger", "\\ast", "\\star", "\\circ", "\\bullet",
                        "\\top", "\\perp", "\\parallel", "\\emptyset", "\\varnothing",
                        "\\Re", "\\Im", "\\hslash", "\\eth", "\\mho"})

# The `physics` LaTeX package. Its macros are *notation* — `\cross` is `\times`, `\dv` is
# `d/dx` — and they are undefined in the source because the package supplies them, so the
# `\newcommand` sweep cannot see them. Measured on 15 arXiv sources, `\abs` (139) and
# `\cross` (121) were the two largest genuinely-unrecognised commands; left alone each
# becomes a spurious atom sitting inside a product.
PHYSICS_PKG_ALIAS = {
    "\\cross": ("cmd", "\\times"), "\\vdot": ("cmd", "\\cdot"),
    "\\dotproduct": ("cmd", "\\cdot"), "\\crossproduct": ("cmd", "\\times"),
    "\\grad": ("cmd", "\\nabla"), "\\curl": ("cmd", "\\nabla"),
    "\\divergence": ("cmd", "\\nabla"), "\\laplacian": ("cmd", "\\nabla"),
    "\\dd": ("sym", "d"), "\\rmd": ("sym", "d"),
}
# Same package, argument-taking. Rewritten to text before tokenizing, which is the only
# place a `#1`-style expansion belongs.
# `\abs` and `\norm` are NOT here. Expanding them to `\left|…\right|` produced bars the
# grammar cannot pair with the paper's own bars, and cost 29 of 257 equations on one
# measured source — the largest single regression in this file's history. They are handled
# as parser commands instead, where the argument's extent is known.
PHYSICS_PKG_MACROS = {
    "\\qty": (1, "\\left(#1\\right)"), "\\pqty": (1, "\\left(#1\\right)"),
    "\\bqty": (1, "\\left[#1\\right]"), "\\va": (1, "\\vec{#1}"),
    "\\vb": (1, "\\mathbf{#1}"), "\\vu": (1, "\\hat{#1}"),
    "\\ket": (1, "|#1\\rangle"), "\\bra": (1, "\\langle #1|"),
    "\\braket": (2, "\\langle #1|#2\\rangle"),
    "\\ev": (1, "\\langle #1\\rangle"), "\\expval": (1, "\\langle #1\\rangle"),
    "\\dv": (2, "\\frac{d#1}{d#2}"), "\\pdv": (2, "\\frac{\\partial#1}{\\partial#2}"),
    "\\dif": (0, "d"), "\\Tr": (0, "\\operatorname{Tr}"), "\\tr": (0, "\\operatorname{tr}"),
}

OPEN_DELIM = {"(", "[", "{", "|"}
CLOSE_DELIM = {")", "]", "}", "|"}


def relop_of(tok) -> str | None:
    if tok is None:
        return None
    k, v = tok
    if k == "op" and v in ("=", "<", ">"):
        return v
    if k == "cmd" and (v in EQ_RELS or v in ORD_RELS or v in SILENT_RELS):
        return v
    return None


def _group_at(toks, i):
    """Token list of the group starting at `i` (braced or single token), and the next index."""
    if i >= len(toks):
        raise ParseError("truncated-group")
    if toks[i] == ("op", "{"):
        depth, j = 0, i
        while j < len(toks):
            if toks[j] == ("op", "{"):
                depth += 1
            elif toks[j] == ("op", "}"):
                depth -= 1
                if depth == 0:
                    return toks[i + 1:j], j + 1
            j += 1
        raise ParseError("unbalanced-brace")
    return [toks[i]], i + 1


class Parser:
    def __init__(self, toks, opts=None):
        self.t = toks
        self.i = 0
        self.opts = opts or {}
        self.notes = collections.Counter()
        # An unrecognised command becomes an atom, which is the safe direction but is *not*
        # free: it enters every product it sits in. Named here rather than merely counted,
        # because the only way to know whether `\Tr` should have been a rule is to see it.
        self.unknown = collections.Counter()

    # -- cursor --------------------------------------------------------------

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def next(self):
        t = self.peek()
        if t is None:
            raise ParseError("truncated")
        self.i += 1
        return t

    def take_group(self):
        g, self.i = _group_at(self.t, self.i)
        return g

    def sub(self, toks):
        p = Parser(toks, self.opts)
        ast = p.p_expr()
        if p.peek() is not None:
            raise ParseError("trailing-tokens", render_tokens(p.t[p.i:])[:30])
        self.notes.update(p.notes)
        self.unknown.update(p.unknown)
        return ast

    # -- relations -----------------------------------------------------------

    def p_document(self):
        """A chain `a = b = c` becomes two relations; a silent relation ends the chain."""
        rels = []
        lhs = self.p_expr()
        while True:
            op = relop_of(self.peek())
            if op is None:
                break
            self.next()
            rhs = self.p_expr()
            if op in SILENT_RELS:
                self.notes["silent-relation"] += 1
            else:
                rels.append((op, lhs, rhs))
            lhs = rhs
        if self.peek() is not None:
            raise ParseError("trailing-tokens", render_tokens(self.t[self.i:])[:30])
        return rels

    # -- expressions ---------------------------------------------------------

    def p_expr(self):
        terms = [self.p_term()]
        while True:
            t = self.peek()
            if t is None:
                break
            if t[0] == "op" and t[1] in ADD_OPS:
                self.next()
                terms.append(self.p_term())
                continue
            if t[0] == "cmd" and t[1] in ADD_CMDS:
                self.next()
                terms.append(self.p_term())
                continue
            break
        return terms[0] if len(terms) == 1 else ("add", terms)

    def starts_factor(self, t) -> bool:
        if t is None:
            return False
        k, v = t
        if k in ("sym", "num"):
            return True
        if k == "op":
            return v in OPEN_DELIM and v != "}"
        if k == "cmd":
            if v in MUL_CMDS or v in ADD_CMDS or relop_of(t):
                return False
            return True
        return False

    def p_term(self, stop_at_space=False):
        node = self.p_factor()
        while True:
            t = self.peek()
            if t is None:
                break
            if t == ("op", "~"):
                if stop_at_space:
                    break
                self.next()
                continue
            if t == ("op", "/") or t == ("cmd", "\\div"):
                self.next()
                node = ("div", node, self.p_factor())
                continue
            if t == ("op", "*") or (t[0] == "cmd" and t[1] in MUL_CMDS):
                self.next()
                node = ("mul", [node, self.p_factor()])
                continue
            if self.starts_factor(t):
                node = ("mul", [node, self.p_factor()])
                continue
            break
        return node

    def p_factor(self):
        t = self.peek()
        if t is not None and ((t[0] == "op" and t[1] in ADD_OPS)
                              or (t[0] == "cmd" and t[1] in ADD_CMDS)):
            self.next()
            return ("neg", self.p_factor())
        node, name = self.p_primary()
        while True:
            t = self.peek()
            if t is None:
                break
            if t == ("op", "_"):
                self.next()
                g = self.take_group()
                if name is not None:
                    name = f"{name}_{{{render_tokens(g)}}}"
                    node = ("sym", name)
                else:
                    self.notes["subscript-on-compound"] += 1
                continue
            if t == ("op", "'"):
                self.next()
                if name is not None:
                    name += "'"
                    node = ("sym", name)
                continue
            if t == ("op", "^"):
                self.next()
                g = self.take_group()
                node, name = self.apply_super(node, name, g)
                continue
            if t == ("op", "!"):
                self.next()
                node = ("dimensionless", node)
                name = None
                continue
            if t == ("op", "|") and self.peek(1) == ("op", "_"):
                # `\left. f \right|_{x=0}` is an evaluation, not a magnitude: same dimension,
                # and the subscript is a condition rather than a quantity.
                self.next()
                self.next()
                self.take_group()
                self.notes["evaluation-bar"] += 1
                continue
            if t == ("op", "(") and name is not None and self.opts.get("paren") != "product":
                args = self.p_arglist()
                self.notes["application"] += 1
                node = ("app", node, args)
                name = None
                continue
            break
        return node

    def apply_super(self, node, name, g):
        kind, val = self.classify_super(g)
        if name in EULER and kind != "rat":
            self.notes["euler-exp"] += 1
            return ("trans", self.sub(g)), None
        if kind == "rat":
            return ("pow", node, val), None
        if kind == "name" and name is not None:
            self.notes["index-superscript"] += 1
            nm = f"{name}^{{{val}}}"
            return ("sym", nm), nm
        # A compound superscript is a real exponent, and a real exponent is dimensionless.
        # That is sound; the powered term itself is not linear in the exponents, so it goes
        # opaque rather than guessing.
        self.notes["symbolic-power"] += 1
        return ("opaque-with", self.sub(g)), None

    def classify_super(self, g):
        try:
            q = const_fold(self.sub(g))
        except ParseError:
            q = None
        if q is not None:
            return ("rat", q)
        if g and all(k == "sym" or (k == "cmd" and _LETTER.match(v[1:2] or ""))
                     for k, v in g):
            return ("name", render_tokens(g))
        return ("expr", g)

    def p_arglist(self):
        assert self.next() == ("op", "(")
        args, depth, start = [], 0, self.i
        while True:
            t = self.peek()
            if t is None:
                raise ParseError("unbalanced-paren")
            if t[0] == "op" and t[1] in "([{":
                depth += 1
            elif t[0] == "op" and t[1] in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif t == ("op", ",") and depth == 0:
                args.append(self.t[start:self.i])
                self.i += 1
                start = self.i
                continue
            self.i += 1
        args.append(self.t[start:self.i])
        self.next()
        return [self.sub(a) for a in args if a]

    # -- primaries -----------------------------------------------------------

    def p_primary(self):
        t = self.peek()
        if t is None:
            raise ParseError("truncated")
        k, v = t
        if k == "num":
            self.next()
            return ("num", Fraction(v) if "." not in v
                    else Fraction(v).limit_denominator(10 ** 9)), None
        if k == "sym":
            self.next()
            return ("sym", v), v
        if k == "op":
            if v == "(" or v == "[":
                close = ")" if v == "(" else "]"
                self.next()
                parts = [self.p_expr()]
                while self.peek() == ("op", ","):
                    self.next()
                    parts.append(self.p_expr())
                if self.peek() != ("op", close):
                    raise ParseError("unbalanced-paren")
                self.next()
                if len(parts) == 1:
                    inner = parts[0]
                    return inner, inner[1] if inner[0] == "sym" else None
                # `[A,B]` is a commutator and `(a,b)` a pair; both scale as the product.
                self.notes["bracket-list"] += 1
                return ("mul", parts), None
            if v == "{":
                g = self.take_group()
                inner = self.sub(g)
                return inner, inner[1] if inner[0] == "sym" else None
            if v == "|":
                # `|x|` is a magnitude and `|n\rangle` is a ket. Deciding by which delimiter
                # closes first is the only reading that does not reject every quantum paper:
                # `\rangle` with no matching bar was 38 of the measured parse failures.
                j, depth = self.i + 1, 0
                closer = None
                while j < len(self.t):
                    k2, v2 = self.t[j]
                    if k2 == "op" and v2 in "([{":
                        depth += 1
                    elif k2 == "op" and v2 in ")]}":
                        if depth == 0:
                            break
                        depth -= 1
                    elif depth == 0 and (self.t[j] == ("op", "|")
                                         or self.t[j] == ("cmd", "\\rangle")):
                        closer = j
                        break
                    j += 1
                if closer is not None and self.t[closer] == ("cmd", "\\rangle"):
                    body = self.t[self.i + 1:closer]
                    self.i = closer + 1
                    self.notes["ket"] += 1
                    nm = "|" + render_tokens(body) + "\\rangle"
                    return ("sym", nm), nm
                self.next()
                inner = self.p_expr()
                if self.peek() != ("op", "|"):
                    raise ParseError("unbalanced-bar")
                self.next()
                return ("magnitude", inner), None
            raise ParseError("unexpected-op", v)
        # k == "cmd"
        return self.p_command(v)

    def p_command(self, v):
        if v in ("\\frac", "\\dfrac", "\\tfrac", "\\cfrac", "\\nicefrac"):
            self.next()
            num = self.take_group()
            den = self.take_group()
            d = self.as_derivative(num, den)
            if d is not None:
                return d, None
            return ("div", self.sub(num), self.sub(den)), None
        if v == "\\sqrt":
            self.next()
            root = Fraction(1, 2)
            if self.peek() == ("op", "["):
                self.next()
                g, depth = [], 0
                while self.peek() is not None and not (depth == 0
                                                       and self.peek() == ("op", "]")):
                    if self.peek()[0] == "op" and self.peek()[1] in "([{":
                        depth += 1
                    if self.peek()[0] == "op" and self.peek()[1] in ")]}":
                        depth -= 1
                    g.append(self.next())
                if self.peek() is None:
                    raise ParseError("unbalanced-bracket")
                self.next()
                q = const_fold(self.sub(g)) if g else None
                if q is None or q == 0:
                    raise ParseError("symbolic-root")
                root = 1 / q
            return ("pow", self.sub(self.take_group()), root), None
        if v in TRANS_FUNCS:
            self.next()
            if self.peek() == ("op", "^"):
                self.next()
                self.take_group()
            arg = self.trans_arg()
            return ("trans", arg), None
        if v in ("\\dot", "\\ddot", "\\dddot"):
            self.next()
            order = Fraction({"\\dot": 1, "\\ddot": 2, "\\dddot": 3}[v])
            self.notes["overdot"] += 1
            return ("deriv", self.sub(self.take_group()),
                    [(("sym", DOT_ATOM), order)]), None
        if v == "\\nabla":
            self.next()
            order = ONE
            if self.peek() == ("op", "^"):
                self.next()
                # `\nabla^2` is a Laplacian; `\nabla^\nu` is a *raised index* on a first-order
                # derivative. Rejecting the second lost equations from every relativity paper
                # measured, and reading it as a power would have been worse.
                q = const_fold_tokens(self.take_group())
                order = q if q is not None else ONE
            if self.peek() is not None and self.peek()[0] == "cmd" \
                    and self.peek()[1] in ("\\cdot", "\\times"):
                self.next()
            if self.peek() == ("op", "_"):
                self.next()
                self.take_group()
            if not self.starts_factor(self.peek()):
                return ("sym", "\\nabla"), "\\nabla"
            self.notes["nabla"] += 1
            return ("deriv", self.p_factor(),
                    [(("sym", NABLA_ATOM), order)]), None
        if v in ("\\Box", "\\square"):
            self.next()
            if self.peek() == ("op", "^"):
                self.next()
                self.take_group()
            if not self.starts_factor(self.peek()):
                return ("sym", v), v
            return ("deriv", self.p_factor(),
                    [(("sym", PARTIAL_ATOM), Fraction(2))]), None
        if v == "\\partial":
            self.next()
            order = ONE
            if self.peek() == ("op", "_"):
                self.next()
                self.take_group()
            if self.peek() == ("op", "^"):
                self.next()
                q = const_fold_tokens(self.take_group())
                order = q if q is not None else ONE
            if not self.starts_factor(self.peek()):
                return ("sym", "\\partial"), "\\partial"
            self.notes["partial-operator"] += 1
            return ("deriv", self.p_factor(),
                    [(("sym", PARTIAL_ATOM), order)]), None
        if v in ("\\int", "\\oint", "\\iint", "\\iiint", "\\intop"):
            return self.p_integral(v), None
        if v in ("\\sum", "\\tsum"):
            self.next()
            self.eat_limits()
            self.notes["sum"] += 1
            return self.p_term(), None
        if v in ("\\prod", "\\bigotimes", "\\bigoplus"):
            self.next()
            self.eat_limits()
            self.notes["product-operator"] += 1
            return ("opaque-with", self.p_term()), None
        if v in ("\\lim", "\\limsup", "\\liminf", "\\max", "\\min", "\\sup", "\\inf",
                 "\\arg", "\\argmin", "\\argmax"):
            self.next()
            self.eat_limits()
            return self.p_term(), None
        if v == "\\Delta" and self.opts.get("delta") != "opaque":
            self.next()
            if self.peek() == ("op", "^"):
                # `\Delta^2` is a Laplacian, not a difference. Refuse rather than guess.
                raise ParseError("delta-power")
            if not self.starts_factor(self.peek()):
                return ("sym", "\\Delta"), "\\Delta"
            self.notes["delta-difference"] += 1
            inner = self.p_factor()
            return inner, inner[1] if inner[0] == "sym" else None
        if v == "\\langle":
            self.next()
            parts, cur = [], []
            depth = 0
            while True:
                t = self.peek()
                if t is None:
                    raise ParseError("unbalanced-angle")
                if t == ("cmd", "\\rangle") and depth == 0:
                    self.next()
                    break
                if t == ("cmd", "\\langle"):
                    depth += 1
                if t == ("op", "|") and depth == 0:
                    self.next()
                    parts.append(cur)
                    cur = []
                    continue
                cur.append(self.next())
            parts.append(cur)
            parts = [p for p in parts if p]
            if not parts:
                raise ParseError("empty-bracket")
            asts = [self.sub(p) for p in parts]
            # `⟨x⟩` is an expectation (same dimension); `⟨a|b⟩` is a pairing (product).
            return (asts[0] if len(asts) == 1 else ("mul", asts)), None
        if v in ("\\abs", "\\norm", "\\magnitude", "\\modulus"):
            self.next()
            return ("magnitude", self.sub(self.take_group())), None
        if v == "\\|":
            self.next()
            inner = self.p_expr()
            if self.peek() != ("cmd", "\\|"):
                raise ParseError("unbalanced-norm")
            self.next()
            return ("magnitude", inner), None
        if v in ("\\infty",):
            self.next()
            return ("free",), None
        if v in ("\\cdots", "\\ldots", "\\dots", "\\vdots", "\\ddots"):
            raise ParseError("ellipsis")
        if v in MUL_CMDS or v in ADD_CMDS or relop_of(("cmd", v)):
            raise ParseError("dangling-operator", v)
        # An unrecognised command becomes an atom. Safe: it can only fail to constrain.
        self.next()
        if not re.fullmatch(r"\\[A-Za-z]+", v):
            raise ParseError("unknown-symbol", v)
        if v not in KNOWN_SYMBOL_CMDS:
            self.notes["unknown-command"] += 1
            self.unknown[v] += 1
        return ("sym", v), v

    def eat_limits(self):
        while self.peek() is not None and self.peek()[0] == "op" \
                and self.peek()[1] in ("_", "^"):
            self.next()
            self.take_group()

    def trans_arg(self):
        """The argument of an unparenthesized `\\sin`/`\\log`/… .

        Parenthesized: one factor, unambiguous. Bare: the rest of the product up to an
        explicit thin space, because `\\sin\\omega t` means `sin(ωt)` and reading it as
        `sin(ω)·t` would assert D(ω)=0 — a false constraint on a real frequency.
        """
        t = self.peek()
        if t is not None and t[0] == "op" and t[1] in ("(", "[", "{", "|"):
            return self.p_factor()
        if t is not None and t == ("cmd", "\\|"):
            return self.p_factor()
        self.notes["bare-transcendental-arg"] += 1
        return self.p_term(stop_at_space=True)

    # -- derivatives written as fractions ------------------------------------

    def as_derivative(self, num, den):
        dn = split_differential(num)
        if dn is None:
            return None
        k_num, body = dn
        segs = split_denominator(den)
        if segs is None:
            return None
        wrt = []
        for var_toks, k_den in segs:
            if not var_toks:
                return None
            # The numerator's order is the *total* order, so it may only be pushed onto a
            # single denominator factor. `\partial^2 u / (\partial x \partial y)` is first
            # order in each; reading the 2 onto both would square the whole rule.
            order = k_den if (k_den != 1 or len(segs) > 1) else k_num
            wrt.append((self.sub(var_toks), order))
        if not body:
            # Operator form `\frac{d}{dt} X`: the operand is the following *product*, which
            # is what `\frac{d}{dt} m v = F` means.
            self.notes["derivative-operator"] += 1
            body_ast = self.p_term()
        else:
            self.notes["derivative-fraction"] += 1
            body_ast = self.sub(body)
        return ("deriv", body_ast, wrt)

    # -- integrals -----------------------------------------------------------

    def p_integral(self, kind):
        self.next()
        lo = hi = None
        while self.peek() is not None and self.peek()[0] == "op" \
                and self.peek()[1] in ("_", "^"):
            mark = self.next()[1]
            g = self.take_group()
            ast = self.sub(g) if g else None
            if mark == "_":
                lo = ast
            else:
                hi = ast
        start = self.i
        end = self.body_end(start)
        found = self.find_measure(start, end)
        if found is None:
            self.notes["integral-no-measure"] += 1
            body = self.t[start:end]
            measure = None
        else:
            mi, mj, order, var_toks = found
            if mi == start:
                body = self.t[mj:end]
                self.notes["integral-measure-first"] += 1
            else:
                body = self.t[start:mi] + self.t[mj:end]
                self.notes["integral"] += 1
            measure = (self.sub(var_toks), order)
        self.i = end
        if not body:
            raise ParseError("empty-integrand")
        return ("integral", self.sub(body), measure, lo, hi)

    def body_end(self, start):
        depth, j = 0, start
        while j < len(self.t):
            k, v = self.t[j]
            if k == "op" and v in "([{":
                depth += 1
            elif k == "op" and v in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0:
                if relop_of(self.t[j]) is not None:
                    break
                if (k == "op" and v in ADD_OPS and j > start) or v == "\\\\":
                    break
                if k == "cmd" and v in ADD_CMDS:
                    break
            j += 1
        return j

    def find_measure(self, start, end):
        """`(i, j, order, var_tokens)` for the differential `d^k x` inside `[start, end)`."""
        depth = 0
        hits = []
        j = start
        while j < end:
            k, v = self.t[j]
            if k == "op" and v in "([{":
                depth += 1
            elif k == "op" and v in ")]}":
                depth -= 1
            elif depth == 0 and self.t[j] in DIFF_TOKS and self.t[j] != ("sym", "D"):
                m = j + 1
                order = ONE
                if m < end and self.t[m] == ("op", "^"):
                    try:
                        g, m2 = _group_at(self.t, m + 1)
                    except ParseError:
                        g, m2 = None, None
                    if g is not None:
                        q = const_fold(self.sub(g))
                        if q is not None:
                            order, m = q, m2
                if m < end and self.t[m][0] in ("sym", "cmd"):
                    var = [self.t[m]]
                    m += 1
                    while m + 1 < end and self.t[m] == ("op", "_"):
                        g, m = _group_at(self.t, m + 1)
                        var += [("op", "_"), ("op", "{")] + g + [("op", "}")]
                    hits.append((j, m, order, var))
            j += 1
        if not hits:
            return None
        for h in hits:
            if h[0] == start:
                return h
        return hits[-1]


def split_differential(toks):
    """`d`/`\\partial` with an optional `^k`, then the rest. `None` if not a differential."""
    if not toks or toks[0] not in DIFF_TOKS:
        return None
    i = 1
    k = ONE
    if i < len(toks) and toks[i] == ("op", "^"):
        try:
            g, i2 = _group_at(toks, i + 1)
        except ParseError:
            return None
        q = const_fold_tokens(g)
        if q is None:
            return None
        k, i = q, i2
    return k, toks[i:]


def split_denominator(toks):
    """`dx`, `dt^2`, `\\partial x \\partial y` -> [(var_tokens, order), …]."""
    if not toks or toks[0] not in DIFF_TOKS:
        return None
    segs = []
    i = 0
    while i < len(toks):
        if toks[i] not in DIFF_TOKS:
            return None
        j = i + 1
        while j < len(toks) and toks[j] not in DIFF_TOKS:
            j += 1
        body = toks[i + 1:j]
        order = ONE
        for p in range(len(body) - 1, -1, -1):
            if body[p] == ("op", "^"):
                try:
                    g, e = _group_at(body, p + 1)
                except ParseError:
                    g, e = None, None
                if g is not None and e == len(body):
                    q = const_fold_tokens(g)
                    if q is not None:
                        order, body = q, body[:p]
                break
        segs.append((body, order))
        i = j
    return segs


def const_fold(ast):
    """The rational an AST denotes, or `None`."""
    if ast is None:
        return None
    k = ast[0]
    if k == "num":
        return ast[1]
    if k == "neg":
        v = const_fold(ast[1])
        return None if v is None else -v
    if k == "div":
        a, b = const_fold(ast[1]), const_fold(ast[2])
        return None if a is None or b is None or b == 0 else a / b
    if k == "mul":
        acc = ONE
        for x in ast[1]:
            v = const_fold(x)
            if v is None:
                return None
            acc *= v
        return acc
    if k == "add":
        acc = ZERO
        for x in ast[1]:
            v = const_fold(x)
            if v is None:
                return None
            acc += v
        return acc
    if k == "pow":
        b = const_fold(ast[1])
        if b is None or ast[2].denominator != 1:
            return None
        try:
            return b ** int(ast[2])
        except (ValueError, ZeroDivisionError):
            return None
    return None


def const_fold_tokens(toks):
    try:
        return const_fold(Parser(toks).p_expr())
    except ParseError:
        return None


# ---------------------------------------------------------------------------
# AST -> constraint rows
# ---------------------------------------------------------------------------

class Walker:
    """Turns one equation's AST into rows over `AtomTable` atoms.

    Global atoms are keyed by the symbol's rendered name, so two equations that mention `v`
    mention the same atom — that identification across equations is the only thing that makes
    a paper a *system*. Everything not understood becomes a per-equation **local** atom, which
    `eliminate_locals` projects away; the row then says nothing rather than something wrong.
    """

    def __init__(self, table: AtomTable, eq_id: str) -> None:
        self.table = table
        self.eq = eq_id
        self.rows: list[dict[int, Fraction]] = []
        self._fresh = 0
        self.opaque = 0
        self.understood = 0

    def fresh(self) -> int:
        self._fresh += 1
        return self.table.intern(f"?{self.eq}#f{self._fresh}", True)

    def atom(self, key: str) -> int:
        return self.table.intern(key, False)

    def emit(self, row):
        if row:
            self.rows.append(row)

    # -- the dimension of a node --------------------------------------------

    def dim(self, ast) -> dict[int, Fraction]:
        k = ast[0]
        if k == "sym":
            name = ast[1]
            if name in DIMENSIONLESS:
                self.understood += 1
                return {}
            self.understood += 1
            return {self.atom(name): ONE}
        if k == "num":
            self.understood += 1
            # `0` is the additive unit at every dimension; asserting it dimensionless would
            # invent a constraint everywhere `x = 0` appears.
            return {self.fresh(): ONE} if ast[1] == 0 else {}
        if k == "free":
            return {self.fresh(): ONE}
        if k == "add":
            self.understood += 1
            d = self.dim(ast[1][0])
            for x in ast[1][1:]:
                self.emit(_sub(d, self.dim(x)))
            return d
        if k == "neg":
            self.understood += 1
            return self.dim(ast[1])
        if k == "mul":
            self.understood += 1
            acc: dict[int, Fraction] = {}
            for x in ast[1]:
                acc = _add(acc, self.dim(x))
            return acc
        if k == "div":
            self.understood += 1
            return _sub(self.dim(ast[1]), self.dim(ast[2]))
        if k == "pow":
            self.understood += 1
            return _scale(self.dim(ast[1]), ast[2])
        if k == "magnitude":
            self.understood += 1
            return self.dim(ast[1])
        if k == "trans":
            self.understood += 1
            self.emit(self.dim(ast[1]))       # the argument must be dimensionless
            return {}
        if k == "dimensionless":
            self.understood += 1
            self.emit(self.dim(ast[1]))
            return {}
        if k == "app":
            self.understood += 1
            for a in ast[2]:
                self.dim(a)                   # kept for the `+` rows inside the argument
            return self.dim(ast[1])
        if k == "deriv":
            self.understood += 1
            d = self.dim(ast[1])
            for var, order in ast[2]:
                d = _sub(d, _scale(self.dim(var), order))
            return d
        if k == "integral":
            self.understood += 1
            d = self.dim(ast[1])
            _, measure, lo, hi = ast[1], ast[2], ast[3], ast[4]
            if measure is None:
                d = _add(d, {self.fresh(): ONE})
                mvar = None
            else:
                mvar = self.dim(measure[0])
                d = _add(d, _scale(mvar, measure[1]))
            for lim in (lo, hi):
                if lim is not None and mvar is not None:
                    self.emit(_sub(self.dim(lim), mvar))
                elif lim is not None:
                    self.dim(lim)
            return d
        if k == "opaque-with":
            self.opaque += 1
            self.dim(ast[1])
            return {self.fresh(): ONE}
        self.opaque += 1
        return {self.fresh(): ONE}

    def relation(self, op, lhs, rhs):
        self.emit(_sub(self.side(lhs), self.side(rhs)))

    def side(self, ast):
        """A bare literal alone on one side of a relation is a choice of units, not a claim.

        `c = 1` and `E = 0` must not force `c` and `E` dimensionless, so the literal gets a
        free per-equation atom that `eliminate_locals` then removes along with the row.
        """
        if ast[0] == "num" or (ast[0] == "neg" and ast[1][0] == "num"):
            return {self.fresh(): ONE}
        return self.dim(ast)


# ---------------------------------------------------------------------------
# Driver: LaTeX text -> a solved system
# ---------------------------------------------------------------------------

_NEWCMD = re.compile(r"\\(?:re)?newcommand\s*\*?\s*(?:\{\s*(\\[A-Za-z@]+)\s*\}|(\\[A-Za-z@]+))"
                     r"\s*(?:\[(\d+)\])?\s*(?:\[[^\]]*\])?\s*\{")
_DEF = re.compile(r"\\def\s*(\\[A-Za-z@]+)((?:#\d)*)\s*\{")
_MATHOP = re.compile(r"\\DeclareMathOperator\s*\*?\s*\{\s*(\\[A-Za-z@]+)\s*\}\s*\{([^}]*)\}")


def collect_macros(tex: str) -> dict[str, tuple[int, str]]:
    """`\\newcommand` / `\\def` / `\\DeclareMathOperator` definitions found anywhere in a source.

    Not optional. Fifteen recent arXiv physics sources carry 113 `\\newcommand`s, 69 `\\def`s
    and 3 `\\DeclareMathOperator`s between them, and an unexpanded `\\rpd{\\mu}` reads as a
    product with a symbol nobody wrote — a *constraint the paper does not assert*. That is
    the direction this file exists to avoid, so the definitions are read rather than ignored.
    """
    macros: dict[str, tuple[int, str]] = dict(PHYSICS_PKG_MACROS)
    for m in _MATHOP.finditer(tex):
        macros[m.group(1)] = (0, "\\operatorname{" + m.group(2).strip() + "}")
    for pat, nidx in ((_NEWCMD, 3), (_DEF, 2)):
        for m in pat.finditer(tex):
            name = m.group(1) or m.group(2)
            if not name:
                continue
            try:
                body, _ = _read_balanced(tex, m.end() - 1)
            except ParseError:
                continue
            raw = m.group(nidx)
            n = int(raw) if (raw and raw.isdigit()) else (len(raw) // 2 if raw else 0)
            macros[name] = (n, body)
    return macros


def expand_macros(src: str, macros, rounds=6) -> str:
    if not macros:
        return src
    for _ in range(rounds):
        out, i, changed = [], 0, False
        while i < len(src):
            if src[i] != "\\":
                out.append(src[i])
                i += 1
                continue
            j = i + 1
            while j < len(src) and _LETTER.match(src[j]):
                j += 1
            name = src[i:j]
            spec = macros.get(name)
            if spec is None or j == i + 1:
                out.append(src[i:max(j, i + 2)])
                i = max(j, i + 2)
                continue
            n, body = spec
            args, k = [], j
            ok = True
            for _a in range(n):
                try:
                    a, k = _next_arg_text(src, k)
                except ParseError:
                    ok = False
                    break
                args.append(a)
            if not ok:
                out.append(src[i:j])
                i = j
                continue
            rep = body
            for a in range(n, 0, -1):
                rep = rep.replace(f"#{a}", "{" + args[a - 1] + "}")
            out.append(rep)
            i = k
            changed = True
        src = "".join(out)
        if not changed:
            break
    return src


DISPLAY_PATTERNS = [
    re.compile(r"\\begin\{(equation\*?|align\*?|alignat\*?|eqnarray\*?|gather\*?|"
               r"multline\*?|displaymath|dmath\*?|flalign\*?)\}(.*?)\\end\{\1\}", re.S),
    re.compile(r"\$\$(.*?)\$\$", re.S),
    re.compile(r"\\\[(.*?)\\\]", re.S),
]

_SPLIT_ENV = re.compile(r"\\(?:begin|end)\{(?:split|aligned|array|cases|matrix|pmatrix|"
                        r"bmatrix|vmatrix|smallmatrix|subequations)\}(?:\{[^}]*\})?")


_CONT_START = re.compile(r"^\s*&?\s*(=|<|>|\+|-|\\(?:equiv|approx|simeq|cong|le|leq|ge|geq"
                         r"|ll|gg|times|cdot|pm|mp|propto|sim)\b)")
_QUAD = re.compile(r"\\q?quad\b|\\hspace\s*\{[^}]*\}")

# English connectives, not quantities. A displayed equation often carries its own prose tail
# — `x = y \quad \text{where } y = z` — and `\text{where}` reaching the expression grammar
# becomes an *atom in a product*, which is a constraint nobody asserted. Measured: one paper
# recovered the relation `\phi = -\theta_{amp} - where`. The list is English, auditable, and
# contains no physics; `\text{kg}` and `\text{const}` are deliberately not in it.
PROSE_WORDS = {"where", "with", "and", "or", "for", "if", "otherwise", "else", "when",
               "while", "as", "since", "hence", "thus", "therefore", "respectively",
               "provided", "such", "that", "here", "we", "have", "is", "are", "let",
               "then", "given", "all", "any", "each", "both", "of", "in", "on", "to",
               "from", "by", "at", "so", "but", "also", "note", "recall"}
_PROSE = re.compile(r"\\(?:text|mbox|textrm|textnormal)\s*\{\s*(" +
                    "|".join(sorted(PROSE_WORDS)) + r")\b", re.I)


def extract_display(tex: str, macros=None, repair=True) -> list[str]:
    """Every display equation in a LaTeX source, one parseable relation per entry.

    Three splits, each of which was a measured false negative on real papers:

    * `\\\\` inside an `align` separates equations — **except** when the next line begins with
      a relation or a binary operator, which is a *continuation* (`X &= A \\\\ &= B`). Reading
      those as separate equations produced 194 `unexpected-op` failures and lost the
      continuation's content entirely.
    * `\\quad` separates two equations typeset on one line (`dt = dT, \\quad dr = …`).
    * a top-level `,` between two relations does the same.
    """
    out, spans = [], []
    if macros:
        tex = expand_macros(tex, macros)
    for pat in DISPLAY_PATTERNS:
        for m in pat.finditer(tex):
            body = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
            spans.append((m.start(), m.end(), body))
    spans.sort()
    taken_to = -1
    for s, e, body in spans:
        if s < taken_to:
            continue
        taken_to = e
        body = _SPLIT_ENV.sub("", body)
        lines: list[str] = []
        for line in body.split("\\\\"):
            # `\\[-2mm]` is vertical spacing, and its bracket lands at the start of the
            # *next* equation, where it reads as a bracketed expression.
            line = re.sub(r"^\s*\[[^\]]{0,12}\]", "", line)
            if not line.strip():
                continue
            if lines and _CONT_START.match(line):
                lines[-1] = lines[-1] + " " + line.strip()
            else:
                lines.append(line.strip())
        pieces = []
        for line in lines:
            line = _PROSE.split(line)[0]
            for piece in _QUAD.split(line):
                piece = piece.strip().strip(",.;").strip()
                if piece:
                    pieces.append(piece)
        out.extend(_repair(pieces) if repair else pieces)
    return out


def _parses(src: str) -> bool:
    try:
        parse_equation(src)
        return True
    except (ParseError, RecursionError):
        return False


def _repair(pieces: list[str]) -> list[str]:
    """Re-join a fragment that only parses when glued to its predecessor.

    `_CONT_START` catches the continuations that *begin* with an operator; it does not catch
    `\\Bigg[ … ` or a line that resumes inside a bracket. Rather than widen a regex until it
    starts merging genuinely separate equations, the merge is attempted only where the split
    demonstrably failed and the merge demonstrably works — which cannot lose an equation that
    already parsed.
    """
    out: list[str] = []
    for p in pieces:
        if out and not _parses(p):
            joined = out[-1] + " " + p
            if _parses(joined):
                out[-1] = joined
                continue
        out.append(p)
    return out


def parse_equation(src: str, opts=None):
    """LaTeX -> `(relations, parser_notes)`; raises `ParseError` with a category."""
    toks = tokenize(src)
    toks = cleanup_tokens([t for t in toks if t != ("op", "\\\\")])
    if not toks:
        raise ParseError("empty")
    p = Parser(toks, opts)
    rels = p.p_document()
    return rels, p.notes, p.unknown


class System:
    def __init__(self) -> None:
        self.table = AtomTable()
        self.global_rows: list[dict[int, Fraction]] = []
        self.provenance: list[str] = []
        self.parsed = 0
        self.attempted = 0
        self.with_rows = 0
        self.failures = collections.Counter()
        self.fail_examples: dict[str, str] = {}
        self.notes = collections.Counter()
        self.unknown = collections.Counter()
        self.opaque = 0
        self.understood = 0

    def add(self, src: str, name: str | None = None, opts=None) -> bool:
        self.attempted += 1
        eq_id = name or f"eq{self.attempted}"
        try:
            rels, notes, unknown = parse_equation(src, opts)
        except ParseError as ex:
            self.failures[ex.kind] += 1
            self.fail_examples.setdefault(ex.kind, src[:110])
            return False
        except RecursionError:
            self.failures["recursion"] += 1
            self.fail_examples.setdefault("recursion", src[:110])
            return False
        self.parsed += 1
        self.notes.update(notes)
        self.unknown.update(unknown)
        w = Walker(self.table, eq_id)
        for op, lhs, rhs in rels:
            w.relation(op, lhs, rhs)
        if not rels:
            # No relation, but the expression's own `+` nodes are still constraints.
            for _ in ():
                pass
        self.opaque += w.opaque
        self.understood += w.understood
        grows = eliminate_locals(w.rows, lambda c: self.table.is_local[c])
        if grows:
            self.with_rows += 1
        for r in grows:
            self.global_rows.append(r)
            self.provenance.append(eq_id)
        return True

    def solve(self):
        ech = Echelon(order=lambda c: self.table.keys[c])
        for r in self.global_rows:
            ech.add(r)
        return ech, ech.columns()


def grading_dim(rows) -> tuple[int, int, int]:
    ech = Echelon()
    for r in rows:
        ech.add(r)
    cols = ech.columns()
    return len(cols), ech.rank, len(cols) - ech.rank


def classify(ech):
    single = [c for c, r in ech.pivots.items() if len(r) == 1]
    pairs = [(c, r) for c, r in ech.pivots.items() if len(r) == 2]
    rich = [(c, r) for c, r in ech.pivots.items() if len(r) >= 3]
    powered = [(c, r) for c, r in rich if any(abs(v) != 1 for v in r.values())]
    return single, pairs, rich, powered


def _coef(v):
    if v == 1:
        return "+ "
    if v == -1:
        return "- "
    return ("+ " if v > 0 else "- ") + str(abs(v)) + "*"


def render_relation(table, col, row, width=6):
    terms = [f"{_coef(-v)}{table.keys[c]}"
             for c, v in sorted(row.items(), key=lambda kv: table.keys[kv[0]]) if c != col]
    if not terms:
        return f"{table.keys[col]} = 0"
    body = " ".join(terms[:width]) + ("" if len(terms) <= width
                                      else f" … (+{len(terms) - width})")
    return f"{table.keys[col]} = " + body.lstrip("+ ")


def rows_by_name(table, rows):
    return [{table.keys[c]: v for c, v in r.items()} for r in rows]


def shuffle_rows(rows, rng):
    """Rewire which symbol each entry names, keeping every row's shape and coefficients.

    A **bijection** per row, so no two entries of one row can collide onto one atom: a
    collision would shrink the row and make the control easier to pass than it should be.
    """
    pool = sorted({c for r in rows for c in r})
    out = []
    for r in rows:
        pick = rng.sample(pool, len(r))
        out.append({pick[i]: v for i, (c, v) in enumerate(r.items())})
    return out


# ---------------------------------------------------------------------------
# The hand-built corpora whose grading is known before the code runs
# ---------------------------------------------------------------------------

MECH_SMALL = [
    r"F = m a",
    r"a = \frac{dv}{dt}",
    r"v = \frac{dx}{dt}",
    r"p = m v",
    r"E = \frac{1}{2} m v^2",
    r"W = F x",
    r"P = \frac{dW}{dt}",
]

MECH_SMALL_TRUTH = {
    #      M   L   T
    "F": (1, 1, -2), "m": (1, 0, 0), "a": (0, 1, -2), "v": (0, 1, -1),
    "t": (0, 0, 1), "x": (0, 1, 0), "p": (1, 1, -1), "E": (1, 2, -2),
    "W": (1, 2, -2), "P": (1, 2, -3),
}

PHYS_BIG = [
    r"F = m a",
    r"a = \frac{dv}{dt}",
    r"v = \frac{dx}{dt}",
    r"p = m v",
    r"F = \frac{dp}{dt}",
    r"K = \frac{1}{2} m v^2",
    r"W = \int F \, dx",
    r"P = \frac{dW}{dt}",
    r"P = F v",
    r"U = m g h",
    r"E = K + U",
    r"g = \frac{G M}{r^2}",
    r"F = \frac{G M m}{r^2}",
    r"v = \omega r",
    r"\omega = 2 \pi f",
    r"f = \frac{1}{T_p}",
    r"\omega = \sqrt{\frac{k}{m}}",
    r"U = \frac{1}{2} k x^2",
    r"I = m r^2",
    r"L = I \omega",
    r"\tau = r F",
    r"\tau = \frac{dL}{dt}",
    r"K = \frac{1}{2} I \omega^2",
    r"\rho = \frac{m}{V}",
    r"V = A h",
    r"A = 4 \pi r^2",
    r"P_r = \frac{F}{A}",
    r"E = \hbar \omega",
    r"p = \frac{\hbar}{\lambda}",
    r"E = m c^2",
    r"v = a t",
    r"x = v t + \frac{1}{2} a t^2",
    r"v^2 = 2 a x",
    r"T_p = 2 \pi \sqrt{\frac{m}{k}}",
    r"E = \frac{p^2}{2 m}",
    r"W = \Delta K",
    r"\mu = \frac{m M}{m + M}",
    r"P = \tau \omega",
    r"h = \frac{1}{2} g t^2",
    r"\beta = \frac{v}{c}",
    r"x = A_0 e^{-t / \tau_d} \cos(\omega t + \phi)",
    r"\int_0^{T_p} v \, dt = x",
    r"\nabla \cdot \vec{g} = - 4 \pi G \rho",
    r"L = m v r",
    r"K = \frac{L^2}{2 I}",
    r"P = \frac{W}{t}",
    r"\omega = \frac{2 \pi}{T_p}",
    r"F = - k x",
    r"a = \frac{v^2}{r}",
    r"\rho = \frac{M}{V}",
    r"P_r = \rho g h",
    r"E = \frac{1}{2} m v^2 + m g h",
    r"v = \frac{\lambda}{T_p}",
    r"\dot{x} = v",
    r"\ddot{x} = a",
    r"m \ddot{x} = - k x",
    r"W = \int_0^x F \, dx",
    r"\tau = I \frac{d\omega}{dt}",
]

PHYS_BIG_TRUTH = {
    #                  M   L   T
    "t": (0, 0, 1), "x": (0, 1, 0), "r": (0, 1, 0), "h": (0, 1, 0),
    "\\lambda": (0, 1, 0), "A_{0}": (0, 1, 0),
    "m": (1, 0, 0), "M": (1, 0, 0), "\\mu": (1, 0, 0),
    "v": (0, 1, -1), "c": (0, 1, -1),
    "a": (0, 1, -2), "g": (0, 1, -2),
    "F": (1, 1, -2), "p": (1, 1, -1),
    "K": (1, 2, -2), "U": (1, 2, -2), "E": (1, 2, -2), "W": (1, 2, -2),
    "P": (1, 2, -3),
    "\\omega": (0, 0, -1), "f": (0, 0, -1),
    "T_{p}": (0, 0, 1), "\\tau_{d}": (0, 0, 1),
    "k": (1, 0, -2), "I": (1, 2, 0), "L": (1, 2, -1), "\\hbar": (1, 2, -1),
    "\\tau": (1, 2, -2), "\\rho": (1, -3, 0), "V": (0, 3, 0), "A": (0, 2, 0),
    "P_{r}": (1, -1, -2), "G": (-1, 3, -2),
    "\\phi": (0, 0, 0), "\\beta": (0, 0, 0),
    NABLA_ATOM: (0, 1, 0), DOT_ATOM: (0, 0, 1),
}

# Each of these is dimensionally wrong given the corpus above, in a different way: a dropped
# factor, a wrong power, a dimensionful transcendental argument, a mismatched sum.
WRONG_SMALL = [
    (r"E = m v", "dropped a velocity"),
    (r"F = m v", "force as momentum"),
    (r"\theta = \sin(t)", "dimensionful trig argument"),
    (r"p = m v^2", "wrong power"),
    (r"W = F x + p", "sum of unlike terms"),
    (r"a = \frac{dx}{dt}", "derivative order off by one"),
]
CORRECT_SMALL = [
    (r"E = F x", "restates a derivable law"),
    (r"P = F v", "restates a derivable law"),
    (r"I = m x^2", "correct, introduces a new symbol"),
    (r"\rho_2 = \frac{m}{x^3}", "correct, introduces two new symbols"),
    (r"J = F t", "correct, new symbol"),
]

WRONG_BIG = [
    (r"E = m v", "dropped a velocity"),
    (r"F = \frac{G M m}{r}", "wrong power in Newtonian gravity"),
    (r"T_p = 2 \pi \sqrt{\frac{k}{m}}", "inverted radicand"),
    (r"\omega = \frac{v}{r^2}", "wrong power"),
    (r"E = \hbar \omega^2", "wrong power"),
    (r"x = A_0 \cos(\omega + \phi)", "dimensionful trig argument"),
    (r"P = \frac{W}{t^2}", "wrong power"),
    (r"L = I \omega + p", "sum of unlike terms"),
    (r"\rho = \frac{m}{A}", "area for volume"),
    (r"K = \frac{1}{2} m v", "dropped a velocity"),
    (r"g = \frac{G M}{r^3}", "wrong power"),
    (r"W = \int F \, dt", "wrong measure"),
]
CORRECT_BIG = [
    (r"E = F r", "correct and derivable"),
    (r"P = \tau \omega", "correct and already present"),
    (r"J_i = m r^2", "correct, new symbol"),
    (r"\Phi = g A", "correct, new symbol"),
    (r"\sigma = \frac{m}{A}", "correct, new symbol"),
    (r"S_a = \frac{E}{T_p}", "correct, new symbol"),
    (r"v_e = \sqrt{\frac{2 G M}{r}}", "correct escape speed, derivable"),
]


def build(equations, opts=None, prefix="eq") -> System:
    sysm = System()
    for i, eq in enumerate(equations):
        sysm.add(eq, f"{prefix}{i}", opts)
    return sysm


def truth_violations(table, rows, truth) -> list[tuple[int, dict]]:
    """Rows the known grading does not satisfy, plus rows mentioning an unexpected atom."""
    bad = []
    for idx, row in enumerate(rows):
        named = {table.keys[c]: v for c, v in row.items()}
        if any(k not in truth for k in named):
            bad.append((idx, named))
            continue
        for d in range(len(next(iter(truth.values())))):
            s = sum(v * truth[k][d] for k, v in named.items())
            if s != 0:
                bad.append((idx, named))
                break
    return bad


def truth_in_nullspace(table, rows, truth) -> bool:
    return not truth_violations(table, rows, truth)


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

class Gate:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.checks = 0

    def check(self, ok, label, got=None, want=None):
        self.checks += 1
        if ok:
            print(f"  ok    {label}" + (f"   [{got}]" if got is not None else ""))
        else:
            msg = f"{label}: got {got!r}, want {want!r}"
            print(f"  FAIL  {msg}")
            self.fails.append(msg)
        return ok

    def eq(self, got, want, label):
        return self.check(got == want, label, got, want)


PARSE_UNITS = [
    # (latex, [rows as {atom: coefficient}]) — rows compared up to sign and order.
    (r"\frac{d^2 x}{dt^2} = a", [{"x": 1, "t": -2, "a": -1}]),
    (r"a = \frac{dv}{dt}", [{"a": 1, "v": -1, "t": 1}]),
    (r"E = \hbar \omega", [{"E": 1, "\\hbar": -1, "\\omega": -1}]),
    (r"E = \frac{1}{2} m v^2", [{"E": 1, "m": -1, "v": -2}]),
    (r"c = \sqrt{\frac{T}{\mu}}", [{"c": 1, "T": Fraction(-1, 2), "\\mu": Fraction(1, 2)}]),
    (r"\int_0^{L} \rho A \, dx = m", [{"L": 1, "x": -1},
                                      {"\\rho": 1, "A": 1, "x": 1, "m": -1}]),
    (r"\theta = \sin(\omega t)", [{"\\omega": 1, "t": 1}, {"\\theta": 1}]),
    (r"y = f(x)", [{"y": 1, "f": -1}]),
    (r"\nabla \times \vec{A} = \vec{B}", [{"A": 1, NABLA_ATOM: -1, "B": -1}]),
    (r"\Delta t = t_1", [{"t": 1, "t_{1}": -1}]),
    (r"\dot{x} = v", [{"x": 1, DOT_ATOM: -1, "v": -1}]),
    (r"E = m c^2", [{"E": 1, "m": -1, "c": -2}]),
    (r"N = N_0 e^{-t/\tau}", [{"t": 1, "\\tau": -1}, {"N": 1, "N_{0}": -1}]),
    (r"\Gamma \sim \frac{1}{\tau}", []),            # `\sim` must emit nothing
    (r"v \ll c", [{"v": 1, "c": -1}]),              # comparison must emit an equality
    (r"E = 0", []),                                 # `0` must not force dimensionlessness
    (r"c = 1", []),                                 # units, not a claim
    (r"\frac{\partial^2 u}{\partial x \partial y} = w",
     [{"u": 1, "x": -1, "y": -1, "w": -1}]),
    (r"P = \frac{dE}{dt} = F v", [{"P": 1, "E": -1, "t": 1}, {"E": 1, "t": -1,
                                                              "F": -1, "v": -1}]),
    (r"A^{\mu} = j^{\mu} r", [{"A^{\\mu}": 1, "j^{\\mu}": -1, "r": -1}]),
]


def _norm_row(d):
    d = {k: Fraction(v) for k, v in d.items() if v}
    if not d:
        return ()
    first = min(d)
    f = d[first]
    return tuple(sorted((k, v / f) for k, v in d.items()))


def selftest(seeds=20, verbose=False) -> int:
    g = Gate()
    print("=" * 88)
    print("PARSER UNITS — each row is fixed here before the corpus runs")
    print("=" * 88)
    for src, want in PARSE_UNITS:
        s = System()
        ok = s.add(src, "u")
        if not ok:
            g.check(False, f"parse {src}", dict(s.failures), "parsed")
            continue
        got = {_norm_row(r) for r in rows_by_name(s.table, s.global_rows)}
        wnt = {_norm_row(r) for r in want}
        g.check(got == wnt, f"parse {src}",
                sorted(str(dict(x)) for x in got), sorted(str(dict(x)) for x in wnt))

    print()
    print("=" * 88)
    print("P1/P2 — MECH_SMALL: the grading is known by hand and must be recovered exactly")
    print("=" * 88)
    small = build(MECH_SMALL, prefix="s")
    ech, cols = small.solve()
    dim = len(cols) - ech.rank
    single, pairs, rich, powered = classify(ech)
    print(f"  equations {small.attempted}  parsed {small.parsed}  "
          f"global rows {len(small.global_rows)}")
    print(f"  columns {len(cols)}  rank {ech.rank}  grading dim {dim}")
    for c, r in sorted(ech.pivots.items(), key=lambda kv: small.table.keys[kv[0]]):
        print(f"      {render_relation(small.table, c, r)}")
    g.eq(small.parsed, len(MECH_SMALL), "P1 every equation parses")
    g.eq(len(cols), 10, "P1 columns == 10")
    g.eq(ech.rank, 7, "P1 rank == 7")
    g.eq(dim, 3, "P1 grading dimension == 3 (M, L, T)")
    g.eq(len(single), 0, "P1 no atom forced dimensionless")
    viol = truth_violations(small.table, small.global_rows, MECH_SMALL_TRUTH)
    g.eq(len(viol), 0, "P1 the hand M/L/T grading satisfies every row")
    idx = {k: small.table.ids.get(k) for k in MECH_SMALL_TRUTH}
    g.check(all(v is not None for v in idx.values()), "P1 every hand symbol became an atom",
            [k for k, v in idx.items() if v is None], [])

    def as_row(pos, neg):
        r = {}
        for k in pos:
            r[idx[k]] = r.get(idx[k], ZERO) + ONE
        for k in neg:
            r[idx[k]] = r.get(idx[k], ZERO) - ONE
        return {k: v for k, v in r.items() if v}

    g.check(ech.implies(as_row(["E"], ["F", "x"])), "P2 implies D(E) = D(F) + D(x)")
    g.check(ech.implies(as_row(["P"], ["F", "v"])), "P2 implies D(P) = D(F) + D(v)")
    g.check(not ech.implies(as_row(["E"], ["p"])), "P2 does NOT imply D(E) = D(p)")
    g.check(not ech.implies(as_row(["F"], ["m"])), "P2 does NOT imply D(F) = D(m)")

    print()
    print("=" * 88)
    print("P3 — PHYS_BIG: 58 equations, derivatives / integrals / nabla / dot / exp / sqrt")
    print("=" * 88)
    big = build(PHYS_BIG, prefix="b")
    bech, bcols = big.solve()
    bdim = len(bcols) - bech.rank
    bsingle, bpairs, brich, bpowered = classify(bech)
    print(f"  equations {big.attempted}  parsed {big.parsed}  "
          f"rows-yielding {big.with_rows}  global rows {len(big.global_rows)}")
    print(f"  columns {len(bcols)}  rank {bech.rank}  grading dim {bdim}")
    print(f"  multi-atom relations {len(brich)}  of which powered {len(bpowered)}  "
          f"forced dimensionless {len(bsingle)}")
    if big.failures:
        print(f"  parse failures {dict(big.failures)}")
    g.eq(big.parsed, len(PHYS_BIG), "P3 every equation parses")
    g.eq(bdim, 3, "P3 grading dimension == 3")
    bviol = truth_violations(big.table, big.global_rows, PHYS_BIG_TRUTH)
    if bviol:
        for i, r in bviol[:6]:
            print(f"      violating row {i}: {r}  (from {big.provenance[i]})")
    g.eq(len(bviol), 0, "P3 the hand M/L/T grading satisfies every row")
    g.check(len(brich) >= 20, "P3 at least 20 multi-atom relations", len(brich), ">=20")
    g.check(len(bpowered) >= 5, "P3 at least 5 carry a coefficient outside +-1",
            len(bpowered), ">=5")
    if verbose:
        for c, r in sorted(bech.pivots.items(), key=lambda kv: big.table.keys[kv[0]]):
            print(f"      {render_relation(big.table, c, r)}")

    print()
    print("=" * 88)
    print("N1 / N1b — the error detector, and the control that says it is not just novelty")
    print("=" * 88)

    def detect(base_eqs, extra, prefix):
        """Detected iff adding `extra` strictly reduces the grading dimension."""
        a = build(base_eqs, prefix=prefix)
        _, ca = a.solve()
        ra = len(ca) - grading_dim(a.global_rows)[1]
        b = build(list(base_eqs) + [extra], prefix=prefix)
        _, cb = b.solve()
        rb = len(cb) - grading_dim(b.global_rows)[1]
        return rb < ra, ra, rb

    for label, base, wrong, right in (
            ("MECH_SMALL", MECH_SMALL, WRONG_SMALL, CORRECT_SMALL),
            ("PHYS_BIG", PHYS_BIG, WRONG_BIG, CORRECT_BIG)):
        hits = 0
        for eq, why in wrong:
            fired, ra, rb = detect(base, eq, "n")
            hits += fired
            print(f"  {'DETECT' if fired else 'MISS  '}  {label:<11} {eq:<40} "
                  f"dim {ra}->{rb}   ({why})")
        g.eq(hits, len(wrong), f"N1 {label}: every wrong equation detected")
        false = 0
        for eq, why in right:
            fired, ra, rb = detect(base, eq, "n")
            false += fired
            print(f"  {'ALARM ' if fired else 'quiet '}  {label:<11} {eq:<40} "
                  f"dim {ra}->{rb}   ({why})")
        g.eq(false, 0, f"N1b {label}: no correct equation flagged")

    print()
    print("=" * 88)
    print("N2 — shuffle control: rewire which symbol each entry names, keep every row shape")
    print("=" * 88)
    for label, sysm, truth, real_dim in (("MECH_SMALL", small, MECH_SMALL_TRUTH, dim),
                                         ("PHYS_BIG", big, PHYS_BIG_TRUTH, bdim)):
        dims, contained, riches = [], 0, []
        for s in range(seeds):
            rng = random.Random(1000 + s)
            sh = shuffle_rows(sysm.global_rows, rng)
            ncols, rank, d = grading_dim(sh)
            e2 = Echelon()
            for r in sh:
                e2.add(r)
            riches.append(len(classify(e2)[2]))
            dims.append(d)
            if truth_in_nullspace(sysm.table, sh, truth):
                contained += 1
        dims.sort()
        med = dims[len(dims) // 2]
        print(f"  {label:<11} real grading dim {real_dim}   shuffled median {med}   "
              f"range {dims[0]}..{dims[-1]}   truth contained {contained}/{seeds}")
        print(f"              real multi-atom relations "
              f"{len(classify(sysm.solve()[0])[2])}   shuffled median "
              f"{sorted(riches)[len(riches) // 2]}")
        g.check(med < real_dim, f"N2 {label}: shuffled grading dim collapses",
                med, f"<{real_dim}")
        g.eq(contained, 0, f"N2 {label}: truth grading survives 0 shuffles")

    print()
    print("=" * 88)
    print(f"{g.checks - len(g.fails)}/{g.checks} checks passed")
    if g.fails:
        for f in g.fails:
            print(f"  FAILED: {f}")
        return 1
    print("SELFTEST PASS")
    return 0


# ---------------------------------------------------------------------------
# Running against a real document
# ---------------------------------------------------------------------------

def report(sysm: System, show=0, label="document"):
    ech, cols = sysm.solve()
    single, pairs, rich, powered = classify(ech)
    dim = len(cols) - ech.rank
    print(f"\n{'=' * 88}\n{label}\n{'=' * 88}")
    rate = sysm.parsed / max(sysm.attempted, 1)
    print(f"  display equations found      {sysm.attempted:,}")
    print(f"  parsed                       {sysm.parsed:,}  ({rate:.1%})")
    print(f"  yielded >=1 global row       {sysm.with_rows:,}  "
          f"({sysm.with_rows / max(sysm.attempted, 1):.1%} of found)")
    print(f"  global rows                  {len(sysm.global_rows):,}")
    tot = sysm.opaque + sysm.understood
    print(f"  opacity over the walk        {sysm.opaque / max(tot, 1):.1%}  "
          f"({sysm.opaque:,} opaque / {tot:,} nodes)")
    print(f"  columns                      {len(cols):,}")
    print(f"  rank                         {ech.rank:,}")
    print(f"  grading space dimension      {dim:,}")
    print(f"  forced dimensionless         {len(single):,}")
    print(f"  identifications (2 atoms)    {len(pairs):,}")
    print(f"  multi-atom relations         {len(rich):,}")
    print(f"  of which powered (coef != 1) {len(powered):,}")
    if sysm.failures:
        print("\n  parse failures by category (a silently skipped equation is a false "
              "negative):")
        for k, n in sysm.failures.most_common():
            print(f"    {n:>5}  {k:<22} e.g.  {sysm.fail_examples[k][:70]}")
    if sysm.notes:
        print("\n  reading rules that fired (each is an ambiguity resolved; audit these):")
        for k, n in sysm.notes.most_common():
            print(f"    {n:>5}  {k}")
    if sysm.unknown:
        print("\n  unrecognised commands, now atoms in whatever product they sat in:")
        for k, n in sysm.unknown.most_common(20):
            print(f"    {n:>5}  {k}")
    if show:
        print(f"\n  top {show} multi-atom relations:")
        for c, r in sorted(rich, key=lambda kv: -len(kv[1]))[:show]:
            print(f"    {render_relation(sysm.table, c, r)}")
    return ech, cols


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--tex", help="a LaTeX source file (or `-` for stdin)")
    ap.add_argument("--eqs", help="a file with one LaTeX equation per line")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--paren", choices=["apply", "product"], default="apply")
    ap.add_argument("--delta", choices=["transparent", "opaque"], default="transparent")
    ap.add_argument("--shuffle", action="store_true",
                    help="also run the N2 shuffle control on the document")
    ap.add_argument("--dump-failures", type=int, default=0)
    ap.add_argument("--no-macros", action="store_true",
                    help="ablation: do not expand \\newcommand/\\def definitions")
    args = ap.parse_args()

    if args.selftest:
        return selftest(seeds=args.seeds, verbose=args.verbose)

    opts = {"paren": args.paren, "delta": args.delta}
    if args.tex:
        src = sys.stdin.read() if args.tex == "-" else open(args.tex, encoding="utf-8",
                                                            errors="replace").read()
        macros = {} if args.no_macros else collect_macros(src)
        eqs = extract_display(src, macros)
        label = (f"{args.tex}  ({len(eqs)} display equations, "
                 f"{len(macros)} macros expanded)")
    elif args.eqs:
        eqs = [ln.strip() for ln in open(args.eqs, encoding="utf-8", errors="replace")
               if ln.strip() and not ln.strip().startswith("#")]
        label = f"{args.eqs}  ({len(eqs)} equations)"
    else:
        ap.error("one of --selftest, --tex, --eqs")
        return 2

    sysm = System()
    for i, e in enumerate(eqs):
        sysm.add(e, f"e{i}", opts)
    report(sysm, show=args.show, label=label)
    if args.dump_failures:
        print("\n  unparsed equations:")
        n = 0
        for e in eqs:
            try:
                parse_equation(e, opts)
            except (ParseError, RecursionError) as ex:
                print(f"    [{getattr(ex, 'kind', 'recursion')}] {e[:120]}")
                n += 1
                if n >= args.dump_failures:
                    break
    if args.shuffle:
        dims = []
        for s in range(args.seeds):
            rng = random.Random(2000 + s)
            dims.append(grading_dim(shuffle_rows(sysm.global_rows, rng))[2])
        dims.sort()
        ech, cols = sysm.solve()
        print(f"\n  shuffle control: real grading dim {len(cols) - ech.rank}  "
              f"shuffled median {dims[len(dims) // 2]}  range {dims[0]}..{dims[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
