extends GdUnitTestSuite

## Exact-value checks, including each comparison's boundary. GoBreak Turbo
## should kill every mutant these tests reach and report unused_double as
## dead and only_called_by_caller as unreached.

const FixtureMath = preload("res://fixture_math.gd")


func test_over_cap() -> void:
	assert_bool(FixtureMath.over_cap(8, 6, 10)).is_true()
	assert_bool(FixtureMath.over_cap(4, 6, 10)).is_false()


func test_label() -> void:
	assert_str(FixtureMath.label(5)).is_equal("positive")
	assert_str(FixtureMath.label(1)).is_equal("positive")
	assert_str(FixtureMath.label(0)).is_equal("not positive")


func test_both_positive() -> void:
	assert_bool(FixtureMath.both_positive(1, 1)).is_true()
	assert_bool(FixtureMath.both_positive(0, 1)).is_false()
	assert_bool(FixtureMath.both_positive(1, 0)).is_false()


func test_scaled() -> void:
	assert_array(FixtureMath.scaled([2, 3], 4)).is_equal([8, 12])
