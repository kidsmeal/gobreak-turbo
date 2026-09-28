import subprocess
import tempfile
import unittest
from pathlib import Path

from gobreak import project as proj


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "game"
        (self.root / "src").mkdir(parents=True)
        (self.root / "tests" / "unit").mkdir(parents=True)
        (self.root / ".git").mkdir()
        (self.root / "project.godot").write_text("config_version=5\n")
        self.target = self.root / "src" / "health.gd"
        self.target.write_text("class_name Health\nextends RefCounted\n")

    def tearDown(self):
        self._tmp.cleanup()

    def write_test(self, rel, text):
        path = self.root / rel
        path.write_text(text)
        return path

    def test_find_project_root_walks_up(self):
        self.assertEqual(proj.find_project_root(self.target), self.root.resolve())

    def test_res_path_round_trip(self):
        res = proj.to_res(self.root, self.target)
        self.assertEqual(res, "res://src/health.gd")
        self.assertEqual(proj.from_res(self.root, res), self.root / "src/health.gd")

    def test_covering_tests_match_class_name_or_res_path(self):
        self.write_test("tests/test_by_class.gd", "var h := Health.new()")
        self.write_test("tests/unit/test_by_path.gd", 'const H = preload("res://src/health.gd")')
        self.write_test("tests/test_unrelated.gd", "var h := HealthBar.new()")
        self.write_test("tests/helper.gd", "var h := Health.new()")
        found = proj.find_covering_tests(self.root, self.target)
        self.assertEqual(found, ["res://tests/test_by_class.gd", "res://tests/unit/test_by_path.gd"])

    def test_copy_skips_git_and_excludes(self):
        (self.root / "big").mkdir()
        copy = proj.copy_project(self.root, ["big"])
        try:
            self.assertTrue((copy / "project.godot").is_file())
            self.assertFalse((copy / ".git").exists())
            self.assertFalse((copy / "big").exists())
        finally:
            proj.remove_tree(copy.parent)
        self.assertFalse(copy.parent.exists())

    def test_sync_copies_only_changed_files_and_removes_stale_ones(self):
        dest = Path(self._tmp.name) / "work" / "game"
        self.assertGreater(proj.sync_project(self.root, dest, []), 0)
        self.assertFalse((dest / ".git").exists())
        self.assertEqual(proj.sync_project(self.root, dest, []), 0)

        self.target.write_text("class_name Health\nextends Node\n")
        (dest / "stale.gd").write_text("")
        (dest / "stale_dir").mkdir()
        self.assertEqual(proj.sync_project(self.root, dest, []), 1)
        self.assertEqual((dest / "src/health.gd").read_text(), "class_name Health\nextends Node\n")
        self.assertFalse((dest / "stale.gd").exists())
        self.assertFalse((dest / "stale_dir").exists())


class ChangedLinesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "project.godot").write_text("config_version=5\n")
        self.target = self.root / "grid.gd"
        self.target.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false", *args],
            cwd=self.root, check=True, capture_output=True,
        )

    def test_edited_and_added_lines_are_reported(self):
        self.target.write_text("a = 1\nb = 20\nc = 3\nd = 4\ne = 5\n")
        self.assertEqual(proj.changed_lines(self.root, self.target, "HEAD"), {2, 5})

    def test_committed_changes_count_against_an_older_ref(self):
        self.target.write_text("a = 10\nb = 2\nc = 3\nd = 4\n")
        self.git("commit", "-q", "-am", "edit")
        self.assertEqual(proj.changed_lines(self.root, self.target, "HEAD~1"), {1})
        self.assertEqual(proj.changed_lines(self.root, self.target, "HEAD"), set())

    def test_pure_deletion_changes_no_current_line(self):
        self.target.write_text("a = 1\nc = 3\nd = 4\n")
        self.assertEqual(proj.changed_lines(self.root, self.target, "HEAD"), set())

    def test_untracked_file_means_every_line(self):
        other = self.root / "new.gd"
        other.write_text("x = 1\n")
        self.assertIsNone(proj.changed_lines(self.root, other, "HEAD"))

    def test_bad_ref_raises(self):
        with self.assertRaises(ValueError):
            proj.changed_lines(self.root, self.target, "no-such-ref")


if __name__ == "__main__":
    unittest.main()
