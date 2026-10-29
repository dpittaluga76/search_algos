import contextlib
import doctest
import io
import itertools
import random
import unittest
from bisect import bisect_left
from collections.abc import Sequence

from search_algos import algorithms

COMPARABLE_SEARCHES = (
    algorithms.linear_search,
    algorithms.binary_search,
    algorithms.binary_search_std_lib,
    algorithms.binary_search_by_recursion,
    algorithms.exponential_search,
    algorithms.jump_search,
    algorithms.find_by_dict,
)
NUMERIC_SEARCHES = (
    algorithms.interpolation_search,
    algorithms.interpolation_search_hybrid,
)
INDEX_SEARCHES = COMPARABLE_SEARCHES + NUMERIC_SEARCHES


class CountedSequence(Sequence):
    """Count indexing work without depending on machine-specific timings."""

    def __init__(self, values):
        self.values = values
        self.reads = 0

    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        self.reads += 1
        return self.values[index]


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
        for search in COMPARABLE_SEARCHES:
            with self.subTest(search=search.__name__):
                self.assertEqual(search(["a", "b", "b", "c"], "b"), 1)
                self.assertIsNone(search(["a", "b", "c"], "z"))

    def test_set_results_are_boolean(self):
        for values, target, expected in [
            ([], 1, False),
            ([1], 1, True),
            ([1, 1], 9, False),
        ]:
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
        for left, right in ((True, True), (False, 1), (0, False), (True, None)):
            with self.subTest(left=left, right=right), self.assertRaises(TypeError):
                search([1, 2], 2, left, right)

    def test_interpolation_constant_and_singleton_inputs(self):
        for values in [[], [5], [5, 5, 5]]:
            for target in [4, 5, 6]:
                expected = 0 if values and target == 5 else None
                for search in NUMERIC_SEARCHES:
                    self.assertEqual(search(values, target), expected)

    def test_interpolation_floats_and_extreme_numbers(self):
        cases = [
            [-0.2, 0.1, 0.1, 0.3, 10.5],
            [-1e308, -1.0, 0.0, 1.0, 1e308],
            [10**400, 10**400 + 1, 10**400 + 1, 10**401],
            [0.0, 5e-324, 1e-323, 1.0],
        ]
        for values in cases:
            for target in values + [-2.0, 0.2]:
                with self.subTest(values=values, target=target):
                    expected = values.index(target) if target in values else None
                    for search in NUMERIC_SEARCHES:
                        self.assertEqual(search(values, target), expected)

    def test_hash_index_preserves_first_occurrence_and_accepts_iterators(self):
        values = [3, 1, 3, 2, 1]
        index = algorithms.build_first_index(iter(values))
        self.assertEqual(index, {3: 0, 1: 1, 2: 3})
        self.assertEqual(index.get(3), 0)
        self.assertIsNone(index.get(9))
        self.assertEqual(algorithms.find_by_dict(iter(values), 1), 1)

    def test_seeded_larger_inputs_match_bisect(self):
        for seed in (0, 7, 42):
            rng = random.Random(seed)
            for size in (127, 1024, 4096):
                values = sorted(rng.randrange(-size, size + 1) for _ in range(size))
                targets = [rng.randrange(-2 * size, 2 * size) for _ in range(40)]
                targets.extend((values[0], values[-1], values[size // 2]))
                index = algorithms.build_first_index(values)
                for target in targets:
                    position = bisect_left(values, target)
                    expected = (
                        position if position < len(values) and values[position] == target else None
                    )
                    for search in INDEX_SEARCHES:
                        with self.subTest(
                            seed=seed, size=size, target=target, search=search.__name__
                        ):
                            self.assertEqual(search(values, target), expected)
                    self.assertEqual(index.get(target), expected)
                    self.assertIs(algorithms.find_by_sets(values, target), expected is not None)

    def test_adversarial_sequence_preserves_first_matches(self):
        values = [i // 3 for i in range(3000)] + [10**12]
        for target in (-1, 0, 1, 500, 999, 1000, 10**12, 10**12 + 1):
            position = bisect_left(values, target)
            expected = position if position < len(values) and values[position] == target else None
            for search in INDEX_SEARCHES:
                with self.subTest(target=target, search=search.__name__):
                    self.assertEqual(search(values, target), expected)

    def test_hybrid_has_logarithmically_bounded_adversarial_probes(self):
        for size in (1000, 10000, 100000):
            sequence = CountedSequence(list(range(1, size)) + [10**12])
            self.assertEqual(algorithms.interpolation_search_hybrid(sequence, size - 1), size - 2)
            self.assertLessEqual(sequence.reads, 10 * size.bit_length() + 10)

    def test_jump_search_first_match_crosses_block_boundaries(self):
        values = [0] * 8 + [1] * 12 + [2] * 16
        self.assertEqual(algorithms.jump_search(values, 0), 0)
        self.assertEqual(algorithms.jump_search(values, 1), 8)
        self.assertEqual(algorithms.jump_search(values, 2), 20)

    def test_doctests(self):
        result = doctest.testmod(algorithms, verbose=False)
        self.assertGreaterEqual(result.attempted, 14)
        self.assertEqual(result.failed, 0)


if __name__ == "__main__":
    unittest.main()
