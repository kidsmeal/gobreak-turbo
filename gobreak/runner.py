"""Running a test command and classifying its result."""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass

KILLED = "killed"
SURVIVED = "survived"
TIMEOUT = "timeout"
INVALID = "invalid"

# Godot prints these when a script fails to compile. A mutant that hits one
# never reached the tests, so the tests get no credit for it.
_PARSE_ERROR = re.compile(r"Parse Error:|with error \"Parse error\"")
# Godot prints this for a runtime error. GDScript has no exceptions: the
# failing call aborts and the rest of the run continues, so a harness that
# only counts assertions can exit 0 through it.
_SCRIPT_ERROR = "SCRIPT ERROR"

_TESTS_PLACEHOLDER = re.compile(r"\{tests(?::([^}]*))?\}")


@dataclass
class RunResult:
    exit_code: int | None
    output: str
    seconds: float
    timed_out: bool


def _quote(value: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def build_command(template: str, godot: str, tests: list[str]) -> str:
    """Fill `{godot}` and `{tests}` in a command template.

    `{tests}` becomes the test paths joined by commas.
    `{tests:FLAG}` becomes `FLAG path` once per test path.
    """

    def fill_tests(m: re.Match[str]) -> str:
        flag = m.group(1)
        if flag is None:
            return _quote(",".join(tests)) if tests else '""'
        return " ".join(f"{flag} {_quote(t)}" for t in tests)

    command = _TESTS_PLACEHOLDER.sub(fill_tests, template)
    return command.replace("{godot}", _quote(godot))


def uses_tests(template: str) -> bool:
    return bool(_TESTS_PLACEHOLDER.search(template))


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_command(command: str, cwd: str, timeout: float | None) -> RunResult:
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, _ = proc.communicate()
        timed_out = True
    return RunResult(
        exit_code=None if timed_out else proc.returncode,
        output=(out or b"").decode("utf-8", errors="replace"),
        seconds=time.monotonic() - start,
        timed_out=timed_out,
    )


@dataclass
class Baseline:
    seconds: float
    has_script_error: bool
    has_parse_error: bool


def baseline_from(result: RunResult) -> Baseline:
    return Baseline(
        seconds=result.seconds,
        has_script_error=_SCRIPT_ERROR in result.output,
        has_parse_error=bool(_PARSE_ERROR.search(result.output)),
    )


def classify(result: RunResult, baseline: Baseline) -> str:
    if result.timed_out:
        return TIMEOUT
    if not baseline.has_parse_error and _PARSE_ERROR.search(result.output):
        return INVALID
    if result.exit_code != 0:
        return KILLED
    if not baseline.has_script_error and _SCRIPT_ERROR in result.output:
        return KILLED
    return SURVIVED
