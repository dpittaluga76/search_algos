"""Regression coverage using real spawn workers, including failure paths."""

import contextlib
import gc
import io
import multiprocessing
import os
import subprocess
import sys
import unittest
from array import array
from collections import deque
from collections.abc import Sequence
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from unittest.mock import patch

from search_algos.algorithms import binary_search, linear_search
from search_algos.parallel import (
    ParallelSearchPool,
    _search_chunk,
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


def abruptly_exit_on_ready():
    os._exit(8)


def reject_unrelated_chunk(values, target):
    if target not in values:
        raise RuntimeError("received a query for an unrelated chunk")
    return binary_search(values, target)


def earliest_duplicate_chunk_only(values, target):
    if values[0] == 2:
        raise RuntimeError("duplicate target routed to a later chunk")
    return binary_search(values, target)


def require_disabled_gc(values, target):
    if gc.isenabled():
        raise RuntimeError("worker GC was enabled")
    return binary_search(values, target)


def require_enabled_gc(values, target):
    if not gc.isenabled():
        raise RuntimeError("worker GC was disabled")
    return binary_search(values, target)


class IndexOnlySequence(Sequence):
    def __init__(self, values):
        self.values = values

    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise TypeError("this sequence supports integer indices only")
        return self.values[index]


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

    try:
        with patch("search_algos.parallel._worker_ready", abruptly_exit_on_ready):
            with ParallelSearchPool([1, 2, 3, 4], 2):
                raise AssertionError("startup should have failed")
    except BrokenProcessPool:
        if multiprocessing.active_children():
            raise AssertionError("startup failure left child processes running")
        print("startup failure propagated")
    else:
        raise AssertionError("abrupt startup failure was not propagated")


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

    def test_outside_ranges_and_chunk_gaps_avoid_starting_a_pool(self):
        with patch("search_algos.parallel.ProcessPoolExecutor", side_effect=AssertionError):
            self.assertEqual(
                parallel_search_many([1, 2, 10, 11], [0, 3, 9, 12], 2),
                [None, None, None, None],
            )

    def test_pool_options_reject_non_boolean_values(self):
        for option in ("route_targets", "disable_gc"):
            for value in (0, 1, None, "false"):
                with self.subTest(option=option, value=value), self.assertRaises(ValueError):
                    ParallelSearchPool([], **{option: value})

    def test_worker_search_restores_gc_state_after_failure(self):
        original = gc.isenabled()
        try:
            for enabled in (True, False):
                if enabled:
                    gc.enable()
                else:
                    gc.disable()
                for disabled_during_search in (True, False):
                    with self.subTest(enabled=enabled, disabled=disabled_during_search):
                        with self.assertRaisesRegex(RuntimeError, "worker search failed"):
                            _search_chunk(
                                [1, 2], [(0, 2)], 0, raising_search, disabled_during_search
                            )
                        self.assertEqual(gc.isenabled(), enabled)
        finally:
            if original:
                gc.enable()
            else:
                gc.disable()


class ParallelSearchTests(unittest.TestCase):
    def test_non_sliceable_and_non_pickleable_sequence_containers(self):
        for values in (
            deque([1, 2, 2, 2, 2, 3]),
            memoryview(array("i", [1, 2, 2, 2, 2, 3])),
            IndexOnlySequence([1, 2, 2, 2, 2, 3]),
        ):
            with self.subTest(container=type(values).__name__):
                self.assertEqual(parallel_search_many(values, [3, 2, 0, 4], 2), [5, 1, None, None])

    def test_generic_container_broadcast_preserves_first_match(self):
        self.assertEqual(
            parallel_search_many(
                deque([9, 1, 4, 2, 9, 3]),
                [9, 3, 1, 7],
                2,
                linear_search,
                route_targets=False,
            ),
            [0, 5, 1, None],
        )

    def test_remainder_and_missing_targets(self):
        self.assertEqual(
            parallel_search_many(list(range(1, 11)), [10, 7, 1, 0, 11], 4),
            [9, 6, 0, None, None],
        )

    def test_chunk_offsets_are_global(self):
        self.assertEqual(parallel_search_many(list(range(100)), [55, 99], 2), [55, 99])

    def test_duplicates_return_first_global_index(self):
        self.assertEqual(parallel_search_many([1, 2, 2, 2, 2, 3], [2, 3], 4), [1, 5])

    def test_routing_sends_only_queries_for_the_matching_chunk(self):
        self.assertEqual(
            parallel_search_many([1, 2, 3, 4, 5, 6], [6, 1, 4, 6, 2], 3, reject_unrelated_chunk),
            [5, 0, 3, 5, 1],
        )

    def test_duplicate_boundary_routing_uses_earliest_eligible_chunk(self):
        self.assertEqual(
            parallel_search_many([1, 2, 2, 2, 2, 3], [2], 2, earliest_duplicate_chunk_only),
            [1],
        )

    def test_broadcast_mode_supports_unsorted_custom_search(self):
        self.assertEqual(
            parallel_search_many(
                [9, 1, 4, 2, 9, 3],
                [9, 3, 1, 7],
                2,
                linear_search,
                route_targets=False,
            ),
            [0, 5, 1, None],
        )

    def test_worker_gc_policy_is_explicit_and_parent_state_is_unchanged(self):
        previous_gc = gc.isenabled()
        self.assertEqual(
            parallel_search([1, 2, 3, 4], 2, 2, require_disabled_gc, disable_gc=True),
            1,
        )
        self.assertEqual(
            parallel_search([1, 2, 3, 4], 3, 2, require_enabled_gc, disable_gc=False),
            2,
        )
        self.assertEqual(gc.isenabled(), previous_gc)

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
                    parallel_search([1, 2, 3, 4], 2, 2, search_func)

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
        self.assertIn("startup failure propagated", completed.stdout)


class ReusedPoolTests(unittest.TestCase):
    def test_generic_sequence_container_reuses_workers(self):
        before = {child.pid for child in multiprocessing.active_children()}
        with ParallelSearchPool(deque([1, 2, 2, 2, 2, 3]), 2) as pool:
            self.assertEqual(pool.search_many([2, 3, 0]), [1, 5, None])
            self.assertEqual(pool.search_many([1, 2, 4]), [0, 1, None])
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)

    def test_pool_starts_all_workers_and_reuses_them_across_batches(self):
        before = {child.pid for child in multiprocessing.active_children()}
        with ParallelSearchPool([1, 2, 2, 3, 4, 5], 2) as pool:
            self.assertEqual(pool.worker_count, 2)
            started = {child.pid for child in multiprocessing.active_children()} - before
            self.assertEqual(len(started), 2)
            self.assertEqual(pool.search_many([5, 2, 6]), [5, 1, None])
            self.assertEqual(pool.search_many([1, 4, 2, 2]), [0, 4, 1, 1])
            self.assertEqual(
                {child.pid for child in multiprocessing.active_children()} - before,
                started,
            )
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)

    def test_reused_worker_gc_policy(self):
        with ParallelSearchPool([1, 2, 3, 4], 2, require_disabled_gc, disable_gc=True) as pool:
            self.assertEqual(pool.search_many([1, 4]), [0, 3])
            self.assertEqual(pool.search_many([2, 3]), [1, 2])

    def test_pool_failure_closes_workers_even_if_caller_catches_error(self):
        before = {child.pid for child in multiprocessing.active_children()}
        with ParallelSearchPool([1, 2, 3, 4], 2, raising_search) as pool:
            with self.assertRaisesRegex(RuntimeError, "worker search failed"):
                pool.search_many([2])
            self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)
            with self.assertRaisesRegex(RuntimeError, "active search-pool"):
                pool.search_many([2])

    def test_empty_pool_and_lifecycle(self):
        pool = ParallelSearchPool([], 2)
        with self.assertRaisesRegex(RuntimeError, "active search-pool"):
            pool.search_many([])
        with patch("search_algos.parallel.ProcessPoolExecutor", side_effect=AssertionError):
            with pool:
                self.assertEqual(pool.worker_count, 0)
                self.assertEqual(pool.search_many([1, 2]), [None, None])
                self.assertEqual(pool.search_many([]), [])
        pool.close()
        with self.assertRaisesRegex(RuntimeError, "active search-pool"):
            pool.search_many([])
        with self.assertRaisesRegex(RuntimeError, "only be entered once"):
            pool.__enter__()


if __name__ == "__main__":
    unittest.main()
