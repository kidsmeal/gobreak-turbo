"""Mutation sessions: project copies, baseline, coverage map, mutants, triage."""

from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import mutants as mut
from . import project as proj
from . import runner
from . import triage


class SessionError(Exception):
    """A session cannot start: bad input or a failing baseline."""


@dataclass
class MutantResult:
    mutant: mut.Mutant
    status: str
    seconds: float
    tests_run: int = 0  # 0 with status survived: no test reaches the line
    triage: str | None = None  # survivors only: one of the triage.* statuses
    ruling: triage.Ruling | None = None


@dataclass
class Session:
    target: str
    tests: list[str]
    command: str
    baseline_seconds: float
    timeout: float
    results: list[MutantResult] = field(default_factory=list)
    coverage_seconds: float | None = None  # None: no coverage map was built
    coverage_note: str | None = None
    triaged: bool = False
    triage_note: str | None = None
    stale_rulings: list[triage.Ruling] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    def survivors(self, triage_status: str | None = None) -> list[MutantResult]:
        return [
            r for r in self.results
            if r.status == runner.SURVIVED and (triage_status is None or r.triage == triage_status)
        ]

    @property
    def open_survivors(self) -> list[MutantResult]:
        """Survivors not ruled equivalent: the ones still owed a fix."""
        return [r for r in self.survivors() if r.triage != triage.RULED_EQUIVALENT]

    @property
    def score(self) -> float | None:
        killed = self.count(runner.KILLED) + self.count(runner.TIMEOUT)
        scored = killed + self.count(runner.SURVIVED)
        return None if scored == 0 else killed / scored


class Workspace:
    """Project copies the mutants run in, one per job.

    Temp copies are deleted on close unless `keep`; `workdir` copies persist
    and are synced incrementally on the next run.
    """

    def __init__(
        self,
        project: Path,
        jobs: int = 1,
        excludes: list[str] | None = None,
        workdir: Path | None = None,
        keep: bool = False,
        say: Callable[[str], None] | None = None,
    ) -> None:
        self.project = project
        self.jobs = max(1, jobs)
        self.excludes = excludes or []
        self.workdir = workdir
        self.keep = keep
        self.say = say or (lambda _msg: None)
        self.copies: list[Path] = []

    def __enter__(self) -> Workspace:
        try:
            for i in range(self.jobs):
                if self.workdir is not None:
                    dest = self.workdir / f"job-{i + 1}" / self.project.name
                    self.say(f"syncing project copy {dest}")
                    n = proj.sync_project(self.project, dest, self.excludes)
                    self.say(f"  {n} file(s) copied")
                    self.copies.append(dest)
                else:
                    self.say(f"copying project ({i + 1}/{self.jobs})")
                    self.copies.append(proj.copy_project(self.project, self.excludes))
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self.workdir is not None:
            return
        for c in self.copies:
            if self.keep:
                self.say(f"kept copy: {c}")
            else:
                proj.remove_tree(c.parent)
        self.copies = []


