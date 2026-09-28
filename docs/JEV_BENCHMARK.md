# Jev benchmark

Tested whether TypeSafe's Jev classifier (`jev-latest`, `POST https://api.typesafe.ai/v1/systemone`) can sort `reached` survivors into equivalent and gap. Result: rejected. At every threshold that saves real work, it marks real gaps as equivalent. The `gobreak suggest` command built for the test was deleted; this file is the record.

Date: 2026-09-27. Project: Capsule Castle (Godot `4.6.2`). Cost of the whole benchmark: about `100k` input tokens, about `$0.004`.

## Method
- State: the whole target file, line-numbered, plus `res://` path and language.
- Questions: yes/no (`noul`) only. TypeSafe's docs state `noul` answers are bit-identical for identical input; choice answers carry sampling noise.
- Round 1: one question per survivor, "does this change something a caller can observe".
- Round 2: four narrow questions per survivor; a survivor is "likely equivalent" when any answer reaches the threshold:
  - `perf`: only changes speed, memory or internal distribution.
  - `log`: only changes log text.
  - `overwritten`: the value is always overwritten before it is read.
  - `filtered`: a later check in the file discards the difference.
- Answer key: a line-by-line read of each file. Not verified by tests for every survivor.

## Results

### `systems/sim/swarm_grid.gd`, 28 `reached` survivors (5 real gaps)
| Round | Threshold | Correct equivalent hints | Real gaps hinted equivalent |
|---|---|---|---|
| 1 | `0.5` | 8 | 0 |
| 1 | gap answers | 6 of 20 correct | n/a |
| 2 | `0.4` | 14 | 0 |
| 2 | `0.4`, file re-asked after an unrelated edit | 13 | 1 (`#91`, `0.25` -> `0.48`) |

### `systems/sim/combat_transaction.gd`, 52 `reached` survivors (held out; threshold `0.4` from round 2)
| Threshold | Correct equivalent hints | Real gaps hinted equivalent |
|---|---|---|
| `0.4` | 10 | 5 |
| `0.5` | 5 | 1 |
| `0.6` | 4 | 0 |

Real gaps hinted equivalent at `0.4`:
- `if reduction != 0.0:` -> `!= 1.0` (`0.52`): a 1-point reduction is skipped.
- `if exposed_points > 0.0:` -> `> 1.0` (`0.47`): an exposure of exactly 1 point is dropped.
- `var knockback_strength_val: float = 0.0` -> `1.0` (`0.42`): a source without `knockback_strength` applies knockback.
- deleting `_event_data[3] = ...` (`0.41`): the `DAMAGE_DEALT` event keeps the previous hit's crit flag.
- `CRIT_FLAG) > 0.5` -> `> 1.5` (`0.41`): the event never flags a crit.

## Why it was rejected
- A wrong "equivalent" hides a real test gap, the failure mutation testing exists to catch.
- The only threshold with zero wrong hints (`0.6`) caught 4 trivial cases: static initial values overwritten before use.
- Answers moved across the threshold when an unrelated part of the file changed.
- Gap answers were wrong 14 times in 20 on the first file.

## Re-test conditions
Re-run this benchmark before adopting any classifier: same two files, same answer key, zero real gaps hinted equivalent, and at least half the equivalent survivors hinted.
