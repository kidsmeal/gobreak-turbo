import argparse
import json
import tempfile
import unittest
from pathlib import Path

from gobreak import cli
from gobreak import config as cfg
from gobreak import engine


def run_args(**overrides):
    base = dict(
        command=None, godot=None, tests=None, skip_tests=None, test_dirs=None, test_patterns=None,
        jobs=None, timeout=None, exclude=None, workdir=None, no_triage=False, no_coverage_selection=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "game"
        (self.root / ".gobreak").mkdir(parents=True)
        (self.root / "project.godot").write_text("config_version=5\n")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, data):
        (self.root / cfg.CONFIG_PATH).write_text(json.dumps(data))

    def test_missing_file_is_empty(self):
        (self.root / ".gobreak").rmdir()
        self.assertEqual(cfg.load(self.root), {})

    def test_config_fills_unset_options_and_flags_win(self):
        self.write({"command": "godot {tests}", "jobs": 4, "skip_tests": ["perf"], "triage": False})
        args = run_args(jobs=2)
        cli._apply_config(args, self.root)
        self.assertEqual(args.command, "godot {tests}")
        self.assertEqual(args.jobs, 2)
        self.assertEqual(args.skip_tests, ["perf"])
        self.assertTrue(args.no_triage)
        self.assertEqual(args.exclude, [])

    def test_relative_workdir_resolves_against_the_project(self):
        self.write({"workdir": "../work"})
        self.assertEqual(Path(cfg.load(self.root)["workdir"]), (self.root / "../work").resolve())

    def test_unknown_key_and_wrong_type_are_rejected(self):
        self.write({"comand": "x"})
        with self.assertRaises(cfg.ConfigError):
            cfg.load(self.root)
        self.write({"jobs": "4"})
        with self.assertRaises(cfg.ConfigError):
            cfg.load(self.root)
        self.write({"jobs": True})
        with self.assertRaises(cfg.ConfigError):
            cfg.load(self.root)
        self.write({"skip_tests": [1]})
        with self.assertRaises(cfg.ConfigError):
            cfg.load(self.root)

    def test_bad_config_surfaces_as_a_session_error(self):
        (self.root / cfg.CONFIG_PATH).write_text("{not json")
        with self.assertRaises(engine.SessionError):
            cli._apply_config(run_args(), self.root)


class CollectTargetsTest(unittest.TestCase):
    def test_directory_run_skips_tests_addons_and_dot_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("src/a.gd", "src/deep/b.gd", "src/test_c.gd", "tests/test_a.gd",
                        "tests/helpers/h.gd", "addons/gut/x.gd", ".godot/y.gd", "src/readme.md"):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x = 1\n")
            found = cli._collect_targets(root, root, None, None)
            self.assertEqual([p.relative_to(root).as_posix() for p in found], ["src/a.gd", "src/deep/b.gd"])


class CoverageMapTest(unittest.TestCase):
    def test_tests_for_line_uses_hits_plus_unmapped(self):
        cov = engine._Coverage(
            marked={3, 4, 5},
            hits={"res://t/a.gd": {3, 4}, "res://t/b.gd": {4}},
            unmapped=["res://t/c.gd"],
        )
        self.assertEqual(cov.tests_for_line(3), ["res://t/a.gd", "res://t/c.gd"])
        self.assertEqual(cov.tests_for_line(4), ["res://t/a.gd", "res://t/b.gd", "res://t/c.gd"])
        self.assertEqual(cov.tests_for_line(5), ["res://t/c.gd"])

    def test_line_no_test_reaches(self):
        cov = engine._Coverage(marked={7}, hits={"res://t/a.gd": set()}, unmapped=[])
        self.assertEqual(cov.tests_for_line(7), [])
        self.assertFalse(cov.reached(7))


if __name__ == "__main__":
    unittest.main()
