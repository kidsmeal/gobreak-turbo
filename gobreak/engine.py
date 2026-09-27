"""One mutation session: copy, baseline, run every mutant, collect results."""

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


class SessionError(Exception):
    """A session cannot start: bad input or a failing baseline."""


@dataclass
class MutantResult:
    mutant: mut.Mutant
    status: str
    seconds: float


@dataclass
class Session:
    target: str
    tests: list[str]
    command: str
    baseline_seconds: float
    timeout: float
    results: list[MutantResult] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def score(self) -> float | None:
        killed = self.count(runner.KILLED) + self.count(runner.TIMEOUT)
        scored = killed + self.count(runner.SURVIVED)
        return None if scored == 0 else killed / scored


def run_session(
    project: Path,
    target: Path,
    command_template: str,
    godot: str,
    tests: list[str],
    jobs: int = 1,
    timeout: float | None = None,
    excludes: list[str] | None = None,
    keep_copies: bool = False,
    workdir: Path | None = None,
    lines: tuple[int, int] | None = None,
    on_result: Callable[[MutantResult, int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> Session:
    say = on_status or (lambda _msg: None)
    source = target.read_bytes().decode("utf-8")
    all_mutants = mut.generate(source)
    if lines is not None:
        all_mutants = [m for m in all_mutants if lines[0] <= m.line <= lines[1]]
    target_res = proj.to_res(project, target)
    rel = target.resolve().relative_to(project.resolve())
    command = runner.build_command(command_template, godot, tests)

    copies: list[Path] = []
    try:
        for i in range(max(1, jobs)):
            if workdir is not None:
                dest = workdir / f"job-{i + 1}" / project.name
                say(f"syncing project copy {dest}")
                n = proj.sync_project(project, dest, excludes or [])
                say(f"  {n} file(s) copied")
                copies.append(dest)
            else:
                say(f"copying project ({i + 1}/{max(1, jobs)})")
                copies.append(proj.copy_project(project, excludes or []))

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
        lock = threading.Lock()
        done = [0]

        def run_one(m: mut.Mutant) -> MutantResult:
            copy = pool.get()
            path = copy / rel
            original = path.read_bytes()
            try:
                path.write_bytes(mut.apply(source, m).encode("utf-8"))
                result = runner.run_command(command, str(copy), limit)
                status = runner.classify(result, baseline)
                seconds = result.seconds
                if status == runner.TIMEOUT:
                    # Confirm a timeout once before counting it: a machine
                    # under load can stall one run.
                    again = runner.run_command(command, str(copy), limit)
                    status = runner.classify(again, baseline)
                    seconds += again.seconds
            finally:
                path.write_bytes(original)
                pool.put(copy)
            res = MutantResult(m, status, seconds)
            with lock:
                done[0] += 1
                if on_result:
                    on_result(res, done[0], len(all_mutants))
            return res

        with ThreadPoolExecutor(max_workers=len(copies)) as ex:
            session.results = list(ex.map(run_one, all_mutants))
        return session
    finally:
        # --workdir copies persist for the next run's incremental sync.
        if workdir is None:
            for c in copies:
                if keep_copies:
                    say(f"kept copy: {c}")
                else:
                    proj.remove_tree(c.parent)
