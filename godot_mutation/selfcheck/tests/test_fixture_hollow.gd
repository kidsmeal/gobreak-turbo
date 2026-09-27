extends "res://tests/fixture_suite.gd"

## Calls every function and checks only the result's type. These tests
## pass against every mutant of fixture_math.gd, so the self-check expects
## survivors here.

const FixtureMath = preload("res://fixture_math.gd")


func test_over_cap_runs() -> void:
	check(typeof(FixtureMath.over_cap(8, 6, 10)) == TYPE_BOOL, "returns a bool")


func test_label_runs() -> void:
	check(typeof(FixtureMath.label(5)) == TYPE_STRING, "returns a String")


func test_both_positive_runs() -> void:
	check(typeof(FixtureMath.both_positive(1, 1)) == TYPE_BOOL, "returns a bool")


func test_scaled_runs() -> void:
	check(typeof(FixtureMath.scaled([2, 3], 4)) == TYPE_ARRAY, "returns an Array")
