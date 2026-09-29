# Configuration

`gobreak run` reads defaults from `.gobreak/config.json` in the Godot project root. A command-line flag overrides the matching key. The config's `command` runs like any project script: run gobreak only on projects whose code you would run anyway.

## Config file
```json
{
  "command": "{godot} --headless --path . res://tests/run_all.tscn -- --test-filter {tests}",
  "godot": "godot",
  "skip_tests": ["test_perf_budgets", "/integration/"],
  "jobs": 4,
  "workdir": "../gobreak-work"
}
```

| Key | Type | Default | Effect |
|---|---|---|---|
| `command` | string | none, required to run | test command template, see Placeholders |
| `godot` | string | `$GODOT`, then `godot` | Godot executable |
| `tests` | list | auto-select | `res://` test paths to run; disables auto-select |
| `skip_tests` | list | none | drop auto-selected tests whose path contains any entry |
| `test_dirs` | list | `test`, `tests` | directories searched recursively for tests |
| `test_patterns` | list | `test_*.gd`, `*_test.gd`, `*Test.gd` | test file name globs |
| `jobs` | int | `1` | parallel workers; each makes its own project copy |
| `timeout` | number | `3 x baseline + 10` s | seconds per mutant run; a timeout is re-run once before it counts |
| `exclude` | list | none | directory or file names left out of the copy; `.git` is always left out |
| `workdir` | string | temp dir, deleted after the run | kept copies; relative paths resolve against the project; must be outside the project |
| `coverage_selection` | bool | `true` | run only the tests that reach each mutated line |
| `triage` | bool | `true` | sort survivors into `dead`, `unreached`, `reached`, ruled |

An unknown key or a value of the wrong type stops the run with exit `2`.

## Flags
| Flag | Config key | Effect |
|---|---|---|
| `target` | none | a `.gd` file or a directory, as a file path or a `res://` path |
| `--command` | `command` | test command template |
| `--project` | none | project root; default is the nearest `project.godot` above the target |
| `--godot` | `godot` | Godot executable |
| `--tests` | `tests` | comma-separated `res://` test paths |
| `--skip-tests` | `skip_tests` | comma-separated substrings |
| `--test-dirs` | `test_dirs` | comma-separated directories |
| `--test-patterns` | `test_patterns` | comma-separated globs |
| `--jobs` | `jobs` | parallel workers |
| `--timeout` | `timeout` | seconds per mutant run |
| `--lines A-B` | none | mutate lines `A` to `B` only; single file target only |
| `--changed-since REF` | none | mutate only lines changed since a git ref, uncommitted edits included; an untracked file counts as all lines |
| `--exclude NAME` | `exclude` | repeatable |
| `--workdir` | `workdir` | kept copies directory |
| `--keep-copies` | none | keep temp copies; ignored with a workdir |
| `--json PATH` | none | full report as JSON; a directory run writes one entry per file |
| `--dry-run` | none | list mutants only; no copy, no Godot |
| `--no-triage` | `triage: false` | skip rulings and survivor sorting |
| `--no-coverage-selection` | `coverage_selection: false` | run every selected test for every mutant |

`rule` takes `target`, `id`, `equivalent` or `gap`, `--reason`, `--clear`, `--clear-stale`, `--project`. `selfcheck` takes `--godot` and `--jobs`.

## Placeholders
| Placeholder | Becomes |
|---|---|
| `{godot}` | the Godot executable, quoted |
| `{tests}` | selected test paths joined by `,` |
| `{tests:FLAG}` | `FLAG path` once per selected test, for runners that repeat a flag |

The command runs with the project copy as its working directory, so use `--path .`. Coverage selection needs `{tests}` or `{tests:FLAG}` in the command; without it every mutant runs the full command.

## Framework commands
Verified with `examples/` on Godot `4.6.2`:

| Framework | `command` |
|---|---|
| GUT `v9.6.1` | `{godot} --headless --path . -s addons/gut/gut_cmdln.gd -gexit -gtest={tests}` |
| gdUnit4 `v6.2.1` | `{godot} --headless --path . -s -d --remote-debug tcp://127.0.0.1:0 res://addons/gdUnit4/bin/GdUnitCmdTool.gd --ignoreHeadlessMode {tests:-a}` |

The gdUnit4 `--remote-debug` address is never bound; it stops Godot's interactive debugger from waiting on a parse error, as gdUnit4's own `runtest.cmd` does.

## Directory runs
`gobreak run <dir>` mutates every `.gd` file under the directory, except files matching `test_patterns`, anything under `test_dirs`, `addons/`, and dot-directories. Project copies are made once and shared by every file. A file with no covering test is skipped and listed in the summary.
