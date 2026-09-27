import tempfile
import unittest
from pathlib import Path

from gobreak import cli
from gobreak import mutants as mut
from gobreak import triage

SOURCE = """extends RefCounted

const LIMIT = 3


static func pick(n: int) -> int:
\tif n > LIMIT:
\t\treturn 1
\telif n == 0:
\t\treturn 2
\telse:
\t\treturn 3


func route(kind: int) -> int:
\tmatch kind:
\t\t1:
\t\t\treturn kind + 1
\t\t_:
\t\t\treturn 0


func call_many(a: int,
\t\tb: int) -> int:
\tvar total := foo(a,
\t\tb)
\treturn total


class Inner:
\tfunc twice(n: int) -> int:
\t\treturn n * 2
"""


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.infos = triage.analyze(SOURCE)

    def info(self, line):
        return self.infos[line - 1]

    def test_class_level_lines_are_not_markable(self):
        self.assertFalse(self.info(3).markable)
        self.assertIsNone(self.info(3).func)

    def test_function_body_lines_are_markable_and_know_their_function(self):
        self.assertTrue(self.info(7).markable)
        self.assertEqual(self.info(7).func, "pick")
        self.assertTrue(self.info(8).markable)

    def test_elif_and_else_are_not_markable(self):
        self.assertFalse(self.info(9).markable)
        self.assertFalse(self.info(11).markable)

    def test_match_patterns_are_not_markable_but_their_bodies_are(self):
        self.assertFalse(self.info(17).markable)
        self.assertTrue(self.info(18).markable)
        self.assertFalse(self.info(19).markable)

    def test_continuation_lines_are_not_markable(self):
        self.assertFalse(self.info(24).markable)
        self.assertTrue(self.info(25).markable)
        self.assertFalse(self.info(26).markable)
        self.assertEqual(self.info(25).func, "call_many")

    def test_inner_class_methods_are_tracked(self):
        self.assertTrue(self.info(32).markable)
        self.assertEqual(self.info(32).func, "twice")


class InstrumentTest(unittest.TestCase):
    def test_marker_goes_before_the_line_with_its_indent(self):
        out, marked = triage.instrument(SOURCE, {8, 9, 3})
        self.assertEqual(marked, {8})
        lines = out.split("\n")
        self.assertIn('print("__GB_HIT_8__")', lines[7])
        self.assertTrue(lines[7].startswith("\t\tif not Engine.has_meta"))
        self.assertEqual(lines[8], "\t\treturn 1")
        self.assertEqual(len(lines), len(SOURCE.split("\n")) + 1)

    def test_crlf_is_kept(self):
        src = "func f():\r\n\tpass\r\n"
        out, marked = triage.instrument(src, {2})
        self.assertEqual(marked, {2})
        self.assertTrue(out.split("\n")[1].endswith("\r"))

    def test_hits_are_parsed_from_output(self):
        self.assertEqual(triage.hits_from_output("x __GB_HIT_8__\n__GB_HIT_12__ y"), {8, 12})


class ReferenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "project.godot").write_text("config_version=5\n")
        self.target = self.root / "grid.gd"
        self.source = (
            "func sort_ids(a):\n"
            "\tsort_ids(a)  # recursion is not a reference\n"
            "\n"
            "func used():\n"
            "\treturn 1\n"
        )
        self.target.write_text(self.source)

    def tearDown(self):
        self._tmp.cleanup()

    def count(self, func):
        return triage.count_references(self.root, self.target, func, self.source, ["test_*.gd"])

    def test_no_reference_outside_own_body(self):
        self.assertEqual(self.count("sort_ids"), 0)

    def test_comment_and_test_file_mentions_do_not_count(self):
        (self.root / "other.gd").write_text("# sort_ids is gone\n")
        (self.root / "tests" / "test_grid.gd").write_text('var names = ["sort_ids"]\n')
        self.assertEqual(self.count("sort_ids"), 0)

    def test_code_string_and_scene_mentions_count(self):
        (self.root / "a.gd").write_text("func x():\n\tGrid.used()\n")
        (self.root / "b.gd").write_text('func y():\n\tcall("used")\n')
        (self.root / "c.tscn").write_text('[connection signal="s" from="." to="." method="used"]\n')
        self.assertEqual(self.count("used"), 3)

    def test_engine_callbacks_are_known(self):
        self.assertTrue(triage.is_engine_callback("_ready"))
        self.assertFalse(triage.is_engine_callback("sort_ids"))


class RulingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "project.godot").write_text("config_version=5\n")
        self.target = self.root / "hash.gd"
        self.target.write_text("func h(x):\n\treturn x * 31\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_load_round_trip(self):
        r = triage.Ruling("res://hash.gd", "return x * 31", "return x * 32", triage.EQUIVALENT, "hash constant")
        triage.save_rulings(self.root, [r])
        self.assertEqual(triage.load_rulings(self.root), [r])

    def test_rule_command_records_by_line_text(self):
        ids = {m.after: m.index for m in mut.generate(self.target.read_text())}
        code = cli.main(["rule", str(self.target), str(ids["return x * 32"]), "equivalent", "--reason", "hash constant"])
        self.assertEqual(code, 0)
        rulings = triage.load_rulings(self.root)
        self.assertEqual(len(rulings), 1)
        self.assertEqual(rulings[0].before, "return x * 31")

        # A line inserted above keeps the ruling matched: it is keyed by text.
        self.target.write_text("# header\nfunc h(x):\n\treturn x * 31\n")
        m = next(m for m in mut.generate(self.target.read_text()) if m.after == "return x * 32")
        self.assertIsNotNone(triage.ruling_for(triage.load_rulings(self.root), "res://hash.gd", m))

    def test_rule_command_needs_a_reason(self):
        self.assertEqual(cli.main(["rule", str(self.target), "1", "gap"]), cli.EXIT_ERROR)

    def test_clear_stale_removes_rulings_whose_line_is_gone(self):
        gone = triage.Ruling("res://hash.gd", "return x * 7", "return x * 8", triage.GAP, "old")
        triage.save_rulings(self.root, [gone])
        self.assertEqual(cli.main(["rule", str(self.target), "--clear-stale"]), 0)
        self.assertEqual(triage.load_rulings(self.root), [])


if __name__ == "__main__":
    unittest.main()
