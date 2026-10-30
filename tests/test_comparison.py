"""Saved-report comparisons, invalid input, and statistical edge cases."""

import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from search_algos.benchmarks import DEFAULT_DATASETS, BenchmarkConfig, run_benchmarks
from search_algos.comparison import compare_reports, load_report, render_comparison


def report(samples=(10, 20, 30), setup=None, *, version=1, **row_changes):
    row = {
        "algorithm": "binary",
        "workload_id": "same-data-and-queries",
        "dataset": "uniform",
        "size": 10,
        "queries": 4,
        "result_kind": "first_index",
        "timing_scope": "lookup_batch",
        "effective_workers": 0,
        "lookup_samples_ns": list(samples),
        "setup_samples_ns": list(setup) if setup is not None else [0] * len(samples),
    }
    if version == 2:
        row.update(
            status="complete",
            gc_mode="disabled",
            repetitions=max(1, len(samples)),
            warmups=0,
            repetitions_completed=len(samples),
            warmups_completed=0,
            completed_queries=len(samples) * row["queries"],
        )
    row.update(row_changes)
    return {
        "schema_version": version,
        "metadata": {
            "cpu_model": "test CPU",
            "platform": "test OS",
            "machine": "test machine",
            "python_version": "3.11",
            "python_implementation": "CPython",
            "package_version": "0.2.0",
            "git_commit": "old-commit",
        },
        "config": {},
        "results": [row],
    }


