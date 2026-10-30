"""Correctness, strategy, and input-safety checks for additional searches."""

import contextlib
import doctest
import gc
import io
import itertools
import random
import sys
import unittest
import weakref
from bisect import bisect_left
from unittest.mock import patch

import search_algos
from search_algos import alternatives
from tests.test_algorithms import CountedSequence

COMPARABLE_SEARCHES = (
    alternatives.fibonacci_search,
    alternatives.ternary_search,
    alternatives.ternary_search_by_recursion,
    alternatives.double_linear_search,
    alternatives.double_linear_search_by_recursion,
    alternatives.sentinel_linear_search,
)
INDEX_SEARCHES = (*COMPARABLE_SEARCHES, alternatives.interpolation_search_by_recursion)
UNSORTED_SEARCHES = (
    alternatives.double_linear_search,
    alternatives.double_linear_search_by_recursion,
    alternatives.sentinel_linear_search,
)


class AlternativeSearchTests(unittest.TestCase):
    def test_exhaustive_small_sorted_inputs_and_membership(self):
        for size in range(8):
            for values in itertools.combinations_with_replacement(range(-1, 3), size):
                for target in range(-2, 4):
                    expected = values.index(target) if target in values else None
                    for search in INDEX_SEARCHES:
                        with self.subTest(search=search.__name__, values=values, target=target):
                            result = search(values, target)
                            self.assertEqual(result, expected)
                            self.assertIs(type(result), int if expected is not None else type(None))
                    self.assertIs(
                        alternatives.binary_search_slicing(values, target), expected is not None
                    )

    def test_exhaustive_unsorted_inputs_preserve_first_occurrence(self):
        for size in range(7):
            for values in itertools.product(range(3), repeat=size):
                for target in range(-1, 4):
                    expected = values.index(target) if target in values else None
                    for search in UNSORTED_SEARCHES:
                        with self.subTest(search=search.__name__, values=values, target=target):
                            self.assertEqual(search(values, target), expected)

    def test_public_exports_are_quiet_and_do_not_mutate_input(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            for search in INDEX_SEARCHES:
                self.assertIs(getattr(search_algos, search.__name__), search)
                values = [1, 1, 3]
                self.assertEqual(search(values, 1), 0)
                self.assertIsNone(search(values, 2))
                self.assertIsNone(search([], 1))
                self.assertEqual(values, [1, 1, 3])
            self.assertIs(search_algos.binary_search_slicing([1, 1, 3], 1), True)
            self.assertIs(search_algos.binary_search_slicing([], 1), False)
            self.assertIs(search_algos.build_sentinel_search, alternatives.build_sentinel_search)
        self.assertEqual(output.getvalue(), "")

    def test_strings_and_equality_only_unhashable_values(self):
        for search in COMPARABLE_SEARCHES:
            with self.subTest(search=search.__name__):
                self.assertEqual(search(["a", "b", "b", "c"], "b"), 1)
                self.assertIsNone(search(["a", "b", "c"], "z"))
        self.assertIs(alternatives.binary_search_slicing(["a", "b", "c"], "b"), True)
        for search in UNSORTED_SEARCHES:
            self.assertEqual(search([[2], [1], [2]], [2]), 0)
            self.assertIsNone(search([[2], [1], [2]], [3]))

    def test_seeded_larger_inputs_against_bisect(self):
        for seed in (0, 7, 42):
            rng = random.Random(seed)
            for size in (127, 1024, 4096):
                values = sorted(rng.randrange(-size, size + 1) for _ in range(size))
                targets = [rng.randrange(-2 * size, 2 * size) for _ in range(24)]
                targets.extend((values[0], values[-1], values[size // 2]))
                for target in targets:
                    index = bisect_left(values, target)
                    expected = index if index < size and values[index] == target else None
                    for search in INDEX_SEARCHES:
                        with self.subTest(
                            seed=seed, size=size, target=target, search=search.__name__
                        ):
                            self.assertEqual(search(values, target), expected)
                    self.assertIs(
                        alternatives.binary_search_slicing(values, target), expected is not None
                    )

    def test_first_match_spans_fibonacci_and_ternary_probe_boundaries(self):
        for prefix in (0, 1, 10, 63, 127):
            values = [-1] * prefix + [1] * 300 + [9] * 20
            for search in INDEX_SEARCHES:
                with self.subTest(search=search.__name__, prefix=prefix):
                    self.assertEqual(search(values, 1), prefix)
                    self.assertEqual(search(values, 9), prefix + 300)

    def test_fibonacci_and_ternary_have_logarithmic_indexing_work(self):
        for search in COMPARABLE_SEARCHES[:3]:
            for size in (1000, 10000, 100000):
                for target in (0, size // 2, size - 1, size):
                    values = CountedSequence(range(size))
                    with self.subTest(search=search.__name__, size=size, target=target):
                        self.assertEqual(search(values, target), target if target < size else None)
                        self.assertLessEqual(values.reads, 10 * size.bit_length() + 10)

    def test_recursive_linear_handles_long_misses_and_late_hits_without_limit_changes(self):
        limit = sys.getrecursionlimit()
        search = alternatives.double_linear_search_by_recursion
        values = list(range(10000))
        for target in (-1, 0, 4999, 9999):
            self.assertEqual(search(values, target), target if target >= 0 else None)
        self.assertEqual(sys.getrecursionlimit(), limit)

    def test_recursive_searches_release_inputs_without_cyclic_gc(self):
        class Values(list):
            pass

        searches = (
            alternatives.ternary_search_by_recursion,
            alternatives.double_linear_search_by_recursion,
            alternatives.interpolation_search_by_recursion,
        )
        previous = gc.isenabled()
        gc.disable()
        try:
            for search in searches:
                with self.subTest(search=search.__name__):
                    values = Values(range(200))
                    reference = weakref.ref(values)
                    self.assertEqual(search(values, 100), 100)
                    del values
                    self.assertIsNone(reference(), "recursive helper retained its input")
        finally:
            gc.enable() if previous else gc.disable()

    def test_recursive_interpolation_retains_adversarial_interpolation_strategy(self):
        limit = sys.getrecursionlimit()
        values = CountedSequence([*range(1, 10000), 10**12])
        with patch("search_algos.alternatives.bisect_left", side_effect=AssertionError("fallback")):
            self.assertEqual(alternatives.interpolation_search_by_recursion(values, 9999), 9998)
        self.assertGreaterEqual(values.reads, len(values))
        self.assertEqual(sys.getrecursionlimit(), limit)

    def test_recursive_interpolation_numeric_safeguards(self):
        cases = (
            [-0.2, 0.1, 0.1, 0.3, 10.5],
            [-1e308, -1.0, 0.0, 1.0, 1e308],
            [10**400, 10**400 + 1, 10**400 + 1, 10**401],
            [0.0, 5e-324, 1e-323, 1.0],
            [2**53 + 3, float(2**53 + 4), float(2**53 + 4)],
            [-float(2**53 + 4), -(2**53 + 3), -(2**53 + 3)],
        )
        for values in cases:
            for target in [*values, -2.0, 0.2]:
                with self.subTest(values=values, target=target):
                    expected = values.index(target) if target in values else None
                    self.assertEqual(
                        alternatives.interpolation_search_by_recursion(values, target), expected
                    )

    def test_sentinel_snapshots_iterables_and_reuses_private_buffers(self):
        values = [3, 1, 3]
        first = alternatives.build_sentinel_search(values)
        second = alternatives.build_sentinel_search(iter([4, 2, 4]))
        values[:] = [9]
        for _ in range(3):
            self.assertEqual(first(3), 0)
            self.assertEqual(first(1), 1)
            self.assertIsNone(first(2))
            self.assertIsNone(first(9))
            self.assertEqual(second(4), 0)
            self.assertIsNone(second(3))
        self.assertIsNone(alternatives.build_sentinel_search([])(1))
        self.assertEqual(alternatives.sentinel_linear_search(iter([3, 1, 3]), 1), 1)

    def test_sentinel_cleanup_releases_target_after_equality_exception(self):
        class Target:
            pass

        class Explosive:
            def __eq__(self, other):
                if isinstance(other, Target):
                    raise RuntimeError("equality failed")
                return False

        values = [Explosive()]
        lookup = alternatives.build_sentinel_search(values)
        target = Target()
        reference = weakref.ref(target)
        with self.assertRaisesRegex(RuntimeError, "equality failed"):
            lookup(target)
        del target
        gc.collect()
        self.assertIsNone(reference(), "private buffer retained a failed query's sentinel")
        self.assertIsNone(lookup("absent"))
        self.assertEqual(len(values), 1)

    def test_sentinel_uses_the_same_equality_operation_as_other_index_searches(self):
        class EqualityOnly:
            def __eq__(self, other):
                return isinstance(other, EqualityOnly)

            def __ne__(self, other):
                raise AssertionError("search must use equality")

        value = EqualityOnly()
        self.assertEqual(alternatives.sentinel_linear_search([value], EqualityOnly()), 0)
        lookup = alternatives.build_sentinel_search([value])
        self.assertEqual(lookup(EqualityOnly()), 0)

    def test_binary_membership_preserves_recursive_slicing_cost(self):
        class SliceCountingSequence(CountedSequence):
            def __getitem__(self, index):
                if isinstance(index, slice):
                    slices.append(index)
                    return SliceCountingSequence(self.values[index])
                return super().__getitem__(index)

        slices = []
        values = SliceCountingSequence(tuple(range(1000)))
        self.assertIs(alternatives.binary_search_slicing(values, 999), True)
        self.assertGreater(len(slices), 1)
        self.assertIs(alternatives.binary_search_slicing(values, -1), False)

    def test_doctests(self):
        result = doctest.testmod(alternatives, verbose=False)
        self.assertGreaterEqual(result.attempted, 20)
        self.assertEqual(result.failed, 0)


if __name__ == "__main__":
    unittest.main()
