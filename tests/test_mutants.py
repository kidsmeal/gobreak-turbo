import unittest

from gobreak import mutants as mut


def after_lines(source: str) -> list[str]:
    """Mutated lines, statement deletions left out."""
    return [m.after for m in mut.generate(source) if m.group != mut.DEL]


def groups(source: str) -> list[str]:
    """Mutant groups, statement deletions left out."""
    return [m.group for m in mut.generate(source) if m.group != mut.DEL]


def all_groups(source: str) -> list[str]:
    return [m.group for m in mut.generate(source)]


class MaskTest(unittest.TestCase):
    def test_string_contents_are_blanked_and_quotes_kept(self):
        masked, _, _ = mut.mask('var s = "a > b"')
        self.assertEqual(masked, 'var s = "     "')

    def test_comment_is_blanked_and_its_column_recorded(self):
        masked, _, comments = mut.mask("x = 1 # a > b")
        self.assertEqual(masked, "x = 1        ")
        self.assertEqual(comments, {0: 6})

    def test_escaped_quote_does_not_end_the_string(self):
        masked, _, _ = mut.mask('var s = "a\\" > b" + c')
        self.assertTrue(masked.endswith('" + c'))
        self.assertNotIn(">", masked)

    def test_triple_quoted_string_marks_every_line_it_spans(self):
        masked, multiline, _ = mut.mask('var s = """one\ntwo > 1\nthree"""\nx = 2')
        self.assertEqual(multiline, {0, 1, 2})
        self.assertNotIn(">", masked)

    def test_offsets_and_line_count_are_unchanged(self):
        src = 'a = "x"  # c\r\nb = """\nq\n"""\n'
        masked, _, _ = mut.mask(src)
        self.assertEqual(len(masked), len(src))
        self.assertEqual(masked.count("\n"), src.count("\n"))


class OperatorTest(unittest.TestCase):
    def test_comparisons_swap_to_their_boundary_partner(self):
        self.assertEqual(
            after_lines("x = a < b"), ["x = a <= b"]
        )
        self.assertIn("x = a != b", after_lines("x = a == b"))
        self.assertIn("x = a > b", after_lines("x = a >= b"))

    def test_binary_arithmetic_swaps(self):
        self.assertIn("x = a - b", after_lines("x = a + b"))
        self.assertIn("x = a * b", after_lines("x = a / b"))
        self.assertIn("x -= 2", after_lines("x += 2"))

    def test_unary_minus_is_not_an_arithmetic_mutant(self):
        self.assertNotIn("arith", groups("x = -a"))

    def test_string_operand_counts_as_binary(self):
        self.assertIn('x = "a" - b', after_lines('x = "a" + b'))

    def test_power_shift_and_arrow_are_left_alone(self):
        self.assertEqual(groups("x = a ** b"), [])
        self.assertEqual(groups("x = a << b"), [])

    def test_logic_words_and_symbols_swap(self):
        self.assertIn("x = a or b", after_lines("x = a and b"))
        self.assertIn("x = a || b", after_lines("x = a && b"))

    def test_not_is_removed(self):
        self.assertIn("x = a", after_lines("x = not a"))
        self.assertIn("x = a", after_lines("x = !a"))
        self.assertIn("x = a in b", after_lines("x = a not in b"))

    def test_bool_literals_flip(self):
        self.assertEqual(after_lines("x = true"), ["x = false"])

    def test_numbers_bump_by_one(self):
        self.assertEqual(after_lines("x = 7"), ["x = 8"])
        self.assertEqual(after_lines("x = 0.5"), ["x = 1.5"])
        self.assertEqual(after_lines("x = 1_000"), ["x = 1001"])

    def test_numbers_inside_names_hex_and_exponents_are_skipped(self):
        self.assertEqual(groups("p1.v2 = Vector2i.ZERO"), [])
        self.assertNotIn("num", groups("x = 0xFF"))
        self.assertNotIn("num", groups("x = 1e5"))

    def test_text_inside_strings_and_comments_is_never_mutated(self):
        self.assertEqual(groups('print("a > 1 and true")  # b < 2'), [])


class LineRuleTest(unittest.TestCase):
    def test_declaration_lines_are_skipped(self):
        src = "func f(a: int = 1) -> int:\n\treturn a\n"
        self.assertEqual(all_groups(src), [])
        self.assertEqual(all_groups("@export var speed := 5.0"), [])
        self.assertEqual(all_groups("enum State { A = 1 }"), [])
        self.assertEqual(all_groups("signal hit(amount: int)"), [])

    def test_multiline_signature_continuation_is_skipped(self):
        src = "func f(\n\ta: int = 1,\n\tb: int = 2\n) -> void:\n\tx = 3\n"
        self.assertEqual([m.line for m in mut.generate(src)], [5, 5])

    def test_if_condition_is_negated_on_single_line_ifs(self):
        src = "if a > b:\n\tpass\n"
        self.assertIn("if not (a > b):", after_lines(src))

    def test_inline_if_body_is_not_negated(self):
        self.assertNotIn("if", groups("if a: return b"))

    def test_statement_deletion_replaces_with_pass(self):
        src = "func f():\n\tcount += 1\n"
        dels = [m for m in mut.generate(src) if m.group == "del"]
        self.assertEqual(len(dels), 1)
        self.assertEqual(dels[0].new_line, "\tpass")

    def test_deletion_skips_returns_vars_blocks_and_multiline_statements(self):
        src = (
            "func f():\n"
            "\treturn 1\n"
            "\tvar a = 2\n"
            "\tfor i in 3:\n"
            "\t\tpass\n"
            "\tcall(\n"
            "\t\t4)\n"
        )
        self.assertNotIn("del", all_groups(src))

    def test_logging_only_lines_get_no_mutants(self):
        src = (
            "func f(a):\n"
            '\tpush_error("grew from %d to %d" % [a, a + 1])\n'
            '\tprint("x", a * 2)\n'
            "\tvar y = a + 1\n"
        )
        self.assertEqual({m.line for m in mut.generate(src)}, {4})

    def test_logging_call_inside_a_larger_statement_is_still_mutated(self):
        self.assertIn("arith", all_groups('x = a + 1; print("x")'))
        self.assertIn("arith", all_groups('print("x"); y = a + 1'))

    def test_ignore_tag_skips_every_group(self):
        self.assertEqual(all_groups("x = a + 1  # mutation: ignore"), [])

    def test_ignore_tag_with_groups_skips_only_those(self):
        self.assertEqual(all_groups("x = a + 1  # mutation: ignore=num,del"), ["arith"])


class ApplyTest(unittest.TestCase):
    def test_apply_replaces_one_line_and_keeps_crlf(self):
        src = "a = 1\r\nb = 2\r\n"
        m = [m for m in mut.generate(src) if m.line == 2 and m.group == "num"][0]
        self.assertEqual(mut.apply(src, m), "a = 1\r\nb = 3\r\n")

    def test_mutant_indexes_are_sequential(self):
        found = mut.generate("x = a + 1\ny = b < 2\n")
        self.assertEqual([m.index for m in found], list(range(1, len(found) + 1)))


if __name__ == "__main__":
    unittest.main()
