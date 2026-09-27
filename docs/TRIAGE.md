# Triage

A survivor is a mutant that no test failed on. Triage sorts every survivor into one status so the report says what to do with it. It runs by default; `--no-triage` turns it off.

| Status | Rule | Action |
|---|---|---|
| `dead` | the line never ran during the tests, and its function has no reference in non-test code | delete the code |
| `unreached` | the line never ran, and non-test code references its function (or it is an engine callback) | add a test that runs it |
| `reached` | the line ran during the tests and no test failed | rule it: `equivalent` or `gap` |
| `ruled-gap` | a ruling records it as a missing test | write the test |
| `ruled-equivalent` | a ruling records it as no behavior change | none |

`gobreak run` exits `1` while any survivor is not `ruled-equivalent`.

## Line coverage
- After the mutant runs, `gobreak` runs the tests once more with a marker before every unruled survivor line.
- The marker prints `__GB_HIT_<line>__` once per process (`Engine.set_meta` guard), so hot loops add one line of output.
- Lines that cannot take a marker count as `reached`: class-level lines (they run at load), `elif` / `else` lines, `match` patterns, continuation lines of a multi-line statement.
- If the coverage run fails or times out, every unruled survivor is `reached` and the report prints a `note:` line.

## References
- A function is referenced when its name appears as a whole word in a `.gd`, `.tscn` or `.tres` file.
- Not counted: the function's own body (recursion), comments in `.gd` files, files matching `--test-patterns`, dot-directories such as `.godot/`.
- Counted: string mentions such as `call("name")`, `connect("s", ...)` and scene `[connection ... method="name"]` entries. A string mention in unrelated code can turn a `dead` line into `unreached`; it never turns a used function into `dead`.
- Engine callbacks (`_ready`, `_process`, `_init` and the rest in `triage.ENGINE_CALLBACKS`) are never `dead`.

## Rulings
Rulings live in `.gobreak/rulings.json` in the Godot project. Commit the file so every run and every machine sorts the same survivors the same way.

```bash
gobreak run src/grid.gd --dry-run
```
Lists mutant ids. Ids come from the current file contents.

```bash
gobreak rule src/grid.gd 42 equivalent --reason "hash constant: any odd multiplier gives the same query results"
```
Records mutant `#42` as equivalent.

```bash
gobreak rule src/grid.gd 17 gap --reason "no test puts a row exactly on the radius"
```
Records mutant `#17` as a known missing test.

```bash
gobreak rule src/grid.gd --clear-stale
```
Removes rulings for this file whose mutant no longer exists.

- A ruling is keyed by `res://` path, the original line text and the mutated line text. Lines inserted or removed above it do not break the match.
- A ruling whose mutant is now killed, or whose line text changed, is listed under `stale rulings`.
