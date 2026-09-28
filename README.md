# GoBreak Turbo

Mutation testing CLI for Godot 4 projects. It changes one line of GDScript at a time, reruns your tests, and lists the changes no test caught.

## What it does
- Generates single-line mutants: comparison, arithmetic, logic, `not`, bool, number, `if` negation, statement deletion. Full list in `docs/MUTATORS.md`.
- Runs each mutant in a copy of the project; your working tree is never written.
- Maps which test file reaches which line, then runs only those tests per mutant.
- Mutates a file, a whole directory, or only the lines changed since a git ref.
- Counts a GDScript runtime error (`SCRIPT ERROR`) as killed even when the test command exits `0`.
- Sorts survivors as `dead`, `unreached`, `reached` or ruled, and records rulings in `.gobreak/rulings.json`. Details in `docs/TRIAGE.md`.
- Works with any test command that exits non-zero on failure.
- Proves itself with `selfcheck` on a bundled fixture of strong and hollow tests.

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
Exits `0` when the tool tells the bundled strong tests from the hollow ones.

```bash
gobreak run src/health.gd
```
Mutates `src/health.gd` with the command from `.gobreak/config.json`. Exit `0`: no open survivors. Exit `1`: survivors listed by status. Exit `2`: error or failing baseline.

```bash
gobreak run src/ --changed-since main
```
Mutates the lines changed since `main` in every non-test `.gd` file under `src/`, then prints a per-file summary.

```bash
gobreak rule src/health.gd 42 equivalent --reason "clamp bound is re-applied by the caller"
```
Records mutant `#42` as equivalent; later runs list it under `ruled equivalent`.

## Configuration
See `docs/CONFIGURATION.md` for the config file, every flag, and the `{tests}` placeholders.

## Tests
See `docs/TESTING.md`.

## Mutators
See `docs/MUTATORS.md`.

## Triage
See `docs/TRIAGE.md`.

## How it works
1. `cli.cmd_run` merges `.gobreak/config.json` with flags and collects targets; `mutants.generate` builds each file's mutants.
2. `project.find_covering_tests` picks test files that name the target's `class_name` or `res://` path.
3. `engine.Workspace` copies the project once per job, or syncs kept copies with `--workdir`.
4. `engine.run_session` runs the unmutated baseline; a failing baseline stops that file with exit `2`.
5. `engine._build_coverage` runs each test file alone against a copy with `triage.instrument` markers, recording which lines it reaches.
6. Each mutant runs only the tests that reach its line; a line no test reaches is a survivor without a run.
7. `runner.classify` reads the exit code and output: `Parse Error:` is `invalid`, a non-zero exit or a new `SCRIPT ERROR` is `killed`, exit `0` is `survived`.
8. `engine._triage` applies rulings and sorts survivors with the coverage map and `triage.count_references`.

## License
MIT. See `LICENSE`.
