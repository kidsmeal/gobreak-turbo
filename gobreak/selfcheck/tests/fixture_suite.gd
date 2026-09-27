extends RefCounted

## Base for the self-check test files. run_tests.gd reads `checks` and
## `failures` after each test method.

var checks: int = 0
var failures: int = 0


func check(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failures += 1
		printerr("check failed: %s" % message)
