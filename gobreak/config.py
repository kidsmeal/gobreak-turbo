"""Project config: `.gobreak/config.json` supplies defaults for `gobreak run`.

A flag on the command line overrides the matching config key. The config's
`command` runs like any project script: only run gobreak on projects whose
code you would run anyway.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(".gobreak") / "config.json"

# key -> (accepted types, description)
KEYS: dict[str, tuple[tuple[type, ...], str]] = {
    "command": ((str,), "test command template"),
    "godot": ((str,), "Godot executable"),
    "tests": ((list,), "res:// test paths; disables auto-select"),
    "skip_tests": ((list,), "substrings that drop auto-selected tests"),
    "test_dirs": ((list,), "directories searched for tests"),
    "test_patterns": ((list,), "test file name globs"),
    "jobs": ((int,), "parallel workers"),
    "timeout": ((int, float), "seconds per mutant run"),
    "exclude": ((list,), "names left out of the project copy"),
    "workdir": ((str,), "kept copies directory, relative to the project or absolute"),
    "coverage_selection": ((bool,), "run only the tests that reach each mutated line"),
    "triage": ((bool,), "sort survivors into dead, unreached, reached, ruled"),
}


class ConfigError(Exception):
    pass


def load(project: Path) -> dict:
    """Return the validated config, or {} when the file does not exist."""
    path = project / CONFIG_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a JSON object")
    for key, value in data.items():
        if key not in KEYS:
            raise ConfigError(f"{path}: unknown key {key!r}; valid keys: {', '.join(sorted(KEYS))}")
        types, _ = KEYS[key]
        # bool is a subclass of int; reject it where a number is expected.
        if isinstance(value, bool) and bool not in types:
            raise ConfigError(f"{path}: {key!r} must be {types[0].__name__}")
        if not isinstance(value, types):
            raise ConfigError(f"{path}: {key!r} must be {types[0].__name__}")
        if types == (list,) and not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{path}: {key!r} must be a list of strings")
    if "workdir" in data:
        workdir = Path(data["workdir"])
        data["workdir"] = str(workdir if workdir.is_absolute() else (project / workdir).resolve())
    return data
