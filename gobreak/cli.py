"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from . import engine
from . import mutants as mut
from . import project as proj
from . import runner

EXIT_CLEAN = 0
EXIT_SURVIVORS = 1
EXIT_ERROR = 2

SELFCHECK_DIR = Path(__file__).parent / "selfcheck"
SELFCHECK_COMMAND = "{godot} --headless --path . -s res://run_tests.gd -- --tests {tests}"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _lines(value: str) -> tuple[int, int]:
    first, _, last = value.partition("-")
    a = int(first)
    b = int(last) if last else a
    if a < 1 or b < a:
        raise argparse.ArgumentTypeError("expected A-B with 1 <= A <= B")
    return a, b


def _resolve_godot(explicit: str | None) -> str:
    candidate = explicit or os.environ.get("GODOT") or "godot"
    found = shutil.which(candidate)
    if found is None and not Path(candidate).is_file():
        raise engine.SessionError(f"godot executable not found: {candidate} (pass --godot or set GODOT)")
    return found or candidate


def _resolve_target(target: str, project_arg: str | None) -> tuple[Path, Path]:
    if target.startswith("res://"):
        root = Path(project_arg) if project_arg else proj.find_project_root(Path.cwd())
        if root is None:
            raise engine.SessionError("no project.godot found; pass --project")
        path = proj.from_res(root, target)
    else:
        path = Path(target)
        root = Path(project_arg) if project_arg else proj.find_project_root(path)
        if root is None:
            raise engine.SessionError(f"no project.godot above {target}; pass --project")
    if not path.is_file():
        raise engine.SessionError(f"target not found: {path}")
    if not (root / "project.godot").is_file():
        raise engine.SessionError(f"not a Godot project (no project.godot): {root}")
    return root.resolve(), path.resolve()


def _print_result(res: engine.MutantResult, done: int, total: int) -> None:
    print(f"[{done}/{total}] {res.status:<8} {res.mutant.describe()}  ({res.seconds:.1f}s)", flush=True)


def _print_report(session: engine.Session) -> None:
    print()
    print(f"target:   {session.target}")
    print(f"tests:    {len(session.tests)} file(s)")
    print(f"baseline: {session.baseline_seconds:.1f}s, timeout {session.timeout:.1f}s")
    counts = ", ".join(
        f"{name} {session.count(name)}"
        for name in (runner.KILLED, runner.SURVIVED, runner.TIMEOUT, runner.INVALID)
    )
    print(f"mutants:  {len(session.results)} ({counts})")
    score = session.score
    print("score:    n/a" if score is None else f"score:    {score:.0%} killed")
    survivors = [r for r in session.results if r.status == runner.SURVIVED]
    if survivors:
        print("\nsurvivors (no test failed with this change):")
        for r in survivors:
            print(f"  {session.target}:{r.mutant.describe()}")


def _write_json(session: engine.Session, path: str) -> None:
    data = {
        "version": __version__,
        "target": session.target,
        "tests": session.tests,
        "command": session.command,
        "baseline_seconds": round(session.baseline_seconds, 3),
        "timeout_seconds": round(session.timeout, 3),
        "summary": {
            name: session.count(name)
            for name in (runner.KILLED, runner.SURVIVED, runner.TIMEOUT, runner.INVALID)
        },
        "score": session.score,
        "mutants": [
            {
                "id": r.mutant.index,
                "line": r.mutant.line,
                "col": r.mutant.col,
                "group": r.mutant.group,
                "before": r.mutant.before,
                "after": r.mutant.after,
                "status": r.status,
                "seconds": round(r.seconds, 3),
            }
            for r in session.results
        ],
    }
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cmd_run(args: argparse.Namespace) -> int:
    root, target = _resolve_target(args.target, args.project)
    source = target.read_bytes().decode("utf-8")
    found = mut.generate(source)
    if args.lines:
        found = [m for m in found if args.lines[0] <= m.line <= args.lines[1]]

    if args.dry_run:
        for m in found:
            print(f"#{m.index:<4} {m.describe()}")
        print(f"\n{len(found)} mutant(s)")
        return EXIT_CLEAN

    if not found:
        print("no mutants generated")
        return EXIT_CLEAN

    if args.tests:
        tests = args.tests
    elif runner.uses_tests(args.command):
        tests = proj.find_covering_tests(root, target, args.test_dirs, args.test_patterns)
        if args.skip_tests:
            tests = [t for t in tests if not any(s in t for s in args.skip_tests)]
        if not tests:
            raise engine.SessionError(
                "no test file names the target's class_name or res:// path; pass --tests"
            )
    else:
        tests = []

    if args.workdir and Path(args.workdir).resolve().is_relative_to(root):
        raise engine.SessionError("--workdir must be outside the project directory")

    godot = _resolve_godot(args.godot)
    print(f"{len(found)} mutant(s), {len(tests)} test file(s), {args.jobs} job(s)")
    for t in tests:
        print(f"  {t}")
    session = engine.run_session(
        root,
        target,
        args.command,
        godot,
        tests,
        jobs=args.jobs,
        timeout=args.timeout,
        excludes=args.exclude,
        keep_copies=args.keep_copies,
        workdir=Path(args.workdir).resolve() if args.workdir else None,
        lines=args.lines,
        on_result=_print_result,
        on_status=lambda msg: print(msg, flush=True),
    )
    _print_report(session)
    if args.json:
        _write_json(session, args.json)
    return EXIT_SURVIVORS if session.count(runner.SURVIVED) else EXIT_CLEAN


