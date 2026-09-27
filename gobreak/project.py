"""Project-level helpers: res:// paths, covering-test selection, copies."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

DEFAULT_TEST_DIRS = ("test", "tests")
DEFAULT_TEST_PATTERNS = ("test_*.gd", "*_test.gd", "*Test.gd")
ALWAYS_EXCLUDED = (".git",)

_CLASS_NAME = re.compile(r"^\s*class_name\s+(\w+)", re.M)


def find_project_root(start: Path) -> Path | None:
    """Walk up from `start` to the directory holding `project.godot`."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "project.godot").is_file():
            return candidate
    return None


def to_res(project: Path, path: Path) -> str:
    rel = path.resolve().relative_to(project.resolve())
    return "res://" + rel.as_posix()


def from_res(project: Path, res_path: str) -> Path:
    if res_path.startswith("res://"):
        return project / res_path[len("res://"):]
    return project / res_path


def find_covering_tests(
    project: Path,
    target: Path,
    test_dirs: list[str] | None = None,
    patterns: list[str] | None = None,
) -> list[str]:
    """Return res:// paths of test files that name the target.

    A test file covers the target when its text contains the target's
    `class_name` as a whole word, or the target's res:// path (a
    `preload`/`load` call). Tests that reach the target only through
    other classes are not found; pass them with `--tests`.
    """
    source = target.read_text(encoding="utf-8", errors="replace")
    m = _CLASS_NAME.search(source)
    needles: list[re.Pattern[str]] = [re.compile(re.escape(to_res(project, target)))]
    if m:
        needles.append(re.compile(r"\b" + re.escape(m.group(1)) + r"\b"))

    dirs = test_dirs or [d for d in DEFAULT_TEST_DIRS if (project / d).is_dir()]
    pats = patterns or list(DEFAULT_TEST_PATTERNS)
    target_resolved = target.resolve()
    found: list[str] = []
    for d in dirs:
        root = from_res(project, d)
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [n for n in dirnames if not n.startswith(".")]
            for name in filenames:
                if not any(fnmatch.fnmatch(name, p) for p in pats):
                    continue
                path = Path(dirpath) / name
                if path.resolve() == target_resolved:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(n.search(text) for n in needles):
                    found.append(to_res(project, path))
    return sorted(set(found))


def _make_writable(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    if path.exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_make_writable)
        else:
            shutil.rmtree(path, onerror=_make_writable)


def sync_project(project: Path, dest: Path, excludes: list[str]) -> int:
    """Make `dest` a copy of `project`, copying only files that differ.

    A file is copied when its size or modification time differs from the
    source. Files and directories missing from the source are removed.
    Returns the number of files copied.
    """
    skip = set(ALWAYS_EXCLUDED) | set(excludes)
    copied = 0
    dest.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in skip]
        src_dir = Path(dirpath)
        dst_dir = dest / src_dir.relative_to(project)
        dst_dir.mkdir(exist_ok=True)
        wanted = set(dirnames) | {f for f in filenames if f not in skip}
        for name in filenames:
            if name in skip:
                continue
            s = src_dir / name
            d = dst_dir / name
            st = s.stat()
            try:
                dt = d.stat()
                same = dt.st_size == st.st_size and dt.st_mtime_ns == st.st_mtime_ns
            except FileNotFoundError:
                same = False
            if not same:
                if d.exists():
                    os.chmod(d, stat.S_IWRITE)
                shutil.copy2(s, d)
                copied += 1
        for entry in dst_dir.iterdir():
            if entry.name not in wanted:
                if entry.is_dir() and not entry.is_symlink():
                    remove_tree(entry)
                else:
                    os.chmod(entry, stat.S_IWRITE)
                    entry.unlink()
    return copied


def copy_project(project: Path, excludes: list[str], parent: Path | None = None) -> Path:
    """Copy the project into a fresh temp directory and return the copy.

    The `.godot/` import cache is copied too, so the copy runs without a
    re-import. `.git/` and every name in `excludes` are skipped.
    """
    skip = set(ALWAYS_EXCLUDED) | set(excludes)
    base = Path(tempfile.mkdtemp(prefix="gobreak-", dir=parent))
    dest = base / project.name

    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in skip}

    shutil.copytree(project, dest, ignore=ignore)
    return dest
