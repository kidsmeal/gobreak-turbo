extends RefCounted

## Self-check target. tests/test_fixture_strong.gd kills every mutant of
## this file; tests/test_fixture_hollow.gd kills none.


static func over_cap(a: int, b: int, cap: int) -> bool:
	return a + b > cap


static func label(n: int) -> String:
	if n > 0:
		return "positive"
	return "not positive"


static func both_positive(a: int, b: int) -> bool:
	return a > 0 and b > 0


static func scaled(values: Array[int], factor: int) -> Array[int]:
	var out: Array[int] = []
	for v in values:
		out.append(v * factor)
	return out
