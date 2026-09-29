# Testing

## Unit tests
```bash
python -m unittest discover -s tests -t .
```
Stdlib only, no Godot needed; `git` is needed for the `--changed-since` cases. Covers masking, every mutator, line skip rules, command templates, result classification, process timeout, test selection, project copies, changed-line detection, the config file, directory target collection and the coverage map.

## Self-check
```bash
python -m gobreak selfcheck
```
Needs Godot `4.x` (`--godot`, `$GODOT` or `godot` on `PATH`). Runs `gobreak/selfcheck/fixture_math.gd` against two test files:
- `tests/test_fixture_strong.gd` must kill every reached mutant. Triage must report `unused_double` as `dead` and `only_called_by_caller` as `unreached` (referenced only by `fixture_caller.gd`).
- `tests/test_fixture_hollow.gd` must kill none and leave `reached` survivors.

Exit `0` means the tool can tell a test that checks results from one that only runs the code. Exit `2` names which half failed.

## Framework examples
`examples/gut/` (GUT `v9.6.1`) and `examples/gdunit4/` (gdUnit4 `v6.2.1`) hold the same fixture with each framework's tests and a `.gobreak/config.json` carrying that framework's command. The addons are not committed.
```bash
python examples/fetch_addons.py
```
```bash
godot --headless --path examples/gut --import
```
```bash
gobreak run examples/gut/fixture_math.gd
```
Repeat the last two for `examples/gdunit4`. Expected on both, verified on Godot `4.6.2`: 16 mutants, 12 killed, triage `dead 2` (`unused_double`), `unreached 2` (`only_called_by_caller`), `reached 0`, exit `1`.

## Godot output strings the classifier depends on
Verified on Godot `4.6.2`:
- A mutant that does not compile prints `SCRIPT ERROR: Parse Error: ...` and is classed `invalid`.
- A runtime error prints `SCRIPT ERROR: ...` while the process can still exit `0`; the mutant is classed `killed`.
