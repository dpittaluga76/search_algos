"""Exercise real command entry points and parse their exported reports."""

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from search_algos.benchmarks import ALGORITHM_NAMES
from search_algos.cli import render_report

ROOT = Path(__file__).resolve().parents[1]
SMALL_RUN = [
    "--size",
    "0",
    "1",
    "10",
    "--datasets",
    "duplicates",
    "--queries",
    "4",
    "--repetitions",
    "2",
    "--warmups",
    "0",
    "--algorithms",
    "binary",
    "set",
]


def report_row(
    algorithm,
    total,
    *,
    size=10,
    dataset="uniform",
    result_kind="first_index",
    timing_scope="lookup_batch",
    status="complete",
    workload_id=None,
):
    return {
        "algorithm": algorithm,
        "size": size,
        "dataset": dataset,
        "workload_id": workload_id or f"{dataset}-{size}",
        "result_kind": result_kind,
        "timing_scope": timing_scope,
        "status": status,
        "hits": 2 if size else 0,
        "queries": 4,
        "setup_median_ns": 0 if total is not None else None,
        "lookup_median_ns": total,
        "lookup_iqr_ns": 0 if total is not None else None,
        "total_median_ns": total,
        "per_query_median_ns": total / 4 if total is not None else None,
    }


def benchmark_report(*rows):
    return {
        "metadata": {
            "python_version": "3",
            "python_implementation": "CPython",
            "platform": "test",
        },
        "config": {"seed": 0, "repetitions": 1, "queries": 4, "warmups": 0},
        "results": list(rows),
    }


