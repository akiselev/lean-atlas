#!/usr/bin/env python3
"""An expert-event set of human generalization moves mined from Mathlib history.

## Why this exists

Every oracle in this repository is either the Lean kernel or the author. The kernel
answers "does this proof term still typecheck with a weaker binder", which is a soundness
question; nobody has ever asked the recall question — *does the detector find what a
mathematician finds?* — because there was no external record of what mathematicians find.

There is one source of external evidence. `mathlib4`'s history contains 33,269 commits,
and a subset of them are expert judgments that a hypothesis was too strong: "generalize
lemmas to CommSemiring", "weaken NormalizationMonoid", "more general algHom_ext". Each such
commit is an accepted event, reviewed by other humans and merged.

That is an independent **positive event log**, not automatically a ground truth or a recall
denominator. It contains accepted changes, not every opportunity maintainers considered; a
commit message can describe a structure-field change, a type-parameter generalization, or a
new API rather than a theorem-binder weakening; and the old revision is not elaborated here.
The output therefore supports two honest questions only:

* how often does a message-selected commit contain a structurally visible theorem-binder
  weakening, compared with a matched non-selected commit; and
* what do those visible expert events look like, including which ones the current detector's
  candidate language could express?

Calling the result detector recall requires a separate replay at the historical parent
revision. This script deliberately does not manufacture that stronger claim.

## Locate by text, judge by structure

CLAUDE.md forbids using names or prose as a *semantic* oracle, and this script does not.
The commit message is used for exactly one thing: **narrowing 33,269 commits to the ~1,600
worth diffing.** No move is admitted because a message said "generalize".

The semantic judgment is entirely structural, and has two halves:

1. **The diff must actually weaken a binder.** Both revisions of the file are parsed, each
   declaration's instance-binder brackets are read at depth 0, and a move is only proposed
   when a bracket over the *same arguments* changed its head class. A binder that was
   added, removed, or re-argumented is not a class weakening and is discarded by category.

2. **`to_class` must be a strict ancestor of `from_class` in the lattice the corpus
   records.** The lattice is read off parent projections exactly as `scripts/atlas_home.py`
   reads it — a declaration `X.toY` whose conclusion heads a class `Y` and whose owner `X`
   is a class is the edge `X -> Y` — and `selftest` asserts this module's streaming
   reconstruction is *identical* to `atlas_home.HomeIndex`'s on the algebra slice. Ancestry is
   that relation's transitive closure. A move whose target is not a strict ancestor is not
   a generalization however the commit described it, and is discarded by category.

The second half makes the retained events structurally meaningful rather than merely a list
of commits someone labelled. It also rejects a whole genre the message-based approach would
swallow:
declarations *moved into a stronger section* by a generalization commit (which reads as a
class change on that declaration and is a specialization), and rewrites where the type
parameter rather than the class changed.

## Two strata, because Mathlib generalizes through `variable`

The dominant idiom is not `theorem foo [CommRing R]` -> `theorem foo [CommSemiring R]`.
It is `variable [CommRing R]` -> `variable [CommSemiring R]` at the top of a section, which
changes every declaration inside it and touches none of their lines. A per-declaration
line diff sees nothing at all.

So the miner resolves section scope: `section`/`namespace`/`end` are tracked, `variable`
binders are attached to the scope that introduced them, and a declaration inherits the
binders in scope subject to an approximation of Lean's *variable inclusion* rule — an
inherited binder counts only when every variable-bound identifier in its arguments also
occurs in that declaration's own statement text.

The two strata are reported separately and never pooled, because they are not equally
trustworthy:

* **own** — the class name is written in the declaration's own brackets. Textually exact.
* **inherited** — the class came from an enclosing `variable`. Depends on the inclusion
  approximation above, which is not Lean's elaborator and can be wrong in both directions.

## The control that can fail

Commits whose messages make no generalization claim are run through the identical pipeline.
Each control is matched without replacement on number of Lean files changed and log2-binned
line churn, then chosen as close in time as possible. If they yield validated weakenings at
a comparable rate per commit, the message filter is selecting little or nothing. The rate
and the matching balance are reported, not asserted away.

## What this cannot see, stated up front

* `@[to_additive]` twins are never generated in source, so a generalization of
  `oneLePart_one` yields one move here and two in the library.
* A declaration deleted and restated elsewhere in the same commit is a rename to this
  script, and renames are discarded.
* Old revisions cannot be elaborated (the toolchain has moved 5 years), so nothing here is
  kernel-checked. It is a record of what humans did, not proof that they were right.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MATHLIB = os.path.join(HERE, "..", "lean", ".lake", "packages", "mathlib")
MATHLIB = os.path.abspath(MATHLIB)

CLOSURE = "/tmp/mathlib-closure.jsonl"
ALGEBRA = "/tmp/mathlib-algebra.jsonl"
LATTICE = "/tmp/kuna-lattice.json"
RAW = "/tmp/kuna-moves-raw.json"
OUT = os.path.abspath(os.path.join(HERE, "..", "research", "data",
                                   "kuna-e0-events.json"))

# The message vocabulary. Used to LOCATE candidate diffs and for nothing else; the
# `--set control` run applies the identical extractor to its complement.
CLAIM_PATTERNS = ["generali", "weaken", "more general", "relax"]
PRIMARY_KINDS = {"theorem", "lemma"}


# ---------------------------------------------------------------------------
# The lattice — same rule as `atlas_home.HomeIndex`, streamed so it fits the 4.8 GB closure.
#
# `atlas_home` holds every row in memory to find the instance-binder heads; on the whole
# closure that is ~15 GB of Python objects. Both facts it needs can be read without
# building a single term:
#
#   * a class is the head of an instance-binder domain, and an instance binder is `pt(`,
#     so `pt\((?:a\()*c\(N:` over the raw bytes finds every one of them — the encoding is
#     prefix, so stripping the `a(` spine from the domain lands on its head constant;
#   * a parent edge needs the *conclusion* head, which does need the telescope walk, but
#     only for rows whose name contains `.to` — 17,496 of 470,435.
#
# `selftest` is the differential: on the algebra slice this must reproduce
# `atlas_home.HomeIndex`'s class set and parent edges exactly, and it does (644 / 628).
# ---------------------------------------------------------------------------

PT_HEAD = re.compile(rb"pt\((?:a\()*c\((\d+):")
ROW_NAME = re.compile(rb'"name":"((?:[^"\\]|\\.)*)"')


def build_lattice(corpus: str, verbose=True):
    from atlas_home import telescope
    t0 = time.time()
    classes: set[str] = set()
    cand: list[bytes] = []
    with open(corpus, "rb") as f:
        for line in f:
            for m in PT_HEAD.finditer(line):
                n = int(m.group(1))
                s = m.end()
                classes.add(line[s:s + n].decode("utf-8", "replace"))
            nm = ROW_NAME.search(line)
            if nm and b".to" in nm.group(1):
                cand.append(line)
    parents: dict[str, set[str]] = collections.defaultdict(set)
    for line in cand:
        row = json.loads(line)
        stmt = row.get("stmt")
        if not stmt:
            continue
        try:
            _b, concl = telescope(stmt)
        except Exception:
            continue
        name = row["name"]
        owner = name.rsplit(".to", 1)[0]
        if owner in classes and concl in classes and concl != owner:
            parents[owner].add(concl)
    if verbose:
        print(f"lattice: {len(classes)} classes, "
              f"{sum(len(v) for v in parents.values())} edges, "
              f"{time.time() - t0:.1f}s", file=sys.stderr)
    return {"classes": sorted(classes),
            "parents": {k: sorted(v) for k, v in parents.items()}}


class Lattice:
    def __init__(self, d: dict) -> None:
        self.classes = set(d["classes"])
        self.parents = {k: set(v) for k, v in d["parents"].items()}
        self._anc: dict[str, set[str]] = {}

    def ancestors(self, cls: str) -> set[str]:
        hit = self._anc.get(cls)
        if hit is not None:
            return hit
        out: set[str] = set()
        stack = list(self.parents.get(cls, ()))
        while stack:
            p = stack.pop()
            if p in out or p == cls:
                continue
            out.add(p)
            stack.extend(self.parents.get(p, ()))
        self._anc[cls] = out
        return out


# ---------------------------------------------------------------------------
# A shallow reader for Lean 4 declaration signatures.
#
# Not a parser. The only things wanted per declaration are its depth-0 `[...]` groups and
# enough section structure to know which `variable` binders were in scope; everything else
# is skipped by bracket counting. Written against text because old revisions cannot be
# elaborated — the toolchain has moved five years and Mathlib's own build is not
# reproducible at an arbitrary 2021 commit.
# ---------------------------------------------------------------------------

OPENERS = {"(": ")", "[": "]", "{": "}", "⦃": "⦄", "⟨": "⟩", "⟦": "⟧"}
CLOSERS = {v: k for k, v in OPENERS.items()}

MODIFIERS = {"private", "protected", "noncomputable", "partial", "unsafe", "nonrec",
             "scoped", "local", "public", "meta", "irreducible"}
DECL_KW = {"theorem", "lemma", "def", "abbrev", "instance", "structure", "class",
           "inductive", "opaque", "axiom"}
CMD_KW = DECL_KW | {"variable", "variables", "section", "namespace", "end", "open",
                    "import", "universe", "attribute", "set_option", "example", "mutual",
                    "macro", "notation", "syntax", "elab", "macro_rules", "run_cmd",
                    "initialize", "deriving", "alias", "declare_config_elab"}

IDENT = re.compile(r"[^\s(){}\[\],:;⦃⦄⟨⟩]+")
HEAD = re.compile(r"[^\s(){}\[\],:;⦃⦄⟨⟩@]+")
TOKEN = re.compile(r"[A-Za-z_α-ωΑ-Ω𝕜ℕℤℚℝℂ][A-Za-z0-9_'!?α-ωₐ-ₜ₀-₉]*")


def strip_comments(src: str) -> str:
    """Blank comments in place, so every offset and line number still lines up."""
    out = list(src)
    i, n, depth = 0, len(src), 0
    while i < n:
        if depth == 0 and src.startswith("--", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif src.startswith("/-", i):
            depth += 1
            out[i] = out[i + 1] = " "
            i += 2
        elif depth > 0 and src.startswith("-/", i):
            depth -= 1
            out[i] = out[i + 1] = " "
            i += 2
        elif depth > 0:
            if src[i] != "\n":
                out[i] = " "
            i += 1
        elif depth == 0 and src[i] == '"':
            i += 1
            while i < n and src[i] != '"':
                i += 2 if src[i] == "\\" else 1
            i += 1
        else:
            i += 1
    return "".join(out)


def split_commands(src: str):
    """Mathlib puts every top-level command in column 0; that is the whole heuristic."""
    lines = src.split("\n")
    starts = []
    for idx, ln in enumerate(lines):
        if not ln or ln[0].isspace():
            continue
        head = ln.split(" ", 1)[0]
        if head.startswith("@[") or head.rstrip(":") in CMD_KW or head in MODIFIERS:
            starts.append(idx)
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        yield "\n".join(lines[s:e])


def skip_attrs(t: str, i: int) -> int:
    n = len(t)
    while i < n:
        while i < n and t[i].isspace():
            i += 1
        if t.startswith("@[", i):
            d, j = 0, i + 1
            while j < n:
                if t[j] == "[":
                    d += 1
                elif t[j] == "]":
                    d -= 1
                    if d == 0:
                        break
                j += 1
            i = j + 1
            continue
        m = IDENT.match(t, i)
        if m and m.group(0) in MODIFIERS:
            i = m.end()
            continue
        return i
    return i


def groups_at_depth_0(text: str):
    """Every depth-0 bracket group, as (opener, content). Bails on unbalanced text."""
    out, stack, i, n, start = [], [], 0, len(text), None
    while i < n:
        c = text[i]
        if c in OPENERS:
            if not stack:
                start = i
            stack.append(OPENERS[c])
            i += 1
            continue
        if stack and c == stack[-1]:
            stack.pop()
            if not stack and start is not None:
                out.append((text[start], text[start + 1:i]))
                start = None
            i += 1
            continue
        if c in CLOSERS:
            return out
        i += 1
    return out


def statement_region(t: str, i: int) -> tuple[str, str]:
    """(binder region, binders + type) — the two spans a declaration's signature spans.

    Binders end at the depth-0 `:`; the statement ends at the depth-0 `:=`, `where`, or
    `by`, which is where Lean stops caring for variable inclusion too.
    """
    stack, n, j, colon = [], len(t), i, None
    while j < n:
        c = t[j]
        if c in OPENERS:
            stack.append(OPENERS[c])
            j += 1
            continue
        if stack and c == stack[-1]:
            stack.pop()
            j += 1
            continue
        if not stack:
            if t.startswith(":=", j):
                break
            if c == ":" and colon is None:
                colon = j
            for kwd in ("where", "by", "|"):
                if t.startswith(kwd, j) and (j + len(kwd) >= n
                                             or not (t[j + len(kwd)].isalnum()
                                                     or t[j + len(kwd)] == "_")):
                    if colon is not None or kwd == "|":
                        return t[i:colon if colon is not None else j], t[i:j]
        j += 1
    end = colon if colon is not None else j
    return t[i:end], t[i:j]


def parse_bracket(content: str):
    """`[inst : Foo α β]` -> `('Foo', 'α β')`, or None when nothing identifier-like heads it."""
    c = content.strip()
    d, k = 0, 0
    while k < len(c):
        ch = c[k]
        if ch in OPENERS:
            d += 1
        elif ch in CLOSERS:
            d -= 1
        elif ch == ":" and d == 0 and not c.startswith("::", k):
            lhs = c[:k].strip()
            if lhs and " " not in lhs and TOKEN.fullmatch(lhs):
                c = c[k + 1:].strip()
            break
        k += 1
    m = HEAD.match(c)
    if not m or m.start() != 0:
        return None
    head = m.group(0).rstrip(",")
    if not TOKEN.fullmatch(head.replace(".", "x")):
        return None
    return head, re.sub(r"\s+", " ", c[m.end():].strip())


def bound_names(opener: str, content: str) -> list[str]:
    """The identifiers a `variable` binder group introduces."""
    c = content
    d, k = 0, 0
    while k < len(c):
        ch = c[k]
        if ch in OPENERS:
            d += 1
        elif ch in CLOSERS:
            d -= 1
        elif ch == ":" and d == 0 and not c.startswith("::", k):
            c = c[:k]
            break
        k += 1
    if opener == "[" and k >= len(content):
        return []          # anonymous instance binder: binds nothing usable
    return [t for t in TOKEN.findall(c)]


def parse_file(src: str) -> dict:
    """Every declaration in a file, with its own and its inherited instance binders."""
    src = strip_comments(src)
    ns: list[str] = []
    scopes: list[list] = []      # per scope: [(head, args, bound_vars_in_scope)]
    var_names: list[set] = []    # per scope: names bound by `variable` there
    kinds: list[str] = []
    decls: dict[str, dict] = {}
    dup: set[str] = set()
    order = 0
    for cmd in split_commands(src):
        i = skip_attrs(cmd, 0)
        m = IDENT.match(cmd, i)
        if not m:
            continue
        kw = m.group(0)
        rest = m.end()
        if kw == "namespace":
            nm = IDENT.match(cmd, rest + 1) if rest + 1 <= len(cmd) else None
            ns.append(nm.group(0) if nm else "_")
            scopes.append([])
            var_names.append(set())
            kinds.append("ns")
        elif kw == "section":
            ns.append("")
            scopes.append([])
            var_names.append(set())
            kinds.append("sec")
        elif kw == "end":
            if kinds:
                kinds.pop()
                ns.pop()
                scopes.pop()
                var_names.pop()
        elif kw in ("variable", "variables"):
            if not scopes:
                ns.append("")
                scopes.append([])
                var_names.append(set())
                kinds.append("sec")
            for opener, content in groups_at_depth_0(cmd[rest:]):
                if opener == "[":
                    p = parse_bracket(content)
                    if p:
                        scopes[-1].append(p)
                nm = parse_bracket(content) if opener == "[" else None
                for b in bound_names(opener, content):
                    var_names[-1].add(b)
        elif kw in DECL_KW:
            j = rest
            while j < len(cmd) and cmd[j].isspace():
                j += 1
            nm = IDENT.match(cmd, j)
            if not nm:
                continue
            name = nm.group(0)
            if name.startswith(":") or name in ("where", "extends") or "(" in name:
                continue
            name = name.split(".{")[0]
            binders, stmt = statement_region(cmd, nm.end())
            own = [p for p in (parse_bracket(c) for o, c in groups_at_depth_0(binders)
                               if o == "[") if p]
            allvars = set().union(*var_names) if var_names else set()
            mentioned = set(TOKEN.findall(stmt))
            inherited = []
            for head, args in [b for lvl in scopes for b in lvl]:
                # Lean includes a `variable` instance binder when the variables its type
                # mentions are themselves included, i.e. mentioned in the statement. This
                # approximates that: a binder over `α` follows a declaration that talks
                # about `α` and not one that does not. It is not the elaborator, and the
                # `inherited` stratum is reported separately for exactly that reason.
                need = {t for t in TOKEN.findall(args) if t in allvars}
                if need and not need <= mentioned:
                    continue
                inherited.append((head, args))
            prefix = ".".join(x for x in ns if x)
            full = f"{prefix}.{name}" if prefix else name
            if full in decls:
                dup.add(full)
                continue
            decls[full] = {"kw": kw, "own": own, "inherited": inherited, "order": order}
            order += 1
    for d in dup:
        decls.pop(d, None)
    return decls


# ---------------------------------------------------------------------------
# Mining
# ---------------------------------------------------------------------------

class Blobs:
    """One long-lived `git cat-file --batch`; ~30k blob reads otherwise cost 30k forks."""

    def __init__(self, repo: str) -> None:
        self.p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=repo,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def get(self, rev: str, path: str) -> str | None:
        self.p.stdin.write(f"{rev}:{path}\n".encode())
        self.p.stdin.flush()
        hdr = self.p.stdout.readline().decode(errors="replace").strip()
        if hdr.endswith("missing") or " " not in hdr:
            return None
        size = int(hdr.rsplit(" ", 1)[1])
        data = self.p.stdout.read(size)
        self.p.stdout.read(1)
        return data.decode("utf-8", "replace")


def git(repo: str, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({p.returncode}): "
            f"{p.stderr.decode('utf-8', 'replace').strip()}"
        )
    return p.stdout.decode("utf-8", "replace")


def history(repo: str) -> list[dict]:
    """Non-merge commits touching Lean, with cheap matching covariates.

    One `git log --numstat` replaces tens of thousands of subprocesses. Churn is only a
    nuisance covariate here: binary/rename rows report `-` and count as one changed file but
    contribute zero lines.
    """
    out = git(repo, "log", "--no-merges", "--format=@@Atlas@@%H%x01%ct%x01%s",
              "--numstat", "--", "*.lean")
    rows: list[dict] = []
    cur: dict | None = None
    for line in out.splitlines():
        if line.startswith("@@Atlas@@"):
            if cur is not None:
                rows.append(cur)
            sha, ts, subject = line[len("@@Atlas@@"):].split("\x01", 2)
            cur = {"sha": sha, "timestamp": int(ts), "subject": subject,
                   "lean_files": 0, "churn": 0}
        elif cur is not None and "\t" in line:
            parts = line.split("\t", 2)
            if len(parts) == 3:
                cur["lean_files"] += 1
                if parts[0].isdigit() and parts[1].isdigit():
                    cur["churn"] += int(parts[0]) + int(parts[1])
    if cur is not None:
        rows.append(cur)
    return rows


def claimed_hashes(repo: str) -> set[str]:
    args = ["log", "--no-merges", "--format=%H"]
    for p in CLAIM_PATTERNS:
        args += ["--grep", p]
    args += ["-i"]
    return set(git(repo, *args).splitlines())


def churn_bin(n: int) -> int:
    return int(math.log2(n + 1))


def matched_controls(all_rows: list[dict], claims: list[dict], limit: int | None,
                     _seed: int) -> tuple[list[dict], dict]:
    """Match without replacement on Lean-file count and line-churn scale.

    Exact-bin candidates are resolved by temporal proximity. The fallback minimizes file
    imbalance first, churn-bin imbalance second, then time; the commit hash breaks exact
    ties deterministically. The retained seed argument keeps old invocations compatible.
    """
    if limit is not None:
        claims = claims[:limit]
    claim_ids = {r["sha"] for r in all_rows if r.get("claimed")}
    pool = [r for r in all_rows if r["sha"] not in claim_ids]
    by_bin: dict[tuple[int, int], list[dict]] = collections.defaultdict(list)
    for row in pool:
        by_bin[(row["lean_files"], churn_bin(row["churn"]))].append(row)
    used: set[str] = set()
    pairs: list[dict] = []
    # Rare strata go first so a huge one-file commit cannot consume their only match.
    ordered = sorted(enumerate(claims), key=lambda x: (
        len(by_bin[(x[1]["lean_files"], churn_bin(x[1]["churn"]))]), x[0]))
    for original_i, claim in ordered:
        key = (claim["lean_files"], churn_bin(claim["churn"]))
        exact = [r for r in by_bin[key] if r["sha"] not in used]
        if exact:
            control = min(exact, key=lambda r: (
                abs(r["timestamp"] - claim["timestamp"]),
                r["sha"]))
            exact_bin = True
        else:
            remaining = (r for r in pool if r["sha"] not in used)
            control = min(remaining, key=lambda r: (
                abs(r["lean_files"] - claim["lean_files"]),
                abs(churn_bin(r["churn"]) - churn_bin(claim["churn"])),
                abs(r["timestamp"] - claim["timestamp"]),
                r["sha"]))
            exact_bin = False
        used.add(control["sha"])
        pairs.append({"order": original_i, "claim": claim, "control": control,
                      "exact_bin": exact_bin})
    pairs.sort(key=lambda p: p["order"])
    selected = [p["control"] for p in pairs]

    def mean(rows: list[dict], field: str) -> float:
        return sum(r[field] for r in rows) / len(rows) if rows else 0.0

    meta = {
        "method": "without replacement; exact (lean_files, floor(log2(churn+1))), then nearest time",
        "pairs": len(pairs),
        "exact_bin_pairs": sum(p["exact_bin"] for p in pairs),
        "claim_mean_lean_files": mean(claims, "lean_files"),
        "control_mean_lean_files": mean(selected, "lean_files"),
        "claim_mean_churn": mean(claims, "churn"),
        "control_mean_churn": mean(selected, "churn"),
        "mean_date_gap_days": (sum(abs(p["claim"]["timestamp"] - p["control"]["timestamp"])
                                   for p in pairs) / len(pairs) / 86400 if pairs else 0.0),
        "matched_pairs": [{"claim": p["claim"]["sha"],
                           "control": p["control"]["sha"],
                           "exact_bin": p["exact_bin"]} for p in pairs],
    }
    return selected, meta


def commit_set(repo: str, which: str, limit: int | None, seed: int,
               claim_limit: int | None = None) -> tuple[list[list[str]], dict]:
    """Message-selected commits or nuisance-matched non-selected controls."""
    rows = history(repo)
    selected = claimed_hashes(repo)
    for row in rows:
        row["claimed"] = row["sha"] in selected
    claims = [r for r in rows if r["claimed"]]
    if claim_limit is not None:
        claims = claims[:claim_limit]
    if which == "claim":
        if limit is not None:
            claims = claims[:limit]
        picked, meta = claims, {"method": "commit-message vocabulary", "pairs": len(claims)}
    else:
        picked, meta = matched_controls(rows, claims, limit, seed)
    return [[r["sha"], r["subject"]] for r in picked], meta


def changed_lean_files(repo: str, sha: str):
    out = git(repo, "diff-tree", "-r", "-M", "--no-commit-id", "--name-status",
              sha + "^", sha, "--", "*.lean")
    for line in out.splitlines():
        parts = line.split("\t")
        st = parts[0]
        if st.startswith("M") and len(parts) >= 2:
            yield parts[1], parts[1]
        elif st.startswith("R") and len(parts) >= 3:
            yield parts[1], parts[2]


def diff_decls(before: dict, after: dict):
    """Per declaration, the proposed moves and every non-move the diff contained."""
    moves, disc = [], collections.Counter()
    only_before = set(before) - set(after)
    only_after = set(after) - set(before)
    disc["decl-only-in-parent (deleted or renamed)"] += len(only_before)
    disc["decl-only-in-child (added or renamed)"] += len(only_after)
    for name in set(before) & set(after):
        b, a = before[name], after[name]
        for stratum in ("own", "inherited"):
            bb = collections.Counter(b[stratum])
            aa = collections.Counter(a[stratum])
            if bb == aa:
                continue
            removed = list((bb - aa).elements())
            added = list((aa - bb).elements())
            # Pair by argument text: a weakening keeps the carrier and changes the class.
            by_args = collections.defaultdict(list)
            for h, ar in added:
                by_args[ar].append(h)
            for h, ar in removed:
                if by_args.get(ar):
                    h2 = by_args[ar].pop(0)
                    moves.append({"decl": name, "from": h, "to": h2,
                                  "args": ar, "stratum": stratum, "kw": a["kw"]})
                else:
                    disc[f"binder-removed-outright ({stratum})"] += 1
            for ar, heads in by_args.items():
                disc[f"binder-added ({stratum})"] += len(heads)
    return moves, disc


def mine(repo: str, which: str, limit: int | None, seed: int, out: str,
         claim_limit: int | None = None):
    rows, selection = commit_set(repo, which, limit, seed, claim_limit)
    blobs = Blobs(repo)
    moves, disc = [], collections.Counter()
    stats = collections.Counter()
    commit_rows = []
    t0 = time.time()
    for k, (sha, subject) in enumerate(rows):
        if k % 100 == 0:
            print(f"  {k}/{len(rows)} commits, {len(moves)} raw moves, "
                  f"{time.time() - t0:.0f}s", file=sys.stderr)
        stats["commits"] += 1
        before = len(moves)
        file_pairs = 0
        for oldp, newp in changed_lean_files(repo, sha):
            sb = blobs.get(sha + "^", oldp)
            sa = blobs.get(sha, newp)
            if sb is None or sa is None:
                stats["file-blob-missing"] += 1
                continue
            stats["file-pairs"] += 1
            file_pairs += 1
            try:
                B = parse_file(sb)
                A = parse_file(sa)
            except Exception:
                stats["file-parse-error"] += 1
                continue
            m, d = diff_decls(B, A)
            disc.update(d)
            for x in m:
                x["commit"] = sha
                x["subject"] = subject
                x["parent_file"] = oldp
                x["file"] = newp
            moves += m
        added = len(moves) - before
        if added:
            stats["commits-with-raw-moves"] += 1
        commit_rows.append({"commit": sha, "subject": subject, "file_pairs": file_pairs,
                            "raw_moves": added})
    stats["raw-primary-claim-moves"] = sum(m["kw"] in PRIMARY_KINDS for m in moves)
    stats["raw-nonclaim-moves"] = len(moves) - stats["raw-primary-claim-moves"]
    with open(out, "w") as f:
        json.dump({"set": which, "commits": len(rows), "selection": selection,
                   "stats": dict(stats), "raw_discards": dict(disc),
                   "commit_rows": commit_rows, "moves": moves}, f)
    print(f"[{which}] {len(rows)} commits, {stats['file-pairs']} file pairs, "
          f"{len(moves)} raw moves ({stats['raw-primary-claim-moves']} theorem/lemma) "
          f"-> {out}", file=sys.stderr)
    return moves


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------

def validate(raw: dict, lat: Lattice):
    disc = collections.Counter()
    kept, rejected = [], []
    seen = set()
    for mv in raw["moves"]:
        f, t = mv["from"], mv["to"]
        # The carrier arguments are part of the event identity.  A theorem may weaken the
        # same class pair independently on (say) both its domain and codomain.
        key = (mv["commit"], mv["decl"], f, t, mv["args"], mv["stratum"])
        if f == t:
            disc["from == to"] += 1
            continue
        fin, tin = f in lat.classes, t in lat.classes
        if not fin and not tin:
            disc["neither endpoint is a class in the corpus"] += 1
            continue
        if not fin:
            disc["from_class absent from the corpus lattice"] += 1
            continue
        if not tin:
            disc["to_class absent from the corpus lattice"] += 1
            continue
        up = t in lat.ancestors(f)
        down = f in lat.ancestors(t)
        if up and down:
            disc["mutually reachable (not a strict weakening)"] += 1
            continue
        if down:
            disc["strengthening (to_class is a descendant)"] += 1
            rejected.append({**mv, "why": "strengthening"})
            continue
        if not up:
            disc["no ancestor relation between the two classes"] += 1
            rejected.append({**mv, "why": "unrelated"})
            continue
        if key in seen:
            disc["duplicate exact event"] += 1
            continue
        seen.add(key)
        kept.append(mv)
    return kept, disc, rejected


def restore_parent_files(raw: dict, repo: str) -> None:
    """Backfill the parent path in raw files produced before it entered the schema.

    `changed_lean_files` is rename-aware, but the first miner draft persisted only the child
    path.  Replaying the commit's path map makes those raw runs auditable without repeating
    the expensive source parse.
    """
    missing = {m["commit"] for m in raw.get("moves", []) if "parent_file" not in m}
    maps = {sha: {new: old for old, new in changed_lean_files(repo, sha)} for sha in missing}
    for move in raw.get("moves", []):
        if "parent_file" not in move:
            move["parent_file"] = maps.get(move["commit"], {}).get(move["file"], move["file"])


def paired_enrichment(pairs: list[dict], claim_hits: set[str], control_hits: set[str]) -> dict:
    """One-sided exact paired test: among discordant pairs, do claim hits dominate?"""
    claim_only = sum(p["claim"] in claim_hits and p["control"] not in control_hits
                     for p in pairs)
    control_only = sum(p["claim"] not in claim_hits and p["control"] in control_hits
                       for p in pairs)
    both = sum(p["claim"] in claim_hits and p["control"] in control_hits for p in pairs)
    neither = len(pairs) - claim_only - control_only - both
    n = claim_only + control_only
    p_value = (sum(math.comb(n, k) for k in range(claim_only, n + 1)) / (2 ** n)
               if n else 1.0)
    return {"pairs": len(pairs), "claim_only": claim_only,
            "control_only": control_only, "both": both, "neither": neither,
            "one_sided_exact_p": p_value,
            "passes_preregistered_sanity_check": claim_only > control_only and p_value < 0.01}


def deterministic_sample(items: list[dict], n: int, tag: str, key) -> list[dict]:
    """A sample whose membership cannot depend on iteration or hash-table order."""
    def record_hash(item: dict) -> bytes:
        payload = json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(payload).digest()

    def rank(item: dict) -> tuple[bytes, bytes]:
        payload = f"20260804|{tag}|{key(item)}".encode()
        # `key` was frozen without carrier arguments.  The full-record hash is only a
        # deterministic tie-break for declarations that weaken the same pair on two
        # carriers; it does not redraw the pre-registered declaration/pair sample.
        return hashlib.sha256(payload).digest(), record_hash(item)

    # The audit unit was frozen as a declaration/class-pair event before carrier arguments
    # were added to the event identity.  Keep one deterministically selected carrier per
    # audit key so that the identity repair cannot make one declaration occupy several of
    # the 30 pre-registered audit slots.
    representatives: dict[str, dict] = {}
    for item in items:
        k = repr(key(item))
        if k not in representatives or record_hash(item) < record_hash(representatives[k]):
            representatives[k] = item
    return sorted(representatives.values(), key=rank)[:n]


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------

def cmd_selftest(args):
    """Exercise the parser/differ and the independently streamed lattice."""
    before = """
