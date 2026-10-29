import contextlib
import doctest
import io
import itertools
import unittest

from lib import algorithms


INDEX_SEARCHES = (
    algorithms.linear_search,
    algorithms.binary_search,
    algorithms.binary_search_std_lib,
    algorithms.binary_search_by_recursion,
    algorithms.interpolation_search,
)


class SearchTests(unittest.TestCase):
    def test_small_sorted_inputs_match_first_index(self):
        for size in range(6):
            for values in itertools.combinations_with_replacement(range(-1, 3), size):
                for target in range(-2, 4):
                    expected = values.index(target) if target in values else None
                    for search in INDEX_SEARCHES:
                        with self.subTest(search=search.__name__, values=values, target=target):
                            self.assertEqual(search(values, target), expected)

    def test_searches_are_quiet_and_preserve_index_zero(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for search in INDEX_SEARCHES:
                self.assertEqual(search([1, 1, 3], 1), 0)
                self.assertIsNone(search([], 1))
            self.assertIs(algorithms.find_by_sets([1], 1), True)
        self.assertEqual(output.getvalue(), "")

    def test_linear_handles_unsorted_input(self):
        self.assertEqual(algorithms.linear_search([4, 1, 4, 2], 4), 0)
        self.assertEqual(algorithms.linear_search(iter([3, 1, 2]), 2), 2)

    def test_comparable_non_numeric_values(self):
        for search in INDEX_SEARCHES[:-1]:
            with self.subTest(search=search.__name__):
                self.assertEqual(search(["a", "b", "b", "c"], "b"), 1)
                self.assertIsNone(search(["a", "b", "c"], "z"))

    def test_set_results_are_boolean(self):
        for values, target, expected in [([], 1, False), ([1], 1, True), ([1, 1], 9, False)]:
            self.assertIs(algorithms.find_by_sets(values, target), expected)

    def test_recursive_bounds(self):
        search = algorithms.binary_search_by_recursion
        self.assertEqual(search([1, 2, 2, 3], 2, 2, 3), 2)
        self.assertIsNone(search([1, 2], 3))
        self.assertIsNone(search([1, 2], 0))
        self.assertIsNone(search([1, 2], 2, 1, 0))
        self.assertIsNone(search([], 1, 0, -1))
        for left, right in [(-1, 1), (0, 2), (3, 1), (0, -2)]:
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                search([1, 2], 3, left, right)
        with self.assertRaises(TypeError):
            search([1, 2], 1, 0.0, 1)

    def test_interpolation_constant_and_singleton_inputs(self):
        for values in [[], [5], [5, 5, 5]]:
            for target in [4, 5, 6]:
                expected = 0 if values and target == 5 else None
                self.assertEqual(algorithms.interpolation_search(values, target), expected)

    def test_interpolation_floats_and_extreme_numbers(self):
        cases = [
            [-0.2, 0.1, 0.1, 0.3, 10.5],
            [-1e308, -1.0, 0.0, 1.0, 1e308],
            [10 ** 400, 10 ** 400 + 1, 10 ** 400 + 1, 10 ** 401],
            [0.0, 5e-324, 1e-323, 1.0],
        ]
        for values in cases:
            for target in values + [-2.0, 0.2]:
                with self.subTest(values=values, target=target):
                    expected = values.index(target) if target in values else None
                    self.assertEqual(algorithms.interpolation_search(values, target), expected)

    def test_doctests(self):
        result = doctest.testmod(algorithms, verbose=False)
        self.assertGreaterEqual(result.attempted, 14)
        self.assertEqual(result.failed, 0)


if __name__ == "__main__":
    unittest.main()
