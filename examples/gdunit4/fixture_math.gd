extends RefCounted

## Self-check target. tests/test_fixture_strong.gd kills every mutant the
## tests reach; tests/test_fixture_hollow.gd kills none. Triage must report
## unused_double as dead (no reference) and only_called_by_caller as
## unreached (referenced by fixture_caller.gd, never run by a test).


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


static func unused_double(n: int) -> int:
	return n * 2


static func only_called_by_caller(n: int) -> int:
	return n + 1
