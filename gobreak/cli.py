"""Command-line entry point."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from . import config as cfg
from . import engine
from . import mutants as mut
from . import project as proj
from . import runner
from . import triage

EXIT_CLEAN = 0
EXIT_SURVIVORS = 1
EXIT_ERROR = 2

SELFCHECK_DIR = Path(__file__).parent / "selfcheck"
SELFCHECK_COMMAND = "{godot} --headless --path . -s res://run_tests.gd -- --tests {tests}"

# Directories never walked for targets in a directory run.
SKIPPED_TARGET_DIRS = ("addons",)

_TRIAGE_ORDER = (
    (triage.DEAD, "dead: never ran in the tests, no reference in non-test code; delete it"),
    (triage.UNREACHED, "unreached: never ran in the tests, referenced by other code; add a test that runs it"),
    (triage.REACHED, "reached: ran in the tests, no test failed; rule it with `gobreak rule`"),
    (triage.RULED_GAP, "ruled gap: a recorded missing test"),
    (triage.RULED_EQUIVALENT, "ruled equivalent: recorded as no behavior change"),
)


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


def _resolve_path(target: str, project_arg: str | None) -> tuple[Path, Path]:
    """Return (project root, target path) for a file or directory target."""
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
    if not path.exists():
        raise engine.SessionError(f"target not found: {path}")
    if not (root / "project.godot").is_file():
        raise engine.SessionError(f"not a Godot project (no project.godot): {root}")
    return root.resolve(), path.resolve()


def _resolve_target(target: str, project_arg: str | None) -> tuple[Path, Path]:
    root, path = _resolve_path(target, project_arg)
    if not path.is_file():
        raise engine.SessionError(f"not a file: {path}")
    return root, path


def _collect_targets(root: Path, directory: Path, test_dirs: list[str] | None,
                     test_patterns: list[str] | None) -> list[Path]:
    """Every .gd file under `directory` except tests, addons and dot-dirs."""
    dirs = test_dirs or [d for d in proj.DEFAULT_TEST_DIRS if (root / d).is_dir()]
    test_roots = [proj.from_res(root, d).resolve() for d in dirs]
    pats = test_patterns or list(proj.DEFAULT_TEST_PATTERNS)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(directory):
        here = Path(dirpath).resolve()
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in SKIPPED_TARGET_DIRS
            and (here / d).resolve() not in test_roots
        ]
        if any(here == t or t in here.parents for t in test_roots):
            continue
        for name in filenames:
            if name.endswith(".gd") and not any(fnmatch.fnmatch(name, p) for p in pats):
                found.append(here / name)
    return sorted(found)


def _apply_config(args: argparse.Namespace, root: Path) -> None:
    """Fill every unset run option from .gobreak/config.json."""
    try:
        conf = cfg.load(root)
    except cfg.ConfigError as exc:
        raise engine.SessionError(str(exc)) from exc
    for key in ("command", "godot", "tests", "skip_tests", "test_dirs", "test_patterns",
                "jobs", "timeout", "exclude", "workdir"):
        if getattr(args, key) is None and key in conf:
            setattr(args, key, conf[key])
    if conf.get("coverage_selection") is False:
        args.no_coverage_selection = True
    if conf.get("triage") is False:
        args.no_triage = True
    if args.jobs is None:
        args.jobs = 1
    if args.exclude is None:
        args.exclude = []
    if args.jobs < 1:
        raise engine.SessionError("jobs must be >= 1")


def _print_result(res: engine.MutantResult, done: int, total: int) -> None:
    note = "  (no test reaches this line)" if res.tests_run == 0 and res.status == runner.SURVIVED else ""
    print(f"[{done}/{total}] {res.status:<8} {res.mutant.describe()}  ({res.seconds:.1f}s){note}", flush=True)


def _print_report(session: engine.Session) -> None:
    print()
    print(f"target:   {session.target}")
    print(f"tests:    {len(session.tests)} file(s)")
    print(f"baseline: {session.baseline_seconds:.1f}s, timeout {session.timeout:.1f}s")
    if session.coverage_seconds is not None:
        print(f"coverage: {session.coverage_seconds:.1f}s; each mutant runs only the tests that reach its line")
    if session.coverage_note:
        print(f"note:     {session.coverage_note}")
    counts = ", ".join(
        f"{name} {session.count(name)}"
        for name in (runner.KILLED, runner.SURVIVED, runner.TIMEOUT, runner.INVALID)
    )
    print(f"mutants:  {len(session.results)} ({counts})")
    score = session.score
    print("score:    n/a" if score is None else f"score:    {score:.0%} killed")
    survivors = session.survivors()
    if not survivors:
        return
    if not session.triaged:
        print("\nsurvivors (no test failed with this change):")
        for r in survivors:
            print(f"  #{r.mutant.index:<4} {r.mutant.describe()}")
        return
    print("triage:   " + ", ".join(f"{name} {len(session.survivors(name))}" for name, _ in _TRIAGE_ORDER))
    if session.triage_note:
        print(f"note:     {session.triage_note}")
    for name, heading in _TRIAGE_ORDER:
        group = session.survivors(name)
        if not group:
            continue
        print(f"\n{heading} ({len(group)}):")
        for r in group:
            line = f"  #{r.mutant.index:<4} {r.mutant.describe()}"
            if r.ruling is not None:
                line += f"  [{r.ruling.reason}]"
            print(line)
    if session.stale_rulings:
        print(f"\nstale rulings ({len(session.stale_rulings)}): the mutant is now killed or its line changed; "
              "remove with `gobreak rule <target> --clear-stale`:")
        for ruling in session.stale_rulings:
            print(f"  {ruling.ruling:<10} {ruling.before}  ->  {ruling.after}")


def _session_dict(session: engine.Session) -> dict:
    return {
        "target": session.target,
        "tests": session.tests,
        "command": session.command,
        "baseline_seconds": round(session.baseline_seconds, 3),
        "coverage_seconds": None if session.coverage_seconds is None else round(session.coverage_seconds, 3),
        "coverage_note": session.coverage_note,
        "timeout_seconds": round(session.timeout, 3),
        "summary": {
            name: session.count(name)
            for name in (runner.KILLED, runner.SURVIVED, runner.TIMEOUT, runner.INVALID)
        },
        "triage": (
            {name: len(session.survivors(name)) for name, _ in _TRIAGE_ORDER}
            if session.triaged else None
        ),
        "triage_note": session.triage_note,
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
                "tests_run": r.tests_run,
                "triage": r.triage,
                "reason": r.ruling.reason if r.ruling else None,
                "seconds": round(r.seconds, 3),
            }
            for r in session.results
        ],
        "stale_rulings": [
            {"before": s.before, "after": s.after, "ruling": s.ruling, "reason": s.reason}
            for s in session.stale_rulings
        ],
    }


def _selected_lines(args: argparse.Namespace, root: Path, target: Path) -> set[int] | None:
    """Lines to mutate from --lines and --changed-since; None means all."""
    selected: set[int] | None = None
    if args.lines:
        selected = set(range(args.lines[0], args.lines[1] + 1))
    if args.changed_since:
        try:
            changed = proj.changed_lines(root, target, args.changed_since)
        except ValueError as exc:
            raise engine.SessionError(f"--changed-since: {exc}") from exc
        if changed is not None:
            selected = changed if selected is None else selected & changed
    return selected


def _mutants_for(args: argparse.Namespace, root: Path, target: Path) -> tuple[list[mut.Mutant], set[int] | None]:
    only_lines = _selected_lines(args, root, target)
    found = mut.generate(target.read_bytes().decode("utf-8"))
    if only_lines is not None:
        found = [m for m in found if m.line in only_lines]
    return found, only_lines


def _tests_for(args: argparse.Namespace, root: Path, target: Path) -> list[str]:
    if args.tests:
        return args.tests
    if not runner.uses_tests(args.command):
        return []
    tests = proj.find_covering_tests(root, target, args.test_dirs, args.test_patterns)
    if args.skip_tests:
        tests = [t for t in tests if not any(s in t for s in args.skip_tests)]
    return tests


def _score_text(score: float | None) -> str:
    return "n/a" if score is None else f"{score:.0%}"


def _print_summary(sessions: list[engine.Session], skipped: list[tuple[str, str]]) -> None:
    print("\n== summary")
    header = f"{'file':<48}{'mutants':>8}{'killed':>8}{'surv':>6}{'dead':>6}{'unrch':>6}{'reach':>6}{'ruled':>6}{'score':>7}"
    print(header)
    totals = [0] * 7
    for s in sessions:
        killed = s.count(runner.KILLED) + s.count(runner.TIMEOUT)
        ruled = len(s.survivors(triage.RULED_GAP)) + len(s.survivors(triage.RULED_EQUIVALENT))
        row = [len(s.results), killed, s.count(runner.SURVIVED), len(s.survivors(triage.DEAD)),
               len(s.survivors(triage.UNREACHED)), len(s.survivors(triage.REACHED)), ruled]
        totals = [a + b for a, b in zip(totals, row)]
        name = s.target if len(s.target) <= 47 else "..." + s.target[-44:]
        print(f"{name:<48}" + "".join(f"{v:>{w}}" for v, w in zip(row, (8, 8, 6, 6, 6, 6, 6)))
              + f"{_score_text(s.score):>7}")
    scored = totals[1] + totals[2]
    total_score = None if scored == 0 else totals[1] / scored
    print(f"{'total':<48}" + "".join(f"{v:>{w}}" for v, w in zip(totals, (8, 8, 6, 6, 6, 6, 6)))
          + f"{_score_text(total_score):>7}")
    for name, why in skipped:
        print(f"skipped {name}: {why}")


def cmd_run(args: argparse.Namespace) -> int:
    root, path = _resolve_path(args.target, args.project)
    _apply_config(args, root)
    directory = path.is_dir()
    if directory and args.lines:
        raise engine.SessionError("--lines needs a single file target")
    targets = _collect_targets(root, path, args.test_dirs, args.test_patterns) if directory else [path]
    if directory and not targets:
        raise engine.SessionError(f"no .gd files to mutate under {path}")

    plan: list[tuple[Path, list[mut.Mutant], set[int] | None]] = []
    skipped: list[tuple[str, str]] = []
    for target in targets:
        found, only_lines = _mutants_for(args, root, target)
        if not found:
            skipped.append((proj.to_res(root, target), "no mutants on the selected lines"))
            continue
        plan.append((target, found, only_lines))

    if args.dry_run:
        for target, found, _ in plan:
            if directory:
                print(f"\n== {proj.to_res(root, target)}")
            for m in found:
                print(f"#{m.index:<4} {m.describe()}")
        print(f"\n{sum(len(f) for _, f, _ in plan)} mutant(s) in {len(plan)} file(s)")
        for name, why in skipped:
            print(f"skipped {name}: {why}")
        return EXIT_CLEAN

    if not args.command:
        raise engine.SessionError("run: --command (or `command` in .gobreak/config.json) is required unless --dry-run")
    if not plan:
        print("no mutants generated")
        return EXIT_CLEAN

    runnable: list[tuple[Path, list[mut.Mutant], set[int] | None, list[str]]] = []
    for target, found, only_lines in plan:
        tests = _tests_for(args, root, target)
        if runner.uses_tests(args.command) and not tests:
            if not directory:
                raise engine.SessionError("no test file names the target's class_name or res:// path; pass --tests")
            skipped.append((proj.to_res(root, target), "no test file names it"))
            continue
        runnable.append((target, found, only_lines, tests))

    if args.workdir and Path(args.workdir).resolve().is_relative_to(root):
        raise engine.SessionError("--workdir must be outside the project directory")
    godot = _resolve_godot(args.godot)
    sessions: list[engine.Session] = []
    say = lambda msg: print(msg, flush=True)  # noqa: E731

    with engine.Workspace(root, args.jobs, args.exclude,
                          Path(args.workdir).resolve() if args.workdir else None,
                          args.keep_copies, say) as ws:
        for target, found, only_lines, tests in runnable:
            print(f"\n== {proj.to_res(root, target)}: {len(found)} mutant(s), {len(tests)} test file(s), {args.jobs} job(s)")
            for t in tests:
                print(f"  {t}")
            try:
                session = engine.run_session(
                    ws, target, args.command, godot, tests,
                    timeout=args.timeout,
                    only_lines=only_lines,
                    on_result=_print_result,
                    on_status=say,
                    triage_enabled=not args.no_triage,
                    test_patterns=args.test_patterns,
                    coverage_selection=not args.no_coverage_selection,
                )
            except engine.SessionError as exc:
                if not directory:
                    raise
                skipped.append((proj.to_res(root, target), str(exc).splitlines()[0]))
                continue
            _print_report(session)
            sessions.append(session)

    if directory:
        _print_summary(sessions, skipped)
    if args.json:
        data = (
            {"version": __version__, "sessions": [_session_dict(s) for s in sessions],
             "skipped": [{"target": n, "reason": w} for n, w in skipped]}
            if directory else dict(version=__version__, **_session_dict(sessions[0]))
        )
        Path(args.json).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return EXIT_SURVIVORS if any(s.open_survivors for s in sessions) else EXIT_CLEAN


def cmd_rule(args: argparse.Namespace) -> int:
    root, target = _resolve_target(args.target, args.project)
    source = target.read_bytes().decode("utf-8")
    found = {m.index: m for m in mut.generate(source)}
    target_res = proj.to_res(root, target)
    rulings = triage.load_rulings(root)

    if args.clear_stale:
        live = {(target_res, m.before, m.after) for m in found.values()}
        kept = [r for r in rulings if r.file != target_res or r.key() in live]
        path = triage.save_rulings(root, kept)
        print(f"removed {len(rulings) - len(kept)} ruling(s) whose mutant no longer exists; {path}")
        return EXIT_CLEAN

    if args.id is None:
        raise engine.SessionError("rule: pass a mutant id (from --dry-run or the run report), or --clear-stale")
    m = found.get(args.id)
    if m is None:
        raise engine.SessionError(f"no mutant #{args.id} in {target_res}; ids come from the current file, rerun --dry-run")
    key = (target_res, m.before, m.after)
    rulings = [r for r in rulings if r.key() != key]
    if args.clear:
        path = triage.save_rulings(root, rulings)
        print(f"cleared ruling for #{m.index} {m.describe()}; {path}")
        return EXIT_CLEAN
    if args.verdict is None or not args.reason:
        raise engine.SessionError("rule: pass a verdict (equivalent or gap) and --reason")
    rulings.append(triage.Ruling(target_res, m.before, m.after, args.verdict, args.reason))
    path = triage.save_rulings(root, rulings)
    print(f"ruled #{m.index} {args.verdict}: {m.describe()}; {path}")
    return EXIT_CLEAN


def _funcs_of(session: engine.Session, source: str, status: str) -> set[str]:
    infos = triage.analyze(source)
    return {infos[r.mutant.line - 1].func or "" for r in session.survivors(status)}


def cmd_selfcheck(args: argparse.Namespace) -> int:
    godot = _resolve_godot(args.godot)
    target = SELFCHECK_DIR / "fixture_math.gd"
    source = target.read_text(encoding="utf-8")
    failures: list[str] = []
    say = lambda msg: print(msg, flush=True)  # noqa: E731

    with engine.Workspace(SELFCHECK_DIR, args.jobs, say=say) as ws:
        def session_for(test: str) -> engine.Session:
            print(f"\n== {test}")
            s = engine.run_session(ws, target, SELFCHECK_COMMAND, godot, [test],
                                   on_result=_print_result, on_status=say)
            _print_report(s)
            return s

        strong = session_for("res://tests/test_fixture_strong.gd")
        hollow = session_for("res://tests/test_fixture_hollow.gd")

    reached = strong.survivors(triage.REACHED)
    if reached:
        failures.append(f"strong tests: expected 0 reached survivors, got {len(reached)}")
    dead = _funcs_of(strong, source, triage.DEAD)
    if dead != {"unused_double"}:
        failures.append(f"strong tests: expected dead survivors only in unused_double, got {sorted(dead)}")
    unreached = _funcs_of(strong, source, triage.UNREACHED)
    if unreached != {"only_called_by_caller", "safe_div"}:
        failures.append(f"strong tests: expected unreached survivors only in only_called_by_caller and safe_div, got {sorted(unreached)}")
    if strong.count(runner.KILLED) == 0:
        failures.append("strong tests: expected killed mutants, got 0")
    if not hollow.survivors(triage.REACHED):
        failures.append("hollow tests: expected reached survivors, got 0 (hollow tests reported as killing mutants)")
    if hollow.count(runner.KILLED):
        failures.append(f"hollow tests: expected 0 killed, got {hollow.count(runner.KILLED)}")

    print()
    if failures:
        for f in failures:
            print(f"SELFCHECK FAIL: {f}")
        return EXIT_ERROR
    print("SELFCHECK PASS: strong tests killed every reached mutant; triage found the dead and "
          "unreached functions; hollow tests left reached survivors")
    return EXIT_CLEAN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gobreak",
        description="Mutation testing for GDScript: change one line at a time, rerun the tests, report changes no test caught.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command_name", required=True)

    run = sub.add_parser("run", help="mutate a .gd file (or every .gd file under a directory) and run the tests against each mutant")
    run.add_argument("target", help="a .gd file or a directory: a file path or a res:// path")
    run.add_argument("--command", help="test command template; {godot} and {tests} are filled in")
    run.add_argument("--project", help="Godot project directory (default: nearest project.godot above the target)")
    run.add_argument("--godot", help="Godot executable (default: $GODOT, then godot on PATH)")
    run.add_argument("--tests", type=_csv, help="comma-separated res:// test paths (default: auto-select)")
    run.add_argument("--skip-tests", type=_csv, help="comma-separated substrings; auto-selected tests containing one are dropped")
    run.add_argument("--test-dirs", type=_csv, help="comma-separated dirs searched for tests (default: test,tests)")
    run.add_argument("--test-patterns", type=_csv, help="comma-separated test file globs (default: test_*.gd,*_test.gd,*Test.gd)")
    run.add_argument("--jobs", type=int, help="parallel workers, one project copy each (default: 1)")
    run.add_argument("--timeout", type=float, help="seconds per mutant run (default: 3 x baseline + 10)")
    run.add_argument("--lines", type=_lines, help="only mutate lines A-B (1-based, inclusive); single file only")
    run.add_argument("--changed-since", metavar="REF",
                     help="only mutate lines changed since this git ref, uncommitted edits included")
    run.add_argument("--exclude", action="append", help="directory or file name left out of the project copy; repeatable")
    run.add_argument("--workdir", help="keep project copies here between runs; later runs copy only changed files")
    run.add_argument("--keep-copies", action="store_true", help="keep the temp project copies after the run")
    run.add_argument("--json", help="write the full report as JSON to this path")
    run.add_argument("--dry-run", action="store_true", help="list mutants only; no copy, no Godot")
    run.add_argument("--no-triage", action="store_true", help="skip rulings and survivor sorting")
    run.add_argument("--no-coverage-selection", action="store_true",
                     help="run every selected test for every mutant instead of only the tests that reach its line")
    run.set_defaults(func=cmd_run)

    rule = sub.add_parser("rule", help="record a ruling for one surviving mutant in .gobreak/rulings.json")
    rule.add_argument("target", help="the .gd file: a file path or a res:// path")
    rule.add_argument("id", type=int, nargs="?", help="mutant id from --dry-run or the run report")
    rule.add_argument("verdict", nargs="?", choices=[triage.EQUIVALENT, triage.GAP],
                      help="equivalent: no behavior change; gap: a missing test")
    rule.add_argument("--reason", help="why; stored with the ruling and printed in reports")
    rule.add_argument("--clear", action="store_true", help="remove the ruling for this mutant")
    rule.add_argument("--clear-stale", action="store_true", help="remove rulings for this file whose mutant no longer exists")
    rule.add_argument("--project", help="Godot project directory (default: nearest project.godot above the target)")
    rule.set_defaults(func=cmd_rule)

    check = sub.add_parser("selfcheck", help="prove the tool tells strong tests from hollow ones on a bundled fixture")
    check.add_argument("--godot", help="Godot executable (default: $GODOT, then godot on PATH)")
    check.add_argument("--jobs", type=int, default=1, help="parallel workers (default: 1)")
    check.set_defaults(func=cmd_selfcheck)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command_name == "selfcheck" and args.jobs < 1:
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
