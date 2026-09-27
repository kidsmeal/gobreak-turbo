# Testing

## Unit tests
```bash
python -m unittest discover -s tests -t .
```
Stdlib only, no Godot needed. Covers masking, every mutator, line skip rules, command templates, result classification, process timeout, test selection and project copies.

## Self-check
```bash
python -m gobreak selfcheck
```
Needs Godot `4.x` (`--godot`, `$GODOT` or `godot` on `PATH`). Runs `gobreak/selfcheck/fixture_math.gd` against two test files:
- `tests/test_fixture_strong.gd` must kill every reached mutant. Triage must report `unused_double` as `dead` and `only_called_by_caller` as `unreached` (referenced only by `fixture_caller.gd`).
- `tests/test_fixture_hollow.gd` must kill none and leave `reached` survivors.

Exit `0` means the tool can tell a test that checks results from one that only runs the code. Exit `2` names which half failed.

## Godot output strings the classifier depends on
Verified on Godot `4.6.2`:
- A mutant that does not compile prints `SCRIPT ERROR: Parse Error: ...` and is classed `invalid`.
- A runtime error prints `SCRIPT ERROR: ...` while the process can still exit `0`; the mutant is classed `killed`.