def run_session(
    workspace: Workspace,
    target: Path,
    command_template: str,
    godot: str,
    tests: list[str],
    timeout: float | None = None,
    only_lines: set[int] | None = None,
    on_result: Callable[[MutantResult, int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    triage_enabled: bool = True,
    test_patterns: list[str] | None = None,
    coverage_selection: bool = True,
) -> Session:
    say = on_status or (lambda _msg: None)
    project = workspace.project
    copies = workspace.copies
    source = target.read_bytes().decode("utf-8")
    all_mutants = mut.generate(source)
    if only_lines is not None:
        all_mutants = [m for m in all_mutants if m.line in only_lines]
    target_res = proj.to_res(project, target)
    rel = target.resolve().relative_to(project.resolve())
    command = runner.build_command(command_template, godot, tests)

    say("baseline run")
    base = runner.run_command(command, str(copies[0]), None)
    if base.exit_code != 0:
        tail = "\n".join(base.output.splitlines()[-30:])
        raise SessionError(f"baseline run failed with exit {base.exit_code}; tests must pass unmutated\n{tail}")
    baseline = runner.baseline_from(base)
    limit = timeout if timeout is not None else base.seconds * 3 + 10
    session = Session(target_res, tests, command, base.seconds, limit)

    pool: queue.Queue[Path] = queue.Queue()
    for c in copies:
        pool.put(c)

    coverage: _Coverage | None = None
    if coverage_selection and tests and runner.uses_tests(command_template) and all_mutants:
        coverage = _build_coverage(session, all_mutants, source, rel, copies, pool,
                                   command_template, godot, tests, limit, say)

    lock = threading.Lock()
    done = [0]

    def tests_for(m: mut.Mutant) -> list[str]:
        if coverage is None or m.line not in coverage.marked:
            return tests
        return coverage.tests_for_line(m.line)

    def run_one(m: mut.Mutant) -> MutantResult:
        selected = tests_for(m)
        if not selected:
            res = MutantResult(m, runner.SURVIVED, 0.0, tests_run=0)
        else:
            cmd = command if selected is tests else runner.build_command(command_template, godot, selected)
            copy = pool.get()
            path = copy / rel
            original = path.read_bytes()
            try:
                path.write_bytes(mut.apply(source, m).encode("utf-8"))
                result = runner.run_command(cmd, str(copy), limit)
                status = runner.classify(result, baseline)
                seconds = result.seconds
                if status == runner.TIMEOUT:
                    # Confirm a timeout once before counting it: a machine
                    # under load can stall one run.
                    again = runner.run_command(cmd, str(copy), limit)
                    status = runner.classify(again, baseline)
                    seconds += again.seconds
            finally:
                path.write_bytes(original)
                pool.put(copy)
            res = MutantResult(m, status, seconds, tests_run=len(selected))
        with lock:
            done[0] += 1
            if on_result:
                on_result(res, done[0], len(all_mutants))
        return res

    with ThreadPoolExecutor(max_workers=len(copies)) as ex:
        session.results = list(ex.map(run_one, all_mutants))

    if triage_enabled:
        _triage(session, project, target, source, copies[0], rel, command, limit,
                test_patterns or list(proj.DEFAULT_TEST_PATTERNS), coverage, say)
    return session


@dataclass
class _Coverage:
    marked: set[int]  # lines that carried a marker
    hits: dict[str, set[int]]  # test path -> marked lines it reached
    unmapped: list[str]  # tests that failed alone; kept for every line

    def tests_for_line(self, line: int) -> list[str]:
        reached = [t for t, lines in self.hits.items() if line in lines]
        return reached + [t for t in self.unmapped if t not in reached]

    def reached(self, line: int) -> bool:
        return bool(self.tests_for_line(line))


def _build_coverage(
    session: Session,
    mutants: list[mut.Mutant],
    source: str,
    rel: Path,
    copies: list[Path],
    pool: queue.Queue,
    command_template: str,
    godot: str,
    tests: list[str],
    limit: float,
    say: Callable[[str], None],
) -> _Coverage:
    """Run each test file alone once against the instrumented target."""
    instrumented, marked = triage.instrument(source, {m.line for m in mutants})
    say(f"coverage map: {len(tests)} test file(s), {len(marked)} marked line(s)")
    originals = {c: (c / rel).read_bytes() for c in copies}
    hits: dict[str, set[int]] = {}
    unmapped: list[str] = []
    total = [0.0]
    lock = threading.Lock()

    def map_one(test: str) -> None:
        copy = pool.get()
        try:
            run = runner.run_command(runner.build_command(command_template, godot, [test]), str(copy), limit)
        finally:
            pool.put(copy)
        with lock:
            total[0] += run.seconds
            if run.timed_out or run.exit_code != 0:
                unmapped.append(test)
            else:
                hits[test] = triage.hits_from_output(run.output) & marked

    try:
        for c in copies:
            (c / rel).write_bytes(instrumented.encode("utf-8"))
        with ThreadPoolExecutor(max_workers=len(copies)) as ex:
            list(ex.map(map_one, tests))
    finally:
        for c, data in originals.items():
            (c / rel).write_bytes(data)

    session.coverage_seconds = total[0]
    if unmapped:
        session.coverage_note = (
            f"{len(unmapped)} test file(s) failed when run alone and run for every mutant: "
            + ", ".join(sorted(unmapped))
        )
    return _Coverage(marked, hits, sorted(unmapped))


def _triage(
    session: Session,
    project: Path,
    target: Path,
    source: str,
    copy_root: Path,
    rel: Path,
    command: str,
    limit: float,
    test_patterns: list[str],
    coverage: _Coverage | None,
    say: Callable[[str], None],
) -> None:
    """Sort survivors by rulings, then by line coverage and references.

    Uses the coverage map when one was built; otherwise runs the tests once
    with markers before the unruled survivor lines.
    """
    session.triaged = True
    rulings = [r for r in triage.load_rulings(project) if r.file == session.target]
    by_key = {(session.target, r.mutant.before, r.mutant.after): r for r in session.results}
    for ruling in rulings:
        res = by_key.get(ruling.key())
        if res is None or res.status != runner.SURVIVED:
            session.stale_rulings.append(ruling)
        else:
            res.ruling = ruling
            res.triage = triage.RULED_EQUIVALENT if ruling.ruling == triage.EQUIVALENT else triage.RULED_GAP

    unruled = [r for r in session.survivors() if r.triage is None]
    if not unruled:
        return

    if coverage is not None:
        marked = coverage.marked
        hits = {line for line in marked if coverage.reached(line)}
    else:
        say("triage run (line coverage)")
        copy_target = copy_root / rel
        instrumented, marked = triage.instrument(source, {r.mutant.line for r in unruled})
        original = copy_target.read_bytes()
        try:
            copy_target.write_bytes(instrumented.encode("utf-8"))
            run = runner.run_command(command, str(copy_root), limit)
        finally:
            copy_target.write_bytes(original)
        if run.timed_out or run.exit_code != 0:
            session.triage_note = (
                f"triage run failed (exit {run.exit_code}, timed out {run.timed_out}); "
                "unruled survivors marked reached"
            )
            for r in unruled:
                r.triage = triage.REACHED
            return
        hits = triage.hits_from_output(run.output)

    infos = triage.analyze(source)
    refs: dict[str, int] = {}
    for r in unruled:
        line = r.mutant.line
        if line not in marked or line in hits:
            r.triage = triage.REACHED
            continue
        func = infos[line - 1].func
        if func is None or triage.is_engine_callback(func):
            r.triage = triage.UNREACHED
            continue
        if func not in refs:
            refs[func] = triage.count_references(project, target, func, source, test_patterns)
        r.triage = triage.DEAD if refs[func] == 0 else triage.UNREACHED
