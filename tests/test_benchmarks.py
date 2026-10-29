"""Workload, correctness-gating, and measurement regression tests."""

import gc
import random
import statistics
import unittest
from unittest.mock import patch

from search_algos.algorithms import build_radix_index
from search_algos.benchmarks import (
    ALGORITHM_NAMES,
    DATASET_NAMES,
    DEFAULT_ALGORITHMS,
    DEFAULT_DATASETS,
    INDEX_ALGORITHMS,
    PREPARED_ALGORITHMS,
    BenchmarkConfig,
    make_workload,
    run_benchmarks,
    verify_results,
)
from search_algos.comparison import compare_reports
from search_algos.prepared import build_first_index_reversed

NEW_PREPARED_NAMES = ("neighbor_prepared", "dict_reverse", "guarded_prepared", "adaptive_index")


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
                        self.assertEqual(
                            sum(index is not None for index in expected),
                            round(20 * hit_rate) if size else 0,
                        )

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
    def test_prepared_algorithms_are_selected_by_default_and_preserve_baselines(self):
        defaults = (
            "linear",
            "binary",
            "bisect",
            "recursive",
            "interpolation",
            "interpolation_hybrid",
            "exponential",
            "jump",
            "set",
            "dict",
            "radix",
        )
        self.assertEqual(DEFAULT_ALGORITHMS[: len(defaults)], defaults)
        self.assertEqual(set(DEFAULT_ALGORITHMS), set(defaults + NEW_PREPARED_NAMES))
        self.assertEqual(len(DEFAULT_ALGORITHMS), 15)
        self.assertEqual(BenchmarkConfig().algorithms, DEFAULT_ALGORITHMS)
        self.assertEqual(ALGORITHM_NAMES, (*DEFAULT_ALGORITHMS, "parallel", "parallel_warm"))
        self.assertEqual(len(ALGORITHM_NAMES), 17)
        for name in (*defaults, *NEW_PREPARED_NAMES, "parallel", "parallel_warm"):
            with self.subTest(algorithm=name):
                self.assertEqual(ALGORITHM_NAMES.count(name), 1)
        for name in NEW_PREPARED_NAMES:
            with self.subTest(algorithm=name):
                self.assertEqual(DEFAULT_ALGORITHMS.count(name), 1)
                self.assertNotIn(name, INDEX_ALGORITHMS)
                self.assertEqual(BenchmarkConfig(algorithms=(name,)).algorithms, (name,))

    def test_radix_is_selected_by_default_and_available_once_in_all(self):
        self.assertIn("radix", ALGORITHM_NAMES)
        self.assertIn("radix", DEFAULT_ALGORITHMS)
        self.assertIn("radix", BenchmarkConfig().algorithms)
        self.assertEqual(ALGORITHM_NAMES.count("radix"), 1)
        self.assertNotIn("radix", INDEX_ALGORITHMS)
        self.assertEqual(BenchmarkConfig(algorithms=("radix",)).algorithms, ("radix",))

    def test_prepared_benchmarks_validate_all_distributions_and_compare(self):
        algorithms = ("radix", *NEW_PREPARED_NAMES)
        report = run_benchmarks(
            BenchmarkConfig(
                sizes=(0, 1, 40, 1000),
                datasets=DATASET_NAMES,
                algorithms=algorithms,
                queries=16,
                repetitions=2,
                warmups=1,
                time_budget=0,
            )
        )
        self.assertEqual(len(report["results"]), 4 * len(DATASET_NAMES) * len(algorithms))
        for row in report["results"]:
            with self.subTest(algorithm=row["algorithm"], size=row["size"], dataset=row["dataset"]):
                self.assertEqual(row["status"], "complete")
                self.assertEqual(row["result_kind"], "first_index")
                self.assertEqual(row["timing_scope"], "lookup_batch")
                self.assertEqual(row["effective_workers"], 0)
                self.assertEqual(row["repetitions_completed"], 2)
                self.assertEqual(row["warmups_completed"], 1)
                self.assertEqual(len(row["setup_samples_ns"]), 2)
                self.assertEqual(len(row["lookup_samples_ns"]), 2)
                totals = [
                    setup + lookup
                    for setup, lookup in zip(row["setup_samples_ns"], row["lookup_samples_ns"])
                ]
                self.assertEqual(row["total_median_ns"], statistics.median(totals))
        compared = compare_reports(report, report)
        self.assertEqual(len(compared["comparisons"]), len(report["results"]))
        self.assertTrue(all(row["status"] == "compared" for row in compared["comparisons"]))
        self.assertTrue(all(row["speedup"] == 1 for row in compared["comparisons"]))

    def test_radix_build_and_lookup_have_separate_timers_each_batch(self):
        ticks = iter((0, 30, 50, 150, 200, 240, 250, 360, 400, 450, 470, 590))
        timer_calls = []
        lookups = []

        def timer():
            timer_calls.append(None)
            return next(ticks)

        def prepare(values):
            self.assertEqual(len(timer_calls) % 4, 1)
            self.assertFalse(gc.isenabled())
            search = build_radix_index(values)

            def lookup(target):
                self.assertEqual(len(timer_calls) % 4, 3)
                self.assertFalse(gc.isenabled())
                lookups.append(target)
                return search(target)

            return lookup

        def verify_after_timing(algorithm, results, workload):
            self.assertEqual(len(timer_calls) % 4, 0)
            verify_results(algorithm, results, workload)

        with (
            patch("search_algos.benchmarks.perf_counter_ns", side_effect=timer),
            patch("search_algos.benchmarks.build_radix_index", side_effect=prepare) as builder,
            patch("search_algos.benchmarks.verify_results", side_effect=verify_after_timing),
        ):
            report = run_benchmarks(
                BenchmarkConfig(
                    sizes=(10,),
                    datasets=("uniform",),
                    algorithms=("radix",),
                    queries=4,
                    repetitions=2,
                    warmups=1,
                    time_budget=0,
                )
            )
        row = report["results"][0]
        self.assertEqual(builder.call_count, 3)
        self.assertEqual(len(lookups), 12)
        self.assertEqual(row["setup_samples_ns"], [40, 50])
        self.assertEqual(row["lookup_samples_ns"], [110, 120])
        self.assertEqual(row["total_median_ns"], 160)

    def test_incorrect_radix_lookup_aborts_the_benchmark(self):
        with patch("search_algos.benchmarks.build_radix_index", return_value=lambda target: None):
            with self.assertRaisesRegex(RuntimeError, "radix returned"):
                run_benchmarks(
                    BenchmarkConfig(
                        sizes=(10,),
                        datasets=("duplicates",),
                        algorithms=("radix",),
                        queries=4,
                        hit_rate=1,
                        repetitions=1,
                        warmups=0,
                    )
                )

    def test_new_prepared_build_and_lookup_have_separate_timers_each_batch(self):
        for algorithm in NEW_PREPARED_NAMES:
            with self.subTest(algorithm=algorithm):
                original = (
                    build_first_index_reversed
                    if algorithm == "dict_reverse"
                    else PREPARED_ALGORITHMS[algorithm]
                )
                ticks = iter((0, 30, 50, 150, 200, 240, 250, 360, 400, 450, 470, 590))
                timer_calls, builds, lookups = [], [], []

                def timer():
                    timer_calls.append(None)
                    return next(ticks)

                def prepare(values):
                    self.assertEqual(len(timer_calls) % 4, 1)
                    self.assertFalse(gc.isenabled())
                    builds.append(values)
                    prepared = original(values)
                    search = prepared.get if algorithm == "dict_reverse" else prepared

                    def lookup(target):
                        self.assertEqual(len(timer_calls) % 4, 3)
                        self.assertFalse(gc.isenabled())
                        lookups.append(target)
                        return search(target)

                    if algorithm == "dict_reverse":

                        class ObservedDictionary(dict):
                            def get(self, target):
                                return lookup(target)

                        return ObservedDictionary(prepared)
                    return lookup

                def verify_after_timing(name, results, workload):
                    self.assertEqual(len(timer_calls) % 4, 0)
                    verify_results(name, results, workload)

                replacement = (
                    patch("search_algos.benchmarks.build_first_index_reversed", side_effect=prepare)
                    if algorithm == "dict_reverse"
                    else patch.dict(PREPARED_ALGORITHMS, {algorithm: prepare})
                )
                with (
                    replacement,
                    patch("search_algos.benchmarks.perf_counter_ns", side_effect=timer),
                    patch(
                        "search_algos.benchmarks.verify_results", side_effect=verify_after_timing
                    ),
                ):
                    report = run_benchmarks(
                        BenchmarkConfig(
                            sizes=(10,),
                            datasets=("duplicates",),
                            algorithms=(algorithm,),
                            queries=4,
                            repetitions=2,
                            warmups=1,
                            time_budget=0,
                        )
                    )
                row = report["results"][0]
                self.assertEqual(len(builds), 3)
                self.assertEqual(len(lookups), 12)
                self.assertEqual(row["setup_samples_ns"], [40, 50])
                self.assertEqual(row["lookup_samples_ns"], [110, 120])
                self.assertEqual(row["total_median_ns"], 160)

    def test_incorrect_new_prepared_lookups_abort_the_benchmark(self):
        for algorithm in NEW_PREPARED_NAMES:
            replacement = (
                patch("search_algos.benchmarks.build_first_index_reversed", return_value={})
                if algorithm == "dict_reverse"
                else patch.dict(
                    PREPARED_ALGORITHMS, {algorithm: lambda values: lambda target: None}
                )
            )
            with (
                self.subTest(algorithm=algorithm),
                replacement,
                self.assertRaisesRegex(RuntimeError, f"{algorithm} returned"),
            ):
                run_benchmarks(
                    BenchmarkConfig(
                        sizes=(10,),
                        datasets=("duplicates",),
                        algorithms=(algorithm,),
                        queries=4,
                        hit_rate=1,
                        repetitions=1,
                        warmups=0,
                    )
                )

    def test_invalid_configuration_is_rejected(self):
        invalid = [
            {"sizes": ()},
            {"sizes": (-1,)},
            {"sizes": (True,)},
            {"sizes": (1, 1)},
            {"datasets": ()},
            {"datasets": ("unknown",)},
            {"algorithms": ()},
            {"algorithms": ("binary", "binary")},
            {"algorithms": ("unknown",)},
            {"queries": 0},
            {"queries": 1.5},
            {"repetitions": 0},
            {"warmups": -1},
            {"workers": 0},
            {"workers": True},
            {"seed": 1.5},
            {"hit_rate": -0.1},
            {"hit_rate": 1.1},
            {"hit_rate": float("nan")},
            {"hit_rate": float("inf")},
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                BenchmarkConfig(**arguments)

    def test_all_sequential_algorithms_validate_on_all_distributions(self):
        config = BenchmarkConfig(sizes=(0, 1, 40), queries=8, repetitions=2, warmups=1)
        report = run_benchmarks(config)
        self.assertEqual(
            len(report["results"]), 3 * len(DEFAULT_DATASETS) * len(DEFAULT_ALGORITHMS)
        )
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
            if row["algorithm"] in INDEX_ALGORITHMS:
                self.assertEqual(row["setup_samples_ns"], [0, 0])
            if row["size"] == 0:
                self.assertEqual(row["actual_hit_rate"], 0)
        self.assertIn("python_version", report["metadata"])
        self.assertEqual(report["metadata"]["timer"], "perf_counter_ns")

    def test_wrong_results_abort_the_run(self):
        with patch.dict(INDEX_ALGORITHMS, {"binary": lambda values, target: None}):
            with self.assertRaisesRegex(RuntimeError, "binary returned"):
                run_benchmarks(
                    BenchmarkConfig(
                        sizes=(10,),
                        datasets=("uniform",),
                        algorithms=("binary",),
                        queries=4,
                        hit_rate=1,
                        repetitions=1,
                        warmups=0,
                    )
                )

    def test_result_validation_distinguishes_boolean_from_index_zero(self):
        workload = make_workload(1, "uniform", queries=1, hit_rate=1)
        verify_results("binary", [0], workload)
        verify_results("set", [True], workload)
        for algorithm, results in (("binary", [False]), ("set", [0]), ("binary", [])):
            with (
                self.subTest(algorithm=algorithm, results=results),
                self.assertRaises(RuntimeError),
            ):
                verify_results(algorithm, results, workload)

    def test_single_repetition_has_zero_iqr(self):
        report = run_benchmarks(
            BenchmarkConfig(
                sizes=(10,),
                datasets=("uniform",),
                algorithms=("set",),
                queries=4,
                repetitions=1,
                warmups=0,
            )
        )
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
                report = run_benchmarks(
                    BenchmarkConfig(
                        sizes=(10,),
                        datasets=("uniform",),
                        algorithms=("binary",),
                        queries=4,
                        repetitions=1,
                        warmups=0,
                    )
                )
        self.assertEqual(report["results"][0]["lookup_samples_ns"], [100])

    def test_gc_policy_is_applied_and_previous_state_restored(self):
        original = gc.isenabled()
        search = INDEX_ALGORITHMS["binary"]
        observed = []

        def observe(values, target):
            observed.append(gc.isenabled())
            return search(values, target)

        try:
            for previous in (False, True):
                for mode in ("disabled", "enabled"):
                    with self.subTest(previous=previous, mode=mode):
                        gc.enable() if previous else gc.disable()
                        observed.clear()
                        with patch.dict(INDEX_ALGORITHMS, {"binary": observe}):
                            report = run_benchmarks(
                                BenchmarkConfig(
                                    sizes=(5,),
                                    datasets=("uniform",),
                                    algorithms=("binary",),
                                    queries=2,
                                    warmups=0,
                                    repetitions=1,
                                    gc_mode=mode,
                                )
                            )
                        self.assertEqual(observed, [mode == "enabled"] * 2)
                        self.assertEqual(gc.isenabled(), previous)
                        self.assertEqual(report["results"][0]["gc_mode"], mode)
            gc.enable()
            with patch.dict(INDEX_ALGORITHMS, {"binary": lambda values, target: 1 / 0}):
                with self.assertRaises(ZeroDivisionError):
                    run_benchmarks(
                        BenchmarkConfig(
                            sizes=(5,),
                            datasets=("uniform",),
                            algorithms=("binary",),
                            queries=1,
                            warmups=0,
                            repetitions=1,
                        )
                    )
            self.assertTrue(gc.isenabled())
        finally:
            gc.enable() if original else gc.disable()

    def test_linear_work_cap_reports_skip_and_explicit_override(self):
        config = dict(
            sizes=(10,),
            datasets=("uniform",),
            algorithms=("linear", "binary"),
            queries=4,
            repetitions=2,
            warmups=1,
        )
        with patch.dict(
            INDEX_ALGORITHMS,
            {"linear": lambda values, target: self.fail("linear should be skipped")},
        ):
            report = run_benchmarks(BenchmarkConfig(**config, max_linear_work=1))
        linear, binary = report["results"]
        self.assertEqual(linear["status"], "skipped")
        self.assertIn("estimated work 120", linear["reason"])
        self.assertEqual(linear["lookup_samples_ns"], [])
        self.assertIsNone(linear["total_median_ns"])
        self.assertEqual(binary["status"], "complete")
        unlimited = run_benchmarks(BenchmarkConfig(**config, max_linear_work=0, time_budget=0))
        self.assertTrue(all(row["status"] == "complete" for row in unlimited["results"]))

    def test_soft_budget_keeps_partial_samples_without_claiming_completion(self):
        config = dict(
            sizes=(5,),
            datasets=("uniform",),
            queries=2,
            repetitions=3,
            time_budget=1,
        )
        for algorithm in ("binary", "radix", *NEW_PREPARED_NAMES):
            for warmups, status, repetitions in ((0, "incomplete", 1), (1, "skipped", 0)):
                with self.subTest(algorithm=algorithm, warmups=warmups):
                    with patch("search_algos.benchmarks.perf_counter", side_effect=[0, 2]):
                        report = run_benchmarks(
                            BenchmarkConfig(**config, algorithms=(algorithm,), warmups=warmups)
                        )
                    row = report["results"][0]
                    self.assertEqual(row["status"], status)
                    self.assertEqual(row["repetitions_completed"], repetitions)
                    self.assertEqual(row["completed_queries"], repetitions * 2)
                    self.assertEqual(row["warmups_completed"], warmups)
                    self.assertIn("soft time budget", row["reason"])
                    self.assertEqual(
                        compare_reports(report, report)["comparisons"][0]["status"], status
                    )

    def test_new_limits_and_gc_options_are_validated(self):
        for options in (
            {"max_linear_work": -1},
            {"max_linear_work": True},
            {"time_budget": -1},
            {"time_budget": float("nan")},
            {"time_budget": float("inf")},
            {"gc_mode": "auto"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                BenchmarkConfig(**options)

    def test_adversarial_workload_contains_a_dense_prefix_and_deep_target(self):
        workload = make_workload(1000, "adversarial", queries=10, hit_rate=0.5)
        self.assertEqual(workload.values[:-1], tuple(range(0, 1998, 2)))
        self.assertGreater(workload.values[-1], workload.values[-2] * 1000)
        self.assertIn(workload.values[-2], workload.targets)
        self.assertEqual(sum(index is not None for index in workload.expected_indices), 5)

    def test_warm_parallel_reports_lifecycle_separately(self):
        report = run_benchmarks(
            BenchmarkConfig(
                sizes=(10,),
                datasets=("duplicates",),
                algorithms=("parallel_warm",),
                workers=2,
                queries=4,
                repetitions=2,
                warmups=1,
                time_budget=0,
            )
        )
        row = report["results"][0]
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["timing_scope"], "batch_reused_pool")
        self.assertEqual(row["lookup_median_ns"], row["total_median_ns"])
        self.assertEqual(row["setup_samples_ns"], [0, 0])
        self.assertGreater(row["pool_startup_ns"], 0)
        self.assertGreater(row["pool_shutdown_ns"], 0)
        self.assertEqual(row["repetitions_completed"], 2)


if __name__ == "__main__":
    unittest.main()
