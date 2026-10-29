"""Exercise real command entry points and parse their exported reports."""

import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SMALL_RUN = [
    "--size", "0", "1", "10", "--datasets", "duplicates",
    "--queries", "4", "--repetitions", "2", "--warmups", "0",
    "--algorithms", "binary", "set",
]


class CliTests(unittest.TestCase):
    def run_cli(self, *args, module=False):
        command = [sys.executable, "-B"]
        command += ["-m", "lib"] if module else ["search_algos.py"]
        return subprocess.run(command + list(args), cwd=ROOT, capture_output=True, text=True, timeout=30)

    def test_json_stdout_is_a_clean_report(self):
        completed = self.run_cli(*SMALL_RUN, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        report = json.loads(completed.stdout)
        self.assertEqual(len(report["results"]), 6)
        self.assertEqual(report["config"]["sizes"], [0, 1, 10])
        self.assertEqual(report["results"][0]["hits"], 0)

    def test_module_entry_point_csv_includes_metadata_and_samples(self):
        completed = self.run_cli(*SMALL_RUN, "--format", "csv", module=True)
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
            ["--size", "-1"], ["--size", "abc"], ["--queries", "0"],
            ["--workers", "0"], ["--warmups", "-1"], ["--repetitions", "0"],
            ["--hit-rate", "nan"], ["--hit-rate", "1.1"],
            ["--algorithms", "all", "binary"], ["--size", "1", "1"],
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
        completed = self.run_cli(
            "--size", "10", "--datasets", "gapped", "--algorithms", "all",
            "--workers", "2", "--queries", "4", "--repetitions", "1",
            "--warmups", "0", "--format", "json",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = json.loads(completed.stdout)["results"]
        self.assertEqual(len(rows), 7)
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


if __name__ == "__main__":
    unittest.main()
