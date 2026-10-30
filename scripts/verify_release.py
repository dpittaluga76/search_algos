"""Build an sdist and its wheel, then test outside this checkout.

Run with ``python scripts/verify_release.py``. Only pip and the standard library
are needed; pip installs the build frontend into a temporary environment, and
the frontend installs the build dependencies declared in pyproject.toml.
Source staging, build output, the virtual environment, and reports are temporary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import venv
from pathlib import Path


def _environment() -> dict[str, str]:
    """Keep checkout imports and inherited coverage hooks out of the smoke run."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "COVERAGE_"))
    }
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _run(arguments: list[str], directory: Path, environment: dict[str, str]) -> None:
    subprocess.run(arguments, cwd=directory, env=environment, check=True, timeout=180)


def _source_archive_files(archive: Path, required: set[str]) -> dict[str, bytes]:
    """Read required regular files without extracting archive paths to disk."""
    prefix = archive.name.removesuffix(".tar.gz")
    files = {}
    with tarfile.open(archive, "r:gz") as source:
        for relative in sorted(required):
            name = f"{prefix}/{relative}"
            try:
                member = source.getmember(name)
            except KeyError as error:
                raise RuntimeError(f"Source distribution is missing {relative}") from error
            if not member.isfile():
                raise RuntimeError(f"Source distribution must contain a regular file: {relative}")
            contents = source.extractfile(member)
            if contents is None:
                raise RuntimeError(f"Cannot read source distribution file: {relative}")
            with contents:
                files[relative] = contents.read()
    return files


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    environment = _environment()
    with tempfile.TemporaryDirectory(prefix="search-algos-release-") as directory:
        temporary = Path(directory).resolve()
        if temporary.is_relative_to(root):
            raise RuntimeError("The system temporary directory must be outside the checkout")
        source = temporary / "source"
        shutil.copytree(
            root,
            source,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "venv",
                "build",
                "dist",
                "*.egg-info",
                "__pycache__",
                ".mypy_cache",
                ".ruff_cache",
                ".pytest_cache",
                ".coverage*",
                "coverage.xml",
                "htmlcov",
                "benchmark-smoke.*",
            ),
        )
        work = temporary / "work"
        work.mkdir()
        artifacts = temporary / "artifacts"
        builder = temporary / "builder"
        venv.EnvBuilder(with_pip=True).create(builder)
        builder_python = builder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _run(
            [str(builder_python), "-I", "-m", "pip", "install", "build>=1.2,<2"],
            work,
            environment,
        )
        print("Building the source distribution and a wheel from that archive...", flush=True)
        _run(
            [
                str(builder_python),
                "-I",
                "-m",
                "build",
                "--outdir",
                str(artifacts),
                str(source),
            ],
            work,
            environment,
        )
        # build's default operation builds the wheel from the freshly built
        # sdist. Explicit --sdist --wheel flags would instead build both from
        # the source tree, potentially hiding missing source-archive files.
        built = list(artifacts.glob("*.whl"))
        if len(built) != 1:
            raise RuntimeError(f"Expected exactly one project wheel, found {len(built)}")
        sdists = list(artifacts.glob("*.tar.gz"))
        if len(sdists) != 1:
            raise RuntimeError(f"Expected exactly one source distribution, found {len(sdists)}")
        required = {
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "search_algos.py",
            "search_algos/py.typed",
            "docs/algorithm-names.md",
            *(path.relative_to(source).as_posix() for path in (source / "scripts").rglob("*.py")),
            *(path.relative_to(source).as_posix() for path in (source / "tests").rglob("*.py")),
        }
        archive_files = _source_archive_files(sdists[0], required)
        isolated = temporary / "venv"
        venv.EnvBuilder(with_pip=True).create(isolated)
        python = isolated / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _run(
            [str(python), "-I", "-m", "pip", "install", "--no-deps", "--no-index", str(built[0])],
            work,
            environment,
        )
        smoke = work / "installed_smoke.py"
        smoke.write_bytes(archive_files["tests/installed_smoke.py"])
        (work / "search_algos.py").write_bytes(archive_files["search_algos.py"])
        print("Checking the installed wheel from outside the checkout...", flush=True)
        _run([str(python), "-I", str(smoke), "-v"], work, environment)
    print("Source-distribution and installed-wheel verification passed; temporary files removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
