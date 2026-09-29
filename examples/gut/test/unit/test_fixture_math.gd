extends GutTest

## Exact-value checks, including each comparison's boundary. GoBreak Turbo
## should kill every mutant these tests reach and report unused_double as
## dead and only_called_by_caller as unreached.

const FixtureMath = preload("res://fixture_math.gd")


func test_over_cap() -> void:
	assert_true(FixtureMath.over_cap(8, 6, 10), "8 + 6 is over 10")
	assert_false(FixtureMath.over_cap(4, 6, 10), "4 + 6 is not over 10")


func test_label() -> void:
	assert_eq(FixtureMath.label(5), "positive")
	assert_eq(FixtureMath.label(1), "positive")
	assert_eq(FixtureMath.label(0), "not positive")


func test_both_positive() -> void:
	assert_true(FixtureMath.both_positive(1, 1))
	assert_false(FixtureMath.both_positive(0, 1))
	assert_false(FixtureMath.both_positive(1, 0))


func test_scaled() -> void:
	var result: Array[int] = FixtureMath.scaled([2, 3], 4)
	assert_eq(result.size(), 2, "two values in, two out")
	if result.size() == 2:
		assert_eq(result[0], 8)
		assert_eq(result[1], 12)
