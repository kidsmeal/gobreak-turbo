extends RefCounted

## Non-test code that references FixtureMath.only_called_by_caller. No test
## loads this file, so the function is referenced but never run.

const FixtureMath = preload("res://fixture_math.gd")


static func run() -> int:
	return FixtureMath.only_called_by_caller(1)
