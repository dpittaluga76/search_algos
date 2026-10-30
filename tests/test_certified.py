"""Exact first-index results for every certified radix representation."""

import contextlib
import doctest
import io
import itertools
import random
import unittest
from bisect import bisect_left
from collections.abc import Sequence

from search_algos import certified
from search_algos.certified import build_certified_radix_index


class UnsliceableSequence(Sequence):
    """A generic borrowed sequence with indexed access but no slice support."""

    def __init__(self, values):
        self.values = values

    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise AssertionError("certified radix must not slice its source")
        return self.values[index]


class CertifiedRadixTests(unittest.TestCase):
    def assert_matches_bisect(self, values, targets, *, bits=12):
        lookup = build_certified_radix_index(values, bits=bits)
        for target in targets:
            position = bisect_left(values, target)
            expected = position if position < len(values) and values[position] == target else None
            with self.subTest(bits=bits, target=target):
                actual = lookup(target)
                self.assertEqual(actual, expected)
                if actual is not None:
                    self.assertIs(type(actual), int)

    def test_small_sorted_multisets_match_first_indices(self):
        for size in range(7):
            for values in itertools.combinations_with_replacement(range(-2, 4), size):
                for bits in (0, 1, 2, 12):
                    with self.subTest(values=values):
                        self.assert_matches_bisect(values, range(-3, 5), bits=bits)

    def test_progressions_preserve_first_indices_with_variable_duplicate_runs(self):
        counts = (1, 4, 2, 9, 1, 3, 12, 2, 5)
        for step in (1, 3, 16, 1000):
            values = [
                -37 + step * offset for offset, count in enumerate(counts) for _ in range(count)
            ]
            targets = sorted({value + delta for value in values for delta in (-1, 0, 1)})
            for bits in (0, 2, 12):
                with self.subTest(step=step):
                    self.assert_matches_bisect(values, targets, bits=bits)

    def test_endpoints_do_not_certify_unchecked_interior_spacing(self):
        cases = (
            [0, 0, 2],
            [0, 1, 1, 3],
            [0, 3, 5, 9, 12],
            [-12, -8, -7, 0, 4],
            [0, 2, 2, 6, 8, 8, 12],
        )
        for values in cases:
            for bits in (0, 1, 12):
                with self.subTest(values=values):
                    self.assert_matches_bisect(
                        values, range(values[0] - 1, values[-1] + 2), bits=bits
                    )

    def test_irregular_compact_spans_and_bitmap_width_boundary(self):
        # These cases straddle a 256-value bitmap limit; all must
        # preserve the same result contract, including holes and duplicate runs.
        for upper in (17, 254, 255, 256, 257):
            distinct = [-101, -100, -97, -89, -101 + upper]
            values = [
                value for value, count in zip(distinct, (3, 1, 7, 2, 4)) for _ in range(count)
            ]
            for bits in (0, 3, 12):
                with self.subTest(upper=upper):
                    self.assert_matches_bisect(
                        values, range(values[0] - 1, values[-1] + 2), bits=bits
                    )

    def test_bucket_edges_empty_buckets_and_duplicate_runs(self):
        values = [-64] * 5 + [-32] * 17 + [-1, 0, 0, 1] + [32] * 23 + [63] * 8
        for bits in (0, 1, 2, 3, 6, 12):
            self.assert_matches_bisect(values, range(-65, 65), bits=bits)

    def test_huge_integer_progressions_and_irregular_spans(self):
        huge = 10**400
        cases = (
            [-huge, -1, 0, 0, 1, huge],
            [huge, huge + 1, huge + 1, huge + 4, huge + 9],
            [-huge, -huge, 0, huge, huge, huge, 2 * huge],
            [0, 1, 3, 300, 301, 1000, 1000, huge],
        )
        for values in cases:
            targets = sorted(
                {value + delta for value in values for delta in (-1, 0, 1)}
                | {-huge // 2, huge // 2, 2, 299, 302, 999, 1001}
            )
            for bits in (0, 1, 12):
                with self.subTest(values=values):
                    self.assert_matches_bisect(values, targets, bits=bits)

    def test_seeded_mixed_parity_and_clustered_inputs(self):
        for seed in (0, 7, 42):
            rng = random.Random(seed)
            for size in (17, 127, 4096):
                cases = (
                    sorted(rng.randrange(-size * 5, size * 5) for _ in range(size)),
                    sorted(
                        rng.choice((-10000, -123, 0, 43, 90000)) + rng.randrange(13)
                        for _ in range(size)
                    ),
                )
                for values in cases:
                    targets = [rng.randrange(-size * 6, size * 6) for _ in range(100)]
                    targets.extend(values[:: max(1, size // 20)])
                    targets.extend(value + 1 for value in values[:: max(1, size // 20)])
                    for bits in (0, 4, 12):
                        with self.subTest(seed=seed, size=size, endpoints=(values[0], values[-1])):
                            self.assert_matches_bisect(values, targets, bits=bits)

    def test_preparation_and_queries_leave_input_unchanged(self):
        values = [-19, -19, -10, -2, 0, 1, 1, 12, 10000]
        original = values.copy()
        for bits in (0, 3, 12):
            self.assert_matches_bisect(values, range(-20, 14), bits=bits)
            self.assertEqual(values, original)

    def test_generic_sequences_need_no_source_slices(self):
        cases = (
            (),
            (-7,),
            (-7, -7, -7),
            (-12, -9, -6, -3, 0, 3),
            (-12, -9, -9, -6, -3, -3, -3, 0, 3),
            (-12, -9, -9, -5, 0, 3),
            (-12, -9, -9, -5, 0, 3, 10000),
        )
        for values in cases:
            source = UnsliceableSequence(values)
            targets = (*range(-13, 5), 9999, 10000, 10001)
            for bits in (0, 3, 12):
                with self.subTest(values=values):
                    self.assert_matches_bisect(source, targets, bits=bits)

    def test_invalid_bits_are_rejected_even_for_empty_input(self):
        for bits in (-1, 13, 1000, True, False, 1.5, "12", None):
            for values in ([], [1, 2, 3]):
                with (
                    self.subTest(bits=bits, values=values),
                    self.assertRaisesRegex(ValueError, "bits must be an integer between 0 and 12"),
                ):
                    build_certified_radix_index(values, bits=bits)

    def test_empty_constant_and_reused_lookups_are_quiet(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for values in ([], [-7], [-7] * 200):
                lookup = build_certified_radix_index(values)
                for _ in range(3):
                    self.assertEqual(lookup(-7), 0 if values else None)
                    self.assertIsNone(lookup(-8))
                    self.assertIsNone(lookup(-6))
        self.assertEqual(output.getvalue(), "")

    def test_certified_doctests(self):
        results = doctest.testmod(certified, verbose=False)
        self.assertGreater(results.attempted, 0)
        self.assertEqual(results.failed, 0)


if __name__ == "__main__":
    unittest.main()
