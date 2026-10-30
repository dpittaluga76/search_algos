"""Study artifacts retain fingerprints of every measured implementation."""

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import benchmark_certified, benchmark_landmark, confirm_landmark

ROOT = Path(__file__).resolve().parents[1]
STUDIES = (benchmark_landmark, benchmark_certified, confirm_landmark)


class StudySourceTests(unittest.TestCase):
    def make_checkout(self, root):
        for directory in ("search_algos", "scripts"):
            for source in (ROOT / directory).rglob("*.py"):
                target = root / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        (root / "benchmarks" / "landmark_sprint").mkdir(parents=True)

    def run_study(self, module, root):
        script = root / "scripts" / Path(module.__file__).name
        if module is benchmark_certified:
            output = root / "certified.json"
        elif module is benchmark_landmark:
            output = root / "benchmarks" / "landmark_sprint" / "results.json"
        else:
            output = root / "benchmarks" / "landmark_sprint" / "confirmation.json"
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(module, "__file__", str(script)))
            stack.enter_context(patch.object(module, "collect_metadata", return_value={}))
            stack.enter_context(
                patch.object(module, "run_benchmarks", return_value={"results": []})
            )
            if module is not confirm_landmark:
                stack.enter_context(
                    patch.object(
                        module, "make_custom_workload", return_value=SimpleNamespace(values=())
                    )
                )
                stack.enter_context(patch.object(module, "measure_custom", return_value=[]))
            if module is benchmark_landmark:
                stack.enter_context(patch.object(module, "render_report", return_value="report\n"))
            elif module is benchmark_certified:
                stack.enter_context(patch.object(module, "measure_allocations", return_value=[]))
                stack.enter_context(
                    patch.object(
                        sys,
                        "argv",
                        [
                            str(script),
                            "--output",
                            str(output),
                            "--size",
                            "100",
                            "--queries",
                            "2",
                            "--seeds",
                            "0",
                        ],
                    )
                )
            module.main()
        return json.loads(output.read_text(encoding="utf-8"))["source_sha256"]

    def test_generated_studies_fingerprint_all_package_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_checkout(root)
            expected = {
                path.relative_to(root).as_posix() for path in (root / "search_algos").rglob("*.py")
            }
            for module in STUDIES:
                with self.subTest(study=module.__name__):
                    hashes = self.run_study(module, root)
                    self.assertIn("search_algos/alternatives.py", hashes)
                    self.assertIn("search_algos/landmark.py", hashes)
                    self.assertIn("scripts/study_sources.py", hashes)
                    self.assertIn(f"scripts/{Path(module.__file__).name}", hashes)
                    if module is benchmark_landmark:
                        self.assertIn("scripts/benchmark_certified.py", hashes)
                    self.assertTrue(expected <= hashes.keys(), expected - hashes.keys())
                    self.assertEqual(list(hashes), sorted(hashes))
                    for path, digest in hashes.items():
                        self.assertEqual(
                            digest, hashlib.sha256((root / path).read_bytes()).hexdigest()
                        )

    def test_modified_and_new_implementation_sources_change_generated_fingerprints(self):
        for module in STUDIES:
            with self.subTest(study=module.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_checkout(root)
                before = self.run_study(module, root)
                implementation = root / "search_algos" / "alternatives.py"
                implementation.write_bytes(
                    implementation.read_bytes() + b"\nchanged_source = True\n"
                )
                added = root / "search_algos" / "future_family" / "search.py"
                added.parent.mkdir()
                added.write_text("def lookup(values, target):\n    return None\n", encoding="utf-8")
                after = self.run_study(module, root)
                self.assertNotEqual(
                    before.get("search_algos/alternatives.py"),
                    after.get("search_algos/alternatives.py"),
                )
                self.assertNotIn("search_algos/future_family/search.py", before)
                self.assertEqual(
                    after["search_algos/future_family/search.py"],
                    hashlib.sha256(added.read_bytes()).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
