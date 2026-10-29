"""Workload, correctness-gating, and measurement regression tests."""

import random
import statistics
import unittest
from unittest.mock import patch

from search_algos.benchmarks import (
    DATASET_NAMES,
    DEFAULT_ALGORITHMS,
    INDEX_ALGORITHMS,
    BenchmarkConfig,
    make_workload,
    run_benchmarks,
    verify_results,
)


class WorkloadTests(unittest.TestCase):
    def test_seed_reproduces_data_queries_and_identifier_without_global_rng_changes(self):
        state = random.getstate()
        first = make_workload(100, "gapped", seed=42)
        self.assertEqual(make_workload(100, "gapped", seed=42), first)
        self.assertNotEqual(make_workload(100, "gapped", seed=43).workload_id, first.workload_id)
        self.assertEqual(random.getstate(), state)

    def test_workloads_have_known_hits_misses_and_first_indices(self):
        for dataset in DATASET_NAMES:
            for size in (0, 1, 25, 200):
                for hit_rate in (0, 0.5, 1):
                    with self.subTest(dataset=dataset, size=size, hit_rate=hit_rate):
                        workload = make_workload(size, dataset, queries=20, hit_rate=hit_rate)
                        self.assertEqual(len(workload.values), size)
                        self.assertEqual(tuple(sorted(workload.values)), workload.values)
                        self.assertEqual(len(workload.targets), 20)
                        expected = tuple(
                            workload.values.index(target) if target in workload.values else None
                            for target in workload.targets
                        )
                        self.assertEqual(workload.expected_indices, expected)
                        self.assertEqual(sum(index is not None for index in expected), round(20 * hit_rate) if size else 0)

    def test_misses_include_inside_and_outside_the_data_range(self):
        workload = make_workload(100, "gapped", queries=20, hit_rate=0)
        low, high = workload.values[0], workload.values[-1]
        self.assertTrue(any(target < low for target in workload.targets))
        self.assertTrue(any(low < target < high for target in workload.targets))
        self.assertTrue(any(target > high for target in workload.targets))

    def test_distributions_include_duplicates_and_nonuniform_gaps(self):
        repeated = make_workload(100, "duplicates").values
        self.assertLess(len(set(repeated)), len(repeated))
        for dataset in ("gapped", "skewed"):
            values = make_workload(100, dataset).values
            self.assertGreater(len({b - a for a, b in zip(values, values[1:])}), 1)


class BenchmarkTests(unittest.TestCase):
    def test_invalid_configuration_is_rejected(self):
        invalid = [
            {"sizes": ()}, {"sizes": (-1,)}, {"sizes": (True,)},
            {"sizes": (1, 1)}, {"datasets": ()}, {"datasets": ("unknown",)},
            {"algorithms": ()}, {"algorithms": ("binary", "binary")},
            {"algorithms": ("unknown",)}, {"queries": 0}, {"queries": 1.5},
            {"repetitions": 0}, {"warmups": -1}, {"workers": 0},
            {"workers": True}, {"seed": 1.5}, {"hit_rate": -0.1},
            {"hit_rate": 1.1}, {"hit_rate": float("nan")}, {"hit_rate": float("inf")},
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                BenchmarkConfig(**arguments)

    def test_all_sequential_algorithms_validate_on_all_distributions(self):
        config = BenchmarkConfig(sizes=(0, 1, 40), queries=8, repetitions=2, warmups=1)
        report = run_benchmarks(config)
        self.assertEqual(len(report["results"]), 3 * 4 * len(DEFAULT_ALGORITHMS))
        ids = {}
        for row in report["results"]:
            key = (row["size"], row["dataset"])
            ids.setdefault(key, row["workload_id"])
            self.assertEqual(ids[key], row["workload_id"])
            self.assertEqual(len(row["lookup_samples_ns"]), 2)
            self.assertEqual(len(row["setup_samples_ns"]), 2)
            self.assertEqual(row["hits"] + row["misses"], 8)
            self.assertEqual(row["lookup_median_ns"], statistics.median(row["lookup_samples_ns"]))
            total = [a + b for a, b in zip(row["setup_samples_ns"], row["lookup_samples_ns"])]
            self.assertEqual(row["total_median_ns"], statistics.median(total))
            self.assertGreaterEqual(row["lookup_iqr_ns"], 0)
            self.assertEqual(row["per_query_median_ns"], row["lookup_median_ns"] / 8)
            if row["algorithm"] != "set":
                self.assertEqual(row["setup_samples_ns"], [0, 0])
            if row["size"] == 0:
                self.assertEqual(row["actual_hit_rate"], 0)
        self.assertIn("python_version", report["metadata"])
        self.assertEqual(report["metadata"]["timer"], "perf_counter_ns")

    def test_wrong_results_abort_the_run(self):
        with patch.dict(INDEX_ALGORITHMS, {"binary": lambda values, target: None}):
            with self.assertRaisesRegex(RuntimeError, "binary returned"):
                run_benchmarks(BenchmarkConfig(
                    sizes=(10,), datasets=("uniform",), algorithms=("binary",),
                    queries=4, hit_rate=1, repetitions=1, warmups=0,
                ))

    def test_result_validation_distinguishes_boolean_from_index_zero(self):
        workload = make_workload(1, "uniform", queries=1, hit_rate=1)
        verify_results("binary", [0], workload)
        verify_results("set", [True], workload)
        for algorithm, results in (("binary", [False]), ("set", [0]), ("binary", [])):
            with self.subTest(algorithm=algorithm, results=results), self.assertRaises(RuntimeError):
                verify_results(algorithm, results, workload)

    def test_single_repetition_has_zero_iqr(self):
        report = run_benchmarks(BenchmarkConfig(
            sizes=(10,), datasets=("uniform",), algorithms=("set",),
            queries=4, repetitions=1, warmups=0,
        ))
        row = report["results"][0]
        self.assertEqual(row["lookup_iqr_ns"], 0)
        self.assertEqual(row["setup_iqr_ns"], 0)

    def test_verification_runs_after_lookup_timer_stops(self):
        # Slow correctness checks must not contaminate the advertised timings.
        timer_calls = []
        def timer():
            timer_calls.append(None)
            return len(timer_calls) * 100
        def verify_after_timing(algorithm, results, workload):
            self.assertEqual(len(timer_calls), 2)
            verify_results(algorithm, results, workload)
        with patch("search_algos.benchmarks.perf_counter_ns", side_effect=timer):
            with patch("search_algos.benchmarks.verify_results", side_effect=verify_after_timing):
                report = run_benchmarks(BenchmarkConfig(
                    sizes=(10,), datasets=("uniform",), algorithms=("binary",),
                    queries=4, repetitions=1, warmups=0,
                ))
        self.assertEqual(report["results"][0]["lookup_samples_ns"], [100])


if __name__ == "__main__":
    unittest.main()