def cmd_selfcheck(args: argparse.Namespace) -> int:
    godot = _resolve_godot(args.godot)
    target = SELFCHECK_DIR / "fixture_math.gd"
    failures: list[str] = []

    for label, test, expect_survivors in (
        ("strong tests", "res://tests/test_fixture_strong.gd", False),
        ("hollow tests", "res://tests/test_fixture_hollow.gd", True),
    ):
        print(f"\n== {label}: {test}")
        session = engine.run_session(
            SELFCHECK_DIR,
            target,
            SELFCHECK_COMMAND,
            godot,
            [test],
            jobs=args.jobs,
            on_result=_print_result,
            on_status=lambda msg: print(msg, flush=True),
        )
        _print_report(session)
        survived = session.count(runner.SURVIVED)
        killed = session.count(runner.KILLED)
        if expect_survivors and survived == 0:
            failures.append(f"{label}: expected survivors, got 0 (hollow tests reported as killing mutants)")
        if not expect_survivors and survived:
            failures.append(f"{label}: expected 0 survivors, got {survived}")
        if not expect_survivors and killed == 0:
            failures.append(f"{label}: expected killed mutants, got 0")

    print()
    if failures:
        for f in failures:
            print(f"SELFCHECK FAIL: {f}")
        return EXIT_ERROR
    print("SELFCHECK PASS: strong tests killed every mutant, hollow tests left survivors")
    return EXIT_CLEAN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gobreak",
        description="Mutation testing for GDScript: change one line at a time, rerun the tests, report changes no test caught.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command_name", required=True)

    run = sub.add_parser("run", help="mutate one .gd file and run the tests against each mutant")
    run.add_argument("target", help="the .gd file to mutate: a file path or a res:// path")
    run.add_argument("--command", help="test command template; {godot} and {tests} are filled in")
    run.add_argument("--project", help="Godot project directory (default: nearest project.godot above the target)")
    run.add_argument("--godot", help="Godot executable (default: $GODOT, then godot on PATH)")
    run.add_argument("--tests", type=_csv, help="comma-separated res:// test paths (default: auto-select)")
    run.add_argument("--skip-tests", type=_csv, help="comma-separated substrings; auto-selected tests containing one are dropped")
    run.add_argument("--test-dirs", type=_csv, help="comma-separated dirs searched for tests (default: test,tests)")
    run.add_argument("--test-patterns", type=_csv, help="comma-separated test file globs (default: test_*.gd,*_test.gd,*Test.gd)")
    run.add_argument("--jobs", type=int, default=1, help="parallel workers, one project copy each (default: 1)")
    run.add_argument("--timeout", type=float, help="seconds per mutant run (default: 3 x baseline + 10)")
    run.add_argument("--lines", type=_lines, help="only mutate lines A-B (1-based, inclusive)")
    run.add_argument("--exclude", action="append", default=[], help="directory or file name left out of the project copy; repeatable")
    run.add_argument("--workdir", help="keep project copies here between runs; later runs copy only changed files")
    run.add_argument("--keep-copies", action="store_true", help="keep the temp project copies after the run")
    run.add_argument("--json", help="write the full report as JSON to this path")
    run.add_argument("--dry-run", action="store_true", help="list mutants only; no copy, no Godot")
    run.set_defaults(func=cmd_run)

    check = sub.add_parser("selfcheck", help="prove the tool tells strong tests from hollow ones on a bundled fixture")
    check.add_argument("--godot", help="Godot executable (default: $GODOT, then godot on PATH)")
    check.add_argument("--jobs", type=int, default=1, help="parallel workers (default: 1)")
    check.set_defaults(func=cmd_selfcheck)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command_name == "run" and not args.dry_run and not args.command:
        parser.error("run: --command is required unless --dry-run")
    if getattr(args, "jobs", 1) < 1:
        parser.error("--jobs must be >= 1")
    try:
        return args.func(args)
    except engine.SessionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