class CliTests(unittest.TestCase):
    def run_cli(self, *args, script=False):
        command = [sys.executable, "-B"]
        command += ["search_algos.py"] if script else ["-m", "search_algos"]
        return subprocess.run(
            command + list(args), cwd=ROOT, capture_output=True, text=True, timeout=30
        )

    def test_json_stdout_is_a_clean_report(self):
        completed = self.run_cli(*SMALL_RUN, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        report = json.loads(completed.stdout)
        self.assertEqual(len(report["results"]), 6)
        self.assertEqual(report["config"]["sizes"], [0, 1, 10])
        self.assertEqual(report["results"][0]["hits"], 0)

    def test_csv_includes_metadata_and_samples(self):
        completed = self.run_cli(*SMALL_RUN, "--format", "csv")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = list(csv.DictReader(io.StringIO(completed.stdout)))
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["python_version"], sys.version.split()[0])
        self.assertEqual(len(json.loads(rows[0]["lookup_samples_ns"])), 2)
        self.assertEqual(rows[0]["queries"], "4")
        self.assertEqual(rows[0]["actual_hit_rate"], "0.0")

    def test_output_file_and_seed_are_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report with spaces.json"
            completed = self.run_cli(*SMALL_RUN, "--format", "json", "--output", str(path))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "")
            saved = json.loads(path.read_text(encoding="utf-8"))
            second = self.run_cli(*SMALL_RUN, "--format", "json")
            self.assertEqual(second.returncode, 0, second.stderr)
            rerun = json.loads(second.stdout)
            self.assertEqual(
                [row["workload_id"] for row in saved["results"]],
                [row["workload_id"] for row in rerun["results"]],
            )

    def test_invalid_arguments_report_usage_without_tracebacks(self):
        for args in (
            ["--size", "-1"],
            ["--size", "abc"],
            ["--queries", "0"],
            ["--workers", "0"],
            ["--warmups", "-1"],
            ["--repetitions", "0"],
            ["--hit-rate", "nan"],
            ["--hit-rate", "1.1"],
            ["--algorithms", "all", "binary"],
            ["--size", "1", "1"],
        ):
            with self.subTest(args=args):
                completed = self.run_cli(*args)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("error:", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_unwritable_output_location_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing" / "report.json"
            completed = self.run_cli(*SMALL_RUN, "--output", str(path))
            self.assertEqual(completed.returncode, 1)
            self.assertIn("error:", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_all_algorithms_include_parallel_in_a_real_cli_run(self):
        for script in (False, True):
            with self.subTest(script=script):
                completed = self.run_cli(
                    "--size",
                    "10",
                    "--datasets",
                    "gapped",
                    "--algorithms",
                    "all",
                    "--workers",
                    "2",
                    "--queries",
                    "4",
                    "--repetitions",
                    "1",
                    "--warmups",
                    "0",
                    "--time-budget",
                    "0",
                    "--format",
                    "json",
                    script=script,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                rows = json.loads(completed.stdout)["results"]
                self.assertEqual(len(rows), len(ALGORITHM_NAMES))
                parallel = next(row for row in rows if row["algorithm"] == "parallel")
                self.assertEqual(parallel["effective_workers"], 2)
                self.assertEqual(parallel["timing_scope"], "batch_with_process_startup")
                self.assertEqual(parallel["hits"], 2)

    def test_help_and_text_report(self):
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--repetitions", help_result.stdout)
        completed = self.run_cli(*SMALL_RUN)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("lookup IQR", completed.stdout)
        self.assertIn("set", completed.stdout)
        self.assertNotIn("found at positions", completed.stdout)

    def test_text_report_ranks_within_each_workload(self):
        report = benchmark_report(
            report_row("binary", 400),
            report_row("bisect", 100),
            report_row("binary", 50, dataset="skewed"),
            report_row("bisect", 0, dataset="skewed"),
            report_row("binary", 0, size=0),
            report_row("bisect", 0, size=0),
        )
        lines = render_report(report, "text").splitlines()
        headers = [line for line in lines if " size " in line and "queries" in line]
        self.assertEqual(
            headers,
            [
                "uniform, size 10: 2 hits / 4 queries",
                "skewed, size 10: 2 hits / 4 queries",
                "uniform, size 0: 0 hits / 4 queries",
            ],
        )
        first = lines.index(headers[0])
        self.assertTrue(lines[first + 5].startswith("bisect "))
        self.assertTrue(lines[first + 5].endswith("1.00x"))
        self.assertTrue(lines[first + 6].endswith("4.00x"))
        second = lines.index(headers[1])
        self.assertTrue(lines[second + 6].endswith("n/a"))
        third = lines.index(headers[2])
        self.assertTrue(lines[third + 6].endswith("1.00x"))

    def test_text_rankings_separate_result_contracts_and_timing_scopes(self):
        report = benchmark_report(
            report_row("binary", 400),
            report_row("set", 1, result_kind="membership"),
            report_row("parallel", 2, timing_scope="batch_with_process_startup"),
            report_row("parallel_warm", 3, timing_scope="batch_reused_pool"),
            report_row("bisect", 100),
        )
        rendered = render_report(report, "text")
        lines = rendered.splitlines()
        for algorithm, expected_ratio in (
            ("binary", "4.00x"),
            ("bisect", "1.00x"),
            ("set", "1.00x"),
            ("parallel", "1.00x"),
            ("parallel_warm", "1.00x"),
        ):
            with self.subTest(algorithm=algorithm):
                line = next(line for line in lines if line.startswith(algorithm + " "))
                self.assertTrue(line.endswith(expected_ratio), line)
        self.assertEqual(rendered.count("uniform, size 10:"), 4)
        self.assertIn("Result: first_index (first matching index or None)", rendered)
        self.assertIn("Result: membership (whether the target is present (True/False))", rendered)
        self.assertIn("Timing scope: lookup_batch (sequential lookup", rendered)
        self.assertIn("cold pool; includes process startup and shutdown", rendered)
        self.assertIn("reused pool; excludes separately reported startup and shutdown", rendered)
        self.assertIn("parallel_warm lifecycle (excluded from batch totals)", rendered)

    def test_text_rankings_keep_distinct_workload_ids_separate(self):
        report = benchmark_report(
            report_row("binary", 400, workload_id="first-workload"),
            report_row("bisect", 1, workload_id="second-workload"),
        )
        rendered = render_report(report, "text")
        self.assertIn("Workload: first-workload", rendered)
        self.assertIn("Workload: second-workload", rendered)
        for line in rendered.splitlines():
            if line.startswith(("binary ", "bisect ")):
                self.assertTrue(line.endswith("1.00x"), line)

    def test_text_rankings_exclude_incomplete_and_skipped_rows(self):
        report = benchmark_report(
            report_row("binary", 400),
            report_row("bisect", 1, status="incomplete"),
            report_row("linear", None, status="skipped"),
            report_row("set", 1, status="incomplete", result_kind="membership"),
        )
        lines = render_report(report, "text").splitlines()
        complete = next(line for line in lines if line.startswith("binary "))
        self.assertTrue(complete.endswith("1.00x"), complete)
        for algorithm in ("bisect", "linear", "set"):
            with self.subTest(algorithm=algorithm):
                line = next(line for line in lines if line.startswith(algorithm + " "))
                self.assertTrue(line.endswith("n/a"), line)

    def test_skipped_rows_are_explicit_in_text_json_and_csv(self):
        arguments = [
            "--size",
            "100",
            "--datasets",
            "uniform",
            "--algorithms",
            "linear",
            "binary",
            "--queries",
            "4",
            "--repetitions",
            "1",
            "--warmups",
            "0",
            "--max-linear-work",
            "1",
        ]
        for output_format in ("text", "json", "csv"):
            with self.subTest(output_format=output_format):
                completed = self.run_cli(*arguments, "--format", output_format)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                if output_format == "json":
                    row = json.loads(completed.stdout)["results"][0]
                    self.assertEqual(row["status"], "skipped")
                    self.assertIsNone(row["lookup_median_ns"])
                elif output_format == "csv":
                    row = next(csv.DictReader(io.StringIO(completed.stdout)))
                    self.assertEqual(row["status"], "skipped")
                    self.assertEqual(row["lookup_median_ns"], "")
                else:
                    self.assertIn("skipped", completed.stdout)
                    self.assertIn("estimated work", completed.stdout)

    def test_compare_command_accepts_saved_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "baseline.json"
            generated = self.run_cli(*SMALL_RUN, "--format", "json", "--output", str(source))
            self.assertEqual(generated.returncode, 0, generated.stderr)
            completed = self.run_cli("compare", str(source), str(source), "--format", "json")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            comparisons = json.loads(completed.stdout)["comparisons"]
            self.assertEqual(len(comparisons), 6)
            self.assertTrue(all(row["status"] == "compared" for row in comparisons))
            self.assertTrue(all(row["speedup"] == 1 for row in comparisons))
            for output_format in ("text", "csv"):
                output = self.run_cli(
                    "compare", str(source), str(source), "--format", output_format, script=True
                )
                self.assertEqual(output.returncode, 0, output.stderr)
                self.assertIn("binary", output.stdout)

    def test_compare_reports_invalid_files_without_tracebacks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            for content in ("not json", "[]", '{"schema_version": 999}'):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    completed = self.run_cli("compare", str(path), str(path))
                    self.assertEqual(completed.returncode, 1)
                    self.assertIn("error:", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)

    def test_compare_rejects_truncated_complete_report_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "truncated.json"
            generated = self.run_cli(*SMALL_RUN, "--format", "json", "--output", str(source))
            self.assertEqual(generated.returncode, 0, generated.stderr)
            report = json.loads(source.read_text(encoding="utf-8"))
            row = report["results"][0]
            row["setup_samples_ns"] = row["setup_samples_ns"][:1]
            row["lookup_samples_ns"] = row["lookup_samples_ns"][:1]
            row["repetitions_completed"] = 1
            row["completed_queries"] = row["queries"]
            source.write_text(json.dumps(report), encoding="utf-8")
            completed = self.run_cli("compare", str(source), str(source))
            self.assertEqual(completed.returncode, 1)
            self.assertIn("error:", completed.stderr)
            self.assertIn("complete", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
