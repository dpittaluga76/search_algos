"""Exact results and bounded preparation work for the reusable radix index."""

import contextlib
import io
import itertools
import random
import unittest
from bisect import bisect_left
from collections.abc import Sequence

from search_algos import build_radix_index


class CountedRange(Sequence):
    """A large virtual sequence that forbids scans and copies."""

    def __init__(self, size):
        self.size = size
        self.reads = 0

    def __len__(self):
        return self.size

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise AssertionError("radix construction must not slice the sequence")
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError(index)
        self.reads += 1
        return 2 * index

    def __iter__(self):
        raise AssertionError("radix construction must not scan or copy the sequence")


class RadixTests(unittest.TestCase):
    def test_small_sorted_multisets_match_first_index(self):
        for size in range(7):
            for values in itertools.combinations_with_replacement(range(-2, 4), size):
                for bits in (0, 1, 2, 12):
                    lookup = build_radix_index(values, bits=bits)
                    for target in range(-3, 5):
                        expected = values.index(target) if target in values else None
                        with self.subTest(values=values, bits=bits, target=target):
                            actual = lookup(target)
                            self.assertEqual(actual, expected)
                            if actual is not None:
                                self.assertIs(type(actual), int)

    def test_bucket_boundaries_keep_duplicate_runs_and_empty_buckets_correct(self):
        values = [-64] * 5 + [-32] * 17 + [-1, 0, 0, 1] + [32] * 23 + [63] * 8
        for bits in (0, 1, 2, 3, 6, 12):
            lookup = build_radix_index(values, bits=bits)
            for target in range(-65, 65):
                expected = values.index(target) if target in values else None
                with self.subTest(bits=bits, target=target):
                    self.assertEqual(lookup(target), expected)

    def test_seeded_larger_inputs_match_bisect(self):
        for seed in (0, 7, 42):
            rng = random.Random(seed)
            for size in (127, 4096, 100000):
                values = sorted(rng.randrange(-size, size + 1) for _ in range(size))
                targets = [rng.randrange(-2 * size, 2 * size) for _ in range(100)]
                targets.extend((values[0], values[-1], values[size // 2]))
                for bits in (0, 4, 8, 12):
                    lookup = build_radix_index(values, bits=bits)
                    for target in targets:
                        position = bisect_left(values, target)
                        expected = (
                            position
                            if position < len(values) and values[position] == target
                            else None
                        )
                        with self.subTest(seed=seed, size=size, bits=bits, target=target):
                            self.assertEqual(lookup(target), expected)

    def test_outlier_and_huge_integer_values_preserve_first_matches(self):
        cases = [
            [i // 3 for i in range(3000)] + [10**12],
            [-(10**400), -1, 0, 0, 10**400],
            [10**400, 10**400 + 1, 10**400 + 1, 10**401],
        ]
        for values in cases:
            lookup = build_radix_index(values)
            sampled = values if len(values) < 83 else values[::83]
            for target in sampled + [values[0] - 1, values[-1], values[-1] + 1, 0, 1]:
                expected = values.index(target) if target in values else None
                with self.subTest(values=values[:3], target=target):
                    self.assertEqual(lookup(target), expected)

    def test_invalid_bits_are_rejected_even_for_empty_input(self):
        for bits in (-1, 13, 1000, True, False, 1.5, "12", None):
            for values in ([], [1, 2, 3]):
                with (
                    self.subTest(bits=bits, values=values),
                    self.assertRaisesRegex(ValueError, "bits must be an integer between 0 and 12"),
                ):
                    build_radix_index(values, bits=bits)

    def test_preparation_is_bounded_and_lookups_reuse_the_directory(self):
        size = 1_000_000
        values = CountedRange(size)
        lookup = build_radix_index(values)
        self.assertLessEqual(values.reads, 2 + (4096 + 1) * size.bit_length())
        values.reads = 0
        for target, expected in ((0, 0), (123456, 61728), (1999998, 999999), (123457, None)):
            self.assertEqual(lookup(target), expected)
        # Balanced buckets contain fewer than 512 entries, so four lookups
        # require far fewer accesses than rebuilding even a small directory.
        self.assertLessEqual(values.reads, 4 * 11)
        values.reads = 0
        self.assertIsNone(lookup(-1))
        self.assertIsNone(lookup(2 * size))
        self.assertEqual(values.reads, 0)

    def test_empty_constant_and_reused_lookups_are_quiet(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for values in ([], [5], [5] * 100):
                lookup = build_radix_index(values)
                for _ in range(2):
                    self.assertEqual(lookup(5), 0 if values else None)
                    self.assertIsNone(lookup(4))
                    self.assertIsNone(lookup(6))
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
