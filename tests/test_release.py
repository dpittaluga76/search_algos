"""Source-archive checks used before installing a release wheel."""

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.verify_release import _source_archive_files


class SourceDistributionTests(unittest.TestCase):
    def make_archive(self, directory, files):
        archive = Path(directory) / "search_algos-0.3.0.tar.gz"
        with tarfile.open(archive, "w:gz") as destination:
            for path, content in files.items():
                member = tarfile.TarInfo(f"search_algos-0.3.0/{path}")
                if content is None:
                    member.type = tarfile.DIRTYPE
                    destination.addfile(member)
                else:
                    member.size = len(content)
                    destination.addfile(member, io.BytesIO(content))
        return archive

    def test_reads_shipped_tests_and_compatibility_script(self):
        required = {
            "search_algos.py": b"compatibility script",
            "tests/installed_smoke.py": b"tests",
        }
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory, required)
            self.assertEqual(_source_archive_files(archive, set(required)), required)

    def test_rejects_missing_compatibility_script(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory, {"tests/test_cli.py": b"tests"})
            with self.assertRaisesRegex(RuntimeError, "missing search_algos.py"):
                _source_archive_files(archive, {"search_algos.py", "tests/test_cli.py"})

    def test_a_directory_cannot_satisfy_a_required_file(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory, {"search_algos.py": None})
            with self.assertRaisesRegex(RuntimeError, "regular file: search_algos.py"):
                _source_archive_files(archive, {"search_algos.py"})


if __name__ == "__main__":
    unittest.main()
