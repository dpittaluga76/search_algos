"""Exact prepared alternatives, selector heuristics, and their preparation costs."""

import contextlib
import doctest
import io
import itertools
import random
import unittest
from bisect import bisect_left
from collections.abc import Sequence
from unittest.mock import patch

from search_algos import (
    build_adaptive_index,
    build_first_index_reversed,
    build_guarded_index,
    build_neighbor_index,
    prepared,
)

NUMERIC_BUILDERS = (build_neighbor_index, build_guarded_index, build_adaptive_index)


class CountedSequence(Sequence):
    """Expose large synthetic input without allowing an accidental full scan."""

    def __init__(self, size, *, outlier=False, constant=False):
        self.size = size
        self.outlier = outlier
        self.constant = constant
        self.reads = 0

    def __len__(self):
        return self.size

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise AssertionError("prepared numeric input must not be sliced")
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError(index)
        self.reads += 1
        if self.constant:
            return 7
        return 10**100 if self.outlier and index == self.size - 1 else 2 * index

    def __iter__(self):
        raise AssertionError("selected strategy must not scan or copy the input")


class EqualKey:
    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        return isinstance(other, EqualKey) and self.value == other.value


class PreparedSearchTests(unittest.TestCase):
    def test_small_sorted_multisets_match_first_indices(self):
        for size in range(8):
            for values in itertools.combinations_with_replacement(range(-2, 4), size):
                lookups = [builder(values) for builder in NUMERIC_BUILDERS]
                lookups.append(build_first_index_reversed(values).get)
                for target in range(-3, 5):
                    expected = values.index(target) if target in values else None
                    for lookup in lookups:
                        with self.subTest(values=values, target=target, lookup=lookup):
                            result = lookup(target)
                            self.assertEqual(result, expected)
                            if result is not None:
                                self.assertIs(type(result), int)

    def test_large_duplicate_runs_negative_and_huge_integers(self):
        cases = [
            [-10] * 500 + [0] * 1000 + [1] * 800 + [9000],
            [i // 3 for i in range(3000)] + [10**100],
            [-(10**400), -1, 0, 0, 1, 10**400],
            [10**400, 10**400 + 1, 10**400 + 1, 10**401],
        ]
        for values in cases:
            targets = sorted(set(values)) + [values[0] - 1, values[-1] + 1, 2, 50]
            expected = [values.index(target) if target in values else None for target in targets]
            for builder in NUMERIC_BUILDERS:
                lookup = builder(values)
                with self.subTest(builder=builder, endpoints=(values[0], values[-1])):
                    self.assertEqual([lookup(target) for target in targets], expected)
            index = build_first_index_reversed(values)
            self.assertEqual([index.get(target) for target in targets], expected)

    def test_seeded_irregular_inputs_match_bisect(self):
        for seed in (0, 7, 42):
            rng = random.Random(seed)
            for size in (17, 127, 4096):
                values = sorted(rng.randrange(-size * 5, size * 5) for _ in range(size))
                targets = [rng.randrange(-size * 6, size * 6) for _ in range(100)]
                targets.extend(values[:: max(1, size // 20)])
                for builder in NUMERIC_BUILDERS:
                    lookup = builder(values)
                    for target in targets:
                        position = bisect_left(values, target)
                        expected = (
                            position
                            if position < len(values) and values[position] == target
                            else None
                        )
                        with self.subTest(seed=seed, size=size, builder=builder, target=target):
                            self.assertEqual(lookup(target), expected)

    def test_numeric_builders_borrow_input_and_bound_preparation_reads(self):
        for builder in NUMERIC_BUILDERS:
            for outlier in (False, True):
                values = CountedSequence(1_000_001, outlier=outlier)
                lookup = builder(values)
                with self.subTest(builder=builder, outlier=outlier):
                    # Endpoint preparation plus at most16 adjacent sample pairs,
                    # 16 prediction samples, and delegated endpoint preparation.
                    self.assertLessEqual(values.reads, 52)
                    values.reads = 0
                    self.assertEqual(lookup(123456), 61728)
                    self.assertIsNone(lookup(123457))
                    self.assertLessEqual(values.reads, 2 * (values.size.bit_length() + 5))
                    values.reads = 0
                    self.assertIsNone(lookup(-1))
                    self.assertIsNone(lookup(10**101))
                    self.assertEqual(values.reads, 0)

    def test_empty_constant_and_reused_lookups_are_quiet(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for values in ([], [-7], [-7] * 200):
                for builder in NUMERIC_BUILDERS:
                    lookup = builder(values)
                    for _ in range(3):
                        self.assertEqual(lookup(-7), 0 if values else None)
                        self.assertIsNone(lookup(-8))
                        self.assertIsNone(lookup(-6))
        self.assertEqual(output.getvalue(), "")

    def test_neighbor_and_adaptive_constant_inputs_only_need_endpoints(self):
        for builder in (build_neighbor_index, build_adaptive_index):
            values = CountedSequence(1_000_001, constant=True)
            lookup = builder(values)
            with self.subTest(builder=builder):
                self.assertEqual(values.reads, 2)
                values.reads = 0
                self.assertEqual(lookup(7), 0)
                self.assertIsNone(lookup(6))
                self.assertIsNone(lookup(8))
                self.assertEqual(values.reads, 0)

    def test_prepared_doctests(self):
        results = doctest.testmod(prepared, verbose=False)
        self.assertGreater(results.attempted, 0)
        self.assertEqual(results.failed, 0)


class ReverseIndexTests(unittest.TestCase):
    def test_unsorted_sequence_and_iterator_preserve_first_indices(self):
        values = [3, 1, 3, 2, 1]
        for source in (values, tuple(values), iter(values), (value for value in values)):
            with self.subTest(source=type(source)):
                result = build_first_index_reversed(source)
                self.assertEqual(result, {3: 0, 1: 1, 2: 3})
                self.assertIsNone(result.get(9))
        self.assertEqual(build_first_index_reversed(iter(())), {})

    def test_key_order_follows_reverse_last_occurrences(self):
        result = build_first_index_reversed(["a", "b", "a", "c", "b"])
        self.assertEqual(list(result.items()), [("b", 1), ("c", 3), ("a", 0)])

    def test_equal_keys_retain_last_occurrence_object(self):
        first, last = EqualKey("same"), EqualKey("same")
        result = build_first_index_reversed([first, "other", last])
        self.assertIs(next(iter(result)), last)
        self.assertEqual(result[first], 0)
        self.assertEqual(result[last], 0)

    def test_sequence_does_not_require_forward_iteration(self):
        values = CountedSequence(10)
        self.assertEqual(build_first_index_reversed(values), {2 * i: i for i in range(10)})
        self.assertEqual(values.reads, 10)


class AdaptiveSelectionTests(unittest.TestCase):
    def assert_engine(self, values, engine):
        with contextlib.ExitStack() as stack:
            spies = {
                name: stack.enter_context(
                    patch.object(prepared, name, wraps=getattr(prepared, name))
                )
                for name in (
                    "build_first_index_reversed",
                    "build_neighbor_index",
                    "build_guarded_index",
                    "build_radix_index",
                )
            }
            lookup = build_adaptive_index(values)
            for name, spy in spies.items():
                if name == engine:
                    spy.assert_called_once_with(values)
                else:
                    spy.assert_not_called()
            for target in values + [values[0] - 1, values[-1] + 1]:
                expected = values.index(target) if target in values else None
                self.assertEqual(lookup(target), expected)

    def test_each_nonconstant_strategy_is_selected(self):
        self.assert_engine([0] * 99 + [100], "build_first_index_reversed")
        self.assert_engine(list(range(129)), "build_neighbor_index")
        self.assert_engine(list(range(128)) + [10**12], "build_guarded_index")
        # Maximum sampled prediction error is exactly last/4, selecting radix.
        self.assert_engine([i * i for i in range(65)], "build_radix_index")

    def test_duplicate_threshold_requires_more_than_half_the_samples(self):
        for duplicate_samples, engine in (
            (8, "build_neighbor_index"),
            (9, "build_first_index_reversed"),
        ):
            values = list(range(129))
            for position in range(8, 8 * duplicate_samples + 1, 8):
                values[position] = values[position - 1]
            with self.subTest(duplicate_samples=duplicate_samples):
                self.assert_engine(values, engine)

    def test_deceptively_regular_samples_preserve_exact_results(self):
        values = list(range(1025))
        for start in range(1, 1024, 64):
            values[start : start + 62] = [values[start + 61]] * 62
        self.assert_engine(values, "build_neighbor_index")
        lookup = build_adaptive_index(values)
        for target in range(-1, 1027):
            expected = values.index(target) if target in values else None
            self.assertEqual(lookup(target), expected)


if __name__ == "__main__":
    unittest.main()
