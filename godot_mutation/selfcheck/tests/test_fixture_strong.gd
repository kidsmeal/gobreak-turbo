extends "res://tests/fixture_suite.gd"

## Exact-value checks, including each comparison's boundary. Every mutant
## of fixture_math.gd changes at least one of these results.

const FixtureMath = preload("res://fixture_math.gd")


func test_over_cap() -> void:
	check(FixtureMath.over_cap(8, 6, 10) == true, "8 + 6 is over 10")
	check(FixtureMath.over_cap(4, 6, 10) == false, "4 + 6 is not over 10")


func test_label() -> void:
	check(FixtureMath.label(5) == "positive", "5 is positive")
	check(FixtureMath.label(1) == "positive", "1 is positive")
	check(FixtureMath.label(0) == "not positive", "0 is not positive")


func test_both_positive() -> void:
	check(FixtureMath.both_positive(1, 1) == true, "1 and 1 are positive")
	check(FixtureMath.both_positive(0, 1) == false, "0 is not positive")
	check(FixtureMath.both_positive(1, 0) == false, "0 is not positive")


func test_scaled() -> void:
	var result: Array[int] = FixtureMath.scaled([2, 3], 4)
	check(result.size() == 2, "two values in, two out")
	if result.size() == 2:
		check(result[0] == 8 and result[1] == 12, "2 and 3 scaled by 4")