class ComparisonTests(unittest.TestCase):
    def test_speedup_uses_raw_samples_and_pairs_setup_with_lookup(self):
        baseline = report([0, 100, 0], setup=[100, 0, 100])
        candidate = report([50, 50, 50], total_median_ns=99999)
        row = compare_reports(baseline, candidate)["comparisons"][0]
        self.assertEqual(row["baseline_median_ns"], 100)
        self.assertEqual(row["candidate_median_ns"], 50)
        self.assertEqual(row["speedup"], 2)
        self.assertFalse(row["iqr_overlap"])
        lookup = compare_reports(baseline, candidate, metric="lookup")["comparisons"][0]
        self.assertEqual(lookup["baseline_median_ns"], 0)
        self.assertEqual(lookup["speedup"], 0)

    def test_quartiles_are_actual_asymmetric_intervals(self):
        row = compare_reports(report([0, 0, 0, 100]), report([1, 2, 3, 4]))["comparisons"][0]
        self.assertEqual((row["baseline_q1_ns"], row["baseline_q3_ns"]), (0, 25))
        self.assertEqual((row["candidate_q1_ns"], row["candidate_q3_ns"]), (1.75, 3.25))
        self.assertTrue(row["iqr_overlap"])

    def test_single_samples_have_no_overlap_claim(self):
        row = compare_reports(report([10]), report([5]))["comparisons"][0]
        self.assertEqual(row["speedup"], 2)
        self.assertIsNone(row["iqr_overlap"])
        self.assertIsNone(row["baseline_q1_ns"])

    def test_zero_denominators(self):
        row = compare_reports(report([10, 10]), report([0, 0]))["comparisons"][0]
        self.assertIsNone(row["speedup"])
        self.assertIn("undefined", row["reason"])
        both = compare_reports(report([0, 0]), report([0, 0]))["comparisons"][0]
        self.assertEqual(both["speedup"], 1)

    def test_extreme_finite_samples_do_not_emit_infinite_statistics(self):
        compared = compare_reports(report([1e308, 1e308]), report([1e-308, 1e-308]))
        row = compared["comparisons"][0]
        self.assertEqual(row["baseline_median_ns"], 1e308)
        self.assertEqual(row["baseline_q1_ns"], 1e308)
        self.assertIsNone(row["speedup"])
        json.loads(render_comparison(compared, "json"))
        with self.assertRaises(ValueError):
            compare_reports(report([1e308], setup=[1e308]), report())

    def test_identity_includes_algorithm_result_kind_and_timing_scope(self):
        for field, value in (
            ("algorithm", "set"),
            ("result_kind", "membership"),
            ("timing_scope", "batch_reused_pool"),
            ("workload_id", "other-workload"),
        ):
            with self.subTest(field=field):
                candidate = report(**{field: value})
                rows = compare_reports(report(), candidate)["comparisons"]
                self.assertEqual(
                    [row["status"] for row in rows], ["missing_candidate", "missing_baseline"]
                )
                self.assertTrue(all(row["speedup"] is None for row in rows))

    def test_skipped_and_incomplete_rows_are_retained_without_comparison(self):
        for status, samples in (("skipped", []), ("incomplete", [5])):
            with self.subTest(status=status):
                candidate = report(
                    samples, version=2, status=status, repetitions=3, reason="budget exceeded"
                )
                row = compare_reports(report(version=2), candidate)["comparisons"][0]
                self.assertEqual(row["status"], status)
                self.assertIn("budget exceeded", row["reason"])
                self.assertIsNone(row["speedup"])
                self.assertIsNone(row["iqr_overlap"])

    def test_same_workload_in_different_scenarios_matches_by_scenario(self):
        baseline = report([10, 20, 30], dataset="uniform")
        second = report([100, 200, 300], dataset="duplicates")["results"][0]
        baseline["results"].append(second)
        candidate = report([50, 100, 150], dataset="duplicates")
        candidate["results"].append(report([10, 20, 30], dataset="uniform")["results"][0])
        compared = compare_reports(baseline, candidate)
        rows = compared["comparisons"]
        self.assertEqual([row["dataset"] for row in rows], ["uniform", "duplicates"])
        self.assertEqual([row["speedup"] for row in rows], [1, 2])
        self.assertTrue(all(row["status"] == "compared" for row in rows))
        self.assertTrue(
            any("matched by dataset and size" in warning for warning in compared["warnings"])
        )

    def test_ambiguous_scenarios_without_matching_labels_remain_missing(self):
        baseline = report(dataset="uniform")
        baseline["results"].append(report(dataset="duplicates")["results"][0])
        rows = compare_reports(baseline, report(dataset="renamed"))["comparisons"]
        self.assertEqual(
            [row["status"] for row in rows],
            ["missing_candidate", "missing_candidate", "missing_baseline"],
        )

    def test_unique_workloads_can_match_across_renamed_dataset_labels(self):
        rows = compare_reports(report(dataset="old"), report(dataset="new"))["comparisons"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "compared")
        self.assertEqual(rows[0]["speedup"], 1)

    def test_conflicting_known_workload_dimensions_are_incomparable(self):
        for dimensions in ({"size": 1000000}, {"queries": 400}, {"size": 1000000, "queries": 400}):
            with self.subTest(dimensions=dimensions):
                row = compare_reports(report(), report([5, 10, 15], **dimensions))["comparisons"][0]
                self.assertEqual(row["status"], "incomparable")
                self.assertIsNone(row["speedup"])
                self.assertIsNone(row["iqr_overlap"])
                for dimension in dimensions:
                    self.assertIn(f"{dimension} differs", row["reason"])

    def test_legacy_config_query_counts_participate_in_compatibility(self):
        baseline = report()
        del baseline["results"][0]["queries"]
        baseline["config"]["queries"] = 100
        for config_only in (False, True):
            candidate = report(queries=100000)
            if config_only:
                del candidate["results"][0]["queries"]
                candidate["config"]["queries"] = 100000
            with self.subTest(config_only=config_only):
                row = compare_reports(baseline, candidate)["comparisons"][0]
                self.assertEqual(row["status"], "incomparable")
                self.assertIsNone(row["speedup"])
                self.assertIn("queries differs: 100 versus 100000", row["reason"])
        matching = report(queries=100)
        self.assertEqual(compare_reports(baseline, matching)["comparisons"][0]["speedup"], 1)
        self.assertNotIn("queries", baseline["results"][0])

    def test_empty_workloads_self_compare_without_collapsing_dataset_rows(self):
        generated = run_benchmarks(
            BenchmarkConfig(
                sizes=(0,),
                datasets=DEFAULT_DATASETS,
                algorithms=("binary",),
                queries=1,
                warmups=0,
                repetitions=1,
                time_budget=0,
            )
        )
        self.assertEqual(len({row["workload_id"] for row in generated["results"]}), 1)
        rows = compare_reports(generated, generated)["comparisons"]
        self.assertEqual([row["dataset"] for row in rows], list(DEFAULT_DATASETS))
        self.assertTrue(all(row["status"] == "compared" for row in rows))
        self.assertTrue(all(row["speedup"] == 1 for row in rows))

    def test_different_known_gc_policies_are_incomparable(self):
        baseline = report(version=2, gc_mode="enabled")
        row = compare_reports(baseline, report(version=2))["comparisons"][0]
        self.assertEqual(row["status"], "incomparable")
        self.assertIn("GC policies differ", row["reason"])
        self.assertIsNone(row["speedup"])

    def test_legacy_unknown_gc_warns_but_comparison_remains_available(self):
        compared = compare_reports(report(), report(version=2))
        self.assertEqual(compared["comparisons"][0]["status"], "compared")
        self.assertTrue(any("GC policy" in warning for warning in compared["warnings"]))

    def test_environment_and_worker_differences_warn_but_code_versions_can_differ(self):
        baseline = report(version=2, effective_workers=2)
        candidate = report(version=2, effective_workers=4)
        candidate["metadata"].update(
            cpu_model="other CPU",
            python_version="3.12",
            package_version="0.3.0",
            git_commit="new-commit",
        )
        compared = compare_reports(baseline, candidate)
        self.assertEqual(compared["comparisons"][0]["status"], "compared")
        self.assertTrue(any("cpu_model differs" in warning for warning in compared["warnings"]))
        self.assertTrue(
            any("python_version differs" in warning for warning in compared["warnings"])
        )
        self.assertTrue(compared["comparisons"][0]["warnings"])
        self.assertFalse(any("git_commit" in warning for warning in compared["warnings"]))

    def test_missing_optional_metadata_is_graceful(self):
        candidate = report()
        del candidate["metadata"]
        compared = compare_reports(report(), candidate)
        self.assertEqual(compared["comparisons"][0]["speedup"], 1)
        self.assertTrue(compared["warnings"])

    def test_invalid_samples_and_status_are_rejected(self):
        invalid = [
            report([]),
            report([True]),
            report([-1]),
            report([float("nan")]),
            report([float("inf")]),
            report(["2"]),
            report([10**400]),
            report([1, 2], setup=[1]),
            report([1], version=2, status="skipped"),
            report([1], version=2, status="unknown"),
            report([1], gc_mode="sometimes"),
            report([1], size=True),
            report([1], version=2),
        ]
        del invalid[-1]["results"][0]["status"]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                compare_reports(data, report())

    def test_schema_two_requires_completion_evidence(self):
        for field in (
            "queries",
            "repetitions",
            "warmups",
            "repetitions_completed",
            "warmups_completed",
            "completed_queries",
        ):
            candidate = report(version=2)
            del candidate["results"][0][field]
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, rf"candidate results\[0\] {field}"),
            ):
                compare_reports(report(), candidate)

    def test_count_fields_reject_invalid_types_and_ranges(self):
        for field in (
            "queries",
            "repetitions",
            "warmups",
            "repetitions_completed",
            "warmups_completed",
            "completed_queries",
        ):
            invalid_values = [True, False, -1, 1.5, "1", None]
            if field in ("queries", "repetitions"):
                invalid_values.append(0)
            for value in invalid_values:
                for location in (
                    ("row", "config")
                    if field in ("queries", "repetitions", "warmups")
                    else ("row",)
                ):
                    candidate = report(version=2)
                    destination = (
                        candidate["results"][0] if location == "row" else candidate["config"]
                    )
                    destination[field] = value
                    with self.subTest(field=field, value=value, location=location):
                        with self.assertRaisesRegex(ValueError, field):
                            compare_reports(report(), candidate)

    def test_progress_counts_and_status_must_match_samples(self):
        for changes, message in (
            ({"repetitions_completed": 2}, "repetitions_completed"),
            ({"completed_queries": 11}, "completed_queries"),
            ({"repetitions": 2}, "exceeds requested repetitions"),
            ({"repetitions": 4}, "complete but timing sample count"),
            ({"warmups": 2, "warmups_completed": 3}, "warmups_completed exceeds"),
            ({"warmups": 2, "warmups_completed": 1}, "before all warmups"),
            ({"status": "incomplete"}, "all requested repetitions are present"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                compare_reports(report(), report(version=2, **changes))
        with self.assertRaisesRegex(ValueError, "incomplete but has no timing samples"):
            compare_reports(report(), report([], version=2, status="incomplete", repetitions=3))

    def test_requested_counts_must_agree_with_config(self):
        for field, value in (("queries", 5), ("repetitions", 4), ("warmups", 1)):
            candidate = report(version=2)
            candidate["config"][field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    ValueError, rf"candidate results\[0\] {field} conflicts with config"
                ),
            ):
                compare_reports(report(), candidate)

    def test_truncated_complete_report_is_rejected_on_load_and_compare(self):
        generated = run_benchmarks(
            BenchmarkConfig(
                sizes=(10,),
                datasets=("uniform",),
                algorithms=("binary",),
                queries=4,
                repetitions=3,
                warmups=1,
                time_budget=0,
            )
        )
        row = generated["results"][0]
        row["setup_samples_ns"] = row["setup_samples_ns"][:1]
        row["lookup_samples_ns"] = row["lookup_samples_ns"][:1]
        row["repetitions_completed"] = 1
        row["completed_queries"] = 4
        with self.assertRaisesRegex(ValueError, "complete but timing sample count"):
            compare_reports(report(), generated)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.json"
            path.write_text(json.dumps(generated), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complete but timing sample count"):
                load_report(path)

    def test_legacy_counts_are_optional_but_checked_when_present(self):
        legacy = report()
        legacy["config"].update(queries=4, repetitions=3, warmups=1)
        self.assertEqual(compare_reports(legacy, legacy)["comparisons"][0]["speedup"], 1)
        legacy["results"][0].update(repetitions_completed=3, completed_queries=12)
        self.assertEqual(compare_reports(legacy, legacy)["comparisons"][0]["speedup"], 1)
        for changes in (
            {"repetitions_completed": 2},
            {"completed_queries": 11},
            {"warmups_completed": 0},
            {"queries": 5},
        ):
            invalid = copy.deepcopy(legacy)
            invalid["results"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                compare_reports(legacy, invalid)
        legacy["config"]["repetitions"] = 4
        with self.assertRaisesRegex(ValueError, "complete but timing sample count"):
            compare_reports(legacy, legacy)

    def test_generated_complete_incomplete_and_skipped_reports_are_accepted(self):
        options = dict(
            sizes=(5,),
            datasets=("uniform",),
            algorithms=("binary",),
            queries=2,
            repetitions=3,
        )
        complete = run_benchmarks(BenchmarkConfig(**options, warmups=1, time_budget=0))
        self.assertEqual(
            compare_reports(complete, complete)["comparisons"][0]["status"], "compared"
        )
        for warmups, status in ((0, "incomplete"), (1, "skipped"), (2, "skipped")):
            with patch("search_algos.benchmarks.perf_counter", side_effect=[0, 2]):
                generated = run_benchmarks(
                    BenchmarkConfig(**options, warmups=warmups, time_budget=1)
                )
            with self.subTest(warmups=warmups, status=status):
                self.assertEqual(generated["results"][0]["status"], status)
                self.assertEqual(
                    compare_reports(generated, generated)["comparisons"][0]["status"], status
                )
        options["algorithms"] = ("linear",)
        skipped = run_benchmarks(BenchmarkConfig(**options, warmups=2, max_linear_work=1))
        self.assertEqual(skipped["results"][0]["warmups_completed"], 0)
        self.assertEqual(compare_reports(skipped, skipped)["comparisons"][0]["status"], "skipped")

    def test_invalid_structure_schema_and_duplicate_identities_are_rejected(self):
        duplicate = report()
        duplicate["results"].append(copy.deepcopy(duplicate["results"][0]))
        missing_identity = report()
        del missing_identity["results"][0]["algorithm"]
        for data in (
            [],
            {},
            {"schema_version": True},
            report(version=3),
            duplicate,
            missing_identity,
            {"schema_version": 1, "results": [None]},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                compare_reports(data, report())
        with self.assertRaises(ValueError):
            compare_reports(report(), report(), metric="unknown")

    def test_renderers_cover_missing_and_complete_rows(self):
        candidate = report([5, 10, 15])
        extra = copy.deepcopy(candidate["results"][0])
        extra["algorithm"] = "jump"
        candidate["results"].append(extra)
        compared = compare_reports(report(), candidate)
        text = render_comparison(compared)
        self.assertIn("2.00x", text)
        self.assertIn("missing_baseline", text)
        self.assertIn("not a statistical significance test", text)
        self.assertEqual(json.loads(render_comparison(compared, "json"))["metric"], "total")
        rows = list(csv.DictReader(io.StringIO(render_comparison(compared, "csv"))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["speedup"], "2.0")
        self.assertTrue(json.loads(rows[0]["report_warnings"]))
        with self.assertRaises(ValueError):
            render_comparison(compared, "unknown")

    def test_empty_reports_render_cleanly(self):
        empty = report()
        empty["results"] = []
        compared = compare_reports(empty, empty)
        self.assertIn("No result rows", render_comparison(compared))
        self.assertIn("workload_id", render_comparison(compared, "csv"))

    def test_load_report_validates_files_and_rejects_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report()), encoding="utf-8")
            self.assertEqual(load_report(path)["schema_version"], 1)
            for contents in (
                "not json",
                "[]",
                '{"value": NaN}',
                '{"schema_version": 1, "schema_version": 2}',
            ):
                path.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents), self.assertRaises(ValueError):
                    load_report(path)
            with self.assertRaises(ValueError):
                load_report(Path(directory) / "missing.json")

    def test_load_report_rejects_excessive_json_nesting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested.json"
            path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON nesting is too deep"):
                load_report(path)


if __name__ == "__main__":
    unittest.main()
