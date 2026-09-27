"""Mutant generation for GDScript source.

Every mutant is a single-line edit. Strings and comments are masked before
any operator is matched, so text inside them is never mutated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Operator group names. These are the names accepted by the
# `# mutation: ignore=<group>,<group>` line tag.
CMP = "cmp"
ARITH = "arith"
LOGIC = "logic"
NOT = "not"
BOOL = "bool"
NUM = "num"
IF = "if"
DEL = "del"
ALL_GROUPS = (CMP, ARITH, LOGIC, NOT, BOOL, NUM, IF, DEL)

_IGNORE_TAG = re.compile(r"#\s*mutation:\s*ignore(?:=([\w,\s]+))?")

# Lines whose first word matches are declarations, not statements. No
# mutant is generated on them, or on the continuation lines of a
# declaration that spans several lines.
_DECL_START = re.compile(r"^\s*(?:static\s+)?(func|class_name|class|extends|signal|enum)\b|^\s*@")

# Statement deletion never removes these: removing them breaks the block
# structure, the return path, or a declaration later lines depend on.
_NO_DELETE_START = re.compile(
    r"^\s*(?:return|var|const|static|func|class|class_name|extends|signal|enum|pass|"
    r"break|continue|if|elif|else|for|while|match|breakpoint)\b|^\s*@"
)

_OP_TOKEN = re.compile(
    r"\*\*=|<<=|>>=|\*\*|<<|>>|->|==|!=|<=|>=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|&&|\|\||:=|[<>+\-*/%!=&|^~]"
)

_CMP_SWAP = {"==": "!=", "!=": "==", "<": "<=", "<=": "<", ">": ">=", ">=": ">"}
_ARITH_SWAP = {"+": "-", "-": "+", "*": "/", "/": "*", "+=": "-=", "-=": "+=", "*=": "/=", "/=": "*="}
_LOGIC_SWAP = {"&&": "||", "||": "&&"}

_WORD = re.compile(r"\b(and|or|not|true|false)\b")
_NUMBER = re.compile(r"(?<![\w.])(\d[\d_]*\.\d*(?:e[+-]?\d+)?|\.\d+(?:e[+-]?\d+)?|\d[\d_]*(?:e[+-]?\d+)?)(?![\w.])")
_IF_LINE = re.compile(r"^(\s*)(if|elif)(\s+)(.*?)(\s*):\s*$")


@dataclass(frozen=True)
class Mutant:
    index: int
    line: int  # 1-based
    col: int  # 1-based
    group: str
    before: str  # the line, stripped
    after: str  # the mutated line, stripped
    new_line: str  # the full mutated line, without its line ending

    def describe(self) -> str:
        return f"L{self.line}:{self.col} {self.group:<5} {self.before}  ->  {self.after}"


def mask(text: str) -> tuple[str, set[int], dict[int, int]]:
    """Blank out string contents and comments, keeping every offset.

    Returns the masked text, the 0-based line numbers a multi-line string
    touches, and the column where each commented line's `#` starts.
    Quote delimiters are kept so binary-operator detection sees them.
    """
    out = list(text)
    n = len(text)
    multiline: set[int] = set()
    comments: dict[int, int] = {}
    line = 0
    line_start = 0
    i = 0
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            line_start = i + 1
            i += 1
            continue
        if c == "#":
            comments[line] = i - line_start
            j = i
            while j < n and text[j] != "\n":
                if text[j] != "\r":
                    out[j] = " "
                j += 1
            i = j
            continue
        if c in "\"'":
            quote = c * 3 if text.startswith(c * 3, i) else c
            j = i + len(quote)
            start_line = line
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text.startswith(quote, j):
                    break
                if len(quote) == 1 and text[j] == "\n":
                    break
                j += 1
            end = min(j, n)
            for k in range(i + len(quote), end):
                if text[k] == "\n":
                    line += 1
                    line_start = k + 1
                elif text[k] != "\r":
                    out[k] = " "
            if line != start_line:
                multiline.update(range(start_line, line + 1))
            i = end + len(quote) if end < n and text.startswith(quote, end) else end
            continue
        i += 1
    return "".join(out), multiline, comments


def _ignored_groups(raw_line: str, comment_col: int | None) -> set[str]:
    if comment_col is None:
        return set()
    m = _IGNORE_TAG.search(raw_line[comment_col:])
    if not m:
        return set()
    if m.group(1) is None:
        return set(ALL_GROUPS)
    return {g.strip() for g in m.group(1).split(",") if g.strip()}


def _is_binary(masked: str, pos: int) -> bool:
    k = pos - 1
    while k >= 0 and masked[k] in " \t":
        k -= 1
    return k >= 0 and (masked[k].isalnum() or masked[k] in "_)]}\"'")


def _bump(literal: str) -> str | None:
    clean = literal.replace("_", "")
    if "e" in clean.lower():
        return None
    if "." in clean:
        value = float(clean) + 1.0
        text = repr(value)
        return text if "." in text or "e" in text else text + ".0"
    return str(int(clean) + 1)


def _depth_delta(masked: str) -> int:
    return sum(masked.count(ch) for ch in "([{") - sum(masked.count(ch) for ch in ")]}")


def generate(source: str) -> list[Mutant]:
    """Return every mutant for `source`, in line then column order."""
    masked_text, multiline, comments = mask(source)
    raw_lines = source.split("\n")
    masked_lines = masked_text.split("\n")
    mutants: list[Mutant] = []

    depth = 0
    continuation = False
    in_decl = False

    for li, (raw_full, masked_full) in enumerate(zip(raw_lines, masked_lines)):
        raw = raw_full[:-1] if raw_full.endswith("\r") else raw_full
        masked = masked_full[: len(raw)]
        start_depth = depth
        starts_inside = start_depth > 0 or continuation
        depth = max(0, depth + _depth_delta(masked))
        continuation = masked.rstrip().endswith("\\")
        ends_inside = depth > 0 or continuation

        if not masked.strip():
            continue
        if _DECL_START.match(masked) and not starts_inside:
            in_decl = ends_inside
            continue
        if in_decl:
            in_decl = ends_inside
            continue

        ignored = _ignored_groups(raw, comments.get(li))
        edits: list[tuple[int, str, str, str]] = []  # (col, group, old, new)

        for m in _OP_TOKEN.finditer(masked):
            tok = m.group(0)
            pos = m.start()
            if tok in _CMP_SWAP:
                edits.append((pos, CMP, tok, _CMP_SWAP[tok]))
            elif tok in _ARITH_SWAP:
                if tok in ("+", "-", "*", "/") and not _is_binary(masked, pos):
                    continue
                edits.append((pos, ARITH, tok, _ARITH_SWAP[tok]))
            elif tok in _LOGIC_SWAP:
                edits.append((pos, LOGIC, tok, _LOGIC_SWAP[tok]))
            elif tok == "!":
                edits.append((pos, NOT, "!", ""))

        for m in _WORD.finditer(masked):
            word = m.group(1)
            pos = m.start()
            if word == "and":
                edits.append((pos, LOGIC, "and", "or"))
            elif word == "or":
                edits.append((pos, LOGIC, "or", "and"))
            elif word == "not":
                end = m.end()
                while end < len(masked) and masked[end] in " \t":
                    end += 1
                edits.append((pos, NOT, raw[pos:end], ""))
            elif word == "true":
                edits.append((pos, BOOL, "true", "false"))
            elif word == "false":
                edits.append((pos, BOOL, "false", "true"))

        for m in _NUMBER.finditer(masked):
            pos = m.start()
            if pos > 0 and masked[pos - 1] in "xXbB" and pos > 1 and masked[pos - 2] == "0":
                continue
            bumped = _bump(m.group(1))
            if bumped is not None:
                edits.append((pos, NUM, m.group(1), bumped))

        for col, group, old, new in sorted(edits):
            if group in ignored:
                continue
            new_line = raw[:col] + new + raw[col + len(old):]
            if new_line == raw:
                continue
            mutants.append(Mutant(0, li + 1, col + 1, group, raw.strip(), new_line.strip(), new_line))

        single_line = not starts_inside and not ends_inside and li not in multiline

        if IF not in ignored and single_line:
            m = _IF_LINE.match(masked)
            if m:
                cond_start = m.start(4)
                cond_end = m.end(4)
                cond = raw[cond_start:cond_end]
                new_line = raw[:cond_start] + f"not ({cond})" + raw[cond_end:]
                mutants.append(Mutant(0, li + 1, cond_start + 1, IF, raw.strip(), new_line.strip(), new_line))

        if DEL not in ignored and single_line:
            stripped = masked.strip()
            if not stripped.endswith(":") and not _NO_DELETE_START.match(masked):
                indent = raw[: len(raw) - len(raw.lstrip())]
                new_line = indent + "pass"
                mutants.append(Mutant(0, li + 1, len(indent) + 1, DEL, raw.strip(), "pass", new_line))

    return [
        Mutant(i + 1, m.line, m.col, m.group, m.before, m.after, m.new_line)
        for i, m in enumerate(sorted(mutants, key=lambda m: (m.line, m.col, m.group)))
    ]


def apply(source: str, mutant: Mutant) -> str:
    """Return `source` with `mutant`'s line replaced, line endings kept."""
    lines = source.split("\n")
    old = lines[mutant.line - 1]
    lines[mutant.line - 1] = mutant.new_line + ("\r" if old.endswith("\r") else "")
    return "\n".join(lines)
