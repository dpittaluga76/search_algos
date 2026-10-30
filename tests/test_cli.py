"""Exercise real command entry points and parse their exported reports."""

import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from search_algos.benchmarks import ADDITIONAL_ALGORITHMS, ALGORITHM_NAMES
from search_algos.cli import main, render_report
from search_algos.naming import ALGORITHM_LABELS, format_algorithm

ROOT = Path(__file__).resolve().parents[1]
PREPARED_ALGORITHMS = (
    "neighbor_prepared",
    "dict_reverse",
    "guarded_prepared",
    "adaptive_index",
    "landmark_index",
)
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

    def test_closed_stdout_pipes_report_errors_before_interpreter_shutdown(self):
        saved = benchmark_report(report_row("binary", 2))
        saved["schema_version"] = 1
        saved["results"][0].update(setup_samples_ns=[0], lookup_samples_ns=[2])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "baseline.json"
            source.write_text(json.dumps(saved), encoding="utf-8")
            benchmark = [
                "--size",
                "10",
                "--datasets",
                "uniform",
                "--queries",
                "2",
                "--repetitions",
                "1",
                "--warmups",
                "0",
                "--algorithms",
                "binary",
            ]
            for arguments in (benchmark, ["compare", str(source), str(source)]):
                for output_format in ("text", "json", "csv"):
                    with self.subTest(arguments=arguments, output_format=output_format):
                        reader, writer = os.pipe()
                        # Close before spawning so the child can never race the reader.
                        os.close(reader)
                        try:
                            completed = subprocess.run(
                                [
                                    sys.executable,
                                    "-B",
                                    "-m",
                                    "search_algos",
                                    *arguments,
                                    "--format",
                                    output_format,
                                ],
                                cwd=ROOT,
                                stdout=writer,
                                stderr=subprocess.PIPE,
                                text=True,
                                timeout=30,
                            )
                        finally:
                            os.close(writer)
                        self.assertEqual(completed.returncode, 1, completed.stderr)
                        self.assertIn("error:", completed.stderr)
                        self.assertNotIn("Exception ignored", completed.stderr)
                        self.assertNotIn("Traceback", completed.stderr)

    def test_custom_stdout_errors_are_not_masked_by_descriptor_cleanup(self):
        saved = benchmark_report(report_row("binary", 2))
        for operation in ("write", "flush"):
            output, errors = io.StringIO(), io.StringIO()
            with (
                self.subTest(operation=operation),
                patch("search_algos.cli.run_benchmarks", return_value=saved),
                patch("sys.stdout", output),
                patch("sys.stderr", errors),
                patch.object(output, operation, side_effect=OSError("original output failure")),
            ):
                self.assertEqual(main(["--format", "json"]), 1)
                self.assertIn("error: original output failure", errors.getvalue())
                self.assertNotIn("Traceback", errors.getvalue())

    def test_all_algorithms_include_radix_and_parallel_in_a_real_cli_run(self):
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
                names = [row["algorithm"] for row in rows]
                self.assertEqual(len(names), len(set(names)))
                for row in rows:
                    self.assertEqual(row["algorithm_label"], ALGORITHM_LABELS[row["algorithm"]])
                for algorithm in (*PREPARED_ALGORITHMS, "certified_radix", *ADDITIONAL_ALGORITHMS):
                    self.assertEqual(names.count(algorithm), 1)
                radix = next(row for row in rows if row["algorithm"] == "radix")
                self.assertEqual(radix["result_kind"], "first_index")
                self.assertEqual(radix["timing_scope"], "lookup_batch")
                parallel = next(row for row in rows if row["algorithm"] == "parallel")
                self.assertEqual(parallel["effective_workers"], 2)
                self.assertEqual(parallel["timing_scope"], "batch_with_process_startup")
                self.assertEqual(parallel["hits"], 2)

    def test_additional_entries_export_correct_result_kinds_to_json_and_csv(self):
        for output_format in ("json", "csv"):
            with self.subTest(output_format=output_format):
                completed = self.run_cli(
                    "--size",
                    "0",
                    "40",
                    "--datasets",
                    "duplicates",
                    "--algorithms",
                    *ADDITIONAL_ALGORITHMS,
                    "--queries",
                    "4",
                    "--warmups",
                    "0",
                    "--repetitions",
                    "1",
                    "--time-budget",
                    "0",
                    "--format",
                    output_format,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                rows = (
                    json.loads(completed.stdout)["results"]
                    if output_format == "json"
                    else list(csv.DictReader(io.StringIO(completed.stdout)))
                )
                self.assertEqual(len(rows), 16)
                for row in rows:
                    self.assertEqual(row["status"], "complete")
                    self.assertEqual(row["algorithm_label"], ALGORITHM_LABELS[row["algorithm"]])
                    kind = "membership" if row["algorithm"] == "binary_slicing" else "first_index"
                    self.assertEqual(row["result_kind"], kind)
                    samples = row["setup_samples_ns"]
                    if output_format == "csv":
                        samples = json.loads(samples)
                    self.assertEqual(len(samples), 1)
                    if row["algorithm"] != "sentinel":
                        self.assertEqual(samples, [0])

    def test_default_run_adds_all_eight_and_keeps_linear_available_explicitly(self):
        expected = {
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
            *PREPARED_ALGORITHMS,
            *ADDITIONAL_ALGORITHMS,
        }
        for script in (False, True):
            with self.subTest(script=script):
                completed = self.run_cli(
                    "--size",
                    "0",
                    "10",
                    "--datasets",
                    "uniform",
                    "--queries",
                    "2",
                    "--repetitions",
                    "1",
                    "--warmups",
                    "0",
                    "--format",
                    "json",
                    script=script,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                rows = json.loads(completed.stdout)["results"]
                self.assertEqual(len(rows), 46)
                self.assertTrue(all(row["status"] == "complete" for row in rows))
                for size in (0, 10):
                    algorithms = [row["algorithm"] for row in rows if row["size"] == size]
                    self.assertEqual(set(algorithms), expected)
                    self.assertEqual(len(algorithms), len(expected))

    def test_radix_exports_and_saved_comparison_preserve_setup_and_result_contract(self):
        arguments = [
            "--size",
            "128",
            "--datasets",
            "duplicates",
            "--algorithms",
            "bisect",
            "radix",
            "dict",
            "--queries",
            "6",
            "--repetitions",
            "2",
            "--warmups",
            "1",
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "radix.json"
            for output_format in ("text", "json", "csv"):
                with self.subTest(output_format=output_format):
                    completed = self.run_cli(*arguments, "--format", output_format)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    if output_format == "text":
                        self.assertIn("radix-directory construction", completed.stdout)
                        self.assertEqual(completed.stdout.count("Result: first_index"), 1)
                        self.assertIn("Timing scope: lookup_batch", completed.stdout)
                        for algorithm in ("bisect", "radix", "dict"):
                            self.assertTrue(
                                any(
                                    line.startswith(format_algorithm(algorithm) + " ")
                                    for line in completed.stdout.splitlines()
                                )
                            )
                        continue
                    if output_format == "json":
                        source.write_text(completed.stdout, encoding="utf-8")
                        rows = json.loads(completed.stdout)["results"]
                        radix = next(row for row in rows if row["algorithm"] == "radix")
                        setup_samples = radix["setup_samples_ns"]
                        lookup_samples = radix["lookup_samples_ns"]
                    else:
                        rows = list(csv.DictReader(io.StringIO(completed.stdout)))
                        radix = next(row for row in rows if row["algorithm"] == "radix")
                        setup_samples = json.loads(radix["setup_samples_ns"])
                        lookup_samples = json.loads(radix["lookup_samples_ns"])
                    self.assertEqual(
                        {row["algorithm"] for row in rows}, {"bisect", "radix", "dict"}
                    )
                    self.assertEqual(len({row["workload_id"] for row in rows}), 1)
                    self.assertEqual(radix["result_kind"], "first_index")
                    self.assertEqual(radix["timing_scope"], "lookup_batch")
                    self.assertEqual(radix["status"], "complete")
                    self.assertEqual(len(setup_samples), 2)
                    self.assertEqual(len(lookup_samples), 2)
                    self.assertTrue(
                        all(type(sample) is int and sample >= 0 for sample in setup_samples)
                    )
            for metric in ("total", "lookup"):
                compared = self.run_cli(
                    "compare", str(source), str(source), "--metric", metric, "--format", "json"
                )
                self.assertEqual(compared.returncode, 0, compared.stderr)
                rows = json.loads(compared.stdout)["comparisons"]
                self.assertEqual({row["algorithm"] for row in rows}, {"bisect", "radix", "dict"})
                self.assertTrue(
                    all(row["status"] == "compared" and row["speedup"] == 1 for row in rows)
                )

    def test_help_and_text_report(self):
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--repetitions", help_result.stdout)
        self.assertIn(
            "defaults include radix and prepared alternatives", " ".join(help_result.stdout.split())
        )
        self.assertIn("certified_radix is opt-in", " ".join(help_result.stdout.split()))
        completed = self.run_cli(*SMALL_RUN)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("lookup IQR", completed.stdout)
        self.assertIn("set", completed.stdout)
        self.assertNotIn("found at positions", completed.stdout)

    def test_prepared_alternatives_export_and_compare_without_replacing_baselines(self):
        arguments = [
            "--size",
            "128",
            "--datasets",
            "gapped",
            "--algorithms",
            "bisect",
            "dict",
            *PREPARED_ALGORITHMS,
            "certified_radix",
            "--queries",
            "6",
            "--repetitions",
            "2",
            "--warmups",
            "1",
        ]
        expected_algorithms = {"bisect", "dict", *PREPARED_ALGORITHMS, "certified_radix"}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "prepared.json"
            for output_format in ("text", "json", "csv"):
                with self.subTest(output_format=output_format):
                    completed = self.run_cli(*arguments, "--format", output_format)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    if output_format == "text":
                        self.assertIn("other index preparation", completed.stdout)
                        self.assertEqual(completed.stdout.count("Result: first_index"), 1)
                        for algorithm in expected_algorithms:
                            self.assertTrue(
                                any(
                                    line.startswith(format_algorithm(algorithm) + " ")
                                    for line in completed.stdout.splitlines()
                                )
                            )
                        continue
                    if output_format == "json":
                        source.write_text(completed.stdout, encoding="utf-8")
                        rows = json.loads(completed.stdout)["results"]
                    else:
                        rows = list(csv.DictReader(io.StringIO(completed.stdout)))
                    self.assertEqual({row["algorithm"] for row in rows}, expected_algorithms)
                    self.assertEqual(len(rows), len(expected_algorithms))
                    self.assertEqual(len({row["workload_id"] for row in rows}), 1)
                    for row in rows:
                        self.assertEqual(row["result_kind"], "first_index")
                        self.assertEqual(row["timing_scope"], "lookup_batch")
                        self.assertEqual(row["status"], "complete")
                        for field in ("setup_samples_ns", "lookup_samples_ns"):
                            samples = (
                                json.loads(row[field]) if output_format == "csv" else row[field]
                            )
                            self.assertEqual(len(samples), 2)
                            self.assertTrue(
                                all(type(sample) is int and sample >= 0 for sample in samples)
                            )
            for metric in ("total", "lookup"):
                compared = self.run_cli(
                    "compare", str(source), str(source), "--metric", metric, "--format", "json"
                )
                self.assertEqual(compared.returncode, 0, compared.stderr)
                rows = json.loads(compared.stdout)["comparisons"]
                self.assertEqual({row["algorithm"] for row in rows}, expected_algorithms)
                self.assertTrue(
                    all(row["status"] == "compared" and row["speedup"] == 1 for row in rows)
                )

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
        second = lines.index(headers[1])
        third = lines.index(headers[2])
        for start, end, ratios in (
            (first, second, ("1.00x", "4.00x")),
            (second, third, ("1.00x", "n/a")),
            (third, len(lines), ("1.00x", "1.00x")),
        ):
            ranked = [
                line
                for line in lines[start:end]
                if line.startswith(
                    (format_algorithm("bisect") + " ", format_algorithm("binary") + " ")
                )
            ]
            self.assertEqual(len(ranked), 2)
            self.assertTrue(
                ranked[0].startswith(format_algorithm("bisect") + " ") or start == third
            )
            for line, ratio in zip(ranked, ratios):
                self.assertTrue(line.endswith(ratio), line)

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
                line = next(
                    line for line in lines if line.startswith(format_algorithm(algorithm) + " ")
                )
                self.assertTrue(line.endswith(expected_ratio), line)
        self.assertEqual(rendered.count("uniform, size 10:"), 4)
        self.assertIn("Result: first_index (first matching index or None)", rendered)
        self.assertIn("Result: membership (whether the target is present (True/False))", rendered)
        self.assertIn("Timing scope: lookup_batch (sequential lookup", rendered)
        self.assertIn("cold pool; includes process startup and shutdown", rendered)
        self.assertIn("reused pool; excludes separately reported startup and shutdown", rendered)
        self.assertIn(
            format_algorithm("parallel_warm") + " lifecycle (excluded from batch totals)", rendered
        )

    def test_text_names_include_compatible_identifiers_and_align_columns(self):
        # These legacy-shaped rows deliberately have no algorithm_label field.
        report = benchmark_report(
            report_row("radix", 100),
            report_row("recursive", 200),
            report_row("double_linear_recursive", 300),
        )
        rendered = render_report(report, "text")
        labels = (
            "Radix Binary Search (RBS) [radix]",
            "Recursive binary search [recursive]",
            "Recursive double-ended linear search [double_linear_recursive]",
        )
        positions = []
        for label in labels:
            self.assertIn(label, rendered)
            line = next(line for line in rendered.splitlines() if line.startswith(label))
            positions.append(line.index("complete"))
        self.assertEqual(len(set(positions)), 1)

    def test_colors_preserve_rankings_and_narrow_layout_preserves_every_metric(self):
        report = benchmark_report(
            report_row("radix", 100),
            report_row("double_linear_recursive", 300),
            report_row("bisect", 1, status="incomplete"),
            report_row("linear", None, status="skipped"),
        )
        for width in (None, 40, 80, 120, 200):
            with self.subTest(width=width):
                plain = render_report(report, "text", width=width)
                styled = render_report(report, "text", color=True, width=width)
                self.assertIn("\x1b[", styled)
                self.assertEqual(re.sub(r"\x1b\[[0-9;]*m", "", styled), plain)
                self.assertEqual(plain.count("[radix] *"), 1)
                self.assertNotIn("[bisect] *", plain)
                self.assertIn("1.00x", plain)
                self.assertIn("3.00x", plain)
                for field in (
                    "setup med",
                    "lookup med",
                    "lookup IQR",
                    "total med",
                    "ns/query",
                    "vs fastest",
                ):
                    self.assertIn(field, plain)
                for algorithm in ("radix", "double_linear_recursive", "bisect", "linear"):
                    self.assertIn(f"[{algorithm}]", plain)
                if width:
                    self.assertLessEqual(max(map(len, plain.splitlines())), width)

    def test_color_flags_apply_to_text_but_never_to_machine_formats(self):
        for mode in ("auto", "always", "never"):
            for output_format in ("text", "json", "csv"):
                with self.subTest(mode=mode, output_format=output_format):
                    completed = self.run_cli(*SMALL_RUN, "--color", mode, "--format", output_format)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(completed.stderr, "")
                    self.assertEqual(
                        "\x1b[" in completed.stdout, mode == "always" and output_format == "text"
                    )
                    if output_format == "json":
                        self.assertEqual(len(json.loads(completed.stdout)["results"]), 6)
                    elif output_format == "csv":
                        self.assertEqual(
                            len(list(csv.DictReader(io.StringIO(completed.stdout)))), 6
                        )

    def test_footer_wraps_in_very_narrow_terminals(self):
        report = benchmark_report(report_row("radix", 100))
        for width in (12, 18, 20, 22):
            for color in (False, True):
                with self.subTest(width=width, color=color):
                    text = render_report(report, "text", width=width, color=color)
                    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
                    self.assertLessEqual(max(map(len, plain.splitlines())), width)
                    self.assertIn("READING THE RESULTS", " ".join(plain.split()))

    def test_terminal_auto_layout_and_file_output_color_policy(self):
        report = benchmark_report(report_row("radix", 100))
        terminal = io.StringIO()
        with (
            patch("search_algos.cli.run_benchmarks", return_value=report),
            patch("sys.stdout", terminal),
            patch.object(terminal, "isatty", return_value=True),
            patch("search_algos.console._enable_windows_ansi", return_value=True),
            patch(
                "search_algos.cli.shutil.get_terminal_size", return_value=os.terminal_size((80, 24))
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(main([]), 0)
            styled = terminal.getvalue()
            self.assertIn("\x1b[", styled)
            self.assertIn("status:", styled)
            self.assertLessEqual(
                max(map(len, re.sub(r"\x1b\[[0-9;]*m", "", styled).splitlines())), 80
            )
            terminal.seek(0)
            terminal.truncate()
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "report.txt"
                for mode in ("auto", "always", "never"):
                    self.assertEqual(main(["--output", str(destination), "--color", mode]), 0)
                    self.assertEqual(
                        "\x1b[" in destination.read_text(encoding="utf-8"), mode == "always"
                    )
                self.assertEqual(terminal.getvalue(), "")

    def test_text_rankings_keep_distinct_workload_ids_separate(self):
        report = benchmark_report(
            report_row("binary", 400, workload_id="first-workload"),
            report_row("bisect", 1, workload_id="second-workload"),
        )
        rendered = render_report(report, "text")
        self.assertIn("Workload: first-workload", rendered)
        self.assertIn("Workload: second-workload", rendered)
        for line in rendered.splitlines():
            if line.startswith(
                (format_algorithm("binary") + " ", format_algorithm("bisect") + " ")
            ):
                self.assertTrue(line.endswith("1.00x"), line)

    def test_text_rankings_exclude_incomplete_and_skipped_rows(self):
        report = benchmark_report(
            report_row("binary", 400),
            report_row("bisect", 1, status="incomplete"),
            report_row("linear", None, status="skipped"),
            report_row("set", 1, status="incomplete", result_kind="membership"),
        )
        lines = render_report(report, "text").splitlines()
        complete = next(line for line in lines if line.startswith(format_algorithm("binary") + " "))
        self.assertTrue(complete.endswith("1.00x"), complete)
        for algorithm in ("bisect", "linear", "set"):
            with self.subTest(algorithm=algorithm):
                line = next(
                    line for line in lines if line.startswith(format_algorithm(algorithm) + " ")
                )
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
                    "compare",
                    str(source),
                    str(source),
                    "--format",
                    output_format,
                    "--color",
                    "always",
                    script=True,
                )
                self.assertEqual(output.returncode, 0, output.stderr)
                self.assertIn("binary", output.stdout)
                self.assertEqual("\x1b[" in output.stdout, output_format == "text")

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

    def test_compare_rejects_excessive_json_nesting_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "deep.json"
            source.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
            completed = self.run_cli("compare", str(source), str(source))
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "")
            self.assertIn("error:", completed.stderr)
            self.assertIn("deep.json", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)

    def test_compare_reports_encoding_recursion_without_traceback(self):
        report = benchmark_report(report_row("bisect", 1))
        report["schema_version"] = 1
        report["results"][0].update(setup_samples_ns=[0], lookup_samples_ns=[1])
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("search_algos.comparison.load_report", return_value=report),
            patch("search_algos.comparison.json.dumps", side_effect=RecursionError),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            status = main(["compare", "before.json", "after.json", "--format", "json"])
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
