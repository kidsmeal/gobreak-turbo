"""Survivor triage: sort each survivor into dead, unreached, reached or ruled.

- dead: the line never ran during the tests and its function has no
  reference in non-test code.
- unreached: the line never ran, but non-test code references its function.
- reached: the line ran and the tests still passed; needs a ruling.
- ruled: a ruling in `.gobreak/rulings.json` matches this exact mutant.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import mutants as mut

DEAD = "dead"
UNREACHED = "unreached"
REACHED = "reached"
RULED_EQUIVALENT = "ruled-equivalent"
RULED_GAP = "ruled-gap"

EQUIVALENT = "equivalent"
GAP = "gap"

RULINGS_PATH = Path(".gobreak") / "rulings.json"

HIT_PATTERN = re.compile(r"__GB_HIT_(\d+)__")

# Engine callbacks: Godot calls these by name, so no reference exists.
ENGINE_CALLBACKS = frozenset(
    {
        "_init", "_static_init", "_ready", "_process", "_physics_process",
        "_enter_tree", "_exit_tree", "_notification", "_input", "_unhandled_input",
        "_unhandled_key_input", "_shortcut_input", "_gui_input", "_draw",
        "_integrate_forces", "_get", "_set", "_get_property_list",
        "_property_can_revert", "_property_get_revert", "_validate_property",
        "_to_string", "_get_configuration_warnings", "_can_drop_data", "_drop_data",
        "_get_drag_data", "_make_custom_tooltip", "_has_point", "_run",
        "_initialize", "_finalize", "_iter_init", "_iter_next", "_iter_get",
    }
)

_FUNC = re.compile(r"^\s*(?:static\s+)?func\s+(\w+)")
_FIRST_WORD = re.compile(r"^\s*(\w+)")
_ELSE_LINE = re.compile(r"^\s*(elif|else)\b")


@dataclass(frozen=True)
class LineInfo:
    func: str | None  # innermost enclosing named function
    markable: bool  # a marker statement can be inserted before this line
    func_line: int | None = None  # 1-based line of that function's `func` keyword


def analyze(source: str) -> list[LineInfo]:
    """Per-line block context: enclosing function and whether a marker fits."""
    masked_text, multiline, _ = mut.mask(source)
    masked_lines = masked_text.split("\n")
    infos: list[LineInfo] = []
    # (indent, kind, func name, func line)
    stack: list[tuple[int, str, str | None, int | None]] = []
    depth = 0
    continuation = False

    def enclosing() -> tuple[str | None, int | None]:
        return next(((name, line) for _, kind, name, line in reversed(stack) if kind == "func"), (None, None))

    for li, masked_full in enumerate(masked_lines):
        masked = masked_full.rstrip("\r")
        starts_inside = depth > 0 or continuation
        depth = max(0, depth + mut._depth_delta(masked))
        continuation = masked.rstrip().endswith("\\")

        stripped = masked.strip()
        if not stripped or starts_inside:
            func, func_line = enclosing()
            infos.append(LineInfo(func, False, func_line))
            continue

        indent = len(masked) - len(masked.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent_kind = stack[-1][1] if stack else None
        func, func_line = enclosing()
        in_func = func is not None

        m = _FUNC.match(masked)
        if m:
            infos.append(LineInfo(m.group(1), False, li + 1))
            stack.append((indent, "func", m.group(1), li + 1))
            continue

        is_pattern = parent_kind == "match" and stripped.endswith(":")
        markable = (
            in_func
            and not _ELSE_LINE.match(masked)
            and not is_pattern
            and li not in multiline
        )
        infos.append(LineInfo(func, markable, func_line))

        if stripped.endswith(":"):
            word = _FIRST_WORD.match(masked)
            kind = "pattern" if is_pattern else (word.group(1) if word else "block")
            stack.append((indent, kind, None, None))
    return infos


def function_entries(source: str) -> dict[int, int]:
    """Map each function's `func` line to its first markable body line (1-based).

    A marker on that line records whether the function ran at all.
    """
    entries: dict[int, int] = {}
    for li, info in enumerate(analyze(source)):
        if info.markable and info.func_line is not None and info.func_line not in entries:
            entries[info.func_line] = li + 1
    return entries


def instrument(source: str, lines: set[int]) -> tuple[str, set[int]]:
    """Insert a once-per-process hit marker before each markable line.

    Returns the instrumented source and the set of lines that got a marker.
    Line numbers are 1-based and refer to the original source.
    """
    infos = analyze(source)
    raw_lines = source.split("\n")
    out: list[str] = []
    marked: set[int] = set()
    for li, raw in enumerate(raw_lines):
        n = li + 1
        if n in lines and infos[li].markable:
            body = raw.rstrip("\r")
            indent = body[: len(body) - len(body.lstrip())]
            eol = "\r" if raw.endswith("\r") else ""
            out.append(
                f'{indent}if not Engine.has_meta(&"__gb_hit_{n}"): '
                f'Engine.set_meta(&"__gb_hit_{n}", true); print("__GB_HIT_{n}__"){eol}'
            )
            marked.add(n)
        out.append(raw)
    return "\n".join(out), marked


def hits_from_output(output: str) -> set[int]:
    return {int(m) for m in HIT_PATTERN.findall(output)}


def _strip_gd_comments(text: str) -> str:
    _, _, comments = mut.mask(text)
    lines = text.split("\n")
    for li, col in comments.items():
        lines[li] = lines[li][:col]
    return "\n".join(lines)


def count_references(
    project: Path,
    target: Path,
    func: str,
    source: str,
    test_patterns: list[str],
) -> int:
    """Count mentions of `func` outside its own definition, tests excluded.

    Scans `.gd`, `.tscn` and `.tres` files. Comments in `.gd` files are
    ignored; string mentions (`call("name")`, `connect("x", ...)`) count.
    """
    word = re.compile(r"\b" + re.escape(func) + r"\b")
    target_resolved = target.resolve()
    total = 0

    own = _strip_gd_comments(source).split("\n")
    infos = analyze(source)
    for li, line in enumerate(own):
        if infos[li].func == func:
            continue
        m = _FUNC.match(line)
        if m and m.group(1) == func:
            continue
        total += len(word.findall(line))

    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.endswith((".gd", ".tscn", ".tres")):
                continue
            if any(fnmatch.fnmatch(name, p) for p in test_patterns):
                continue
            path = Path(dirpath) / name
            if path.resolve() == target_resolved:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if name.endswith(".gd"):
                text = _strip_gd_comments(text)
            total += len(word.findall(text))
    return total


@dataclass(frozen=True)
class Ruling:
    file: str
    before: str
    after: str
    ruling: str
    reason: str

    def key(self) -> tuple[str, str, str]:
        return (self.file, self.before, self.after)


def load_rulings(project: Path) -> list[Ruling]:
    path = project / RULINGS_PATH
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Ruling(**r) for r in data.get("rulings", [])]


def save_rulings(project: Path, rulings: list[Ruling]) -> Path:
    path = project / RULINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rulings, key=lambda r: r.key())
    data = {
        "version": 1,
        "rulings": [
            {"file": r.file, "before": r.before, "after": r.after, "ruling": r.ruling, "reason": r.reason}
            for r in ordered
        ],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def ruling_for(rulings: list[Ruling], file: str, m: mut.Mutant) -> Ruling | None:
    key = (file, m.before, m.after)
    return next((r for r in rulings if r.key() == key), None)


def is_engine_callback(func: str | None) -> bool:
    return func in ENGINE_CALLBACKS
