"""Exactness of the stride, run-map, and directory landmark strategies."""

import doctest
import itertools
import random
import unittest
from bisect import bisect_left
from collections.abc import Sequence

from search_algos import landmark
from search_algos.landmark import build_landmark_index


class NoSlices(Sequence):
    def __init__(self, values):
        self.values = values

    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise AssertionError("landmark preparation must not slice its input")
        return self.values[index]


class LandmarkTests(unittest.TestCase):
    def assert_matches(self, values, targets):
        lookup = build_landmark_index(values)
        for target in targets:
            position = bisect_left(values, target)
            expected = position if position < len(values) and values[position] == target else None
            with self.subTest(target=target):
                actual = lookup(target)
                self.assertEqual(actual, expected)
                if actual is not None:
                    self.assertIs(type(actual), int)

    def test_exhaustive_small_multisets(self):
        for size in range(7):
            for values in itertools.combinations_with_replacement(range(-2, 4), size):
                with self.subTest(values=values):
                    self.assert_matches(values, range(-3, 5))

    def test_divisible_endpoints_do_not_establish_regular_interior(self):
        cases = (
            [0, 0, 2],
            [0, 1, 1, 3],
            [0, 3, 5, 9, 12],
            [0, 1, 2, 3, 20],
            [0, 17, 18, 19, 20],
            [0, 6, 6, 9, 12],
            [-20, -19, -19, -5, 0],
        )
        for values in cases:
            with self.subTest(values=values):
                self.assert_matches(values, range(values[0] - 1, values[-1] + 2))

    def test_duplicate_runs_preserve_first_positions(self):
        rng = random.Random(18)
        values = [key for key in range(-100, 101, 3) for _ in range(rng.randrange(20, 80))]
        self.assert_matches(values, range(-101, 102))

    def test_misleading_duplicate_samples_with_unique_tails(self):
        # All sampled adjacent pairs are equal, despite almost all keys being
        # unique. Any run-budget fallback must retain exact first-index results.
        values = [index * 3 for index in range(4096)]
        for sample in range(1, 17):
            position = max(1, (len(values) - 1) * sample // 16)
            values[position] = values[position - 1]
        self.assert_matches(values, range(-1, values[-1] + 2))

    def test_mixed_parity_random_and_clustered_data(self):
        for seed in (0, 1, 7, 42):
            rng = random.Random(seed)
            for size in (1, 2, 31, 2048):
                cases = (
                    sorted(rng.sample(range(-size * 20, size * 20), size)),
                    sorted(rng.randrange(-50, 51) for _ in range(size)),
                    sorted(rng.choice((-10000, 0, 10000)) + rng.randrange(17) for _ in range(size)),
                )
                for values in cases:
                    targets = [rng.randrange(-size * 21, size * 21) for _ in range(100)]
                    targets.extend(value + delta for value in values for delta in (-1, 0, 1))
                    with self.subTest(seed=seed, size=size):
                        self.assert_matches(values, targets)

    def test_huge_integers_and_sparse_bucket_edges(self):
        huge = 10**400
        for values in (
            [-huge, -huge, -1, 0, 1, huge],
            [huge, huge + 3, huge + 6, huge + 9],
            [-8192, -8191, -4096, 0, 0, 4095, 8192],
        ):
            targets = {value + delta for value in values for delta in (-1, 0, 1)}
            targets.update((-huge // 2, huge // 2, -4095, 4096, 8191))
            self.assert_matches(values, sorted(targets))

    def test_borrowed_sequence_is_not_mutated_or_sliced(self):
        for values in ([], [-7], [-7] * 100, list(range(-20, 21, 3)), [-40, -1, -1, 7, 1024]):
            original = values.copy()
            self.assert_matches(NoSlices(values), (*range(-41, 42), 1023, 1024, 1025))
            self.assertEqual(values, original)

    def test_doctests(self):
        result = doctest.testmod(landmark, verbose=False)
        self.assertEqual(result.failed, 0)


if __name__ == "__main__":
    unittest.main()
