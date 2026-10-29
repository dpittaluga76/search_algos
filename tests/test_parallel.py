"""Regression coverage using real spawn workers, including failure paths."""

from concurrent.futures.process import BrokenProcessPool
import contextlib
import io
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from search_algos.algorithms import binary_search
from search_algos.parallel import (
    chunk_ranges,
    effective_worker_count,
    multiproc_test,
    parallel_search,
    parallel_search_many,
)


def raising_search(values, target):
    raise RuntimeError("worker search failed")


def invalid_index_search(values, target):
    return len(values)


def boolean_search(values, target):
    return True


def wrong_value_search(values, target):
    return 0


def abruptly_exit(values, target):
    os._exit(7)


def verify_abrupt_failure():
    """Run in a bounded subprocess so a regression cannot hang the test suite."""
    try:
        parallel_search_many([1, 2, 3, 4], [2], 2, abruptly_exit)
    except BrokenProcessPool:
        if multiprocessing.active_children():
            raise AssertionError("executor left child processes running")
        print("worker death propagated")
    else:
        raise AssertionError("abrupt worker failure was not propagated")


class PartitionTests(unittest.TestCase):
    def test_partitions_cover_every_element_once(self):
        for size in (0, 1, 2, 5, 10, 17, 100):
            for workers in (1, 2, 4, 16):
                with self.subTest(size=size, workers=workers):
                    ranges = chunk_ranges(size, workers)
                    covered = [i for start, stop in ranges for i in range(start, stop)]
                    self.assertEqual(covered, list(range(size)))
                    self.assertEqual(len(ranges), min(size, workers))
                    if ranges:
                        lengths = [stop - start for start, stop in ranges]
                        self.assertGreater(min(lengths), 0)
                        self.assertLessEqual(max(lengths) - min(lengths), 1)

    def test_invalid_worker_counts_even_with_empty_input(self):
        for workers in (0, -1, True, False, 1.5, "2"):
            with self.subTest(workers=workers):
                with self.assertRaises(ValueError):
                    chunk_ranges(0, workers)
                with self.assertRaises(ValueError):
                    parallel_search_many([], [], workers)

    def test_invalid_sizes(self):
        for size in (-1, True, 1.5, "2"):
            with self.subTest(size=size), self.assertRaises(ValueError):
                effective_worker_count(size, 2)

    def test_default_workers_and_windows_limit(self):
        with patch("search_algos.parallel.os.cpu_count", return_value=4):
            self.assertEqual(effective_worker_count(10), 4)
            self.assertEqual(effective_worker_count(2), 2)
        with patch("search_algos.parallel.os.cpu_count", return_value=None):
            self.assertEqual(effective_worker_count(10), 1)
        with patch("search_algos.parallel.sys.platform", "win32"):
            self.assertEqual(effective_worker_count(1000, 1000), 61)

    def test_empty_work_avoids_starting_a_pool(self):
        with patch("search_algos.parallel.ProcessPoolExecutor", side_effect=AssertionError):
            self.assertEqual(parallel_search_many([], [1, 2], 2), [None, None])
            self.assertEqual(parallel_search_many([1, 2], [], 2), [])
            self.assertIsNone(parallel_search([], 1, 2))


class ParallelSearchTests(unittest.TestCase):
    def test_remainder_and_missing_targets(self):
        self.assertEqual(
            parallel_search_many(list(range(1, 11)), [10, 7, 1, 0, 11], 4),
            [9, 6, 0, None, None],
        )

    def test_chunk_offsets_are_global(self):
        self.assertEqual(parallel_search_many(list(range(100)), [55, 99], 2), [55, 99])

    def test_duplicates_return_first_global_index(self):
        self.assertEqual(parallel_search_many([1, 2, 2, 2, 2, 3], [2, 3], 4), [1, 5])

    def test_more_workers_than_elements(self):
        self.assertEqual(parallel_search([1, 2], 2, 20), 1)
        self.assertEqual(parallel_search_many([7], [7, 8], 20), [0, None])

    def test_legacy_entry_point_returns_result_without_printing(self):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            result = multiproc_test(binary_search, 5, [1, 2, 3, 4, 5], 5, 2)
        self.assertEqual(result, 4)
        self.assertEqual(captured.getvalue(), "")

    def test_legacy_entry_point_rejects_size_mismatch(self):
        with self.assertRaises(ValueError):
            multiproc_test(binary_search, 10, [1, 2], 1, 2)

    def test_worker_exception_propagates_and_children_are_joined(self):
        before = {child.pid for child in multiprocessing.active_children()}
        with self.assertRaisesRegex(RuntimeError, "worker search failed"):
            parallel_search([1, 2, 3, 4], 2, 2, raising_search)
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)

    def test_invalid_worker_results_are_rejected(self):
        for search_func in (invalid_index_search, boolean_search, wrong_value_search):
            with self.subTest(search_func=search_func.__name__):
                with self.assertRaisesRegex(ValueError, "matching index"):
                    parallel_search([1, 2], 2, 2, search_func)

    def test_abrupt_worker_failure_does_not_hang(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "from tests.test_parallel import verify_abrupt_failure; verify_abrupt_failure()",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("worker death propagated", completed.stdout)


if __name__ == "__main__":
    unittest.main()
