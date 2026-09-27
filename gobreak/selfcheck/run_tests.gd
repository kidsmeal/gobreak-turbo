extends SceneTree

## Headless runner for the self-check fixture.
## godot --headless --path . -s res://run_tests.gd -- --tests res://tests/a.gd,res://tests/b.gd
## Exits 0 only when every test method ran at least one check and none failed.


func _initialize() -> void:
	var paths := PackedStringArray()
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		if args[i] == "--tests" and i + 1 < args.size():
			paths = args[i + 1].split(",", false)
	if paths.is_empty():
		printerr("no tests given; pass -- --tests res://tests/test_x.gd")
		quit(1)
		return

	var failed := 0
	for path in paths:
		var script: Script = load(path)
		if script == null:
			printerr("failed to load %s" % path)
			failed += 1
			continue
		var suite: Object = script.new()
		for method in script.get_script_method_list():
			var method_name: String = method["name"]
			if not method_name.begins_with("test_"):
				continue
			suite.checks = 0
			suite.failures = 0
			suite.call(method_name)
			if suite.checks == 0:
				printerr("%s::%s ran no checks" % [path, method_name])
				failed += 1
			elif suite.failures > 0:
				printerr("%s::%s failed" % [path, method_name])
				failed += 1
			else:
				print("ok %s::%s" % [path, method_name])
	quit(1 if failed > 0 else 0)
