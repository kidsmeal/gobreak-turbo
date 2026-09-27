# GoBreak Turbo

Mutation testing CLI for Godot 4 projects. It changes one line of a GDScript file at a time, reruns your tests, and lists the changes no test caught.

## What it does
- Generates single-line mutants for a `.gd` file: comparison, arithmetic, logic, `not`, bool, number, `if` negation, statement deletion. Full list in `docs/MUTATORS.md`.
- Skips text inside strings and comments, declaration lines, and lines tagged `# mutation: ignore`.
- Auto-selects the test files that name the target's `class_name` or `res://` path.
- Runs each mutant in a temp copy of the project; your working tree is never written.
- Runs mutants in parallel with `--jobs N`, one project copy per worker.
- Classifies each mutant as `killed`, `survived`, `timeout` or `invalid` (does not compile).
- Counts a GDScript runtime error (`SCRIPT ERROR`) as killed even when the test command exits `0`.
- Works with any test command that exits non-zero on failure: GUT, gdUnit4, or a custom runner.
- Proves itself with `selfcheck`: a bundled fixture where strong tests must kill every mutant and hollow tests must kill none.

## Requirements
- Python `>= 3.10`, no third-party packages.
- Godot `4.x` on `PATH` as `godot`, in `$GODOT`, or passed with `--godot`.
- A test suite that passes before mutation and runs headless.

## Install
From a clone of this repo:
```bash
pip install .
```

## Usage
```bash
gobreak selfcheck
```
Runs the bundled fixture twice and exits `0` when strong tests kill every mutant and hollow tests leave survivors.

```bash
gobreak run src/health.gd --dry-run
```
Lists the mutants for `src/health.gd` without starting Godot.

```bash
gobreak run src/health.gd --command "{godot} --headless --path . -s addons/gut/gut_cmdln.gd -gexit -gtest={tests}"
```
Mutates `src/health.gd` and runs the covering GUT tests against each mutant. Exit `0`: no survivors. Exit `1`: survivors listed. Exit `2`: error or failing baseline.

```bash
gobreak run res://src/health.gd --command "..." --jobs 4 --lines 40-90 --json report.json
```
Mutates lines `40`-`90` only, 4 workers, full report written to `report.json`.

`--command` placeholders:

| Placeholder | Becomes |
|---|---|
| `{godot}` | the Godot executable, quoted |
| `{tests}` | selected test paths joined by `,` |
| `{tests:FLAG}` | `FLAG path` once per selected test, for runners that repeat a flag |

The command runs with the project copy as its working directory, so use `--path .`.

## Configuration

| Key | Type | Default | Effect |
|---|---|---|---|
| `target` | path | required | `.gd` file to mutate: a file path or a `res://` path |
| `--command` | string | required for `run` | test command template |
| `--project` | path | nearest `project.godot` above the target | Godot project directory |
| `--godot` | path | `$GODOT`, then `godot` | Godot executable |
| `--tests` | csv | auto-select | `res://` test paths to run; disables auto-select |
| `--skip-tests` | csv | none | drop auto-selected tests whose path contains any entry |
| `--test-dirs` | csv | `test,tests` | directories searched recursively for tests |
| `--test-patterns` | csv | `test_*.gd,*_test.gd,*Test.gd` | test file name globs |
| `--jobs` | int | `1` | parallel workers; each makes its own project copy |
| `--timeout` | float | `3 x baseline + 10` s | seconds per mutant run; a timeout is re-run once before it counts |
| `--lines` | `A-B` | all | mutate lines `A` to `B` only |
| `--exclude` | name, repeatable | none | directory or file name left out of the copy; `.git` is always left out |
| `--workdir` | path | temp dir, deleted after the run | keep project copies here; later runs copy only files whose size or mtime changed. Must be outside the project |
| `--keep-copies` | flag | off | keep the temp project copies; ignored with `--workdir` |
| `--json` | path | none | write the full report as JSON |
| `--dry-run` | flag | off | list mutants only |

`selfcheck` reads `--godot` and `--jobs`.

## Tests
See `docs/TESTING.md`.

## Mutators
See `docs/MUTATORS.md`.

## How it works
1. `cli.cmd_run` resolves the project root and target, then `mutants.generate` builds the mutant list.
2. `project.find_covering_tests` picks test files that name the target's `class_name` or `res://` path.
3. `project.copy_project` copies the project, `.godot/` import cache included, once per job; with `--workdir`, `project.sync_project` updates a kept copy instead.
4. `engine.run_session` runs the unmutated baseline; a failing baseline stops the run with exit `2`.
5. For each mutant, `engine.run_session` writes the mutated line into a copy, runs the command, and writes the original back.
6. `runner.classify` reads the exit code and Godot's output: `Parse Error:` is `invalid`, a non-zero exit or a new `SCRIPT ERROR` is `killed`, exit `0` is `survived`.
7. `cli._print_report` prints survivors as `res://path:Lline:col group before -> after` and the kill score.

## License
MIT. See `LICENSE`.
