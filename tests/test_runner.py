import os
import sys
import unittest

from gobreak import runner


def result(exit_code=0, output="", timed_out=False):
    return runner.RunResult(exit_code, output, 1.0, timed_out)


CLEAN = runner.Baseline(1.0, has_script_error=False, has_parse_error=False)


class BuildCommandTest(unittest.TestCase):
    def test_tests_placeholder_joins_with_commas(self):
        cmd = runner.build_command("{godot} -- --tests {tests}", "godot", ["res://a.gd", "res://b.gd"])
        self.assertEqual(cmd, "godot -- --tests res://a.gd,res://b.gd")

    def test_tests_flag_placeholder_repeats_the_flag(self):
        cmd = runner.build_command("{godot} {tests:-a}", "godot", ["res://a.gd", "res://b.gd"])
        self.assertEqual(cmd, "godot -a res://a.gd -a res://b.gd")

    def test_godot_path_with_spaces_is_quoted(self):
        cmd = runner.build_command("{godot} --headless", "C:/Program Files/godot.exe", [])
        self.assertTrue(cmd.startswith(("\"C:/Program Files/godot.exe\"", "'C:/Program Files/godot.exe'")))

    def test_uses_tests(self):
        self.assertTrue(runner.uses_tests("x {tests}"))
        self.assertTrue(runner.uses_tests("x {tests:-a}"))
        self.assertFalse(runner.uses_tests("x {godot}"))


class ClassifyTest(unittest.TestCase):
    def test_non_zero_exit_is_killed(self):
        self.assertEqual(runner.classify(result(1), CLEAN), runner.KILLED)

    def test_zero_exit_is_survived(self):
        self.assertEqual(runner.classify(result(0), CLEAN), runner.SURVIVED)

    def test_parse_error_is_invalid_even_with_non_zero_exit(self):
        out = 'SCRIPT ERROR: Parse Error: Invalid operands "int" and "String" for "+" operator.'
        self.assertEqual(runner.classify(result(1, out), CLEAN), runner.INVALID)

    def test_runtime_error_with_zero_exit_is_killed(self):
        out = "SCRIPT ERROR: Invalid access to property or key 'missing'"
        self.assertEqual(runner.classify(result(0, out), CLEAN), runner.KILLED)

    def test_runtime_error_already_in_baseline_is_not_a_signal(self):
        noisy = runner.Baseline(1.0, has_script_error=True, has_parse_error=False)
        self.assertEqual(runner.classify(result(0, "SCRIPT ERROR: x"), noisy), runner.SURVIVED)

    def test_timeout(self):
        self.assertEqual(runner.classify(result(None, "", True), CLEAN), runner.TIMEOUT)


class RunCommandTest(unittest.TestCase):
    def test_exit_code_and_output_are_captured(self):
        py = runner._quote(sys.executable)
        res = runner.run_command(f"{py} -c \"print('hi'); raise SystemExit(3)\"", os.getcwd(), 30)
        self.assertEqual(res.exit_code, 3)
        self.assertIn("hi", res.output)
        self.assertFalse(res.timed_out)

    def test_timeout_kills_the_process(self):
        py = runner._quote(sys.executable)
        res = runner.run_command(f"{py} -c \"import time; time.sleep(30)\"", os.getcwd(), 1)
        self.assertTrue(res.timed_out)
        self.assertLess(res.seconds, 15)


if __name__ == "__main__":
    unittest.main()
