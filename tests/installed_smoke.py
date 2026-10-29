"""Installed-wheel checks, run only by scripts/verify_release.py in a clean venv.

This file is deliberately outside unittest's test*.py discovery: it must be
copied outside the checkout and executed against the newly built distribution.
"""

import csv
import io
import json
import os
import subprocess
import sys
import unittest
from importlib.metadata import distribution
from pathlib import Path

import search_algos
from search_algos.comparison import load_report
from search_algos.metadata import collect_metadata

PREPARED_ALGORITHMS = ("neighbor_prepared", "dict_reverse", "guarded_prepared", "adaptive_index")


class InstalledWheelTests(unittest.TestCase):
    def run_command(self, *arguments, module=False):
        if module:
            command = [sys.executable, "-I", "-m", "search_algos"]
        else:
            executable = "search-algos.exe" if os.name == "nt" else "search-algos"
            command = [str(Path(sys.executable).with_name(executable))]
        completed = subprocess.run(
            command + list(arguments), capture_output=True, text=True, timeout=60
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stderr, "")
        return completed.stdout

    def test_import_provenance_typing_marker_and_metadata(self):
        prefix = Path(sys.prefix).resolve()
        package = Path(search_algos.__file__).resolve()
        self.assertNotEqual(sys.prefix, sys.base_prefix)
        self.assertTrue(package.is_relative_to(prefix), package)
        self.assertFalse(package.is_relative_to(Path.cwd()))
        installed = distribution("search-algos")
        self.assertIn("search_algos/py.typed", [str(path) for path in installed.files or []])
        marker = Path(installed.locate_file("search_algos/py.typed")).resolve()
        self.assertTrue(marker.is_relative_to(prefix))
        self.assertTrue(marker.is_file())
        metadata = collect_metadata()
        self.assertEqual(metadata["package_version"], installed.version)
        self.assertIsNone(metadata["git_commit"])
        self.assertIsNone(metadata["git_dirty"])

    def test_installed_search_api(self):
        for name in search_algos.__all__:
            self.assertTrue(callable(getattr(search_algos, name)), name)
        for name in (
            "linear_search",
            "binary_search",
            "binary_search_std_lib",
            "binary_search_by_recursion",
            "interpolation_search",
            "interpolation_search_hybrid",
            "exponential_search",
            "jump_search",
            "find_by_dict",
        ):
            with self.subTest(algorithm=name):
                search = getattr(search_algos, name)
                self.assertEqual(search([1, 3, 3, 8], 3), 1)
                self.assertIsNone(search([1, 3, 3, 8], 9))
        self.assertIs(search_algos.find_by_sets([1, 3, 3, 8], 3), True)
        self.assertEqual(search_algos.build_first_index([3, 1, 3]), {3: 0, 1: 1})
        radix = search_algos.build_radix_index([-3, -3, 2, 2, 8])
        self.assertEqual(radix(-3), 0)
        self.assertEqual(radix(2), 2)
        self.assertIsNone(radix(4))
        for factory_name in ("build_neighbor_index", "build_guarded_index", "build_adaptive_index"):
            with self.subTest(factory=factory_name):
                lookup = getattr(search_algos, factory_name)([-3, -3, 2, 2, 8])
                self.assertEqual(lookup(-3), 0)
                self.assertEqual(lookup(2), 2)
                self.assertIsNone(lookup(4))
        reversed_index = search_algos.build_first_index_reversed(iter([3, 1, 3]))
        self.assertEqual(reversed_index, {3: 0, 1: 1})
        self.assertIsNone(reversed_index.get(9))

    def test_console_json_export_and_module_comparison(self):
        report_path = Path.cwd() / "installed report.json"
        stdout = self.run_command(
            "--size",
            "0",
            "10",
            "--datasets",
            "duplicates",
            "--algorithms",
            "binary",
            "set",
            "dict",
            "radix",
            *PREPARED_ALGORITHMS,
            "--queries",
            "4",
            "--repetitions",
            "2",
            "--warmups",
            "0",
            "--time-budget",
            "0",
            "--format",
            "json",
            "--output",
            str(report_path),
        )
        self.assertEqual(stdout, "")
        report = load_report(report_path)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(len(report["results"]), 16)
        self.assertTrue(all(row["status"] == "complete" for row in report["results"]))
        radix_rows = [row for row in report["results"] if row["algorithm"] == "radix"]
        self.assertEqual(len(radix_rows), 2)
        for row in radix_rows:
            self.assertEqual(row["result_kind"], "first_index")
            self.assertEqual(row["timing_scope"], "lookup_batch")
            self.assertEqual(len(row["setup_samples_ns"]), 2)
        for algorithm in PREPARED_ALGORITHMS:
            prepared_rows = [row for row in report["results"] if row["algorithm"] == algorithm]
            self.assertEqual(len(prepared_rows), 2)
            for row in prepared_rows:
                self.assertEqual(row["result_kind"], "first_index")
                self.assertEqual(row["timing_scope"], "lookup_batch")
                self.assertEqual(len(row["setup_samples_ns"]), 2)
        compared = json.loads(
            self.run_command(
                "compare", str(report_path), str(report_path), "--format", "json", module=True
            )
        )
        self.assertEqual(len(compared["comparisons"]), 16)
        for row in compared["comparisons"]:
            self.assertEqual(row["status"], "compared")
            self.assertEqual(row["speedup"], 1.0)

    def test_module_csv_with_cold_and_reused_spawn_workers(self):
        output = self.run_command(
            "--size",
            "10",
            "--datasets",
            "gapped",
            "--algorithms",
            "binary",
            "radix",
            "parallel",
            "parallel_warm",
            *PREPARED_ALGORITHMS,
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
            "csv",
            module=True,
        )
        rows = list(csv.DictReader(io.StringIO(output)))
        self.assertEqual(len(rows), 8)
        by_algorithm = {row["algorithm"]: row for row in rows}
        self.assertEqual(
            set(by_algorithm),
            {"binary", "radix", "parallel", "parallel_warm", *PREPARED_ALGORITHMS},
        )
        self.assertEqual(by_algorithm["radix"]["result_kind"], "first_index")
        self.assertEqual(by_algorithm["radix"]["timing_scope"], "lookup_batch")
        self.assertEqual(len(json.loads(by_algorithm["radix"]["setup_samples_ns"])), 1)
        for algorithm in PREPARED_ALGORITHMS:
            row = by_algorithm[algorithm]
            self.assertEqual(row["result_kind"], "first_index")
            self.assertEqual(row["timing_scope"], "lookup_batch")
            self.assertEqual(len(json.loads(row["setup_samples_ns"])), 1)
        for algorithm, scope in (
            ("parallel", "batch_with_process_startup"),
            ("parallel_warm", "batch_reused_pool"),
        ):
            row = by_algorithm[algorithm]
            self.assertEqual(row["timing_scope"], scope)
            self.assertEqual(row["effective_workers"], "2")
            self.assertEqual(row["status"], "complete")
            self.assertEqual(row["hits"], "2")
            self.assertEqual(len(json.loads(row["lookup_samples_ns"])), 1)


if __name__ == "__main__":
    unittest.main()