namespace Demo
variable {α : Type} [Ring α]
theorem inherited (x : α) : x = x := rfl
theorem own {β : Type} [CommRing β] (x : β) : x = x := rfl
def nonclaim {β : Type} [CommRing β] (x : β) := x
end Demo
"""
    after = """
namespace Demo
variable {α : Type} [Semiring α]
theorem inherited (x : α) : x = x := rfl
theorem own {β : Type} [Semiring β] (x : β) : x = x := rfl
def nonclaim {β : Type} [Semiring β] (x : β) := x
end Demo
"""
    moves, disc = diff_decls(parse_file(before), parse_file(after))
    got = {(m["decl"], m["from"], m["to"], m["stratum"], m["kw"])
           for m in moves}
    want = {
        ("Demo.inherited", "Ring", "Semiring", "inherited", "theorem"),
        ("Demo.own", "CommRing", "Semiring", "own", "theorem"),
        ("Demo.nonclaim", "CommRing", "Semiring", "own", "def"),
    }
    assert got == want, f"source diff mismatch: got {got}, want {want}"
    assert not any(disc.values()), f"unexpected source-diff discards: {disc}"

    added = after.replace("theorem inherited (x : α)",
                          "theorem inherited [DecidableEq α] (x : α)")
    added_moves, added_disc = diff_decls(parse_file(after), parse_file(added))
    assert not added_moves, "adding a binder must not be paired as a class replacement"
    assert added_disc["binder-added (own)"] == 1

    fixture_rows = [
        {"sha": "claim", "timestamp": 100, "subject": "", "lean_files": 2,
         "churn": 31, "claimed": True},
        {"sha": "exact", "timestamp": 120, "subject": "", "lean_files": 2,
         "churn": 40, "claimed": False},
        {"sha": "near", "timestamp": 101, "subject": "", "lean_files": 1,
         "churn": 31, "claimed": False},
    ]
    controls, matching = matched_controls(fixture_rows, fixture_rows[:1], None, 0)
    assert controls[0]["sha"] == "exact"
    assert matching["exact_bin_pairs"] == 1
    print("source parser/differ: inherited + own + nonclaim strata, add-only control  OK")
    print("control matcher: exact nuisance bin beats a closer unmatched commit  OK")

    from atlas_home import HomeIndex
    rows = {}
    for line in open(ALGEBRA, "rb"):
        r = json.loads(line)
        rows[r["name"]] = r
    H = HomeIndex(rows)
    mine_ = build_lattice(ALGEBRA)
    cls_ok = set(mine_["classes"]) == H.classes
    ref = {(k, v) for k, vs in H.parents.items() for v in vs}
    got = {(k, v) for k, vs in mine_["parents"].items() for v in vs}
    print(f"classes: reference {len(H.classes)}, streamed {len(mine_['classes'])}, "
          f"identical={cls_ok}")
    print(f"edges:   reference {len(ref)}, streamed {len(got)}, identical={ref == got}")
    if not (cls_ok and ref == got):
        print("MISMATCH", sorted(ref ^ got)[:20])
        return 1
    # A lattice that answers "no" to everything would also pass the above if both were
    # empty, so pin three ancestries every algebraist knows.
    L = Lattice(mine_)
    for f, t in [("CommRing", "Semiring"), ("Group", "Monoid"), ("Field", "CommRing")]:
        assert t in L.ancestors(f), f"{t} should be an ancestor of {f}"
        assert f not in L.ancestors(t), f"{f} must not be an ancestor of {t}"
    print("ancestry spot checks: CommRing>Semiring, Group>Monoid, Field>CommRing  OK")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["lattice", "mine", "control", "validate",
                                      "selftest", "all"])
    ap.add_argument("--corpus", default=CLOSURE)
    ap.add_argument("--repo", default=MATHLIB)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--control-limit", type=int, default=None,
                    help="cap matched controls; default is one per selected claim commit")
    ap.add_argument("--seed", type=int, default=20260803)
    args = ap.parse_args()

    if args.stage == "selftest":
        return cmd_selftest(args)
    if args.stage in ("lattice", "all"):
        json.dump(build_lattice(args.corpus), open(LATTICE, "w"))
    if args.stage in ("mine", "all"):
        mine(args.repo, "claim", args.limit, args.seed, RAW)
    if args.stage in ("control", "all"):
        mine(args.repo, "control", args.control_limit, args.seed,
             RAW.replace(".json", "-control.json"), claim_limit=args.limit)
    if args.stage in ("validate", "all"):
        lat = Lattice(json.load(open(LATTICE)))
        report = {}
        raw_by_tag = {}
        for tag, path in (("claim", RAW),
                          ("control", RAW.replace(".json", "-control.json"))):
            if not os.path.exists(path):
                continue
            raw = json.load(open(path))
            restore_parent_files(raw, args.repo)
            raw_by_tag[tag] = raw
            kept_all, disc, rej = validate(raw, lat)
            kept = [m for m in kept_all if m["kw"] in PRIMARY_KINDS]
            other = [m for m in kept_all if m["kw"] not in PRIMARY_KINDS]
            hit_commits = {m["commit"] for m in kept}
            combined_discards = collections.Counter(raw["raw_discards"])
            combined_discards.update(disc)
            report[tag] = {"commits": raw["commits"], "stats": raw["stats"],
                           "selection": raw.get("selection", {}),
                           "raw_moves": len(raw["moves"]),
                           "validated_all_kinds": len(kept_all),
                           "validated": len(kept),
                           "validated_nonclaim_kinds": len(other),
                           "commits_with_validated_moves": len(hit_commits),
                           "event_rate_per_commit": (len(hit_commits) / raw["commits"]
                                                     if raw["commits"] else 0.0),
                           "strata": dict(collections.Counter(m["stratum"] for m in kept)),
                           "discarded": dict(combined_discards),
                           "moves": kept, "other_kinds": other,
                           "rejected_sample": rej[:200]}
        pairs = report.get("control", {}).get("selection", {}).get("matched_pairs", [])
        paired = paired_enrichment(
            pairs,
            {m["commit"] for m in report.get("claim", {}).get("moves", [])},
            {m["commit"] for m in report.get("control", {}).get("moves", [])},
        ) if pairs else None
        public_moves = [{"decl": m["decl"], "from": m["from"], "to": m["to"],
                         "args": m["args"],
                         "commit": m["commit"], "stratum": m["stratum"],
                         "kind": m["kw"], "parent_file": m["parent_file"],
                         "file": m["file"],
                         "subject": m["subject"]}
                        for m in report.get("claim", {}).get("moves", [])]
        claim_hit_commits = {m["commit"] for m in public_moves}
        no_event = [r for r in raw_by_tag.get("claim", {}).get("commit_rows", [])
                    if r["commit"] not in claim_hit_commits]
        # This key was frozen before the full run and before the carrier-identity defect
        # above was found.  Keep it unchanged so fixing event deduplication cannot redraw a
        # manual-audit sample after its diffs have already been inspected.
        event_key = lambda m: (m["commit"], m["decl"], m["from"], m["to"])
        audit_samples = {
            "own": deterministic_sample([m for m in public_moves if m["stratum"] == "own"],
                                        30, "own", event_key),
            "inherited": deterministic_sample(
                [m for m in public_moves if m["stratum"] == "inherited"],
                30, "inherited", event_key),
            "selected_commits_without_event": deterministic_sample(
                no_event, 30, "no-event", lambda r: r["commit"]),
        }
        out = {"schema": "atlas-kuna-e0-v1",
               "provenance": {
                   "mathlib_head": git(args.repo, "rev-parse", "HEAD").strip(),
                   "corpus": os.path.abspath(args.corpus),
                   "corpus_bytes": os.path.getsize(args.corpus),
                   "corpus_sha256": sha256_file(args.corpus),
                   "lattice_sha256": sha256_file(LATTICE),
                   "miner_sha256": sha256_file(__file__),
                   "claim_patterns": CLAIM_PATTERNS,
                   "primary_kinds": sorted(PRIMARY_KINDS),
                   "lattice_classes": len(lat.classes),
                   "lattice_edges": sum(len(v) for v in lat.parents.values()),
                   "method": "research/kuna-math-loop.md#7-pre-registration-for-e0",
               },
               "moves": public_moves,
               "discarded": report.get("claim", {}).get("discarded", {}),
               "claim_summary": {k: v for k, v in report.get("claim", {}).items()
                                 if k not in ("moves", "other_kinds", "rejected_sample",
                                              "discarded")},
               "control": {k: v for k, v in report.get("control", {}).items()
                           if k not in ("moves", "other_kinds", "rejected_sample")},
               "paired_enrichment": paired,
               "audit_samples": audit_samples,
               "control_moves": [{"decl": m["decl"], "from": m["from"], "to": m["to"],
                                  "args": m["args"],
                                  "commit": m["commit"], "stratum": m["stratum"],
                                  "parent_file": m["parent_file"], "file": m["file"]}
                                 for m in report.get("control", {}).get("moves", [])]}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(out, open(OUT, "w"), indent=1)
        for tag in report:
            r = report[tag]
            print(f"\n== {tag}: {r['commits']} commits, {r['stats'].get('file-pairs', 0)}"
                  f" file pairs, {r['raw_moves']} raw -> {r['validated']} validated "
                  f"theorem/lemma events in {r['commits_with_validated_moves']} commits "
                  f"({r['event_rate_per_commit']:.2%})")
            print(f"   strata: {r['strata']}; other declaration kinds: "
                  f"{r['validated_nonclaim_kinds']}")
            for k, v in sorted(r["discarded"].items(), key=lambda x: -x[1]):
                print(f"   {v:7d}  {k}")
        if paired is not None:
            print(f"\npaired enrichment: {paired}")
        print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
