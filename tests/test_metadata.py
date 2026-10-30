"""Metadata must describe the executing package, not its caller's checkout."""

import importlib.metadata
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from search_algos import metadata


class MetadataTests(unittest.TestCase):
    def test_inline_toml_comments_preserve_source_provenance(self):
        cases = (
            '[project] # package metadata\nname = "search-algos"\nversion = "0.3.0"\n',
            '[project]\nname = "search-algos" # package name\nversion = "0.3.0"\n',
            '[project]\nname = "search-algos"\nversion = "0.3.0" # source version\n',
            "[project] # package metadata\nname = 'search-algos' # name\nversion = '0.3.0' # version\n",
            "  [project] # package metadata\n  name = 'search-algos'\n\tversion = '0.3.0' # version\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            revision = "a" * 40
            for document in cases:
                with self.subTest(document=document):
                    (root / "pyproject.toml").write_text(document, encoding="utf-8")
                    with (
                        patch.object(
                            metadata, "__file__", str(root / "search_algos" / "metadata.py")
                        ),
                        patch.object(metadata, "_command", side_effect=[str(root), revision, ""]),
                        patch.object(metadata, "_cpu_model", return_value=None),
                        patch("importlib.metadata.version", return_value="0.2.0") as installed,
                    ):
                        report = metadata.collect_metadata()
                        self.assertEqual(report["package_version"], "0.3.0")
                        self.assertEqual(report["git_commit"], revision)
                        self.assertIs(report["git_dirty"], False)
                        installed.assert_not_called()

    def test_source_version_does_not_come_from_another_table_or_comment(self):
        documents = (
            "[project] # package metadata\nname = 'search-algos'\n  [tool.example]\nversion = '99.0'\n",
            "[project] # package metadata\nname = 'unrelated' # search-algos\nversion = '99.0'\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for document in documents:
                with self.subTest(document=document):
                    (root / "pyproject.toml").write_text(document, encoding="utf-8")
                    self.assertIsNone(metadata._project_version(root))

    def test_source_version_takes_precedence_over_stale_installed_distribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "search-algos"\nversion = "0.3.0"\n', encoding="utf-8"
            )
            with patch("importlib.metadata.version", return_value="0.2.0"):
                self.assertEqual(metadata._package_version(root), "0.3.0")

    def test_installed_package_does_not_use_an_unrelated_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "environment" / "site-packages" / "search_algos"
            package.mkdir(parents=True)
            (root / ".git").mkdir()
            (root / "pyproject.toml").write_text(
                '[project]\nname = "search-algos"\nversion = "99.0"\n', encoding="utf-8"
            )
            with patch.object(metadata, "__file__", str(package / "metadata.py")):
                self.assertIsNone(metadata._source_root())
            with patch.object(metadata, "_command", side_effect=AssertionError("unexpected git")):
                self.assertEqual(metadata._git_metadata(None), (None, None))
                self.assertEqual(metadata._git_metadata(package.parent), (None, None))

    def test_source_detection_requires_this_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "unrelated"\nversion = "1.0"\n', encoding="utf-8"
            )
            with patch.object(metadata, "__file__", str(root / "search_algos" / "metadata.py")):
                self.assertIsNone(metadata._source_root())

    def test_git_metadata_records_revision_and_dirty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
            revision = "a" * 40
            for status, expected_dirty in (("", False), (" M README.md", True), (None, None)):
                with self.subTest(status=status):
                    with patch.object(
                        metadata, "_command", side_effect=[str(root), revision, status]
                    ) as command:
                        self.assertEqual(metadata._git_metadata(root), (revision, expected_dirty))
                        self.assertTrue(
                            all(call.args[1] == root for call in command.call_args_list)
                        )

    def test_git_unavailable_or_wrong_repository_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            for outputs in ([None], [str(root.parent)], [str(root), "invalid"]):
                with self.subTest(outputs=outputs):
                    with patch.object(metadata, "_command", side_effect=outputs):
                        self.assertEqual(metadata._git_metadata(root), (None, None))

    def test_commands_handle_missing_tools_failure_and_timeouts(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("git", 2)):
            with patch.object(metadata.subprocess, "run", side_effect=error):
                self.assertIsNone(metadata._command(["git", "--version"]))
        with patch.object(
            metadata.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "error")
        ):
            self.assertIsNone(metadata._command(["git", "--version"]))

    def test_linux_cpu_model_and_portable_fallback(self):
        with patch.object(metadata.sys, "platform", "linux"):
            with patch.object(
                Path, "read_text", return_value="processor : 0\nmodel name : Example CPU\n"
            ):
                self.assertEqual(metadata._cpu_model(), "Example CPU")
            with patch.object(Path, "read_text", side_effect=OSError):
                with patch.object(metadata.platform, "processor", return_value=""):
                    self.assertIsNone(metadata._cpu_model())

    def test_macos_cpu_model(self):
        with patch.object(metadata.sys, "platform", "darwin"):
            with patch.object(metadata, "_command", return_value="Example Silicon"):
                self.assertEqual(metadata._cpu_model(), "Example Silicon")

    def test_missing_distribution_and_cpu_are_reported_as_null(self):
        with patch.object(metadata, "_source_root", return_value=None):
            with patch.object(metadata, "_cpu_model", return_value=None):
                with patch(
                    "importlib.metadata.version",
                    side_effect=importlib.metadata.PackageNotFoundError,
                ):
                    report = metadata.collect_metadata()
        self.assertIsNone(report["package_version"])
        self.assertIsNone(report["cpu_model"])
        self.assertIsNone(report["git_commit"])
        self.assertIsNone(report["git_dirty"])
        self.assertEqual(report["timer"], "perf_counter_ns")
        self.assertIn("python_version", report)
        self.assertIn("created_at_utc", report)


if __name__ == "__main__":
    unittest.main()
