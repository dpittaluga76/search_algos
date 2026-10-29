import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from search_algos.algorithms import binary_search_by_recursion, find_by_sets, linear_search
from search_algos.timing import format_result, profile_this, show_runtime_and_result


class TimingTests(unittest.TestCase):
    def test_wrapper_returns_result_and_supports_keywords(self):
        wrapped = show_runtime_and_result(linear_search)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = wrapped(input_list=[1, 2], lookup_value=1)
        self.assertEqual(result, 0)
        self.assertIn("found at index 0", output.getvalue())
        self.assertEqual(wrapped.__name__, linear_search.__name__)

    def test_recursive_wrapper_reports_only_once(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = show_runtime_and_result(binary_search_by_recursion)(list(range(16)), 15)
        self.assertEqual(result, 15)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(output.getvalue().count("binary_search_by_recursion"), 1)

    def test_membership_and_missing_results(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertIs(show_runtime_and_result(find_by_sets)([1, 2], 9), False)
            self.assertIs(show_runtime_and_result(find_by_sets)([1, 2], 2), True)
            self.assertIsNone(show_runtime_and_result(linear_search)([1], 9))
        self.assertIn("absent", output.getvalue())
        self.assertIn("present", output.getvalue())
        self.assertIn("not found", output.getvalue())
        self.assertNotIn("found at index", output.getvalue())

    def test_formatter(self):
        for result, expected in [(None, "not found"), (0, "found at index 0"), (True, "present"), (False, "absent")]:
            self.assertEqual(format_result(result), expected)

    def test_profiler_returns_result(self):
        profiler = Mock()
        with patch("search_algos.timing.cProfile.Profile", return_value=profiler):
            self.assertEqual(profile_this(linear_search)([7], 7), 0)
        profiler.enable.assert_called_once_with()
        profiler.disable.assert_called_once_with()
        profiler.print_stats.assert_called_once_with()

    def test_profiler_disables_after_exception(self):
        def fail():
            raise RuntimeError("expected failure")

        profiler = Mock()
        with patch("search_algos.timing.cProfile.Profile", return_value=profiler):
            with self.assertRaisesRegex(RuntimeError, "expected failure"):
                profile_this(fail)()
        profiler.disable.assert_called_once_with()
        profiler.print_stats.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
